"""知识库 — 代理 RAGFlow。

提供:
- GET  /api/v1/kb/datasets        列出 RAGFlow datasets
- POST /api/v1/kb/search          检索 (代理 RAGFlow /retrieval)
- GET  /api/v1/kb/health          健康检查
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Response
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

@router.api_route("/share-embed/{path:path}", methods=["GET"])
async def share_embed_proxy(path: str = "", theme: str = "light", shared_id: str = "ea62499872bb11f1a82f771aafbe4f81") -> Response:
    """代理 RAGFlow 共享搜索页 + 静态资源.

    浏览器访问 /api/v1/kb/share-embed/search/share?shared_id=xxx&theme=dark
    后端去 RAGFlow 拉 HTML, 在 <head> 注入 localStorage 主题, 再透传.

    RAGFlow HTML 里的 /entry/ /chunk/ /assets/ 静态资源由前端 nginx 在
    /api/v1/kb/share-embed/{path} 透传 (nginx 配 /share-embed/ 反代到 RAGFlow 端口 18080).
    """
    import httpx
    # 透传到 RAGFlow
    if path:
        # 子资源: /entry/.../xxx.js, /chunk/.../xxx.js, /assets/.../xxx.css 等
        target_url = f"http://host.docker.internal:18080/{path}"
    else:
        target_url = f"http://host.docker.internal:18080/search/share?shared_id={shared_id}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(target_url)
        r.raise_for_status()
        content = r.content
        content_type = r.headers.get("content-type", "application/octet-stream")

    # 仅对 HTML 注入 localStorage 主题
    if "text/html" in content_type:
        html = content.decode("utf-8", errors="ignore")
        inject = (
            "<script>(function(){"
            "try{var t='" + theme + "';"
            "localStorage.setItem('ragflow-ui-theme',t);"
            "localStorage.setItem('ragflow-ui-theme-mode',t);}catch(e){}"
            "})();</script>"
        )
        if "</head>" in html:
            html = html.replace("</head>", inject + "</head>", 1)
        else:
            html = inject + html
        return Response(content=html, media_type="text/html; charset=utf-8")

    return Response(content=content, media_type=content_type)
