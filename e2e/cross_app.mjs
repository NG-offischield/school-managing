// Cross-application integration run (TEST backend only): the 11 scenarios of
// docs/integration-matrix.md played over the REAL network — REST + WebSocket on
// the PC's LAN address, exactly what the phones and the admin desktop use.
//
// Nothing is hardcoded: the API address, the password and the fixture come from
// the environment (see e2e/README.md).
//
//   E2E_API_URL   http://<LAN IP of the PC>:<port>   (no trailing /api/v1)
//   DEMO_PASSWORD password of the DEMO accounts and of the fixture's accounts
//   E2E_FIXTURE   JSON file printed by backend/tools/e2e_cross_app_fixture.py
//   E2E_ADMIN     DEMO administrator login (default demo.admin)
//
// Prints one line per check (PASS / FAIL / GAP) and a summary; exits 1 on any FAIL.
// GAP = behaviour not provided by the product today, reported, never hidden.
import fs from 'node:fs';

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
// The fixture's output may start with the Django shell banner: the JSON is its last `{` line.
// Windows PowerShell 5.1 `>` writes UTF-16 (BOM FF FE): both encodings are read.
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
const device = (name) => ({ identifier: `e2e-${name}`, device_name: `E2E ${name}`, device_type: 'PHONE', platform: 'ANDROID' });
async function login(identifier, name) {
  const r = await call(null, 'POST', 'auth/login/', { identifier, password: PW, device: device(name) });
  if (r.status !== 200) throw new Error(`login ${identifier}: ${r.status} ${JSON.stringify(r.json?.error)}`);
  return { access: r.data.access_token, refresh: r.data.refresh_token };
}
const memberOf = async (token) => (await call(token, 'GET', 'auth/me/')).data.memberships[0].id;
async function rows(token, path) {
  const r = await call(token, 'GET', path + (path.includes('?') ? '&' : '?') + 'page_size=100');
  return { status: r.status, rows: Array.isArray(r.data) ? r.data : [] };
}

// Live connection: first-frame auth (no custom header, as on a phone), every frame recorded.
function live(token, name, since) {
  const frames = [];
  const ws = new WebSocket(WS);
  const state = { closeCode: null, ws, frames, name };
  ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token }));
  ws.onmessage = (event) => {
    const frame = JSON.parse(event.data);
    frames.push(frame);
    if (frame.type === 'auth.ok') ws.send(JSON.stringify({ type: 'sync', ...(since ? { since } : {}) }));
  };
  ws.onclose = (event) => {
    state.closeCode = event.code;
  };
  state.wait = async (predicate, ms = 10000) => {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const hit = frames.find(predicate);
      if (hit) return hit;
      await sleep(100);
    }
    return null;
  };
  state.close = () => ws.close();
  return state;
}
const notif = (type, extra = () => true) => (f) => f.type === 'notification' && f.data?.notification_type === type && extra(f.data);
const about = (key, id) => (data) => data?.payload?.[key] === id;

// --- accounts -------------------------------------------------------------------------------------
console.log(`API ${B}\nWS  ${WS}\n`);
const admin = await login(ADMIN, 'admin');
const other = await login(fx.other_admin_login, 'test01');
const parentA = await login('parent.a@demo-ecole.test', 'parentA');
const parentB = await login('parent.b@demo-ecole.test', 'parentB');
const teacher = await login(fx.teacher_login, 'teacher');
const guardian = await login(fx.guardian_login, 'guardian');
const staff = await login(fx.staff_login, 'staff');
const memberA = await memberOf(parentA.access);
const memberD = await memberOf((await login('parent.d@demo-ecole.test', 'parentD-id')).access);
check('AUTH', `login of admin, parent, teacher, guardian, staff (${fx.school}) and ${fx.other_school} admin`, true);

const wsAdmin = live(admin.access, 'admin');
const wsA = live(parentA.access, 'parentA');
const wsTeacher = live(teacher.access, 'teacher');
const wsStaff = live(staff.access, 'staff');
const wsGuardian = live(guardian.access, 'guardian');
const wsOther = live(other.access, 'test01');
const sockets = [wsAdmin, wsA, wsTeacher, wsStaff, wsGuardian, wsOther];
const oks = await Promise.all(sockets.map((s) => s.wait((f) => f.type === 'auth.ok')));
check('WS', 'auth.ok for the 6 live connections', oks.every(Boolean), sockets.filter((_, i) => !oks[i]).map((s) => s.name).join(' '));
const bad = live('not-a-token', 'bad');
await sleep(1500);
check('WS', 'invalid token refused (close 4401)', bad.closeCode === 4401, `close=${bad.closeCode}`);

// --- S1 announcement -> parent --------------------------------------------------------------------
const space = await call(admin.access, 'POST', 'admin/forum/spaces/', {
  name: `Vie de l'école ${stamp()}`,
  audience: 'SCHOOL',
  roles: ['PARENT', 'TEACHER', 'STAFF'],
});
const ann = await call(admin.access, 'POST', 'forum/threads/', {
  space: space.data?.id,
  title: 'Réunion des parents',
  body: 'Vendredi 17 h, salle polyvalente.',
  thread_type: 'ANNOUNCEMENT',
});
check('S1', 'admin publishes an announcement in a school space', space.status === 201 && ann.status === 201, `${space.status}/${ann.status}`);
check('S1', 'parent A receives it live', !!(await wsA.wait(notif('ANNOUNCEMENT', about('thread', ann.data?.id)))));
check('S1', 'teacher and staff receive it live', !!(await wsTeacher.wait(notif('ANNOUNCEMENT'))) && !!(await wsStaff.wait(notif('ANNOUNCEMENT'))));
const offB = (await rows(parentB.access, 'notifications/')).rows.some((n) => n.payload?.thread === ann.data?.id);
check('S1', 'parent B (offline) finds it with GET /notifications/', offB);

// --- S2 parent reads the forum and replies --------------------------------------------------------
const topic = await call(admin.access, 'POST', 'forum/threads/', {
  space: space.data?.id,
  title: 'Kermesse de décembre',
  body: 'Qui peut tenir un stand ?',
});
check('S2', 'admin opens a discussion', topic.status === 201, `${topic.status}`);
check('S2', 'parent A notified live of the new discussion (FORUM)', !!(await wsA.wait(notif('FORUM', about('thread', topic.data?.id)))));
const listed = (await rows(parentA.access, `forum/threads/?space=${space.data?.id}`)).rows.some((t) => t.id === topic.data?.id);
const posts = await rows(parentA.access, `forum/threads/${topic.data?.id}/posts/`);
check('S2', 'parent A lists the space and reads the discussion', listed && posts.rows.length === 1);
const readOnly = await call(parentA.access, 'POST', `forum/threads/${ann.data?.id}/posts/`, { body: 'Merci' });
check('S2', 'an announcement stays read-only for a parent (403)', readOnly.status === 403, `${readOnly.status}`);
const reply = await call(parentA.access, 'POST', `forum/threads/${topic.data?.id}/posts/`, { body: 'Je tiens le stand de jus.' });
check('S2', 'parent A replies', reply.status === 201, `${reply.status}`);

// --- S3 admin sees the reply and moderates --------------------------------------------------------
check('S3', 'admin (author) notified live of the reply', !!(await wsAdmin.wait(notif('FORUM', about('post', reply.data?.id)))));
const adminPosts = (await rows(admin.access, `forum/threads/${topic.data?.id}/posts/`)).rows;
check('S3', 'admin reads the reply (GET, as the desktop does)', adminPosts.some((p) => p.id === reply.data?.id && p.body));
const off = await call(parentB.access, 'POST', `forum/threads/${topic.data?.id}/posts/`, { body: 'Message hors sujet' });
const moderated = await call(admin.access, 'DELETE', `forum/posts/${off.data?.id}/`, { reason: 'Hors sujet' });
const hidden = (await rows(parentA.access, `forum/threads/${topic.data?.id}/posts/`)).rows.find((p) => p.id === off.data?.id);
check('S3', 'admin moderates a post with a reason; members see it removed', moderated.status === 200 && hidden?.deleted_at && !hidden?.body, `${moderated.status}`);
const lock = await call(admin.access, 'POST', `admin/forum/threads/${topic.data?.id}/status/`, { status: 'LOCKED', reason: 'Inscriptions closes' });
const late = await call(parentA.access, 'POST', `forum/threads/${topic.data?.id}/posts/`, { body: 'Encore moi' });
const lateRule = late.json?.error?.details?.rule;
check('S3', 'admin locks the discussion; a reply is then refused (409 thread_locked)', lock.status === 200 && late.status === 409 && lateRule === 'thread_locked', `${lock.status}/${late.status} ${lateRule}`);

// --- S4 teacher scope -----------------------------------------------------------------------------
const contacts = await call(teacher.access, 'GET', 'teacher/contacts/');
const pupils = new Set((contacts.data ?? []).map((p) => p.student));
check('S4', 'teacher contacts = pupils of 6e A only (S1 yes, S4 of 3e B no)', contacts.status === 200 && pupils.has(fx.s1) && !pupils.has(fx.s4), `${contacts.status} ${pupils.size} pupils`);
const parentContacts = await call(parentA.access, 'GET', 'teacher/contacts/');
check('S4', 'a parent cannot use the teacher directory (403)', parentContacts.status === 403, `${parentContacts.status}`);
const classSpace = await call(admin.access, 'POST', 'admin/forum/spaces/', { name: `6e A ${stamp()}`, audience: 'CLASS', school_class: fx.class_6a });
const classTopic = await call(teacher.access, 'POST', 'forum/threads/', { space: classSpace.data?.id, title: 'Sortie au musée', body: 'Autorisations à rendre lundi.' });
check('S4', 'teacher opens a discussion in the 6e A class space', classSpace.status === 201 && classTopic.status === 201, `${classSpace.status}/${classTopic.status}`);
check('S4', 'parent A (child in 6e A) notified live', !!(await wsA.wait(notif('FORUM', about('thread', classTopic.data?.id)))));
const otherClass = await call(admin.access, 'POST', 'admin/forum/spaces/', { name: `3e B ${stamp()}`, audience: 'CLASS', school_class: fx.class_3b });
const noAccess = await call(teacher.access, 'POST', 'forum/threads/', { space: otherClass.data?.id, title: 'x', body: 'x' });
check('S4', 'teacher cannot write in the 3e B space (not their class)', [403, 404].includes(noAccess.status), `${noAccess.status}`);

// --- S5 teacher contacts a parent -----------------------------------------------------------------
const ptc = await call(teacher.access, 'POST', 'conversations/', {
  conversation_type: 'PARENT_TEACHER',
  participants: [memberA],
  student: fx.s1,
  title: 'Suivi de Léa',
  body: 'Bonjour, Léa a très bien progressé ce mois-ci.',
  client_id: `e2e-${stamp()}`,
});
check('S5', 'teacher writes to parent A about S1', ptc.status === 201, `${ptc.status} ${JSON.stringify(ptc.json?.error ?? '')}`);
check('S5', 'parent A notified live (MESSAGE)', !!(await wsA.wait(notif('MESSAGE', about('conversation', ptc.data?.id)))));
const seen = (await rows(parentA.access, 'conversations/')).rows.some((c) => c.id === ptc.data?.id);
const answer = await call(parentA.access, 'POST', `conversations/${ptc.data?.id}/messages/`, { body: 'Merci beaucoup !', client_id: `e2e-${stamp()}` });
check('S5', 'parent A sees the conversation and answers', seen && answer.status === 201, `${answer.status}`);
check('S5', 'teacher notified live of the answer', !!(await wsTeacher.wait(notif('MESSAGE', about('conversation', ptc.data?.id)))));
const outOfScope = await call(teacher.access, 'POST', 'conversations/', {
  conversation_type: 'PARENT_TEACHER',
  participants: [memberD],
  student: fx.s4,
  body: 'x',
  client_id: `e2e-${stamp()}`,
});
check('S5', 'teacher refused about a pupil they do not teach (S4, 403)', outOfScope.status === 403, `${outOfScope.status}`);

// --- S8 payment -> finance -> admin -----------------------------------------------------------------
const lea = fx.s1;
const obligations = (await call(parentA.access, 'GET', `finance/students/${lea}/obligations/`)).data;
const wallet = (await rows(parentA.access, 'finance/wallets/')).rows[0];
const invoice = obligations?.open_invoices?.[0];
if (!invoice || !wallet) {
  check('S8', 'parent A has an open invoice and a wallet (DEMO)', false, 'reseed DEMO: nothing left to pay');
} else {
  const pay = await call(parentA.access, 'POST', 'finance/payments/', {
    student: lea,
    amount: invoice.balance_due,
    payment_method: 'WALLET',
    wallet: wallet.id,
    invoices: [invoice.id],
    idempotency_key: `e2e-pay-${stamp()}`,
  });
  check('S8', 'parent A pays an invoice', pay.status === 201 && pay.data?.status === 'SUCCEEDED', `${pay.status} ${pay.data?.status}`);
  check('S8', 'parent A notified live (PAYMENT)', !!(await wsA.wait(notif('PAYMENT'))));
  const adminPay = (await rows(admin.access, `finance/payments/?student=${lea}`)).rows.find((p) => p.id === pay.data?.id);
  const adminInvoice = (await call(admin.access, 'GET', `finance/invoices/${invoice.id}/`)).data;
  check('S8', 'admin Finance sees the payment and the PAID invoice', adminPay?.status === 'SUCCEEDED' && adminInvoice?.status === 'PAID');
  check('S8', 'admin notified of the payment', (await wsAdmin.wait(notif('PAYMENT'), 2000)) ? true : 'GAP', 'payments notify the payer; the school sees them in Finance');
}

// --- S9 planning change ---------------------------------------------------------------------------
const cancel = await call(admin.access, 'POST', `admin/sessions/${fx.session}/cancel/`, { reason: 'Formation des enseignants' });
check('S9', "admin cancels tomorrow's 6e A session", cancel.status === 200, `${cancel.status} ${JSON.stringify(cancel.json?.error ?? '')}`);
check('S9', 'parent A (6e A) notified live', !!(await wsA.wait(notif('SCHEDULE_CHANGE'))));
check('S9', 'teacher notified live', !!(await wsTeacher.wait((f) => f.type === 'notification' && ['SCHEDULE_CHANGE', 'SUBSTITUTION'].includes(f.data?.notification_type))));
const parentD = await login('parent.d@demo-ecole.test', 'parentD');
const offD = (await rows(parentD.access, 'notifications/')).rows.some((n) => n.notification_type === 'SCHEDULE_CHANGE');
check('S9', 'parent D (S5 in 6e A, offline) finds it with GET', offD);

// --- S10 reconnection -----------------------------------------------------------------------------
const lastSeen = [...wsA.frames].reverse().find((f) => f.type === 'notification')?.data?.created_at;
wsA.close();
await sleep(500);
const missed = await call(teacher.access, 'POST', `conversations/${ptc.data?.id}/messages/`, { body: 'Message pendant la coupure', client_id: `e2e-${stamp()}` });
const back = live(parentA.access, 'parentA-back', lastSeen);
const synced = await back.wait((f) => f.type === 'sync');
const recovered = (synced?.notifications ?? []).some((n) => n.notification_type === 'MESSAGE' && n.created_at > lastSeen);
check('S10', 'missed notification delivered by the sync frame after reconnection', missed.status === 201 && recovered);
back.ws.send(JSON.stringify({ type: 'subscribe', conversation: ptc.data?.id, since: lastSeen }));
const sub = await back.wait((f) => f.type === 'subscribed');
check('S10', 'missed message delivered by subscribe(since)', (sub?.messages ?? []).some((m) => m.body === 'Message pendant la coupure'));

// --- S6 staff receives only what concerns it ------------------------------------------------------
const staffNotes = wsStaff.frames.filter((f) => f.type === 'notification').map((f) => f.data);
check('S6', 'staff got the school announcement', staffNotes.some((n) => n.notification_type === 'ANNOUNCEMENT'));
// Member of the school space: told of its NEW discussion (validated rule), nothing more.
check('S6', "staff told of the school space's new discussion", staffNotes.some((n) => n.notification_type === 'FORUM' && n.payload?.thread === topic.data?.id && !n.payload?.post));
const leaked = staffNotes.filter(
  (n) =>
    ['MESSAGE', 'PAYMENT', 'SCHEDULE_CHANGE', 'COMPLAINT'].includes(n.notification_type) ||
    (n.notification_type === 'FORUM' && (n.payload?.post || n.payload?.thread !== topic.data?.id)),
);
check('S6', 'staff got no reply, class-space, message, payment or planning notification', leaked.length === 0, leaked.map((n) => `${n.notification_type}:${n.title}`).join(' | '));

// --- S7 guardian has no forum -----------------------------------------------------------------------
const gSpaces = await call(guardian.access, 'GET', 'forum/spaces/');
const gThreads = await call(guardian.access, 'GET', `forum/threads/?space=${space.data?.id}`);
check('S7', 'guardian: no forum space, no thread', gSpaces.status === 200 && (gSpaces.data ?? []).length === 0 && (gThreads.data ?? []).length === 0, `${gSpaces.status}/${gThreads.status}`);
const gPost = await call(guardian.access, 'POST', 'forum/threads/', { space: space.data?.id, title: 'x', body: 'x' });
const gMsg = await call(guardian.access, 'POST', 'conversations/', { conversation_type: 'ADMINISTRATION', body: 'x', client_id: `e2e-${stamp()}` });
check('S7', 'guardian cannot post in the forum nor message', [403, 404].includes(gPost.status) && gMsg.status === 403, `${gPost.status}/${gMsg.status}`);
const gTypes = wsGuardian.frames.filter((f) => f.type === 'notification').map((f) => f.data?.notification_type);
check('S7', 'guardian received no forum / announcement / message notification', gTypes.length === 0, gTypes.join(' '));

// --- S11 DEMO <-> TEST01 ----------------------------------------------------------------------------
const otherConversations = (await rows(other.access, 'conversations/')).rows;
check('S11', `${fx.other_school} sees none of DEMO's conversations`, otherConversations.length === 0, `${otherConversations.length}`);
const otherStudent = await call(other.access, 'GET', `students/${lea}/`);
check('S11', `${fx.other_school}: a DEMO pupil does not exist (404)`, otherStudent.status === 404, `${otherStudent.status}`);
const cross = await call(other.access, 'POST', 'conversations/', { conversation_type: 'ADMINISTRATION', participants: [memberA], body: 'x', client_id: `e2e-${stamp()}` });
check('S11', `${fx.other_school} cannot write to a DEMO parent`, [403, 404].includes(cross.status), `${cross.status}`);
const otherThreads = (await rows(other.access, 'forum/threads/')).rows.length;
const otherSpaces = (await call(other.access, 'GET', 'forum/spaces/')).data ?? [];
check('S11', `${fx.other_school} sees no DEMO forum space or thread`, otherThreads === 0 && !otherSpaces.some((s) => s.id === space.data?.id), `${otherThreads}`);
const otherFrames = wsOther.frames.filter((f) => f.type === 'notification');
check('S11', `${fx.other_school}'s live connection received no DEMO event`, otherFrames.length === 0, `${otherFrames.length}`);

// --- sessions ---------------------------------------------------------------------------------------
const refreshed = await call(null, 'POST', 'auth/refresh/', { refresh_token: parentB.refresh });
check('AUTH', 'refresh token gives a new access token', refreshed.status === 200 && !!refreshed.data?.access_token);
const wsB = live(refreshed.data.access_token, 'parentB');
await wsB.wait((f) => f.type === 'auth.ok');
await call(refreshed.data.access_token, 'POST', 'auth/logout/');
const end = Date.now() + 40000;
while (wsB.closeCode === null && Date.now() < end) {
  if (wsB.ws.readyState === 1) wsB.ws.send(JSON.stringify({ type: 'ping' }));
  await sleep(1000);
}
check('AUTH', 'logout closes the live connection (4401, within 30 s)', wsB.closeCode === 4401, `close=${wsB.closeCode}`);
const revoked = await call(refreshed.data.access_token, 'GET', 'auth/me/');
check('AUTH', 'revoked access token refused by REST (401)', revoked.status === 401, `${revoked.status}`);

for (const s of [wsAdmin, wsTeacher, wsStaff, wsGuardian, wsOther, back]) s.close();
const fails = results.filter((r) => r[2] === false).length;
const gaps = results.filter((r) => r[2] === 'GAP').length;
console.log(`\n${results.length} checks: ${results.length - fails - gaps} PASS, ${fails} FAIL, ${gaps} GAP`);
process.exit(fails ? 1 : 0);
