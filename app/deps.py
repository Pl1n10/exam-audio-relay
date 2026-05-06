from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import get_current_user, get_csrf_token
from app.config import get_settings
from app.database import get_db
from app.models import AudioFile, ExamSession, Role, User
from app.session_logic import derive_status


_settings = get_settings()
templates = Jinja2Templates(directory="app/templates")


def _format_local(value):
    if value is None:
        return ""
    if value.tzinfo is None:
        from datetime import timezone

        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_settings.tzinfo).strftime("%Y-%m-%d %H:%M")


templates.env.filters["local_dt"] = _format_local
templates.env.globals["app_name"] = _settings.APP_NAME
templates.env.globals["base_url"] = _settings.BASE_URL or ""


def render(request: Request, template: str, *, status_code: int = 200, **ctx):
    """Render a template with common variables (request, csrf_token, current_user)."""
    if "csrf_token" not in ctx:
        ctx["csrf_token"] = get_csrf_token(request)
    if "current_user" not in ctx:
        from app.auth import SESSION_USER_KEY  # noqa: WPS433 — local to break import cycle

        ctx["current_user"] = ctx.get("current_user")
        ctx["_have_session"] = bool(request.session.get(SESSION_USER_KEY))
    ctx["request"] = request
    ctx["derive_status"] = derive_status
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)


def get_owned_audio_file(
    file_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AudioFile:
    audio = db.get(AudioFile, file_id)
    if audio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if user.role != Role.SUPERADMIN.value and audio.owner_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return audio


def get_owned_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExamSession:
    sess = db.get(ExamSession, session_id)
    if sess is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if user.role != Role.SUPERADMIN.value and sess.owner_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return sess
