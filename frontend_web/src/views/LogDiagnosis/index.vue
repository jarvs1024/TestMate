<template>
  <div class="ld">
    <h1 class="title">日志分析</h1>
    <p class="lede">上传 log · AI 提取 assert · 三段式根因结论 (DIFY_MOCK)</p>

    <div class="card">
      <h2><span>输入</span> <span class="badge">P0 demo</span></h2>
      <div class="field">
        <label>环境变量 <span class="hint">— JSON, 选填, 提升准确度</span></label>
        <textarea v-model="environment" rows="3" placeholder='{"firmware": "v1.2.3", "nand": "Micron B47R"}'></textarea>
      </div>
      <div class="field">
        <label>log 内容 <span class="req">*</span></label>
        <textarea v-model="logContent" rows="14" placeholder="粘贴 PCIe trace / 串口 log / kernel log…" class="mono"></textarea>
      </div>

      <div class="row" style="margin-top: 4px">
        <button class="primary" :disabled="!logContent.trim() || diagnosing" @click="onDiagnose">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg>
          <span>{{ diagnosing ? '诊断中…' : '开始诊断' }}</span>
        </button>
        <button class="secondary" @click="onLoadSample">填入示例</button>
        <button class="secondary" @click="onClear">清空</button>
      </div>
    </div>

    <div class="card">
      <h2><span>输出</span>
        <span class="badge" v-if="diagnosing">流式中</span>
        <span class="badge done" v-else-if="result">已完成</span>
        <span class="badge" v-else>待发起</span>
      </h2>
      <pre class="terminal">{{ result || '// 点击「开始诊断」,AI 结论会流式渲染到这里' }}</pre>
      <div v-if="error" class="err">❌ {{ error }}</div>
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
.ld { display: flex; flex-direction: column; gap: 18px; }
.title { font-size: 30px; font-weight: 800; margin: 0 0 10px; letter-spacing: -0.4px; color: var(--ink-900); }
.lede { color: var(--ink-700); margin: 0 0 24px; font-size: 14.5px; }

h2 { font-size: 15px; font-weight: 700; margin: 0 0 14px; display: flex; align-items: center; gap: 8px; }
.badge {
  font-size: 10.5px; font-weight: 600;
  padding: 2px 8px; border-radius: var(--radius-pill);
  background: var(--primary-soft); color: var(--primary);
}
.badge.done { background: rgba(22, 163, 74, 0.12); color: var(--ok); }

.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.field label { font-size: 12.5px; color: var(--ink-700); font-weight: 500; }
.field .hint { font-size: 11.5px; color: var(--ink-500); }
.field textarea {
  width: 100%; padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink-900);
  font-size: 13px;
  font-family: inherit;
  resize: vertical; min-height: 64px;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.field textarea:focus {
  outline: none; border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}
.field .mono { font-family: var(--font-mono); font-size: 12.5px; }
.req { color: var(--err); }

.row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.row > * { flex: 0 0 auto; min-width: 0; }

button.primary {
  background: var(--primary); color: #fff; border: 0;
  padding: 9px 18px; border-radius: 9px;
  font-size: 13.5px; font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px;
  transition: transform .05s ease, box-shadow .15s ease, background .15s ease;
}
button.primary:hover:not(:disabled) { box-shadow: 0 4px 12px rgba(28, 100, 242, 0.3); }
button.primary:active:not(:disabled) { transform: translateY(1px); }
button.primary:disabled { opacity: 0.5; cursor: not-allowed; }

button.secondary {
  background: var(--surface-soft);
  color: var(--ink-700);
  border: 1px solid var(--border);
  padding: 9px 14px;
  border-radius: 9px;
  font-size: 13px; font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: border-color .15s ease, color .15s ease;
}
button.secondary:hover { border-color: var(--border-strong); color: var(--ink-900); }

.terminal {
  background: var(--code-bg);
  color: var(--code-text);
  padding: 16px 18px;
  border-radius: 8px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  max-height: 480px;
  overflow: auto;
}

.err {
  margin-top: 10px;
  background: rgba(220, 38, 38, 0.06);
  border: 1px solid rgba(220, 38, 38, 0.25);
  border-radius: 8px;
  padding: 10px 12px;
  color: var(--err);
  font-size: 12.5px;
  font-family: var(--font-mono);
  white-space: pre-wrap;
}
</style>
