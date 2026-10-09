"""后台修复只允许既有资源上的最窄写入，不以Access页面冒充发布成功。"""
import copy
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import repair
import springbok as sba
from stack import StackError, scratch, write_json


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'accountId': '1' * 32, 'kvId': '2' * 32,
                         'database': {'id': '11111111-2222-3333-4444-555555555555', 'name': 'db'},
                         'server': {'name': 'auth', 'url': 'https://auth.example.com', 'secretNames': []},
                         'admin': {'name': 'admin', 'url': 'https://admin.example.com', 'spaClientId': 'spa', 's2sClientId': 's2s'}, 'vars': {}}
        self.request = {'taskId': 'dc-' + '1' * 32, 'context': {'repairId': 'admin-publish',
            'parentTaskId': 'dc-' + '2' * 32, 'parentRunId': 1, 'requestDigest': 'a' * 64,
            'resultDigest': 'b' * 64, 'errorCode': 'NACCOUNT_ADMIN_PUBLISH_FAILED'}}

    def test_context_is_exact_and_bound_to_original_error(self):
        repair.validate_context(self.request)
        for key, value in [('repairId', 'deploy'), ('parentRunId', True), ('parentRunId', 0),
                           ('parentTaskId', self.request['taskId']), ('requestDigest', 'secret'),
                           ('errorCode', 'OTHER_FAILED'), ('extra', 'unexpected')]:
            request = copy.deepcopy(self.request); request['context'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(StackError):
                repair.validate_context(request)

    def provider(self):
        auth = {'settings': {'compatibility_date': '2025-01-01', 'bindings': [
            {'name': 'DB', 'type': 'd1', 'id': self.settings['database']['id']},
            {'name': 'KV', 'type': 'kv_namespace', 'namespace_id': self.settings['kvId']} ]}, 'version': {'id': 'auth-old'}}
        admin = {'settings': {'compatibility_date': '', 'annotations': {'workers/triggered_by': 'secret'},
                 'bindings': [{'name': 'SERVER_CLIENT_SECRET', 'type': 'secret_text'}]},
                 'version': {'resources': {'script_runtime': {}}}}
        domains = [{'hostname': 'auth.example.com', 'service': 'auth', 'environment': 'production'}]
        return auth, admin, domains

    def test_preflight_refuses_placeholder_resource_and_domain_drift(self):
        for change in ('none', 'admin-date', 'admin-binding', 'admin-assets', 'db', 'kv', 'domain', 'occupied'):
            auth, admin, domains = self.provider()
            if change == 'admin-date': admin['settings']['compatibility_date'] = '2025-01-01'
            if change == 'admin-binding': admin['settings']['bindings'].append({'name': 'other', 'type': 'secret_text'})
            if change == 'admin-assets': admin['version']['resources']['script_runtime']['assets'] = {'base_path': 'existing'}
            if change == 'db': auth['settings']['bindings'][0]['id'] = 'other'
            if change == 'kv': auth['settings']['bindings'][1]['namespace_id'] = 'other'
            if change == 'domain': domains[0]['service'] = 'other'
            if change == 'occupied': domains.append({'hostname': 'admin.example.com', 'service': 'other', 'environment': 'production'})
            with self.subTest(change=change), patch.object(repair, 'domains', return_value=domains), \
                    patch.object(repair, 'worker', side_effect=lambda _s, role: auth if role == 'server' else admin), \
                    patch.object(repair.deploy, 'cloud_api', return_value={'name': 'db'}):
                if change == 'none': self.assertEqual(set(repair.preflight(self.settings)), {'auth', 'admin', 'domain'})
                else:
                    with self.assertRaises(StackError): repair.preflight(self.settings)

    def test_published_requires_actual_assets_vars_domain_and_unchanged_auth(self):
        release = scratch('naccount-repair-config-')
        write_json(release / 'source/admin-panel/wrangler.json', {'compatibility_date': '2025-01-01', 'compatibility_flags': ['nodejs_compat']})
        for change in ('none', 'auth', 'domain', 'assets', 'vars', 'date', 'flags', 'binding'):
            auth, old, domains = self.provider()
            before = {'auth': repair.digest(auth), 'domain': repair.digest(domains), 'admin': repair.digest(old)}
            admin = {'settings': {'compatibility_date': '2025-01-01', 'compatibility_flags': ['nodejs_compat'], 'bindings': [
                {'name': 'SERVER_CLIENT_SECRET', 'type': 'secret_text'}, {'name': 'ASSETS', 'type': 'assets'},
                *[{'name': k, 'type': 'plain_text', 'text': v} for k, v in repair.deploy.admin_env(self.settings).items()]]},
                'version': {'resources': {'script_runtime': {'assets': {'base_path': 'deployed-assets'}}}}}
            domains.append({'hostname': 'admin.example.com', 'service': 'admin', 'environment': 'production'})
            if change == 'auth': auth['version']['id'] = 'changed'
            if change == 'domain': domains[1]['service'] = 'other'
            if change == 'assets': admin['version']['resources']['script_runtime']['assets']['base_path'] = ''
            if change == 'vars': admin['settings']['bindings'][-1]['text'] = 'wrong'
            if change == 'date': admin['settings']['compatibility_date'] = ''
            if change == 'flags': admin['settings']['compatibility_flags'] = []
            if change == 'binding': admin['settings']['bindings'][1]['type'] = 'plain_text'
            with self.subTest(change=change), patch.object(repair, 'domains', return_value=domains), \
                    patch.object(repair, 'worker', side_effect=lambda _s, role: auth if role == 'server' else admin):
                if change == 'none': repair.published(self.settings, before, release)
                else:
                    with self.assertRaises(StackError): repair.published(self.settings, before, release)

    def test_domain_pagination_and_worker_aliases_fail_closed(self):
        with patch.object(repair.deploy, 'cloud_api', return_value=[{}] * 100) as api:
            with self.assertRaises(StackError): repair.domains(self.settings)
            self.assertEqual(api.call_count, 20)
        identifier = '1' * 8 + '-1111-1111-1111-' + '1' * 12
        for enabled, percentage in ((True, 100), (False, 50), (False, 100)):
            responses = [{}, {'enabled': enabled, 'previews_enabled': False},
                         {'deployments': [{'versions': [{'version_id': identifier, 'percentage': percentage}]}]}, {'id': identifier}]
            with patch.object(repair.deploy, 'cloud_api', side_effect=responses):
                if not enabled and percentage == 100: repair.worker(self.settings, 'admin')
                else:
                    with self.assertRaises(StackError): repair.worker(self.settings, 'admin')

    def test_data_witness_detects_values_migrations_and_schema_changes(self):
        db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
        db.executescript("CREATE TABLE user(id INTEGER PRIMARY KEY,secret TEXT); INSERT INTO user VALUES(1,'private'); CREATE TABLE d1_migrations(id INTEGER PRIMARY KEY,name TEXT); INSERT INTO d1_migrations VALUES(1,'old');")
        db.executescript('CREATE TABLE acfx_user(id INTEGER); CREATE TABLE _cf_internal(id INTEGER);')
        def query(_settings, sql, params=None):
            self.assertTrue(sql.startswith(('SELECT ', 'PRAGMA ')))
            return [dict(row) for row in db.execute(sql, params or [])]
        try:
            with patch.object(repair.lifecycle, 'query', side_effect=query):
                before = repair.data_witness(self.settings)
                self.assertNotIn('private', str(before)); self.assertIn('d1_migrations', before['tables'])
                self.assertIn('acfx_user', before['tables']); self.assertNotIn('_cf_internal', before['tables'])
                db.execute("UPDATE user SET secret='changed'")
                self.assertNotEqual(before, repair.data_witness(self.settings))
                db.execute("UPDATE user SET secret='private'")
                self.assertEqual(before, repair.data_witness(self.settings))
                db.execute("UPDATE d1_migrations SET name='new'")
                self.assertNotEqual(before, repair.data_witness(self.settings))
                db.execute("UPDATE d1_migrations SET name='old'")
                db.execute('CREATE INDEX user_secret ON user(secret)')
                self.assertNotEqual(before, repair.data_witness(self.settings))
        finally:
            db.close()

    def test_keys_are_bounded_read_only_and_do_not_return_raw_secrets(self):
        response = Mock(); response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        response.status = 200; response.read.return_value = b'private-key-fixture'
        opener = Mock(); opener.open.return_value = response
        with patch.dict(os.environ, {'CLOUDFLARE_API_TOKEN': 'private-token-fixture'}), patch.object(repair, 'build_opener', return_value=opener):
            witness = repair.key_witness(self.settings)
            self.assertEqual(set(witness), repair.deploy.KEY_NAMES)
            self.assertNotIn('private', str(witness)); self.assertEqual(opener.open.call_count, 3)
            for call in opener.open.call_args_list:
                self.assertEqual(call.args[0].get_method(), 'GET')
            response.read.assert_called_with(65537)
            for value in (b'', b'a' * 65537):
                response.read.return_value = value
                with self.assertRaises(StackError): repair.key_witness(self.settings)
        self.assertIsNone(repair.NoRedirect().redirect_request(None, None, None, None, None, None))

    def flow(self, *, drift=False, publish_error=False):
        release = scratch('naccount-repair-test-'); stages = []
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'SBA_EXECUTE': '1', 'CLOUDFLARE_API_TOKEN': 'fixture'}, clear=True))
            stack.enter_context(patch.object(repair, 'preflight', return_value={'admin': 'old'}))
            data = stack.enter_context(patch.object(repair, 'data_witness', side_effect=[{'schema': 'same'}, {'schema': 'changed' if drift else 'same'}]))
            stack.enter_context(patch.object(repair, 'key_witness', return_value={'keys': 'same'}))
            initialize = stack.enter_context(patch.object(repair, 'Stack'))
            build = stack.enter_context(patch.object(repair.deploy, 'build', return_value=release))
            stack.enter_context(patch.object(repair.deploy, 'checked_release', return_value=(self.settings, {'component': 'admin'})))
            published = stack.enter_context(patch.object(repair, 'published'))
            publish = stack.enter_context(patch.object(repair.deploy, 'publish', side_effect=StackError('publish failed') if publish_error else None))
            forbidden = [stack.enter_context(patch.object(repair.deploy, name)) for name in ['bootstrap_keys', 'wrangler']]
            configure = Mock(return_value=(self.settings, 'existing-secret')); readiness = Mock(return_value=[])
            call = lambda: repair.execute(self.request, self.settings, sba.ROOT, lambda a, b: stages.append((a, b)), configure, readiness)
            if drift or publish_error:
                with self.assertRaises(StackError): call()
                self.assertIn(('admin-publish', True), stages); published.assert_not_called()
            else:
                status, checks, extra = call(); self.assertEqual(status, 'succeeded'); self.assertIsNone(extra)
                self.assertEqual({row['id'] for row in checks}, {'repair-completed', 'data-preserved', 'unchanged-resources-verified', 'service-ready'})
                readiness.assert_called_once_with(self.settings, admin_http=False)
            publish.assert_called_once_with(release, migrate=False); build.assert_called_once_with(sba.ROOT, self.settings, 'admin')
            initialize.return_value.initialize.assert_called_once_with()
            for call in configure.call_args_list: self.assertEqual(call.kwargs, {'read_only': True})
            for operation in forbidden: operation.assert_not_called()
            self.assertNotIn('SERVER_CLIENT_SECRET', os.environ)
            self.assertEqual(data.call_count, 1 if publish_error else 2)

    def test_success_only_builds_and_publishes_admin(self):
        self.flow()

    def test_preservation_failure_after_publish_does_not_claim_success(self):
        self.flow(drift=True)

    def test_publish_failure_is_never_replayed(self):
        self.flow(publish_error=True)

    def test_entry_dispatches_repair_before_ordinary_credentials_and_deploy_chain(self):
        request = {'action': 'repair', 'configuration': self.settings}
        with patch.object(sba, 'validated_request', return_value=request), patch.dict(os.environ, {'SBA_EXECUTE': '1', 'CLOUDFLARE_API_TOKEN': 'fixture', 'ADMIN_BOOTSTRAP_PASSWORD': 'must-not-be-used'}, clear=True), \
                patch.object(sba.repair, 'execute', return_value=('succeeded', [], None)) as execute, \
                patch.object(sba, 'Stack') as stack, patch.object(sba.deploy, 'build') as build:
            self.assertEqual(sba.execute(request), ('succeeded', [], None))
            execute.assert_called_once(); stack.assert_not_called(); build.assert_not_called()
            self.assertNotIn('ADMIN_BOOTSTRAP_PASSWORD', os.environ)

    def test_real_request_requires_newer_version_and_exact_context(self):
        manifest = sba.read_json(sba.ROOT / '.sba/manifest.json')
        request = {**self.request, 'schemaVersion': 3, 'action': 'repair', 'repository': 'aiaimimi0920/NAccount',
                   'sourceSha': 'a' * 40, 'applicationId': manifest['id'], 'applicationVersion': manifest['version'],
                   'environment': 'test', 'configuration': self.settings, 'previous': {'sourceSha': 'b' * 40, 'applicationVersion': '3.0.2'}}
        with patch.object(sba, 'clean'), patch.object(sba, 'git', return_value='a' * 40):
            self.assertEqual(sba.validated_request(request, sba.ROOT), request)
            request['previous']['applicationVersion'] = manifest['version']
            with self.assertRaises(StackError): sba.validated_request(request, sba.ROOT)
