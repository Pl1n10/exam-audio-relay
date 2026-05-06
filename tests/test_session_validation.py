from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import AudioFile, EventType, ExamSession, Role, User
from app.security import generate_session_token, hash_password
from app.session_logic import (
    SessionStatus,
    derive_status,
    evaluate_session,
    log_event,
)


def _user(active: bool = True, role: str = Role.TEACHER.value) -> User:
    return User(
        username=f"u{generate_session_token()[:8]}",
        password_hash=hash_password("password"),
        display_name="t",
        role=role,
        is_active=active,
    )


def _audio(owner: User) -> AudioFile:
    return AudioFile(
        owner=owner,
        display_name="audio",
        original_filename="a.mp3",
        stored_filename=f"{generate_session_token()[:16]}.mp3",
        content_type="audio/mpeg",
        size_bytes=1000,
    )


def _session(
    owner: User,
    audio: AudioFile,
    *,
    starts_at: datetime,
    ends_at: datetime,
    revoked: bool = False,
    max_access: int | None = None,
) -> ExamSession:
    return ExamSession(
        owner=owner,
        audio_file=audio,
        title="t",
        token=generate_session_token(),
        starts_at=starts_at,
        ends_at=ends_at,
        revoked_at=datetime.now(timezone.utc) if revoked else None,
        max_access_count=max_access,
    )


def _persist(db, *objs):
    for o in objs:
        db.add(o)
    db.commit()


@pytest.fixture()
def now():
    return datetime.now(timezone.utc)


def test_evaluate_missing_session(db_session):
    decision = evaluate_session(db_session, None, None)
    assert decision.allowed is False
    assert decision.deny_event == EventType.DENIED_MISSING


def test_evaluate_active(db_session, now):
    teacher = _user()
    audio = _audio(teacher)
    sess = _session(teacher, audio, starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(minutes=30))
    _persist(db_session, teacher, audio, sess)

    decision = evaluate_session(db_session, sess, teacher)
    assert decision.allowed is True
    assert decision.status == SessionStatus.ACTIVE


def test_evaluate_not_started(db_session, now):
    teacher = _user()
    audio = _audio(teacher)
    sess = _session(teacher, audio, starts_at=now + timedelta(hours=1), ends_at=now + timedelta(hours=2))
    _persist(db_session, teacher, audio, sess)

    decision = evaluate_session(db_session, sess, teacher)
    assert decision.allowed is False
    assert decision.deny_event == EventType.DENIED_NOT_STARTED
    assert derive_status(sess) == SessionStatus.SCHEDULED


def test_evaluate_expired(db_session, now):
    teacher = _user()
    audio = _audio(teacher)
    sess = _session(teacher, audio, starts_at=now - timedelta(hours=2), ends_at=now - timedelta(minutes=1))
    _persist(db_session, teacher, audio, sess)

    decision = evaluate_session(db_session, sess, teacher)
    assert decision.allowed is False
    assert decision.deny_event == EventType.DENIED_EXPIRED
    assert derive_status(sess) == SessionStatus.EXPIRED


def test_evaluate_revoked(db_session, now):
    teacher = _user()
    audio = _audio(teacher)
    sess = _session(
        teacher, audio, starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(minutes=30), revoked=True
    )
    _persist(db_session, teacher, audio, sess)

    decision = evaluate_session(db_session, sess, teacher)
    assert decision.allowed is False
    assert decision.deny_event == EventType.DENIED_REVOKED
    assert derive_status(sess) == SessionStatus.REVOKED


def test_evaluate_teacher_disabled(db_session, now):
    teacher = _user(active=False)
    audio = _audio(teacher)
    sess = _session(teacher, audio, starts_at=now - timedelta(minutes=5), ends_at=now + timedelta(minutes=30))
    _persist(db_session, teacher, audio, sess)

    decision = evaluate_session(db_session, sess, teacher)
    assert decision.allowed is False
    assert decision.deny_event == EventType.DENIED_TEACHER_DISABLED


def test_max_access_count_blocks_new_streams(db_session, now):
    teacher = _user()
    audio = _audio(teacher)
    sess = _session(
        teacher,
        audio,
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(minutes=30),
        max_access=2,
    )
    _persist(db_session, teacher, audio, sess)

    # First two stream_starts should pass; third must be denied.
    for _ in range(2):
        decision = evaluate_session(db_session, sess, teacher, count_for_max=True)
        assert decision.allowed is True
        log_event(
            db_session,
            session_id=sess.id,
            event_type=EventType.STREAM_START,
            ip_address="127.0.0.1",
            user_agent="ua",
        )

    decision = evaluate_session(db_session, sess, teacher, count_for_max=True)
    assert decision.allowed is False
    assert decision.deny_event == EventType.DENIED_MAX_ACCESS

    # Page-view evaluation (count_for_max=False) is independent of max_access
    decision_page = evaluate_session(db_session, sess, teacher, count_for_max=False)
    assert decision_page.allowed is True
