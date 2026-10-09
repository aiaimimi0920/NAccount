"""应用统一入口的边界与顺序测试，不连接真实云资源。"""
import copy
import io
import json
import os
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import springbok as sba
from stack import StackError, read_json, scratch, write_json


class SpringBokTests(unittest.TestCase):
    def test_deployment_form_matches_public_configuration_and_owns_no_credentials(self):
        declaration = read_json(sba.ROOT / '.sba/deployment.json')
        self.assertEqual(declaration['schemaVersion'], 2)
        self.assertEqual(declaration['target'], 'cloudflare-workers')
        self.assertEqual(declaration['accountPath'], ['accountId'])
        self.assertEqual([r['kind'] for r in declaration['resources']], ['d1', 'kv'])
        self.assertEqual([t['kind'] for t in declaration['targets']], ['worker', 'domain', 'worker', 'domain'])
        settings = copy.deepcopy(declaration['defaults'])
        def assign(path, value):
            row = settings
            for key in path[:-1]:
                row = row.setdefault(key, {})
            row[path[-1]] = value
        assign(declaration['accountPath'], self.settings['accountId'])
        for field in declaration['fields']:
            value = self.settings
            for key in field['path']:
                value = value[key]
            assign(field['path'], copy.deepcopy(value))
        for resource in declaration['resources']:
            assign(resource['idPath'], self.settings['database']['id'] if resource['kind'] == 'd1' else self.settings['kvId'])
            if resource['namePath']:
                assign(resource['namePath'], self.settings['database']['name'])
        self.assertEqual(settings, self.settings)
        self.assertEqual(declaration['defaults']['server']['secretNames'], [])
        self.assertEqual(declaration['defaults']['admin']['spaClientId'], '')
        self.assertEqual(declaration['defaults']['admin']['s2sClientId'], '')
        self.assertEqual(declaration['defaults']['vars']['EMAIL_PROVIDER_NAME'], 'cloudflare')
        self.assertEqual(declaration['defaults']['server']['name'], '')
        with patch.object(sba, 'clean'), patch.object(sba, 'git', return_value='a' * 40):
            value = copy.deepcopy(self.request)
            value['configuration'] = settings
            self.assertEqual(sba.validated_request(value, sba.ROOT)['configuration'], settings)

    def setUp(self):
        unused = patch.object(sba.lifecycle, 'require_unused_workers')
        unused.start()
        self.addCleanup(unused.stop)
        self.temp = scratch('naccount-sba-test-')
        self.settings = {'accountId': '1' * 32, 'kvId': '2' * 32,
                         'database': {'name': 'naccount-test', 'id': '11111111-2222-3333-4444-555555555555'},
                         'server': {'name': 'naccount-auth', 'url': 'https://auth.example.com', 'secretNames': []},
                         'admin': {'name': 'naccount-admin', 'url': 'https://admin.example.com', 'spaClientId': '', 's2sClientId': ''},
                         'vars': {'SUPPORTED_LOCALES': ['en', 'zh']}}
        self.request = {'schemaVersion': 3, 'taskId': 'sba-test-01', 'action': 'deploy',
                        'repository': 'aiaimimi0920/NAccount', 'sourceSha': 'a' * 40,
                        'applicationId': 'naccount-cloudflare', 'applicationVersion': json.loads((sba.ROOT / '.sba/manifest.json').read_text(encoding='utf-8'))['version'],
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

    def test_bootstrap_password_is_not_a_runtime_secret(self):
        value=copy.deepcopy(self.settings);value['server']['secretNames']=['ADMIN_BOOTSTRAP_PASSWORD']
        with self.assertRaises(StackError):
            sba.public_settings(value,read_json(sba.ROOT / '.sba/manifest.json'))

    def test_first_admin_initializes_before_publish_and_password_never_reaches_build(self):
        self.settings['admin']['bootstrapEmail']='fixture@gmail.com'
        events=[]
        def build(*args):
            self.assertNotIn('ADMIN_BOOTSTRAP_PASSWORD',os.environ)
            events.append('build');return Path('release')
        def publish(*args,**kwargs):
            self.assertNotIn('ADMIN_BOOTSTRAP_PASSWORD',os.environ);events.append('publish')
        def initialize(*args):
            events.append('administrator');return {'id':'administrator-initialized','passed':True}
        with patch.object(sba,'validated_request',return_value=self.request), \
                patch.dict(os.environ,{'SBA_EXECUTE':'1','CLOUDFLARE_API_TOKEN':'test-only','ADMIN_BOOTSTRAP_PASSWORD':'Synthetic-Only!42'}), \
                patch.object(sba,'Stack'),patch.object(sba.deploy,'build',side_effect=build), \
                patch.object(sba.deploy,'wrangler'),patch.object(sba.deploy,'bootstrap_keys'),patch.object(sba.deploy,'publish',side_effect=publish), \
                patch.object(sba.admin_bootstrap,'material',return_value={'hash':'synthetic','otp':'synthetic'}) as material, \
                patch.object(sba.admin_bootstrap,'initialize',side_effect=initialize), \
                patch.object(sba,'configure_admin',return_value=(self.settings,'test-s2s')),patch.object(sba,'readiness',return_value=[]):
            status,checks,_=sba.execute(self.request)
            material.assert_called_once_with(Path('release'),'Synthetic-Only!42')
        self.assertEqual(status,'deployed-unverified');self.assertEqual(events,['build','administrator','publish','build','publish'])
        self.assertIn({'id':'administrator-initialized','passed':True},checks)

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
                patch.object(sba, 'Stack') as stack, patch.object(sba.deploy, 'build', side_effect=[Path('server-release'), Path('admin-release')]), \
                patch.object(sba.lifecycle, 'export_snapshot', return_value={'createdAt': 1, 'witness': {}}), \
                patch.object(sba.deploy, 'cloud_api', return_value={'bookmark': 'test-bookmark'}), patch.object(sba.deploy, 'wrangler'), \
                patch.object(sba.lifecycle, 'prove_rows'), \
                patch.object(sba.deploy, 'bootstrap_keys') as bootstrap, patch.object(sba.deploy, 'publish', side_effect=publish), \
                patch.object(sba, 'configure_admin', return_value=(self.settings, 'private-test-value')), \
                patch.object(sba, 'readiness', return_value=[]):
            status, _, _ = sba.execute(self.request)
            bootstrap.assert_not_called()
            stack.return_value.initialize.assert_called_once()
            self.assertEqual(os.environ['SERVER_CLIENT_SECRET'], 'prior-value')
        self.assertEqual(calls, [(Path('server-release'), False), (Path('admin-release'), False)])
        self.assertEqual(status, 'deployed-unverified')

    def test_server_failure_stops_before_admin_and_does_not_replay(self):
        with patch.object(sba, 'validated_request', return_value=self.request), patch.dict(os.environ, {'SBA_EXECUTE': '1', 'CLOUDFLARE_API_TOKEN': 'test-only'}), \
                patch.object(sba, 'Stack'), patch.object(sba.deploy, 'build', return_value=Path('server')), patch.object(sba.deploy, 'wrangler'), \
                patch.object(sba.deploy, 'bootstrap_keys'), patch.object(sba.deploy, 'publish', side_effect=StackError('failed')) as publish, \
                patch.object(sba, 'configure_admin') as admin:
            with self.assertRaises(StackError):
                sba.execute(self.request)
            self.assertEqual(publish.call_count, 1)
            admin.assert_not_called()

    def test_readiness_uses_identifiable_agent_without_credentials(self):
        calls = []
        payloads = [{'issuer': self.settings['server']['url']}, {'keys': [{'kid': 'test-key'}]}, {}]
        def response(request, *, timeout):
            self.assertIsInstance(request, Request)
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.get_header('User-agent'), 'NAccount-SBA/2.0')
            self.assertEqual(dict(request.header_items()), {'User-agent': 'NAccount-SBA/2.0'})
            self.assertIsNone(request.data)
            self.assertEqual(timeout, 30)
            calls.append(request.full_url)
            stream = io.BytesIO(json.dumps(payloads[len(calls) - 1]).encode())
            stream.status = 200
            return stream
        with patch.dict(os.environ, {'CLOUDFLARE_API_TOKEN': 'private-test-value'}), patch.object(sba, 'urlopen', side_effect=response):
            checks = sba.readiness(self.settings)
        self.assertEqual(calls, ['https://auth.example.com/.well-known/openid-configuration',
                                 'https://auth.example.com/.well-known/jwks.json', 'https://admin.example.com'])
        self.assertEqual(checks, [{'id': name, 'passed': True} for name in
                                 ('oidc-discovery', 'jwks-ready', 'admin-http-ready')])

    def test_readiness_denial_stops_without_retry_or_cloud_writes(self):
        failure = HTTPError(self.settings['server']['url'], 403, 'Forbidden', {}, None)
        with patch.object(sba, 'urlopen', side_effect=failure) as request, \
                patch.object(sba.deploy, 'cloud_api') as cloud, patch.object(sba.deploy, 'publish') as publish:
            with self.assertRaises(HTTPError):
                sba.readiness(self.settings)
        self.assertEqual(request.call_count, 1)
        cloud.assert_not_called(); publish.assert_not_called()

    def test_readiness_preserves_issuer_and_nonempty_jwks_checks(self):
        for payloads, message, count in [([{'issuer': 'https://wrong.example.com'}], 'issuer mismatch', 1),
                                         ([{'issuer': self.settings['server']['url']}, {'keys': []}], 'JWKS empty', 2)]:
            with self.subTest(message=message), patch.object(sba, 'urlopen', side_effect=[
                    io.BytesIO(json.dumps(value).encode()) for value in payloads]) as request:
                with self.assertRaisesRegex(StackError, message):
                    sba.readiness(self.settings)
                self.assertEqual(request.call_count, count)

    def test_post_publish_readiness_failure_stays_unknown(self):
        request_path, result_path = self.temp / 'request.json', self.temp / 'result.json'
        write_json(request_path, self.request)
        def failure(_request, *, on_stage):
            on_stage('readiness', True)
            raise HTTPError(self.settings['server']['url'], 403, 'private-test-value', {}, None)
        with patch.object(sys, 'argv', ['springbok.py', '--request', str(request_path), '--result', str(result_path)]), \
                patch.dict(os.environ, {'SBA_EXECUTE': '1'}), patch.object(sba, 'execute', side_effect=failure), \
                redirect_stderr(io.StringIO()) as logs:
            self.assertEqual(sba.main(), 1)
        result = read_json(result_path)
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['errorCode'], 'NACCOUNT_READINESS_FAILED')
        self.assertEqual(result['checks'], [])
        self.assertNotIn('private-test-value', str(result) + logs.getvalue())

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
