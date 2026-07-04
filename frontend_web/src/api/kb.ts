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

export async function listDatasets(): Promise<{ items: KbDataset[]; total: number }> {
  return (await request.get('/kb/datasets')) as { items: KbDataset[]; total: number };
}

export async function kbSearch(params: KbSearchParams): Promise<KbSearchResult> {
  return (await request.post('/kb/search', params)) as KbSearchResult;
}

export async function kbHealth(): Promise<{ status: string; message: string }> {
  return (await request.get('/kb/health')) as { status: string; message: string };
}
