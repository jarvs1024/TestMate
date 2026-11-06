"""Adapters from authenticated MCP calls to knowledge-base core functions."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from app.api import kb
from app.core.security import create_kb_upload_ticket
from app.mcp.common.context import McpContext
from app.mcp.common.errors import McpRuntimeError
from app.mcp.common.oauth import resolve_public_base

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
        if name:
            raise McpRuntimeError("not_found", "文档不存在")
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
        await _sleep(max(0.0, min(2.0, deadline - _monotonic())))


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


# ============ 文本写工具 (2026-11-06 Task 7) ============
# ⚠️ 写工具的成功语义是**已提交**, 不是解析成功 —— 解析结果让调用方去
#    kb_document_status 查, adapter 绝不等待 / 绝不谎报 DONE.


def _upload_items(name, content, content_type, documents):
    if documents is not None:
        if not 1 <= len(documents) <= MAX_MCP_BATCH_DOCS:
            raise McpRuntimeError("invalid_arguments", "documents 需为 1..5 篇")
        return [dict(item) for item in documents]
    if name is None or content is None:
        raise McpRuntimeError("invalid_arguments", "请提供 name+content 或 documents 数组")
    item = {"name": name, "content": content}
    if content_type is not None:
        item["content_type"] = content_type
    return [item]


def _prepare_text(name: str, content: str, content_type: str | None):
    # ⚠️ 顺序不能反: `_sanitize_kb_filename` 是**按 200 字符**截断的 ——
    #    先洗后裁, `"a"*260 + ".md"` 会被截成 200 个 a, 扩展名没了,
    #    然后误报「请用上传票」. 先用 `_fit_kb_name_bytes` 按字节裁到
    #    `MAX_KB_FILE_NAME_LEN` (它保扩展名), 洗的时候就不会再截第二次.
    clean = kb._sanitize_kb_filename(
        kb._fit_kb_name_bytes(name, kb.MAX_KB_FILE_NAME_LEN), "document"
    )
    ext = os.path.splitext(clean.lower())[1]
    if ext not in TEXT_DOC_EXTENSIONS:
        raise McpRuntimeError(
            "invalid_document_type",
            "文本工具只支持 .txt/.md/.markdown/.csv/.json/.log/.html/.htm；"
            "二进制文件请用 kb_document_write_ticket 签票后直传。",
        )
    payload = (content or "").encode("utf-8")
    if not payload:
        raise McpRuntimeError("invalid_arguments", "文件内容是空的")
    if len(payload) > MAX_MCP_INLINE_BYTES:
        raise McpRuntimeError(
            "file_too_large", "单篇文本超过 2 MB，请改用 kb_document_write_ticket 签票后直传。"
        )
    return clean, payload, content_type or "text/plain; charset=utf-8"


def _write_result(
    docs, errors, ingest_started, warnings, *, count_key="uploaded", replaced=None
):
    state = "submitted" if not errors else ("failed" if not docs else "partial")
    result = {
        "ok": not errors,
        "state": state,
        count_key: len(docs),
        "failed": len(errors),
        "ingest_started": ingest_started,
        "warning": " ".join(dict.fromkeys(warnings)),
        "docs": docs,
        "errors": errors,
    }
    if replaced is not None:
        result["replaced"] = replaced
    return result


async def dataset_create(
    ctx: McpContext, *, name, description="", chunk_method="naive", language="Chinese"
):
    payload = kb.CreateDatasetIn(
        name=name, description=description, chunk_method=chunk_method, language=language
    )
    return await _call(kb.create_kb_dataset(payload=payload, user=ctx.principal.user))


async def document_upload(
    ctx: McpContext,
    *,
    dataset_id,
    name=None,
    content=None,
    content_type=None,
    documents=None,
):
    items = _upload_items(name, content, content_type, documents)
    await _require_dataset(dataset_id)

    prepared = []
    errors = []
    for index, item in enumerate(items):
        label = str(item.get("name") or f"doc-{index + 1}")
        try:
            prepared.append(
                (index, _prepare_text(label, str(item.get("content") or ""), item.get("content_type")))
            )
        except McpRuntimeError as exc:
            errors.append({"name": label, "error": exc.code, "message": exc.message})
    if sum(len(payload) for _, (_, payload, _) in prepared) > MAX_MCP_BATCH_BYTES:
        raise McpRuntimeError(
            "file_too_large", "本次文本总量超过 8 MB，请分批上传或改用上传票。"
        )

    docs, warnings, ingest_started = [], [], False
    for _, file_tuple in prepared:
        try:
            result = await _call(
                kb.upload_prepared_documents(dataset_id, [file_tuple], ctx.principal.user)
            )
        except McpRuntimeError as exc:
            errors.append(
                {"name": file_tuple[0], "error": exc.code, "message": exc.message}
            )
            continue
        # ⚠️ RAGFlow 返回空 data 时 `upload_prepared_documents` 仍是 ok=True/uploaded=0
        #    (kb.py:835-847) —— 那是「零提交」, 不能当成功报给调用方.
        if not result.get("docs"):
            errors.append(
                {
                    "name": file_tuple[0],
                    "error": "kb_unavailable",
                    "message": "知识库服务暂时不可用，请稍后重试。",
                }
            )
            continue
        # 每篇有自己的 ingest_started —— 顶层只做 OR, 调用方要靠它定位「哪篇没起解析」.
        doc_ingest = bool(result.get("ingest_started"))
        ingest_started = ingest_started or doc_ingest
        if result.get("warning"):
            warnings.append(str(result["warning"]))
        for doc in result.get("docs") or []:
            docs.append(
                {
                    "document_id": doc.get("id"),
                    "name": doc.get("name"),
                    "state": "submitted",
                    "run": doc.get("run", "UNSTART"),
                    "size": doc.get("size", 0),
                    "ingest_started": doc_ingest,
                }
            )
    return _write_result(docs, errors, ingest_started, warnings)


async def document_update(
    ctx: McpContext,
    *,
    dataset_id,
    document_id=None,
    content=None,
    documents=None,
):
    if documents is not None:
        if not 1 <= len(documents) <= MAX_MCP_BATCH_DOCS:
            raise McpRuntimeError("invalid_arguments", "documents 需为 1..5 篇")
        items = [dict(item) for item in documents]
    else:
        if document_id is None or content is None:
            raise McpRuntimeError(
                "invalid_arguments", "请提供 document_id+content 或 documents 数组"
            )
        items = [{"document_id": document_id, "content": content}]
    await _require_dataset(dataset_id)

    total_bytes = sum(
        len(str(item.get("content") or "").encode("utf-8")) for item in items
    )
    if total_bytes > MAX_MCP_BATCH_BYTES:
        raise McpRuntimeError(
            "file_too_large", "本次文本总量超过 8 MB，请分批更新或改用上传票。"
        )

    docs, errors, warnings = [], [], []
    replaced_ids: list[str] = []
    ingest_started = False
    for item in items:
        old_id = str(item.get("document_id") or "")
        try:
            old = await _call(kb._find_document(dataset_id, old_id))
            if not old:
                raise McpRuntimeError("not_found", "文档不存在")
            name, payload, ctype = _prepare_text(
                str(old.get("name") or ""), str(item.get("content") or ""), None
            )
            result = await _call(
                kb.replace_document(
                    dataset_id, old_id, name, payload, ctype, ctx.principal.user
                )
            )
        except McpRuntimeError as exc:
            errors.append(
                {"document_id": old_id, "name": "", "error": exc.code, "message": exc.message}
            )
            continue
        doc_ingest = bool(result.get("ingest_started"))
        ingest_started = ingest_started or doc_ingest
        if result.get("warning"):
            warnings.append(str(result["warning"]))
        updated = result.get("updated") or {}
        docs.append(
            {
                "document_id": updated.get("id"),
                "name": updated.get("name"),
                "state": "submitted",
                "run": updated.get("run", "UNSTART"),
                "size": updated.get("size", 0),
                "ingest_started": doc_ingest,
            }
        )
        replaced_ids.append(old_id)

    # 规格只要求「替换成功后多返回 replaced」—— 一篇都没成功就不该出现这个键.
    replaced = None
    if replaced_ids:
        replaced = replaced_ids[0] if len(items) == 1 else replaced_ids
    return _write_result(
        docs, errors, ingest_started, warnings, count_key="updated", replaced=replaced
    )


async def document_reparse(ctx: McpContext, *, dataset_id, document_id):
    # 先确认数据集存在 —— 否则未知 dataset 会被 `_find_document` 报成「文档不存在」.
    await _require_dataset(dataset_id)
    result = await _call(
        kb.reparse_kb_document(
            dataset_id=dataset_id, document_id=document_id, user=ctx.principal.user
        )
    )
    doc = await _call(kb._find_document(dataset_id, document_id)) or {}
    name = result.get("name") or doc.get("name") or ""
    run = str(doc.get("run") or "UNSTART")
    return {
        "ok": True,
        "state": "submitted",
        "document_id": document_id,
        "name": name,
        "run": run,
        "ingest_started": True,
        "warning": "",
        "docs": [
            {
                "document_id": document_id,
                "name": name,
                "state": "submitted",
                "run": run,
                "size": doc.get("size", 0),
                "ingest_started": True,
            }
        ],
        "errors": [],
    }


# ============ 上传票工具 (2026-11-06 Task 8) ============
# ⚠️ 票是「数据集级 + 30 分钟可复用」的: 二进制文件走 curl -F 直传,
#    不经过 MCP 通道 (base64 会膨胀 + 撑爆 JSON 请求体).


async def document_write_ticket(ctx: McpContext, *, dataset_id):
    await _require_dataset(dataset_id)
    base = (await resolve_public_base()).strip().rstrip("/")
    if not base:
        raise McpRuntimeError(
            "kb_unavailable", "无法确定上传地址，请联系管理员配置 extensions.public_base_url。"
        )
    ticket, expires_in = create_kb_upload_ticket(
        user_id=int(ctx.principal.user.id),
        token_version=int(ctx.principal.user.token_version or 0),
        dataset_id=dataset_id,
    )
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    return {
        "ticket": ticket,
        "upload_url": f"{base}/api/v1/kb/datasets/{dataset_id}/documents/ticket-upload",
        "method": "POST",
        "file_field": "file",
        "replace_field": "document_id",
        "expires_in": expires_in,
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        "max_bytes_per_file": kb.MAX_UPLOAD_BYTES,
        "max_files_per_request": kb.MAX_UPLOAD_FILES,
        "reusable": True,
        "note": (
            "30 分钟内可复用；上传多篇就重复 -F file；替换时加 -F document_id=<id>。"
            "批量超过 30 分钟就重新签票，已传文件不受影响。"
        ),
    }
