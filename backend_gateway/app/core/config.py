"""Pydantic 强校验加载 .env,所有 .env key 必须在这里声明。"""
from typing import List
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
    JWT_SECRET: str = "change-me-in-production-please-use-32-bytes-random"
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
    DIFY_BASE_URL: str = "http://dify:80/v1"
    DIFY_API_KEY: str = "app-xxxxx"
    DIFY_TIMEOUT_SECONDS: int = 120

    # RAGFlow
    RAGFLOW_BASE_URL: str = "http://ragflow:9380/api/v1"
    RAGFLOW_API_KEY: str = "ragflow-xxxxx"

    # DingTalk
    DINGTALK_DEFAULT_WEBHOOK: str = ""

    @property
    def mysql_async_dsn(self) -> str:
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )

    @property
    def mysql_sync_dsn(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )


settings = Settings()
