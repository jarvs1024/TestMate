"""健康检查 + 后端服务状态聚合。"""
import asyncio
import httpx
from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


async def _probe(name: str, base_url: str, api_key: str, timeout: float = 1.5) -> str:
    """P0 简化:发一个最小请求,2s 内通就 ok,否则 off.

    返回 'ok' | 'warn' | 'off'
    """
    if not base_url or "xxxxx" in api_key or "mock" in api_key:
        # 未配置(mock 模式 / 默认占位)
        return "off"
    try:
        # 试着打 health / ping 之类的根路径,各家不通也没关系
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(base_url.rstrip("/").replace("/v1", "/").replace("/api/v1", "/"))
            if r.status_code < 500:
                return "ok"
            return "warn"
    except Exception:
        return "off"


@router.get("/health/services")
async def health_services() -> dict:
    """聚合 RAGFlow / Dify 的可达性,前端顶栏 30s 轮询一次。

    返回格式:{"ragflow": "ok|warn|off", "dify": "ok|warn|off"}
    P0 阶段如果配置是 mock / 默认占位,直接报 "off"。
    """
    rag, dify = await asyncio.gather(
        _probe("ragflow", settings.RAGFLOW_BASE_URL, settings.RAGFLOW_API_KEY),
        _probe("dify", settings.DIFY_BASE_URL, settings.DIFY_API_KEY),
    )
    return {"ragflow": rag, "dify": dify}
