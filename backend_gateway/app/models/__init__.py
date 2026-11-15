"""SQLAlchemy ORM models."""
from app.models.user import User, UserRole  # noqa: F401
from app.models.machine import Machine, MachineStatus  # noqa: F401
from app.models.agent import Agent, AgentStatus, AgentCategory, AgentEngine  # noqa: F401
from app.models.system_setting import SystemSetting  # noqa: F401
# 扩展 (Asset / AssetJob / AssetAudit / AssetNotification).
# ⚠️ 必须在这里导出: Base.metadata 靠它才知道这些表 —— alembic autogenerate 与
#    测试库的 create_all 都依赖它, 漏了会导致表建不出来.
from app.models.asset import (  # noqa: F401
    Asset,
    AssetAudit,
    AssetComment,
    AssetJob,
    AssetNotification,
)
# 软件库 (SoftwareItem / SoftwareVersion) —— 内部软件的条目与版本 (文件在服务端磁盘).
# ⚠️ 同上: 必须在这里导出, 否则建表时漏掉这两张表.
from app.models.software import (  # noqa: F401
    SoftwareItem,
    SoftwareVersion,
)
# 知识库 (RAGFlow) 的操作审计 —— 内容存在 RAGFlow 里, 不留痕就不知道谁传的.
# ⚠️ 同上: 必须在这里导出, 否则建表时漏掉这张表.
from app.models.kb import KbAudit  # noqa: F401
# RAGFlow 用户空间 —— 多把 API key 对应多个租户空间.
# ⚠️ 同上: 必须在这里导出, 否则建表时漏掉这张表.
from app.models.ragflow_space import RagflowSpace  # noqa: F401
from app.models.mcp import (  # noqa: F401
    McpApiToken,
    McpOAuthClient,
    McpOAuthGrant,
    McpToolCall,
)
# 下载/复制计数的冷却窗口去重标记.
# ⚠️ 同上: 必须在这里导出, 否则建表时漏掉这张表.
from app.models.count import CountMark  # noqa: F401
# 外部系统集成凭据 (PingCode / PLM), 密码与 token 均为 AES-GCM 密文.
# ⚠️ 同上: 必须在这里导出, 否则建表时漏掉这张表.
from app.models.integration import IntegrationCredential  # noqa: F401
