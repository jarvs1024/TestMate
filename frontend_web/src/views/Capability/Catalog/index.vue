<template>
  <div class="market">
    <!-- ===== 能力详情统一外壳 ===== -->
    <CapabilityShell
      name="AI 资产市场"
      icon="🏪"
      kind="platform"
      status="beta"
      version="v0.1.0"
      category="ai-market" />

    <!-- ===== 动作条: 类型 Tab + 搜索 + 主操作 (一栏装下) ===== -->
    <div class="mk-actions">
      <div class="kind-tabs">
        <button v-for="k in MARKET_KINDS" :key="k.value"
          class="kind-tab" :class="{ active: kind === k.value }"
          @click="kind = k.value">
          {{ k.label }}
          <!-- ⚠️ 计数取不到时显示 "?" 而不是 0 —— 0 看着像"这个类型一个都没有" -->
          <span class="count" :title="kindCountsError ? `计数读取失败: ${kindCountsError}` : ''">
            {{ kindCountsError ? '?' : (kindCounts[k.value] || 0) }}
          </span>
        </button>
      </div>
      <div class="ma-right">
        <div class="search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
          </svg>
          <input v-model="keyword" placeholder="搜索名称、说明、标签或项目号"
                 title="项目号指资产归属的项目 (如 6100); 搜「通用」找通用资产"
                 @input="onSearch" />
        </div>
        <!-- ⚠️ 操作记录 = **运营数据** (谁在什么时候上架/下架/驳回/删了哪个资产,
             钉钉通知回了什么) —— 只给管理员. 后端也收紧了 (GET /assets/audits
             改成 admin only), 前端同步隐藏, 免得点了只吃一个 403. -->
        <el-tooltip v-if="isAdmin"
                    content="谁在什么时候上架/下架/更新过, 以及钉钉通知送没送到" placement="bottom">
          <button class="mini-btn" @click="auditOpen = true">🕘 操作记录</button>
        </el-tooltip>
        <!-- ===== 上传入口: 先选形态, 再进对应表单 (2026-10-24) =====
             以前点开就是「技能」表单, 传连接器得滚到底改类型下拉才知道要填 JSON。 -->
        <div class="upload-pick" ref="pickWrap">
          <button class="mini-btn primary" @click="pickOpen = !pickOpen">
            ＋ 上传资产 <span class="up-caret">▾</span>
          </button>
          <div v-if="pickOpen" class="pick-menu">
            <div class="pick-lead">选一种资产形态 —— 三种的配置表单不一样</div>
            <button v-for="k in KIND_META" :key="k.value" type="button"
                    class="pick-item" @click="startCreate(k.value)">
              <span class="pi-ic">{{ k.icon }}</span>
              <span class="pi-body">
                <b>{{ k.label }} <i>{{ k.code }}</i></b>
                <span class="pi-tag">{{ k.tagline }}</span>
              </span>
              <span class="pi-go">→</span>
            </button>
          </div>
        </div>
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
      <!-- ⚠️ 后端把 GET /assets/jobs 收紧了: 非管理员只能看到**自己**创建的任务.
           所以文案不能说"全部" —— 说的应该是"我看得见的那些失败任务". -->
      <button v-if="sync.failed_count" class="sb-btn" :disabled="retrying" @click="retryFailed">
        {{ retrying ? '重试中…' : '重试失败任务' }}
      </button>
      <button class="sb-btn ghost" @click="load">刷新</button>
    </div>

    <!-- ⚠️ 资产状态取不到 → 说清楚 (别让"同步状态条"整段消失, 看着像"一切正常") -->
    <div v-if="syncError" class="sync-bar err">
      <span class="sb-icon">⚠️</span>
      <span class="sb-text">资产状态读取失败: {{ syncError }}</span>
      <button class="sb-btn ghost" @click="loadSyncStatus">重试</button>
    </div>

    <!-- ===== 我提交但还没过审的资产: 给个显眼入口, 免得被埋在列表里 ===== -->
    <div v-if="sync.my_review_count > 0" class="my-review-bar">
      <span>📋 你有 <b>{{ sync.my_review_count }}</b> 个资产需要处理 (在等审核或被驳回)</span>
      <button class="mrb-btn" @click="toggleOnlyMine('review')">
        {{ onlyMine === 'review' ? '显示全部' : '只看这些' }}
      </button>
    </div>

    <!-- ===== 下架申请: 作者等确认 / 管理员等拍板 ===== -->
    <div v-if="sync.my_unpublish_count > 0" class="my-review-bar">
      <span>🗑 你的 <b>{{ sync.my_unpublish_count }}</b> 个资产在等下架确认 —— 管理员通过后会被彻底删除</span>
      <button class="mrb-btn" @click="toggleOnlyMine('unpublish')">
        {{ onlyMine === 'unpublish' ? '显示全部' : '只看这些' }}
      </button>
    </div>
    <div v-if="isAdmin && othersUnpublishCount > 0" class="my-review-bar admin">
      <span>🗑 有 <b>{{ othersUnpublishCount }}</b> 个资产在等下架确认 —— 通过后会被彻底删除</span>
      <button class="mrb-btn" @click="load">刷新</button>
    </div>

    <!-- ===== 分类 + 项目/排序筛选 (状态不在这层过滤 —— 每张卡片自己标着) ===== -->
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
          {{ c.name }}<span v-if="catCount(c)" class="count">{{ catCount(c) }}</span>
        </button>
      </div>

      <!-- ⚠️ 分类 / 项目取不到 → 筛选维度会凭空消失 (只剩「全部 / ⭐精选」),
           用户会以为市场里没有别的分类 —— 得说清楚是"读失败"不是"没有" -->
      <div v-if="filterLoadError" class="filter-err">⚠️ {{ filterLoadError }}</div>

      <!-- ===== 项目 + 排序 (合成一个下拉) =====
           原来项目是一排 chip, 跟分类 chip 挤在一起换行, 很乱.
           现在收进一个菜单: 按钮上显示当前选择 (如「6100 · 最新」),
           面板里分「项目」「排序」两组, 点一下就生效.
           语义跟原来一致: 选某项目 = 该项目特有 **+ 通用**; 选「通用」= 只看通用. -->
      <MarketFilterMenu
        :project="projectFilter"
        :sort="sortBy"
        :projects="projects"
        @update:project="onProjectChange"
        @update:sort="onSortChange" />
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
      <div>当前筛选下没有资产</div>
      <button class="reset" @click="resetFilters">清空筛选</button>
    </div>
    <div v-else class="grid">
      <AssetCard v-for="it in list" :key="it.code" :item="it" @open="openDetail" />
    </div>

    <AssetDetailDrawer
      v-model="drawerOpen" :item="current" :can-edit="canEdit"
      @edit="openUpdate" @deleted="current = null" @changed="onAssetChanged" />

    <AssetUploadDialog
      v-model="uploadOpen" :mode="uploadMode" :asset="current" :initial-kind="uploadKind"
      @done="load" />

    <AssetAuditDrawer v-model="auditOpen" />

    <p v-if="total > 0" class="foot-hint mono">
      共 {{ total }} 项 · 数据源: GitLab {{ gitRemoteText }}
      <button v-if="!syncing" class="link-btn" title="重新读一次市场数据 (不拉 GitLab, 快)"
              @click="manualRefresh">刷新</button>
      <!-- ⚠️ 「重新同步」= 从 GitLab 全量回灌 + 重新入队 → 后端已收紧成 **admin only**.
           非管理员点了只吃一个 403, 不如直接不显示. -->
      <button v-if="isAdmin && !syncing" class="link-btn" title="从 GitLab 拉取最新资产 (慢一点, 仅管理员)"
              @click="doSync">重新同步</button>
      <!-- ⚠️ 这里**不能**用 v-else: 非管理员 (isAdmin=false) 时按钮不渲染,
           v-else 会跟着渲染出「同步中…」—— 看着像有个同步一直在跑, 实际根本没有.
           所以单独判 syncing: 只有**真的在同步**时才显示. -->
      <span v-if="syncing" class="muted">同步中…</span>
      <!-- ⚠️ 两个时间源必须分清:
           「GitLab 最近对齐」= 后端最后一次从 GitLab 拉取的时间;
           「本页上次刷新」= 前端最后一次读本地镜像的时间. -->
      <span v-if="sync.last_sync_at" class="muted">
        · GitLab 最近对齐 {{ new Date(sync.last_sync_at).toLocaleTimeString('zh-CN') }}
      </span>
      <span class="muted" :class="{ 'refresh-fail': !!refreshError }">
        · 本页上次刷新 {{ lastRefreshText }}
      </span>
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { ElMessage } from 'element-plus';
import AssetCard from './AssetCard.vue';
import AssetDetailDrawer from './AssetDetailDrawer.vue';
import AssetUploadDialog from './AssetUploadDialog.vue';
import AssetAuditDrawer from './AssetAuditDrawer.vue';
import MarketFilterMenu from './MarketFilterMenu.vue';
import CapabilityShell from '@/components/CapabilityShell.vue';
import { useUserStore } from '@/stores/user';
import { MARKET_KINDS, type MarketProjectItem, type MarketSort } from './marketCatalog';
import { KIND_META } from './kindMeta';
import {
  listAssets, listCategories, listJobs, listProjects, getSyncStatus, getMarketConfig, retryJob, syncFromGit,
  type AssetItem, type AssetJob, type MarketKind, type SyncStatus,
} from '@/api/assets';
import { isAuthor } from './identity';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';

/**
 * 从 Git 远端地址里取出**给人看的仓库路径** (如 root/testmate-market).
 *
 * ⚠️ 别把整条 SSH 地址摊在页脚上 —— 那带���内网 host:port (host.docker.internal:8922),
 *    界面里没必要暴露部署拓扑; 管理员要看完整地址去设置页, 那儿是管理员专属页.
 */
function repoPathOf(remote: string): string {
  let s = (remote || '').trim();
  if (!s) return '';
  s = s.replace(/\.git$/, '');
  // URL 形态: ssh://git@host:port/group/project → 取路径部分
  const m = s.match(/^[a-z+]+:\/\/[^/]*\/(.+)$/i);
  if (m) return m[1];
  // 本地路径形态: /a/b/c → 取最后两段
  const segs = s.split('/').filter(Boolean);
  return segs.slice(-2).join('/');
}

/**
 * 市场仓库的兜底路径 —— 只在**取不到后端配置**时用.
 *
 * ⚠️ 真源是后端的 marketplace.git.remote (设置页可改), 前端写死只是兜底.
 */
const GITLAB_PROJECT_FALLBACK = 'root/testmate-market';
/** 列表加载超时 (ms) —— 超过就提示重试, 不让页面无限转圈 */
const LOAD_TIMEOUT_MS = 15000;

const kind = ref<MarketKind>('plugin');
const category = ref('');
const keyword = ref('');
const sortBy = ref<MarketSort>('hot');
/**
 * 「只看这些」的模式 —— 两条提示条要分开:
 *   review    → 我提交的、还等审核或被驳回的
 *   unpublish → 我申请下架、等管理员确认的
 *
 * ⚠️ 以前两个提示条共用一个开关, 但过滤条件只有 pending/rejected ——
 *    点「🗑 你的 N 个资产在等下架确认」→ 一条都显示不出来 (它们是 unpublish_pending)。
 */
const onlyMine = ref<'review' | 'unpublish' | ''>('');

function toggleOnlyMine(mode: 'review' | 'unpublish') {
  onlyMine.value = onlyMine.value === mode ? '' : mode;
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
  // ⚠️ 用 isAuthor (短名/全邮箱都认) —— 别写 `author === me`:
  //    用户名现在是邮箱式, 存量资产的 author 可能还是短名, 精确比会判成"不是我的".
  return isAuthor(it.author, userStore.user?.username);
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
/** 上传入口选定的形态 (空 = 没选, 抽屉里再选) */
const uploadKind = ref<MarketKind | ''>('');
/** 上传入口的形态菜单是否展开 */
const pickOpen = ref(false);
const pickWrap = ref<HTMLElement | null>(null);
const sync = ref<SyncStatus>({
  has_remote_updates: false, conflict_count: 0, pending_count: 0,
  failed_count: 0, unpublished_count: 0,
  awaiting_review_count: 0, rejected_count: 0, my_review_count: 0, my_pending_count: 0,
  unpublish_pending_count: 0, my_unpublish_count: 0,
  last_sync_at: null,
});
/** 资产状态读取失败 —— 页面内提示用 (失败 ≠ 没有待办/没有冲突) */
const syncError = ref('');

/** 后端的 detail 可能是字符串也可能是对象 —— 取不到就退化到 message */
function errText(e: any, fallback: string): string {
  // ⚠️ 状态码也要翻译 —— 502/503 的原始报文 ("Request failed with status code 502")
  //    对用户是天书, 而这恰恰是本地部署最常见的故障 (后端没在跑).
  return httpErrorText(errorStatus(e), errorDetail(e), fallback);
}

/**
 * 自动刷新周期 (2026-10-25 用户要求: 市场首页要能自动更新).
 *
 * ⚠️ 为什么是 20s: 后端从 GitLab 拉取的周期是 30s (设置项 marketplace.sync.interval_seconds),
 *    前端每 20s 读一次**本地镜像** → 端到端延迟 ≈ 30-50s.
 *    前端这一步只是查一次库, 成本很低.
 */
const AUTO_REFRESH_MS = 20000;
/** 本页最后一次读到镜像的时间 —— 用户得知道屏幕上的数据是新的 */
const lastRefreshAt = ref<Date | null>(null);
/** 上次刷新失败 (静默刷新失败只提示一句, 不把整页换成错误态) */
const refreshError = ref('');
const lastRefreshText = computed(() => {
  if (refreshError.value) return `失败 (${refreshError.value})`;
  if (!lastRefreshAt.value) return '—';
  return lastRefreshAt.value.toLocaleTimeString('zh-CN');
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
   ⚠️ 以前用硬编码的分类清单: 用户自建的分类**没有 chip** → 筛不出来. */
const categories = ref<{ name: string; slug: string; desc?: string; total: number }[]>([]);
/** 项目列表 (通用 + 各项目) —— 筛选菜单用 */
const projects = ref<MarketProjectItem[]>([]);
/** 项目筛选: '' = 全部, 'general' = 只看通用, '6100' = 该项目特有 + 通用 */
const projectFilter = ref('');

/**
 * 分类 / 项目取数失败 —— 页面内提示用.
 *
 * ⚠️ 以前两个 catch 都是空注释: 后端 500 时分类只剩「全部 / ⭐精选」,
 *    项目菜单一个都没有 —— 用户以为市场里就这些, 筛选维度**凭空消失**了.
 */
const filterLoadError = ref('');
/** 分类 / 项目各自的失败原因 (两种都失败时合成一条显示) */
const filterErrors = reactive({ categories: '', projects: '' });
function refreshFilterError() {
  const parts: string[] = [];
  if (filterErrors.categories) parts.push(`分类加载失败: ${filterErrors.categories}`);
  if (filterErrors.projects) parts.push(`项目列表加载失败: ${filterErrors.projects}`);
  filterLoadError.value = parts.join(' · ');
}

async function loadProjects() {
  try {
    const r = await listProjects();
    projects.value = (r?.items || []) as typeof projects.value;
    filterErrors.projects = '';
    refreshFilterError();
  } catch (e: any) {
    /* 拿不到就不过滤 —— 但要说出来, 别让筛选维度凭空消失 */
    filterErrors.projects = errText(e, '未知错误');
    refreshFilterError();
  }
}
async function loadCategories() {
  try {
    const r = await listCategories();
    categories.value = (r?.items || []) as typeof categories.value;
    filterErrors.categories = '';
    refreshFilterError();
  } catch (e: any) {
    /* 分类表拿不到就不显示 chip —— 但要说出来 */
    filterErrors.categories = errText(e, '未知错误');
    refreshFilterError();
  }
}

/**
 * Tab 上的计数取数失败 —— 页面内提示用.
 *
 * ⚠️ 以前 catch 是空注释, 计数留 0 —— 后端挂掉时用户以为市场是空的.
 *    现在显示 "?" 并在 title 里说明.
 */
const kindCountsError = ref('');

/* Tab 上的计数: 各类型总数, 不受筛选影响 */
async function loadKindCounts() {
  try {
    const counts: Record<string, number> = {};
    for (const k of MARKET_KINDS) {
      const r = await listAssets({ kind: k.value, limit: 500 });
      counts[k.value] = r?.total ?? r?.items?.length ?? 0;
    }
    kindCounts.value = counts;
    kindCountsError.value = '';
  } catch (e: any) {
    kindCountsError.value = errText(e, '未知错误');
  }
}

/**
 * 分类 chip 上的计数 —— **按当前类型 tab 算**.
 *
 * ⚠️ 以前用的是后端给的 total (全部形态的总数) → 切到「技能」tab 时数字
 *    比实际能看到的多, 点进去发现是空的, 像是分类坏了.
 */
function catCount(c: { by_kind?: Record<string, number>; total?: number }): number {
  if (!onlyMine.value && c.by_kind && c.by_kind[kind.value] !== undefined) {
    return c.by_kind[kind.value] || 0;
  }
  return c.total || 0;
}

/**
 * 读一次市场列表.
 *
 * ⚠️ `silent` = **静默刷新** (自动刷新用):
 *    不置 loading (免得整页闪一下 spinner), 失败也**不动页面** ——
 *    用户正在看的列表保留, 只在页脚提示一句.
 */
// 请求序号: 快速切 Tab / 分类 chip 时, 慢的旧响应会覆盖新结果 ——
// Tab 高亮已经是「技能」, 列表却还是「插件」. 只有最后一次请求的结果允许写回.
// (跟 BoardView 的周报刷新 wrSeq 一个写法)
let listSeq = 0;
/** 最后一次**非静默**请求的序号 —— 只有它才有权关掉 loading,
 *  否则旧的静默刷新会把新请求的 spinner 提前关掉 (或者永远关不掉). */
let loadingSeq = 0;
async function fetchList(opts: { silent?: boolean } = {}) {
  const seq = ++listSeq;
  const silent = !!opts.silent;
  if (!silent) {
    loading.value = true;
    loadingSeq = seq;
    loadError.value = '';
  }
  // 看门狗: 请求卡住 (网络中断 / 上游异常) 时给出可操作提示, 而不是无限转圈
  const watchdog = window.setTimeout(() => {
    if (seq === listSeq && loading.value) loadError.value = '加载超时, 请检查后端服务后点「重试」';
  }, LOAD_TIMEOUT_MS);
  try {
    // ⚠️ 「只看这些」时**只按状态过滤**, 别的筛选一律让路 ——
    //    否则我提交的待审资产因为落在别的分类/项目下, 就一条都显示不出来。
    const mine = !!onlyMine.value;
    const r = await listAssets({
      // 「只看这些」时不按类型卡 —— 我提交的待审资产可能是任意类型
      kind: mine ? undefined : kind.value,
      category: mine || category.value === '__featured'
        ? undefined : (category.value || undefined),
      // 项目筛选: 留空 = 不过滤; 'general' → 后端约定的 '__general' (只看通用);
      // 其他 = 该项目特有 + 通用
      project: mine ? undefined : (projectFilter.value === 'general'
        ? '__general'
        : (projectFilter.value || undefined)),
      q: keyword.value.trim() || undefined,
      sort: sortBy.value,
      limit: 500,
    });
    if (seq !== listSeq) return;   // 已有更新的请求在飞, 丢弃本次结果
    const rows = r?.items ?? [];
    rawItems.value = rows;
    items.value = (!mine && category.value === '__featured')
      ? rows.filter((i) => i.featured)
      : rows;
    if (onlyMine.value) {
      // 提示条的"只看这些": 我自己提交的, 按提示条的种类过滤
      // ⚠️ 作者比对走 isAuthor (短名/全邮箱都认) —— 后端认两种写法,
      //    这里只认一种的话, 自己提交的资产会**整片消失**.
      const me = userStore.user?.username || '';
      const want = onlyMine.value === 'unpublish'
        ? ['unpublish_pending']
        : ['pending', 'rejected'];
      items.value = items.value.filter(
        (i) => isAuthor(i.author, me) && want.includes(i.publish_status),
      );
    }
    // ⚠️ 客户端过滤之后, 条数就是过滤后的条数 —— 别再显示后端的总数 (虚高)
    total.value = items.value.length;
    lastRefreshAt.value = new Date();
    refreshError.value = '';
    // ⚠️ 成功后要**清掉看门狗置的 loadError** —— 以前只在请求开始时清,
    //    看门狗超时置的错误会一直留着, 页面永远停在「加载超时」面板,
    //    尽管数据早就加载好了.
    loadError.value = '';
    // 抽屉里开着的资产同步一下 (静默刷新后抽屉别停在旧数据上).
    // ⚠️ 找不到**不关抽屉** —— 刷新期间资产可能被并发删掉, 关抽屉会打断用户.
    if (current.value) {
      const fresh = rawItems.value.find((i) => i.code === current.value!.code);
      if (fresh) current.value = fresh;
    }
  } catch (e: any) {
    if (seq !== listSeq) return;   // 过期请求的失败不该改页面
    const msg = httpErrorText(errorStatus(e), errorDetail(e), '未知错误');
    if (silent) {
      refreshError.value = msg;
    } else {
      loadError.value = msg;
      items.value = [];
      total.value = 0;
    }
  } finally {
    window.clearTimeout(watchdog);
    if (!silent && loadingSeq === seq) loading.value = false;
  }
}

/** 正常加载 —— 整页 loading 态 (首次进入 / 改筛选条件 / 手动重试) */
function load() {
  return fetchList();
}
/** 静默刷新 —— 自动刷新用: 不闪 spinner, 失败不动页面 */
function silentLoad() {
  return fetchList({ silent: true });
}

/** 筛选菜单改了项目 / 排序 → 立刻刷列表 (不靠 watch, 免得复位时重复请求) */
function onProjectChange(v: string) {
  projectFilter.value = v;
  load();
}
function onSortChange(v: MarketSort) {
  sortBy.value = v;
  load();
}
/** 页脚的「刷新」按钮 —— 只重读本地镜像, 不去 GitLab 拉 (那个是「重新同步」) */
function manualRefresh() {
  load();
}

let searchTimer: number | null = null;
function onSearch() {
  if (searchTimer) window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(load, 320);
}

async function loadSyncStatus() {
  try {
    // ⚠️ silent: 这段自己会显示错误提示, 不用再弹一个全局红条 (重复提示)
    const s = await getSyncStatus({ silent: true });
    sync.value = { ...sync.value, ...(s ?? {}) };
    syncError.value = '';
  } catch (e: any) {
    // ⚠️ 以前 catch 是空的 —— 状态条整段消失, 看着像"一切正常"
    syncError.value = errText(e, '未知错误');
  }
}

/**
 * 市场当前生效的配置 —— 页脚显示的"数据源仓库"以它为准.
 *
 * ⚠️ 以前页脚写死 root/testmate-market, 后端换了仓库地址, 页脚还在说旧的.
 *    取不到才回退常量; 还没取到时不渲染 (别先闪一个错的出来).
 * ⚠️ 非管理员拿不到 remote (后端按设计隐藏了仓库地址) → 也走同一个兜底常量,
 *    页脚**不能**渲染成空白 (那会让人以为数据源没配).
 */
const gitRemote = ref('');
const gitRemoteLoaded = ref(false);
const gitRemoteText = computed(() => {
  if (!gitRemoteLoaded.value) return '…';
  // ⚠️ 只显示仓库路径 —— 完整 SSH 地址 (带内网 host:port) 不该摊在页脚上
  return repoPathOf(gitRemote.value) || GITLAB_PROJECT_FALLBACK;
});
async function loadMarketConfig() {
  try {
    const c = await getMarketConfig();
    gitRemote.value = c?.remote || '';
  } catch {
    // ⚠️ 取不到就用兜底常量 (总比空着强)
    gitRemote.value = GITLAB_PROJECT_FALLBACK;
  } finally {
    gitRemoteLoaded.value = true;
  }
}

async function pollJobs() {
  try {
    const r = await listJobs(20);
    failedJobs.value = r.items.filter((j) => j.status === 'failed');
    const active = r.items.some((j) => j.status === 'staged' || j.status === 'syncing');
    // ⚠️ 轮询里的刷新走**静默**路径 —— 以前调的是 load(), 一遇到同步中的任务
    //    就整页切 loading 态, 列表每 5s 消失一次, 闪得人眼睛疼.
    if (active) await silentLoad();
    await loadSyncStatus();
  } catch {
    /* 轮询失败静默 */
  }
}

/**
 * 重试**看得见的**失败任务.
 *
 * ⚠️ 后端把 GET /assets/jobs 收紧了: 非管理员只能拿到**自己**创建的任务,
 *    所以这里重试的只是"我能看见的那些" —— 按钮文案也跟着说"重试失败任务",
 *    别写成"全部重试" (会让人以为是全市场的任务).
 */
async function retryFailed() {
  retrying.value = true;
  try {
    let okCount = 0;
    let failCount = 0;
    for (const j of failedJobs.value) {
      try {
        await retryJob(j.id);
        okCount++;
      } catch {
        // 单个失败不中断, 但**要记数** —— 全失败也弹"已重新排队"是谎报军情
        failCount++;
      }
    }
    if (failCount === 0) {
      ElMessage.success(`已重新排队 ${okCount} 个任务, 正在重试同步`);
    } else if (okCount > 0) {
      ElMessage.warning(`重试完成: ${okCount} 个已排队, ${failCount} 个失败 (刷新列表查看原因)`);
    } else {
      ElMessage.error(`重试失败: ${failCount} 个任务都没排上, 刷新列表查看原因`);
    }
    await pollJobs();
  } finally {
    retrying.value = false;
  }
}

/**
 * 从 GitLab 全量回灌 + 重新入队 —— **admin only** (后端已收紧).
 *
 * ⚠️ 页脚的「重新同步」按钮用 v-if="isAdmin" 门控: 普通发布者点了只吃一个 403.
 */
async function doSync() {
  syncing.value = true;
  try {
    const r = await syncFromGit();
    ElMessage.success(`已从 GitLab 同步: 新增 ${r.added} / 更新 ${r.updated}`);
    await load();
    await loadKindCounts();
    await loadSyncStatus();
  } catch (e: any) {
    ElMessage.error('同步失败: ' + (httpErrorText(errorStatus(e), errorDetail(e))));
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

/**
 * 上传入口 —— **先选形态, 再开抽屉**.
 *
 * 形态决定了表单长什么样 (技能/插件传安装包, 连接器填 MCP JSON),
 * 所以在入口就定下来, 免得进了表单还要自己找类型下拉。
 */
function startCreate(k: MarketKind) {
  pickOpen.value = false;
  uploadMode.value = 'create';
  uploadKind.value = k;
  uploadOpen.value = true;
}

function openUpdate(item: AssetItem) {
  current.value = item;
  uploadMode.value = 'update';
  uploadKind.value = '';      // 更新版本: 类型不可改
  uploadOpen.value = true;
}

/** 点菜单外面 → 关掉形态菜单 */
function onDocClick(e: MouseEvent) {
  if (!pickOpen.value) return;
  if (pickWrap.value && pickWrap.value.contains(e.target as Node)) return;
  pickOpen.value = false;
}
onMounted(() => document.addEventListener('click', onDocClick));
onUnmounted(() => document.removeEventListener('click', onDocClick));

function resetFilters() {
  kind.value = 'plugin';
  category.value = '';
  keyword.value = '';
  onlyMine.value = '';
  sortBy.value = 'hot';
  projectFilter.value = '';
  load();
}



watch(kind, () => load());

/**
 * 自动刷新 (静默) —— 定时重读本地镜像, 让页面上的数据自己变新.
 *
 * ⚠️ 页面**看不见**时跳过 (切到别的标签页了, 没人看, 白费一次请求);
 *    切回来时立刻补一次 —— 免得用户盯着一个十分钟前的列表.
 */
function autoRefresh() {
  if (typeof document !== 'undefined' && document.hidden) return;
  silentLoad();
}
function onVisibilityChange() {
  if (!document.hidden) autoRefresh();
}

let timer: number | null = null;
let autoTimer: number | null = null;
onMounted(async () => {
  await Promise.all([load(), loadKindCounts(), loadSyncStatus(), loadCategories(), loadProjects(), loadMarketConfig()]);
  timer = window.setInterval(pollJobs, 5000);
  autoTimer = window.setInterval(autoRefresh, AUTO_REFRESH_MS);
  document.addEventListener('visibilitychange', onVisibilityChange);
});
onUnmounted(() => {
  if (timer) window.clearInterval(timer);
  if (autoTimer) window.clearInterval(autoTimer);
  // ⚠️ 搜索防抖的定时器也要清 —— 以前漏了它: 离开页面后这个定时器照样触发
  //    load(), 请求失败时全局错误 toast 会弹在**别的页面**上.
  if (searchTimer) { window.clearTimeout(searchTimer); searchTimer = null; }
  document.removeEventListener('visibilitychange', onVisibilityChange);
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
/* 状态读取失败 —— 跟"有冲突/有失败"区分开 (那个是黄色, 这个是红色) */
.sync-bar.err {
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

/* ===== 上传入口: 形态菜单 ===== */
.upload-pick { position: relative; }
.up-caret { font-size: 10px; opacity: 0.85; }
.pick-menu {
  position: absolute; right: 0; top: calc(100% + 8px); z-index: 40;
  width: 340px; padding: 10px;
  /* ⚠️ 菜单要**不透明** —— 半透明毛玻璃底会透出后面的卡片文字, 读不清.
     ⚠️ 颜色只能写在 background 的**最后一层** (多层时前层必须是图像),
        所以用渐变当第一层, 把半透明 surface 压到不透明底色上. */
  background: linear-gradient(var(--surface), var(--surface)), var(--bg-base);
  border: 1px solid var(--border);
  border-radius: 12px; box-shadow: var(--shadow-lg);
}
.pick-lead { font-size: 12px; color: var(--ink-500); padding: 2px 6px 8px; }
.pick-item {
  display: flex; align-items: flex-start; gap: 10px; width: 100%;
  padding: 9px 10px; margin-bottom: 4px; text-align: left;
  background: transparent; border: 1px solid transparent; border-radius: 10px;
  cursor: pointer; font-family: inherit; transition: all 0.15s ease;
}
.pick-item:hover { background: var(--surface-soft); border-color: var(--border); }
.pi-ic { font-size: 20px; line-height: 1.2; }
.pi-body { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
.pi-body b { font-size: 13px; color: var(--ink-900); }
.pi-body i { font-style: normal; font-size: 11px; color: var(--ink-500); margin-left: 4px; }
.pi-tag { font-size: 12px; color: var(--ink-500); line-height: 1.5; }
.pi-go { color: var(--ink-500); font-size: 13px; align-self: center; }
.pick-item:hover .pi-go { color: var(--primary); }

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


/* ===== 分类 + 项目/排序筛选 ===== */
.mk-filters {
  display: flex; justify-content: space-between; align-items: center;
  gap: 14px; flex-wrap: wrap;
}
.cat-chips { display: flex; gap: 6px; flex-wrap: wrap; flex: 1; min-width: 0; }
/* 分类 / 项目取数失败 —— 提示要显眼, 但别抢列表的戏 */
.filter-err {
  width: 100%;
  font-size: 12px; color: var(--err);
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 8px; padding: 6px 12px;
}
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

/* ===== 网格 =====
   ⚠️ 目录页 **4 列** —— 跟首页能力墙 (3 列大卡片) 拉开密度差:
   首页是"白底浮动大卡片", 这里是"扁平紧凑列表卡", 一眼能分清两个页面. */
.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
@media (max-width: 1400px) { .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1100px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .grid { grid-template-columns: 1fr; } }

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
/* 静默刷新失败 —— 提示一句, 但页面不动 (别把用户正在看的列表变成错误页) */
.refresh-fail { color: var(--err); }
</style>
