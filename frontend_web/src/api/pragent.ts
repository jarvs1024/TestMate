/** pr-agent telemetry 看板 API. 全部走 backend Gateway (/api/v1/pr-agent/*),
 *  前端不直接连 pr-agent 容器 (避免 token 泄漏 + 跨域).
 */
import request from '@/utils/request';

export interface OverviewMr {
  total: number;
  merged: number;
  open: number;
}
export interface OverviewSuggestion {
  total: number;
  applied: number;
  dismissed: number;
  open: number;
  adoption_rate: number;
  dismissal_rate: number;
}
export interface OverviewRun {
  total: number;
  failed: number;
  success_rate: number;
}
export interface SeverityBucket {
  severity: 'critical' | 'high' | 'medium' | 'low' | 'unknown';
  total: number;
  applied: number;
  dismissed: number;
  open: number;
  superseded: number;
  adoption_rate: number;
  dismissal_rate: number;
}

export interface OverviewResp {
  configured?: boolean;   // false = 后端没配 pr-agent base_url
  since?: string | null;
  mrs?: OverviewMr;
  suggestions?: OverviewSuggestion;
  runs?: OverviewRun;
  severity_breakdown?: SeverityBucket[];   // 7d/30d/all 共用, 自带 since 过滤
}

/** 规则命中聚合 — pr-agent 返回字段: total / applied / dismissed / open / superseded / adoption_rate
 *  兼容旧 schema (cited_count / applied_count / dismissed_count / open_count), 函数里 fallback */
export interface RuleStat {
  rule_key: string;
  total?: number;            // 规则被引用次数 (旧: cited_count)
  cited_count?: number;
  applied?: number;          // 旧: applied_count
  applied_count?: number;
  dismissed?: number;        // 旧: dismissed_count
  dismissed_count?: number;
  open?: number;             // 旧: open_count
  open_count?: number;
  superseded?: number;
  adoption_rate?: number;
}

export interface AuthorStat {
  author: string;
  mr_count?: number;
  merged_count?: number;
  suggestion_total?: number;
  suggestion_applied?: number;
  suggestion_dismissed?: number;
  adoption_rate?: number;
  runs_by_command?: Record<string, { total: number; failed: number }>;
}

export interface MrRow {
  mr_id: number;
  project_id: number;
  source_branch?: string;
  target_branch?: string;
  title?: string;
  author?: string;
  state?: string;
  opened_at?: string;
  last_seen_at?: string;
  merged_at?: string | null;
  url?: string;
  head_sha?: string | null;
  last_run?: MrRun | null;
  suggestion_counts?: SuggestionCounts | null;
}

/** MR 建议统计 — 字段来自 pr-agent /stats.suggestion_counts, 经 backend gateway 白名单透传.
 *  字段语义:
 *  - applied 已包含 adopted_implicitly (GitLab Apply + 用户 /adopt 都计入 applied)
 *  - adoption_rate = applied / total, **不要**把 adopted_implicitly 再加一次
 *    (否则 /adopt 会被重复计算; 详见 pr_agent.py whitelist)
 *  - adopted_implicitly 仅用于展示或下钻分析, 不参与采纳率
 */
export interface SuggestionCounts {
  total?: number;
  applied?: number;                  // 全部采纳数 (GitLab Apply + 用户 /adopt)
  dismissed?: number;
  open?: number;
  superseded?: number;               // 已替代 (pr-agent 增量字段)
  adopted_implicitly?: number;       // 其中通过 /adopt 手动采纳 — 仅展示用
}

/** MR 最近一次 pr-agent 评审 run, 拍平自 /mrs/{pid}/{mr_id}/stats.runs[0]. */
export interface MrRun {
  run_id?: string;
  command?: string;
  status?: 'success' | 'failed' | 'empty' | string;   // success / failed / empty
  model?: string;
  started_at?: string;
  duration_ms?: number | null;
  error?: string | null;
  suggestion_count?: number;
}

/** listMrs 响应: items + 失败 MR 计数 (顶部 banner 用). */
export interface MrListResp {
  items: MrRow[];
  failed_mr_count?: number;
  total?: number;
}

export interface SuggestionRow {
  id?: number;
  file?: string;
  line?: number;
  label?: string;
  importance?: number;
  severity?: 'critical' | 'high' | 'medium' | 'low' | 'unknown';   // 3 层解析后的桶
  severity_source?: 'rule_file' | 'pattern' | 'importance' | 'default';  // 来源
  one_sentence_summary?: string;
  state?: string;
  posted_at?: string;
  rule_keys?: string[];
  /** 用户在 /dismiss 时附带的忽略原因 (来自 pr-agent suggestions.dismissed_reason) */
  dismissed_reason?: string;
}

/** 单条 reason 计数字段, 见 /dismissals/by-rule.reasons. */
export interface DismissReasonBucket {
  reason: string;
  count: number;
}

/** 一条规则的聚合, 见 /dismissals/by-rule. */
export interface DismissalsByRuleItem {
  rule_key: string;
  dismissal_count: number;
  reasons: DismissReasonBucket[];
}

export interface RunRow {
  run_id: string;
  command: string;
  status: string;
  model?: string;
  started_at: string;
  finished_at?: string | null;
  duration_ms?: number | null;
  suggestion_count?: number;
  error?: string | null;
}

/** 时间线事件 — 来自 pr-agent /timeline.actions (gateway 透传, 无白名单).
 *  典型值:
 *  - action = "applied"           GitLab 「应用建议」按钮 (review-bot 自动, note 带 commit SHA)
 *  - action = "adopted_implicitly" 用户回复 /adopt 手动采纳 (note 带人类理由)
 *  前端 drawer 会渲染此列表为「操作记录」区; 类型先清晰化避免从 any 里猜字段.
 */
export interface ActionRow {
  action?: string;                   // 'applied' | 'adopted_implicitly' | ...
  suggestion_id?: string;
  actor?: string;
  note?: string;
  at?: string;
  [k: string]: any;
}

export interface TimelineResp {
  mr?: MrRow;
  suggestions: SuggestionRow[];
  runs: RunRow[];
  actions: ActionRow[];
}

export interface HealthResp {
  configured: boolean;
  status: 'ok' | 'warn' | 'off';
  message: string;
}

export async function getHealth(): Promise<HealthResp> {
  return (await request.get('/pr-agent/health')) as HealthResp;
}
export async function getOverview(since?: string): Promise<OverviewResp> {
  return (await request.get('/pr-agent/metrics/overview', { params: since ? { since } : {} })) as OverviewResp;
}
export async function getRules(since?: string): Promise<RuleStat[]> {
  return (await request.get('/pr-agent/metrics/rules', { params: since ? { since } : {} })) as RuleStat[];
}
export async function getAuthors(since?: string): Promise<AuthorStat[]> {
  return (await request.get('/pr-agent/metrics/authors', { params: since ? { since } : {} })) as AuthorStat[];
}
export async function listMrs(params: { limit?: number; offset?: number; project_id?: number; state?: string; since?: string } = {}): Promise<MrListResp> {
  return (await request.get('/pr-agent/mrs', { params })) as MrListResp;
}
export async function getTimeline(projectId: number, mrId: number): Promise<TimelineResp> {
  return (await request.get(`/pr-agent/mrs/${projectId}/${mrId}/timeline`)) as TimelineResp;
}
export async function getSeverity(since?: string, prUrl?: string): Promise<SeverityBucket[]> {
  const params: Record<string, string> = {};
  if (since) params.since = since;
  if (prUrl) params.pr_url = prUrl;
  return (await request.get('/pr-agent/metrics/severity', { params })) as SeverityBucket[];
}

/** 按 rule_key 聚合 dismiss 计数 + reason 分布 (来自 pr-agent /dismissals/by-rule). */
export async function getDismissalsByRule(since?: string): Promise<DismissalsByRuleItem[]> {
  return (await request.get('/pr-agent/dismissals/by-rule', { params: since ? { since } : {} })) as DismissalsByRuleItem[];
}
