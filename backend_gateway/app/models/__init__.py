"""SQLAlchemy ORM models."""
from app.models.user import User, UserRole  # noqa: F401
from app.models.machine import Machine, MachineStatus  # noqa: F401
from app.models.agent import Agent, AgentStatus, AgentCategory, AgentEngine  # noqa: F401
from app.models.system_setting import SystemSetting  # noqa: F401
# 资产市场 (Asset / AssetJob / AssetAudit / AssetNotification).
# ⚠️ 必须在这里导出: Base.metadata 靠它才知道这些表 —— alembic autogenerate 与
#    测试库的 create_all 都依赖它, 漏了会导致表建不出来.
from app.models.asset import (  # noqa: F401
    Asset,
    AssetAudit,
    AssetJob,
    AssetNotification,
)
# 软件库 (SoftwareItem / SoftwareVersion) —— 内部软件的条目与版本 (文件在服务端磁盘).
# ⚠️ 同上: 必须在这里导出, 否则建表时漏掉这两张表.
from app.models.software import (  # noqa: F401
    SoftwareItem,
    SoftwareVersion,
)
