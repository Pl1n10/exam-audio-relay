from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_superadmin, verify_csrf
from app.database import get_db
from app.deps import render
from app.models import Role, User
from app.security import hash_password


router = APIRouter(prefix="/admin/teachers", dependencies=[Depends(require_superadmin)])


def _active_superadmin_count(db: Session, exclude_user_id: int | None = None) -> int:
    stmt = select(func.count(User.id)).where(User.role == Role.SUPERADMIN.value, User.is_active.is_(True))
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return int(db.scalar(stmt) or 0)


@router.get("")
@router.get("/")
def teachers_list(
    request: Request,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    teachers = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return render(request, "teachers.html", current_user=user, teachers=teachers)


@router.get("/new")
def new_teacher_form(request: Request, user: User = Depends(require_superadmin)):
    return render(request, "new_teacher.html", current_user=user, error=None)


@router.post("/new", dependencies=[Depends(verify_csrf)])
def new_teacher_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(""),
    display_name: str = Form(""),
    password: str = Form(...),
    role: str = Form(Role.TEACHER.value),
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    username = username.strip()
    if not username or len(username) > 64:
        return render(request, "new_teacher.html", current_user=user, error="Username required (max 64 chars)")
    if role not in {Role.TEACHER.value, Role.SUPERADMIN.value}:
        return render(request, "new_teacher.html", current_user=user, error="Invalid role")
    if len(password) < 8:
        return render(request, "new_teacher.html", current_user=user, error="Password must be at least 8 characters")
    if db.scalar(select(User).where(User.username == username)):
        return render(request, "new_teacher.html", current_user=user, error="Username already exists")

    new_user = User(
        username=username,
        email=email.strip() or None,
        display_name=display_name.strip() or username,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse(f"/admin/teachers/{new_user.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{teacher_id}")
def teacher_detail(
    request: Request,
    teacher_id: int,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    teacher = db.get(User, teacher_id)
    if teacher is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")
    can_disable = not (teacher.is_superadmin and teacher.is_active and _active_superadmin_count(db, teacher.id) == 0)
    can_demote = not (teacher.is_superadmin and teacher.is_active and _active_superadmin_count(db, teacher.id) == 0)
    return render(
        request,
        "teacher_detail.html",
        current_user=user,
        teacher=teacher,
        can_disable=can_disable,
        can_demote=can_demote,
        error=None,
        info=None,
    )


@router.post("/{teacher_id}/toggle-active", dependencies=[Depends(verify_csrf)])
def toggle_active(
    teacher_id: int,
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    teacher = db.get(User, teacher_id)
    if teacher is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")

    if teacher.is_active and teacher.is_superadmin and _active_superadmin_count(db, teacher.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot disable the last active superadmin",
        )

    teacher.is_active = not teacher.is_active
    db.commit()
    return RedirectResponse(f"/admin/teachers/{teacher.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{teacher_id}/role", dependencies=[Depends(verify_csrf)])
def change_role(
    teacher_id: int,
    role: str = Form(...),
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    if role not in {Role.TEACHER.value, Role.SUPERADMIN.value}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")
    teacher = db.get(User, teacher_id)
    if teacher is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")

    is_demotion = teacher.is_superadmin and role == Role.TEACHER.value
    if is_demotion and teacher.is_active and _active_superadmin_count(db, teacher.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot demote the last active superadmin",
        )

    teacher.role = role
    db.commit()
    return RedirectResponse(f"/admin/teachers/{teacher.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{teacher_id}/reset-password", dependencies=[Depends(verify_csrf)])
def reset_password(
    request: Request,
    teacher_id: int,
    new_password: str = Form(...),
    user: User = Depends(require_superadmin),
    db: Session = Depends(get_db),
):
    teacher = db.get(User, teacher_id)
    if teacher is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher not found")
    if len(new_password) < 8:
        return render(
            request,
            "teacher_detail.html",
            current_user=user,
            teacher=teacher,
            error="Password must be at least 8 characters",
            info=None,
            can_disable=True,
            can_demote=True,
        )
    teacher.password_hash = hash_password(new_password)
    db.commit()
    return RedirectResponse(f"/admin/teachers/{teacher.id}?reset=ok", status_code=status.HTTP_303_SEE_OTHER)
