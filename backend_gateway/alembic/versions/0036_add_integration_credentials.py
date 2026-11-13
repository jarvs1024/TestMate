"""add integration_credentials (PingCode / PLM 凭据)

每个用户每个外部系统一行; 密码、token、cookie 均为 AES-256-GCM 密文
(`v1:<b64(nonce||ciphertext||tag)>`, AAD=`user_id:provider`).

Revision ID: 0036_add_integration_credentials
Revises: 0035_rename_market_to_ext_lib
Create Date: 2026-11-12
"""
from alembic import op
import sqlalchemy as sa


revision = "0036_add_integration_credentials"
down_revision = "0035_rename_market_to_ext_lib"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_credentials",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("token_encrypted", sa.Text(), nullable=True),
        sa.Column("cookies_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="ok"),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("login_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_integration_credential_user", ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "provider", name="uk_integration_credential_user_provider"
        ),
    )
    op.create_index(
        "ix_integration_credentials_user_id", "integration_credentials", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_integration_credentials_user_id", table_name="integration_credentials")
    op.drop_table("integration_credentials")
