"""AI 资产市场数据模型。

**GitLab 是资产的唯一真实来源 (source of truth)**: manifest / 源码 / README 全部
以 commit 形式存在仓库里。本表只是**查询镜像**, 用来做列表筛选、搜索与本地态关联。

镜像与 GitLab 的关系:
  - 上传成功后, 同一次请求里把 index.json + 资产文件写进 GitLab, 然后 upsert 本表
  - GitLab 侧被人直接 push 改动时, 调 `POST /api/v1/assets/sync` 或等 webhook 回灌本表
  - 本表被清空也不影响真实资产, 重新 sync 即可恢复

⚠️ status 等字段一律用 String + 应用层校验, 不用 MySQL ENUM。
   ENUM 走 SQLAlchemy Enum 时 ALTER 必须写裸 SQL (见 0003/0004 迁移), 既不可组合
   也会被 `alembic check` 判成漂移 —— String 更省心.
"""
from datetime import datetime

from sqlalchemy import String, Text, JSON, BigInteger, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Asset(Base):
    """资产镜像 — 每个字段都与 index.json 里的一项对应."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    icon: Mapped[str] = mapped_column(String(16), nullable=False, default="🧩")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # plugin/skill/mcp
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.1.0")

    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    use_when: Mapped[str] = mapped_column(Text, nullable=False, default="")
    not_for: Mapped[str] = mapped_column(Text, nullable=False, default="")

    category: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    # 适用范围: 空 = **通用** (所有项目都能用); "6100" = 6100 项目特有.
    # 项目列表在设置项 marketplace.projects 里 —— 见 app/core/market_projects.py
    project: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    keywords: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # 权限声明 — 市场区别于普通插件目录的核心, 也是审核重点
    permissions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    install_steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    bindings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    author: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    featured: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    homepage: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ---- GitLab 侧定位信息 ----
    git_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    git_commit_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    git_web_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # 同步状态: staged(已落本地待同步) / pushed(已推到 GitLab) / failed(同步失败)
    sync_status: Mapped[str] = mapped_column(String(16), nullable=False, default="staged", index=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 生命周期状态: published(在架) / unpublished(已下架)
    # 与 sync_status 解耦 —— sync_status 说的是"推没推上去", 这里说的是"要不要上架"
    # 五态:
    #   pending           已提交, 等管理员审核 (不对普通用户可见)
    #   published         在架
    #   rejected          审核未通过 (发布者可改了重新提交)
    #   unpublished       审核通过后又下架 (文件保留, 在用用户仍可见并看到「已下架」)
    #   unpublish_pending 申请下架, 等管理员确认 (确认后资产会被**彻底删除**)
    publish_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="published", index=True
    )
    # 最近一次审核意见 (驳回理由 / 审核备注) —— 审核动作也记在 asset_audits 里
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # 下载次数 —— 热门度指标 (不是"安装次数": 后端只知道用户点了下载,
    # 不知道人家到底解压没有, 那个是猜不出来的)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ⚠️ 只有**连接器 (mcp)** 有这个字段: MCP 配置 (mcpServers).
    #    连接器是配置型资产 —— 没有安装包也没有 README, 就这一段配置.
    #    技能/插件一律为 None.
    mcp_config: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AssetJob(Base):
    """上传/更新任务 — 支持后台异步执行与断点重试.

    流程: 前端 POST 文件 → 建 job(pending) → 返回 job_id → BackgroundTasks 执行
    → running → succeeded/failed. 进程重启时把滞留的 running 重新置 pending 再跑一遍
    (提交动作幂等, 重复执行不会产生重复 commit).
    """

    __tablename__ = "asset_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # action: create / update / publish / unpublish / unpublish_request /
    #         unpublish_approve / unpublish_reject / unpublish_cancel /
    #         approve / reject / submit
    action: Mapped[str] = mapped_column(String(24), nullable=False)  # create/update
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    # pending → running → succeeded | failed

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="skill")

    # 上传内容: {相对路径: 文本内容} + manifest; 二进制不走这里
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    git_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    staged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class AssetAudit(Base):
    """资产操作审计流水.

    记录上架/下架/更新/安装/卸载/冲突解决等动作 —— 谁在什么时候动了什么.
    共享 GitLab 仓库下多成员共用一个 SSH key, git commit 作者无法区分真实操作者,
    所以"谁做的"只能靠这张表留痕.
    """

    __tablename__ = "asset_audits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actor_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    detail: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AssetNotification(Base):
    """钉钉通知的**送达回执**.

    通知原本是 fire-and-forget 的: 发出去了没人知道成没成. 这里把每次尝试落库 ——
    成功记 sent, 失败记 failed + 错误原因, 后台再按指数退避重试.

    为什么必须有: 上架/下架/更新是**要通知全队**的动作, 静默失败等于没通知.
    """

    __tablename__ = "asset_notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event: Mapped[str] = mapped_column(String(32), nullable=False, default="", index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    asset_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # pending(待发) / sent(已送达) / failed(最终失败)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 消息正文 —— 重试时直接复用, 不用重新拼
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
