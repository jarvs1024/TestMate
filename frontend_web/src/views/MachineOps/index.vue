<template>
  <div class="uc">
    <header class="page-head">
      <h1 class="title">环境运维</h1>
      <p class="sub">机台三道闸:互斥锁 + 指令白名单 + 二次确认</p>
    </header>
    <div class="bar-row">
      <span class="lbl">P1 计划中</span>
      <div class="bar"><div class="fill" style="width: 9%"></div></div>
      <span class="pct">1 / 11 步</span>
    </div>
    <ul class="plan">
      <li>machine_locks 表 + Redis 分布式锁</li>
      <li>command_whitelist: 指令白名单</li>
      <li>paramiko SSH: 中台直连机台</li>
      <li>二次确认 UI: 高危命令人工把关</li>
      <li>实时 stdout 回报: 异步 worker + SSE</li>
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
