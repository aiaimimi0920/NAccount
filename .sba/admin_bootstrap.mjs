import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
import { randomBytes } from 'node:crypto';

// Only this bounded stdin consumes a deployment password. Never log input or
// dependency exceptions; output contains only generated password/OTP material.
try {
  let data = '';
  for await (const part of process.stdin) { data += part; if (Buffer.byteLength(data) > 256) throw new Error(); }
  const { password } = JSON.parse(data);
  const require = createRequire(join(process.argv[2], 'package.json'));
  const bcrypt = require('bcryptjs'), { isStrongPassword } = require('class-validator');
  const base32 = (await import(pathToFileURL(require.resolve('base32-encode')).href)).default;
  if (typeof password !== 'string' || Buffer.byteLength(password) > 72 || !isStrongPassword(password, { minLength: 12 })) throw new Error();
  process.stdout.write(JSON.stringify({ hash: bcrypt.hashSync(password, 12), otp: base32(randomBytes(20), 'RFC4648') }));
} catch { process.stderr.write('ADMIN_BOOTSTRAP_MATERIAL_FAILED\n'); process.exitCode = 1; }
