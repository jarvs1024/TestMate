<template>
  <UnderConstruction
    title="用例生成"
    lede="输入需求 → 自动生成符合 import ssd_tool 规范的 pytest 脚本,支持从 spec / log / 模板三种入口派生。"
    :plan="plan"
  />
</template>

<script setup lang="ts">
import UnderConstruction from '@/components/UnderConstruction.vue';

const plan = [
  'Spec 入口: 引用 spec 章节,生成断言脚本(基于 ssd_tool.spec.assert_*)',
  'Log 入口: 解析历史 log 失败模式,生成回归用例',
  '模板入口: 选模板 → 填参数 → 出可执行 pytest 文件',
  'MCP 集成: 用例可直连 RAGFlow 查 spec 切片',
];
</script>
