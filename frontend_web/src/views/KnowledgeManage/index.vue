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

    <!-- 知识检索 / 知识对话: 两个 tab 共享一张卡, 由 settings.search.* / settings.chat.* 配置驱动 -->
    <div class="card card-share">
      <div class="share-hd">
        <div class="share-t">🔎 知识检索<span class="share-sub-inline">{{ activeSubLabel }}</span></div>
        <div class="share-tabs" role="tablist">
          <button
            class="share-tab"
            :class="{ active: activeTab === 'search' }"
            role="tab"
            :aria-selected="activeTab === 'search'"
            @click="activeTab = 'search'"
          ><span class="lbl">搜索</span></button>
          <button
            class="share-tab"
            :class="{ active: activeTab === 'chat' }"
            role="tab"
            :aria-selected="activeTab === 'chat'"
            @click="activeTab = 'chat'"
          ><span class="lbl">对话</span></button>
        </div>
      </div>
      <!-- 检索 tab -->
      <template v-if="activeTab === 'search'">
        <template v-if="searchEmbedUrl">
          <div class="share-frame-wrap" :style="{ minHeight: searchMinHeight + 'px' }">
            <iframe
              :src="searchResolvedUrl"
              frameborder="0"
              class="share-frame"
              :style="{ minHeight: searchMinHeight + 'px' }"
              title="knowledge-search"
              sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
              referrerpolicy="no-referrer"
            ></iframe>
          </div>
          <a :href="searchEmbedUrl"
             target="_blank" rel="noopener" class="share-pop">{{ searchOpenUrlLabel }}</a>
        </template>
        <div v-else class="search-placeholder">
          <div class="ph-ic">🔎</div>
          <div class="ph-t">知识检索建设中</div>
          <div class="ph-d">admin 可在 设置 → 知识检索 配置 <code>search.embed_url</code> 启用</div>
        </div>
      </template>

      <!-- 对话 tab -->
      <template v-else-if="activeTab === 'chat'">
        <template v-if="chatEmbedUrl">
          <div class="share-frame-wrap" :style="{ minHeight: searchMinHeight + 'px' }">
            <iframe
              :src="chatResolvedUrl"
              frameborder="0"
              class="share-frame"
              :style="{ minHeight: searchMinHeight + 'px' }"
              title="knowledge-chat"
              sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
              referrerpolicy="no-referrer"
            ></iframe>
          </div>
          <a :href="chatEmbedUrl"
             target="_blank" rel="noopener" class="share-pop">{{ chatOpenUrlLabel }}</a>
        </template>
        <div v-else class="search-placeholder">
          <div class="ph-ic">💬</div>
          <div class="ph-t">知识对话建设中</div>
          <div class="ph-d">admin 可在 设置 → 知识对话 配置 <code>chat.embed_url</code> 启用</div>
        </div>
      </template>

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
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref, watch } from 'vue';
import { buildEmbedUrl as apiBuildEmbedUrl, getSchema } from '@/api/settings';
import { listDatasets, kbHealth, type KbDataset } from '@/api/kb';

const datasets = ref<KbDataset[]>([]);
const loading = ref(false);

// 知识检索 / 知识对话: 从 system_settings 读 search.* / chat.* 配置, 一个卡两个 tab 共用
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

// 当前 tab 的副标题 (卡标题下那行小字, 说明底层引擎)
const activeSubLabel = computed(() => {
  if (activeTab.value === 'chat') return chatLabel.value;
  return searchLabel.value;
});

// 当前主题: 从 <html data-theme="..."> 读, light/dark/auto; auto 视作 light 传给后端
function readCurrentTheme(): string {
  const t = document.documentElement.getAttribute('data-theme') || 'light';
  return t === 'dark' ? 'dark' : 'light';
}

// 调后端 /api/v1/settings/embed/<key>?theme=xxx 拼 userId+theme, 后端按 schema 中 *\.append_user_id / *\.append_theme 开关

async function resolve(prefix: 'search' | 'chat', raw: string): Promise<string> {
  if (!raw) return '';
  try {
    const r = await apiBuildEmbedUrl(prefix, readCurrentTheme());
    return r.url || raw;
  } catch (e) {
    console.warn('build embed url failed', prefix, e);
    return raw; // 后端失败时降级用 raw URL, 页面不至于空白
  }
}
const searchResolvedUrl = ref('');
const chatResolvedUrl = ref('');

// 拼 URL: 当前 tab 的 raw URL + 后端 runtime 拼 userId/theme
// 注意: loadSearchConfig 异步拉配置, 期间 raw URL 还没填; 所以同时监听 activeTab 和 raw URL,
//       只有两边都 ready 才发请求, 避免一上来并发 3 个 (也避免空 raw 发请求).
function resolveForTab(t: ShareTab) {
  if (t === 'search' && !searchResolvedUrl.value && searchEmbedUrl.value) {
    resolve('search', searchEmbedUrl.value).then((u) => (searchResolvedUrl.value = u));
  } else if (t === 'chat' && !chatResolvedUrl.value && chatEmbedUrl.value) {
    resolve('chat', chatEmbedUrl.value).then((u) => (chatResolvedUrl.value = u));
  }
}
watch(activeTab, (t) => resolveForTab(t));
watch(searchEmbedUrl, (v) => { if (v && activeTab.value === 'search') resolveForTab('search'); });
watch(chatEmbedUrl, (v) => { if (v && activeTab.value === 'chat') resolveForTab('chat'); });

async function loadShareConfig() {
  try {
    const r = await getSchema();
    const searchItems = r.groups.find((g) => g.category === 'search')?.items || [];
    const chatItems = r.groups.find((g) => g.category === 'chat')?.items || [];
    for (const it of searchItems) {
      // 后端 value 已经是 merged (DB || default), 直接用
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
  } catch (e) {
    console.error('load search/chat config failed', e);
  }
}
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

onMounted(async () => {
  // 概览数据 + 配置并发拉, 任一失败 ElMessage 提示; 配置到位后拼默认 tab 的 URL
  await Promise.allSettled([loadAll(), loadShareConfig()]);
  resolveForTab(activeTab.value);
});
</script>

<style scoped>
.kb { display: flex; flex-direction: column; gap: 10px; }

/* 概览卡: 顶部一行, 3 列横排, 缩小 */
.card-overview { padding: 14px 18px; }
.card-overview h2 { margin-bottom: 10px; }
.card-overview .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.card-overview .stat { text-align: center; padding: 8px 6px; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 8px; }
.card-overview .num {
  font-size: 20px; font-weight: 800;
  font-family: var(--font-mono); line-height: 1; letter-spacing: -0.5px;
  background: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}
.card-overview .num.hi { color: var(--ok); }
.card-overview .lbl { font-size: 11px; color: var(--ink-500); margin-top: 4px; }

/* RAGFlow 共享搜索: 全宽, iframe 600px */
.card-share { display: flex; flex-direction: column; padding: 14px 18px; }
.card-share h2 { display: flex; align-items: center; gap: 8px; margin-bottom: 0; }
.share-hd { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 8px; flex-wrap: wrap; }
.share-t { font-size: 15px; font-weight: 700; color: var(--ink-900); display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.share-tabs { display: inline-flex; background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 9px; padding: 3px; gap: 2px; }
.share-tab {
  background: transparent; border: 0; cursor: pointer;
  padding: 6px 14px; border-radius: 7px;
  font-size: 12.5px; font-weight: 500; font-family: inherit;
  color: var(--ink-700);
  transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
}
.share-tab:hover { color: var(--ink-900); }
.share-tab.active {
  /* 保持浅色 (跟之前一致: var(--surface) 白底), 但文字从纯蓝改成品牌渐变
     跟 Settings toc / Sidebar nav / Plaza filter 的 active 风格统一 */
  background: var(--surface);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08), 0 0 0 1px var(--primary-soft);
}
.share-tab.active .lbl {
  display: inline-block;  /* inline 元素 background-clip:text 在部分浏览器失效, 转 inline-block */
  background: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}
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
.s-ok { background: rgba(22, 163, 74, 0.1); color: var(--ok); }
.s-warn { background: rgba(217, 119, 6, 0.1); color: var(--warn); }
.s-off { background: rgba(220, 38, 38, 0.1); color: var(--err); }


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
