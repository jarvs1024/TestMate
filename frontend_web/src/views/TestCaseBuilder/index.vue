<template>
  <div class="uc">
    <header class="page-head">
      <h1 class="title">用例生成</h1>
      <p class="sub">需求 → 符合 <code>import ssd_tool</code> 规范的 pytest 脚本</p>
    </header>
    <div class="bar-row">
      <span class="lbl">P1 计划中</span>
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
</template>

<style scoped>
.uc { max-width: 720px; padding: 0; }
.page-head { margin-bottom: 20px; }
.title { font-size: 18px; font-weight: 600; margin: 0; color: var(--ink-900); }
.sub { font-size: 13px; color: var(--ink-500); margin: 4px 0 0; }
.sub code {
  font-family: var(--font-mono); font-size: 12px;
  background: var(--bg-hover); padding: 1px 5px; border-radius: 3px;
  color: var(--ink-700);
}

.bar-row { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.lbl { font-size: 12px; color: var(--ink-500); }
.bar { flex: 1; height: 4px; background: var(--bg-hover); border-radius: 2px; overflow: hidden; }
.fill { height: 100%; background: var(--primary); }
.pct { font-size: 11.5px; color: var(--ink-500); font-family: var(--font-mono); }

.plan { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.plan li { font-size: 13px; color: var(--ink-700); padding: 6px 0; border-bottom: 1px solid var(--border); }
.plan li:last-child { border-bottom: none; }
</style>
