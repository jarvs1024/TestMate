"""RAGFlow API 客户端。

P0 简化: 列表 datasets + 检索 retrieval,够用即可。
"""
from __future__ import annotations
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _base_url() -> str:
    """从 settings 读 base url, 如果是 mock 占位则返回 None 标记不可用."""
    u = (settings.RAGFLOW_BASE_URL or "").rstrip("/")
    if not u or "xxxxx" in settings.RAGFLOW_API_KEY or "mock" in settings.RAGFLOW_API_KEY:
        return ""
    return u


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.RAGFLOW_API_KEY}",
        "Content-Type": "application/json",
    }


async def list_datasets(page: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
    """列出当前 API key 可访问的数据集."""
    base = _base_url()
    if not base:
        return []
    url = f"{base}/datasets"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=_headers(), params={"page": page, "page_size": page_size})
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow list_datasets: {data.get('message') or data}")
        return data.get("data") or []


async def retrieval(
    question: str,
    dataset_ids: list[str],
    document_ids: list[str] | None = None,
    top_k: int = 5,
    similarity_threshold: float = 0.2,
    vector_similarity_weight: float = 0.3,
    keyword: bool = False,
    highlight: bool = True,
    page_size: int = 10,
) -> dict[str, Any]:
    """RAGFlow 检索接口.

    返回 RAGFlow data 块: { chunks: [...], doc_aggs: [...], total: N }
    """
    base = _base_url()
    if not base:
        return {"chunks": [], "doc_aggs": [], "total": 0, "_mock": True}
    url = f"{base}/retrieval"
    body: dict[str, Any] = {
        "question": question,
        "dataset_ids": dataset_ids,
        "top_k": top_k,
        "similarity_threshold": similarity_threshold,
        "vector_similarity_weight": vector_similarity_weight,
        "keyword": keyword,
        "highlight": highlight,
        "page_size": page_size,
    }
    if document_ids:
        body["document_ids"] = document_ids
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=_headers(), json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow retrieval: {data.get('message') or data}")
        return data.get("data") or {"chunks": [], "doc_aggs": [], "total": 0}


async def probe() -> tuple[str, str]:
    """健康检查: 返 ('ok' | 'warn' | 'off', message)."""
    base = _base_url()
    if not base:
        return ("off", "未配置")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{base}/datasets?page=1&page_size=1", headers=_headers())
            if r.status_code < 500 and r.json().get("code") == 0:
                return ("ok", "正常")
            return ("warn", f"HTTP {r.status_code}")
    except Exception as e:
        return ("off", f"不可达: {type(e).__name__}")
