<template>
  <div class="kb">
    <header class="page-head">
      <div>
        <h1 class="title">知识库检索</h1>
        <p class="sub">NVMe / JEDEC / 企业 spec · RAGFlow 索引</p>
      </div>
      <div class="head-actions">
        <el-input v-model="docFilter" placeholder="过滤文档" size="default" clearable style="width: 200px;" />
        <el-button @click="reload" plain>刷新索引</el-button>
      </div>
    </header>

    <div class="grid">
      <aside class="docs card">
        <div class="list-head">{{ docs.length }} 个文档</div>
        <div class="list">
          <button
            v-for="d in filteredDocs"
            :key="d.id"
            class="doc"
            :class="{ active: d.id === activeId }"
            @click="activeId = d.id"
          >
            <div class="doc-title">{{ d.name }}</div>
            <div class="doc-meta">
              <span>{{ d.version }}</span>
              <span class="dim">·</span>
              <span class="dim">{{ d.chunks }} chunks</span>
            </div>
          </button>
        </div>
      </aside>

      <section class="reader card">
        <header class="r-head">
          <div class="r-crumbs">
            <span>{{ activeDoc?.name }}</span>
            <span class="dim">/</span>
            <span class="dim">{{ activeDoc?.chapter }}</span>
          </div>
          <div class="r-meta">
            <span class="ok">已索引</span>
            <span class="dim">{{ activeDoc?.chunks }} chunks</span>
          </div>
        </header>
        <article class="r-body">
          <h2 class="r-h2">4.2 Random Write Performance</h2>
          <p>
            The random write performance of NVMe 2.0 controllers shall be measured
            under steady-state conditions as defined in
            <mark class="hit">SNIA SSS-PT-2024 §3.4</mark>.
            For 4KB random writes at queue depth 32, the minimum sustained
            <mark class="hit">throughput shall not fall below 80,000 IOPS</mark>
            for consumer-grade devices operating at the JEDEC JESD219A workload.
          </p>
          <p>
            Latency targets are tiered:
            <mark class="hit">P99 ≤ 250 μs</mark> at the controller boundary,
            <mark class="hit">P99.9 ≤ 1.2 ms</mark> at the application boundary.
            Tail-latency outliers exceeding 3σ shall be reported in the
            compliance log and trigger automatic
            <code>fw_regression_check</code>.
          </p>
          <pre class="code"><span class="cmt"># 引用此规范</span>
<span class="kw">from</span> ssd_tool <span class="kw">import</span> spec
spec.<span class="fn">assert_random_write</span>(<span class="str">'NVMe 2.0 §4.2'</span>, iops=<span class="num">82_400</span>, p99_us=<span class="num">180</span>)</pre>
        </article>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import request from '@/utils/request';

const docFilter = ref('');
const activeId = ref('nvme-2');

const docs = ref([
  { id: 'nvme-2',    name: 'NVMe 2.0 Base Spec',     version: '2.0',   chunks: 1284, chapter: '§4.2 Random Write' },
  { id: 'nvme-mi',   name: 'NVMe-MI 1.2',             version: '1.2',   chunks: 412,  chapter: '§6 Health Data' },
  { id: 'jedec-219', name: 'JEDEC JESD219A',          version: '2014',  chunks: 198,  chapter: '§5 Workloads' },
  { id: 'jedec-220', name: 'JEDEC JESD220A',          version: '2022',  chunks: 156,  chapter: '§3 UBER' },
  { id: 'pcie-6',    name: 'PCI Express 6.0',         version: '6.0',   chunks: 723,  chapter: '§4.3 LTSSM' },
  { id: 'bics8',     name: 'BICS8 错误码字典',         version: 'v3.2',  chunks: 88,   chapter: 'E0xx PCIe' },
  { id: 'ssd-tool',  name: 'ssd_tool API 文档',       version: 'v1.8',  chunks: 64,   chapter: 'spec.assert_*' },
]);

const filteredDocs = computed(() => {
  const q = docFilter.value.trim().toLowerCase();
  if (!q) return docs.value;
  return docs.value.filter((d) => d.name.toLowerCase().includes(q));
});

const activeDoc = computed(() => docs.value.find((d) => d.id === activeId.value));

async function reload() {
  try { await request.get('/health'); } catch { /* 占位 */ }
}
</script>

<style scoped>
.kb { display: flex; flex-direction: column; gap: 16px; height: 100%; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.title { font-size: 18px; font-weight: 600; margin: 0; color: var(--ink-900); }
.sub { font-size: 12.5px; color: var(--ink-500); margin: 2px 0 0; }
.head-actions { display: flex; gap: 8px; }

.grid {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.docs, .reader { min-height: 0; }
.docs { display: flex; flex-direction: column; }
.list-head {
  padding: 10px 14px;
  font-size: 11.5px;
  color: var(--ink-500);
  border-bottom: 1px solid var(--border);
  font-weight: 500;
}
.list { flex: 1; overflow: auto; padding: 4px; }
.doc {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  padding: 8px 10px;
  border-radius: 4px;
  cursor: pointer;
  color: var(--ink-900);
  font-family: inherit;
}
.doc:hover { background: var(--bg-hover); }
.doc.active {
  background: var(--primary-soft);
  border-color: var(--primary);
}
.doc-title { font-size: 13px; font-weight: 500; }
.doc-meta { font-size: 11px; color: var(--ink-500); margin-top: 2px; display: flex; gap: 6px; }
.dim { color: var(--ink-400); }

.r-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 18px;
  border-bottom: 1px solid var(--border);
}
.r-crumbs { font-size: 12.5px; color: var(--ink-700); display: flex; gap: 6px; }
.r-meta { display: flex; gap: 8px; font-size: 11.5px; color: var(--ink-500); }
.ok { color: var(--ok); }

.r-body { padding: 28px 36px; overflow: auto; }
.r-h2 { font-size: 17px; font-weight: 600; margin: 0 0 14px; color: var(--ink-900); }
.r-body p {
  font-size: 13.5px;
  line-height: 1.85;
  color: var(--ink-700);
  margin: 0 0 12px;
  max-width: 760px;
}
.r-body code {
  font-family: var(--font-mono);
  font-size: 12px;
  background: var(--bg-hover);
  padding: 1px 4px;
  border-radius: 3px;
  color: var(--ink-700);
}
.hit {
  background: rgba(22, 163, 74, 0.12);
  color: inherit;
  padding: 0 2px;
  border-radius: 2px;
}
.code {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.7;
  background: var(--code-bg);
  color: var(--code-fg);
  padding: 14px 16px;
  border-radius: 4px;
  border: 1px solid var(--border);
  overflow-x: auto;
  max-width: 760px;
}
.code .cmt { color: #64748B; }
.code .kw  { color: #93C5FD; }
.code .fn  { color: #C4B5FD; }
.code .str { color: #86EFAC; }
.code .num { color: #FCD34D; }
</style>
