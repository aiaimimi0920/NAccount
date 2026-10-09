import os
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import springbok as sba
import admin_bootstrap as bootstrap
from stack import StackError


class AdminBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        folder = sba.ROOT / 'melody-auth/server/migrations/sqlite'
        # Standard offline CI does not materialize upstream: reproduce the exact
        # columns this adapter touches; the optional full migration run below
        # is also exercised in the developer checkout.
        if folder.is_dir():
            for path in sorted(folder.glob('*.sql')):
                self.db.executescript(path.read_text(encoding='utf-8'))
        else:
            self.db.executescript('''CREATE TABLE user(id INTEGER PRIMARY KEY,authId TEXT UNIQUE,email TEXT,password TEXT,
            locale TEXT,otpSecret TEXT,orgSlug TEXT DEFAULT '',emailVerified INTEGER DEFAULT 0,otpVerified INTEGER DEFAULT 0,
            mfaTypes TEXT DEFAULT '',deletedAt TEXT);
            CREATE TABLE role(id INTEGER PRIMARY KEY,name TEXT,deletedAt TEXT);
            CREATE TABLE user_role(userId INTEGER,roleId INTEGER,deletedAt TEXT);
            INSERT INTO role(id,name) VALUES(7,'super_admin');''')
        self.settings = {'admin': {'bootstrapEmail': 'fixture@gmail.com'}}
        self.generated = {'hash': 'test-only-hash', 'otp': 'A' * 32}

    def tearDown(self):
        self.db.close()

    def query(self, settings, sql, params):
        return [dict(row) for row in self.db.execute(sql, params).fetchall()]

    def test_new_admin_uses_real_role_id_without_verifying_email_or_otp(self):
        self.assertEqual(bootstrap.initialize(self.settings, self.generated, self.query), {'id': 'administrator-initialized', 'passed': True})
        self.assertEqual(self.db.execute('SELECT count(*) FROM user_role').fetchone()[0], 1)
        with self.assertRaises(StackError):
            bootstrap.initialize(self.settings, self.generated, self.query)
        self.assertEqual(self.db.execute('SELECT count(*) FROM user').fetchone()[0], 1)

    def test_existing_email_never_receives_password_or_role(self):
        for email in ['fixture@gmail.com', ' FIXTURE@GMAIL.COM ']:
            with self.subTest(email=email):
                self.db.execute('DELETE FROM user')
                self.db.execute('INSERT INTO user(authId,email,password,locale,otpSecret,orgSlug) VALUES(?,?,?,?,?,?)',
                                ('prior', email, 'unchanged', 'en', '', ''))
                with self.assertRaises(StackError):
                    bootstrap.initialize(self.settings, self.generated, self.query)
                self.assertEqual(self.db.execute('SELECT password FROM user').fetchone()[0], 'unchanged')
                self.assertEqual(self.db.execute('SELECT count(*) FROM user_role').fetchone()[0], 0)

    def test_missing_role_fails_without_creating_user(self):
        self.db.execute("DELETE FROM role WHERE name='super_admin'")
        with self.assertRaises(StackError):
            bootstrap.initialize(self.settings, self.generated, self.query)
        self.assertEqual(self.db.execute('SELECT count(*) FROM user').fetchone()[0], 0)

    def test_partial_assignment_failure_stops_without_retry(self):
        calls = []
        def query(settings, sql, params):
            calls.append(sql)
            if sql == bootstrap.INSERT_ROLE:
                raise StackError('synthetic loss')
            return self.query(settings, sql, params)
        with self.assertRaises(StackError):
            bootstrap.initialize(self.settings, self.generated, query)
        self.assertEqual(len(calls), 3)
        self.assertEqual(self.db.execute('SELECT count(*) FROM user_role').fetchone()[0], 0)

    def test_invalid_password_and_email_fail_closed(self):
        for password in [None, '', 'weak', 'a' * 80, 'onlylowercase123!', 'Upperlower123\n']:
            with self.assertRaises(StackError):
                bootstrap.validate('fixture@gmail.com', password)
        bootstrap.validate('fixture@gmail.com', 'Synthetic-Only!42')
        with self.assertRaises(StackError):
            bootstrap.validate('other@example.com', 'Synthetic-Only!42')

    def test_helper_suppresses_errors_and_limits_environment(self):
        from types import SimpleNamespace
        with patch.dict(os.environ, {'CLOUDFLARE_API_TOKEN': 'private-value', 'ADMIN_BOOTSTRAP_PASSWORD': 'private-value'}), \
                patch.object(bootstrap.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout=b'private-value', stderr=b'private-value')) as run:
            with self.assertRaisesRegex(StackError, '^Administrator material generation failed$'):
                bootstrap.material(Path('release'), 'Synthetic-Only!42')
            self.assertNotIn('private-value', str(run.call_args.kwargs['env']))
            self.assertNotIn('Synthetic-Only!42', str(run.call_args.args))
