<template>
  <div class="kb">
    <!-- 概览 -->
    <div class="card card-overview">
      <h2>
        <span>概览</span>
        <span class="rf-status" :class="`s-${rfStatus}`" v-if="rfStatus">
          <span class="dot"></span>{{ rfMsg }}
        </span>
      </h2>
      <div class="stats">
        <div class="stat"><div class="num">{{ datasets.length }}</div><div class="lbl">数据集</div></div>
        <div class="stat"><div class="num">{{ totalDocs }}</div><div class="lbl">文档</div></div>
        <div class="stat"><div class="num">{{ totalChunks }}</div><div class="lbl">分段</div></div>
        <div class="stat"><div class="num">{{ fmtSize(totalSize) }}</div><div class="lbl">总大小</div></div>
      </div>
    </div>

    <!-- 知识检索 / 知识对话: 两个 tab 共享一张卡 -->
    <div class="card card-share">
      <div class="share-hd">
        <div class="share-t">🔎 知识检索<span class="share-sub-inline">{{ activeSubLabel }}</span></div>
        <div class="share-tabs" role="tablist">
          <button class="share-tab" :class="{ active: activeTab === 'search' }" @click="activeTab = 'search'"><span class="lbl">搜索</span></button>
          <button class="share-tab" :class="{ active: activeTab === 'chat' }" @click="activeTab = 'chat'"><span class="lbl">对话</span></button>
        </div>
      </div>
      <template v-if="activeTab === 'search'">
        <template v-if="searchEmbedUrl">
          <div class="share-frame-wrap" :style="{ minHeight: searchMinHeight + 'px' }">
            <iframe :key="`search-${themeKey}-${themeNonce}`" :src="searchIframeSrc" frameborder="0" class="share-frame" :style="{ minHeight: searchMinHeight + 'px' }" title="knowledge-search" sandbox="allow-scripts allow-same-origin allow-popups allow-forms" referrerpolicy="no-referrer"></iframe>
          </div>
          <a :href="searchEmbedUrl" target="_blank" rel="noopener" class="share-pop">{{ searchOpenUrlLabel }}</a>
        </template>
        <div v-else class="search-placeholder">
          <div class="ph-ic">🔎</div><div class="ph-t">知识检索建设中</div>
          <div class="ph-d">admin 可在 设置 → 知识检索 配置 <code>search.embed_url</code> 启用</div>
        </div>
      </template>
      <template v-else-if="activeTab === 'chat'">
        <template v-if="chatEmbedUrl">
          <div class="share-frame-wrap" :style="{ minHeight: searchMinHeight + 'px' }">
            <iframe :key="`chat-${themeKey}-${themeNonce}`" :src="chatIframeSrc" frameborder="0" class="share-frame" :style="{ minHeight: searchMinHeight + 'px' }" title="knowledge-chat" sandbox="allow-scripts allow-same-origin allow-popups allow-forms" referrerpolicy="no-referrer"></iframe>
          </div>
          <a :href="chatEmbedUrl" target="_blank" rel="noopener" class="share-pop">{{ chatOpenUrlLabel }}</a>
        </template>
        <div v-else class="search-placeholder">
          <div class="ph-ic">💬</div><div class="ph-t">知识对话建设中</div>
          <div class="ph-d">admin 可在 设置 → 知识对话 配置 <code>chat.embed_url</code> 启用</div>
        </div>
      </template>
    </div>

    <!-- 数据集列表 (P1 加列 + 行可展开看文档) -->
    <div class="card">
      <div class="ds-hd">
        <h2><span>数据集</span> <button class="reload" @click="loadAll" :disabled="loading">↻ 刷新</button></h2>
      </div>
      <table class="ds-tbl">
        <thead>
          <tr>
            <th style="width:24px"></th>
            <th>名称</th>
            <th>说明</th>
            <th>状态</th>
            <th>文档</th>
            <th>分段</th>
            <th>切片法</th>
            <th>更新时间</th>
            <th style="width:80px">操作</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="d in datasets" :key="d.id">
            <tr class="ds-row" :class="{ open: expandedId === d.id }">
              <td>
                <button class="exp" @click="toggleExpand(d.id)" :title="expandedId === d.id ? '收起' : '展开文档'">
                  {{ expandedId === d.id ? '▾' : '▸' }}
                </button>
              </td>
              <td class="nm">
                <span class="ds-ic">📁</span>
                <span>{{ d.name }}</span>
                <span class="ds-id mono">{{ d.id.slice(0, 8) }}…</span>
              </td>
              <td class="ds-desc" :title="d.description">{{ d.description || '—' }}</td>
              <td>
                <span class="run-badge" :class="d.status === '1' ? 'run-done' : 'run-fail'">{{ d.status === '1' ? '启用' : '禁用' }}</span>
              </td>
              <td class="mono">{{ d.document_count }}</td>
              <td class="mono">{{ d.chunk_count }}</td>
              <td class="mono">{{ fmtChunkMethod(d.chunk_method) }}</td>
              <td class="mono">{{ fmtTime(d.update_time) || d.update_date || '—' }}</td>
              <td>
                <button class="ghost-btn" @click="openDetail(d)">详情</button>
              </td>
            </tr>
            <!-- 展开的文档子表 -->
            <tr v-if="expandedId === d.id" class="ds-subrow">
              <td colspan="9" class="ds-subcell">
                <div class="doc-panel">
                  <div class="doc-hd">
                    <div class="doc-t">📄 {{ d.name }} · 文档列表</div>
                    <div class="doc-tools">
                      <button class="reload sm" @click="loadDocs(d.id)" :disabled="docLoading">↻</button>
                    </div>
                  </div>
                  <table class="doc-tbl">
                    <thead>
                      <tr>
                        <th>名称</th><th>大小</th><th>分段</th><th>Tokens</th><th>状态</th><th>进度</th><th>更新</th><th style="width:120px">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="doc in docsOf(d.id)" :key="doc.id" :class="{ failed: doc.run === 'FAIL' }">
                        <td class="nm">
                          <span class="doc-ic">{{ docIcon(doc.type) }}</span>
                          <span class="doc-name" :title="doc.location">{{ doc.name }}</span>
                        </td>
                        <td class="mono">{{ fmtSize(doc.size) }}</td>
                        <td class="mono">{{ doc.chunk_count }}</td>
                        <td class="mono">{{ doc.token_count }}</td>
                        <td>
                          <span class="run-badge" :class="runStatusClass(doc.run)" :title="doc.progress_msg || ''">{{ runStatusLabel(doc.run) }}</span>
                        </td>
                        <td class="prog-cell">
                          <div class="prog-bar"><div class="prog-fill" :style="{ width: Math.round((doc.progress || 0) * 100) + '%' }"></div></div>
                          <span class="prog-num">{{ Math.round((doc.progress || 0) * 100) }}%</span>
                        </td>
                        <td class="mono">{{ fmtTime(doc.update_time) || doc.update_date || '—' }}</td>
                        <td>
                          <a class="link-btn" :href="kbDownloadUrl(d.id, doc.id)" :download="doc.name" title="下载原文件">下载</a>
                          <button class="link-btn" @click="openChunks(d, doc)" title="查看分段内容">分段</button>
                        </td>
                      </tr>
                      <tr v-if="docsOf(d.id).length === 0 && !docLoading">
                        <td :colspan="8" class="empty">暂无文档</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </td>
            </tr>
          </template>
          <tr v-if="datasets.length === 0 && !loading">
            <td colspan="9" class="empty">暂无数据集</td>
          </tr>
          <tr v-if="loading">
            <td colspan="9" class="empty">加载中…</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 数据集详情抽屉 (P1) -->
    <el-drawer v-model="detailOpen" :title="detailDs?.name || '数据集详情'" size="520px" direction="rtl">
      <template v-if="detailDs">
        <div class="dt">
          <div class="dt-row"><span class="dt-k">ID</span><span class="dt-v mono">{{ detailDs.id }}</span></div>
          <div class="dt-row"><span class="dt-k">名称</span><span class="dt-v">{{ detailDs.name }}</span></div>
          <div class="dt-row"><span class="dt-k">嵌入模型</span><span class="dt-v mono">{{ detailDs.embedding_model || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">权限</span><span class="dt-v"><span class="perm" :class="`perm-${detailDs.permission}`">{{ detailDs.permission === 'team' ? '团队' : '私有' }}</span></span></div>
          <div class="dt-row"><span class="dt-k">语言</span><span class="dt-v">{{ detailDs.language || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">文档数</span><span class="dt-v mono">{{ detailDs.document_count }}</span></div>
          <div class="dt-row"><span class="dt-k">分段数</span><span class="dt-v mono">{{ detailDs.chunk_count }}</span></div>
          <div class="dt-row"><span class="dt-k">Token 数</span><span class="dt-v mono">{{ detailDs.token_num }}</span></div>
          <div class="dt-row"><span class="dt-k">切片法</span><span class="dt-v">{{ fmtChunkMethod(detailDs.chunk_method) }}（{{ detailDs.chunk_method }}）</span></div>
          <div class="dt-row"><span class="dt-k">相似度阈值</span><span class="dt-v mono">{{ detailDs.similarity_threshold }}</span></div>
          <div class="dt-row"><span class="dt-k">向量权重</span><span class="dt-v mono">{{ detailDs.vector_similarity_weight }}</span></div>
          <div class="dt-row"><span class="dt-k">PageRank</span><span class="dt-v mono">{{ detailDs.pagerank }}</span></div>
          <div class="dt-row"><span class="dt-k">创建</span><span class="dt-v mono">{{ fmtTime(detailDs.create_time) }}</span></div>
          <div class="dt-row"><span class="dt-k">更新</span><span class="dt-v mono">{{ fmtTime(detailDs.update_time) }}</span></div>

          <div class="dt-sep">切片参数 (parser_config)</div>
          <pre class="dt-pre mono">{{ JSON.stringify(detailDs.parser_config, null, 2) }}</pre>
        </div>
      </template>
    </el-drawer>

    <!-- 文档分段预览抽屉 -->
    <el-drawer v-model="chunksOpen" :title="chunksTitle" size="640px" direction="rtl">
      <div class="chunks-panel">
        <div class="chunks-hd">
          <div class="chunks-meta">
            <span class="chunks-tot">共 {{ chunksTotal }} 个分段</span>
            <span v-if="chunksLoading" class="chunks-load">加载中…</span>
          </div>
        </div>
        <div v-if="chunksList.length === 0 && !chunksLoading" class="empty">该文档暂无分段</div>
        <div v-for="(c, idx) in chunksList" :key="c.id" class="chunk-card">
          <div class="chunk-hd">
            <span class="chunk-num">#{{ idx + 1 }}</span>
            <span class="chunk-id mono">{{ c.id.slice(0, 12) }}…</span>
            <span v-if="c.important_keywords?.length" class="chunk-kw">
              <span v-for="k in c.important_keywords" :key="k" class="kw-tag">{{ k }}</span>
            </span>
            <span v-if="c.tag_kwd?.length" class="chunk-kw">
              <span v-for="t in c.tag_kwd" :key="t" class="kw-tag kw-tag-tag">{{ t }}</span>
            </span>
          </div>
          <div class="chunk-body">{{ c.content || '—' }}</div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import { buildEmbedUrl as apiBuildEmbedUrl, getSchema } from '@/api/settings';
import {
  listDatasets, kbHealth, type KbDataset, type KbDocument,
  listDocuments, downloadDocumentUrl, listDocChunks,
  type KbDocChunk,
} from '@/api/kb';
import { useThemeStore } from '@/stores/theme';
import {
  fmtSize, fmtTime, fmtChunkMethod, docIcon,
  runStatusClass, runStatusLabel,
} from '@/utils/format';

const datasets = ref<KbDataset[]>([]);
const loading = ref(false);
const rfStatus = ref<'ok' | 'warn' | 'off' | ''>('');
const rfMsg = ref('');

const themeStore = useThemeStore();

// search/chat embed 配置 (沿用)
type ShareTab = 'search' | 'chat';
const activeTab = ref<ShareTab>('search');
const searchEngine = ref('ragflow-share');
const searchEmbedUrl = ref('');
const searchLabel = ref('基于 RAGFlow 共享 Search App');
const searchOpenUrlLabel = ref('↗ 新窗口打开 RAGFlow 共享搜索');
const searchMinHeight = ref(600);
const chatEmbedUrl = ref('');
const chatLabel = ref('基于 RAGFlow 共享 Chat App');
const chatOpenUrlLabel = ref('↗ 新窗口打开 RAGFlow 共享对话');
const activeSubLabel = computed(() => activeTab.value === 'chat' ? chatLabel.value : searchLabel.value);
const themeKey = computed(() => themeStore.resolved);
const themeNonce = ref(Date.now());

function readCurrentTheme(): string { return themeStore.resolved; }

async function resolve(prefix: 'search' | 'chat', raw: string): Promise<string> {
  if (!raw) return '';
  try { const r = await apiBuildEmbedUrl(prefix, readCurrentTheme()); return r.url || raw; }
  catch (e) { console.warn('build embed url failed', prefix, e); return raw; }
}
const searchResolvedUrl = ref('');
const chatResolvedUrl = ref('');
function withNonce(u: string, nonce: number): string {
  if (!u) return '';
  return u + (u.includes('?') ? '&' : '?') + '_t=' + nonce;
}
const searchIframeSrc = computed(() => withNonce(searchResolvedUrl.value, themeNonce.value));
const chatIframeSrc = computed(() => withNonce(chatResolvedUrl.value, themeNonce.value));

async function reResolve(prefix: 'search' | 'chat') {
  const raw = prefix === 'search' ? searchEmbedUrl.value : chatEmbedUrl.value;
  if (!raw) return;
  const u = await resolve(prefix, raw);
  if (prefix === 'search') searchResolvedUrl.value = u; else chatResolvedUrl.value = u;
}

watch(() => themeStore.resolved, async () => {
  themeNonce.value++;
  await Promise.all([reResolve('search'), reResolve('chat')]);
});
watch(activeTab, async (t) => {
  if (t === 'search' && searchEmbedUrl.value && !searchResolvedUrl.value) await reResolve('search');
  else if (t === 'chat' && chatEmbedUrl.value && !chatResolvedUrl.value) await reResolve('chat');
});
watch(searchEmbedUrl, (v) => { if (v && activeTab.value === 'search' && !searchResolvedUrl.value) reResolve('search'); });
watch(chatEmbedUrl, (v) => { if (v && activeTab.value === 'chat' && !chatResolvedUrl.value) reResolve('chat'); });

async function loadShareConfig() {
  try {
    const r = await getSchema();
    const searchItems = r.groups.find((g) => g.category === 'search')?.items || [];
    const chatItems = r.groups.find((g) => g.category === 'chat')?.items || [];
    for (const it of searchItems) {
      const v = it.value;
      if (it.key === 'search.engine') searchEngine.value = v ?? 'ragflow-share';
      else if (it.key === 'search.embed_url') searchEmbedUrl.value = v ?? '';
      else if (it.key === 'search.label') searchLabel.value = v ?? '基于 RAGFlow 共享 Search App';
      else if (it.key === 'search.open_url_label') searchOpenUrlLabel.value = v ?? '↗ 新窗口打开';
      else if (it.key === 'search.min_height') searchMinHeight.value = Number(v) || 600;
    }
    for (const it of chatItems) {
      const v = it.value;
      if (it.key === 'chat.embed_url') chatEmbedUrl.value = v ?? '';
      else if (it.key === 'chat.label') chatLabel.value = v ?? '基于 RAGFlow 共享 Chat App';
      else if (it.key === 'chat.open_url_label') chatOpenUrlLabel.value = v ?? '↗ 新窗口打开';
    }
    if (searchEngine.value === 'none') searchEmbedUrl.value = '';
  } catch (e) { console.error('load search/chat config failed', e); }
}

// === 数据集 + 文档 ===
const totalDocs = computed(() => datasets.value.reduce((s, d) => s + d.document_count, 0));
const totalChunks = computed(() => datasets.value.reduce((s, d) => s + d.chunk_count, 0));
// P1: 概览加总大小 — 需要 docs, 用懒加载的总量; 这里先按数据集的 token_num 估算不易, 改为文档列表都加载后汇总
const totalSize = ref(0);

// 行展开
const expandedId = ref('');
const docsByDataset = ref<Record<string, KbDocument[]>>({});
const docLoadingByDs = ref<Record<string, boolean>>({});

function docsOf(datasetId: string): KbDocument[] { return docsByDataset.value[datasetId] || []; }
function docLoading(datasetId: string): boolean { return !!docLoadingByDs.value[datasetId]; }

async function toggleExpand(datasetId: string) {
  if (expandedId.value === datasetId) { expandedId.value = ''; return; }
  expandedId.value = datasetId;
  if (!docsByDataset.value[datasetId]) await loadDocs(datasetId);
}

async function loadDocs(datasetId: string) {
  docLoadingByDs.value[datasetId] = true;
  try {
    const r = await listDocuments(datasetId, { page_size: 100 });
    docsByDataset.value[datasetId] = r.docs;
    // 累加 totalSize
    totalSize.value = Object.values(docsByDataset.value).reduce(
      (s, list) => s + list.reduce((ss, doc) => ss + (doc.size || 0), 0), 0,
    );
  } catch (e: any) {
    ElMessage.error('加载文档失败: ' + (e?.response?.data?.detail || e?.message));
    docsByDataset.value[datasetId] = [];
  } finally {
    docLoadingByDs.value[datasetId] = false;
  }
}

// === 详情抽屉 ===
const detailOpen = ref(false);
const detailDs = ref<KbDataset | null>(null);
function openDetail(d: KbDataset) { detailDs.value = d; detailOpen.value = true; }

// 文档下载 (返回给 template 用的 url)
function kbDownloadUrl(datasetId: string, documentId: string): string {
  return downloadDocumentUrl(datasetId, documentId);
}

// chunks 抽屉状态
const chunksOpen = ref(false);
const chunksTitle = ref('');
const chunksList = ref<KbDocChunk[]>([]);
const chunksTotal = ref(0);
const chunksLoading = ref(false);

async function openChunks(d: KbDataset, doc: KbDocument) {
  chunksTitle.value = `📑 ${doc.name} · 分段预览`;
  chunksOpen.value = true;
  chunksList.value = [];
  chunksLoading.value = true;
  try {
    // RAGFlow 限制 page_size <= 100, 后端 / API 层都会兜底; 这里用 100
    const r = await listDocChunks(d.id, doc.id, { page_size: 100 });
    chunksList.value = r.chunks;
    chunksTotal.value = r.total;
  } catch (e: any) {
    ElMessage.error('加载分段失败: ' + (e?.response?.data?.detail || e?.message));
  } finally {
    chunksLoading.value = false;
  }
}

// === 数据加载 ===
async function loadAll() {
  loading.value = true;
  try {
    const h = await kbHealth();
    rfStatus.value = h.status as any;
    rfMsg.value = h.message || h.status;
    const r = await listDatasets();
    datasets.value = r.items;
    // 清掉已展开 dataset 不存在的 docs
    const keep = new Set(r.items.map(x => x.id));
    for (const id of Object.keys(docsByDataset.value)) {
      if (!keep.has(id)) { delete docsByDataset.value[id]; delete docLoadingByDs.value[id]; }
    }
  } catch (e: any) {
    rfStatus.value = 'off'; rfMsg.value = '加载失败';
    ElMessage.error('知识库加载失败: ' + (e?.response?.data?.detail || e?.message));
  } finally { loading.value = false; }
}

onMounted(async () => {
  await Promise.allSettled([loadAll(), loadShareConfig()]);
  if (activeTab.value === 'search' && searchEmbedUrl.value) await reResolve('search');
  else if (activeTab.value === 'chat' && chatEmbedUrl.value) await reResolve('chat');
});
</script>

<style scoped>
.kb { display: flex; flex-direction: column; gap: 10px; }
.card-overview { padding: 14px 18px; }
.card-overview h2 { margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
.card-overview .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.card-overview .stat { text-align: center; padding: 8px 6px; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 8px; }
.card-overview .num { font-size: 20px; font-weight: 800; font-family: var(--font-mono); line-height: 1; letter-spacing: -0.5px; background: var(--primary-grad-text); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; color: transparent; }
.card-overview .lbl { font-size: 11px; color: var(--ink-500); margin-top: 4px; }

/* RAGFlow 共享搜索 */
.card-share { display: flex; flex-direction: column; padding: 14px 18px; }
.share-hd { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 8px; flex-wrap: wrap; }
.share-t { font-size: 15px; font-weight: 700; color: var(--ink-900); display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.share-tabs { display: inline-flex; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 9px; padding: 3px; gap: 2px; }
.share-tab { background: transparent; border: 0; cursor: pointer; padding: 6px 14px; border-radius: 7px; font-size: 12.5px; font-weight: 500; font-family: inherit; color: var(--ink-700); transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease; }
.share-tab:hover { color: var(--ink-900); }
.share-tab.active { background: var(--surface); font-weight: 600; box-shadow: inset 0 0 0 1px var(--border); }
.share-tab.active .lbl { display: inline-block; background: var(--primary-grad-text); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; color: transparent; }
.share-sub-inline { font-size: 12px; font-weight: 400; color: var(--ink-500); }
.share-frame-wrap { width: 100%; border-radius: 10px; overflow: hidden; border: 1px solid var(--border); background: var(--surface-sunken); }
.share-frame { display: block; border: 0; width: 100%; height: 100%; min-height: inherit; }
.share-pop { display: inline-block; margin-top: 10px; font-size: 11.5px; color: var(--primary); text-decoration: none; align-self: flex-end; }
.share-pop:hover { text-decoration: underline; }
.search-placeholder { padding: 60px 20px; text-align: center; color: var(--ink-500); }
.ph-ic { font-size: 48px; opacity: 0.4; margin-bottom: 12px; }
.ph-t { font-size: 16px; font-weight: 600; color: var(--ink-700); margin-bottom: 6px; }
.ph-d { font-size: 12.5px; color: var(--ink-500); }
.ph-d code { background: var(--surface-sunken); padding: 2px 6px; border-radius: 4px; font-size: 11.5px; color: var(--primary); }

h2 { font-size: 15px; font-weight: 700; margin: 0 0 14px; color: var(--ink-900); display: flex; align-items: center; gap: 8px; }

.rf-status { margin-left: auto; font-size: 11px; font-weight: 500; display: inline-flex; align-items: center; gap: 5px; padding: 3px 9px; border-radius: var(--radius-pill); }
.rf-status .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.s-ok { background: rgba(16, 185, 129, 0.1); color: var(--ok); }
.s-warn { background: rgba(245, 158, 11, 0.1); color: var(--warn); }
.s-off { background: rgba(239, 68, 68, 0.1); color: var(--err); }

/* 数据集表 */
.ds-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
.ds-hd h2 { margin: 0; }
.reload { background: transparent; border: 1px solid var(--border); padding: 4px 10px; border-radius: 6px; color: var(--ink-700); font-size: 11.5px; cursor: pointer; font-family: inherit; }
.reload:hover { border-color: var(--primary); color: var(--primary); }
.reload:disabled { opacity: 0.5; }
.reload.sm { padding: 2px 8px; font-size: 11px; }

.ds-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.ds-tbl th { text-align: left; padding: 10px 12px; color: var(--ink-500); font-weight: 500; font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid var(--border); }
.ds-tbl td { padding: 10px 12px; color: var(--ink-700); border-bottom: 1px solid var(--border); vertical-align: middle; }
.ds-tbl tr:hover { background: var(--surface-sunken); }
.ds-row.open { background: var(--surface-sunken); }
.ds-row.open td { border-bottom-color: transparent; }

.exp { background: transparent; border: 0; color: var(--ink-500); cursor: pointer; font-size: 12px; padding: 2px 4px; }
.exp:hover { color: var(--primary); }

.nm { display: flex; align-items: center; gap: 6px; color: var(--ink-900); font-weight: 500; }
.ds-ic { font-size: 16px; }
.ds-id { font-size: 10.5px; color: var(--ink-500); margin-left: 4px; }
.emb { color: var(--ink-500); font-size: 11.5px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ds-desc { color: var(--ink-700); font-size: 12px; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.perm { font-size: 10.5px; padding: 2px 7px; border-radius: var(--radius-pill); font-weight: 600; }
.perm-me { background: var(--surface-sunken); color: var(--ink-700); }
.perm-team { background: rgba(13, 148, 136, 0.12); color: var(--primary-2, var(--primary)); }

.mono { font-family: var(--font-mono); font-size: 12px; }
.empty { text-align: center; color: var(--ink-500); padding: 32px 12px !important; }

.ghost-btn { background: transparent; border: 1px solid var(--border); color: var(--ink-700); padding: 3px 9px; border-radius: 6px; font-size: 11.5px; cursor: pointer; font-family: inherit; transition: border-color .15s, color .15s; }
.ghost-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--primary); }
.ghost-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* 文档子表 */
.ds-subcell { padding: 0 12px 14px 36px !important; background: var(--surface-sunken); }
.doc-panel { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.doc-hd { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.doc-t { font-size: 12.5px; font-weight: 600; color: var(--ink-900); }
.doc-tools { display: flex; gap: 6px; align-items: center; }
.doc-tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.doc-tbl th { text-align: left; padding: 6px 8px; color: var(--ink-500); font-weight: 500; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid var(--border); }
.doc-tbl td { padding: 7px 8px; color: var(--ink-700); border-bottom: 1px dashed var(--border); }
.doc-tbl tr:last-child td { border-bottom: none; }
.doc-tbl tr.failed td { background: rgba(239, 68, 68, 0.04); }
.doc-ic { font-size: 15px; margin-right: 4px; }
.doc-name { color: var(--ink-900); font-weight: 500; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; vertical-align: middle; }

.prog-cell { display: flex; align-items: center; gap: 6px; min-width: 130px; }
.prog-bar { flex: 1; height: 6px; background: var(--surface-sunken); border-radius: 999px; overflow: hidden; }
.prog-fill { height: 100%; background: var(--primary-grad); transition: width 0.3s ease; }
.prog-num { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-500); min-width: 32px; text-align: right; }

/* run 状态徽章 */
.run-badge { display: inline-block; font-size: 10.5px; padding: 2px 8px; border-radius: var(--radius-pill); font-weight: 600; white-space: nowrap; }
.run-done { background: rgba(16, 185, 129, 0.12); color: var(--ok); }
.run-running { background: rgba(59, 130, 246, 0.12); color: var(--primary); }
.run-unstart { background: var(--surface-sunken); color: var(--ink-500); }
.run-cancel { background: rgba(245, 158, 11, 0.12); color: var(--warn); }
.run-fail { background: rgba(239, 68, 68, 0.12); color: var(--err); }

/* 详情抽屉 */
.dt { display: flex; flex-direction: column; gap: 10px; }
.dt-row { display: grid; grid-template-columns: 110px 1fr; gap: 10px; align-items: baseline; padding: 6px 0; border-bottom: 1px dashed var(--border); }
.dt-k { font-size: 11.5px; color: var(--ink-500); }
.dt-v { font-size: 12.5px; color: var(--ink-900); }
.dt-v.mono { font-family: var(--font-mono); font-size: 12px; }
.dt-sep { font-size: 12.5px; font-weight: 700; color: var(--ink-700); margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--border); }
.dt-pre { font-family: var(--font-mono); font-size: 11.5px; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 6px; padding: 10px; max-height: 240px; overflow: auto; white-space: pre-wrap; word-break: break-all; }

/* 文档行内联操作按钮 (下载 / 分段) */
.link-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--ink-700);
  padding: 3px 9px;
  border-radius: 6px;
  font-size: 11px;
  font-family: inherit;
  cursor: pointer;
  margin-right: 4px;
  text-decoration: none;
  display: inline-block;
  transition: border-color .15s, color .15s, background .15s;
}
.link-btn:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-soft); }
.link-btn:last-child { margin-right: 0; }

/* chunks 抽屉 */
.chunks-panel { display: flex; flex-direction: column; gap: 12px; }
.chunks-hd { display: flex; align-items: center; justify-content: space-between; padding: 4px 0 8px; border-bottom: 1px solid var(--border); }
.chunks-meta { display: flex; gap: 10px; align-items: center; font-size: 12px; color: var(--ink-500); }
.chunks-tot { font-weight: 600; color: var(--ink-900); }
.chunks-load { color: var(--primary); }
.chunk-card { background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.chunk-hd { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.chunk-num { font-size: 11px; font-weight: 700; color: var(--primary); font-family: var(--font-mono); }
.chunk-id { font-size: 10.5px; color: var(--ink-500); }
.chunk-kw { display: inline-flex; gap: 4px; flex-wrap: wrap; margin-left: auto; }
.kw-tag { font-size: 10px; padding: 2px 7px; border-radius: var(--radius-pill); background: rgba(59, 130, 246, 0.1); color: var(--primary); font-weight: 500; }
.kw-tag-tag { background: rgba(13, 148, 136, 0.12); color: var(--primary-2, var(--primary)); }
.chunk-body { font-size: 12.5px; color: var(--ink-700); line-height: 1.6; white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow: auto; }

</style>
