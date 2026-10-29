/** 知识库 (RAGFlow 代理) API. */
import request from '@/utils/request';

export interface KbDataset {
  id: string;
  name: string;
  description: string;
  chunk_count: number;
  document_count: number;
  chunk_method: string;
  create_date: string;
  // P1 新增
  embedding_model: string;
  permission: string;          // 'me' | 'team'
  status: string;              // '1' = 启用
  language: string;
  token_num: number;
  similarity_threshold: number;
  vector_similarity_weight: number;
  pagerank: number;
  update_date: string;
  create_time: number;         // epoch ms
  update_time: number;
  parser_config: Record<string, any>;
}

export interface KbChunk {
  id: string;
  content: string;
  highlight: string;
  dataset_id: string;
  document_id: string;
  document_keyword: string;
  positions: number[][];
  similarity: number;
  vector_similarity: number;
  term_similarity: number;
  tag_kwd: string[];
}

export interface KbSearchResult {
  total: number;
  chunks: KbChunk[];
  doc_aggs: Array<{ doc_id: string; doc_name: string; count: number }>;
  elapsed_ms: number;
}

export interface KbSearchParams {
  question: string;
  dataset_ids: string[];
  document_ids?: string[];
  top_k?: number;
  similarity_threshold?: number;
  vector_similarity_weight?: number;
  keyword?: boolean;
  highlight?: boolean;
  page_size?: number;
}

// P2 新增: 文档列表
export type DocRunStatus = 'UNSTART' | 'RUNNING' | 'CANCEL' | 'DONE' | 'FAIL';

export interface KbDocument {
  id: string;
  name: string;
  location: string;
  type: string;                // 'doc' | 'pdf' | 'excel' | ...
  size: number;                // bytes
  chunk_count: number;
  token_count: number;
  chunk_method: string;
  run: DocRunStatus | string;  // 文档处理状态
  progress: number;            // 0~1
  progress_msg: string;        // 失败原因 (FAIL 时)
  process_begin_at: string | null;
  process_duration: number;    // 秒
  source_type: string;         // 'local' | 'http' | ...
  parser_config: Record<string, any>;
  status: string;              // '1' = 启用
  create_date: string;
  update_date: string;
  create_time: number;
  update_time: number;
}


export interface KbDocChunk {
  id: string;
  content: string;
  docnm_kwd: string;
  document_id: string;
  available: boolean;
  image_id: string;
  important_keywords: string[];
  tag_kwd: string[];
  positions: number[][];
  create_time: string;
  create_timestamp: number;
}

export interface KbDocChunksResult {
  chunks: KbDocChunk[];
  total: number;
  doc: Record<string, any>;
}
export interface KbDocumentListResult {
  docs: KbDocument[];
  total: number;
}

/**
 * 列出 RAGFlow 数据集.
 * @param opts.silent 失败时不弹全局错误 (调用方自己降级, 比如首页卡片取数)
 */
export async function listDatasets(
  opts: { silent?: boolean } = {},
): Promise<{ items: KbDataset[]; total: number }> {
  return (await request.get('/kb/datasets', { silent: opts.silent })) as {
    items: KbDataset[];
    total: number;
  };
}

export async function kbSearch(params: KbSearchParams): Promise<KbSearchResult> {
  return (await request.post('/kb/search', params)) as KbSearchResult;
}

export async function kbHealth(
  opts: { silent?: boolean } = {},
): Promise<{ status: string; message: string }> {
  return (await request.get('/kb/health', { silent: opts.silent })) as {
    status: string;
    message: string;
  };
}

// P2 新增: 文档相关
export async function listDocuments(
  datasetId: string,
  params: { page?: number; page_size?: number; keywords?: string; run?: string } = {},
): Promise<KbDocumentListResult> {
  return (await request.get(`/kb/datasets/${encodeURIComponent(datasetId)}/documents`, { params })) as KbDocumentListResult;
}

export async function ingestDocuments(
  datasetId: string,
  docIds: string[],
  run: '1' | '2' = '1',
  deleteExisting = false,
): Promise<{ ok: boolean }> {
  return (await request.post(`/kb/datasets/${encodeURIComponent(datasetId)}/documents/ingest`, {
    doc_ids: docIds, run, delete: deleteExisting,
  })) as { ok: boolean };
}

export async function deleteKbDocuments(
  datasetId: string,
  docIds?: string[],
  deleteAll = false,
): Promise<{ ok: boolean }> {
  return (await request.delete(`/kb/datasets/${encodeURIComponent(datasetId)}/documents`, {
    data: { ids: docIds, delete_all: deleteAll },
  })) as { ok: boolean };
}

// 列出某文档的 chunks
export async function listDocChunks(
  datasetId: string,
  documentId: string,
  params: { page?: number; page_size?: number; keywords?: string } = {},
): Promise<KbDocChunksResult> {
  // RAGFlow 限制 page_size <= 100, 兜底 (后端也会兜)
  const p = { page: 1, page_size: 100, ...params };
  if (p.page_size > 100) p.page_size = 100;
  return (await request.get(
    `/kb/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/chunks`,
    { params: p },
  )) as KbDocChunksResult;
}

// ---------- 新建数据集 (2026-10-29) ----------

/**
 * RAGFlow v0.26.1 的切片方式.
 *
 * ⚠️ 对外字段是 `chunk_method` —— 传 `parser_id` 会被 RAGFlow 当多余字段拒掉.
 * ⚠️ 通用切片的值是 `'naive'` (界面显示「通用」), `'general'` 是更新版本的说法.
 */
export type KbChunkMethod = 'naive' | 'manual';

export interface KbCreateResult {
  ok: boolean;
  dataset: {
    id: string;
    name: string;
    description: string;
    chunk_method: string;
    embedding_model: string;
    permission: string;
    document_count: number;
    chunk_count: number;
  };
}

/**
 * 新建知识库数据集.
 *
 * ⚠️ 新建的库**立刻出现在所有人的列表里** —— 名字要说清楚这个库放什么.
 * ⚠️ `chunkMethod`: 'naive'(通用/自动分段, 默认) | 'manual'(手动切分).
 *    manual 的解析器只认 pdf/docx, 传 .txt/.md 进去解析不了.
 */
export async function createKbDataset(
  name: string,
  description = '',
  chunkMethod: KbChunkMethod = 'naive',
): Promise<KbCreateResult> {
  return (await request.post('/kb/datasets', {
    name, description, chunk_method: chunkMethod,
  })) as KbCreateResult;
}

// ---------- 上传 / 下载 (2026-10-29) ----------

export interface KbUploadResult {
  ok: boolean;
  /** 实际入库的文档数 */
  uploaded: number;
  /** 是否已经发起解析 (解析是异步的, 状态要等轮询) */
  ingest_started: boolean;
  /** ⚠️ 有话要说 (比如数据集是"手动分块", 解析不了) */
  warning?: string;
  docs: Array<{
    id: string;
    name: string;
    size: number;
    location: string;
    run: string;
  }>;
}

/**
 * 上传文档到数据集 (multipart/form-data, 字段名 `file`).
 *
 * ⚠️ 后端限: 单文件 20MB / 单次最多 5 个 —— 超了后端会 413 / 422.
 * ⚠️ 上传后会自动发起解析, 但解析是异步的 —— 状态要看文档列表轮询.
 */
export async function uploadKbDocuments(
  datasetId: string,
  files: File[],
): Promise<KbUploadResult> {
  const fd = new FormData();
  for (const f of files) fd.append('file', f);
  return (await request.post(
    `/kb/datasets/${encodeURIComponent(datasetId)}/documents`,
    fd,
    // ⚠️ **别手动设 Content-Type** —— axios 不会替你补 boundary,
    //    写成 'multipart/form-data' (没有 boundary) 后端直接解析失败.
    //    交给浏览器自己设就行.
    // ⚠️ 超时放宽: 5 个 20MB 的文件传完还要等 RAGFlow 收, 30 秒不够.
    { timeout: 180000 },
  )) as KbUploadResult;
}

/**
 * 下载文档原始文件.
 *
 * ⚠️ 这条走的是**浏览器直接下载** —— 不能走 axios (二进制流过 JSON 解析会坏掉).
 *    所以用 fetch + blob, 手动触发 a[download].
 */
export async function downloadKbDocument(
  datasetId: string,
  documentId: string,
  docName: string,
): Promise<void> {
  const token = localStorage.getItem('testmate:token') || '';
  const r = await fetch(
    `/api/v1/kb/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/download`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try {
      const j = await r.json();
      detail = j?.detail || detail;
    } catch { /* 不是 JSON 就用状态码 */ }
    throw new Error(detail);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = docName || 'document';
  document.body.appendChild(a);
  a.click();
  a.remove();
  // ⚠️ 必须 revoke —— 不 revoke 的话 blob 会一直占着内存
  URL.revokeObjectURL(url);
}

export interface KbAuditItem {
  id: number;
  dataset_id: string;
  dataset_name: string;
  document_id: string;
  doc_name: string;
  action: string;
  actor_name: string;
  error: string;
  size: number;
  created_at: string;
}

/**
 * 知识库操作审计 —— 谁在什么时候传了什么.
 *
 * ⚠️ 内容存在 RAGFlow 里, RAGFlow 自己记不了 TestMate 的账号
 *    (所有人共用一把 API key) —— "谁传的"只能靠这张表.
 */
export async function listKbAudits(limit = 50): Promise<{ items: KbAuditItem[]; total: number }> {
  return (await request.get('/kb/audits', { params: { limit } })) as {
    items: KbAuditItem[]; total: number;
  };
}

