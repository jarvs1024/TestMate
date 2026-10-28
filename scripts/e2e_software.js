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
    // ⚠️ 软件标识 2026-10-28 起是**自动生成**的 (由文件名派生, 只读) —— 不能手填.
    //    这里断言它是只读的自动字段 (选完文件后才有值, 见 E12b).
    const autoCode = await page.evaluate(() => {
      const el = [...document.querySelectorAll('.sw-up-drawer input')]
        .find((e) => (e.placeholder || '').includes('自动生成'));
      return el
        ? { found: true, readonly: !!el.readOnly, value: (el.value || '').trim() }
        : { found: false };
    });
    check('E6 软件标识是自动生成的 (只读, 不用手填)',
      autoCode.found && autoCode.readonly === true, JSON.stringify(autoCode));
    check('E7 填版本号', await setValue('如 1.0.0', '1.0.0'));
    check('E8 填简介', await setValue('一句话说清', 'e2e 走查用的演示软件'));
    check('E9 填功能清单', await setValue('一行一条', '读取 SMART 日志\n定位失败扇区\n导出 CSV'));
    check('E10 填适用场景', await setValue('什么情况下该用它', '排查 SSD 掉盘问题时'));
    check('E11 填更新说明', await setValue('这次改了什么', '首个版本'));
    // ⚠️ 选填栏: 安装说明 / 注意事项 / 版本变体标签 (2026-10-28)
    check('E11a 填安装说明', await setValue('怎么装', '解压到 /opt/tool\n运行 install.sh'));
    check('E11b 填注意事项', await setValue('有什么坑', '需要管理员权限, 会往系统目录写配置'));
    check('E11c 填版本变体标签', await setValue('如 Windows版', '通用版'));

    // ---------- 选文件 + 上传 ----------
    const fileInput = await page.$('.sw-up-drawer input[type=file]');
    await fileInput.uploadFile(srcFile);
    await sleep(400);
    check('E12 选中了软件包',
      await page.evaluate((c) => (document.querySelector('.file-chip')?.textContent || '').includes(c), CODE));
    // ⚠️ 选完文件 → 标识**自动派生**出来 (由文件名去扩展名转小写)
    check('E12b 选完文件后标识自动生成',
      await page.evaluate((c) => {
        const el = [...document.querySelectorAll('.sw-up-drawer input')]
          .find((e) => (e.placeholder || '').includes('自动生成'));
        return !!el && (el.value || '').trim() === c;
      }, CODE), CODE);

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
        variants: [...d.querySelectorAll('.ver-row .vr-variant')].map((x) => x.textContent.trim()),
      };
    });
    check('E14 详情里有功能清单', detail.features.length === 3, detail.features.join(' | '));
    check('E15 详情里有适用场景', detail.text.includes('排查 SSD 掉盘问题时'));
    check('E16 详情里有发布与更新说明', detail.notes.some((n) => n.includes('首个版本')), detail.notes.join(' | '));
    check('E17 版本历史有 1 条', detail.versions.length === 1, detail.versions.join(' | '));
    // ⚠️ 选填栏在详情里要真的显示出来 (2026-10-28)
    check('E17a 详情里有安装说明', detail.text.includes('解压到 /opt/tool'), detail.text.slice(0, 120));
    check('E17b 详情里有注意事项', detail.text.includes('需要管理员权限'));
    check('E17c 详情里有版本变体标签', detail.variants.includes('通用版'), detail.variants.join(' | '));
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

    // ---------- 多版本: 变体标签 / 推荐版本 / 单版本下架 (2026-10-28) ----------
    // 场景: 一个软件挂两个版本、**两个都有用** —— 一个是「LTS版」还在给老环境用,
    // 一个是新版. 这时要能: ① 看得出谁是谁; ② 指定该下哪个; ③ 单独撤掉一个.
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('.sw-drawer button')]
        .find((b) => (b.textContent || '').includes('发布新版本'));
      if (btn) btn.click();
    });
    await page.waitForSelector('.sw-up-drawer input[type=file]', { timeout: 10000 });
    await sleep(800);
    // 版本号改成 2.0.0 (自增建议是 1.0.1), 变体标签填「LTS版」, 并且**不抢推荐位**
    check('E23a 版本号可自定义 (不限于自增建议)',
      await setValue('如 1.1.0', '2.0.0'));
    check('E23b 发新版本可填变体标签',
      await setValue('如 Windows版', 'LTS版'));
    // ⚠️ el-checkbox 的可点区域是它自己的 label, 点 input 未必触发 —— 直接点 label
    const noTake = await page.evaluate(() => {
      const cb = [...document.querySelectorAll('.sw-up-drawer .el-checkbox')]
        .find((c) => (c.textContent || '').includes('默认下载的那个'));
      if (!cb) return null;
      const input = cb.querySelector('input');
      const was = input ? input.checked : null;
      if (input && input.checked) {
        // 点 label 里的文字区域 —— Element Plus 把 input 藏起来了
        const label = cb.querySelector('.el-checkbox__label') || cb;
        label.click();
      }
      return was;
    });
    check('E23c 推荐位默认勾上 (可以手动取消)', noTake === true, `checkbox=${noTake}`);

    const fileInput3 = await page.$('.sw-up-drawer input[type=file]');
    await fileInput3.uploadFile(srcFile2);
    await sleep(400);
    await setValue('这次改了什么', 'LTS 分支: 继续支持老环境');
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll('.sw-up-drawer button, .up-foot button')]
        .find((b) => (b.textContent || '').includes('发布新版本'));
      if (btn) btn.click();
    });
    await sleep(4000);

    const multi = await page.evaluate(async (c) => {
      const t = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/software/' + c, { headers: { Authorization: 'Bearer ' + t } });
      const d = await r.json();
      const dom = document.querySelector('.sw-drawer');
      return {
        apiVersions: (d.versions || []).map((v) => ({
          version: v.version, variant: v.variant, is_default: v.is_default, status: v.status,
        })),
        download_version: d.download_version,
        domVariants: dom ? [...dom.querySelectorAll('.ver-row .vr-variant')].map((x) => x.textContent.trim()) : [],
        domDefaults: dom ? dom.querySelectorAll('.ver-row .vr-default').length : 0,
        domText: dom ? dom.innerText : '',
      };
    }, CODE);
    // ⚠️ 前面已经发过 1.0.1, 这里再发 2.0.0 → 共 3 个版本并存
    check('E24a 多个版本并存 (都有用)', multi.apiVersions.length === 3,
      JSON.stringify(multi.apiVersions));
    check('E24b 两个版本都能下载 (status 都是 ready)',
      multi.apiVersions.every((v) => v.status === 'ready'),
      JSON.stringify(multi.apiVersions.map((v) => `${v.version}:${v.status}`)));
    check('E24c 变体标签存住了',
      multi.apiVersions.some((v) => v.variant === 'LTS版') && multi.apiVersions.some((v) => v.variant === '通用版'),
      JSON.stringify(multi.apiVersions.map((v) => `${v.version}=${v.variant}`)));
    check('E24d 详情里两个变体标签都显示', multi.domVariants.length === 2, multi.domVariants.join(' | '));
    check('E24e 不抢推荐位时, 推荐还是原来那个',
      multi.download_version === '1.0.1',
      `download_version=${multi.download_version}`);
    check('E24e2 三个版本里只有一个是推荐',
      multi.apiVersions.filter((v) => v.is_default).length === 1,
      JSON.stringify(multi.apiVersions.filter((v) => v.is_default)));
    await page.screenshot({ path: path.join(OUT_DIR, 'sw-4-multi-version.png') });

    // 把 2.0.0 设成推荐 → 下载目标切过去
    await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.ver-row')];
      const row = rows.find((r) => r.querySelector('.vr-ver')?.textContent.trim() === '2.0.0');
      const btn = row ? [...row.querySelectorAll('button')].find((b) => (b.textContent || '').includes('设为推荐')) : null;
      if (btn) btn.click();
    });
    await sleep(2500);
    const afterDefault = await page.evaluate(async (c) => {
      const t = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/software/' + c, { headers: { Authorization: 'Bearer ' + t } });
      const d = await r.json();
      return {
        download_version: d.download_version,
        defaults: (d.versions || []).filter((v) => v.is_default).map((v) => v.version),
      };
    }, CODE);
    check('E24f 手动设推荐后, 下载目标切过去',
      afterDefault.download_version === '2.0.0',
      `download_version=${afterDefault.download_version}`);
    check('E24g 推荐版本只有一个', afterDefault.defaults.length === 1, afterDefault.defaults.join(' | '));

    // 单版本下架: 只删 2.0.0, 1.0.0 / 1.0.1 照旧
    const delRes = await page.evaluate(async (c) => {
      const t = localStorage.getItem('testmate:token');
      const r = await fetch(`/api/v1/software/${c}/versions/2.0.0`, {
        method: 'DELETE', headers: { Authorization: 'Bearer ' + t },
      });
      return r.status;
    }, CODE);
    check('E24h 单版本下架成功', delRes === 200, 'HTTP ' + delRes);
    const afterDel = await page.evaluate(async (c) => {
      const t = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/software/' + c, { headers: { Authorization: 'Bearer ' + t } });
      const d = await r.json();
      return {
        versions: (d.versions || []).map((v) => v.version),
        publish_status: d.publish_status,
      };
    }, CODE);
    check('E24i 下架一个版本后, 其他版本还在',
      afterDel.versions.length === 2 && !afterDel.versions.includes('2.0.0'),
      afterDel.versions.join(' | '));
    check('E24j 下架一个版本后, 条目仍然是上架状态',
      afterDel.publish_status === 'published', afterDel.publish_status);

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
