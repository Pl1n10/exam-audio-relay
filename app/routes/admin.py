from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, verify_csrf
from app.config import get_settings
from app.database import get_db
from app.deps import get_owned_audio_file, get_owned_session, render
from app.models import AccessLog, AudioFile, ExamSession, Role, User
from app.security import generate_session_token
from app.session_logic import access_count, derive_status
from app.storage import (
    absolute_path_for,
    content_type_for,
    delete_file,
    ensure_upload_dir,
    generate_stored_filename,
    is_allowed_extension,
)


router = APIRouter(prefix="/admin")
settings = get_settings()


# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------
@router.get("")
@router.get("/")
def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.role == Role.SUPERADMIN.value:
        sessions = db.scalars(select(ExamSession).order_by(ExamSession.created_at.desc())).all()
        files = db.scalars(select(AudioFile).order_by(AudioFile.created_at.desc())).all()
        teachers = db.scalars(select(User).order_by(User.created_at.desc())).all()
    else:
        sessions = db.scalars(
            select(ExamSession).where(ExamSession.owner_user_id == user.id).order_by(ExamSession.created_at.desc())
        ).all()
        files = db.scalars(
            select(AudioFile).where(AudioFile.owner_user_id == user.id).order_by(AudioFile.created_at.desc())
        ).all()
        teachers = []

    counts = {s.id: access_count(db, s.id) for s in sessions}
    return render(
        request,
        "admin_dashboard.html",
        current_user=user,
        sessions=sessions,
        files=files,
        teachers=teachers,
        access_counts=counts,
    )


# -----------------------------------------------------------------------------
# Audio files
# -----------------------------------------------------------------------------
@router.get("/files")
def files_list(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(AudioFile).order_by(AudioFile.created_at.desc())
    if user.role != Role.SUPERADMIN.value:
        stmt = stmt.where(AudioFile.owner_user_id == user.id)
    files = db.scalars(stmt).all()
    return render(request, "files.html", current_user=user, files=files)


@router.get("/upload")
def upload_form(request: Request, user: User = Depends(get_current_user)):
    return render(request, "upload.html", current_user=user, error=None)


@router.post("/upload", dependencies=[Depends(verify_csrf)])
async def upload_submit(
    request: Request,
    display_name: str = Form(...),
    description: str = Form(""),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    original = file.filename or ""
    if not is_allowed_extension(original):
        return render(
            request,
            "upload.html",
            current_user=user,
            error=f"Unsupported file extension. Allowed: .mp3 .wav .m4a .ogg",
        )

    upload_dir = ensure_upload_dir()
    stored_name = generate_stored_filename(original)
    target = upload_dir / stored_name

    max_bytes = settings.max_upload_bytes
    written = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    out.close()
                    target.unlink(missing_ok=True)
                    return render(
                        request,
                        "upload.html",
                        current_user=user,
                        error=f"File too large (max {settings.MAX_UPLOAD_MB} MB)",
                    )
                out.write(chunk)
    finally:
        await file.close()

    record = AudioFile(
        owner_user_id=user.id,
        display_name=display_name.strip() or Path(original).stem,
        description=(description or "").strip() or None,
        original_filename=Path(original).name,
        stored_filename=stored_name,
        content_type=content_type_for(original),
        size_bytes=written,
    )
    db.add(record)
    db.commit()
    return RedirectResponse("/admin/files", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/files/{file_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_audio_file(
    file_id: int,
    audio: AudioFile = Depends(get_owned_audio_file),
    db: Session = Depends(get_db),
):
    if audio.sessions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete: file is referenced by sessions. Revoke and remove them first.",
        )
    delete_file(audio.stored_filename)
    db.delete(audio)
    db.commit()
    return RedirectResponse("/admin/files", status_code=status.HTTP_303_SEE_OTHER)


# -----------------------------------------------------------------------------
# Sessions
# -----------------------------------------------------------------------------
def _parse_local_dt(value: str) -> datetime:
    """Parse an HTML datetime-local string ("2026-04-30T15:30") as configured local TZ -> UTC."""
    naive = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    return naive.replace(tzinfo=settings.tzinfo).astimezone(timezone.utc)


@router.get("/sessions/new")
def new_session_form(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(AudioFile).order_by(AudioFile.created_at.desc())
    if user.role != Role.SUPERADMIN.value:
        stmt = stmt.where(AudioFile.owner_user_id == user.id)
    files = db.scalars(stmt).all()
    return render(request, "new_session.html", current_user=user, files=files, error=None)


@router.post("/sessions/new", dependencies=[Depends(verify_csrf)])
def new_session_submit(
    request: Request,
    title: str = Form(...),
    audio_file_id: int = Form(...),
    mode: str = Form("scheduled"),  # "scheduled" or "now"
    starts_at: str | None = Form(None),
    ends_at: str | None = Form(None),
    duration_minutes: int | None = Form(None),
    max_access_count: str | None = Form(None),
    notes: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw_max = (max_access_count or "").strip()
    if not raw_max:
        max_access_count_value: int | None = None
    else:
        try:
            max_access_count_value = int(raw_max)
        except ValueError:
            return _new_session_error(request, user, db, "Invalid max access count")
        if max_access_count_value <= 0:
            max_access_count_value = None

    audio = db.get(AudioFile, audio_file_id)
    if audio is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found")
    if user.role != Role.SUPERADMIN.value and audio.owner_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your audio file")

    if mode == "now":
        if duration_minutes not in {15, 30, 45, 60, 90, 120}:
            return _new_session_error(request, user, db, "Pick a valid duration")
        start_utc = datetime.now(timezone.utc)
        end_utc = start_utc + timedelta(minutes=int(duration_minutes))
    else:
        if not starts_at or not ends_at:
            return _new_session_error(request, user, db, "Both start and end datetimes are required")
        try:
            start_utc = _parse_local_dt(starts_at)
            end_utc = _parse_local_dt(ends_at)
        except ValueError:
            return _new_session_error(request, user, db, "Invalid datetime format")

    if end_utc <= start_utc:
        return _new_session_error(request, user, db, "End must be after start")

    session = ExamSession(
        owner_user_id=audio.owner_user_id if user.role == Role.SUPERADMIN.value else user.id,
        audio_file_id=audio.id,
        title=title.strip()[:255],
        token=generate_session_token(),
        starts_at=start_utc,
        ends_at=end_utc,
        max_access_count=max_access_count_value,
        notes=(notes or "").strip() or None,
    )
    db.add(session)
    db.commit()
    return RedirectResponse(f"/admin/sessions/{session.id}", status_code=status.HTTP_303_SEE_OTHER)


def _new_session_error(request: Request, user: User, db: Session, msg: str):
    stmt = select(AudioFile).order_by(AudioFile.created_at.desc())
    if user.role != Role.SUPERADMIN.value:
        stmt = stmt.where(AudioFile.owner_user_id == user.id)
    files = db.scalars(stmt).all()
    return render(request, "new_session.html", current_user=user, files=files, error=msg)


@router.get("/sessions/{session_id}")
def session_detail(
    request: Request,
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    sess: ExamSession = Depends(get_owned_session),
):
    return render(
        request,
        "session_detail.html",
        current_user=user,
        sess=sess,
        access_count=access_count(db, sess.id),
        status=derive_status(sess),
    )


@router.post("/sessions/{session_id}/revoke", dependencies=[Depends(verify_csrf)])
def revoke_session(
    session_id: int,
    db: Session = Depends(get_db),
    sess: ExamSession = Depends(get_owned_session),
):
    if sess.revoked_at is None:
        sess.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return RedirectResponse(f"/admin/sessions/{sess.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sessions/{session_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_session(
    session_id: int,
    db: Session = Depends(get_db),
    sess: ExamSession = Depends(get_owned_session),
):
    db.delete(sess)
    db.commit()
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/sessions/{session_id}/logs")
def session_logs(
    request: Request,
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    sess: ExamSession = Depends(get_owned_session),
):
    logs = db.scalars(
        select(AccessLog).where(AccessLog.session_id == sess.id).order_by(AccessLog.created_at.desc())
    ).all()
    return render(request, "session_logs.html", current_user=user, sess=sess, logs=logs)
