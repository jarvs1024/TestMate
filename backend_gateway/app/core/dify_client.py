"""Dify 异步客户端 + SSE 流式转发。"""
import json
from typing import AsyncIterator

import httpx

from app.core.config import settings


class DifyClient:
    def __init__(self) -> None:
        self.base_url = settings.DIFY_BASE_URL.rstrip("/")
        self.api_key = settings.DIFY_API_KEY
        self.timeout = settings.DIFY_TIMEOUT_SECONDS

    async def chat_messages_stream(
        self,
        query: str,
        user: str,
        inputs: dict | None = None,
        conversation_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """Dify /chat-messages 流式接口,逐 chunk yield 解析后的事件。"""
        payload: dict = {
            "inputs": inputs or {},
            "query": query,
            "user": user,
            "response_mode": "streaming",
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat-messages", json=payload, headers=headers
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        yield {"event": "done"}
                        return
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue


_client: DifyClient | None = None


def get_dify() -> DifyClient:
    global _client
    if _client is None:
        _client = DifyClient()
    return _client
