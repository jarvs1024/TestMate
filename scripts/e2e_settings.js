#!/usr/bin/env node
/**
 * 设置页实机走查 (真实 Chrome) —— 软件库 section + adminOnly 可见性.
 *
 * 盯住四件事 (2026-10-28):
 *   ① 设置页里**有**「软件库」这一组, 4 项配置都在 (以前后端有、前端没渲染);
 *   ② 存储目录能体检 —— 说清当前路径 / 能不能写 / 缺哪些文件;
 *   ③ 描述里的 `**粗体**` 渲染成**真加粗** (以前是一堆星号);
 *   ④ **非管理员整个设置页都看不到** —— 菜单里没有「设置」,
 *      手敲 /settings 会被踢回工作台.
 *
 * 用法:
 *   NODE_PATH=/tmp/tm-e2e/node_modules node scripts/e2e_settings.js [baseUrl]
 *
 * ⚠️ 需要一个**非管理员**账号来验第 ④ 条 ——
 *    优先用 TESTMATE_TESTER_USER / TESTMATE_TESTER_PASSWORD,
 *    没给就跳过那条 (不算失败, 但会打印"跳过").
 *
 * 退出码: 0 = 全过, 1 = 有断言失败, 2 = 脚本异常。
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.argv[2] || process.env.TESTMATE_BASE || 'http://localhost:8081').replace(/\/$/, '');
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');
const ADMIN_USER = process.env.TESTMATE_USER || 'admin';
const ADMIN_PASSWORD = process.env.TESTMATE_PASSWORD || 'Admin@123';
// 非管理员账号 (验第 ④ 条用) —— 没配就跳过那条
const TESTER_USER = process.env.TESTMATE_TESTER_USER || '';
const TESTER_PASSWORD = process.env.TESTMATE_TESTER_PASSWORD || '';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail || '' });
  const tag = ok ? '  ok  ' : ' FAIL ';
  console.log(`[${tag}] ${name}${detail ? ' — ' + detail : ''}`);
}
function skip(name, why) {
  console.log(`[ skip ] ${name} — ${why}`);
}

/**
 * 登录 (带密码).
 *
 * ⚠️ 账号框要**先清空再输** ——
 *   同一个 browser 里所有 page 共享 localStorage, 上一个账号 (admin) 的 token
 *   会让登录页记住用户名, 直接 type 上去就变成 "adminzhangsan@twsc.com.cn",
 *   登录静默失败, 页面还停在 /login, 后面找 .tm-user 就报
 *   "No element found for selector". 这是 2026-10-28 实际踩到的.
 */
async function login(page, user, password) {
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle2' });
  await sleep(600);
  await page.evaluate(() => {
    const el = document.querySelector('input[autocomplete="username"]');
    if (el) {
      el.value = '';
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });
  await page.type('input[autocomplete="username"]', user, { delay: 10 });
  await sleep(900);
  const pwd = await page.$('input[autocomplete="current-password"]');
  if (pwd) await pwd.type(password, { delay: 10 });
  await page.click('button.primary');
  await sleep(2500);
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--window-size=1600,1000'],
  });

  try {
    // ================= 管理员视角 =================
    const page = await browser.newPage();
    await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 2 });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

    await login(page, ADMIN_USER, ADMIN_PASSWORD);
    await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle2' });
    await sleep(1800);

    // ① 目录里跟**首页能力墙**对齐: 能力墙 → 资产/工具/看板, 资产下三张卡
    const toc = await page.evaluate(() =>
      [...document.querySelectorAll('.set-toc .toc-item, .set-toc .toc-sub li')]
        .map((t) => t.textContent.trim()));
    check('S1 目录里有「能力墙」', toc.some((t) => t.includes('能力墙')), toc.join(' | '));
    check('S1b 能力墙下分 资产/工具/看板',
      ['资产', '工具', '看板'].every((k) => toc.some((t) => t.includes(k))));
    check('S1c 资产下挂 插件·技能·连接/知识库/软件库',
      ['插件·技能·连接', '知识库', '软件库'].every((k) => toc.some((t) => t.includes(k))));
    const topLabels = await page.evaluate(() =>
      [...document.querySelectorAll('.set-toc > .toc-item')].map((t) => t.textContent.trim()));
    check('S1d 顶级没有平级的「知识库」「软件库」',
      !topLabels.some((t) => t.includes('知识库')) && !topLabels.some((t) => t.includes('软件库')),
      topLabels.join(' | '));

    // 点进「能力墙」顶级项, 再点资产下的「软件库」(第三层)
    await page.evaluate(() => {
      const it = [...document.querySelectorAll('.set-toc .toc-item')]
        .find((t) => t.textContent.includes('能力墙'));
      if (it) it.click();
    });
    await sleep(1200);
    await page.evaluate(() => {
      const it = [...document.querySelectorAll('.set-toc .toc-sub3 li')]
        .find((t) => t.textContent.includes('软件库'));
      if (it) it.click();
    });
    await sleep(1500);

    const sw = await page.evaluate(() => {
      const d = document.querySelector('.set-main');
      return {
        keys: [...d.querySelectorAll('.lbl-col code')].map((c) => c.textContent.trim()),
        descs: [...d.querySelectorAll('.lbl-col .d')].map((x) => x.innerHTML),
        hasProbe: [...d.querySelectorAll('button')].some((b) => b.textContent.includes('体检存储目录')),
      };
    });
    check('S2 软件库 4 项配置都在',
      ['software.storage_path', 'software.max_size_mb',
        'software.keep_versions', 'software.public_download'].every((k) => sw.keys.includes(k)),
      sw.keys.join(' | '));
    check('S3 有「体检存储目录」按钮', sw.hasProbe);

    // ② 点体检
    await page.evaluate(() => {
      const b = [...document.querySelectorAll('.set-main button')]
        .find((x) => x.textContent.includes('体检存储目录'));
      if (b) b.click();
    });
    await sleep(2500);
    const probe = await page.evaluate(() => {
      const r = document.querySelector('.set-main .test-result');
      return r ? r.textContent.trim() : '';
    });
    check('S4 体检有结果', probe.length > 0, probe.slice(0, 120));
    check('S4b 体检说清了当前路径', probe.includes('/'), probe.slice(0, 120));
    await page.screenshot({ path: path.join(OUT_DIR, 'set-software.png') });

    // ③ 粗体渲染
    check('S5 描述里没有残留的 ** 星号',
      !sw.descs.some((d) => d.includes('**')));
    check('S6 描述里有真加粗的 <strong>',
      sw.descs.some((d) => d.includes('<strong>')));

    // ⑦ 数据源各归各家 (2026-10-28): RAGFlow → 知识库, ReviewAgent → 代码检视
    const ds = await page.evaluate(() => {
      const kb = document.querySelector('#sec-asset-kb');
      const board = document.querySelector('#sec-board-code-review');
      const general = document.querySelector('#sec-general');
      return {
        kbHasRagflow: !!(kb && kb.textContent.includes('ragflow.base_url')),
        kbHasReview: !!(kb && kb.textContent.includes('review_agent.base_url')),
        boardHasReview: !!(board && board.textContent.includes('review_agent.base_url')),
        boardHasRagflow: !!(board && board.textContent.includes('ragflow.base_url')),
        generalHasDs: !!(general && general.textContent.includes('ragflow.base_url')),
        generalCnt: (() => {
          const h = document.querySelector('#sec-general h2');
          return h ? h.textContent.replace(/\s+/g, ' ').trim() : '';
        })(),
        toolNote: (() => {
          const t = document.querySelector('#sec-tool');
          return t ? t.textContent.replace(/\s+/g, ' ').trim() : '';
        })(),
      };
    });
    check('S7 RAGFlow 归到「资产 → 知识库」下',
      ds.kbHasRagflow && !ds.kbHasReview, JSON.stringify([ds.kbHasRagflow, ds.kbHasReview]));
    check('S7b ReviewAgent 归到「看板 → 代码检视」下',
      ds.boardHasReview && !ds.boardHasRagflow, JSON.stringify([ds.boardHasReview, ds.boardHasRagflow]));
    check('S7c「通用」里不再挂数据源', !ds.generalHasDs, ds.generalCnt);
    check('S7d 工具组说清了「暂无可配置项」',
      ds.toolNote.includes('还没有'), ds.toolNote.slice(0, 60));

    check('S8 全程无 JS 错误', errors.length === 0, errors.slice(0, 3).join(' | '));

    // ================= 非管理员视角 =================
    if (TESTER_USER) {
      // ⚠️ 必须用**独立的 browser context** ——
      //   同一个 browser 里的所有 page 共享 localStorage, admin 的 token
      //   还在的话, 非管理员这一段会被当成 admin (登录页记住用户名 + 直接带 token),
      //   测出来的「菜单里没有设置」就成了假阳性。
      const ctx = await browser.createBrowserContext();
      const p2 = await ctx.newPage();
      await p2.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 2 });
      await login(p2, TESTER_USER, TESTER_PASSWORD);

      const landed = await p2.evaluate(() => ({
        url: location.pathname,
        hasUser: !!document.querySelector('.tm-user'),
      }));
      check('S9a 非管理员登录成功并落到工作台',
        landed.hasUser && landed.url !== '/login',
        `${landed.url} / 顶栏用户区 ${landed.hasUser ? '有' : '无'}`);

      // ④a 菜单里没有「设置」
      await p2.click('.tm-user');
      await sleep(900);
      const menu = await p2.evaluate(() => document.body.innerText);
      check('S9 非管理员菜单里没有「设置」', !menu.includes('设置'));
      await p2.screenshot({ path: path.join(OUT_DIR, 'set-nonadmin-menu.png') });
      await p2.keyboard.press('Escape');
      await sleep(500);

      // ④b 手敲 /settings → 踢回工作台
      await p2.goto(`${BASE}/settings`, { waitUntil: 'networkidle2' });
      await sleep(2000);
      const nd = await p2.evaluate(() => ({
        url: location.pathname,
        text: document.body.innerText,
      }));
      check('S10 非管理员手敲 /settings 被踢回工作台', nd.url === '/', nd.url);
      check('S11 非管理员看不到任何配置项',
        !nd.text.includes('software.storage_path') && !nd.text.includes('platform_name'),
        nd.text.slice(0, 100));
      await p2.screenshot({ path: path.join(OUT_DIR, 'set-nonadmin-redirect.png') });
    } else {
      skip('S9~S11 非管理员可见性', '没配 TESTMATE_TESTER_USER / TESTMATE_TESTER_PASSWORD');
    }

    const failed = results.filter((r) => !r.ok);
    console.log(`\n=== 设置页走查: ${results.length - failed.length}/${results.length} 通过 ===`);
    if (failed.length) {
      console.log('失败项:');
      failed.forEach((f) => console.log(`  ✗ ${f.name} ${f.detail}`));
    }
    process.exitCode = failed.length ? 1 : 0;
  } catch (e) {
    console.error('FAILED:', e && e.stack || e);
    process.exitCode = 2;
  } finally {
    await browser.close();
  }
})();
