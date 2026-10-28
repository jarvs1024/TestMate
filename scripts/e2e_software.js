#!/usr/bin/env node
/**
 * 软件库走查 (真实 Chrome) —— 上传 / 浏览 / 下载 / 发新版本.
 *
 * 盯住 2026-10-27 这轮落地的功能:
 *   ① /software 页面能打开, 卡片按「插件·技能·连接」那套视觉呈现;
 *   ② 上传抽屉: 填信息 + 选文件 → 上传 → 卡片出现;
 *   ③ 详情抽屉能看到 **功能清单 / 适用场景 / 发布与更新说明**;
 *   ④ 下载: 走短时票据, 文件真的落到磁盘, sha256 与后端一致;
 *   ⑤ 发新版本 → 版本历史多一条 → 新版能下, **旧版仍然能下**;
 *   ⑥ 全程无 JS 错误.
 *
 * ⚠️ 收尾: 用平台的 purge 接口把条目与**磁盘文件**一起删干净
 *    (审计流水 asset_audits 里会留一条记录 —— 那是审计, 不该删).
 *
 * 用法: NODE_PATH=/tmp/tm-e2e/node_modules node scripts/e2e_software.js [baseUrl]
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
// ⚠️ 互斥锁: 并行跑 e2e 会互相改生产设置/删数据 (见 e2e_lock.js)
require('./e2e_lock').acquire(__filename);

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.argv[2] || process.env.TESTMATE_BASE || 'http://localhost:8081').replace(/\/$/, '');
const USER = process.env.TESTMATE_USER || 'admin';
const PASSWORD = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');

/** 这次跑用的软件标识 —— 带时间戳, 免得跟别的跑撞上 */
const CODE = `e2e-sw-${Date.now().toString(36)}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail: detail || '' });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}

/** 本次上传的文件内容 (故意用二进制, 验证"任意格式"这条路) */
const PAYLOAD = Buffer.from('TestMate 软件库 e2e payload — 任意二进制内容\n'.repeat(64));
const PAYLOAD_SHA = crypto.createHash('sha256').update(PAYLOAD).digest('hex');
const FILE_NAME = `${CODE}.bin`;

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1600, height: 1000 },
  });
  const errors = [];
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'tm-sw-e2e-'));
  const srcFile = path.join(tmpDir, FILE_NAME);
  fs.writeFileSync(srcFile, PAYLOAD);

  try {
    const page = await browser.newPage();
    // ⚠️ 无头 Chrome 默认**禁止下载** —— 必须用 CDP 显式允许
    const dlDir = path.join(OUT_DIR, 'sw-downloads');
    fs.rmSync(dlDir, { recursive: true, force: true });
    fs.mkdirSync(dlDir, { recursive: true });
    const bcdp = await browser.target().createCDPSession();
    await bcdp.send('Browser.setDownloadBehavior', {
      behavior: 'allow',
      downloadPath: dlDir,
      eventsEnabled: true,
    });
    await page.setCacheEnabled(false);
    page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
    page.on('console', (m) => { if (m.type() === 'error') errors.push('[console] ' + m.text()); });

    // ---------- 登录 ----------
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
    if (!tk) throw new Error('登录失败');

    // ---------- 打软件库页面 ----------
    await page.goto(BASE + '/software', { waitUntil: 'domcontentloaded' });
    await sleep(1800);
    check('E2 /software 页面能打开',
      await page.evaluate(() => !!document.querySelector('.cap-shell')),
      await page.evaluate(() => document.body.innerText.slice(0, 80)));
    check('E3 页头是「软件库」',
      await page.evaluate(() => (document.querySelector('.sh-name')?.textContent || '').includes('软件库')));
    await page.screenshot({ path: path.join(OUT_DIR, 'sw-1-list.png') });

    // ---------- 打开上传抽屉 ----------
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('上架软件'));
      if (btn) btn.click();
    });
    await page.waitForSelector('.sw-up-drawer input[type=file]', { timeout: 10000 });
    await sleep(600);
    check('E4 上传抽屉能打开', true);

    // ---------- 填表单 ----------
    const setValue = async (placeholder, value) => page.evaluate((ph, val) => {
      const els = [...document.querySelectorAll('.sw-up-drawer input, .sw-up-drawer textarea')];
      const el = els.find((e) => (e.placeholder || '').includes(ph));
      if (!el) return false;
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    }, placeholder, value);

    check('E5 填软件名', await setValue('展示名', 'E2E 演示软件'));
    check('E6 填软件标识', await setValue('唯一标识', CODE));
    check('E7 填版本号', await setValue('如 1.0.0', '1.0.0'));
    check('E8 填简介', await setValue('一句话说清', 'e2e 走查用的演示软件'));
    check('E9 填功能清单', await setValue('一行一条', '读取 SMART 日志\n定位失败扇区\n导出 CSV'));
    check('E10 填适用场景', await setValue('什么情况下该用它', '排查 SSD 掉盘问题时'));
    check('E11 填更新说明', await setValue('这次改了什么', '首个版本'));

    // ---------- 选文件 + 上传 ----------
    const fileInput = await page.$('.sw-up-drawer input[type=file]');
    await fileInput.uploadFile(srcFile);
    await sleep(400);
    check('E12 选中了软件包',
      await page.evaluate((c) => (document.querySelector('.file-chip')?.textContent || '').includes(c), CODE));

    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('.sw-up-drawer button, .up-foot button')]
        .find((b) => (b.textContent || '').includes('上架软件'));
      if (btn) btn.click();
    });
    // 传文件要一会儿 (走的是原始字节流 + 流式落盘)
    await page.waitForSelector('.asset-card', { timeout: 30000 });
    await sleep(1500);
    check('E13 上传后卡片出现',
      await page.evaluate((c) => [...document.querySelectorAll('.ac-name')].some((n) => n.textContent.includes('E2E 演示软件')), CODE));

    // ---------- 图标不许重复 (2026-10-28) ----------
    // 再开一次上架抽屉 → 图标下拉里, **刚才这条用掉的图标**应该
    //   ① 标着「已被「…」用了」; ② 是禁用的 (点不动).
    // ⚠️ 用的是自己上架时的那个图标, 而不是写死某个 ——
    //    库里可能已经有别的演示条目占着别的图标 (截图脚本留下的).
    const myIcon = await page.evaluate(() => {
      const t = localStorage.getItem('testmate:token');
      return fetch('/api/v1/software/config', { headers: { Authorization: 'Bearer ' + t } })
        .then((r) => r.json()).then((d) => {
          const u = (d.used_icons || {});
          const hit = Object.keys(u).find((k) => u[k] === 'E2E 演示软件');
          return hit || '';
        });
    });
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('button')]
        .find((b) => b.textContent.includes('上架软件'));
      if (btn) btn.click();
    });
    await page.waitForSelector('.sw-up-drawer .el-select__wrapper', { timeout: 10000 });
    await sleep(1200);
    await page.click('.sw-up-drawer .el-select__wrapper');
    await sleep(900);
    const iconState = await page.evaluate((ic) => {
      const opt = [...document.querySelectorAll('.el-select-dropdown__item')]
        .find((o) => (o.textContent || '').includes(ic) && (o.textContent || '').includes('已被'));
      return {
        label: opt ? opt.textContent.trim() : '',
        disabled: opt ? opt.classList.contains('is-disabled') : false,
      };
    }, myIcon);
    check('E13a 已用图标标出占用者', iconState.label.includes('E2E 演示软件'), `${myIcon} ${iconState.label}`);
    check('E13b 已用图标是禁用的', iconState.disabled === true, `disabled=${iconState.disabled}`);
    // 关掉抽屉 (点「取消」, 不用 Escape)
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('.sw-up-drawer button, .up-foot button')]
        .find((b) => (b.textContent || '').trim() === '取消');
      if (btn) btn.click();
    });
    await sleep(1200);

    // ---------- 详情抽屉 ----------
    await page.evaluate(() => {
      const card = [...document.querySelectorAll('.asset-card')]
        .find((c) => c.querySelector('.ac-name')?.textContent.includes('E2E 演示软件'));
      if (card) card.click();
    });
    await page.waitForSelector('.sw-drawer .sw-body', { timeout: 15000 });
    await sleep(900);

    const detail = await page.evaluate(() => {
      const d = document.querySelector('.sw-drawer');
      return {
        text: d ? d.innerText : '',
        features: [...d.querySelectorAll('.feature-list li')].map((x) => x.textContent.trim()),
        versions: [...d.querySelectorAll('.ver-row .vr-ver')].map((x) => x.textContent.trim()),
        notes: [...d.querySelectorAll('.vr-notes')].map((x) => x.textContent.trim()),
      };
    });
    check('E14 详情里有功能清单', detail.features.length === 3, detail.features.join(' | '));
    check('E15 详情里有适用场景', detail.text.includes('排查 SSD 掉盘问题时'));
    check('E16 详情里有发布与更新说明', detail.notes.some((n) => n.includes('首个版本')), detail.notes.join(' | '));
    check('E17 版本历史有 1 条', detail.versions.length === 1, detail.versions.join(' | '));
    await page.screenshot({ path: path.join(OUT_DIR, 'sw-2-detail.png') });

    // ---------- 下载 ----------
    const apiSha = await page.evaluate(async (c) => {
      const t = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/software/' + c, { headers: { Authorization: 'Bearer ' + t } });
      const d = await r.json();
      const v = (d.versions || []).find((x) => x.status === 'ready');
      return v ? v.sha256 : '';
    }, CODE);
    check('E18 后端记录了文件的 sha256', !!apiSha, apiSha);

    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('.sw-drawer button')]
        .find((b) => (b.textContent || '').includes('下载'));
      if (btn) btn.click();
    });
    // 等文件落到下载目录
    let dlFile = '';
    for (let i = 0; i < 60; i++) {
      await sleep(500);
      const files = fs.existsSync(dlDir) ? fs.readdirSync(dlDir).filter((f) => !f.endsWith('.crdownload')) : [];
      if (files.length) { dlFile = path.join(dlDir, files[0]); break; }
    }
    check('E19 下载的文件落到了磁盘', !!dlFile, dlFile);
    if (dlFile) {
      const got = crypto.createHash('sha256').update(fs.readFileSync(dlFile)).digest('hex');
      check('E20 下载内容与源文件一致 (sha256)', got === PAYLOAD_SHA && got === apiSha,
        `本地 ${got} / 后端 ${apiSha}`);
    }

    // ---------- 发新版本 ----------
    // ⚠️ 2026-10-28: 两个要点.
    //    ① 新版本要用**内容不同**的文件, 并断言新版本记的 sha256 是新内容的 ——
    //       否则"用户选了新文件、实际传的还是旧文件"这种错位抓不到.
    //    ② 更新说明必须是**空的** —— 打开发新版本抽屉时不能带上上一版的说明.
    //       (以前抽屉里的草稿不清, 上一版的说明会直接躺在新版本的输入框里.)
    const PAYLOAD2 = Buffer.concat([PAYLOAD, Buffer.from('\n-- v2 增加了 CSV 导出 --\n')]);
    const PAYLOAD2_SHA = crypto.createHash('sha256').update(PAYLOAD2).digest('hex');
    const srcFile2 = path.join(tmpDir, `${CODE}-v2.bin`);
    fs.writeFileSync(srcFile2, PAYLOAD2);

    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('.sw-drawer button')]
        .find((b) => (b.textContent || '').includes('发布新版本'));
      if (btn) btn.click();
    });
    await page.waitForSelector('.sw-up-drawer input[type=file]', { timeout: 10000 });
    await sleep(600);

    check('E20a 发新版本时「更新说明」是空的 (不带上版的)',
      await page.evaluate(() => {
        const ta = [...document.querySelectorAll('.sw-up-drawer textarea')]
          .find((t) => (t.placeholder || '').includes('这次改了什么'));
        return !!ta && ta.value.trim() === '';
      }),
      await page.evaluate(() => {
        const ta = [...document.querySelectorAll('.sw-up-drawer textarea')]
          .find((t) => (t.placeholder || '').includes('这次改了什么'));
        return ta ? JSON.stringify(ta.value) : '(找不到输入框)';
      }));

    await setValue('这次改了什么', '第二个版本: 加了 CSV 导出');
    const fileInput2 = await page.$('.sw-up-drawer input[type=file]');
    await fileInput2.uploadFile(srcFile2);
    await sleep(400);
    check('E21a 发新版本时抽屉里选中了文件',
      await page.evaluate((c) => {
        const chip = document.querySelector('.file-chip')?.textContent || '';
        return chip.includes(c) && !chip.includes('未选择文件');
      }, CODE),
      await page.evaluate(() => document.querySelector('.file-chip')?.textContent?.trim() || ''));
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('.sw-up-drawer button, .up-foot button')]
        .find((b) => (b.textContent || '').includes('发布新版本'));
      if (btn) btn.click();
    });
    // 等抽屉刷新 (发完新版本后详情抽屉要自动重读 —— 否则用户看到的是旧的版本历史)
    await sleep(4000);

    // 新版本记的 sha256 必须是**新内容**的, 不能是旧文件的
    const v2Sha = await page.evaluate(async (c) => {
      const t = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/software/' + c, { headers: { Authorization: 'Bearer ' + t } });
      const d = await r.json();
      const v = (d.versions || []).find((x) => x.version === '1.0.1');
      return v ? v.sha256 : '';
    }, CODE);
    check('E21b 新版本记录的 sha256 是新内容的 (不是旧文件的)',
      v2Sha === PAYLOAD2_SHA && v2Sha !== PAYLOAD_SHA,
      `新 ${v2Sha.slice(0, 12)} / 旧 ${PAYLOAD_SHA.slice(0, 12)}`);

    const after = await page.evaluate(() => {
      const d = document.querySelector('.sw-drawer');
      if (!d) return { versions: [], notes: [] };
      return {
        versions: [...d.querySelectorAll('.ver-row .vr-ver')].map((x) => x.textContent.trim()),
        notes: [...d.querySelectorAll('.vr-notes')].map((x) => x.textContent.trim()),
      };
    });
    check('E21 发新版本后版本历史多一条', after.versions.length === 2, after.versions.join(' | '));
    check('E22 新版本的更新说明在列表里', after.notes.some((n) => n.includes('第二个版本')), after.notes.join(' | '));
    await page.screenshot({ path: path.join(OUT_DIR, 'sw-3-versions.png') });

    // 旧版本仍然能下 (版本历史里每一行都有下载按钮)
    const oldDl = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.ver-row')];
      const old = rows.find((r) => r.querySelector('.vr-ver')?.textContent.trim() === '1.0.0');
      const btn = old ? [...old.querySelectorAll('button')].find((b) => (b.textContent || '').includes('下载')) : null;
      return !!btn;
    });
    check('E23 旧版本仍然有下载按钮', oldDl);

    // ---------- 收尾: 彻底清理 (记录 + 磁盘文件) ----------
    // ⚠️ 清理之后会故意再读一次详情 (预期 404) —— 那一下的报错不算"JS 错误",
    //    所以先记下此时的错误数, E26 只看清理**之前**有没有出错.
    const errorsBeforeCleanup = errors.length;
    const cleaned = await page.evaluate(async (c) => {
      const t = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/software/' + c + '/purge', {
        method: 'DELETE', headers: { Authorization: 'Bearer ' + t },
      });
      return r.status;
    }, CODE);
    check('E24 彻底清理成功', cleaned === 200, 'HTTP ' + cleaned);

    const gone = await page.evaluate(async (c) => {
      const t = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/software/' + c, { headers: { Authorization: 'Bearer ' + t } });
      return r.status;
    }, CODE);
    check('E25 清理后详情接口返回 404', gone === 404, 'HTTP ' + gone);

    check('E26 全程无 JS 错误', errorsBeforeCleanup === 0, errors.slice(0, 3).join(' | '));
  } catch (e) {
    check('脚本执行', false, String(e && e.stack || e));
  } finally {
    try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (e) { /* ignore */ }
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n=== 软件库 e2e: ${results.length - failed.length}/${results.length} 通过 ===`);
  if (failed.length) {
    console.log('失败项:');
    failed.forEach((f) => console.log(`  ✗ ${f.name} ${f.detail || ''}`));
    process.exit(1);
  }
})();
