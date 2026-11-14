"""18 个 PingCode 工具的显式 schema 与 ToolSpec 声明."""
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
_LIBRARY_ID = {
    "type": "string",
    "description": "用例库 _id；先用 pingcode_case_list_libraries 查询",
}
_CASE_FILTERS = {
    "type": "array",
    "description": (
        "字段筛选，对应网页筛选器的 criteria.conditions。property_key 为字段 key，"
        "operation 透传网页抓包值（常见 6=属于），value 为值数组，"
        "logic 1=且（默认）、2=或；字段与选项 _id 用 pingcode_case_get_properties 解析。"
        "人员字段（created_by/updated_by）的 value 元素传裸 uid 或 {\"id\": uid, \"type\": 1}，"
        "字符串会按 uid 自动包装"
    ),
    "items": {
        "type": "object",
        "properties": {
            "property_key": {"type": "string"},
            "operation": {"type": "integer"},
            "value": {"type": "array"},
            "logic": {"type": "integer"},
            "id": {"type": "string", "description": "条件 id，可选"},
        },
        "required": ["property_key", "operation"],
        "additionalProperties": False,
    },
}


READ_SPECS = (
    ToolSpec(
        name="pingcode_common_whoami",
        description=(
            "返回当前 TestMate 账号绑定的 PingCode 配置状态、最近登录结果，"
            "以及真实登录的 PingCode 用户（user: uid/name/display_name/email/mobile）。"
            "username 只是登录账号，user 才是登录后的成员身份。"
        ),
        input_schema=_object(),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.whoami,
    ),
    ToolSpec(
        name="pingcode_common_list_projects",
        description="列出当前账号可提单的 PingCode 项目。",
        input_schema=_object(),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.list_projects,
    ),
    ToolSpec(
        name="pingcode_issue_list_types",
        description="列出指定项目可创建的工单类型及其必填字段 key。",
        input_schema=_object({"project_id": _PROJECT_ID}, ["project_id"]),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.list_work_item_types,
    ),
    ToolSpec(
        name="pingcode_issue_get_schema",
        description=(
            "返回工单字段定义（中文名、类型、是否必填、选项），必填项按项目自身的字段模板解析。"
            "work_item_type_id 必须是该项目可创建的类型，否则直接拒绝并列出可选类型；"
            "可先调用 pingcode_issue_list_types 获取。返回 template_type 与 used_global_fallback（全局兜底时为 true）。"
        ),
        input_schema=_object(
            {
                "project_id": _PROJECT_ID,
                "work_item_type_id": _WORK_ITEM_TYPE_ID,
                "project_template_type": {
                    "type": "string",
                    "description": "模板类型；省略时按项目自身的 template_type 解析",
                },
            },
            ["project_id", "work_item_type_id"],
        ),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.get_issue_schema,
    ),
    ToolSpec(
        name="pingcode_common_list_members",
        description="列出项目成员（提单时用于 assignee / participants）。",
        input_schema=_object({"project_id": _PROJECT_ID}, ["project_id"]),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.list_members,
    ),
    ToolSpec(
        name="pingcode_issue_search",
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
        name="pingcode_issue_get",
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
        name="pingcode_issue_list_comments",
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
        name="pingcode_issue_list_attachments",
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
        name="pingcode_case_list_libraries",
        description=(
            "列出当前账号可见的 PingCode 测试用例库（testhub），返回 _id、名称、identifier 与描述。"
            "上游列表接口不提供 project_id/case_count（实际为 null）。后续用例工具必须传 library_id。"
        ),
        input_schema=_object(),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.list_test_case_libraries,
    ),
    ToolSpec(
        name="pingcode_case_search",
        description=(
            "在指定 PingCode 测试用例库中按编号/标题搜索用例，支持网页筛选器同款字段条件，"
            "以及 created_by/updated_by 人员筛选（人名或 uid，多人用逗号分隔）。"
            "identifier 传完整编号（如 HIMA3361-8077）或纯数字；返回用例编号、标题与预置条件。"
        ),
        input_schema=_object(
            {
                "library_id": _LIBRARY_ID,
                "keyword": {"type": "string", "description": "标题关键字"},
                "identifier": {
                    "type": "string",
                    "description": "用例编号，如 HIMA3361-8077（也接受纯数字 8077）",
                },
                "filters": _CASE_FILTERS,
                "created_by": {
                    "type": "string",
                    "description": "创建人：显示名/登录名或 uid，多人用逗号/空格分隔",
                },
                "updated_by": {
                    "type": "string",
                    "description": "更新人：显示名/登录名或 uid，多人用逗号/空格分隔",
                },
                "page": _PAGE,
                "page_size": _PAGE_SIZE,
            },
            ["library_id"],
        ),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.search_test_cases,
    ),
    ToolSpec(
        name="pingcode_case_get",
        description=(
            "按编号获取测试用例详情（预置条件、步骤与预期结果），并解析状态名与用例目录名。"
            "编号支持完整形式 HIMA3361-8077 或纯数字 8077。"
        ),
        input_schema=_object(
            {
                "identifier": {
                    "type": "string",
                    "description": "用例编号，如 HIMA3361-8077",
                },
                "library_id": _LIBRARY_ID,
                "include_raw": {
                    "type": "boolean",
                    "description": "是否附带原始字段（创建人/更新人/时间等）",
                },
            },
            ["library_id", "identifier"],
        ),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.get_test_case,
    ),
    ToolSpec(
        name="pingcode_case_get_properties",
        description=(
            "获取用例库字段字典：字段 key、中文名、类型与选项 _id↔text，"
            "用于把筛选字段/选项名解析成 pingcode_case_search 的 filters。"
        ),
        input_schema=_object({"library_id": _LIBRARY_ID}, ["library_id"]),
        scope="pingcode:read",
        read_only=True,
        handler=adapter.get_test_case_properties,
    ),
    ToolSpec(
        name="pingcode_issue_download_attachment",
        description=(
            "下载附件或截图（自动跟随 302 到对象存储）。图片内联返回 base64，其它返回同源下载链接。"
            "附件请传 pingcode_issue_list_attachments 返回的 url（已带 token）；"
            "file_id 仅适用于描述中 /atlas/files/public/ 引用的内联截图，"
            "传 file_id 下载附件会失败并提示改用 url。"
        ),
        input_schema=_object(
            {
                "url": {"type": "string", "description": "附件 URL，必须与 PingCode 同源"},
                "file_id": {"type": "string", "description": "atlas 文件 id；仅用于描述中的内联截图，附件请改用 url"},
                "name": {"type": "string", "description": "文件名"},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "上限，默认 20MB，最大 100MB",
                },
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
        name="pingcode_issue_preview",
        description=(
            "校验并组装建单 payload，不提交。必填项按 project_id 所属项目自身的字段模板判定，"
            "不同项目可能不同；项目不可提单时报错，项目自带模板但取不到时也报错，"
            "只有共用全局模板的项目（is_local_configure=0）才用全局模板。"
            "返回 ok、missing_fields 与 invalid_fields：缺少必填或选项非法时列出字段中文名、类型提示与合法选项 _id。"
        ),
        input_schema=_object(
            {
                "project_id": {"type": "string"},
                "work_item_type_id": {"type": "string"},
                "project_template_type": {
                    "type": "string",
                    "description": "模板类型；省略时按项目自身的 template_type 解析",
                },
                "properties": _PROPERTIES,
                "description_template": _DESCRIPTION_TEMPLATE,
                "description_fields": _DESCRIPTION_FIELDS,
            },
            ["project_id", "work_item_type_id"],
        ),
        scope="pingcode:write",
        read_only=True,
        handler=adapter.preview_work_item,
    ),
    ToolSpec(
        name="pingcode_issue_create",
        description="创建 PingCode 工单。负责人 assignee 必填；提交前按项目字段模板校验必填项与选项值，不合法直接拒绝并列出字段中文名、类型提示与合法选项 _id（先调用 pingcode_issue_get_schema 查询）；attachments 传已上传的 file_id 列表，建单后自动关联；必须传 confirm=true；client_request_id 用于 10 分钟内幂等。",
        input_schema=_object(
            {
                "project_id": {"type": "string"},
                "work_item_type_id": {"type": "string"},
                "project_template_type": {
                    "type": "string",
                    "description": "模板类型；省略时按项目自身的 template_type 解析",
                },
                "properties": _PROPERTIES,
                "description_template": _DESCRIPTION_TEMPLATE,
                "description_fields": _DESCRIPTION_FIELDS,
                "attachments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "建单后关联的附件 file_id 列表，file_id 由 pingcode_issue_upload_attachment 返回",
                },
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
                "confirm",
                "client_request_id",
            ],
        ),
        scope="pingcode:write",
        read_only=False,
        handler=adapter.create_work_item,
    ),
    ToolSpec(
        name="pingcode_issue_add_comment",
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
    ToolSpec(
        name="pingcode_issue_upload_attachment",
        description=(
            "上传附件或内联图片（单文件上限 100MB）。path 与 content_base64 二选一；"
            "purpose=attachment 上传为工单附件并可传 work_item_id 立即关联，"
            "purpose=inline 返回可插入描述 HTML 的 public_url；必须传 confirm=true；"
            "client_request_id 用于 10 分钟内幂等。"
        ),
        input_schema=_object(
            {
                "path": {
                    "type": "string",
                    "description": "后端主机上的文件路径，与 content_base64 二选一",
                },
                "content_base64": {
                    "type": "string",
                    "description": "文件内容的 base64，与 path 二选一",
                },
                "name": {
                    "type": "string",
                    "description": "文件名（决定 content-type 与下载名），默认取 path 的文件名",
                },
                "purpose": {
                    "type": "string",
                    "enum": ["attachment", "inline"],
                    "default": "attachment",
                    "description": "attachment=工单附件(scope=1); inline=描述内嵌图(scope=3)",
                },
                "work_item_id": {
                    "type": "string",
                    "description": "上传后立即关联的工单 _id，仅 purpose=attachment 可用",
                },
                "client_request_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "调用方生成的唯一 id，10 分钟内重复调用返回同一结果",
                },
                "confirm": {"type": "boolean"},
            },
            ["confirm"],
        ),
        scope="pingcode:write",
        read_only=False,
        handler=adapter.upload_attachment,
    ),
)

TOOL_SPECS = READ_SPECS + WRITE_SPECS
