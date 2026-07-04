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
      // 在 resolved 基础上翻
      this.set(this.resolved === 'dark' ? 'light' : 'dark');
    },
  },
});
