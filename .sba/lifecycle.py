"""SBA v3 应用数据快照和隔离资源生命周期；不扫描前缀或重放未知写入。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.error import HTTPError
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen

import cloudflare as deploy
from stack import StackError, write_json


def require(value, message='Invalid lifecycle boundary'):
    if not value:
        raise StackError(message)


def inventory(settings):
    account = settings['accountId']
    values = [('resource-database', 'd1', settings['database']['id']),
              ('resource-session', 'kv', settings['kvId'])]
    for index, (role, field) in enumerate([('server', 'name'), ('server', 'url'), ('admin', 'name'), ('admin', 'url')]):
        values.append((f'target-{index}', 'worker' if field == 'name' else 'domain', settings[role][field]))
    return {(key, kind, account, remote) for key, kind, remote in values}


def check_inventory(rows, settings, *, allow_source_email: bool = False):
    require(isinstance(rows, list))
    require(all(isinstance(row, dict) and set(row) == {'key', 'kind', 'accountId', 'remoteId', 'name'} for row in rows))
    if allow_source_email:
        email_rows = [r for r in rows if r['kind'] == 'email-routing']
        base_rows = [r for r in rows if r['kind'] != 'email-routing']
        require(len(rows) <= 20 and len({r['key'] for r in rows}) == len(rows)
                and len({(r['accountId'], r['kind'], r['remoteId']) for r in rows}) == len(rows))
        require(all(r['accountId'] == settings['accountId'] and isinstance(r['key'], str)
                    and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,79}', r['key'])
                    and isinstance(r['name'], str) and 0 < len(r['name']) <= 256
                    and isinstance(r['remoteId'], str) and re.fullmatch(r'email-routing:[a-f0-9]{32}', r['remoteId'])
                    for r in email_rows))
    else:
        base_rows = rows
    require(len(base_rows) == 6)
    require({(r['key'], r['kind'], r['accountId'], r['remoteId']) for r in base_rows} == inventory(settings))


def validate_context(request):
    action, context, settings = request['action'], request['context'], request['configuration']
    require(re.fullmatch(r'test-[a-f0-9]{12}', request['environment']))
    require(settings['server']['name'] == request['environment'] + '-auth')
    require(settings['admin']['name'] == request['environment'] + '-admin')
    require(settings['database']['name'] == request['environment'] + '-db')
    require(all(urlparse(settings[role]['url']).hostname.startswith(settings[role]['name'] + '.') for role in ('server', 'admin')))
    require(isinstance(context, dict))
    check_inventory(context.get('resources'), settings)
    if action == 'preview':
        require(set(context) == {'source', 'resources', 'urls'})
        source = context['source']
        require(isinstance(source, dict) and set(source) == {'instanceId', 'taskId', 'sourceSha', 'applicationVersion', 'environment', 'configuration', 'resources', 'resultDigest'})
        require(source['sourceSha'] == request['previous']['sourceSha'] and source['applicationVersion'] == request['previous']['applicationVersion'])
        require(source['environment'] != request['environment'])
        require(all(re.fullmatch(r'dc-[a-f0-9]{32}', source[key]) for key in ('instanceId', 'taskId')))
        require(re.fullmatch(r'[a-f0-9]{64}', source['resultDigest']))
        check_inventory(source['resources'], source['configuration'], allow_source_email=True)
        require(source['configuration']['accountId'] == settings['accountId'])
        old = {(r['kind'], r['remoteId']) for r in source['resources']}
        require(not old.intersection((r['kind'], r['remoteId']) for r in context['resources']))
        require(set(context['urls']) == {settings['server']['url'], settings['admin']['url']} and len(context['urls']) == 2)
    else:
        require(set(context) == {'instanceId', 'previewTaskId', 'resultDigest', 'resources'})
        require(all(re.fullmatch(r'dc-[a-f0-9]{32}', context[key]) for key in ('instanceId', 'previewTaskId')))
        require(re.fullmatch(r'[a-f0-9]{64}', context['resultDigest']))


def preview_guard(settings, role):
    allowed = [settings['server']['url']] if role == 'admin-panel' else []
    return f'''export const allowedOrigins = {json.dumps(allowed)};
const allowed = new Set(allowedOrigins);
const originalFetch = globalThis.fetch;
globalThis.fetch = function(input, init) {{
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
  if (!allowed.has(url.origin)) throw new Error('NACCOUNT_PREVIEW_EGRESS_BLOCKED');
  return originalFetch(input, {{...init, redirect: 'manual'}});
}};
export async function checkIsolation() {{
  try {{ await globalThis.fetch('https://naccount-sba-egress-check.invalid'); return false; }}
  catch (error) {{ return error.message === 'NACCOUNT_PREVIEW_EGRESS_BLOCKED'; }}
}}
'''


def preview_entry(original, settings, role):
    allowed = [settings['server']['url'], settings['admin']['url']]
    csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-src 'none'; connect-src " + ' '.join(allowed) + "; form-action " + ' '.join(allowed)
    return f'''import {{checkIsolation, allowedOrigins}} from './naccount-preview-guard.mjs';
import app from './{original.removeprefix('./')}';
const allowed = new Set({json.dumps(allowed)});
export default {{ async fetch(request, env, ctx) {{
  if (new URL(request.url).pathname === '/__naccount_preview_check' && request.method === 'GET')
    return Response.json({{kind: 'naccount-preview-v3', egressBlocked: await checkIsolation(), allowedOrigins}}, {{headers: {{'cache-control': 'no-store'}}}});
  const response = await app.fetch(request, {{...env, SMTP: undefined, CLOUDFLARE_EMAIL: undefined}}, ctx);
  const location = response.headers.get('location');
  if (location && !allowed.has(new URL(location, request.url).origin)) return new Response('NACCOUNT_PREVIEW_REDIRECT_BLOCKED', {{status: 409}});
  const headers = new Headers(response.headers);
  headers.set('content-security-policy', {json.dumps(csp)});
  headers.set('x-naccount-preview', 'isolated');
  return new Response(response.body, {{status: response.status, statusText: response.statusText, headers}});
}} }};
'''


def export_snapshot(settings, directory: Path):
    endpoint = f"/d1/database/{settings['database']['id']}/export"
    body = {'output_format': 'polling'}
    for _ in range(120):
        result = deploy.cloud_api(settings, endpoint, method='POST', payload=body)
        if result.get('status') == 'complete':
            url = result['result']['signed_url']; parsed = urlparse(url)
            require(parsed.scheme == 'https' and parsed.hostname.endswith('.cloudflarestorage.com') and not parsed.username)
            with urlopen(Request(url), timeout=60) as response:
                raw = response.read(64 * 1024 * 1024 + 1)
            require(0 < len(raw) <= 64 * 1024 * 1024, 'Snapshot exceeds bounded export size')
            path = directory / 'snapshot.sql'; path.write_bytes(raw)
            witness = snapshot_witness(path)
            return {'path': path, 'id': hashlib.sha256(raw).hexdigest(), 'createdAt': int(time.time() * 1000), 'witness': witness}
        require(result.get('status') == 'active' and isinstance(result.get('at_bookmark'), str), 'D1 export not confirmed')
        body['current_bookmark'] = result['at_bookmark']
        write_json(directory / 'export-progress.json', {'databaseId': settings['database']['id'], 'bookmark': result['at_bookmark']})
        time.sleep(1)
    raise StackError('D1 export timed out; do not replay mutations')


TRANSIENT_TABLES = {
    'naccount_security_limit',
    'naccount_otp_use',
    'naccount_security_request',
    'naccount_link_request',
}


def sql_name(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value))
    return '"' + value + '"'


def row_digest(row):
    return hashlib.sha256(json.dumps(list(row), ensure_ascii=False, separators=(',', ':'), default=lambda b: {'bytes': bytes(b).hex()}).encode()).hexdigest()


def snapshot_witness(path):
    # SQLite 只在内存中解析受信 D1 导出，不允许扩展或 ATTACH/文件写入语句。
    db = sqlite3.connect(':memory:')
    try:
        db.set_authorizer(lambda op, *_: sqlite3.SQLITE_DENY if op in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH) else sqlite3.SQLITE_OK)
        db.executescript(path.read_text(encoding='utf-8'))
        require(not db.execute('PRAGMA foreign_key_check').fetchall(), 'Invalid snapshot relationships')
        witness = {}
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%' AND name!='d1_migrations'").fetchall():
            if table in TRANSIENT_TABLES:
                continue
            columns = [r[1] for r in db.execute('PRAGMA table_info(' + sql_name(table) + ')')]
            rows = db.execute('SELECT ' + ','.join(map(sql_name, columns)) + ' FROM ' + sql_name(table)).fetchall()
            witness[table] = {'columns': columns, 'rows': sorted(row_digest(row) for row in rows)}
            require(len(rows) <= 100000 and len(witness) <= 100, 'Snapshot exceeds bounded verification size')
        return witness
    finally:
        db.close()


def query(settings, sql, params=None):
    return deploy.d1_query(settings, sql, params, error='D1 query unconfirmed')


def fetch_table_digests(query_fn, settings, table, columns, *, max_rows=100000, max_json_bytes=None,
                        overflow_error='Data verification exceeds bounded row count'):
    quoted_table = sql_name(table)
    projected = ','.join(map(sql_name, columns))
    can_keyset = not any(col.lower() in ('rowid', '_rowid_', 'oid') for col in columns)
    hashes = []
    json_size = 0
    cursor = None
    for page in range(max_rows // 500 + 1):
        if can_keyset:
            try:
                if cursor is None:
                    rows = query_fn(settings, f'SELECT rowid AS "__naccount_rowid__", {projected} FROM {quoted_table} ORDER BY rowid LIMIT 500')
                else:
                    rows = query_fn(settings, f'SELECT rowid AS "__naccount_rowid__", {projected} FROM {quoted_table} WHERE rowid > ? ORDER BY rowid LIMIT 500', [cursor])
            except (sqlite3.OperationalError, StackError):
                if page == 0:
                    can_keyset = False
                else:
                    raise
        if not can_keyset:
            rows = query_fn(settings, f'SELECT {projected} FROM {quoted_table} LIMIT 500 OFFSET ?', [page * 500])
        if max_json_bytes is not None:
            clean_rows = [{col: row[col] for col in columns} for row in rows]
            json_size += len(json.dumps(clean_rows).encode())
            require(json_size <= max_json_bytes, overflow_error)
        hashes.extend(row_digest([row[column] for column in columns]) for row in rows)
        require(len(hashes) <= max_rows, overflow_error)
        if len(rows) < 500:
            return hashes
        if can_keyset:
            cursor = rows[-1]['__naccount_rowid__']
    raise StackError(overflow_error)


def prove_rows(settings, witness, *, exact=False):
    # 投影旧列，允许新增列/记录；每个旧行的值与重复数量必须保留。
    from collections import Counter
    if exact:
        tables = query(settings, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%' AND name!='d1_migrations'")
        require(({r['name'] for r in tables} - TRANSIENT_TABLES) == set(witness), 'Source schema changed during preview')
    for table, entry in witness.items():
        columns = entry['columns']
        if exact:
            require([r['name'] for r in query(settings, 'PRAGMA table_info(' + sql_name(table) + ')')] == columns, 'Source columns changed during preview')
        hashes = fetch_table_digests(query, settings, table, columns)
        require(not (Counter(entry['rows']) - Counter(hashes)), 'Existing database rows were changed or lost')
        if exact:
            require(Counter(entry['rows']) == Counter(hashes), 'Source changed during preview; cannot attest unchanged')
    require(not query(settings, 'PRAGMA foreign_key_check'), 'Migration broke foreign keys')


def isolate_apps(settings):
    # 不让复制的 OAuth 客户端回调或管理员 secret 继续关联源环境。
    admins = query(settings, 'SELECT id,name,type,isActive FROM app WHERE deletedAt IS NULL AND name IN (?,?)', ['Admin Panel (SPA)', 'Admin Panel (S2S)'])
    require(len(admins) == 2 and {(r['name'], r['type'], r['isActive']) for r in admins} == {('Admin Panel (SPA)', 'spa', 1), ('Admin Panel (S2S)', 's2s', 1)}, 'Unique active admin clients required before preview publish')
    spa = next(r for r in admins if r['type'] == 'spa'); s2s = next(r for r in admins if r['type'] == 's2s')
    query(settings, 'UPDATE app SET isActive=0 WHERE id NOT IN (?,?)', [spa['id'], s2s['id']])
    locales = settings['vars'].get('SUPPORTED_LOCALES', ['en', 'fr'])
    require(all(isinstance(locale, str) and re.fullmatch(r'[a-z]{2}(?:-[A-Za-z]{2,4})?', locale) for locale in locales))
    redirects = ','.join(settings['admin']['url'] + '/' + locale + '/dashboard' for locale in locales)
    query(settings, 'UPDATE app SET redirectUris=? WHERE id=? AND deletedAt IS NULL', [redirects, spa['id']])
    secret = secrets.token_urlsafe(48)
    query(settings, 'UPDATE app SET secret=? WHERE id=? AND deletedAt IS NULL', [secret, s2s['id']])
    query(settings, 'UPDATE saml_idp SET isActive=0')
    require(not query(settings, 'SELECT id FROM app WHERE isActive!=0 AND id NOT IN (?,?)', [spa['id'], s2s['id']]))
    rows = query(settings, 'SELECT redirectUris FROM app WHERE name=? AND type=? AND deletedAt IS NULL', ['Admin Panel (SPA)', 'spa'])
    require(len(rows) == 1 and rows[0]['redirectUris'] == redirects)
    rows = query(settings, 'SELECT secret FROM app WHERE id=? AND deletedAt IS NULL', [s2s['id']])
    require(len(rows) == 1 and rows[0]['secret'] == secret, 'Preview credential rotation unconfirmed')


def isolation_checks(settings):
    for role in ('server', 'admin'):
        with urlopen(Request(settings[role]['url'] + '/__naccount_preview_check', headers={'User-Agent': 'NAccount-SBA/3.0'}), timeout=30) as response:
            value = json.load(response)
        require(value == {'kind': 'naccount-preview-v3', 'egressBlocked': True, 'allowedOrigins': [settings['server']['url']] if role == 'admin' else []}, 'Live preview isolation check failed')


def isolated_settings(settings):
    import copy
    result = copy.deepcopy(settings);result['_sbaPreview'] = True
    result['vars'].update({key: '' for key in ('GOOGLE_AUTH_CLIENT_ID', 'FACEBOOK_AUTH_CLIENT_ID', 'GITHUB_AUTH_CLIENT_ID', 'GITHUB_AUTH_APP_NAME', 'DISCORD_AUTH_CLIENT_ID', 'APPLE_AUTH_CLIENT_ID', 'COMPANY_LOGO_URL', 'COMPANY_EMAIL_LOGO_URL')})
    result['vars'].update(OIDC_AUTH_PROVIDERS=[], EMBEDDED_AUTH_ORIGINS=[], ENABLE_SAML_SP=False, ENABLE_SAML_SSO_AS_SP=False, EMAIL_PROVIDER_NAME='disabled-preview')
    result['server']['secretNames'] = []
    return result


def maybe_get(settings, path):
    try:
        return deploy.cloud_api(settings, path)
    except StackError as error:
        if isinstance(error.__cause__, HTTPError) and error.__cause__.code == 404:
            if path.startswith('/d1/database/') and isinstance(error, deploy.CloudApiError) and error.has_body and not error.d1_not_found:
                raise
            return None
        raise


def require_unused_workers(settings):
    for role in ('server', 'admin'):
        require(maybe_get(settings, '/workers/scripts/' + settings[role]['name'] + '/settings') is None,
                'Target Worker already exists; refusing to overwrite')
    hosts = {urlparse(settings[role]['url']).hostname for role in ('server', 'admin')}
    require(not any(domain['hostname'] in hosts for domain in deploy.cloud_api(settings, '/workers/domains')),
            'Target domain already exists; refusing to replace')


def destroy_preview(request, on_stage):
    settings = request['configuration']; resources = request['context']['resources']; results = {r['key']: 'unknown' for r in resources}
    # 在任何删除之前核对完整归属。不存在视作 absent；权限/网络失败不能视作不存在。
    database = maybe_get(settings, '/d1/database/' + settings['database']['id'])
    require(database is None or database.get('name') == settings['database']['name'])
    namespace = maybe_get(settings, '/storage/kv/namespaces/' + settings['kvId'])
    require(namespace is None or namespace.get('title') == request['environment'] + '-session')
    domains = deploy.cloud_api(settings, '/workers/domains')
    for role in ('server', 'admin'):
        worker = maybe_get(settings, '/workers/scripts/' + settings[role]['name'] + '/settings')
        if worker and role == 'server':
            bindings = {b['name']: b for b in worker['bindings']}
            require(bindings.get('DB', {}).get('id') == settings['database']['id'] and bindings.get('KV', {}).get('namespace_id') == settings['kvId'])
        matches = [d for d in domains if d['hostname'] == urlparse(settings[role]['url']).hostname]
        require(all(d['service'] == settings[role]['name'] for d in matches))
    on_stage('cleanup', True)
    for row in sorted(resources, key=lambda r: {'domain': 0, 'worker': 1, 'd1': 2, 'kv': 3}[r['kind']]):
        if row['kind'] == 'domain':
            matches = [d for d in domains if d['hostname'] == urlparse(row['remoteId']).hostname]
            for domain in matches:
                deploy.cloud_api(settings, '/workers/domains/' + quote(domain['id'], safe=''), method='DELETE')
            results[row['key']] = 'removed' if matches else 'absent'
            continue
        path = {'worker': '/workers/scripts/', 'd1': '/d1/database/', 'kv': '/storage/kv/namespaces/'}[row['kind']] + row['remoteId']
        current = maybe_get(settings, path + ('/settings' if row['kind'] == 'worker' else ''))
        if current is None:
            results[row['key']] = 'absent'
        else:
            deploy.cloud_api(settings, path, method='DELETE')
            require(maybe_get(settings, path + ('/settings' if row['kind'] == 'worker' else '')) is None, 'Deletion not confirmed')
            results[row['key']] = 'removed'
    # workers.dev 地址由 Worker 的删除一并撤销。
    remaining = deploy.cloud_api(settings, '/workers/domains')
    require(not any(d['hostname'] in {urlparse(settings[r]['url']).hostname for r in ('server', 'admin')} for d in remaining), 'Domain removal not confirmed')
    return {'resources': [{'key': key, 'status': status} for key, status in results.items()]}
