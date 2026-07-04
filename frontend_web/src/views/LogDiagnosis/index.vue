<template>
  <div class="ld">
    <header class="page-head">
      <div>
        <h1 class="title">日志分析</h1>
        <p class="sub">上传 log · AI 提取 assert · 三段式根因</p>
      </div>
      <div class="head-actions">
        <span class="badge">DIFY_MOCK</span>
        <el-button @click="onLoadSample" plain>填入示例</el-button>
        <el-button @click="onClear" plain>清空</el-button>
      </div>
    </header>

    <div class="grid">
      <section class="pane">
        <div class="lbl">环境变量 (可选)</div>
        <el-input
          v-model="environment"
          type="textarea"
          :rows="3"
          placeholder='{"firmware": "v1.2.3", "nand": "Micron B47R"}'
        />
        <div class="lbl mt">log 内容</div>
        <el-input
          v-model="logContent"
          type="textarea"
          :rows="14"
          placeholder="粘贴 PCIe trace / 串口 log / kernel log…"
          class="mono"
        />
        <div class="actions">
          <el-button
            type="primary"
            :loading="diagnosing"
            :disabled="!logContent.trim()"
            @click="onDiagnose"
          >开始诊断</el-button>
        </div>
      </section>

      <section class="terminal">
        <div class="t-head">
          <span>输出</span>
          <span v-if="diagnosing" class="ok">● 流式</span>
          <span v-else-if="result" class="dim">已完成</span>
          <span v-else class="dim">待发起</span>
        </div>
        <pre class="t-body">{{ result || '// 诊断结果会流式渲染到这里' }}</pre>
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
        } catch { /* ignore */ }
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
.ld { display: flex; flex-direction: column; gap: 16px; height: 100%; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.title { font-size: 18px; font-weight: 600; margin: 0; color: var(--ink-900); }
.sub { font-size: 12.5px; color: var(--ink-500); margin: 2px 0 0; }
.head-actions { display: flex; gap: 8px; align-items: center; }
.badge {
  font-size: 10.5px; padding: 2px 7px; border: 1px solid var(--border);
  border-radius: 3px; color: var(--ink-500);
  font-family: var(--font-mono);
  letter-spacing: 0.3px;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.pane, .terminal {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.pane { padding: 16px 18px; gap: 4px; }
.lbl { font-size: 11.5px; color: var(--ink-500); font-weight: 500; margin-bottom: 6px; }
.lbl.mt { margin-top: 12px; }
.mono :deep(textarea) { font-family: var(--font-mono); font-size: 12px; }
.actions { margin-top: 14px; }

.terminal { background: var(--code-bg); border-color: var(--code-bg); }
.t-head {
  padding: 8px 14px;
  font-size: 11.5px;
  color: var(--ink-500);
  border-bottom: 1px solid #1e293b;
  display: flex; gap: 8px; align-items: center;
}
.t-head .ok { color: #34D399; }
.t-head .dim { color: #64748B; }
.t-body {
  flex: 1; margin: 0;
  padding: 16px 18px;
  color: #6EE7B7;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  overflow: auto;
}
.t-err {
  padding: 8px 14px;
  background: rgba(244, 63, 94, 0.1);
  color: #FDA4AF;
  font-family: var(--font-mono);
  font-size: 12px;
  border-top: 1px solid rgba(244, 63, 94, 0.3);
}
</style>
