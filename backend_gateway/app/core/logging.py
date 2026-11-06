"""结构化 JSON 日志 —— stdlib 与 structlog 共用一条输出管道。

目的: 容器化后, 日志进 docker logs / journald / ELK / Loki, 需要 JSON 格式才好解析。

用法:
  # 入口模块顶端调用一次即可
  from app.core.logging import setup_logging
  setup_logging()

  # 业务代码照常写 stdlib —— 也会输出 JSON
  import logging
  logging.getLogger(__name__).info("user_login username=%s ip=%s", username, ip)

  # 需要结构化字段 / request_id 关联时用 structlog
  import structlog
  structlog.get_logger().info("asset_pushed", code=code, sha=sha)

⚠️ 2026-11-06 统一格式:
   以前 stdlib 侧是 format="%(message)s" —— 140 多处业务日志打出来
   **没有时间 / 级别 / 模块名**, 只能靠人肉看上下文; 而 structlog 是 JSON.
   同一份日志两种形态, 检索和聚合都难. 现在 stdlib 也走
   ProcessorFormatter + JSONRenderer, 两边一个格式.
"""
from __future__ import annotations

import logging
import sys
import time
from typing import Any

import structlog

# 循环类告警的限流状态: key -> 上次实际打印的 monotonic 时间.
# 有上限, 不会因为 key 无限增长而吃内存.
_RATE_LIMITED_MAX_KEYS = 512
_rate_limited_last: dict[str, float] = {}


def setup_logging(level: str = "INFO") -> None:
    """配置 stdlib logging + structlog 输出同一份 JSON 到 stdout。

    stdout 输出: 单行 JSON, 每条日志一个 dict.
    """
    log_level = getattr(logging, str(level or "INFO").upper(), logging.INFO)

    # 两边共用的处理器: 时间 / 级别 / 模块 / request_id / 异常堆栈
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        # 非 structlog 来源 (即全部 stdlib logger) 先过一遍共用处理器
        foreign_pre_chain=shared_processors,
        # 两边最后都渲染成 JSON (remove_processors_meta 由 processor= 自动加)
        processor=structlog.processors.JSONRenderer(ensure_ascii=False),
        # ⚠️ 保持默认 False: 异常由 format_exc_info 渲染成 JSON 的 exception 字段,
        #    如果 keep_exc_info=True, logging 还会在 JSON 行后面**再追加一遍
        #    纯文本 traceback** (实测), 一次异常两处输出.
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(log_level)

    # ⚠️ uvicorn 默认给 `uvicorn` / `uvicorn.error` / `uvicorn.access` 各挂了
    #    propagate=False 的独立 handler —— 不接管的话这些日志仍是纯文本.
    unify_uvicorn_loggers()

    # ⚠️ 这两类日志纯属噪音, 统一压到 WARNING:
    #    · uvicorn.access: 每个健康检查 (15s) / 前端轮询都一行 ——
    #      请求级日志由 main._request_logging 统一记录, 只记有意义的.
    #    · httpx/httpcore: 每次外呼 (钉钉 / GitLab / ReviewAgent) 一行 INFO.
    for name in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def unify_uvicorn_loggers() -> None:
    """把 uvicorn 自己的日志接进 root 的 JSON handler.

    ⚠️ uvicorn 默认 dictConfig 给这几个 logger 挂了 propagate=False 的独立
       handler (纯文本). 不清掉的话启动/异常日志会跟业务日志格式不一致.
    """
    access = logging.getLogger("uvicorn.access")
    access.handlers[:] = []
    access.propagate = False
    access.setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True


def current_request_id() -> str:
    """当前请求的 request_id (后台任务 / 非请求上下文里返回空串)."""
    try:
        return str(structlog.contextvars.get_contextvars().get("request_id") or "")
    except Exception:  # noqa: BLE001 — 取不到就当没有, 绝不能影响业务
        return ""


def log_rate_limited(
    logger: logging.Logger,
    key: str,
    level: int,
    msg: str,
    *args: Any,
    interval: float = 60.0,
    **kwargs: Any,
) -> bool:
    """同一个 key 在 interval 秒内只真正打印一条 —— 给循环里的重复告警用.

    返回本次是否真的打了. 状态字典上限 _RATE_LIMITED_MAX_KEYS 条,
    超了淘汰最早的一条 (走的是同一个循环 worker, 这点竞争可以忽略).
    """
    now = time.monotonic()
    last = _rate_limited_last.get(key)
    if last is not None and now - last < interval:
        return False
    if key not in _rate_limited_last and len(_rate_limited_last) >= _RATE_LIMITED_MAX_KEYS:
        oldest = min(_rate_limited_last, key=_rate_limited_last.__getitem__)
        _rate_limited_last.pop(oldest, None)
    _rate_limited_last[key] = now
    logger.log(level, msg, *args, **kwargs)
    return True


# uvicorn 的 log_config —— 保留给需要 dictConfig 的场景.
# ⚠️ 目前**不会自动生效**: 启动命令统一用 --no-access-log + 本模块的
#    setup_logging. 别以为有这个常量日志就自动是 JSON 了.
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
