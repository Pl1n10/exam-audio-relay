from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.deps import get_owned_audio_file, get_owned_session
from app.models import AudioFile, ExamSession, Role, User
from app.security import generate_session_token, hash_password


def _make_teacher(db, *, role: str = Role.TEACHER.value, active: bool = True) -> User:
    u = User(
        username=f"u{generate_session_token()[:10]}",
        password_hash=hash_password("password"),
        display_name="x",
        role=role,
        is_active=active,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_audio(db, owner: User) -> AudioFile:
    a = AudioFile(
        owner_user_id=owner.id,
        display_name="audio",
        original_filename="a.mp3",
        stored_filename=f"{generate_session_token()[:16]}.mp3",
        content_type="audio/mpeg",
        size_bytes=1,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_session(db, owner: User, audio: AudioFile) -> ExamSession:
    now = datetime.now(timezone.utc)
    s = ExamSession(
        owner_user_id=owner.id,
        audio_file_id=audio.id,
        title="s",
        token=generate_session_token(),
        starts_at=now - timedelta(minutes=1),
        ends_at=now + timedelta(hours=1),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def test_teacher_cannot_access_other_teacher_file(db_session):
    t1 = _make_teacher(db_session)
    t2 = _make_teacher(db_session)
    audio = _make_audio(db_session, t1)

    # Owner allowed
    assert get_owned_audio_file(audio.id, user=t1, db=db_session) is audio

    # Other teacher denied
    with pytest.raises(HTTPException) as exc_info:
        get_owned_audio_file(audio.id, user=t2, db=db_session)
    assert exc_info.value.status_code == 403


def test_teacher_cannot_access_other_teacher_session(db_session):
    t1 = _make_teacher(db_session)
    t2 = _make_teacher(db_session)
    audio = _make_audio(db_session, t1)
    sess = _make_session(db_session, t1, audio)

    assert get_owned_session(sess.id, user=t1, db=db_session) is sess
    with pytest.raises(HTTPException) as exc_info:
        get_owned_session(sess.id, user=t2, db=db_session)
    assert exc_info.value.status_code == 403


def test_superadmin_can_access_anything(db_session):
    teacher = _make_teacher(db_session)
    superadmin = _make_teacher(db_session, role=Role.SUPERADMIN.value)
    audio = _make_audio(db_session, teacher)
    sess = _make_session(db_session, teacher, audio)

    assert get_owned_audio_file(audio.id, user=superadmin, db=db_session) is audio
    assert get_owned_session(sess.id, user=superadmin, db=db_session) is sess


def test_last_active_superadmin_cannot_be_disabled_or_demoted(db_session):
    from app.routes.teachers import _active_superadmin_count  # noqa: WPS433

    sa1 = _make_teacher(db_session, role=Role.SUPERADMIN.value)
    # Only one active superadmin exists
    assert _active_superadmin_count(db_session, exclude_user_id=sa1.id) == 0

    # Add a teacher (still only 1 superadmin)
    _make_teacher(db_session)
    assert _active_superadmin_count(db_session, exclude_user_id=sa1.id) == 0

    # Add another superadmin -> now safe
    sa2 = _make_teacher(db_session, role=Role.SUPERADMIN.value)
    assert _active_superadmin_count(db_session, exclude_user_id=sa1.id) == 1
    assert _active_superadmin_count(db_session, exclude_user_id=sa2.id) == 1


def test_password_hashing_roundtrip():
    from app.security import verify_password  # noqa: WPS433

    h = hash_password("hunter2-secret")
    assert h != "hunter2-secret"
    assert verify_password("hunter2-secret", h)
    assert not verify_password("hunter2-wrong", h)
    assert not verify_password("", h)
