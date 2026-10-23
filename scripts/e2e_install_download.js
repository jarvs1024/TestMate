#!/usr/bin/env node
/**
 * 一键安装 —— **下载安装包**的界面验收.
 *
 * 安装现在只有一条路: 下载 zip, 自己解压到 ~/.qoder-cn/skills/<code>/.
 * ⚠️ 浏览器写盘 (File System Access) 与服务端写盘**都已下线** ——
 *    设置里也没有"安装目录"了.
 *
 * 验用户真正看到的东西:
 *   1. 安装对话框能打开
 *   2. **没有**选目录 / 写入本机的选项
 *   3. 写清下载的文件名与"解压到哪"
 *   4. 主按钮就是「下载安装包」
 *   5. 点了真的能下载 (文件名正确)
 *   6. 有「复制安装命令」兜底
 *   7. 全程无 JS 错误
 *
 * 用法: node scripts/e2e_install_download.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const os = require('os');
const path = require('path');

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
    // ⚠️ 无头 Chrome 默认**禁止下载** —— 必须用 CDP 显式允许, 否则点下载没反应
    // ⚠️ Browser 域的指令要走 **browser 级** CDP session (page 级的不生效)
    const dlDir = path.join(OUT_DIR, 'downloads');
    fs.rmSync(dlDir, { recursive: true, force: true });
    fs.mkdirSync(dlDir, { recursive: true });
    const bcdp = await browser.target().createCDPSession();
    await bcdp.send('Browser.setDownloadBehavior', {
      behavior: 'allow',
      downloadPath: dlDir,
      eventsEnabled: true,
    });
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

    // 先点开详情抽屉 —— 「安装」按钮在抽屉里 (.ad-actions), 不在卡片上
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
    await sleep(600);

    const opened = await page.evaluate(() => {
      const b = [...document.querySelectorAll('.ad-actions button')].find(
        (x) => /安装/.test(x.textContent || '') && !x.disabled,
      );
      if (b) { b.click(); return true; }
      return false;
    });
    check('E3 详情抽屉里有可点的安装按钮', opened);
    if (!opened) throw new Error('没有找到安装按钮');

    await page.waitForSelector('.inst-pkg', { timeout: 15000 });
    await sleep(800);

    const ui = await page.evaluate(() => {
      const txt = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
      const footerBtns = [...document.querySelectorAll('.el-dialog__footer button')].map(txt);
      return {
        chanCount: document.querySelectorAll('.inst-chan').length,
        pkgRows: [...document.querySelectorAll('.inst-pkg-row')].map(txt),
        note: txt(document.querySelector('.inst-note')),
        primaryBtn: footerBtns[footerBtns.length - 1],
        footerBtns,
        wholeDialog: txt(document.querySelector('.el-dialog')),
      };
    });

    check('E4 没有选目录 / 本机写入的选项',
      ui.chanCount === 0 && !/选择目录|写入你选的目录|本地目录/.test(ui.wholeDialog),
      `chan=${ui.chanCount}`);
    check('E5 写清了文件名与解压目标',
      ui.pkgRows.length === 2
      && /\.zip$/.test(ui.pkgRows[0]) && ui.pkgRows[1].includes('~/'),
      ui.pkgRows.join(' | '));
    check('E6 主按钮就是「下载安装包」',
      /下载安装包/.test(ui.primaryBtn), ui.primaryBtn);
    check('E7 有「复制安装命令」兜底',
      ui.footerBtns.some((b) => /复制安装命令/.test(b)),
      ui.footerBtns.join(' | '));

    // 点下载 → 应该真的把 zip 落到下载目录
    // ⚠️ 无头 Chrome 里 puppeteer 的 download 事件可能不触发, 所以直接查目录
    let downloaded = '';
    page.on('download', async (dl) => {
      downloaded = dl.suggestedFilename();
      try { await dl.cancel(); } catch { /* 已取消 */ }
    });
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('.el-dialog__footer .el-button')]
        .find((x) => x.textContent.includes('下载安装包'));
      b && b.click();
    });
    await sleep(4000);
    const files = fs.existsSync(dlDir) ? fs.readdirSync(dlDir) : [];
    const zips = files.filter((f) => f.endsWith('.zip'));
    check('E8 点下载真的把 zip 落到了磁盘',
      zips.length > 0 || /\.zip$/.test(downloaded),
      zips.length ? `下载目录: ${zips.join(', ')}` : (downloaded || '(没有下载事件, 目录也空)'));

    const done = await page.evaluate(() =>
      document.querySelector('.el-dialog .el-alert__title')?.textContent.trim() || '');
    check('E9 提示了下载完成与解压位置',
      /已下载/.test(done) && /解压/.test(done), done.slice(0, 70));

    await page.screenshot({ path: path.join(OUT_DIR, 'install-download.png'), fullPage: false });

    check('E10 全程无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ; '));
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
