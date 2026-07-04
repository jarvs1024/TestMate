<template>
  <UnderConstruction
    title="测试方案生成"
    lede="需求 → 完整测试方案:覆盖矩阵 + 用例清单 + 风险点 + 机台分配建议,产出可评审的 Markdown 报告。"
    :plan="plan"
  />
</template>

<script setup lang="ts">
import UnderConstruction from '@/components/UnderConstruction.vue';

const plan = [
  '需求解析: 从 PRD / issue / 邮件抽取验收点',
  '覆盖矩阵: 按 spec 章节 × 风险等级自动展开',
  '用例清单: 联动用例生成模块,引用已生成的 pytest',
  '机台分配: 根据机台状态 + 用例时长智能调度',
  '评审导出: 一键导出 Markdown 报告,内嵌 spec 引用',
];
</script>
