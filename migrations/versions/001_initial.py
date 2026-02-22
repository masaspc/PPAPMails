"""Initial database schema

Revision ID: 001
Revises: None
Create Date: 2026-02-22
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # transfers
    op.create_table(
        "transfers",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("original_message_id", sa.String(255), nullable=False),
        sa.Column("sender_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.Text),
        sa.Column("sent_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_transfers_sender", "transfers", ["sender_email"])
    op.create_index("idx_transfers_status", "transfers", ["status"])
    op.create_index("idx_transfers_expires", "transfers", ["expires_at"])

    # recipients
    op.create_table(
        "recipients",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("transfer_id", UUID(as_uuid=True),
                  sa.ForeignKey("transfers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("recipient_type", sa.String(5), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_recipients_email", "recipients", ["email"])
    op.create_index("idx_recipients_transfer", "recipients", ["transfer_id"])

    # attachments
    op.create_table(
        "attachments",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("transfer_id", UUID(as_uuid=True),
                  sa.ForeignKey("transfers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("stored_filename", sa.String(500), nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False),
        sa.Column("mime_type", sa.String(255)),
        sa.Column("download_url_token", UUID(as_uuid=True), unique=True, nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("download_count", sa.Integer, server_default="0"),
        sa.Column("max_downloads", sa.Integer, server_default="10"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_attachments_token", "attachments", ["download_url_token"])
    op.create_index("idx_attachments_transfer", "attachments", ["transfer_id"])

    # auth_codes
    op.create_table(
        "auth_codes",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("transfer_id", UUID(as_uuid=True),
                  sa.ForeignKey("transfers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean, server_default="false"),
        sa.Column("attempt_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_auth_codes_email", "auth_codes", ["email"])
    op.create_index("idx_auth_codes_transfer", "auth_codes", ["transfer_id"])

    # auth_sessions
    op.create_table(
        "auth_sessions",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("transfer_id", UUID(as_uuid=True),
                  sa.ForeignKey("transfers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("session_token", UUID(as_uuid=True), unique=True, nullable=False,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_auth_sessions_token", "auth_sessions", ["session_token"])

    # download_logs
    op.create_table(
        "download_logs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("attachment_id", UUID(as_uuid=True),
                  sa.ForeignKey("attachments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_email", sa.String(255), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
        sa.Column("ip_address", INET),
        sa.Column("user_agent", sa.Text),
    )
    op.create_index("idx_download_logs_attachment", "download_logs", ["attachment_id"])

    # system_settings
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )

    # デフォルト設定の挿入
    op.execute("""
        INSERT INTO system_settings (key, value, description) VALUES
        ('max_file_size_mb', '50', '添付ファイルの最大サイズ（MB）'),
        ('download_expiry_days', '30', 'ダウンロードURLの有効期間（日）'),
        ('max_downloads', '10', 'ファイルごとの最大ダウンロード回数'),
        ('auth_code_expiry_minutes', '10', '認証コードの有効期間（分）'),
        ('auth_code_max_attempts', '5', '認証コードの最大入力失敗回数'),
        ('session_expiry_days', '14', '認証セッションの保持期間（日）'),
        ('rate_limit_per_minute', '30', 'IPあたりのレート制限（回/分）'),
        ('notification_email', 'admin@tbnet.jp', 'アラート通知先メール'),
        ('portal_domain', 'download.tbnet.jp', 'ダウンロードポータルのドメイン')
    """)

    # excluded_domains
    op.create_table(
        "excluded_domains",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("domain", sa.String(255), unique=True, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )

    # audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"),
                  primary_key=True),
        sa.Column("actor_email", sa.String(255)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50)),
        sa.Column("target_id", UUID(as_uuid=True)),
        sa.Column("details", JSONB),
        sa.Column("ip_address", INET),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()")),
    )
    op.create_index("idx_audit_logs_created", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("excluded_domains")
    op.drop_table("download_logs")
    op.drop_table("auth_sessions")
    op.drop_table("auth_codes")
    op.drop_table("attachments")
    op.drop_table("recipients")
    op.drop_table("system_settings")
    op.drop_table("transfers")
