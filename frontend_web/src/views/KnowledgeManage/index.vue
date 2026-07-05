<template>
  <div class="kb">
    <!-- 顶部: 概览 (左) + RAGFlow 共享搜索 (右) -->
    <div class="row-grid">
      <!-- 概览: 缩小, 3 列横排 (无最近命中) -->
      <div class="card card-overview">
        <h2>
          <span>概览</span>
          <span class="rf-status" :class="`s-${rfStatus}`" v-if="rfStatus">
            <span class="dot"></span>{{ rfMsg }}
          </span>
        </h2>
        <div class="stats">
          <div class="stat">
            <div class="stat-hd"><span class="num">{{ datasets.length }}</span><span class="lbl">数据集</span></div>
          </div>
          <div class="stat">
            <div class="stat-hd"><span class="num">{{ totalDocs }}</span><span class="lbl">文档</span></div>
          </div>
          <div class="stat">
            <div class="stat-hd"><span class="num">{{ totalChunks }}</span><span class="lbl">分段</span></div>
          </div>
        </div>
        <div class="ds-preview" v-if="datasets.length > 0">
          <div class="ds-preview-hd">数据集</div>
          <ul>
            <li v-for="d in datasets.slice(0, 3)" :key="d.id">
              <span class="ds-name">{{ d.name }}</span>
              <span class="ds-meta">{{ d.chunk_count }} 段</span>
            </li>
          </ul>
          <div v-if="datasets.length > 3" class="ds-more">+ {{ datasets.length - 3 }} 个</div>
        </div>
        <div v-else class="ds-empty">
          <span>暂无数据集, 在 RAGFlow 后台创建后刷新</span>
        </div>
      </div>

      <!-- RAGFlow 共享搜索: 全屏 iframe -->
      <div class="card card-share">
        <h2>
          <span>🔎 知识检索</span>
          <span class="share-sub">基于 RAGFlow 共享 Search App</span>
        </h2>
        <div class="share-frame-wrap">
          <iframe
            src="http://127.0.0.1:18080/search/share?shared_id=ea62499872bb11f1a82f771aafbe4f81&from=search&auth=ir7sYP4h2kMSxcjSi2IfailLxbATmCdm&tenantId=7ddaa0b472b511f1a82f771aafbe4f81"
            frameborder="0"
            allow="microphone"
            class="share-frame"
            title="ragflow-shared-search"
          ></iframe>
        </div>
        <a href="http://127.0.0.1:18080/search/share?shared_id=ea62499872bb11f1a82f771aafbe4f81&from=search&auth=ir7sYP4h2kMSxcjSi2IfailLxbATmCdm&tenantId=7ddaa0b472b511f1a82f771aafbe4f81"
           target="_blank" rel="noopener" class="share-pop">↗ 新窗口打开 RAGFlow 共享搜索</a>
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
import { listDatasets, kbHealth, type KbDataset } from '@/api/kb';
import { listAgents, type AgentSummary } from '@/api/agents';

const datasets = ref<KbDataset[]>([]);
const loading = ref(false);
const rfStatus = ref<'ok' | 'warn' | 'off' | ''>('');
const rfMsg = ref('');


const totalDocs = computed(() => datasets.value.reduce((s, d) => s + d.document_count, 0));
const totalChunks = computed(() => datasets.value.reduce((s, d) => s + d.chunk_count, 0));



const usingAgents = ref<AgentSummary[]>([]);







async function loadAll() {
  loading.value = true;
  try {
    const h = await kbHealth();
    rfStatus.value = h.status as any;
    rfMsg.value = h.message || h.status;

    const r = await listDatasets();
    datasets.value = r.items;

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

/* 概览卡: 缩小, 3 列横排, 跟右侧 share 卡等高 */
.card-overview { display: flex; flex-direction: column; }
.card-overview .stats { display: flex; gap: 10px; }
.card-overview .stat { flex: 1; padding: 12px 14px; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 10px; display: flex; flex-direction: column; gap: 4px; }
.card-overview .stat-hd { display: flex; align-items: baseline; gap: 6px; }
.card-overview .num { font-size: 24px; font-weight: 800; color: var(--primary); font-family: var(--font-mono); line-height: 1; letter-spacing: -0.5px; }
.card-overview .num.hi { color: var(--ok); }
.card-overview .lbl { font-size: 11px; color: var(--ink-500); }

/* RAGFlow 共享搜索: 占右侧大块, iframe 自适应 */
.card-share { display: flex; flex-direction: column; min-height: 360px; }
.card-share h2 { display: flex; align-items: center; gap: 8px; }
.share-sub { font-size: 11.5px; color: var(--ink-500); font-weight: 400; margin-left: 4px; }
.share-frame-wrap { flex: 1; min-height: 320px; border-radius: 10px; overflow: hidden; border: 1px solid var(--border); background: var(--surface-sunken); }
.share-frame { width: 100%; height: 100%; min-height: 320px; display: block; border: 0; }
.share-pop { display: inline-block; margin-top: 10px; font-size: 11.5px; color: var(--primary); text-decoration: none; align-self: flex-end; }
.share-pop:hover { text-decoration: underline; }

.ds-preview { margin-top: 14px; padding-top: 14px; border-top: 1px dashed var(--border); }
.ds-preview-hd { font-size: 11px; color: var(--ink-500); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }
.ds-preview ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.ds-preview li { display: flex; align-items: center; justify-content: space-between; padding: 5px 8px; background: var(--surface-sunken); border-radius: 6px; font-size: 12px; }
.ds-name { color: var(--ink-900); font-weight: 500; }
.ds-meta { color: var(--ink-500); font-family: var(--font-mono); font-size: 10.5px; }
.ds-more { margin-top: 6px; font-size: 11px; color: var(--ink-500); text-align: center; padding: 3px; }
.ds-empty { margin-top: 14px; padding: 14px; text-align: center; color: var(--ink-500); font-size: 12px; background: var(--surface-sunken); border-radius: 8px; }
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

.res-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.res-hd h2 { margin: 0; }
.filter-input {
  padding: 5px 10px; border: 1px solid var(--border);
  border-radius: 6px; background: var(--surface);
  color: var(--ink-900); font-size: 12px; font-family: inherit; width: 180px;
}
.filter-input:focus { outline: none; border-color: var(--primary); }


.chunk {
  background: var(--surface); border: 1px solid var(--border);
  border-left: 3px solid var(--primary);
  border-radius: 10px; padding: 12px 14px;
  transition: border-color 0.15s ease;
}
.chunk:hover { border-left-color: var(--primary-2); }
.sim { font-family: var(--font-mono); font-weight: 600; padding: 1px 7px; border-radius: var(--radius-pill); font-size: 10.5px; }
.sim.hi { background: rgba(22, 163, 74, 0.1); color: var(--ok); }
.sim.mid { background: rgba(245, 158, 11, 0.1); color: var(--warn); }
.sim.low { background: rgba(148, 163, 184, 0.15); color: var(--ink-500); }
.copy { margin-left: auto; color: var(--ink-500); cursor: pointer; padding: 2px 6px; border-radius: 4px; font-size: 11px; }
.copy:hover { background: var(--primary-soft); color: var(--primary); }

.ch-body { font-size: 13px; line-height: 1.7; color: var(--ink-900); white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow: auto; }
.ch-body :deep(mark) { background: rgba(245, 158, 11, 0.35); color: inherit; padding: 0 2px; border-radius: 2px; font-weight: 600; }


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
