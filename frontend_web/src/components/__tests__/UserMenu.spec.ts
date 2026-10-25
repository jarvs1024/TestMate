/**
 * 用户菜单 (UserMenu) —— 顶栏右上角的账号下拉.
 *
 * 为什么盯这个 (2026-10-25):
 *   下拉里原来有两条**死路** —— 点了只弹一句话, 什么都不发生:
 *     · 「能力注册 (admin)」→ 只弹 "能力注册 · P1 实现"
 *     · 「主题 · ☀ / 🌙 / 自动」→ 只弹 "点顶栏 ☀/🌙 切换主题"
 *       (顶栏那颗太阳就在旁边, 这条是纯废话)
 *   死路菜单项比没有更糟 —— 用户以为有功能, 点一下才发现是空头支票.
 *
 * 所以下拉现在只留三件事: 身份 → 设置 → 退出登录.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SRC = readFileSync(resolve(process.cwd(), 'src/components/UserMenu.vue'), 'utf8');
/** 只看 <template> —— 注释里可以写"以前有过这两条", 不该被当成还留着 */
const TPL = SRC.slice(SRC.indexOf('<template>'), SRC.indexOf('</template>'));

describe('用户菜单', () => {
  it('下拉里没有「能力注册」和「主题」两条死路', () => {
    expect(TPL).not.toContain('能力注册');
    expect(TPL).not.toContain('command="theme"');
    expect(TPL).not.toContain('command="agents"');
  });

  it('对应的占位提示也一并没了 (不是换个地方继续弹)', () => {
    expect(SRC).not.toContain('P1 实现');
    expect(SRC).not.toContain('点顶栏');
  });

  it('保留 身份 / 设置 / 退出登录', () => {
    expect(TPL).toContain('command="settings"');
    expect(TPL).toContain('command="logout"');
    expect(TPL).toContain('dd-head');       // 身份头 (用户名 + 角色)
  });

  it('主题切换走顶栏的 ThemeSwitcher (下拉里不再重复一份)', () => {
    const header = readFileSync(resolve(process.cwd(), 'src/components/AppHeader.vue'), 'utf8');
    expect(header).toContain('<ThemeSwitcher');
  });
});
