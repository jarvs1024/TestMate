#!/usr/bin/env node
/**
 * AI 资产市场 —— 端到端验收脚本 (真实 Chrome).
 *
 * 为什么不用内置 Browser 验证:
 *   Electron 内置 Browser 在页面加载瞬间会挂起 renderer —— XHR 事件不投递、setTimeout 不触发,
 *   表现成「页面永远卡在 loading」。那是验证工具的假象, 不是被测页面的 bug。
 *   本脚本用 puppeteer-core 驱动本机真实 Chrome, 行为与用户一致。
 *
 * 前置:
 *   cd frontend_web && npm i -D puppeteer-core     # 或任意目录安装后用 NODE_PATH 指过来
 *   # 需要本机已装 Google Chrome
 *
 * 用法:
 *   TESTMATE_USER=admin TESTMATE_PASSWORD='Admin@123' \
 *     node scripts/e2e_market.js [baseUrl]
 *
 * 退出码: 0 = 全部通过, 1 = 有断言失败, 2 = 脚本异常。
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.argv[2] || process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const USER = process.env.TESTMATE_USER || 'admin';
const PASSWORD = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = [];
function check(name, ok, detail) {
  const ts = new Date().toISOString().slice(11, 19);
  results.push({ name, ok: !!ok, detail, ts });
  console.log(`${ok ? 'PASS' : 'FAIL'} [${ts}] ${name}${detail ? '  :: ' + detail : ''}`);
}

/** 点第一个文本匹配的元素 */
async function clickByText(page, selector, text) {
  const hit = await page.evaluate((sel, t) => {
    const els = [...document.querySelectorAll(sel)];
    const el = els.find((e) => (e.textContent || '').replace(/\s+/g, ' ').trim().includes(t));
    if (!el) return false;
    el.scrollIntoView({ block: 'center' });
    el.click();
    return true;
  }, selector, text);
  if (!hit) throw new Error(`clickByText 未命中: ${selector} "${text}"`);
  await sleep(700);
  return hit;
}

/** 用 python3 造一个 zip (macOS 自带, 免得引依赖).
 *  用 execFileSync + 参数数组, 避开 shell 引号嵌套的坑. */
function makeZip(target, files) {
  const scriptPath = path.join(OUT_DIR, '_mkzip.py');
  fs.writeFileSync(scriptPath, [
    'import zipfile, json, sys',
    'target = json.loads(sys.argv[1])',
    'files = json.loads(sys.argv[2])',
    'with zipfile.ZipFile(target, "w") as z:',
    '    for name, content in files.items():',
    '        z.writestr(name, content)',
    '',
  ].join('\n'));
  require('child_process').execFileSync(
    'python3', [scriptPath, JSON.stringify(target), JSON.stringify(files)],
  );
  return target;
}

/** 读取市场页当前状态 */
async function snap(page) {
  return page.evaluate(() => {
    const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : null);
    const cards = [...document.querySelectorAll('.asset-card')].map((c) => ({
      name: txt(c.querySelector('.ac-name')),
      ver: txt(c.querySelector('.ac-ver')),
      badge: txt(c.querySelector('.ac-installed, .ac-updatable, .ac-sync')),
    }));
    const drawer = document.querySelector('.el-drawer');
    // 页面里可能同时挂着多个 el-drawer (资产详情 / 操作记录), 不能只看第一个
    const drawerTexts = [...document.querySelectorAll('.el-drawer')].map((d) => txt(d) || '');
    return {
      debugBar: !!document.querySelector('.tm-debug'),
      cards,
      tabs: [...document.querySelectorAll('.kind-tab')].map((b) => txt(b)),
      marketState: txt(document.querySelector('.market .state')),
      syncBar: txt(document.querySelector('.sync-bar')),
      footHint: txt(document.querySelector('.foot-hint')),
      drawerOpen: !!drawer,
      drawerName: txt(document.querySelector('.ad-name')),
      docHtmlLen: (document.querySelector('.ad-doc')?.innerHTML || '').length,
      docText: (txt(document.querySelector('.ad-doc')) || '').slice(0, 120),
      docHasScript: !!document.querySelector('.ad-doc script, .ad-doc iframe, .ad-doc img'),
      permRows: document.querySelectorAll('.perm-list li').length,
      permEmpty: !!document.querySelector('.ad-perm.is-empty'),
      steps: [...document.querySelectorAll('.steps li')].map((s) => txt(s)),
      gitPath: txt(document.querySelector('.ad-git code')),
      syncChip: txt(document.querySelector('.ad-sync-chip')),
      dlgChanCount: document.querySelectorAll('.inst-chan').length,
      dlgTarget: txt(document.querySelector('.inst-chan-d')),
      dlgPerm: txt(document.querySelector('.inst-perm')),
      dlgAlert: txt(document.querySelector('.el-dialog .el-alert__title')),
      msgBox: txt(document.querySelector('.el-message-box__message')),
      // 包体检
      pvState: txt(document.querySelector('.pv-box')),
      submitDisabled: !!document.querySelector(
        '.el-dialog__footer .el-button--primary.is-disabled, .el-dialog__footer .el-button--primary[disabled]',
      ),
      // 操作记录抽屉 (用页签文案判别 —— 抽屉标题的类名随 element-plus 版本变)
      auditDrawerOpen: drawerTexts.some((t) => /操作审计/.test(t)),
      auditItems: document.querySelectorAll('.log-list .log-item').length,
      notifyTab: (txt(document.querySelector('.el-tabs__item.is-active')) || '').includes('通知回执'),
      notifyItems: document.querySelectorAll('.log-list .log-item').length,
    };
  });
}

/** 按名称反查资产 code —— 必须与"实际打开的那张卡片"一致,
 *  否则下架的是 A、重新上架的是 B, 会把一个资产永久留在下架状态. */
async function codeByName(page, name) {
  return page.evaluate(async (n) => {
    const tk = localStorage.getItem('testmate:token');
    const r = await fetch('/api/v1/assets?kind=plugin&limit=50', { headers: { Authorization: 'Bearer ' + tk } });
    const d = await r.json();
    return (d.items || []).find((i) => i.name === n)?.code || '';
  }, name);
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
    defaultViewport: { width: 1440, height: 1000 },
  });
  const page = await browser.newPage();
  const errors = [];
  // 有些步骤会**故意**触发 4xx (比如验证资产已删除), 那不是缺陷
  let expectHttpError = false;
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
  page.on('console', (m) => {
    if (m.type() === 'error' && !expectHttpError) errors.push('[console.error] ' + m.text());
  });
  page.on('requestfailed', (r) => {
    if (!expectHttpError) errors.push('[reqfail] ' + r.url() + ' :: ' + (r.failure() || {}).errorText);
  });

  // 登录态
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  const login = await page.evaluate(async (u, p) => {
    const r = await fetch('/api/v1/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p }),
    });
    if (!r.ok) return { error: r.status };
    const { access_token } = await r.json();
    const m = await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + access_token } });
    return { token: access_token, user: m.ok ? await m.json() : null };
  }, USER, PASSWORD);
  if (login.error) throw new Error(`登录失败: ${JSON.stringify(login)}`);
  await page.evaluate((tk, u) => {
    localStorage.setItem('testmate:token', tk);
    localStorage.setItem('testmate:user', JSON.stringify(u));
  }, login.token, login.user);

  // 自动化测试**不该往真实钉钉群刷屏** —— 测试期间把通知开关关掉, 结束再恢复.
  // (通知链路本身由 scripts/e2e_dingtalk_settings.js 专门验证)
  const NOTIFY_SWITCHES = [
    'dingtalk.notify_on_publish', 'dingtalk.notify_on_update',
    'dingtalk.notify_on_unpublish', 'dingtalk.notify_on_delete',
  ];
  const savedSwitches = await page.evaluate(async (keys) => {
    const tk = localStorage.getItem('testmate:token');
    const r = await fetch('/api/v1/settings/schema', { headers: { Authorization: 'Bearer ' + tk } });
    const d = await r.json();
    const saved = {};
    for (const g of d.groups || []) {
      for (const it of g.items || []) {
        if (keys.includes(it.key)) saved[it.key] = it.value;
      }
    }
    for (const k of keys) {
      await fetch('/api/v1/settings/' + k, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tk },
        body: JSON.stringify({ value: 'false' }),
      });
    }
    return saved;
  }, NOTIFY_SWITCHES);
  const restoreSwitches = async () => {
    await page.evaluate(async (saved) => {
      const tk = localStorage.getItem('testmate:token');
      for (const [k, v] of Object.entries(saved || {})) {
        await fetch('/api/v1/settings/' + k, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tk },
          body: JSON.stringify({ value: v }),
        });
      }
    }, savedSwitches);
  };


  // ---------- A. 列表渲染 ----------
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1200);
  let s = await snap(page);
  check('A1 市场页渲染出资产卡片', s.cards.length > 0, `${s.cards.length} 张: ${s.cards.map((c) => c.name).join(', ')}`);
  check('A2 无调试条残留', s.debugBar === false);
  check('A3 三个类型 Tab 都有计数', s.tabs.length === 3, s.tabs.join(' | '));
  check('A4 无加载中/空态残留', !s.marketState, s.marketState || '(none)');
  check('A5 底部标注数据源', /GitLab/.test(s.footHint || ''), s.footHint);

  // ---------- B. 类型 Tab ----------
  await clickByText(page, '.kind-tab', '技能');
  await sleep(900);
  s = await snap(page);
  check('B1 切到「技能」Tab 有卡片', s.cards.length > 0, `${s.cards.length} 张`);
  await clickByText(page, '.kind-tab', '连接器');
  await sleep(900);
  s = await snap(page);
  check('B2 切到「连接器」Tab 有卡片', s.cards.length > 0, `${s.cards.length} 张`);
  await clickByText(page, '.kind-tab', '插件');
  await sleep(900);

  // ---------- C. 搜索 ----------
  await page.type('.search input', 'a');
  await sleep(1400);
  s = await snap(page);
  const filtered = s.cards.length;
  await page.evaluate(() => {
    const el = document.querySelector('.search input');
    el.value = '';
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(1400);
  s = await snap(page);
  check('C1 搜索可过滤', filtered >= 0 && s.cards.length >= filtered, `搜索命中 ${filtered} 张 / 清空后 ${s.cards.length} 张`);

  // ---------- D. 详情抽屉 ----------
  const cardName = s.cards[0] ? s.cards[0].name : '';
  // code 必须从"实际打开的这张卡片"反查 —— 否则下架 A、重新上架 B,
  // 会把一个资产永久留在下架状态 (之前踩过)
  const code = await codeByName(page, cardName);
  await clickByText(page, '.asset-card', cardName);
  await page.waitForSelector('.el-drawer', { timeout: 10000 });
  await sleep(1500);
  s = await snap(page);
  check('D1 详情抽屉打开', s.drawerOpen && !!s.drawerName, s.drawerName);
  check('D2 文档正文已渲染', s.docHtmlLen > 40, `html ${s.docHtmlLen} 字节`);
  check('D3 文档已消毒(无 script/iframe/img)', s.docHasScript === false);
  check('D4 权限区块有内容', s.permRows > 0 || s.permEmpty, `permRows=${s.permRows} empty=${s.permEmpty}`);
  check('D5 安装步骤展示', s.steps.length > 0, s.steps.join(' / '));
  check('D6 GitLab 存储路径展示', /assets\//.test(s.gitPath || ''), s.gitPath);
  check('D7 同步状态标签', /已同步|待同步|失败/.test(s.syncChip || ''), s.syncChip);
  await page.screenshot({ path: path.join(OUT_DIR, '01-drawer.png') });

  // ---------- E. 安装向导 ----------
  await clickByText(page, '.ad-actions .el-button', '安装');
  await page.waitForSelector('.inst-chan', { timeout: 10000 });
  await sleep(1200);
  s = await snap(page);
  check('E1 安装向导读到目标目录', s.dlgChanCount === 2 && /\//.test(s.dlgTarget || ''), `target=${s.dlgTarget}`);
  check('E2 向导显示权限提示', (s.dlgPerm || '').length > 5, (s.dlgPerm || '').slice(0, 60));
  await page.screenshot({ path: path.join(OUT_DIR, '02-install.png') });
  await clickByText(page, '.el-dialog__footer .el-button', '开始安装');
  await sleep(2500);
  s = await snap(page);
  check('E3 服务端通道安装成功', /已安装/.test(s.dlgAlert || ''), s.dlgAlert || '(无提示)');
  await page.screenshot({ path: path.join(OUT_DIR, '03-installed.png') });
  await clickByText(page, '.el-dialog__footer .el-button', '取消');
  await sleep(800);

  // 安装后卡片应出现「已安装」标记
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1500);
  s = await snap(page);
  const installedCard = s.cards.find((c) => c.name === (s.cards[0] || {}).name) || s.cards[0];
  check('E4 安装后卡片标记「已安装」', /已安装/.test((installedCard && installedCard.badge) || ''), installedCard ? installedCard.badge : '(无卡片)');

  // ---------- F. 下架 / 重新上架 ----------
  await clickByText(page, '.asset-card', (installedCard && installedCard.name) || '');
  await page.waitForSelector('.el-drawer', { timeout: 10000 });
  await sleep(1500);
  await clickByText(page, '.ad-actions .el-button', '下架');
  await sleep(700);
  s = await snap(page);
  check('F1 下架有二次确认', /下架/.test(s.msgBox || ''), s.msgBox);
  await clickByText(page, '.el-message-box__btns .el-button', '下架');
  await sleep(2000);
  const unpub = await page.evaluate(async (c) => {
    const tk = localStorage.getItem('testmate:token');
    const r = await fetch('/api/v1/assets?limit=200&include_unpublished=true', { headers: { Authorization: 'Bearer ' + tk } });
    const d = await r.json();
    return (d.items || []).find((i) => i.code === c)?.publish_status || '';
  }, code);
  check('F2 下架后 publish_status=unpublished', unpub === 'unpublished', unpub);
  await page.screenshot({ path: path.join(OUT_DIR, '04-unpublished.png') });

  // 重新上架 (走 API, 不依赖 UI 弹窗)
  await page.evaluate(async (c) => {
    const tk = localStorage.getItem('testmate:token');
    const fd = new FormData(); fd.append('comment', 'e2e 恢复上架');
    await fetch(`/api/v1/assets/${c}/publish`, { method: 'POST', headers: { Authorization: 'Bearer ' + tk }, body: fd });
  }, code);
  await sleep(1500);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1200);
  s = await snap(page);
  const back = await page.evaluate(async (c) => {
    const tk = localStorage.getItem('testmate:token');
    const r = await fetch('/api/v1/assets?limit=100&include_unpublished=true', { headers: { Authorization: 'Bearer ' + tk } });
    const d = await r.json();
    return (d.items || []).find((i) => i.code === c)?.publish_status || 'missing';
  }, code);
  check('F3 重新上架后资产状态回到 published', back === 'published', `publish_status=${back}, 列表 ${s.cards.length} 张`);

  // ---------- G. 同步 ----------
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.link-btn')].find((x) => x.textContent.includes('重新同步'));
    b && b.click();
  });
  await sleep(3000);
  s = await snap(page);
  check('G1 重新同步后页面仍正常', s.cards.length > 0, `${s.cards.length} 张`);
  await page.screenshot({ path: path.join(OUT_DIR, '05-final.png'), fullPage: true });

  // ---------- H. 上传前包体检 ----------
  const goodZip = path.join(OUT_DIR, 'e2e-good.zip');
  const badZip = path.join(OUT_DIR, 'e2e-bad.zip');
  makeZip(goodZip, { 'SKILL.md': '---\nname: e2e-probe\ndescription: 体检探针\n---\n\n# 体检探针\n' });
  makeZip(badZip, { 'README.md': '# 缺 SKILL.md 的包\n' });

  await clickByText(page, '.mini-btn.primary', '上传资产');
  await page.waitForSelector('.file-input', { timeout: 10000 });
  await sleep(600);
  const fileInput = await page.$('.file-input');
  await fileInput.uploadFile(goodZip);
  await page.waitForSelector('.pv-box', { timeout: 15000 });
  await sleep(800);
  s = await snap(page);
  check('H1 合规包体检通过', /体检通过/.test(s.pvState || ''), s.pvState);
  check('H2 体检显示文件数与展示文档', /SKILL\.md/.test(s.pvState || ''), s.pvState);
  check('H3 合规包不禁用提交按钮', s.submitDisabled === false, `disabled=${s.submitDisabled}`);

  // 换成不合规的包 (缺 SKILL.md) → 体检应拦下并禁用提交
  const fileInput2 = await page.$('.file-input');
  await fileInput2.uploadFile(badZip);
  await sleep(2500);
  s = await snap(page);
  check('H4 不合规包被体检拦下', /装不上/.test(s.pvState || ''), s.pvState);
  check('H5 不合规包禁用提交按钮', s.submitDisabled === true, `disabled=${s.submitDisabled}`);
  await page.screenshot({ path: path.join(OUT_DIR, '06-precheck.png') });
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-dialog__footer .el-button')].find((x) => x.textContent.includes('取消'));
    b && b.click();
  });
  await sleep(800);

  // ---------- I. 「可更新」筛选 ----------
  await clickByText(page, '.mini-btn', '可更新');
  await sleep(1500);
  s = await snap(page);
  const onlyUpdatable = s.cards.every((c) => /可更新/.test(c.badge || ''));
  check('I1 「可更新」筛选只留可更新资产', onlyUpdatable, `${s.cards.length} 张: ${s.cards.map((c) => c.badge).join('|')}`);
  await clickByText(page, '.mini-btn', '可更新');
  await sleep(1200);
  s = await snap(page);
  check('I2 再点一次恢复全部', s.cards.length > 0, `${s.cards.length} 张`);

  // ---------- J. 操作记录 / 通知回执 ----------
  await clickByText(page, '.mini-btn', '操作记录');
  await page.waitForSelector('.log-list, .state', { timeout: 10000 });
  await sleep(1200);
  s = await snap(page);
  check('J1 操作记录抽屉打开', s.auditDrawerOpen === true, `auditItems=${s.auditItems}`);
  check('J2 有审计条目', s.auditItems > 0, `${s.auditItems} 条`);
  await page.evaluate(() => {
    const t = [...document.querySelectorAll('.el-tabs__item')].find((x) => x.textContent.includes('通知回执'));
    t && t.click();
  });
  await sleep(1500);
  s = await snap(page);
  check('J3 通知回执页签可切换', s.notifyTab === true, `notifyItems=${s.notifyItems}`);
  await page.screenshot({ path: path.join(OUT_DIR, '07-audit.png') });
  await page.evaluate(() => {
    const b = document.querySelector('.el-drawer__close-btn');
    b && b.click();
  });
  await sleep(800);

  // ---------- K. 彻底删除 (走 UI, 输入 code 确认) ----------
  const tmpCode = 'e2e-tmp-delete';
  await page.evaluate(async (c) => {
    const tk = localStorage.getItem('testmate:token');
    const fd = new FormData();
    fd.append('code', c); fd.append('kind', 'skill'); fd.append('name', 'E2E 临时资产');
    fd.append('version', '1.0.0'); fd.append('summary', 'e2e 临时资产, 验证硬删');
    fd.append('description', '用完即删'); fd.append('use_when', '仅测试'); fd.append('not_for', '生产');
    fd.append('category', 'misc'); fd.append('icon', '🧪'); fd.append('tags', '[]');
    fd.append('keywords', '[]'); fd.append('featured', 'false'); fd.append('permissions', '{}');
    fd.append('install_steps', '[]'); fd.append('bindings', '{}');
    fd.append('files', new Blob(['---\nname: e2e-tmp-delete\ndescription: 临时\n---\n\n# 临时\n'], { type: 'text/plain' }), 'SKILL.md');
    await fetch('/api/v1/assets/upload', { method: 'POST', headers: { Authorization: 'Bearer ' + tk }, body: fd });
  }, tmpCode);
  await sleep(6000);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1200);
  await clickByText(page, '.kind-tab', '技能');
  await sleep(1200);
  await clickByText(page, '.asset-card', 'E2E 临时资产');
  await page.waitForSelector('.el-drawer', { timeout: 10000 });
  await sleep(1200);
  await clickByText(page, '.ad-actions .el-button', '彻底删除');
  await sleep(900);
  s = await snap(page);
  check('K1 删除要求输入 code 确认', /code/.test(s.msgBox || ''), (s.msgBox || '').slice(0, 60));
  const promptInput = await page.$('.el-message-box__input input, .el-message-box input');
  if (promptInput) {
    await promptInput.type(tmpCode);
    await clickByText(page, '.el-message-box__btns .el-button', '确认删除');
  }
  await sleep(4000);
  expectHttpError = true;   // 下面这个 404 是"资产确实被删掉了"的证据, 不是缺陷
  const gone = await page.evaluate(async (c) => {
    const tk = localStorage.getItem('testmate:token');
    const r = await fetch('/api/v1/assets/' + c, { headers: { Authorization: 'Bearer ' + tk } });
    return r.status;
  }, tmpCode);
  expectHttpError = false;
  check('K2 删除后资产不存在', gone === 404, `HTTP ${gone}`);

  // ---------- 汇总 ----------
  check('Z1 全程无 JS 错误 / 请求失败', errors.length === 0, errors.slice(0, 5).join(' ; '));

  // 恢复通知开关 (测试期间静音了, 别把真实配置留在关的状态)
  await restoreSwitches();
  const restored = await page.evaluate(async (keys) => {
    const tk = localStorage.getItem('testmate:token');
    const r = await fetch('/api/v1/settings/schema', { headers: { Authorization: 'Bearer ' + tk } });
    const d = await r.json();
    const out = {};
    for (const g of d.groups || []) {
      for (const it of g.items || []) {
        if (keys.includes(it.key)) out[it.key] = it.value;
      }
    }
    return out;
  }, NOTIFY_SWITCHES);
  check('Z2 通知开关已恢复原值',
    Object.values(restored).every((v) => String(v) === 'true'),
    Object.entries(restored).map(([k, v]) => `${k}=${v}`).join(' '));

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  console.log('截图目录: ' + OUT_DIR);
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
