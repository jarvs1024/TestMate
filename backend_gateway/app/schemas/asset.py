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
    bindings: dict[str, Any] = {}
    git_path: str = ""
    git_commit_sha: str = ""
    install_count: int = 0
    updated_at: datetime | None = None
    # 同步状态: staged / pushed / failed
    sync_status: str = "staged"
    last_error: str = ""
    # 生命周期: published / unpublished
    publish_status: str = "published"
    # 本地态
    installed: bool = False
    updatable: bool = False
    install_path: str = ""

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


class AssetInstallTargetOut(BaseModel):
    """前端点安装时先查这个: 本地安装目录 + 解析后的目标路径."""

    code: str
    kind: str
    version: str
    skill_dir: str
    plugin_dir: str
    target: str
    server_channel_available: bool = True


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


class SyncStatusOut(BaseModel):
    """前端顶部状态条用."""

    has_remote_updates: bool = False
    conflict_count: int = 0
    pending_count: int = 0
    failed_count: int = 0
    updatable_count: int = 0
    unpublished_count: int = 0
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
