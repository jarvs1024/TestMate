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
from app.core.ragflow_client import (
    list_datasets, retrieval, probe,
    list_documents, ingest_documents, delete_documents,
    list_doc_chunks,
)
from app.models.user import User
from app.models.user import UserRole

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
                # P1: 多放一些字段, 前端可展示 embedding_model / 权限 / 切片参数等
                "embedding_model": d.get("embedding_model", ""),
                "permission": d.get("permission", "me"),
                "status": d.get("status", "1"),
                "language": d.get("language", ""),
                "token_num": d.get("token_num", 0),
                "similarity_threshold": d.get("similarity_threshold", 0.2),
                "vector_similarity_weight": d.get("vector_similarity_weight", 0.3),
                "pagerank": d.get("pagerank", 0),
                "update_date": d.get("update_date", ""),
                "create_time": d.get("create_time", 0),
                "update_time": d.get("update_time", 0),
                "parser_config": d.get("parser_config") or {},
            }
            for d in items
        ]
        return {"items": cleaned, "total": len(cleaned)}
    except Exception as e:
        logger.exception("list_datasets failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")





# ============ Documents (P2: 数据集下文档列表 / 重跑 / 删除) ============

@router.get("/datasets/{dataset_id}/documents")
@router.get("/datasets/{dataset_id}/documents/{document_id}/chunks")
async def get_doc_chunks(
    dataset_id: str,
    document_id: str,
    page: int = 1,
    page_size: int = 100,
    keywords: str = "",
    _user: User = Depends(get_current_user),
) -> dict:
    """列出某 document 下的 chunks (代理 RAGFlow).

    注意: RAGFlow API 限制 page_size <= 100. 前端想要看完整分段列表应自己分页.
    """
    # 兜底: 防止前端传超过 100
    if page_size > 100:
        page_size = 100
    if page_size < 1:
        page_size = 30
    try:
        data = await list_doc_chunks(dataset_id, document_id, page=page, page_size=page_size, keywords=keywords)
        # 精简 chunks: content 不裁, 但去掉 content_ltks (很大)
        chunks = data.get("chunks") or []
        cleaned = []
        for c in chunks:
            cleaned.append({
                "id": c.get("id"),
                "content": c.get("content", ""),
                "docnm_kwd": c.get("docnm_kwd", ""),
                "document_id": c.get("document_id"),
                "available": c.get("available", True),
                "image_id": c.get("image_id", ""),
                "important_keywords": c.get("important_keywords", []),
                "tag_kwd": c.get("tag_kwd", []),
                "positions": c.get("positions", []),
                "create_time": c.get("create_time", ""),
                "create_timestamp": c.get("create_timestamp", 0),
            })
        return {
            "chunks": cleaned,
            "total": data.get("total", len(cleaned)),
            "doc": data.get("doc") or {},
        }
    except Exception as e:
        logger.exception("list_doc_chunks failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")



class IngestIn(BaseModel):
    doc_ids: list[str] = Field(..., min_length=1)
    run: str = Field("1", description="1=start, 2=cancel")
    delete: bool = False


@router.post("/datasets/{dataset_id}/documents/ingest")
async def ingest(
    dataset_id: str,
    payload: IngestIn,
    user: User = Depends(get_current_user),
) -> dict:
    """启动/取消文档解析. admin only."""
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="admin only")
    try:
        ok = await ingest_documents(payload.doc_ids, run=payload.run, delete=payload.delete)
        return {"ok": ok}
    except Exception as e:
        logger.exception("ingest failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")


class DeleteDocsIn(BaseModel):
    ids: list[str] | None = None
    delete_all: bool = False


@router.delete("/datasets/{dataset_id}/documents")
async def delete_docs(
    dataset_id: str,
    payload: DeleteDocsIn,
    user: User = Depends(get_current_user),
) -> dict:
    """删除 dataset 下的文档. admin only."""
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="admin only")
    try:
        ok = await delete_documents(dataset_id, doc_ids=payload.ids, delete_all=payload.delete_all)
        return {"ok": ok}
    except Exception as e:
        logger.exception("delete_docs failed")
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
