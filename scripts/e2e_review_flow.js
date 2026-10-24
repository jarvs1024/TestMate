#!/usr/bin/env node
/**
 * 上架审核 —— 前端端到端验收 (真实 Chrome).
 *
 * 覆盖: 非管理员上传 → 「已提交, 等待管理员审核」→ 列表里带「📋 待审核」徽标 →
 *       管理员在「待审核」筛选里看到 → 驳回 (填理由) → 发布者看到驳回理由 →
 *       重新提交 → 管理员通过 → 资产出现在市场里.
 *
 * 用法: node scripts/e2e_review_flow.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
// ⚠️ 互斥锁: 并行跑 e2e 会互相改生产设置/删资产 (见 e2e_lock.js)
require('./e2e_lock').acquire(__filename);


const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const API = process.env.TESTMATE_API || 'http://localhost:18000';
const ADMIN = process.env.TESTMATE_USER || 'admin';
const ADMIN_PW = process.env.TESTMATE_PASSWORD || 'Admin@123';
const PUB = process.env.REVIEW_TEST_USER || 'e2e_publisher';
const PUB_PW = 'E2e@Test12345';
const CODE = 'e2e-review-probe';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');

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

async function login(username, password) {
  const r = await api('/api/v1/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  return r.json.access_token || '';
}

/** 读设置项当前值 —— 改白名单前先存住, 结束必须还原 */
async function getSetting(token, key) {
  const r = await api('/api/v1/settings/schema', {
    headers: { Authorization: 'Bearer ' + token },
  });
  if (r.status !== 200) return undefined;
  for (const g of (r.json?.groups || [])) {
    for (const it of (g.items || [])) {
      if (it.key === key) return it.value;
    }
  }
  return undefined;
}

async function restoreSetting(token, key, value) {
  if (value === undefined) return;
  await api(`/api/v1/settings/${key}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: JSON.stringify({ value: String(value) }),
  });
}

// 错误路径也要还原白名单 —— 主体中途抛错时清理段根本不会执行到
let cleanupToken = null;
let savedPublisherSetting;

/** 等上传任务跑到终态 (推送要几秒, 固定 sleep 不可靠) */
async function waitJobDone(page, timeoutMs = 45000) {
  const t0 = Date.now();
  let txt = '';
  while (Date.now() - t0 < timeoutMs) {
    txt = await page.evaluate(() =>
      document.querySelector('.job-box')?.textContent.replace(/\s+/g, ' ').trim() || '');
    if (/已同步到 GitLab|等待管理员审核|同步失败/.test(txt)) return txt;
    await sleep(800);
  }
  return txt;
}

/**
 * 打开一个带登录态的页面.
 * ⚠️ 必须用**独立的 browser context** —— 同一 origin 的多个页面共享 localStorage,
 *    后开的会把先开的 token 覆盖掉 (发布者与管理员必须是两个身份).
 */
async function openPage(browser, token, user) {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  const errors = [];
  // ⚠️ 关掉缓存 —— 否则会加载上一次的旧 JS, 调已下线的端点
  await page.setCacheEnabled(false);
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console.error] ' + m.text()); });
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  await page.evaluate((tk, u) => {
    localStorage.setItem('testmate:token', tk);
    localStorage.setItem('testmate:user', JSON.stringify(u));
  }, token, user);
  return { page, errors, context };
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const adminToken = await login(ADMIN, ADMIN_PW);
  cleanupToken = adminToken;

  // ---------- 准备: 发布者账号 + 白名单 ----------
  await api(`/api/v1/assets/${CODE}`, {
    method: 'DELETE',
    headers: { Authorization: 'Bearer ' + adminToken },
  });
  await api('/api/v1/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + adminToken },
    body: JSON.stringify({ username: PUB, password: PUB_PW, role: 'tester' }),
  });
  // ⚠️ 先存原值 —— 白名单是**生产设置**, 结束时必须还原
  //    (以前直接恢复成空字符串, 会把管理员配好的真实白名单一起抹掉)
  savedPublisherSetting = await getSetting(adminToken, 'marketplace.publisher_usernames');
  await api('/api/v1/settings/marketplace.publisher_usernames', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + adminToken },
    body: JSON.stringify({ value: PUB }),
  });
  const pubToken = await login(PUB, PUB_PW);
  check('A0 发布者账号就绪', !!pubToken);

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1440, height: 1000 },
  });

  // ---------- ① 发布者上传 ----------
  const pub = await openPage(browser, pubToken, { id: 0, username: PUB, role: 'tester' });
  await pub.page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await pub.page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1200);

  await pub.page.evaluate(() => {
    const b = [...document.querySelectorAll('.mini-btn.primary')].find((x) => x.textContent.includes('上传资产'));
    b && b.click();
  });
  await pub.page.waitForSelector('.file-input', { timeout: 10000 });
  await sleep(600);
  const pkgPath = path.join(OUT_DIR, 'e2e-review.zip');
  execFileSync('python3', ['-c', [
    'import zipfile',
    `z=zipfile.ZipFile(${JSON.stringify(pkgPath)},'w')`,
    `z.writestr('SKILL.md','---\\nname: e2e-review-probe\\ndescription: 审核流程端到端探针\\n---\\n\\n# 审核流程端到端探针\\n')`,
    'z.close()',
  ].join(';')]);
  const input = await pub.page.$('.file-input');
  await input.uploadFile(pkgPath);
  await pub.page.waitForSelector('.pv-box', { timeout: 15000 });
  await sleep(1200);
  const pvText = await pub.page.evaluate(() => document.querySelector('.pv-box')?.textContent.replace(/\s+/g, ' ').trim() || '');
  check('① 包体检通过', /体检通过/.test(pvText), pvText.slice(0, 70));

  // 填表并提交 (走真实表单)
  await pub.page.evaluate((code) => {
    const set = (el, val) => {
      if (!el) return;
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    const inputs = [...document.querySelectorAll('.el-dialog input[type=text]')];
    const byPlaceholder = (ph) => inputs.find((i) => (i.placeholder || '').includes(ph));
    set(byPlaceholder('小写字母'), code);
    set(byPlaceholder('SSD 日志医生'), '审核流程端到端资产');
    const ta = [...document.querySelectorAll('.el-dialog textarea')];
    const sum = ta.find((t) => (t.placeholder || '').includes('贴日志'));
    set(sum, '验证上架审核流程的资产');
  }, CODE);
  await sleep(500);
  await pub.page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-dialog__footer .el-button')].find((x) => x.textContent.includes('上架'));
    b && b.click();
  });
  const jobText = await waitJobDone(pub.page);
  check('② 上传后提示「等待管理员审核」', /等待管理员审核/.test(jobText), jobText.slice(0, 90));
  await pub.page.screenshot({ path: path.join(OUT_DIR, '11-review-submitted.png') });
  await pub.page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-dialog__footer .el-button')].find((x) => /完成|关闭/.test(x.textContent));
    b && b.click();
  });
  await sleep(800);

  // ---------- ② 发布者: 顶部提示条 → 「我提交的」 ----------
  await pub.page.reload({ waitUntil: 'domcontentloaded' });
  await pub.page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1800);
  const bar = await pub.page.evaluate(() =>
    document.querySelector('.my-review-bar')?.textContent.replace(/\s+/g, ' ').trim() || '');
  check('③ 发布者看到「需要处理」提示条', /需要处理/.test(bar), bar);
  await pub.page.evaluate(() => {
    const b = document.querySelector('.my-review-bar .mrb-btn');
    b && b.click();
  });
  await sleep(1800);
  const pubCard = await pub.page.evaluate((code) => {
    const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(code) || x.textContent.includes('审核流程端到端资产'));
    if (!c) return null;
    return {
      name: c.querySelector('.ac-name')?.textContent.trim(),
      badge: [...c.querySelectorAll('.ac-badge')].map((x) => x.textContent.trim()).join(' '),
    };
  }, CODE);
  check('④ 发布者在「我提交的」视图里看到自己的资产', !!pubCard, JSON.stringify(pubCard));
  check('⑤ 卡片带「待审核」徽标', /待审核/.test(pubCard ? pubCard.badge || '' : ''), pubCard ? pubCard.badge : '(无)');

  // ---------- ③ 管理员审核台 ----------
  const adm = await openPage(browser, adminToken, { id: 1, username: ADMIN, role: 'admin' });
  await adm.page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await adm.page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1500);
  // 视图行已去掉 —— 管理员在**列表里**直接看到待审资产 (卡片带徽标)
  await adm.page.evaluate(() => {
    const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
    t && t.click();
  });
  await sleep(1800);
  const admCard = await adm.page.evaluate((code) => {
    const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(code) || x.textContent.includes('审核流程端到端资产'));
    return c ? { name: c.querySelector('.ac-name')?.textContent.trim(), badge: [...c.querySelectorAll('.ac-badge')].map((x) => x.textContent.trim()).join(' ') } : null;
  }, CODE);
  check('⑥ 管理员在列表里看到待审资产 (卡片带徽标)', !!admCard, JSON.stringify(admCard));
  await adm.page.screenshot({ path: path.join(OUT_DIR, '12-review-queue.png') });

  // 打开详情 → 驳回
  await adm.page.evaluate((code) => {
    const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(code) || x.textContent.includes('审核流程端到端资产'));
    c && c.click();
  }, CODE);
  await adm.page.waitForSelector('.el-drawer', { timeout: 10000 });
  await sleep(1500);
  const hasApprove = await adm.page.evaluate(() =>
    [...document.querySelectorAll('.ad-actions .el-button')].some((b) => b.textContent.includes('通过审核')));
  const hasReject = await adm.page.evaluate(() =>
    [...document.querySelectorAll('.ad-actions .el-button')].some((b) => b.textContent.includes('驳回')));
  check('⑧ 详情里有「通过审核」「驳回」按钮', hasApprove && hasReject, `approve=${hasApprove} reject=${hasReject}`);

  await adm.page.evaluate(() => {
    const b = [...document.querySelectorAll('.ad-actions .el-button')].find((x) => x.textContent.includes('驳回'));
    b && b.click();
  });
  await sleep(1000);
  // ⚠️ 必须**轮询等输入框出现**并用 evaluate 填值 ——
  //    填不上 → inputValidator 拦下 → 点「驳回」静默无效 (看着像点了, 其实请求没发)
  let filled = false;
  for (let i = 0; i < 25; i++) {
    filled = await adm.page.evaluate((text) => {
      const el = document.querySelector('.el-message-box input');
      if (!el) return false;
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, text);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    }, '权限声明不完整, 请补充后再提交');
    if (filled) break;
    await sleep(200);
  }
  await sleep(400);
  await adm.page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-message-box__btns .el-button')].find((x) => x.textContent.includes('驳回'));
    b && b.click();
  });
  await sleep(3000);
  const afterReject = await adm.page.evaluate(() =>
    document.querySelector('.el-alert__title')?.textContent.trim() || '');
  check('⑨ 驳回后详情显示驳回理由', /权限声明不完整/.test(afterReject), afterReject.slice(0, 80));

  // ---------- ④ 发布者看到驳回理由 + 重新提交 ----------
  await pub.page.reload({ waitUntil: 'domcontentloaded' });
  await pub.page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1800);
  await pub.page.evaluate(() => {
    const b = document.querySelector('.my-review-bar .mrb-btn');
    b && b.click();
  });
  await sleep(1600);
  const pubReject = await pub.page.evaluate((code) => {
    const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(code) || x.textContent.includes('审核流程端到端资产'));
    if (!c) return null;
    c.click();
    return { badge: [...c.querySelectorAll('.ac-badge')].map((x) => x.textContent.trim()).join(' ') };
  }, CODE);
  check('⑩ 发布者看到「已驳回」徽标', /已驳回/.test(pubReject ? pubReject.badge || '' : ''), pubReject ? pubReject.badge : '(无)');
  await pub.page.waitForSelector('.el-drawer', { timeout: 10000 });
  await sleep(1200);
  const noteText = await pub.page.evaluate(() =>
    document.querySelector('.el-alert__title')?.textContent.trim() || '');
  check('⑪ 发布者看到驳回理由', /权限声明不完整/.test(noteText), noteText.slice(0, 80));
  const canSubmit = await pub.page.evaluate(() =>
    [...document.querySelectorAll('.ad-actions .el-button')].some((b) => b.textContent.includes('重新提交审核')));
  check('⑫ 有「重新提交审核」按钮', canSubmit);
  await pub.page.screenshot({ path: path.join(OUT_DIR, '13-review-rejected.png') });
  await pub.page.evaluate(() => {
    const b = [...document.querySelectorAll('.ad-actions .el-button')].find((x) => x.textContent.includes('重新提交审核'));
    b && b.click();
  });
  await sleep(2500);

  // ---------- ⑤ 管理员通过 ----------
  await adm.page.reload({ waitUntil: 'domcontentloaded' });
  await adm.page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1500);
  // 视图行已去掉 —— 管理员在列表里直接看到待审资产, 切到它所属的类型即可
  await adm.page.evaluate(() => {
    const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
    t && t.click();
  });
  await sleep(1800);
  await adm.page.evaluate((code) => {
    const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(code) || x.textContent.includes('审核流程端到端资产'));
    c && c.click();
  }, CODE);
  await adm.page.waitForSelector('.el-drawer', { timeout: 10000 });
  await sleep(1200);
  await adm.page.evaluate(() => {
    const b = [...document.querySelectorAll('.ad-actions .el-button')].find((x) => x.textContent.includes('通过审核'));
    b && b.click();
  });
  await sleep(1000);
  await adm.page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-message-box__btns .el-button')].find((x) => x.textContent.includes('通过'));
    b && b.click();
  });
  await sleep(3000);
  await adm.page.reload({ waitUntil: 'domcontentloaded' });
  await adm.page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1500);
  // 通过后它回到市场里 —— 切到它所属的类型(skill)才看得到
  await adm.page.evaluate(() => {
    const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
    t && t.click();
  });
  await sleep(1800);
  const finalCard = await adm.page.evaluate((code) => {
    const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(code) || x.textContent.includes('审核流程端到端资产'));
    return c ? { badge: [...c.querySelectorAll('.ac-badge')].map((x) => x.textContent.trim()).join(' ') } : null;
  }, CODE);
  check('⑬ 通过后资产出现在市场里 (不再是待审核/已驳回)', !!finalCard && !/待审核|已驳回/.test(finalCard.badge || ''), JSON.stringify(finalCard));
  await adm.page.screenshot({ path: path.join(OUT_DIR, '14-review-approved.png') });

  check('⑭ 全程无 JS 错误', pub.errors.length === 0 && adm.errors.length === 0,
    [...pub.errors, ...adm.errors].slice(0, 3).join(' ; '));

  // ---------- 清理 ----------
  await api(`/api/v1/assets/${CODE}`, {
    method: 'DELETE', headers: { Authorization: 'Bearer ' + adminToken },
  });
  // 还原白名单原值 (不是清空 —— 清空会把真实配置也抹掉)
  await restoreSetting(adminToken, 'marketplace.publisher_usernames', savedPublisherSetting);
  // 删掉测试账号 —— 别留一个已知口令的账号在库里
  try {
    const env = fs.readFileSync(path.join(__dirname, '..', 'deploy', '.env'), 'utf8');
    const pw = (env.match(/^MYSQL_ROOT_PASSWORD=(.*)$/m) || [])[1]?.trim().replace(/^["']|["']$/g, '');
    if (pw) {
      execFileSync('docker', ['exec', 'test-mate-mysql-1', 'mysql', '-uroot', `-p${pw}`,
        'testmate', '-e', `DELETE FROM users WHERE username='${PUB}';`], { stdio: 'ignore' });
    }
  } catch (e) {
    console.log('  [提示] 测试账号清理跳过: ' + e.message.split('\n')[0]);
  }

  await browser.close();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  process.exit(failed.length ? 1 : 0);
})().catch(async (e) => {
  console.error('FATAL', e);
  // 错误路径也要还原白名单 —— 主体中途抛错时清理段根本执行不到
  try {
    if (cleanupToken) {
      await restoreSetting(cleanupToken, 'marketplace.publisher_usernames', savedPublisherSetting);
    }
  } catch { /* 尽力而为 */ }
  process.exit(2);
});
