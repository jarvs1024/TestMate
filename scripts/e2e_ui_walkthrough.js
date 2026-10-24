#!/usr/bin/env node
/**
 * 资产市场的**UI 全流程走查** (真实 Chrome) —— 走一遍用户真会走的路, 每步留截图.
 *
 * 与 e2e 断言不同: 这里不看断言, 只看**界面在每一步是否正常** (截图给人看).
 * 用途: 单测和断言都绿, 但界面可能已经歪了 —— 这个脚本专门抓那种.
 *
 * 用法: NODE_PATH=/tmp/tm-e2e/node_modules node scripts/e2e_ui_walkthrough.js
 */
const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');
require('./e2e_lock').acquire(__filename);

const CHROME = process.env.CHROME_PATH
  || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = (process.env.TESTMATE_BASE || 'http://localhost:8090').replace(/\/$/, '');
const API = process.env.TESTMATE_API || 'http://localhost:18000';
const ADMIN = process.env.TESTMATE_USER || 'admin';
const ADMIN_PW = process.env.TESTMATE_PASSWORD || 'Admin@123';
const OUT_DIR = process.env.E2E_OUT_DIR || path.join(__dirname, '..', '.e2e-out');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const shots = [];
async function shot(page, name, desc) {
  const file = path.join(OUT_DIR, `walk-${name}.png`);
  await page.screenshot({ path: file });
  shots.push({ file, desc });
  console.log(`  📸 ${name} — ${desc}`);
}

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const r = await fetch(API + '/api/v1/auth/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: ADMIN, password: ADMIN_PW }),
  });
  const token = (await r.json()).access_token || '';

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

  // ---- ① 登录 → 市场页 ----
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  await page.evaluate((t) => {
    localStorage.setItem('testmate:token', t);
    localStorage.setItem('testmate:user', JSON.stringify({ id: 1, username: 'admin', role: 'admin' }));
  }, token);
  await page.goto(BASE + '/market', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.asset-card', { timeout: 15000 });
  await sleep(1800);
  await shot(page, '01-market', '市场页: 类型 tab + 分类 chip + 项目 chip + 搜索');

  // ---- ② 切类型 tab ----
  await page.evaluate(() => {
    const t = [...document.querySelectorAll('.kind-tab')].find((x) => x.textContent.includes('连接器'));
    t && t.click();
  });
  await sleep(1500);
  await shot(page, '02-connectors', '切到「连接器」tab');

  // ---- ③ 打开一个连接器详情 (MCP 配置) ----
  await page.evaluate(() => {
    const c = document.querySelector('.asset-card');
    c && c.click();
  });
  await page.waitForSelector('.ad-scope', { timeout: 10000 });
  await sleep(1500);
  await shot(page, '03-detail-mcp', '详情抽屉: 适用范围 + MCP 配置');

  // ---- ④ 展开技术信息 ----
  await page.evaluate(() => {
    const b = document.querySelector('.tech-toggle');
    b && b.click();
  });
  await sleep(800);
  await shot(page, '04-detail-tech', '详情抽屉: 技术信息展开');
  await page.evaluate(() => {
    const b = document.querySelector('.el-drawer__close-btn');
    b && b.click();
  });
  await sleep(900);

  // ---- ⑤ 上传抽屉: 选形态 ----
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.mini-btn.primary')].find((x) => x.textContent.includes('上传资产'));
    b && b.click();
  });
  await sleep(800);
  await shot(page, '05-upload-kinds', '上传: 第 ① 步选形态');

  // ---- ⑥ 技能表单 (含包要求 + code 字段) ----
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.pick-item')].find((x) => x.textContent.includes('技能'));
    el && el.click();
  });
  await page.waitForSelector('.file-input', { timeout: 10000 });
  await sleep(900);
  await shot(page, '06-upload-skill', '上传: 技能表单 (包要求 + code 归在包区)');

  // ---- ⑦ 展开进阶信息 ----
  await page.evaluate(() => {
    const b = document.querySelector('.up-drawer .sec-toggle');
    b && b.click();
  });
  await sleep(700);
  await page.evaluate(() => {
    const d = document.querySelector('.up-drawer');
    d.querySelector('.adv-body')?.scrollIntoView({ block: 'center' });
  });
  await sleep(500);
  await shot(page, '07-upload-advanced', '上传: 进阶信息 (标签/关键词)');
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer__footer .el-button')].find((x) => x.textContent.includes('取消'));
    b && b.click();
  });
  await sleep(900);

  // ---- ⑧ 连接器表单 (MCP 配置区) ----
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.mini-btn.primary')].find((x) => x.textContent.includes('上传资产'));
    b && b.click();
  });
  await sleep(800);
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.pick-item')].find((x) => x.textContent.includes('连接器'));
    el && el.click();
  });
  await page.waitForSelector('.mcp-json', { timeout: 10000 });
  await sleep(900);
  await shot(page, '08-upload-mcp', '上传: 连接器表单 (MCP 配置区)');
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer__footer .el-button')].find((x) => x.textContent.includes('取消'));
    b && b.click();
  });
  await sleep(900);

  // ---- ⑨ 图标选择面板 ----
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.mini-btn.primary')].find((x) => x.textContent.includes('上传资产'));
    b && b.click();
  });
  await sleep(700);
  await page.evaluate(() => {
    const el = [...document.querySelectorAll('.pick-item')].find((x) => x.textContent.includes('技能'));
    el && el.click();
  });
  await page.waitForSelector('.file-input', { timeout: 10000 });
  await sleep(800);
  await page.evaluate(() => {
    const b = document.querySelector('.up-drawer .icon-btn');
    b && b.click();
  });
  await sleep(800);
  await shot(page, '09-icon-picker', '上传: 图标面板 (只列没被占用的)');
  await page.evaluate(() => {
    const b = document.querySelector('.up-drawer .icon-btn');
    b && b.click();
  });
  await sleep(400);
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.el-drawer__footer .el-button')].find((x) => x.textContent.includes('取消'));
    b && b.click();
  });
  await sleep(800);

  // ---- ⑩ 搜索 ----
  await page.evaluate(() => {
    const i = document.querySelector('.search input');
    if (!i) return;
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(i, '日志');
    i.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await sleep(1800);
  await shot(page, '10-search', '市场页: 搜索');

  // ---- ⑪ 操作记录抽屉 ----
  await page.evaluate(() => {
    const b = [...document.querySelectorAll('.mini-btn')].find((x) => x.textContent.includes('操作记录'));
    b && b.click();
  });
  await sleep(1500);
  await shot(page, '11-audit', '操作记录抽屉');

  await browser.close();
  console.log(`\n共 ${shots.length} 张截图 → ${OUT_DIR}`);
  console.log(errors.length ? `⚠️ 全程有 ${errors.length} 条 JS 错误:\n` + errors.slice(0, 5).join('\n') : '✅ 全程无 JS 错误');
  process.exit(errors.length ? 1 : 0);
})().catch((e) => { console.error('FATAL', e); process.exit(2); });
