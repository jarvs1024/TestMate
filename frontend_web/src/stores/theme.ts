import { defineStore } from 'pinia';

export type ThemeMode = 'light' | 'dark' | 'auto';
const STORAGE_KEY = 'testmate:theme';
const DEFAULT: ThemeMode = 'auto';

function applyTheme(mode: ThemeMode) {
  const html = document.documentElement;
  html.setAttribute('data-theme', mode);
  const isDark =
    mode === 'dark' ||
    (mode === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  html.classList.toggle('dark', isDark);
}

export const useThemeStore = defineStore('theme', {
  state: () => ({
    mode: (localStorage.getItem(STORAGE_KEY) as ThemeMode) || DEFAULT,
  }),
  getters: {
    resolved: (state): 'light' | 'dark' =>
      state.mode === 'auto'
        ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
        : state.mode,
  },
  actions: {
    init() {
      applyTheme(this.mode);
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      mq.addEventListener('change', () => {
        if (this.mode === 'auto') applyTheme('auto');
      });
    },
    set(mode: ThemeMode) {
      this.mode = mode;
      localStorage.setItem(STORAGE_KEY, mode);
      applyTheme(mode);
    },
    toggle() {
      // ⚠️ 循环顺序 (2026-11-17 用户指定): 跟随系统 (默认) → 浅色 → 深色 → 跟随系统.
      //    把 auto 放在首步: 从默认态出发第一下**一定**换成浅色 —— 有可见变化.
      //    必须用 this.mode 判断, 不能用 resolved (会把 auto 解析掉).
      const next: ThemeMode =
        this.mode === 'auto' ? 'light'
        : this.mode === 'light' ? 'dark'
        : 'auto';
      this.set(next);
    },
  },
});
