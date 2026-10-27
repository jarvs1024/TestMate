"""软件库 Pydantic schemas."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SoftwareVersionOut(BaseModel):
    """一个版本的对外形状 —— 详情页的"版本历史"用它."""

    id: int
    version: str
    release_notes: str = ""
    file_name: str = ""
    file_size: int = 0
    sha256: str = ""
    # 版本状态: awaiting_file(在等文件) / ready(可下载) / failed(上传中断)
    status: str = "awaiting_file"
    # 上次失败的原因 (status=failed 时有值)
    last_error: str = ""
    author: str = ""
    download_count: int = 0
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class SoftwareOut(BaseModel):
    """软件条目 —— 卡片与列表用它."""

    code: str
    name: str
    icon: str = "🧰"
    version: str = ""
    summary: str = ""
    description: str = ""
    # 展示功能 (这个软件能干什么)
    features: list[str] = []
    # 适用场景 / 不适合的场景
    use_when: str = ""
    not_for: str = ""
    platform: str = ""
    category: str = ""
    tags: list[str] = []
    keywords: list[str] = []
    author: str = ""
    download_count: int = 0
    # 生命周期: awaiting_file / published / hidden
    publish_status: str = "awaiting_file"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # 当前用户能不能改这个条目 (作者本人或管理员) —— 前端据此显示按钮
    can_edit: bool = False
    # 当前**可下载**的版本号 (最新的 ready 版本) —— 空 = 还没有能下的文件.
    # ⚠️ 跟 version (指针) 不是一回事: 指针可能已经切到"正在上传"的新版本.
    download_version: str = ""

    class Config:
        from_attributes = True


class SoftwareListOut(BaseModel):
    items: list[SoftwareOut]
    total: int


class SoftwareDetailOut(SoftwareOut):
    """详情 = 条目 + 版本历史."""

    versions: list[SoftwareVersionOut] = []


class SoftwareCategoryOut(BaseModel):
    """分类 (后端下发, 前端动态渲染 chip)."""

    name: str
    total: int = 0


class SoftwareCategoryListOut(BaseModel):
    items: list[SoftwareCategoryOut]
    total: int = 0


class SoftwareConfigOut(BaseModel):
    """前端要知道的运行时配置."""

    # 单个软件包的上限 (字节)
    max_bytes: int = 0
    # 当前用户能不能上传
    can_publish: bool = False
    # 当前用户是不是管理员 (决定能不能看存储路径)
    is_admin: bool = False
    # 匿名能不能下载
    public_download: bool = False
    # 存储根目录 (**仅 admin 可见**, 其他角色拿到空串)
    storage_root: str = ""
    # 当前根目录是**哪来的**: setting(设置项) / env(环境变量) / default(兜底)
    # ⚠️ 为什么要有这个: "我改了设置项怎么没生效" 是最常见的问法 ——
    #    实际多半是环境变量把它盖住了, 光看路径猜不出来.
    storage_source: str = ""
    # 存储根是否可用 (可写) —— admin 看到的健康信号
    path_ok: bool = False
    # 已占用的字节数
    used_bytes: int = 0
    # 磁盘剩余字节数
    free_bytes: int = 0


class SoftwareCreateIn(BaseModel):
    """建条目 (JSON 元数据) —— 文件随后用 PUT /{code}/file 传."""

    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    icon: str = Field(default="🧰", max_length=16)
    version: str = Field(default="", max_length=32)
    summary: str = Field(default="", max_length=500)
    description: str = ""
    features: list[str] = []
    use_when: str = ""
    not_for: str = ""
    platform: str = Field(default="", max_length=32)
    category: str = Field(default="", max_length=64)
    tags: list[str] = []
    keywords: list[str] = []
    # 原始文件名 (清洗前) —— 后端会清洗
    file_name: str = Field(default="", max_length=255)
    # 声明的文件大小 —— 实收对不上 → 409 (文件不完整)
    file_size: int = Field(default=0, ge=0)
    release_notes: str = ""


class SoftwareUpdateIn(BaseModel):
    """改元信息 (不动文件)."""

    name: str | None = Field(default=None, max_length=128)
    icon: str | None = Field(default=None, max_length=16)
    summary: str | None = Field(default=None, max_length=500)
    description: str | None = None
    features: list[str] | None = None
    use_when: str | None = None
    not_for: str | None = None
    platform: str | None = Field(default=None, max_length=32)
    category: str | None = Field(default=None, max_length=64)
    tags: list[str] | None = None
    keywords: list[str] | None = None


class SoftwareVersionCreateIn(BaseModel):
    """发新版本."""

    version: str = Field(min_length=1, max_length=32)
    release_notes: str = ""
    file_name: str = Field(default="", max_length=255)
    file_size: int = Field(default=0, ge=0)


class SoftwareUploadOut(BaseModel):
    """传完文件后的回执."""

    ok: bool = True
    code: str
    version: str
    size: int = 0
    sha256: str = ""


class SoftwareDownloadTicketOut(BaseModel):
    """短时下载票."""

    url: str
    expires_in: int = 600


class SoftwareDeleteOut(BaseModel):
    ok: bool = True
    code: str
    deleted_files: int = 0
