"""Agent Pydantic schemas."""
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class AgentOut(BaseModel):
    id: int
    code: str
    name: str
    icon: str
    category: str
    version: str
    status: str
    summary: str
    use_when: str
    not_for: str
    tags: list[str] = []
    engine: str
    engine_config: dict[str, Any] = {}
    input_schema: list[dict[str, Any]] = []
    data_sources: list[str] = []
    tools: list[str] = []
    call_count: int = 0
    last_called_at: datetime | None = None
    is_featured: bool = False
    embed_url: str | None = None
    route: str | None = None

    class Config:
        from_attributes = True


class AgentListOut(BaseModel):
    items: list[AgentOut]
    total: int


class AgentCreateIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=2, max_length=64)
    icon: str = "🩺"
    category: str
    version: str = "v0.1.0"
    status: str = "draft"
    summary: str
    use_when: str = ""
    not_for: str = ""
    tags: list[str] = []
    engine: str = "dify"
    engine_config: dict[str, Any] = {}
    input_schema: list[dict[str, Any]] = []
    data_sources: list[str] = []
    tools: list[str] = []
    visibility: str = "all"
    allowed_roles: list[str] = []
    is_featured: bool = False
    embed_url: str | None = None
    route: str | None = None
