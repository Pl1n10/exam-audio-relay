from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(StrEnum):
    SUPERADMIN = "superadmin"
    TEACHER = "teacher"


class EventType(StrEnum):
    PAGE_VIEW = "page_view"
    STREAM_START = "stream_start"
    DENIED_EXPIRED = "denied_expired"
    DENIED_REVOKED = "denied_revoked"
    DENIED_NOT_STARTED = "denied_not_started"
    DENIED_MISSING = "denied_missing"
    DENIED_TEACHER_DISABLED = "denied_teacher_disabled"
    DENIED_MAX_ACCESS = "denied_max_access"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=Role.TEACHER.value)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    audio_files: Mapped[list["AudioFile"]] = relationship(back_populates="owner", cascade="all,delete-orphan")
    sessions: Mapped[list["ExamSession"]] = relationship(back_populates="owner", cascade="all,delete-orphan")

    @property
    def is_superadmin(self) -> bool:
        return self.role == Role.SUPERADMIN.value


class AudioFile(Base):
    __tablename__ = "audio_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    owner: Mapped[User] = relationship(back_populates="audio_files")
    sessions: Mapped[list["ExamSession"]] = relationship(back_populates="audio_file", cascade="all,delete-orphan")


class ExamSession(Base):
    __tablename__ = "exam_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_file_id: Mapped[int] = mapped_column(ForeignKey("audio_files.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_access_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    owner: Mapped[User] = relationship(back_populates="sessions")
    audio_file: Mapped[AudioFile] = relationship(back_populates="sessions")
    access_logs: Mapped[list["AccessLog"]] = relationship(back_populates="session", cascade="all,delete-orphan")


class AccessLog(Base):
    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("exam_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)

    session: Mapped[ExamSession | None] = relationship(back_populates="access_logs")
