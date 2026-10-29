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
  /**
   * 归属: 这个库是谁建的.
   *
   * ⚠️ RAGFlow 那边记不了 —— 它的 `created_by` 指的是 RAGFlow 用户,
   *    而 TestMate 的所有登录用户共用同一把 API key.
   * ⚠️ 2026-10-29 建库功能上线**之前**手工建的库没有记录 → 空串 (显示「—」).
   */
  created_by_name?: string;
  created_by?: number | null;
  /** ISO 串, 带 Z (UTC) */
  created_at?: string;
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
  /**
   * 归属: 这篇是谁传的 (最后一次上传的人).
   *
   * ⚠️ 同 KbDataset.created_by_name —— RAGFlow 记不了 TestMate 的账号.
   * ⚠️ 上传功能上线之前传的文件没有记录 → 空串 (显示「—」).
   */
  uploaded_by_name?: string;
  uploaded_by?: number | null;
  /** ISO 串, 带 Z (UTC) */
  uploaded_at?: string;
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

/**
 * 删除**整个**数据集 (admin only).
 *
 * ⚠️ **硬删, 不可逆** —— 库里的所有文档、分段、源文件一起没了, 没有回收站.
 * ⚠️ 前端要**先让用户输入库名确认**再调这个 —— RAGFlow 那边不提供任何撤销.
 */
export async function deleteKbDataset(datasetId: string): Promise<{
  ok: boolean;
  deleted: { dataset_id: string; name: string; documents: number; chunks: number };
}> {
  return (await request.delete(`/kb/datasets/${encodeURIComponent(datasetId)}`)) as {
    ok: boolean;
    deleted: { dataset_id: string; name: string; documents: number; chunks: number };
  };
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
/**
 * RAGFlow v0.26.1 建库接口支持的**全部**切片方式.
 *
 * ⚠️ 对外字段是 `chunk_method` —— 传 `parser_id` 会被 RAGFlow 当多余字段拒掉.
 * ⚠️ 通用切片的值是 `'naive'` (界面显示「通用」), `'general'` 是更新版本的说法,
 *    **这版 RAGFlow 不认** (真机实测 → code 101).
 */
export type KbChunkMethod =
  | 'naive' | 'qa' | 'table' | 'paper' | 'book' | 'laws'
  | 'presentation' | 'picture' | 'one' | 'email' | 'tag' | 'resume'
  | 'manual';

/** 数据集语言 (影响自动问答 / 关键词提取). */
export type KbLanguage = 'Chinese' | 'English';

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
    language?: string;
  };
  /** ⚠️ 语言没设上之类的"部分成功"提示 —— 如实告诉用户 */
  warning?: string;
}

/**
 * 新建知识库数据集.
 *
 * ⚠️ 新建的库**立刻出现在所有人的列表里** —— 名字要说清楚这个库放什么.
 * ⚠️ `chunkMethod`: 默认 `'naive'`(通用/自动分段).
 *    `'manual'`(手动切分)的解析器只认 pdf/docx, 传 .txt/.md 进去解析不了.
 * ⚠️ `language`: 默认 `'Chinese'` —— ⚠️ **RAGFlow 建库接口不认这个字段**,
 *    是网关建完库再补一次 PUT 设上的, 所以这一步失败会有 `warning` 返回.
 */
export async function createKbDataset(
  name: string,
  description = '',
  chunkMethod: KbChunkMethod = 'naive',
  language: KbLanguage = 'Chinese',
): Promise<KbCreateResult> {
  return (await request.post('/kb/datasets', {
    name, description, chunk_method: chunkMethod, language,
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

// ---------- 更新文档 / 重新解析 (2026-10-29) ----------

export interface KbUpdateResult {
  ok: boolean;
  /** ⚠️ **新的文档 id** —— RAGFlow 里"更新"是删旧建新, id 变了 */
  updated: { id: string; name: string; size: number };
  /** 被换掉的那一篇 (已经没了) */
  replaced: { id: string; name: string };
  /** 是否已经发起解析 (异步的, 状态要看文档列表轮询) */
  ingest_started: boolean;
  /** ⚠️ 有话要说 (比如手动分块的数据集解析不了) */
  warning?: string;
}

/**
 * **替换**一篇文档的内容 (换新文件), 旧版直接删除.
 *
 * ⚠️ 旧版本是**永久删除**的 —— 审计表里会留一条 update 记录, 但旧文件本身找不回来.
 * ⚠️ 返回的 `updated.id` 是**新的**文档 id —— 拿到之后别再用旧的 id 操作.
 * ⚠️ 只能换内容, **不能换文件类型** (扩展名必须一致) —— 后端会 422.
 */
export async function updateKbDocument(
  datasetId: string,
  documentId: string,
  file: File,
): Promise<KbUpdateResult> {
  const fd = new FormData();
  fd.append('file', file);
  return (await request.put(
    `/kb/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}`,
    fd,
    // ⚠️ 别手动设 Content-Type —— axios 不会替你补 boundary
    // ⚠️ 超时放宽: 20MB 文件传完还要等 RAGFlow 收 + 删旧 + 改名
    { timeout: 180000 },
  )) as KbUpdateResult;
}

/**
 * **重新解析**一篇文档 (内容不变, 重跑一遍切片 / 向量化).
 *
 * ⚠️ 跟"启动/取消解析"(ingest) 不是一回事 ——
 *    ingest 是队列开关, 这个是**强制重跑** (清掉已有分段再解析一遍).
 */
export async function reparseKbDocument(
  datasetId: string,
  documentId: string,
): Promise<{ ok: boolean; document_id: string; name: string }> {
  return (await request.post(
    `/kb/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/reparse`,
  )) as { ok: boolean; document_id: string; name: string };
}

// ---------- 文档搜索 (2026-10-29) ----------

export interface KbDocSearchHit extends KbDocument {
  /** 文档所在的库 —— 跨库搜索必须带上, 否则用户不知道东西在哪 */
  dataset_id: string;
  dataset_name: string;
}

export interface KbDocSearchResult {
  items: KbDocSearchHit[];
  /** 命中的**总数**(可能被 limit 截断) */
  total: number;
  keywords: string;
  /** 搜了几个库 */
  datasets: number;
  /** 结果被截断了(总数 > limit) */
  truncated?: boolean;
}

/**
 * 按**文件名**跨数据集搜文档.
 *
 * ⚠️ RAGFlow 的 keywords 是 `LOWER(name).contains(keywords.lower())`
 *    —— **不区分大小写的子串匹配**, 只搜**文件名**, 不搜内容.
 * ⚠️ 搜全部库要**逐个库**查 (后端并发做), 库多了会慢一点.
 */
export async function searchKbDocuments(
  keywords: string,
  datasetId = '',
): Promise<KbDocSearchResult> {
  return (await request.get('/kb/documents/search', {
    params: { keywords, ...(datasetId ? { dataset_id: datasetId } : {}) },
  })) as KbDocSearchResult;
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
 *
 * ⚠️ **分页** (2026-10-29) —— 审计流水只增不减, 一次全拉几千条会把页面
 *    拖死, 而且新记录反而看不见. 现在按页拉.
 *
 * ⚠️ 这里的兜底不是为了好看 —— 后端返回结构变了以后, 老测试的 mock 还是
 *    `{items, total}` 两字段. 归一化在**这一层**做, 页面里就不用到处
 *    写 `r.pages ?? ...`.
 */
export interface KbAuditPage {
  items: KbAuditItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export async function listKbAudits(
  page = 1,
  pageSize = 20,
): Promise<KbAuditPage> {
  const r = (await request.get('/kb/audits', {
    params: { page, page_size: pageSize },
  })) as Partial<KbAuditPage> & { items?: KbAuditItem[] };

  const items = r?.items || [];
  const total = Number(r?.total ?? items.length);
  const ps = Number(r?.page_size ?? pageSize) || pageSize;
  const pages = Number(r?.pages ?? Math.max(1, Math.ceil(total / ps)));
  return {
    items,
    total,
    page: Number(r?.page ?? page) || page,
    page_size: ps,
    pages,
  };
}

