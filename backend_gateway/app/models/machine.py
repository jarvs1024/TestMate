"""机台资产字典。"""
from datetime import datetime
from sqlalchemy import String, DateTime, Enum, BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column
import enum

from app.db.session import Base


class MachineStatus(str, enum.Enum):
    online = "online"
    offline = "offline"
    busy = "busy"
    error = "error"


class Machine(Base):
    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str] = mapped_column(String(45), nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_user: Mapped[str] = mapped_column(String(32), nullable=False)
    ssh_key_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slot: Mapped[str | None] = mapped_column(String(32), nullable=True)
    firmware: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nand_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[MachineStatus] = mapped_column(
        Enum(MachineStatus), nullable=False, default=MachineStatus.offline
    )
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
