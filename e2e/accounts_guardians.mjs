// Self-service accounts and gate guardians over the REAL network (TEST backend
// only): what the phones and the admin desktop do — REST on the PC's LAN
// address. Same environment as cross_app.mjs (see e2e/README.md):
//
//   E2E_API_URL   http://<LAN IP of the PC>:<port>   (no trailing /api/v1)
//   DEMO_PASSWORD password of the DEMO accounts and of the fixture's accounts
//   E2E_FIXTURE   JSON file printed by backend/tools/e2e_cross_app_fixture.py
//   E2E_ADMIN     DEMO administrator login (default demo.admin)
//
// Run it AFTER cross_app.mjs / school_plans.mjs: it changes contact details of
// DEMO accounts and creates a guardian. The photo is GENERATED here (no real
// face). Prints PASS / FAIL per check; exits 1 on any FAIL.
import crypto from 'node:crypto';
import fs from 'node:fs';
import zlib from 'node:zlib';

const env = (name, fallback) => {
  const value = process.env[name] ?? fallback;
  if (!value) {
    console.error(`Missing environment variable ${name} (see e2e/README.md).`);
    process.exit(2);
  }
  return value;
};
const ROOT = env('E2E_API_URL').replace(/\/+$/, '').replace(/\/api\/v1$/, '');
const PW = env('DEMO_PASSWORD');
const raw = fs.readFileSync(env('E2E_FIXTURE'));
const text = raw[0] === 0xff && raw[1] === 0xfe ? raw.toString('utf16le') : raw.toString('utf8');
const fx = JSON.parse(
  text
    .replace(/^﻿/, '')
    .split(/\r?\n/)
    .filter((line) => line.startsWith('{'))
    .pop() ?? 'null',
);
const ADMIN = env('E2E_ADMIN', 'demo.admin');
const B = `${ROOT}/api/v1/`;
if (/\/\/(localhost|127\.|\[::1\])/.test(ROOT)) {
  console.warn('WARNING: loopback address — this does not test the LAN path the phones use.');
}

const results = [];
const check = (id, label, ok, detail = '') => {
  results.push([id, label, ok]);
  console.log(`${ok === true ? 'PASS' : 'FAIL'} ${id} ${label}${detail ? ` — ${detail}` : ''}`);
};
const stamp = () => `${Date.now()}${Math.random().toString(36).slice(2, 6)}`;

async function call(token, method, path, body) {
  const res = await fetch(B + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => null);
  return { status: res.status, data: json?.data, json };
}
async function upload(token, path, field, name, bytes) {
  const form = new FormData();
  form.append(field, new Blob([bytes]), name);
  const res = await fetch(B + path, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form });
  const json = await res.json().catch(() => null);
  return { status: res.status, data: json?.data, json };
}
async function bytes(token, path) {
  const res = await fetch(B + path, { headers: { Accept: 'application/pdf, application/json', Authorization: `Bearer ${token}` } });
  return { status: res.status, headers: res.headers, body: Buffer.from(await res.arrayBuffer()) };
}
const device = (name) => ({ identifier: `e2e-acc-${name}`, device_name: `E2E ${name}`, device_type: 'PHONE', platform: 'ANDROID' });
async function login(identifier, name, password = PW) {
  const r = await call(null, 'POST', 'auth/login/', { identifier, password, device: device(name) });
  if (r.status !== 200) throw new Error(`login ${identifier}: ${r.status} ${JSON.stringify(r.json?.error)}`);
  return r.data.access_token;
}

// A real PNG with EXIF-like text metadata (tEXt chunk): the server must drop it.
const crcTable = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
const crc32 = (buf) => {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
};
function png(width, height) {
  const chunk = (type, data) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type), data]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(body));
    return Buffer.concat([len, body, crc]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const rows = [];
  for (let y = 0; y < height; y++) {
    const row = Buffer.alloc(1 + width * 3, 0x80);
    row[0] = 0;
    rows.push(row);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('tEXt', Buffer.from('Author\0Telephone de Paul, GPS 3.86N 11.52E')),
    chunk('IDAT', zlib.deflateSync(Buffer.concat(rows))),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

console.log(`API ${B}\n`);
const admin = await login(ADMIN, 'admin');
const other = await login(fx.other_admin_login, 'test01');
const parentA = await login('parent.a@demo-ecole.test', 'parentA');
const teacher = await login(fx.teacher_login, 'teacher');
const staff = await login(fx.staff_login, 'staff');
check('AUTH', 'admin, parent, teacher, staff and the other school logged in', true);

// --- A1 profile: each role edits only its own contact details ---------------------------------
const editable = async (token) => (await call(token, 'GET', 'auth/me/profile/')).data?.editable ?? [];
const [pe, te, se, ae] = await Promise.all([editable(parentA), editable(teacher), editable(staff), editable(admin)]);
check('A1', 'editable fields decided by the server per role', pe.includes('occupation') && te.includes('address') && !te.includes('occupation') && se.includes('address') && ae.includes('phone'), `parent=${pe} teacher=${te}`);
const phone = '699 55 44 33';
const saved = await call(parentA, 'PATCH', 'auth/me/profile/', { phone, occupation: 'Infirmière' });
check('A1', 'parent A updates phone and occupation', saved.status === 200 && saved.data?.phone === phone && saved.data?.parent?.occupation === 'Infirmière', `${saved.status}`);
const sneaky = await call(parentA, 'PATCH', 'auth/me/profile/', { phone: '600000000', roles: ['ADMIN'], school_code: fx.other_school, email: 'pirate@x.test' });
const after = (await call(parentA, 'GET', 'auth/me/profile/')).data;
const me = (await call(parentA, 'GET', 'auth/me/')).data;
check(
  'A1',
  'role / school / e-mail in the request: whole request refused (400), nothing applied',
  sneaky.status === 400 && after.phone === phone && after.roles?.join() === 'PARENT' && me.email === 'parent.a@demo-ecole.test',
  `${sneaky.status} ${Object.keys(sneaky.json?.error?.details ?? {})}`,
);
const bad = await call(teacher, 'PATCH', 'auth/me/profile/', { phone: 'abc' });
check('A1', 'invalid phone explained per field (400)', bad.status === 400 && 'phone' in (bad.json?.error?.details ?? {}), `${bad.status}`);

// --- A2 photo -------------------------------------------------------------------------------------
const pic = await upload(staff, 'auth/me/photo/', 'photo', 'moi.png', png(300, 300));
const got = await bytes(staff, 'auth/me/photo/');
check('A2', 'staff photo uploaded, re-encoded JPEG, metadata gone, private', pic.status === 200 && got.status === 200 && got.headers.get('content-type') === 'image/jpeg' && !got.body.includes('GPS') && /no-store/.test(got.headers.get('cache-control') ?? ''), `${pic.status}/${got.status}`);
const someoneElse = await bytes(parentA, 'auth/me/photo/');
check('A2', "another member asking for « my photo » never gets the staff member's", someoneElse.status === 404 || crypto.createHash('sha256').update(someoneElse.body).digest('hex') !== crypto.createHash('sha256').update(got.body).digest('hex'), `${someoneElse.status}`);
const fake = await upload(staff, 'auth/me/photo/', 'photo', 'x.jpg', Buffer.from('MZ not an image'));
check('A2', 'a non-image is refused (photo_invalid)', fake.status === 400 && fake.json?.error?.details?.rule === 'photo_invalid', `${fake.status}`);
const anon = await bytes(null, 'auth/me/photo/');
check('A2', 'without a token: 401', anon.status === 401, `${anon.status}`);

// --- G1 guardian created by the admin, activated by the person -------------------------------------
const number = `G-E2E-${stamp()}`.slice(0, 40);
const email = `gardien.${stamp()}@e2e.test`;
const created = await call(admin, 'POST', 'admin/guardians/', { first_name: 'Gardien', last_name: 'E2E', email, guardian_number: number });
check('G1', 'admin creates a guardian (no password)', created.status === 201 && created.data?.activated === false, `${created.status}`);
const dup = await call(admin, 'POST', 'admin/guardians/', { first_name: 'X', last_name: 'Y', email: `x.${stamp()}@e2e.test`, guardian_number: number });
check('G1', 'same guardian number refused (409)', dup.status === 409, `${dup.status}`);
const code = (await call(admin, 'POST', `admin/accounts/${created.data?.membership}/activation/`)).data?.code;
const newPw = `Portail-${stamp()}!`;
const activated = await call(null, 'POST', 'auth/activation/complete/', { code, password: newPw });
check('G1', 'the person activates the account with the code (public endpoint)', activated.status === 200, `${activated.status}`);
const guardian = await login(email, 'guardian', newPw);
check('G1', 'the new guardian logs in', !!guardian);
const outsider = await call(other, 'GET', `admin/guardians/${created.data?.id}/`);
const notAdmin = await call(teacher, 'GET', 'admin/guardians/');
check('G1', `${fx.other_school} admin: 404; a teacher: 403`, outsider.status === 404 && notAdmin.status === 403, `${outsider.status}/${notAdmin.status}`);

// --- G2 scan, then the admin's views ------------------------------------------------------------------
const qr = (await call(admin, 'GET', 'admin/qr-codes/?status=ACTIVE&page_size=1')).data?.[0];
const scan = await call(guardian, 'POST', 'qr/scans/', { token: qr?.token });
check('G2', 'the guardian scans a pupil QR', scan.status === 201 && !!scan.data?.result, `${scan.status} ${scan.data?.result}`);
check('G2', 'the scan answer shows no amount', !/amount|balance|montant|xaf/i.test(JSON.stringify(scan.data ?? {})));
const theirs = (await call(admin, 'GET', `admin/scans/?guardian=${created.data?.id}&page_size=100`)).data ?? [];
check('G2', 'admin lists THIS guardian\'s scans (and only them)', theirs.length === 1 && theirs[0].guardian === created.data?.id && theirs[0].scanned_by_name === 'Gardien E2E', `${theirs.length}`);
const detail = (await call(admin, 'GET', `admin/guardians/${created.data?.id}/`)).data;
check('G2', 'guardian row: activated, one scan today', detail?.activated === true && detail?.scans_today === 1, `${detail?.scans_today}`);
const today = new Date().toISOString().slice(0, 10);
const daily = await call(admin, 'GET', `admin/attendance/daily/?date=${today}&page_size=200`);
const otherDaily = await call(other, 'GET', `admin/attendance/daily/?date=${today}&page_size=200`);
check('G2', `day's attendance listed for the admin; ${fx.other_school} sees none of it`, daily.status === 200 && Array.isArray(daily.data) && (otherDaily.data ?? []).every((r) => !(daily.data ?? []).some((d) => d.id === r.id)), `${daily.status} ${daily.data?.length}`);

// --- G3 suspension / reactivation (existing account endpoints) -----------------------------------------
const off = await call(admin, 'POST', `admin/accounts/${created.data?.membership}/disable/`, { reason: 'Fin de contrat' });
const refused = await call(null, 'POST', 'auth/login/', { identifier: email, password: newPw, device: device('guardian-2') });
const deadToken = await call(guardian, 'POST', 'qr/scans/', { token: qr?.token });
check('G3', 'suspended: login refused and the open session cannot scan', off.status === 200 && refused.status === 401 && deadToken.status === 401, `${off.status}/${refused.status}/${deadToken.status}`);
await call(admin, 'POST', `admin/accounts/${created.data?.membership}/enable/`);
const back = await call(null, 'POST', 'auth/login/', { identifier: email, password: newPw, device: device('guardian-3') });
check('G3', 'reactivated: the guardian logs in again', back.status === 200, `${back.status}`);

// --- P1 password and sessions (on the new guardian account) ---------------------------------------------
const phoneTok = back.data?.access_token;
const tablet = await login(email, 'guardian-tablet', newPw);
const sessions = (await call(phoneTok, 'GET', 'auth/sessions/')).data ?? [];
check('P1', 'two devices listed, this one flagged', sessions.length >= 2 && sessions.filter((s) => s.is_current).length === 1, `${sessions.length}`);
const wrong = await call(phoneTok, 'POST', 'auth/password/change/', { current_password: 'faux', new_password: `Autre-${stamp()}!` });
const newer = `Nouveau-${stamp()}!`;
const changed = await call(phoneTok, 'POST', 'auth/password/change/', { current_password: newPw, new_password: newer });
const tabletAfter = await call(tablet, 'GET', 'auth/me/profile/');
const phoneAfter = await call(phoneTok, 'GET', 'auth/me/profile/');
check('P1', 'password changed: wrong current refused, the OTHER device disconnected, this one kept', wrong.status === 400 && changed.status === 200 && tabletAfter.status === 401 && phoneAfter.status === 200, `${wrong.status}/${changed.status}/${tabletAfter.status}/${phoneAfter.status}`);
const tablet2 = await login(email, 'guardian-tablet-2', newer);
const t2 = (await call(phoneTok, 'GET', 'auth/sessions/')).data?.find((s) => !s.is_current);
const intruder = await call(parentA, 'POST', `auth/sessions/${t2?.id}/revoke/`);
const revoked = await call(phoneTok, 'POST', `auth/sessions/${t2?.id}/revoke/`);
check('P1', "one session revoked by its owner (another member: 404)", intruder.status === 404 && revoked.status === 200 && (await call(tablet2, 'GET', 'auth/me/profile/')).status === 401, `${intruder.status}/${revoked.status}`);

const fails = results.filter((r) => r[2] === false).length;
console.log(`\n${results.length} checks: ${results.length - fails} PASS, ${fails} FAIL`);
process.exit(fails ? 1 : 0);
