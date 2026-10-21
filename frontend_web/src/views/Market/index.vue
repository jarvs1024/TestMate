<template>
  <div class="market">
    <!-- ===== 同步状态条: 本地已存 ≠ 已共享, 这个差异必须显式暴露 ===== -->
    <div v-if="hasSyncNotice" class="sync-bar" :class="{ hasErr: sync.failed_count > 0 || sync.conflict_count > 0 }">
      <span class="sb-icon">{{ sync.failed_count || sync.conflict_count ? '❌' : '🕐' }}</span>
      <span class="sb-text">
        <template v-if="sync.failed_count">{{ sync.failed_count }} 个资产同步失败</template>
        <template v-else-if="sync.conflict_count">{{ sync.conflict_count }} 个资产更新冲突已自动解决</template>
        <template v-else-if="sync.pending_count">{{ sync.pending_count }} 个资产待同步到 GitLab</template>
        <template v-else-if="sync.updatable_count">{{ sync.updatable_count }} 个已安装资产有新版本</template>
        <span class="sb-sub">{{ syncSubHint }}</span>
      </span>
      <button v-if="sync.failed_count" class="sb-btn" :disabled="retrying" @click="retryAll">
        {{ retrying ? '重试中…' : '全部重试' }}
      </button>
      <button class="sb-btn ghost" @click="load">刷新</button>
    </div>

    <!-- ===== 类型 Tab: 插件 / 技能 / 连接器 ===== -->
    <div class="mk-toolbar">
      <div class="kind-tabs">
        <button v-for="k in MARKET_KINDS" :key="k.value"
          class="kind-tab" :class="{ active: kind === k.value }"
          @click="kind = k.value">
          {{ k.label }}
          <span class="count">{{ kindCounts[k.value] || 0 }}</span>
        </button>
      </div>

      <div class="toolbar-right">
        <button class="mini-btn" :class="{ on: onlyInstalled }"
                :title="onlyInstalled ? '显示全部资产' : '只看我已安装的'"
                @click="onlyInstalled = !onlyInstalled; load()">
          <span :class="{ 'tick-off': !onlyInstalled }">✓</span> 已安装
        </button>
        <el-tooltip content="把团队沉淀的技能 / 连接器 / 插件上架到 GitLab" placement="bottom">
          <button class="mini-btn primary" @click="openCreate">＋ 上传资产</button>
        </el-tooltip>
        <div class="search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
          </svg>
          <input v-model="keyword" placeholder="搜索名称、说明或标签" @input="onSearch" />
        </div>
      </div>
    </div>

    <!-- ===== 分类 + 排序 ===== -->
    <div class="mk-filters">
      <div class="chips">
        <button class="chip" :class="{ active: category === '' }" @click="category = ''; load()">
          全部 <span class="count">{{ total }}</span>
        </button>
        <button class="chip" :class="{ active: category === '__featured' }" @click="category = '__featured'; load()">
          精选
        </button>
        <button v-for="c in MARKET_CATEGORIES" :key="c" class="chip"
          :class="{ active: category === c }" @click="category = c; load()">
          {{ c }}
        </button>
      </div>
      <select v-model="sortBy" class="sort" @change="load">
        <option value="hot">热门</option>
        <option value="new">最新</option>
        <option value="name">名称</option>
      </select>
    </div>

    <!-- ===== 加载 / 空态 / 错误 ===== -->
    <div v-if="loading" class="state">
      <div class="spinner" />
      <div>正在从 GitLab 加载资产索引…</div>
    </div>
    <div v-else-if="loadError" class="state err">
      <div style="font-size: 28px">⚠️</div>
      <div>{{ loadError }}</div>
      <button class="reset" @click="load">重试</button>
    </div>
    <div v-else-if="list.length === 0" class="state">
      <div style="font-size: 30px; opacity: 0.4">🏪</div>
      <div>该分类下还没有资产</div>
      <button class="reset" @click="resetFilters">清空筛选</button>
    </div>
    <div v-else class="grid">
      <AssetCard v-for="it in list" :key="it.code" :item="it" @open="openDetail" />
    </div>

    <AssetDetailDrawer
      v-model="drawerOpen" :item="current" :can-edit="true"
      @edit="openUpdate" @changed="load" />

    <AssetUploadDialog
      v-model="uploadOpen" :mode="uploadMode" :asset="current"
      @done="load" />

    <p v-if="total > 0" class="foot-hint mono">
      共 {{ total }} 项 · 数据源: GitLab {{ GITLAB_PROJECT }}
      <button v-if="!syncing" class="link-btn" @click="doSync">重新同步</button>
      <span v-else class="muted">同步中…</span>
      <span v-if="sync.last_sync_at" class="muted">
        · 最近对齐 {{ new Date(sync.last_sync_at).toLocaleTimeString('zh-CN') }}
      </span>
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import AssetCard from './AssetCard.vue';
import AssetDetailDrawer from './AssetDetailDrawer.vue';
import AssetUploadDialog from './AssetUploadDialog.vue';
import { MARKET_CATEGORIES, MARKET_KINDS } from './marketCatalog';
import {
  listAssets, listJobs, getSyncStatus, retryJob, syncFromGit,
  type AssetItem, type AssetJob, type MarketKind, type SyncStatus,
} from '@/api/assets';

const GITLAB_PROJECT = 'root/testmate-market';
/** 列表加载超时 (ms) —— 超过就提示重试, 不让页面无限转圈 */
const LOAD_TIMEOUT_MS = 15000;

const kind = ref<MarketKind>('plugin');
const category = ref('');
const keyword = ref('');
const sortBy = ref<'hot' | 'new' | 'name'>('hot');
const onlyInstalled = ref(false);

const items = ref<AssetItem[]>([]);
const total = ref(0);
const loading = ref(false);
const loadError = ref('');
const syncing = ref(false);
const retrying = ref(false);
const kindCounts = ref<Record<string, number>>({});
const failedJobs = ref<AssetJob[]>([]);
const drawerOpen = ref(false);
const current = ref<AssetItem | null>(null);
const uploadOpen = ref(false);
const uploadMode = ref<'create' | 'update'>('create');
const sync = ref<SyncStatus>({
  has_remote_updates: false, conflict_count: 0, pending_count: 0,
  failed_count: 0, updatable_count: 0, unpublished_count: 0, last_sync_at: null,
});

/** 防御: items 可能是 undefined (响应形状异常 / 请求被中断), 绝不能让 list.length 抛错
 *  —— 一旦渲染抛异常, Vue 会保留上一次的 DOM, 页面就会永远停在 loading 态. */
const list = computed(() => items.value ?? []);

const hasSyncNotice = computed(() =>
  sync.value.pending_count > 0 || sync.value.failed_count > 0 ||
  sync.value.conflict_count > 0 || sync.value.updatable_count > 0);

const syncSubHint = computed(() => {
  if (sync.value.failed_count) return '资产仍在本机工作区, 只是没推到 GitLab';
  if (sync.value.conflict_count) return '多人同时改了同一资产, 已按版本号高低自动取舍';
  if (sync.value.pending_count) return '已保存在本机工作区, 推送完成后才算共享给团队';
  return '本地安装的版本比仓库里的旧, 建议更新';
});

/* Tab 上的计数: 各类型总数, 不受筛选影响 */
async function loadKindCounts() {
  try {
    const counts: Record<string, number> = {};
    for (const k of MARKET_KINDS) {
      const r = await listAssets({ kind: k.value, limit: 500 });
      counts[k.value] = r?.total ?? r?.items?.length ?? 0;
    }
    kindCounts.value = counts;
  } catch {
    /* 计数失败不阻塞主列表 */
  }
}

async function load() {
  loading.value = true;
  loadError.value = '';
  // 看门狗: 请求卡住 (网络中断 / 上游异常) 时给出可操作提示, 而不是无限转圈
  const watchdog = window.setTimeout(() => {
    if (loading.value) loadError.value = '加载超时, 请检查后端服务后点「重试」';
  }, LOAD_TIMEOUT_MS);
  try {
    const r = await listAssets({
      kind: kind.value,
      category: category.value === '__featured' ? undefined : (category.value || undefined),
      q: keyword.value.trim() || undefined,
      sort: sortBy.value,
      limit: 500,
    });
    const rows = r?.items ?? [];
    items.value = category.value === '__featured'
      ? rows.filter((i) => i.featured)
      : rows;
    if (onlyInstalled.value) items.value = items.value.filter((i) => i.installed);
    total.value = r?.total ?? rows.length;
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail || e?.message || '未知错误';
    items.value = [];
    total.value = 0;
  } finally {
    window.clearTimeout(watchdog);
    loading.value = false;
  }
}

let searchTimer: number | null = null;
function onSearch() {
  if (searchTimer) window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(load, 320);
}

async function loadSyncStatus() {
  try {
    const s = await getSyncStatus();
    sync.value = { ...sync.value, ...(s ?? {}) };
  } catch {
    /* 状态条失败不阻塞 */
  }
}

async function pollJobs() {
  try {
    const r = await listJobs(20);
    failedJobs.value = r.items.filter((j) => j.status === 'failed');
    const active = r.items.some((j) => j.status === 'staged' || j.status === 'syncing');
    if (active) await load();
    await loadSyncStatus();
  } catch {
    /* 轮询失败静默 */
  }
}

async function retryAll() {
  retrying.value = true;
  try {
    for (const j of failedJobs.value) {
      try { await retryJob(j.id); } catch { /* 单个失败不中断 */ }
    }
    ElMessage.success('已重新排队, 正在重试同步');
    await pollJobs();
  } finally {
    retrying.value = false;
  }
}

async function doSync() {
  syncing.value = true;
  try {
    const r = await syncFromGit();
    ElMessage.success(`已从 GitLab 同步: 新增 ${r.added} / 更新 ${r.updated}`);
    await load();
    await loadKindCounts();
    await loadSyncStatus();
  } catch (e: any) {
    ElMessage.error('同步失败: ' + (e?.response?.data?.detail || e?.message));
  } finally {
    syncing.value = false;
  }
}

function openDetail(item: AssetItem) {
  current.value = item;
  drawerOpen.value = true;
}

function openCreate() {
  uploadMode.value = 'create';
  uploadOpen.value = true;
}

function openUpdate(item: AssetItem) {
  current.value = item;
  uploadMode.value = 'update';
  uploadOpen.value = true;
}

function resetFilters() {
  category.value = '';
  keyword.value = '';
  onlyInstalled.value = false;
  sortBy.value = 'hot';
  load();
}

watch(kind, () => load());

let timer: number | null = null;
onMounted(async () => {
  await Promise.all([load(), loadKindCounts(), loadSyncStatus()]);
  timer = window.setInterval(pollJobs, 5000);
});
onUnmounted(() => {
  if (timer) window.clearInterval(timer);
});
</script>

<style scoped>
.market { display: flex; flex-direction: column; gap: 14px; }

/* ===== 同步状态条 ===== */
.sync-bar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.28);
  border-radius: var(--radius-card);
  padding: 9px 14px; font-size: 12.5px; color: var(--warn);
}
.sync-bar.hasErr {
  background: rgba(239, 68, 68, 0.07);
  border-color: rgba(239, 68, 68, 0.3); color: var(--err);
}
.sb-icon { font-size: 15px; }
.sb-text { display: flex; flex-direction: column; gap: 1px; flex: 1; min-width: 0; }
.sb-sub { font-size: 11px; color: var(--ink-500); }
.sb-btn {
  background: var(--surface); border: 1px solid var(--border);
  padding: 5px 12px; border-radius: var(--radius-pill);
  font-size: 12px; color: var(--ink-700); cursor: pointer; font-family: inherit;
}
.sb-btn:hover:not(:disabled) { border-color: var(--primary); color: var(--ink-900); }
.sb-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.sb-btn.ghost { background: transparent; }

/* ===== 类型 Tab ===== */
.mk-toolbar {
  display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 10px 14px; box-shadow: var(--shadow-sm);
  position: sticky; top: 0; z-index: 4;
}
.kind-tabs { display: flex; gap: 6px; }
.kind-tab {
  background: transparent; border: 1px solid transparent;
  padding: 7px 16px; border-radius: var(--radius-pill);
  font-size: 13.5px; color: var(--ink-700); cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
  display: inline-flex; align-items: center; gap: 6px;
}
.kind-tab:hover { background: var(--surface-sunken); color: var(--ink-900); }
.kind-tab.active { background: var(--primary-grad-soft); font-weight: 700; box-shadow: inset 0 0 0 1px var(--border); }
.kind-tab.active .count { background: var(--primary-grad); color: #fff; }
.count {
  font-size: 11px; background: var(--surface); color: var(--ink-700);
  padding: 1px 7px; border-radius: var(--radius-pill);
  font-family: var(--font-mono); font-weight: 600;
}

.toolbar-right { display: flex; align-items: center; gap: 8px; }
.mini-btn {
  display: inline-flex; align-items: center; gap: 5px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 6px 12px; border-radius: 8px;
  font-size: 12.5px; color: var(--ink-700); cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
}
.mini-btn:hover { border-color: var(--primary); color: var(--ink-900); }
.mini-btn.on { background: rgba(16, 185, 129, 0.12); border-color: transparent; color: var(--ok); font-weight: 600; }
.mini-btn.primary { color: #fff; border-color: transparent; background: var(--primary-grad); }
.mini-btn.primary:hover { filter: brightness(1.06); color: #fff; }
.tick-off { opacity: 0.3; }

.search {
  display: flex; align-items: center; gap: 6px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 6px 10px; border-radius: 8px; color: var(--ink-500);
}
.search input {
  border: 0; outline: none; background: transparent;
  font-size: 13px; color: var(--ink-900); font-family: inherit; width: 190px;
}

/* ===== 分类 + 排序 ===== */
.mk-filters { display: flex; justify-content: space-between; align-items: center; gap: 14px; flex-wrap: wrap; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip {
  background: transparent; border: 1px solid var(--border);
  padding: 5px 12px; border-radius: var(--radius-pill);
  font-size: 12.5px; color: var(--ink-07); cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
  display: inline-flex; align-items: center; gap: 5px;
}
.chip:hover { background: var(--surface-sunken); color: var(--ink-900); }
.chip.active { background: var(--primary-grad); border-color: transparent; color: #fff; font-weight: 600; }
.chip.active .count { background: rgba(255, 255, 255, 0.25); color: #fff; }

.sort {
  background: var(--surface); border: 1px solid var(--border);
  padding: 6px 10px; border-radius: 8px;
  font-size: 12.5px; color: var(--ink-700); font-family: inherit; cursor: pointer;
}

/* ===== 网格 ===== */
.grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
@media (max-width: 1100px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

.state {
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 56px 20px; text-align: center; color: var(--ink-500);
  font-size: 13.5px; display: flex; flex-direction: column; gap: 10px; align-items: center;
}
.state.err { color: var(--err); border-color: rgba(239, 68, 68, 0.3); }
.spinner {
  width: 22px; height: 22px; border-radius: 50%;
  border: 2px solid var(--border); border-top-color: var(--primary);
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.reset {
  background: transparent; border: 1px solid var(--border);
  padding: 5px 14px; border-radius: var(--radius-pill);
  font-size: 12px; color: var(--ink-700); cursor: pointer; font-family: inherit;
}
.reset:hover { border-color: var(--primary); color: var(--ink-900); }

.foot-hint {
  font-size: 11px; color: var(--ink-500);
  display: flex; align-items: center; gap: 8px; padding-top: 4px; flex-wrap: wrap;
}
.link-btn {
  background: transparent; border: 0; color: var(--primary);
  font-size: 11px; cursor: pointer; font-family: inherit; padding: 0; text-decoration: underline;
}
.muted { color: var(--ink-500); }
</style>
