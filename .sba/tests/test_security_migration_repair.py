import copy
import os
from pathlib import Path
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import repair
import security_migration_repair as resume
from stack import StackError, scratch, write_json


class SecurityMigrationRepairTests(unittest.TestCase):
    def setUp(self):
        self.root = scratch('naccount-security-repair-test-')
        self.settings = {'accountId': '1'*32, 'kvId': '2'*32,
                         'database': {'id': 'db-id', 'name': 'db'},
                         'server': {'name': 'auth', 'url': 'https://auth.example.com', 'secretNames': []},
                         'admin': {'name': 'admin', 'url': 'https://admin.example.com'}}
        self.request = {'taskId': 'dc-'+'1'*32,
            'previous': {'applicationVersion': '3.2.0', 'sourceSha': 'a8621252ab167e70f4abae6896cc7458faf17235'},
            'context': {'repairId': 'security-migration', 'parentTaskId': 'dc-'+'2'*32,
                        'parentRunId': 1, 'requestDigest': 'a'*64, 'resultDigest': 'b'*64,
                        'errorCode': 'NACCOUNT_SERVER_PUBLISH_COMMAND_CF_7500'}}
        self.before = {'workers': {'server': 'old-auth', 'admin': 'old-admin'}, 'domains': 'old-domains'}

    def test_context_only_accepts_known_failed_version_and_error(self):
        repair.validate_context(self.request)
        for field, value in [('applicationVersion', '3.1.0'), ('sourceSha', 'f'*40)]:
            request = copy.deepcopy(self.request); request['previous'][field] = value
            with self.assertRaises(StackError): repair.validate_context(request)
        request = copy.deepcopy(self.request); request['context']['errorCode'] = 'NACCOUNT_ADMIN_PUBLISH_FAILED'
        with self.assertRaises(StackError): repair.validate_context(request)

    def test_preflight_refuses_replayed_or_partial_migration_and_resource_drift(self):
        folder = self.root / 'server/migrations/sqlite'; folder.mkdir(parents=True)
        for name in ['0049_naccount_profile.sql', resume.MIGRATION]: (folder/name).write_text('-- fixture', encoding='utf-8')
        for drift in ['none', 'migrated', 'extra', 'phone', 'epoch', 'table', 'db', 'kv', 'portal', 'extra-callback', 'assets']:
            def query(_settings, sql, params=None):
                if sql == 'SELECT name FROM d1_migrations':
                    names = ['0049_naccount_profile.sql']
                    if drift == 'migrated': names.append(resume.MIGRATION)
                    if drift == 'extra': names.append('unknown.sql')
                    return [{'name': name} for name in names]
                if sql == 'PRAGMA table_info(naccount_profile)':
                    return [{'name': name} for name in ['userId','nickname','signature'] + (['phone'] if drift=='phone' else [])]
                if sql == 'PRAGMA table_info(user)': return [{'name': 'securityVersion' if drift=='epoch' else 'id'}]
                if 'sqlite_master' in sql: return [{'name':'naccount_security_request'}] if drift=='table' else []
                if 'FROM app' in sql: return [{'isActive': 0 if drift=='portal' else 1, 'redirectUris':'https://auth.example.com/account' + (',https://other.example.com' if drift=='extra-callback' else '')}]
                raise AssertionError(sql)
            worker={'settings':{'compatibility_date':'2025-01-01','bindings':[
                {'name':'DB','type':'d1','id':'wrong' if drift=='db' else 'db-id'},
                {'name':'KV','type':'kv_namespace','namespace_id':'wrong' if drift=='kv' else '2'*32}]},
                'version':{'resources':{'script_runtime':{'assets':{'base_path':'' if drift=='assets' else '/'}}}}}
            with self.subTest(drift=drift), patch.object(resume.lifecycle,'query',side_effect=query), \
                    patch.object(repair,'worker',return_value=worker), patch.object(repair,'domains',return_value=[]), \
                    patch.object(repair,'bound_domain',return_value=['domain']), patch.object(resume.deploy,'cloud_api',return_value={'name':'db'}):
                if drift=='none': self.assertEqual(set(resume.preflight(self.settings,self.root)),{'workers','domains'})
                else:
                    with self.assertRaises(StackError): resume.preflight(self.settings,self.root)

    def test_execute_builds_then_backs_up_migrates_once_and_preserves_before_publishing(self):
        for failure in ['none','drift','backup','migration','preservation','keys','publish','ready']:
            events=[]; server=self.root/'server-release'; admin=self.root/'admin-release'
            def event(name, result=None):
                def run(*args, **kwargs):
                    events.append(name)
                    if failure==name: raise StackError('fixture failure')
                    return result
                return run
            with self.subTest(failure=failure), ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ,{'SBA_EXECUTE':'1','CLOUDFLARE_API_TOKEN':'fixture'},clear=True))
                stack.enter_context(patch.object(resume,'Stack'))
                stack.enter_context(patch.object(resume,'preflight',side_effect=event('drift',self.before)))
                stack.enter_context(patch.object(resume.deploy,'build',side_effect=lambda _r,_s,c: events.append('build-'+c) or (server if c=='server' else admin)))
                stack.enter_context(patch.object(resume.deploy,'checked_release',side_effect=lambda p:(self.settings,{'component':'server' if p==server else 'admin'})))
                stack.enter_context(patch.object(repair,'key_witness',side_effect=event('keys',{'key':'digest'})))
                stack.enter_context(patch.object(resume.lifecycle,'export_snapshot',side_effect=event('backup',{'witness':{},'createdAt':1})))
                stack.enter_context(patch.object(resume.deploy,'cloud_api',return_value={'bookmark':'fixture'}))
                stack.enter_context(patch.object(resume.deploy,'wrangler',side_effect=event('migration')))
                stack.enter_context(patch.object(resume.lifecycle,'prove_rows',side_effect=event('preservation')))
                stack.enter_context(patch.object(resume.lifecycle,'query',side_effect=lambda _s,sql: [{'name':resume.MIGRATION}] if 'd1_migrations' in sql else [{'name':'naccount_security_apply'}]))
                stack.enter_context(patch.object(resume.deploy,'publish',side_effect=event('publish')))
                stack.enter_context(patch.object(resume,'published',side_effect=event('ready')))
                configure=lambda _s,**kw:(self.settings,'fixture-secret')
                if failure=='none':
                    state,checks,_=resume.execute(self.request,self.settings,self.root,lambda *_:None,configure,lambda *_a,**_k:[])
                    self.assertEqual(state,'succeeded')
                    self.assertEqual(events.count('migration'),1); self.assertEqual(events.count('publish'),2)
                    self.assertLess(events.index('build-admin'),events.index('backup'))
                    self.assertLess(events.index('backup'),events.index('migration'))
                    self.assertLess(events.index('preservation'),events.index('publish'))
                    self.assertIn('unchanged-resources-verified',[c['id'] for c in checks])
                else:
                    with self.assertRaises(StackError): resume.execute(self.request,self.settings,self.root,lambda *_:None,configure,lambda *_a,**_k:[])
                    self.assertLessEqual(events.count('migration'),1)
                    if failure in ['drift','backup','migration','preservation','keys']: self.assertNotIn('publish',events)
                self.assertNotIn('SERVER_CLIENT_SECRET',os.environ)

    def test_d1_trigger_does_not_contain_inner_end_statement(self):
        path = Path(__file__).resolve().parents[2] / 'melody-auth/server/migrations/sqlite' / resume.MIGRATION
        if not path.is_file(): self.skipTest('Source checkout is validated separately from catalog CI')
        sql=path.read_text(encoding='utf-8')
        self.assertEqual(sql.count('END;'),1)
        self.assertEqual(sql.count('SELECT RAISE(ABORT,'),4)

    def test_published_rejects_incorrect_vars_assets_bindings_and_domains(self):
        releases={'server':self.root/'server-release','admin':self.root/'admin-release'}
        for role, release in releases.items():
            folder='server' if role=='server' else 'admin-panel'
            write_json(release/'source'/folder/'wrangler.json',{'compatibility_date':'2025-01-01','compatibility_flags':[], 'vars':{'LABEL':'test','ENABLED':True}, 'assets': {'directory': 'static', **({'binding': 'ASSETS'} if role == 'admin' else {})}})
        before={'workers':{'server':'old','admin':'old'},'domains':repair.digest({'server':['domain'],'admin':['domain']})}
        for drift in ['none','text','json','assets','asset-binding','db','kv','secret','domain','date']:
            def worker(_settings,role):
                bindings=[{'name':'LABEL','type':'plain_text','text':'bad' if drift=='text' else 'test'},
                          {'name':'ENABLED','type':'json','json':drift!='json'},
                          {'name':'DB','type':'d1','database_id':'bad' if drift=='db' else 'db-id'},
                          {'name':'KV','type':'kv_namespace','namespace_id':'bad' if drift=='kv' else '2'*32},
                          {'name':'SERVER_CLIENT_SECRET','type':'plain_text' if drift=='secret' else 'secret_text'}]
                if role == 'admin' and drift != 'asset-binding': bindings.append({'name':'ASSETS','type':'assets'})
                return {'settings':{'compatibility_date':'' if drift=='date' else '2025-01-01','bindings':bindings},
                        'version':{'resources':{'script_runtime':{'assets':{'base_path':'' if drift=='assets' else '/'}}}}}
            with self.subTest(drift=drift), patch.object(repair,'domains',return_value=[]), \
                    patch.object(repair,'bound_domain',return_value=['bad' if drift=='domain' else 'domain']), \
                    patch.object(repair,'worker',side_effect=worker):
                if drift=='none': resume.published(self.settings,releases,before)
                else:
                    with self.assertRaises(StackError): resume.published(self.settings,releases,before)


if __name__ == '__main__': unittest.main()
