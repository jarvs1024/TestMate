#!/usr/bin/env node
/**
 * 软件库 **变更生命周期** e2e (真实 Chrome) —— 补 e2e_software.js 的缺口.
 *
 * e2e_software.js 走的是「上架 → 浏览 → 下载 → 发新版本」的**正向**流程,
 * 但软件库真正的复杂度全在**改 / 删 / 换 / 越权 / 边界**上:
 *   · 固定下载链接 (按别名) 到底给不给"推荐版本";
 *   · 短时下载票据能不能免登录用;
 *   · 改版本信息 / 删版本 / 换包 / 改条目 / 删条目 / 彻底清理 的**顺序与后果**;
 *   · 别人家的软件能不能被我改 (越权);
 *   · 不存在 / 非法 / 重复 / 超限 的**状态码口径**.
 *
 * 本脚本把这些**全走 API** (页内 fetch), 跟后端口径逐条对齐.
 *
 * ⚠️ **数据安全红线** (违反就是真实数据损坏):
 *   1. 只操作本次跑创建的条目 —— code 一律带时间戳 (e2e-sw-lc-<base36 时间戳>),
 *      跑完用 purge 接口删干净 (记录 + 磁盘文件一起没);
 *   2. **绝不发真实钉钉消息** —— 跑之前把 5 个通知开关关掉, 结束按**原值**恢复
 *      (先读原值再改, 不写死);
 *   3. 临时非管理员账号**用完即删**;
 *   4. 改生产设置 (max_size_mb / publisher_usernames) 之前先存原值, 结束还原.
 *
 * 用法:
 *   node scripts/e2e_software_lifecycle.js [baseUrl]
 *   TESTMATE_BASE=http://localhost:8081 node scripts/e2e_software_lifecycle.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
// ⚠️ 互斥锁: 并行跑 e2e 会互相改生产设置/删数据 (见 e2e_lock.js)
require('./e2e_lock').acquire(__filename);

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.argv[2] || process.env.TESTMATE_BASE || 'http://localhost:8081').replace(/\/$/, '');
const USER = process.env.TESTMATE_USER || 'admin';
const PASSWORD = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');

/** 本次跑的唯一标识 —— 所有 code 都带它, 绝不碰别人的东西 */
const STAMP = Date.now().toString(36);
const CODE_MAIN = `e2e-sw-lc-${STAMP}`;              // 主条目 (管理员创建)
const CODE_VER = `e2e-sw-lc-${STAMP}b-v2.1`;         // 别名条目 (code 里带版本号)
const CODE_CNT = `e2e-sw-lc-${STAMP}c`;              // 数量上限条目
const CODE_OVR = `e2e-sw-lc-${STAMP}d`;              // 大小超限条目
const TMP_USER = `e2e_swlc_${STAMP}`;                // 临时非管理员账号
const TMP_PW = 'SwLc@2026x';

const NAME_MAIN = `E2E 生命周期主条目 ${STAMP}`;
const NAME_VER = `E2E 生命周期别名条目 ${STAMP}`;

/** 所有要删干净的条目 (创建成功才登记) */
const created = new Set();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail: detail || '' });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}

const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');

/** 页内 fetch —— 所有 API 断言都走它 (跟 e2e_ext.js 同一个套路) */
async function api(page, method, urlPath, opt = {}) {
  return await page.evaluate(async (m, p, o) => {
    const headers = Object.assign({}, o.headers || {});
    if (o.token) headers.Authorization = 'Bearer ' + o.token;
    let body;
    if (o.json !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(o.json);
    } else if (o.bodyB64 !== undefined) {
      const bin = atob(o.bodyB64);
      const u8 = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      body = u8;
    }
    const r = await fetch(p, { method: m, headers, body });
    const buf = await r.arrayBuffer();
    let b64 = '';
    if (buf.byteLength) {
      const u8 = new Uint8Array(buf);
      let s = '';
      const CH = 0x8000;
      for (let i = 0; i < u8.length; i += CH) s += String.fromCharCode.apply(null, u8.subarray(i, i + CH));
      b64 = btoa(s);
    }
    const text = new TextDecoder().decode(buf);
    let parsed = null;
    try { parsed = JSON.parse(text); } catch (e) { /* 非 JSON */ }
    const h = {};
    r.headers.forEach((v, k) => { h[k] = v; });
    return { status: r.status, ok: r.ok, json: parsed, text, bodyB64: b64, headers: h };
  }, method, urlPath, {
    token: opt.token,
    json: opt.json,
    bodyB64: opt.bodyB64,
    headers: opt.headers,
  });
}

/** 读设置项当前值 (只取指定 key) —— 改之前必须先存住 */
async function getSettings(page, token, keys) {
  const r = await api(page, 'GET', '/api/v1/settings/schema', { token });
  const out = {};
  if (r.status !== 200) return out;
  for (const g of (r.json && r.json.groups) || []) {
    for (const it of g.items || []) {
      if (keys.includes(it.key)) out[it.key] = it.value;
    }
  }
  return out;
}

async function putSetting(page, token, key, value) {
  const r = await api(page, 'PUT', '/api/v1/settings/' + encodeURIComponent(key), {
    token, json: { value },
  });
  return r.status;
}

/** 造一个软件条目 (元数据 + 一个版本行, 文件随后用 PUT /file 传) */
async function createItem(page, token, code, name, icon, version = '1.0.0') {
  const r = await api(page, 'POST', '/api/v1/software', {
    token,
    json: {
      code,
      name,
      icon,
      version,
      summary: `e2e 生命周期探针 ${code}`,
      features: ['探针一: 校验上架', '探针二: 校验下载'],
      use_when: '只在 e2e 跑批时用',
      not_for: '生产环境',
      install_steps: '解压即用',
      caveats: '跑完即删',
      platform: '',
      category: 'e2e',
      tags: ['e2e', 'lifecycle'],
      keywords: ['e2e'],
      file_name: `${code}.bin`,
      file_size: 0,
      release_notes: '首个版本',
      variant: '通用版',
    },
  });
  if (r.status === 201 && r.json && r.json.code) created.add(r.json.code);
  return r;
}

/** 上传软件包 (原始字节流) */
async function uploadFile(page, token, code, buf, fileName) {
  const name = fileName || `${code}.bin`;
  return await api(page, 'PUT', `/api/v1/software/${encodeURIComponent(code)}/file`, {
    token,
    bodyB64: buf.toString('base64'),
    headers: {
      'Content-Type': 'application/octet-stream',
      // 前端也是这么发的 (原始文件名走 URL 编码, 后端会 unquote)
      'X-File-Name': encodeURIComponent(name),
      'X-File-Size': String(buf.length),
    },
  });
}

/** 发一个新版本 (元数据) —— 文件随后单独传 */
async function createVersion(page, token, code, version, isDefault = true) {
  return await api(page, 'POST', `/api/v1/software/${encodeURIComponent(code)}/versions`, {
    token,
    json: {
      version,
      release_notes: `版本 ${version}`,
      variant: '通用版',
      is_default: isDefault,
      file_name: `${code}-${version}.bin`,
      file_size: 0,
    },
  });
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1600, height: 1000 },
  });
  const page = await browser.newPage();
  const pageErrors = [];
  await page.setCacheEnabled(false);
  page.on('pageerror', (e) => pageErrors.push('[pageerror] ' + e.message));

  // 临时账号 / 设置的"原值" —— finally 里要还原
  let adminToken = '';
  let tmpToken = '';
  let tmpUserId = 0;
  const savedSettings = {};
  const NOTIFY_SWITCHES = [
    'dingtalk.notify_on_software',
    'dingtalk.notify_on_publish',
    'dingtalk.notify_on_update',
    'dingtalk.notify_on_unpublish',
    'dingtalk.notify_on_delete',
  ];
  const TOUCHED = [
    ...NOTIFY_SWITCHES,
    'software.max_size_mb',
    'software.keep_versions',
    'extensions.publisher_usernames',
  ];

  try {
    // ================= 登录 =================
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    const login = await api(page, 'POST', '/api/v1/auth/login', {
      json: { username: USER, password: PASSWORD },
    });
    adminToken = (login.json && login.json.access_token) || '';
    check('L1 管理员登录成功', !!adminToken, adminToken ? 'token 已拿到' : `HTTP ${login.status} ${login.text.slice(0, 80)}`);
    if (!adminToken) throw new Error('登录失败 —— 后面的用例都跑不了');
    await page.evaluate((tk, u) => {
      localStorage.setItem('testmate:token', tk);
      localStorage.setItem('testmate:user', JSON.stringify(u));
    }, adminToken, { id: 0, username: USER, role: 'admin' });

    // ================= 关通知开关 (先读原值) =================
    Object.assign(savedSettings, await getSettings(page, adminToken, TOUCHED));
    check('L2 通知开关原值已读取 (跑完按原值还原)',
      NOTIFY_SWITCHES.every((k) => k in savedSettings),
      NOTIFY_SWITCHES.map((k) => `${k}=${savedSettings[k]}`).join(' '));
    for (const k of NOTIFY_SWITCHES) {
      const st = await putSetting(page, adminToken, k, 'false');
      if (st !== 200) check('L3 通知开关关闭失败 ' + k, false, 'HTTP ' + st);
    }
    const nowOff = await getSettings(page, adminToken, NOTIFY_SWITCHES);
    check('L3 五个通知开关已全部关掉 (软件上架/更新/下架不会发真实钉钉消息)',
      NOTIFY_SWITCHES.every((k) => nowOff[k] === false),
      NOTIFY_SWITCHES.map((k) => `${k}=${nowOff[k]}`).join(' '));

    // ================= 临时非管理员账号 (用完即删) =================
    const cu = await api(page, 'POST', '/api/v1/auth/users', {
      token: adminToken,
      json: { username: TMP_USER, password: TMP_PW, role: 'tester' },
    });
    tmpUserId = (cu.json && cu.json.id) || 0;
    check('L4 临时非管理员账号创建成功', cu.status === 201 && tmpUserId > 0,
      `HTTP ${cu.status} id=${tmpUserId} ${(cu.json && cu.json.username) || ''}`);
    const tlogin = await api(page, 'POST', '/api/v1/auth/login', {
      json: { username: TMP_USER, password: TMP_PW },
    });
    tmpToken = (tlogin.json && tlogin.json.access_token) || '';
    check('L5 临时账号登录成功 (拿到自己的 token)', !!tmpToken,
      `HTTP ${tlogin.status} ${(tlogin.json && tlogin.json.username) || ''}`);
    // 让临时账号**能发布** —— 否则它会被 require_publisher 挡在门口 (403),
    // 测不到"作者本人 or admin"那道真正的闸.
    const wl = await putSetting(page, adminToken, 'extensions.publisher_usernames', TMP_USER);
    check('L6 临时账号已加入发布者白名单 (保证能走到越权判定那一步)', wl === 200, 'HTTP ' + wl);

    // ================= 图标 =================
    // ⚠️ 图标全局唯一 —— 必须挑一个**没人用**的, 否则创建条目直接 409.
    const cfg = await api(page, 'GET', '/api/v1/software/config', { token: adminToken });
    const used = (cfg.json && cfg.json.used_icons) || {};
    const POOL = ['🧿', '🪙', '🧬', '🫧', '🪄', '🧊', '🪶', '🧨', '🎏', '🛟'];
    const freeIcons = [];
    for (const ic of POOL) if (!(ic in used)) freeIcons.push(ic);
    for (let i = 0; freeIcons.length < 6; i++) freeIcons.push(`E2E${i}${STAMP.slice(-4)}`);
    const ICON_MAIN = freeIcons[0];
    const ICON_VER = freeIcons[1];
    const ICON_CNT = freeIcons[2];
    const ICON_OVR = freeIcons[3];
    // ⚠️ 2026-11-06: 「撞标识」探针**会真的建出一条条目** (撞名自动加序号),
    //    所以它必须用**自己的**图标 —— 以前它借用了 ICON_CNT, 结果这条探针条目
    //    把 ICON_CNT 占住了, 后面 L56 再用同一个图标建条目 → 409 图标重复.
    const ICON_DUP = freeIcons[4];
    check('L7 挑到了没被占用的图标 (图标重复会 409, 创建条目就废了)',
      freeIcons.length >= 5, `主=${ICON_MAIN} 别名=${ICON_VER}`);

    // ================= 主条目: 建 + 传文件 =================
    const PAYLOAD1 = Buffer.from('TestMate 软件库生命周期 e2e payload v1\n'.repeat(64));
    const SHA1 = sha256(PAYLOAD1);
    const PAYLOAD2 = Buffer.concat([PAYLOAD1, Buffer.from('\n-- v2 换了内容 --\n')]);
    const SHA2 = sha256(PAYLOAD2);

    const c1 = await createItem(page, adminToken, CODE_MAIN, NAME_MAIN, ICON_MAIN, '1.0.0');
    check('L8 创建软件条目成功 (awaiting_file, 还没传文件)',
      c1.status === 201 && c1.json && c1.json.code === CODE_MAIN,
      `HTTP ${c1.status} code=${(c1.json && c1.json.code) || ''}`);

    const u1 = await uploadFile(page, adminToken, CODE_MAIN, PAYLOAD1);
    check('L9 上传软件包成功 (sha256 与本地一致)',
      u1.status === 200 && u1.json && u1.json.sha256 === SHA1,
      `HTTP ${u1.status} 后端sha=${(u1.json && u1.json.sha256 || '').slice(0, 12)} 本地=${SHA1.slice(0, 12)}`);

    const d1 = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), { token: adminToken });
    check('L10 详情可读 (已上架 / 可下载版本 = 1.0.0 / 版本行 ready)',
      d1.status === 200 && d1.json && d1.json.publish_status === 'published'
        && d1.json.download_version === '1.0.0'
        && (d1.json.versions || []).some((v) => v.version === '1.0.0' && v.status === 'ready'),
      `status=${d1.json && d1.json.publish_status} dl=${d1.json && d1.json.download_version}`);

    // ================= 别名条目 (code 里带版本号 → 别名要把它剥掉) =================
    const c2 = await createItem(page, adminToken, CODE_VER, NAME_VER, ICON_VER, '1.0.0');
    check('L11 带版本号的 code 也能建成条目', c2.status === 201, `HTTP ${c2.status} code=${(c2.json && c2.json.code) || ''}`);
    const u2 = await uploadFile(page, adminToken, CODE_VER, PAYLOAD1);
    check('L12 别名条目上传文件成功', u2.status === 200, 'HTTP ' + u2.status);
    const d2 = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_VER), { token: adminToken });
    const alias = (d2.json && d2.json.download_alias) || '';
    const fixedUrl = (d2.json && d2.json.fixed_download_url) || '';
    check('L13 下载别名已把版本号剥掉 (alias ≠ code, 且不含 v2.1)',
      !!alias && alias !== CODE_VER && !alias.includes('v2.1'),
      `code=${CODE_VER} alias=${alias}`);
    check('L14 固定下载链接走的是 /software/alias/ 且不含版本号',
      fixedUrl.includes('/software/alias/') && !fixedUrl.includes('v2.1'),
      fixedUrl);

    // ================= 固定下载链接 (按别名) 免登录 =================
    const a1 = await api(page, 'GET', `/api/v1/software/alias/${encodeURIComponent(alias)}/download`);
    const a1sha = a1.bodyB64 ? sha256(Buffer.from(a1.bodyB64, 'base64')) : '';
    check('L15 别名固定链接免登录可下载 (不带 token, 内容 sha256 一致)',
      a1.status === 200 && a1sha === SHA1,
      `HTTP ${a1.status} sha=${a1sha.slice(0, 12)}`);
    check('L16 别名下载给的是「推荐版本」 (响应头 X-Software-Version)',
      a1.headers['x-software-version'] === '1.0.0',
      `X-Software-Version=${a1.headers['x-software-version']}`);
    const a2 = await api(page, 'GET', '/api/v1/software/alias/no-such-alias-e2e/download');
    check('L17 不存在的别名 → 404', a2.status === 404, 'HTTP ' + a2.status);

    // ================= 下载票据链路 =================
    const tk = await api(page, 'POST', `/api/v1/software/${encodeURIComponent(CODE_MAIN)}/download-ticket?version=1.0.0`, {
      token: adminToken,
    });
    const dlUrl = (tk.json && tk.json.url) || '';
    check('L18 下载票据签发成功 (url 指向 /software/dl?t=)',
      tk.status === 200 && dlUrl.includes('/api/v1/software/dl?t='),
      `HTTP ${tk.status} ${dlUrl.slice(0, 48)}…`);
    const dl = await api(page, 'GET', dlUrl);   // ⚠️ **不带 token** —— 票据本身就是凭证
    const dlSha = dl.bodyB64 ? sha256(Buffer.from(dl.bodyB64, 'base64')) : '';
    check('L19 凭票据免登录下载成功 (不带 Authorization, 内容 sha256 一致)',
      dl.status === 200 && dlSha === SHA1,
      `HTTP ${dl.status} sha=${dlSha.slice(0, 12)}`);
    const dlBad = await api(page, 'GET', dlUrl.replace(/v=[^&]+/, 'v=9.9.9'));
    check('L20 票据与版本不匹配 → 403', dlBad.status === 403, 'HTTP ' + dlBad.status);
    const dlFake = await api(page, 'GET', '/api/v1/software/dl?t=forged.ticket.value&v=1.0.0');
    check('L21 伪造/过期票据 → 401', dlFake.status === 401, 'HTTP ' + dlFake.status);

    // ================= 发新版本 + 推荐位 =================
    const cv = await createVersion(page, adminToken, CODE_MAIN, '2.0.0', true);
    check('L22 发新版本 2.0.0 成功 (版本行 awaiting_file)',
      cv.status === 201 && cv.json && cv.json.version === '2.0.0',
      `HTTP ${cv.status} ${(cv.json && cv.json.version) || ''}`);
    const uv = await uploadFile(page, adminToken, CODE_MAIN, PAYLOAD2, `${CODE_MAIN}-2.0.0.bin`);
    check('L23 新版本文件上传成功 (sha256 换成新内容的)',
      uv.status === 200 && uv.json && uv.json.sha256 === SHA2,
      `HTTP ${uv.status} 后端sha=${(uv.json && uv.json.sha256 || '').slice(0, 12)} 本地=${SHA2.slice(0, 12)}`);
    const d3 = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), { token: adminToken });
    const vers = (d3.json && d3.json.versions) || [];
    check('L24 推荐版本切到 2.0.0 (旧版仍可下载)',
      d3.json && d3.json.download_version === '2.0.0'
        && vers.length === 2 && vers.every((v) => v.status === 'ready'),
      `dl=${d3.json && d3.json.download_version} 版本=${vers.map((v) => v.version + ':' + v.status).join(' ')}`);
    // ⚠️ 2026-11-06: 这里要用**主条目自己的别名** (CODE_MAIN 的 download_alias),
    //    上面那个 `alias` 是**别名条目** (CODE_VER, 只有 1.0.0) 的 ——
    //    拿错条目的话, 这里下到的当然是 1.0.0, 跟推荐版本 2.0.0 对不上.
    const aliasMain = (d3.json && d3.json.download_alias) || '';
    const a3 = await api(page, 'GET', `/api/v1/software/alias/${encodeURIComponent(aliasMain)}/download`);
    check('L25 别名固定链接自动跟着推荐版本走 (给的是 2.0.0 的内容)',
      a3.status === 200 && a3.headers['x-software-version'] === '2.0.0'
        && sha256(Buffer.from(a3.bodyB64 || '', 'base64')) === SHA2,
      `alias=${aliasMain} X-Software-Version=${a3.headers['x-software-version']} sha=${sha256(Buffer.from(a3.bodyB64 || '', 'base64')).slice(0, 12)}`);

    // ================= 改版本信息 (PATCH) =================
    const pv = await api(page, 'PATCH', `/api/v1/software/${encodeURIComponent(CODE_MAIN)}/versions/2.0.0`, {
      token: adminToken, json: { variant: 'LTS版' },
    });
    const d4 = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), { token: adminToken });
    const v200 = ((d4.json && d4.json.versions) || []).find((v) => v.version === '2.0.0');
    check('L26 PATCH 改版本信息生效 (变体标签改成 LTS版)',
      pv.status === 200 && v200 && v200.variant === 'LTS版',
      `HTTP ${pv.status} variant=${v200 && v200.variant}`);

    // ================= 删版本 =================
    const dv = await api(page, 'DELETE', `/api/v1/software/${encodeURIComponent(CODE_MAIN)}/versions/1.0.0`, {
      token: adminToken,
    });
    check('L27 DELETE 删掉一个版本成功 (另一个版本不受影响)',
      dv.status === 200 && dv.json && dv.json.item_unpublished === false && dv.json.remaining_versions === 1,
      `HTTP ${dv.status} ${dv.text.slice(0, 90)}`);
    const d5 = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), { token: adminToken });
    check('L28 删后详情里只剩 2.0.0 (条目仍然上架)',
      d5.status === 200 && (d5.json.versions || []).length === 1
        && d5.json.versions[0].version === '2.0.0' && d5.json.publish_status === 'published',
      `版本=${(d5.json.versions || []).map((v) => v.version).join(' ')} 状态=${d5.json.publish_status}`);
    const pv2 = await api(page, 'PATCH', `/api/v1/software/${encodeURIComponent(CODE_MAIN)}/versions/2.0.0`, {
      token: adminToken, json: { is_default: false },
    });
    check('L29 取消「最后一个可下载版本」的推荐 → 409 (不能把条目下成没有推荐版)',
      pv2.status === 409, `HTTP ${pv2.status} ${pv2.text.slice(0, 80)}`);
    const dvn = await api(page, 'DELETE', `/api/v1/software/${encodeURIComponent(CODE_MAIN)}/versions/9.9.9`, {
      token: adminToken,
    });
    check('L30 删不存在的版本 → 404', dvn.status === 404, 'HTTP ' + dvn.status);

    // ================= 改条目信息 (PUT /{code}) =================
    const NEW_NAME = `${NAME_MAIN} (已改名)`;
    const pu = await api(page, 'PUT', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), {
      token: adminToken,
      json: { name: NEW_NAME, summary: '改过的简介', features: ['改过的功能一', '改过的功能二'] },
    });
    const d6 = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), { token: adminToken });
    check('L31 PUT 改软件信息生效 (名字 / 简介 / 功能清单)',
      pu.status === 200 && d6.json && d6.json.name === NEW_NAME
        && d6.json.summary === '改过的简介' && (d6.json.features || []).length === 2,
      `HTTP ${pu.status} name=${d6.json && d6.json.name}`);

    // ================= 界面上看一眼"固定下载链接" =================
    await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1200);
    await page.screenshot({ path: path.join(OUT_DIR, 'sw-lc-1-list.png') });
    const openDrawer = async (name) => {
      const hit = await page.evaluate((n) => {
        const card = [...document.querySelectorAll('.asset-card')]
          .find((c) => (c.querySelector('.ac-name')?.textContent || '').includes(n));
        if (!card) return false;
        card.click();
        return true;
      }, name);
      if (!hit) return '';
      await page.waitForSelector('.sw-drawer .fx-url', { timeout: 15000 });
      await sleep(500);
      const url = await page.evaluate(() => {
        const d = document.querySelector('.sw-drawer');
        return {
          fx: d ? (d.querySelector('.fx-url')?.textContent || '').trim() : '',
          text: d ? d.innerText.slice(0, 200) : '',
        };
      });
      await page.screenshot({ path: path.join(OUT_DIR, 'sw-lc-2-detail.png') });
      await page.keyboard.press('Escape');
      await sleep(600);
      return url.fx;
    };
    const fxMain = await openDrawer(NEW_NAME);
    check('L32 详情抽屉里「固定下载链接」= 别名地址 (不含版本号)',
      fxMain.includes('/software/alias/') && !fxMain.includes('v2.1'),
      fxMain);
    const fxVer = await openDrawer(NAME_VER);
    check('L33 带版本号的条目, 抽屉里的链接同样不含版本号',
      fxVer.includes('/software/alias/') && !fxVer.includes('v2.1'),
      fxVer);

    // ================= 不存在 / 非法 =================
    const miss = '/api/v1/software/e2e-sw-lc-not-exist-' + STAMP;
    const g404 = await api(page, 'GET', miss, { token: adminToken });
    check('L34 不存在的 code 查详情 → 404', g404.status === 404, 'HTTP ' + g404.status);
    const d404 = await api(page, 'DELETE', miss, { token: adminToken });
    check('L35 不存在的 code 删条目 → 404', d404.status === 404, 'HTTP ' + d404.status);
    const p404 = await api(page, 'PATCH', miss + '/versions/1.0.0', { token: adminToken, json: { variant: 'x' } });
    check('L36 不存在的 code 改版本 → 404', p404.status === 404, 'HTTP ' + p404.status);
    const badCode = await api(page, 'POST', '/api/v1/software', {
      token: adminToken,
      json: { code: 'Bad Code!@', name: '非法标识', version: '1.0.0', file_name: 'x.bin' },
    });
    check('L37 非法软件标识 → 422', badCode.status === 422, `HTTP ${badCode.status} ${badCode.text.slice(0, 80)}`);
    const badName = await api(page, 'POST', '/api/v1/software', {
      token: adminToken,
      json: { code: `e2e-sw-lc-${STAMP}bad`, name: '非法文件名', version: '1.0.0', file_name: '中文名.zip' },
    });
    check('L38 非法软件包文件名 → 422', badName.status === 422, `HTTP ${badName.status} ${badName.text.slice(0, 80)}`);
    const badVerSlash = await createVersion(page, adminToken, CODE_MAIN, 'a/b');
    check('L39 版本号带斜杠 → 422', badVerSlash.status === 422, `HTTP ${badVerSlash.status} ${badVerSlash.text.slice(0, 80)}`);
    const badVerEmpty = await createVersion(page, adminToken, CODE_MAIN, '');
    check('L40 版本号为空 → 422', badVerEmpty.status === 422, `HTTP ${badVerEmpty.status}`);
    const badVerLong = await createVersion(page, adminToken, CODE_MAIN, 'v'.repeat(33));
    check('L41 版本号超长 (>32) → 422', badVerLong.status === 422, `HTTP ${badVerLong.status}`);

    // ================= 重复 =================
    const dupVer = await createVersion(page, adminToken, CODE_MAIN, '2.0.0', true);
    check('L42 重复版本号 → 409', dupVer.status === 409, `HTTP ${dupVer.status} ${dupVer.text.slice(0, 80)}`);
    const dupFile = await uploadFile(page, adminToken, CODE_MAIN, PAYLOAD1, `${CODE_MAIN}-2.0.0.bin`);
    check('L43 同一版本重复上传文件 → 409 (想换包请发新版本)', dupFile.status === 409,
      `HTTP ${dupFile.status} ${dupFile.text.slice(0, 80)}`);
    const dupIcon = await api(page, 'POST', '/api/v1/software', {
      token: adminToken,
      json: {
        code: `e2e-sw-lc-${STAMP}e`, name: '撞图标', icon: ICON_MAIN,
        version: '1.0.0', file_name: `e2e-sw-lc-${STAMP}e.bin`,
      },
    });
    check('L44 重复图标 → 409', dupIcon.status === 409, `HTTP ${dupIcon.status} ${dupIcon.text.slice(0, 80)}`);
    const dupIconGone = await api(page, 'GET', `/api/v1/software/e2e-sw-lc-${STAMP}e`, { token: adminToken });
    check('L45 撞图标的请求**没有**留下条目', dupIconGone.status === 404, 'HTTP ' + dupIconGone.status);
    const dupCode = await api(page, 'POST', '/api/v1/software', {
      token: adminToken,
      json: {
        code: CODE_MAIN, name: '撞标识', icon: ICON_DUP,
        version: '1.0.0', file_name: `${CODE_MAIN}.bin`,
      },
    });
    const dupCodeOut = (dupCode.json && dupCode.json.code) || '';
    check('L46 重复标识不是 409, 而是自动加序号 (后端口径: 撞名自动 base2/base3)',
      dupCode.status === 201 && dupCodeOut !== CODE_MAIN && dupCodeOut.startsWith(CODE_MAIN),
      `HTTP ${dupCode.status} code=${dupCodeOut}`);
    if (dupCodeOut) created.add(dupCodeOut);

    // ================= 越权 (非管理员动别人的东西) =================
    const own = await api(page, 'PUT', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), {
      token: tmpToken, json: { name: '我改了' },
    });
    check('L47 越权: 非管理员改别人的软件 → 403', own.status === 403,
      `HTTP ${own.status} ${own.text.slice(0, 80)}`);
    const ownVer = await api(page, 'PATCH', `/api/v1/software/${encodeURIComponent(CODE_MAIN)}/versions/2.0.0`, {
      token: tmpToken, json: { variant: '我改的' },
    });
    check('L48 越权: 非管理员改别人的版本 → 403', ownVer.status === 403, 'HTTP ' + ownVer.status);
    const ownNew = await createVersion(page, tmpToken, CODE_MAIN, '3.0.0', true);
    check('L49 越权: 非管理员给别人的软件发新版本 → 403', ownNew.status === 403,
      `HTTP ${ownNew.status} ${ownNew.text.slice(0, 80)}`);
    const ownDelVer = await api(page, 'DELETE', `/api/v1/software/${encodeURIComponent(CODE_MAIN)}/versions/2.0.0`, {
      token: tmpToken,
    });
    check('L50 越权: 非管理员删别人的版本 → 403', ownDelVer.status === 403, 'HTTP ' + ownDelVer.status);
    const ownDel = await api(page, 'DELETE', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), {
      token: tmpToken,
    });
    check('L51 越权: 非管理员删别人的软件 → 403', ownDel.status === 403, `HTTP ${ownDel.status}`);
    const ownPurge = await api(page, 'DELETE', '/api/v1/software/' + encodeURIComponent(CODE_MAIN) + '/purge', {
      token: tmpToken,
    });
    check('L52 越权: 非管理员彻底清理别人的软件 → 403', ownPurge.status === 403, 'HTTP ' + ownPurge.status);
    const stillThere = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), { token: adminToken });
    check('L53 越权尝试之后条目**完好无损** (没被改/没被删)',
      stillThere.status === 200 && stillThere.json.name === NEW_NAME
        && (stillThere.json.versions || []).length === 1,
      `HTTP ${stillThere.status} name=${stillThere.json && stillThere.json.name}`);

    // ================= 存储路径体检 =================
    const pc = await api(page, 'GET', '/api/v1/software/path-check', { token: adminToken });
    check('L54 path-check 管理员可用 (root / roots / missing / lost 都在)',
      pc.status === 200 && pc.json && !!pc.json.root && Array.isArray(pc.json.roots)
        && Array.isArray(pc.json.missing) && Array.isArray(pc.json.lost),
      `HTTP ${pc.status} root=${pc.json && pc.json.root}`);
    const pcNo = await api(page, 'GET', '/api/v1/software/path-check', { token: tmpToken });
    check('L55 path-check 非管理员 → 403 (admin only)', pcNo.status === 403, 'HTTP ' + pcNo.status);

    // ================= 数量上限 (software.keep_versions) =================
    // ⚠️ 用**配置里本来就有的**上限值来测 —— 不改全局设置, 免得连带影响别人的条目.
    const keep = Number(savedSettings['software.keep_versions'] || 0);
    if (keep > 0 && keep <= 12) {
      const cc = await createItem(page, adminToken, CODE_CNT, `E2E 数量上限 ${STAMP}`, ICON_CNT, '1.0.0');
      check('L56 数量上限探针条目创建成功', cc.status === 201, 'HTTP ' + cc.status);
      const SMALL = Buffer.from('count probe\n'.repeat(32));
      // ⚠️ 2026-11-06: 1.0.0 也**必须传文件** —— 剪枝只处理 status='ready' 的版本,
      //    没传文件的那条是 awaiting_file, 根本不进剪枝名单 → 留着 → 数出来多一个.
      //    (以前这里没传, 于是留下 keep+1 个, 断言一直红.)
      await uploadFile(page, adminToken, CODE_CNT, SMALL, `${CODE_CNT}-1.0.0.bin`);
      let lastV = '';
      for (let i = 1; i <= keep + 1; i++) {
        lastV = `v${i}.0`;
        await createVersion(page, adminToken, CODE_CNT, lastV, true);
        await uploadFile(page, adminToken, CODE_CNT, SMALL, `${CODE_CNT}-${lastV}.bin`);
      }
      const dc = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_CNT), { token: adminToken });
      const cvs = (dc.json && dc.json.versions) || [];
      check('L57 版本数超过保留上限 → 最老的被自动清掉 (keep_versions=' + keep + ')',
        cvs.length === keep && !cvs.some((v) => v.version === 'v1.0') && cvs.some((v) => v.version === lastV),
        `留下 ${cvs.length} 个: ${cvs.map((v) => v.version).join(' ')}`);
    } else {
      check('L56 数量上限 (keep_versions) 本次跳过 (配置值不在 1~12, 不想改全局设置)',
        true, `software.keep_versions=${savedSettings['software.keep_versions']}`);
      check('L57 版本数超过保留上限 → 最老的被自动清掉', true, '跳过');
    }

    // ================= 大小上限 (413) =================
    // ⚠️ 软件库默认上限 5120MB —— 传 5G 不现实, 所以**临时把上限调到 1MB**再试,
    //    试完立刻还原 (原值已存). 这一小段时间里别人的超大包会被拒, 窗口极短.
    const origMax = savedSettings['software.max_size_mb'];
    const co = await createItem(page, adminToken, CODE_OVR, `E2E 大小超限 ${STAMP}`, ICON_OVR, '1.0.0');
    check('L58 大小上限探针条目创建成功', co.status === 201, 'HTTP ' + co.status);
    const stMax = await putSetting(page, adminToken, 'software.max_size_mb', '1');
    const BIG = Buffer.alloc(2 * 1024 * 1024, 0x41);   // 2MB > 1MB
    const bigUp = await uploadFile(page, adminToken, CODE_OVR, BIG);
    check('L59 超过单文件大小上限 → 413 (文件被拒, 没落盘)',
      stMax === 200 && bigUp.status === 413,
      `HTTP ${bigUp.status} ${bigUp.text.slice(0, 80)}`);
    const backMax = await putSetting(page, adminToken, 'software.max_size_mb', origMax);
    const nowMax = await getSettings(page, adminToken, ['software.max_size_mb']);
    check('L60 大小上限已还原成原值', backMax === 200 && String(nowMax['software.max_size_mb']) === String(origMax),
      `原值=${origMax} 现在=${nowMax['software.max_size_mb']}`);
    const dovr = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_OVR), { token: adminToken });
    check('L61 超限那次没把条目推上架 (仍是 awaiting_file)',
      dovr.status === 200 && dovr.json && dovr.json.publish_status === 'awaiting_file',
      `状态=${dovr.json && dovr.json.publish_status}`);

    // ================= 删条目 (软删) → 彻底清理 (purge) =================
    const ds = await api(page, 'DELETE', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), { token: adminToken });
    check('L62 DELETE 删条目成功 (软删, 文件先留着)', ds.status === 200 && ds.json && ds.json.ok === true,
      `HTTP ${ds.status} ${ds.text.slice(0, 80)}`);
    const dsd = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), { token: adminToken });
    check('L63 软删后查详情 → 404 (条目已下架)', dsd.status === 404, 'HTTP ' + dsd.status);
    const dsa = await api(page, 'GET', `/api/v1/software/alias/${encodeURIComponent(aliasMain)}/download`);
    check('L64 软删后别名固定链接也 404 (未上架的不给免登录下载)', dsa.status === 404, 'HTTP ' + dsa.status);
    const dp = await api(page, 'DELETE', '/api/v1/software/' + encodeURIComponent(CODE_MAIN) + '/purge', { token: adminToken });
    check('L65 purge 彻底清理成功 (记录 + 磁盘文件一起删)',
      dp.status === 200 && dp.json && dp.json.ok === true,
      `HTTP ${dp.status} deleted_files=${dp.json && dp.json.deleted_files}`);
    // ⚠️ 已经在 L65 purge 掉了 → 把它从待清理集合里摘出去,
    //    不然收尾那轮再 purge 一次会拿到 404, 条目就永远留在集合里 (L68 误报).
    if (dp.status === 200) created.delete(CODE_MAIN);
    const dpg = await api(page, 'GET', '/api/v1/software/' + encodeURIComponent(CODE_MAIN), { token: adminToken });
    check('L66 purge 后查详情仍然 404', dpg.status === 404, 'HTTP ' + dpg.status);
    const pc2 = await api(page, 'GET', '/api/v1/software/path-check', { token: adminToken });
    const orphans = (pc2.json && pc2.json.orphan_dirs) || [];
    check('L67 purge 后磁盘目录真的没了 (path-check 里没有我们的孤儿目录)',
      !orphans.some((o) => (o.name || '').includes(STAMP)),
      `孤儿目录=${orphans.map((o) => o.name).join(' ') || '(无)'}`);

    // ================= 收尾: 删干净 + 还原设置 =================
    // 剩下的条目 (别名 / 数量 / 大小 / 撞标识) 逐个 purge
    for (const code of Array.from(created)) {
      if (!code) continue;
      const r = await api(page, 'DELETE', '/api/v1/software/' + encodeURIComponent(code) + '/purge', { token: adminToken });
      if (r.status === 200) created.delete(code);
    }
    check('L68 本次创建的所有条目都已 purge 干净',
      created.size === 0,
      `残留=${Array.from(created).join(' ') || '(无)'}`);
    const leftOver = await api(page, 'GET', `/api/v1/software?q=${encodeURIComponent(STAMP)}&limit=100`, { token: adminToken });
    const leftovers = ((leftOver.json && leftOver.json.items) || []).filter((i) => (i.code || '').includes(STAMP));
    check('L69 库里搜不到本次的残留条目', leftovers.length === 0,
      leftovers.map((i) => i.code).join(' ') || '(无)');
  } catch (e) {
    check('脚本执行', false, String((e && e.stack) || e));
  } finally {
    // ---- 还原生产设置 (先读原值再改, 这里按原值写回) ----
    try {
      for (const k of NOTIFY_SWITCHES) {
        if (k in savedSettings) await putSetting(page, adminToken, k, savedSettings[k]);
      }
      if ('extensions.publisher_usernames' in savedSettings) {
        await putSetting(page, adminToken, 'extensions.publisher_usernames', savedSettings['extensions.publisher_usernames']);
      }
      if ('software.max_size_mb' in savedSettings) {
        await putSetting(page, adminToken, 'software.max_size_mb', savedSettings['software.max_size_mb']);
      }
      const after = await getSettings(page, adminToken, [...NOTIFY_SWITCHES, 'extensions.publisher_usernames', 'software.max_size_mb']);
      const same = NOTIFY_SWITCHES.every((k) => after[k] === savedSettings[k])
        && String(after['software.max_size_mb']) === String(savedSettings['software.max_size_mb'])
        && String(after['extensions.publisher_usernames'] || '') === String(savedSettings['extensions.publisher_usernames'] || '');
      check('L70 生产设置已全部按原值还原 (通知开关 / 白名单 / 大小上限)', same,
        NOTIFY_SWITCHES.map((k) => `${k}=${after[k]}`).join(' '));
    } catch (e) {
      check('L70 生产设置已全部按原值还原', false, String(e && e.message || e));
    }
    // ---- 删临时账号 ----
    try {
      if (tmpUserId) {
        const dr = await api(page, 'DELETE', '/api/v1/auth/users/' + tmpUserId, { token: adminToken });
        const ul = await api(page, 'GET', '/api/v1/auth/users', { token: adminToken });
        const still = (ul.json || []).some((u) => u.username === (ul.json.find((x) => x.id === tmpUserId) || {}).username
          || (u.username || '').includes(TMP_USER));
        check('L71 临时非管理员账号已删除 (回读确认)', dr.status === 204 && !still,
          `HTTP ${dr.status} 残留=${still}`);
      } else {
        check('L71 临时非管理员账号已删除 (回读确认)', true, '没建成功, 无需删');
      }
    } catch (e) {
      check('L71 临时非管理员账号已删除 (回读确认)', false, String(e && e.message || e));
    }
    // ---- 清掉本次创建的条目 (万一中途抛错) ----
    try {
      for (const code of Array.from(created)) {
        if (!code) continue;
        await api(page, 'DELETE', '/api/v1/software/' + encodeURIComponent(code) + '/purge', { token: adminToken });
      }
    } catch (e) { /* 收尾尽力而为 */ }
    check('L72 全程无页面 JS 错误', pageErrors.length === 0, pageErrors.slice(0, 2).join(' | '));
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) {
    console.log('失败项:');
    failed.forEach((f) => console.log(`  ✗ ${f.name}  ${f.detail || ''}`));
  }
  process.exit(failed.length ? 1 : 0);
})();
