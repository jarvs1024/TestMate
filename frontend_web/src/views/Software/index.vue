<template>
  <div class="software">
    <!-- ===== 能力详情统一外壳 ===== -->
    <CapabilityShell
      name="软件库"
      icon="🧰"
      kind="platform"
      status="beta"
      version="v1.0.0"
      category="sw-library" />

    <!-- ===== 动作条: 分类 chip + 搜索 + 上传 ===== -->
    <div class="mk-actions">
      <div class="ma-right">
        <div class="search">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
          </svg>
          <input v-model="keyword" placeholder="搜索名称、说明、标签"
                 @input="onSearch" />
        </div>
        <select v-model="sortBy" class="sort-sel" @change="load">
          <option value="new">最新优先</option>
          <option value="hot">下载最多</option>
          <option value="name">按名称</option>
        </select>
        <button class="mini-btn primary" :disabled="!canPublish" @click="openUpload('create')">
          ＋ 上架软件
        </button>
      </div>
    </div>

    <!-- ⚠️ 分类取不到 → 筛选维度会凭空消失, 得说清楚是"读失败"不是"没有" -->
    <div class="mk-filters">
      <div class="cat-chips">
        <button class="chip" :class="{ active: category === '' }" @click="category = ''; load()">
          全部 <span class="count">{{ total }}</span>
        </button>
        <button v-for="c in categories" :key="c.name" class="chip"
                :class="{ active: category === c.name }"
                @click="category = c.name; load()">
          {{ c.name }}<span v-if="c.total" class="count">{{ c.total }}</span>
        </button>
      </div>
      <div v-if="filterError" class="filter-err">⚠️ {{ filterError }}</div>
    </div>

    <!-- ⚠️ 配置读不到 ≠ 没有上架权限 (2026-10-30) ——
         以前 GET /software/config 一挂 (502/断网) → config=null → canPublish 永远 false,
         页面还告诉用户「当前账号没有上架权限」. 其实人家有权限, 是**服务挂了**,
         而且**没有重试入口** —— 按钮就一直灰着.
         所以配置错误单独一个 ref, 单独一条提示 + 重试按钮. -->
    <div v-if="configError" class="sw-note err">
      <div>读不到发布配置（{{ configError }}），暂时无法确认你能不能上架 —— 请重试。</div>
      <button class="reset" @click="loadConfig">重试</button>
    </div>
    <!-- ✓ 只有配置**读到了**、且确实 can_publish=false, 才说"没有权限" -->
    <div v-else-if="!canPublish && configLoaded" class="sw-note">
      当前账号没有上架权限 —— 上架软件需要「测试工程」角色, 或由管理员加进发布者白名单.
    </div>

    <!-- ===== 管理员: 存储路径健康 ===== -->
    <div v-if="isAdmin && config && !config.path_ok" class="sw-note err">
      ⚠️ 软件包存放目录不可用: <code>{{ config.storage_root }}</code> —— 请到设置页检查路径.
    </div>
    <div v-else-if="isAdmin && config" class="sw-note ok">
      📁 软件包存放目录 <code>{{ config.storage_root }}</code>
      <span class="muted">(来自{{ sourceText }})</span>
      · 可用空间 {{ formatSize(config.free_bytes) }}
      · 已占用 {{ formatSize(config.used_bytes) }}
    </div>

    <!-- ===== 加载 / 空态 / 错误 ===== -->
    <div v-if="loading" class="state">
      <div class="spinner" />
      <div>正在读取软件库…</div>
    </div>
    <div v-else-if="loadError" class="state err">
      <div style="font-size: 28px">⚠️</div>
      <div>{{ loadError }}</div>
      <button class="reset" @click="load">重试</button>
    </div>
    <!-- ⚠️ 空态分两支 (2026-10-30): 搜不到 ≠ 库里没有.
         以前不管有没有筛选条件, 一律显示「🧰 这里还没有软件」+「上架第一个软件」——
         库里明明有几十个软件, 用户以为整个库空了, 甚至真去上架重复条目. -->
    <div v-else-if="list.length === 0 && hasFilter" class="state">
      <div style="font-size: 30px; opacity: 0.4">🔍</div>
      <div>没有匹配「{{ filterDesc }}」的软件</div>
      <div class="state-sub">
        软件库里是有东西的 —— 只是不满足当前的筛选条件. 换个关键词, 或者把筛选清掉.
      </div>
      <button class="reset" @click="clearFilter">清空筛选</button>
    </div>
    <div v-else-if="list.length === 0" class="state">
      <div style="font-size: 30px; opacity: 0.4">🧰</div>
      <div>这里还没有软件</div>
      <!-- ⚠️ 空的时候最需要说清"接下来怎么做" —— 页头 lede 说了"放什么",
           这里别重复一遍 (同一句话说两遍), 说"怎么上架" -->
      <div class="state-sub">
        选好软件包、填几项说明就能上架 —— 上架后同事直接在这里下载.
      </div>
      <button v-if="canPublish" class="reset" @click="openUpload('create')">上架第一个软件</button>
    </div>
    <div v-else class="grid">
      <SoftwareCard v-for="it in list" :key="it.code" :item="it" @open="openDetail" />
    </div>

    <!-- ===== 详情抽屉 ===== -->
    <SoftwareDetailDrawer
      v-model="drawerOpen" :code="currentCode" :refresh-key="detailRefreshKey"
      :can-edit="canEdit" @changed="load" @new-version="openVersion" @edit="openEdit" />

    <!-- ===== 编辑软件信息 (2026-10-30) ===== -->
    <SoftwareEditDialog v-model="editOpen" :item="currentItem" @done="onEditDone" />

    <!-- ===== 上传 / 发版本 ===== -->
    <SoftwareUploadDialog
      v-model="uploadOpen" :mode="uploadMode" :item="currentItem"
      @done="onDone" />

    <p v-if="total > 0" class="foot-hint mono">
      共 {{ total }} 项
      <!-- ⚠️ 2026-10-30: 后端一次最多给 500 条 (le=500) —— 超出部分前端**看不到**,
           以前页脚只写「共 500 项」, 看着像下面全是, 实际只渲染了前 200 条.
           跟用户说清楚还差多少 (⚠️ 不做"加载更多"按钮 —— 那要改分页逻辑, 风险大). -->
      <span v-if="total > list.length" class="muted">
        · 只显示前 {{ list.length }} 条（还有 {{ total - list.length }} 条没显示）
      </span>
      <button class="link-btn" @click="load">刷新</button>
      <span class="muted">· 上次刷新 {{ lastRefreshText }}</span>
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import SoftwareCard from './SoftwareCard.vue';
import SoftwareDetailDrawer from './SoftwareDetailDrawer.vue';
import SoftwareEditDialog from './SoftwareEditDialog.vue';
import SoftwareUploadDialog from './SoftwareUploadDialog.vue';
import CapabilityShell from '@/components/CapabilityShell.vue';
import { useUserStore } from '@/stores/user';
import {
  getSoftware, getSoftwareConfig, listSoftware, listSoftwareCategories,
  type SoftwareConfig, type SoftwareDetail, type SoftwareItem, type SoftwareSort,
} from '@/api/software';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';
import { isAuthor } from '@/utils/author';
import { formatSize } from './softwareForm';

const userStore = useUserStore();
const isAdmin = computed(() => userStore.user?.role === 'admin');

const items = ref<SoftwareItem[]>([]);
const total = ref(0);
const loading = ref(false);
const loadError = ref('');
const categories = ref<{ name: string; total: number }[]>([]);
const filterError = ref('');
const keyword = ref('');
const category = ref('');
const sortBy = ref<SoftwareSort>('new');
const config = ref<SoftwareConfig | null>(null);
const configLoaded = ref(false);
/**
 * 配置读取失败的原因 —— 空串 = 没失败.
 *
 * ⚠️ 2026-10-30: 以前配置一挂就 config=null → canPublish 永远 false →
 *    页面显示「当前账号没有上架权限」. 其实用户**有**权限, 是服务挂了.
 *    单独一个 ref, 好跟"真的没权限"分开说 (⚠️ 别写进 filterError ——
 *    那是分类 chip 下面的错, 混在一起会让人以为是分类挂了).
 */
const configError = ref('');

const drawerOpen = ref(false);
const currentCode = ref<string | null>(null);
/** 详情抽屉的刷新计数 —— 发完新版本/删完之后 +1, 让抽屉重读一次 */
const detailRefreshKey = ref(0);
const currentItem = ref<SoftwareDetail | null>(null);
/** 当前打开的**列表项** —— 用来算「能不能编辑」 (详情是抽屉异步读的) */
const currentListItem = ref<SoftwareItem | null>(null);
const uploadOpen = ref(false);
const uploadMode = ref<'create' | 'version'>('create');
/** 编辑软件信息的抽屉 (2026-10-30) */
const editOpen = ref(false);

const lastRefreshAt = ref<Date | null>(null);
const lastRefreshText = computed(() => {
  if (!lastRefreshAt.value) return '—';
  return lastRefreshAt.value.toLocaleTimeString('zh-CN');
});

function errText(e: unknown, fallback: string): string {
  return httpErrorText(errorStatus(e), errorDetail(e), fallback);
}

/** 当前用户能不能上传 —— 后端也判一遍 (前端只是提前把按钮灰掉) */
const canPublish = computed(() => config.value?.can_publish ?? false);

/**
 * 存储根目录是**哪来的** —— 管理员最常问的是"我改了设置项怎么没生效".
 * 实际多半是环境变量把它盖住了 (容器模式就是 compose 注入的).
 */
const sourceText = computed(() => {
  const s = config.value?.storage_source;
  if (s === 'setting') return '设置项';
  if (s === 'env') return '环境变量';
  return '默认路径';
});

const list = computed(() => items.value ?? []);

/**
 * 当前有没有筛选条件 —— 决定空态是"库里没有"还是"没匹配上".
 *
 * ⚠️ 2026-10-30: 以前不管有没有筛选, 空态都是「这里还没有软件」——
 *    搜索一个不存在的词, 用户以为整个库空了.
 */
const hasFilter = computed(() => keyword.value.trim() !== '' || category.value !== '');

/** 空态里回显的筛选条件 (关键词优先) */
const filterDesc = computed(() => {
  const kw = keyword.value.trim();
  const cat = category.value;
  if (kw && cat) return `${kw} · ${cat}`;
  return kw || cat;
});

/** 清空筛选 —— 回到"全部", 重新取一次列表 */
async function clearFilter() {
  keyword.value = '';
  category.value = '';
  await load();
}

async function load() {
  loading.value = true;
  loadError.value = '';
  try {
    const r = await listSoftware({
      q: keyword.value.trim(),
      category: category.value,
      sort: sortBy.value,
      // ⚠️ 2026-10-30: 以前是 200 —— 库里超过 200 条时, 后面的**永远看不到**
      //    (页脚还写「共 500 项」). 提到后端允许的上限 500 (le=500).
      //    ⚠️ 不做"加载更多"按钮 —— 那要改分页逻辑, 风险大.
      limit: 500,
    });
    items.value = r?.items ?? [];
    total.value = r?.total ?? 0;
    lastRefreshAt.value = new Date();
  } catch (e: any) {
    loadError.value = errText(e, '读取软件列表失败');
  } finally {
    loading.value = false;
  }
}

async function loadCategories() {
  try {
    const r = await listSoftwareCategories();
    categories.value = r?.items ?? [];
    filterError.value = '';
  } catch (e: any) {
    categories.value = [];
    filterError.value = errText(e, '分类读取失败');
  }
}

async function loadConfig() {
  try {
    config.value = await getSoftwareConfig();
    configError.value = '';
  } catch (e: any) {
    // ⚠️ 配置读不到**不是**"没权限" —— 单独记下来, 页面上给一个重试入口.
    //    ⚠️ 2026-10-30: 以前写进 filterError (分类 chip 下面那条),
    //    现在挪到 configError —— 配置错了跟分类没关系.
    config.value = null;
    configError.value = errText(e, '配置读取失败');
  } finally {
    configLoaded.value = true;
  }
}

let searchTimer: ReturnType<typeof setTimeout> | null = null;
function onSearch() {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(load, 300);
}

async function openDetail(item: SoftwareItem) {
  currentCode.value = item.code;
  // ⚠️ 列表项里就有 can_edit / author —— 详情抽屉是异步读的,
  //    「能不能编辑」得先有个准, 不然按钮要等详情回来才出现.
  currentListItem.value = item;
  drawerOpen.value = true;
}

/**
 * 当前用户能不能**编辑**这个软件的说明信息 (2026-10-30).
 *
 * ⚠️ 口径: **上传者本人 或 管理员** —— 跟「发布新版本」「下架」一致.
 * · 后端已经判过一遍 (`can_edit` = _assert_can_modify), 以它为准;
 * · 再本地兜一次 (万一后端字段没带上) —— isAuthor 短名/全邮箱都认.
 * ⚠️ 前端这个只是**按钮显不显示**, 真正的闸门在后端 (_assert_can_modify).
 *
 * ⚠️ 判的是**列表里点开的那个条目** (currentListItem) —— 详情抽屉打开时
 *    currentItem 可能还是上一次的 (详情是抽屉自己异步读的), 用列表项才准.
 */
const canEdit = computed(() => {
  const it = currentListItem.value || currentItem.value;
  if (!it) return false;
  if (it.can_edit) return true;
  if (userStore.user?.role === 'admin') return true;
  return isAuthor(it.author, userStore.user?.username);
});

/**
 * 打开「编辑软件信息」抽屉.
 *
 * ⚠️ 跟 openVersion 一样 —— **先把详情抽屉关掉**再开编辑抽屉,
 *    否则两个抽屉叠在一起 (el-drawer 的 z-index 是"打开时递增"分配的).
 */
async function openEdit(item: SoftwareDetail) {
  currentItem.value = item;
  drawerOpen.value = false;
  await new Promise((r) => setTimeout(r, 320));
  editOpen.value = true;
}

/** 编辑保存完 → 刷列表 + 刷详情 */
async function onEditDone() {
  await load();
  detailRefreshKey.value += 1;
  if (currentCode.value) {
    try {
      currentItem.value = await getSoftware(currentCode.value);
      drawerOpen.value = true;
    } catch {
      /* 读不到就算了 */
    }
  }
}

/**
 * 发新版本.
 *
 * ⚠️ 2026-10-28 修: 以前直接开上传抽屉, 结果**两个抽屉叠在一起** ——
 *    el-drawer 的 z-index 是"打开时递增"分配的, 同一个抽屉实例(create → version)
 *    复用第一次的 z-index, 比详情抽屉小 → **发新版本的表单被详情抽屉压住**,
 *    用户点了"发新版本"却只看见详情. 现在先把详情抽屉关掉再开.
 */
async function openVersion(item: SoftwareDetail) {
  currentItem.value = item;
  uploadMode.value = 'version';
  drawerOpen.value = false;
  // 等详情抽屉的关闭动画走完, 再开上传抽屉 (否则两层会闪一下)
  await new Promise((r) => setTimeout(r, 320));
  uploadOpen.value = true;
}

function openUpload(mode: 'create' | 'version') {
  uploadMode.value = mode;
  uploadOpen.value = true;
}

async function onDone() {
  await load();
  await loadCategories();
  // 详情抽屉开着的话, 刷新一下它 (版本历史变了)
  detailRefreshKey.value += 1;
  if (currentCode.value) {
    try {
      currentItem.value = await getSoftware(currentCode.value);
      // 发新版本完成后**回到详情抽屉** —— 用户能直接看到版本历史多了条,
      // 不用自己再点开卡片 (发版时详情抽屉是先关掉的, 见 openVersion).
      drawerOpen.value = true;
    } catch {
      /* 读不到就算了, 抽屉里显示旧数据 */
    }
  }
}

onMounted(async () => {
  await Promise.all([load(), loadCategories(), loadConfig()]);
});
</script>

<style scoped>
/* ⚠️ 版式与「插件·技能·连接」那一页保持一致 (mk-actions / cat-chips / grid /
   state) —— 两个页面要看起来是一套东西. */
.software { display: flex; flex-direction: column; }

.mk-actions {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin-bottom: 10px;
}
.ma-right { display: flex; align-items: center; gap: 9px; flex: 1; flex-wrap: wrap; }

.search {
  display: flex; align-items: center; gap: 6px;
  border: 1px solid var(--border); border-radius: var(--radius-btn);
  padding: 5px 10px; background: var(--surface); color: var(--ink-500);
  min-width: 220px; flex: 1; max-width: 340px;
}
.search input {
  border: none; outline: none; background: transparent; flex: 1;
  font-size: 12.5px; color: var(--ink-900); font-family: inherit;
}
.sort-sel {
  border: 1px solid var(--border); border-radius: var(--radius-btn);
  padding: 5px 8px; font-size: 12px; color: var(--ink-700);
  background: var(--surface); font-family: inherit; cursor: pointer;
}

.mk-filters { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.cat-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip {
  border: 1px solid var(--border); background: var(--surface);
  border-radius: var(--radius-pill); padding: 3px 11px;
  font-size: 11.5px; color: var(--ink-700); cursor: pointer; font-family: inherit;
  display: inline-flex; align-items: center; gap: 5px;
}
.chip.active { border-color: var(--primary); color: var(--primary); background: rgba(59, 130, 246, .08); }
.chip .count { font-size: 10px; color: var(--ink-500); font-family: var(--font-mono); }
.filter-err { font-size: 11.5px; color: var(--warn); }

.sw-note {
  padding: 8px 11px; border-radius: var(--radius-sm); font-size: 12px;
  background: rgba(245, 158, 11, 0.10); color: var(--warn);
  border: 1px solid rgba(245, 158, 11, 0.25); margin-bottom: 10px;
}
.sw-note.err { background: rgba(239, 68, 68, 0.08); color: var(--err); border-color: rgba(239, 68, 68, .25); }
.sw-note.ok { background: rgba(16, 185, 129, .08); color: var(--ink-700); border-color: rgba(16, 185, 129, .22); }
.sw-note code { font-family: var(--font-mono); font-size: 11px; }

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(258px, 1fr));
  gap: 12px;
}

.state {
  display: flex; flex-direction: column; align-items: center; gap: 10px;
  padding: 46px 0; color: var(--ink-500); font-size: 13px;
}
.state.err { color: var(--err); }
/* 空态补充说明 —— 说清"这个库放什么", 一行灰字, 别抢主文案 */
.state-sub {
  max-width: 460px; text-align: center; line-height: 1.7;
  color: var(--ink-500); opacity: 0.85; font-size: 12px;
}
.spinner {
  width: 22px; height: 22px; border-radius: 50%;
  border: 2px solid var(--border); border-top-color: var(--primary);
  animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.reset {
  border: 1px solid var(--border); background: var(--surface);
  border-radius: var(--radius-btn); padding: 5px 13px;
  font-size: 12px; color: var(--ink-700); cursor: pointer; font-family: inherit;
}
.reset:hover { border-color: var(--primary); color: var(--primary); }

.foot-hint { margin-top: 12px; font-size: 11px; color: var(--ink-500); }
.link-btn {
  border: none; background: none; color: var(--primary);
  font-size: 11px; cursor: pointer; font-family: inherit; padding: 0 4px;
}
.muted { color: var(--ink-500); }
</style>
