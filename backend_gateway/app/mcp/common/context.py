"""Authenticated principal and per-call context shared by MCP domains."""
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@dataclass(frozen=True, slots=True)
class Principal:
    """Current database user and the effective credentials granted to this call."""

    user: User
    client_id: str
    scopes: frozenset[str]
    grant_id: int | None = None


@dataclass(slots=True)
class McpContext:
    """Dependencies passed explicitly to tools instead of HTTP headers."""

    principal: Principal
    session: AsyncSession
