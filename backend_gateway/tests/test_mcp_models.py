"""MCP persistence model registration and constraints."""
from sqlalchemy import UniqueConstraint

from app.db.session import Base
import app.models  # noqa: F401


MCP_TABLES = {
    "mcp_oauth_clients",
    "mcp_oauth_grants",
    "mcp_api_tokens",
    "mcp_tool_calls",
}


def test_mcp_tables_are_registered_in_metadata():
    assert MCP_TABLES <= Base.metadata.tables.keys()


def test_oauth_grant_has_version_and_unique_user_client_constraint():
    grant = Base.metadata.tables["mcp_oauth_grants"]

    assert "version" in grant.c
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uk_mcp_grant_user_client"
        and tuple(constraint.columns.keys()) == ("user_id", "client_id")
        for constraint in grant.constraints
    )
