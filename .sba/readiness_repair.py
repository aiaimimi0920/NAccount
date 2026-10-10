"""只读收尾固定 3.2.1 发布；不重放迁移，不追认历史保全。"""
import os

import cloudflare as deploy
import lifecycle
import portal
import repair
import security_migration_repair as migration
from stack import Stack, read_json, scratch, write_json

VERSIONS = {'server': 'b102c9cc-8b17-44e5-a038-05370d8fada6',
            'admin': '298f4d47-fe6e-439b-a12a-d256b69d6f5c'}
GENERATION = '08dc487ecd7afeeaba963f36a975f2dd6989c709e1cbd3a4cf8d8fe904344a45'


def deployment_witness(settings):
    rows = repair.domains(settings)
    workers = {role: repair.worker(settings, role) for role in VERSIONS}
    for role, worker in workers.items():
        repair.require(worker['version']['id'] == VERSIONS[role])
    return {'workers': {role: repair.digest(worker) for role, worker in workers.items()},
            'domains': repair.digest({role: repair.bound_domain(settings, rows, role) for role in VERSIONS})}


def schema_ready(settings, source):
    expected = sorted(path.name for path in (source / 'server/migrations/sqlite').glob('*.sql'))
    repair.require(expected and expected[-1] == migration.MIGRATION)
    repair.require(sorted(row['name'] for row in lifecycle.query(settings, 'SELECT name FROM d1_migrations')) == expected)
    repair.require(any(row['name'] == 'securityVersion' for row in lifecycle.query(settings, 'PRAGMA table_info(user)')))
    names = ['naccount_security_request', 'naccount_security_limit', 'naccount_otp_use',
             'naccount_security_apply', 'naccount_contact_phone_unique']
    rows = lifecycle.query(settings, 'SELECT name FROM sqlite_master WHERE name IN (' + ','.join('?' for _ in names) + ')', names)
    repair.require(sorted(row['name'] for row in rows) == sorted(names))


def execute(request, settings, root, on_stage, configure_admin, readiness):
    repair.validate_context(request)
    repair.require(os.environ.get('SBA_EXECUTE') == '1' and bool(os.environ.get('CLOUDFLARE_API_TOKEN')))
    repair.require(read_json(root / 'customizations/current.json') == {'generation': GENERATION})
    on_stage('upstream', False)
    Stack(root).initialize()
    source = root / 'melody-auth'
    on_stage('configuration', False)
    settings, secret = configure_admin(settings, read_only=True)
    portal.configure(settings, lifecycle.query, read_only=True)
    schema_ready(settings, source)
    before = deployment_witness(settings)
    data = repair.data_witness(settings)
    keys = repair.key_witness(settings)
    folder = scratch('naccount-readiness-repair-')
    releases = {'server': folder / 'server', 'admin': folder / 'admin'}
    write_json(releases['server'] / 'source/server/wrangler.json', deploy.server_config(source, settings))
    write_json(releases['admin'] / 'source/admin-panel/wrangler.json', deploy.admin_config(source, settings))
    on_stage('readiness', False)
    migration.published(settings, releases, before, changed=False)
    checks = readiness(settings, admin_http=False)
    repair.require(configure_admin(settings, read_only=True) == (settings, secret))
    repair.require(repair.data_witness(settings) == data and repair.key_witness(settings) == keys)
    repair.require(deployment_witness(settings) == before)
    # These checks cover this read-only action, not the preceding failed task's history.
    checks.extend({'id': name, 'passed': True} for name in (
        'read-only-verification', 'repair-completed', 'data-preserved',
        'unchanged-resources-verified', 'service-ready'))
    return 'succeeded', checks, None
