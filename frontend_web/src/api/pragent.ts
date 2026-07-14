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

export interface RuleStat {
  rule_key: string;
  cited_count?: number;
  applied_count?: number;
  dismissed_count?: number;
  open_count?: number;
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

export interface ActionRow {
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
export async function listMrs(params: { limit?: number; project_id?: number; state?: string; since?: string } = {}): Promise<MrRow[]> {
  return (await request.get('/pr-agent/mrs', { params })) as MrRow[];
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
