"""Repair only the verified 3.2.0 interruption before migration 0050; never replay a run."""
import json
import os

import cloudflare as deploy
import lifecycle
import repair
from stack import Stack, scratch, read_json

MIGRATION = '0050_naccount_security.sql'


def preflight(settings, source):
    expected = sorted(path.name for path in (source / 'server/migrations/sqlite').glob('*.sql'))
    applied = sorted(row['name'] for row in lifecycle.query(settings, 'SELECT name FROM d1_migrations'))
    repair.require(expected and expected[-1] == MIGRATION and applied == expected[:-1])
    columns = lifecycle.query(settings, 'PRAGMA table_info(naccount_profile)')
    repair.require([row['name'] for row in columns] == ['userId', 'nickname', 'signature'])
    repair.require(not any(row['name'] == 'securityVersion' for row in lifecycle.query(settings, 'PRAGMA table_info(user)')))
    repair.require(not lifecycle.query(settings, "SELECT name FROM sqlite_master WHERE name IN ('naccount_security_request','naccount_security_limit','naccount_otp_use','naccount_security_apply','naccount_contact_phone_unique')"))
    rows = repair.domains(settings)
    workers = {role: repair.worker(settings, role) for role in ('server', 'admin')}
    domains = {role: repair.bound_domain(settings, rows, role) for role in workers}
    for value in workers.values():
        repair.require(bool(value['settings'].get('compatibility_date')))
        repair.require(bool(value['version']['resources'].get('script_runtime', {}).get('assets', {}).get('base_path')))
    bindings = {row['name']: row for row in workers['server']['settings']['bindings']}
    repair.require(bindings['DB']['type'] == 'd1' and (bindings['DB'].get('id') or bindings['DB'].get('database_id')) == settings['database']['id'])
    repair.require(bindings['KV']['type'] == 'kv_namespace' and bindings['KV']['namespace_id'] == settings['kvId'])
    repair.require(deploy.cloud_api(settings, '/d1/database/' + settings['database']['id'])['name'] == settings['database']['name'])
    # This repair consumes the already configured portal; it never repairs client identities.
    portal = lifecycle.query(settings, 'SELECT redirectUris,isActive FROM app WHERE clientId=? AND deletedAt IS NULL', ['naccount-user-portal'])
    repair.require(len(portal) == 1 and portal[0]['isActive'] == 1 and settings['server']['url'] + '/account' == portal[0]['redirectUris'])
    return {'workers': {role: repair.digest(value) for role, value in workers.items()}, 'domains': repair.digest(domains)}


def published(settings, releases, before):
    domains = repair.domains(settings)
    repair.require(repair.digest({role: repair.bound_domain(settings, domains, role) for role in releases}) == before['domains'])
    for role, release in releases.items():
        worker = repair.worker(settings, role)
        repair.require(repair.digest(worker) != before['workers'][role])
        folder = 'server' if role == 'server' else 'admin-panel'
        expected = read_json(release / 'source' / folder / 'wrangler.json')
        config = worker['settings']
        repair.require(config.get('compatibility_date') == expected['compatibility_date'])
        repair.require(set(config.get('compatibility_flags', [])) == set(expected.get('compatibility_flags', [])))
        bindings = {row['name']: row for row in config['bindings']}
        for name, value in expected.get('vars', {}).items():
            binding = bindings.get(name, {})
            if isinstance(value, str):
                repair.require(binding.get('type') == 'plain_text' and binding.get('text') == value)
            else:
                repair.require(binding.get('type') == 'json' and binding.get('json') == value)
        repair.require(bool(worker['version']['resources'].get('script_runtime', {}).get('assets', {}).get('base_path')))
        repair.require(bindings.get('ASSETS', {}).get('type') == 'assets')
        if role == 'server':
            repair.require(bindings.get('DB', {}).get('type') == 'd1' and (bindings['DB'].get('id') or bindings['DB'].get('database_id')) == settings['database']['id'])
            repair.require(bindings.get('KV', {}).get('namespace_id') == settings['kvId'])
        else:
            repair.require(bindings.get('SERVER_CLIENT_SECRET', {}).get('type') == 'secret_text')


def execute(request, settings, root, on_stage, configure_admin, readiness):
    repair.validate_context(request)
    repair.require(os.environ.get('SBA_EXECUTE') == '1' and bool(os.environ.get('CLOUDFLARE_API_TOKEN')))
    repair.require(not settings['server'].get('secretNames'))
    on_stage('upstream', False); Stack(root).initialize()
    on_stage('configuration', False)
    before = preflight(settings, root / 'melody-auth')
    settings, secret = configure_admin(settings, read_only=True)
    on_stage('server-build', False); server = deploy.build(root, settings, 'server')
    on_stage('admin-build', False); admin = deploy.build(root, settings, 'admin')
    for component, release in [('server', server), ('admin', admin)]:
        checked, receipt = deploy.checked_release(release)
        repair.require(checked == settings and receipt['component'] == component)
    on_stage('preservation', False)
    repair.require(preflight(settings, server / 'source') == before)
    repair.require(configure_admin(settings, read_only=True) == (settings, secret))
    keys = repair.key_witness(settings)
    snapshot = lifecycle.export_snapshot(settings, scratch('naccount-security-repair-backup-'))
    recovery = deploy.cloud_api(settings, '/d1/database/' + settings['database']['id'] + '/time_travel/bookmark')
    repair.require(isinstance(recovery.get('bookmark'), str) and 0 < len(recovery['bookmark']) <= 256)
    print('NACCOUNT_D1_RECOVERY_POINT ' + json.dumps({'databaseId': settings['database']['id'], 'bookmark': recovery['bookmark'], 'createdAt': snapshot['createdAt'], 'minimumWindowDays': 7}))
    # Recheck the exact unapplied migration and live deployments immediately before the write.
    repair.require(preflight(settings, server / 'source') == before)
    on_stage('server-publish', True)
    deploy.wrangler(server / 'source', 'server', ['d1', 'migrations', 'apply', 'DB', '--remote'], settings, cloud=True)
    lifecycle.prove_rows(settings, snapshot['witness'])
    repair.require(lifecycle.query(settings, 'SELECT name FROM d1_migrations ORDER BY id DESC LIMIT 1') == [{'name': MIGRATION}])
    repair.require(len(lifecycle.query(settings, "SELECT name FROM sqlite_master WHERE type='trigger' AND name='naccount_security_apply'")) == 1)
    repair.require(repair.key_witness(settings) == keys)
    deploy.publish(server, migrate=False, portal_read_only=True)
    previous_secret = os.environ.get('SERVER_CLIENT_SECRET')
    try:
        os.environ['SERVER_CLIENT_SECRET'] = secret
        on_stage('admin-publish', True); deploy.publish(admin, migrate=False)
    finally:
        if previous_secret is None:
            os.environ.pop('SERVER_CLIENT_SECRET', None)
        else:
            os.environ['SERVER_CLIENT_SECRET'] = previous_secret
    on_stage('preservation', True)
    lifecycle.prove_rows(settings, snapshot['witness'])
    repair.require(repair.key_witness(settings) == keys)
    repair.require(configure_admin(settings, read_only=True) == (settings, secret))
    on_stage('readiness', True)
    published(settings, {'server': server, 'admin': admin}, before)
    checks = readiness(settings, admin_http=False)
    checks.extend({'id': name, 'passed': True} for name in (
        'backup-created', 'repair-completed', 'data-preserved', 'unchanged-resources-verified', 'service-ready'))
    return 'succeeded', checks, None
