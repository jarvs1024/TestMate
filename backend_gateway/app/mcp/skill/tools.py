"""Explicit schemas and common-runtime registration specs for skill tools."""
from __future__ import annotations

from app.core.market_rules import CODE_MAX_LENGTH, CODE_MIN_LENGTH
from app.mcp.common.tool import ToolSpec
from app.mcp.skill import adapter


def _object(properties=None, required=None):
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


_CODE = {
    "type": "string",
    "minLength": CODE_MIN_LENGTH,
    "maxLength": CODE_MAX_LENGTH,
}
_CODE_ONLY = _object({"code": _CODE}, ["code"])
_VERSION = {"type": "string", "minLength": 1, "maxLength": 32}
_STRING_LIST = {"type": "array", "items": {"type": "string"}}
_OBJECT_VALUE = {"type": "object"}
_PACKAGE_CHOICE = [
    {"required": ["files"], "not": {"required": ["package_base64"]}},
    {"required": ["package_base64"], "not": {"required": ["files"]}},
]


def _metadata_properties(*, include_featured: bool) -> dict:
    properties = {
        "name": {"type": "string", "minLength": 1, "maxLength": 128},
        "icon": {"type": "string", "maxLength": 16},
        "summary": {"type": "string", "minLength": 1, "maxLength": 500},
        "description": {"type": "string"},
        "use_when": {"type": "string"},
        "not_for": {"type": "string"},
        "category": {"type": "string", "maxLength": 64},
        "project": {"type": "string", "maxLength": 32},
        "tags": _STRING_LIST,
        "keywords": _STRING_LIST,
        "permissions": _OBJECT_VALUE,
        "install_steps": _STRING_LIST,
        "bindings": _OBJECT_VALUE,
    }
    if include_featured:
        properties["featured"] = {"type": "boolean"}
    return properties


def _package_schema(properties: dict, required: list[str]) -> dict:
    properties.update(
        {
            "files": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"type": "string"},
            },
            "package_base64": {
                "type": "string",
                "minLength": 1,
                "contentEncoding": "base64",
            },
        }
    )
    schema = _object(properties, required)
    schema["oneOf"] = _PACKAGE_CHOICE
    return schema


def _edit_meta_schema() -> dict:
    properties = _metadata_properties(include_featured=False)
    schema = _object({"code": _CODE, **properties}, ["code"])
    schema["anyOf"] = [{"required": [field]} for field in sorted(properties)]
    return schema


TOOL_SPECS = (
    ToolSpec(
        name="skill_search",
        description="检索市场中可见的资产，支持关键字、分类、项目、标签、作者筛选与统一分页。",
        input_schema=_object(
            {
                "keyword": {"type": "string"},
                "category": {"type": "string"},
                "project": {"type": "string"},
                "tag": {"type": "string"},
                "author": {"type": "string"},
                "include_unpublished": {"type": "boolean", "default": False},
                "page": {"type": "integer", "minimum": 1, "default": 1},
                "page_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                },
            }
        ),
        scope="market:read",
        read_only=True,
        handler=adapter.search,
    ),
    ToolSpec(
        name="skill_get",
        description="获取可见资产的清单、安装数据、权限声明与绑定配置。",
        input_schema=_CODE_ONLY,
        scope="market:read",
        read_only=True,
        handler=adapter.get,
    ),
    ToolSpec(
        name="skill_read_doc",
        description="读取资产现有的 SKILL.md 或 README.md 文档。",
        input_schema=_CODE_ONLY,
        scope="market:read",
        read_only=True,
        handler=adapter.read_doc,
    ),
    ToolSpec(
        name="skill_list_files",
        description="列出可见资产包现有的文件树。",
        input_schema=_CODE_ONLY,
        scope="market:read",
        read_only=True,
        handler=adapter.list_files,
    ),
    ToolSpec(
        name="skill_read_file",
        description="按精确的相对路径读取可见资产包中的一个文本文件。",
        input_schema=_object(
            {
                "code": _CODE,
                "path": {"type": "string", "minLength": 1, "maxLength": 1024},
            },
            ["code", "path"],
        ),
        scope="market:read",
        read_only=True,
        handler=adapter.read_file,
    ),
    ToolSpec(
        name="skill_package_info",
        description="获取指定版本安装包的真实字节数与 SHA256 校验值。",
        input_schema=_object(
            {
                "code": _CODE,
                "version": {"type": "string", "minLength": 1, "maxLength": 32},
            },
            ["code"],
        ),
        scope="market:read",
        read_only=True,
        handler=adapter.package_info,
    ),
    ToolSpec(
        name="skill_categories",
        description="列出市场统一规则源中的全部分类。",
        input_schema=_object(),
        scope="market:read",
        read_only=True,
        handler=adapter.categories,
    ),
    ToolSpec(
        name="skill_projects",
        description="列出市场统一规则源中的全部项目。",
        input_schema=_object(),
        scope="market:read",
        read_only=True,
        handler=adapter.projects,
    ),
    ToolSpec(
        name="skill_job_status",
        description="查询市场任务状态，仅任务发起人或管理员可见。",
        input_schema=_object(
            {"job_id": {"type": "integer", "minimum": 1}}, ["job_id"]
        ),
        scope="market:read",
        read_only=True,
        handler=adapter.job_status,
    ),
    ToolSpec(
        name="skill_publish",
        description="发布新技能，需给出完整元信息，并只能选择一种安装包来源。",
        input_schema=_package_schema(
            {
                "code": _CODE,
                "version": _VERSION,
                **_metadata_properties(include_featured=True),
            },
            ["code", "name", "version", "summary"],
        ),
        scope="market:write",
        read_only=False,
        handler=adapter.publish,
    ),
    ToolSpec(
        name="skill_update",
        description="发布一个明确不同的新版本，未填写的元信息保持原值。",
        input_schema=_package_schema(
            {"code": _CODE, "version": _VERSION, **_metadata_properties(include_featured=True)},
            ["code", "version"],
        ),
        scope="market:write",
        read_only=False,
        handler=adapter.update,
    ),
    ToolSpec(
        name="skill_edit_meta",
        description="修改技能元信息，至少填写一个字段，不涉及安装包与版本。",
        input_schema=_edit_meta_schema(),
        scope="market:write",
        read_only=False,
        handler=adapter.edit_meta,
    ),
    ToolSpec(
        name="skill_submit_review",
        description="将本人技能提交到现有市场审核流程。",
        input_schema=_object(
            {"code": _CODE, "comment": {"type": "string"}}, ["code"]
        ),
        scope="market:write",
        read_only=False,
        handler=adapter.submit_review,
    ),
    ToolSpec(
        name="skill_unpublish_request",
        description="按市场审核开关的配置，申请下架或直接下架技能。",
        input_schema=_object(
            {"code": _CODE, "reason": {"type": "string"}}, ["code"]
        ),
        scope="market:write",
        read_only=False,
        handler=adapter.unpublish_request,
    ),
)
