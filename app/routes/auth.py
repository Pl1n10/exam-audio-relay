from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import login_user, logout_user
from app.database import get_db
from app.deps import render
from app.models import User
from app.security import verify_password


router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "login.html", error=None)


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return render(request, "login.html", error="Invalid credentials or account disabled")
    login_user(request, user)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout(request: Request):
    logout_user(request)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/")
def root(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
