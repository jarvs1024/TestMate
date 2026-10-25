#!/usr/bin/env node
/**
 * 资产市场的**异常与边界**端到端验收 (真实 Chrome).
 *
 * 正常路径由 e2e_market.js 覆盖; 这里专挑"容易出事"的地方:
 *   ① 包名不合规 → 体检要说不装不上, 且不让上架
 *   ② code 与包名不一致 → 报错 + 不让上架
 *   ③ MCP 配置非法 / 连接器名不合法 → 实时报错 + 不让上架
 *   ④ 项目筛选到空结果 → 空态正常, 不崩
 *   ⑤ 未登录/无权访问详情 → 拦住
 *   ⑥ 分类 chip 的计数与实际条数对得上
 *
 * 用法: NODE_PATH=/tmp/tm-e2e/node_modules node scripts/e2e_market_edge.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
require('./e2e_lock').acquire(__filename);

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const API = process.env.TESTMATE_API || 'http://localhost:18000';
const ADMIN = process.env.TESTMATE_USER || 'admin';
const ADMIN_PW = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}

async function api(pathname, opts = {}) {
  const r = await fetch(API + pathname, opts);
  const t = await r.text();
  try { return { status: r.status, json: JSON.parse(t) }; } catch { return { status: r.status, json: null }; }
}

/** 造一个 zip */
function makeZip(target, files) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  execFileSync('python3', ['-c', [
    'import zipfile',
    `z=zipfile.ZipFile(${JSON.stringify(target)},'w')`,
    ...files.map(([n, c]) => `z.writestr(${JSON.stringify(n)},${JSON.stringify(c)})`),
    'z.close()',
  ].join(';')]);
  execFileSync('python3', ['-c', [
    'import zipfile',
    `z=zipfile.ZipFile(${JSON.stringify(target)},'a')`,
    'z.close()',
  ].join(';')]);
}

/** 在抽屉里填字段 */
async function fillDrawer(page, values) {
  await page.evaluate((vals) => {
    const set = (el, val) => {
      if (!el) return;
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    };
    const inputs = [...document.querySelectorAll('.up-drawer input[type=text]')];
    for (const [ph, val] of Object.entries(vals)) {
      const el = inputs.find((i) => (i.placeholder || '').includes(ph));
      set(el, val);
    }
  }, values);
  await sleep(400);
}

/** 抽屉底部状态 */
async function drawerState(page) {
  return page.evaluate(() => {
    const d = document.querySelector('.up-drawer');
    if (!d) return null;
    return {
      // ⚠️ 要读 code 字段自己的错误 —— 抽屉里第一个 .el-form-item__error 是包区的
      err: (d.querySelector('.code-item .el-form-item__error')?.textContent || '').trim(),
      pkgErr: (d.querySelector('.el-form-item__error')?.textContent || '').trim(),
      foot: (d.querySelector('.foot-bar')?.textContent || '').replace(/\s+/g, ' ').trim(),
      pv: (d.querySelector('.pv-box')?.textContent || '').replace(/\s+/g, ' ').trim(),
      mcpMsg: (d.querySelector('.mcp-msg')?.textContent || '').replace(/\s+/g, ' ').trim(),
      disabled: !!d.querySelector(
        '.el-drawer__footer .el-button--primary.is-disabled, .el-drawer__footer .el-button--primary[disabled]'),
    };
  });
}

/** 打开上传抽屉 (选形态) */
async function openUpload(page, kindLabel) {
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.mini-btn.primary')].find((x) => x.textContent.includes('上传资产'));
    b && b.click();
  });
  await sleep(600);
  await page.evaluate((label) => {
    const el = [...document.querySelectorAll('.pick-item')].find((x) => x.textContent.includes(label));
    el && el.click();
  }, kindLabel);
  await sleep(800);
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const tk = (await api('/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
  })).json.access_token || '';

  const browser = await puppeteer.launch({
    executablePath: CHROME, headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1440, height: 900 },
  });
  const page = await browser.newPage();
  await page.setCacheEnabled(false);
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => {
    localStorage.setItem('testmate:token', t);
    localStorage.setItem('testmate:user', JSON.stringify({ id: 1, username: 'admin', role: 'admin' }));
  }, tk);
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1500);

  // ================= ① 包名不合规 → 体检不通过 + 不让上架 =================
  const badNameZip = path.join(OUT_DIR, 'weekly-report.zip');
  makeZip(badNameZip, [['SKILL.md', '---\nname: x\ndescription: d\n---\n\n# x\n']]);
  await openUpload(page, '技能');
  const fileInput = await page.$('.up-drawer .file-input');
  await fileInput.uploadFile(badNameZip);
  await sleep(2500);
  let st = await drawerState(page);
  check('E1 包名不合规 → 体检不通过', /装不上/.test(st.pv || ''), st.pv.slice(0, 90));
  check('E2 体检结论点名包名问题', /dml-/.test(st.pv || ''), st.pv.slice(0, 120));
  check('E3 包名不合规 → 不让上架', st.disabled === true, `disabled=${st.disabled}`);

  // ================= ② 资产 code 是**只读派生值**, 跟着包名自动变 =================
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer__footer .el-button')]
      .find((x) => x.textContent.includes('取消'));
    b && b.click();
  });
  await sleep(600);
  const goodZip = path.join(OUT_DIR, 'dml-weekly-report.zip');
  makeZip(goodZip, [['SKILL.md', '---\nname: x\ndescription: d\n---\n\n# x\n']]);
  await openUpload(page, '技能');
  const fileInput2 = await page.$('.up-drawer .file-input');
  await fileInput2.uploadFile(goodZip);
  await sleep(2500);
  let codeState = await page.evaluate(() => {
    const d = document.querySelector('.up-drawer');
    const v = d.querySelector('.pkg-req .pr-code');
    return {
      text: (v?.textContent || '').replace(/\s+/g, ' ').trim(),
      hasInput: !!d.querySelector('input[placeholder*="dml-"]'),
    };
  });
  check('E4 资产 code 只做展示, 没有输入框',
    codeState.hasInput === false && /dml-weekly-report/.test(codeState.text),
    codeState.text.slice(0, 70));
  check('E5 code 自动跟包名一致', /dml-weekly-report/.test(codeState.text), codeState.text.slice(0, 70));

  // 换包 → code 跟着变 (而不是让用户去改一个派生值)
  const otherZip = path.join(OUT_DIR, 'dml-other-report.zip');
  makeZip(otherZip, [['SKILL.md', '---\nname: y\ndescription: d\n---\n\n# y\n']]);
  const fileInput3 = await page.$('.up-drawer .file-input');
  await fileInput3.uploadFile(otherZip);
  await sleep(2500);
  codeState = await page.evaluate(() => {
    const v = document.querySelector('.up-drawer .pkg-req .pr-code');
    return (v?.textContent || '').replace(/\s+/g, ' ').trim();
  });
  check('E6 换包后 code 自动跟着变',
    /dml-other-report/.test(codeState) && !/dml-weekly-report/.test(codeState),
    codeState.slice(0, 70));
  await page.screenshot({ path: path.join(OUT_DIR, 'edge-01-code-readonly.png') });

  // 取消, 退出抽屉
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer__footer .el-button')].find((x) => x.textContent.includes('取消'));
    b && b.click();
  });
  await sleep(800);

  // ================= ③ MCP 配置异常 =================
  await openUpload(page, '连接器');
  // 非法 JSON
  await page.evaluate(() => {
    const ta = document.querySelector('.up-drawer .mcp-json textarea');
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(ta, '{ 这不是 JSON');
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(900);
  st = await drawerState(page);
  check('E8 MCP 配置非法 JSON → 实时报错', /JSON/.test(st.mcpMsg || ''), st.mcpMsg.slice(0, 90));
  check('E9 MCP 配置非法 → 不让上架', st.disabled === true, `disabled=${st.disabled}`);

  // 连接器名不以 dml- 开头
  await page.evaluate(() => {
    const ta = document.querySelector('.up-drawer .mcp-json textarea');
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(ta, '{"mcpServers": {"xx-xxx": {"url": "http://host:5050/mcp"}}}');
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(900);
  st = await drawerState(page);
  check('E10 连接器名不以 dml- 开头 → 实时报错', /dml-/.test(st.mcpMsg || ''), st.mcpMsg.slice(0, 100));
  check('E11 连接器名不合法 → 不让上架', st.disabled === true, `disabled=${st.disabled}`);
  await page.screenshot({ path: path.join(OUT_DIR, 'edge-02-bad-mcp.png') });

  // 合法配置 → 错误消失
  await page.evaluate(() => {
    const ta = document.querySelector('.up-drawer .mcp-json textarea');
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(ta, '{"mcpServers": {"dml-good-conn": {"url": "http://host:5050/mcp"}}}');
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(900);
  st = await drawerState(page);
  check('E12 改成合法连接器名 → 错误消失', /✓ 配置合法/.test(st.mcpMsg || ''), st.mcpMsg.slice(0, 60));
  // code 应自动同步成连接器名 (只读展示区)
  const syncedCode = await page.evaluate(() => {
    const v = document.querySelector('.up-drawer .pkg-req .pr-code');
    return (v?.textContent || '').replace(/\s+/g, ' ').trim();
  });
  check('E13 code 自动同步成连接器名 (只读展示)',
    /dml-good-conn/.test(syncedCode), `code=${syncedCode.slice(0, 60)}`);

  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer__footer .el-button')].find((x) => x.textContent.includes('取消'));
    b && b.click();
  });
  await sleep(800);

  // ================= ④ 项目筛选到空结果 =================
  // ⚠️ 2026-10-25: 项目筛选从 chip 收进了**下拉菜单** (跟排序合并) —— 定位方式跟着改
  // ⚠️ 选「通用」而不是某个具体项目号 —— 项目列表是**配置**
  //    (设置项 marketplace.projects), 生产上未必有某个号, 写死会误判.
  await page.evaluate(() => {
    document.querySelector('.filter-trigger')?.click();
  });
  await sleep(600);
  const pickedGeneral = await page.evaluate(() => {
    const it = [...document.querySelectorAll('.filter-panel .fp-item')]
      .find((x) => x.textContent.includes('通用'));
    if (!it) return false;
    it.click();
    return true;
  });
  await sleep(1800);
  //    ⚠️ 语义: 选某项目 = 该项目特有 **+ 通用** —— 所以通用资产仍然显示是**对的**
  const emptyState = await page.evaluate(() => ({
    cards: document.querySelectorAll('.asset-card').length,
    state: (document.querySelector('.market .state')?.textContent || '').trim(),
    allGeneral: [...document.querySelectorAll('.asset-card .ac-badge.proj')].length === 0,
  }));
  check('E14 项目筛选 → 只剩通用资产, 页面不报错',
    pickedGeneral && emptyState.allGeneral && !/失败|错误/.test(emptyState.state || ''),
    `cards=${emptyState.cards} state=${emptyState.state || '(空)'}`);

  // 切回全部
  await page.evaluate(() => {
    document.querySelector('.filter-trigger')?.click();
  });
  await sleep(600);
  await page.evaluate(() => {
    const it = [...document.querySelectorAll('.filter-panel .fp-item')]
      .find((x) => x.textContent.includes('全部项目'));
    it && it.click();
  });
  await sleep(1500);

  // ================= ④b 更新**存量无前缀**资产 (回归: 曾被前端误判, 永远更新不了) =================
  //   存量资产的 code 不带 dml- 前缀 (如 ssd-log-doctor), 它的"包名必须 dml- 开头"
  //   这条规则只在**新建**时适用 —— 更新时若还要求前缀, 那批资产就永远更新不了.
  const legacyCode = 'legacy-demo';
  const LEGACY_NAME = '存量无前缀资产';
  const legacyZip = path.join(OUT_DIR, `${legacyCode}.zip`);
  makeZip(legacyZip, [['SKILL.md', '---\nname: legacy\ndescription: d\n---\n\n# legacy\n']]);
  {
    // ⚠️ 先清一次 —— 上次跑崩了会留下同名资产, 这次上传就 409 了 (用例要幂等)
    await api(`/api/v1/assets/${legacyCode}`, {
      method: 'DELETE', headers: { Authorization: 'Bearer ' + tk },
    });
    const fd = new FormData();
    fd.append('code', legacyCode);
    fd.append('kind', 'skill');
    fd.append('name', LEGACY_NAME);
    fd.append('summary', '回归用: code 不带 dml- 前缀的存量资产');
    fd.append('version', '1.0.0');
    fd.append('category', '其他');
    fd.append('icon', '🧩');
    fd.append('tags', '[]');
    fd.append('keywords', '[]');
    fd.append('permissions', '{}');
    fd.append('install_steps', '[]');
    fd.append('bindings', '{}');
    fd.append('package', new Blob([fs.readFileSync(legacyZip)]), `${legacyCode}.zip`);
    const up = await api('/api/v1/assets/upload', {
      method: 'POST', headers: { Authorization: 'Bearer ' + tk }, body: fd,
    });
    check('E17 造一个无前缀的存量资产', up.status === 202, `status=${up.status}`);
  }
  // 等它落库并推上 GitLab
  for (let i = 0; i < 20; i++) {
    await sleep(700);
    const st = await api(`/api/v1/assets/${legacyCode}`, { headers: { Authorization: 'Bearer ' + tk } });
    if (st.status === 200) break;
  }

  // 在市场页找到它 → 发布新版本
  // ⚠️ 必须**刷新** —— 资产是刚上传的, 页面上的列表还是旧的
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1500);
  await page.evaluate(() => {
    const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
    t && t.click();
  });
  await sleep(1600);
  const opened = await page.evaluate((name) => {
    // ⚠️ 卡片上显示的是**名称**, 不是 code —— 按 code 找永远找不到
    const c = [...document.querySelectorAll('.asset-card')].find((x) => x.textContent.includes(name));
    if (!c) return false;
    c.click();
    return true;
  }, LEGACY_NAME);
  check('E18 市场页能找到这个存量资产', opened);
  await page.waitForSelector('.el-drawer', { timeout: 10000 });
  await sleep(1200);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.ad-actions .el-button')]
      .find((x) => x.textContent.includes('发布新版本'));
    b && b.click();
  });
  await sleep(1800);
  const inUpdate = await page.evaluate(() => {
    const d = document.querySelector('.up-drawer');
    if (!d) return { open: false, title: '' };
    const title = (document.querySelector('.el-drawer__title')?.textContent || '').trim();
    return { open: true, title };
  });
  check('E19 能进入「发布新版本」的抽屉',
    inUpdate.open && /更新资产/.test(inUpdate.title || ''),
    `title=${inUpdate.title || '(无)'}`);

  // 上传同名包 → **不该**报"包名必须以 dml- 开头"
  const legacyInput = await page.$('.up-drawer .file-input');
  if (!legacyInput) {
    check('E20 更新存量资产: 同名包不被误判为"缺 dml- 前缀"', false, '找不到包选择框 (抽屉没打开)');
  } else {
    await legacyInput.uploadFile(legacyZip);
    await sleep(2500);
    const legacyState = await drawerState(page);
    check('E20 更新存量资产: 同名包不被误判为"缺 dml- 前缀"',
      !/dml-/.test(legacyState.pkgErr || ''), legacyState.pkgErr || '(无包名错误)');
    check('E21 更新存量资产: 缺项清单里没有「安装包名」',
      !/安装包名/.test(legacyState.foot || ''), legacyState.foot.slice(0, 90));
  }
  await page.screenshot({ path: path.join(OUT_DIR, 'edge-03-legacy-update.png') });

  // 收尾: 关抽屉 + 删掉这个临时资产
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer__footer .el-button')].find((x) => x.textContent.includes('取消'));
    b && b.click();
  });
  await sleep(800);
  {
    const del = await api(`/api/v1/assets/${legacyCode}`, {
      method: 'DELETE', headers: { Authorization: 'Bearer ' + tk },
    });
    check('E22 清理临时存量资产', del.status === 200, `status=${del.status}`);
  }

  // ================= ⑤ 分类 chip 计数与实际条数对得上 =================
  await page.evaluate(() => {
    const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('技能'));
    t && t.click();
  });
  await sleep(1600);
  const chipVsActual = await page.evaluate(() => {
    const chip = [...document.querySelectorAll('.cat-chips .chip')]
      .find((c) => /\d/.test(c.textContent) && !c.textContent.includes('全部'));
    const count = chip ? Number((chip.textContent.match(/\d+/) || [0])[0]) : -1;
    // 点这个分类, 看实际有多少张
    if (chip) chip.click();
    return { count };
  });
  await sleep(1600);
  const actual = await page.evaluate(() => document.querySelectorAll('.asset-card').length);
  check('E15 分类 chip 计数 = 该分类实际条数', chipVsActual.count === actual,
    `chip=${chipVsActual.count} actual=${actual}`);

  // ================= ⑥ 未登录 / 无权访问详情 =================
  const anon = await browser.createBrowserContext();
  const anonPage = await anon.newPage();
  await anonPage.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await sleep(1200);
  const anonState = await anonPage.evaluate(async () => {
    const r = await fetch('/api/v1/assets/definitely-not-exists', {
      headers: localStorage.getItem('testmate:token') ? { Authorization: 'Bearer ' + localStorage.getItem('testmate:token') } : {},
    });
    return r.status;
  });
  check('E16 未登录访问不存在的资产 → 401', anonState === 401, `status=${anonState}`);

  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error('FATAL', e); process.exit(2); });
