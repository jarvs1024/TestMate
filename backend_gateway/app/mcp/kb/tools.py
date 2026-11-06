"""Explicit schemas and ToolSpec declarations for the knowledge-base domain."""
from __future__ import annotations

from typing import Any

from app.core.ragflow_client import CHUNK_METHODS, KB_LANGUAGES
from app.mcp.common.tool import ToolSpec
from app.mcp.kb import adapter


def _object(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


_STRING_LIST = {"type": "array", "items": {"type": "string"}}
_INT = {"type": "integer"}


READ_SPECS = (
    ToolSpec(
        name="kb_dataset_list",
        description="列出知识库数据集，支持分页与按名称/描述过滤。",
        input_schema=_object({
            "page": {**_INT, "minimum": 1, "default": 1},
            "page_size": {**_INT, "minimum": 1, "maximum": 100, "default": 50},
            "keyword": {"type": "string", "default": ""},
        }),
        scope="kb:read",
        read_only=True,
        handler=adapter.dataset_list,
    ),
    ToolSpec(
        name="kb_document_list",
        description="列出某个数据集下的文档，包含解析状态与上传者。",
        input_schema=_object({
            "dataset_id": {"type": "string", "minLength": 1},
            "page": {**_INT, "minimum": 1, "default": 1},
            "page_size": {**_INT, "minimum": 1, "maximum": 100, "default": 30},
            "orderby": {"type": "string", "default": "create_time"},
            "desc": {"type": "boolean", "default": True},
            "keywords": {"type": "string", "default": ""},
            "run": {"type": "string", "default": ""},
        }, ["dataset_id"]),
        scope="kb:read",
        read_only=True,
        handler=adapter.document_list,
    ),
    ToolSpec(
        name="kb_document_search",
        description="按文件名搜索文档，可跨数据集；只搜文件名，不搜内容。",
        input_schema=_object({
            "keywords": {"type": "string", "minLength": 1},
            "dataset_id": {"type": "string", "default": ""},
            "limit": {**_INT, "minimum": 1, "maximum": 500, "default": 200},
        }, ["keywords"]),
        scope="kb:read",
        read_only=True,
        handler=adapter.document_search,
    ),
    ToolSpec(
        name="kb_document_chunks",
        description="列出某篇文档的分段（chunks），用于查看检索命中内容。",
        input_schema=_object({
            "dataset_id": {"type": "string", "minLength": 1},
            "document_id": {"type": "string", "minLength": 1},
            "page": {**_INT, "minimum": 1, "default": 1},
            "page_size": {**_INT, "minimum": 1, "maximum": 100, "default": 100},
            "keywords": {"type": "string", "default": ""},
        }, ["dataset_id", "document_id"]),
        scope="kb:read",
        read_only=True,
        handler=adapter.document_chunks,
    ),
    ToolSpec(
        name="kb_document_status",
        description=(
            "查询文档解析状态（run: UNSTART/RUNNING/CANCEL/DONE/FAIL）。"
            "wait_seconds>0 时每 2 秒轮询一次；到点返回当前状态并置 timed_out=true，"
            "超时只表示还没解析完，不是失败。"
        ),
        input_schema=_object({
            "dataset_id": {"type": "string", "minLength": 1},
            "document_id": {"type": "string", "default": ""},
            "name": {"type": "string", "default": ""},
            "wait_seconds": {**_INT, "minimum": 0, "maximum": 60, "default": 0},
        }, ["dataset_id"]),
        scope="kb:read",
        read_only=True,
        handler=adapter.document_status,
    ),
    ToolSpec(
        name="kb_search",
        description="按问题对知识库做语义检索，返回命中的分段与文档聚合。",
        input_schema=_object({
            "question": {"type": "string", "minLength": 1},
            "dataset_ids": {**_STRING_LIST, "minItems": 1, "maxItems": 20},
            "document_ids": {**_STRING_LIST, "default": []},
            "top_k": {**_INT, "minimum": 1, "maximum": 20, "default": 5},
            "similarity_threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.2},
            "vector_similarity_weight": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.3},
            "keyword": {"type": "boolean", "default": False},
            "highlight": {"type": "boolean", "default": True},
            "page_size": {**_INT, "minimum": 1, "maximum": 50, "default": 10},
        }, ["question", "dataset_ids"]),
        scope="kb:read",
        read_only=True,
        handler=adapter.search,
    ),
    ToolSpec(
        name="kb_health",
        description="检查 RAGFlow 知识库服务是否可达。",
        input_schema=_object(),
        scope="kb:read",
        read_only=True,
        handler=adapter.health,
    ),
)

TOOL_SPECS = READ_SPECS
