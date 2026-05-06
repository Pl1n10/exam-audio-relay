from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User
from app.security import constant_time_equals, generate_csrf_token


SESSION_USER_KEY = "user_id"
SESSION_CSRF_KEY = "csrf_token"


def login_user(request: Request, user: User) -> str:
    """Mark the request session as authenticated for ``user`` and return a fresh CSRF token."""
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    csrf = generate_csrf_token()
    request.session[SESSION_CSRF_KEY] = csrf
    return csrf


def logout_user(request: Request) -> None:
    request.session.clear()


def get_csrf_token(request: Request) -> str:
    token = request.session.get(SESSION_CSRF_KEY)
    if not token:
        token = generate_csrf_token()
        request.session[SESSION_CSRF_KEY] = token
    return token


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get(SESSION_USER_KEY)
    if not uid:
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def require_superadmin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.SUPERADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return user


async def verify_csrf(request: Request) -> None:
    """Validate CSRF token on state-changing requests under /admin.

    The token must be present in form data ``csrf_token`` and match the value stored in the
    user's session cookie. Read-only methods are skipped. Pre-auth /login endpoint must not
    use this dependency.
    """
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    expected = request.session.get(SESSION_CSRF_KEY)
    if not expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF token missing in session")
    submitted: str | None = None
    ctype = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
        form = await request.form()
        raw = form.get("csrf_token")
        if isinstance(raw, str):
            submitted = raw
    if submitted is None:
        submitted = request.headers.get("x-csrf-token")
    if not submitted or not constant_time_equals(submitted, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
