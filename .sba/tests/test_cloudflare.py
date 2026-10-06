"""Deployment boundaries with fake providers; never contacts Cloudflare."""

import json
import io
import os
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cloudflare as deploy
from stack import StackError, read_json, scratch, write_json


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = scratch("naccount-deploy-test-")
        self.settings = {"accountId": "1" * 32, "kvId": "2" * 32,
                         "database": {"name": "naccount-test", "id": "11111111-2222-3333-4444-555555555555"},
                         "server": {"name": "naccount-auth", "url": "https://auth.example.com", "secretNames": []},
                         "admin": {"name": "naccount-admin", "url": "https://admin.example.com", "spaClientId": "spa-id", "s2sClientId": "s2s-id"},
                         "vars": {"SUPPORTED_LOCALES": ["en", "zh"]}}
        self.path = self.temp / "config.json"
        write_json(self.path, self.settings)

    def test_config_rejects_placeholder_resource_ids(self):
        self.settings["kvId"] = "REPLACE_ME"
        write_json(self.path, self.settings)
        with self.assertRaisesRegex(StackError, "kvId"):
            deploy.config(self.path, "server")

    def test_admin_requires_created_client_ids(self):
        self.settings["admin"]["spaClientId"] = ""
        write_json(self.path, self.settings)
        deploy.config(self.path, "server")
        with self.assertRaisesRegex(StackError, "Bootstrap"):
            deploy.config(self.path, "all")

    def test_secret_values_not_allowed_in_public_vars(self):
        self.settings["vars"]["RESEND_API_KEY"] = "do-not-persist"
        write_json(self.path, self.settings)
        with self.assertRaisesRegex(StackError, "Secret"):
            deploy.config(self.path, "server")

    def test_same_domain_and_workers_dev_are_rejected(self):
        for url in (self.settings["server"]["url"], "https://admin.test.workers.dev", "https://user:pass@example.com"):
            self.settings["admin"]["url"] = url
            write_json(self.path, self.settings)
            with self.assertRaises(StackError):
                deploy.config(self.path, "all")

    def test_server_config_uses_owned_resources_and_preserves_defaults(self):
        server = self.temp / "server"
        server.mkdir()
        (server / "wrangler.toml").write_text('name="upstream"\n[vars]\nSAFE=true\n', encoding="utf-8")
        generated = deploy.server_config(self.temp, self.settings)
        self.assertEqual(generated["name"], "naccount-auth")
        self.assertEqual(generated["vars"]["ENVIRONMENT"], "prod")
        self.assertTrue(generated["vars"]["SAFE"])
        self.assertEqual(generated["d1_databases"][0]["binding"], "DB")
        self.assertEqual(generated["kv_namespaces"][0]["id"], "2" * 32)
        self.assertFalse(generated["workers_dev"])

    def test_unbuilt_release_refused(self):
        write_json(self.temp / "release.json", {"state": "prepared"})
        with self.assertRaisesRegex(StackError, "did not pass"):
            deploy.checked_release(self.temp)

    def test_cloudflare_email_binding_uses_only_the_configured_sender(self):
        server = self.temp / 'server'
        server.mkdir()
        (server / 'wrangler.toml').write_text('name="upstream"\n[vars]\nSAFE=true\n', encoding='utf-8')
        self.settings['vars'].update(EMAIL_PROVIDER_NAME='cloudflare', CLOUDFLARE_SENDER_ADDRESS='accounts@example.com')
        write_json(self.path, self.settings)
        deploy.config(self.path, 'server')
        generated = deploy.server_config(self.temp, self.settings)
        self.assertEqual(generated['send_email'], [{'name': 'CLOUDFLARE_EMAIL', 'allowed_sender_addresses': ['accounts@example.com']}])
        self.assertNotIn('CLOUDFLARE_API_TOKEN', str(generated))
        self.settings['vars']['CLOUDFLARE_SENDER_ADDRESS'] = 'bad\naddress'
        write_json(self.path, self.settings)
        with self.assertRaises(StackError):
            deploy.config(self.path, 'server')

    def test_runtime_secrets_not_passed_to_local_build(self):
        (self.temp / "server").mkdir()
        self.settings["server"]["secretNames"] = ["RESEND_API_KEY"]
        with patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "test-token", "SERVER_CLIENT_SECRET": "test-secret", "RESEND_API_KEY": "test-mail"}):
            with patch.object(deploy, "run") as command:
                command.return_value.stdout = b""
                command.return_value.stderr = b""
                deploy.app_command(self.temp, "server", ["npm", "run", "build"], self.settings)
                env = command.call_args.kwargs["env"]
                for name in ("CLOUDFLARE_API_TOKEN", "SERVER_CLIENT_SECRET", "RESEND_API_KEY"):
                    self.assertNotIn(name, env)

    def test_existing_keys_are_never_rotated(self):
        with patch.object(deploy, "checked_release", return_value=(self.settings, {"component": "server"})), \
                patch.object(deploy, "existing_keys", return_value=deploy.KEY_NAMES), \
                patch.object(deploy, "cloud_api") as api, patch.object(deploy, "run") as command:
            deploy.bootstrap_keys(self.temp)
            api.assert_not_called()
            command.assert_not_called()

    def test_partial_keys_fail_without_writes(self):
        with patch.object(deploy, "checked_release", return_value=(self.settings, {"component": "server"})), \
                patch.object(deploy, "existing_keys", return_value={"sessionSecret"}), \
                patch.object(deploy, "cloud_api") as api:
            with self.assertRaisesRegex(StackError, "Partial"):
                deploy.bootstrap_keys(self.temp)
            api.assert_not_called()

    def test_publish_backs_up_then_migrates_without_key_generation(self):
        with patch.object(deploy, "checked_release", return_value=(self.settings, {"component": "server"})), \
                patch.object(deploy, "existing_keys", return_value=deploy.KEY_NAMES), \
                patch.object(deploy, "wrangler") as cli, patch.object(deploy, "bootstrap_keys") as keys:
            deploy.publish(self.temp, migrate=True)
            commands = [call.args[2] for call in cli.call_args_list]
            self.assertEqual(commands[0][:2], ["d1", "export"])
            self.assertEqual(commands[1][:3], ["d1", "migrations", "apply"])
            self.assertEqual(commands[2], ["deploy"])
            keys.assert_not_called()

    def test_failed_migration_stops_before_deploy(self):
        with patch.object(deploy, "checked_release", return_value=(self.settings, {"component": "server"})), \
                patch.object(deploy, "existing_keys", return_value=deploy.KEY_NAMES), \
                patch.object(deploy, "wrangler", side_effect=[b"", StackError("migration failed")]) as cli:
            with self.assertRaisesRegex(StackError, "migration failed"):
                deploy.publish(self.temp, migrate=True)
            self.assertEqual(cli.call_count, 2)

    def test_cloud_actions_require_execute_before_reading_release(self):
        for action in ("publish", "bootstrap-keys"):
            with patch.object(sys, "argv", ["cloudflare.py", action, "--release", str(self.temp)]), \
                    patch.object(deploy, "checked_release") as checked, \
                    patch.object(deploy, "cloud_api") as api, redirect_stderr(io.StringIO()):
                self.assertEqual(deploy.main(), 1)
                checked.assert_not_called()
                api.assert_not_called()

    def test_plan_is_catalog_only_without_cloud_or_build_commands(self):
        with patch.object(sys, "argv", ["cloudflare.py", "plan", "--config", str(self.path)]), \
                patch.object(deploy, "Stack") as stack, patch.object(deploy, "cloud_api") as api, \
                patch.object(deploy, "app_command") as command, redirect_stdout(io.StringIO()) as output:
            stack.return_value.verify.return_value = {"head": "a" * 40}
            self.assertEqual(deploy.main(), 0)
            stack.return_value.verify.assert_called_once_with(catalog_only=True)
            api.assert_not_called()
            command.assert_not_called()
            self.assertFalse(json.loads(output.getvalue())["cloudWrites"])

    def test_json_plan_has_single_machine_readable_result(self):
        with patch.object(sys, "argv", ["cloudflare.py", "plan", "--config", str(self.path), "--json"]), \
                patch.object(deploy, "Stack") as stack, patch.object(deploy, "cloud_api") as api, \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as logs:
            stack.return_value.verify.return_value = {"head": "a" * 40}
            self.assertEqual(deploy.main(), 0)
            response = json.loads(output.getvalue())
            self.assertEqual(response["schemaVersion"], 1)
            self.assertTrue(response["ok"])
            self.assertEqual(response["action"], "plan")
            self.assertFalse(response["result"]["cloudWrites"])
            self.assertEqual(logs.getvalue(), "")
            api.assert_not_called()

    def test_json_failure_requires_execute_before_cloud_access(self):
        with patch.object(sys, "argv", ["cloudflare.py", "publish", "--release", str(self.temp), "--json"]), \
                patch.object(deploy, "checked_release") as checked, patch.object(deploy, "cloud_api") as api, \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as logs:
            self.assertEqual(deploy.main(), 1)
            response = json.loads(output.getvalue())
            self.assertFalse(response["ok"])
            self.assertEqual(response["action"], "publish")
            self.assertIn("--execute", response["error"]["message"])
            self.assertIn("ERROR:", logs.getvalue())
            checked.assert_not_called()
            api.assert_not_called()

    def test_manifest_owns_actions_and_entrypoint(self):
        folder = Path(deploy.__file__).resolve().parent
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 2)
        self.assertEqual(manifest["entrypoint"], "springbok.ps1")
        self.assertTrue((folder / manifest["entrypoint"]).is_file())
        self.assertEqual(set(manifest["actions"]), {"deploy", "update", "verify"})
        self.assertTrue((folder / 'deploy.ps1').is_file())
        self.assertEqual(manifest['runtime']['runner'], 'windows-2025')

    def built_fixture(self):
        payload = self.temp / "source/server/dist/worker.js"
        payload.parent.mkdir(parents=True)
        payload.write_text("export default {}\n", encoding="utf-8")
        write_json(self.temp / "deployment.json", self.settings)
        receipt = {"state": "built", "component": "all", "files": deploy.inventory(self.temp),
                   "deploymentScriptSha256": deploy.sha(Path(deploy.__file__).read_bytes()),
                   "stackScriptSha256": deploy.sha((deploy.ROOT / "scripts/stack.py").read_bytes())}
        write_json(self.temp / "release.json", receipt)
        return payload

    def test_checked_release_requires_explicit_cloud_token(self):
        self.built_fixture()
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(StackError, "CLOUDFLARE_API_TOKEN"):
            deploy.checked_release(self.temp)

    def test_changed_payload_is_refused_before_publishing(self):
        payload = self.built_fixture()
        payload.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(StackError, "payload or configuration changed"):
            deploy.checked_release(self.temp)

    def test_changed_deployment_tools_require_rebuild(self):
        self.built_fixture()
        receipt = read_json(self.temp / "release.json")
        receipt["deploymentScriptSha256"] = "0" * 64
        write_json(self.temp / "release.json", receipt)
        with self.assertRaisesRegex(StackError, "tools changed"):
            deploy.checked_release(self.temp)

    def test_missing_runtime_secret_stops_before_cloud_reads_or_writes(self):
        self.settings["server"]["secretNames"] = ["RESEND_API_KEY"]
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(deploy, "checked_release", return_value=(self.settings, {"component": "server"})), \
                patch.object(deploy, "existing_keys") as keys, patch.object(deploy, "wrangler") as cli:
            with self.assertRaisesRegex(StackError, "Missing runtime secrets"):
                deploy.publish(self.temp, migrate=True)
            keys.assert_not_called()
            cli.assert_not_called()


if __name__ == "__main__":
    unittest.main()
