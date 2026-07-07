"""结构化 JSON 日志。

目的: 容器化后, 日志进 docker logs / journald / ELK / Loki, 需要 JSON 格式才好解析。

用法:
  # 入口模块顶端调用一次即可
  from app.core.logging import setup_logging
  setup_logging()

  # 业务代码里
  import structlog
  log = structlog.get_logger()
  log.info("user_login", username=username, ip=request.client.host)
"""
import logging
import sys
from typing import Any

import structlog


def setup_logging(level: str = "INFO") -> None:
    """配置 stdlib logging + structlog 都输出 JSON。

    stdout 输出: 单行 JSON, 每条日志一个 dict
    """
    # stdlib logging 配 — 走 INFO 级别, JSON 格式
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )

    # structlog 配 — 共享 stdlib 的 handler, 但输出结构化字段
    structlog.configure(
        processors=[
            # 添加 log level 字段
            structlog.stdlib.add_log_level,
            # 添加 logger 名
            structlog.stdlib.add_logger_name,
            # 时间戳 ISO 格式
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            # 异常堆栈
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # 最终 JSON 渲染
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


# uvicorn 的 log_config — 让 uvicorn/access 日志也走 JSON
# 用法: uvicorn app.main:app --log-config app/core/logging.py:UVICORN_LOG_CONFIG
# (uvicorn 的 --log-config 是 file path, 不是 module attr, 所以这里另外导出 dict 走代码)
UVICORN_LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": "%(message)s",
        },
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}
