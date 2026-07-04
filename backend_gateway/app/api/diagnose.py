"""log 诊断:转发到 Dify,SSE 流式返回。"""
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dify_client import get_dify
from app.db.session import get_session
from app.models.user import User
from app.schemas.log import DiagnoseRequest
from app.api.auth import get_current_user

router = APIRouter()


@router.post("/stream")
async def diagnose_stream(
    req: DiagnoseRequest,
    user: User = Depends(get_current_user),
    _session: AsyncSession = Depends(get_session),
):
    """上传 log → 中台预处理 → Dify 流式 → SSE 返回前端。"""
    dify = get_dify()

    # P0 简化:大文件截断到前 50KB + 末尾 50KB
    MAX = 50_000
    log = req.log_content
    if len(log) > MAX * 2:
        truncated = log[:MAX] + "\n\n... [中台截断:省略中间内容] ...\n\n" + log[-MAX:]
    else:
        truncated = log

    async def event_gen():
        try:
            async for chunk in dify.chat_messages_stream(
                query=f"请分析以下 log 中的异常:\n\n```\n{truncated}\n```",
                user=user.username,
                inputs={
                    "environment": req.environment or {},
                    "dataset": req.dataset or "",
                },
            ):
                # 转发 Dify 事件
                event = chunk.get("event", "")
                answer = chunk.get("answer", "")
                if event == "message" and answer:
                    payload = {"type": "code", "content": answer}
                elif event == "agent_message" and answer:
                    payload = {"type": "thinking", "content": answer}
                elif event == "error":
                    payload = {"type": "error", "content": chunk.get("message", "未知错误")}
                else:
                    continue
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            yield "data: {\"type\":\"done\"}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','content':str(e)}, ensure_ascii=False)}\n\n"
            yield "data: {\"type\":\"done\"}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
