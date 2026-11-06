"""Adapters from authenticated MCP calls to knowledge-base core functions."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from fastapi import HTTPException

from app.api import kb
from app.mcp.common.context import McpContext
from app.mcp.common.errors import McpRuntimeError

logger = logging.getLogger(__name__)

TEXT_DOC_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".json", ".log", ".html", ".htm",
}
MAX_MCP_INLINE_BYTES = 2 * 1024 * 1024
MAX_MCP_BATCH_DOCS = 5
MAX_MCP_BATCH_BYTES = 8 * 1024 * 1024

#: 测试可替换的时钟/睡眠，避免真的等 2 秒。
_monotonic = time.monotonic
_sleep = asyncio.sleep


def _business_error(exc: HTTPException) -> McpRuntimeError:
    code = {
        403: "permission_denied",
        404: "not_found",
        409: "conflict",
        413: "file_too_large",
        422: "invalid_arguments",
    }.get(exc.status_code)
    if code is None:
        return McpRuntimeError("kb_unavailable", "知识库服务暂时不可用，请稍后重试。")
    detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
    return McpRuntimeError(code, detail)


async def _call(operation):
    try:
        return await operation
    except McpRuntimeError:
        raise
    except HTTPException as exc:
        raise _business_error(exc) from None
    except Exception:
        logger.exception("kb mcp adapter failure")
        raise McpRuntimeError("kb_unavailable", "知识库服务暂时不可用，请稍后重试。") from None


async def _require_dataset(dataset_id: str) -> dict[str, Any]:
    page = 1
    while page <= 5:
        items = await _call(kb._dataset_items(page=page, page_size=100))
        for item in items:
            if str(item.get("id") or "") == dataset_id:
                return item
        if len(items) < 100:
            break
        page += 1
    raise McpRuntimeError("not_found", "数据集不存在")


async def dataset_list(ctx: McpContext, *, page=1, page_size=50, keyword=""):
    if keyword:
        all_items = await _call(
            kb._dataset_items(page=1, page_size=500, keyword=keyword)
        )
        start = max(page - 1, 0) * page_size
        items = all_items[start:start + page_size]
        has_more = start + page_size < len(all_items)
    else:
        items = await _call(kb._dataset_items(page=page, page_size=page_size))
        has_more = len(items) == page_size
    return {"items": items, "page": page, "page_size": page_size, "has_more": has_more}


async def document_list(
    ctx: McpContext,
    *,
    dataset_id,
    page=1,
    page_size=30,
    orderby="create_time",
    desc=True,
    keywords="",
    run="",
):
    return await _call(
        kb.get_documents(
            dataset_id=dataset_id, page=page, page_size=page_size, orderby=orderby,
            desc=desc, keywords=keywords, run=run, _user=ctx.principal.user,
        )
    )


async def document_search(
    ctx: McpContext, *, keywords, dataset_id="", limit=200
):
    return await _call(
        kb.search_documents(
            keywords=keywords, dataset_id=dataset_id, limit=limit,
            _user=ctx.principal.user,
        )
    )


async def document_chunks(
    ctx: McpContext,
    *,
    dataset_id,
    document_id,
    page=1,
    page_size=100,
    keywords="",
):
    return await _call(
        kb.get_doc_chunks(
            dataset_id=dataset_id, document_id=document_id, page=page,
            page_size=page_size, keywords=keywords, _user=ctx.principal.user,
        )
    )


async def _status_document(dataset_id: str, document_id: str, name: str) -> dict:
    if name:
        data = await _call(
            kb.list_documents(dataset_id=dataset_id, page=1, page_size=100, keywords=name)
        )
        for doc in data.get("docs") or []:
            if doc.get("name") == name or str(doc.get("id") or "") == document_id:
                return doc
    if not document_id:
        raise McpRuntimeError("invalid_arguments", "document_id 或 name 至少提供一个")
    doc = await _call(kb._find_document(dataset_id, document_id))
    if not doc:
        raise McpRuntimeError("not_found", "文档不存在")
    return doc


async def document_status(
    ctx: McpContext,
    *,
    dataset_id,
    document_id="",
    name="",
    wait_seconds=0,
):
    deadline = _monotonic() + max(int(wait_seconds), 0)
    while True:
        doc = await _status_document(dataset_id, document_id, name)
        run = str(doc.get("run") or "UNSTART")
        finished = run in {"DONE", "FAIL", "CANCEL"}
        timed_out = wait_seconds > 0 and not finished and _monotonic() >= deadline
        if finished or timed_out or wait_seconds <= 0:
            return {
                "document_id": str(doc.get("id") or document_id),
                "name": str(doc.get("name") or name),
                "run": run,
                "progress": doc.get("progress", 0.0),
                "progress_msg": doc.get("progress_msg", ""),
                "chunk_count": doc.get("chunk_count", 0),
                "token_count": doc.get("token_count", 0),
                "timed_out": timed_out,
            }
        await _sleep(2)


async def search(
    ctx: McpContext,
    *,
    question,
    dataset_ids,
    document_ids=None,
    top_k=5,
    similarity_threshold=0.2,
    vector_similarity_weight=0.3,
    keyword=False,
    highlight=True,
    page_size=10,
):
    payload = kb.SearchIn(
        question=question,
        dataset_ids=dataset_ids,
        document_ids=document_ids or [],
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        vector_similarity_weight=vector_similarity_weight,
        keyword=keyword,
        highlight=highlight,
        page_size=page_size,
    )
    return await _call(kb.search(payload=payload, _user=ctx.principal.user))


async def health(ctx: McpContext):
    status, message = await _call(kb.probe())
    return {"status": status, "message": message}
