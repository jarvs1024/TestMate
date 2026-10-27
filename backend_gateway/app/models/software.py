"""软件库 数据模型 —— 公司内部软件的统一分发入口.

跟「插件·技能·连接」(Asset) 的分工:
  · Asset  —— 装进 Agent 的扩展 (文本包), 真身在 GitLab, 本表只是查询镜像
  · Software —— **给人用的内部软件** (任意格式二进制), 真身在**服务端磁盘**

两个东西在存储 (GitLab 文本包 vs 本地磁盘二进制)、权限、审核三个维度都不同,
所以独立建表 —— 混在一起会让现有市场逻辑复杂化, 而且二进制根本进不了 GitLab.

⚠️ status 一律用 String + 应用层校验, 不用 MySQL ENUM (理由同 models/asset.py).
"""
from datetime import datetime

from sqlalchemy import String, Text, JSON, BigInteger, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SoftwareItem(Base):
    """软件条目 —— 一个软件 (如 "SSD 日志医生").

    条目与版本是 1:N: 条目是**门面** (卡片上看到的那张卡), 版本是**文件本体**
    (每次发新版本多一行, 旧的仍然能下).
    """

    __tablename__ = "software_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # code 是唯一标识 —— 同时是存储目录名, 所以**必须**严校验 (见 software_store)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    icon: Mapped[str] = mapped_column(String(16), nullable=False, default="🧰")
    # 当前版本指针 —— 发新版本时切过去
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="")

    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 展示功能 (用户在卡片/详情里看到的"这个软件能干什么"清单)
    features: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 适用场景 / 不适合的场景 —— 沿用市场那套"该用与不该用"的说法
    use_when: Mapped[str] = mapped_column(Text, nullable=False, default="")
    not_for: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # 适用平台: windows / linux / macos / 通用 —— 只是标签, 不做平台校验
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    keywords: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    author: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 生命周期: awaiting_file(信息填了没传文件) / published(可下载) / hidden(被隐藏)
    # ⚠️ **没有审核态** —— 软件库是"上架即上架", 有发布权的人传完就能下.
    publish_status: Mapped[str] = mapped_column(String(16), nullable=False, default="awaiting_file", index=True)
    # 软删标记 —— 删条目不立刻删磁盘文件 (跟市场"下架申请 → 管理员确认"一个口径)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class SoftwareVersion(Base):
    """软件的某个版本 —— 一行对应**一个文件**.

    file_path 存的是**相对**存储根的路径 (不是绝对路径): 换机器 / 改设置项
    (storage_path) 后绝对路径会失效, 相对路径不会.
    """

    __tablename__ = "software_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # 发布与更新说明 —— 用户在版本历史里看到的"这次改了什么"
    release_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # 原始文件名 (清洗后) —— 下载时的 Content-Disposition 用它
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 相对存储根的路径, 如 "smartctl/7.4/smartctl-7.4.tar.gz"
    file_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # 版本状态: awaiting_file(在等文件) / uploading(正在传) / ready(文件已落盘且校验过) / failed(上传中断)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="awaiting_file", index=True)
    # 声明的文件大小 —— 上传前先声明, 实收对不上 → 409 (文件不完整)
    declared_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # 上次失败的原因 —— 界面上直接告诉用户"上次为什么没传上去"
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    author: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
