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
          ＋ 上传软件
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

    <!-- ===== 没有发布权限 → 说清楚, 别让人以为按钮坏了 ===== -->
    <div v-if="!canPublish && configLoaded" class="sw-note">
      当前账号没有上传权限 —— 上传软件需要「测试工程」角色, 或由管理员加进发布者白名单.
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
    <div v-else-if="list.length === 0" class="state">
      <div style="font-size: 30px; opacity: 0.4">🧰</div>
      <div>这里还没有软件</div>
      <button v-if="canPublish" class="reset" @click="openUpload('create')">上传第一个软件</button>
    </div>
    <div v-else class="grid">
      <SoftwareCard v-for="it in list" :key="it.code" :item="it" @open="openDetail" />
    </div>

    <!-- ===== 详情抽屉 ===== -->
    <SoftwareDetailDrawer
      v-model="drawerOpen" :code="currentCode" :refresh-key="detailRefreshKey"
      @changed="load" @new-version="openVersion" />

    <!-- ===== 上传 / 发版本 ===== -->
    <SoftwareUploadDialog
      v-model="uploadOpen" :mode="uploadMode" :item="currentItem"
      @done="onDone" />

    <p v-if="total > 0" class="foot-hint mono">
      共 {{ total }} 项
      <button class="link-btn" @click="load">刷新</button>
      <span class="muted">· 上次刷新 {{ lastRefreshText }}</span>
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import SoftwareCard from './SoftwareCard.vue';
import SoftwareDetailDrawer from './SoftwareDetailDrawer.vue';
import SoftwareUploadDialog from './SoftwareUploadDialog.vue';
import CapabilityShell from '@/components/CapabilityShell.vue';
import { useUserStore } from '@/stores/user';
import {
  getSoftware, getSoftwareConfig, listSoftware, listSoftwareCategories,
  type SoftwareConfig, type SoftwareDetail, type SoftwareItem, type SoftwareSort,
} from '@/api/software';
import { errorDetail, errorStatus, httpErrorText } from '@/utils/httpError';
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

const drawerOpen = ref(false);
const currentCode = ref<string | null>(null);
/** 详情抽屉的刷新计数 —— 发完新版本/删完之后 +1, 让抽屉重读一次 */
const detailRefreshKey = ref(0);
const currentItem = ref<SoftwareDetail | null>(null);
const uploadOpen = ref(false);
const uploadMode = ref<'create' | 'version'>('create');

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

async function load() {
  loading.value = true;
  loadError.value = '';
  try {
    const r = await listSoftware({
      q: keyword.value.trim(),
      category: category.value,
      sort: sortBy.value,
      limit: 200,
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
  } catch (e: any) {
    config.value = null;
    filterError.value = filterError.value || errText(e, '配置读取失败');
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
  drawerOpen.value = true;
}

async function openVersion(item: SoftwareDetail) {
  currentItem.value = item;
  uploadMode.value = 'version';
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
  if (drawerOpen.value && currentCode.value) {
    try {
      currentItem.value = await getSoftware(currentCode.value);
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
