"""NAccount's MiDot-style source checkout and generated patch catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMP = Path("C:/Users/Public/nas_home/AI/GameEditor/linshi")


class StackError(RuntimeError):
    pass


def local_path(path: Path) -> Path:
    path = path.resolve()
    if str(path).startswith("\\\\"):
        raise StackError("Use the existing mapped drive or equivalent local path instead of UNC.")
    return path


def scratch(prefix: str) -> Path:
    parent = Path(os.environ.get("NACCOUNT_TEMP", str(DEFAULT_TEMP) if os.name == "nt" else tempfile.gettempdir()))
    parent = local_path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))


def encode_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value
    except (OSError, ValueError) as exc:
        raise StackError(f"Cannot read JSON: {path}: {exc}") from exc


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_json(value))


def atomic_json(path: Path, value: object) -> None:
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_bytes(encode_json(value))
    os.replace(temp, path)


def run(args: list[str], cwd: Path, *, check: bool = True, data: bytes | None = None,
        env: dict | None = None) -> subprocess.CompletedProcess:
    cwd = local_path(cwd)
    command = [str(arg) for arg in args]
    if shutil.which("rtk"):
        command = ["rtk", "proxy", *command]
    else:
        # Windows CreateProcess 不会为裸 npm 按 PATHEXT 解析 npm.cmd；使用 PATH 的精确结果。
        path = env.get("PATH", env.get("Path")) if env is not None else None
        command[0] = shutil.which(command[0], path=path) or command[0]
    result = subprocess.run(command, cwd=cwd, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, check=False)
    if check and result.returncode:
        detail = (result.stderr + result.stdout).decode("utf-8", errors="replace").strip()
        raise StackError(f"Command failed ({result.returncode}): {' '.join(args)}\n{detail}")
    return result


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", "-c", "core.quotepath=false", "-C", str(repo), *args], repo,
               check=check).stdout.decode("utf-8", errors="strict").strip()


def git_bytes(repo: Path, *args: str) -> bytes:
    return run(["git", "-C", str(repo), *args], repo).stdout


def independent(repo: Path) -> None:
    if not repo.is_dir() or not (repo / ".git").is_dir():
        raise StackError(f"Expected an independent checkout with its own .git directory: {repo}")
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo.resolve():
        raise StackError(f"Refusing parent-repository fallback: {repo}")


def git_dir(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--absolute-git-dir"))


def clean(repo: Path) -> None:
    independent(repo)
    directory = git_dir(repo)
    for name in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if (directory / name).exists():
            raise StackError(f"Unfinished Git operation: {name}; resolve explicitly.")
    if git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise StackError(f"Dirty checkout; preserve and commit your changes before this operation: {repo}")


def oid(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def tree(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", f"{ref}^{{tree}}")


def contained(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise StackError("Invalid catalog path")
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts or ":" in relative:
        raise StackError(f"Unsafe catalog path: {relative}")
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise StackError(f"Catalog path escapes its root: {relative}")
    return path


class Stack:
    def __init__(self, root: Path):
        self.root = local_path(root)
        self.source = self.root / "melody-auth"
        self.catalog = self.root / "customizations"
        self.config_path = self.catalog / "stack.json"
        self.config = read_json(self.config_path)
        if self.config.get("schemaVersion") != 1:
            raise StackError("Unsupported stack schema")
        for key in ("upstreamBranch", "integrationBranch"):
            name = self.config[key]
            if not isinstance(name, str) or name.startswith("-"):
                raise StackError(f"Invalid branch: {key}")
            run(["git", "check-ref-format", "refs/heads/" + name], self.root)
        if self.config["upstreamBranch"] == self.config["integrationBranch"]:
            raise StackError("Upstream and integration branches must differ")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", self.config["commitTopicTrailer"]):
            raise StackError("Invalid topic trailer")
        topics = self.config.get("topics", [])
        ids = [item["id"] for item in topics]
        if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", x) for x in ids):
            raise StackError("Invalid or duplicate topic ID")

    @property
    def base_branch(self) -> str:
        return self.config["upstreamBranch"]

    @property
    def branch(self) -> str:
        return self.config["integrationBranch"]

    def assert_source(self, source: Path | None = None) -> Path:
        source = source or self.source
        clean(source)
        if git(source, "remote", "get-url", "origin") != self.config["upstreamUrl"]:
            raise StackError("Source origin differs from the configured upstream")
        if git(source, "symbolic-ref", "--short", "HEAD") != self.branch:
            raise StackError(f"Expected source branch {self.branch}")
        return source

    def load(self) -> tuple[Path, dict]:
        pointer = read_json(self.catalog / "current.json")
        generation = pointer.get("generation", "")
        if not re.fullmatch(r"[0-9a-f]{64}", generation):
            raise StackError("Invalid generation ID")
        folder = contained(self.catalog, "generated/" + generation)
        lock_path = contained(folder, "stack.lock.json")
        lock_bytes = lock_path.read_bytes()
        if sha(lock_bytes) != generation:
            raise StackError("Lock hash mismatch")
        lock = read_json(lock_path)
        if lock.get("schemaVersion") != 1 or lock["configSha256"] != sha(self.config_path.read_bytes()):
            raise StackError("Stack configuration differs from exported catalog; re-export reviewed commits")
        for key in ("base", "head", "tree"):
            if not re.fullmatch(r"[0-9a-f]{40}", lock.get(key, "")):
                raise StackError(f"Invalid locked {key}")
        expected = {"stack.lock.json", *lock["files"]}
        actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
        if actual != expected:
            raise StackError("Catalog has missing or unexpected files")
        for name, digest in lock["files"].items():
            if sha(contained(folder, name).read_bytes()) != digest:
                raise StackError(f"Catalog hash mismatch: {name}")
        entries = lock["patches"]
        series = (folder / "series.txt").read_text(encoding="utf-8").splitlines()
        if series != [entry["file"] for entry in entries] or len(series) != len(set(series)):
            raise StackError("Patch series differs from the lock")
        if any(not name.startswith("patches/") or name not in lock["files"] for name in series):
            raise StackError("Invalid patch entry")
        if bool(entries) != ("personal-history.bundle" in lock["files"]):
            raise StackError("Exact-history bundle is required for a non-empty stack")
        return folder, lock

    def verify(self, *, catalog_only: bool = False, source: Path | None = None) -> dict:
        folder, lock = self.load()
        if catalog_only:
            return lock
        source = self.assert_source(source)
        if oid(source, "HEAD") != lock["head"] or oid(source, self.base_branch) != lock["base"]:
            raise StackError("Source HEAD or pristine base differs from the exported catalog")
        if tree(source, "HEAD") != lock["tree"]:
            raise StackError("Source tree differs from lock")
        commits = git(source, "rev-list", "--reverse", f"{lock['base']}..{lock['head']}").splitlines()
        if commits != [entry["commit"] for entry in lock["patches"]]:
            raise StackError("Exact source commit sequence differs from lock")
        if commits:
            bundle = folder / "personal-history.bundle"
            git(source, "bundle", "verify", str(bundle))
            if git(source, "bundle", "list-heads", str(bundle)) != f"{lock['head']} refs/heads/{self.branch}":
                raise StackError("Bundle branch differs from lock")
        return lock

    def export(self, *, during_update: bool = False) -> dict:
        source = self.assert_source()
        if self.pending_path().exists() and not during_update:
            raise StackError("An upstream update is pending; use finalize, not export")
        base, head = oid(source, self.base_branch), oid(source, "HEAD")
        git(source, "merge-base", "--is-ancestor", base, head)
        commits = git(source, "rev-list", "--reverse", f"{base}..{head}").splitlines()
        topics = {item["id"] for item in self.config["topics"]}
        pattern = re.compile(r"^" + re.escape(self.config["commitTopicTrailer"]) + r":\s*([a-z0-9][a-z0-9.-]*)\s*$", re.M)
        output = scratch("naccount-export-")
        entries, files = [], {}
        previous = base
        for index, commit in enumerate(commits, 1):
            if git(source, "show", "-s", "--format=%P", commit).split() != [previous]:
                raise StackError("Only a linear, non-merge personal commit stack is supported")
            message = git(source, "show", "-s", "--format=%B", commit)
            matches = pattern.findall(message)
            if len(matches) != 1 or matches[0] not in topics:
                raise StackError(f"Commit {commit} needs exactly one declared {self.config['commitTopicTrailer']} trailer")
            topic = matches[0]
            if not (self.catalog / "topics" / topic / "README.md").is_file():
                raise StackError(f"Missing topic documentation: topics/{topic}/README.md")
            name = f"patches/{index:04d}-{topic}.patch"
            payload = git_bytes(source, "format-patch", "-1", "--stdout", "--full-index", "--binary", "--no-signature", commit)
            if not payload:
                raise StackError(f"Empty commit cannot be exported as a patch: {commit}")
            path = contained(output, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            files[name] = sha(payload)
            entries.append({"commit": commit, "topic": topic, "file": name})
            previous = commit
        series = "".join(entry["file"] + "\n" for entry in entries).encode("utf-8")
        (output / "series.txt").write_bytes(series)
        files["series.txt"] = sha(series)
        if entries:
            bundle = output / "personal-history.bundle"
            git(source, "bundle", "create", str(bundle), f"{base}..refs/heads/{self.branch}")
            files[bundle.name] = sha(bundle.read_bytes())
        lock = {"schemaVersion": 1, "configSha256": sha(self.config_path.read_bytes()),
                "base": base, "head": head, "tree": tree(source, head), "patches": entries, "files": files}
        payload = encode_json(lock)
        (output / "stack.lock.json").write_bytes(payload)
        generation = sha(payload)
        destination = contained(self.catalog, "generated/" + generation)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Generations are immutable. A failed copy never becomes the active pointer.
        if destination.exists():
            expected = {p.relative_to(output) for p in output.rglob("*") if p.is_file()}
            actual = {p.relative_to(destination) for p in destination.rglob("*") if p.is_file()}
            if expected != actual or any((output / p).read_bytes() != (destination / p).read_bytes() for p in expected):
                raise StackError(f"Existing generation differs; preserve for inspection: {destination}")
        else:
            shutil.copytree(output, destination)
        atomic_json(self.catalog / "current.json", {"generation": generation})
        self.verify()
        return lock

    def new_checkout(self, destination: Path, lock: dict) -> None:
        destination = local_path(destination)
        if destination.exists():
            raise StackError(f"Will not overwrite an existing destination: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-b", "naccount-bootstrap", str(destination)], destination.parent)
        git(destination, "config", "core.autocrlf", "false")
        git(destination, "config", "core.longpaths", "true")
        git(destination, "remote", "add", "origin", self.config["upstreamUrl"])
        git(destination, "config", "remote.origin.pushurl", "disabled://upstream-read-only")
        git(destination, "-c", "http.version=HTTP/1.1", "fetch", "--depth=1", "--no-tags", "origin", lock["base"])
        git(destination, "update-ref", f"refs/remotes/origin/{self.base_branch}", lock["base"])
        git(destination, "checkout", "-b", self.base_branch, lock["base"])

    def initialize(self) -> dict:
        folder, lock = self.load()
        if self.source.exists():
            return self.verify()
        staging = self.source.with_name("melody-auth.initialize-" + uuid.uuid4().hex)
        try:
            self.new_checkout(staging, lock)
            if lock["patches"]:
                bundle = folder / "personal-history.bundle"
                git(staging, "bundle", "verify", str(bundle))
                git(staging, "fetch", "--no-tags", str(bundle), f"refs/heads/{self.branch}:refs/heads/{self.branch}")
                git(staging, "checkout", self.branch)
            else:
                git(staging, "checkout", "-b", self.branch)
            self.verify(source=staging)
            if self.source.exists():
                raise StackError("Destination appeared during initialization; refusing overwrite")
            staging.rename(self.source)
            return lock
        except Exception:
            print(f"Incomplete checkout preserved: {staging}", file=sys.stderr)
            raise

    def apply(self, destination: Path) -> dict:
        folder, lock = self.load()
        destination = local_path(destination)
        self.new_checkout(destination, lock)
        git(destination, "checkout", "-b", self.branch)
        # git am necessarily creates new committer identities; only tree equality is promised.
        for entry in lock["patches"]:
            git(destination, "-c", "user.name=NAccount Patch Replay", "-c", "user.email=patch-replay@localhost",
                "am", "--3way", "--keep-cr", str(contained(folder, entry["file"])))
        if tree(destination, "HEAD") != lock["tree"]:
            raise StackError("Replayed source tree differs from the locked source tree")
        return lock

    def pending_path(self) -> Path:
        return git_dir(self.source) / "naccount-update.json"

    def update(self) -> dict:
        lock = self.verify()
        pending = self.pending_path()
        if pending.exists():
            raise StackError("Pending update exists; resolve it and use finalize")
        if git(self.source, "for-each-ref", "--format=%(upstream)", "refs/heads/" + self.branch):
            raise StackError("Refusing to rebase a tracking branch; this workflow is for a local private patch branch")
        backup = "refs/naccount/backups/" + uuid.uuid4().hex
        git(self.source, "update-ref", backup, lock["head"])
        git(self.source, "-c", "http.version=HTTP/1.1", "fetch", "--no-tags", "origin", self.base_branch)
        target = oid(self.source, "FETCH_HEAD")
        git(self.source, "merge-base", "--is-ancestor", lock["base"], target)
        if target == lock["base"]:
            return lock
        state = {"schemaVersion": 1, "root": str(self.root), "configSha256": lock["configSha256"],
                 "oldBase": lock["base"], "oldHead": lock["head"], "target": target, "backup": backup,
                 "generation": read_json(self.catalog / "current.json")["generation"]}
        write_json(pending, state)
        try:
            git(self.source, "-c", "rebase.autoStash=false", "rebase", "--onto", target, lock["base"], self.branch)
        except StackError as exc:
            raise StackError(f"{exc}\nUpdate stopped; resolve and run git rebase --continue, then finalize. "
                             f"No reset, clean or skip was run. Safety ref: {backup}") from exc
        return self.finalize()

    def finalize(self) -> dict:
        self.assert_source()
        pending = self.pending_path()
        state = read_json(pending)
        if state["root"] != str(self.root) or state["configSha256"] != sha(self.config_path.read_bytes()):
            raise StackError("Pending update belongs to a different root/configuration")
        if oid(self.source, state["backup"]) != state["oldHead"]:
            raise StackError("Update safety ref changed")
        mirror = oid(self.source, self.base_branch)
        if mirror not in (state["oldBase"], state["target"]):
            raise StackError("Pristine mirror changed outside this update")
        folder, lock = self.load()
        original = lock["base"] == state["oldBase"] and lock["head"] == state["oldHead"]
        completed = lock["base"] == state["target"] and lock["head"] == oid(self.source, "HEAD")
        if not original and not completed:
            raise StackError("Catalog changed outside this update")
        git(self.source, "merge-base", "--is-ancestor", state["target"], "HEAD")
        worktrees = git(self.source, "worktree", "list", "--porcelain")
        if f"branch refs/heads/{self.base_branch}" in worktrees.splitlines():
            raise StackError("Pristine branch is checked out in another worktree")
        git(self.source, "update-ref", "refs/heads/" + self.base_branch, state["target"], mirror)
        lock = self.export(during_update=True)
        # Keep the receipt instead of deleting operation state outside the temporary area.
        pending.rename(pending.with_name("naccount-update-completed-" + uuid.uuid4().hex + ".json"))
        return lock

    def abandon(self) -> dict:
        """Archive an aborted update only after exact old source/catalog verification."""
        lock = self.verify()
        pending = self.pending_path()
        state = read_json(pending)
        if lock["head"] != state["oldHead"] or lock["base"] != state["oldBase"]:
            raise StackError("Explicitly abort the rebase and restore the old catalog before abandon")
        if state["root"] != str(self.root) or oid(self.source, state["backup"]) != state["oldHead"]:
            raise StackError("Pending state or backup differs")
        pending.rename(pending.with_name("naccount-update-aborted-" + uuid.uuid4().hex + ".json"))
        return lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "export", "update", "finalize", "abandon"):
        commands.add_parser(name)
    verify = commands.add_parser("verify")
    verify.add_argument("--catalog-only", action="store_true")
    apply = commands.add_parser("apply")
    apply.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        stack = Stack(args.root)
        if args.command == "verify":
            lock = stack.verify(catalog_only=args.catalog_only)
        elif args.command == "apply":
            lock = stack.apply(args.destination)
        else:
            method = "initialize" if args.command == "init" else args.command
            lock = getattr(stack, method)()
        print(f"{args.command}: OK; patches={len(lock['patches'])}; base={lock['base']}; head={lock['head']}")
        return 0
    except (StackError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
