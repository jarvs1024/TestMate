<template>
  <UnderConstruction
    title="环境运维"
    lede="机台三道闸:互斥锁 + 指令白名单 + 二次确认,防止 AI 幻觉炸机。机台状态实时监控,长任务流异步回报 stdout。"
    :plan="plan"
  />
</template>

<script setup lang="ts">
import UnderConstruction from '@/components/UnderConstruction.vue';

const plan = [
  'machine_locks 表 + Redis 分布式锁,双写防并发',
  'command_whitelist: 机台指令白名单,只放行已知安全命令',
  'paramiko SSH: 中台直连机台,执行测试脚本',
  '二次确认 UI: 高危命令必须人工确认才下发',
  '实时 stdout 回报: 异步 worker + SSE 流式回传',
];
</script>
