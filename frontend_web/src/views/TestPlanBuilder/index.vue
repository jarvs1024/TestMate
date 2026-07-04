<template>
  <div class="uc">
    <header class="page-head">
      <h1 class="title">测试方案</h1>
      <p class="sub">需求 → 覆盖矩阵 + 用例清单 + 风险点 + 机台分配</p>
    </header>
    <div class="bar-row">
      <span class="lbl">P1 计划中</span>
      <div class="bar"><div class="fill" style="width: 9%"></div></div>
      <span class="pct">1 / 11 步</span>
    </div>
    <ul class="plan">
      <li>需求解析: 从 PRD / issue / 邮件抽取验收点</li>
      <li>覆盖矩阵: spec 章节 × 风险等级自动展开</li>
      <li>用例清单: 联动用例生成模块</li>
      <li>机台分配: 按机台状态智能调度</li>
      <li>评审导出: 一键 Markdown 报告</li>
    </ul>
  </div>
</template>

<style scoped>
.uc { max-width: 720px; padding: 0; }
.page-head { margin-bottom: 20px; }
.title { font-size: 18px; font-weight: 600; margin: 0; color: var(--ink-900); }
.sub { font-size: 13px; color: var(--ink-500); margin: 4px 0 0; }
.bar-row { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; }
.lbl { font-size: 12px; color: var(--ink-500); }
.bar { flex: 1; height: 4px; background: var(--bg-hover); border-radius: 2px; overflow: hidden; }
.fill { height: 100%; background: var(--primary); }
.pct { font-size: 11.5px; color: var(--ink-500); font-family: var(--font-mono); }
.plan { list-style: none; padding: 0; margin: 0; }
.plan li { font-size: 13px; color: var(--ink-700); padding: 6px 0; border-bottom: 1px solid var(--border); }
.plan li:last-child { border-bottom: none; }
</style>
