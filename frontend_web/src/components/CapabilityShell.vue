<template>
  <div class="cap-shell">
    <button class="back" type="button" @click="goHome">← 返回工作台</button>
    <span class="sh-div" aria-hidden="true"></span>

    <div class="sh-icon">{{ icon }}</div>
    <div class="sh-text">
      <span class="sh-name">{{ name }}</span>
      <span v-if="version" class="sh-ver">{{ version }}</span>
    </div>

    <span class="sh-kind">{{ kindMeta(kind).icon }} {{ kindMeta(kind).label }}</span>
    <span class="sh-dot">·</span>
    <span class="sh-cat">{{ categoryLabel(category) }}</span>

    <div class="sh-badge" :class="`st-${status}`">
      <span class="dot"></span>{{ statusLabel(kind, status) }}
    </div>

    <div v-if="$slots.actions" class="sh-actions"><slot name="actions" /></div>
  </div>
</template>

<script setup lang="ts">
/**
 * 能力详情页的统一外壳 (头部) —— **一行身份条**.
 *
 * 为什么需要 (2026-10-25):
 *   重构前三个详情页各写各的头部 —— AgentRunner 叫 `.run-hd`, 代码检视抄了一份,
 *   资产市场只有一个"← 返回广场"按钮, 知识库页干脆没有头部.
 *   卡片不再都是智能体之后, 详情页长得不一样会让用户怀疑"是不是进了另一个系统".
 *   现在四个详情页共用这一个头: 返回 / 图标 / 名称 / 角色 / 状态 / 右侧动作.
 *
 * ⚠️ 为什么**没有描述行** (2026-10-25 第四轮):
 *   原来外壳底部还有一行 summary, 但页头 (AppHeader) 已经有 lede 了 ——
 *   两行说的是同一句话的两种写法 (例: 资产市场 lede "能力的技能沉淀 —— …"
 *   vs summary "团队共享的插件 / 技能 / 连接器 —— …"), 用户看着只觉得啰嗦.
 *   现在分工明确:
 *     · 页头 (AppHeader) = **页面级**: 这是什么页面 + 一句话说明
 *     · 本外壳 = **能力级**: 这是哪项能力 + 什么角色 + 现在能不能用 + 能做什么操作
 *   描述归位到正文 (工具型的 summary 放在参数配置卡顶部), 一律不在外壳重复。
 *   顺带把两行压成一行 —— 正文能多出 ~40px。
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
  version?: string;
  /** 业务域标签 (跟角色正交) */
  category?: string;
}>(), {
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
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 8px 12px;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  box-shadow: var(--shadow-sm);
  margin-bottom: 10px;
}
.back {
  background: transparent; border: 1px solid var(--border);
  padding: 5px 11px; border-radius: var(--radius-btn);
  font-size: 12.5px; color: var(--ink-700); cursor: pointer;
  font-family: inherit; transition: all .15s ease;
  flex-shrink: 0;
}
.back:hover { border-color: var(--primary); color: var(--ink-900); }

/* 返回键与身份之间的竖分隔 —— 把"去哪儿"跟"这是啥"分开 */
.sh-div { width: 1px; height: 22px; background: var(--border); flex-shrink: 0; }

.sh-icon {
  width: 32px; height: 32px; border-radius: 9px;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; flex-shrink: 0;
  box-shadow: var(--primary-shadow);
}
.sh-text { display: flex; align-items: baseline; gap: 7px; min-width: 0; }
.sh-name { font-size: 15px; font-weight: 700; color: var(--ink-900); line-height: 1.2; white-space: nowrap; }
.sh-ver { font-size: 11px; color: var(--ink-500); font-family: var(--font-mono); }

.sh-kind { font-size: 11.5px; color: var(--primary-2); font-weight: 600; white-space: nowrap; }
.sh-dot { opacity: .45; }
.sh-cat { font-size: 11.5px; color: var(--ink-500); font-family: var(--font-mono); white-space: nowrap; }

.sh-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 8px; border-radius: var(--radius-pill);
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
</style>
