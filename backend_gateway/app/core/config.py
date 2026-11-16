"""Pydantic 强校验加载 .env,所有 .env key 必须在这里声明。"""
import base64
import secrets
from typing import List
from urllib.parse import quote_plus
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 服务
    APP_NAME: str = "TestMate Gateway"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    # 日志级别 (DEBUG/INFO/WARNING/ERROR). 留空 = 按 DEBUG 推导:
    #   DEBUG=true → DEBUG, 否则 INFO.
    # ⚠️ 跟 SQL echo 分开: 以前想开详细日志只能开 DEBUG, 结果 SQL 全打出来.
    LOG_LEVEL: str = ""
    # SQLAlchemy 是否打印每条 SQL (默认关, 排查慢查询时按需开)
    DB_ECHO: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    # 业务展示时区 —— 「今天」的口径 (日活/统计切日) 跟部署环境保持一致.
    TIMEZONE: str = "Asia/Shanghai"
    CORS_ORIGINS: List[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])

    # JWT
    # 默认值用 secrets 动态生成 (每次进程启动随机, 源码不暴露固定占位串).
    # 生产必须通过 .env 显式注入 JWT_SECRET, 启动时 _validate_jwt_secret() 强制校验.
    JWT_SECRET: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 天

    # MySQL
    MYSQL_HOST: str = "mysql"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "testmate"
    MYSQL_PASSWORD: str = "testmate"
    MYSQL_DATABASE: str = "testmate"

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # ===== 登录身份 =====
    # 账号**必须管理员先建过**才能登录 (建号入口: 设置页「用户管理」).
    # 普通用户 = 公司邮箱 (后缀固定), 建号时给了密码就得输密码, 没给就是免密;
    # 管理员 = 不含 @ 的账号名, 一律要密码.
    AUTH_EMAIL_DOMAIN: str = "@twsc.com.cn"

    # RAGFlow
    # 默认空:本工程不打包 RAGFlow,需要时由用户在 Settings 页或 .env 填真值
    # 填的时候注意:从 backend 容器内访问 host 用 host.docker.internal,不要用 127.0.0.1
    RAGFLOW_BASE_URL: str = ""
    RAGFLOW_API_KEY: str = ""

    # pr-agent (代码检视 telemetry) — 默认空, 用户在 Settings 或 .env 填
    # 注意:从 backend 容器内访问 host 用 host.docker.internal:5050
    # ReviewAgent (代码检视 telemetry) — HTTP 服务地址 (代码检视唯一后端).
    # ReviewAgent 跑在 host:3000, 容器内走 host.docker.internal:3000.
    REVIEW_AGENT_BASE_URL: str = "http://host.docker.internal:3000"
    REVIEW_AGENT_API_TOKEN: str = ""

    # DingTalk
    DINGTALK_DEFAULT_WEBHOOK: str = ""

    # ===== 外部系统集成 (PingCode / PLM) =====
    PINGCODE_BASE_URL: str = "http://10.20.24.30"
    PINGCODE_TEAM_ID: str = "66209672995cb95d777b6aec"
    # PLM 站点证书无法通过标准链校验 (线上实测), 默认关闭校验; 若换了可信证书可打开.
    PLM_BASE_URL: str = "https://plm.twsc.com.cn"
    PLM_VERIFY_TLS: bool = False
    # 凭据落库主密钥 (base64 32 字节). 生产必填, 开发/测试缺省时由
    # JWT_SECRET 经 HKDF 派生 —— 换 JWT_SECRET 会让已存凭据不可解.
    INTEGRATION_CREDENTIAL_KEY: str = ""

    # ===== 扩展 (本地 git 工作区 + GitLab SSH 同步) =====
    EXTENSIONS_WORKSPACE: str = "/workspace"
    EXTENSIONS_GIT_REMOTE: str = "ssh://git@host.docker.internal:8922/root/testmate-extensions.git"
    EXTENSIONS_GIT_BRANCH: str = "main"

    @property
    def mysql_async_dsn(self) -> str:
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{quote_plus(self.MYSQL_PASSWORD)}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )

    @property
    def mysql_sync_dsn(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{quote_plus(self.MYSQL_PASSWORD)}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )


def _validate_jwt_secret(s: Settings) -> None:
    """生产环境强制要求 .env 注入 JWT_SECRET, 禁止使用动态默认值.
    DEBUG=True 时跳过 (本地开发允许动态).

    ⚠️ 判断"用户配了没有"**不能**用 os.getenv ——
       pydantic-settings 会从 .env **文件**里读值, 但不会把它写回 os.environ,
       于是 os.getenv("JWT_SECRET") 永远是 None, 本地按 README 用 uvicorn 起
       后端会直接 RuntimeError (而 .env 里明明配了).
       正确做法: 看 model_fields_set —— 显式提供的字段 (环境变量或 .env 文件)
       才会出现在里面, 走 default_factory 的不会.
    """
    if s.DEBUG:
        return
    if "JWT_SECRET" not in s.model_fields_set:
        # 走的是 default_factory (每次进程启动随机生成) —— 生产环境不能这样,
        # 重启一次所有已发 token 全废.
        raise RuntimeError(
            "JWT_SECRET 未在 .env 配置. 生产环境必须显式设置 JWT_SECRET "
            "(可用 `python -c 'import secrets;print(secrets.token_urlsafe(48))'` 生成)."
        )
    if len(s.JWT_SECRET) < 32:
        raise RuntimeError(
            f"JWT_SECRET 长度必须 >= 32 字节, 当前 {len(s.JWT_SECRET)}, 不安全."
        )


def _validate_integration_key(s: Settings) -> None:
    """生产必须显式配置凭据主密钥; 开发允许 HKDF 派生 (见 integrations.crypto)."""
    if s.DEBUG:
        return
    if "INTEGRATION_CREDENTIAL_KEY" not in s.model_fields_set:
        raise RuntimeError(
            "INTEGRATION_CREDENTIAL_KEY 未在 .env 配置. 生产环境必须显式设置 "
            "(base64 编码的 32 字节, 可用 "
            "`python -c 'import base64,secrets;print(base64.b64encode(secrets.token_bytes(32)).decode())'` 生成)."
        )
    try:
        key = base64.b64decode(s.INTEGRATION_CREDENTIAL_KEY.strip(), validate=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("INTEGRATION_CREDENTIAL_KEY 不是合法 base64") from exc
    if len(key) != 32:
        raise RuntimeError(
            f"INTEGRATION_CREDENTIAL_KEY 必须是 32 字节, 当前 {len(key)} 字节."
        )


settings = Settings()
_validate_jwt_secret(settings)
_validate_integration_key(settings)
