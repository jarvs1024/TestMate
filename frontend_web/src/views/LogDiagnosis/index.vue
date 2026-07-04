<template>
  <div class="ld-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">
          日志分析
          <span class="tm-serif suffix">— Dify agent + mock</span>
        </h1>
        <p class="page-lede">
          上传 log → AI 提取 assert → 对比历史缺陷图谱 → 三段式根因结论
        </p>
      </div>
      <div class="head-actions">
        <span class="chip chip-demo">P0 Demo · DIFY_MOCK 模式</span>
      </div>
    </div>

    <div class="ld-grid">
      <!-- 左:输入 (PreviewWindow 包装) -->
      <PreviewWindow
        title="log-input"
        subtitle="粘贴 / 拖拽"
        class="input-pane"
      >
        <div class="pane-body">
          <label class="lbl">环境变量 (可选)</label>
          <el-input
            v-model="environment"
            type="textarea"
            :rows="3"
            placeholder='例:{"firmware": "v1.2.3", "nand": "Micron B47R"}'
          />

          <label class="lbl mt-4">log 内容 (必填)</label>
          <el-input
            v-model="logContent"
            type="textarea"
            :rows="14"
            placeholder="粘贴 PCIe trace / 串口 log / kernel log…"
            class="tm-mono"
          />

          <div class="actions">
            <el-button
              type="primary"
              :loading="diagnosing"
              :disabled="!logContent.trim()"
              @click="onDiagnose"
            >🚀 开始诊断</el-button>
            <el-button @click="onClear">清空</el-button>
            <el-button @click="onLoadSample">填入示例</el-button>
          </div>
        </div>
      </PreviewWindow>

      <!-- 右:输出 (深色终端 + PreviewWindow) -->
      <PreviewWindow
        title="ai-stream"
        subtitle="DIFY_MOCK"
        class="output-pane"
      >
        <template #actions>
          <span v-if="diagnosing" class="status-pill is-live">● 流式中</span>
          <span v-else-if="result" class="status-pill is-done">✓ 已完成</span>
          <span v-else class="status-pill is-idle">○ 待发起</span>
        </template>

        <div class="terminal">
          <pre class="terminal-body">{{ result || '// 点击「开始诊断」,AI 结论会流式渲染到这里…' }}</pre>
          <div v-if="error" class="terminal-err">❌ {{ error }}</div>
        </div>
      </PreviewWindow>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import request from '@/utils/request';
import PreviewWindow from '@/components/PreviewWindow.vue';

const environment = ref('');
const logContent = ref('');
const result = ref('');
const error = ref('');
const diagnosing = ref(false);

async function onDiagnose() {
  if (!logContent.value.trim()) {
    ElMessage.warning('请输入 log 内容');
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
    if (!resp.ok) {
      const t = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${t}`);
    }
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

function parseEnv(text: string): Record<string, any> {
  if (!text.trim()) return {};
  try { return JSON.parse(text); } catch { return { raw: text }; }
}

function onClear() {
  logContent.value = '';
  result.value = '';
  error.value = '';
}

function onLoadSample() {
  environment.value = '{"firmware":"v1.2.3","nand":"Micron B47R"}';
  logContent.value = `[ 1234.567890] pcieport 0000:01:00.0: PCIe link down
[ 1234.568001] nvme nvme0: Removing after probe failure status: -19
[ 1234.580000] BICS8 FW assert 0xE0A1 at pcie_link.c:245
[ 1234.581000] nvme0: PCI device unresponsive
[ 1235.100000] kernel: I/O error, dev nvme0, sector 12345678`;
}

// 避免 lint 警告
void request;
</script>

<style scoped>
.ld-page { display: flex; flex-direction: column; gap: 16px; height: 100%; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.page-title { font-size: 24px; font-weight: 700; margin: 0; color: var(--ink-900); line-height: 1.2; }
.page-title .suffix { color: var(--ink-500); font-size: 18px; margin-left: 6px; }
.page-lede { font-size: 13.5px; color: var(--ink-500); margin: 4px 0 0; }
.head-actions { display: flex; gap: 8px; }

.chip {
  font-size: 11px; padding: 3px 10px; border-radius: 999px;
  border: 1px solid transparent;
  font-weight: 500; letter-spacing: 0.2px;
}
.chip-demo {
  background: var(--primary-soft);
  color: var(--primary);
}

.ld-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  flex: 1;
  min-height: 0;
}
.input-pane, .output-pane { min-height: 0; }
.pane-body { padding: 18px 20px; display: flex; flex-direction: column; gap: 4px; }
.lbl {
  display: block;
  font-size: 12.5px;
  color: var(--ink-500);
  font-weight: 500;
  margin-bottom: 6px;
}
.lbl.mt-4 { margin-top: 16px; }
.actions { display: flex; gap: 8px; margin-top: 16px; }

.status-pill {
  font-size: 11px; padding: 2px 8px; border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--ink-500);
}
.status-pill.is-live {
  background: var(--status-ok-soft); color: var(--status-ok);
  border-color: transparent;
  animation: tm-pulse 1.6s ease-in-out infinite;
}
.status-pill.is-done { color: var(--status-ok); }
@keyframes tm-pulse { 0%, 100% { opacity: 1 } 50% { opacity: .5 } }

.terminal {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--code-bg, #0f172a);
  min-height: 0;
}
.terminal-body {
  flex: 1;
  margin: 0;
  padding: 20px 24px;
  color: #6ee7b7;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  overflow: auto;
}
.terminal-err {
  padding: 10px 24px;
  background: rgba(244, 63, 94, 0.12);
  color: #fda4af;
  font-family: var(--font-mono);
  font-size: 12px;
  border-top: 1px solid rgba(244, 63, 94, 0.3);
}
</style>
