"""Rename market/marketplace identifiers to extensions.

Covers settings keys, stored MCP OAuth scopes, tool-call domains, capability
routes, and pending notification links. Historical notification receipts are
left untouched unless they are still queued for retry.

Revision ID: 0032_rename_market_to_extensions
Revises: 0031_add_mcp_token_value
Create Date: 2026-11-02
"""
import json

from alembic import op
import sqlalchemy as sa


revision = "0032_rename_market_to_extensions"
down_revision = "0031_add_mcp_token_value"
branch_labels = None
depends_on = None


_SETTING_RENAMES = {
    "marketplace.projects": "extensions.projects",
    "marketplace.publisher_roles": "extensions.publisher_roles",
    "marketplace.publisher_ids": "extensions.publisher_ids",
    "marketplace.publisher_usernames": "extensions.publisher_usernames",
    "marketplace.review.enabled": "extensions.review.enabled",
    "marketplace.review.reviewer_usernames": "extensions.review.reviewer_usernames",
    "marketplace.review.admin_self_approve": "extensions.review.admin_self_approve",
    "marketplace.git.max_push_attempts": "extensions.git.max_push_attempts",
    "marketplace.upload.max_files": "extensions.upload.max_files",
    "marketplace.upload.max_total_mb": "extensions.upload.max_total_mb",
    "marketplace.git.remote": "extensions.git.remote",
    "marketplace.git.branch": "extensions.git.branch",
    "marketplace.git.web_url": "extensions.git.web_url",
    "marketplace.sync.interval_seconds": "extensions.sync.interval_seconds",
    "marketplace.max_package_mb": "extensions.max_package_mb",
    "marketplace.marketplace_name": "extensions.name",
    "marketplace.public_base_url": "extensions.public_base_url",
    "marketplace.public_download": "extensions.public_download",
    "dingtalk.market_webhook": "dingtalk.extensions_webhook",
    "dingtalk.market_secret": "dingtalk.extensions_secret",
    "dingtalk.market_keyword": "dingtalk.extensions_keyword",
}

_SCOPE_RENAMES = {
    "market:read": "extensions:read",
    "market:write": "extensions:write",
}

_SCOPE_TABLES = {
    "mcp_api_tokens": "id",
    "mcp_oauth_grants": "id",
    "mcp_oauth_clients": "client_id",
}


def _rename_settings(bind: sa.engine.Connection, renames: dict[str, str]) -> None:
    rows = bind.execute(sa.text("SELECT `key` FROM system_settings")).scalars().all()
    existing = set(rows)
    for old, new in renames.items():
        if old not in existing:
            continue
        if new in existing:
            # New key already seeded — keep it and drop the stale duplicate.
            bind.execute(
                sa.text("DELETE FROM system_settings WHERE `key` = :key"), {"key": old}
            )
            continue
        bind.execute(
            sa.text("UPDATE system_settings SET `key` = :new WHERE `key` = :old"),
            {"new": new, "old": old},
        )
    bind.execute(
        sa.text(
            "UPDATE system_settings SET category = 'extensions' "
            "WHERE category = 'marketplace'"
        )
    )


def _rename_scopes(bind: sa.engine.Connection, renames: dict[str, str]) -> None:
    for table, pk in _SCOPE_TABLES.items():
        rows = bind.execute(sa.text(f"SELECT {pk}, scopes FROM {table}")).all()
        for row_id, scopes in rows:
            if isinstance(scopes, str):
                try:
                    scopes = json.loads(scopes)
                except json.JSONDecodeError:
                    continue
            if not isinstance(scopes, list):
                continue
            renamed = [
                renames.get(scope, scope) if isinstance(scope, str) else scope
                for scope in scopes
            ]
            if renamed != scopes:
                bind.execute(
                    sa.text(f"UPDATE {table} SET scopes = :scopes WHERE {pk} = :id"),
                    {"scopes": json.dumps(renamed), "id": row_id},
                )


def upgrade() -> None:
    bind = op.get_bind()
    _rename_settings(bind, _SETTING_RENAMES)
    _rename_scopes(bind, _SCOPE_RENAMES)

    bind.execute(
        sa.text(
            "UPDATE mcp_tool_calls SET domain = 'extensions' WHERE domain = 'skill'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE agents SET route = 'page:extensions' WHERE route = 'page:market'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE asset_notifications SET text = REPLACE(text, '/market', '/extensions') "
            "WHERE status = 'pending' AND text LIKE '%/market%'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    _rename_settings(
        bind, {new: old for old, new in _SETTING_RENAMES.items()}
    )
    _rename_scopes(bind, {new: old for old, new in _SCOPE_RENAMES.items()})

    bind.execute(
        sa.text(
            "UPDATE mcp_tool_calls SET domain = 'skill' WHERE domain = 'extensions'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE agents SET route = 'page:market' WHERE route = 'page:extensions'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE asset_notifications SET text = REPLACE(text, '/extensions', '/market') "
            "WHERE status = 'pending' AND text LIKE '%/extensions%'"
        )
    )
