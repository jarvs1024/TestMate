/** ReviewAgent telemetry 看板 API. 全部走 backend Gateway (/api/v1/review-agent/*),
 *  前端不直接连 ReviewAgent (避免 host 路径泄漏 + 跨域).
 *  字段形态对齐 pragent.ts, 让 V2 视图几乎能复用 V1 代码.
 */
import request from '@/utils/request';

export interface OverviewMr {
  total: number;
  merged: number;
  open: number;
  closed?: number;
}
export interface OverviewSuggestion {
  total: number;
  applied: number;
  dismissed: number;
  /** ReviewAgent 自带: GitLab 解决主题但未 apply/dismiss 的 (commit c080f7e) */
  resolved?: number;
  /** ReviewAgent 自带: applied + dismissed + processed (含 resolved), 采纳率分母用这个更准 */
  processed?: number;
  open: number;
  adoption_rate: number;
  /** ReviewAgent 自带: 0~100 的百分数 (adoption_rate * 100, 保留 1 位), 直显用 */
  adoption_pct?: number;
  dismissal_rate: number;
}
export interface OverviewRun {
  total: number;
  failed: number;
  success_rate: number;
  /** /summary by_status.skipped 透传 (运行成功率卡副标展示) */
  skipped?: number;
  /** /summary by_command[*].total_tokens 汇总 (Token 用量卡主指标) */
  tokens_total?: number;
  /** 按命令拆分: {improve: 69588, describe: 14310, ...} */
  tokens_by_command?: Record<string, number>;
}
export interface SeverityBucket {
  severity: string;
  total: number;
  applied: number;
  dismissed: number;
  /** ReviewAgent 自带 resolved 总量按 severity 比例分摊 (后端兜底逻辑) */
  resolved?: number;
  open: number;
  /** V2 默认无 superseded, 但前端视图会读, 兜底 0 */
  superseded?: number;
  adoption_rate: number;
  dismissal_rate: number;
}
export interface OverviewResp {
  configured?: boolean;
  since?: string | null;
  mrs: OverviewMr;
  suggestions: OverviewSuggestion;
  runs: OverviewRun;
  severity_breakdown: SeverityBucket[];
}
/** 规则命中聚合. ReviewAgent 没有 cited_count, total 即命中数 */
export interface RuleStat {
  rule_key: string;
  total: number;
  applied: number;
  dismissed: number;
  open: number;
  /** 兼容 V1 视图字段 */
  cited_count?: number;
  superseded?: number;
  adoption_rate: number;
  /** 后端已给 (dismissed / total, 0~1) */
  dismissal_rate?: number;
}
export interface AuthorStat {
  author: string;
  mr_count: number;
  suggestion_count: number;
  applied: number;
  dismissed: number;
  /** 兼容 V1 视图 (suggestion_total / runs_by_command 用不到, 兜底 undefined) */
  suggestion_total?: number;
  runs_by_command?: Record<string, { total: number; failed: number }>;
  adoption_rate: number;
}
export interface MrRow {
  project_id: number;
  mr_id: number;
  title: string;
  author: string;
  source_branch: string;
  target_branch: string;
  state: string;
  opened_at?: string | null;
  last_seen_at?: string | null;
  /** V2: ReviewAgent 提供的精确最后活动 (MAX of review/adopt/dismiss), 比 updated_at 更准 */
  last_activity_at?: string | null;
  last_review_at?: string | null;
  description_generated?: boolean;
  merged_at?: string | null;
  url?: string;
  /** V2 特有: 基于 last_review_at 时间窗的 'updated' 标识 */
  _v2_state?: string;
  last_run?: MrRun | null;
  suggestion_counts?: SuggestionCounts | null;
}
export interface SuggestionCounts {
  total: number;
  applied: number;
  dismissed: number;
  open: number;
  superseded: number;
  adopted_implicitly?: number;
}
export interface MrRun {
  run_id: string;
  command: string;
  status: string;
  model?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
  error?: string | null;
  suggestion_count?: number | null;
  /** webhook / note / scheduled */
  triggered_by?: string | null;
  actor_username?: string | null;
  total_tokens?: number | null;
  rule_keys_cited?: string[] | null;
  top_comment_id?: string | null;
}
export interface MrListResp {
  items: MrRow[];
  failed_mr_count: number;
  /** 跨页 (limit=200 扫一次拿全), banner 列表同源, 不会出现 count=2, list=0 这种不一致. */
  failed_items: MrRow[];
  total: number;
}
/** V2 的 suggestion 多了 suggestion_id (字符串, sqlite row id), 跟 actions 对齐 */
export interface SuggestionRow {
  id?: number | null;
  suggestion_id?: string;
  file?: string;
  line?: number;
  label?: string;
  importance?: number;
  score?: number;
  severity?: 'critical' | 'high' | 'medium' | 'low' | 'unknown';
  severity_source?: string;
  rule_keys?: string[];
  one_sentence_summary?: string;
  state?: string;
  posted_at?: string;
  applied_at?: string | null;
  dismissed_at?: string | null;
  dismissed_by?: string | null;
  dismissed_reason?: string | null;
  /** 采纳来源: ui_apply (GitLab 按钮自动) / manual_change (人工改代码) / adopt_command (/adopt) / unknown */
  adoption_source?: string | null;
  /** 采纳来源中文标签: 自动采纳 / 手动修改 / etc. */
  adoption_source_label?: string | null;
  /** ReviewAgent 中文状态标签 (后端 _STATE_LABELS):
   *  待处理 / 已采纳 / 已忽略 / 已关闭（未分类） / 已过期.
   *  优先用这个展示, 比前端 enum 维护更准. */
  state_label?: string | null;
  /** /adopt 校验用: suggestion 发布时 vs 当前的 head_sha (前 8 位), 用于展示"已落后" */
  head_sha_posted?: string | null;
  head_sha_current?: string | null;
  /** 落后 commit 数 (前端粗略估算, 后端可补) */
  behind_commits?: number | null;
  /** state='resolved' (GitLab 解决主题) 时填充 — 用户在 GitLab UI 关 thread 但没 apply/dismiss */
  resolved_at?: string | null;
  resolved_by?: string | null;
  resolution_source?: string | null;
}
export interface DismissReasonBucket {
  reason: string;
  count: number;
}
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
  error?: string | null;
  triggered_by?: string | null;
  actor_username?: string | null;
  total_tokens?: number | null;
  rule_keys_cited?: string[] | null;
  top_comment_id?: string | null;
  suggestion_count?: number;
}
export interface ActionRow {
  id: number;
  suggestion_id: string;
  action: string;
  actor?: string;
  note?: string;
  at: string;
  /** ReviewAgent validation_status: ui-apply / ok / target-unchanged / content-unavailable / gitlab-resolve */
  validation_status?: string;
  head_sha_posted?: string;
  head_sha_current?: string;
}
export interface TimelineResp {
  mr?: MrRow;
  suggestions: SuggestionRow[];
  runs: RunRow[];
  actions: ActionRow[];
}
export interface HealthResp {
  configured: boolean;
  status: string;
  message: string;
}

export async function getHealth(): Promise<HealthResp> {
  return (await request.get('/review-agent/health')) as HealthResp;
}
export async function getOverview(since?: string): Promise<OverviewResp> {
  return (await request.get('/review-agent/metrics/overview', { params: since ? { since } : {} })) as OverviewResp;
}
export async function getRules(since?: string): Promise<RuleStat[]> {
  return ((await request.get('/review-agent/metrics/rules', { params: since ? { since } : {} })) as RuleStat[]) || [];
}
export async function getAuthors(since?: string): Promise<AuthorStat[]> {
  return ((await request.get('/review-agent/metrics/authors', { params: since ? { since } : {} })) as AuthorStat[]) || [];
}
export async function listMrs(params: { limit?: number; offset?: number; project_id?: number; state?: string; since?: string } = {}): Promise<MrListResp> {
  return (await request.get('/review-agent/mrs', { params })) as MrListResp;
}
export async function getTimeline(projectId: number, mrId: number): Promise<TimelineResp> {
  return (await request.get(`/review-agent/mrs/${projectId}/${mrId}/timeline`)) as TimelineResp;
}
export async function getSeverity(since?: string): Promise<SeverityBucket[]> {
  return ((await request.get('/review-agent/metrics/severity', { params: since ? { since } : {} })) as SeverityBucket[]) || [];
}
export async function getDismissalsByRule(since?: string): Promise<DismissalsByRuleItem[]> {
  return ((await request.get('/review-agent/dismissals/by-rule', { params: since ? { since } : {} })) as DismissalsByRuleItem[]) || [];
}

/** 周报 list item: name / path / size / modified */
export interface WeeklyReportListItem {
  name: string;
  path: string;
  size: number;
  modified: number;
}
/** 周报完整内容: sections.telemetry / merged_mrs / repo_scan + LLM 综述 */
export interface WeeklyReport {
  schema_version?: number;
  project_id?: number;
  week_label: string;
  week_start: string;
  week_end: string;
  generated_at: string;
  timezone?: string;
  report_title?: string;
  report_emoji?: string;
  dashboard_url?: string;
  sections: {
    telemetry?: { status?: string; data?: any };
    merged_mrs?: { status?: string; data?: any };
    repo_scan?: { status?: string; data?: any };
    [k: string]: any;
  };
}

export async function getWeeklyReports(limit = 5): Promise<WeeklyReportListItem[]> {
  const r = await request.get('/review-agent/weekly-reports', { params: { limit } });
  return (r as any)?.reports || [];
}
export async function getWeeklyReport(name: string): Promise<WeeklyReport> {
  return (await request.get(`/review-agent/weekly-reports/${encodeURIComponent(name)}`)) as WeeklyReport;
}
