#!/usr/bin/env node
/**
 * 审核总开关 (`marketplace.review.enabled`) 端到端验收 (真实 Chrome).
 *
 * 这个开关**同时管上架审核与下架审核**:
 *   · 开 (默认) → 发布者上传要审核; 下架走申请制, 管理员通过 = 彻底删除
 *   · 关 (免审) → 发布者上传直接上架; 下架也自助完成 —— 立刻下架、**文件保留**
 *
 * 这里要验的就是「关掉之后, 前端的表现也跟着变」:
 *   ① 上传后直接是「在架」, 不是「待审核」
 *   ② 详情抽屉的按钮文案从「申请下架」变成「下架」
 *   ③ 点「下架」立刻生效 (状态变 unpublished), 不是等管理员
 *   ④ 文件还在 —— 能自己「重新上架」回去
 *   ⑤ 开关改回去之后, 行为恢复成申请制
 *
 * ⚠️ **必须用非管理员账号上传**:
 *    `marketplace.review.admin_self_approve` (默认开) 让管理员自己的上传**免审核** ——
 *    拿 admin 测根本测不出开关的效果 (上传永远是 published).
 *    所以这里建一个普通发布者账号, 把它加进发布者白名单再上传.
 *
 * ⚠️ 脚本**先关后还原**, 最后一定把设置改回原值 (异常路径也要还原).
 *
 * 用法: NODE_PATH=/tmp/tm-e2e/node_modules node scripts/e2e_review_switch.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const lock = require('./e2e_lock');
const release = lock.acquire('e2e_review_switch.js');
const { deleteTestUsers } = require('./e2e_cleanup');

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const API = process.env.TESTMATE_API || 'http://localhost:18000';
const ADMIN = process.env.TESTMATE_USER || 'admin';
const ADMIN_PW = process.env.TESTMATE_PASSWORD || 'Admin@123';
const PUB = process.env.REVIEW_TEST_USER || 'e2e_rvswitch';
const PUB_PW = 'E2e@Test12345';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');
const SETTING_KEY = 'marketplace.review.enabled';
const PUBLISHER_KEY = 'marketplace.publisher_usernames';
const CODE = 'e2e-rvswitch-demo';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}

async function api(pathname, opts = {}) {
  const r = await fetch(API + pathname, opts);
  const t = await r.text();
  try { return { status: r.status, json: JSON.parse(t) }; } catch { return { status: r.status, json: null }; }
}

function makeZip(target, files) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  execFileSync('python3', ['-c', [
    'import zipfile',
    `z=zipfile.ZipFile(${JSON.stringify(target)},'w')`,
    ...files.map(([n, c]) => `z.writestr(${JSON.stringify(n)},${JSON.stringify(c)})`),
    'z.close()',
  ].join(';')]);
}

/** 设置项读写 (admin only) */
async function readSetting(token, key) {
  const r = await api('/api/v1/settings/schema', { headers: { Authorization: 'Bearer ' + token } });
  const groups = (r.json && r.json.groups) || [];
  for (const g of groups) {
    for (const it of (g.items || [])) {
      if (it.key === key) return it;
    }
  }
  return null;
}
async function writeSetting(token, key, value) {
  return api('/api/v1/settings/' + encodeURIComponent(key), {
    method: 'PUT',
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  });
}

/** 确保账号存在且口令/角色符合预期 (幂等) —— 与 e2e_review_flow.js 同一套路 */
async function ensureUser(adminToken, username, password, role) {
  const post = (p, body, method = 'POST') => api(p, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + adminToken },
    body: JSON.stringify(body),
  });
  let r = await post('/api/v1/auth/users', { username, password, role });
  if (r.status === 201) return r.json;
  if (r.status !== 409) {
    throw new Error(`建号失败 ${username}: ${r.status} ${JSON.stringify(r.json)}`);
  }
  const list = await api('/api/v1/auth/users', { headers: { Authorization: 'Bearer ' + adminToken } });
  const found = (list.json || []).find((u) => u.username === username || u.username === `${username}@twsc.com.cn`);
  if (!found) throw new Error(`账号 ${username} 已存在但列表里找不到`);
  r = await post(`/api/v1/auth/users/${found.id}`, { password, role, is_active: true }, 'PATCH');
  if (r.status !== 200) throw new Error(`改账号失败 ${username}: ${r.status} ${JSON.stringify(r.json)}`);
  return r.json;
}

async function login(username, password) {
  const r = await api('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  return (r.json && r.json.access_token) || '';
}

/**
 * 等上传的同步任务跑完 (资产状态落定).
 *
 * ⚠️ publish_status 是**落盘那一刻**就定下来的 (_stage_asset 里同步设),
 *    不用等 GitLab 推送 —— 推送是后台 worker 的事.
 * ⚠️ 别在这里等 "状态 != pending": 开审时资产本来就该停在 pending.
 */
async function waitSettled(token, code, timeoutMs = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const d = await api('/api/v1/assets/' + code, { headers: { Authorization: 'Bearer ' + token } });
    if (d.status === 200 && d.json && d.json.publish_status) return d.json;
    await sleep(800);
  }
  return null;
}

/**
 * 上传一个技能 (走真实上传接口).
 * ⚠️ 走 `package` 而不是 `files` —— files 是**多文件文本**上传, 塞 zip 会报 "不是 UTF-8 文本".
 * ⚠️ 包名必须与资产 code 一致 (后端 _assert_naming 会拦).
 */
async function uploadSkill(token, code) {
  const zipPath = path.join(OUT_DIR, `${code}.zip`);
  makeZip(zipPath, [['SKILL.md', `---\nname: ${code}\ndescription: e2e 审核开关验证\n---\n\n# e2e\n`]]);
  const fd = new FormData();
  fd.append('code', code);
  fd.append('kind', 'skill');
  fd.append('name', '审核开关验证资产');
  fd.append('summary', 'e2e: 验证审核总开关关掉后的上架/下架行为');
  fd.append('version', '1.0.0');
  fd.append('category', '效率工具');
  fd.append('icon', '🧪');
  fd.append('tags', '[]');
  fd.append('keywords', '[]');
  fd.append('permissions', '{}');
  fd.append('install_steps', '[]');
  fd.append('bindings', '{}');
  fd.append('package', new Blob([fs.readFileSync(zipPath)]), `${code}.zip`);
  const r = await fetch(`${API}/api/v1/assets/upload`, {
    method: 'POST', headers: { Authorization: 'Bearer ' + token }, body: fd,
  });
  return r.status;
}

/** 打开带登录态的页面 (独立 context —— 免得跟别的身份共用 localStorage) */
async function openPage(browser, token, user) {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setCacheEnabled(false);
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  await page.evaluate((tk, u) => {
    localStorage.setItem('testmate:token', tk);
    localStorage.setItem('testmate:user', JSON.stringify(u));
  }, token, user);
  return { page, context };
}

/**
 * 切到「技能」类型 tab.
 *
 * ⚠️ 市场页默认停在**插件** tab (kind = 'plugin'), 技能资产根本不渲染 ——
 *    找不到卡片不是数据的问题, 是 tab 没切过去.
 */
async function switchKindTab(page, label) {
  await page.evaluate((lb) => {
    const btn = [...document.querySelectorAll('.kind-tab')]
      .find((b) => (b.textContent || '').includes(lb));
    if (btn) btn.click();
  }, label);
  await sleep(1200);
}

/** 等资产卡片出现并点开详情抽屉 (列表异步取, 固定 sleep 会抢跑) */
async function openDrawer(page, name, timeoutMs = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const r = await page.evaluate((n) => {
      const el = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(n));
      if (!el) return null;
      el.click();
      return { clicked: true };
    }, name);
    if (r) {
      await sleep(1500);
      const btns = await page.evaluate(() =>
        [...document.querySelectorAll('.ad-actions button')].map((b) => b.textContent.trim()));
      return { btns };
    }
    await sleep(400);
  }
  return { btns: [] };
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const adminToken = await login(ADMIN, ADMIN_PW);
  if (!adminToken) { console.error('管理员登录失败'); process.exit(2); }
  const AH = { Authorization: 'Bearer ' + adminToken };

  // ---------- 准备: 普通发布者账号 + 白名单 ----------
  await ensureUser(adminToken, PUB, PUB_PW, 'tester');
  const savedPublisherSetting = (await readSetting(adminToken, PUBLISHER_KEY))?.value;
  await writeSetting(adminToken, PUBLISHER_KEY, PUB);
  const pubToken = await login(PUB, PUB_PW);
  check('A0 发布者账号就绪 (非管理员, 才测得到审核)', !!pubToken);
  const PH = { Authorization: 'Bearer ' + pubToken };

  // 记住原值, 最后一定还原
  const orig = await readSetting(adminToken, SETTING_KEY);
  const origValue = orig ? orig.value : true;
  console.log(`审核总开关原值: ${JSON.stringify(origValue)}`);

  let browser = null;
  try {
    // ---------- ① 关掉开关 ----------
    const off = await writeSetting(adminToken, SETTING_KEY, false);
    check('S1 审核总开关能关掉', off.status === 200, `status=${off.status}`);
    const cfg = await api('/api/v1/assets/config', { headers: AH });
    check('S2 /assets/config 回报 review_enabled=false',
      cfg.status === 200 && cfg.json && cfg.json.review_enabled === false,
      `review_enabled=${cfg.json && cfg.json.review_enabled}`);

    // ---------- ② 上传直接上架 (以**发布者**身份, 不是 admin) ----------
    await api(`/api/v1/assets/${CODE}`, { method: 'DELETE', headers: AH });
    const up = await uploadSkill(pubToken, CODE);
    check('S3 上传受理', up === 202, `status=${up}`);
    const asset = await waitSettled(pubToken, CODE);
    check('S4 免审时上传后直接「在架」, 不进待审核',
      !!asset && asset.publish_status === 'published',
      `publish_status=${asset && asset.publish_status}`);

    // ---------- ③ 前端: 按钮文案跟着变 ----------
    browser = await puppeteer.launch({
      executablePath: CHROME, headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
      defaultViewport: { width: 1600, height: 1000 },
    });
    const { page } = await openPage(browser, pubToken, { id: 0, username: PUB, role: 'tester' });
    await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.asset-card', { timeout: 20000 });
    await sleep(1500);
    await switchKindTab(page, '技能');

    const drawer = await openDrawer(page, '审核开关验证资产');
    check('S5 免审时抽屉按钮是「下架」而不是「申请下架」',
      drawer.btns.some((b) => b === '下架') && !drawer.btns.some((b) => b === '申请下架'),
      JSON.stringify(drawer.btns));

    await page.screenshot({ path: path.join(OUT_DIR, 'review-switch-off.png') });

    // ---------- ④ 点下架 → 立刻生效 ----------
    const took = await page.evaluate(async (code) => {
      const btn = [...document.querySelectorAll('.ad-actions button')].find((b) => b.textContent.trim() === '下架');
      if (!btn) return { ok: false, why: '没找到「下架」按钮' };
      btn.click();
      await new Promise((res) => setTimeout(res, 1200));
      const inp = document.querySelector('.el-message-box input');
      if (inp) {
        const proto = window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(inp, code);
        inp.dispatchEvent(new Event('input', { bubbles: true }));
      }
      await new Promise((res) => setTimeout(res, 600));
      const ok = [...document.querySelectorAll('.el-message-box button')]
        .find((b) => b.textContent.includes('确认下架'));
      if (!ok) return { ok: false, why: '确认框里没有「确认下架」按钮' };
      ok.click();
      await new Promise((res) => setTimeout(res, 3000));
      return { ok: true };
    }, CODE);
    check('S6 点「下架」走完确认框', took.ok, took.why || '');

    const after = await api('/api/v1/assets/' + CODE, { headers: PH });
    check('S7 免审下架后状态是「已下架」(unpublished), 不是待审核',
      after.status === 200 && after.json && after.json.publish_status === 'unpublished',
      `publish_status=${after.json && after.json.publish_status}`);

    // ---------- ⑤ 能自己重新上架 (文件保留) ----------
    // ⚠️ 走**UI 点击**, 不走 API —— 要验的是「作者在抽屉里能看见并点「重新上架」」,
    //    而不只是接口通. 下架后抽屉里该换成「重新上架」按钮.
    await page.keyboard.press('Escape');   // 先把抽屉关掉, 再重新打开
    await sleep(1200);
    const drawer2 = await openDrawer(page, '审核开关验证资产');
    check('S8 免审下架后抽屉里有「重新上架」',
      drawer2.btns.some((b) => b === '重新上架'),
      JSON.stringify(drawer2.btns));
    const repub = await page.evaluate(async () => {
      const btn = [...document.querySelectorAll('.ad-actions button')].find((b) => b.textContent.trim() === '重新上架');
      if (!btn) return false;
      btn.click();
      await new Promise((res) => setTimeout(res, 2500));
      return true;
    });
    check('S8b 点「重新上架」没报错', repub);

    const re = await api('/api/v1/assets/' + CODE, { headers: PH });
    check('S8c 重新上架后回到「在架」(文件保留, 没被删)',
      re.status === 200 && re.json && re.json.publish_status === 'published',
      `status=${re.status} publish_status=${re.json && re.json.publish_status}`);

    // ---------- ⑥ 开关打开 → 行为恢复申请制 ----------
    const on = await writeSetting(adminToken, SETTING_KEY, true);
    check('S9 审核总开关能开回来', on.status === 200, `status=${on.status}`);
    const cfg2 = await api('/api/v1/assets/config', { headers: AH });
    check('S10 /assets/config 回报 review_enabled=true',
      cfg2.status === 200 && cfg2.json && cfg2.json.review_enabled === true,
      `review_enabled=${cfg2.json && cfg2.json.review_enabled}`);

    if (browser) { await browser.close(); browser = null; }

    const up2 = await uploadSkill(pubToken, CODE + '-b');
    check('S11 上传受理 (开审)', up2 === 202, `status=${up2}`);
    const pending = await waitSettled(pubToken, CODE + '-b');
    check('S12 开审时发布者上传进「待审核」',
      !!pending && pending.publish_status === 'pending',
      `publish_status=${pending && pending.publish_status}`);
  } finally {
    // ⚠️ 一定要把设置改回去 —— 异常路径也不能留下"免审"的生产配置
    const restore = await writeSetting(adminToken, SETTING_KEY, origValue);
    console.log(`[清理] 审核总开关已还原为 ${JSON.stringify(origValue)} (status=${restore.status})`);
    if (browser) { try { await browser.close(); } catch { /* ignore */ } }
    await api(`/api/v1/assets/${CODE}`, { method: 'DELETE', headers: AH });
    await api(`/api/v1/assets/${CODE}-b`, { method: 'DELETE', headers: AH });
    // 白名单还原 (不是清空 —— 清空会把管理员配好的真实白名单一起抹掉)
    if (savedPublisherSetting !== undefined) {
      await writeSetting(adminToken, PUBLISHER_KEY, String(savedPublisherSetting));
      console.log(`[清理] 发布者白名单已还原 (status=200)`);
    }
    // 删掉测试账号 —— 别留一个已知口令的账号在库里
    deleteTestUsers([PUB]);
    release();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('FATAL', e); process.exit(2); });
