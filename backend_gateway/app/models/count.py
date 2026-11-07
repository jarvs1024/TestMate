"""下载/复制计数的冷却窗口去重标记 (2026-11-05).

同一 dedup_key (u:{用户id} / ip:{客户端IP}) 在 DEDUP_WINDOW_SECONDS (2 小时) 内
对同一 code 只计一次 —— 防误触/重试/恶意连点把 download_count 刷虚高.
软件库的版本计数用 `code@版本` 当 code, 与条目计数互相独立.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CountMark(Base):
    """一条标记 = 一个人 (或一个 IP) 对某个目标最近一次计数的时间.

    (code, dedup_key) 唯一 —— 一行一对, 只翻新时间戳, 表永不膨胀.
    """

    __tablename__ = "count_marks"
    __table_args__ = (
        UniqueConstraint("code", "dedup_key", name="uq_count_marks_code_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(200), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(120), nullable=False)
    last_counted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
