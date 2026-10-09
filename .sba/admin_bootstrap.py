"""首次新用户初始化；不覆盖已有用户，不把部署密码发布成 Worker secret。"""
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from stack import StackError


def validate(email, password):
    if not isinstance(email, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._%+\-]{0,63}@gmail\.com', email):
        raise StackError('Invalid administrator email')
    if not isinstance(password, str) or len(password) < 12 or not 12 <= len(password.encode('utf-8')) <= 72 or any(
            not re.search(pattern, password) for pattern in (r'[a-z]', r'[A-Z]', r'[0-9]', r'[^a-zA-Z0-9\s]')) or re.search(r'[\x00-\x1f\x7f]', password):
        raise StackError('Invalid administrator password')


def material(release: Path, password: str):
    source = release / 'source' / 'server'
    # npm/build/Cloudflare credentials are unnecessary for the isolated helper.
    env = {key: value for key, value in os.environ.items() if key.upper() in
           {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATHEXT', 'COMSPEC'}}
    result = subprocess.run(['node', str(Path(__file__).with_suffix('.mjs')), str(source)],
                            cwd=source, env=env, input=json.dumps({'password': password}, ensure_ascii=False).encode('utf-8'),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
    if result.returncode or len(result.stdout) > 512:
        raise StackError('Administrator material generation failed')
    try:
        value = json.loads(result.stdout)
        if set(value) != {'hash', 'otp'} or not re.fullmatch(r'\$2[aby]\$12\$[./A-Za-z0-9]{53}', value['hash']) or not re.fullmatch(r'[A-Z2-7]{32}', value['otp']):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise StackError('Administrator material generation failed') from None
    return value


INSERT_USER = """INSERT INTO user (authId,email,password,locale,otpSecret,orgSlug)
SELECT ?,?,?,?,?,'' WHERE NOT EXISTS (SELECT 1 FROM user WHERE lower(trim(email))=?)
AND (SELECT count(*) FROM role WHERE name='super_admin' AND deletedAt IS NULL)=1"""
INSERT_ROLE = """INSERT INTO user_role(userId,roleId)
SELECT u.id,r.id FROM user u CROSS JOIN role r WHERE u.authId=? AND u.deletedAt IS NULL
AND r.name='super_admin' AND r.deletedAt IS NULL"""
READ_BACK = """SELECT u.email,u.emailVerified,u.otpVerified,u.mfaTypes,u.orgSlug,r.name AS role
FROM user u JOIN user_role ur ON ur.userId=u.id AND ur.deletedAt IS NULL
JOIN role r ON r.id=ur.roleId AND r.deletedAt IS NULL WHERE u.authId=? AND u.deletedAt IS NULL"""


def initialize(settings, generated, query):
    email = settings['admin']['bootstrapEmail']
    identity = str(uuid.uuid4())
    query(settings, INSERT_USER, [identity, email, generated['hash'], 'en', generated['otp'], email])
    # These two REST writes are not claimed to be a transaction. Any collision,
    # partial write or lost reply stops deployment as unknown; never retry or
    # promote a pre-existing email. The role selects only our fresh random UUID.
    rows = query(settings, 'SELECT authId FROM user WHERE authId=?', [identity])
    if rows != [{'authId': identity}]:
        raise StackError('Administrator creation unconfirmed or email already exists')
    query(settings, INSERT_ROLE, [identity])
    expected = [{'email': email, 'emailVerified': 0, 'otpVerified': 0, 'mfaTypes': '', 'orgSlug': '', 'role': 'super_admin'}]
    if query(settings, READ_BACK, [identity]) != expected:
        raise StackError('Administrator role initialization unconfirmed')
    return {'id': 'administrator-initialized', 'passed': True}
