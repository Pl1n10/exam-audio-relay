from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

# Configure environment BEFORE importing the app
_tmp = tempfile.TemporaryDirectory()
_db_file = Path(_tmp.name) / "test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_db_file}")
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-secret-key")
os.environ.setdefault("INITIAL_ADMIN_USERNAME", "")
os.environ.setdefault("INITIAL_ADMIN_PASSWORD", "")
os.environ.setdefault("SESSION_COOKIE_SECURE", "false")
os.environ["DATA_DIR"] = _tmp.name
os.environ["UPLOAD_DIR"] = str(Path(_tmp.name) / "uploads")


@pytest.fixture(scope="session")
def _db_setup() -> Generator[None, None, None]:
    from app.config import get_settings  # noqa: WPS433
    from app.database import Base, engine  # noqa: WPS433
    from app import models  # noqa: F401, WPS433

    get_settings.cache_clear()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db_session(_db_setup):
    from app.database import SessionLocal  # noqa: WPS433
    from app.models import AccessLog, AudioFile, ExamSession, User  # noqa: WPS433

    session = SessionLocal()
    try:
        # Clean tables to keep tests independent
        session.query(AccessLog).delete()
        session.query(ExamSession).delete()
        session.query(AudioFile).delete()
        session.query(User).delete()
        session.commit()
        yield session
    finally:
        session.close()
