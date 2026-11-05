import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/__tests__/**/*.spec.ts'],
    globals: true,
    // ⚠️ 必须挂 setup —— Node 25 内置的 globalThis.localStorage 会抢占这个全局名,
    //    而它没有 clear() → 一片用例 `localStorage.clear()` 直接 TypeError.
    //    详见 src/test-setup.ts 的说明.
    setupFiles: ['./src/test-setup.ts'],
  },
});
