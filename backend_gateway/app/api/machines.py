"""机台字典 + 状态。P0 占位,P1 补全。"""
from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("")
async def list_machines(_user: User = Depends(get_current_user)) -> dict:
    return {"machines": [], "note": "P0 占位,P1 接 SSH 心跳"}
