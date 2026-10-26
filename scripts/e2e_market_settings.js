#!/usr/bin/env node
/**
 * 资产市场设置 —— 前端端到端验收.
 *
 * 覆盖: 设置页「能力墙 → 🧩 资产市场」子分组 / GitLab 仓库连接测试 /
 *       工作区与远端只读展示 / 市场页「在 GitLab 查看」链接.
 *
 * 用法: node scripts/e2e_market_settings.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
// ⚠️ 互斥锁: 并行跑 e2e 会互相改生产设置/删资产 (见 e2e_lock.js)
require('./e2e_lock').acquire(__filename);


const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const USER = process.env.TESTMATE_USER || 'admin';
const PASSWORD = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR
  || path.join(__dirname, '..', '.e2e-out');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
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
  // ⚠️ 关掉缓存 —— 否则会加载上一次的旧 JS, 调已下线的端点
  await page.setCacheEnabled(false);
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console.error] ' + m.text()); });

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

  // ---------- A. 设置页「能力墙 → 资产市场」 ----------
  await page.goto(BASE + '/settings', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.set-layout', { timeout: 15000 });
  await sleep(1500);
  const picked = await page.evaluate(() => {
    const el = [...document.querySelectorAll('.set-toc *')]
      .find((x) => x.textContent.trim().startsWith('能力墙'));
    if (!el) return false;
    el.click();
    return true;
  });
  await sleep(1800);
  check('A1 设置页能进入「能力墙」区', picked);

  const keys = await page.evaluate(() =>
    [...document.querySelectorAll('#sec-capability code')].map((c) => c.textContent.trim()));
  const expect = [
    'marketplace.git.remote', 'marketplace.git.branch', 'marketplace.git.web_url',
    'marketplace.publisher_ids',
    'marketplace.sync.interval_seconds', 'marketplace.max_package_mb',
    'marketplace.marketplace_name', 'marketplace.public_base_url',
    'marketplace.projects',   // 项目列表 (资产的适用项目)
    // 2026-10-26: 新增的权限/暴露策略项 (admin only —— 非管理员的 schema 里没有)
    'marketplace.publisher_roles', 'marketplace.public_download',
  ];
  const missing = expect.filter((k) => !keys.includes(k));
  check('A2 资产市场配置项全部渲染出来', missing.length === 0,
    missing.length ? '缺: ' + missing.join(',') : `${expect.length} 项齐全`);

  // ⚠️ 服务端写盘通道下线 → 安装目录不再可配, 这三项必须**消失**
  const removed = [
    'marketplace.install.skill_dir', 'marketplace.install.plugin_dir',
    'marketplace.install.enabled',
  ];
  const stillThere = removed.filter((k) => keys.includes(k));
  check('A2b 安装目录配置项已移除',
    stillThere.length === 0,
    stillThere.length ? '还在: ' + stillThere.join(',') : '三项均已移除');

  const ws = await page.evaluate(() => {
    const el = document.querySelector('#sec-capability .workdir');
    return el ? el.textContent.replace(/\s+/g, ' ').trim() : '';
  });
  check('A3 展示当前生效的工作区与远端', /工作区/.test(ws) && /远端/.test(ws), ws.slice(0, 110));
  await page.screenshot({ path: path.join(OUT_DIR, '09-market-settings.png'), fullPage: false });

  // ---------- B. 测试仓库连接 ----------
  const clicked = await page.evaluate(() => {
    const b = [...document.querySelectorAll('#sec-capability button')]
      .find((x) => x.textContent.includes('测试仓库连接'));
    if (!b) return false;
    b.click();
    return true;
  });
  await sleep(6000);
  const probe = await page.evaluate(() => {
    const el = document.querySelector('#sec-capability .test-result');
    return el ? { cls: el.className, msg: el.textContent.replace(/\s+/g, ' ').trim() } : null;
  });
  check('B1 「测试仓库连接」有结果', clicked && !!probe, probe ? probe.msg : '(无结果)');
  check('B2 仓库连接测试通过', !!probe && /s-ok/.test(probe.cls), probe ? probe.msg : '(无结果)');

  // ---------- C. 市场页「在 GitLab 查看」 ----------
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1200);
  await page.evaluate(() => {
    const c = document.querySelector('.asset-card');
    c && c.click();
  });
  await page.waitForSelector('.el-drawer', { timeout: 10000 });
  await sleep(1500);
  const link = await page.evaluate(() => {
    const a = document.querySelector('.ad-git-link');
    return a ? { href: a.getAttribute('href'), text: a.textContent.trim() } : null;
  });
  check('C1 详情抽屉有「在 GitLab 查看」链接', !!link, link ? `${link.text} → ${link.href}` : '(无)');
  check('C2 链接指向配置的 GitLab 地址',
    !!link && /^https?:\/\/.+\/root\/testmate-market\/-\/tree\/.+/.test(link.href || ''),
    link ? link.href : '(无)');
  await page.screenshot({ path: path.join(OUT_DIR, '10-gitlab-link.png'), fullPage: false });

  check('D1 全程无 JS 错误', errors.length === 0, errors.slice(0, 3).join(' ; '));

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
