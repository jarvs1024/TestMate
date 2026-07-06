"""RAGFlow API 客户端 — 配置从 DB 读, 兜底用 .env."""
from __future__ import annotations
import logging
from typing import Any

import httpx

from app.core.settings_store import get, _rewrite_loopback

logger = logging.getLogger(__name__)


async def _config() -> tuple[str, str]:
    """(base_url, api_key) 实时从 DB / 兜底 .env 读."""
    base = (await get("ragflow.base_url", "")) or ""
    key = (await get("ragflow.api_key", "")) or ""
    return _rewrite_loopback(base).rstrip("/"), key


async def _headers() -> dict[str, str]:
    _, key = await _config()
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def list_datasets(page: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return []
    url = f"{base}/datasets"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=await _headers(), params={"page": page, "page_size": page_size})
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
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
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
        r = await client.post(url, headers=await _headers(), json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow retrieval: {data.get('message') or data}")
        return data.get("data") or {"chunks": [], "doc_aggs": [], "total": 0}


async def probe() -> tuple[str, str]:
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return ("off", "未配置")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{base}/datasets?page=1&page_size=1", headers=await _headers())
            if r.status_code < 500 and r.json().get("code") == 0:
                return ("ok", "正常")
            return ("warn", f"HTTP {r.status_code}")
    except Exception as e:
        return ("off", f"不可达: {type(e).__name__}")
