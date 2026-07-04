<template>
  <div class="kb">
    <header class="head">
      <div>
        <h1 class="title">知识库检索</h1>
        <p class="sub">NVMe / JEDEC / 企业 spec · RAGFlow 索引 · 命中分段按相似度排序</p>
      </div>
      <div class="actions">
        <el-input v-model="docFilter" placeholder="过滤文档" size="default" clearable style="width: 220px;" />
        <el-button @click="reload" plain>
          <span class="btn-row">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>
            刷新索引
          </span>
        </el-button>
      </div>
    </header>

    <div class="grid">
      <aside class="docs card">
        <div class="docs-h">
          <span>文档列表</span>
          <span class="count">{{ docs.length }}</span>
        </div>
        <div class="docs-list">
          <button
            v-for="d in filteredDocs"
            :key="d.id"
            class="doc"
            :class="{ active: d.id === activeId }"
            @click="activeId = d.id"
          >
            <div class="doc-title">{{ d.name }}</div>
            <div class="doc-meta">
              <span class="v">{{ d.version }}</span>
              <span class="dot">·</span>
              <span>{{ d.chunks }} chunks</span>
            </div>
          </button>
        </div>
      </aside>

      <section class="reader card">
        <header class="r-h">
          <div class="r-crumbs">
            <span class="r-cn">{{ activeDoc?.name }}</span>
            <span class="r-sep">/</span>
            <span class="r-cp">{{ activeDoc?.chapter }}</span>
          </div>
          <div class="r-stat">
            <span class="ok">
              <span class="d"></span>
              已索引
            </span>
            <span class="count">{{ activeDoc?.chunks }} chunks</span>
          </div>
        </header>
        <article class="r-body">
          <h2 class="r-h2">4.2 Random Write Performance</h2>
          <p>
            The random write performance of NVMe 2.0 controllers shall be measured
            under steady-state conditions as defined in
            <mark class="hit">SNIA SSS-PT-2024 §3.4</mark>.
            For 4KB random writes at queue depth 32, the minimum sustained
            <mark class="hit">throughthrough shall not fall below 80,000 IOPS</mark>
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
  try { await request.get('/health'); } catch { /* */ }
}
</script>

<style scoped>
.kb { display: flex; flex-direction: column; gap: 20px; height: 100%; }
.head { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.title { font-size: 28px; font-weight: 700; margin: 0; color: var(--ink-900); letter-spacing: -0.4px; }
.sub { font-size: 13.5px; color: var(--ink-500); margin: 4px 0 0; }
.actions { display: flex; gap: 8px; }
.btn-row { display: inline-flex; align-items: center; gap: 6px; }

.grid {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 16px;
  flex: 1;
  min-height: 0;
}
.docs, .reader { min-height: 0; display: flex; flex-direction: column; }

.docs-h {
  padding: 14px 18px;
  font-size: 13px; font-weight: 600; color: var(--ink-700);
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border);
}
.count {
  font-size: 11px;
  font-family: var(--font-mono);
  color: var(--ink-500);
  background: var(--surface-sunken);
  padding: 2px 8px;
  border-radius: var(--radius-pill);
}
.docs-list { flex: 1; overflow: auto; padding: 8px; }
.doc {
  display: block; width: 100%; text-align: left;
  background: transparent; border: 1px solid transparent;
  padding: 10px 12px; border-radius: var(--radius-md);
  cursor: pointer; color: var(--ink-900);
  font-family: inherit;
  margin-bottom: 2px;
  transition: background .12s ease, border-color .12s ease;
}
.doc:hover { background: var(--surface-sunken); }
.doc.active {
  background: var(--primary-soft);
  border-color: var(--primary);
}
.doc-title { font-size: 13.5px; font-weight: 500; }
.doc-meta { font-size: 11.5px; color: var(--ink-500); margin-top: 2px; display: flex; gap: 6px; align-items: center; }
.v {
  font-family: var(--font-mono);
  background: var(--surface-sunken);
  padding: 1px 6px; border-radius: var(--radius-sm);
  color: var(--ink-700);
  font-size: 10.5px;
}
.dot { color: var(--ink-300); }

.r-h {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 24px;
  border-bottom: 1px solid var(--border);
}
.r-crumbs { display: flex; gap: 8px; align-items: center; font-size: 13px; }
.r-cn { color: var(--ink-900); font-weight: 600; }
.r-sep { color: var(--ink-300); }
.r-cp { color: var(--ink-500); }
.r-stat { display: flex; gap: 12px; align-items: center; font-size: 12px; color: var(--ink-500); }
.ok { display: inline-flex; align-items: center; gap: 5px; color: var(--ok-text); font-weight: 500; }
.ok .d { width: 6px; height: 6px; border-radius: 50%; background: var(--ok); }
.r-stat .count { font-family: var(--font-mono); }

.r-body { padding: 32px 40px; overflow: auto; }
.r-h2 { font-size: 22px; font-weight: 700; margin: 0 0 16px; color: var(--ink-900); letter-spacing: -0.2px; }
.r-body p {
  font-size: 14px;
  line-height: 1.85;
  color: var(--ink-700);
  margin: 0 0 14px;
  max-width: 780px;
}
.r-body code {
  font-family: var(--font-mono);
  font-size: 12.5px;
  background: var(--surface-sunken);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  color: var(--ink-700);
}
.hit {
  background: rgba(79, 70, 229, 0.12);
  color: var(--primary-deep);
  padding: 1px 3px;
  border-radius: var(--radius-sm);
  font-weight: 500;
}
.code {
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.75;
  background: var(--surface-sunken);
  color: var(--ink-900);
  padding: 16px 20px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  overflow-x: auto;
  max-width: 780px;
}
.code .cmt { color: var(--ink-400); }
.code .kw  { color: var(--primary); }
.code .fn  { color: #7C3AED; }
.code .str { color: #059669; }
.code .num { color: #D97706; }
</style>
