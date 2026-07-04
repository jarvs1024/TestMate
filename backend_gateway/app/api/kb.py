"""知识库 — 代理 RAGFlow。

提供:
- GET  /api/v1/kb/datasets        列出 RAGFlow datasets
- POST /api/v1/kb/search          检索 (代理 RAGFlow /retrieval)
- GET  /api/v1/kb/health          健康检查
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.core.ragflow_client import list_datasets, retrieval, probe
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/datasets")
async def get_datasets(_user: User = Depends(get_current_user)) -> dict:
    """列出 RAGFlow datasets (代理)."""
    try:
        items = await list_datasets()
        # 精简: 去掉大字段 (avatar / create_time / update_time)
        cleaned = [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "description": d.get("description", ""),
                "chunk_count": d.get("chunk_count", 0),
                "document_count": d.get("document_count", 0),
                "chunk_method": d.get("chunk_method", ""),
                "create_date": d.get("create_date", ""),
            }
            for d in items
        ]
        return {"items": cleaned, "total": len(cleaned)}
    except Exception as e:
        logger.exception("list_datasets failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")


class SearchIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    dataset_ids: list[str] = Field(..., min_length=1, description="至少 1 个 dataset")
    document_ids: list[str] | None = None
    top_k: int = 5
    similarity_threshold: float = 0.2
    vector_similarity_weight: float = 0.3
    keyword: bool = False
    highlight: bool = True
    page_size: int = 10


@router.post("/search")
async def search(payload: SearchIn, _user: User = Depends(get_current_user)) -> dict:
    """RAGFlow 检索代理."""
    try:
        data = await retrieval(
            question=payload.question,
            dataset_ids=payload.dataset_ids,
            document_ids=payload.document_ids,
            top_k=payload.top_k,
            similarity_threshold=payload.similarity_threshold,
            vector_similarity_weight=payload.vector_similarity_weight,
            keyword=payload.keyword,
            highlight=payload.highlight,
            page_size=payload.page_size,
        )
        # 精简 chunks: 去掉 content_ltks (很大, 前端不用)
        chunks = data.get("chunks", [])
        cleaned = []
        for c in chunks:
            cleaned.append({
                "id": c.get("id"),
                "content": c.get("content", ""),
                "highlight": c.get("highlight") or c.get("content", ""),
                "dataset_id": c.get("dataset_id"),
                "document_id": c.get("document_id"),
                "document_keyword": c.get("document_keyword", ""),
                "positions": c.get("positions", []),
                "similarity": c.get("similarity", 0.0),
                "vector_similarity": c.get("vector_similarity", 0.0),
                "term_similarity": c.get("term_similarity", 0.0),
                "tag_kwd": c.get("tag_kwd", []),
            })
        return {
            "total": data.get("total", len(cleaned)),
            "chunks": cleaned,
            "doc_aggs": data.get("doc_aggs", []),
            "elapsed_ms": data.get("elapsed_ms", 0),
        }
    except Exception as e:
        logger.exception("search failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")


@router.get("/health")
async def health() -> dict:
    status, msg = await probe()
    return {"status": status, "message": msg}
