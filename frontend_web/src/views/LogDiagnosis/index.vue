<template>
  <div class="ld">
    <header class="head">
      <div>
        <h1 class="title">日志分析</h1>
        <p class="sub">上传 log · AI 提取 assert · 三段式根因结论 (DIFY_MOCK)</p>
      </div>
      <div class="actions">
        <el-button @click="onLoadSample" plain>
          <span class="btn-row">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
            填入示例
          </span>
        </el-button>
        <el-button @click="onClear" plain>
          <span class="btn-row">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
            清空
          </span>
        </el-button>
      </div>
    </header>

    <div class="grid">
      <section class="pane card">
        <div class="sec-h">
          <span>输入</span>
          <span class="hint">环境变量选填,提升准确度</span>
        </div>

        <div class="field">
          <label class="lbl">环境变量</label>
          <el-input v-model="environment" type="textarea" :rows="3" placeholder='{"firmware": "v1.2.3", "nand": "Micron B47R"}' />
        </div>

        <div class="field">
          <label class="lbl">log 内容 <span class="req">*</span></label>
          <el-input v-model="logContent" type="textarea" :rows="14" placeholder="粘贴 PCIe trace / 串口 log / kernel log…" class="mono" />
        </div>

        <button class="primary" :disabled="!logContent.trim() || diagnosing" @click="onDiagnose">
          <svg v-if="!diagnosing" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/>
          </svg>
          <span v-if="diagnosing">诊断中…</span>
          <span v-else>开始诊断</span>
        </button>
      </section>

      <section class="terminal card">
        <div class="t-h">
          <span>输出</span>
          <span v-if="diagnosing" class="s-live"><span class="d"></span>流式中</span>
          <span v-else-if="result" class="s-done">已完成</span>
          <span v-else class="s-idle">待发起</span>
        </div>
        <pre class="t-body">{{ result || '// 点击「开始诊断」,AI 结论会流式渲染到这里' }}</pre>
        <div v-if="error" class="t-err">❌ {{ error }}</div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { ElMessage } from 'element-plus';

const environment = ref('');
const logContent = ref('');
const result = ref('');
const error = ref('');
const diagnosing = ref(false);

async function onDiagnose() {
  if (!logContent.value.trim()) {
    ElMessage.warning('请输入 log');
    return;
  }
  result.value = '';
  error.value = '';
  diagnosing.value = true;
  try {
    const resp = await fetch('/api/v1/diagnose/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('testmate:token') || ''}`,
      },
      body: JSON.stringify({
        log_content: logContent.value,
        environment: parseEnv(environment.value),
        dataset: '',
      }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const reader = resp.body?.getReader();
    const decoder = new TextDecoder();
    if (!reader) throw new Error('无响应流');
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value);
      for (const line of chunk.split('\n\n')) {
        if (!line.startsWith('data:')) continue;
        const json = line.slice(5).trim();
        if (!json || json === '[DONE]') continue;
        try {
          const ev = JSON.parse(json);
          if (ev.type === 'error') error.value += ev.content + '\n';
          else if (ev.content) result.value += ev.content;
        } catch { /* */ }
      }
    }
  } catch (e: any) {
    error.value = e.message || '请求出错';
  } finally {
    diagnosing.value = false;
  }
}

function parseEnv(t: string): Record<string, any> {
  if (!t.trim()) return {};
  try { return JSON.parse(t); } catch { return { raw: t }; }
}

function onClear() { logContent.value = ''; result.value = ''; error.value = ''; }
function onLoadSample() {
  environment.value = '{"firmware":"v1.2.3","nand":"Micron B47R"}';
  logContent.value = `[ 1234.567890] pcieport 0000:01:00.0: PCIe link down
[ 1234.568001] nvme nvme0: Removing after probe failure status: -19
[ 1234.580000] BICS8 FW assert 0xE0A1 at pcie_link.c:245
[ 1234.581000] nvme0: PCI device unresponsive
[ 1235.100000] kernel: I/O error, dev nvme0, sector 12345678`;
}
</script>

<style scoped>
.ld { display: flex; flex-direction: column; gap: 20px; height: 100%; }
.head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.title { font-size: 28px; font-weight: 700; margin: 0; color: var(--ink-900); letter-spacing: -0.4px; }
.sub { font-size: 13.5px; color: var(--ink-500); margin: 4px 0 0; }
.actions { display: flex; gap: 8px; }
.btn-row { display: inline-flex; align-items: center; gap: 6px; }

.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; flex: 1; min-height: 0; }
.pane, .terminal { min-height: 0; display: flex; flex-direction: column; }

.pane { padding: 20px 24px; gap: 14px; }
.sec-h { display: flex; justify-content: space-between; align-items: baseline; padding-bottom: 4px; }
.sec-h > span:first-child { font-size: 15px; font-weight: 600; color: var(--ink-900); }
.hint { font-size: 11.5px; color: var(--ink-500); }

.field { display: flex; flex-direction: column; }
.lbl { font-size: 12.5px; color: var(--ink-700); font-weight: 500; margin-bottom: 6px; }
.req { color: var(--primary); }
.mono :deep(textarea) { font-family: var(--font-mono); font-size: 12.5px; }

.primary {
  margin-top: 6px;
  height: 44px;
  display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  background: var(--primary-grad);
  color: #fff;
  border: none;
  border-radius: var(--radius-md);
  font-size: 14px; font-weight: 600;
  cursor: pointer;
  box-shadow: var(--primary-shadow);
  transition: filter .15s ease, transform .05s ease;
  font-family: inherit;
}
.primary:hover:not(:disabled) { filter: brightness(1.05); }
.primary:active:not(:disabled) { transform: scale(0.99); }
.primary:disabled { opacity: 0.5; cursor: not-allowed; }

.terminal { background: #0F172A; border-color: #0F172A; }
.t-h {
  padding: 12px 18px;
  font-size: 13px;
  color: #94A3B8;
  display: flex; gap: 12px; align-items: center;
  border-bottom: 1px solid #1E293B;
  background: #0B1220;
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}
.s-live { display: inline-flex; align-items: center; gap: 6px; color: #34D399; font-size: 12px; }
.s-live .d { width: 6px; height: 6px; border-radius: 50%; background: #34D399; animation: tm-pulse 1.6s ease-in-out infinite; }
.s-done { color: #34D399; font-size: 12px; }
.s-idle { color: #64748B; font-size: 12px; }
@keyframes tm-pulse { 0%, 100% { opacity: 1 } 50% { opacity: .4 } }

.t-body {
  flex: 1; margin: 0;
  padding: 18px 22px;
  color: #6EE7B7;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  overflow: auto;
}
.t-err {
  padding: 10px 18px;
  background: rgba(244, 63, 94, 0.12);
  color: #FDA4AF;
  font-family: var(--font-mono);
  font-size: 12px;
  border-top: 1px solid rgba(244, 63, 94, 0.3);
}
</style>
