from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO

from fastapi.testclient import TestClient


def _client():
    from app.main import app  # noqa: WPS433

    return TestClient(app)


def _login(c: TestClient, username: str, password: str) -> str:
    r = c.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    page = c.get("/admin/upload")
    # extract csrf token from form
    token = _extract_csrf(page.text)
    return token


def _extract_csrf(html: str) -> str:
    import re

    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "csrf token not found in page"
    return m.group(1)


def test_full_happy_path(db_session):
    # Create a superadmin & teacher directly in DB
    from app.models import Role, User
    from app.security import hash_password

    sa = User(
        username="admin",
        password_hash=hash_password("adminpass"),
        display_name="Admin",
        role=Role.SUPERADMIN.value,
        is_active=True,
    )
    teacher = User(
        username="teach1",
        password_hash=hash_password("teachpass"),
        display_name="Teacher One",
        role=Role.TEACHER.value,
        is_active=True,
    )
    db_session.add_all([sa, teacher])
    db_session.commit()

    c = _client()

    # 1. Teacher logs in
    csrf = _login(c, "teach1", "teachpass")

    # 2. Upload a fake mp3
    fake_audio = BytesIO(b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff" * 1024)
    r = c.post(
        "/admin/upload",
        data={"display_name": "Test track", "description": "x", "csrf_token": csrf},
        files={"file": ("hello.mp3", fake_audio, "audio/mpeg")},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text

    # 3. Create "start now for 60 minutes" session
    page = c.get("/admin/sessions/new")
    csrf = _extract_csrf(page.text)
    from app.models import AudioFile

    audio = db_session.query(AudioFile).filter_by(owner_user_id=teacher.id).first()
    r = c.post(
        "/admin/sessions/new",
        data={
            "title": "Exam 1",
            "audio_file_id": str(audio.id),
            "mode": "now",
            "duration_minutes": "60",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text

    from app.models import ExamSession

    sess = db_session.query(ExamSession).filter_by(owner_user_id=teacher.id).first()
    assert sess is not None
    assert sess.token

    # 4. Public page works
    r = c.get(f"/s/{sess.token}")
    assert r.status_code == 200
    assert "Exam 1" in r.text

    # 5. Stream returns audio bytes
    r = c.get(f"/stream/{sess.token}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/")
    assert len(r.content) >= 1024
    assert r.headers.get("accept-ranges") == "bytes"

    # 6. Range request returns 206 Partial Content
    r = c.get(f"/stream/{sess.token}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert r.headers["content-range"].startswith("bytes 0-99/")
    assert len(r.content) == 100

    # 7. Revoke -> link stops working
    detail = c.get(f"/admin/sessions/{sess.id}")
    csrf = _extract_csrf(detail.text)
    r = c.post(
        f"/admin/sessions/{sess.id}/revoke",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    r = c.get(f"/s/{sess.token}")
    assert r.status_code == 200  # generic unavailable page
    assert "unavailable" in r.text.lower()
    r = c.get(f"/stream/{sess.token}")
    assert r.status_code == 404

    # 8. Other teacher cannot see the file/session
    other = User(
        username="teach2",
        password_hash=hash_password("teachpass"),
        display_name="Teacher Two",
        role=Role.TEACHER.value,
        is_active=True,
    )
    db_session.add(other)
    db_session.commit()

    c2 = TestClient(__import__("app.main", fromlist=["app"]).app)
    c2.post("/login", data={"username": "teach2", "password": "teachpass"}, follow_redirects=False)
    r = c2.get(f"/admin/sessions/{sess.id}")
    # Forbidden -> rendered as the unavailable page with 403 status
    assert r.status_code == 403


def test_csrf_required_for_admin_post(db_session):
    from app.models import Role, User
    from app.security import hash_password

    teacher = User(
        username="t-csrf",
        password_hash=hash_password("teachpass"),
        display_name="t",
        role=Role.TEACHER.value,
        is_active=True,
    )
    db_session.add(teacher)
    db_session.commit()

    c = _client()
    c.post("/login", data={"username": "t-csrf", "password": "teachpass"}, follow_redirects=False)

    fake_audio = BytesIO(b"\x00" * 256)
    # Missing csrf_token -> 403
    r = c.post(
        "/admin/upload",
        data={"display_name": "x"},
        files={"file": ("h.mp3", fake_audio, "audio/mpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 403

    # Wrong csrf_token -> 403
    fake_audio = BytesIO(b"\x00" * 256)
    r = c.post(
        "/admin/upload",
        data={"display_name": "x", "csrf_token": "wrong"},
        files={"file": ("h.mp3", fake_audio, "audio/mpeg")},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_login_required_for_admin(db_session):
    c = _client()
    r = c.get("/admin", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert r.headers["location"] == "/login"


def test_unknown_token_shows_unavailable(db_session):
    c = _client()
    r = c.get("/s/some-bogus-token")
    assert r.status_code == 200
    assert "unavailable" in r.text.lower()

    r = c.get("/stream/some-bogus-token")
    assert r.status_code == 404
