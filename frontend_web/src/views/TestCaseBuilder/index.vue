<template>
  <div class="uc">
    <div class="box card">
      <div class="ico">
        <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
        </svg>
      </div>
      <h1 class="title">用例生成</h1>
      <p class="lede">输入需求 → 自动生成符合 <code>import ssd_tool</code> 规范的 pytest 脚本</p>
      <span class="badge">P1 计划中 · 预计 3 周</span>

      <div class="bar-row">
        <div class="bar"><div class="fill" style="width: 9%"></div></div>
        <span class="pct">1 / 11 步</span>
      </div>

      <ul class="plan">
        <li>spec 入口: 引用 spec 章节生成断言</li>
        <li>log 入口: 解析历史失败模式生成回归</li>
        <li>模板入口: 选模板 → 填参数 → 出 pytest</li>
        <li>MCP 集成: 用例可直连 RAGFlow 查 spec 切片</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.uc { display: flex; justify-content: center; padding: 24px 0; }
.box {
  width: 100%; max-width: 680px;
  padding: 40px 44px;
  text-align: center;
  display: flex; flex-direction: column; align-items: center;
}
.ico {
  width: 64px; height: 64px;
  display: grid; place-items: center;
  background: var(--primary-soft); color: var(--primary);
  border-radius: var(--radius-lg);
  margin-bottom: 20px;
}
.title { font-size: 26px; font-weight: 700; margin: 0 0 8px; color: var(--ink-900); letter-spacing: -0.2px; }
.lede { font-size: 14px; color: var(--ink-500); margin: 0 0 16px; }
.lede code {
  font-family: var(--font-mono); font-size: 13px;
  background: var(--surface-sunken); padding: 1px 6px; border-radius: var(--radius-sm);
  color: var(--ink-700);
}
.badge {
  font-size: 11.5px; font-weight: 500;
  padding: 4px 12px; border-radius: var(--radius-pill);
  background: var(--primary-soft); color: var(--primary);
  margin-bottom: 24px;
}
.bar-row { display: flex; align-items: center; gap: 12px; width: 100%; max-width: 420px; margin-bottom: 24px; }
.bar { flex: 1; height: 6px; background: var(--surface-sunken); border-radius: var(--radius-pill); overflow: hidden; }
.fill { height: 100%; background: var(--primary-grad); border-radius: var(--radius-pill); }
.pct { font-size: 11.5px; color: var(--ink-500); font-family: var(--font-mono); }
.plan { list-style: none; padding: 0; margin: 0; width: 100%; max-width: 460px; text-align: left; }
.plan li {
  font-size: 13.5px; color: var(--ink-700);
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}
.plan li:last-child { border-bottom: none; }
.plan li::before {
  content: '›';
  color: var(--primary);
  font-weight: 700;
  margin-right: 8px;
}
</style>
