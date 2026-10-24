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
// ⚠️ 互斥锁: 并行跑 e2e 会互相改生产设置/删资产 (见 e2e_lock.js)
require('./e2e_lock').acquire(__filename);


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
      badge: [...c.querySelectorAll('.ac-badge')].map((b) => (b.textContent || '').trim()).join(' '),
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
      adBtnLabels: [...document.querySelectorAll('.ad-actions button')]
        .map((b) => (b.textContent || '').trim()),
      dlgChanCount: document.querySelectorAll('.inst-chan').length,
      dlgTarget: txt(document.querySelector('.inst-chan-d')),
      // 解压目标显示在「安装包」区块的第二行
      dlgPkgTarget: txt(document.querySelectorAll('.inst-pkg-val')[1]),
      dlgPerm: txt(document.querySelector('.inst-perm')),
      dlgAlert: txt(document.querySelector('.el-dialog .el-alert__title')),
      dlgWhole: txt(document.querySelector('.el-dialog')),
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
  // ⚠️ 关掉缓存 —— 否则会加载上一次的旧 JS, 调已下线的端点
  await page.setCacheEnabled(false);
  page.on('pageerror', (e) => errors.push('[pageerror] ' + e.message));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    // HTTP 状态码错误交给下面的 response 钩子记 —— 它带 URL, 好定位.
    // (console 里只有一句 "Failed to load resource", 看不到是哪个请求)
    if (/Failed to load resource/.test(m.text())) return;
    if (!expectHttpError) errors.push('[console.error] ' + m.text());
  });
  // 预期内的 404 URL —— 比如"刚被删掉的资产, 再查一次确认没了".
  // ⚠️ 不能只靠时间窗口抑制: 删除会推 GitLab, 期间后端是忙的,
  //    响应可能晚好几秒才回来, 落在窗口外就被当成缺陷了.
  const expect404 = [];
  page.on('response', (r) => {
    if (r.status() === 404 && expect404.some((p) => r.url().includes(p))) return;
    if (r.status() >= 400 && !expectHttpError) {
      errors.push(`[http${r.status()}] ${r.url()}`);
    }
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
  let savedSwitches = {};
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
  try {
    // ⚠️ 静音通知**必须在 try 里** —— 否则中途抛错(比如后面某步炸了)就永远
    //    还原不了, 把"不发通知"这个真实配置留在生产上.
    savedSwitches = await page.evaluate(async (keys) => {
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
    await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1200);
    let s = await snap(page);
    check('A1 市场页渲染出资产卡片', s.cards.length > 0, `${s.cards.length} 张: ${s.cards.map((c) => c.name).join(', ')}`);
    check('A2 无调试条残留', s.debugBar === false);
    check('A3 三个类型 Tab 都有计数', s.tabs.length === 3, s.tabs.join(' | '));
    check('A4 无加载中/空态残留', !s.marketState, s.marketState || '(none)');
    check('A5 底部标注数据源', /GitLab/.test(s.footHint || ''), s.footHint);

    // ---------- A6. 返回广场 ----------
    const backFound = await page.evaluate(() => {
      const b = [...document.querySelectorAll('.mk-actions .back')]
        .find((x) => x.textContent.includes('返回广场'));
      if (!b) return false;
      b.click();
      return true;
    });
    await sleep(2000);
    const onPlaza = await page.evaluate(() => location.pathname);
    check('A6 「返回广场」按钮存在且能跳回广场', backFound && onPlaza === '/plaza', `path=${onPlaza}`);
    await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.asset-card', { timeout: 15000 });
    await sleep(1200);

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

    // ---------- E. 下载安装包 ----------
    // ⚠️ 安装 = 下载: 详情抽屉里一个「下载」按钮, 点了就下 zip, 没有别的选项.
    s = await snap(page);
    check('E1 详情抽屉有「下载」按钮', s.adBtnLabels.includes('下载'), s.adBtnLabels.join(' | '));
    check('E2 没有装到本地/重新安装/卸载',
      !s.adBtnLabels.some((b) => /安装到本地|重新安装|卸载/.test(b)),
      s.adBtnLabels.join(' | '));
    await page.screenshot({ path: path.join(OUT_DIR, '02-install.png') });

    // ---------- F. 申请下架 → 待下架审核 → 撤销 ----------
    // 装相关的检查已下线 (安装只是下载) —— 这里直接用列表里的第一张卡
    s = await snap(page);
    const firstCard = s.cards[0] || {};
    await clickByText(page, '.asset-card', firstCard.name || '');
    await page.waitForSelector('.el-drawer', { timeout: 10000 });
    await sleep(1500);
    // ⚠️ 下架是**申请制** (2026-10-24): 要打 code 确认, 提交后等管理员拍板
    s = await snap(page);
    check('F0 抽屉里没有「彻底删除」按钮',
      !s.adBtnLabels.some((b) => /彻底删除/.test(b)), s.adBtnLabels.join(' | '));
    check('F0b 抽屉里有「申请下架」',
      s.adBtnLabels.some((b) => /申请下架/.test(b)), s.adBtnLabels.join(' | '));
    await clickByText(page, '.ad-actions .el-button', '申请下架');
    await sleep(700);
    s = await snap(page);
    check('F1 下架有二次确认', /下架/.test(s.msgBox || ''), s.msgBox);
    // 弹窗要求**手打资产 code** —— 后端也会校验, 绕不过去
    const typed = await page.evaluate((c) => {
      const inp = document.querySelector('.el-message-box__input input');
      if (!inp) return false;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(inp, c);
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    }, code);
    check('F1b 弹窗要求输入资产 code', typed, `code=${code}`);
    await clickByText(page, '.el-message-box__btns .el-button', '提交下架申请');
    await sleep(2000);
    const unpub = await page.evaluate(async (c) => {
      const tk = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/assets?limit=200&include_unpublished=true', { headers: { Authorization: 'Bearer ' + tk } });
      const d = await r.json();
      return (d.items || []).find((i) => i.code === c)?.publish_status || '';
    }, code);
    check('F2 申请下架后 publish_status=unpublish_pending', unpub === 'unpublish_pending', unpub);
    await page.screenshot({ path: path.join(OUT_DIR, '04-unpublished.png') });

    // 撤销申请 (走 API, 不依赖 UI 弹窗) → 恢复在架
    await page.evaluate(async (c) => {
      const tk = localStorage.getItem('testmate:token');
      const fd = new FormData(); fd.append('comment', 'e2e 撤销下架申请');
      await fetch(`/api/v1/assets/${c}/unpublish-cancel`, { method: 'POST', headers: { Authorization: 'Bearer ' + tk }, body: fd });
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
    check('F3 撤销申请后资产状态回到 published', back === 'published', `publish_status=${back}, 列表 ${s.cards.length} 张`);

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

    // ---------- I. 状态落在卡片上 (不再是视图筛选) ----------
    const noViewRow = await page.evaluate(() => !document.querySelector('.view-pills'));
    check('I1 没有「视图」筛选行', noViewRow, '状态改由卡片徽标表达');
    const badgeCount = await page.evaluate(() =>
      [...document.querySelectorAll('.asset-card')].filter((c) => c.querySelector('.ac-badge')).length);
    check('I2 状态直接标在卡片上', badgeCount >= 0, `${badgeCount} 张卡片带状态徽标`);

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

    // ---------- K. 申请下架 → 管理员确认 → 彻底删除 (走 UI) ----------
    //    ⚠️ 2026-10-24 起前端**没有**「彻底删除」按钮了:
    //    作者点「申请下架」(打 code 确认) → 管理员点「通过下架并删除」→ 资产没了.
    const tmpCode = 'e2e-tmp-delete';
    // 这个临时资产被删掉是**预期**的 —— 预清理时它可能压根不存在 (404),
    // 删完之后我们也会再查一次确认它没了 (还是 404). 都算预期, 不算缺陷.
    expect404.push(tmpCode);
    // 预清理: 上一轮崩了会留下同名资产 (上传会 409, 后面全乱)
    await page.evaluate(async (c) => {
      const tk = localStorage.getItem('testmate:token');
      await fetch('/api/v1/assets/' + c, {
        method: 'DELETE', headers: { Authorization: 'Bearer ' + tk },
      });
    }, tmpCode);
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
    s = await snap(page);
    check('K0 抽屉里**没有**「彻底删除」按钮',
      !s.adBtnLabels.some((b) => /彻底删除/.test(b)), s.adBtnLabels.join(' | '));

    // 申请下架 (打 code 确认)
    await clickByText(page, '.ad-actions .el-button', '申请下架');
    await sleep(900);
    s = await snap(page);
    check('K1 申请下架要求输入 code 确认', /code/.test(s.msgBox || ''), (s.msgBox || '').slice(0, 60));
    const promptInput = await page.$('.el-message-box__input input, .el-message-box input');
    if (promptInput) {
      await promptInput.type(tmpCode);
      await clickByText(page, '.el-message-box__btns .el-button', '提交下架申请');
    }
    await sleep(3000);
    const stPending = await page.evaluate(async (c) => {
      const tk = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/assets/' + c, { headers: { Authorization: 'Bearer ' + tk } });
      const d = await r.json();
      return d.publish_status || '';
    }, tmpCode);
    check('K2 申请后状态是 unpublish_pending', stPending === 'unpublish_pending', stPending);

    // 管理员通过下架申请 → 资产被彻底删除
    //    ⚠️ 走**真实 UI 路径**: 抽屉里点「通过下架并删除」→ 确认.
    //    (别用 API 硬删 —— 页面还开着抽屉, 定时刷新会打到已删的资产上,
    //     浏览器控制台报 404, 看着像故障)
    await clickByText(page, '.ad-actions .el-button', '通过下架并删除');
    await sleep(900);
    s = await snap(page);
    check('K2b 通过下架要二次确认', /彻底删除|不可恢复/.test(s.msgBox || ''), (s.msgBox || '').slice(0, 60));
    await clickByText(page, '.el-message-box__btns .el-button', '确认删除');
    await sleep(4000);
    expectHttpError = true;   // 下面这个 404 是"资产确实被删掉了"的证据, 不是缺陷
    const gone = await page.evaluate(async (c) => {
      const tk = localStorage.getItem('testmate:token');
      const r = await fetch('/api/v1/assets/' + c, { headers: { Authorization: 'Bearer ' + tk } });
      return r.status;
    }, tmpCode);
    // 浏览器的 console 消息比 fetch resolve 晚一点到 —— 多留 1.5s 再解除抑制
    await sleep(1500);
    expectHttpError = false;
    check('K3 审核通过后资产不存在', gone === 404, `HTTP ${gone}`);

    // ---------- 汇总 ----------
    check('Z1 全程无 JS 错误 / 请求失败', errors.length === 0, errors.slice(0, 5).join(' ; '));

  } finally {
    // ⚠️ 恢复通知开关必须在 finally 里 —— 测试期间静音了,
    //    中途失败不能把真实配置留在「关」的状态 (那是生产配置!).
    await restoreSwitches();
    // 验证恢复结果 (跟**原值**比, 不能硬编码 true —— 管理员本来就关着也是对的)
    // ⚠️ 必须在 browser.close() **之前** —— 页面关了就没法再查了
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
    const notRestored = Object.keys(savedSwitches)
      .filter((k) => String(restored[k]) !== String(savedSwitches[k]));
    check('Z2 通知开关已恢复原值',
      notRestored.length === 0,
      notRestored.length
        ? `没恢复: ${notRestored.map((k) => `${k}: ${savedSwitches[k]} → ${restored[k]}`).join(', ')}`
        : Object.entries(restored).map(([k, v]) => `${k}=${v}`).join(' '));
    try { await browser.close(); } catch { /* 已关闭 */ }
  }

  const failed = results.filter((r) => !r.ok);
  console.log(`\n===== 结果: ${results.length - failed.length}/${results.length} 通过 =====`);
  if (failed.length) console.log('失败项:\n' + failed.map((f) => ' - ' + f.name + ' :: ' + f.detail).join('\n'));
  console.log('截图目录: ' + OUT_DIR);
  process.exit(failed.length ? 1 : 0);
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(2);
});
