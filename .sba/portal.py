"""Owned public portal client. No administrator secrets or roles are copied."""
from stack import StackError

CLIENT_ID = 'naccount-user-portal'
CLIENT_NAME = 'NAccount User Portal (SPA)'
SCOPES = {'openid', 'profile', 'offline_access'}


def configure(settings, query, *, preview=False):
    rows = query(settings, 'SELECT id,name,type,clientId,redirectUris,isActive,deletedAt FROM app WHERE name=? OR clientId=?', [CLIENT_NAME, CLIENT_ID])
    if len(rows) != 1 or any(rows[0].get(k) != v for k, v in {'name': CLIENT_NAME, 'type': 'spa', 'clientId': CLIENT_ID, 'deletedAt': None}.items()):
        raise StackError('Unique migrated portal client required')
    row = rows[0]
    if row['isActive'] != 1 and not preview:
        raise StackError('Portal client is disabled; refusing to reactivate')
    grants = query(settings, 'SELECT scope.name,scope.type FROM scope JOIN app_scope ON scope.id=app_scope.scopeId WHERE app_scope.appId=? AND app_scope.deletedAt IS NULL AND scope.deletedAt IS NULL', [row['id']])
    if len(grants) != 3 or {(g['name'], g['type']) for g in grants} != {(name, 'spa') for name in SCOPES}:
        raise StackError('Portal must have exactly the three ordinary-user scopes')
    expected = settings['server']['url'] + '/account'
    if row['redirectUris'] != expected or row['isActive'] != 1:
        query(settings, 'UPDATE app SET redirectUris=?,isActive=1 WHERE id=? AND redirectUris=? AND isActive=? AND deletedAt IS NULL',
              [expected, row['id'], row['redirectUris'], row['isActive']])
    check = query(settings, 'SELECT clientId,redirectUris,isActive FROM app WHERE id=? AND deletedAt IS NULL', [row['id']])
    if check != [{'clientId': CLIENT_ID, 'redirectUris': expected, 'isActive': 1}]:
        raise StackError('Portal callback configuration uncertain')
