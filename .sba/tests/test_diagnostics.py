"""失败诊断只传固定类别，不能把发布日志或密码带入回执。"""
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cloudflare as deploy
import springbok as sba
from diagnostics import command_failure, DeploymentCommandError, result_error
from stack import scratch, write_json, read_json


class DiagnosticsTests(unittest.TestCase):
    command = ['node', 'C:/isolated/server/node_modules/wrangler/bin/wrangler.js', 'deploy', '--config', 'wrangler.json']

    def test_cf_code_excludes_private_output(self):
        error = command_failure(self.command, b'private-stdout', b'private-token [code: 10000]')
        self.assertEqual(str(error), 'WRANGLER_DEPLOY_CF_10000')
        self.assertEqual(result_error('NACCOUNT_ADMIN_PUBLISH_FAILED', error), 'NACCOUNT_ADMIN_PUBLISH_WRANGLER_DEPLOY_CF_10000')

    def test_ambiguous_unknown_and_network_are_bounded(self):
        for data, expected in [(b'[code: 10000] [code: 10021]', 'EXIT_NONZERO'),
                               (b'private fetch failed private', 'NETWORK'),
                               (b'private [code: 1234567]', 'EXIT_NONZERO'),
                               (b'private-output', 'EXIT_NONZERO')]:
            self.assertEqual(str(command_failure(self.command, b'', data)), 'WRANGLER_DEPLOY_' + expected)

    def test_secret_output_is_not_inspected(self):
        command = self.command[:2] + ['secret', 'bulk']
        self.assertEqual(str(command_failure(command, b'[code: 10021]', b'fetch failed', secret_input=True)),
                         'WRANGLER_SECRET_EXIT_NONZERO')

    def test_failed_command_is_not_retried_or_printed(self):
        settings = {'accountId': '1' * 32, 'server': {'secretNames': []}}
        temp = scratch('naccount-diagnostic-test-')
        output = io.StringIO()
        completed = subprocess.CompletedProcess(self.command, 1, b'private-output', b'private-token [code: 10021]')
        with patch.object(deploy, 'run', return_value=completed) as run, redirect_stdout(output), redirect_stderr(output):
            with self.assertRaises(DeploymentCommandError) as error:
                deploy.app_command(temp, 'server', self.command, settings)
        self.assertEqual(str(error.exception), 'WRANGLER_DEPLOY_CF_10021')
        self.assertEqual(run.call_count, 1)
        self.assertFalse(run.call_args.kwargs['check'])
        self.assertNotIn('private-', output.getvalue())

    def test_spawn_failure_is_fixed_and_does_not_leak(self):
        with patch.object(deploy, 'run', side_effect=OSError('private-path')), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(DeploymentCommandError, '^WRANGLER_DEPLOY_SPAWN_FAILED$'):
                deploy.app_command(scratch('naccount-diagnostic-test-'), 'server', self.command,
                                   {'accountId': '1' * 32, 'server': {'secretNames': []}})

    def test_public_result_preserves_unknown_and_identity(self):
        self.assert_public_result_preserves_unknown_and_identity('deploy')

    def test_repair_failure_preserves_unknown_and_identity(self):
        self.assert_public_result_preserves_unknown_and_identity('repair')

    def assert_public_result_preserves_unknown_and_identity(self, action):
        temp = scratch('naccount-diagnostic-result-')
        request = {'schemaVersion': 3, 'taskId': 'diagnostic-test', 'action': action,
                   'sourceSha': 'a' * 40, 'applicationVersion': '3.0.2'}
        write_json(temp / 'request.json', request)
        def execute(_request, *, on_stage):
            on_stage('admin-publish', True)
            raise command_failure(self.command, b'private-password', b'[code: 10021] private-token')
        logs = io.StringIO()
        with patch.object(sys, 'argv', ['springbok.py', '--request', str(temp / 'request.json'), '--result', str(temp / 'result.json')]), \
                patch.dict(os.environ, {'SBA_EXECUTE': '1'}), patch.object(sba, 'execute', side_effect=execute), redirect_stderr(logs):
            self.assertEqual(sba.main(), 1)
        result = read_json(temp / 'result.json')
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['checks'], [])
        self.assertEqual(result['errorCode'], 'NACCOUNT_ADMIN_PUBLISH_WRANGLER_DEPLOY_CF_10021')
        for key, value in request.items():
            self.assertEqual(result[key], value)
        self.assertNotIn('private-', str(result) + logs.getvalue())

    def test_untyped_exception_is_not_serialized(self):
        self.assertEqual(result_error('NACCOUNT_ADMIN_PUBLISH_FAILED', ValueError('private')),
                         'NACCOUNT_ADMIN_PUBLISH_FAILED')

    def test_diagnostic_module_is_inside_build_hash_fence(self):
        temp = scratch('naccount-diagnostic-hash-')
        for name in ['cloudflare.py', 'lifecycle.py', 'springbok.py', 'repair.py', 'diagnostics.py', 'admin_bootstrap.py', 'admin_bootstrap.mjs']:
            (temp / name).write_text('fixture', encoding='utf-8')
        with patch.object(deploy, '__file__', str(temp / 'cloudflare.py')):
            before = deploy.deployment_tools_hash()
            write_json(temp / 'release.json', {'state': 'built', 'deploymentScriptSha256': before})
            (temp / 'diagnostics.py').write_text('changed', encoding='utf-8')
            self.assertNotEqual(before, deploy.deployment_tools_hash())
            with self.assertRaisesRegex(Exception, 'Deployment tools changed since build'):
                deploy.checked_release(temp)


if __name__ == '__main__':
    unittest.main()
