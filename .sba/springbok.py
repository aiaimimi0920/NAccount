"""NAccount 应用自有部署流程；SpringBok 仅调用和消费结果。"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import urlopen

import cloudflare as deploy
from stack import ROOT, Stack, StackError, atomic_json, clean, git, read_json, scratch, write_json


def validated_request(value: dict, root: Path) -> dict:
    manifest = read_json(root / '.sba/manifest.json')
    fields = {'schemaVersion', 'taskId', 'action', 'repository', 'sourceSha', 'applicationId',
              'applicationVersion', 'environment', 'configuration', 'previous'}
    if set(value) != fields or value.get('schemaVersion') != 2:
        raise StackError('Invalid SBA request')
    if value['action'] not in ('deploy', 'update', 'verify'):
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
        if value['action'] == 'update' and (current <= old or value['sourceSha'] == previous['sourceSha']):
            raise StackError('Update requires a newer version')
        if value['action'] == 'verify' and (current != old or value['sourceSha'] != previous['sourceSha']):
            raise StackError('Verify must target the deployed release')
    if not isinstance(value['configuration'], dict):
        raise StackError('Public configuration required')
    settings = value['configuration']
    if set(settings) != {'accountId', 'database', 'kvId', 'server', 'admin', 'vars'}:
        raise StackError('Unexpected public configuration fields')
    for key, allowed in [('database', {'name', 'id'}), ('server', {'name', 'url', 'secretNames'}),
                         ('admin', {'name', 'url', 'spaClientId', 's2sClientId'})]:
        if not isinstance(settings[key], dict) or set(settings[key]) != allowed:
            raise StackError('Unexpected public configuration fields')
    if not isinstance(settings['server']['secretNames'], list) or any(
            name not in manifest['secrets'] for name in settings['server']['secretNames']):
        raise StackError('Undeclared runtime secret')
    return copy.deepcopy(value)


def database_query(settings: dict, sql: str, params: list) -> list:
    response = deploy.cloud_api(settings, f"/d1/database/{settings['database']['id']}/query",
                                method='POST', payload={'sql': sql, 'params': params})
    if not isinstance(response, list) or len(response) != 1 or response[0].get('success') is not True:
        raise StackError('D1 query failed')
    return response[0]['results']


def configure_admin(settings: dict) -> tuple[dict, str]:
    rows = database_query(settings, 'SELECT id,name,type,clientId,secret,redirectUris FROM app '
                          'WHERE deletedAt IS NULL AND name IN (?,?)', ['Admin Panel (SPA)', 'Admin Panel (S2S)'])
    spa = [row for row in rows if row['name'] == 'Admin Panel (SPA)' and row['type'] == 'spa']
    s2s = [row for row in rows if row['name'] == 'Admin Panel (S2S)' and row['type'] == 's2s']
    if len(rows) != 2 or len(spa) != 1 or len(s2s) != 1 or not s2s[0].get('secret'):
        raise StackError('Unique real admin clients required; no guessed IDs')
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
        database_query(settings, 'UPDATE app SET redirectUris=? WHERE id=? AND redirectUris=? AND deletedAt IS NULL',
                       [new, spa[0]['id'], old])
        check = database_query(settings, 'SELECT redirectUris FROM app WHERE id=? AND deletedAt IS NULL', [spa[0]['id']])
        if len(check) != 1 or check[0]['redirectUris'] != new:
            raise StackError('Admin callback update uncertain')
    return result, s2s[0]['secret']


def readiness(settings: dict) -> list[dict]:
    checks = []
    for suffix, key in [('/.well-known/openid-configuration', 'issuer'), ('/.well-known/jwks.json', 'keys')]:
        with urlopen(settings['server']['url'] + suffix, timeout=30) as response:
            payload = json.load(response)
        if key == 'issuer' and payload.get(key) != settings['server']['url']:
            raise StackError('OIDC issuer mismatch')
        if key == 'keys' and not payload.get(key):
            raise StackError('JWKS empty')
        checks.append({'id': 'oidc-discovery' if key == 'issuer' else 'jwks-ready', 'passed': True})
    with urlopen(settings['admin']['url'], timeout=30) as response:
        if response.status != 200:
            raise StackError('Admin page not ready')
    checks.append({'id': 'admin-http-ready', 'passed': True})
    return checks


def execute(value: dict, root: Path = ROOT) -> tuple[str, list]:
    request = validated_request(value, root)
    staging = scratch('naccount-sba-')
    config_path = staging / 'deployment.json'
    write_json(config_path, request['configuration'])
    settings = deploy.config(config_path, 'server')
    if request['action'] == 'verify':
        return 'succeeded', readiness(settings)
    if os.environ.get('SBA_EXECUTE') != '1':
        raise StackError('Explicit SBA_EXECUTE=1 required')
    if any(not os.environ.get(name) for name in ['CLOUDFLARE_API_TOKEN', *settings['server'].get('secretNames', [])]):
        raise StackError('Missing deployment credentials; no cloud writes attempted')
    # 重建锁定版本；不拉浮动上游，不触碰开发者原始 checkout。
    Stack(root).initialize()
    server = deploy.build(root, settings, 'server')
    if request['action'] == 'deploy':
        deploy.bootstrap_keys(server)
    # 迁移、备份和幂等均属于应用；平台只知道 update/deploy 动作。
    deploy.publish(server, migrate=True)
    settings, secret = configure_admin(settings)
    admin = deploy.build(root, settings, 'admin')
    previous_secret = os.environ.get('SERVER_CLIENT_SECRET')
    try:
        os.environ['SERVER_CLIENT_SECRET'] = secret
        deploy.publish(admin, migrate=False)
    finally:
        if previous_secret is None:
            os.environ.pop('SERVER_CLIENT_SECRET', None)
        else:
            os.environ['SERVER_CLIENT_SECRET'] = previous_secret
    return 'deployed-unverified', readiness(settings)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    args = parser.parse_args()
    request = read_json(args.request)
    result = {key: request.get(key) for key in ('schemaVersion', 'taskId', 'action', 'sourceSha', 'applicationVersion')}
    try:
        status, checks = execute(request)
        result.update(status=status, checks=checks)
        code = 0
    except Exception:
        # 不输出原始异常：API、子进程或输入可能包含凭据。外部副作用不确定时不重试。
        result.update(status='unknown' if os.environ.get('SBA_EXECUTE') == '1' and request.get('action') in ('deploy', 'update') else 'failed',
                      checks=[], errorCode='NACCOUNT_EXECUTION_FAILED')
        print('NACCOUNT_EXECUTION_FAILED; preserve the runner diagnostics and do not replay cloud writes', file=sys.stderr)
        code = 1
    atomic_json(args.result, result)
    return code


if __name__ == '__main__':
    sys.exit(main())
