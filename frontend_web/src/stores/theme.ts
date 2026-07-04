import { defineStore } from 'pinia';

export type ThemeMode = 'light' | 'dark' | 'auto';

const STORAGE_KEY = 'testmate:theme';
const DEFAULT: ThemeMode = 'auto';

/** 把 mode 落到 <html data-theme=...>, 顺带同步 Element Plus 的 .dark 类 */
function applyTheme(mode: ThemeMode) {
  const html = document.documentElement;
  html.setAttribute('data-theme', mode);
  // Element Plus 跟我们的 deep 主题对齐
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
    /** 用于显示: 把 auto 解析成实际的 light/dark */
    resolved: (state): 'light' | 'dark' => {
      if (state.mode !== 'auto') return state.mode;
      return window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light';
    },
  },
  actions: {
    init() {
      applyTheme(this.mode);
      // auto 模式需要听系统变化
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
  },
});
