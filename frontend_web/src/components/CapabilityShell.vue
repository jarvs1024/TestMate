<template>
  <div class="cap-shell">
    <button class="back" type="button" @click="goHome">← 返回工作台</button>

    <div class="sh-title">
      <div class="sh-icon">{{ icon }}</div>
      <div class="sh-text">
        <div class="sh-name">
          <span>{{ name }}</span>
          <span v-if="version" class="sh-ver">{{ version }}</span>
        </div>
        <div class="sh-sub">
          <span class="sh-kind">{{ kindMeta(kind).icon }} {{ kindMeta(kind).label }}</span>
          <span class="sh-dot">·</span>
          <span class="sh-cat">{{ categoryLabel(category) }}</span>
        </div>
      </div>
    </div>

    <div class="sh-badge" :class="`st-${status}`">
      <span class="dot"></span>{{ statusLabel(kind, status) }}
    </div>

    <div v-if="$slots.actions" class="sh-actions"><slot name="actions" /></div>

    <p v-if="summary" class="sh-summary">{{ summary }}</p>
  </div>
</template>

<script setup lang="ts">
/**
 * 能力详情页的统一外壳 (头部).
 *
 * 为什么需要 (2026-10-25):
 *   重构前三个详情页各写各的头部 —— AgentRunner 叫 `.run-hd`, 代码检视抄了一份,
 *   资产市场只有一个"← 返回广场"按钮, 知识库页干脆没有头部.
 *   卡片不再都是智能体之后, 详情页长得不一样会让用户怀疑"是不是进了另一个系统".
 *   现在四个详情页共用这一个头: 返回 / 图标 / 名称 / 角色 / 状态 / 一句话 / 右侧动作.
 *
 * ⚠️ 外壳**不自己取数** —— 由页面把自己已知的 name/icon/kind/status 传进来.
 *   免得每个详情页都多打一次接口, 也免得外壳和页面的数据打架.
 */
import { useRouter } from 'vue-router';
import { categoryLabel, kindMeta, statusLabel, type CapabilityKind } from '@/constants/capabilityKinds';

withDefaults(defineProps<{
  name: string;
  icon: string;
  kind: CapabilityKind | string;
  status: string;
  summary?: string;
  version?: string;
  /** 业务域标签 (跟角色正交) */
  category?: string;
}>(), {
  summary: '',
  version: '',
  category: '',
});

const router = useRouter();

function goHome() {
  router.push({ name: 'home' });
}
</script>

<style scoped>
.cap-shell {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 10px 14px;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  box-shadow: var(--shadow-sm);
  margin-bottom: 14px;
}
.back {
  background: transparent; border: 1px solid var(--border);
  padding: 6px 12px; border-radius: var(--radius-btn);
  font-size: 12.5px; color: var(--ink-700); cursor: pointer;
  font-family: inherit; transition: all .15s ease;
}
.back:hover { border-color: var(--primary); color: var(--ink-900); }

.sh-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.sh-icon {
  width: 36px; height: 36px; border-radius: 10px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; flex-shrink: 0;
  box-shadow: var(--primary-shadow);
}
.sh-text { min-width: 0; }
.sh-name { display: flex; align-items: baseline; gap: 8px; }
.sh-name > span:first-child { font-size: 16px; font-weight: 700; color: var(--ink-900); line-height: 1.2; }
.sh-ver { font-size: 11px; color: var(--ink-500); font-family: var(--font-mono); }
.sh-sub {
  font-size: 11.5px; color: var(--ink-500); margin-top: 2px;
  font-family: var(--font-mono);
  display: flex; align-items: center; gap: 5px;
}
.sh-kind { color: var(--primary-2); font-weight: 600; }
.sh-dot { opacity: .5; }

.sh-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 8px; border-radius: var(--radius-pill);
  font-size: 10.5px; font-weight: 600;
  background: var(--surface-sunken); color: var(--ink-700);
  flex-shrink: 0;
}
.sh-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.st-stable { background: rgba(16, 185, 129, .12); color: var(--ok); }
.st-beta { background: rgba(245, 158, 11, .12); color: var(--warn); }
.st-alpha { background: rgba(245, 158, 11, .14); color: var(--warn); }
.st-draft { background: var(--surface-sunken); color: var(--ink-500); }
.st-deprecated { background: rgba(239, 68, 68, .10); color: var(--err); }

.sh-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; }

.sh-summary {
  flex-basis: 100%; margin: 0;
  font-size: 12.5px; color: var(--ink-500); line-height: 1.5;
}
</style>
