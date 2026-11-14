"""14 个 PLM 工具的显式 schema 与 ToolSpec 声明 (对齐 AiTestX)."""
from __future__ import annotations

from typing import Any

from app.mcp.common.tool import ToolSpec
from app.mcp.plm import adapter


def _object(
    properties: dict[str, Any] | None = None, required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


_PROJECT_ID = {
    "type": "string",
    "description": "PLM 项目 id (先用 plm_common_list_projects 查询)",
}
_PROJECT_CODE = {
    "type": "string",
    "description": "PLM 项目编码, 如 TIANFU, 与 project_id 二选一",
}
_PAGE = {"type": "integer", "minimum": 1, "default": 1}
_PAGE_SIZE = {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}
_OPTION = {
    "type": "string",
    "description": "下拉选项 id; 取值见 plm_issue_get_create_meta 的 options, 传中文名会被拒绝",
}
_ATTACHMENT = {
    "type": "object",
    "description": "附件: name 文件名, content_base64 文件内容 base64; 单个≤10MB, 合计≤20MB, 最多 3 个",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "content_base64": {"type": "string", "minLength": 1},
    },
    "required": ["name", "content_base64"],
    "additionalProperties": False,
}

_CREATE_PROPERTIES: dict[str, Any] = {
    "name": {"type": "string", "minLength": 1, "description": "问题标题"},
    "project_id": _PROJECT_ID,
    "project_code": _PROJECT_CODE,
    "questionCgrId": {
        "type": "string",
        "minLength": 1,
        "description": "问题类型 id; 必须是字典中的有效 id, 否则无法生成 WSD 单号并拒绝提单",
    },
    "raisePerson": {
        "type": "string",
        "minLength": 1,
        "description": "下一步处理人人员 id; 用 plm_common_search_members 查询, 提单后会反查确认已写入",
    },
    "raisePerson_name": {"type": "string", "description": "处理人姓名 (仅用于展示)"},
    "quesBelongArea": dict(_OPTION, description="问题归属领域选项 id (必填)"),
    "QuesmoduleSel": dict(_OPTION, description="问题模块选项 id (必填)"),
    "projectJD": dict(_OPTION, description="项目阶段选项 id (必填), 如 3=TR3, 8=GA"),
    "questionTdArea": dict(_OPTION, description="提单领域选项 id (必填)"),
    "questionPriority": dict(_OPTION, description="优先级选项 id (必填): 1=P1 … 32=P32, 0=P0"),
    "quesSever": dict(_OPTION, description="严重程度选项 id (必填): 1 致命 / 2 严重 / 3 一般 / 4 提示"),
    "attribute2": {"type": "string", "minLength": 1, "description": "固件版本 (必填)"},
    "genyinfenxi": {"type": "string", "description": "产品型号, 省略时默认 NA"},
    "attribute1": {"type": "string", "description": "产品类别, 省略时默认 NA"},
    "description": {
        "type": "string",
        "description": "问题描述 (支持 HTML); 省略时用标题生成段落",
    },
    "attachments": {"type": "array", "items": _ATTACHMENT, "maxItems": 3},
    "confirm": {"type": "boolean", "description": "必须为 true 才会提交"},
    "client_request_id": {
        "type": "string",
        "minLength": 1,
        "description": "调用方生成的唯一 id, 10 分钟内重复调用返回同一结果",
    },
}

_CREATE_REQUIRED = ["confirm"]


READ_SPECS = (
    ToolSpec(
        name="plm_common_whoami",
        description="返回当前 TestMate 账号绑定的 PLM 配置状态与最近登录结果, 用于确认集成是否可用。",
        input_schema=_object(),
        scope="plm:read",
        read_only=True,
        handler=adapter.whoami,
    ),
    ToolSpec(
        name="plm_common_list_projects",
        description=(
            "列出当前账号名下可关联的 PLM 项目 (我名下项目)。"
            "PLM 建单必须关联项目, 用返回的 id 或 code 作为 project_id / project_code。"
        ),
        input_schema=_object(
            {
                "keyword": {"type": "string", "description": "按项目编码/名称过滤"},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 50, "default": 50},
            }
        ),
        scope="plm:read",
        read_only=True,
        handler=adapter.list_projects,
    ),
    ToolSpec(
        name="plm_issue_get_create_meta",
        description=(
            "返回建单必填字段、下拉选项 id、可关联项目与建单提示。"
            "创建问题单前必须先调用本工具获取 questionCgrId / raisePerson / 各下拉选项的合法 id。"
        ),
        input_schema=_object(
            {
                "project_keyword": {"type": "string", "description": "按项目编码/名称过滤项目列表"},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 50, "default": 50},
            }
        ),
        scope="plm:read",
        read_only=True,
        handler=adapter.get_create_meta,
    ),
    ToolSpec(
        name="plm_common_search_members",
        description="按关键字搜索 PLM 人员字典, 用于获取下一步处理人 raisePerson。",
        input_schema=_object(
            {
                "keyword": {"type": "string", "description": "姓名/工号关键字"},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 50, "default": 30},
            }
        ),
        scope="plm:read",
        read_only=True,
        handler=adapter.search_members,
    ),
    ToolSpec(
        name="plm_issue_search",
        description=(
            "搜索 PLM 问题单, 返回单号、标题、状态、处理人、优先级等精简字段。"
            "status 可传状态 id 或状态名; updated_after 支持 Unix 秒或 ISO 时间。"
        ),
        input_schema=_object(
            {
                "keyword": {"type": "string", "description": "标题关键字"},
                "code": {"type": "string", "description": "问题单号, 如 WSD202511130001"},
                "status": {"type": "string", "description": "状态 id 或状态名"},
                "raise_person_id": {"type": "string", "description": "处理人人员 id"},
                "updated_after": {
                    "type": ["string", "number"],
                    "description": "更新时间下界 (Unix 秒 / 毫秒或 ISO 时间)",
                },
                "page": _PAGE,
                "page_size": _PAGE_SIZE,
            }
        ),
        scope="plm:read",
        read_only=True,
        handler=adapter.search_questions,
    ),
    ToolSpec(
        name="plm_issue_get",
        description=(
            "获取问题单详情: 字段(中文名+值)、描述 HTML/纯文本、内联截图(images)、"
            "附件(含可直接下载的 url/file_id)、评论数。id 与 code 至少给一个。"
        ),
        input_schema=_object(
            {
                "id": {"type": "string", "description": "问题单内部 id"},
                "code": {"type": "string", "description": "问题单号, 如 WSD202511130001"},
                "include_raw": {"type": "boolean", "description": "附带原始字段值"},
            }
        ),
        scope="plm:read",
        read_only=True,
        handler=adapter.get_question,
    ),
    ToolSpec(
        name="plm_issue_list_comments",
        description="列出问题单评论 (作者、时间、纯文本内容与评论内附件)。",
        input_schema=_object(
            {
                "id": {"type": "string", "description": "问题单内部 id"},
                "code": {"type": "string", "description": "问题单号 (可选)"},
                "page": _PAGE,
                "page_size": _PAGE_SIZE,
            },
            ["id"],
        ),
        scope="plm:read",
        read_only=True,
        handler=adapter.list_comments,
    ),
    ToolSpec(
        name="plm_issue_list_attachments",
        description=(
            "列出问题单附件与内嵌到字段/描述里的截图 (file_id、名称、大小、类型、下载 url)。"
            "id 与 code 至少给一个。"
        ),
        input_schema=_object(
            {
                "id": {"type": "string", "description": "问题单内部 id"},
                "code": {"type": "string", "description": "问题单号"},
            }
        ),
        scope="plm:read",
        read_only=True,
        handler=adapter.list_attachments,
    ),
    ToolSpec(
        name="plm_issue_download_attachment",
        description=(
            "下载 PLM 附件或截图。url 必须与 PLM 同源; 也可传 file_id 由服务端解析下载地址。"
            "图片内联返回 base64, 其它类型返回同源下载地址。"
        ),
        input_schema=_object(
            {
                "url": {"type": "string", "description": "附件地址, 必须与 PLM 同源"},
                "file_id": {"type": "string", "description": "文件 id"},
                "name": {"type": "string", "description": "文件名"},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "大小上限, 默认 20MB, 最大 100MB",
                },
            }
        ),
        scope="plm:read",
        read_only=True,
        handler=adapter.download_attachment,
    ),
    ToolSpec(
        name="plm_case_search",
        description=(
            "搜索 PLM 用例库, 按编号/标题/目录过滤, 返回用例编号、标题、模块与预置条件。"
            "identifier 传完整编号或纯数字。"
        ),
        input_schema=_object(
            {
                "keyword": {"type": "string", "description": "用例标题关键字"},
                "identifier": {"type": "string", "description": "用例编号, 如 HIMA3361-8077"},
                "category": {"type": "string", "description": "用例目录/模块关键字"},
                "page": _PAGE,
                "page_size": _PAGE_SIZE,
            }
        ),
        scope="plm:read",
        read_only=True,
        handler=adapter.search_test_cases,
    ),
    ToolSpec(
        name="plm_case_get",
        description=(
            "按编号获取 PLM 用例详情 (预置条件、步骤与预期结果、所属模块与状态)。"
            "identifier 支持完整编号 HIMA3361-8077 或纯数字 8077。"
        ),
        input_schema=_object(
            {
                "identifier": {"type": "string", "minLength": 1, "description": "用例编号"},
                "include_raw": {"type": "boolean", "description": "附带原始字段值"},
            },
            ["identifier"],
        ),
        scope="plm:read",
        read_only=True,
        handler=adapter.get_test_case,
    ),
)

WRITE_SPECS = (
    ToolSpec(
        name="plm_issue_preview",
        description=(
            "校验并组装建单 payload, 不提交。用于提交前确认项目已关联、必填字段与选项合法。"
            "字段同 plm_issue_create (confirm 除外)。"
        ),
        input_schema=_object(
            {key: value for key, value in _CREATE_PROPERTIES.items() if key not in {"confirm", "client_request_id"}}
        ),
        scope="plm:write",
        read_only=True,
        handler=adapter.preview_question,
    ),
    ToolSpec(
        name="plm_issue_create",
        description=(
            "创建 PLM 问题单。严格校验: 必须关联项目 (project_id/project_code)、问题类型必须有效并能预占 WSD 单号、"
            "必须指定处理人 raisePerson; 必填属性必须填写且下拉选项必须合规, 否则直接拒绝; "
            "保存后会反查单号与处理人, 未落库或处理人未写入时返回 plm_verify_failed。"
            "先调用 plm_issue_get_create_meta 获取字段与选项 id; 必须传 confirm=true; "
            "client_request_id 用于 10 分钟内幂等。"
        ),
        input_schema=_object(_CREATE_PROPERTIES, _CREATE_REQUIRED),
        scope="plm:write",
        read_only=False,
        handler=adapter.create_question,
    ),
    ToolSpec(
        name="plm_issue_add_comment",
        description="给 PLM 问题单添加评论。必须传 confirm=true。",
        input_schema=_object(
            {
                "id": {"type": "string", "description": "问题单内部 id"},
                "code": {"type": "string", "description": "问题单号 (可选)"},
                "content": {"type": "string", "minLength": 1, "description": "评论内容"},
                "confirm": {"type": "boolean"},
            },
            ["id", "content", "confirm"],
        ),
        scope="plm:write",
        read_only=False,
        handler=adapter.add_comment,
    ),
)

TOOL_SPECS = READ_SPECS + WRITE_SPECS
