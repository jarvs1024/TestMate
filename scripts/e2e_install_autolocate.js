#!/usr/bin/env node
/**
 * 一键安装「自动定位家目录」—— 前端 UI 验收.
 *
 * 验的是用户真正看到的东西:
 *   1. 安装对话框能打开
 *   2. 显示的目标路径是**家目录相对**形式 (~/.qoder-cn/skills/<code>)
 *   3. 勾上"自动装到"时, 提示语讲清了首次要选一次家目录
 *   4. 有「记住我的家目录 / 换一个安装目录 / 清除记忆」三个入口
 *   5. 全程无 JS 错误
 *
 * ⚠️ 真正的写盘要在有头浏览器里手动授权目录, 无头环境做不到 ——
 *    这里验的是"自动定位的路径与提示是否正确", 写盘由单测覆盖.
 *
 * 用法: node scripts/e2e_install_autolocate.js
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
      const cards = [...document.querySelectorAll('.asset-card')];
      const c = cards[0];
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

    // 先等对话框加载完, 再切到**前端通道** —— 自动定位区块只在前端通道下渲染
    await page.waitForSelector('.inst-chan', { timeout: 15000 });
    await sleep(500);
    await page.evaluate(() => {
      const r = document.querySelectorAll('.inst-chan input')[1];
      if (r) { r.click(); }
    });
    await page.waitForSelector('.inst-auto', { timeout: 15000 });
    await sleep(800);

    const ui = await page.evaluate(() => {
      const txt = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
      return {
        autoTitle: txt(document.querySelector('.inst-auto-t')),
        autoPath: txt(document.querySelector('.inst-auto-path')),
        autoDesc: txt(document.querySelector('.inst-auto-d')),
        buttons: [...document.querySelectorAll('.inst-auto-actions button')].map(txt),
        frontendChan: txt(document.querySelectorAll('.inst-chan-d')[1]),
        note: txt(document.querySelector('.inst-note')),
        checked: !!document.querySelector('.inst-auto-row input')?.checked,
      };
    });

    check('E4 自动安装区块渲染出来', !!ui.autoTitle, ui.autoTitle);
    check('E5 目标路径是家目录相对形式',
      /^~\//.test(ui.autoPath) && /skills|plugins/.test(ui.autoPath),
      ui.autoPath);
    check('E6 提示语说清了首次授权一次',
      /首次|选一次|主目录|记住/.test(ui.autoDesc),
      ui.autoDesc);
    check('E7 三个操作入口都在',
      ui.buttons.length === 3
      && ui.buttons.some((b) => /家目录/.test(b))
      && ui.buttons.some((b) => /换一个安装目录/.test(b))
      && ui.buttons.some((b) => /清除记忆/.test(b)),
      ui.buttons.join(' | '));
    check('E8 前端通道文案说明自动定位',
      /自动定位|指定安装位置/.test(ui.frontendChan),
      ui.frontendChan);
    check('E8b 默认勾选自动定位',
      !!ui.checked,
      `checked=${ui.checked} 标题="${ui.autoTitle}"`);

    // 已经在前端通道上了, 确认自动定位提示
    const after = await page.evaluate(() => {
      const txt = (el) => (el?.textContent || '').replace(/\s+/g, ' ').trim();
      return {
        desc: txt(document.querySelector('.inst-auto-d')),
        path: txt(document.querySelector('.inst-auto-path')),
        checked: !!document.querySelector('.inst-auto-row input')?.checked,
      };
    });
    check('E9 切到前端通道后仍显示自动路径',
      /^~\//.test(after.path), after.path);
    check('E10 提示语说明浏览器安全限制',
      /首次|授权|选一次|主目录/.test(after.desc), after.desc);

    await page.screenshot({ path: path.join(OUT_DIR, 'install-autolocate.png'), fullPage: false });

    check('E11 全程无 JS 错误', errors.length === 0, errors.slice(0, 2).join(' ; '));
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
