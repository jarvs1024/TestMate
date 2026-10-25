/** AI 资产市场 API (后端 /api/v1/assets/*).
 *
 * ⚠️ 响应拦截器 (utils/request.ts) 返回的是**响应体本身**, axios 的类型声明
 *    仍是 Promise<AxiosResponse> —— 两者不一致, 所以统一走 apiGet/apiPost/apiPut
 *    三个 helper 做类型收敛.
 *
 * 真实资产存放在 GitLab 仓库 root/testmate-market, 后端只维护查询镜像.
 */
import request from '@/utils/request';
import { getClientId } from '@/utils/clientId';

export type MarketKind = 'plugin' | 'skill' | 'mcp';

export interface MarketPermissions {
  filesystem_read?: string[];
  filesystem_write?: string[];
  network?: string[];
  process_exec?: string[];
  secrets?: string[];
}

export interface AssetItem {
  code: string;
  name: string;
  icon: string;
  kind: MarketKind;
  version: string;
  summary: string;
  description: string;
  use_when: string;
  not_for: string;
  category: string;
  /** 适用项目: 空 = 通用 (所有项目都能用); "6100" = 6100 项目特有 */
  project: string;
  tags: string[];
  keywords: string[];
  author: string;
  featured: boolean;
  homepage: string | null;
  permissions: MarketPermissions;
  install_steps: string[];
  bindings: Record<string, any>;
  git_path: string;
  git_commit_sha: string;
  /** 资产在 GitLab 上的网页地址 (由 marketplace.git.web_url 拼出; 没配就为空) */
  git_web_url: string;
  /** 下载次数 (热门度) —— 不是"安装次数" */
  download_count: number;
  updated_at: string | null;
  /** 同步状态: staged(待同步) / pushed(已同步) / failed(失败) */
  sync_status: 'staged' | 'pushed' | 'failed' | string;
  last_error: string;
  /** 连接器 (mcp) 的 MCP 配置 —— 非连接器为 null */
  mcp_config?: Record<string, any> | null;
  /** 生命周期: published(在架) / pending(待审核) / rejected(已驳回) /
   *  unpublished(已下架) / unpublish_pending(申请下架, 等管理员确认) */
  publish_status: 'published' | 'pending' | 'rejected' | 'unpublished' | 'unpublish_pending' | string;
  /** 最近一次审核意见 (驳回理由) */
  review_note: string;
  /** 当前用户能不能审这个资产 (管理员或被授权的审核人) */
  can_review: boolean;
}

export interface AssetListResp {
  items: AssetItem[];
  total: number;
}

export interface AssetFileNode {
  name: string;
  path: string;
  type: string;
  size: number | null;
}

export interface AssetJob {
  id: number;
  action: string;
  status: 'pending' | 'staged' | 'syncing' | 'pushed' | 'failed';
  code: string;
  asset_name: string;
  kind: string;
  git_path: string;
  commit_sha: string;
  error: string;
  attempts: number;
  staged_at: string | null;
  pushed_at: string | null;
  next_retry_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** 详情页展示的文档 (SKILL.md / README.md) */
export interface AssetDoc {
  kind: string;
  filename: string;
  frontmatter: Record<string, any>;
  content: string;
}

/** 前端通道安装用: 已解压的明文文件清单 */
export interface AssetFileContent {
  path: string;
  encoding: 'text' | 'base64';
  content: string;
}

export interface AssetBundle {
  code: string;
  version: string;
  files: AssetFileContent[];
  total: number;
}



/** 上传前的包体检结果 */
export interface PackagePreview {
  ok: boolean;
  filename: string;
  size_bytes: number;
  kind: string;
  total_files: number;
  files: string[];
  doc_file: string;
  has_skill_md: boolean;
  has_plugin_manifest: boolean;
  has_mcp_config: boolean;
  installable: boolean;
  block_reason: string;
  issues: string[];
  warnings: string[];
}

/** 钉钉通知回执 */
export interface AssetNotification {
  id: number;
  event: string;
  code: string;
  asset_name: string;
  status: 'pending' | 'sent' | 'failed' | string;
  attempts: number;
  error: string;
  last_attempt_at: string | null;
  created_at: string | null;
}

/** 市场当前生效的配置 (只读) —— 设置页展示用 */
export interface MarketConfig {
  workspace: string;
  remote: string;
  branch: string;
  web_url: string;
  skill_dir: string;
  plugin_dir: string;
  install_enabled: boolean;
  is_repo: boolean;
  head: string;
}

export interface SyncStatus {
  has_remote_updates: boolean;
  conflict_count: number;
  pending_count: number;
  failed_count: number;
  unpublished_count: number;
  /** 待审核 / 已驳回 的资产数 (审核台徽标) */
  awaiting_review_count: number;
  rejected_count: number;
  /** 我自己提交但还没通过审核的资产数 (待审核 + 已驳回) */
  my_review_count: number;
  /** 我自己提交的、还在等审核的资产数 */
  my_pending_count: number;
  /** 申请下架、等管理员确认的资产数 (确认后资产会被彻底删除) */
  unpublish_pending_count: number;
  /** 我自己申请下架、还在等确认的资产数 */
  my_unpublish_count: number;
  last_sync_at: string | null;
}

export interface AssetAudit {
  id: number;
  asset_id: number | null;
  code: string;
  action: string;
  actor_id: number | null;
  actor_name: string;
  comment: string;
  detail: Record<string, any>;
  created_at: string | null;
  /** 动作的中文说明 —— **后端给的** (唯一真源, 见 market_state.audit_action_label) */
  action_label?: string;
}

export interface UploadForm {
  code?: string;
  kind: MarketKind;
  name: string;
  version: string;
  summary: string;
  description: string;
  use_when: string;
  not_for: string;
  category: string;
  /** 适用项目: 空 = 通用; "6100" = 6100 项目特有 */
  project?: string;
  icon: string;
  tags: string[];
  /** 搜索关键词 (同义词) —— 搜不到时靠它 */
  keywords?: string[];
  /** 连接器 (mcp) 的 MCP 配置 (JSON 文本) —— 非连接器留空 */
  mcp_config?: string;
  permissions: MarketPermissions;
  install_steps: string[];
  featured: boolean;
  /** 压缩包 (zip / tar.gz) — 与 files 二选一 */
  package?: File | null;
  files: File[];
}

// ---------- 类型收敛的请求封装 ----------

async function apiGet<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return (await request.get(url, { params })) as unknown as T;
}
async function apiPost<T>(url: string, body?: unknown): Promise<T> {
  return (await request.post(url, body)) as unknown as T;
}
async function apiPut<T>(url: string, body?: unknown): Promise<T> {
  return (await request.put(url, body)) as unknown as T;
}
async function apiDelete<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return (await request.delete(url, { params })) as unknown as T;
}

// ---------- 读 ----------

export async function listAssets(params: {
  kind?: MarketKind; category?: string; q?: string; sort?: 'hot' | 'new' | 'name';
  /** 按项目过滤: 留空=不过滤; __general=只看通用; 6100=该项目特有 + 通用 */
  project?: string;
  include_unpublished?: boolean; limit?: number; offset?: number;
  /** 按上架状态过滤: published | pending | rejected | unpublished | mine | all; 留空=默认可见性 */
  status?: string;
} = {}): Promise<AssetListResp> {
  return apiGet<AssetListResp>('/assets', { client_id: getClientId(), ...params });
}

export async function listCategories(): Promise<{
  items: {
    name: string; slug: string; desc?: string; order?: number;
    by_kind: Record<string, number>; total: number;
  }[];
  total?: number;
}> {
  return apiGet('/assets/categories');
}

/**
 * 项目列表 + 每个项目的资产数 —— 上传表单的「适用项目」与市场页的筛选都用它.
 *
 * ⚠️ 通用 (code = "") 也在列表里 —— 它是"默认选项", 不是某个项目。
 */
export async function listProjects(): Promise<{
  items: { code: string; name: string; total: number; is_general?: boolean }[];
  total?: number;
}> {
  return apiGet('/assets/projects');
}

export async function getAsset(code: string): Promise<AssetItem> {
  return apiGet<AssetItem>(`/assets/${encodeURIComponent(code)}`, { client_id: getClientId() });
}

export async function getAssetDoc(code: string): Promise<AssetDoc> {
  return apiGet<AssetDoc>(`/assets/${encodeURIComponent(code)}/doc`);
}

export async function getAssetFiles(code: string): Promise<{ code: string; git_path: string; files: AssetFileNode[] }> {
  return apiGet(`/assets/${encodeURIComponent(code)}/files`);
}

export async function getAssetBundle(code: string): Promise<AssetBundle> {
  return apiGet<AssetBundle>(`/assets/${encodeURIComponent(code)}/bundle`);
}

export async function getSyncStatus(): Promise<SyncStatus> {
  return apiGet<SyncStatus>('/assets/sync-status', { client_id: getClientId() });
}

export async function listAudits(code?: string): Promise<{ items: AssetAudit[]; total: number }> {
  return apiGet('/assets/audits', code ? { code, limit: 50 } : { limit: 50 });
}

/** 钉钉通知送达回执 */
export async function listNotifications(limit = 50): Promise<{ items: AssetNotification[]; total: number }> {
  return apiGet('/assets/notifications', { limit });
}

/** 市场当前生效的配置 (只读) */
export async function getMarketConfig(): Promise<MarketConfig> {
  return apiGet<MarketConfig>('/assets/config');
}

/** 上传前体检: 这个包装不装得上 */
export async function previewPackage(file: File, kind: string): Promise<PackagePreview> {
  const fd = new FormData();
  fd.append('package', file, file.name);
  fd.append('kind', kind);
  return (await request.post('/assets/preview-package', fd)) as unknown as PackagePreview;
}

/** 管理员审核上架: decision = approve | reject */
export async function reviewAsset(
  code: string, decision: 'approve' | 'reject', comment = '',
): Promise<{ ok: boolean; code: string; publish_status: string; changed: boolean }> {
  const fd = new FormData();
  fd.append('decision', decision);
  fd.append('comment', comment);
  return (await request.post(`/assets/${encodeURIComponent(code)}/review`, fd)) as unknown as {
    ok: boolean; code: string; publish_status: string; changed: boolean;
  };
}

/** 发布者把资产重新提交审核 (驳回后改了再交) */
export async function submitForReview(
  code: string, comment = '',
): Promise<{ ok: boolean; code: string; publish_status: string; changed: boolean }> {
  const fd = new FormData();
  fd.append('comment', comment);
  return (await request.post(`/assets/${encodeURIComponent(code)}/submit`, fd)) as unknown as {
    ok: boolean; code: string; publish_status: string; changed: boolean;
  };
}

/**
 * 彻底删除资产 (不只是下架).
 *
 * ⚠️ 在架的资产: **管理员专用** —— 用户删除要走「申请下架 → 管理员确认」.
 * ⚠️ 还没上架过的 (待审核 / 被驳回): **作者本人也能删** ——
 *    这两种状态的东西从来没对外可见过, 直接删是安全的, 不用走审核.
 */
export async function deleteAsset(code: string, comment = ''): Promise<{
  ok: boolean; code: string; commit_sha: string;
}> {
  return apiDelete('/assets/' + encodeURIComponent(code), { comment });
}

/**
 * **申请下架** —— 提交后等管理员确认, 确认通过资产会被彻底删除.
 *
 * ⚠️ confirmCode 必须与资产 code 一致 —— 后端会校验, 绕不过去.
 *    (前端弹窗只是提醒, 不是防线)
 */
export async function unpublishAsset(
  code: string, confirmCode: string, comment = '',
): Promise<{ ok: boolean; code: string; publish_status: string; changed: boolean }> {
  const fd = new FormData();
  fd.append('confirm_code', confirmCode);
  fd.append('comment', comment);
  return (await request.post(`/assets/${encodeURIComponent(code)}/unpublish`, fd)) as unknown as {
    ok: boolean; code: string; publish_status: string; changed: boolean;
  };
}

/**
 * 管理员审核下架申请: approve = 通过并**彻底删除**
 *
 * ⚠️ 下架审核**没有"驳回"** —— 不通过的话不处理即可, 作者可自行撤销申请.
 */
export async function reviewUnpublish(
  code: string, decision: 'approve' = 'approve', comment = '',
): Promise<{ ok: boolean; code: string; decision: string; deleted?: boolean; publish_status?: string }> {
  const fd = new FormData();
  fd.append('decision', decision);
  fd.append('comment', comment);
  return (await request.post(`/assets/${encodeURIComponent(code)}/unpublish-review`, fd)) as unknown as {
    ok: boolean; code: string; decision: string; deleted?: boolean; publish_status?: string;
  };
}

/** 作者撤销自己的下架申请 —— 资产恢复在架, 不用等管理员驳回 */
export async function cancelUnpublish(
  code: string, comment = '',
): Promise<{ ok: boolean; code: string; publish_status: string; changed: boolean }> {
  const fd = new FormData();
  fd.append('comment', comment);
  return (await request.post(`/assets/${encodeURIComponent(code)}/unpublish-cancel`, fd)) as unknown as {
    ok: boolean; code: string; publish_status: string; changed: boolean;
  };
}

export async function getJob(id: number): Promise<AssetJob> {
  return apiGet<AssetJob>(`/assets/jobs/${id}`);
}

export async function listJobs(limit = 20): Promise<{ items: AssetJob[]; total: number }> {
  return apiGet<{ items: AssetJob[]; total: number }>('/assets/jobs', { limit });
}

/** 人工重试一个失败的同步任务 */
export async function retryJob(id: number): Promise<AssetJob> {
  return apiPost<AssetJob>(`/assets/jobs/${id}/retry`);
}

// ---------- 写 ----------

function toFormData(f: UploadForm, includeCode: boolean): FormData {
  const fd = new FormData();
  if (includeCode && f.code) fd.append('code', f.code);
  fd.append('kind', f.kind);
  fd.append('name', f.name);
  fd.append('version', f.version);
  fd.append('summary', f.summary);
  fd.append('description', f.description);
  fd.append('use_when', f.use_when);
  fd.append('not_for', f.not_for);
  fd.append('category', f.category);
  fd.append('project', f.project || '');
  fd.append('icon', f.icon);
  fd.append('tags', JSON.stringify(f.tags));
  fd.append('keywords', JSON.stringify(f.keywords || []));
  fd.append('mcp_config', f.mcp_config || '');
  fd.append('featured', String(f.featured));
  fd.append('permissions', JSON.stringify(f.permissions));
  fd.append('install_steps', JSON.stringify(f.install_steps));
  fd.append('bindings', JSON.stringify({}));
  if (f.package) {
    fd.append('package', f.package, f.package.name);
  } else {
    f.files.forEach((file) => fd.append('files', file, file.name));
  }
  return fd;
}

export async function uploadAsset(form: UploadForm): Promise<AssetJob> {
  return apiPost<AssetJob>('/assets/upload', toFormData(form, true));
}

export async function updateAsset(code: string, form: UploadForm): Promise<AssetJob> {
  return apiPut<AssetJob>(`/assets/${encodeURIComponent(code)}`, toFormData(form, false));
}

/**
 * 下载安装包 (原始 zip) —— 给"下载安装包后自行解压"这条路用.
 *
 * 下载端点要带 token, 所以不能用 <a href> 直接开 (没 Authorization 头),
 * 得先 fetch 成 blob 再由前端触发保存.
 */
export async function downloadAssetPackage(code: string, version: string): Promise<Blob> {
  const resp = await request.get(
    `/assets/${encodeURIComponent(code)}/versions/${encodeURIComponent(version)}/download`,
    { responseType: 'blob' },
  );
  return resp as unknown as Blob;
}

export async function publishAsset(code: string, comment = ''): Promise<void> {
  const fd = new FormData();
  fd.append('comment', comment);
  await request.post(`/assets/${encodeURIComponent(code)}/publish`, fd);
}

export async function syncFromGit(): Promise<{ ok: boolean; added: number; updated: number; index_present: boolean; gitlab: string }> {
  return apiPost('/assets/sync');
}

export async function probeGitLab(): Promise<{ ok: boolean; status: string; message: string }> {
  return apiGet('/assets/probe/gitlab');
}
