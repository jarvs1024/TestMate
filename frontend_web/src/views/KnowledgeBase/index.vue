<template>
  <div class="kb-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">
          知识库检索
          <span class="tm-serif suffix">— RAG-backed spec</span>
        </h1>
        <p class="page-lede">
          NVMe / JEDEC / 企业 spec 切片 + 高亮问答,所有文档都在 RAGFlow 索引里
        </p>
      </div>
      <div class="head-actions">
        <el-button :icon="Refresh" size="default" @click="reload" plain>刷新索引</el-button>
      </div>
    </div>

    <div class="kb-grid">
      <!-- 左:文档列表 -->
      <PreviewWindow
        title="docs.testmate.local"
        subtitle="数据集"
        class="doc-list"
      >
        <template #actions>
          <button class="light-btn" title="新建数据集">
            <span>+</span>
          </button>
        </template>

        <div class="list-search">
          <span>🔍</span>
          <input v-model="docFilter" placeholder="过滤文档…" />
        </div>

        <div class="list-body">
          <div
            v-for="d in filteredDocs"
            :key="d.id"
            class="doc-item"
            :class="{ active: activeId === d.id }"
            @click="activeId = d.id"
          >
            <div class="doc-icon">{{ d.icon }}</div>
            <div class="doc-meta">
              <div class="doc-title">{{ d.name }}</div>
              <div class="doc-sub">
                <span class="chip chip-ver">{{ d.version }}</span>
                <span class="dim">{{ d.chunks }} 切片</span>
              </div>
            </div>
          </div>
        </div>
      </PreviewWindow>

      <!-- 右:PDF / 文档预览 -->
      <PreviewWindow
        :title="activeDoc?.name || '未选文档'"
        :subtitle="activeDoc?.version"
        class="doc-view"
      >
        <template #actions>
          <button class="light-btn" title="下载">
            <span>⤓</span>
          </button>
        </template>

        <div class="viewer">
          <div class="viewer-head">
            <div class="breadcrumb">
              <span>{{ activeDoc?.name }}</span>
              <span class="sep">›</span>
              <span>{{ activeDoc?.chapter }}</span>
            </div>
            <div class="viewer-stats">
              <span class="chip chip-ok">● 已索引</span>
              <span class="chip chip-meta">{{ activeDoc?.chunks }} chunks</span>
            </div>
          </div>

          <div class="page-paper">
            <div class="page-h">4.2 Random Write Performance</div>
            <p class="page-p">
              The random write performance of NVMe 2.0 controllers shall be measured
              under steady-state conditions as defined in
              <mark class="hit">SNIA SSS-PT-2024 §3.4</mark>.
              For 4KB random writes at queue depth 32, the minimum sustained
              <mark class="hit">throughput shall not fall below 80,000 IOPS</mark>
              for consumer-grade devices operating at the JEDEC JESD219A workload.
            </p>
            <p class="page-p">
              Latency targets are tiered:
              <mark class="hit">P99 ≤ 250 μs</mark> at the controller boundary,
              <mark class="hit">P99.9 ≤ 1.2 ms</mark> at the application boundary.
              Tail-latency outliers exceeding 3σ shall be reported in the
              compliance log and trigger automatic <span class="code">fw_regression_check</span>.
            </p>
            <p class="page-p dim">
              <span class="code">// 引用此规范</span><br>
              <span class="code">from ssd_tool import spec</span><br>
              <span class="code">spec.assert_random_write('NVMe 2.0 §4.2', iops=82_400, p99_us=180)</span>
            </p>
          </div>
        </div>

        <template #footer>
          <div class="hit-legend">
            <span class="hit-sample"></span>
            命中片段(由 RAGFlow 检索高亮)
          </div>
        </template>
      </PreviewWindow>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { Refresh } from '@element-plus/icons-vue';
import PreviewWindow from '@/components/PreviewWindow.vue';

const docFilter = ref('');
const activeId = ref<string>('nvme-2');

const docs = ref([
  { id: 'nvme-2',     name: 'NVMe 2.0 Base Spec',          version: '2.0',   icon: '📘', chunks: 1284, chapter: '§4.2 Random Write' },
  { id: 'nvme-mi-1',  name: 'NVMe-MI 1.2',                  version: '1.2',   icon: '📗', chunks: 412,  chapter: '§6 Health Data' },
  { id: 'jedec-219',  name: 'JEDEC JESD219A',               version: '2014',  icon: '📕', chunks: 198,  chapter: '§5 Workloads' },
  { id: 'jedec-220',  name: 'JEDEC JESD220A',               version: '2022',  icon: '📕', chunks: 156,  chapter: '§3 UBER' },
  { id: 'pcie-6',     name: 'PCI Express 6.0',              version: '6.0',   icon: '📙', chunks: 723,  chapter: '§4.3 LTSSM' },
  { id: 'bics8',      name: '内部: BICS8 错误码字典',         version: 'v3.2',  icon: '🛠', chunks: 88,   chapter: 'E0xx PCIe' },
  { id: 'ssd-tool',   name: '内部: ssd_tool API 文档',       version: 'v1.8',  icon: '🛠', chunks: 64,   chapter: 'spec.assert_*' },
]);

const filteredDocs = computed(() => {
  const q = docFilter.value.trim().toLowerCase();
  if (!q) return docs.value;
  return docs.value.filter((d) => d.name.toLowerCase().includes(q));
});

const activeDoc = computed(() => docs.value.find((d) => d.id === activeId.value));

function reload() {
  // P0 占位: 假装刷一下
}
</script>

<style scoped>
.kb-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 16px;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}
.page-title {
  font-size: 24px;
  font-weight: 700;
  margin: 0;
  color: var(--ink-900);
  line-height: 1.2;
}
.page-title .suffix {
  color: var(--ink-500);
  font-size: 18px;
  margin-left: 6px;
}
.page-lede {
  font-size: 13.5px;
  color: var(--ink-500);
  margin: 4px 0 0;
}
.head-actions { display: flex; gap: 8px; }

.kb-grid {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  flex: 1;
  min-height: 0;
}
.doc-list, .doc-view { min-height: 0; }

.list-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 12.5px;
  color: var(--ink-500);
}
.list-search input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  color: var(--ink-900);
  font-family: inherit;
}

.list-body {
  overflow: auto;
  padding: 6px;
  flex: 1;
}
.doc-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background .15s ease;
}
.doc-item:hover { background: var(--surface-sunken); }
.doc-item.active {
  background: var(--primary-soft);
  outline: 1px solid var(--primary);
}
.doc-icon { font-size: 18px; }
.doc-meta { flex: 1; min-width: 0; }
.doc-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink-900);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.doc-sub {
  display: flex; gap: 8px; align-items: center;
  font-size: 11px;
  color: var(--ink-500);
  margin-top: 2px;
}
.chip {
  font-size: 10.5px; padding: 1px 7px; border-radius: 999px;
  font-weight: 500;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--ink-500);
}
.chip-ver {
  background: var(--primary-soft);
  color: var(--primary);
  border-color: transparent;
}
.dim { color: var(--ink-400); }

.viewer { display: flex; flex-direction: column; min-height: 0; }
.viewer-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 18px;
  border-bottom: 1px solid var(--border);
}
.breadcrumb {
  font-size: 12.5px;
  color: var(--ink-500);
  display: flex; gap: 6px; align-items: center;
}
.breadcrumb .sep { color: var(--ink-300); }
.breadcrumb span:first-child { color: var(--ink-900); font-weight: 500; }
.viewer-stats { display: flex; gap: 6px; }
.chip-ok {
  background: var(--status-ok-soft);
  color: var(--status-ok);
  border-color: transparent;
}
.chip-meta {
  background: var(--surface-sunken);
  color: var(--ink-500);
}

.page-paper {
  flex: 1;
  overflow: auto;
  padding: 32px 48px;
  background: var(--surface);
  color: var(--ink-900);
}
.page-h {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 16px;
  letter-spacing: -0.2px;
}
.page-p {
  font-size: 14.5px;
  line-height: 1.85;
  color: var(--ink-700);
  margin: 0 0 14px;
  max-width: 720px;
}
.page-p.dim { color: var(--ink-500); }
.page-p .code {
  font-family: var(--font-mono);
  font-size: 12.5px;
  background: var(--surface-sunken);
  padding: 1px 5px;
  border-radius: 3px;
  color: var(--ink-700);
}
mark.hit {
  background: linear-gradient(180deg, transparent 55%, rgba(245, 158, 11, 0.35) 55%);
  color: inherit;
  padding: 0 2px;
  border-radius: 2px;
}

.hit-legend {
  display: flex; align-items: center; gap: 8px;
  font-size: 11.5px; color: var(--ink-500);
}
.hit-sample {
  width: 24px; height: 8px; border-radius: 2px;
  background: linear-gradient(180deg, transparent 55%, rgba(245, 158, 11, 0.5) 55%);
}

.light-btn {
  width: 24px; height: 24px;
  display: grid; place-items: center;
  border: 1px solid var(--border);
  background: var(--surface);
  border-radius: 6px;
  color: var(--ink-500);
  cursor: pointer;
  font-size: 12px;
}
.light-btn:hover { color: var(--ink-900); }
</style>
