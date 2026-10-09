"""NAccount 应用自有部署流程；SpringBok 仅调用和消费结果。"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

import cloudflare as deploy
import lifecycle
import admin_bootstrap
import repair
from diagnostics import result_error
from stack import ROOT, Stack, StackError, atomic_json, clean, git, read_json, scratch, write_json

ERROR_CODES = {stage: f'NACCOUNT_{stage.upper().replace("-", "_")}_FAILED' for stage in (
    'request', 'configuration', 'credentials', 'upstream', 'server-build', 'keys',
    'server-publish', 'admin-config', 'admin-build', 'admin-publish', 'readiness',
    'snapshot', 'copy', 'preservation', 'isolation', 'cleanup', 'admin-bootstrap')}


def validated_request(value: dict, root: Path) -> dict:
    manifest = read_json(root / '.sba/manifest.json')
    fields = {'schemaVersion', 'taskId', 'action', 'repository', 'sourceSha', 'applicationId',
              'applicationVersion', 'environment', 'configuration', 'previous'}
    if value.get('action') in ('preview', 'destroy-preview', 'repair'):
        fields.add('context')
    if set(value) != fields or value.get('schemaVersion') != 3:
        raise StackError('Invalid SBA request')
    if value['action'] not in ('deploy', 'update', 'verify', 'preview', 'destroy-preview', 'repair'):
        raise StackError('Unsupported SBA action')
    if value['repository'] != 'aiaimimi0920/NAccount':
        raise StackError('Unexpected repository')
    if (value['applicationId'] != manifest['id'] or value['applicationVersion'] != manifest['version']
            or not re.fullmatch(r'[a-f0-9]{40}', str(value['sourceSha']))):
        raise StackError('Application or source identity mismatch')
    for key in ('taskId', 'environment'):
        if not re.fullmatch(r'[a-z][a-z0-9-]{1,62}', str(value[key])):
            raise StackError('Invalid execution identity')
    clean(root)
    if git(root, 'rev-parse', 'HEAD') != value['sourceSha']:
        raise StackError('Checkout does not match requested GitHub commit')
    def version(text):
        if not isinstance(text, str) or not re.fullmatch(r'(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})\.(0|[1-9]\d{0,8})', text):
            raise StackError('Stable version required')
        return tuple(map(int, text.split('.')))
    current = version(value['applicationVersion'])
    previous = value['previous']
    if value['action'] == 'deploy':
        if previous is not None:
            raise StackError('Deploy requires an empty previous release')
    else:
        if not isinstance(previous, dict) or set(previous) != {'sourceSha', 'applicationVersion'}:
            raise StackError('Previous release required')
        if not re.fullmatch(r'[a-f0-9]{40}', str(previous['sourceSha'])):
            raise StackError('Invalid previous source')
        old = version(previous['applicationVersion'])
        if value['action'] in ('update', 'preview', 'repair') and (current <= old or value['sourceSha'] == previous['sourceSha']):
            raise StackError('Update requires a newer version')
        if value['action'] in ('verify', 'destroy-preview') and (current != old or value['sourceSha'] != previous['sourceSha']):
            raise StackError('Verify must target the deployed release')
    public_settings(value['configuration'], manifest)
    if value['action'] == 'repair':
        repair.validate_context(value)
    if value['action'] in ('preview', 'destroy-preview'):
        lifecycle.validate_context(value)
        if value['action'] == 'preview':
            public_settings(value['context']['source']['configuration'], manifest)
    return copy.deepcopy(value)


def public_settings(settings, manifest):
    if not isinstance(settings, dict):
        raise StackError('Public configuration required')
    if set(settings) != {'accountId', 'database', 'kvId', 'server', 'admin', 'vars'}:
        raise StackError('Unexpected public configuration fields')
    for key, allowed in [('database', {'name', 'id'}), ('server', {'name', 'url', 'secretNames'}),
                         ('admin', {'name', 'url', 'spaClientId', 's2sClientId'})]:
        if key == 'admin' and isinstance(settings[key], dict) and 'bootstrapEmail' in settings[key]:
            allowed = allowed | {'bootstrapEmail'}
            if not isinstance(settings[key]['bootstrapEmail'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9._%+\-]{0,63}@gmail\.com', settings[key]['bootstrapEmail']):
                raise StackError('Invalid administrator email')
        if not isinstance(settings[key], dict) or set(settings[key]) != allowed:
            raise StackError('Unexpected public configuration fields')
    if not isinstance(settings['server']['secretNames'], list) or any(
            name not in manifest['secrets'] or name == 'ADMIN_BOOTSTRAP_PASSWORD' for name in settings['server']['secretNames']):
        raise StackError('Undeclared runtime secret')


def database_query(settings: dict, sql: str, params: list) -> list:
    response = deploy.cloud_api(settings, f"/d1/database/{settings['database']['id']}/query",
                                method='POST', payload={'sql': sql, 'params': params})
    if not isinstance(response, list) or len(response) != 1 or response[0].get('success') is not True:
        raise StackError('D1 query failed')
    return response[0]['results']


def configure_admin(settings: dict, *, read_only: bool = False) -> tuple[dict, str]:
    rows = database_query(settings, 'SELECT id,name,type,clientId,secret,redirectUris,isActive FROM app '
                          'WHERE deletedAt IS NULL AND name IN (?,?)', ['Admin Panel (SPA)', 'Admin Panel (S2S)'])
    spa = [row for row in rows if row['name'] == 'Admin Panel (SPA)' and row['type'] == 'spa']
    s2s = [row for row in rows if row['name'] == 'Admin Panel (S2S)' and row['type'] == 's2s']
    if len(rows) != 2 or len(spa) != 1 or len(s2s) != 1 or not s2s[0].get('secret'):
        raise StackError('Unique real admin clients required; no guessed IDs')
    if read_only and any(row.get('isActive') != 1 or not isinstance(row.get('clientId'), str)
                         or not row['clientId'] for row in rows):
        raise StackError('Active existing admin clients required for repair')
    result = copy.deepcopy(settings)
    for field, row in [('spaClientId', spa[0]), ('s2sClientId', s2s[0])]:
        if result['admin'].get(field) and result['admin'][field] != row['clientId']:
            raise StackError('Configured admin client differs from actual database')
        result['admin'][field] = row['clientId']
    old = spa[0]['redirectUris']
    callbacks = [uri for uri in old.split(',') if uri]
    for locale in settings.get('vars', {}).get('SUPPORTED_LOCALES', ['en', 'fr']):
        if not isinstance(locale, str) or not re.fullmatch(r'[a-z]{2}(?:-[A-Za-z]{2,4})?', locale):
            raise StackError('Invalid callback locale')
        uri = f"{settings['admin']['url']}/{locale}/dashboard"
        if uri not in callbacks:
            callbacks.append(uri)
    new = ','.join(callbacks)
    if old != new:
        if read_only:
            raise StackError('Existing admin callbacks required for repair; no database writes attempted')
        database_query(settings, 'UPDATE app SET redirectUris=? WHERE id=? AND redirectUris=? AND deletedAt IS NULL',
                       [new, spa[0]['id'], old])
        check = database_query(settings, 'SELECT redirectUris FROM app WHERE id=? AND deletedAt IS NULL', [spa[0]['id']])
        if len(check) != 1 or check[0]['redirectUris'] != new:
            raise StackError('Admin callback update uncertain')
    return result, s2s[0]['secret']


def readiness(settings: dict, *, admin_http: bool = True) -> list[dict]:
    checks = []
    # 使用真实的应用探针标识，避免默认 Python-urllib 被边缘规则拒绝；不携带凭据。
    headers = {'User-Agent': 'NAccount-SBA/2.0'}
    for suffix, key in [('/.well-known/openid-configuration', 'issuer'), ('/.well-known/jwks.json', 'keys')]:
        with urlopen(Request(settings['server']['url'] + suffix, headers=headers), timeout=30) as response:
            payload = json.load(response)
        if key == 'issuer' and payload.get(key) != settings['server']['url']:
            raise StackError('OIDC issuer mismatch')
        if key == 'keys' and not payload.get(key):
            raise StackError('JWKS empty')
        checks.append({'id': 'oidc-discovery' if key == 'issuer' else 'jwks-ready', 'passed': True})
    if admin_http:
        with urlopen(Request(settings['admin']['url'], headers=headers), timeout=30) as response:
            if response.status != 200:
                raise StackError('Admin page not ready')
        checks.append({'id': 'admin-http-ready', 'passed': True})
    return checks


def execute(value: dict, root: Path = ROOT, *, on_stage=lambda _stage, _writes: None) -> tuple[str, list, dict | None]:
    bootstrap_password = os.environ.pop('ADMIN_BOOTSTRAP_PASSWORD', None)
    on_stage('request', False)
    request = validated_request(value, root)
    on_stage('configuration', False)
    staging = scratch('naccount-sba-')
    config_path = staging / 'deployment.json'
    write_json(config_path, request['configuration'])
    settings = deploy.config(config_path, 'server')
    if request['action'] == 'verify':
        on_stage('readiness', False)
        return 'succeeded', readiness(settings), None
    bootstrap = request['action'] == 'deploy' and bool(settings['admin'].get('bootstrapEmail'))
    if bootstrap:
        admin_bootstrap.validate(settings['admin']['bootstrapEmail'], bootstrap_password)
    else:
        bootstrap_password = None
    on_stage('credentials', False)
    if os.environ.get('SBA_EXECUTE') != '1':
        raise StackError('Explicit SBA_EXECUTE=1 required')
    if request['action'] == 'repair':
        return repair.execute(request, settings, root, on_stage, configure_admin, readiness)
    if any(not os.environ.get(name) for name in ['CLOUDFLARE_API_TOKEN', *settings['server'].get('secretNames', [])]):
        raise StackError('Missing deployment credentials; no cloud writes attempted')
    if request['action'] == 'destroy-preview':
        return 'succeeded', [{'id': 'owned-resources-removed', 'passed': True}], lifecycle.destroy_preview(request, on_stage)
    preview = request['action'] == 'preview'
    if preview:
        settings = lifecycle.isolated_settings(settings)
    # 重建锁定版本；不拉浮动上游，不触碰开发者原始 checkout。
    on_stage('upstream', False)
    Stack(root).initialize()
    on_stage('server-build', False)
    server = deploy.build(root, settings, 'server')
    generated = admin_bootstrap.material(server, bootstrap_password) if bootstrap else None
    bootstrap_password = None
    if request['action'] in ('deploy', 'preview'):
        on_stage('configuration', False)
        lifecycle.require_unused_workers(settings)
    snapshot = None
    if request['action'] in ('update', 'preview'):
        on_stage('snapshot', False)
        source = request['context']['source']['configuration'] if preview else settings
        write_json(staging / 'snapshot-source.json', source)
        source = deploy.config(staging / 'snapshot-source.json', 'server')
        snapshot = lifecycle.export_snapshot(source, staging)
        if not preview:
            recovery = deploy.cloud_api(settings, f"/d1/database/{settings['database']['id']}/time_travel/bookmark")
            lifecycle.require(isinstance(recovery.get('bookmark'), str) and 0 < len(recovery['bookmark']) <= 256)
            # 恢复点不含凭据或业务内容，写入 GitHub runner 日志，SQL 仅留私有临时目录。
            print('NACCOUNT_D1_RECOVERY_POINT ' + json.dumps({'databaseId': settings['database']['id'], 'bookmark': recovery['bookmark'], 'createdAt': snapshot['createdAt'], 'minimumWindowDays': 7}))
        else:
            lifecycle.require(not lifecycle.query(settings, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%'"), 'Preview database must be empty')
            on_stage('copy', True)
            deploy.wrangler(server / 'source', 'server', ['d1', 'execute', 'DB', '--remote', '--file', str(snapshot['path'])], settings, cloud=True)
            lifecycle.prove_rows(settings, snapshot['witness'])
    if request['action'] in ('deploy', 'preview'):
        on_stage('keys', True)
        if preview:
            lifecycle.require(deploy.cloud_api(settings, f"/storage/kv/namespaces/{settings['kvId']}/keys?limit=1") == [], 'Preview KV must be empty')
        initialized = deploy.bootstrap_keys(server)
        if preview:
            lifecycle.require(initialized.get('state') == 'initialized', 'Preview must have newly generated keys')
    # 迁移、备份和幂等均属于应用；平台只知道 update/deploy 动作。
    on_stage('server-publish', True)
    deploy.wrangler(server / 'source', 'server', ['d1', 'migrations', 'apply', 'DB', '--remote'], settings, cloud=True)
    checks = []
    if snapshot:
        on_stage('preservation', True)
        lifecycle.prove_rows(settings, snapshot['witness'])
        checks.extend({'id': name, 'passed': True} for name in (('snapshot-copied', 'migration-verified') if preview else ('backup-created', 'data-preserved')))
    if preview:
        on_stage('isolation', True)
        lifecycle.isolate_apps(settings)
    if bootstrap:
        on_stage('admin-bootstrap', True)
        checks.append(admin_bootstrap.initialize(settings, generated, database_query))
        generated = None
    deploy.publish(server, migrate=False)
    on_stage('admin-config', True)
    settings, secret = configure_admin(settings)
    on_stage('admin-build', True)
    admin = deploy.build(root, settings, 'admin')
    previous_secret = os.environ.get('SERVER_CLIENT_SECRET')
    try:
        os.environ['SERVER_CLIENT_SECRET'] = secret
        on_stage('admin-publish', True)
        deploy.publish(admin, migrate=False)
    finally:
        if previous_secret is None:
            os.environ.pop('SERVER_CLIENT_SECRET', None)
        else:
            os.environ['SERVER_CLIENT_SECRET'] = previous_secret
    on_stage('readiness', True)
    checks.extend(readiness(settings))
    result = None
    if preview:
        # 源数据仅调用 export/query，最后再核对源旧行未丢失；不复制源 KV 会话或签名材料。
        lifecycle.prove_rows(source, snapshot['witness'], exact=True)
        lifecycle.isolation_checks(settings)
        checks.extend({'id': name, 'passed': True} for name in ('source-unchanged', 'side-effects-isolated'))
        result = {'resources': [{'key': row['key'], 'status': 'created'} for row in request['context']['resources']],
                  'urls': request['context']['urls'], 'snapshot': {'id': snapshot['id'], 'createdAt': snapshot['createdAt']}}
    return 'deployed-unverified', checks, result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    request = read_json(args.request)
    result = {key: request.get(key) for key in ('schemaVersion', 'taskId', 'action', 'sourceSha', 'applicationVersion')}
    progress = {'stage': 'unconfirmed', 'writes': None}
    def on_stage(stage, writes):
        if stage not in ERROR_CODES or not isinstance(writes, bool) or (progress['writes'] is True and not writes):
            raise StackError('Invalid execution progress')
        progress.update(stage=stage, writes=writes)
    try:
        status, checks, lifecycle_result = execute(request, on_stage=on_stage)
        result.update(status=status, checks=checks)
        if lifecycle_result is not None:
            result['lifecycle'] = lifecycle_result
        code = 0
    except Exception as error:
        # 不输出原始异常：API、子进程或输入可能包含凭据。外部副作用不确定时不重试。
        possible_writes = progress['writes'] is not False
        result.update(status='unknown' if possible_writes and os.environ.get('SBA_EXECUTE') == '1' and request.get('action') in ('deploy', 'update', 'preview', 'destroy-preview', 'repair') else 'failed',
                      checks=[] if possible_writes else [{'id': 'cloud-writes-not-started', 'passed': True}],
                      errorCode=result_error(ERROR_CODES.get(progress['stage'], 'NACCOUNT_EXECUTION_FAILED'), error))
        print('NACCOUNT_EXECUTION_FAILED; preserve the runner diagnostics and do not replay cloud writes', file=sys.stderr)
        code = 1
    atomic_json(args.result, result)
    return code


if __name__ == '__main__':
    sys.exit(main())
