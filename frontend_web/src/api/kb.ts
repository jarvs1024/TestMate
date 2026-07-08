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

export async function listDatasets(): Promise<{ items: KbDataset[]; total: number }> {
  return (await request.get('/kb/datasets')) as { items: KbDataset[]; total: number };
}

export async function kbSearch(params: KbSearchParams): Promise<KbSearchResult> {
  return (await request.post('/kb/search', params)) as KbSearchResult;
}

export async function kbHealth(): Promise<{ status: string; message: string }> {
  return (await request.get('/kb/health')) as { status: string; message: string };
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

// 文档下载: 浏览器直接走 <a :href download> 即可, 这里只返回 URL
export function downloadDocumentUrl(datasetId: string, documentId: string): string {
  return `/api/v1/kb/datasets/${encodeURIComponent(datasetId)}/documents/${encodeURIComponent(documentId)}/download`;
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

