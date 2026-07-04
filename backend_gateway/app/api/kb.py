"""知识库(代理 RAGFlow)。P0 占位,P1 补全。"""
from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/datasets")
async def list_datasets(_user: User = Depends(get_current_user)) -> dict:
    return {"datasets": [], "note": "P0 占位,P1 接 RAGFlow"}
