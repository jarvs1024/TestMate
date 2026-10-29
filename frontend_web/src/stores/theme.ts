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
      // ⚠️ 以前是在 resolved 基础上翻 —— 那会把「跟随系统 (auto)」**永久吃掉**:
      //    系统是深色 → 首屏 auto 解析成 dark → 点一下就变成 light,
      //    并把 light 写死进 localStorage. 此后系统主题怎么改都不跟随,
      //    而且界面上**没有任何入口能回到 auto** (UserMenu 的三态选项已删).
      //    现在按三态循环: light → dark → auto → light, auto 永远回得来.
      //
      // ⚠️ 必须用 this.mode 判断当前态, **不能用 resolved** ——
      //    resolved 只返回 light/dark, auto 会被解析掉, 判断不出"当前是不是自动".
      const next: ThemeMode =
        this.mode === 'light' ? 'dark'
        : this.mode === 'dark' ? 'auto'
        : 'light';
      this.set(next);
    },
  },
});
