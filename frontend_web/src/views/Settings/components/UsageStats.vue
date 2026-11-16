<template>
  <section class="usage-stats" data-testid="usage-stats">
    <div class="stats-head">
      <div>
        <h2>使用统计</h2>
        <p class="stats-sub">
          在线 = 最近 5 分钟内有操作；活跃按自然日去重，不含通知轮询等后台请求。
        </p>
      </div>
      <div class="range-tabs" aria-label="统计周期">
        <button
          v-for="d in RANGES"
          :key="d"
          :data-testid="`range-${d}`"
          :class="{ on: days === d }"
          @click="pickRange(d)">
          {{ d }} 天
        </button>
      </div>
    </div>

    <div v-if="loading" class="state muted">统计加载中…</div>

    <div v-else-if="error" class="state err" data-testid="stats-error">
      统计加载失败：{{ error }}
      <button class="mini-link" data-testid="stats-retry" @click="load()">重试</button>
    </div>

    <template v-else>
      <div class="kpis">
        <div class="kpi" data-testid="kpi-online">
          <span class="kpi-label">当前在线</span>
          <strong class="kpi-num">{{ online?.count ?? '—' }}</strong>
          <button class="kpi-link" data-testid="online-toggle" @click="onlineOpen = !onlineOpen">
            {{ onlineOpen ? '收起名单' : '查看名单' }}
          </button>
        </div>
        <div class="kpi" data-testid="kpi-active">
          <span class="kpi-label">今日活跃</span>
          <strong class="kpi-num">{{ summary?.active.today ?? '—' }}</strong>
          <span class="kpi-hint">近 {{ days }} 天按日去重</span>
        </div>
        <div class="kpi" data-testid="kpi-downloads">
          <span class="kpi-label">累计下载</span>
          <strong class="kpi-num">{{ totalDownloads }}</strong>
          <span class="kpi-hint">
            软件库 {{ summary?.downloads.software.total ?? 0 }} · 扩展库
            {{ summary?.downloads.extensions.total ?? 0 }}
          </span>
        </div>
      </div>

      <div v-if="onlineOpen" class="online-list" data-testid="online-list">
        <span v-if="!online?.users.length" class="muted">最近 5 分钟没有在线用户</span>
        <span v-for="u in online?.users ?? []" :key="u.id" class="online-chip">
          <i class="dot" />{{ u.username }}
        </span>
      </div>

      <div class="charts">
        <div class="panel">
          <h3>活跃用户趋势</h3>
          <svg
            class="line-svg"
            data-testid="active-chart"
            :viewBox="`0 0 ${W} ${H}`"
            role="img"
            aria-label="活跃用户趋势">
            <line
              v-for="g in gridLines"
              :key="g.f"
              :x1="P"
              :x2="W - P"
              :y1="g.y"
              :y2="g.y"
              class="grid" />
            <text v-for="g in gridLines" :key="`t-${g.f}`" :x="4" :y="g.y + 4" class="axis-y">
              {{ g.label }}
            </text>
            <polygon v-if="points.length" :points="areaPoints" class="area" />
            <polyline v-if="points.length" :points="linePoints" class="line" />
            <circle
              v-for="p in points"
              :key="p.date"
              :cx="p.x"
              :cy="p.y"
              r="3"
              class="point">
              <title>{{ p.date }}：{{ p.count }} 人</title>
            </circle>
          </svg>
          <div class="axis-x">
            <span
              v-for="l in xLabels"
              :key="l.date"
              :style="{ left: `${(l.x / W) * 100}%` }">
              {{ shortDate(l.date) }}
            </span>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h3>下载排行</h3>
            <div class="lib-tabs">
              <button
                data-testid="lib-software"
                :class="{ on: activeLibrary === 'software' }"
                @click="activeLibrary = 'software'">
                软件库
              </button>
              <button
                data-testid="lib-extensions"
                :class="{ on: activeLibrary === 'extensions' }"
                @click="activeLibrary = 'extensions'">
                扩展库
              </button>
            </div>
          </div>

          <div class="bars" data-testid="download-bars">
            <div v-if="!library.items.length" class="muted">还没有下载记录</div>
            <div v-for="(item, i) in library.items" :key="item.code" class="bar-row">
              <span class="rank">{{ i + 1 }}</span>
              <span class="b-icon">{{ item.icon || '·' }}</span>
              <span class="b-name" :title="item.name">
                <span class="b-text">{{ item.name }}</span>
                <span v-if="item.kind === 'mcp'" class="kind">配置复制</span>
              </span>
              <span class="b-track">
                <i class="b-fill" :style="{ width: barWidth(item.count) }" />
              </span>
              <span class="b-count">{{ item.count }}</span>
            </div>
            <div class="lib-total">累计 {{ library.total }} 次（两库均为累计值，不随周期切换）</div>
          </div>
        </div>
      </div>

      <div class="panel user-panel">
        <div class="panel-head user-head">
          <div>
            <h3>用户明细</h3>
            <p class="user-sub">按人汇总所选周期内的活跃天数和两库下载次数；点一行看具体资产。</p>
          </div>
          <div class="lib-tabs" aria-label="用户排序">
            <button
              data-testid="sort-active"
              :class="{ on: sortBy === 'active' }"
              @click="sortBy = 'active'">
              按活跃
            </button>
            <button
              data-testid="sort-downloads"
              :class="{ on: sortBy === 'downloads' }"
              @click="sortBy = 'downloads'">
              按下载
            </button>
          </div>
        </div>

        <div v-if="userError" class="state err" data-testid="users-error">
          用户明细加载失败：{{ userError }}
          <button class="mini-link" data-testid="users-retry" @click="reloadUsers()">重试</button>
        </div>

        <template v-else-if="userStats">
          <div class="user-table" data-testid="user-table">
            <div class="user-grid user-head-row">
              <span>用户</span>
              <span>活跃度</span>
              <span>最近活跃</span>
              <span class="num">软件</span>
              <span class="num">扩展</span>
              <span class="num">合计</span>
              <span></span>
            </div>

            <div v-for="u in sortedUsers" :key="u.id" class="user-item">
              <button
                type="button"
                class="user-grid user-row"
                :class="{ open: expandedId === u.id }"
                :data-testid="`user-row-${u.id}`"
                @click="toggleUser(u.id)">
                <span class="u-who">
                  <i class="dot" :class="{ off: !u.is_online }" />
                  <span class="u-name" :title="u.username">{{ u.username }}</span>
                  <span v-if="!u.is_active" class="kind">已停用</span>
                </span>
                <span class="u-active">
                  <i class="u-track"><i class="u-fill" :style="{ width: activeWidth(u.active_days) }" /></i>
                  <span :data-testid="`user-active-${u.id}`">{{ u.active_days }} 天</span>
                </span>
                <span class="u-last">{{ u.last_seen_at ? fmtIso(u.last_seen_at) : '—' }}</span>
                <span class="num" :data-testid="`user-software-${u.id}`">{{ u.software_downloads }}</span>
                <span class="num" :data-testid="`user-extension-${u.id}`">{{ u.extension_downloads }}</span>
                <span class="num strong" :data-testid="`user-total-${u.id}`">{{ u.total_downloads }}</span>
                <span class="u-chev">{{ expandedId === u.id ? '▾' : '▸' }}</span>
              </button>

              <div
                v-if="expandedId === u.id"
                class="user-detail"
                :data-testid="`user-detail-${u.id}`">
                <div v-if="detailLoading" class="muted">下载明细加载中…</div>
                <div v-else-if="detailError" class="err detail-err">
                  下载明细加载失败：{{ detailError }}
                  <button class="mini-link" @click="loadDetail(u.id, true)">重试</button>
                </div>
                <div v-else-if="!detail?.items.length" class="muted">
                  该用户在这个周期内没有下载记录
                </div>
                <div v-else class="detail-list">
                  <div
                    v-for="item in detail.items"
                    :key="`${item.kind}:${item.action}:${item.code}`"
                    class="detail-row">
                    <span class="kind">
                      {{ item.kind === 'software' ? '软件库' : item.action === 'copy' ? '配置复制' : '扩展库' }}
                    </span>
                    <span class="detail-name" :title="item.name">{{ item.name || item.code }}</span>
                    <span class="detail-count">{{ item.count }} 次</span>
                    <span class="detail-time">{{ fmtIso(item.last_at) }}</span>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="!sortedUsers.length" class="muted">还没有用户</div>
          </div>

          <div class="user-notes">
            <span data-testid="stats-since">
              用户维度从 {{ userStats.since }} 开始记录，之前的下载无法回溯。
            </span>
            <span data-testid="anonymous-note">
              另有 {{ userStats.anonymous_downloads }} 次匿名下载（未登录）未计入个人。
            </span>
          </div>
        </template>

        <div v-else class="muted">用户明细加载中…</div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import {
  getOnlineUsers,
  getStatsUsers,
  getUsageSummary,
  getUserDownloads,
  type StatsOnline,
  type StatsLibrary,
  type StatsUserDownloads,
  type StatsUsers,
  type UsageSummary,
} from '@/api/stats';
import { fmtIso } from '@/utils/format';

const emit = defineEmits<{ online: [count: number] }>();

const RANGES = [7, 30, 90] as const;
type Range = (typeof RANGES)[number];

const W = 640;
const H = 180;
const P = 28;
const POLL_MS = 60_000;

const days = ref<Range>(30);
const summary = ref<UsageSummary | null>(null);
const online = ref<StatsOnline | null>(null);
const error = ref('');
const loading = ref(true);
const onlineOpen = ref(false);
const activeLibrary = ref<StatsLibrary>('software');

const userStats = ref<StatsUsers | null>(null);
const userError = ref('');
const sortBy = ref<'active' | 'downloads'>('active');
const expandedId = ref<number | null>(null);
const detail = ref<StatsUserDownloads | null>(null);
const detailLoading = ref(false);
const detailError = ref('');
const detailCache = new Map<string, StatsUserDownloads>();

let timer: ReturnType<typeof setInterval> | null = null;
let disposed = false;
let seq = 0;
let userSeq = 0;
let detailSeq = 0;

const totalDownloads = computed(() => {
  const d = summary.value?.downloads;
  return (d?.software.total ?? 0) + (d?.extensions.total ?? 0);
});

const library = computed(
  () => summary.value?.downloads[activeLibrary.value] ?? { total: 0, items: [] },
);

const sortedUsers = computed(() => {
  const list = [...(userStats.value?.users ?? [])];
  return list.sort((a, b) =>
    sortBy.value === 'downloads'
      ? b.total_downloads - a.total_downloads || b.active_days - a.active_days || a.id - b.id
      : b.active_days - a.active_days || b.total_downloads - a.total_downloads || a.id - b.id,
  );
});

const series = computed(() => summary.value?.active.series ?? []);

const maxActive = computed(() =>
  Math.max(1, ...series.value.map((p) => p.count)),
);

const points = computed(() => {
  const n = series.value.length;
  return series.value.map((p, i) => ({
    ...p,
    x: n <= 1 ? W / 2 : P + (i * (W - 2 * P)) / (n - 1),
    y: H - P - (p.count / maxActive.value) * (H - 2 * P),
  }));
});

const linePoints = computed(() =>
  points.value.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' '),
);

const areaPoints = computed(() => {
  if (!points.value.length) return '';
  const first = points.value[0];
  const last = points.value[points.value.length - 1];
  return `${first.x.toFixed(1)},${H - P} ${linePoints.value} ${last.x.toFixed(1)},${H - P}`;
});

const gridLines = computed(() =>
  [0, 0.5, 1].map((f) => ({
    f,
    y: H - P - f * (H - 2 * P),
    label: String(Math.round(maxActive.value * f)),
  })),
);

/** X 轴最多 6 个日期标签, 首尾必留. */
const xLabels = computed(() => {
  const pts = points.value;
  if (!pts.length) return [];
  const count = Math.min(6, pts.length);
  const indexes = new Set<number>();
  for (let i = 0; i < count; i++) {
    indexes.add(Math.round((i * (pts.length - 1)) / Math.max(1, count - 1)));
  }
  return [...indexes].sort((a, b) => a - b).map((i) => pts[i]);
});

function shortDate(d: string) {
  return d.slice(5);
}

function barWidth(count: number) {
  const max = Math.max(1, ...library.value.items.map((i) => i.count));
  return count > 0 ? `${Math.max(4, Math.round((count / max) * 100))}%` : '0%';
}

function activeWidth(activeDays: number) {
  if (!activeDays) return '0%';
  return `${Math.max(6, Math.round((activeDays / days.value) * 100))}%`;
}

function errText(e: any) {
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string' && detail) return detail;
  return e?.message || '请稍后重试';
}

function applyOnline(data: StatsOnline) {
  online.value = data;
  if (summary.value) summary.value = { ...summary.value, online: data };
  if (userStats.value) {
    const ids = new Set(data.users.map((u) => u.id));
    userStats.value = {
      ...userStats.value,
      users: userStats.value.users.map((u) => ({ ...u, is_online: ids.has(u.id) })),
    };
  }
  emit('online', data.count);
}

async function load(target: Range = days.value) {
  const my = ++seq;
  const mu = ++userSeq;
  error.value = '';
  userError.value = '';
  if (!summary.value) loading.value = true;
  const [summaryRes, usersRes] = await Promise.allSettled([
    getUsageSummary(target),
    getStatsUsers(target),
  ]);
  if (disposed || my !== seq) return;

  if (summaryRes.status === 'fulfilled') {
    summary.value = summaryRes.value;
  } else {
    error.value = errText(summaryRes.reason);
  }
  if (mu === userSeq) {
    if (usersRes.status === 'fulfilled') {
      userStats.value = usersRes.value;
    } else {
      userError.value = errText(usersRes.reason);
    }
  }
  if (summaryRes.status === 'fulfilled') applyOnline(summaryRes.value.online);
  loading.value = false;
}

async function reloadUsers() {
  const my = ++userSeq;
  userError.value = '';
  try {
    const data = await getStatsUsers(days.value);
    if (disposed || my !== userSeq) return;
    userStats.value = data;
  } catch (e: any) {
    if (disposed || my !== userSeq) return;
    userError.value = errText(e);
  }
}

async function pickRange(d: Range) {
  if (d === days.value) return;
  days.value = d;
  expandedId.value = null;
  detail.value = null;
  detailError.value = '';
  detailCache.clear();
  await load(d);
}

async function toggleUser(id: number) {
  if (expandedId.value === id) {
    expandedId.value = null;
    detail.value = null;
    detailError.value = '';
    return;
  }
  expandedId.value = id;
  detail.value = null;
  detailError.value = '';
  await loadDetail(id);
}

async function loadDetail(id: number, force = false) {
  const key = `${id}:${days.value}`;
  const cached = detailCache.get(key);
  if (cached && !force) {
    detail.value = cached;
    return;
  }
  const my = ++detailSeq;
  detailLoading.value = true;
  detailError.value = '';
  try {
    const data = await getUserDownloads(id, days.value);
    if (disposed || my !== detailSeq || expandedId.value !== id) return;
    detailCache.set(key, data);
    detail.value = data;
  } catch (e: any) {
    if (disposed || my !== detailSeq || expandedId.value !== id) return;
    detailError.value = errText(e);
  } finally {
    if (!disposed && my === detailSeq) detailLoading.value = false;
  }
}

async function refreshOnline() {
  try {
    const data = await getOnlineUsers();
    if (disposed) return;
    applyOnline(data);
  } catch {
    // 轮询失败保留上一次在线数 —— 不把页面打成错误态
  }
}

onMounted(() => {
  load();
  timer = setInterval(refreshOnline, POLL_MS);
});

onBeforeUnmount(() => {
  disposed = true;
  if (timer) clearInterval(timer);
  timer = null;
});
</script>

<style scoped>
.usage-stats {
  padding: 0 0 16px;
  margin-bottom: 16px;
  border-bottom: 1px dashed var(--border, #e5e9f0);
}

.stats-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.stats-head h2 {
  margin: 0 0 4px;
  font-size: 17px;
  color: var(--ink-900, #1f2937);
}

.stats-sub {
  margin: 0;
  font-size: 12.5px;
  color: var(--ink-500, #6b7280);
  line-height: 1.6;
}

.range-tabs,
.lib-tabs {
  display: inline-flex;
  padding: 3px;
  background: var(--surface-2, #f3f5f9);
  border-radius: 9px;
  gap: 2px;
}

.range-tabs button,
.lib-tabs button {
  border: none;
  background: transparent;
  color: var(--ink-600, #4b5563);
  font-size: 12.5px;
  padding: 5px 11px;
  border-radius: 7px;
  cursor: pointer;
}

.range-tabs button.on,
.lib-tabs button.on {
  background: var(--surface, #fff);
  color: var(--primary, #2563eb);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.12);
}

.state {
  padding: 18px 0 4px;
  font-size: 13px;
}

.muted {
  color: var(--ink-500, #6b7280);
  font-size: 13px;
}

.err {
  color: var(--err, #dc2626);
}

.mini-link {
  margin-left: 8px;
  border: none;
  background: none;
  color: var(--primary, #2563eb);
  cursor: pointer;
  font-size: 12.5px;
}

.kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.kpi {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 13px 15px;
  border: 1px solid var(--line, #e5e9f0);
  border-radius: 11px;
  background: linear-gradient(180deg, var(--surface-2, #f8fafc), var(--surface, #fff));
}

.kpi-label {
  font-size: 12px;
  color: var(--ink-500, #6b7280);
}

.kpi-num {
  font-size: 26px;
  line-height: 1.2;
  color: var(--ink-900, #111827);
  font-variant-numeric: tabular-nums;
}

.kpi-hint {
  font-size: 11.5px;
  color: var(--ink-400, #9ca3af);
}

.kpi-link {
  align-self: flex-start;
  padding: 0;
  border: none;
  background: none;
  color: var(--primary, #2563eb);
  font-size: 11.5px;
  cursor: pointer;
}

.online-list {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 10px;
  padding: 10px 12px;
  background: var(--surface-2, #f8fafc);
  border-radius: 9px;
}

.online-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--ink-700, #374151);
  background: var(--surface, #fff);
  border: 1px solid var(--line, #e5e9f0);
  border-radius: 999px;
  padding: 3px 9px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ok, #10b981);
}

.charts {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: 18px;
  margin-top: 18px;
}

.user-panel {
  margin-top: 18px;
}

.user-head {
  align-items: flex-start;
}

.user-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ink-500, #6b7280);
}

.user-table {
  overflow-x: auto;
}

.user-grid {
  display: grid;
  grid-template-columns: minmax(140px, 1.5fr) minmax(104px, 1fr) 104px 40px 40px 44px 12px;
  align-items: center;
  gap: 7px;
  min-width: 560px;
}

.user-head-row {
  padding: 0 4px 6px;
  font-size: 11px;
  color: var(--ink-400, #9ca3af);
  border-bottom: 1px solid var(--line, #e5e9f0);
}

.user-item + .user-item {
  border-top: 1px solid var(--line, #eef1f6);
}

.user-row {
  width: 100%;
  padding: 8px 4px;
  border: none;
  background: transparent;
  font: inherit;
  font-size: 12px;
  color: var(--ink-700, #374151);
  text-align: left;
  cursor: pointer;
}

.user-row:hover,
.user-row.open {
  background: var(--surface-2, #f8fafc);
}

.u-who {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.u-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dot.off {
  background: var(--ink-300, #cbd5e1);
}

.u-active {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  color: var(--ink-600, #4b5563);
  font-variant-numeric: tabular-nums;
}

.u-track {
  flex: 0 1 52px;
  display: block;
  height: 6px;
  border-radius: 999px;
  background: var(--surface-2, #eef2f7);
  overflow: hidden;
}

.u-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #86efac, #10b981);
}

.u-last {
  font-size: 11.5px;
  color: var(--ink-500, #6b7280);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.num.strong {
  color: var(--ink-900, #111827);
  font-weight: 600;
}

.u-chev {
  color: var(--ink-400, #9ca3af);
  font-size: 11px;
  text-align: right;
}

.user-detail {
  margin: 0 4px 8px;
  padding: 9px 12px;
  border-radius: 8px;
  background: var(--surface-2, #f8fafc);
}

.detail-err {
  font-size: 12px;
}

.detail-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.detail-row {
  display: grid;
  grid-template-columns: 68px minmax(120px, 1fr) 52px 118px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.detail-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-700, #374151);
}

.detail-count {
  text-align: right;
  color: var(--ink-800, #1f2937);
  font-variant-numeric: tabular-nums;
}

.detail-time {
  text-align: right;
  color: var(--ink-500, #6b7280);
  font-variant-numeric: tabular-nums;
}

.user-notes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin-top: 10px;
  font-size: 11.5px;
  color: var(--ink-400, #9ca3af);
}

.panel {
  min-width: 0;
  border: 1px solid var(--line, #e5e9f0);
  border-radius: 12px;
  padding: 14px 16px 12px;
}

.panel h3 {
  margin: 0 0 10px;
  font-size: 13.5px;
  color: var(--ink-800, #1f2937);
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.panel-head h3 {
  margin: 0;
}

.line-svg {
  display: block;
  width: 100%;
  height: auto;
}

.grid {
  stroke: var(--line, #e5e9f0);
  stroke-width: 1;
  stroke-dasharray: 3 5;
}

.axis-y {
  font-size: 9px;
  fill: var(--ink-400, #9ca3af);
}

.area {
  fill: rgba(37, 99, 235, 0.1);
}

.line {
  fill: none;
  stroke: var(--primary, #2563eb);
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.point {
  fill: var(--surface, #fff);
  stroke: var(--primary, #2563eb);
  stroke-width: 1.5;
}

.axis-x {
  position: relative;
  height: 16px;
  margin: 2px 28px 0;
  font-size: 10px;
  color: var(--ink-400, #9ca3af);
}

.axis-x span {
  position: absolute;
  transform: translateX(-50%);
  white-space: nowrap;
}

.bars {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.bar-row {
  display: grid;
  grid-template-columns: 16px 20px minmax(84px, 1.1fr) minmax(70px, 1.4fr) 42px;
  align-items: center;
  gap: 7px;
  font-size: 12px;
}

.rank {
  color: var(--ink-400, #9ca3af);
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.b-icon {
  text-align: center;
  font-size: 14px;
}

.b-name {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  color: var(--ink-700, #374151);
}

.b-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kind {
  flex: 0 0 auto;
  padding: 1px 5px;
  border-radius: 5px;
  background: rgba(100, 116, 139, 0.13);
  color: var(--ink-500, #6b7280);
  font-size: 10px;
}

.b-track {
  height: 9px;
  border-radius: 999px;
  background: var(--surface-2, #f1f5f9);
  overflow: hidden;
}

.b-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #60a5fa, var(--primary, #2563eb));
}

.b-count {
  text-align: right;
  color: var(--ink-800, #1f2937);
  font-variant-numeric: tabular-nums;
}

.lib-total {
  margin-top: 4px;
  font-size: 11px;
  color: var(--ink-400, #9ca3af);
}

@media (max-width: 900px) {
  .charts {
    grid-template-columns: 1fr;
  }
}
</style>
