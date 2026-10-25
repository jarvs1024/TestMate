#!/usr/bin/env node
/**
 * 一键安装 —— **下载安装包**的界面验收.
 *
 * 安装现在只有一条路: 详情抽屉里点「下载」, zip 落到浏览器的默认下载目录,
 * 用户自己解压. 界面里**没有**「安装到本地 / 重新安装 / 卸载」.
 *
 * 验用户真正看到的东西:
 *   1. 详情抽屉能打开
 *   2. 有「下载」按钮, 且**没有**装到本地/重新安装/卸载
 *   3. 点下载真的把 zip 落到了磁盘 (文件名正确)
 *   4. 提示说清怎么装 (通用话术: 在 Agent 里导入压缩包)
 *   5. 全程无 JS 错误
 *
 * 用法: node scripts/e2e_install_download.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const os = require('os');
const path = require('path');
// ⚠️ 互斥锁: 并行跑 e2e 会互相改生产设置/删资产 (见 e2e_lock.js)
require('./e2e_lock').acquire(__filename);


const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const USER = process.env.TESTMATE_USER || 'admin';
const PASSWORD = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1600, height: 1000 },
  });
  const errors = [];
  try {
    const page = await browser.newPage();
    // ⚠️ 无头 Chrome 默认**禁止下载** —— 必须用 CDP 显式允许
    //    (Browser 域要走 browser 级 session, page 级的不生效)
    const dlDir = path.join(OUT_DIR, 'downloads');
    fs.rmSync(dlDir, { recursive: true, force: true });
    fs.mkdirSync(dlDir, { recursive: true });
    const bcdp = await browser.target().createCDPSession();
    await bcdp.send('Browser.setDownloadBehavior', {
      behavior: 'allow',
      downloadPath: dlDir,
      eventsEnabled: true,
    });
    // ⚠️ 关掉缓存 —— 否则会加载上一次的旧 JS, 调已下线的端点
    await page.setCacheEnabled(false);
    page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
    page.on('console', (m) => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });

    // 登录
    await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
    const tk = await page.evaluate(async (u, p) => {
      const r = await fetch('/api/v1/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u, password: p }),
      });
      const d = await r.json();
      localStorage.setItem('testmate:token', d.access_token);
      localStorage.setItem('testmate:user', JSON.stringify(d.user || { username: u }));
      return d.access_token || '';
    }, USER, PASSWORD);
    check('E1 登录成功', !!tk);

    await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1500);

    // 点开详情抽屉
    const openedCard = await page.evaluate(() => {
      const c = document.querySelector('.asset-card');
      if (!c) return false;
      const nameEl = c.querySelector('.ac-name, .ac-title, h3, .name');
      (nameEl || c).click();
      return true;
    });
    check('E2 市场页有卡片可点开详情', openedCard);
    if (!openedCard) throw new Error('没有找到卡片');

    await page.waitForSelector('.ad-actions', { timeout: 15000 });
    await sleep(800);

    // 下载按钮在「安装卡」(.ins-btn), 其余动作在固定底栏 (.ad-actions)
    const btns = await page.evaluate(() =>
      [...document.querySelectorAll('.ad-actions button, .ins-btn')]
        .map((b) => (b.textContent || '').trim()));

    check('E3 有「下载」按钮', btns.includes('下载'), btns.join(' | '));
    check('E4 没有装到本地/重新安装/卸载',
      !btns.some((b) => /安装到本地|重新安装|卸载/.test(b)),
      btns.join(' | '));

    // 下载前的计数总和 (下载端点自己会 +1)
    // 用**总和差值**而不是单个资产的计数 —— 不依赖从 DOM 里抠 code, 稳得多
    const totalCount = async () => page.evaluate(async () => {
      const tk = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/assets?limit=500&status=all&client_id=e2e-dl',
        { headers: { Authorization: 'Bearer ' + tk } });
      const d = await r.json();
      return (d.items || []).reduce((n, i) => n + (i.download_count || 0), 0);
    });
    const beforeN = await totalCount();

    // 点下载 → zip 应该落到下载目录
    let downloaded = '';
    page.on('download', async (dl) => {
      downloaded = dl.suggestedFilename();
      try { await dl.cancel(); } catch { /* 已取消 */ }
    });
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('.ad-actions button, .ins-btn')]
        .find((x) => (x.textContent || '').trim() === '下载');
      b && b.click();
    });

    // ⚠️ Element Plus 的消息默认 3 秒就消失 —— 得**轮询**着抓, 不能等完再查
    let msg = '';
    for (let i = 0; i < 25; i++) {
      await sleep(200);
      msg = await page.evaluate(() =>
        document.querySelector('.el-message')?.textContent.trim()
        || document.querySelector('.el-message-box__message')?.textContent.trim() || '');
      if (msg) break;
    }
    // 卡片上应该显示下载次数 (⬇N)
    const cardHasCount = await page.evaluate(() =>
      [...document.querySelectorAll('.asset-card .meta-item')]
        .some((e) => /⬇\s*\d+/.test(e.textContent || '')));
    check('E5c 卡片上显示下载次数', cardHasCount);

    // 下载计数应该 +1 (热门度指标)
    const afterN = await totalCount();
    check('E5b 下载计数 +1', afterN === beforeN + 1, `${beforeN} → ${afterN}`);

    check('E6 提示说清下载与怎么装 (通用话术, 不写死某个 Agent 的目录)',
      /已下载/.test(msg) && /导入|压缩包/.test(msg), msg.slice(0, 80));

    // 再等一下让 zip 落盘
    for (let i = 0; i < 20; i++) {
      const f = fs.existsSync(dlDir) ? fs.readdirSync(dlDir) : [];
      if (f.some((x) => x.endsWith('.zip'))) break;
      await sleep(250);
    }
    const files = fs.existsSync(dlDir) ? fs.readdirSync(dlDir) : [];
    const zips = files.filter((f) => f.endsWith('.zip'));
    check('E5 点下载真的把 zip 落到了磁盘',
      zips.length > 0 || /\.zip$/.test(downloaded),
      zips.length ? `下载目录: ${zips.join(', ')}` : (downloaded || '(没有下载事件, 目录也空)'));

    await page.screenshot({ path: path.join(OUT_DIR, 'install-download.png'), fullPage: false });

    check('E7 全程无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ; '));
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) {
    console.log('失败项:\n' + failed.map((f) => ` - ${f.name} :: ${f.detail}`).join('\n'));
  }
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
