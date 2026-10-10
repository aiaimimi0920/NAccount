import copy
import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import readiness_repair as verify
import repair
from stack import StackError, scratch, write_json


class ReadinessRepairTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch('naccount-readonly-test-')
        write_json(self.root / 'customizations/current.json', {'generation': verify.GENERATION})
        self.request = {'taskId': 'dc-' + '1'*32,
            'previous': {'applicationVersion': '3.2.1', 'sourceSha': 'ee09fb42efddcf1f96d1a84206ceeec578546c07'},
            'context': {'repairId': 'readiness-only', 'parentTaskId': 'dc-9595995db7764b0e88462de04d63b56d',
                'parentRunId': 38021757950, 'requestDigest': 'a'*64, 'resultDigest': 'b'*64,
                'errorCode': 'NACCOUNT_READINESS_FAILED'}}

    def test_exact_parent_and_version_required(self):
        repair.validate_context(self.request)
        for section, key, value in [('previous','applicationVersion','3.2.0'),
                ('previous','sourceSha','f'*40), ('context','parentTaskId','dc-'+'2'*32),
                ('context','parentRunId',1), ('context','errorCode','NACCOUNT_ADMIN_PUBLISH_FAILED')]:
            request = copy.deepcopy(self.request); request[section][key] = value
            with self.subTest(key=key), self.assertRaises(StackError): repair.validate_context(request)

    def test_version_drift_refused(self):
        for drift in [False, True]:
            def worker(_settings, role):
                return {'version': {'id': 'wrong' if drift else verify.VERSIONS[role]}}
            with patch.object(repair, 'worker', side_effect=worker), patch.object(repair, 'domains', return_value=[]), \
                    patch.object(repair, 'bound_domain', return_value=['domain']):
                if drift:
                    with self.assertRaises(StackError): verify.deployment_witness({})
                else: self.assertEqual(set(verify.deployment_witness({})), {'workers','domains'})

    def test_schema_requires_all_migrations_and_security_objects(self):
        folder = self.root / 'server/migrations/sqlite'; folder.mkdir(parents=True)
        (folder / verify.migration.MIGRATION).write_text('--fixture', encoding='utf-8')
        for drift in ['none','migration','column','objects']:
            def query(_settings, sql, params=None):
                if 'd1_migrations' in sql: return [] if drift == 'migration' else [{'name':verify.migration.MIGRATION}]
                if 'PRAGMA' in sql: return [] if drift == 'column' else [{'name':'securityVersion'}]
                return [] if drift == 'objects' else [{'name':name} for name in params]
            with self.subTest(drift=drift), patch.object(verify.lifecycle, 'query', side_effect=query):
                if drift == 'none': verify.schema_ready({}, self.root)
                else:
                    with self.assertRaises(StackError): verify.schema_ready({}, self.root)

    def test_readonly_execution_and_drift_rejection(self):
        for failure in ['none','data','keys','deployment','configuration','readiness','generation']:
            with self.subTest(failure=failure), ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {'SBA_EXECUTE':'1','CLOUDFLARE_API_TOKEN':'fixture'}, clear=True))
                stack.enter_context(patch.object(verify, 'Stack'))
                stack.enter_context(patch.object(verify, 'schema_ready'))
                stack.enter_context(patch.object(verify.portal, 'configure'))
                if failure == 'generation': stack.enter_context(patch.object(verify, 'read_json', return_value={'generation':'wrong'}))
                for module, method, label in [(repair,'data_witness','data'), (repair,'key_witness','keys'), (verify,'deployment_witness','deployment')]:
                    stack.enter_context(patch.object(module, method, side_effect=[{'same':1}, {'same':2 if failure==label else 1}]))
                for name in ['build','publish','wrangler','bootstrap_keys']:
                    stack.enter_context(patch.object(verify.deploy, name, side_effect=AssertionError('cloud write forbidden')))
                stack.enter_context(patch.object(verify.deploy, 'server_config', return_value={}))
                stack.enter_context(patch.object(verify.deploy, 'admin_config', return_value={}))
                published = stack.enter_context(patch.object(verify.migration, 'published'))
                from unittest.mock import Mock
                configure = Mock(side_effect=[({},'secret'), ({},'changed' if failure=='configuration' else 'secret')])
                readiness = Mock(side_effect=StackError('fixture') if failure=='readiness' else None, return_value=[])
                stages=[]
                call=lambda: verify.execute(self.request, {}, self.root, lambda s,w: stages.append((s,w)), configure, readiness)
                if failure == 'none':
                    state, checks, _ = call()
                    self.assertEqual(state,'succeeded')
                    self.assertIn('read-only-verification',[c['id'] for c in checks])
                    self.assertEqual(published.call_args.kwargs, {'changed':False})
                    self.assertTrue(all(c.kwargs == {'read_only':True} for c in configure.call_args_list))
                else:
                    with self.assertRaises(StackError): call()
                self.assertTrue(all(w is False for _,w in stages))


if __name__ == '__main__': unittest.main()
