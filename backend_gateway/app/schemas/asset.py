"""资产市场 Pydantic schemas."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AssetOut(BaseModel):
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
    # 最近一次审核意见 (驳回理由 / 审核备注)
    review_note: str = ""
    # 当前用户能不能审这个资产 (管理员或被授权的审核人) —— 前端据此显示审核按钮
    can_review: bool = False

    class Config:
        from_attributes = True


class AssetListOut(BaseModel):
    items: list[AssetOut]
    total: int


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


class AssetDeleteOut(BaseModel):
    """硬删结果."""

    ok: bool = True
    code: str = ""
    commit_sha: str = ""


class AssetNotificationOut(BaseModel):
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


class AssetJobOut(BaseModel):
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


class AssetAuditOut(BaseModel):
    id: int
    asset_id: int | None = None
    code: str = ""
    action: str
    actor_id: int | None = None
    actor_name: str = ""
    comment: str = ""
    detail: dict[str, Any] = {}
    created_at: datetime | None = None

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


class SyncStatusOut(BaseModel):
    """前端顶部状态条用."""

    has_remote_updates: bool = False
    conflict_count: int = 0
    pending_count: int = 0
    failed_count: int = 0
    unpublished_count: int = 0
    # 上架审核: 待审核 / 已驳回 的资产数 (管理员审核台的徽标)
    awaiting_review_count: int = 0
    rejected_count: int = 0
    # 我自己提交但还没通过审核的资产数 (待审核 + 已驳回)
    my_review_count: int = 0
    # 我自己提交的、还在等审核的资产数
    my_pending_count: int = 0
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
