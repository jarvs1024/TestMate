#!/usr/bin/env node
/**
 * 一键安装 —— **两种手动方式**的界面验收.
 *
 * 安装现在的形态:
 *   ① 选择目录安装 —— 浏览器弹目录选择器, 把文件写进去
 *   ② 下载安装包   —— 下 zip, 自己解压
 * ⚠️ 不再有「装到服务器配置的目录」—— 服务端写盘通道已下线.
 *
 * 验用户真正看到的东西:
 *   1. 安装对话框能打开
 *   2. **没有**服务端安装选项
 *   3. 两种手动方式都在, 默认选「选择目录安装」
 *   4. 目标路径是家目录相对形式 (~/.qoder-cn/skills/<code>)
 *   5. 主按钮文案随方式变
 *   6. 「下载安装包」方式说明了解压到哪
 *   7. 全程无 JS 错误
 *
 * ⚠️ 真正的写盘要在有头浏览器里手动授权目录, 无头环境做不到 ——
 *    这里验的是"选项与提示是否正确", 写盘由单元测试覆盖.
 *
 * 用法: node scripts/e2e_install_manual.js
 */
const puppeteer = require('puppeteer-core');
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

    await page.waitForSelector('.inst-chan', { timeout: 15000 });
    await sleep(800);

    const ui = await page.evaluate(() => {
      const txt = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
      const chanTitles = [...document.querySelectorAll('.inst-chan-t')].map(txt);
      const radios = [...document.querySelectorAll('.inst-chan input')].map((r) => r.value);
      const footerBtns = [...document.querySelectorAll('.el-dialog__footer button')].map(txt);
      return {
        chanTitles,
        radios,
        checked: [...document.querySelectorAll('.inst-chan input')]
          .filter((r) => r.checked).map((r) => r.value),
        note: txt(document.querySelector('.inst-note')),
        zipDesc: txt(document.querySelectorAll('.inst-chan-d')[1]),
        primaryBtn: footerBtns[footerBtns.length - 1],
        wholeDialog: txt(document.querySelector('.el-dialog')),
      };
    });

    check('E4 只有两种安装方式',
      ui.radios.length === 2 && ui.radios.includes('dir') && ui.radios.includes('zip'),
      `radios=${ui.radios.join(',')}`);
    check('E5 没有「装到服务器配置的目录」',
      !/服务器/.test(ui.wholeDialog),
      ui.chanTitles.join(' | '));
    check('E6 默认选「选择目录安装」',
      ui.checked.length === 1 && ui.checked[0] === 'dir',
      `checked=${ui.checked.join(',')}`);
    check('E7 目标路径是家目录相对形式',
      /~\/\.qoder-cn/.test(ui.zipDesc),
      ui.zipDesc);
    check('E8 主按钮文案随方式变',
      /选择目录并安装/.test(ui.primaryBtn),
      ui.primaryBtn);
    check('E9 提示说明了选哪个目录',
      /安装根目录/.test(ui.note),
      ui.note);

    // 切到「下载安装包」→ 主按钮与说明都要变
    await page.evaluate(() => {
      const r = [...document.querySelectorAll('.inst-chan input')].find((x) => x.value === 'zip');
      if (r) { r.click(); }
    });
    await sleep(600);
    const after = await page.evaluate(() => {
      const txt = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
      const footerBtns = [...document.querySelectorAll('.el-dialog__footer button')].map(txt);
      return {
        note: txt(document.querySelector('.inst-note')),
        primaryBtn: footerBtns[footerBtns.length - 1],
      };
    });
    check('E10 切到下载方式后主按钮变「下载安装包」',
      /下载安装包/.test(after.primaryBtn), after.primaryBtn);
    check('E11 下载方式说明了解压到哪',
      /解压到/.test(after.note), after.note);

    await page.screenshot({ path: path.join(OUT_DIR, 'install-manual.png'), fullPage: false });

    check('E12 全程无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ; '));
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
