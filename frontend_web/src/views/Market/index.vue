<template>
  <div class="market">
    <!-- ===== 动作条: 返回 + 类型 Tab + 搜索 + 主操作 (一栏装下) ===== -->
    <div class="mk-actions">
      <button class="back" type="button" @click="$router.push({ name: 'plaza' })">← 返回广场</button>
      <div class="kind-tabs">
        <button v-for="k in MARKET_KINDS" :key="k.value"
          class="kind-tab" :class="{ active: kind === k.value }"
          @click="kind = k.value">
          {{ k.label }}
          <span class="count">{{ kindCounts[k.value] || 0 }}</span>
        </button>
      </div>
      <div class="ma-right">
        <div class="search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
          </svg>
          <input v-model="keyword" placeholder="搜索名称、说明或标签" @input="onSearch" />
        </div>
        <el-tooltip content="谁在什么时候上架/下架/安装过, 以及钉钉通知送没送到" placement="bottom">
          <button class="mini-btn" @click="auditOpen = true">🕘 操作记录</button>
        </el-tooltip>
        <el-tooltip content="把团队沉淀的技能 / 连接器 / 插件上架到 GitLab" placement="bottom">
          <button class="mini-btn primary" @click="openCreate">＋ 上传资产</button>
        </el-tooltip>
      </div>
    </div>

    <!-- ===== 同步状态条: 本地已存 ≠ 已共享, 这个差异必须显式暴露 ===== -->
    <div v-if="hasSyncNotice" class="sync-bar" :class="{ hasErr: sync.failed_count > 0 || sync.conflict_count > 0 }">
      <span class="sb-icon">{{ sync.failed_count || sync.conflict_count ? '❌' : '🕐' }}</span>
      <span class="sb-text">
        <template v-if="sync.failed_count">{{ sync.failed_count }} 个资产同步失败</template>
        <template v-else-if="sync.conflict_count">{{ sync.conflict_count }} 个资产更新冲突已自动解决</template>
        <template v-else-if="sync.pending_count">{{ sync.pending_count }} 个资产待同步到 GitLab</template>
        <span class="sb-sub">{{ syncSubHint }}</span>
      </span>
      <button v-if="sync.failed_count" class="sb-btn" :disabled="retrying" @click="retryAll">
        {{ retrying ? '重试中…' : '全部重试' }}
      </button>
      <button class="sb-btn ghost" @click="load">刷新</button>
    </div>

    <!-- ===== 我提交但还没过审的资产: 给个显眼入口, 免得被埋在列表里 ===== -->
    <div v-if="sync.my_review_count > 0" class="my-review-bar">
      <span>📋 你有 <b>{{ sync.my_review_count }}</b> 个资产需要处理 (在等审核或被驳回)</span>
      <button class="mrb-btn" @click="toggleOnlyMine">
        {{ onlyMine ? '显示全部' : '只看这些' }}
      </button>
    </div>

    <!-- ===== 下架申请: 作者等确认 / 管理员等拍板 ===== -->
    <div v-if="sync.my_unpublish_count > 0" class="my-review-bar">
      <span>🗑 你的 <b>{{ sync.my_unpublish_count }}</b> 个资产在等下架确认 —— 管理员通过后会被彻底删除</span>
      <button class="mrb-btn" @click="toggleOnlyMine">
        {{ onlyMine ? '显示全部' : '只看这些' }}
      </button>
    </div>
    <div v-if="isAdmin && othersUnpublishCount > 0" class="my-review-bar admin">
      <span>🗑 有 <b>{{ othersUnpublishCount }}</b> 个资产在等下架确认 —— 通过后会被彻底删除</span>
      <button class="mrb-btn" @click="load">刷新</button>
    </div>

    <!-- ===== 分类 + 排序 (状态不在这层过滤 —— 每张卡片自己标着) ===== -->
    <div class="mk-filters">
      <div class="cat-chips">
        <button class="chip" :class="{ active: category === '' }" @click="category = ''; load()">
          全部 <span class="count">{{ rawItems.length }}</span>
        </button>
        <button class="chip" :class="{ active: category === '__featured' }" @click="category = '__featured'; load()">
          ⭐ 精选
        </button>
        <button v-for="c in categories" :key="c.name" class="chip"
                :class="{ active: category === c.name }" :title="c.desc"
                @click="category = c.name; load()">
          {{ c.name }}<span v-if="c.total" class="count">{{ c.total }}</span>
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
      v-model="drawerOpen" :item="current" :can-edit="canEdit"
      @edit="openUpdate" @deleted="current = null" @changed="onAssetChanged" />

    <AssetUploadDialog
      v-model="uploadOpen" :mode="uploadMode" :asset="current"
      @done="load" />

    <AssetAuditDrawer v-model="auditOpen" />

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
import AssetAuditDrawer from './AssetAuditDrawer.vue';
import { useUserStore } from '@/stores/user';
import { MARKET_KINDS } from './marketCatalog';
import {
  listAssets, listCategories, listJobs, getSyncStatus, retryJob, syncFromGit,
  type AssetItem, type AssetJob, type MarketKind, type SyncStatus,
} from '@/api/assets';

const GITLAB_PROJECT = 'root/testmate-market';
/** 列表加载超时 (ms) —— 超过就提示重试, 不让页面无限转圈 */
const LOAD_TIMEOUT_MS = 15000;

const kind = ref<MarketKind>('plugin');
const category = ref('');
const keyword = ref('');
const sortBy = ref<'hot' | 'new' | 'name'>('hot');
/** 只看我自己的"待处理"资产 (提示条里的即时过滤, 不做成常驻筛选) */
const onlyMine = ref(false);

function toggleOnlyMine() {
  onlyMine.value = !onlyMine.value;
  load();
}
/** 未过滤的结果 (分类 chip 上的「全部 N」用) */
const rawItems = ref<AssetItem[]>([]);

const userStore = useUserStore();
/** 管理员 —— 能拍板下架申请 (通过 = 资产被彻底删除) */
const isAdmin = computed(() => userStore.user?.role === 'admin');
/** 别人申请下架、还在等确认的资产数 (管理员视角) */
const othersUnpublishCount = computed(() =>
  Math.max(0, sync.value.unpublish_pending_count - sync.value.my_unpublish_count));

/** 能不能改这个资产 (更新版本 / 下架 / 彻底删除) —— **作者本人或管理员**.
 *  ⚠️ 之前是硬编码 true —— 任何登录用户打开别人的资产都能看到并操作这些按钮,
 *    后端也没拦 (只查"是不是发布者"). 多用户场景下这是完整的越权链路.
 *    现在前端按作者判断, 后端也加了同样的校验 (见 _assert_can_modify).
 */
const canEdit = computed(() => {
  const it = current.value;
  if (!it) return false;
  if (userStore.user?.role === 'admin') return true;
  const me = (userStore.user?.username || '').trim().toLowerCase();
  const author = (it.author || '').trim().toLowerCase();
  return !!me && !!author && me === author;
});



const items = ref<AssetItem[]>([]);
const total = ref(0);
const loading = ref(false);
const loadError = ref('');
const syncing = ref(false);
const retrying = ref(false);
const kindCounts = ref<Record<string, number>>({});
const failedJobs = ref<AssetJob[]>([]);
const drawerOpen = ref(false);
const auditOpen = ref(false);
const current = ref<AssetItem | null>(null);
const uploadOpen = ref(false);
const uploadMode = ref<'create' | 'update'>('create');
const sync = ref<SyncStatus>({
  has_remote_updates: false, conflict_count: 0, pending_count: 0,
  failed_count: 0, unpublished_count: 0,
  awaiting_review_count: 0, rejected_count: 0, my_review_count: 0, my_pending_count: 0,
  unpublish_pending_count: 0, my_unpublish_count: 0,
  last_sync_at: null,
});

/** 防御: items 可能是 undefined (响应形状异常 / 请求被中断), 绝不能让 list.length 抛错
 *  —— 一旦渲染抛异常, Vue 会保留上一次的 DOM, 页面就会永远停在 loading 态. */
const list = computed(() => items.value ?? []);

const hasSyncNotice = computed(() =>
  sync.value.pending_count > 0 || sync.value.failed_count > 0 ||
  sync.value.conflict_count > 0);

const syncSubHint = computed(() => {
  if (sync.value.failed_count) return '资产仍在本机工作区, 只是没推到 GitLab';
  if (sync.value.conflict_count) return '多人同时改了同一资产, 已按版本号高低自动取舍';
  if (sync.value.pending_count) return '已保存在本机工作区, 推送完成后才算共享给团队';
  return '本地安装的版本比仓库里的旧, 建议更新';
});

/* 分类表 (后端下发的完整分类 + 各分类资产数) —— chip 动态渲染, 不再硬编码.
   ⚠️ 以前用硬编码的 MARKET_CATEGORIES: 用户自建的分类**没有 chip** → 筛不出来. */
const categories = ref<{ name: string; slug: string; desc?: string; total: number }[]>([]);
async function loadCategories() {
  try {
    const r = await listCategories();
    categories.value = (r?.items || []) as typeof categories.value;
  } catch {
    /* 分类表拿不到就不显示 chip, 不阻塞主列表 */
  }
}

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
      // 「只看这些」时不按类型卡 —— 我提交的待审资产可能是任意类型
      kind: onlyMine.value ? undefined : kind.value,
      category: category.value === '__featured' ? undefined : (category.value || undefined),
      q: keyword.value.trim() || undefined,
      sort: sortBy.value,
      limit: 500,
    });
    const rows = r?.items ?? [];
    rawItems.value = rows;
    items.value = category.value === '__featured'
      ? rows.filter((i) => i.featured)
      : rows;
    if (onlyMine.value) {
      // 提示条的"只看这些": 我自己提交的、还没过审的
      const me = (userStore.user?.username || '').trim();
      items.value = items.value.filter(
        (i) => (i.author || '').trim() === me
          && (i.publish_status === 'pending' || i.publish_status === 'rejected'),
      );
    }
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

/** 资产状态变了 (审核/上下架/删除) —— 列表和抽屉里那份都要跟着更新 */
async function onAssetChanged() {
  await load();
  if (!current.value) return;
  // 列表里已经有**最新**的那份了 —— 直接用它, 不用再单独 GET 一次:
  //   ① 少一个请求  ② 资产刚被彻底删除时不会打到 404 (浏览器控制台会报错)
  const fresh = rawItems.value.find((i) => i.code === current.value!.code);
  if (!fresh) {
    // 资产没了 (下架审核通过 = 彻底删除) —— 关掉抽屉
    current.value = null;
    drawerOpen.value = false;
    return;
  }
  current.value = fresh;
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
  onlyMine.value = false;
  sortBy.value = 'hot';
  load();
}



watch(kind, () => load());

let timer: number | null = null;
onMounted(async () => {
  await Promise.all([load(), loadKindCounts(), loadSyncStatus(), loadCategories()]);
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

/* ===== 类型 Tab (在动作条里) ===== */
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

/* ===== 我提交但未过审的提示条 ===== */
.my-review-bar {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  background: rgba(59, 130, 246, 0.07);
  border: 1px solid rgba(59, 130, 246, 0.25);
  border-radius: var(--radius-card); padding: 8px 13px;
  font-size: 12.5px; color: var(--ink-700);
}
.my-review-bar b { color: var(--primary); }
.my-review-bar.admin { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.3); }
.my-review-bar.admin b { color: var(--warn); }
.mrb-btn {
  background: transparent; border: 1px solid var(--primary); color: var(--primary);
  padding: 3px 12px; border-radius: var(--radius-pill);
  font-size: 12px; cursor: pointer; font-family: inherit;
}
.mrb-btn:hover { background: var(--primary); color: #fff; }

/* ===== 动作条: 返回 + 类型 Tab + 搜索 + 主操作 (一栏, 粘顶) ===== */
.mk-actions {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 10px 14px; box-shadow: var(--shadow-sm);
  position: sticky; top: 0; z-index: 4;
}
.ma-right {
  display: flex; align-items: center; gap: 8px;
  margin-left: auto; flex-shrink: 0;
}
.back {
  background: transparent; border: 1px solid var(--border);
  padding: 6px 12px; border-radius: 8px;
  color: var(--ink-700); font-size: 12.5px; cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
  flex-shrink: 0;
}
.back:hover { background: var(--surface-sunken); color: var(--ink-900); }


/* ===== 分类 + 排序 ===== */
.mk-filters {
  display: flex; justify-content: space-between; align-items: center;
  gap: 14px; flex-wrap: wrap;
}
.cat-chips { display: flex; gap: 6px; flex-wrap: wrap; }
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
