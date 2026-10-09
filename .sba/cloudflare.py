"""Explicit, locked-source Cloudflare deployment; no cloud writes by default."""

from __future__ import annotations

import argparse
from contextlib import nullcontext, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tomllib
from urllib.error import HTTPError
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stack import (ROOT, Stack, StackError, contained, encode_json, git_bytes, local_path,
                   read_json, run, scratch, sha, write_json)

KEY_NAMES = {"sessionSecret", "jwtPublicSecret", "jwtPrivateSecret"}
EXCLUDED = {"node_modules", ".git", ".next", ".wrangler", "__pycache__"}


def deployment_tools_hash():
    folder = Path(__file__).parent
    return sha(b'\0'.join((folder / name).read_bytes() for name in ('cloudflare.py', 'lifecycle.py', 'springbok.py', 'admin_bootstrap.py', 'admin_bootstrap.mjs')))


def config(path: Path, component: str) -> dict:
    result = read_json(path)
    if not re.fullmatch(r"[0-9a-f]{32}", result["accountId"]):
        raise StackError("Set a real Cloudflare accountId (32 lowercase hex characters)")
    if not re.fullmatch(r"[0-9a-f]{32}", result["kvId"]):
        raise StackError("Set a real kvId")
    if not re.fullmatch(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", result["database"]["id"]):
        raise StackError("Set a real D1 database UUID")
    for name in (result["database"]["name"], result["server"]["name"], result["admin"]["name"]):
        if not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", name):
            raise StackError("Resource names must use lowercase letters, digits and hyphens")
    hosts = []
    for role in ("server", "admin"):
        parsed = urlparse(result[role]["url"])
        if (parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port
                or not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", parsed.hostname)):
            raise StackError("Use two HTTPS origins without ports, paths or credentials")
        if parsed.hostname.endswith('.workers.dev') and not re.fullmatch(
                re.escape(result[role]['name']) + r'\.[a-z0-9-]+\.workers\.dev', parsed.hostname):
            raise StackError('workers.dev origin must match its Worker name')
        hosts.append(parsed.hostname)
        result[role]["url"] = f"https://{parsed.hostname}"
    if len(set(hosts)) != 2 or result["server"]["name"] == result["admin"]["name"]:
        raise StackError("Auth and admin must have distinct Worker names and custom domains")
    if component in ("admin", "all"):
        if not result["admin"].get("spaClientId") or not result["admin"].get("s2sClientId"):
            raise StackError("Bootstrap the server's Admin Panel clients before building admin/all")
    for key, value in result.get("vars", {}).items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or re.search(r"(?:_SECRET|_API_KEY|_TOKEN|_PASSWORD|CONNECTION_STRING)$", key):
            raise StackError(f"Secret or invalid variable must not appear in public configuration: {key}")
        if not isinstance(value, (str, bool, int, float, list)):
            raise StackError(f"Unsupported public variable value: {key}")
    for name in result["server"].get("secretNames", []):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name) or name.startswith("CLOUDFLARE_"):
            raise StackError("Invalid application secret name")
    if "secret" in result.get("admin", {}) or "secrets" in result:
        raise StackError("Do not store secret values in deployment configuration")
    if result.get('vars', {}).get('EMAIL_PROVIDER_NAME') == 'cloudflare':
        sender = result['vars'].get('CLOUDFLARE_SENDER_ADDRESS')
        if not isinstance(sender, str) or not re.fullmatch(r'[a-zA-Z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}', sender):
            raise StackError('Cloudflare Email requires an explicit sender address')
    return result


def components(component: str) -> list[str]:
    return ["server", "admin-panel"] if component == "all" else ["admin-panel" if component == "admin" else "server"]


def server_config(source: Path, settings: dict) -> dict:
    upstream = tomllib.loads((source / "server/wrangler.toml").read_text(encoding="utf-8"))
    upstream.update({"name": settings["server"]["name"], "main": "src/index.tsx",
                     "account_id": settings["accountId"], "keep_vars": False, "workers_dev": False,
                     "preview_urls": False,
                     "routes": [{"pattern": urlparse(settings["server"]["url"]).hostname, "custom_domain": True}]})
    upstream["kv_namespaces"] = [{"binding": "KV", "id": settings["kvId"]}]
    upstream["d1_databases"] = [{"binding": "DB", "database_name": settings["database"]["name"],
                                 "database_id": settings["database"]["id"], "migrations_dir": "./migrations/sqlite"}]
    upstream["vars"].update(settings.get("vars", {}))
    upstream["vars"].update({"AUTH_SERVER_URL": settings["server"]["url"], "ENVIRONMENT": "prod"})
    if settings.get('vars', {}).get('EMAIL_PROVIDER_NAME') == 'cloudflare':
        upstream['send_email'] = [{'name': 'CLOUDFLARE_EMAIL',
                                   'allowed_sender_addresses': [settings['vars']['CLOUDFLARE_SENDER_ADDRESS']]}]
    return runtime_config(upstream, settings, 'server')


def admin_config(source: Path, settings: dict) -> dict:
    upstream = tomllib.loads((source / "admin-panel/wrangler.toml").read_text(encoding="utf-8"))
    upstream.update({"name": settings["admin"]["name"], "account_id": settings["accountId"],
                     "workers_dev": False, "preview_urls": False,
                     "routes": [{"pattern": urlparse(settings["admin"]["url"]).hostname, "custom_domain": True}],
                     "vars": admin_env(settings)})
    return runtime_config(upstream, settings, 'admin')


def runtime_config(value: dict, settings: dict, role: str) -> dict:
    if urlparse(settings[role]['url']).hostname.endswith('.workers.dev'):
        value.update(workers_dev=True, routes=[])
    value['compatibility_flags'] = sorted(set(value.get('compatibility_flags', [])) | {'global_fetch_strictly_public'})
    if settings.get('_sbaPreview'):
        # 预升级配置不继承任何邮件、定时、队列或外部服务通道。
        for key in ('send_email', 'triggers', 'queues', 'services', 'unsafe', 'durable_objects'):
            value.pop(key, None)
        original = value['main']
        value['main'] = 'naccount-preview-entry.mjs'
        value['_previewOriginalMain'] = original
    return value


def admin_env(settings: dict) -> dict[str, str]:
    return {"NEXT_PUBLIC_CLIENT_URI": settings["admin"]["url"],
            "NEXT_PUBLIC_SERVER_URI": settings["server"]["url"],
            "NEXT_PUBLIC_CLIENT_ID": settings["admin"].get("spaClientId", ""),
            "NEXT_PUBLIC_SUPPORTED_LOCALES": ",".join(settings.get("vars", {}).get("SUPPORTED_LOCALES", ["en", "fr"])),
            "SERVER_CLIENT_ID": settings["admin"].get("s2sClientId", "")}


def prepare(root: Path, settings: dict, component: str) -> Path:
    stack = Stack(root)
    lock = stack.verify()
    if stack.pending_path().exists():
        raise StackError("Finalize the pending upstream update before deployment")
    release = scratch("naccount-release-")
    source = release / "source"
    source.mkdir()
    payload = git_bytes(stack.source, "archive", "--format=tar", lock["head"])
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        for member in archive.getmembers():
            contained(source, member.name.rstrip("/"))
            if not member.isfile() and not member.isdir():
                raise StackError("Deployment archives must not contain symlinks or special files")
        archive.extractall(source, filter="data")
    generated = {"server": server_config(source, settings), "admin-panel": admin_config(source, settings)}
    for role, value in generated.items():
        original_main = value.pop('_previewOriginalMain', None)
        if original_main:
            from lifecycle import preview_entry, preview_guard
            (source / role / 'naccount-preview-entry.mjs').write_text(
                preview_entry(original_main, settings, role), encoding='utf-8')
            (source / role / 'naccount-preview-guard.mjs').write_text(
                preview_guard(settings, role), encoding='utf-8')
        # Only the isolated build copy is changed; original checkout remains untouched.
        original = source / role / "wrangler.toml"
        original.rename(original.with_name("wrangler.upstream.toml"))
        write_json(source / role / "wrangler.json", value)
    write_json(release / "deployment.json", settings)
    write_json(release / "release.json", {"schemaVersion": 1, "state": "prepared", "component": component,
               "sourceHead": lock["head"], "sourceTree": lock["tree"],
               "catalogGeneration": read_json(stack.catalog / "current.json")["generation"],
               "deploymentScriptSha256": deployment_tools_hash(),
               "stackScriptSha256": sha((ROOT / "scripts/stack.py").read_bytes())})
    return release


def app_command(source: Path, role: str, command: list[str], settings: dict,
                *, secret_input: bytes | None = None, cloud: bool = False) -> bytes:
    env = os.environ.copy()
    env.pop('ADMIN_BOOTSTRAP_PASSWORD', None)
    env.update({"CI": "true", "WRANGLER_SEND_METRICS": "false", "NEXT_TELEMETRY_DISABLED": "1",
                "CLOUDFLARE_ACCOUNT_ID": settings["accountId"]})
    # Keep dependency caches and logs with isolated artifacts, not the user's global cache.
    env.update({"npm_config_cache": os.environ.get("npm_config_cache", str(source.parent / "npm-cache")),
                "npm_config_maxsockets": os.environ.get("npm_config_maxsockets", "5"),
                "npm_config_fetch_retries": "1", "npm_config_fetch_timeout": "60000",
                "WRANGLER_LOG_PATH": str(source.parent / "wrangler-logs")})
    if not cloud:
        # Local builds must not inherit cloud/application credentials.
        for key in list(env):
            if key.startswith("CLOUDFLARE_") or key in settings["server"].get("secretNames", []) or key == "SERVER_CLIENT_SECRET":
                env.pop(key, None)
    if role == "admin-panel":
        env.update(admin_env(settings))
    print(f"[{role}] {' '.join(command)}", flush=True)
    result = run(command, source / role, env=env, data=secret_input, check=secret_input is None)
    if secret_input is not None and result.returncode:
        raise StackError("Secret upload failed; output suppressed to avoid exposing secret values")
    if result.stdout and secret_input is None:
        print(result.stdout.decode("utf-8", errors="replace"), flush=True)
    if result.stderr and secret_input is None:
        print(result.stderr.decode("utf-8", errors="replace"), file=sys.stderr, flush=True)
    return result.stdout


def wrangler(source: Path, role: str, args: list[str], settings: dict, **kwargs) -> bytes:
    cli = source / role / "node_modules/wrangler/bin/wrangler.js"
    if not cli.is_file():
        raise StackError("Wrangler is missing; build this release first")
    return app_command(source, role, ["node", str(cli), *args, "--config", "wrangler.json"], settings, **kwargs)


def inventory(release: Path) -> dict[str, str]:
    files = {}
    for path in (release / "source").rglob("*"):
        relative = path.relative_to(release)
        if any(part in EXCLUDED for part in relative.parts) or not path.is_file():
            continue
        if path.is_symlink():
            raise StackError("Symlink found in release payload")
        files[relative.as_posix()] = sha(path.read_bytes())
    files["deployment.json"] = sha((release / "deployment.json").read_bytes())
    return dict(sorted(files.items()))


def build(root: Path, settings: dict, component: str) -> Path:
    release = prepare(root, settings, component)
    print(f"Release directory (preserved on failure): {release}", flush=True)
    source = release / "source"
    for role in components(component):
        app_command(source, role, ["npm", "ci", "--no-audit", "--no-fund"], settings)
        app_command(source, role, ["npm", "run", "type:check"], settings)
        app_command(source, role, ["npm", "run", "cf:build" if role == "admin-panel" else "build"], settings)
        wrangler(source, role, ["deploy", "--dry-run", "--outdir", str(release / "dry-run" / role)], settings)
    receipt = read_json(release / "release.json")
    if receipt["deploymentScriptSha256"] != deployment_tools_hash() or receipt["stackScriptSha256"] != sha((ROOT / "scripts/stack.py").read_bytes()):
        raise StackError("Deployment tools changed during build; rebuild before publishing")
    receipt.update({"state": "built", "files": inventory(release)})
    write_json(release / "release.json", receipt)
    return release


def checked_release(release: Path) -> tuple[dict, dict]:
    release = local_path(release)
    receipt = read_json(release / "release.json")
    if receipt.get("state") != "built":
        raise StackError("Release did not pass install, typecheck, build and Wrangler dry-run")
    if receipt["deploymentScriptSha256"] != deployment_tools_hash() or receipt["stackScriptSha256"] != sha((ROOT / "scripts/stack.py").read_bytes()):
        raise StackError("Deployment tools changed since build; rebuild before publishing")
    if receipt["files"] != inventory(release):
        raise StackError("Release payload or configuration changed since build")
    settings = config(release / "deployment.json", receipt["component"])
    if not os.environ.get("CLOUDFLARE_API_TOKEN"):
        raise StackError("Set CLOUDFLARE_API_TOKEN explicitly; no implicit account/OAuth session is used")
    return settings, receipt


def cloud_api(settings: dict, suffix: str, *, method: str = "GET", payload=None):
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        raise StackError("CLOUDFLARE_API_TOKEN is required")
    url = "https://api.cloudflare.com/client/v4/accounts/" + settings["accountId"] + suffix
    request = Request(url, method=method, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                      data=None if payload is None else encode_json(payload))
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise StackError(f"Cloudflare API failed with HTTP {exc.code}; response body suppressed") from exc
    if not result.get("success"):
        raise StackError("Cloudflare API operation failed; response body suppressed")
    return result["result"]


def existing_keys(settings: dict) -> set[str]:
    found = set()
    for name in KEY_NAMES:
        results = cloud_api(settings, f"/storage/kv/namespaces/{settings['kvId']}/keys?prefix={quote(name)}")
        if any(item["name"] == name for item in results):
            found.add(name)
    return found


def bootstrap_keys(release: Path) -> dict:
    settings, receipt = checked_release(release)
    if receipt["component"] == "admin":
        raise StackError("Use a built server release for initial KV keys")
    found = existing_keys(settings)
    if found == KEY_NAMES:
        print("All signing/session keys already exist; no rotation or writes performed.")
        return {"state": "already-initialized", "release": str(release)}
    if found:
        raise StackError("Partial key initialization found; preserve it and repair explicitly, never rotate automatically")
    # In-memory generation and API upload: no PEM or private key enters the repository/build directory.
    code = """const c=require('node:crypto');const k=c.generateKeyPairSync('rsa',{modulusLength:2048,
publicKeyEncoding:{type:'spki',format:'pem'},privateKeyEncoding:{type:'pkcs8',format:'pem'}});
process.stdout.write(JSON.stringify({sessionSecret:c.randomBytes(32).toString('hex'),
jwtPublicSecret:k.publicKey,jwtPrivateSecret:k.privateKey}));"""
    keys = json.loads(run(["node", "-e", code], release).stdout)
    cloud_api(settings, f"/storage/kv/namespaces/{settings['kvId']}/bulk", method="PUT",
              payload=[{"key": key, "value": value} for key, value in keys.items()])
    print("Initial keys uploaded. Never run the upstream rotating generator during routine deployment.")
    return {"state": "initialized", "release": str(release)}


def publish(release: Path, *, migrate: bool) -> dict:
    settings, receipt = checked_release(release)
    roles = components(receipt["component"])
    secrets = {}
    for role in roles:
        names = settings["server"].get("secretNames", []) if role == "server" else ["SERVER_CLIENT_SECRET"]
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise StackError("Missing runtime secrets: " + ", ".join(missing))
        secrets[role] = {name: os.environ[name] for name in names}
    if "server" in roles and existing_keys(settings) != KEY_NAMES:
        raise StackError("Signing/session keys missing; explicitly bootstrap keys before publishing")
    source = release / "source"
    journal = scratch("naccount-publish-")
    steps = []
    write_json(journal / "status.json", {"release": str(release), "state": "started", "steps": steps})
    try:
        if "server" in roles and migrate:
            wrangler(source, "server", ["d1", "export", "DB", "--remote", "--output", str(journal / "before-migration.sql")], settings, cloud=True)
            steps.append("database-backup")
            wrangler(source, "server", ["d1", "migrations", "apply", "DB", "--remote"], settings, cloud=True)
            steps.append("database-migrations")
        for role in roles:
            # Upload application secrets only when explicitly listed. JWT/session keys are not touched.
            if secrets[role]:
                wrangler(source, role, ["secret", "bulk"], settings, secret_input=encode_json(secrets[role]), cloud=True)
                steps.append(role + "-secrets")
            wrangler(source, role, ["deploy"], settings, cloud=True)
            steps.append(role + "-deployed")
    except Exception:
        write_json(journal / "status.json", {"release": str(release), "state": "failed", "steps": steps})
        print(f"Deployment stopped; no automatic database rollback. Receipt: {journal}", file=sys.stderr)
        raise
    write_json(journal / "status.json", {"release": str(release), "state": "deployed-unverified", "steps": steps})
    print(f"Cloudflare deployment commands completed; business verification remains required. Receipt: {journal}")
    return {"state": "deployed-unverified", "release": str(release), "journal": str(journal),
            "steps": steps, "businessVerified": False}


def execute(args: argparse.Namespace) -> dict:
    if args.action in ("publish", "bootstrap-keys"):
        if not args.execute:
            raise StackError("Cloud writes are disabled without --execute")
        if args.action == "publish":
            return publish(local_path(args.release), migrate=args.migrate)
        return bootstrap_keys(local_path(args.release))
    settings = config(args.config.resolve(), args.component)
    if args.action == "plan":
        lock = Stack(args.root).verify(catalog_only=True)
        result = {"state": "planned", "cloudWrites": False, "sourceHead": lock["head"], "component": args.component,
                  "accountId": settings["accountId"], "database": settings["database"], "kvId": settings["kvId"],
                  "authUrl": settings["server"]["url"], "adminUrl": settings["admin"]["url"],
                  "steps": ["verify pinned source", "export isolated build copy", "npm ci", "typecheck",
                            "build", "wrangler deploy --dry-run", "explicit publish of this release"],
                  "automaticUpstreamUpdate": False, "automaticKeyRotation": False}
        if not args.json_output:
            print(json.dumps(result, indent=2))
        return result
    action = build if args.action == "build" else prepare
    release = action(args.root, settings, args.component)
    receipt = read_json(release / "release.json")
    print(f"{args.action}: OK\nRelease: {release}")
    return {"state": receipt["state"], "release": str(release), "receipt": str(release / "release.json"),
            "sourceHead": receipt["sourceHead"], "component": args.component, "cloudWrites": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("plan", "prepare", "build"):
        command = sub.add_parser(name)
        command.add_argument("--json", dest="json_output", action="store_true", help="JSON result on stdout; logs on stderr")
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--component", choices=("server", "admin", "all"), default="server")
    for name in ("publish", "bootstrap-keys"):
        command = sub.add_parser(name)
        command.add_argument("--json", dest="json_output", action="store_true", help="JSON result on stdout; logs on stderr")
        command.add_argument("--release", type=Path, required=True)
        command.add_argument("--execute", action="store_true")
        if name == "publish":
            command.add_argument("--migrate", action="store_true")
    args = parser.parse_args()
    try:
        with redirect_stdout(sys.stderr) if args.json_output else nullcontext():
            result = execute(args)
        if args.json_output:
            print(json.dumps({"schemaVersion": 1, "ok": True, "action": args.action, "result": result}, ensure_ascii=False))
        return 0
    except (StackError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if args.json_output:
            print(json.dumps({"schemaVersion": 1, "ok": False, "action": args.action,
                              "error": {"message": str(exc)}}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
