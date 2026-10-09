"""显式 admin-publish 修复；只发布后台，保全证据仅在内存中比较。"""
from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import quote, urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

import cloudflare as deploy
import lifecycle
from stack import Stack, StackError, read_json


def require(condition):
    if not condition:
        raise StackError('Repair identity or preservation check failed; do not replay')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def validate_context(request):
    context = request.get('context')
    require(isinstance(context, dict) and set(context) == {
        'repairId', 'parentTaskId', 'parentRunId', 'requestDigest', 'resultDigest', 'errorCode'})
    require(context['repairId'] == 'admin-publish' and context['errorCode'] == 'NACCOUNT_ADMIN_PUBLISH_FAILED')
    require(isinstance(context['parentTaskId'], str) and re.fullmatch(r'dc-[a-f0-9]{32}', context['parentTaskId'])
            and context['parentTaskId'] != request['taskId'])
    require(type(context['parentRunId']) is int and 0 < context['parentRunId'] <= 9007199254740991)
    for name in ('requestDigest', 'resultDigest'):
        require(isinstance(context[name], str) and re.fullmatch(r'[a-f0-9]{64}', context[name]))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def key_witness(settings):
    token = os.environ.get('CLOUDFLARE_API_TOKEN'); require(bool(token))
    result = {}
    for name in sorted(deploy.KEY_NAMES):
        request = Request('https://api.cloudflare.com/client/v4/accounts/' + settings['accountId'] +
                          '/storage/kv/namespaces/' + settings['kvId'] + '/values/' + quote(name),
                          headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'NAccount-SBA/3.0'})
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(65537)
            require(response.status == 200 and 0 < len(raw) <= 65536)
        result[name] = hashlib.sha256(raw).hexdigest()
    return result


def data_witness(settings):
    # 含迁移表、索引、触发器和视图；不将账号/客户端密钥或SQL导出写入artifact。
    schema = lifecycle.query(settings, "SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' AND name NOT GLOB '_cf_*' ORDER BY type,name")
    tables = [row['name'] for row in schema if row['type'] == 'table']
    require(0 < len(tables) <= 100)
    result = {'schema': digest(schema), 'tables': {}}
    for table in tables:
        name = lifecycle.sql_name(table)
        columns = [row['name'] for row in lifecycle.query(settings, 'PRAGMA table_info(' + name + ')')]
        require(bool(columns))
        hashes = []; size = 0
        for offset in range(0, 100001, 500):
            rows = lifecycle.query(settings, 'SELECT * FROM ' + name + ' ORDER BY rowid LIMIT 500 OFFSET ?', [offset])
            size += len(json.dumps(rows).encode()); require(size <= 64 * 1024 * 1024)
            hashes.extend(lifecycle.row_digest([row[column] for column in columns]) for row in rows)
            require(len(hashes) <= 100000)
            if len(rows) < 500:
                break
        else:
            raise StackError('Repair data witness exceeds bounded size')
        result['tables'][table] = digest({'columns': columns, 'rows': sorted(hashes)})
    require(not lifecycle.query(settings, 'PRAGMA foreign_key_check'))
    return result


def domains(settings):
    result = []
    for page in range(1, 21):
        rows = deploy.cloud_api(settings, '/workers/domains?per_page=100&page=' + str(page))
        require(isinstance(rows, list) and len(rows) <= 100)
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise StackError('Repair domain inventory incomplete')


def worker(settings, role):
    path = '/workers/scripts/' + settings[role]['name']
    configuration = deploy.cloud_api(settings, path + '/settings')
    subdomain = deploy.cloud_api(settings, path + '/subdomain')
    deployments = deploy.cloud_api(settings, path + '/deployments')['deployments']
    require(bool(deployments))
    current = deployments[0]
    require(len(current['versions']) == 1 and current['versions'][0]['percentage'] == 100)
    version_id = current['versions'][0]['version_id']
    require(isinstance(version_id, str) and re.fullmatch(r'[a-f0-9-]{36}', version_id))
    version = deploy.cloud_api(settings, path + '/versions/' + version_id)
    require(version['id'] == version_id)
    require(subdomain.get('enabled') is False and subdomain.get('previews_enabled') is False)
    return {'settings': configuration, 'subdomain': subdomain, 'deployment': current, 'version': version}


def role_domains(settings, rows, role):
    host = urlparse(settings[role]['url']).hostname
    return [row for row in rows if row.get('service') == settings[role]['name'] or row.get('hostname') == host]


def bound_domain(settings, rows, role):
    selected = role_domains(settings, rows, role)
    require(len(selected) == 1 and selected[0]['hostname'] == urlparse(settings[role]['url']).hostname
            and selected[0]['service'] == settings[role]['name'] and selected[0]['environment'] == 'production')
    return selected


def preflight(settings):
    rows = domains(settings); auth = worker(settings, 'server'); admin = worker(settings, 'admin')
    require(not role_domains(settings, rows, 'admin'))
    configuration = admin['settings']
    require(configuration.get('compatibility_date') == '' and configuration.get('annotations', {}).get('workers/triggered_by') == 'secret')
    require(configuration.get('bindings') == [{'name': 'SERVER_CLIENT_SECRET', 'type': 'secret_text'}])
    require(not admin['version']['resources'].get('script_runtime', {}).get('assets'))
    bindings = {row['name']: row for row in auth['settings']['bindings']}
    require(bindings['DB']['type'] == 'd1' and (bindings['DB'].get('id') or bindings['DB'].get('database_id')) == settings['database']['id'])
    require(bindings['KV']['type'] == 'kv_namespace' and bindings['KV']['namespace_id'] == settings['kvId'])
    require(bool(auth['settings'].get('compatibility_date')))
    require(deploy.cloud_api(settings, '/d1/database/' + settings['database']['id'])['name'] == settings['database']['name'])
    return {'auth': digest(auth), 'domain': digest(bound_domain(settings, rows, 'server')), 'admin': digest(admin)}


def published(settings, before, release):
    admin = worker(settings, 'admin'); expected = read_json(release / 'source/admin-panel/wrangler.json')
    require(digest(admin) != before['admin'])
    config = admin['settings']; bindings = {row['name']: row for row in config['bindings']}
    require(config.get('compatibility_date') == expected['compatibility_date'])
    require(set(config.get('compatibility_flags', [])) == set(expected.get('compatibility_flags', [])))
    require(bindings['SERVER_CLIENT_SECRET']['type'] == 'secret_text' and bindings['ASSETS']['type'] == 'assets')
    for name, value in deploy.admin_env(settings).items():
        require(bindings[name]['type'] == 'plain_text' and bindings[name].get('text') == value)
    require(bool(admin['version']['resources']['script_runtime'].get('assets', {}).get('base_path')))
    rows = domains(settings); bound_domain(settings, rows, 'admin')
    require(digest(worker(settings, 'server')) == before['auth'])
    require(digest(bound_domain(settings, rows, 'server')) == before['domain'])


def execute(request, settings, root, on_stage, configure_admin, readiness):
    require(os.environ.get('SBA_EXECUTE') == '1' and bool(os.environ.get('CLOUDFLARE_API_TOKEN')))
    on_stage('admin-config', False)
    before = preflight(settings)
    settings, secret = configure_admin(settings, read_only=True)
    on_stage('upstream', False); Stack(root).initialize()
    on_stage('admin-build', False); release = deploy.build(root, settings, 'admin')
    checked, receipt = deploy.checked_release(release)
    require(receipt['component'] == 'admin' and checked == settings)
    on_stage('preservation', False)
    require(preflight(settings) == before)
    data = data_witness(settings); keys = key_witness(settings)
    current, current_secret = configure_admin(settings, read_only=True)
    require(current == settings and current_secret == secret)
    previous_secret = os.environ.get('SERVER_CLIENT_SECRET')
    try:
        os.environ['SERVER_CLIENT_SECRET'] = secret
        on_stage('admin-publish', True)
        deploy.publish(release, migrate=False)
    finally:
        if previous_secret is None:
            os.environ.pop('SERVER_CLIENT_SECRET', None)
        else:
            os.environ['SERVER_CLIENT_SECRET'] = previous_secret
    on_stage('preservation', True)
    require(data_witness(settings) == data and key_witness(settings) == keys)
    on_stage('readiness', True)
    published(settings, before, release)
    checks = readiness(settings, admin_http=False)
    checks.extend({'id': name, 'passed': True} for name in (
        'repair-completed', 'data-preserved', 'unchanged-resources-verified', 'service-ready'))
    return 'succeeded', checks, None
