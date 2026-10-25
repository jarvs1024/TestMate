<template>
  <div class="foot">
    <div class="ft-lbl">📡 数据 / 工具</div>
    <div v-for="s in services" :key="s.key" class="src" v-show="s.visible !== false">
      <span class="dot" :class="`s-${s.status}`"></span>
      <span class="name">{{ s.label }}</span>
      <span class="state">{{ s.statusText }}</span>
    </div>
    <div class="ft-ts">每 30s 心跳 · {{ lastCheck }}</div>
  </div>
</template>

<script setup lang="ts">
/**
 * 服务状态面板 —— 侧栏下半部分.
 *
 * 为什么单独拆出来 (2026-10-25):
 *   侧栏现在有两件互不相干的事 —— "去哪儿" (能力导航) 和 "后台怎么样" (服务状态).
 *   拆开之后各自职责单一, 服务状态这块以后加监控指标也不用碰导航.
 *
 * ⚠️ ReviewAgent 默认隐藏 —— 没配 base_url 时显示"未配置"会误导人.
 */
import { onMounted, onUnmounted, ref } from 'vue';
import axios from 'axios';

interface ServiceHealth {
  key: string;
  label: string;
  status: 'ok' | 'warn' | 'off' | 'unknown';
  statusText: string;
  visible?: boolean;
}

const services = ref<ServiceHealth[]>([
  { key: 'ragflow', label: 'RAGFlow', status: 'unknown', statusText: '...' },
  { key: 'dify', label: 'Dify', status: 'unknown', statusText: '...' },
  // ReviewAgent (代码检视唯一后端) — 默认隐藏, 配过 base_url 才显示
  { key: 'review_agent', label: 'ReviewAgent', status: 'off', statusText: '未配置', visible: false },
]);
const lastCheck = ref('—');
let pollTimer: number | null = null;

function setSvc(key: string, st: 'ok' | 'warn' | 'off', txt?: string) {
  const i = services.value.findIndex((s) => s.key === key);
  if (i < 0) return;
  services.value[i].status = st;
  const map: Record<string, string> = { ok: '正常', warn: '部分', off: '未配置' };
  services.value[i].statusText = txt || map[st] || '未知';
}

async function poll() {
  try {
    const { data } = await axios.get('/api/v1/health/services');
    setSvc('ragflow', data.ragflow);
    setSvc('dify', data.dify);
    // ReviewAgent (代码检视): 服务未返回字段 → 视为未配置
    const ra = data.review_agent || 'off';
    const raMap: Record<string, string> = { ok: '正常', warn: '部分', off: '未配置' };
    const i = services.value.findIndex((x) => x.key === 'review_agent');
    if (i >= 0) {
      services.value[i].status = ra;
      services.value[i].statusText = raMap[ra] || '未知';
      // 配过 (状态非 'off') 才显示, 未配时隐藏避免误导
      services.value[i].visible = ra !== 'off';
    }
  } catch {
    setSvc('ragflow', 'off');
    setSvc('dify', 'off');
  }
  const d = new Date();
  lastCheck.value = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

onMounted(() => { poll(); pollTimer = window.setInterval(poll, 30_000); });
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer); });
</script>

<style scoped>
.foot {
  margin-top: auto;
  padding: 12px;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: 10px;
  box-shadow: var(--shadow-sm);
  display: flex; flex-direction: column; gap: 6px;
  font-size: 11.5px;
}
.ft-lbl { font-size: 10.5px; color: var(--ink-500); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; }
.src { display: flex; align-items: center; gap: 7px; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.s-ok { background: var(--ok); box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.18); }
.s-warn { background: var(--warn); box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.18); }
.s-off { background: var(--err); box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.18); }
.s-unknown { background: var(--ink-500); }
.name { flex: 1; color: var(--ink-700); }
.state { color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
.ft-ts { margin-top: 4px; padding-top: 6px; border-top: 1px dashed var(--border); color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
</style>
