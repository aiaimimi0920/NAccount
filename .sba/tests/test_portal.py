"""SQLite portal configuration contracts; no ignored checkout or cloud requests required."""
import copy
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portal
from stack import ROOT, StackError


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript("""CREATE TABLE app(id INTEGER PRIMARY KEY,name TEXT,type TEXT,clientId TEXT,redirectUris TEXT DEFAULT '',isActive INTEGER DEFAULT 1,deletedAt TEXT);
        INSERT INTO app(name,type,clientId) VALUES('Admin Panel (SPA)','spa','admin-spa'),('Admin Panel (S2S)','s2s','admin-s2s'),('NAccount User Portal (SPA)','spa','naccount-user-portal');
        CREATE TABLE scope(id INTEGER PRIMARY KEY,name TEXT,type TEXT,deletedAt TEXT);
        INSERT INTO scope(name,type) VALUES('openid','spa'),('profile','spa'),('offline_access','spa');
        CREATE TABLE app_scope(appId INTEGER,scopeId INTEGER,deletedAt TEXT);
        INSERT INTO app_scope(appId,scopeId) VALUES(3,1),(3,2),(3,3);""")
        self.settings = {'server': {'url': 'https://auth.example.test'}}
        self.writes = []

    def query(self, settings, sql, params):
        if sql.startswith('UPDATE'): self.writes.append(sql)
        return [dict(row) for row in self.db.execute(sql, params)]

    def test_portal_is_independent_and_configuration_is_idempotent(self):
        admins = [tuple(row) for row in self.db.execute("SELECT * FROM app WHERE name LIKE 'Admin Panel%'")]
        portal.configure(self.settings, self.query)
        self.assertEqual(len(self.writes), 1)
        portal.configure(self.settings, self.query)
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(admins, [tuple(row) for row in self.db.execute("SELECT * FROM app WHERE name LIKE 'Admin Panel%'")])
        self.assertEqual(self.db.execute('SELECT redirectUris FROM app WHERE clientId=?', [portal.CLIENT_ID]).fetchone()[0], 'https://auth.example.test/account')

    def test_disabled_client_is_not_silently_reactivated_except_isolated_preview(self):
        self.db.execute('UPDATE app SET isActive=0 WHERE clientId=?', [portal.CLIENT_ID])
        with self.assertRaisesRegex(StackError, 'disabled'): portal.configure(self.settings, self.query)
        portal.configure(self.settings, self.query, preview=True)
        self.assertEqual(self.db.execute('SELECT isActive FROM app WHERE clientId=?', [portal.CLIENT_ID]).fetchone()[0], 1)

    def test_wrong_identity_or_duplicate_name_refuses_without_updates(self):
        self.db.execute('INSERT INTO app(name,type) VALUES(?,?)', [portal.CLIENT_NAME, 'spa'])
        with self.assertRaisesRegex(StackError, 'Unique'): portal.configure(self.settings, self.query)
        self.assertEqual(self.writes, [])

    def test_missing_or_privileged_grants_are_rejected(self):
        self.db.execute('DELETE FROM app_scope WHERE appId=(SELECT id FROM app WHERE clientId=?)', [portal.CLIENT_ID])
        with self.assertRaisesRegex(StackError, 'three ordinary-user scopes'): portal.configure(self.settings, self.query)
        self.assertEqual(self.writes, [])

    def test_uncertain_callback_write_is_not_replayed(self):
        def no_write(settings, sql, params):
            if sql.startswith('UPDATE'): self.writes.append(sql); return []
            return self.query(settings, sql, params)
        with self.assertRaisesRegex(StackError, 'uncertain'): portal.configure(self.settings, no_write)
        self.assertEqual(len(self.writes), 1)
