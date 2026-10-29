"""软件库 Pydantic schemas."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.base import UTCModel


class SoftwareVersionOut(UTCModel):
    """一个版本的对外形状 —— 详情页的"版本历史"用它."""

    id: int
    version: str
    release_notes: str = ""
    # 变体标签 (选填) —— 如「Windows版」「LTS版」. 一个软件挂两个版本时,
    # 光看版本号分不清谁是谁, 标签就是那个"小名".
    variant: str = ""
    # 是否是**推荐下载**的版本 —— 头部那个「⬇ 下载」按钮下的是它.
    is_default: bool = False
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


class SoftwareOut(UTCModel):
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
    # 安装说明 / 注意事项 —— **选填**, 详情页有则显示、无则不占位
    install_steps: str = ""
    caveats: str = ""
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
    # 已被占用的图标: {emoji: 软件名}
    # ⚠️ 为什么要有这个 (2026-10-28): 图标**不能跟别的软件重复** ——
    #    两张卡长得一模一样, 用户根本分不清谁是谁. 前端拿它把已占用的图标
    #    标成"已用"并禁掉, 后端再兜一道 (见 _assert_icon_free).
    used_icons: dict[str, str] = {}


class SoftwareCreateIn(BaseModel):
    """建条目 (JSON 元数据) —— 文件随后用 PUT /{code}/file 传."""

    # ⚠️ 2026-10-28: code **不再要求填** ——
    #    它会变成服务端存储目录名, 用户手填容易出乱码/撞名.
    #    现在由软件包文件名自动派生 (见 software_store.code_from_file_name),
    #    撞名时后端自动加序号 (base2 / base3 …). 填了也能用, 但同样会走唯一化.
    code: str = Field(default="", max_length=64)
    name: str = Field(min_length=1, max_length=128)
    icon: str = Field(default="🧰", max_length=16)
    version: str = Field(default="", max_length=32)
    summary: str = Field(default="", max_length=500)
    description: str = ""
    features: list[str] = []
    use_when: str = ""
    not_for: str = ""
    # 安装说明 / 注意事项 —— 选填
    install_steps: str = ""
    caveats: str = ""
    platform: str = Field(default="", max_length=32)
    category: str = Field(default="", max_length=64)
    tags: list[str] = []
    keywords: list[str] = []
    # 原始文件名 (清洗前) —— 后端会清洗
    # ⚠️ 2026-10-28: 文件名必须符合**英文数字+标准字符** (见 software_store.validate_file_name),
    #    不合规直接 422 —— 目录名在别的机器上转义不一致, 下载回来容易变乱码.
    file_name: str = Field(default="", max_length=255)
    # 声明的文件大小 —— 实收对不上 → 409 (文件不完整)
    file_size: int = Field(default=0, ge=0)
    release_notes: str = ""
    # 变体标签 (选填) —— 如「Windows版」「LTS版」
    variant: str = Field(default="", max_length=32)


class SoftwareUpdateIn(BaseModel):
    """改元信息 (不动文件)."""

    name: str | None = Field(default=None, max_length=128)
    icon: str | None = Field(default=None, max_length=16)
    summary: str | None = Field(default=None, max_length=500)
    description: str | None = None
    features: list[str] | None = None
    use_when: str | None = None
    not_for: str | None = None
    # 安装说明 / 注意事项 —— 选填, 改的时候不传就是不动它
    install_steps: str | None = None
    caveats: str | None = None
    platform: str | None = Field(default=None, max_length=32)
    category: str | None = Field(default=None, max_length=64)
    tags: list[str] | None = None
    keywords: list[str] | None = None


class SoftwareVersionCreateIn(BaseModel):
    """发新版本."""

    version: str = Field(min_length=1, max_length=32)
    release_notes: str = ""
    # 变体标签 (选填) —— 如「Windows版」「LTS版」
    variant: str = Field(default="", max_length=32)
    # 是否把这个版本设成**推荐下载**的那个 (默认 = 是, 新版本最常用)
    is_default: bool = True
    file_name: str = Field(default="", max_length=255)
    file_size: int = Field(default=0, ge=0)


class SoftwareVersionUpdateIn(BaseModel):
    """改某个版本的元信息 (变体标签 / 推荐标记) —— 不动文件."""

    variant: str | None = Field(default=None, max_length=32)
    is_default: bool | None = None


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
    # ⚠️ 2026-10-28: 删掉**最后一个**版本时, 条目会被连带下架 (软删) ——
    #    前端得知道这件事, 不然它下架完再查详情必然 404, 用户看着像"成功却报错".
    item_unpublished: bool = False
    # 还剩几个能下载的版本
    remaining_versions: int = 0
