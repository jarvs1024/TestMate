"""资产市场 Pydantic schemas."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.base import UTCModel


class AssetOut(UTCModel):
    code: str
    name: str
    icon: str
    kind: str
    version: str
    summary: str
    description: str = ""
    use_when: str = ""
    not_for: str = ""
    category: str = ""
    # 适用项目: 空 = 通用; "6100" = 6100 项目特有
    project: str = ""
    tags: list[str] = []
    keywords: list[str] = []
    author: str = ""
    featured: bool = False
    homepage: str | None = None
    permissions: dict[str, Any] = {}
    install_steps: list[str] = []
    # ⚠️ 只有连接器 (mcp) 有值 —— MCP 配置 (mcpServers), 非 mcp 恒为 None
    mcp_config: dict[str, Any] | None = None
    bindings: dict[str, Any] = {}
    git_path: str = ""
    git_commit_sha: str = ""
    # 资产在 GitLab 上的网页地址 (由 marketplace.git.web_url 拼出; 没配就为空)
    git_web_url: str = ""
    # 下载次数 (热门度) —— 与"是否安装"无关
    download_count: int = 0
    updated_at: datetime | None = None
    # 同步状态: staged / pushed / failed
    sync_status: str = "staged"
    last_error: str = ""
    # 生命周期: published / pending / rejected / unpublished
    publish_status: str = "published"
    # ⚠️ 2026-10-30 (第十二轮): 在等什么审核 —— new(新资产) / update(新版本) / meta(只改了信息).
    #    前端据此显示「📝 编辑信息待审」标记, 管理员才知道这是改简介还是上新包.
    pending_action: str = ""
    # 最近一次审核意见 (驳回理由 / 审核备注)
    review_note: str = ""
    # 当前用户能不能审这个资产 (管理员或被授权的审核人) —— 前端据此显示审核按钮
    can_review: bool = False

    class Config:
        from_attributes = True


class AssetListOut(BaseModel):
    items: list[AssetOut]
    total: int
    # ⚠️ 2026-10-31 (第十九轮): 两个**恒定计数** —— chip 上的数字不该跟着筛选跳.
    #
    #   all_total  = 忽略 category 的可见资产数 (受 kind / q / project / 可见性口径影响)
    #   mine_total = 当前用户作为作者的资产数 (同口径, 不受 category 影响)
    #
    #   以前 chip 上的「全部 N」用的是前端拿到的列表长度 —— 一选「👤 我的」,
    #   那个长度就变成"我的"条数, 「全部 N」跟着变 → 用户完全不知道库里有多少.
    all_total: int = 0
    mine_total: int = 0


class AssetFileNode(BaseModel):
    name: str
    path: str
    type: str          # tree | blob
    size: int | None = None


class AssetFilesOut(BaseModel):
    code: str
    git_path: str
    files: list[AssetFileNode]


class AssetDocOut(BaseModel):
    """详情页展示用的文档正文 (SKILL.md / README.md)."""

    kind: str
    filename: str
    frontmatter: dict[str, Any] = {}
    content: str = ""


class AssetFileContent(BaseModel):
    """前端写盘用的单文件内容 (已解压的明文, 无需前端再解包)."""

    path: str
    encoding: str = "text"      # text | base64
    content: str = ""


class AssetFileBundleOut(BaseModel):
    """前端通道安装用: 整包的文件清单 + 内容."""

    code: str
    version: str
    files: list[AssetFileContent]
    total: int


class PackagePreviewOut(BaseModel):
    """上传前的包体检结果.

    上传对话框选好压缩包后先体检: 能不能解开、有没有展示文档、能不能安装、
    有没有可疑文件 —— 免得填完整张表单才在提交时被 422 拦下.
    """

    ok: bool = False
    filename: str = ""
    size_bytes: int = 0
    kind: str = ""
    total_files: int = 0
    files: list[str] = []
    doc_file: str = ""
    has_skill_md: bool = False
    has_plugin_manifest: bool = False
    has_mcp_config: bool = False
    installable: bool = False
    block_reason: str = ""
    issues: list[str] = []
    # 敏感文件 / 路径越界等安全提示
    warnings: list[str] = []


class MarketConfigOut(BaseModel):
    """市场当前**生效**的配置 (只读) —— 设置页用来展示"仓库在哪 / 装到哪 / 谁能发"."""

    workspace: str = ""
    remote: str = ""
    branch: str = ""
    web_url: str = ""
    skill_dir: str = ""
    plugin_dir: str = ""
    install_enabled: bool = True
    is_repo: bool = False
    head: str = ""
    # ⚠️ 审核总开关的**生效值** —— 前端要用它改按钮文案与确认提示
    #    ("申请下架" vs "下架"), 免得用户点了才发现走的是另一条路.
    review_enabled: bool = True


class AssetDeleteOut(BaseModel):
    """硬删结果."""

    ok: bool = True
    code: str = ""
    commit_sha: str = ""


class AssetNotificationOut(UTCModel):
    """钉钉通知的回执 (送达记录)."""

    id: int
    event: str = ""
    code: str = ""
    asset_name: str = ""
    status: str = "pending"       # pending | sent | failed
    attempts: int = 0
    error: str = ""
    last_attempt_at: datetime | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class AssetNotificationListOut(BaseModel):
    items: list[AssetNotificationOut]
    total: int


class NotifyPreviewOut(BaseModel):
    """通知消息的**预览** (2026-10-30) —— 只渲染, **不发送**.

    ⚠️ 让管理员能看见消息长什么样, 而不用往**公司真实群**里发测试消息.
    """

    event: str
    label: str
    title: str
    text: str
    lines: list[str]


class AssetJobOut(UTCModel):
    id: int
    action: str
    status: str
    code: str
    asset_name: str = ""
    kind: str = ""
    git_path: str = ""
    commit_sha: str = ""
    error: str = ""
    attempts: int = 0
    staged_at: datetime | None = None
    pushed_at: datetime | None = None
    next_retry_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class AssetJobListOut(BaseModel):
    items: list[AssetJobOut]
    total: int


class AssetAuditOut(UTCModel):
    id: int
    asset_id: int | None = None
    code: str = ""
    action: str
    actor_id: int | None = None
    actor_name: str = ""
    comment: str = ""
    detail: dict[str, Any] = {}
    created_at: datetime | None = None
    # ⚠️ 动作的中文说明 —— 由**后端**给 (见 market_state.audit_action_label).
    #    前端原来自己翻译了一份, 结果漏了几个动作、还多一个永远不会出现的,
    #    同一个动作三套说法 —— 中文只有一个真源, 前端直接渲染.
    action_label: str = ""

    class Config:
        from_attributes = True


class AssetAuditListOut(BaseModel):
    items: list[AssetAuditOut]
    total: int


class UploadAssetIn(BaseModel):
    """上传表单字段 (文件本体走 multipart)."""

    code: str = Field(..., min_length=3, max_length=64)
    kind: str = Field(..., description="plugin | skill | mcp")
    name: str = Field(..., min_length=1, max_length=128)
    version: str = Field("0.1.0", max_length=32)
    summary: str = Field(..., min_length=1, max_length=500)
    description: str = ""
    use_when: str = ""
    not_for: str = ""
    category: str = ""
    # 适用项目: 空 = 通用; "6100" = 6100 项目特有 (列表见设置项 marketplace.projects)
    project: str = ""
    icon: str = "🧩"
    tags: list[str] = []
    keywords: list[str] = []
    author: str = ""
    featured: bool = False
    homepage: str | None = None
    permissions: dict[str, Any] = {}
    install_steps: list[str] = []
    bindings: dict[str, Any] = {}
    # ⚠️ 连接器 (mcp) 的 MCP 配置 —— **只有连接器才有**.
    #    (漏了这个字段, pydantic 会**静默丢掉**它, 连接器就变成"没有配置")
    mcp_config: dict[str, Any] | None = None


class AssetMetaUpdateIn(BaseModel):
    """**只改元信息** —— 不碰安装包, 不发新版本 (2026-10-30).

    ⚠️ 为什么要有这个端点: 原来的 `PUT /assets/{code}` 是"发新版本",
       **必须传安装包** (连接器除外) —— 用户只想改个简介/标签都得上传一遍包,
       而且传上去的就是新版本号. 现在多一条"只改说明"的路.

    ⚠️ **不含 version / 文件相关字段** —— 版本号归"发新版本"管,
       这里改了会让"这一版到底是哪个包"对不上.
    ⚠️ 全部字段默认 None = **不改** (不是"清空") —— 传了才生效.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    icon: str | None = Field(default=None, max_length=16)
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    use_when: str | None = None
    not_for: str | None = None
    category: str | None = Field(default=None, max_length=64)
    # 适用项目 (空 = 通用) —— 见 UploadAssetIn.project
    project: str | None = Field(default=None, max_length=32)
    tags: list[str] | None = None
    keywords: list[str] | None = None
    permissions: dict[str, Any] | None = None
    install_steps: list[str] | None = None
    bindings: dict[str, Any] | None = None
    # 连接器 (mcp) 的 MCP 配置 —— 只有连接器才有 (后端会校验)
    mcp_config: dict[str, Any] | None = None


class SyncStatusOut(UTCModel):
    """前端顶部状态条用."""

    has_remote_updates: bool = False
    conflict_count: int = 0
    pending_count: int = 0
    failed_count: int = 0
    unpublished_count: int = 0
    # 上架审核: 待审核 / 已驳回 的资产数 (管理员审核台的徽标)
    awaiting_review_count: int = 0
    # ⚠️ 2026-10-30 (第十二轮): 其中「**只改了信息**」的那部分 (包没变, 不急)
    awaiting_meta_count: int = 0
    rejected_count: int = 0
    # 我自己提交但还没通过审核的资产数 (待审核 + 已驳回)
    my_review_count: int = 0
    # 我自己提交的、还在等审核的资产数
    my_pending_count: int = 0
    # ⚠️ 2026-10-30 (第十二轮): 我自己提交的、**只改了信息**在等审核的数 (包没变)
    my_meta_count: int = 0
    # 下架审核: 申请下架、等人确认的资产数 (确认后资产会被彻底删除)
    unpublish_pending_count: int = 0
    # 我自己申请下架、还在等管理员确认的资产数
    my_unpublish_count: int = 0
    last_sync_at: datetime | None = None


class SyncOut(BaseModel):
    ok: bool
    added: int
    updated: int
    index_present: bool
    gitlab: str = ""


class ProbeOut(BaseModel):
    ok: bool
    status: str
    message: str
