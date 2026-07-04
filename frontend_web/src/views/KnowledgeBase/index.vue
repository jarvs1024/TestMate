<template>
  <div class="kb">
    <h1 class="title">知识库检索</h1>
    <p class="lede">NVMe / JEDEC / 企业 spec · RAGFlow 索引 · 命中分段按相似度排序</p>

    <!-- 顶部控制卡 -->
    <div class="card">
      <h2><span>数据集</span> <span class="badge">{{ docs.length }} 个文档</span></h2>
      <div class="row">
        <div class="field" style="flex: 2">
          <label>API Key <span class="req">*</span> <span class="hint">— 在 RAGFlow 用户设置 → API Keys 生成</span></label>
          <input v-model="apiKey" type="text" placeholder="ragflow-xxxxxxxxxxxxxxxxxxxxxxxx" />
        </div>
        <div class="field" style="flex: 1">
          <label>代理 URL</label>
          <input v-model="proxyUrl" type="text" placeholder="http://127.0.0.1:8765" />
        </div>
      </div>
      <div class="row">
        <div class="field" style="flex: 2">
          <label>Dataset IDs <span class="hint">— 多个用逗号分隔, 留空则报清晰错误</span></label>
          <input v-model="datasetIds" type="text" placeholder="例如: d7d06bc3... 或留空试错" />
        </div>
        <div class="field" style="flex: 1">
          <label>Document IDs <span class="hint">— 可选, 逗号分隔</span></label>
          <input v-model="documentIds" type="text" placeholder="可选" />
        </div>
      </div>
    </div>

    <!-- 查询卡 -->
    <div class="card">
      <h2><span>查询</span></h2>
      <div class="field">
        <label>question <span class="req">*</span></label>
        <textarea v-model="question" rows="3" placeholder="例如: NVMe SSD 垃圾回收 (GC) 流程"></textarea>
      </div>

      <div class="opts">
        <div class="opt"><label>top_k</label><input v-model="topK" type="number" min="1" max="100" /></div>
        <div class="opt"><label>similarity_threshold</label><input v-model="simThreshold" type="number" step="0.05" min="0" max="1" /></div>
        <div class="opt"><label>vector_similarity_weight</label><input v-model="vecWeight" type="number" step="0.05" min="0" max="1" /></div>
        <div class="opt"><label>page_size</label><input v-model="pageSize" type="number" min="1" max="100" /></div>
        <div class="opt">
          <label>keyword</label>
          <select v-model="keyword"><option value="false">false</option><option value="true">true</option></select>
        </div>
        <div class="opt">
          <label>highlight</label>
          <select v-model="highlight"><option value="true">true</option><option value="false">false</option></select>
        </div>
      </div>

      <div class="row" style="margin-top: 4px">
        <button class="primary" :disabled="searching" @click="onSearch">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
          <span>{{ searching ? '搜索中…' : '搜索' }}</span>
        </button>
        <button class="secondary" @click="onReset">重置</button>
        <div class="meta">
          <span v-if="searching">请求中</span>
          <span v-else-if="searched">完成 · {{ results.length }} 命中 · 用时 {{ elapsed }}ms</span>
        </div>
      </div>
    </div>

    <!-- 命中结果卡 -->
    <div class="card">
      <h2><span>命中结果</span> <span class="badge" v-if="searched">{{ results.length }} 段</span></h2>
      <div v-if="!searched" class="empty">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
        <div>填入 API Key + Dataset IDs + query, 点击"搜索".</div>
      </div>
      <div v-else>
        <div v-for="(r, i) in results" :key="i" class="chunk">
          <div class="chunk-hd">
            <span class="idx">{{ i + 1 }}</span>
            <span class="doc">{{ r.doc }}</span>
            <span class="ds">{{ r.ds }}</span>
            <span class="pos">{{ r.pos }}</span>
            <span class="score">score {{ r.score.toFixed(3) }}</span>
          </div>
          <div class="chunk-body" v-html="r.body"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { ElMessage } from 'element-plus';

const apiKey = ref('ragflow-QwGRg-lobL-c93T7_SlritLfgTj2qlWsL-FIXOTWt3E');
const proxyUrl = ref('http://127.0.0.1:8765');
const datasetIds = ref('80748f1872b711f1a82f771aafbe4f81');
const documentIds = ref('');
const question = ref('');
const topK = ref(15);
const simThreshold = ref(0.2);
const vecWeight = ref(0.3);
const pageSize = ref(10);
const keyword = ref('false');
const highlight = ref('false');

const searching = ref(false);
const searched = ref(false);
const elapsed = ref(0);

interface Hit {
  doc: string;
  ds: string;
  pos: string;
  score: number;
  body: string;
}
const results = ref<Hit[]>([]);

// 假数据: 模拟一次成功返回, 让 UI 跑通
function mockResults(): Hit[] {
  return [
    {
      doc: 'NVMe 2.0 Base Spec',
      ds: 'spec/nvme',
      pos: '§4.2.3',
      score: 0.872,
      body: `For 4KB random writes at queue depth 32, the minimum sustained
<mark>throughput shall not fall below 80,000 IOPS</mark> for consumer-grade devices
operating at the JEDEC JESD219A workload. Latency targets are tiered:
<mark>P99 ≤ 250 μs</mark> at the controller boundary, <mark>P99.9 ≤ 1.2 ms</mark>
at the application boundary.`,
    },
    {
      doc: 'NVMe-MI 1.2',
      ds: 'spec/nvme-mi',
      pos: '§6.4.1',
      score: 0.741,
      body: `健康数据上报采用 NVMe-MI 标准结构,包含温度 / 剩余寿命 / 错误计数等字段。
<mark>温度阈值告警</mark>触发后,中台通过 Dify Agent 推送钉钉通知。`,
    },
    {
      doc: 'JEDEC JESD219A',
      ds: 'spec/jedec',
      pos: '§5.2',
      score: 0.688,
      body: `稳态条件 (Steady-State) 定义: 在 SNIA SSS-PT-2024 §3.4 描述的预热流程后,
设备连续运行 4 小时,IOPS 波动 < ±5% 时进入稳态。`,
    },
  ];
}

async function onSearch() {
  if (!question.value.trim()) {
    ElMessage.warning('请输入 question');
    return;
  }
  if (!apiKey.value.trim()) {
    ElMessage.warning('请填写 API Key');
    return;
  }
  if (!datasetIds.value.trim()) {
    ElMessage.warning('请至少填一个 dataset_id');
    return;
  }
  searching.value = true;
  searched.value = false;
  results.value = [];
  const t0 = performance.now();
  // P0 mock: 模拟 1.2s 延迟, 让用户看到 loading
  await new Promise((r) => setTimeout(r, 1200));
  results.value = mockResults();
  elapsed.value = Math.round(performance.now() - t0);
  searching.value = false;
  searched.value = true;
}

function onReset() {
  question.value = '';
  results.value = [];
  searched.value = false;
  elapsed.value = 0;
}

const docs = ref([
  { id: 'nvme-2', name: 'NVMe 2.0 Base Spec', version: '2.0' },
  { id: 'nvme-mi', name: 'NVMe-MI 1.2', version: '1.2' },
  { id: 'jedec', name: 'JEDEC JESD219A', version: '2014' },
]);
</script>

<style scoped>
.kb { display: flex; flex-direction: column; gap: 18px; }
.title { font-size: 30px; font-weight: 800; margin: 0 0 10px; letter-spacing: -0.4px; color: var(--ink-900); }
.lede { color: var(--ink-700); margin: 0 0 24px; font-size: 14.5px; }

h2 { font-size: 15px; font-weight: 700; margin: 0 0 14px; display: flex; align-items: center; gap: 8px; }
.badge {
  font-size: 10.5px; font-weight: 600;
  padding: 2px 8px; border-radius: var(--radius-pill);
  background: var(--primary-soft); color: var(--primary);
}

.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.field label { font-size: 12.5px; color: var(--ink-700); font-weight: 500; }
.field .hint { font-size: 11.5px; color: var(--ink-500); }
.field input, .field textarea, .field select {
  width: 100%; padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--ink-900);
  font-size: 13px;
  font-family: inherit;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.field input:focus, .field textarea:focus, .field select:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}
.field textarea { resize: vertical; min-height: 64px; }
.req { color: var(--err); }

.row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.row > * { min-width: 0; }
.row > .field { flex: 1; }
.row .field { margin-bottom: 0; }

.opts { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 14px; }
.opt {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex; flex-direction: column; gap: 4px;
}
.opt label { font-size: 11px; color: var(--ink-500); text-transform: uppercase; letter-spacing: 0.04em; font-weight: 500; }
.opt input, .opt select {
  width: 100%; border: 0; background: transparent;
  color: var(--ink-900); font-size: 13px;
  font-family: var(--font-mono);
  padding: 0;
}
.opt input:focus, .opt select:focus { outline: none; }

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

.meta {
  flex: 2;
  text-align: right;
  font-size: 12.5px;
  color: var(--ink-500);
  padding: 9px 0;
}

.empty {
  text-align: center;
  color: var(--ink-500);
  padding: 40px 20px;
  font-size: 13.5px;
}
.empty svg { display: block; margin: 0 auto 8px; opacity: 0.5; }

.chunk {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--primary);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 10px;
  transition: border-color .15s ease;
}
.chunk:hover { border-left-color: var(--primary-2); }
.chunk-hd {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  font-size: 11.5px; color: var(--ink-700);
  margin-bottom: 6px;
}
.idx {
  background: var(--primary); color: #fff;
  font-size: 10.5px; font-weight: 700;
  padding: 1px 7px; border-radius: var(--radius-pill);
  line-height: 1.6;
}
.doc { font-family: var(--font-mono); color: var(--ink-900); font-weight: 600; }
.ds { color: var(--ink-500); }
.pos { font-family: var(--font-mono); color: var(--ink-500); font-size: 10.5px; }
.score { margin-left: auto; font-family: var(--font-mono); color: var(--primary); font-weight: 600; }
.chunk-body { color: var(--ink-900); font-size: 13px; line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.chunk-body :deep(mark) { background: rgba(245, 158, 11, 0.35); color: inherit; padding: 0 2px; border-radius: 2px; }
</style>
