"""Pydantic 强校验加载 .env,所有 .env key 必须在这里声明。"""
import os
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
    HOST: str = "0.0.0.0"
    PORT: int = 8000
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

    # Dify
    # 默认 DIFY_MOCK=True:沙箱/无 Dify 环境跑得起来;生产想接真 Dify 时改 .env DIFY_MOCK=false 并填 DIFY_BASE_URL/DIFY_API_KEY
    DIFY_MOCK: bool = True
    DIFY_BASE_URL: str = ""
    DIFY_API_KEY: str = ""
    DIFY_TIMEOUT_SECONDS: int = 120

    # RAGFlow
    # 默认空:本工程不打包 RAGFlow,需要时由用户在 Settings 页或 .env 填真值
    # 填的时候注意:从 backend 容器内访问 host 用 host.docker.internal,不要用 127.0.0.1
    RAGFLOW_BASE_URL: str = ""
    RAGFLOW_API_KEY: str = ""

    # pr-agent (代码检视 telemetry) — 默认空, 用户在 Settings 或 .env 填
    # 注意:从 backend 容器内访问 host 用 host.docker.internal:5050
    PR_AGENT_BASE_URL: str = ""
    PR_AGENT_API_TOKEN: str = ""

    # DingTalk
    DINGTALK_DEFAULT_WEBHOOK: str = ""

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
    DEBUG=True 时跳过 (本地开发允许动态)."""
    if s.DEBUG:
        return
    if not os.getenv("JWT_SECRET"):
        # Pydantic 读到环境变量就用, 没读到走 default_factory (动态生成).
        # 这里没法直接区分"用户配了"vs"用了默认", 用长度+非哨兵特征判定:
        # secrets.token_urlsafe(48) 生成的串是 64 字符的 base64-url.
        # 真正的生产 secret 一般是手动填的 hex/base64/任意字符串.
        # 防御: 强制要求显式设置环境变量, 哪怕是动态生成也至少要 .env 里有占位.
        raise RuntimeError(
            "JWT_SECRET 未在 .env 配置. 生产环境必须显式设置 JWT_SECRET "
            "(可用 `python -c 'import secrets;print(secrets.token_urlsafe(48))'` 生成)."
        )
    if len(s.JWT_SECRET) < 32:
        raise RuntimeError(
            f"JWT_SECRET 长度必须 >= 32 字节, 当前 {len(s.JWT_SECRET)}, 不安全."
        )


settings = Settings()
_validate_jwt_secret(settings)
