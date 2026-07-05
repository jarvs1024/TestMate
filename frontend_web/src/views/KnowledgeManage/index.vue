<template>
  <div class="kb">
    <!-- 概览: 最顶部一行, 3 个数据 -->
    <div class="card card-overview">
      <h2>
        <span>概览</span>
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
      </div>
    </div>

    <!-- 知识检索: RAGFlow 共享搜索 iframe -->
    <div class="card card-share">
      <h2>
        <span>🔎 知识检索</span>
        <span class="share-sub">基于 RAGFlow 共享 Search App</span>
      </h2>
      <div class="share-frame-wrap">
        <iframe
          :src="shareUrl"
          frameborder="0"
          class="share-frame"
          title="ragflow-shared-search"
        ></iframe>
      </div>
      <a :href="shareUrl"
         target="_blank" rel="noopener" class="share-pop">↗ 新窗口打开 RAGFlow 共享搜索</a>
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
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { ElMessage } from 'element-plus';
import { listDatasets, kbHealth, type KbDataset } from '@/api/kb';


const SHARE_BASE = 'http://127.0.0.1:18080/search/share?shared_id=ea62499872bb11f1a82f771aafbe4f81&from=search&auth=ir7sYP4h2kMSxcjSi2IfailLxbATmCdm&tenantId=7ddaa0b472b511f1a82f771aafbe4f81&visible_avatar=1&locale=zh-Hans';
const shareUrl = computed(() => SHARE_BASE);

const datasets = ref<KbDataset[]>([]);
const loading = ref(false);
const rfStatus = ref<'ok' | 'warn' | 'off' | ''>('');
const rfMsg = ref('');


const totalDocs = computed(() => datasets.value.reduce((s, d) => s + d.document_count, 0));
const totalChunks = computed(() => datasets.value.reduce((s, d) => s + d.chunk_count, 0));










async function loadAll() {
  loading.value = true;
  try {
    const h = await kbHealth();
    rfStatus.value = h.status as any;
    rfMsg.value = h.message || h.status;

    const r = await listDatasets();
    datasets.value = r.items;

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

/* 概览卡: 顶部一行, 3 列横排 */
.card-overview .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.card-overview .stat { text-align: center; padding: 14px 8px; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 10px; }
.card-overview .num { font-size: 24px; font-weight: 800; color: var(--primary); font-family: var(--font-mono); line-height: 1; letter-spacing: -0.5px; }
.card-overview .num.hi { color: var(--ok); }
.card-overview .lbl { font-size: 11px; color: var(--ink-500); margin-top: 6px; }

/* RAGFlow 共享搜索: 全宽, iframe 600px */
.card-share { display: flex; flex-direction: column; }
.card-share h2 { display: flex; align-items: center; gap: 8px; }
.share-sub { font-size: 11.5px; color: var(--ink-500); font-weight: 400; margin-left: 4px; }
.share-frame-wrap { width: 100%; min-height: 600px; border-radius: 10px; overflow: hidden; border: 1px solid var(--border); background: var(--surface-sunken); }
.share-frame { display: block; border: 0; width: 100%; height: 600px; }
.share-pop { display: inline-block; margin-top: 10px; font-size: 11.5px; color: var(--primary); text-decoration: none; align-self: flex-end; }
.share-pop:hover { text-decoration: underline; }

.ds-preview li { display: flex; align-items: center; justify-content: space-between; padding: 5px 8px; background: var(--surface-sunken); border-radius: 6px; font-size: 12px; }
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

</style>
