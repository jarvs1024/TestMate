"""Dify 异步客户端 + SSE 流式转发。"""
import asyncio
import json
import time
from typing import AsyncIterator

import httpx

from app.core.config import settings


class DifyClient:
    def __init__(self) -> None:
        self.base_url = settings.DIFY_BASE_URL.rstrip("/")
        self.api_key = settings.DIFY_API_KEY
        self.timeout = settings.DIFY_TIMEOUT_SECONDS
        self.mock = settings.DIFY_MOCK

    async def chat_messages_stream(
        self,
        query: str,
        user: str,
        inputs: dict | None = None,
        conversation_id: str | None = None,
    ) -> AsyncIterator[dict]:
        """Dify /chat-messages 流式接口,逐 chunk yield 解析后的事件。

        DIFY_MOCK=True 时不调外部,本地打字机效果生成假流,用于沙箱/无 Dify 环境。
        产出事件结构与真 Dify 对齐:dify 协议原始 chunk + 最终 {event: done}。
        """
        if self.mock:
            async for ev in self._mock_stream(query, user, inputs, conversation_id):
                yield ev
            return

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

    async def _mock_stream(
        self,
        query: str,
        user: str,
        inputs: dict | None,
        conversation_id: str | None,
    ) -> AsyncIterator[dict]:
        """本地 mock 流:先发 agent_message(思考),再发 message(正文,逐字),最后 message_end。

        打字机速度默认 30ms/字,可由 inputs["mock_speed_ms"] 覆盖,便于压测前端表现。
        """
        speed_ms = int((inputs or {}).get("mock_speed_ms", 30))
        env = (inputs or {}).get("environment") or {}

        # 1) 思考段(短,假装在分析)
        thinking = f"[mock] 收到用户 {user} 的问题,长度 {len(query)} 字符,正在分析...\n"
        yield {
            "event": "agent_message",
            "answer": thinking,
            "conversation_id": conversation_id or "mock-conv",
        }
        await asyncio.sleep(0.3)

        # 2) 正文段:打字机效果
        body_lines = [
            f"这是 DIFY_MOCK 模式下的回复,未调用外部 Dify 服务。",
            f"",
            f"**用户问题**:{query[:200]}{'...' if len(query) > 200 else ''}",
            f"",
            f"**附带输入**:{json.dumps(inputs or {}, ensure_ascii=False)}",
            f"",
            f"**生成参数**:速度 {speed_ms}ms/字,生成时间 {time.strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        for line in body_lines:
            yield {
                "event": "message",
                "answer": line + "\n",
                "conversation_id": conversation_id or "mock-conv",
            }
            await asyncio.sleep(speed_ms / 1000.0 * max(len(line), 1))

        # 3) 结束
        yield {
            "event": "message_end",
            "conversation_id": conversation_id or "mock-conv",
            "metadata": {"usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
        }
        yield {"event": "done"}


_client: DifyClient | None = None


def get_dify() -> DifyClient:
    global _client
    if _client is None:
        _client = DifyClient()
    return _client
