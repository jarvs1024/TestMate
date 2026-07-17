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
          <option value="custom">自定义…</option>
        </select>
        <input v-if="windowSel === 'custom'" v-model.number="customDays" type="number" min="1" max="365" class="win-custom" @change="reload" title="自定义天数 (1-365)" />
        <span class="last-updated" :title="`刷新时间: ${lastUpdatedLabel}`">{{ lastUpdatedRel }} · 更新</span>
        <button class="reload" @click="reload" :disabled="loading">
          <span :class="{ spinning: loading }">↻</span> 刷新
        </button>
      </div>
    </div>

    <!-- 评审失败 banner: 顶部醒目提示, 点击展开 inline failed MR list (不必滚到 MR 表) -->
    <div v-if="failedMrCount > 0" class="banner banner-err" :class="{ open: bannerOpen }" role="region" :aria-expanded="bannerOpen">
      <button class="banner-hd" type="button" @click="bannerOpen = !bannerOpen" :aria-controls="'failed-mr-list'">
        <span class="b-icon">{{ bannerOpen ? '▾' : '▸' }}</span>
        <span class="b-text">
          <b>{{ failedMrCount }}</b> 个 Merge Request 最近一次 pr-agent 评审失败
        </span>
        <span class="b-hint">{{ bannerOpen ? '收起' : '展开' }} {{ bannerOpen ? '' : '↓' }}</span>
      </button>
      <div v-show="bannerOpen" id="failed-mr-list" class="failed-mr-list">
        <table class="tbl">
          <thead>
            <tr><th>MR</th><th>作者</th><th>分支</th><th class="r">上次命令</th><th class="r">错误</th></tr>
          </thead>
          <tbody>
            <tr v-for="m in failedMrs" :key="`${m.project_id}/${m.mr_id}`">
              <td>
                <a v-if="m.url" :href="m.url" target="_blank" rel="noopener" class="mr-link mono">!{{ m.mr_id }}</a>
                <span v-else class="mr-link mono">!{{ m.mr_id }}</span>
              </td>
              <td>{{ m.author || '—' }}</td>
              <td class="mono branches">{{ m.source_branch || '—' }} → {{ m.target_branch || '—' }}</td>
              <td class="r"><span class="cmd-tag-s">{{ m.last_run?.command || '—' }}</span></td>
              <td class="err-cell">
                <span v-if="m.last_run?.error" class="err-text" :title="m.last_run?.error">{{ m.last_run?.error }}</span>
                <span v-else>—</span>
              </td>
            </tr>
            <tr v-if="failedMrs.length === 0"><td colspan="5" class="empty">无</td></tr>
          </tbody>
        </table>
        <div class="banner-foot">
          <button class="link-btn" type="button" @click="scrollToMrTable">查看完整 MR 列表 ↓</button>
        </div>
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
      <!-- 严重等级告警: 红色块 (critical.dismissed) + 黄 (critical.open) -->
      <div class="stat alert" :class="{ hot: (sevBucket('critical')?.dismissed ?? 0) > 0 }">
        <div class="num" :class="{ zero: (sevBucket('critical')?.dismissed ?? 0) === 0 }">
          {{ sevBucket('critical')?.dismissed ?? 0 }}
        </div>
        <div class="lbl">严重建议被忽略</div>
        <div class="sub">
          严重 {{ sevBucket('critical')?.total ?? 0 }} · 待处理 {{ sevBucket('critical')?.open ?? 0 }}
        </div>
      </div>
      <div class="stat">
        <div class="num">{{ fmtPct(overview.runs?.success_rate) }}</div>
        <div class="lbl">运行成功率</div>
        <div class="sub">{{ overview.runs?.total ?? 0 }} 次 · 失败 {{ overview.runs?.failed ?? 0 }}</div>
      </div>
    </div>

    <!-- 严重等级分布: 全宽卡 -->
    <div class="card sev-card">
      <div class="card-hd sev-card-hd">
        <h2>🔥 严重等级分布</h2>
        <span class="sev-head-count">{{ severityBuckets.filter(b => (b.total || 0) > 0).length }} 桶 (有数据)</span>
        <span class="sev-head-legend" v-if="totalSuggestions > 0">
          <span class="sev-legend-item"><span class="legend-swatch seg-applied"></span>已采纳</span>
          <span class="sev-legend-item"><span class="legend-swatch seg-dismissed"></span>已忽略</span>
          <span class="sev-legend-item"><span class="legend-swatch seg-open"></span>待处理</span>
          <span class="sev-legend-item"><span class="legend-swatch seg-superseded"></span>已替代</span>
        </span>
        <span class="sev-head-summary" :title="`${totalSuggestions} 条建议总采纳率`">{{ fmtPct(severityAdoption) }} 整体采纳</span>
      </div>
      <div v-if="severityBuckets.length === 0" class="empty">暂无严重等级数据</div>
      <div v-else class="sev-body">
        <!-- legend: 颜色语义图例 (applied=绿 / dismissed=灰 / open=黄 / superseded=品牌色弱化)
             每个 severity 一行, 行内堆叠 state segment. 整张卡片直观表达:
             哪个 severity 采纳率低 + 哪个 severity 有 open 待处理 -->
        <div class="sev-rows-list" v-if="totalSuggestions > 0">
          <div v-for="b in SEV_ORDER" :key="b" class="sev-row-line"
               :class="sevCls(b)"
               v-show="(sevBucket(b)?.total || 0) > 0">
            <div class="sev-row-hd">
              <span class="sev-row-name"><span class="sev-legend-dot" :class="sevCls(b)"></span>{{ sevLabel(b) }}</span>
              <span class="sev-row-meta">
                <span class="sev-row-total">{{ sevBucket(b)?.total }} 条</span>
                <span class="sev-row-rate" :title="`采纳率`">{{ fmtPct(sevBucket(b)?.adoption_rate) }}</span>
              </span>
            </div>
            <div class="sev-row-bar">
              <div class="seg seg-applied"   :style="{ flex: sevBucket(b)?.applied || 0 }"   :title="`已采纳 ${sevBucket(b)?.applied || 0}`">{{ (sevBucket(b)?.applied || 0) > 0 ? sevBucket(b)?.applied : '' }}</div>
              <div class="seg seg-dismissed" :style="{ flex: sevBucket(b)?.dismissed || 0 }" :title="`已忽略 ${sevBucket(b)?.dismissed || 0}`">{{ (sevBucket(b)?.dismissed || 0) > 0 ? sevBucket(b)?.dismissed : '' }}</div>
              <div class="seg seg-open"      :style="{ flex: sevBucket(b)?.open || 0 }"      :title="`待处理 ${sevBucket(b)?.open || 0}`">{{ (sevBucket(b)?.open || 0) > 0 ? sevBucket(b)?.open : '' }}</div>
              <div class="seg seg-superseded" :style="{ flex: sevBucket(b)?.superseded || 0 }" :title="`已替代 ${sevBucket(b)?.superseded || 0}`">{{ (sevBucket(b)?.superseded || 0) > 0 ? sevBucket(b)?.superseded : '' }}</div>
            </div>
          </div>
        </div>
        <div v-else class="empty">暂无建议数据</div>
        <!-- 详情表 (4 列紧凑: 总 / 采纳 / 忽略 / 待处理; 替代超10条也看不常见, 折叠到 tooltip) -->
        <!-- (详情表删除 — 上方行级 bar 已表达全部字段: 总数 / 采纳数 / 忽略数 / 待处理数 / 整体采纳率 / segment 内数字) -->
      </div>
    </div>

    <!-- 被忽略的规则 (按 reason 汇总, 来自 pr-agent /dismissals/by-rule) -->
    <div v-if="overview" class="card">
      <div class="card-hd">
        <h2>✗ 近期被忽略的规则</h2>
        <span class="cnt">{{ dismissalsByRule.length }} 条 · {{ totalDismissals }} 次忽略</span>
      </div>
      <div v-if="dismissalsByRule.length === 0" class="empty">近 {{ sinceLabel }} 无人忽略建议</div>
      <table v-else class="tbl reason-tbl">
        <thead>
          <tr>
            <th><button class="sort-btn" @click="setDismissSort('key')">规则 <span class="sort-marker">{{ dismissSortKey === 'key' ? (dismissSortAsc ? '▲' : '▼') : '⇅' }}</span></button></th>
            <th class="r"><button class="sort-btn" @click="setDismissSort('count')">次数 <span class="sort-marker">{{ dismissSortKey === 'count' ? (dismissSortAsc ? '▲' : '▼') : '⇅' }}</span></button></th>
            <th>原因分布</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in dismissalsSorted.slice(0, 10)" :key="r.rule_key">
            <td class="mono cell-k" :title="r.rule_key">{{ r.rule_key }}</td>
            <td class="r mono cell-n" :class="{ 'cell-n-hot': r.dismissal_count >= 5 }">{{ r.dismissal_count }}</td>
            <td class="cell-r">
              <div class="reason-wrap">
                <template v-for="(rv, i) in r.reasons" :key="rv.reason + i">
                  <!-- 多数 < 6 全展开; >= 6 时前 4 直接展示, 余下进 +N 折叠 (避免单行表行高过高) -->
                  <span v-if="r.reasons.length < 6 || i < 4" class="reason-pill" :title="rv.reason">
                    {{ rv.reason }}<b>&times;{{ rv.count }}</b>
                  </span>
                </template>
                <details v-if="r.reasons.length >= 6" class="reason-more-wrap">
                  <summary class="reason-more">+{{ r.reasons.length - 4 }}</summary>
                  <div class="reason-extra">
                    <span v-for="(rv, i) in r.reasons.slice(4)" :key="'x' + rv.reason + i" class="reason-pill" :title="rv.reason">
                      {{ rv.reason }}<b>&times;{{ rv.count }}</b>
                    </span>
                  </div>
                </details>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
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
            <div class="rule-n mono" :title="`规则被引用 ${r.cited_count ?? 0} 次`">{{ r.cited_count ?? 0 }}<span class="unit"> 次</span></div>
            <div class="rule-ap mono" :class="ruleAdoptedClass(r)" :title="ruleAdoptedTitle(r)">{{ ruleAdoptedLabel(r) }}</div>
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
            <th>MR</th><th>作者</th><th>源 → 目标</th><th>建议</th><th>状态</th><th>开启</th><th>最后活动</th><th class="r">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in mrs" :key="`${m.project_id}/${m.mr_id}`"
              :class="{ merged: m.state === 'merged' || m.state === 'closed', 'run-failed': m.last_run?.status === 'failed' }">
            <td>
              <div class="mr-t">
                <a v-if="m.url" :href="m.url" target="_blank" rel="noopener" class="mr-link">!{{ m.mr_id }}</a>
                <span v-else class="mr-link">!{{ m.mr_id }}</span>
                <div class="mr-title" :title="m.title">{{ m.title || '—' }}</div>
              </div>
            </td>
            <td>{{ m.author || '—' }}</td>
            <td class="mono branches">{{ m.source_branch || '—' }} → {{ m.target_branch || '—' }}</td>
            <td class="mr-sug-cell">
              <div v-if="m.suggestion_counts" class="mr-sug">
                <div class="ms-total">
                  <span class="ms-n">{{ m.suggestion_counts.total ?? 0 }}</span>
                  <span class="ms-k">建议</span>
                </div>
                <div class="ms-line">
                  <span class="ms-ok" :title="'已采纳 ' + ((m.suggestion_counts && m.suggestion_counts.applied) || 0)">✓ {{ m.suggestion_counts.applied ?? 0 }}</span>
                  <span class="ms-dismissed" :title="'已忽略 ' + ((m.suggestion_counts && m.suggestion_counts.dismissed) || 0)">✗ {{ m.suggestion_counts.dismissed ?? 0 }}</span>
                  <span class="ms-open" :title="'待处理 ' + ((m.suggestion_counts && m.suggestion_counts.open) || 0)">⏵ {{ m.suggestion_counts.open ?? 0 }}</span>
                </div>
              </div>
              <span v-else class="ms-empty">—</span>
            </td>
            <td>
              <span class="badge" :class="stateCls(m.state)">{{ stateLabel(m.state) }}</span>
            </td>
            <td class="mono">{{ fmtIso(m.opened_at) }}</td>
            <td class="mono">{{ fmtIso(m.last_seen_at) }}</td>
            <td class="r">
              <button class="link-btn"
                      :class="{ 'link-btn-err': m.last_run?.status === 'failed' }"
                      :title="mrLastRunTitle(m)"
                      @click="openTimeline(m)"
                      :disabled="tlLoading === `${m.project_id}/${m.mr_id}`">
                <span v-if="m.last_run?.status === 'failed'" class="btn-warn">⚠</span>查看时间线
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 时间线抽屉 -->
    <el-drawer v-model="tlOpen" :title="tlTitle" size="640px" direction="rtl">
      <template v-if="timeline">
        <!-- MR 健康摘要: 应用率 + 4 stat mini -->
        <div class="dt-health">
          <div v-if="timeline.suggestions?.length" class="dt-h-bar" :title="tlHealthTitle">
            <div class="dt-h-seg dt-h-applied" :style="{ flex: tlApplied }" :title="tlSegTitle('已采纳', tlApplied)"></div>
            <div class="dt-h-seg dt-h-dismissed" :style="{ flex: tlDismissed }" :title="tlSegTitle('已忽略', tlDismissed)"></div>
            <div class="dt-h-seg dt-h-open" :style="{ flex: tlOpenCount }" :title="tlSegTitle('待处理', tlOpenCount)"></div>
            <div class="dt-h-seg dt-h-superseded" :style="{ flex: tlSuperseded }" :title="tlSegTitle('已替代', tlSuperseded)"></div>
          </div>
          <div class="dt-h-mini">
            <span class="dt-h-stat"><b>{{ tlTotal }}</b><span>建议</span></span>
            <span class="dt-h-stat ok"><b>{{ tlApplied }}</b><span>采纳</span></span>
            <span class="dt-h-stat mute"><b>{{ tlDismissed }}</b><span>忽略</span></span>
            <span class="dt-h-stat" :class="{ 'dt-h-warn': tlOpenCount > 0 }"><b>{{ tlOpenCount }}</b><span>待处理</span></span>
            <span v-if="timeline.runs?.length" class="dt-h-stat last-run" :class="{ bad: tlLastRun?.status === 'failed' }">
              <span class="run-dot"></span>{{ tlLastRun?.command }} · {{ tlLastRun?.status }}
            </span>
          </div>
        </div>

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
          <div v-for="(s, idx) in timeline.suggestions" :key="s.id ?? idx" class="sug-row" :class="sugRowCls(s.state || 'open')">
            <div class="sug-l">
              <span class="badge sm" :class="sugCls(s.state)">{{ sugLabel(s.state) }}</span>
              <span v-if="s.severity" class="badge sm sev-pill" :class="sevCls(s.severity)"
                    :title="sevTitleHint(s)">
                {{ sevIcon(s.severity) }} {{ sevLabel(s.severity) }}
              </span>
            </div>
            <div class="sug-body">
              <div class="sug-loc mono">{{ s.file || '?' }}:{{ s.line ?? '?' }}</div>
              <div class="sug-sum">{{ s.one_sentence_summary || s.label || '—' }}</div>
              <div v-if="s.rule_keys?.length" class="sug-rules">
                <code v-for="k in s.rule_keys" :key="k">{{ k }}</code>
              </div>
              <div v-if="s.state === 'dismissed' && s.dismissed_reason" class="sug-reason">
                <span class="sug-reason-k">忽略原因</span>
                <span v-if="isCommitSha(s.dismissed_reason)" class="sug-reason-auto" :title="`原始 reason: ${s.dismissed_reason}`">🤖 自动忽略 (因 commit 合并)</span>
                <span v-else>{{ s.dismissed_reason }}</span>
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
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import {
  getHealth, getOverview, getRules, getAuthors, listMrs, getTimeline, getSeverity, getDismissalsByRule,
  type OverviewResp, type RuleStat, type AuthorStat, type MrRow, type MrListResp, type TimelineResp, type HealthResp,
  type SeverityBucket, type DismissalsByRuleItem,
} from '@/api/pragent';
import { fmtIso, fmtPct, fmtMs } from '@/utils/format';

const loading = ref(false);
const loadError = ref('');
const health = ref<HealthResp | null>(null);
const overview = ref<OverviewResp | null>(null);
const rules = ref<RuleStat[]>([]);
const authors = ref<AuthorStat[]>([]);
const mrs = ref<MrRow[]>([]);
const failedMrCount = ref(0);
const bannerOpen = ref(false);

// 失败 MR 子集, banner 展开时用 (取每条 last_run.status==='failed')
const failedMrs = computed(() =>
  mrs.value.filter(m => (m.last_run as any)?.status === 'failed')
);

// 最近一次评审失败的 MR 数 (顶部 banner 用)
const severities = ref<SeverityBucket[]>([]);
const dismissalsByRule = ref<DismissalsByRuleItem[]>([]);

// dismiss 卡: 列点击排序
const dismissSortKey = ref<'key' | 'count'>('count');
const dismissSortAsc = ref(false);
function setDismissSort(k: 'key' | 'count') {
  if (dismissSortKey.value === k) dismissSortAsc.value = !dismissSortAsc.value;
  else { dismissSortKey.value = k; dismissSortAsc.value = k === 'key'; }
}
const dismissalsSorted = computed(() => {
  const arr = [...dismissalsByRule.value];
  const dir = dismissSortAsc.value ? 1 : -1;
  if (dismissSortKey.value === 'key') {
    arr.sort((a, b) => dir * (a.rule_key || '').localeCompare(b.rule_key || ''));
  } else {
    arr.sort((a, b) => dir * ((b.dismissal_count || 0) - (a.dismissal_count || 0)));
  }
  return arr;
});
// 总忽略次数 (按 reason 汇总)
const totalDismissals = computed(() => dismissalsByRule.value.reduce((s, r) => s + (r.dismissal_count || 0), 0));
const sinceLabel = computed(() => windowSel.value === 'all' ? '全部时间' : windowSel.value === '7d' ? '7 天' : '30 天');

const windowSel = ref<'all' | '7d' | '30d' | 'custom'>('all');

function sinceFor(sel: string, customDaysVal?: number): string | undefined {
  if (sel === 'all') return undefined;
  let days = 7;
  if (sel === '7d') days = 7;
  else if (sel === '30d') days = 30;
  else if (sel === 'custom') days = Math.max(1, Math.min(365, customDaysVal || 30));
  const d = new Date(Date.now() - days * 86400_000);
  return d.toISOString();
}
const customDays = ref(14);

// 上次刷新时间 (相对显示)
const lastUpdated = ref<Date | null>(null);
const nowTick = ref(0);
const lastUpdatedRel = computed(() => {
  // 读 nowTick.value 让 interval tick 触发本 computed 重算 + template 重渲染
  void nowTick.value;
  if (!lastUpdated.value) return '尚未加载';
  const sec = Math.round((Date.now() - lastUpdated.value.getTime()) / 1000);
  if (sec < 60) return `${sec} 秒前`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`;
  return `${Math.floor(sec / 86400)} 天前`;
});
const lastUpdatedLabel = computed(() => lastUpdated.value ? lastUpdated.value.toLocaleString('zh-CN') : '—');
// 每 30s 刷新相对时间显示 — 显式 bump nowTick 触发 lastUpdatedRel 重算 + template 重渲染
let _relTimer: number | null = null;
onMounted(() => { _relTimer = window.setInterval(() => { nowTick.value++; }, 30000); });
onUnmounted(() => { if (_relTimer) window.clearInterval(_relTimer); });

async function reload() {
  loading.value = true;
  loadError.value = '';
  try {
    const since = sinceFor(windowSel.value, customDays.value);
    health.value = await getHealth();
    if (!health.value.configured) {
      overview.value = null; rules.value = []; authors.value = []; mrs.value = []; severities.value = [];
      dismissalsByRule.value = [];
      failedMrCount.value = 0;
      return;
    }
    // severity 失败不应阻断其他 4 个, 单独 catch
    let sev: SeverityBucket[] = [];
    try { sev = await getSeverity(since); } catch (e: any) { /* 忽略: 单独显示在严重等级卡 */ }
    const [ov, rl, au, mr, dbr] = await Promise.all([
      getOverview(since),
      getRules(since),
      getAuthors(since),
      listMrs({ limit: 50, since }),
      getDismissalsByRule(since).catch(() => [] as DismissalsByRuleItem[]),  // 单独失败不阻塞其他卡
    ]);
    overview.value = ov;
    rules.value = rl;
    authors.value = au;
    // mr 是 { items, failed_mr_count, total } — 后端已给每条 MR 拍平 last_run
    const mrResp = mr as unknown as MrListResp;
    mrs.value = mrResp.items || [];
    failedMrCount.value = mrResp.failed_mr_count || 0;
    severities.value = sev;
    dismissalsByRule.value = dbr || [];
  } catch (e: any) {
    loadError.value = (e?.response?.data?.detail || e?.message || '未知错误');
    ElMessage.error('代码检视加载失败: ' + loadError.value);
  } finally {
    loading.value = false;
    lastUpdated.value = new Date();
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
// 采纳率: 无引用时无意义, 不显示 100% 误导
function ruleAdoptedLabel(r: RuleStat): string {
  const n = r.cited_count ?? 0;
  if (n === 0) return '—';     // 引用 0 次 → 没法算采纳率
  return fmtPct(r.adoption_rate);
}
function ruleAdoptedClass(r: RuleStat): string {
  const n = r.cited_count ?? 0;
  if (n === 0) return 'muted';
  const ad = r.adoption_rate ?? 0;
  if (ad >= 0.7) return 'high';
  if (ad < 0.3) return 'low';
  return 'mid';
}
function ruleAdoptedTitle(r: RuleStat): string {
  const n = r.cited_count ?? 0;
  if (n === 0) return '未被引用, 无采纳率';
  return `引用 ${n} 次, 采纳率 ${fmtPct(r.adoption_rate)}`;
}

// 严重等级 nested bar 用: 总建议数 (applied+dismissed+open+superseded), 整条 flex 比例
const totalSuggestions = computed(() => severityBuckets.value.reduce((s, b) =>
  s + (b.applied || 0) + (b.dismissed || 0) + (b.open || 0) + (b.superseded || 0), 0));
// 严重等级 整体采纳率 (legend 右侧展示)
const severityAdoption = computed(() => {
  const t = severityBuckets.value.reduce((s, b) => s + (b.applied || 0) + (b.dismissed || 0) + (b.open || 0) + (b.superseded || 0), 0);
  const a = severityBuckets.value.reduce((s, b) => s + (b.applied || 0), 0);
  return t > 0 ? a / t : 0;
});

// ===== 严重等级 =====
// 优先从 overview.severity_breakdown 读 (overview inline), 失败 / 缺失再 fallback 到独立 severities 请求
const severityBuckets = computed<SeverityBucket[]>(() => {
  const inline = overview.value?.severity_breakdown;
  if (inline && inline.length) return inline;
  return severities.value;
});
// bar 渐变 stop 位置: p1/p2/p3 是 4 段分割线 (单位 %), 0/100 是两端

// severity 来源 (rule_file / pattern / importance / default) → 中文
// 40-hex git commit SHA 检测 (pr-agent auto-apply-suggestion 触发 dismiss 时 note 写成 SHA)
function isCommitSha(s: string): boolean {
  return /^commit [0-9a-f]{7,40}$/i.test(s) || /^[0-9a-f]{40}$/i.test(s);
}

function sevSrcLabel(src?: string): string {
  return src === 'rule_file' ? '规则文件'
    : src === 'pattern' ? '配置 pattern'
    : src === 'importance' ? '重要性阈值'
    : '';
}
function sevBucket(name: string): SeverityBucket | undefined {
  return severityBuckets.value.find(b => b.severity === name);
}
const SEV_ORDER = ['critical', 'high', 'medium', 'low'] as const;
const SEV_META: Record<string, { icon: string; label: string; cls: string }> = {
  critical: { icon: '\u25cf', label: '严重', cls: 'sev-c1' },
  high:     { icon: '\u25cf', label: '高',   cls: 'sev-c2' },
  medium:   { icon: '\u25cf', label: '中',   cls: 'sev-c3' },
  low:      { icon: '\u25cf', label: '低',   cls: 'sev-c4' },
};
function sevLabel(s: string): string { return SEV_META[s]?.label || s; }
function sevIcon(s: string): string { return SEV_META[s]?.icon || '⚪'; }
function sevCls(s: string): string { return SEV_META[s]?.cls || 'sev-c4'; }

function sugRowCls(state: string): string { return 's-' + (state || 'open'); }
function sevTitleHint(s: any): string {
  const base = '严重等级 ' + sevLabel(s.severity);
  return s.severity_source ? base + ' · 来源: ' + sevSrcLabel(s.severity_source) : base;
}
function tlSegTitle(label: string, n: any): string { return label + ' ' + Number(n || 0); }


// 状态色
function stateLabel(s?: string): string {
  return s === 'opened' ? '开放'
    : s === 'merged' ? '已合并'
    : s === 'closed' ? '已关闭'
    : s === 'updated' ? '更新' : (s || '—');
}
function stateCls(s?: string): string {
  return s === 'merged' ? 'b-ok'
    : s === 'opened' ? 'b-info-strong'   // 蓝色明显态
    : s === 'closed' ? 'b-err-soft'      // 淡红 (10% 透明度)
    : s === 'updated' ? 'b-progress'     // 进行中: 蓝绿
    : 'b-mute';
}
function runCls(s: string): string {
  return s === 'success' ? 'b-ok' : s === 'failed' ? 'b-err' : s === 'empty' ? 'b-mute' : 'b-info';
}
// MR 最近一次评审失败的简短原因 (查看时间线按钮 title 用)
function mrLastRunTitle(m: MrRow): string {
  const lr = m.last_run;
  if (!lr || lr.status !== 'failed') return '查看时间线';
  const err = (lr.error || '').split('\n')[0].slice(0, 120) || '评审失败';
  return `最近一次评审失败: ${err}`;
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

// 抽屉 MR 健康摘要 mini stat
const tlApplied = computed(() => (timeline.value?.suggestions || []).filter(s => s.state === 'applied').length);
const tlDismissed = computed(() => (timeline.value?.suggestions || []).filter(s => s.state === 'dismissed').length);
const tlOpenCount = computed(() => (timeline.value?.suggestions || []).filter(s => s.state === 'open').length);
const tlSuperseded = computed(() => (timeline.value?.suggestions || []).filter(s => s.state === 'superseded').length);
const tlTotal = computed(() => (timeline.value?.suggestions || []).length);
const tlAdoptionRate = computed(() => tlTotal.value > 0 ? Math.round(tlApplied.value / tlTotal.value * 100) + '%' : '—');
const tlLastRun = computed(() => (timeline.value?.runs || [])[0]);
const tlHealthTitle = computed(() => '采纳率 ' + tlAdoptionRate.value + ' / ' + tlApplied.value + '/' + tlTotal.value);
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

// 点 banner → 滚到 MR 列表 (失败行已用 .run-failed 红框高亮)
function scrollToMrTable() {
  const el = document.querySelector('.mr-tbl');
  if (el) (el as HTMLElement).scrollIntoView({ behavior: 'smooth', block: 'start' });
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
.win-custom { background: var(--surface); border: 1px solid var(--border); color: var(--ink-900); padding: 6px 8px; border-radius: 8px; font-size: 12.5px; font-family: var(--font-mono); width: 70px; }
.last-updated { font-size: 11.5px; color: var(--ink-500); padding: 6px 0; white-space: nowrap; }
.spinning { display: inline-block; animation: spin 0.8s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.sort-btn { background: transparent; border: none; padding: 0; font: inherit; color: inherit; cursor: pointer; display: inline-flex; align-items: center; gap: 4px; }
.sort-btn:hover { color: var(--ink-900); }
.sort-marker { font-size: 10px; opacity: 0.6; }



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

/* 评审失败顶部 banner: 醒目但不刺眼, 跟 .warn 同级, 实心 (可点跳转) */
.banner {
  padding: 0;
  border-radius: var(--radius-card);
  font-size: 13px;
  border: 1px solid;
  user-select: none;
  transition: filter 0.15s ease;
  overflow: hidden;
}
.banner-hd {
  display: flex; align-items: center; gap: 12px;
  width: 100%;
  background: transparent;
  border: none;
  padding: 12px 18px;
  font: inherit; color: inherit;
  cursor: pointer;
  text-align: left;
}
.banner-hd:hover { filter: brightness(0.97); }
.banner .b-icon { font-size: 16px; flex-shrink: 0; }
.banner .b-text { flex: 1; }
.banner .b-text b { font-size: 15px; font-weight: 800; }
.banner .b-hint { font-size: 11.5px; opacity: 0.7; }
.banner-err {
  background: color-mix(in srgb, var(--err) 10%, var(--surface-soft));
  border-color: color-mix(in srgb, var(--err) 45%, var(--border));
  color: color-mix(in srgb, var(--err) 75%, var(--ink-900));
}
.banner-err .b-icon { color: var(--err); }
.failed-mr-list {
  padding: 8px 18px 12px;
  border-top: 1px solid color-mix(in srgb, var(--err) 25%, var(--border));
}
.failed-mr-list .tbl { margin-top: 8px; }
.failed-mr-list th { font-size: 11px; }
.failed-mr-list td { padding: 6px 8px; font-size: 12px; }
.failed-mr-list .err-cell { color: var(--err); max-width: 480px; }
.failed-mr-list .err-text {
  display: inline-block;
  font-family: var(--font-mono); font-size: 11.5px; line-height: 1.5;
  color: color-mix(in srgb, var(--err) 85%, var(--ink-900));
  word-break: break-word; white-space: pre-wrap;
}
/* 上次命令: 失败语境用 err 淡色, 浅深主题都清晰 */
.failed-mr-list .cmd-tag-s {
  display: inline-block;
  background: color-mix(in srgb, var(--err) 14%, transparent);
  color: color-mix(in srgb, var(--err) 80%, var(--ink-900));
  border: 1px solid color-mix(in srgb, var(--err) 30%, transparent);
  padding: 1px 8px; border-radius: 4px; font-size: 10.5px; font-family: var(--font-mono);
}
.banner-foot { padding-top: 8px; display: flex; justify-content: flex-end; }

/* 概览卡片 */
.stats { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
@media (max-width: 1200px) { .stats { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 700px)  { .stats { grid-template-columns: repeat(2, 1fr); } }
.stat {
  background: var(--surface-soft); backdrop-filter: blur(8px);
  border: 1px solid var(--border); border-radius: var(--radius-card);
  padding: 14px 18px; box-shadow: var(--shadow-sm);
  display: flex; flex-direction: column; gap: 4px;
}
.stat .num { font-size: 22px; font-weight: 800; color: var(--ink-900); font-family: var(--font-mono); letter-spacing: -0.3px; }
.stat .lbl { font-size: 11.5px; color: var(--ink-500); font-weight: 600; }
.stat .sub { font-size: 11px; color: var(--ink-500); font-family: var(--font-mono); }
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

/* 严重等级告警 stat 卡 (.alert 通用, .hot 仅当 dismissed > 0 边缘提一档)
   色板: critical 用主题 --err 弱化, hot 时换成 --err 强色; 整体不刺眼 */
.alert { border-color: var(--border); }
.alert .num { color: var(--ink-900); }
.alert .num.zero { opacity: 0.45; }   /* dismissed=0 时数字淡化, 不当告警 */
.alert.hot { border-color: color-mix(in srgb, var(--err) 35%, var(--border)); background: color-mix(in srgb, var(--err) 4%, var(--surface-soft)); }
.alert.hot .num { color: var(--err); }

/* 严重等级分布卡 */
.sev-card { margin-bottom: 16px; }
.sev-body { padding: 4px 14px 14px; display: flex; flex-direction: column; gap: 12px; }
/* sev-card 标题行: 标题 / 桶数 / 内联 legend / 整体采纳率, 都同一 row,
   让 legend 跟着 header 走, 不再占独立行 */
.sev-card-hd { flex-wrap: wrap; row-gap: 6px; column-gap: 12px; }
.sev-head-count { color: var(--ink-500); font-family: var(--font-mono); font-size: 11.5px; }
.sev-head-legend { display: inline-flex; align-items: center; gap: 10px; margin-left: 8px; padding-left: 12px; border-left: 1px solid var(--border); font-size: 11px; color: var(--ink-500); flex-wrap: wrap; }
.sev-legend-item { display: inline-flex; align-items: center; gap: 4px; }
.legend-swatch { display: inline-block; width: 8px; height: 8px; border-radius: 2px; }
/* swatch 色调跟 bar segment 严格一致, 但更薄 */
.legend-swatch.seg-applied   { background: color-mix(in srgb, var(--ok)      35%, transparent); }
.legend-swatch.seg-dismissed { background: color-mix(in srgb, var(--ink-500) 30%, transparent); }
.legend-swatch.seg-open      { background: color-mix(in srgb, var(--warn)    35%, transparent); }
.legend-swatch.seg-superseded{ background: color-mix(in srgb, var(--primary) 25%, transparent); }
.sev-head-summary { margin-left: auto; color: var(--ink-700); font-weight: 600; font-size: 12.5px; }

/* 严重等级行级列表: 每个 severity 一行, 行内堆叠 state segment (整行宽度 = 100%) */
.sev-rows-list { display: flex; flex-direction: column; gap: 10px; margin-bottom: 14px; }
.sev-row-line { display: flex; flex-direction: column; gap: 5px; }
.sev-row-hd { display: flex; align-items: center; justify-content: space-between; font-size: 12.5px; }
.sev-row-name { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-900); font-weight: 600; }
.sev-row-meta { display: inline-flex; align-items: baseline; gap: 10px; }
.sev-row-total { font-size: 11.5px; color: var(--ink-500); font-family: var(--font-mono); }
.sev-row-rate { font-size: 12.5px; color: var(--ok); font-family: var(--font-mono); font-weight: 700; }

/* bar 行: 全宽, 堆 state segment */
.sev-row-bar {
  display: flex;
  width: 100%;
  height: 22px;
  border-radius: 4px;
  overflow: hidden;
  background: var(--surface-sunken);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ink-900) 6%, transparent);
}
.seg {
  height: 100%;
  min-width: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 10.5px; font-weight: 700;
  color: rgba(255,255,255,0.92);
  font-family: var(--font-mono);
  border-right: 1px solid rgba(255,255,255,0.45);
  transition: opacity 0.15s ease;
}
.seg:last-child { border-right: none; }
.seg:hover { opacity: 0.78; }
.seg-applied   { background: color-mix(in srgb, var(--ok)      35%, transparent); }
.seg-dismissed { background: color-mix(in srgb, var(--ink-500) 30%, transparent); }
.seg-open      { background: color-mix(in srgb, var(--warn)    40%, transparent); }
.seg-superseded{ background: color-mix(in srgb, var(--primary) 22%, transparent); }

/* 行级 dot (legend 重用) */
.sev-legend-dot { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; display: inline-block; }
.sev-legend-dot.sev-c1 { background: var(--err); }
.sev-legend-dot.sev-c2 { background: var(--warn); }
.sev-legend-dot.sev-c3 { background: var(--primary); }
.sev-legend-dot.sev-c4 { background: var(--ink-500); }
.sev-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  background: var(--surface-sunken);
  color: var(--ink-700);
}
.sev-badge::before {
  content: '';
  display: inline-block;
  width: 7px; height: 7px;
  border-radius: 50%;
  background: currentColor;
}
/* 主题化 — 用 color-mix 跟 .b-ok/.b-info/.b-warn/.b-err 同款 */
.sev-badge.sev-c1 { background: color-mix(in srgb, var(--err)     13%, transparent); color: var(--err); }
.sev-badge.sev-c2 { background: color-mix(in srgb, var(--warn)    18%, transparent); color: color-mix(in srgb, var(--warn) 80%, var(--ink-900)); }
.sev-badge.sev-c3 { background: color-mix(in srgb, var(--primary) 13%, transparent); color: var(--primary); }
.sev-badge.sev-c4 { background: color-mix(in srgb, var(--ink-500) 13%, transparent); color: var(--ink-700); }

/* 时间线抽屉 severity pill (复用 sev-badge 配色, 透明度稍强以便在浅色卡上突出) */
.sev-pill.sev-c1 { background: color-mix(in srgb, var(--err)     16%, transparent); color: var(--err); }
.sev-pill.sev-c2 { background: color-mix(in srgb, var(--warn)    22%, transparent); color: color-mix(in srgb, var(--warn) 80%, var(--ink-900)); }
.sev-pill.sev-c3 { background: color-mix(in srgb, var(--primary) 16%, transparent); color: var(--primary); }
.sev-pill.sev-c4 { background: color-mix(in srgb, var(--ink-500) 16%, transparent); color: var(--ink-700); }

/* 规则柱图 */
.rules { display: flex; flex-direction: column; gap: 6px; }
.rule-row { display: grid; grid-template-columns: 220px 1fr 56px 64px; gap: 10px; align-items: center; font-size: 12px; }
.rule-k { font-family: var(--font-mono); font-size: 11.5px; color: var(--ink-700); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rule-bar { height: 6px; background: var(--surface-sunken); border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--primary-grad); border-radius: 4px; transition: width 0.3s ease; }
.rule-n { color: var(--ink-700); text-align: right; font-size: 11.5px; }
.rule-n .unit { color: var(--ink-500); font-size: 10px; margin-left: 1px; }
.rule-ap { color: var(--ink-700); text-align: right; font-size: 11.5px; }
.rule-ap.muted { color: var(--ink-500); font-weight: 400; }
.rule-ap.high  { color: var(--ok); font-weight: 600; }
.rule-ap.mid   { color: var(--ink-900); font-weight: 600; }
.rule-ap.low   { color: var(--warn); font-weight: 600; }

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
.mr-tbl tr.merged { opacity: 0.7; }   /* merged + closed 共用置灰 */

/* 建议列: 紧凑两行 (主: 建议总数 / 副: ✓采纳 ✗忽略 ⏵待处理) */
.mr-sug-cell { vertical-align: middle; min-width: 120px; }
.mr-sug { display: flex; flex-direction: column; gap: 2px; line-height: 1.25; }
.ms-total { display: flex; align-items: baseline; gap: 4px; }
.ms-n { font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--ink-900); }
.ms-k { font-size: 10.5px; color: var(--ink-500); }
.ms-line { display: flex; gap: 8px; font-size: 10.5px; font-family: var(--font-mono); }
.ms-ok       { color: var(--ok); }   /* 采纳 — 绿 */
.ms-dismissed{ color: var(--ink-500); }  /* 忽略 — 中性灰 */
.ms-open     { color: var(--primary); }  /* 待处理 — 蓝 */
.ms-empty    { color: var(--ink-500); font-size: 12px; }

.link-btn {
  background: transparent; border: 1px solid var(--border); color: var(--primary);
  padding: 3px 10px; border-radius: 6px; font-size: 11.5px; font-family: inherit; cursor: pointer;
}
.link-btn:hover { background: var(--primary-grad-soft); border-color: transparent; }
.link-btn:disabled { opacity: 0.5; cursor: not-allowed; }
/* 评审失败: 按钮变红 + 醒目 ⚠ 标, 点进去看时间线详情 */
.link-btn.link-btn-err {
  color: var(--err);
  border-color: color-mix(in srgb, var(--err) 50%, transparent);
  background: color-mix(in srgb, var(--err) 8%, transparent);
  font-weight: 600;
}
.link-btn.link-btn-err:hover {
  background: color-mix(in srgb, var(--err) 16%, transparent);
  border-color: color-mix(in srgb, var(--err) 70%, transparent);
}
.link-btn .btn-warn { margin-right: 3px; font-size: 12px; }

/* MR 行评审失败: 左侧红边 + 极淡红底, 不夺主但一眼能看见 */
.mr-tbl tbody tr.run-failed {
  box-shadow: inset 3px 0 0 0 var(--err);
  background: color-mix(in srgb, var(--err) 4%, transparent);
}
.mr-tbl tbody tr.run-failed:hover {
  background: color-mix(in srgb, var(--err) 9%, var(--surface-sunken));
}
.mr-tbl tbody tr.run-failed .mr-link { color: var(--err); }

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
.b-info-strong { background: color-mix(in srgb, var(--primary) 22%, white); color: var(--primary); border: 1px solid color-mix(in srgb, var(--primary) 35%, transparent); }
.b-warn { background: color-mix(in srgb, var(--warn) 18%, transparent); color: var(--warn); }
.b-err { background: color-mix(in srgb, var(--err) 18%, transparent); color: var(--err); }
.b-progress { background: color-mix(in srgb, #F59E0B 22%, transparent); color: #B45309; border: 1px solid color-mix(in srgb, #F59E0B 35%, transparent); }

/* 深色主题覆盖: 亮橙文字 + 深橙底 */
:root[data-theme="dark"] .b-progress,
[data-theme="dark"] .b-progress { background: color-mix(in srgb, #FBBF24 22%, transparent); color: #FBBF24; border-color: color-mix(in srgb, #FBBF24 40%, transparent); }
/* 淡红: closed MR 用, 比 .b-err 弱, 不刺眼 */
.b-err-soft { background: color-mix(in srgb, var(--err) 10%, transparent); color: color-mix(in srgb, var(--err) 80%, var(--ink-700)); }
.b-mute { background: var(--surface-sunken); color: var(--ink-500); }

/* drawer 样式复用 KnowledgeManage 的 .dt-* / .dt-pre 等 */
.dt { display: flex; flex-direction: column; gap: 8px; }
.dt-row { display: grid; grid-template-columns: 80px 1fr; gap: 10px; font-size: 12.5px; }
.dt-k { color: var(--ink-500); font-size: 11.5px; }
.dt-v { color: var(--ink-900); }
.dt-v.mono { font-family: var(--font-mono); font-size: 11.5px; }
.dt-sep { font-size: 12.5px; font-weight: 700; color: var(--ink-700); margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--border); }

/* 抽屉 MR 健康摘要 */
.dt-health { background: var(--surface-sunken); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; display: flex; flex-direction: column; gap: 8px; }
.dt-h-bar { display: flex; height: 10px; border-radius: 4px; overflow: hidden; background: var(--surface); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ink-900) 6%, transparent); }
.dt-h-seg { min-width: 0; }
.dt-h-applied    { background: color-mix(in srgb, var(--ok)      55%, transparent); }
.dt-h-dismissed  { background: color-mix(in srgb, var(--ink-500) 50%, transparent); }
.dt-h-open       { background: color-mix(in srgb, var(--warn)    60%, transparent); }
.dt-h-superseded { background: color-mix(in srgb, var(--primary) 30%, transparent); }
.dt-h-mini { display: flex; gap: 14px; flex-wrap: wrap; font-size: 11.5px; }
.dt-h-stat { display: inline-flex; align-items: baseline; gap: 4px; color: var(--ink-700); }
.dt-h-stat b { font-family: var(--font-mono); font-size: 13px; font-weight: 700; color: var(--ink-900); }
.dt-h-stat.ok   b { color: var(--ok); }
.dt-h-stat.mute b { color: var(--ink-500); }
.dt-h-stat.dt-h-warn b { color: var(--warn); }
.dt-h-stat.last-run { font-size: 11px; }
.dt-h-stat.last-run .run-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ok); display: inline-block; margin-right: 4px; }
.dt-h-stat.last-run.bad .run-dot { background: var(--err); }

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
.sug-reason { font-size: 11px; color: var(--ink-700); line-height: 1.5; word-break: break-word; margin-top: 2px; }
.sug-reason-k { color: var(--ink-500); margin-right: 6px; }
.sug-reason-auto { color: var(--primary); font-weight: 600; }   /* pr-agent auto-apply-commit 触发的 dismiss, 替人类决策时不显示 SHA, 显示成友好占位 */

/* 被忽略规则汇总卡 (按 reason 分布) */
.reason-tbl .cell-k { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.reason-tbl .cell-n { font-weight: 600; }
.reason-tbl .cell-n-hot { color: var(--warn); }
.reason-tbl .cell-r { vertical-align: top; }
.reason-wrap { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; max-width: 340px; }
.reason-pill {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; line-height: 1.5;
  padding: 2px 8px; border-radius: 10px;
  background: var(--surface-sunken); color: var(--ink-700);
  border: 1px solid var(--border);
  max-width: 100%; overflow-wrap: anywhere; white-space: normal;
}
.reason-pill b { color: var(--ink-500); font-weight: 500; }
.reason-more-wrap { display: inline-flex; }
.reason-more-wrap > summary {
  list-style: none; cursor: pointer; user-select: none;
  font-size: 11px; color: var(--ink-500);
  padding: 2px 8px; border-radius: 10px;
  background: var(--surface); border: 1px dashed var(--border);
  transition: color .12s, background .12s;
}
.reason-more-wrap > summary::-webkit-details-marker { display: none; }
.reason-more-wrap > summary:hover { color: var(--primary); background: var(--surface-sunken); }
.reason-more-wrap[open] > summary { color: var(--primary); background: var(--surface-sunken); border-style: solid; }
.reason-extra {
  display: flex; gap: 4px; flex-wrap: wrap; align-items: center;
  width: 100%; margin-top: 4px;
  padding-top: 4px; border-top: 1px dashed var(--border);
}
</style>
