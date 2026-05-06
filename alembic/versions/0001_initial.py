"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="teacher"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "audio_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(255), nullable=False, unique=True),
        sa.Column("content_type", sa.String(100), nullable=False, server_default="application/octet-stream"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audio_files_owner_user_id", "audio_files", ["owner_user_id"])

    op.create_table(
        "exam_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_file_id", sa.Integer(), sa.ForeignKey("audio_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("token", sa.String(128), nullable=False, unique=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_access_count", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_exam_sessions_owner_user_id", "exam_sessions", ["owner_user_id"])
    op.create_index("ix_exam_sessions_token", "exam_sessions", ["token"], unique=True)

    op.create_table(
        "access_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id", sa.Integer(), sa.ForeignKey("exam_sessions.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_access_logs_session_id", "access_logs", ["session_id"])
    op.create_index("ix_access_logs_created_at", "access_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_access_logs_created_at", table_name="access_logs")
    op.drop_index("ix_access_logs_session_id", table_name="access_logs")
    op.drop_table("access_logs")
    op.drop_index("ix_exam_sessions_token", table_name="exam_sessions")
    op.drop_index("ix_exam_sessions_owner_user_id", table_name="exam_sessions")
    op.drop_table("exam_sessions")
    op.drop_index("ix_audio_files_owner_user_id", table_name="audio_files")
    op.drop_table("audio_files")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
