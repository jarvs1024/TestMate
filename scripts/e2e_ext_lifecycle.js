#!/usr/bin/env node
/**
 * 扩展库 —— 资产生命周期端到端验收 (2026-11-05 新功能补测).
 *
 * 补的测试缺口:
 *   · POST /extensions/{code}/revert 「恢复在架版本」—— 在架资产发新版本待审期间,
 *     作者放弃这次修改 → DB 回到老版本 / 暂存区清掉 / 不动 git / 不发通知.
 *   · POST /extensions/{code}/copy (连接器 MCP 配置复制计数)
 *   · GET  /extensions/{code}/bundle (前端通道安装用的明文文件清单 + 内容)
 *   · GET  /extensions/{code}/versions/{v}/download 与 .../ticket-download
 *   · GET  /extensions/notifications/preview (管理员预览, 一条都不发)
 *   · GET  /extensions/rules (命名/包后缀/分类规则)
 *   · 异常与越权: 404 / 409 / 422 / 403
 *
 * ⚠️ **硬性约束** (违反会损坏真实数据):
 *   1. 只操作本脚本**自己创建**的资产 (code 带时间戳), 绝不碰真实用户的资产;
 *   2. 测试期间**关掉全部钉钉通知开关**, 结束前**恢复原值** (先读原值再改);
 *   3. 测试账号用完即删 (不新建永久账号);
 *   4. 结束前把自己创建的资产删干净.
 *
 * 用法:
 *   TESTMATE_USER=admin TESTMATE_PASSWORD='Admin@123' node scripts/e2e_ext_lifecycle.js
 *
 * 退出码: 0 = 全部通过, 1 = 有断言失败, 2 = 脚本异常.
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
// ⚠️ 互斥锁: 并行跑 e2e 会互相改生产设置/删资产 (见 e2e_lock.js)
require('./e2e_lock').acquire(__filename);
const { deleteTestUsers } = require('./e2e_cleanup');


const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const API = (process.env.TESTMATE_API || 'http://localhost:18000').replace(/\/$/, '');
const ADMIN = process.env.TESTMATE_USER || 'admin';
const ADMIN_PW = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');

// ---------- 本次跑的唯一标识 (所有资产 code 都带它, 绝不撞真实资产) ----------
const STAMP = Date.now().toString(36);
const CODE = `e2e-ext-lc-${STAMP}`;            // 主资产 (技能)
const CODE_MCP = `e2e-ext-lc-mcp-${STAMP}`;    // 连接器 (mcp)
const NAME = `E2E 生命周期探针 ${STAMP}`;
const NAME_MCP = `E2E 生命周期连接器 ${STAMP}`;
const V1 = '1.0.0';
const V2 = '2.0.0';
const MARK_V1 = `v1-marker-${STAMP}`;
const MARK_V2 = `v2-marker-${STAMP}`;

const PUBLISHER = { username: 'e2e_extlc_pub', password: 'ExtLc@12345' };
const OTHER = { username: 'e2e_extlc_oth', password: 'ExtLc@12345' };  // 同样有发布权, 但不是作者

// ⚠️ 通知开关 —— 测试期间**全部关掉**, 结束前恢复原值 (先读后改, 别写死).
const NOTIFY_SWITCHES = [
  'dingtalk.notify_on_publish', 'dingtalk.notify_on_update',
  'dingtalk.notify_on_unpublish', 'dingtalk.notify_on_delete',
  'dingtalk.notify_on_review', 'dingtalk.notify_on_reject',
  'dingtalk.notify_on_unpublish_request',
  'dingtalk.notify_on_review_failure',
];
// 这次跑会动到的**生产设置** (结束必须还原成原值)
const TOUCHED = [
  ...NOTIFY_SWITCHES,
  'extensions.review.enabled',        // 开审核 —— 发新版本才会进「待审核」
  'extensions.publisher_usernames',   // 把测试发布者加进白名单 (跑完删掉)
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}
/** 环境不具备时跳过 (不计入分母 —— 不能把"没测"记成"测过了") */
function skip(name, why) {
  console.log(`SKIP [${new Date().toISOString().slice(11, 19)}] ${name}  :: ${why}`);
}

// ---------- HTTP 小工具 ----------
async function api(pathname, { method = 'GET', token, body, form } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload;
  if (form) {
    payload = form;
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const r = await fetch(API + pathname, { method, headers, body: payload });
  const text = await r.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* 非 JSON */ }
  return { status: r.status, json, text };
}

/** 下载类端点 —— 要拿到二进制和响应头 */
async function apiRaw(pathname, token) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(API + pathname, { headers });
  const buf = Buffer.from(await r.arrayBuffer());
  return { status: r.status, buf, headers: r.headers, text: buf.toString('utf8') };
}

async function login(username, password) {
  const r = await api('/api/v1/auth/login', {
    method: 'POST', body: { username, password },
  });
  if (r.status !== 200) throw new Error(`登录失败 ${username}: ${r.status} ${r.text}`);
  return r.json.access_token;
}

/**
 * 确保账号存在且口令/角色符合预期 (幂等).
 * ⚠️ 建号端点是 /auth/users (必须管理员先建过才能登录, /auth/register 已下线).
 */
async function ensureUser(token, username, password, role) {
  let r = await api('/api/v1/auth/users', {
    method: 'POST', token, body: { username, password, role },
  });
  if (r.status === 201) return r.json;
  if (r.status !== 409) throw new Error(`建号失败 ${username}: ${r.status} ${r.text}`);
  const list = await api('/api/v1/auth/users', { token });
  const found = (list.json || []).find((u) => u.username === username || u.username === `${username}@twsc.com.cn`);
  if (!found) throw new Error(`账号 ${username} 已存在但列表里找不到`);
  r = await api(`/api/v1/auth/users/${found.id}`, {
    method: 'PATCH', token, body: { password, role, is_active: true },
  });
  if (r.status !== 200) throw new Error(`改账号失败 ${username}: ${r.status} ${r.text}`);
  return r.json;
}

async function setSetting(token, key, value) {
  const r = await api(`/api/v1/settings/${key}`, {
    method: 'PUT', token, body: { value },
  });
  if (r.status !== 200) throw new Error(`设置 ${key} 失败: ${r.status} ${r.text}`);
}

/** 读设置项当前值 (只取指定 key) —— 改之前必须先存住, 结束要还原 */
async function getSettings(token, keys) {
  const r = await api('/api/v1/settings/schema', { token });
  const out = {};
  if (r.status !== 200) return out;
  for (const g of (r.json.groups || [])) {
    for (const it of g.items || []) {
      if (keys.includes(it.key)) out[it.key] = it.value;
    }
  }
  return out;
}

/**
 * 把白名单**追加**几个用户名 (不覆盖别人).
 * ⚠️ 原值可能是 JSON 数组, 也可能是逗号分隔 —— 两种都认 (见 ext_policy.split_list).
 * @param {string} raw 原值 (跑之前读到的)
 * @param {string[]} usernames 要加进去的用户名
 * @returns {string} 写回去的新值
 */
async function addPublisher(token, raw, usernames) {
  const s = String(raw ?? '').trim();
  let names = [];
  if (s.startsWith('[')) {
    try {
      const d = JSON.parse(s);
      if (Array.isArray(d)) names = d.map((x) => String(x).trim()).filter(Boolean);
    } catch { /* 不是合法 JSON → 退化成分隔符切分 */ }
  }
  if (!names.length) {
    names = s.replace(/^[\[\]]/g, '').split(/[,;、，\s]+/).map((x) => x.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
  }
  for (const u of usernames || []) if (!names.includes(u)) names.push(u);
  const next = JSON.stringify(names);
  await setSetting(token, 'extensions.publisher_usernames', next);
  return next;
}

// ---------- 造包 ----------
/** 用 python3 造 zip (macOS 自带) —— 返回字节 */
function makeZipBytes(files, tag) {
  const target = path.join(OUT_DIR, `${CODE}-${tag}.zip`);
  const scriptPath = path.join(OUT_DIR, '_mkzip_lc.py');
  fs.writeFileSync(scriptPath, [
    'import zipfile, json, sys',
    'target = json.loads(sys.argv[1])',
    'files = json.loads(sys.argv[2])',
    'z = zipfile.ZipFile(target, "w")',
    'for name, content in files.items():',
    '    z.writestr(name, content)',
    'z.close()',
    '',
  ].join('\n'));
  execFileSync('python3', [scriptPath, JSON.stringify(target), JSON.stringify(files)]);
  return fs.readFileSync(target);
}

function skillMd(marker) {
  return [
    '---',
    `name: ${CODE}`,
    'description: e2e 生命周期验证用技能',
    '---',
    '',
    `# 生命周期探针 ${marker}`,
    '',
  ].join('\n');
}

/** 上传技能包 (kind=skill) —— 包名必须与 code 一致 (命名契约) */
async function uploadSkill(token, { code, name, version, summary, bytes }) {
  const fd = new FormData();
  fd.append('code', code);
  fd.append('kind', 'skill');
  fd.append('name', name);
  fd.append('version', version);
  fd.append('summary', summary);
  fd.append('description', 'e2e 生命周期验证用, 跑完即删');
  fd.append('use_when', '仅 e2e');
  fd.append('not_for', '生产');
  fd.append('category', '其他');
  fd.append('icon', '🧪');
  fd.append('tags', '[]');
  fd.append('keywords', '[]');
  fd.append('featured', 'false');
  fd.append('permissions', '{}');
  fd.append('install_steps', '[]');
  fd.append('bindings', '{}');
  fd.append('package', new Blob([bytes], { type: 'application/zip' }), `${code}.zip`);
  return api('/api/v1/extensions/upload', { method: 'POST', token, form: fd });
}

/** 上传多文件文本 (没有包名这回事 —— 用来单独测 code 格式规则) */
async function uploadFiles(token, { code, name, version, summary, files }) {
  const fd = new FormData();
  fd.append('code', code);
  fd.append('kind', 'skill');
  fd.append('name', name);
  fd.append('version', version);
  fd.append('summary', summary);
  fd.append('category', '其他');
  fd.append('icon', '🧪');
  fd.append('tags', '[]');
  fd.append('keywords', '[]');
  fd.append('permissions', '{}');
  fd.append('install_steps', '[]');
  fd.append('bindings', '{}');
  for (const [rel, content] of Object.entries(files || {})) {
    fd.append('files', new Blob([content], { type: 'text/plain' }), rel);
  }
  return api('/api/v1/extensions/upload', { method: 'POST', token, form: fd });
}

/** 上传连接器 (mcp) —— 只有一段 MCP 配置, 没有安装包 */
async function uploadMcp(token, { code, name, version, summary, mcpConfigRaw }) {
  const fd = new FormData();
  fd.append('code', code);
  fd.append('kind', 'mcp');
  fd.append('name', name);
  fd.append('version', version);
  fd.append('summary', summary);
  fd.append('description', 'e2e 生命周期验证用连接器, 跑完即删');
  fd.append('category', '其他');
  fd.append('icon', '🔌');
  fd.append('tags', '[]');
  fd.append('keywords', '[]');
  fd.append('permissions', '{}');
  fd.append('install_steps', '[]');
  fd.append('bindings', '{}');
  fd.append('mcp_config', mcpConfigRaw);
  return api('/api/v1/extensions/upload', { method: 'POST', token, form: fd });
}

/** 等一个 job 跑完 (返回最终状态) */
async function waitJob(token, jobId, timeoutMs = 90000) {
  const t0 = Date.now();
  let last = null;
  while (Date.now() - t0 < timeoutMs) {
    const r = await api(`/api/v1/extensions/jobs/${jobId}`, { token });
    last = r.json || null;
    if (last && ['pushed', 'done', 'failed', 'error'].includes(last.status)) return last;
    await sleep(1500);
  }
  return last;
}

/** 某 code 的 job 数量 (恢复在架不应该新建 job —— 不动 git) */
async function jobCount(token, code) {
  const r = await api('/api/v1/extensions/jobs?limit=100', { token });
  return ((r.json && r.json.items) || []).filter((j) => j.code === code).length;
}

/** 某 code 的通知回执 (回执表是**站内**记录, 与钉钉开关无关) */
async function receipts(token, code, sinceId = 0) {
  const r = await api('/api/v1/extensions/notifications?limit=200', { token });
  return ((r.json && r.json.items) || []).filter((n) => n.code === code && n.id > sinceId);
}

// ---------- 票据 (asset-dl) ----------
/** 读 env 文件里的某个键 */
function envGet(file, key) {
  try {
    const s = fs.readFileSync(file, 'utf8');
    const m = s.match(new RegExp(`^${key}=(.*)$`, 'm'));
    return m ? m[1].trim().replace(/^["']|["']$/g, '') : '';
  } catch {
    return '';
  }
}

/** HS256 签一张 asset-dl 票 (跟 backend_gateway/app/core/security.py 同款) */
function signAssetTicket(secret, { uid, code, version }) {
  const b64u = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
  const head = b64u({ alg: 'HS256', typ: 'JWT' });
  const body = b64u({
    typ: 'asset-dl', uid, code, ver: version,
    exp: Math.floor(Date.now() / 1000) + 600,
  });
  const sig = crypto.createHmac('sha256', secret).update(`${head}.${body}`).digest('base64url');
  return `${head}.${body}.${sig}`;
}

/** 候选 JWT_SECRET (docker 的 .env / 裸机的 .env / 环境变量) */
function jwtSecrets() {
  const out = [];
  const files = [
    path.join(__dirname, '..', 'deploy', '.env'),
    path.join(__dirname, '..', 'deploy', 'native', '.env'),
  ];
  for (const f of files) {
    const v = envGet(f, 'JWT_SECRET');
    if (v) out.push(v);
  }
  if (process.env.JWT_SECRET) out.push(process.env.JWT_SECRET);
  return [...new Set(out)];
}

/** 本地能不能看到后端的待审暂存区 (docker 部署时看不到 —— 那就 SKIP) */
function stagingRoot() {
  // ⚠️ 只有暂存区**真的在这台机器上**时才能验 —— docker 部署里暂存区在容器内,
  //    宿主机看到的同名目录是另一份 (或者压根没有) → 那样验出来的是假结果.
  const cands = [];
  if (process.env.EXTENSIONS_STAGING) cands.push(process.env.EXTENSIONS_STAGING);
  const nativeEnv = envGet(path.join(__dirname, '..', 'deploy', 'native', '.env'), 'EXTENSIONS_STAGING');
  if (nativeEnv) cands.push(nativeEnv);
  // 裸机后端在跑 → 默认暂存区就是 runtime/market_staging (见 deploy/native/tmctl.sh)
  let nativeRunning = false;
  try {
    execFileSync('pgrep', ['-f', 'uvicorn app.main:app'], { stdio: 'ignore' });
    nativeRunning = true;
  } catch { /* 没在跑 → 容器模式 */ }
  if (nativeRunning) {
    cands.push(path.join(__dirname, '..', 'deploy', 'native', 'runtime', 'market_staging'));
  }
  for (const c of cands) {
    try { if (fs.existsSync(c) && fs.statSync(c).isDirectory()) return c; } catch { /* 忽略 */ }
  }
  return '';
}

// ---------- 浏览器 ----------
/** 打开一个带登录态的页面 (独立 context → 独立 localStorage) */
async function openAs(browser, token, user) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  const errors = [];
  await page.setCacheEnabled(false);
  page.on('pageerror', (e) => errors.push(String(e.message)));
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  await page.evaluate((tk, u) => {
    localStorage.setItem('testmate:token', tk);
    localStorage.setItem('testmate:user', JSON.stringify(u));
  }, token, user);
  return { page, errors, ctx };
}

// ================================================================
(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const adminToken = await login(ADMIN, ADMIN_PW);
  // ⚠️ 先读原值 —— 跑完要还原成"跑之前"的样子 (不是写死的默认值)
  const savedSettings = await getSettings(adminToken, TOUCHED);

  const createdCodes = [];
  let browser = null;
  try {
    // ---------- 0. 准备: 静音通知 + 开审核 + 白名单 + 建号 ----------
    // ⚠️ 静音通知**必须在 try 里** —— 否则中途抛错就永远还原不了,
    //    把"不发通知"这个真实配置留在生产上.
    for (const k of NOTIFY_SWITCHES) await setSetting(adminToken, k, false);
    await setSetting(adminToken, 'extensions.review.enabled', true);
    // ⚠️ 两个测试账号都加进白名单 —— 越权用例要测的是"作者校验"(403),
    //    不是"没有发布权"(403, 但原因不对).
    await addPublisher(adminToken, savedSettings['extensions.publisher_usernames'],
      [PUBLISHER.username, OTHER.username]);

    await ensureUser(adminToken, PUBLISHER.username, PUBLISHER.password, 'tester');
    await ensureUser(adminToken, OTHER.username, OTHER.password, 'tester');
    const pubToken = await login(PUBLISHER.username, PUBLISHER.password);
    const otherToken = await login(OTHER.username, OTHER.password);
    const pubMe = await api('/api/v1/auth/me', { token: pubToken });
    const otherMe = await api('/api/v1/auth/me', { token: otherToken });

    const switchesNow = await getSettings(adminToken, NOTIFY_SWITCHES);
    const stillOn = NOTIFY_SWITCHES.filter((k) => switchesNow[k] === true || switchesNow[k] === 'true');
    check('L1 钉钉通知开关已全部静音 (测试期间不往真实群发消息)',
      stillOn.length === 0,
      stillOn.length ? `还开着: ${stillOn.join(', ')}` : `${NOTIFY_SWITCHES.length} 个开关全关`);
    check('L2 发布者与越权账号就位 (临时账号, 跑完即删)',
      !!pubToken && !!otherToken && pubMe.status === 200 && otherMe.status === 200,
      `发布者 id=${pubMe.json && pubMe.json.id} / 越权者 id=${otherMe.json && otherMe.json.id}`);

    // ============================================================
    // ---------- A. 生命周期: 上架 → 开审核 → 发新版本 → 恢复在架 ----------
    // ============================================================
    const v1Bytes = makeZipBytes({ 'SKILL.md': skillMd(MARK_V1) }, 'v1');
    const v2Bytes = makeZipBytes({ 'SKILL.md': skillMd(MARK_V2) }, 'v2');
    createdCodes.push(CODE);

    const up1 = await uploadSkill(pubToken, {
      code: CODE, name: NAME, version: V1,
      summary: 'e2e 生命周期验证 v1', bytes: v1Bytes,
    });
    check('L3 上传 v1 后资产是「待审核」(开审核 → 发布者上传不直接上架)',
      up1.status === 202, `status=${up1.status} ${(up1.text || '').slice(0, 80)}`);

    let st = await api(`/api/v1/extensions/${CODE}`, { token: pubToken });
    check('L4 待审资产状态是 pending',
      st.json && st.json.publish_status === 'pending',
      `publish_status=${st.json && st.json.publish_status}`);

    // 管理员审核通过 → 上架
    const appr = await api(`/api/v1/extensions/${CODE}/review`, {
      method: 'POST', token: adminToken,
      form: (() => { const f = new FormData(); f.append('decision', 'approve'); f.append('comment', 'e2e 生命周期自审'); return f; })(),
    });
    await sleep(1500);
    st = await api(`/api/v1/extensions/${CODE}`, { token: pubToken });
    check('L5 管理员审核通过后资产上架, 版本号是 1.0.0',
      appr.status === 200 && st.json && st.json.publish_status === 'published' && st.json.version === V1,
      `review=${appr.status} publish_status=${st.json && st.json.publish_status} version=${st.json && st.json.version}`);

    // 上架要真的 commit + push 到 GitLab (job 跑完才算数)
    const approveJobId = appr.json && appr.json.job_id;
    const job1 = approveJobId ? await waitJob(adminToken, approveJobId) : null;
    check('L6 上架的同步 job 推送成功 (git commit + push)',
      !!job1 && job1.status === 'pushed',
      job1 ? `job=${job1.id} status=${job1.status} ${job1.error || ''}` : '没拿到 job_id');

    // 发新版本 → 进「待审核」(内容只在仓库外暂存区)
    const up2 = await api(`/api/v1/extensions/${CODE}`, {
      method: 'PUT', token: pubToken,
      form: (() => {
        const f = new FormData();
        f.append('kind', 'skill');
        f.append('name', NAME);
        f.append('version', V2);
        f.append('summary', 'e2e 生命周期验证 v2');
        f.append('description', 'e2e 生命周期验证用, 跑完即删');
        f.append('use_when', '仅 e2e');
        f.append('not_for', '生产');
        f.append('category', '其他');
        f.append('icon', '🧪');
        f.append('tags', '[]');
        f.append('keywords', '[]');
        f.append('permissions', '{}');
        f.append('install_steps', '[]');
        f.append('bindings', '{}');
        f.append('package', new Blob([v2Bytes], { type: 'application/zip' }), `${CODE}.zip`);
        return f;
      })(),
    });
    await sleep(1200);
    st = await api(`/api/v1/extensions/${CODE}`, { token: pubToken });
    check('L7 发新版本 v2 后回到「待审核」, 且 pending_action=update (在等审新包)',
      up2.status === 202 && st.json && st.json.publish_status === 'pending' && st.json.pending_action === 'update',
      `put=${up2.status} publish_status=${st.json && st.json.publish_status} pending_action=${st.json && st.json.pending_action} version=${st.json && st.json.version}`);

    // 越权: 别人来"恢复在架" —— 权限**先**判 → 403 (与 delete / unpublish / PUT 同款口径)
    const badRevert = await api(`/api/v1/extensions/${CODE}/revert`, { method: 'POST', token: otherToken });
    check('L8 越权: 非作者调「恢复在架」被拒 (403)',
      badRevert.status === 403,
      `status=${badRevert.status} ${(badRevert.text || '').slice(0, 80)}`);

    // ---------- 恢复在架: 走**前端按钮** (真实用户路径) ----------
    const jobsBefore = await jobCount(adminToken, CODE);
    const receiptsBefore = await receipts(adminToken, CODE);

    browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
      defaultViewport: { width: 1600, height: 1000 },
    });
    const pub = await openAs(browser, pubToken, pubMe.json);
    let revertResp = null;
    pub.page.on('response', async (r) => {
      if (r.url().includes(`/extensions/${CODE}/revert`)) {
        revertResp = { status: r.status(), text: await r.text().catch(() => '') };
      }
    });
    await pub.page.goto(BASE + '/extensions', { waitUntil: 'domcontentloaded' });
    await pub.page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1200);
    // 资产是技能 → 扩展页默认停在「插件」页签, 得切过去
    await pub.page.evaluate(() => {
      const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
      t && t.click();
    });
    await sleep(1500);
    // ⚠️ 列表默认按热门排、只取前 100 条 —— 新建的资产**可能在第一页之外**.
    //    所以用搜索框按名字过滤, 再找卡片 (不然会误判成"前端没渲染").
    const searchOk = await pub.page.evaluate((name) => {
      const el = document.querySelector('.search input');
      if (!el) return false;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, name);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    }, NAME);
    await sleep(2000);
    const openedCard = await pub.page.evaluate((name) => {
      const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(name));
      if (!c) return false;
      c.click();
      return true;
    }, NAME);
    let drawerOpen = false;
    try {
      await pub.page.waitForSelector('.el-drawer', { timeout: 10000 });
      drawerOpen = true;
    } catch { /* 抽屉没开 → 下面走 API 兜底 */ }
    await sleep(1200);
    const adBtns = await pub.page.evaluate(() =>
      [...document.querySelectorAll('.ad-actions button')].map((b) => (b.textContent || '').trim()));
    const drawerName = await pub.page.evaluate(() =>
      (document.querySelector('.ad-name')?.textContent || '').replace(/\s+/g, ' ').trim());
    check('L9 待审资产详情抽屉里有「恢复在架版本」按钮 (前端文案)',
      openedCard && drawerOpen && drawerName.includes(NAME) && adBtns.includes('恢复在架版本'),
      `搜索=${searchOk} card=${openedCard} drawer=${drawerOpen} 抽屉资产="${drawerName}" 按钮: ${adBtns.join(' | ')}`);
    await pub.page.screenshot({ path: path.join(OUT_DIR, 'lc-01-revert-button.png') });

    if (adBtns.includes('恢复在架版本')) {
      await pub.page.evaluate(() => {
        const b = [...document.querySelectorAll('.ad-actions button')]
          .find((x) => (x.textContent || '').trim() === '恢复在架版本');
        b && b.click();
      });
      await sleep(900);
      const boxMsg = await pub.page.evaluate(() =>
        (document.querySelector('.el-message-box__message')?.textContent || '').replace(/\s+/g, ' ').trim());
      await pub.page.evaluate(() => {
        const b = [...document.querySelectorAll('.el-message-box__btns .el-button')]
          .find((x) => (x.textContent || '').trim() === '恢复');
        b && b.click();
      });
      await sleep(2500);
      check('L10 点「恢复在架版本」→ 二次确认 → 恢复成功 (HTTP 200)',
        !!revertResp && revertResp.status === 200,
        revertResp ? `确认框="${boxMsg.slice(0, 40)}" status=${revertResp.status}` : '没抓到 /revert 的响应');
    } else {
      // 兜底: 前端按钮没出现 (页面没渲染出来) —— 直接打 API 完成链路, 细节写清楚
      const r = await api(`/api/v1/extensions/${CODE}/revert`, { method: 'POST', token: pubToken });
      revertResp = { status: r.status, text: r.text };
      check('L10 点「恢复在架版本」→ 二次确认 → 恢复成功 (HTTP 200)',
        r.status === 200,
        `⚠️ 前端按钮没找到, 已改走 API: status=${r.status} ${(r.text || '').slice(0, 60)}`);
    }
    await pub.page.screenshot({ path: path.join(OUT_DIR, 'lc-02-after-revert.png') });

    // ---------- 恢复之后: 状态 / 版本 / 暂存区 / 通知 / git ----------
    st = await api(`/api/v1/extensions/${CODE}`, { token: pubToken });
    check('L11 恢复后状态回到 published',
      st.json && st.json.publish_status === 'published',
      `publish_status=${st.json && st.json.publish_status}`);
    check('L12 恢复后版本号回到老版本 1.0.0',
      st.json && st.json.version === V1,
      `version=${st.json && st.json.version} (待审的 ${V2} 已放弃)`);
    check('L13 恢复后 pending_action / review_note 清空',
      st.json && !st.json.pending_action && !st.json.review_note,
      `pending_action="${st.json && st.json.pending_action}" review_note="${st.json && st.json.review_note}"`);

    const bundle = await api(`/api/v1/extensions/${CODE}/bundle`, { token: pubToken });
    const bundleText = ((bundle.json && bundle.json.files) || []).map((f) => f.content).join('\n');
    check('L14 恢复后取到的是**老版本内容** (暂存区里那份新版本被丢弃)',
      bundle.status === 200 && bundleText.includes(MARK_V1) && !bundleText.includes(MARK_V2),
      `bundle=${bundle.status} 含 v1 标记=${bundleText.includes(MARK_V1)} 含 v2 标记=${bundleText.includes(MARK_V2)}`);

    // 暂存区清空 —— 能直接看到后端暂存目录时才算 (docker 部署看不到)
    const sRoot = stagingRoot();
    if (!sRoot) {
      skip('L15 恢复后仓库外暂存区已清空', '本机看不到后端的暂存目录 (docker 部署)');
    } else {
      const gitPath = (st.json && st.json.git_path) || '';
      const stagedDir = path.join(sRoot, gitPath);
      const stillThere = fs.existsSync(stagedDir);
      check('L15 恢复后仓库外暂存区已清空', !stillThere,
        `暂存目录 ${stagedDir} 存在=${stillThere}`);
    }

    const receiptsAfter = await receipts(adminToken, CODE);
    const newReceipts = receiptsAfter.filter((n) => !receiptsBefore.some((b) => b.id === n.id));
    const publishReceipts = newReceipts.filter((n) => ['publish', 'update'].includes(n.event));
    check('L16 恢复不发上架通知 (没有新增 publish/update 回执)',
      publishReceipts.length === 0,
      `新增回执: ${newReceipts.map((n) => n.event).join(',') || '(无)'}`);

    const jobsAfter = await jobCount(adminToken, CODE);
    check('L17 恢复不动 git (没有新建同步 job)',
      jobsAfter === jobsBefore,
      `job 数 ${jobsBefore} → ${jobsAfter}`);

    const audits = await api(`/api/v1/extensions/audits?code=${CODE}&limit=50`, { token: adminToken });
    const actions = ((audits.json && audits.json.items) || []).map((a) => a.action);
    check('L18 审计里有 revert 记录, 且没有多出 approve/publish (恢复不是一次上架)',
      actions.includes('revert') && actions.filter((a) => a === 'approve' || a === 'publish').length === 1,
      `审计动作: ${actions.join(',')}`);

    // ============================================================
    // ---------- B. 连接器复制 (POST /{code}/copy) ----------
    // ============================================================
    createdCodes.push(CODE_MCP);
    const mcpCfg = JSON.stringify({
      mcpServers: { [CODE_MCP]: { url: 'http://127.0.0.1:9/mcp' } },
    });
    const upMcp = await uploadMcp(pubToken, {
      code: CODE_MCP, name: NAME_MCP, version: V1,
      summary: 'e2e 生命周期验证连接器', mcpConfigRaw: mcpCfg,
    });
    let stMcp = await api(`/api/v1/extensions/${CODE_MCP}`, { token: pubToken });
    if (stMcp.json && stMcp.json.publish_status === 'pending') {
      await api(`/api/v1/extensions/${CODE_MCP}/review`, {
        method: 'POST', token: adminToken,
        form: (() => { const f = new FormData(); f.append('decision', 'approve'); f.append('comment', 'e2e 自审'); return f; })(),
      });
      await sleep(2000);
      stMcp = await api(`/api/v1/extensions/${CODE_MCP}`, { token: pubToken });
    }
    check('L19 连接器资产创建成功并上架 (mcp 形态)',
      upMcp.status === 202 && stMcp.json && stMcp.json.publish_status === 'published',
      `upload=${upMcp.status} publish_status=${stMcp.json && stMcp.json.publish_status}`);

    const copy = await api(`/api/v1/extensions/${CODE_MCP}/copy`, { method: 'POST', token: adminToken });
    check('L20 POST /{code}/copy 连接器配置复制计数 +1',
      copy.status === 200 && copy.json && copy.json.copy_count >= 1,
      `status=${copy.status} copy_count=${copy.json && copy.json.copy_count}`);

    const copySkill = await api(`/api/v1/extensions/${CODE}/copy`, { method: 'POST', token: adminToken });
    check('L21 对技能资产调 copy 被拒 (只有连接器能计数)',
      copySkill.status === 400,
      `status=${copySkill.status} ${(copySkill.text || '').slice(0, 60)}`);

    // ============================================================
    // ---------- C. bundle / 下载 / 票据 ----------
    // ============================================================
    const bundle2 = await api(`/api/v1/extensions/${CODE}/bundle`, { token: adminToken });
    const files = (bundle2.json && bundle2.json.files) || [];
    check('L22 GET /{code}/bundle 返回明文文件清单 + 内容 (前端通道安装用)',
      bundle2.status === 200 && bundle2.json.total >= 1
      && files.some((f) => f.path.endsWith('SKILL.md') && f.encoding === 'text' && f.content.length > 0),
      `status=${bundle2.status} total=${bundle2.json && bundle2.json.total} 文件: ${files.map((f) => f.path).join(', ')}`);

    const dl = await apiRaw(`/api/v1/extensions/${CODE}/versions/${V1}/download`, adminToken);
    const cd = dl.headers.get('content-disposition') || '';
    check('L23 GET /{code}/versions/1.0.0/download 下载到安装包 (文件名不带版本号)',
      dl.status === 200 && dl.buf.length > 0 && cd.includes(`${CODE}.zip`),
      `status=${dl.status} 字节=${dl.buf.length} content-disposition="${cd}"`);

    const tkNo = await api(`/api/v1/extensions/${CODE}/versions/${V1}/ticket-download`, { token: adminToken });
    check('L24 ticket-download 没有票 → 401',
      tkNo.status === 401, `status=${tkNo.status} ${(tkNo.text || '').slice(0, 60)}`);

    // 票据: 用 JWT_SECRET 自己签一张 asset-dl 票 (跟后端同款算法).
    // ⚠️ 后端可能跑在容器里、用的是**另一份** JWT_SECRET —— 签出来全是 401 时
    //    说明本机读到的密钥不对, 这时**跳过**而不是判失败 (环境不具备, 不是缺陷).
    const uid = pubMe.json && pubMe.json.id;
    const secrets = jwtSecrets();
    const statuses = [];
    let tkMismatch = null;
    for (const secret of secrets) {
      const bad = signAssetTicket(secret, { uid, code: CODE, version: '9.9.9' });
      const r = await api(`/api/v1/extensions/${CODE}/versions/${V1}/ticket-download?ticket=${encodeURIComponent(bad)}`);
      statuses.push(r.status);
      if (r.status === 403) { tkMismatch = r; break; }
    }
    if (tkMismatch) {
      check('L25 ticket-download 票与版本不匹配 → 403', true, `status=403`);
    } else if (statuses.length && statuses.every((s) => s === 401)) {
      skip('L25 ticket-download 票与版本不匹配 → 403',
        `本机读到的 JWT_SECRET 与后端在用的不是同一份 (票据全 401): ${statuses.join(',')}`);
    } else {
      check('L25 ticket-download 票与版本不匹配 → 403', false,
        `status=${statuses.join(',')} ${(tkMismatch && tkMismatch.text || '').slice(0, 60)}`);
    }

    let tkOk = null;
    const okStatuses = [];
    for (const secret of secrets) {
      const good = signAssetTicket(secret, { uid, code: CODE, version: V1 });
      const r = await apiRaw(`/api/v1/extensions/${CODE}/versions/${V1}/ticket-download?ticket=${encodeURIComponent(good)}`, adminToken);
      okStatuses.push(r.status);
      if (r.status === 200) { tkOk = r; break; }
      if (!tkOk) tkOk = r;
    }
    if (!secrets.length) {
      skip('L26 ticket-download 有效票能兑换到精确版本的包', '本机读不到 JWT_SECRET (deploy/*.env)');
    } else if (tkOk && tkOk.status === 200) {
      check('L26 ticket-download 有效票能兑换到精确版本的包',
        tkOk.buf.length > 0,
        `status=200 字节=${tkOk.buf.length}`);
    } else if (okStatuses.every((s) => s === 401)) {
      skip('L26 ticket-download 有效票能兑换到精确版本的包',
        `本机读到的 JWT_SECRET 与后端在用的不是同一份 (票据全 401): ${okStatuses.join(',')}`);
    } else {
      check('L26 ticket-download 有效票能兑换到精确版本的包', false,
        `status=${okStatuses.join(',')} ${(tkOk && tkOk.text || '').slice(0, 80)}`);
    }

    // ============================================================
    // ---------- D. 通知预览 / 规则 ----------
    // ============================================================
    const maxReceipt = await api('/api/v1/extensions/notifications?limit=1', { token: adminToken });
    const receiptBase = ((maxReceipt.json && maxReceipt.json.items) || [])[0]?.id || 0;
    const prev = await api('/api/v1/extensions/notifications/preview', { token: adminToken });
    const prevItems = Array.isArray(prev.json) ? prev.json : [];
    const afterReceipt = await api('/api/v1/extensions/notifications?limit=200', { token: adminToken });
    const newRcpt = ((afterReceipt.json && afterReceipt.json.items) || []).filter((n) => n.id > receiptBase);
    check('L27 GET /notifications/preview 渲染出几种通知 (一条都不发)',
      prev.status === 200 && prevItems.length >= 3
      && prevItems.every((p) => p.title && Array.isArray(p.lines) && p.lines.length > 0),
      `status=${prev.status} 场景数=${prevItems.length} 事件=${prevItems.map((p) => p.event).join(',')}`);
    check('L28 预览不产生任何通知回执 (没往公司群发东西)',
      newRcpt.length === 0,
      `新增回执 ${newRcpt.length} 条`);

    const prevOther = await api('/api/v1/extensions/notifications/preview', { token: otherToken });
    check('L29 通知预览是管理员专用 (普通用户 403)',
      prevOther.status === 403,
      `status=${prevOther.status} ${(prevOther.text || '').slice(0, 60)}`);

    const rules = await api('/api/v1/extensions/rules', { token: adminToken });
    const rc = (rules.json && rules.json.code) || {};
    check('L30 GET /extensions/rules 下发命名/包后缀/分类规则',
      rules.status === 200 && rc.min_length === 3 && rc.max_length === 64
      && Array.isArray(rules.json && rules.json.package && rules.json.package.suffixes)
      && Array.isArray(rules.json && rules.json.categories),
      `status=${rules.status} code 长度=${rc.min_length}~${rc.max_length} 包后缀=${JSON.stringify(rules.json && rules.json.package && rules.json.package.suffixes)} 分类数=${((rules.json && rules.json.categories) || []).length}`);

    // ============================================================
    // ---------- E. 异常 / 边界 ----------
    // ============================================================
    const noCode = `e2e-ext-lc-none-${STAMP}`;
    const g1 = await api(`/api/v1/extensions/${noCode}`, { token: adminToken });
    const g2 = await api(`/api/v1/extensions/${noCode}/bundle`, { token: adminToken });
    check('L31 不存在的 code → 404 (详情 / bundle 都是)',
      g1.status === 404 && g2.status === 404,
      `详情=${g1.status} bundle=${g2.status}`);

    const dup = await uploadSkill(pubToken, {
      code: CODE, name: NAME, version: V1,
      summary: 'e2e 重复上传', bytes: v1Bytes,
    });
    check('L32 重复 code 上传 → 409 (不会覆盖别人的资产)',
      dup.status === 409,
      `status=${dup.status} ${(dup.text || '').slice(0, 70)}`);

    const badCodes = [
      { code: `E2E_Ext--Bad-${STAMP}`, label: '大写/下划线/连续连字符' },
      { code: 'ab', label: '长度不足 3' },
      { code: `e2e--ext-lc-${STAMP}`, label: '连续连字符' },
    ];
    for (let i = 0; i < badCodes.length; i++) {
      const b = badCodes[i];
      const r = await uploadFiles(pubToken, {
        code: b.code, name: `非法 code ${b.label}`, version: V1,
        summary: 'e2e 非法 code', files: { 'SKILL.md': skillMd(MARK_V1) },
      });
      check(`L${33 + i} 非法 code (${b.label}) → 422`,
        r.status === 422,
        `code="${b.code}" status=${r.status} ${(r.text || '').slice(0, 70)}`);
    }

    const badMcp = await uploadMcp(pubToken, {
      code: `${CODE_MCP}-bad`, name: '非法 MCP 配置', version: V1,
      summary: 'e2e 非法 MCP 配置', mcpConfigRaw: '{这不是 json',
    });
    check('L36 MCP 连接器配置非法 JSON → 422',
      badMcp.status === 422,
      `status=${badMcp.status} ${(badMcp.text || '').slice(0, 80)}`);

    // 状态机非法跃迁 (资产现在是 published)
    const badApprove = await api(`/api/v1/extensions/${CODE}/review`, {
      method: 'POST', token: adminToken,
      form: (() => { const f = new FormData(); f.append('decision', 'approve'); f.append('comment', 'e2e 非法跃迁'); return f; })(),
    });
    check('L37 状态机: 对在架资产直接调「审核通过」→ 409',
      badApprove.status === 409,
      `status=${badApprove.status} ${(badApprove.text || '').slice(0, 70)}`);

    const badSubmit = await api(`/api/v1/extensions/${CODE}/submit`, {
      method: 'POST', token: pubToken,
      form: (() => { const f = new FormData(); f.append('comment', 'e2e 非法跃迁'); return f; })(),
    });
    check('L38 状态机: 对在架资产调「重新提交审核」→ 409',
      badSubmit.status === 409,
      `status=${badSubmit.status} ${(badSubmit.text || '').slice(0, 70)}`);

    const badRevert2 = await api(`/api/v1/extensions/${CODE}/revert`, { method: 'POST', token: pubToken });
    check('L39 状态机: 对在架资产调「恢复在架」→ 409 (已经在架, 没得恢复)',
      badRevert2.status === 409,
      `status=${badRevert2.status} ${(badRevert2.text || '').slice(0, 70)}`);

    // 越权 (作者本人 or admin 才能改别人的资产)
    const badUnpub = await api(`/api/v1/extensions/${CODE}/unpublish`, {
      method: 'POST', token: otherToken,
      form: (() => { const f = new FormData(); f.append('confirm_code', CODE); f.append('comment', 'e2e 越权'); return f; })(),
    });
    check('L40 越权: 非作者申请下架别人的资产 → 403',
      badUnpub.status === 403,
      `status=${badUnpub.status} ${(badUnpub.text || '').slice(0, 70)}`);

    const badUpdate = await api(`/api/v1/extensions/${CODE}`, {
      method: 'PUT', token: otherToken,
      form: (() => {
        const f = new FormData();
        f.append('kind', 'skill');
        f.append('name', NAME);
        f.append('version', V2);
        f.append('summary', 'e2e 越权');
        f.append('package', new Blob([v2Bytes], { type: 'application/zip' }), `${CODE}.zip`);
        return f;
      })(),
    });
    check('L41 越权: 非作者给别人的资产发新版本 → 403',
      badUpdate.status === 403,
      `status=${badUpdate.status} ${(badUpdate.text || '').slice(0, 70)}`);

    const badReview = await api(`/api/v1/extensions/${CODE}/review`, {
      method: 'POST', token: otherToken,
      form: (() => { const f = new FormData(); f.append('decision', 'approve'); f.append('comment', 'e2e 越权'); return f; })(),
    });
    check('L42 越权: 非管理员/非审核人调「审核通过」→ 403',
      badReview.status === 403,
      `status=${badReview.status} ${(badReview.text || '').slice(0, 70)}`);
  } finally {
    if (browser) await browser.close();
    // ---------- 清理 1: 删掉本脚本创建的资产 (只删自己的, code 带时间戳) ----------
    for (const code of createdCodes) {
      try {
        const r = await api(`/api/v1/extensions/${code}`, { method: 'DELETE', token: adminToken, body: undefined });
        console.log(`  [清理] 删除资产 ${code} → ${r.status}`);
      } catch (e) {
        console.log(`  [清理] ⚠️ 删除资产 ${code} 失败: ` + String(e.message).split('\n')[0]);
      }
    }
    for (const code of createdCodes) {
      const r = await api(`/api/v1/extensions/${code}`, { token: adminToken });
      if (r.status !== 404) console.log(`  [清理] ⚠️ 资产 ${code} 还在 (status=${r.status}), 请手动清理`);
    }
    // ---------- 清理 2: 还原生产设置 (先读原值再改, 别写死) ----------
    for (const k of TOUCHED) {
      if (savedSettings[k] === undefined) continue;
      try {
        await setSetting(adminToken, k, savedSettings[k]);
      } catch (e) {
        console.log(`  [清理] 设置 ${k} 还原失败: ` + String(e.message).split('\n')[0]);
      }
    }
    const after = await getSettings(adminToken, TOUCHED);
    const notRestored = TOUCHED.filter(
      (k) => savedSettings[k] !== undefined && String(after[k]) !== String(savedSettings[k]));
    if (notRestored.length) {
      console.log('  [清理] ⚠️ 有设置没还原干净, 生产配置是脏的: '
        + notRestored.map((k) => `${k}=${JSON.stringify(after[k])} (应为 ${JSON.stringify(savedSettings[k])})`).join(', '));
    } else {
      console.log('  [清理] 生产设置已全部还原');
    }
    // ---------- 清理 3: 删测试账号 ----------
    deleteTestUsers([PUBLISHER.username, OTHER.username]);
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
