"""Explicit schemas and common-runtime registration specs for extension tools."""
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
_KIND = {"type": "string", "enum": ["skill", "plugin", "mcp"]}
_MCP_CONFIG = {"type": "object"}
_PACKAGE_CHOICE = [
    {"required": ["files"], "not": {"required": ["package_base64"]}},
    {"required": ["package_base64"], "not": {"required": ["files"]}},
]
_CONNECTOR_RULE = {
    "if": {"properties": {"kind": {"const": "mcp"}}, "required": ["kind"]},
    "then": {
        "required": ["mcp_config"],
        "not": {"anyOf": [{"required": ["files"]}, {"required": ["package_base64"]}]},
    },
    "else": {"oneOf": _PACKAGE_CHOICE, "not": {"required": ["mcp_config"]}},
}


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
            "kind": _KIND,
            "mcp_config": _MCP_CONFIG,
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
    schema["allOf"] = [_CONNECTOR_RULE]
    return schema


def _edit_meta_schema() -> dict:
    properties = _metadata_properties(include_featured=False)
    properties["mcp_config"] = _MCP_CONFIG
    schema = _object({"code": _CODE, **properties}, ["code"])
    schema["anyOf"] = [{"required": [field]} for field in sorted(properties)]
    return schema


TOOL_SPECS = (
    ToolSpec(
        name="extension_search",
        description="检索扩展（技能 / 插件 / 连接），支持按类型、关键字、分类、项目、标签、作者筛选与分页。",
        input_schema=_object(
            {
                "kind": _KIND,
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
        scope="extensions:read",
        read_only=True,
        handler=adapter.search,
    ),
    ToolSpec(
        name="extension_get",
        description="获取可见扩展的清单、安装数据、权限声明与绑定配置。",
        input_schema=_CODE_ONLY,
        scope="extensions:read",
        read_only=True,
        handler=adapter.get,
    ),
    ToolSpec(
        name="extension_read_doc",
        description="读取扩展现有文档：技能为 SKILL.md，插件为 README.md，连接器没有文档。",
        input_schema=_CODE_ONLY,
        scope="extensions:read",
        read_only=True,
        handler=adapter.read_doc,
    ),
    ToolSpec(
        name="extension_list_files",
        description="列出可见扩展包现有的文件树。",
        input_schema=_CODE_ONLY,
        scope="extensions:read",
        read_only=True,
        handler=adapter.list_files,
    ),
    ToolSpec(
        name="extension_read_file",
        description="按精确的相对路径读取可见扩展包中的一个文本文件。",
        input_schema=_object(
            {
                "code": _CODE,
                "path": {"type": "string", "minLength": 1, "maxLength": 1024},
            },
            ["code", "path"],
        ),
        scope="extensions:read",
        read_only=True,
        handler=adapter.read_file,
    ),
    ToolSpec(
        name="extension_package_info",
        description="获取指定版本安装包的真实字节数与 SHA256 校验值（连接器没有安装包）。",
        input_schema=_object(
            {
                "code": _CODE,
                "version": {"type": "string", "minLength": 1, "maxLength": 32},
            },
            ["code"],
        ),
        scope="extensions:read",
        read_only=True,
        handler=adapter.package_info,
    ),
    ToolSpec(
        name="extension_categories",
        description="列出扩展统一规则源中的全部分类。",
        input_schema=_object(),
        scope="extensions:read",
        read_only=True,
        handler=adapter.categories,
    ),
    ToolSpec(
        name="extension_projects",
        description="列出扩展统一规则源中的全部项目。",
        input_schema=_object(),
        scope="extensions:read",
        read_only=True,
        handler=adapter.projects,
    ),
    ToolSpec(
        name="extension_job_status",
        description="查询扩展任务状态，仅任务发起人或管理员可见。",
        input_schema=_object(
            {"job_id": {"type": "integer", "minimum": 1}}, ["job_id"]
        ),
        scope="extensions:read",
        read_only=True,
        handler=adapter.job_status,
    ),
    ToolSpec(
        name="extension_publish",
        description="发布新扩展（kind 默认 skill）：技能 / 插件需提供唯一安装包，连接器只需 mcp_config。",
        input_schema=_package_schema(
            {
                "code": _CODE,
                "version": _VERSION,
                **_metadata_properties(include_featured=True),
            },
            ["code", "name", "version", "summary"],
        ),
        scope="extensions:write",
        read_only=False,
        handler=adapter.publish,
    ),
    ToolSpec(
        name="extension_update",
        description="发布一个明确不同的新版本：技能 / 插件需提供新安装包，连接器只更新 mcp_config。",
        input_schema=_package_schema(
            {"code": _CODE, "version": _VERSION, **_metadata_properties(include_featured=True)},
            ["code", "version"],
        ),
        scope="extensions:write",
        read_only=False,
        handler=adapter.update,
    ),
    ToolSpec(
        name="extension_edit_meta",
        description="修改扩展元信息，至少填写一个字段，不涉及安装包与版本；连接器可改 mcp_config。",
        input_schema=_edit_meta_schema(),
        scope="extensions:write",
        read_only=False,
        handler=adapter.edit_meta,
    ),
    ToolSpec(
        name="extension_submit_review",
        description="将本人扩展提交到现有审核流程。",
        input_schema=_object(
            {"code": _CODE, "comment": {"type": "string"}}, ["code"]
        ),
        scope="extensions:write",
        read_only=False,
        handler=adapter.submit_review,
    ),
    ToolSpec(
        name="extension_unpublish_request",
        description="按审核开关的配置，申请下架或直接下架扩展。",
        input_schema=_object(
            {"code": _CODE, "reason": {"type": "string"}}, ["code"]
        ),
        scope="extensions:write",
        read_only=False,
        handler=adapter.unpublish_request,
    ),
)
