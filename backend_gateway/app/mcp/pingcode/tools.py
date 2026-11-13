"""13 个 PingCode 工具的显式 schema 与 ToolSpec 声明."""
from __future__ import annotations

from typing import Any

from app.mcp.common.tool import ToolSpec
from app.mcp.pingcode import adapter


def _object(
    properties: dict[str, Any] | None = None, required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


_PROJECT_ID = {"type": "string", "description": "PingCode 项目 _id"}
_WORK_ITEM_TYPE_ID = {"type": "string", "description": "工单类型 _id"}
_PROPERTIES = {
    "type": "object",
    "description": (
        "字段 key -> 值; key 与选项 _id 见 get_property_schema。"
        "多选字段可传单个选项 _id 或数组, 日期字段传 Unix 秒"
    ),
}
_DESCRIPTION_TEMPLATE = {
    "type": "string",
    "enum": ["standard"],
    "description": "设为 standard 时按测试提单标准 10 段模板渲染描述，覆盖手写 description",
}
_DESCRIPTION_FIELDS = {
    "type": "object",
    "description": (
        "标准模板字段：featureModule 测试特性/开发模块, preconditions 预置条件, "
        "steps 关键操作步骤, expectedResult 预期效果, failurePhenomenon 测试失败现象, "
        "hostIp/hostSn/hostOs/hostSsdTopology 测试环境, fpgaVersion/fwVersion/driverVersion 版本信息, "
        "instrumentName/instrumentIpSn/instrumentVersion 测试仪器, softwareTools 软件工具, "
        "hwVersion/dutFwVersion/dutSn 被测设备, caseId/scriptInfo/scriptRepo/scriptModifications 测试用例信息, "
        "analysisTrace 定位履历, analyzer/initialReason/occurTime 初步分析结论, "
        "logSerial/logTrace/logOs/logTool 测试日志；未填字段渲染为 -"
    ),
}
_PAGE = {"type": "integer", "minimum": 1, "default": 1}
_PAGE_SIZE = {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}


READ_SPECS = (
    ToolSpec(
        name="pingcode_whoami",
        description="返回当前 TestMate 账号绑定的 PingCode 配置状态与最近登录结果，用于确认集成是否可用。",
        input_schema=_object(),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.whoami,
    ),
    ToolSpec(
        name="pingcode_list_projects",
        description="列出当前账号可提单的 PingCode 项目。",
        input_schema=_object(),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.list_projects,
    ),
    ToolSpec(
        name="pingcode_list_work_item_types",
        description="列出指定项目可创建的工单类型及其必填字段 key。",
        input_schema=_object({"project_id": _PROJECT_ID}, ["project_id"]),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.list_work_item_types,
    ),
    ToolSpec(
        name="pingcode_get_property_schema",
        description="返回工单字段定义（中文名、类型、是否必填、选项）。",
        input_schema=_object(
            {
                "project_id": _PROJECT_ID,
                "work_item_type_id": _WORK_ITEM_TYPE_ID,
                "project_template_type": {
                    "type": "string",
                    "description": "模板类型，默认 waterfall",
                },
            },
            ["project_id", "work_item_type_id"],
        ),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.get_property_schema,
    ),
    ToolSpec(
        name="pingcode_list_members",
        description="列出项目成员（提单时用于 assignee / participants）。",
        input_schema=_object({"project_id": _PROJECT_ID}, ["project_id"]),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.list_members,
    ),
    ToolSpec(
        name="pingcode_search_work_items",
        description=(
            "按项目与可选条件搜索工单/缺陷，返回精简列表（含状态/负责人/类型中文名）。"
            "state_id(s) 服务端过滤；type_id、assignee_id 本地过滤。"
        ),
        input_schema=_object(
            {
                "project_id": _PROJECT_ID,
                "project_identifier": {
                    "type": "string",
                    "description": "项目标识（如 TF2），可替代 project_id",
                },
                "keyword": {"type": "string", "description": "标题/编号关键字"},
                "type_id": {"type": "string", "description": "工单类型 id"},
                "state_id": {"type": "string", "description": "状态 id"},
                "state_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "状态 id 列表（多选，服务端过滤）",
                },
                "assignee_id": {"type": "string", "description": "负责人 uid（本地过滤）"},
                "updated_after": {"type": "number", "description": "更新时间下界 (Unix 秒)"},
                "page": _PAGE,
                "page_size": _PAGE_SIZE,
            }
        ),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.search_work_items,
    ),
    ToolSpec(
        name="pingcode_get_work_item",
        description=(
            "获取工单详情：属性（中文名+值）、描述 HTML/纯文本、内联截图（images）、"
            "附件（含可直接下载的 url+token）、评论数。id 与 identifier 至少给一个；"
            "identifier 形如 TF2-60 时自动解析项目。"
        ),
        input_schema=_object(
            {
                "id": {"type": "string", "description": "工单 _id"},
                "identifier": {"type": "string", "description": "工单编号，如 TF2-60"},
                "project_id": {
                    "type": "string",
                    "description": "仅按 identifier 查询时可用，用于搜索兜底（通常可省略）",
                },
            }
        ),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.get_work_item,
    ),
    ToolSpec(
        name="pingcode_list_comments",
        description="列出工单评论（富文本转纯文本，含作者名与评论内附件）。",
        input_schema=_object(
            {"id": {"type": "string", "description": "工单 _id"}, "page": _PAGE, "page_size": _PAGE_SIZE},
            ["id"],
        ),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.list_comments,
    ),
    ToolSpec(
        name="pingcode_list_attachments",
        description=(
            "列出工单附件（file_id、attachment_id、名称、大小、类型、可直接下载的 url 与 token）。"
            "数据来自工单详情的 references.attachments。"
        ),
        input_schema=_object({"id": {"type": "string"}}, ["id"]),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.list_attachments,
    ),
    ToolSpec(
        name="pingcode_download_attachment",
        description=(
            "下载附件或截图（自动跟随 302 到对象存储）。图片内联返回 base64，其它返回同源下载链接。"
            "list_attachments 返回的 url 已带 token，直接传入即可；描述里的截图可用 file_id（自动补 public token）。"
        ),
        input_schema=_object(
            {
                "url": {"type": "string", "description": "附件 URL，必须与 PingCode 同源"},
                "file_id": {"type": "string", "description": "atlas 文件 id"},
                "name": {"type": "string", "description": "文件名"},
                "max_bytes": {"type": "integer", "minimum": 1, "description": "上限，默认 20MB"},
                "token": {
                    "type": "string",
                    "description": "atlas 公共文件 token；省略时自动获取",
                },
            }
        ),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.download_attachment,
    ),
)

WRITE_SPECS = (
    ToolSpec(
        name="pingcode_preview_work_item",
        description="校验并组装建单 payload，不提交。用于提交前确认必填字段。",
        input_schema=_object(
            {
                "project_id": {"type": "string"},
                "work_item_type_id": {"type": "string"},
                "project_template_type": {"type": "string"},
                "properties": _PROPERTIES,
                "description_template": _DESCRIPTION_TEMPLATE,
                "description_fields": _DESCRIPTION_FIELDS,
            },
            ["project_id", "work_item_type_id", "properties"],
        ),
        scope="pingcode:write",
        read_only=True,
        handler=adapter.preview_work_item,
    ),
    ToolSpec(
        name="pingcode_create_work_item",
        description="创建 PingCode 工单。必须传 confirm=true；client_request_id 用于 10 分钟内幂等。",
        input_schema=_object(
            {
                "project_id": {"type": "string"},
                "work_item_type_id": {"type": "string"},
                "project_template_type": {"type": "string"},
                "properties": _PROPERTIES,
                "description_template": _DESCRIPTION_TEMPLATE,
                "description_fields": _DESCRIPTION_FIELDS,
                "confirm": {"type": "boolean"},
                "client_request_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "调用方生成的唯一 id，10 分钟内重复调用返回同一结果",
                },
            },
            [
                "project_id",
                "work_item_type_id",
                "properties",
                "confirm",
                "client_request_id",
            ],
        ),
        scope="pingcode:write",
        read_only=False,
        handler=adapter.create_work_item,
    ),
    ToolSpec(
        name="pingcode_add_comment",
        description="给工单添加评论。必须传 confirm=true。",
        input_schema=_object(
            {
                "id": {"type": "string"},
                "content": {"type": "string", "minLength": 1},
                "confirm": {"type": "boolean"},
            },
            ["id", "content", "confirm"],
        ),
        scope="pingcode:write",
        read_only=False,
        handler=adapter.add_comment,
    ),
)

TOOL_SPECS = READ_SPECS + WRITE_SPECS
