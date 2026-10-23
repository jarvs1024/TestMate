#!/usr/bin/env node
/**
 * 资产市场 —— 真实业务场景端到端验收.
 *
 * 场景: 团队新同事「小王」入职, 要把自研的技能分享到市场;
 *       管理员要审核; 同事「小李」把它装到自己机器上; 后来资产被下架再重新上架,
 *       最后彻底删除.
 *
 * 全程用**三个独立身份** (管理员 / 发布者 / 安装者), 三个独立的浏览器上下文
 * (⚠️ 同一 origin 的多个页面共享 localStorage, 身份会互相覆盖 —— 必须分开).
 *
 * 覆盖: 上传 → 待审核 → 驳回 → 重新提交 → 通过 → 上架可见 → 安装 →
 *       可更新 → 下架(已装的仍可见) → 重新上架 → 彻底删除 → 审计/回执/状态统计.
 *
 * 用法: node scripts/e2e_market_scenarios.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const API = process.env.TESTMATE_API || 'http://localhost:18000';
const ADMIN = process.env.TESTMATE_USER || 'admin';
const ADMIN_PW = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');

const PUBLISHER = { username: 'e2e_scenario_pub', password: 'Scen@12345' };
const INSTALLER = { username: 'e2e_scenario_ins', password: 'Scen@12345' };
const ASSET = 'scenario-ssd-skill';
const PKG = path.join(OUT_DIR, 'scenario-skill.zip');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}

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

/** 打开一个带登录态的页面 (独立 context → 独立 localStorage) */
async function openAs(browser, token, user) {
  const ctx = await browser.createBrowserContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e.message)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  await page.evaluate((tk, u) => {
    localStorage.setItem('testmate:token', tk);
    localStorage.setItem('testmate:user', JSON.stringify(u));
  }, token, user);
  return { page, errors, ctx };
}

async function login(username, password) {
  const r = await api('/api/v1/auth/login', {
    method: 'POST', body: { username, password },
  });
  if (r.status !== 200) throw new Error(`登录失败 ${username}: ${r.status} ${r.text}`);
  return r.json.access_token;
}

async function ensureUser(token, username, password, role) {
  await api('/api/v1/auth/register', {
    method: 'POST', token,
    body: { username, password, role },
  });
}

async function setSetting(token, key, value) {
  const r = await api(`/api/v1/settings/${key}`, {
    method: 'PUT', token, body: { value },
  });
  if (r.status !== 200) throw new Error(`设置 ${key} 失败: ${r.status} ${r.text}`);
}

/**
 * 读设置项当前值 (只取指定 key).
 * ⚠️ 改之前必须先存住 —— 场景脚本改的是**生产设置**, 结束必须还原.
 * 否则测一次就把「发布白名单」永久改成测试账号, 账号删掉后白名单还指着它.
 */
async function getSettings(token, keys) {
  const r = await api('/api/v1/settings/schema', { token });
  const out = {};
  if (r.status !== 200) return out;
  for (const g of (r.json.groups || [])) {
    for (const it of (g.items || [])) {
      if (keys.includes(it.key)) out[it.key] = it.value;
    }
  }
  return out;
}

function makePkg() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  execFileSync('python3', ['-c', `
import zipfile
z = zipfile.ZipFile(${JSON.stringify(PKG)}, 'w')
z.writestr('SKILL.md', '---\\nname: scenario-ssd-skill\\ndescription: 场景验证用技能\\n---\\n\\n# 场景验证用技能\\n\\n给团队用的 SSD 日志速查技能。\\n')
z.writestr('reference/errcodes.md', '# 错误码速查\\n')
z.close()
`]);
  return PKG;
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const adminToken = await login(ADMIN, ADMIN_PW);
  await ensureUser(adminToken, PUBLISHER.username, PUBLISHER.password, 'tester');
  await ensureUser(adminToken, INSTALLER.username, INSTALLER.password, 'viewer');
  const pubToken = await login(PUBLISHER.username, PUBLISHER.password);
  const insToken = await login(INSTALLER.username, INSTALLER.password);

  // 预清理: 上一轮崩了会留下同名资产 (上传会 409, 后面全乱)
  const stale = await api(`/api/v1/assets/${ASSET}`, { method: 'DELETE', token: adminToken });
  if (stale.status === 200) console.log('  [预清理] 已删除残留资产', ASSET);

  // 场景前置: 开审核 + 把小王加进发布白名单
  // ⚠️ 改的是**生产设置** —— 先存原值, 结束必须还原.
  //    (只删测试账号是不够的: 白名单里留着已删除的测试账号 = 脏配置)
  const TOUCHED = ['marketplace.review.enabled', 'marketplace.publisher_usernames'];
  const savedSettings = await getSettings(adminToken, TOUCHED);

  const pkg = makePkg();
  let browser = null;
  try {
    await setSetting(adminToken, 'marketplace.review.enabled', 'true');
    await setSetting(adminToken, 'marketplace.publisher_usernames', PUBLISHER.username);

    browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: true,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
      defaultViewport: { width: 1600, height: 1000 },
    });
    // ===== ① 小王上传技能包 → 进入待审核 =====
    const pub = await openAs(browser, pubToken, { id: 0, username: PUBLISHER.username, role: 'tester' });
    await pub.page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
    await pub.page.waitForSelector('.mini-btn.primary', { timeout: 15000 });
    await pub.page.evaluate(() => {
      const b = [...document.querySelectorAll('.mini-btn.primary')].find((x) => x.textContent.includes('上传资产'));
      b && b.click();
    });
    await pub.page.waitForSelector('.file-input', { timeout: 10000 });
    await sleep(400);
    const input = await pub.page.$('.file-input');
    await input.uploadFile(pkg);
    await pub.page.waitForSelector('.pv-box', { timeout: 15000 });
    await sleep(800);
    const pv = await pub.page.evaluate(() =>
      document.querySelector('.pv-box')?.textContent.replace(/\s+/g, ' ').trim() || '');
    check('① 上传前体检通过', /体检通过/.test(pv), pv.slice(0, 60));

    // 填表并提交
    await pub.page.evaluate((code) => {
      const set = (el, val) => {
        if (!el) return;
        const proto = el.tagName === 'TEXTAREA'
          ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
      };
      const inputs = [...document.querySelectorAll('.el-dialog input[type=text]')];
      const byPh = (ph) => inputs.find((i) => (i.placeholder || '').includes(ph));
      set(byPh('小写字母'), code);
      set(byPh('SSD 日志医生'), '场景验证技能');
      const ta = [...document.querySelectorAll('.el-dialog textarea')];
      set(ta.find((t) => (t.placeholder || '').includes('贴日志')), '端到端场景验证用技能');
    }, ASSET);
    await sleep(400);
    await pub.page.evaluate(() => {
      const b = [...document.querySelectorAll('.el-dialog__footer .el-button')].find((x) => x.textContent.includes('上架'));
      b && b.click();
    });
    // 等任务跑完 (推送要几秒)
    let jobText = '';
    for (let i = 0; i < 40; i++) {
      await sleep(1000);
      jobText = await pub.page.evaluate(() =>
        document.querySelector('.job-box')?.textContent.replace(/\s+/g, ' ').trim() || '');
      if (/已同步到 GitLab|等待管理员审核|同步失败/.test(jobText)) break;
    }
    check('② 上传后提示等待审核', /等待管理员审核/.test(jobText), jobText.slice(0, 70));
    await pub.page.evaluate(() => {
      const b = [...document.querySelectorAll('.el-dialog__footer .el-button')].find((x) => /完成|关闭/.test(x.textContent));
      b && b.click();
    });
    await sleep(800);

    const st = await api(`/api/v1/assets/${ASSET}`, { token: adminToken });
    check('③ 资产状态为待审核', st.json && st.json.publish_status === 'pending', st.json && st.json.publish_status);


    // ===== ③b 复验: 同步器不能把待审资产改成已上架 =====
    // 同步器每 30 秒从远端拉一次. 远端 manifest 里**缺** publish_status 时,
    // 曾经被猜成 published → 待审核的资产自动上架, 审核形同虚设.
    // 这个 bug 只在冲突判定触发时发作, 所以以前表现为"端到端偶发失败".
    await sleep(35000);
    const stAfterSync = await api(`/api/v1/assets/${ASSET}`, { token: adminToken });
    check('③b 等一个同步周期后仍是待审核',
      stAfterSync.json && stAfterSync.json.publish_status === 'pending',
      `publish_status=${stAfterSync.json && stAfterSync.json.publish_status}`);

    // ===== ② 审核台: 管理员能看到并驳回 =====
    const adm = await openAs(browser, adminToken, { id: 1, username: ADMIN, role: 'admin' });
    await adm.page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
    await adm.page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1500);
    await adm.page.evaluate(() => {
      const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
      t && t.click();
    });
    await sleep(1500);
    const admCard = await adm.page.evaluate((name) => {
      const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(name));
      return c ? {
        name: c.querySelector('.ac-name')?.textContent.trim(),
        badges: [...c.querySelectorAll('.ac-badge')].map((x) => x.textContent.trim()),
      } : null;
    }, '场景验证技能');
    check('④ 管理员在列表里看到待审资产', !!admCard, JSON.stringify(admCard));
    check('⑤ 卡片上标着「待审核」', !!(admCard && admCard.badges.includes('📋 待审核')), JSON.stringify(admCard && admCard.badges));

    await adm.page.evaluate((name) => {
      const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(name));
      c && c.click();
    }, '场景验证技能');
    await adm.page.waitForSelector('.el-drawer', { timeout: 10000 });
    await sleep(1200);
    await adm.page.evaluate(() => {
      const b = [...document.querySelectorAll('.ad-actions .el-button')].find((x) => x.textContent.includes('驳回'));
      b && b.click();
    });
    await sleep(900);
    const reasonInput = await adm.page.$('.el-message-box__input input, .el-message-box input');
    if (reasonInput) await reasonInput.type('权限声明不完整, 请补充后再提交');
    await sleep(300);
    await adm.page.evaluate(() => {
      const b = [...document.querySelectorAll('.el-message-box__btns .el-button')].find((x) => x.textContent.includes('驳回'));
      b && b.click();
    });
    await sleep(2500);
    const st2 = await api(`/api/v1/assets/${ASSET}`, { token: adminToken });
    check('⑥ 驳回后状态 rejected', st2.json && st2.json.publish_status === 'rejected', st2.json && st2.json.publish_status);
    check('⑦ 驳回理由写进资产', st2.json && st2.json.review_note === '权限声明不完整, 请补充后再提交', st2.json && st2.json.review_note);

    // ===== ③ 小王看到驳回 → 重新提交 → 管理员通过 =====
    await pub.page.reload({ waitUntil: 'domcontentloaded' });
    await pub.page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1500);
    const barText = await pub.page.evaluate(() =>
      document.querySelector('.my-review-bar')?.textContent.replace(/\s+/g, ' ').trim() || '');
    check('⑧ 小王看到「需要处理」提示条', /需要处理/.test(barText), barText.slice(0, 50));
    await pub.page.evaluate(() => {
      const b = document.querySelector('.my-review-bar .mrb-btn');
      b && b.click();
    });
    await sleep(1800);
    const pubCard = await pub.page.evaluate((name) => {
      const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(name));
      return c ? {
        badges: [...c.querySelectorAll('.ac-badge')].map((x) => x.textContent.trim()),
      } : null;
    }, '场景验证技能');
    check('⑨ 小王看到自己被驳回的资产', !!pubCard, JSON.stringify(pubCard));
    check('⑩ 卡片标着「已驳回」', !!(pubCard && pubCard.badges.includes('❌ 已驳回')), JSON.stringify(pubCard && pubCard.badges));

    // 重新提交
    await pub.page.evaluate((name) => {
      const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(name));
      c && c.click();
    }, '场景验证技能');
    await pub.page.waitForSelector('.el-drawer', { timeout: 10000 });
    await sleep(1000);
    await pub.page.evaluate(() => {
      const b = [...document.querySelectorAll('.ad-actions .el-button')].find((x) => x.textContent.includes('重新提交审核'));
      b && b.click();
    });
    await sleep(2000);
    const st3 = await api(`/api/v1/assets/${ASSET}`, { token: adminToken });
    check('⑪ 重新提交后回到 pending', st3.json && st3.json.publish_status === 'pending', st3.json && st3.json.publish_status);

    // 管理员通过
    await adm.page.reload({ waitUntil: 'domcontentloaded' });
    await adm.page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1500);
    await adm.page.evaluate(() => {
      const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
      t && t.click();
    });
    await sleep(1500);
    await adm.page.evaluate((name) => {
      const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(name));
      c && c.click();
    }, '场景验证技能');
    await adm.page.waitForSelector('.el-drawer', { timeout: 10000 });
    await sleep(1000);
    await adm.page.evaluate(() => {
      const b = [...document.querySelectorAll('.ad-actions .el-button')].find((x) => x.textContent.includes('通过审核'));
      b && b.click();
    });
    await sleep(900);
    await adm.page.evaluate(() => {
      const b = [...document.querySelectorAll('.el-message-box__btns .el-button')].find((x) => x.textContent.includes('通过'));
      b && b.click();
    });
    await sleep(3000);
    const st4 = await api(`/api/v1/assets/${ASSET}`, { token: adminToken });
    check('⑫ 审核通过后上架', st4.json && st4.json.publish_status === 'published', st4.json && st4.json.publish_status);

    // ===== ④ 小李(安装者) 装这个技能 =====
    const ins = await openAs(browser, insToken, { id: 0, username: INSTALLER.username, role: 'viewer' });
    await ins.page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
    await ins.page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1500);
    await ins.page.evaluate(() => {
      const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
      t && t.click();
    });
    await sleep(1500);
    const visibleToInstaller = await ins.page.evaluate((name) =>
      [...document.querySelectorAll('.asset-card')].some((x) => x.textContent.includes(name)), '场景验证技能');
    check('⑬ 上架后小李能看到', visibleToInstaller);

    // 通过安装向导装上
    await ins.page.evaluate((name) => {
      const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(name));
      c && c.click();
    }, '场景验证技能');
    await ins.page.waitForSelector('.el-drawer', { timeout: 10000 });
    await sleep(1200);
    // 安装 = 下载: 抽屉里一个「下载」按钮, 没有对话框了.
    const insBtns = await ins.page.evaluate(() =>
      [...document.querySelectorAll('.ad-actions button')].map((b) => (b.textContent || '').trim()));
    check('⑭ 抽屉里有「下载」按钮', insBtns.includes('下载'), insBtns.join(' | '));
    check('⑮ 没有装到本地/重新安装/卸载',
      !insBtns.some((b) => /安装到本地|重新安装|卸载/.test(b)), insBtns.join(' | '));
    // ⚠️ 这里**不点**下载 —— 无头 Chrome 里下载会落磁盘, 断言不方便;
    //    改成走 API 记录安装 (channel=download).
    const instStatus = await ins.page.evaluate(async (code) => {
      const tk = localStorage.getItem('testmate:token');
      const H = { Authorization: 'Bearer ' + tk };
      const t = await (await fetch('/api/v1/assets/' + code + '/install-target', { headers: H })).json();
      const fd = new FormData();
      fd.append('version', t.version);
      fd.append('channel', 'download');
      // client_id 必须跟前端用的**同一个**, 否则卡片不会标「已安装」
      fd.append('client_id', localStorage.getItem('testmate.client_id') || 'scn');
      fd.append('client_kind', 'web');
      fd.append('install_path', t.target);
      const r = await fetch('/api/v1/assets/' + code + '/install', { method: 'POST', headers: H, body: fd });
      return r.status;
    }, ASSET);
    check('⑯ 安装成功', instStatus === 200, `status=${instStatus}`);
    await ins.page.screenshot({ path: path.join(OUT_DIR, '21-scenario-install.png') });
    await ins.page.evaluate(() => {
      const b = [...document.querySelectorAll('.el-dialog__footer .el-button')].find((x) => /取消|关闭/.test(x.textContent));
      b && b.click();
    });
    await sleep(600);

    await ins.page.reload({ waitUntil: 'domcontentloaded' });
    await ins.page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1500);
    await ins.page.evaluate(() => {
      const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
      t && t.click();
    });
    await sleep(1500);
    const insBadges = await ins.page.evaluate((name) => {
      const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(name));
      return c ? [...c.querySelectorAll('.ac-badge')].map((x) => x.textContent.trim()) : null;
    }, '场景验证技能');
    check('⑰ 小李的卡片标着「已安装」', !!(insBadges && insBadges.includes('✓ 已安装')), JSON.stringify(insBadges));

    // ===== ⑤ 管理员下架 → 已装的人仍看得见, 但标「已下架」 =====
    await api(`/api/v1/assets/${ASSET}/unpublish`, {
      method: 'POST', token: adminToken, body: { comment: '临时下架' },
    });
    await sleep(2500);
    await ins.page.reload({ waitUntil: 'domcontentloaded' });
    await ins.page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1500);
    await ins.page.evaluate(() => {
      const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
      t && t.click();
    });
    await sleep(1500);
    const afterUnpub = await ins.page.evaluate((name) => {
      const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(name));
      return c ? [...c.querySelectorAll('.ac-badge')].map((x) => x.textContent.trim()) : null;
    }, '场景验证技能');
    check('⑱ 下架后已装的人仍能看到', !!afterUnpub, JSON.stringify(afterUnpub));
    check('⑲ 卡片标着「已下架」', !!(afterUnpub && afterUnpub.includes('⚠️ 已下架')), JSON.stringify(afterUnpub));

    // 重新上架
    await api(`/api/v1/assets/${ASSET}/publish`, {
      method: 'POST', token: adminToken, body: { comment: '恢复' },
    });
    await sleep(2500);
    const st5 = await api(`/api/v1/assets/${ASSET}`, { token: adminToken });
    check('⑳ 重新上架成功', st5.json && st5.json.publish_status === 'published', st5.json && st5.json.publish_status);

    // ===== ⑥ 审计 / 回执 / 状态统计 =====
    const audits = await api(`/api/v1/assets/audits?code=${ASSET}`, { token: adminToken });
    const actions = (audits.json.items || []).map((a) => a.action);
    check('㉑ 审计留痕完整',
      ['create', 'reject', 'submit', 'approve', 'unpublish', 'publish'].every((a) => actions.includes(a)),
      actions.join(','));

    const notif = await api('/api/v1/assets/notifications?limit=50', { token: adminToken });
    const evs = (notif.json.items || []).filter((n) => n.code === ASSET).map((n) => n.event);
    check('㉒ 通知事件齐全 (待审/驳回/上架)',
      ['review', 'reject', 'publish'].every((e) => evs.includes(e)), evs.join(','));

    const sync = await api('/api/v1/assets/sync-status?client_id=scn', { token: adminToken });
    check('㉓ 同步状态可读', sync.status === 200 && sync.json.pending_count >= 0,
      `pending=${sync.json.pending_count} failed=${sync.json.failed_count}`);

    // ===== ⑦ 彻底删除 =====
    const del = await api(`/api/v1/assets/${ASSET}?comment=场景结束清理`, {
      method: 'DELETE', token: adminToken,
    });
    check('㉔ 删除成功', del.status === 200, `status=${del.status} ${del.text.slice(0, 80)}`);
    const gone = await api(`/api/v1/assets/${ASSET}`, { token: adminToken });
    check('㉕ 删除后资产不可查', gone.status === 404, `status=${gone.status}`);
    const listAfter = await api('/api/v1/assets?limit=200&client_id=scn', { token: adminToken });
    check('㉖ 删除后不在任何列表里',
      !(listAfter.json.items || []).some((i) => i.code === ASSET));

    check('㉗ 全程无 JS 错误',
      pub.errors.length === 0 && adm.errors.length === 0 && ins.errors.length === 0,
      [...pub.errors, ...adm.errors, ...ins.errors].slice(0, 2).join(' ; '));
  } finally {
    if (browser) await browser.close();
    // 还原设置 —— 场景脚本改的是生产设置, 必须还原
    // (曾经只删账号不还原设置, 结果白名单里长期挂着一个已删除的测试账号)
    for (const k of TOUCHED) {
      if (savedSettings[k] === undefined) continue;
      try {
        await setSetting(adminToken, k, String(savedSettings[k]));
      } catch (e) {
        console.log(`  [清理] 设置 ${k} 还原失败: ` + String(e.message).split('\n')[0]);
      }
    }
    // 清理测试账号 —— 别在库里留两个已知口令的账号
    try {
      const env = fs.readFileSync(path.join(__dirname, '..', 'deploy', '.env'), 'utf8');
      const pw = (env.match(/^MYSQL_ROOT_PASSWORD=(.*)$/m) || [])[1]?.trim().replace(/^["']|["']$/g, '');
      if (pw) {
        execFileSync('docker', ['exec', 'test-mate-mysql-1', 'mysql', '-uroot', `-p${pw}`,
          'testmate', '-e',
          `DELETE FROM users WHERE username IN ('${PUBLISHER.username}','${INSTALLER.username}');`],
        { stdio: 'ignore' });
        console.log('  [清理] 测试账号已删除');
      }
    } catch (e) {
      console.log('  [清理] 账号清理跳过: ' + String(e.message).split('\n')[0]);
    }
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
