<template>
  <footer class="tm-footer">
    <div class="foot-row">
      <span class="ft-lbl">📡 数据 / 工具</span>
      <div v-for="s in services" :key="s.key" class="src">
        <span class="dot" :class="`s-${s.status}`"></span>
        <span class="name">{{ s.label }}</span>
        <span class="state">{{ s.statusText }}</span>
      </div>
      <span class="ft-spacer"></span>
      <span class="ft-ts">每 30s 心跳 · 最后检查 {{ lastCheck }}</span>
    </div>
  </footer>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue';
import axios from 'axios';

interface ServiceHealth { key: string; label: string; status: 'ok' | 'warn' | 'off' | 'unknown'; statusText: string }
const services = ref<ServiceHealth[]>([
  { key: 'ragflow',  label: 'RAGFlow',  status: 'unknown', statusText: '...' },
  { key: 'dify',     label: 'Dify',     status: 'unknown', statusText: '...' },
  { key: 'fwlib',    label: 'FW 库',    status: 'unknown', statusText: '...' },
  { key: 'machines', label: '机台',     status: 'unknown', statusText: '...' },
  { key: 'dingtalk', label: '钉钉通道', status: 'unknown', statusText: '...' },
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
  } catch {
    setSvc('ragflow', 'off');
    setSvc('dify', 'off');
  }
  try {
    const tok = localStorage.getItem('testmate:token');
    const { data } = await axios.get('/api/v1/machines', {
      headers: { Authorization: `Bearer ${tok}` },
    });
    const ms = data.machines || [];
    if (ms.length === 0) setSvc('machines', 'off', '0 台');
    else {
      const online = ms.filter((m: any) => m.status === 'online').length;
      setSvc('machines', online > 0 ? 'ok' : 'warn', `${online}/${ms.length} 在线`);
    }
  } catch { setSvc('machines', 'off'); }

  // 简化: 钉钉/FW 库 健康 (P1 实现真实检测)
  setSvc('fwlib', 'ok', 'P1');
  setSvc('dingtalk', 'ok', 'P1');

  const d = new Date();
  lastCheck.value = `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
}

onMounted(() => { poll(); pollTimer = window.setInterval(poll, 30_000); });
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer); });
</script>

<style scoped>
.tm-footer {
  flex-shrink: 0;
  padding: 0 24px 12px;
}
.foot-row {
  display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
  background: var(--surface-soft);
  backdrop-filter: blur(8px);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 14px;
  box-shadow: var(--shadow-sm);
  font-size: 11.5px;
}
.ft-lbl { font-size: 11px; color: var(--ink-500); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.src { display: inline-flex; align-items: center; gap: 6px; }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.s-ok { background: var(--ok); box-shadow: 0 0 0 2px rgba(22, 163, 74, 0.18); }
.s-warn { background: var(--warn); box-shadow: 0 0 0 2px rgba(217, 119, 6, 0.18); }
.s-off { background: var(--err); box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.18); }
.s-unknown { background: var(--ink-500); }
.name { color: var(--ink-700); }
.state { color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
.ft-spacer { flex: 1; }
.ft-ts { color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
</style>
