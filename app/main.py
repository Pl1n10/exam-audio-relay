from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import SessionLocal, engine
from app.deps import render
from app.models import Role, User
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.public import router as public_router
from app.routes.teachers import router as teachers_router
from app.security import hash_password
from app.storage import ensure_upload_dir


logger = logging.getLogger("exam_audio_relay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _wait_for_db(max_attempts: int = 30, delay_seconds: float = 1.0) -> None:
    import time

    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("DB not ready (attempt %s/%s): %s", attempt, max_attempts, exc)
            time.sleep(delay_seconds)
    raise RuntimeError("Database not reachable after retries")


def _bootstrap_initial_admin() -> None:
    settings = get_settings()
    if not settings.INITIAL_ADMIN_USERNAME or not settings.INITIAL_ADMIN_PASSWORD:
        logger.info("Initial admin env vars missing; skipping bootstrap")
        return
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == settings.INITIAL_ADMIN_USERNAME))
        if existing:
            logger.info("Initial admin %r already exists; skipping bootstrap", settings.INITIAL_ADMIN_USERNAME)
            return
        admin = User(
            username=settings.INITIAL_ADMIN_USERNAME,
            email=settings.INITIAL_ADMIN_EMAIL,
            display_name=settings.INITIAL_ADMIN_USERNAME,
            password_hash=hash_password(settings.INITIAL_ADMIN_PASSWORD),
            role=Role.SUPERADMIN.value,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        logger.info("Created initial superadmin %r", settings.INITIAL_ADMIN_USERNAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    ensure_upload_dir()
    _wait_for_db()
    # Schema is managed via Alembic; do not create_all here.
    _bootstrap_initial_admin()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SECRET_KEY,
        session_cookie="exam_relay_session",
        same_site="lax",
        https_only=settings.SESSION_COOKIE_SECURE,
        max_age=60 * 60 * 8,  # 8h
    )

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    app.include_router(auth_router)
    app.include_router(public_router)
    app.include_router(admin_router)
    app.include_router(teachers_router)

    @app.exception_handler(HTTPException)
    async def http_exc_handler(request: Request, exc: HTTPException):
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            try:
                return render(request, "unavailable.html", message="Forbidden", status_code=403)
            except Exception:  # noqa: BLE001
                return Response(status_code=403, content="Forbidden")
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            try:
                return render(request, "unavailable.html", message="Not found", status_code=404)
            except Exception:  # noqa: BLE001
                return Response(status_code=404, content="Not found")
        return Response(status_code=exc.status_code, content=str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exc_handler(request: Request, exc: RequestValidationError):
        return Response(status_code=status.HTTP_400_BAD_REQUEST, content="Bad request")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()
