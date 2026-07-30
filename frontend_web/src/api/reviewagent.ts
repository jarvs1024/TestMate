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
  severity: string;
  total: number;
  applied: number;
  dismissed: number;
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
}
export interface MrListResp {
  items: MrRow[];
  failed_mr_count: number;
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
  suggestion_count?: number;
  triggered_by?: string;
}
export interface ActionRow {
  id: number;
  suggestion_id: string;
  action: string;
  actor?: string;
  note?: string;
  at: string;
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
