"""SQLAlchemy ORM models."""
from app.models.user import User, UserRole  # noqa: F401
from app.models.machine import Machine, MachineStatus  # noqa: F401
from app.models.agent import Agent, AgentStatus, AgentCategory, AgentEngine  # noqa: F401
from app.models.system_setting import SystemSetting  # noqa: F401
# 资产市场 (Asset / AssetJob / AssetAudit / AssetNotification / AssetInstall).
# ⚠️ 必须在这里导出: Base.metadata 靠它才知道这些表 —— alembic autogenerate 与
#    测试库的 create_all 都依赖它, 漏了会导致表建不出来.
from app.models.asset import (  # noqa: F401
    Asset,
    AssetAudit,
    AssetInstall,
    AssetJob,
    AssetNotification,
)
