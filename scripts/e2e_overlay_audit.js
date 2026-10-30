#!/usr/bin/env node
/**
 * **浮层内部「白盖白」审计** (2026-10-30 · 第十轮 · 配套工具).
 *
 * 背景: 第十轮把浮层面板改成**纯白不透明**之后, 抽屉**内部**那些
 *       用 `var(--surface)` (半透明白 rgba(255,255,255,.60)) 的块
 *       盖在纯白面板上 → 合成后还是纯白 → **底色层次全没了**,
 *       只剩一条 6% 的淡边框, 看着"还是老样子".
 *
 * 这个脚本量化这个问题: 打开每个抽屉, 遍历里面所有元素,
 * 把半透明底色跟父级**合成**一遍, 算出「实际看到的颜色」,
 * 再跟父级比 —— 差 < 3/255 就说明「这块跟背景没区别」= 糊了.
 *
 * ⚠️ 纯只读: 只截图 + 读样式, 不做任何写操作.
 *
 * 用法 (native 端口):
 *   NODE_PATH=/tmp/tm-e2e/node_modules \
 *   TESTMATE_BASE=http://localhost:8081 TESTMATE_API=http://127.0.0.1:8000 \
 *   node scripts/e2e_overlay_audit.js
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
 * ⚠️ 在**页面里**跑的审计函数 ——
 *    半透明底色要跟父级合成才能知道「实际看到的颜色」,
 *    逐层往上递归到不透明底为止.
 */
const AUDIT_FN = `
(() => {
  const parse = (c) => {
    const m = c.match(/rgba?\\(([^)]+)\\)/);
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a),
    a: 1,
  });
  /** 往上找，直到找到不透明的底 */
  const effBg = (el) => {
    let cur = el;
    let stack = [];
    while (cur) {
      const c = parse(getComputedStyle(cur).backgroundColor);
      if (c && c.a > 0) {
        stack.push(c);
        if (c.a >= 0.999) break;
      }
      cur = cur.parentElement;
    }
    let acc = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = stack.length - 1; i >= 0; i--) acc = over(stack[i], acc);
    return acc;
  };
  const near = (a, b) =>
    Math.abs(a.r - b.r) < 3 && Math.abs(a.g - b.g) < 3 && Math.abs(a.b - b.b) < 3;

  const root = document.querySelector('.el-drawer') || document.body;
  const panel = effBg(root);
  const out = [];
  root.querySelectorAll('*').forEach((el) => {
    const cs = getComputedStyle(el);
    const c = parse(cs.backgroundColor);
    if (!c || c.a === 0) return;              // transparent —— 不算
    const rect = el.getBoundingClientRect();
    if (rect.width < 6 || rect.height < 6) return;   // 太小的不看
    const own = effBg(el);
    const parentEff = el.parentElement ? effBg(el.parentElement) : panel;
    // 自己的底跟**父级**几乎一样 → 这一层白盖白, 白画了
    const invisible = near(own, parentEff) && own.a >= 0.999;
    if (!invisible) return;
    // 得是个"块"才有意义: 有边框/圆角/阴影, 或者是个明显成组的容器
    const hasBorder = cs.borderTopWidth !== '0px' || cs.borderBottomWidth !== '0px';
    const hasRadius = parseFloat(cs.borderTopLeftRadius) > 0;
    const hasShadow = cs.boxShadow !== 'none';
    if (!hasBorder && !hasRadius && !hasShadow) return;
    // ⚠️ **别把「白底 + 灰边的小按钮」报成问题** ——
    //    EP 默认按钮就是白底 + 边框, 那是正常样式, 靠边框就能分辨.
    //    真正的问题是: **大面积的块** (靠底色区分) 或者 **完全没边框的块**.
    const area = rect.width * rect.height;
    if (hasBorder && area <= 5000) return;
    out.push({
      tag: el.tagName.toLowerCase(),
      cls: (el.className && typeof el.className === 'string' ? el.className : '')
        .split(/\\s+/).filter(Boolean).slice(0, 3).join('.'),
      ownBg: cs.backgroundColor,
      eff: [Math.round(own.r), Math.round(own.g), Math.round(own.b)].join(','),
      parentEff: [Math.round(parentEff.r), Math.round(parentEff.g), Math.round(parentEff.b)].join(','),
      w: Math.round(rect.width), h: Math.round(rect.height),
      text: (el.textContent || '').trim().slice(0, 24),
    });
  });
  return { panel: [Math.round(panel.r), Math.round(panel.g), Math.round(panel.b)].join(','), out };
})()
`;

const SCENES = [
  {
    key: 'software', route: '/software', desc: '软件库 · 详情抽屉',
    async open(page) {
      await page.waitForSelector('.asset-card', { timeout: 15000 });
      await sleep(1200);
      await page.evaluate(() => document.querySelector('.asset-card')?.click());
    },
  },
  {
    key: 'market', route: '/market', desc: '资产市场 · 详情抽屉',
    async open(page) {
      await page.waitForSelector('.asset-card', { timeout: 15000 });
      await sleep(1500);
      await page.evaluate(() => document.querySelector('.asset-card')?.click());
    },
  },
  {
    key: 'kb', route: '/kb-manage', desc: '知识库 · 新建数据集抽屉',
    async open(page) {
      await page.waitForSelector('.ghost-btn, .ds-hd', { timeout: 15000 });
      await sleep(1200);
      await page.evaluate(() => {
        [...document.querySelectorAll('button')]
          .find((x) => x.textContent.includes('新建数据集'))?.click();
      });
    },
  },
  {
    key: 'kb-upload', route: '/kb-manage', desc: '知识库 · 上传文档抽屉',
    async open(page) {
      await page.waitForSelector('.ghost-btn, .ds-hd', { timeout: 15000 });
      await sleep(1200);
      await page.evaluate(() => {
        [...document.querySelectorAll('button')]
          .find((x) => x.textContent.includes('上传文档'))?.click();
      });
    },
  },
];

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const r = await fetch(API + '/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
  });
  const token = (await r.json()).access_token || '';
  if (!token) throw new Error('登录失败');

  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1440, height: 900 },
  });
  const page = await browser.newPage();
  await page.setCacheEnabled(false);

  let total = 0;
  for (const theme of ['light', 'dark']) {
    for (const scene of SCENES) {
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
      const ok = await page.waitForSelector('.el-drawer', { timeout: 8000 }).catch(() => null);
      if (!ok) { console.log(`  ⚠️  ${theme}-${scene.key}: 抽屉没打开, 跳过`); continue; }
      await sleep(1000);

      const res = await page.evaluate(AUDIT_FN);
      total += res.out.length;
      console.log(`\n  ── ${theme} · ${scene.desc} ──  面板实际底色 = rgb(${res.panel})`);
      if (!res.out.length) { console.log('     ✅ 没有白盖白的块'); continue; }
      console.log(`     ⚠️  ${res.out.length} 个块「跟背景没区别」(白盖白):`);
      res.out.slice(0, 14).forEach((o) => {
        console.log(`        ${o.tag}.${o.cls}  own=${o.ownBg}  eff=rgb(${o.eff})  父=rgb(${o.parentEff})  ${o.w}x${o.h}  "${o.text}"`);
      });
      if (res.out.length > 14) console.log(`        … 还有 ${res.out.length - 14} 个`);
    }
  }
  await browser.close();
  console.log(`\n合计「白盖白」的块: ${total}`);
})().catch((e) => { console.error('❌', e); process.exit(1); });
