from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AccessLog, EventType, ExamSession, User


class SessionStatus(StrEnum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    TEACHER_DISABLED = "teacher_disabled"
    MAX_ACCESS_REACHED = "max_access_reached"


@dataclass
class SessionDecision:
    allowed: bool
    status: SessionStatus
    reason: str
    deny_event: EventType | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def evaluate_session(
    db: Session,
    session: ExamSession | None,
    teacher: User | None,
    *,
    count_for_max: bool = False,
) -> SessionDecision:
    """Pure-ish business logic deciding whether a public session token may be used now.

    ``count_for_max`` should be True when evaluating an actual stream attempt — to compare
    historical stream_start events to ``max_access_count``.
    """
    if session is None:
        return SessionDecision(False, SessionStatus.EXPIRED, "missing", EventType.DENIED_MISSING)

    if session.revoked_at is not None:
        return SessionDecision(False, SessionStatus.REVOKED, "revoked", EventType.DENIED_REVOKED)

    if teacher is None or not teacher.is_active:
        return SessionDecision(
            False, SessionStatus.TEACHER_DISABLED, "teacher_disabled", EventType.DENIED_TEACHER_DISABLED
        )

    now = _now()
    starts = _ensure_aware(session.starts_at)
    ends = _ensure_aware(session.ends_at)

    if now < starts:
        return SessionDecision(False, SessionStatus.SCHEDULED, "not_started", EventType.DENIED_NOT_STARTED)

    if now >= ends:
        return SessionDecision(False, SessionStatus.EXPIRED, "expired", EventType.DENIED_EXPIRED)

    if count_for_max and session.max_access_count:
        used = db.scalar(
            select(func.count(AccessLog.id)).where(
                AccessLog.session_id == session.id,
                AccessLog.event_type == EventType.STREAM_START.value,
            )
        )
        if (used or 0) >= session.max_access_count:
            return SessionDecision(
                False, SessionStatus.MAX_ACCESS_REACHED, "max_access_reached", EventType.DENIED_MAX_ACCESS
            )

    return SessionDecision(True, SessionStatus.ACTIVE, "ok")


def derive_status(session: ExamSession) -> SessionStatus:
    """Best-effort status for dashboard display (does not check teacher.is_active)."""
    if session.revoked_at is not None:
        return SessionStatus.REVOKED
    now = _now()
    starts = _ensure_aware(session.starts_at)
    ends = _ensure_aware(session.ends_at)
    if now < starts:
        return SessionStatus.SCHEDULED
    if now >= ends:
        return SessionStatus.EXPIRED
    return SessionStatus.ACTIVE


def log_event(
    db: Session,
    *,
    session_id: int | None,
    event_type: EventType,
    ip_address: str | None,
    user_agent: str | None,
    commit: bool = True,
) -> AccessLog:
    entry = AccessLog(
        session_id=session_id,
        event_type=event_type.value,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:255] or None,
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry


def access_count(db: Session, session_id: int) -> int:
    val = db.scalar(
        select(func.count(AccessLog.id)).where(
            AccessLog.session_id == session_id,
            AccessLog.event_type == EventType.PAGE_VIEW.value,
        )
    )
    return int(val or 0)
