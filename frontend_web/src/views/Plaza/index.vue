<template>
  <div class="plaza">
    <div class="plaza-hd">
      <h1 class="title">智能体广场</h1>
      <p class="lede">SSD 测试域专用 AI 智能体 · 点击卡片进入运行页</p>
    </div>

    <!-- ===== 代码检视: 广场里的看板型智能体 (顶部显眼位置) ===== -->
    <div class="card review-card" :class="{ 'is-unconfigured': !health?.configured }">
      <div class="rc-hd">
        <div class="rc-t">
          <span class="rc-icon">🧪</span>
          <div class="rc-title">
            <div class="rc-name">代码检视</div>
            <div class="rc-sub">pr-agent 评审数据看板 · MR / 建议采纳率 / 规则命中</div>
          </div>
        </div>
        <div class="rc-status">
          <span v-if="health?.configured" class="rf-status" :class="`s-${health.status}`">
            <span class="dot"></span>{{ health.status === 'ok' ? 'pr-agent 已连接' : health.status === 'warn' ? '部分可用' : '未连接' }}
          </span>
          <span v-else class="rf-status s-off"><span class="dot"></span>未配置</span>
        </div>
      </div>

      <!-- 4 概览 -->
      <div v-if="health?.configured" class="rc-stats">
        <div class="stat">
          <div class="num">{{ overview?.mrs?.total ?? 0 }}</div>
          <div class="lbl">MR</div>
          <div class="sub">合并 {{ overview?.mrs?.merged ?? 0 }} · 开放 {{ overview?.mrs?.open ?? 0 }}</div>
        </div>
        <div class="stat">
          <div class="num">{{ overview?.suggestions?.total ?? 0 }}</div>
          <div class="lbl">建议</div>
          <div class="sub">采纳 {{ overview?.suggestions?.applied ?? 0 }} · 忽略 {{ overview?.suggestions?.dismissed ?? 0 }}</div>
        </div>
        <div class="stat highlight">
          <div class="num">{{ fmtPct(overview?.suggestions?.adoption_rate) }}</div>
          <div class="lbl">建议采纳率</div>
          <div class="sub">已应用 / 总建议</div>
        </div>
        <div class="stat">
          <div class="num">{{ fmtPct(overview?.runs?.success_rate) }}</div>
          <div class="lbl">运行成功率</div>
          <div class="sub">{{ overview?.runs?.total ?? 0 }} 次 · 失败 {{ overview?.runs?.failed ?? 0 }}</div>
        </div>
      </div>
      <div v-else class="rc-empty">
        <div class="rc-empty-ic">⚠️</div>
        <div class="rc-empty-t">pr-agent 未配置</div>
        <div class="rc-empty-d">admin 可在 <strong>设置 → 🧪 代码检视 (pr-agent)</strong> 填 base_url + token.<br />例: <code>http://host.docker.internal:5050</code></div>
      </div>

      <!-- 最近 MR 预览 (配置好时显示前 3 条) -->
      <div v-if="health?.configured && recentMrs.length > 0" class="rc-mrs">
        <div class="rc-mrs-hd">最近 MR</div>
        <div class="rc-mr-list">
          <div v-for="m in recentMrs" :key="`${m.project_id}/${m.mr_id}`" class="rc-mr-row">
            <a v-if="m.url" :href="m.url" target="_blank" rel="noopener" class="rc-mr-link">!{{ m.mr_id }}</a>
            <span v-else class="rc-mr-link">!{{ m.mr_id }}</span>
            <span class="rc-mr-title" :title="m.title">{{ m.title || '—' }}</span>
            <span class="badge" :class="stateCls(m.state)">{{ stateLabel(m.state) }}</span>
            <span class="rc-mr-time mono">{{ fmtIso(m.last_seen_at) }}</span>
          </div>
        </div>
      </div>

      <div class="rc-ft">
        <button class="btn-primary" @click="goReview">查看完整看板 →</button>
        <span class="rc-ft-sub">完整 MR 列表 / 规则命中 / 作者分布 / 时间线</span>
      </div>
    </div>

    <!-- ===== 现有智能体网格 ===== -->
    <div class="plaza-toolbar">
      <div class="filters">
        <button v-for="f in FILTERS" :key="f.value"
          class="filter" :class="{ active: filter === f.value }"
          @click="filter = f.value">
          <span class="lbl">{{ f.label }}</span><span class="count">{{ countBy(f.value) }}</span>
        </button>
      </div>
      <div class="search">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
        <input v-model="keyword" placeholder="搜智能体 / 标签..." />
      </div>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="filtered.length === 0" class="empty">
      <div style="font-size: 32px; opacity: 0.4">🩺</div>
      <div>暂无匹配的智能体</div>
    </div>
    <div v-else class="grid">
      <AgentCard v-for="a in filtered" :key="a.code" :agent="a" @open="onOpen" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import AgentCard from './AgentCard.vue';
import { listAgents, type AgentSummary } from '@/api/agents';
import { getHealth, getOverview, listMrs, type OverviewResp, type MrRow, type HealthResp } from '@/api/pragent';
import { fmtIso, fmtPct } from '@/utils/format';

const router = useRouter();
const agents = ref<AgentSummary[]>([]);
const loading = ref(true);
const filter = ref<'all' | 'stable' | 'beta' | 'featured'>('all');
const keyword = ref('');

const FILTERS = [
  { value: 'all' as const, label: '全部' },
  { value: 'featured' as const, label: '精选' },
  { value: 'stable' as const, label: '稳定' },
  { value: 'beta' as const, label: 'Beta' },
];

const filtered = computed(() => {
  let list = agents.value;
  if (filter.value === 'featured') list = list.filter((a) => a.is_featured);
  else if (filter.value === 'stable') list = list.filter((a) => a.status === 'stable');
  else if (filter.value === 'beta') list = list.filter((a) => a.status === 'beta');
  if (keyword.value.trim()) {
    const k = keyword.value.toLowerCase();
    list = list.filter(
      (a) =>
        a.name.toLowerCase().includes(k) ||
        a.summary.toLowerCase().includes(k) ||
        a.tags.some((t) => t.toLowerCase().includes(k)),
    );
  }
  return list;
});

function countBy(f: string): number {
  if (f === 'all') return agents.value.length;
  if (f === 'featured') return agents.value.filter((a) => a.is_featured).length;
  if (f === 'stable') return agents.value.filter((a) => a.status === 'stable').length;
  if (f === 'beta') return agents.value.filter((a) => a.status === 'beta').length;
  return 0;
}

function onOpen(a: AgentSummary) {
  router.push({ name: 'agent-runner', params: { code: a.code } });
}

function goReview() {
  router.push({ name: 'code-review' });
}

onMounted(async () => {
  try {
    const data = await listAgents();
    agents.value = data.items;
  } finally {
    loading.value = false;
  }
});

// ===== 代码检视 顶部区块数据 =====
const health = ref<HealthResp | null>(null);
const overview = ref<OverviewResp | null>(null);
const recentMrs = ref<MrRow[]>([]);

function stateLabel(s?: string): string {
  return s === 'opened' ? '开放'
    : s === 'merged' ? '已合并'
    : s === 'updated' ? '更新' : (s || '—');
}
function stateCls(s?: string): string {
  return s === 'merged' ? 'b-ok' : s === 'opened' ? 'b-info' : 'b-mute';
}

async function loadReview() {
  try {
    health.value = await getHealth();
    if (!health.value.configured) {
      overview.value = null;
      recentMrs.value = [];
      return;
    }
    const [ov, mr] = await Promise.all([
      getOverview(),
      listMrs({ limit: 3 }),
    ]);
    overview.value = ov;
    recentMrs.value = mr;
  } catch {
    // 静默失败, 顶部区块降级为空态
    health.value = null;
  }
}

onMounted(loadReview);
</script>

<style scoped>
.plaza { display: flex; flex-direction: column; gap: 16px; }
.plaza-hd { display: none; }  /* 标题已挪到 AppHeader, 不再显示 */
.title { font-size: 30px; font-weight: 800; margin: 0 0 8px; letter-spacing: -0.4px; color: var(--ink-900); }
.lede { color: var(--ink-700); margin: 0; font-size: 14.5px; }

/* ===== 代码检视 顶部卡 ===== */
.review-card {
  display: flex; flex-direction: column; gap: 14px;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 18px 20px; box-shadow: var(--shadow-sm);
  position: relative;
  overflow: hidden;
}
.review-card::before {
  /* 顶部装饰条, 跟其他卡片区分 */
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px;
  background: var(--primary-grad);
}
.review-card.is-unconfigured { opacity: 0.92; }

.rc-hd { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.rc-t { display: flex; gap: 12px; align-items: center; min-width: 0; }
.rc-icon {
  width: 40px; height: 40px; border-radius: 11px;
  display: flex; align-items: center; justify-content: center;
  font-size: 22px; flex-shrink: 0;
  background: var(--primary-grad-soft);
  border: 1px solid transparent;
}
.rc-title { min-width: 0; }
.rc-name { font-size: 16px; font-weight: 800; color: var(--ink-900); line-height: 1.2; letter-spacing: -0.2px; }
.rc-sub { font-size: 12px; color: var(--ink-500); margin-top: 2px; }

.rc-status .rf-status {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 11px; font-weight: 600;
  padding: 3px 10px; border-radius: var(--radius-pill);
  background: var(--surface-sunken); color: var(--ink-700);
}
.rc-status .rf-status .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.s-ok { background: color-mix(in srgb, var(--ok) 18%, transparent); color: var(--ok); }
.s-warn { background: color-mix(in srgb, var(--warn) 18%, transparent); color: var(--warn); }
.s-off { background: color-mix(in srgb, var(--err) 14%, transparent); color: var(--err); }

/* 4 stat */
.rc-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
@media (max-width: 900px) { .rc-stats { grid-template-columns: repeat(2, 1fr); } }
.rc-stats .stat {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px; display: flex; flex-direction: column; gap: 3px;
}
.rc-stats .stat .num {
  font-size: 24px; font-weight: 800; color: var(--ink-900);
  font-family: var(--font-mono); letter-spacing: -0.5px;
}
.rc-stats .stat .lbl { font-size: 11.5px; color: var(--ink-500); font-weight: 600; }
.rc-stats .stat .sub { font-size: 10.5px; color: var(--ink-500); font-family: var(--font-mono); }
.rc-stats .stat.highlight {
  background: var(--primary-grad-soft);
}
.rc-stats .stat.highlight .num {
  background: var(--primary-grad-text);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
}

/* 未配置引导 */
.rc-empty {
  display: flex; gap: 12px; align-items: flex-start;
  padding: 14px 16px; border-radius: 10px;
  background: color-mix(in srgb, var(--warn) 6%, var(--surface));
  border: 1px dashed color-mix(in srgb, var(--warn) 50%, transparent);
}
.rc-empty-ic { font-size: 22px; flex-shrink: 0; }
.rc-empty-t { font-size: 13px; font-weight: 700; color: var(--ink-900); }
.rc-empty-d { font-size: 12px; color: var(--ink-700); line-height: 1.6; margin-top: 2px; }
.rc-empty-d code {
  font-family: var(--font-mono); background: var(--surface-sunken);
  padding: 1px 5px; border-radius: 4px; font-size: 11px;
}

/* 最近 MR 预览 */
.rc-mrs { display: flex; flex-direction: column; gap: 6px; }
.rc-mrs-hd {
  font-size: 11.5px; color: var(--ink-500); font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.rc-mr-list { display: flex; flex-direction: column; gap: 2px; }
.rc-mr-row {
  display: grid; grid-template-columns: 56px 1fr auto auto;
  gap: 10px; align-items: center;
  padding: 6px 10px; border-radius: 7px;
  font-size: 12.5px;
}
.rc-mr-row:hover { background: var(--surface-sunken); }
.rc-mr-link { font-family: var(--font-mono); font-weight: 700; color: var(--primary); text-decoration: none; font-size: 12px; }
.rc-mr-link:hover { text-decoration: underline; }
.rc-mr-title { color: var(--ink-900); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rc-mr-time { font-size: 11px; color: var(--ink-500); }

.badge {
  display: inline-flex; align-items: center;
  font-size: 10.5px; font-weight: 600; padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken); color: var(--ink-700);
  font-family: var(--font-mono);
}
.b-ok { background: color-mix(in srgb, var(--ok) 18%, transparent); color: var(--ok); }
.b-info { background: color-mix(in srgb, var(--primary) 15%, transparent); color: var(--primary); }
.b-mute { background: var(--surface-sunken); color: var(--ink-500); }

/* 底部按钮 */
.rc-ft {
  display: flex; align-items: center; gap: 12px;
  padding-top: 10px; border-top: 1px dashed var(--border);
}
.btn-primary {
  background: var(--primary-grad); color: #fff;
  border: none; padding: 7px 16px; border-radius: 8px;
  font-size: 12.5px; font-weight: 600; font-family: inherit; cursor: pointer;
  box-shadow: var(--primary-shadow);
  transition: transform 0.1s ease;
}
.btn-primary:hover { transform: translateY(-1px); }
.rc-ft-sub { font-size: 11px; color: var(--ink-500); }

/* ===== 智能体网格 (保留原样) ===== */
.plaza-toolbar {
  display: flex; justify-content: space-between; align-items: center; gap: 16px;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 12px 16px; box-shadow: var(--shadow-sm);
  position: sticky;
  top: 0;
  z-index: 4;
}
.filters { display: flex; gap: 6px; }
.filter {
  background: transparent; border: 1px solid transparent;
  padding: 7px 14px; border-radius: var(--radius-pill);
  font-size: 13px; color: var(--ink-700); cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
  display: inline-flex; align-items: center; gap: 5px;
}
.filter:hover { background: var(--surface-sunken); color: var(--ink-900); }
.filter.active {
  background: var(--primary-grad-soft);
  border-color: transparent;
  font-weight: 600;
  box-shadow: inset 0 0 0 1px var(--border);
}
.filter.active .lbl {
  display: inline-block;
  background: var(--primary-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
}
.filter .count {
  font-size: 11.5px; background: var(--surface); padding: 1px 7px; border-radius: var(--radius-pill);
  font-family: var(--font-mono); font-weight: 600;
}
.filter.active .count { background: var(--primary-grad); color: #fff; }

.search {
  display: flex; align-items: center; gap: 6px;
  background: var(--surface); border: 1px solid var(--border);
  padding: 6px 10px; border-radius: 8px;
  color: var(--ink-500);
}
.search input {
  border: 0; outline: none; background: transparent;
  font-size: 13px; color: var(--ink-900); font-family: inherit; width: 180px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
@media (max-width: 1100px) {
  .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.loading, .empty {
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 60px 20px; text-align: center; color: var(--ink-500);
  font-size: 13.5px; display: flex; flex-direction: column; gap: 8px; align-items: center;
}
</style>
