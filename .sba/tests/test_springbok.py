"""应用统一入口的边界与顺序测试，不连接真实云资源。"""
import copy
import io
import os
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import springbok as sba
from stack import StackError, read_json, scratch, write_json


class SpringBokTests(unittest.TestCase):
    def setUp(self):
        self.temp = scratch('naccount-sba-test-')
        self.settings = {'accountId': '1' * 32, 'kvId': '2' * 32,
                         'database': {'name': 'naccount-test', 'id': '11111111-2222-3333-4444-555555555555'},
                         'server': {'name': 'naccount-auth', 'url': 'https://auth.example.com', 'secretNames': []},
                         'admin': {'name': 'naccount-admin', 'url': 'https://admin.example.com', 'spaClientId': '', 's2sClientId': ''},
                         'vars': {'SUPPORTED_LOCALES': ['en', 'zh']}}
        self.request = {'schemaVersion': 2, 'taskId': 'sba-test-01', 'action': 'deploy',
                        'repository': 'aiaimimi0920/NAccount', 'sourceSha': 'a' * 40,
                        'applicationId': 'naccount-cloudflare', 'applicationVersion': '1.0.0',
                        'environment': 'acceptance', 'configuration': self.settings, 'previous': None}
        self.rows = [{'id': 7, 'name': 'Admin Panel (SPA)', 'type': 'spa', 'clientId': 'spa-real',
                      'secret': 'unused', 'redirectUris': 'https://existing.example.com/callback'},
                     {'id': 9, 'name': 'Admin Panel (S2S)', 'type': 's2s', 'clientId': 's2s-real',
                      'secret': 'private-test-value', 'redirectUris': ''}]

    def test_exact_checkout_and_application_identity(self):
        with patch.object(sba, 'clean'), patch.object(sba, 'git', return_value='a' * 40):
            value = sba.validated_request(self.request, sba.ROOT)
            value['configuration']['kvId'] = 'changed'
            self.assertEqual(self.request['configuration']['kvId'], '2' * 32)
            for field, bad in [('sourceSha', 'b' * 40), ('applicationVersion', '2.0.0'),
                               ('repository', 'other/repo'), ('action', 'shell')]:
                value = copy.deepcopy(self.request)
                value[field] = bad
                with self.assertRaises(StackError):
                    sba.validated_request(value, sba.ROOT)

    def test_secret_material_cannot_hide_in_extra_configuration_fields(self):
        with patch.object(sba, 'clean'), patch.object(sba, 'git', return_value='a' * 40):
            for field in ('secret', 'credentials', 'unexpected'):
                value = copy.deepcopy(self.request)
                value['configuration'][field] = 'private-test-value'
                with self.assertRaises(StackError):
                    sba.validated_request(value, sba.ROOT)
            value = copy.deepcopy(self.request)
            value['configuration']['admin']['secret'] = 'private-test-value'
            with self.assertRaises(StackError):
                sba.validated_request(value, sba.ROOT)

    def test_cloud_write_requires_explicit_execution_gate(self):
        with patch.object(sba, 'validated_request', return_value=self.request), patch.dict(os.environ, {}, clear=True), \
                patch.object(sba.deploy, 'build') as build:
            with self.assertRaisesRegex(StackError, 'SBA_EXECUTE'):
                sba.execute(self.request)
            build.assert_not_called()

    def test_admin_clients_are_read_from_database_and_callbacks_preserved(self):
        new = 'https://existing.example.com/callback,https://admin.example.com/en/dashboard,https://admin.example.com/zh/dashboard'
        with patch.object(sba, 'database_query', side_effect=[self.rows, [], [{'redirectUris': new}]]) as query:
            settings, secret = sba.configure_admin(self.settings)
        self.assertEqual(settings['admin']['spaClientId'], 'spa-real')
        self.assertEqual(settings['admin']['s2sClientId'], 's2s-real')
        self.assertEqual(secret, 'private-test-value')
        self.assertNotIn(secret, str(settings))
        self.assertEqual(query.call_args_list[1].args[2], [new, 7, self.rows[0]['redirectUris']])
        self.assertEqual(self.settings['admin']['spaClientId'], '')

    def test_ambiguous_admin_clients_fail_before_any_update(self):
        with patch.object(sba, 'database_query', return_value=self.rows + [self.rows[0]]) as query:
            with self.assertRaisesRegex(StackError, 'Unique'):
                sba.configure_admin(self.settings)
            self.assertEqual(query.call_count, 1)

    def test_update_preserves_keys_and_orders_server_before_admin(self):
        self.request['action'] = 'update'
        calls = []
        def publish(release, *, migrate):
            calls.append((release, migrate))
        with patch.object(sba, 'validated_request', return_value=self.request), \
                patch.dict(os.environ, {'SBA_EXECUTE': '1', 'CLOUDFLARE_API_TOKEN': 'test-only', 'SERVER_CLIENT_SECRET': 'prior-value'}), \
                patch.object(sba, 'Stack') as stack, patch.object(sba.deploy, 'build', side_effect=['server-release', 'admin-release']), \
                patch.object(sba.deploy, 'bootstrap_keys') as bootstrap, patch.object(sba.deploy, 'publish', side_effect=publish), \
                patch.object(sba, 'configure_admin', return_value=(self.settings, 'private-test-value')), \
                patch.object(sba, 'readiness', return_value=[]):
            status, _ = sba.execute(self.request)
            bootstrap.assert_not_called()
            stack.return_value.initialize.assert_called_once()
            self.assertEqual(os.environ['SERVER_CLIENT_SECRET'], 'prior-value')
        self.assertEqual(calls, [('server-release', True), ('admin-release', False)])
        self.assertEqual(status, 'deployed-unverified')

    def test_server_failure_stops_before_admin_and_does_not_replay(self):
        with patch.object(sba, 'validated_request', return_value=self.request), patch.dict(os.environ, {'SBA_EXECUTE': '1', 'CLOUDFLARE_API_TOKEN': 'test-only'}), \
                patch.object(sba, 'Stack'), patch.object(sba.deploy, 'build', return_value='server'), \
                patch.object(sba.deploy, 'bootstrap_keys'), patch.object(sba.deploy, 'publish', side_effect=StackError('failed')) as publish, \
                patch.object(sba, 'configure_admin') as admin:
            with self.assertRaises(StackError):
                sba.execute(self.request)
            self.assertEqual(publish.call_count, 1)
            admin.assert_not_called()

    def test_result_failure_is_bound_and_never_contains_exception_secret(self):
        request_path, result_path = self.temp / 'request.json', self.temp / 'result.json'
        write_json(request_path, self.request)
        with patch.object(sys, 'argv', ['springbok.py', '--request', str(request_path), '--result', str(result_path)]), \
                patch.dict(os.environ, {'SBA_EXECUTE': '1'}), \
                patch.object(sba, 'execute', side_effect=StackError('private-test-value')), redirect_stderr(io.StringIO()) as logs:
            self.assertEqual(sba.main(), 1)
        result = read_json(result_path)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['sourceSha'], self.request['sourceSha'])
        self.assertNotIn('private-test-value', str(result) + logs.getvalue())

    def test_build_failure_reports_fixed_prewrite_stage_and_never_calls_cloud(self):
        request_path, result_path = self.temp / 'request.json', self.temp / 'result.json'
        write_json(request_path, self.request)
        with patch.object(sys, 'argv', ['springbok.py', '--request', str(request_path), '--result', str(result_path)]), \
                patch.dict(os.environ, {'SBA_EXECUTE': '1', 'CLOUDFLARE_API_TOKEN': 'test-only'}), \
                patch.object(sba, 'validated_request', return_value=self.request), patch.object(sba, 'Stack'), \
                patch.object(sba.deploy, 'build', side_effect=OSError('private-test-value')), \
                patch.object(sba.deploy, 'bootstrap_keys') as keys, patch.object(sba.deploy, 'publish') as publish, \
                redirect_stderr(io.StringIO()) as logs:
            self.assertEqual(sba.main(), 1)
        result = read_json(result_path)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['errorCode'], 'NACCOUNT_SERVER_BUILD_FAILED')
        self.assertEqual(result['checks'], [{'id': 'cloud-writes-not-started', 'passed': True}])
        keys.assert_not_called(); publish.assert_not_called()
        self.assertNotIn('private-test-value', str(result) + logs.getvalue())

    def test_first_possible_cloud_write_failure_stays_unknown(self):
        request_path, result_path = self.temp / 'request.json', self.temp / 'result.json'
        write_json(request_path, self.request)
        with patch.object(sys, 'argv', ['springbok.py', '--request', str(request_path), '--result', str(result_path)]), \
                patch.dict(os.environ, {'SBA_EXECUTE': '1', 'CLOUDFLARE_API_TOKEN': 'test-only'}), \
                patch.object(sba, 'validated_request', return_value=self.request), patch.object(sba, 'Stack'), \
                patch.object(sba.deploy, 'build', return_value='server'), \
                patch.object(sba.deploy, 'bootstrap_keys', side_effect=OSError('private-test-value')) as keys, \
                patch.object(sba.deploy, 'publish') as publish, redirect_stderr(io.StringIO()) as logs:
            self.assertEqual(sba.main(), 1)
        result = read_json(result_path)
        self.assertEqual(result['status'], 'unknown'); self.assertEqual(result['errorCode'], 'NACCOUNT_KEYS_FAILED')
        self.assertEqual(result['checks'], []); self.assertEqual(keys.call_count, 1); publish.assert_not_called()
        self.assertNotIn('private-test-value', str(result) + logs.getvalue())


if __name__ == '__main__':
    unittest.main()
