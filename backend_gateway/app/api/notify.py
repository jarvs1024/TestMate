"""钉钉通知(中台转发)。P0 占位,P1 补全。"""
from fastapi import APIRouter

router = APIRouter()


@router.post("/test")
async def test_notify() -> dict:
    return {"status": "ok", "note": "P0 占位,P1 接钉钉 webhook"}
