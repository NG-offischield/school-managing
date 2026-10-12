// School plans over the REAL network (TEST backend only): import, publication,
// distribution (AUTO / MANUAL), download, notifications and multi-school
// isolation — REST + WebSocket on the PC's LAN address, what the phones and the
// admin desktop use. Same environment as cross_app.mjs (see e2e/README.md):
//
//   E2E_API_URL   http://<LAN IP of the PC>:<port>   (no trailing /api/v1)
//   DEMO_PASSWORD password of the DEMO accounts and of the fixture's accounts
//   E2E_FIXTURE   JSON file printed by backend/tools/e2e_cross_app_fixture.py
//   E2E_ADMIN     DEMO administrator login (default demo.admin)
//
// The plan files are GENERATED here (a drawn PNG, a one-page PDF): no real
// school plan is used or stored. Prints PASS / FAIL per check; exits 1 on any FAIL.
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
const WS = `${ROOT.replace(/^http/, 'ws')}/ws/v1/realtime/`;
if (/\/\/(localhost|127\.|\[::1\])/.test(ROOT)) {
  console.warn('WARNING: loopback address — this does not test the LAN path the phones use.');
}

const results = [];
const check = (id, label, ok, detail = '') => {
  results.push([id, label, ok]);
  console.log(`${ok === true ? 'PASS' : ok === false ? 'FAIL' : ok} ${id} ${label}${detail ? ` — ${detail}` : ''}`);
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const stamp = () => `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');

async function call(token, method, path, body) {
  const res = await fetch(B + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let json = null;
  try {
    json = await res.json();
  } catch {
    /* empty body */
  }
  return { status: res.status, data: json?.data, json };
}
async function upload(token, path, name, bytes, type) {
  const form = new FormData();
  form.append('file', new Blob([bytes], { type }), name);
  const res = await fetch(B + path, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form });
  const json = await res.json().catch(() => null);
  return { status: res.status, data: json?.data, json };
}
// Exactly what school_core ApiClient.download sends.
async function download(token, path) {
  const res = await fetch(B + path, {
    headers: { Accept: 'application/pdf, application/json', Authorization: `Bearer ${token}` },
  });
  return { status: res.status, headers: res.headers, bytes: Buffer.from(await res.arrayBuffer()) };
}
const device = (name) => ({ identifier: `e2e-plan-${name}`, device_name: `E2E ${name}`, device_type: 'PHONE', platform: 'ANDROID' });
async function login(identifier, name) {
  const r = await call(null, 'POST', 'auth/login/', { identifier, password: PW, device: device(name) });
  if (r.status !== 200) throw new Error(`login ${identifier}: ${r.status} ${JSON.stringify(r.json?.error)}`);
  return r.data.access_token;
}
async function notes(token, type) {
  const r = await call(token, 'GET', `notifications/?type=${type}&page_size=100`);
  return Array.isArray(r.data) ? r.data : [];
}
function live(token, name) {
  const frames = [];
  const ws = new WebSocket(WS);
  const state = { ws, frames, name };
  ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }));
  ws.onmessage = (event) => frames.push(JSON.parse(event.data));
  state.wait = async (predicate, ms = 10000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const hit = frames.find(predicate);
      if (hit) return hit;
      await sleep(100);
    }
    return null;
  };
  return state;
}
const planNote = (versionId) => (f) =>
  f.type === 'notification' && f.data?.notification_type === 'PLAN' && f.data?.payload?.version === versionId;

// --- generated plan files ---------------------------------------------------------------------------
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
  header[8] = 8; // bit depth
  header[9] = 2; // RGB
  const rows = [];
  for (let y = 0; y < height; y++) {
    const row = Buffer.alloc(1 + width * 3, 0xff);
    row[0] = 0;
    for (let x = 0; x < width; x++) {
      const wall = x % 50 < 3 || y % 40 < 3; // a grid of « rooms »
      if (wall) row.fill(0x33, 1 + x * 3, 4 + x * 3);
    }
    rows.push(row);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(Buffer.concat(rows))),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}
function pdf(label) {
  const content = `BT /F1 24 Tf 72 760 Td (${label}) Tj ET 72 100 450 600 re S`;
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  let out = '%PDF-1.4\n';
  const offsets = objects.map((body, i) => {
    const at = out.length;
    out += `${i + 1} 0 obj\n${body}\nendobj\n`;
    return at;
  });
  const xref = out.length;
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  out += offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('');
  out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}

// --- accounts ---------------------------------------------------------------------------------------
console.log(`API ${B}\nWS  ${WS}\n`);
const admin = await login(ADMIN, 'admin');
const other = await login(fx.other_admin_login, 'test01');
const parentA = await login('parent.a@demo-ecole.test', 'parentA');
const teacher = await login(fx.teacher_login, 'teacher');
const guardian = await login(fx.guardian_login, 'guardian');
const staff = await login(fx.staff_login, 'staff');
const wsA = live(parentA, 'parentA');
const wsTeacher = live(teacher, 'teacher');
const wsGuardian = live(guardian, 'guardian');
const wsStaff = live(staff, 'staff');
const wsOther = live(other, 'test01');
const sockets = [wsA, wsTeacher, wsGuardian, wsStaff, wsOther];
const oks = await Promise.all(sockets.map((s) => s.wait((f) => f.type === 'auth.ok')));
check('AUTH', 'admin, parent A, teacher, guardian, staff and the other school logged in; 5 live connections', oks.every(Boolean));

// --- P1 import: refused formats, a draft nobody sees -------------------------------------------------
const created = await call(admin, 'POST', 'admin/plans/', {
  title: `Plan général ${stamp()}`,
  building: 'Bâtiment A',
  floor: 'RDC',
  distribution: 'AUTO',
});
const planId = created.data?.id;
check('P1', 'admin creates a plan (draft, AUTO)', created.status === 201 && created.data?.status === 'DRAFT', `${created.status}`);
const svg = await upload(admin, `admin/plans/${planId}/versions/`, 'plan.svg', Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"/>'), 'image/svg+xml');
const renamed = await upload(admin, `admin/plans/${planId}/versions/`, 'plan.pdf', Buffer.from('MZ\x90\x00 not a pdf'), 'application/pdf');
check(
  'P1',
  'SVG and a renamed file are refused',
  svg.status === 400 && renamed.status === 400,
  `${svg.status} ${svg.json?.error?.details?.rule} / ${renamed.status} ${renamed.json?.error?.details?.rule}`,
);
const pngBytes = png(400, 240);
const v1 = await upload(admin, `admin/plans/${planId}/versions/`, 'plan-rdc.png', pngBytes, 'image/png');
check('P1', 'PNG imported as version 1 (draft, checked by the server)', v1.status === 201 && v1.data?.number === 1 && v1.data?.status === 'DRAFT', `${v1.status} ${v1.data?.width}x${v1.data?.height}`);
const draftList = (await call(parentA, 'GET', 'plans/')).data ?? [];
const draftFile = await download(parentA, `plans/${planId}/file/`);
check('P1', 'a draft is invisible to parent A (not listed, file 404)', !draftList.some((p) => p.id === planId) && draftFile.status === 404, `${draftFile.status}`);

// --- P2 publication (AUTO) -> parents and teachers, never guardian / staff ---------------------------
const pub1 = await call(admin, 'POST', `admin/plans/${planId}/publish/`, { version: v1.data?.id });
check('P2', 'admin publishes version 1', pub1.status === 200 && pub1.data?.status === 'PUBLISHED', `${pub1.status}`);
check('P2', 'parent A notified live (PLAN, this version)', !!(await wsA.wait(planNote(v1.data?.id))));
check('P2', 'teacher notified live', !!(await wsTeacher.wait(planNote(v1.data?.id))));
await sleep(1500);
const leaked = [wsGuardian, wsStaff, wsOther].filter((s) => s.frames.some((f) => f.data?.notification_type === 'PLAN'));
check('P2', 'guardian, staff and the other school receive nothing', leaked.length === 0, leaked.map((s) => s.name).join(' '));

// --- P3 download ------------------------------------------------------------------------------------
const listed = ((await call(parentA, 'GET', 'plans/')).data ?? []).find((p) => p.id === planId);
check('P3', 'parent A lists the plan (version 1, file URL of the API)', listed?.version?.number === 1 && listed?.file_url === `/api/v1/plans/${planId}/file/`);
const fileA = await download(parentA, `plans/${planId}/file/`);
const fileT = await download(teacher, `plans/${planId}/file/`);
check(
  'P3',
  'parent A and teacher download the published file (PNG, sha256 = server version)',
  fileA.status === 200 && fileT.status === 200 && fileA.headers.get('content-type') === 'image/png' && sha256(fileA.bytes) === v1.data?.sha256,
  `${fileA.status}/${fileT.status} ${fileA.headers.get('content-type')}`,
);
check('P3', 'the file is private: Cache-Control no-store', /no-store/.test(fileA.headers.get('cache-control') ?? ''), fileA.headers.get('cache-control'));
const anonymous = await download(null, `plans/${planId}/file/`);
check('P3', 'without a token: refused (401)', anonymous.status === 401, `${anonymous.status}`);
const gFile = await download(guardian, `plans/${planId}/file/`);
const sFile = await download(staff, `plans/${planId}/file/`);
const gList = (await call(guardian, 'GET', 'plans/')).data ?? [];
check('P3', 'guardian and staff: no plan, file refused', [403, 404].includes(gFile.status) && [403, 404].includes(sFile.status) && gList.length === 0, `${gFile.status}/${sFile.status}`);
const parentUpload = await upload(parentA, `admin/plans/${planId}/versions/`, 'x.png', pngBytes, 'image/png');
check('P3', 'a parent cannot manage plans (403)', parentUpload.status === 403, `${parentUpload.status}`);

// --- P4 multi-school isolation ----------------------------------------------------------------------
const oAdmin = await call(other, 'GET', `admin/plans/${planId}/`);
const oFile = await download(other, `plans/${planId}/file/`);
const oList = (await call(other, 'GET', 'admin/plans/')).data ?? [];
check('P4', `${fx.other_school} does not see DEMO's plan (404, not listed)`, oAdmin.status === 404 && oFile.status === 404 && !oList.some((p) => p.id === planId), `${oAdmin.status}/${oFile.status}`);

// --- P5 MANUAL distribution: 6e A parents only --------------------------------------------------------
const audience = await call(admin, 'PUT', `admin/plans/${planId}/audience/`, { entries: [{ target: 'CLASS_PARENTS', school_class: fx.class_6a }] });
const manual = await call(admin, 'PATCH', `admin/plans/${planId}/`, { distribution: 'MANUAL' });
check('P5', 'admin restricts the plan to the parents of 6e A', audience.status === 200 && manual.data?.distribution === 'MANUAL', `${audience.status}/${manual.status}`);
const aStill = await download(parentA, `plans/${planId}/file/`);
const tGone = await download(teacher, `plans/${planId}/file/`);
check('P5', 'parent A (child in 6e A) keeps access; the teacher loses it at once (404)', aStill.status === 200 && tGone.status === 404, `${aStill.status}/${tGone.status}`);
const access = await call(admin, 'GET', `admin/plans/${planId}/access/`);
check('P5', 'admin sees who has access (parents only)', access.status === 200 && access.data?.count > 0 && (access.data?.readers ?? []).every((r) => r.roles.includes('PARENT')), `${access.data?.count}`);
const empty = await call(admin, 'PUT', `admin/plans/${planId}/audience/`, { entries: [] });
check('P5', 'emptying the audience of a published MANUAL plan is refused (409)', empty.status === 409 && empty.json?.error?.details?.rule === 'plan_audience_empty', `${empty.status}`);

// --- P6 new version (PDF): readers of the CURRENT audience notified, once ------------------------------
const v2 = await upload(admin, `admin/plans/${planId}/versions/`, 'plan-rdc-v2.pdf', pdf('Plan RDC v2'), 'application/pdf');
check('P6', 'PDF imported as version 2', v2.status === 201 && v2.data?.number === 2 && v2.data?.page_count === 1, `${v2.status} ${JSON.stringify(v2.json?.error ?? '')}`);
const meta = await call(admin, 'PATCH', `admin/plans/${planId}/`, { title: `${created.data?.title} (rév.)`, building: 'Bâtiment A', floor: 'RDC', description: 'Entrée au nord.' });
const pub2 = await call(admin, 'POST', `admin/plans/${planId}/publish/`, { version: v2.data?.id });
check('P6', 'admin publishes version 2', meta.status === 200 && pub2.status === 200, `${meta.status}/${pub2.status}`);
const updated = await wsA.wait(planNote(v2.data?.id));
check('P6', 'parent A notified live « Plan mis à jour »', !!updated && updated.data.title.startsWith('Plan mis à jour'), updated?.data?.title ?? 'none');
await sleep(1500);
check('P6', 'the teacher (outside the audience) is not notified', !wsTeacher.frames.some(planNote(v2.data?.id)));
const again = await call(admin, 'POST', `admin/plans/${planId}/publish/`, { version: v2.data?.id });
await sleep(1000);
const aNotes = (await notes(parentA, 'PLAN')).filter((n) => n.payload?.plan === planId);
check('P6', 'republishing the same version notifies nobody again; the metadata change notified nobody', again.status === 200 && aNotes.length === 2, `${aNotes.length} PLAN notifications for parent A`);
const pdfA = await download(parentA, `plans/${planId}/file/`);
check('P6', 'parent A now downloads version 2 (PDF), never version 1', pdfA.status === 200 && pdfA.headers.get('content-type') === 'application/pdf' && sha256(pdfA.bytes) === v2.data?.sha256, `${pdfA.headers.get('content-type')}`);

// --- P7 withdrawal --------------------------------------------------------------------------------------
const before = wsA.frames.length;
const withdrawn = await call(admin, 'POST', `admin/plans/${planId}/withdraw/`, { reason: 'Travaux' });
const afterList = (await call(parentA, 'GET', 'plans/')).data ?? [];
const afterFile = await download(parentA, `plans/${planId}/file/`);
check('P7', 'withdrawn: gone at once for parent A (not listed, 404)', withdrawn.status === 200 && !afterList.some((p) => p.id === planId) && afterFile.status === 404, `${withdrawn.status}/${afterFile.status}`);
await sleep(1500);
check('P7', 'a withdrawal notifies nobody', !wsA.frames.slice(before).some((f) => f.data?.notification_type === 'PLAN'));

for (const s of sockets) s.ws.close();
const fails = results.filter((r) => r[2] === false).length;
console.log(`\n${results.length} checks: ${results.length - fails} PASS, ${fails} FAIL`);
process.exit(fails ? 1 : 0);
