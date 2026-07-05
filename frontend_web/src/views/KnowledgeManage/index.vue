<template>
  <div class="kb">
    <h1 class="title" style="display:none">📚 知识库</h1>
    <p class="lede" style="display:none">所有智能体共享的私有知识源 · 已对接 RAGFlow · 喂入文档 / Spec / 历史 Case / 缺陷档</p>

    <!-- 顶部: 健康 + 概览 + 检索 -->
    <div class="row-grid">
      <!-- 概览 -->
      <div class="card">
        <h2><span>概览</span>
          <span class="rf-status" :class="`s-${rfStatus}`" v-if="rfStatus">
            <span class="dot"></span>{{ rfMsg }}
          </span>
        </h2>
        <div class="stats">
          <div class="stat">
            <div class="num">{{ datasets.length }}</div>
            <div class="lbl">数据集</div>
          </div>
          <div class="stat">
            <div class="num">{{ totalDocs }}</div>
            <div class="lbl">文档</div>
          </div>
          <div class="stat">
            <div class="num">{{ totalChunks }}</div>
            <div class="lbl">分段</div>
          </div>
          <div class="stat">
            <div class="num" :class="{ hi: lastSearch }">{{ lastSearch?.total ?? '—' }}</div>
            <div class="lbl">最近命中</div>
          </div>
        </div>
      </div>

      <!-- 检索测试 -->
      <div class="card">
        <h2><span>检索测试</span>
          <span class="hint-t" v-if="lastSearch">用时 {{ lastSearch.elapsed_ms || 0 }}ms</span>
        </h2>
        <div class="field">
          <label>问题 <span class="req">*</span></label>
          <textarea v-model="qText" rows="2" placeholder="例: NVMe GC 流程 / TRIM 时序 / 4K 随机写 P99 抖动"></textarea>
        </div>
        <div class="field">
          <label>数据集 <span class="req">*</span></label>
          <div class="ds-checks">
            <label v-for="d in datasets" :key="d.id" class="ck">
              <input type="checkbox" :value="d.id"
                :checked="searchDs.includes(d.id)"
                @change="toggleDs(d.id, ($event.target as HTMLInputElement).checked)" />
              <span>{{ d.name }}</span>
              <span class="hint-s">{{ d.chunk_count }} 分段</span>
            </label>
            <span v-if="datasets.length === 0" class="hint">未加载到数据集, 刷新页面或检查 RAGFlow 配置</span>
          </div>
        </div>
        <div class="row3">
          <div class="field">
            <label>top_k</label>
            <input v-model.number="topK" type="number" min="1" max="50" />
          </div>
          <div class="field">
            <label>阈值</label>
            <input v-model.number="threshold" type="number" step="0.05" min="0" max="1" />
          </div>
          <div class="field">
            <label>向量权重</label>
            <input v-model.number="vecWeight" type="number" step="0.05" min="0" max="1" />
          </div>
        </div>
        <div class="actions">
          <button class="primary" :disabled="searching || !canSearch" @click="onSearch">
            <span v-if="!searching">▶ 检索</span>
            <span v-else>⏳ 检索中...</span>
          </button>
          <button class="ghost" @click="onReset">重置</button>
        </div>
      </div>
    </div>

    <!-- 命中结果 -->
    <div class="card results">
      <div class="res-hd">
        <h2><span>命中</span>
          <span class="badge" v-if="lastSearch">{{ lastSearch.total }} 段</span>
        </h2>
        <div class="filter-bar">
          <input v-model="filterDoc" placeholder="过滤文档名..." class="filter-input" />
        </div>
      </div>

      <div v-if="!lastSearch" class="empty">
        <div style="font-size: 36px; opacity: 0.4">🔍</div>
        <div>填入问题, 选择数据集, 点击 "检索".</div>
      </div>

      <div v-else-if="filteredChunks.length === 0" class="empty">
        <div>无匹配结果 · 调低阈值或换关键词试试</div>
      </div>

      <div v-else class="chunk-list">
        <div v-for="(c, i) in filteredChunks" :key="c.id" class="chunk">
          <div class="ch-hd">
            <span class="idx">{{ i + 1 }}</span>
            <span class="doc">📄 {{ c.document_keyword || c.document_id.slice(0, 16) }}</span>
            <span class="sim" :class="simClass(c.similarity)">
              {{ (c.similarity * 100).toFixed(1) }}%
            </span>
            <span class="ds">ds: {{ c.dataset_id.slice(0, 16) }}</span>
            <span class="copy" @click="copyText(c.highlight)">📋 复制</span>
          </div>
          <div class="ch-body" v-html="renderHL(c.highlight)"></div>
          <div class="ch-meta" v-if="c.tag_kwd && c.tag_kwd.length">
            <span v-for="t in c.tag_kwd.slice(0, 4)" :key="t" class="kw">#{{ t }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 数据集列表 -->
    <div class="card">
      <div class="ds-hd">
        <h2><span>数据集</span> <button class="reload" @click="loadAll" :disabled="loading">↻ 刷新</button></h2>
      </div>
      <table class="ds-tbl">
        <thead>
          <tr><th>名称</th><th>说明</th><th>文档</th><th>分段</th><th>切片法</th><th>创建</th></tr>
        </thead>
        <tbody>
          <tr v-for="d in datasets" :key="d.id">
            <td class="nm">
              <span class="ds-ic">📁</span>
              <span>{{ d.name }}</span>
              <span class="ds-id mono">{{ d.id.slice(0, 8) }}…</span>
            </td>
            <td class="ds">{{ d.description || '—' }}</td>
            <td class="mono">{{ d.document_count }}</td>
            <td class="mono">{{ d.chunk_count }}</td>
            <td class="mono">{{ d.chunk_method || '—' }}</td>
            <td class="mono">{{ d.create_date || '—' }}</td>
          </tr>
          <tr v-if="datasets.length === 0 && !loading">
            <td colspan="6" class="empty">暂无数据集</td>
          </tr>
          <tr v-if="loading">
            <td colspan="6" class="empty">加载中...</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 谁在用 -->
    <div class="card">
      <h2><span>谁在用这些数据</span></h2>
      <p class="hint" style="margin: 0 0 12px;">数据被哪些智能体引用, 改文档后智能体下次调用会用到新内容 (RAG 实时检索)</p>
      <div class="users">
        <div v-for="a in usingAgents" :key="a.code" class="ua">
          <span class="ua-ic">{{ a.icon }}</span>
          <span class="ua-nm">{{ a.name }}</span>
          <span class="ua-ver">{{ a.version }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { listDatasets, kbSearch, kbHealth, type KbDataset, type KbSearchResult } from '@/api/kb';
import { listAgents, type AgentSummary } from '@/api/agents';

const datasets = ref<KbDataset[]>([]);
const loading = ref(false);
const rfStatus = ref<'ok' | 'warn' | 'off' | ''>('');
const rfMsg = ref('');

const qText = ref('NVMe GC 流程');
const searchDs = ref<string[]>([]);
const topK = ref(5);
const threshold = ref(0.2);
const vecWeight = ref(0.3);
const searching = ref(false);
const lastSearch = ref<KbSearchResult | null>(null);
const filterDoc = ref('');

const totalDocs = computed(() => datasets.value.reduce((s, d) => s + d.document_count, 0));
const totalChunks = computed(() => datasets.value.reduce((s, d) => s + d.chunk_count, 0));

const filteredChunks = computed(() => {
  if (!lastSearch.value) return [];
  if (!filterDoc.value.trim()) return lastSearch.value.chunks;
  const k = filterDoc.value.toLowerCase();
  return lastSearch.value.chunks.filter((c) =>
    (c.document_keyword || '').toLowerCase().includes(k),
  );
});

const canSearch = computed(() => qText.value.trim().length > 0 && searchDs.value.length > 0);

const usingAgents = ref<AgentSummary[]>([]);

function toggleDs(id: string, on: boolean) {
  if (on && !searchDs.value.includes(id)) searchDs.value = [...searchDs.value, id];
  else if (!on) searchDs.value = searchDs.value.filter((x) => x !== id);
}

function simClass(s: number) {
  if (s >= 0.5) return 'hi';
  if (s >= 0.3) return 'mid';
  return 'low';
}

function renderHL(h: string) {
  // RAGFlow highlight 用 <em>...</em> 标高亮
  return h.replace(/&lt;em&gt;/g, '<em>').replace(/&lt;\/em&gt;/g, '</em>')
    .replace(/<em>/g, '<mark>').replace(/<\/em>/g, '</mark>');
}

function copyText(t: string) {
  navigator.clipboard.writeText(t).then(() => ElMessage.success('已复制'));
}

async function onSearch() {
  if (!canSearch.value) return;
  searching.value = true;
  try {
    const data = await kbSearch({
      question: qText.value.trim(),
      dataset_ids: searchDs.value,
      top_k: topK.value,
      similarity_threshold: threshold.value,
      vector_similarity_weight: vecWeight.value,
      highlight: true,
      page_size: topK.value * 2,
    });
    lastSearch.value = data;
    if (data.total === 0) ElMessage.warning('无匹配, 调低阈值或换关键词');
  } catch (e: any) {
    ElMessage.error('检索失败: ' + (e?.response?.data?.detail || e?.message || '未知错误'));
  } finally {
    searching.value = false;
  }
}

function onReset() {
  qText.value = '';
  filterDoc.value = '';
  lastSearch.value = null;
}

async function loadAll() {
  loading.value = true;
  try {
    const h = await kbHealth();
    rfStatus.value = h.status as any;
    rfMsg.value = h.message || h.status;

    const r = await listDatasets();
    datasets.value = r.items;
    // 默认勾选第一个
    if (r.items.length > 0 && searchDs.value.length === 0) {
      searchDs.value = [r.items[0].id];
    }

    // 谁在用
    const ag = await listAgents();
    usingAgents.value = ag.items.filter((a) =>
      a.data_sources.some((s) => s.startsWith('ragflow:') || s === 'fw_library'),
    );
  } catch (e: any) {
    rfStatus.value = 'off';
    rfMsg.value = '加载失败';
    ElMessage.error('知识库加载失败: ' + (e?.response?.data?.detail || e?.message));
  } finally {
    loading.value = false;
  }
}

onMounted(loadAll);
</script>

<style scoped>
.kb { display: flex; flex-direction: column; gap: 16px; }
.title { font-size: 30px; font-weight: 800; margin: 0 0 8px; letter-spacing: -0.4px; color: var(--ink-900); }
.lede { color: var(--ink-700); margin: 0; font-size: 14.5px; }

.row-grid { display: grid; grid-template-columns: 1fr 1.4fr; gap: 16px; }
@media (max-width: 980px) { .row-grid { grid-template-columns: 1fr; } }

h2 { font-size: 15px; font-weight: 700; margin: 0 0 14px; color: var(--ink-900); display: flex; align-items: center; gap: 8px; }

.rf-status { margin-left: auto; font-size: 11px; font-weight: 500; display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px; border-radius: var(--radius-pill); }
.rf-status .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.s-ok { background: rgba(22, 163, 74, 0.1); color: var(--ok); }
.s-warn { background: rgba(217, 119, 6, 0.1); color: var(--warn); }
.s-off { background: rgba(220, 38, 38, 0.1); color: var(--err); }
.hint-t { margin-left: auto; font-size: 11px; color: var(--ink-500); font-family: var(--font-mono); }

.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.stat { text-align: center; padding: 16px 6px; background: var(--surface-sunken); border-radius: 10px; border: 1px solid var(--border); }
.num { font-size: 26px; font-weight: 800; color: var(--primary); font-family: var(--font-mono); line-height: 1; letter-spacing: -0.5px; }
.num.hi { color: var(--ok); }
.lbl { font-size: 11px; color: var(--ink-500); margin-top: 6px; }

.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.field label { font-size: 12.5px; color: var(--ink-700); font-weight: 500; }
.field label .req { color: var(--err); }
.field textarea, .field input {
  width: 100%; padding: 8px 10px; border: 1px solid var(--border);
  border-radius: 7px; background: var(--surface); color: var(--ink-900);
  font-size: 13px; font-family: inherit;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.field textarea:focus, .field input:focus {
  outline: none; border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-soft);
}
.field textarea { resize: vertical; min-height: 56px; }

.ds-checks { display: flex; flex-wrap: wrap; gap: 6px; max-height: 140px; overflow: auto; padding: 2px; }
.ck { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 8px; font-size: 12.5px; cursor: pointer; color: var(--ink-700); background: var(--surface-sunken); border: 1px solid var(--border); white-space: nowrap; transition: all 0.15s ease; }
.ck:hover { border-color: var(--primary); color: var(--primary); }
.ck:hover { background: var(--surface-sunken); }
.ck input { margin: 0; }
.ck span:nth-child(2) { flex: 1; }
.hint-s { color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
.hint { font-size: 11.5px; color: var(--ink-500); }

.row3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 12px; }
.actions { display: flex; gap: 8px; }
.primary {
  background: var(--primary); color: #fff; border: 0;
  padding: 8px 16px; border-radius: 8px;
  font-size: 13px; font-weight: 600; font-family: inherit; cursor: pointer;
}
.primary:disabled { opacity: 0.5; cursor: not-allowed; }
.primary:not(:disabled):hover { box-shadow: 0 4px 12px rgba(28, 100, 242, 0.25); }
.ghost {
  background: transparent; border: 1px solid var(--border);
  padding: 8px 14px; border-radius: 8px;
  color: var(--ink-700); font-size: 13px; cursor: pointer; font-family: inherit;
}
.ghost:hover { border-color: var(--primary); color: var(--primary); }

.results { display: flex; flex-direction: column; }
.res-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.res-hd h2 { margin: 0; }
.badge { font-size: 11px; padding: 2px 8px; background: var(--primary-soft); color: var(--primary); border-radius: var(--radius-pill); font-weight: 600; }
.filter-bar { display: flex; gap: 8px; }
.filter-input {
  padding: 5px 10px; border: 1px solid var(--border);
  border-radius: 6px; background: var(--surface);
  color: var(--ink-900); font-size: 12px; font-family: inherit; width: 180px;
}
.filter-input:focus { outline: none; border-color: var(--primary); }

.empty { padding: 40px 20px; text-align: center; color: var(--ink-500); display: flex; flex-direction: column; gap: 6px; align-items: center; }

.chunk-list { display: flex; flex-direction: column; gap: 10px; }
.chunk {
  background: var(--surface); border: 1px solid var(--border);
  border-left: 3px solid var(--primary);
  border-radius: 10px; padding: 12px 14px;
  transition: border-color 0.15s ease;
}
.chunk:hover { border-left-color: var(--primary-2); }
.ch-hd { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 11.5px; margin-bottom: 8px; }
.idx { background: var(--primary); color: #fff; font-size: 10.5px; font-weight: 700; padding: 1px 7px; border-radius: var(--radius-pill); }
.doc { color: var(--ink-900); font-weight: 600; }
.sim { font-family: var(--font-mono); font-weight: 600; padding: 1px 7px; border-radius: var(--radius-pill); font-size: 10.5px; }
.sim.hi { background: rgba(22, 163, 74, 0.1); color: var(--ok); }
.sim.mid { background: rgba(245, 158, 11, 0.1); color: var(--warn); }
.sim.low { background: rgba(148, 163, 184, 0.15); color: var(--ink-500); }
.ds { color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
.copy { margin-left: auto; color: var(--ink-500); cursor: pointer; padding: 2px 6px; border-radius: 4px; font-size: 11px; }
.copy:hover { background: var(--primary-soft); color: var(--primary); }

.ch-body { font-size: 13px; line-height: 1.7; color: var(--ink-900); white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow: auto; }
.ch-body :deep(mark) { background: rgba(245, 158, 11, 0.35); color: inherit; padding: 0 2px; border-radius: 2px; font-weight: 600; }

.ch-meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); }
.kw { font-size: 10.5px; color: var(--ink-500); background: var(--surface-sunken); padding: 1px 6px; border-radius: var(--radius-sm); font-family: var(--font-mono); }

.ds-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.ds-hd h2 { margin: 0; }
.reload { background: transparent; border: 1px solid var(--border); padding: 4px 10px; border-radius: 6px; color: var(--ink-700); font-size: 11.5px; cursor: pointer; font-family: inherit; }
.reload:hover { border-color: var(--primary); color: var(--primary); }
.reload:disabled { opacity: 0.5; }

.ds-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.ds-tbl th { text-align: left; padding: 10px 12px; color: var(--ink-500); font-weight: 500; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid var(--border); }
.ds-tbl td { padding: 10px 12px; color: var(--ink-700); border-bottom: 1px solid var(--border); }
.ds-tbl tr:last-child td { border-bottom: none; }
.ds-tbl tr:hover { background: var(--surface-sunken); }
.nm { display: flex; align-items: center; gap: 6px; color: var(--ink-900); font-weight: 500; }
.ds-ic { font-size: 16px; }
.ds-id { font-size: 10.5px; color: var(--ink-500); margin-left: 4px; }
.mono { font-family: var(--font-mono); font-size: 12px; }

.users { display: flex; flex-wrap: wrap; gap: 8px; }
.ua { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: var(--radius-pill); font-size: 12px; }
.ua-ic { font-size: 14px; }
.ua-nm { color: var(--ink-900); font-weight: 500; }
.ua-ver { color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
</style>
