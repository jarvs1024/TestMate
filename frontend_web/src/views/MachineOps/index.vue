<template>
  <div class="uc">
    <h1 class="title">环境运维</h1>
    <p class="lede">机台三道闸:互斥锁 + 指令白名单 + 二次确认,防止 AI 幻觉炸机</p>

    <div class="card uc-card">
      <div class="ico">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>
        </svg>
      </div>
      <div class="title-2">环境运维 — P1 计划中</div>
      <div class="sub">机台字典 + 互斥锁 + 指令白名单,接入 P1 启动后</div>

      <div class="bar-row">
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
  </div>
</template>

<style scoped>
.uc { display: flex; flex-direction: column; gap: 0; }
.title { font-size: 30px; font-weight: 800; margin: 0 0 10px; letter-spacing: -0.4px; color: var(--ink-900); }
.lede { color: var(--ink-700); margin: 0 0 24px; font-size: 14.5px; }
.uc-card { display: flex; flex-direction: column; align-items: center; text-align: center; padding: 36px 32px; }
.ico { width: 64px; height: 64px; display: grid; place-items: center; background: var(--primary-soft); color: var(--primary); border-radius: 14px; margin-bottom: 18px; }
.title-2 { font-size: 20px; font-weight: 700; color: var(--ink-900); margin-bottom: 6px; }
.sub { font-size: 13.5px; color: var(--ink-500); margin-bottom: 24px; }
.bar-row { display: flex; align-items: center; gap: 12px; width: 100%; max-width: 420px; margin-bottom: 24px; }
.bar { flex: 1; height: 6px; background: var(--surface-sunken); border-radius: 3px; overflow: hidden; }
.fill { height: 100%; background: var(--primary); }
.pct { font-size: 11.5px; color: var(--ink-500); font-family: var(--font-mono); }
.plan { list-style: none; padding: 0; margin: 0; width: 100%; max-width: 460px; text-align: left; }
.plan li { font-size: 13.5px; color: var(--ink-700); padding: 10px 0; border-bottom: 1px solid var(--border); }
.plan li:last-child { border-bottom: none; }
.plan li::before { content: '›'; color: var(--primary); font-weight: 700; margin-right: 8px; }
</style>
