<template>
  <div class="cr">
    <!-- 顶栏: 与其他智能体详情布局一致 (返回广场 + icon + 名/版本/简介 + status + 时间窗/刷新) -->
    <div class="run-hd">
      <button class="back" @click="$router.push({ name: 'plaza' })">← 返回广场</button>
      <div class="run-title">
        <div class="run-icon">🧪</div>
        <div>
          <div class="run-name">
            <span>代码检视</span>
            <span class="run-ver">v0.1.0</span>
          </div>
          <div class="run-summary">pr-agent 评审数据看板 · MR / 建议采纳率 / 规则命中 / 作者分布</div>
        </div>
      </div>
      <div class="run-badge st-stable">
        <span class="dot"></span>稳定
      </div>
      <div class="hd-r">
        <select v-model="windowSel" class="win-sel" @change="reload">
          <option value="all">全部时间</option>
          <option value="7d">近 7 天</option>
          <option value="30d">近 30 天</option>
        </select>
        <button class="reload" @click="reload" :disabled="loading">↻ 刷新</button>
      </div>
    </div>

    <!-- 未配置 / 连不上 提示 -->
    <div v-if="health && !health.configured" class="card warn">
      <div class="warn-ic">🧪</div>
      <div class="warn-body">
        <div class="warn-t">pr-agent 未配置</div>
        <div class="warn-d">admin 可在 <strong>设置 → 🧪 代码检视 (pr-agent)</strong> 填 base_url + token.<br />
          例: <code>http://host.docker.internal:5050</code> · 默认无需 token.</div>
      </div>
    </div>
    <div v-else-if="loadError" class="card warn">
      <div class="warn-ic">⚠️</div>
      <div class="warn-body">
        <div class="warn-t">pr-agent 不可达</div>
        <div class="warn-d">{{ loadError }}<br />检查 base_url / 网络 / 容器状态.</div>
      </div>
    </div>

    <!-- 概览卡片: 4 大块 -->
    <div v-if="overview" class="stats">
      <div class="stat">
        <div class="num">{{ overview.mrs?.total ?? 0 }}</div>
        <div class="lbl">MR</div>
        <div class="sub">合并 {{ overview.mrs?.merged ?? 0 }} · 开放 {{ overview.mrs?.open ?? 0 }}</div>
      </div>
      <div class="stat">
        <div class="num">{{ overview.suggestions?.total ?? 0 }}</div>
        <div class="lbl">建议</div>
        <div class="sub">采纳 {{ overview.suggestions?.applied ?? 0 }} · 忽略 {{ overview.suggestions?.dismissed ?? 0 }}</div>
      </div>
      <div class="stat highlight">
        <div class="num">{{ fmtPct(overview.suggestions?.adoption_rate) }}</div>
        <div class="lbl">建议采纳率</div>
        <div class="sub">已应用 / 总建议</div>
      </div>
      <div class="stat">
        <div class="num">{{ fmtPct(overview.runs?.success_rate) }}</div>
        <div class="lbl">运行成功率</div>
        <div class="sub">{{ overview.runs?.total ?? 0 }} 次 · 失败 {{ overview.runs?.failed ?? 0 }}</div>
      </div>
    </div>

    <!-- 主区两列: 规则 + 作者 -->
    <div v-if="overview" class="cols">
      <!-- 规则柱图 (横向 bar, 纯 CSS) -->
      <div class="card">
        <div class="card-hd">
          <h2>📐 规则命中</h2>
          <span class="cnt">{{ rules.length }} 条</span>
        </div>
        <div v-if="rules.length === 0" class="empty">暂无规则命中记录</div>
        <div v-else class="rules">
          <div v-for="r in rulesTop" :key="r.rule_key" class="rule-row">
            <div class="rule-k" :title="r.rule_key">{{ r.rule_key }}</div>
            <div class="rule-bar">
              <div class="bar-fill" :style="{ width: rulePct(r) + '%' }"></div>
            </div>
            <div class="rule-n mono">{{ r.cited_count ?? 0 }}</div>
            <div class="rule-ap mono">{{ fmtPct(r.adoption_rate) }}</div>
          </div>
        </div>
      </div>

      <!-- 作者表 -->
      <div class="card">
        <div class="card-hd">
          <h2>👤 作者分布</h2>
          <span class="cnt">{{ authors.length }} 人</span>
        </div>
        <div v-if="authors.length === 0" class="empty">暂无作者数据</div>
        <table v-else class="tbl">
          <thead>
            <tr><th>作者</th><th class="r">MR</th><th class="r">建议</th><th class="r">采纳率</th><th>命令分布</th></tr>
          </thead>
          <tbody>
            <tr v-for="a in authors" :key="a.author">
              <td>{{ a.author }}</td>
              <td class="r mono">{{ a.mr_count ?? 0 }}</td>
              <td class="r mono">{{ a.suggestion_total ?? 0 }}</td>
              <td class="r mono">{{ fmtPct(a.adoption_rate) }}</td>
              <td class="cmds">
                <span v-for="(v, k) in (a.runs_by_command || {})" :key="k" class="cmd-tag">
                  {{ k }} <span class="mono">{{ v.total }}</span>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- MR 列表 -->
    <div class="card">
      <div class="card-hd">
        <h2>📋 Merge Request</h2>
        <span class="cnt">{{ mrs.length }} 条</span>
      </div>
      <div v-if="loading && mrs.length === 0" class="loading">加载中...</div>
      <div v-else-if="mrs.length === 0" class="empty">暂无 MR 记录</div>
      <table v-else class="tbl mr-tbl">
        <thead>
          <tr>
            <th>MR</th><th>作者</th><th>源 → 目标</th><th>状态</th><th>开启</th><th>最后活动</th><th class="r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in mrs" :key="`${m.project_id}/${m.mr_id}`" :class="{ merged: m.state === 'merged' }">
            <td>
              <div class="mr-t">
                <a v-if="m.url" :href="m.url" target="_blank" rel="noopener" class="mr-link">!{{ m.mr_id }}</a>
                <span v-else class="mr-link">!{{ m.mr_id }}</span>
                <div class="mr-title" :title="m.title">{{ m.title || '—' }}</div>
              </div>
            </td>
            <td>{{ m.author || '—' }}</td>
            <td class="mono branches">{{ m.source_branch || '—' }} → {{ m.target_branch || '—' }}</td>
            <td>
              <span class="badge" :class="stateCls(m.state)">{{ stateLabel(m.state) }}</span>
            </td>
            <td class="mono">{{ fmtIso(m.opened_at) }}</td>
            <td class="mono">{{ fmtIso(m.last_seen_at) }}</td>
            <td class="r">
              <button class="link-btn" @click="openTimeline(m)" :disabled="tlLoading === `${m.project_id}/${m.mr_id}`">查看时间线</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 时间线抽屉 -->
    <el-drawer v-model="tlOpen" :title="tlTitle" size="640px" direction="rtl">
      <template v-if="timeline">
        <!-- MR 元信息 -->
        <div class="dt">
          <div class="dt-row"><span class="dt-k">ID</span><span class="dt-v mono">!{{ timeline.mr?.mr_id }} · {{ timeline.mr?.project_id }}</span></div>
          <div class="dt-row"><span class="dt-k">作者</span><span class="dt-v">{{ timeline.mr?.author || '—' }}</span></div>
          <div class="dt-row"><span class="dt-k">分支</span><span class="dt-v mono">{{ timeline.mr?.source_branch }} → {{ timeline.mr?.target_branch }}</span></div>
          <div class="dt-row"><span class="dt-k">状态</span><span class="dt-v"><span class="badge" :class="stateCls(timeline.mr?.state)">{{ stateLabel(timeline.mr?.state) }}</span></span></div>
          <div class="dt-row"><span class="dt-k">开启</span><span class="dt-v mono">{{ fmtIso(timeline.mr?.opened_at) }}</span></div>
          <div v-if="timeline.mr?.merged_at" class="dt-row"><span class="dt-k">合并</span><span class="dt-v mono">{{ fmtIso(timeline.mr?.merged_at) }}</span></div>
        </div>

        <!-- 运行历史 -->
        <div class="dt-sep">运行历史 ({{ timeline.runs?.length || 0 }})</div>
        <div v-if="!timeline.runs?.length" class="empty sm">无</div>
        <div v-else class="runs">
          <div v-for="r in timeline.runs" :key="r.run_id" class="run-row">
            <span class="cmd-tag">{{ r.command }}</span>
            <span class="badge" :class="runCls(r.status)">{{ r.status }}</span>
            <span class="mono small">{{ fmtIso(r.started_at) }}</span>
            <span class="mono small">{{ fmtMs(r.duration_ms) }}</span>
            <span v-if="r.model" class="mono small model">{{ r.model }}</span>
            <span v-if="r.error" class="err mono small" :title="r.error">⚠ {{ r.error }}</span>
          </div>
        </div>

        <!-- 建议列表 -->
        <div class="dt-sep">评审建议 ({{ timeline.suggestions?.length || 0 }})</div>
        <div v-if="!timeline.suggestions?.length" class="empty sm">无</div>
        <div v-else class="sugs">
          <div v-for="(s, idx) in timeline.suggestions" :key="s.id ?? idx" class="sug-row" :class="`s-${s.state}`">
            <div class="sug-l">
              <span class="badge sm" :class="sugCls(s.state)">{{ sugLabel(s.state) }}</span>
              <span class="imp mono" v-if="s.importance" :title="`importance=${s.importance}`">{{ '★'.repeat(Math.min(s.importance, 5)) }}</span>
            </div>
            <div class="sug-body">
              <div class="sug-loc mono">{{ s.file || '?' }}:{{ s.line ?? '?' }}</div>
              <div class="sug-sum">{{ s.one_sentence_summary || s.label || '—' }}</div>
              <div v-if="s.rule_keys?.length" class="sug-rules">
                <code v-for="k in s.rule_keys" :key="k">{{ k }}</code>
              </div>
            </div>
          </div>
        </div>
      </template>
      <template v-else>
        <div class="loading">加载中...</div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import {
  getHealth, getOverview, getRules, getAuthors, listMrs, getTimeline,
  type OverviewResp, type RuleStat, type AuthorStat, type MrRow, type TimelineResp, type HealthResp,
} from '@/api/pragent';
import { fmtIso, fmtPct, fmtMs } from '@/utils/format';

const loading = ref(false);
const loadError = ref('');
const health = ref<HealthResp | null>(null);
const overview = ref<OverviewResp | null>(null);
const rules = ref<RuleStat[]>([]);
const authors = ref<AuthorStat[]>([]);
const mrs = ref<MrRow[]>([]);

const windowSel = ref<'all' | '7d' | '30d'>('all');

function sinceFor(sel: string): string | undefined {
  if (sel === 'all') return undefined;
  const days = sel === '7d' ? 7 : 30;
  const d = new Date(Date.now() - days * 86400_000);
  return d.toISOString();
}

async function reload() {
  loading.value = true;
  loadError.value = '';
  try {
    const since = sinceFor(windowSel.value);
    health.value = await getHealth();
    if (!health.value.configured) {
      overview.value = null; rules.value = []; authors.value = []; mrs.value = [];
      return;
    }
    const [ov, rl, au, mr] = await Promise.all([
      getOverview(since),
      getRules(since),
      getAuthors(since),
      listMrs({ limit: 50, since }),
    ]);
    overview.value = ov;
    rules.value = rl;
    authors.value = au;
    mrs.value = mr;
  } catch (e: any) {
    loadError.value = (e?.response?.data?.detail || e?.message || '未知错误');
    ElMessage.error('代码检视加载失败: ' + loadError.value);
  } finally {
    loading.value = false;
  }
}

// 规则: 取前 10, 按 cited_count 降序
const rulesTop = computed(() => {
  return [...rules.value].sort((a, b) => (b.cited_count ?? 0) - (a.cited_count ?? 0)).slice(0, 10);
});
const maxCited = computed(() => Math.max(1, ...rulesTop.value.map(r => r.cited_count ?? 0)));
function rulePct(r: RuleStat): number {
  return Math.round(((r.cited_count ?? 0) / maxCited.value) * 100);
}

// 状态色
function stateLabel(s?: string): string {
  return s === 'opened' ? '开放'
    : s === 'merged' ? '已合并'
    : s === 'updated' ? '更新' : (s || '—');
}
function stateCls(s?: string): string {
  return s === 'merged' ? 'b-ok' : s === 'opened' ? 'b-info' : 'b-mute';
}
function runCls(s: string): string {
  return s === 'success' ? 'b-ok' : s === 'failed' ? 'b-err' : s === 'empty' ? 'b-mute' : 'b-info';
}
function sugLabel(s?: string): string {
  return s === 'applied' ? '已采纳' : s === 'dismissed' ? '已忽略' : s === 'superseded' ? '已替代' : '开放';
}
function sugCls(s?: string): string {
  return s === 'applied' ? 'b-ok' : s === 'dismissed' ? 'b-mute' : s === 'superseded' ? 'b-warn' : 'b-info';
}

// 时间线抽屉
const tlOpen = ref(false);
const tlLoading = ref('');
const tlTitle = ref('MR 时间线');
const timeline = ref<TimelineResp | null>(null);
async function openTimeline(m: MrRow) {
  const key = `${m.project_id}/${m.mr_id}`;
  tlLoading.value = key;
  tlTitle.value = `!${m.mr_id} · ${m.title || ''}`;
  timeline.value = null;
  tlOpen.value = true;
  try {
    timeline.value = await getTimeline(m.project_id, m.mr_id);
  } catch (e: any) {
    ElMessage.error('时间线加载失败: ' + (e?.response?.data?.detail || e?.message));
    tlOpen.value = false;
  } finally {
    tlLoading.value = '';
  }
}

onMounted(reload);
</script>

<style scoped>
.cr { display: flex; flex-direction: column; gap: 16px; }
/* 顶部栏 (跟 AgentRunner 保持一致) */
.run-hd {
  display: flex; align-items: center; gap: 16px;
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 14px 18px; box-shadow: var(--shadow-sm);
}
.back {
  background: transparent; border: 1px solid var(--border);
  padding: 6px 12px; border-radius: 8px;
  color: var(--ink-700); font-size: 12.5px; cursor: pointer;
  font-family: inherit; transition: all 0.15s ease;
  flex-shrink: 0;
}
.back:hover { background: var(--surface-sunken); color: var(--ink-900); }
.run-title { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }
.run-icon {
  width: 44px; height: 44px; border-radius: 11px;
  background: var(--primary-grad);
  display: flex; align-items: center; justify-content: center; font-size: 22px;
  box-shadow: var(--primary-shadow);
  flex-shrink: 0;
}
.run-name { display: flex; align-items: baseline; gap: 8px; }
.run-name > span:first-child { font-size: 18px; font-weight: 800; color: var(--ink-900); letter-spacing: -0.2px; }
.run-ver { font-size: 12px; color: var(--ink-500); font-family: var(--font-mono); }
.run-summary { font-size: 12.5px; color: var(--ink-700); margin-top: 2px; }
.run-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: var(--radius-pill);
  font-size: 11px; font-weight: 600;
  background: var(--surface-sunken); color: var(--ink-700);
  flex-shrink: 0;
}
.run-badge .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.st-stable { background: color-mix(in srgb, var(--ok) 18%, transparent); color: var(--ok); }
.st-beta { background: color-mix(in srgb, var(--warn) 18%, transparent); color: var(--warn); }
.st-draft { background: var(--surface-sunken); color: var(--ink-500); }
.win-sel, .reload {
  background: var(--surface); border: 1px solid var(--border);
  color: var(--ink-700); padding: 6px 12px; border-radius: 8px;
  font-size: 12.5px; font-family: inherit; cursor: pointer;
}
.win-sel:hover, .reload:hover { background: var(--surface-sunken); color: var(--ink-900); }
.reload:disabled { opacity: 0.5; cursor: not-allowed; }



.hd-r { display: flex; gap: 8px; align-items: center; margin-left: auto; }




/* 状态警告卡 */
.warn {
  display: flex; gap: 14px; align-items: flex-start;
  border: 1px dashed var(--warn);
  background: color-mix(in srgb, var(--warn) 6%, var(--surface-soft));
}
.warn-ic { font-size: 24px; flex-shrink: 0; }
.warn-t { font-size: 14px; font-weight: 700; color: var(--ink-900); margin-bottom: 2px; }
.warn-d { font-size: 12.5px; color: var(--ink-700); line-height: 1.6; }
.warn-d code { font-family: var(--font-mono); background: var(--surface-sunken); padding: 1px 6px; border-radius: 4px; }

/* 概览卡片 */
.stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
@media (max-width: 900px) { .stats { grid-template-columns: repeat(2, 1fr); } }
.stat {
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 14px 18px; box-shadow: var(--shadow-sm);
  display: flex; flex-direction: column; gap: 4px;
}
.stat .num { font-size: 28px; font-weight: 800; color: var(--ink-900); font-family: var(--font-mono); letter-spacing: -0.5px; }
.stat .lbl { font-size: 12px; color: var(--ink-500); font-weight: 600; }
.stat .sub { font-size: 11.5px; color: var(--ink-500); font-family: var(--font-mono); }
.stat.highlight { background: var(--primary-grad-soft); }
.stat.highlight .num {
  background: var(--primary-grad-text);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
}

/* 主区两列 */
.cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 1100px) { .cols { grid-template-columns: 1fr; } }

/* 通用 card */
.card {
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 16px 18px; box-shadow: var(--shadow-sm);
  display: flex; flex-direction: column; gap: 10px;
}
.card-hd { display: flex; justify-content: space-between; align-items: center; margin: 0; }
.card-hd h2 { font-size: 14.5px; font-weight: 700; margin: 0; color: var(--ink-900); }
.card-hd .cnt { font-size: 11.5px; color: var(--ink-500); font-family: var(--font-mono); }

.empty { padding: 40px 12px; text-align: center; color: var(--ink-500); font-size: 12.5px; }
.empty.sm { padding: 14px; }
.loading { padding: 30px; text-align: center; color: var(--ink-500); font-size: 12.5px; }

/* 规则柱图 */
.rules { display: flex; flex-direction: column; gap: 6px; }
.rule-row { display: grid; grid-template-columns: 140px 1fr 44px 56px; gap: 8px; align-items: center; font-size: 12px; }
.rule-k { font-family: var(--font-mono); font-size: 11.5px; color: var(--ink-700); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rule-bar { height: 6px; background: var(--surface-sunken); border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--primary-grad); border-radius: 4px; transition: width 0.3s ease; }
.rule-n { color: var(--ink-700); text-align: right; font-size: 11.5px; }
.rule-ap { color: var(--ink-700); text-align: right; font-size: 11.5px; }

/* 表格 */
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.tbl th, .tbl td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }
.tbl th { font-size: 11.5px; font-weight: 600; color: var(--ink-500); text-transform: uppercase; letter-spacing: 0.04em; }
.tbl td.r, .tbl th.r { text-align: right; }
.tbl tbody tr:hover { background: var(--surface-sunken); }
.tbl tbody tr:last-child td { border-bottom: none; }
.cmds { display: flex; gap: 4px; flex-wrap: wrap; }
.cmd-tag {
  display: inline-flex; align-items: center; gap: 4px;
  background: var(--primary-grad-soft); border: 1px solid transparent;
  font-size: 10.5px; font-weight: 600; padding: 1px 7px; border-radius: var(--radius-pill);
  color: var(--ink-900);
}

/* MR 列表 */
.mr-tbl td { vertical-align: top; }
.mr-t { display: flex; flex-direction: column; gap: 2px; max-width: 380px; }
.mr-link { font-family: var(--font-mono); font-weight: 700; color: var(--primary); text-decoration: none; font-size: 12px; }
.mr-link:hover { text-decoration: underline; }
.mr-title { font-size: 12.5px; color: var(--ink-700); overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; }
.branches { font-size: 11.5px; color: var(--ink-700); }
.mr-tbl tr.merged { opacity: 0.7; }

.link-btn {
  background: transparent; border: 1px solid var(--border); color: var(--primary);
  padding: 3px 10px; border-radius: 6px; font-size: 11.5px; font-family: inherit; cursor: pointer;
}
.link-btn:hover { background: var(--primary-grad-soft); border-color: transparent; }
.link-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* badge */
.badge {
  display: inline-flex; align-items: center;
  font-size: 10.5px; font-weight: 600; padding: 1px 8px;
  border-radius: var(--radius-pill);
  background: var(--surface-sunken); color: var(--ink-700);
  font-family: var(--font-mono);
}
.badge.sm { padding: 0 6px; font-size: 10px; }
.b-ok { background: color-mix(in srgb, var(--ok) 18%, transparent); color: var(--ok); }
.b-info { background: color-mix(in srgb, var(--primary) 15%, transparent); color: var(--primary); }
.b-warn { background: color-mix(in srgb, var(--warn) 18%, transparent); color: var(--warn); }
.b-err { background: color-mix(in srgb, var(--err) 18%, transparent); color: var(--err); }
.b-mute { background: var(--surface-sunken); color: var(--ink-500); }

/* drawer 样式复用 KnowledgeManage 的 .dt-* / .dt-pre 等 */
.dt { display: flex; flex-direction: column; gap: 8px; }
.dt-row { display: grid; grid-template-columns: 80px 1fr; gap: 10px; font-size: 12.5px; }
.dt-k { color: var(--ink-500); font-size: 11.5px; }
.dt-v { color: var(--ink-900); }
.dt-v.mono { font-family: var(--font-mono); font-size: 11.5px; }
.dt-sep { font-size: 12.5px; font-weight: 700; color: var(--ink-700); margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }

.runs { display: flex; flex-direction: column; gap: 4px; }
.run-row { display: flex; gap: 8px; align-items: center; font-size: 11.5px; padding: 5px 0; border-bottom: 1px dashed var(--border); flex-wrap: wrap; }
.run-row:last-child { border-bottom: none; }
.run-row .small { color: var(--ink-500); }
.run-row .model { color: var(--ink-700); }
.run-row .err { color: var(--err); }

.sugs { display: flex; flex-direction: column; gap: 6px; }
.sug-row { display: grid; grid-template-columns: auto 1fr; gap: 10px; padding: 8px 10px; background: var(--surface-sunken); border-radius: 8px; align-items: start; }
.sug-row.s-applied { opacity: 0.65; }
.sug-row.s-dismissed { opacity: 0.45; }
.sug-l { display: flex; flex-direction: column; gap: 4px; align-items: center; }
.sug-l .imp { color: var(--warn); font-size: 10px; letter-spacing: -1px; }
.sug-body { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.sug-loc { font-size: 11px; color: var(--ink-700); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sug-sum { font-size: 12.5px; color: var(--ink-900); }
.sug-rules { display: flex; gap: 4px; flex-wrap: wrap; }
.sug-rules code { font-family: var(--font-mono); font-size: 10px; background: var(--surface); border: 1px solid var(--border); padding: 0 5px; border-radius: 4px; color: var(--ink-700); }
</style>
