import { chromium } from 'playwright';
import fs from 'fs';

const SHOTS = '/tmp/testmate-shots';
fs.mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();

const log = (...a) => console.log('[E2E]', ...a);

// 收集 console 错误
const errors = [];
page.on('pageerror', e => errors.push(`pageerror: ${e.message}`));
page.on('console', msg => { if (msg.type() === 'error') errors.push(`console.error: ${msg.text()}`); });
// 收集网络失败
const netFails = [];
page.on('requestfailed', req => {
  const u = req.url();
  // 跳过已知的 RAGFlow 外网请求
  if (u.includes('18080')) return;
  netFails.push(`${req.failure()?.errorText} ${u}`);
});

try {
  log('1. 打开登录页');
  await page.goto('http://localhost:8080/login', { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(()=>{});
  await page.screenshot({ path: `${SHOTS}/01-login.png`, fullPage: true });

  log('2. 登录');
  await page.fill('input[type=text], input[type=username], input[name=username]', 'admin');
  await page.fill('input[type=password]', 'TestMate@2026');
  const loginBtn = page.locator('button:has-text("登录"), button:has-text("Login")').first();
  await loginBtn.click();
  await page.waitForURL(/\/kb|\/plaza|\/$/, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(()=>{});
  log('   登录后 URL:', page.url());
  await page.screenshot({ path: `${SHOTS}/02-after-login.png`, fullPage: true });

  log('3. 进 KB 页');
  // 找 KB 链接
  const kbLink = page.locator('a[href*="/kb"], a:has-text("知识库"), [role=link]:has-text("知识库")').first();
  if (await kbLink.count() > 0) {
    await kbLink.click();
  } else {
    await page.goto('http://localhost:8080/kb');
  }
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(()=>{});
  await page.waitForSelector('iframe[title=knowledge-search]', { timeout: 15000 });
  log('   搜索 tab iframe 出现');
  await page.screenshot({ path: `${SHOTS}/03-kb-search.png`, fullPage: true });

  // 验证 iframe src 包含 userId=admin + theme=...
  const searchSrc = await page.locator('iframe[title=knowledge-search]').getAttribute('src');
  log('   search iframe src:', searchSrc);
  if (!searchSrc?.includes('userId=admin')) throw new Error('search iframe src 缺 userId=admin');
  if (!searchSrc?.match(/theme=(light|dark)/)) throw new Error('search iframe src 缺 theme=');

  // 验证 3 个数据集
  const dsRows = await page.locator('table.ds-tbl tbody tr').count();
  log('   数据集行数:', dsRows);
  if (dsRows < 3) throw new Error(`预期 >= 3 个数据集, 实际 ${dsRows}`);

  log('4. 切到对话 tab');
  await page.locator('button.share-tab:has-text("对话")').click();
  await page.waitForSelector('iframe[title=knowledge-chat]', { timeout: 10000 });
  await page.waitForTimeout(500);
  const chatSrc = await page.locator('iframe[title=knowledge-chat]').getAttribute('src');
  log('   chat iframe src:', chatSrc);
  if (!chatSrc?.includes('userId=admin')) throw new Error('chat iframe src 缺 userId=admin');
  await page.screenshot({ path: `${SHOTS}/04-kb-chat.png`, fullPage: true });

  log('5. 切回搜索 tab, 验证不空白');
  await page.locator('button.share-tab:has-text("搜索")').click();
  await page.waitForSelector('iframe[title=knowledge-search]', { timeout: 10000 });
  await page.waitForTimeout(500);
  const searchSrc2 = await page.locator('iframe[title=knowledge-search]').getAttribute('src');
  log('   search iframe src (再切回):', searchSrc2);
  if (!searchSrc2?.includes('userId=admin')) throw new Error('切回搜索 tab 后 iframe src 缺 userId=admin');
  await page.screenshot({ path: `${SHOTS}/05-kb-search-again.png`, fullPage: true });

  log('6. 进 Settings 页');
  await page.goto('http://localhost:8080/settings');
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(()=>{});
  await page.waitForSelector('text=知识检索', { timeout: 10000 });
  log('   Settings 知识检索子组出现');
  await page.screenshot({ path: `${SHOTS}/06-settings.png`, fullPage: true });

  // 验证 6+ 个 search 项渲染
  const searchRows = await page.locator('#sec-search .row, #sec-search [class*=row]').count();
  log('   search 子组 row 数:', searchRows);
  if (searchRows < 6) throw new Error(`预期 >= 6 个 search setting row, 实际 ${searchRows}`);

  // 验证开关能交互
  const switches = await page.locator('#sec-search input[type=checkbox]').count();
  log('   search 子组 switch 数:', switches);
  if (switches < 2) throw new Error(`预期 >= 2 个 switch, 实际 ${switches}`);

  log('===E2E PASS===');
  if (errors.length) {
    log('!!! JS 错误:', errors.length);
    errors.forEach(e => log('   ', e));
  } else {
    log('无 JS 错误');
  }
  if (netFails.length) {
    log('!!! 网络失败:', netFails.length);
    netFails.forEach(e => log('   ', e));
  } else {
    log('无网络失败 (除 RAGFlow 外网)');
  }
} catch (e) {
  log('!!! E2E FAIL:', e.message);
  await page.screenshot({ path: `${SHOTS}/FAIL.png`, fullPage: true });
  process.exit(1);
} finally {
  await browser.close();
}
