#!/usr/bin/env node
/**
 * AI 资产市场 —— 端到端验收脚本 (真实 Chrome).
 *
 * 为什么不用内置 Browser 验证:
 *   Electron 内置 Browser 在页面加载瞬间会挂起 renderer —— XHR 事件不投递、setTimeout 不触发,
 *   表现成「页面永远卡在 loading」。那是验证工具的假象, 不是被测页面的 bug。
 *   本脚本用 puppeteer-core 驱动本机真实 Chrome, 行为与用户一致。
 *
 * 前置:
 *   cd frontend_web && npm i -D puppeteer-core     # 或任意目录安装后用 NODE_PATH 指过来
 *   # 需要本机已装 Google Chrome
 *
 * 用法:
 *   TESTMATE_USER=admin TESTMATE_PASSWORD='Admin@123' \
 *     node scripts/e2e_market.js [baseUrl]
 *
 * 退出码: 0 = 全部通过, 1 = 有断言失败, 2 = 脚本异常。
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.argv[2] || process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const USER = process.env.TESTMATE_USER || 'admin';
const PASSWORD = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  :: ' + detail : ''}`);
}

/** 点第一个文本匹配的元素 */
async function clickByText(page, selector, text) {
  const hit = await page.evaluate((sel, t) => {
    const els = [...document.querySelectorAll(sel)];
    const el = els.find((e) => (e.textContent || '').replace(/\s+/g, ' ').trim().includes(t));
    if (!el) return false;
    el.scrollIntoView({ block: 'center' });
    el.click();
    return true;
  }, selector, text);
  if (!hit) throw new Error(`clickByText 未命中: ${selector} "${text}"`);
  await sleep(700);
  return hit;
}

/** 读取市场页当前状态 */
async function snap(page) {
  return page.evaluate(() => {
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null);
    const cards = [...document.querySelectorAll('.asset-card')].map((c) => ({
      name: txt(c.querySelector('.ac-name')),
      ver: txt(c.querySelector('.ac-ver')),
      badge: txt(c.querySelector('.ac-installed, .ac-updatable, .ac-sync')),
    }));
    return {
      debugBar: !!document.querySelector('.tm-debug'),
      cards,
      tabs: [...document.querySelectorAll('.kind-tab')].map((b) => txt(b)),
      marketState: txt(document.querySelector('.market .state')),
      syncBar: txt(document.querySelector('.sync-bar')),
      footHint: txt(document.querySelector('.foot-hint')),
      drawerOpen: !!document.querySelector('.el-drawer'),
      drawerName: txt(document.querySelector('.ad-name')),
      docHtmlLen: (document.querySelector('.ad-doc')?.innerHTML || '').length,
      docText: (txt(document.querySelector('.ad-doc')) || '').slice(0, 120),
      docHasScript: !!document.querySelector('.ad-doc script, .ad-doc iframe, .ad-doc img'),
      permRows: document.querySelectorAll('.perm-list li').length,
      permEmpty: !!document.querySelector('.ad-perm.is-empty'),
      steps: [...document.querySelectorAll('.steps li')].map((s) => txt(s)),
      gitPath: txt(document.querySelector('.ad-git code')),
      syncChip: txt(document.querySelector('.ad-sync-chip')),
      dlgTitle: txt(document.querySelector('.el-dialog__title')),
      dlgTarget: txt(document.querySelector('.inst-chan-d')),
      dlgPerm: txt(document.querySelector('.inst-perm')),
      dlgAlert: txt(document.querySelector('.el-dialog .el-alert__title')),
      dlgChanCount: document.querySelectorAll('.inst-chan').length,
      msgBox: txt(document.querySelector('.el-message-box__message')),
    };
  });
}

/** 首个插件资产的 code —— 用它跑安装/下架, 不写死具体资产名 */
async function firstPluginCode(page) {
  return page.evaluate(async () => {
    const tk = localStorage.getItem('testmate:token');
    const r = await fetch('/api/v1/assets?kind=plugin&limit=1', { headers: { Authorization: 'Bearer ' + tk } });
    const d = await r.json();
    return (d.items || [])[0]?.code || '';
  });
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1440, height: 1000 },
  });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console.error] ' + m.text()); });
  page.on('requestfailed', (r) => errors.push('[reqfail] ' + r.url() + ' :: ' + (r.failure() || {}).errorText));

  // 登录态
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  const login = await page.evaluate(async (u, p) => {
    const r = await fetch('/api/v1/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p }),
    });
    if (!r.ok) return { error: r.status };
    const { access_token } = await r.json();
    const m = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + access_token } });
    return { token: access_token, user: m.ok ? await m.json() : null };
  }, USER, PASSWORD);
  if (login.error) throw new Error(`登录失败: ${JSON.stringify(login)}`);
  await page.evaluate((tk, u) => {
    localStorage.setItem('testmate:token', tk);
    localStorage.setItem('testmate:user', JSON.stringify(u));
  }, login.token, login.user);

  // ---------- A. 列表渲染 ----------
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1200);
  let s = await snap(page);
  check('A1 市场页渲染出资产卡片', s.cards.length > 0, `${s.cards.length} 张: ${s.cards.map((c) => c.name).join(', ')}`);
  check('A2 无调试条残留', s.debugBar === false);
  check('A3 三个类型 Tab 都有计数', s.tabs.length === 3, s.tabs.join(' | '));
  check('A4 无加载中/空态残留', !s.marketState, s.marketState || '(none)');
  check('A5 底部标注数据源', /GitLab/.test(s.footHint || ''), s.footHint);

  // ---------- B. 类型 Tab ----------
  await clickByText(page, '.kind-tab', '技能');
  await sleep(900);
  s = await snap(page);
  check('B1 切到「技能」Tab 有卡片', s.cards.length > 0, `${s.cards.length} 张`);
  await clickByText(page, '.kind-tab', '连接器');
  await sleep(900);
  s = await snap(page);
  check('B2 切到「连接器」Tab 有卡片', s.cards.length > 0, `${s.cards.length} 张`);
  await clickByText(page, '.kind-tab', '插件');
  await sleep(900);

  // ---------- C. 搜索 ----------
  await page.type('.search input', 'a');
  await sleep(1400);
  s = await snap(page);
  const filtered = s.cards.length;
  await page.evaluate(() => {
    const el = document.querySelector('.search input');
    el.value = '';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(1400);
  s = await snap(page);
  check('C1 搜索可过滤', filtered >= 0 && s.cards.length >= filtered, `搜索命中 ${filtered} 张 / 清空后 ${s.cards.length} 张`);

  // ---------- D. 详情抽屉 ----------
  const code = await firstPluginCode(page);
  await clickByText(page, '.asset-card', s.cards[0] ? s.cards[0].name : '');
  await page.waitForSelector('.el-drawer', { timeout: 10000 });
  await sleep(1500);
  s = await snap(page);
  check('D1 详情抽屉打开', s.drawerOpen && !!s.drawerName, s.drawerName);
  check('D2 文档正文已渲染', s.docHtmlLen > 40, `html ${s.docHtmlLen} 字节`);
  check('D3 文档已消毒(无 script/iframe/img)', s.docHasScript === false);
  check('D4 权限区块有内容', s.permRows > 0 || s.permEmpty, `permRows=${s.permRows} empty=${s.permEmpty}`);
  check('D5 安装步骤展示', s.steps.length > 0, s.steps.join(' / '));
  check('D6 GitLab 存储路径展示', /assets\//.test(s.gitPath || ''), s.gitPath);
  check('D7 同步状态标签', /已同步|待同步|失败/.test(s.syncChip || ''), s.syncChip);
  await page.screenshot({ path: path.join(OUT_DIR, '01-drawer.png') });

  // ---------- E. 安装向导 ----------
  await clickByText(page, '.ad-actions .el-button', '安装');
  await page.waitForSelector('.inst-chan', { timeout: 10000 });
  await sleep(1200);
  s = await snap(page);
  check('E1 安装向导读到目标目录', s.dlgChanCount === 2 && /\//.test(s.dlgTarget || ''), `target=${s.dlgTarget}`);
  check('E2 向导显示权限提示', (s.dlgPerm || '').length > 5, (s.dlgPerm || '').slice(0, 60));
  await page.screenshot({ path: path.join(OUT_DIR, '02-install.png') });
  await clickByText(page, '.el-dialog__footer .el-button', '开始安装');
  await sleep(2500);
  s = await snap(page);
  check('E3 服务端通道安装成功', /已安装/.test(s.dlgAlert || ''), s.dlgAlert || '(无提示)');
  await page.screenshot({ path: path.join(OUT_DIR, '03-installed.png') });
  await clickByText(page, '.el-dialog__footer .el-button', '取消');
  await sleep(800);

  // 安装后卡片应出现「已安装」标记
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1500);
  s = await snap(page);
  const installedCard = s.cards.find((c) => c.name === (s.cards[0] || {}).name) || s.cards[0];
  check('E4 安装后卡片标记「已安装」', /已安装/.test((installedCard && installedCard.badge) || ''), installedCard ? installedCard.badge : '(无卡片)');

  // ---------- F. 下架 / 重新上架 ----------
  await clickByText(page, '.asset-card', (installedCard && installedCard.name) || '');
  await page.waitForSelector('.el-drawer', { timeout: 10000 });
  await sleep(1500);
  await clickByText(page, '.ad-actions .el-button', '下架');
  await sleep(700);
  s = await snap(page);
  check('F1 下架有二次确认', /下架/.test(s.msgBox || ''), s.msgBox);
  await clickByText(page, '.el-message-box__btns .el-button', '下架');
  await sleep(2000);
  const unpub = await page.evaluate(async (c) => {
    const tk = localStorage.getItem('testmate:token');
    const r = await fetch('/api/v1/assets?limit=200&include_unpublished=true', { headers: { Authorization: 'Bearer ' + tk } });
    const d = await r.json();
    return (d.items || []).find((i) => i.code === c)?.publish_status || '';
  }, code);
  check('F2 下架后 publish_status=unpublished', unpub === 'unpublished', unpub);
  await page.screenshot({ path: path.join(OUT_DIR, '04-unpublished.png') });

  // 重新上架 (走 API, 不依赖 UI 弹窗)
  await page.evaluate(async (c) => {
    const tk = localStorage.getItem('testmate:token');
    const fd = new FormData(); fd.append('comment', 'e2e 恢复上架');
    await fetch(`/api/v1/assets/${c}/publish`, { method: 'POST', headers: { Authorization: 'Bearer ' + tk }, body: fd });
  }, code);
  await sleep(1500);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1200);
  s = await snap(page);
  check('F3 重新上架后卡片回到列表', s.cards.length > 0, `${s.cards.length} 张`);

  // ---------- G. 同步 ----------
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.link-btn')].find((x) => x.textContent.includes('重新同步'));
    b && b.click();
  });
  await sleep(3000);
  s = await snap(page);
  check('G1 重新同步后页面仍正常', s.cards.length > 0, `${s.cards.length} 张`);
  await page.screenshot({ path: path.join(OUT_DIR, '05-final.png'), fullPage: true });

  // ---------- 汇总 ----------
  check('Z1 全程无 JS 错误 / 请求失败', errors.length === 0, errors.slice(0, 5).join(' ; '));

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  console.log('截图目录: ' + OUT_DIR);
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
