#!/usr/bin/env node
/**
 * **浮层面板整改的对照截图** (2026-10-30 · 第十轮).
 *
 * 用户报: "所有这种抽屉的地方, 上下背景不协调, 整体都不对劲, 不是一个整体了?
 *          改回之前全白色的?"
 *
 * ⚠️ **这个脚本不改仓库任何代码** —— 它在**运行时**往页面里注入一段旧 CSS,
 *    复现「改之前」的样子, 截完再把注入的 <style> 删掉, 截「改之后」.
 *    所以前后对照是**同一个构建产物**下的真实渲染, 不是两套代码拼出来的.
 *
 * ⚠️ **绝对不往真实钉钉群发消息**, 也不做任何写操作 —— 只截图。
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_overlay_screenshot.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
require('./e2e_lock').acquire(__filename);

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8081').replace(/\/$/, '');
const API = process.env.TESTMATE_API || 'http://127.0.0.1:8000';
const ADMIN = process.env.TESTMATE_USER || 'admin';
const ADMIN_PW = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * ⚠️ **「改之前」的样子** —— 第八轮 (`86c1414`) 引入的那套半透明底色.
 *    跟 `main.css` 现在的规则**特异性相同**, 但因为是后注入的, 文档顺序更靠后 → 覆盖生效.
 */
const OLD_CSS = `
html, html[data-theme] {
  --el-bg-color: var(--surface) !important;
  --el-bg-color-overlay: var(--surface) !important;
}
.el-drawer, .el-dialog, .el-message-box { background-color: var(--surface) !important; }
.el-drawer__body { background-color: var(--surface) !important; }
.el-popper, .el-dropdown-menu, .el-select-dropdown, .el-popover { background: var(--surface) !important; }
`;

const shots = [];
async function shot(page, name, desc) {
  const file = path.join(OUT_DIR, `overlay-${name}.png`);
  await page.screenshot({ path: file });
  shots.push({ file, desc });
  console.log(`  📸 ${name} — ${desc}`);
}

/** 读抽屉 header / body 的实际计算底色 —— 用来证明两者是否同一个色 */
async function probePanel(page) {
  return page.evaluate(() => {
    const g = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const cs = getComputedStyle(el);
      return {
        bg: cs.backgroundColor,
        color: cs.color,
        border: cs.borderBottomColor,
        rect: (({ x, y, width, height }) => ({ x, y, width, height }))(el.getBoundingClientRect()),
      };
    };
    return {
      drawer: g('.el-drawer'),
      header: g('.el-drawer__header'),
      body: g('.el-drawer__body'),
      overlay: g('.el-overlay'),
      theme: document.documentElement.getAttribute('data-theme'),
      htmlClass: document.documentElement.className,
    };
  });
}

/** 把旧 CSS 注进去 (复现「改之前」) */
async function injectOld(page) {
  await page.evaluate((css) => {
    const s = document.createElement('style');
    s.id = '__old_overlay_css__';
    s.textContent = css;
    document.head.appendChild(s);
  }, OLD_CSS);
  await sleep(350);
}

/** 把注入的旧 CSS 摘掉 (回到「改之后」) */
async function removeOld(page) {
  await page.evaluate(() => {
    const s = document.getElementById('__old_overlay_css__');
    s && s.remove();
  });
  await sleep(350);
}

/** 关掉抽屉, 回到干净状态 */
async function closeDrawer(page) {
  await page.keyboard.press('Escape');
  await sleep(400);
  await page.evaluate(() => {
    document.querySelectorAll('.el-overlay').forEach((o) => {
      const d = o.querySelector('.el-drawer');
      if (d && getComputedStyle(d).display !== 'none') o.click();
    });
  });
  await sleep(400);
}

/**
 * 三个代表性场景 —— 抽屉是三种宽度 / 三种内容
 */
const SCENES = [
  {
    key: 'software',
    route: '/software',
    desc: '软件库 · 详情抽屉 (720px)',
    async open(page) {
      // ⚠️ 软件卡片用的是 `.asset-card` (跟资产市场同款 class, 见 SoftwareCard.vue)
      await page.waitForSelector('.asset-card', { timeout: 15000 });
      await sleep(1200);
      await page.evaluate(() => {
        const c = document.querySelector('.asset-card');
        c && c.click();
      });
    },
  },
  {
    key: 'market',
    route: '/market',
    desc: '资产市场 · 详情抽屉',
    async open(page) {
      await page.waitForSelector('.asset-card', { timeout: 15000 });
      await sleep(1500);
      await page.evaluate(() => {
        const c = document.querySelector('.asset-card');
        c && c.click();
      });
    },
  },
  {
    key: 'kb',
    route: '/kb-manage',
    desc: '知识库 · 新建数据集抽屉 (表单)',
    async open(page) {
      await page.waitForSelector('.ghost-btn, .ds-hd', { timeout: 15000 });
      await sleep(1200);
      await page.evaluate(() => {
        const b = [...document.querySelectorAll('button')].find((x) =>
          x.textContent.includes('新建数据集'));
        b && b.click();
      });
    },
  },
];

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  // ---- 登录拿 token ----
  const r = await fetch(API + '/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
  });
  const token = (await r.json()).access_token || '';
  if (!token) throw new Error('登录失败, 没有拿到 token');

  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1440, height: 900 },
  });
  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  const errors = [];
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });

  const report = [];

  for (const theme of ['light', 'dark']) {
    for (const scene of SCENES) {
      const tag = `${theme}-${scene.key}`;

      // ---- 设置身份 + 主题, 进场 ----
      await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
      const me = await page.evaluate(async (t) => {
        const rr = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + t } });
        return rr.ok ? await rr.json() : { id: 1, username: 'admin', role: 'admin' };
      }, token);
      await page.evaluate((t, u, th) => {
        localStorage.setItem('testmate:token', t);
        localStorage.setItem('testmate:user', JSON.stringify(u));
        localStorage.setItem('testmate:theme', th);
      }, token, me, theme);

      await page.goto(BASE + scene.route, { waitUntil: 'domcontentloaded' });
      await sleep(1500);
      await scene.open(page);

      // 抽屉没开出来就跳过 (场景依赖真实数据)
      const opened = await page.waitForSelector('.el-drawer', { timeout: 8000 }).catch(() => null);
      if (!opened) {
        console.log(`  ⚠️  ${tag}: 抽屉没打开, 跳过`);
        await closeDrawer(page);
        continue;
      }
      await sleep(1200);

      // ---- 改之后 (现在的样子) ----
      const after = await probePanel(page);
      await shot(page, `${tag}-after`, `${scene.desc} · 改之后 (${theme})`);

      // ---- 改之前 (注入旧 CSS) ----
      await injectOld(page);
      const before = await probePanel(page);
      await shot(page, `${tag}-before`, `${scene.desc} · 改之前 (${theme})`);
      await removeOld(page);

      report.push({ tag, theme, scene: scene.desc, before, after });

      console.log(`\n  ── ${tag} ──`);
      console.log(`     改之前  抽屉底色=${before.drawer?.bg}  header=${before.header?.bg}  body=${before.body?.bg}`);
      console.log(`     改之后  抽屉底色=${after.drawer?.bg}  header=${after.header?.bg}  body=${after.body?.bg}`);
      console.log(`     一致?   header === body → ${after.header?.bg === after.body?.bg ? '✅ 是' : '❌ 不是'}`);

      await closeDrawer(page);
    }
  }

  await browser.close();

  fs.writeFileSync(
    path.join(OUT_DIR, 'overlay-report.json'),
    JSON.stringify({ shots, report, errors }, null, 2),
  );

  console.log(`\n✅ 截图 ${shots.length} 张 → ${OUT_DIR}`);
  if (errors.length) {
    console.log(`⚠️  控制台报错 ${errors.length} 条:`);
    errors.slice(0, 10).forEach((e) => console.log('   ' + e));
  } else {
    console.log('✅ 无控制台报错');
  }
})().catch((e) => { console.error('❌', e); process.exit(1); });
