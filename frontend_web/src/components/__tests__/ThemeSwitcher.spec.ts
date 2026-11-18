/**
 * 顶栏主题控件 (ThemeSwitcher) —— 2026-11-17: 单按钮三态循环.
 *
 * 循环顺序按用户要求: 电脑 (跟随系统) → 太阳 (浅色) → 月亮 (深色) → 电脑.
 * 默认未点过 = 跟随系统.
 *
 * ⚠️ 历史: 中间试过「浅 → 深 → 跟随系统」的循环 —— 从深色出发第一步
 *    落到「跟随系统」, 系统深色时外观不变, 用户以为没生效. 现在把
 *    「跟随系统」放在循环首步 (默认态), 从它出发第一步永远切到浅色,
 *    图标本身也会跟着换成太阳/月亮, 能看出点到了.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { useThemeStore } from '@/stores/theme';
import ThemeSwitcher from '../ThemeSwitcher.vue';

const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');

function mockSystemDark(dark: boolean) {
  window.matchMedia = ((q: string) => ({
    matches: dark, media: q, onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as any;
}

const label = (w: ReturnType<typeof mount>) => w.get('button').attributes('aria-label') || '';

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  mockSystemDark(false);
});

describe('ThemeSwitcher · 单按钮三态循环 (2026-11-17)', () => {
  it('默认是「跟随系统」(电脑图标)', () => {
    const w = mount(ThemeSwitcher);
    expect(label(w)).toContain('跟随系统');
  });

  it('点一次 → 浅色, 再点 → 深色, 再点 → 回跟随系统', async () => {
    const w = mount(ThemeSwitcher);
    const store = useThemeStore();

    await w.get('button').trigger('click');
    expect(store.mode).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
    expect(label(w)).toContain('浅色');

    await w.get('button').trigger('click');
    expect(store.mode).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    expect(label(w)).toContain('深色');

    await w.get('button').trigger('click');
    expect(store.mode).toBe('auto');
    expect(document.documentElement.dataset.theme).toBe('auto');
    expect(label(w)).toContain('跟随系统');
  });

  it('从「深色」出发也能回到跟随系统, 不会被吃掉', async () => {
    const store = useThemeStore();
    store.set('dark');
    const w = mount(ThemeSwitcher);

    await w.get('button').trigger('click');
    expect(store.mode).toBe('auto');
    expect(localStorage.getItem('testmate:theme')).toBe('auto');
  });

  it('系统深色时, 跟随系统仍按系统偏好着色', async () => {
    mockSystemDark(true);
    const store = useThemeStore();
    store.set('auto');
    const w = mount(ThemeSwitcher);
    expect(store.resolved).toBe('dark');
    expect(document.documentElement.classList.contains('dark')).toBe(true);
    // 从 auto 出发第一下仍是切到浅色 —— 一步就有可见变化
    await w.get('button').trigger('click');
    expect(store.mode).toBe('light');
    expect(document.documentElement.classList.contains('dark')).toBe(false);
  });

  it('按钮与消息铃铛同尺寸对齐 —— 32px 按钮 + 17px 图标', () => {
    const theme = read('src/components/ThemeSwitcher.vue');
    const bell = read('src/components/NotificationBell.vue');
    for (const [name, src] of [['主题', theme], ['铃铛', bell]] as [string, string][]) {
      expect(src, `${name}按钮不是 32px`).toMatch(/\.tm-(theme|bell)\s*\{[^}]*width:\s*32px/);
      expect(src, `${name}按钮不是 32px`).toMatch(/\.tm-(theme|bell)\s*\{[^}]*height:\s*32px/);
      expect(src, `${name}图标不是 17px`).toMatch(/width="17" height="17"/);
    }
  });
});
