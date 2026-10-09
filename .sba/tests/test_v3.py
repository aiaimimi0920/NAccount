"""非空 SQLite 快照、隔离代码和精确清理的无云写入回归。"""
import copy
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lifecycle as life
import springbok as sba
from stack import scratch, StackError, write_json, run


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = scratch('naccount-v3-test-')
        self.environment = 'test-123456789abc'
        self.settings = {'accountId': '1'*32, 'database': {'id': '11111111-2222-3333-4444-555555555555', 'name': self.environment+'-db'}, 'kvId': '2'*32,
            'server': {'name': self.environment+'-auth', 'url': 'https://'+self.environment+'-auth.demo.workers.dev', 'secretNames': []},
            'admin': {'name': self.environment+'-admin', 'url': 'https://'+self.environment+'-admin.demo.workers.dev', 'spaClientId': '', 's2sClientId': ''}, 'vars': {'SUPPORTED_LOCALES': ['en', 'zh']}}
        self.request = {'schemaVersion': 3, 'taskId': 'dc-'+'3'*32, 'action': 'destroy-preview', 'repository': 'aiaimimi0920/NAccount', 'sourceSha': 'a'*40,
            'applicationId': 'naccount-cloudflare', 'applicationVersion': json.loads((sba.ROOT / '.sba/manifest.json').read_text(encoding='utf-8'))['version'], 'environment': self.environment, 'configuration': self.settings,
            'previous': {'sourceSha': 'a'*40, 'applicationVersion': json.loads((sba.ROOT / '.sba/manifest.json').read_text(encoding='utf-8'))['version']}, 'context': {'instanceId': 'dc-'+'4'*32, 'previewTaskId': 'dc-'+'4'*32, 'resultDigest': 'b'*64,
            'resources': [{'key': key, 'kind': kind, 'accountId': account, 'remoteId': remote, 'name': key} for key, kind, account, remote in sorted(life.inventory(self.settings))]}}

    def test_v3_request_binds_exact_test_inventory_and_rejects_production_cleanup(self):
        with patch.object(sba, 'clean'), patch.object(sba, 'git', return_value='a'*40):
            self.assertEqual(sba.validated_request(self.request, sba.ROOT), self.request)
            for mutation in ('id', 'environment', 'sha', 'extra'):
                value = copy.deepcopy(self.request)
                if mutation == 'id': value['context']['resources'][0]['remoteId'] = 'f'*32
                if mutation == 'environment': value['environment'] = 'production'
                if mutation == 'sha': value['previous']['sourceSha'] = 'b'*40
                if mutation == 'extra': value['context']['source'] = self.settings
                with self.assertRaises(StackError): sba.validated_request(value, sba.ROOT)

    def test_real_nonempty_snapshot_proves_values_not_just_counts(self):
        path = self.directory/'source.sql'
        path.write_text("CREATE TABLE user(id INTEGER PRIMARY KEY,email TEXT);INSERT INTO user VALUES(1,'first@example.invalid'),(2,'second@example.invalid');", encoding='utf-8')
        witness = life.snapshot_witness(path)
        db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row; db.executescript(path.read_text())
        def query(_settings, sql, params=None): return [dict(row) for row in db.execute(sql, params or [])]
        try:
            with patch.object(life, 'query', side_effect=query):
                life.prove_rows(self.settings, witness)
                db.execute('ALTER TABLE user ADD COLUMN active INTEGER DEFAULT 1')
                db.execute("INSERT INTO user VALUES(3,'new@example.invalid',1)")
                life.prove_rows(self.settings, witness)
                db.execute("UPDATE user SET email='changed@example.invalid' WHERE id=1")
                with self.assertRaisesRegex(StackError, 'changed or lost'): life.prove_rows(self.settings, witness)
        finally: db.close()

    def test_snapshot_refuses_attach(self):
        path=self.directory/'unsafe.sql';path.write_text("ATTACH DATABASE 'outside.db' AS bad;", encoding='utf-8')
        with self.assertRaises(sqlite3.DatabaseError): life.snapshot_witness(path)

    def test_export_polls_downloads_same_bytes_without_forwarding_credentials(self):
        payload=b'CREATE TABLE user(id INTEGER);INSERT INTO user VALUES(7);'
        calls=[]
        def download(request, timeout):
            calls.append(request);self.assertEqual(dict(request.header_items()), {});return io.BytesIO(payload)
        with patch.object(life.deploy, 'cloud_api', side_effect=[{'status':'active','at_bookmark':'opaque'}, {'status':'complete','result':{'signed_url':'https://export.r2.cloudflarestorage.com/file?signature=private'}}]) as api, \
                patch.object(life, 'urlopen', side_effect=download), patch.object(life.time, 'sleep'):
            result=life.export_snapshot(self.settings,self.directory)
        self.assertEqual(result['path'].read_bytes(),payload)
        self.assertEqual(len(result['witness']['user']['rows']),1)
        self.assertEqual(api.call_args_list[1].kwargs['payload']['current_bookmark'],'opaque')

    def test_workers_dev_config_preserves_required_flags_and_removes_unsafe_channels(self):
        path=self.directory/'config.json';write_json(path,self.settings)
        self.assertEqual(sba.deploy.config(path,'server')['server']['url'],self.settings['server']['url'])
        base={'main':'src/index.tsx','compatibility_flags':['nodejs_compat'],'send_email':[{}],'services':[{}],'queues':{},'triggers':{},'unsafe':{}}
        result=sba.deploy.runtime_config(base,{**self.settings,'_sbaPreview':True},'server')
        self.assertTrue(result['workers_dev']);self.assertEqual(result['routes'],[])
        self.assertEqual(result['compatibility_flags'],['global_fetch_strictly_public','nodejs_compat'])
        self.assertFalse(set(result)&{'send_email','services','queues','triggers','unsafe'})

    def test_actual_javascript_guard_blocks_egress_and_external_redirects(self):
        (self.directory/'naccount-preview-guard.mjs').write_text(life.preview_guard(self.settings,'server'),encoding='utf-8')
        (self.directory/'main.mjs').write_text("export default {fetch:async()=>new Response(null,{status:302,headers:{location:'https://production.example.invalid'}})};",encoding='utf-8')
        (self.directory/'entry.mjs').write_text(life.preview_entry('main.mjs',self.settings,'server'),encoding='utf-8')
        script="import assert from 'node:assert/strict';import app from './entry.mjs';assert.throws(()=>fetch('https://outside.example.invalid'),/EGRESS_BLOCKED/);const response=await app.fetch(new Request('https://test.example.invalid'),{},{});assert.equal(response.status,409);"
        (self.directory/'check.mjs').write_text(script,encoding='utf-8')
        run(['node','check.mjs'],self.directory)

    def test_cleanup_validates_all_ownership_before_delete_and_never_replays(self):
        calls=[];deleted=set()
        def api(settings,path,method='GET',payload=None):
            calls.append((method,path))
            if method=='DELETE':deleted.add(path);return None
            if path=='/workers/domains':return []
            if path.removesuffix('/settings') in deleted:raise StackError('missing') from HTTPError('https://api.cloudflare.com',404,'',{},None)
            if path.startswith('/d1/database/'):return {'name':self.settings['database']['name']}
            if path.startswith('/storage/kv/'):return {'title':self.environment+'-session'}
            if path.endswith('-auth/settings'):return {'bindings':[{'name':'DB','id':self.settings['database']['id']},{'name':'KV','namespace_id':self.settings['kvId']}]}
            return {'bindings':[]}
        with patch.object(life.deploy,'cloud_api',side_effect=api):
            result=life.destroy_preview(self.request,lambda *_:None)
        self.assertEqual(len(deleted),4)
        self.assertTrue(all(row['status'] in ('removed','absent') for row in result['resources']))
        self.assertEqual(len([c for c in calls if c[0]=='DELETE']),4)
        with patch.object(life.deploy,'cloud_api',return_value={'name':'somebody-elses-db'}) as bad:
            with self.assertRaises(StackError):life.destroy_preview(self.request,lambda *_:None)
            self.assertTrue(all(c.kwargs.get('method','GET')=='GET' for c in bad.call_args_list))

    def test_partial_cleanup_failure_is_unknown_in_result_not_success(self):
        path,result=self.directory/'request.json',self.directory/'result.json';write_json(path,self.request)
        def failure(_request,_stage):raise StackError('private-error')
        with patch.object(sys,'argv',['springbok.py','--request',str(path),'--result',str(result)]), \
                patch.dict(os.environ,{'SBA_EXECUTE':'1','CLOUDFLARE_API_TOKEN':'fixture'}), \
                patch.object(sba,'validated_request',return_value=self.request), patch.object(life,'destroy_preview',side_effect=lambda r,stage:(stage('cleanup',True),failure(r,stage))):
            self.assertEqual(sba.main(),1)
        value=json.loads(result.read_text());self.assertEqual(value['status'],'unknown');self.assertEqual(value['errorCode'],'NACCOUNT_CLEANUP_FAILED');self.assertNotIn('private-error',result.read_text())

    def test_preview_real_sqlite_copy_migration_isolation_before_publish_and_source_unchanged(self):
        source=copy.deepcopy(self.settings);source['database']={'name':'source-db','id':'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'};source['kvId']='8'*32
        source['server'].update(name='source-auth',url='https://source-auth.example.com');source['admin'].update(name='source-admin',url='https://source-admin.example.com')
        request=copy.deepcopy(self.request);request['action']='preview';request['previous']={'sourceSha':'b'*40,'applicationVersion':'2.0.0'}
        request['context']={'resources':request['context']['resources'],'urls':[self.settings['server']['url'],self.settings['admin']['url']],
            'source':{'instanceId':'dc-'+'4'*32,'taskId':'dc-'+'4'*32,'sourceSha':'b'*40,'applicationVersion':'2.0.0','environment':'source','configuration':source,'resultDigest':'b'*64,
            'resources':[{'key':k,'kind':t,'accountId':a,'remoteId':i,'name':k} for k,t,a,i in sorted(life.inventory(source))]}}
        source_db=sqlite3.connect(':memory:');target_db=sqlite3.connect(':memory:')
        for db in (source_db,target_db):db.row_factory=sqlite3.Row
        source_db.executescript("""CREATE TABLE user(id INTEGER PRIMARY KEY,email TEXT);INSERT INTO user VALUES(1,'retained@example.invalid');
        CREATE TABLE app(id INTEGER PRIMARY KEY,name TEXT,type TEXT,isActive INTEGER,deletedAt TEXT,clientId TEXT,secret TEXT,redirectUris TEXT);
        INSERT INTO app VALUES(1,'Admin Panel (SPA)','spa',1,NULL,'spa-id','','https://source-admin.example.com/en/dashboard');
        INSERT INTO app VALUES(2,'Admin Panel (S2S)','s2s',1,NULL,'s2s-id','source-secret','');
        INSERT INTO app VALUES(3,'External','spa',1,NULL,'external-id','','https://production.example.invalid');
        CREATE TABLE saml_idp(id INTEGER PRIMARY KEY,isActive INTEGER);INSERT INTO saml_idp VALUES(1,1);""")
        original='\n'.join(source_db.iterdump());path=self.directory/'original.sql';path.write_text(original,encoding='utf-8')
        snapshot={'path':path,'id':'f'*64,'createdAt':1,'witness':life.snapshot_witness(path)};published=[]
        def api(settings,suffix,method='GET',payload=None):
            if suffix.endswith('/settings'):raise StackError('missing') from HTTPError('https://api.cloudflare.com',404,'',{},None)
            if suffix=='/workers/domains':return []
            if '/keys?' in suffix:return []
            db=source_db if settings['database']['id']==source['database']['id'] else target_db
            return [{'success':True,'results':[dict(row) for row in db.execute(payload['sql'],payload['params'])]}]
        def wrangler(_source,_role,args,*_args,**_kwargs):
            if args[1]=='execute':target_db.executescript(path.read_text())
            elif args[1]=='migrations':
                target_db.executescript("""ALTER TABLE user ADD COLUMN migrated INTEGER DEFAULT 1;
                INSERT INTO app VALUES(4,'NAccount User Portal (SPA)','spa',1,NULL,'naccount-user-portal','','');
                CREATE TABLE scope(id INTEGER PRIMARY KEY,name TEXT,type TEXT,deletedAt TEXT);
                INSERT INTO scope VALUES(1,'openid','spa',NULL),(2,'profile','spa',NULL),(3,'offline_access','spa',NULL);
                CREATE TABLE app_scope(appId INTEGER,scopeId INTEGER,deletedAt TEXT);
                INSERT INTO app_scope VALUES(4,1,NULL),(4,2,NULL),(4,3,NULL);""")
            else:raise AssertionError(args)
        def publish(_release,**_):
            self.assertEqual(target_db.execute('SELECT isActive FROM app WHERE id=3').fetchone()[0],0)
            self.assertNotEqual(target_db.execute('SELECT secret FROM app WHERE id=2').fetchone()[0],'source-secret')
            published.append(str(_release))
        try:
            with patch.object(sba,'clean'),patch.object(sba,'git',return_value='a'*40),patch.object(sba,'Stack'), \
                    patch.dict(os.environ,{'SBA_EXECUTE':'1','CLOUDFLARE_API_TOKEN':'test-only'}), \
                    patch.object(sba.deploy,'build',side_effect=[self.directory/'server',self.directory/'admin']), \
                    patch.object(sba.deploy,'cloud_api',side_effect=api),patch.object(sba.deploy,'wrangler',side_effect=wrangler), \
                    patch.object(sba.deploy,'bootstrap_keys',return_value={'state':'initialized'}),patch.object(sba.deploy,'publish',side_effect=publish), \
                    patch.object(life,'export_snapshot',return_value=snapshot),patch.object(life,'isolation_checks'),patch.object(sba,'readiness',return_value=[]):
                status,checks,result=sba.execute(request)
            self.assertEqual(status,'deployed-unverified');self.assertEqual(len(published),2)
            self.assertEqual('\n'.join(source_db.iterdump()),original)
            self.assertEqual(target_db.execute('SELECT email FROM user').fetchone()[0],'retained@example.invalid')
            self.assertEqual({c['id'] for c in checks},{'snapshot-copied','migration-verified','source-unchanged','side-effects-isolated'})
            self.assertEqual(result['snapshot']['id'],'f'*64)
            self.assertEqual(target_db.execute('SELECT redirectUris,isActive FROM app WHERE id=4').fetchone()[:], (self.settings['server']['url']+'/account',1))
        finally:source_db.close();target_db.close()

    def test_preview_settings_remove_external_login_and_embedded_origins(self):
        settings=copy.deepcopy(self.settings);settings['vars'].update(DISCORD_AUTH_CLIENT_ID='live',OIDC_AUTH_PROVIDERS=['live'],EMBEDDED_AUTH_ORIGINS=['https://production.example.invalid'])
        isolated=life.isolated_settings(settings)
        self.assertEqual(isolated['vars']['DISCORD_AUTH_CLIENT_ID'],'')
        self.assertEqual(isolated['vars']['OIDC_AUTH_PROVIDERS'],[])
        self.assertEqual(isolated['vars']['EMBEDDED_AUTH_ORIGINS'],[])
        self.assertEqual(settings['vars']['DISCORD_AUTH_CLIENT_ID'],'live')
        settings['server']['secretNames']=['GITHUB_AUTH_CLIENT_SECRET']
        self.assertEqual(life.isolated_settings(settings)['server']['secretNames'],[])

    def test_live_isolation_probe_rejects_wrong_origin_allowlist(self):
        bad={'kind':'naccount-preview-v3','egressBlocked':True,'allowedOrigins':['https://production.example.invalid']}
        with patch.object(life,'urlopen',return_value=io.BytesIO(json.dumps(bad).encode())):
            with self.assertRaises(StackError):life.isolation_checks(self.settings)

    def test_existing_worker_or_domain_blocks_new_deployment_without_writes(self):
        with patch.object(life.deploy,'cloud_api',return_value={'bindings':[]}) as api:
            with self.assertRaisesRegex(StackError,'Worker already exists'):life.require_unused_workers(self.settings)
            self.assertEqual(api.call_count,1)
        with patch.object(life,'maybe_get',return_value=None), patch.object(life.deploy,'cloud_api',return_value=[{'hostname':urlparse(self.settings['admin']['url']).hostname}]) as api:
            with self.assertRaisesRegex(StackError,'domain already exists'):life.require_unused_workers(self.settings)
            self.assertTrue(all(call.kwargs.get('method','GET')=='GET' for call in api.call_args_list))
