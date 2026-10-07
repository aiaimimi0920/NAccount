"""Real Git regression fixtures; no production repository commits or resets."""

import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stack import Stack, StackError, encode_json, git, read_json, run, scratch, tree, write_json
import stack


class CommandTests(unittest.TestCase):
    def test_without_rtk_resolves_batch_entry_from_command_environment(self):
        completed = subprocess.CompletedProcess([], 0, b"ok", b"")
        with patch.object(stack.shutil, "which", side_effect=[None, "C:/node/npm.cmd"]) as which, \
                patch.object(stack.subprocess, "run", return_value=completed) as child:
            self.assertIs(run(["npm", "run", "type:check"], Path.cwd(), env={"PATH": "C:/node"}), completed)
        self.assertEqual(which.call_args_list[1].kwargs, {"path": "C:/node"})
        self.assertEqual(child.call_args.args[0], ["C:/node/npm.cmd", "run", "type:check"])
        self.assertNotIn("shell", child.call_args.kwargs)

    def test_rtk_remains_optional_and_preserves_proxy_arguments(self):
        completed = subprocess.CompletedProcess([], 0, b"", b"")
        with patch.object(stack.shutil, "which", return_value="C:/tools/rtk.exe"), \
                patch.object(stack.subprocess, "run", return_value=completed) as child:
            run(["npm", "ci", "--no-audit"], Path.cwd())
        self.assertEqual(child.call_args.args[0], ["rtk", "proxy", "npm", "ci", "--no-audit"])

    @unittest.skipUnless(os.name == "nt", "Windows batch entry regression")
    def test_real_windows_npm_version_without_rtk(self):
        original = shutil.which
        if not original("npm"):
            self.skipTest("Node/npm not installed")
        with patch.object(stack.shutil, "which", side_effect=lambda name, **kwargs: None if name == "rtk" else original(name, **kwargs)):
            result = run(["npm", "--version"], scratch("naccount-npm-smoke-"))
        self.assertRegex(result.stdout.decode("utf-8").strip(), r"^\d+\.\d+\.\d+$")


class StackTests(unittest.TestCase):
    def setUp(self):
        self.temp = scratch("naccount-stack-test-")
        self.upstream = self.temp / "official"
        self.upstream.mkdir()
        run(["git", "init", "-b", "main"], self.upstream)
        self.identity(self.upstream)
        (self.upstream / "hello.txt").write_text("upstream\n", encoding="utf-8")
        self.commit(self.upstream, "Initial upstream")
        self.root = self.temp / "workspace"
        self.root.mkdir()
        source = self.root / "melody-auth"
        run(["git", "clone", "--no-local", str(self.upstream), str(source)], self.root)
        self.identity(source)
        git(source, "switch", "-c", "naccount/main")
        self.config = {"schemaVersion": 1, "upstreamUrl": str(self.upstream), "upstreamBranch": "main",
                       "integrationBranch": "naccount/main", "commitTopicTrailer": "NAccount-Patch-Topic",
                       "topics": [{"id": "test.feature"}]}
        write_json(self.root / "customizations/stack.json", self.config)
        topic = self.root / "customizations/topics/test.feature/README.md"
        topic.parent.mkdir(parents=True)
        topic.write_text("Test fixture\n", encoding="utf-8")
        self.stack = Stack(self.root)
        self.stack.export()

    @staticmethod
    def identity(repo):
        git(repo, "config", "user.name", "NAccount Test")
        git(repo, "config", "user.email", "naccount-test@localhost")
        git(repo, "config", "core.autocrlf", "false")

    @staticmethod
    def commit(repo, message):
        git(repo, "add", "--all")
        git(repo, "commit", "-m", message)

    def personal(self, content="personal\n", filename="feature.txt"):
        (self.stack.source / filename).write_text(content, encoding="utf-8")
        self.commit(self.stack.source, "Add feature\n\nNAccount-Patch-Topic: test.feature")
        return self.stack.export()

    def fresh(self):
        root = self.temp / "fresh"
        root.mkdir()
        shutil.copytree(self.root / "customizations", root / "customizations")
        return Stack(root)

    def test_empty_stack_idempotent_and_immutable(self):
        before = (self.stack.catalog / "current.json").read_bytes()
        self.stack.initialize()
        self.stack.export()
        self.assertEqual(before, (self.stack.catalog / "current.json").read_bytes())
        restored = self.fresh()
        restored.initialize()
        self.assertEqual(self.stack.verify(), restored.verify())

    def test_exact_commit_restore_and_binary_patch_replay(self):
        (self.stack.source / "binary.bin").write_bytes(bytes(range(256)) * 2)
        (self.stack.source / "crlf.txt").write_bytes("中文 CRLF\r\n".encode("utf-8"))
        (self.stack.source / "lf.txt").write_bytes("中文 LF\n".encode("utf-8"))
        lock = self.personal("中文：账号服务\n")
        restored = self.fresh()
        restored.initialize()
        self.assertEqual(lock["head"], restored.verify()["head"])
        replay = self.temp / "patch-replay"
        self.stack.apply(replay)
        self.assertEqual(lock["tree"], tree(replay, "HEAD"))
        self.assertEqual((replay / "binary.bin").read_bytes(), bytes(range(256)) * 2)
        for name in ("crlf.txt", "lf.txt", "feature.txt"):
            self.assertEqual((replay / name).read_bytes(), (self.stack.source / name).read_bytes())

    def test_dirty_source_is_preserved(self):
        path = self.stack.source / "hello.txt"
        path.write_text("do not lose\n", encoding="utf-8")
        for operation in (self.stack.verify, self.stack.initialize, self.stack.export, self.stack.update):
            with self.assertRaisesRegex(StackError, "Dirty"):
                operation()
        self.assertEqual(path.read_text(encoding="utf-8"), "do not lose\n")

    def test_parent_repository_fallback_rejected(self):
        self.stack.source.rename(self.root / "saved-source")
        self.stack.source.mkdir()
        run(["git", "init", "-b", "main"], self.root)
        with self.assertRaisesRegex(StackError, "independent"):
            self.stack.initialize()

    def test_apply_refuses_existing_destination(self):
        with self.assertRaisesRegex(StackError, "existing destination"):
            self.stack.apply(self.stack.source)

    def test_corrupt_patch_detected(self):
        self.personal()
        folder, lock = self.stack.load()
        path = folder / lock["patches"][0]["file"]
        path.write_bytes(path.read_bytes() + b"tampered")
        with self.assertRaisesRegex(StackError, "hash mismatch"):
            self.stack.verify(catalog_only=True)

    def test_corrupt_bundle_detected(self):
        self.personal()
        folder, _ = self.stack.load()
        (folder / "personal-history.bundle").write_bytes(b"tampered")
        with self.assertRaisesRegex(StackError, "hash mismatch"):
            self.stack.initialize()

    def test_missing_topic_rejects_export_without_replacing_pointer(self):
        before = (self.stack.catalog / "current.json").read_bytes()
        (self.stack.source / "feature.txt").write_text("feature\n", encoding="utf-8")
        self.commit(self.stack.source, "No topic trailer")
        with self.assertRaisesRegex(StackError, "trailer"):
            self.stack.export()
        self.assertEqual(before, (self.stack.catalog / "current.json").read_bytes())

    def test_configuration_drift_detected(self):
        self.config["topics"].append({"id": "new.topic"})
        write_json(self.stack.config_path, self.config)
        with self.assertRaisesRegex(StackError, "configuration differs"):
            Stack(self.root).verify(catalog_only=True)

    def test_catalog_path_escape_rejected(self):
        write_json(self.stack.catalog / "current.json", {"generation": "../../outside"})
        with self.assertRaisesRegex(StackError, "Invalid generation"):
            self.stack.load()

    def test_upstream_update_exports_and_restores_new_stack(self):
        old = self.personal()
        (self.upstream / "new-upstream.txt").write_text("new upstream\n", encoding="utf-8")
        self.commit(self.upstream, "Advance upstream")
        new = self.stack.update()
        self.assertNotEqual(old["base"], new["base"])
        self.assertEqual(len(new["patches"]), 1)
        self.assertFalse(self.stack.pending_path().exists())
        restored = self.fresh()
        restored.initialize()
        self.assertEqual(new["head"], restored.verify()["head"])
        self.assertEqual(len(list((self.stack.catalog / "generated").iterdir())), 3)

    def conflict(self):
        self.personal("personal change\n", "hello.txt")
        (self.upstream / "hello.txt").write_text("upstream change\n", encoding="utf-8")
        self.commit(self.upstream, "Conflicting upstream")
        with self.assertRaisesRegex(StackError, "Update stopped"):
            self.stack.update()
        self.assertTrue(self.stack.pending_path().exists())

    def test_conflict_is_preserved_and_finalize_resumes(self):
        self.conflict()
        with self.assertRaises(StackError):
            self.stack.update()
        (self.stack.source / "hello.txt").write_text("resolved both intentions\n", encoding="utf-8")
        git(self.stack.source, "add", "hello.txt")
        git(self.stack.source, "-c", "core.editor=true", "rebase", "--continue")
        new = self.stack.finalize()
        self.assertEqual(len(new["patches"]), 1)
        self.assertFalse(self.stack.pending_path().exists())
        self.stack.verify()

    def test_abort_requires_explicit_git_abort(self):
        self.conflict()
        with self.assertRaises(StackError):
            self.stack.abandon()
        git(self.stack.source, "rebase", "--abort")
        self.stack.abandon()
        self.stack.verify()
        self.assertFalse(self.stack.pending_path().exists())


if __name__ == "__main__":
    unittest.main()
