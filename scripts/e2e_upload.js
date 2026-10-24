#!/usr/bin/env node
/**
 * 上传入口的统一走法 —— 「先选形态, 再进配置页」.
 *
 * 2026-10-24 之前: 点「上传资产」直接进**技能**表单,
 *   要传连接器得在表单里翻到基础信息改类型下拉, 改完才看到 MCP 配置区。
 * 现在: 点「上传资产」→ 先选形态 → 直接进对应表单。
 *
 * e2e 脚本都走这里, 别各自去点按钮 (入口改了就全废)。
 */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 点开「上传资产」菜单 (还没选形态) —— 用来验「第一步先问一句」 */
async function openUploadMenu(page) {
  const opened = await page.evaluate(() => {
    const b = [...document.querySelectorAll('.mini-btn.primary')]
      .find((x) => x.textContent.includes('上传资产'));
    if (!b) return false;
    b.click();
    return true;
  });
  if (!opened) throw new Error('未找到「上传资产」按钮');
  await sleep(600);
  return true;
}

/**
 * 点「上传资产」→ 选一种形态 → 进对应配置页.
 * @param kindLabel 形态名: 技能 / 插件 / 连接器
 */
async function openUpload(page, kindLabel) {
  await openUploadMenu(page);
  const hit = await page.evaluate((label) => {
    const el = [...document.querySelectorAll('.pick-item')]
      .find((x) => (x.textContent || '').replace(/\s+/g, ' ').includes(label));
    if (!el) return false;
    el.click();
    return true;
  }, kindLabel);
  if (!hit) throw new Error(`上传入口未命中形态: ${kindLabel}`);
  await sleep(800);
  return true;
}

module.exports = { openUpload, openUploadMenu, sleep };
