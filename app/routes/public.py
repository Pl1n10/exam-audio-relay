from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import render
from app.models import EventType, ExamSession
from app.session_logic import evaluate_session, log_event
from app.storage import absolute_path_for


router = APIRouter()

CHUNK_SIZE = 1024 * 64


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    return request.client.host


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _load_session(db: Session, token: str) -> ExamSession | None:
    if not token or len(token) > 128:
        return None
    return db.scalar(select(ExamSession).where(ExamSession.token == token))


@router.get("/s/{token}")
def public_session_page(token: str, request: Request, db: Session = Depends(get_db)):
    sess = _load_session(db, token)
    teacher = sess.owner if sess else None
    decision = evaluate_session(db, sess, teacher)

    log_event(
        db,
        session_id=sess.id if sess else None,
        event_type=decision.deny_event if not decision.allowed else EventType.PAGE_VIEW,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )

    if not decision.allowed or sess is None:
        if sess is None:
            return render(request, "unavailable.html", message="This session is not available.")
        if decision.status.value == "scheduled":
            return render(
                request,
                "unavailable.html",
                message="This audio session is not active yet.",
                starts_at=sess.starts_at,
            )
        if decision.status.value == "expired":
            return render(request, "unavailable.html", message="This audio session has expired.")
        return render(request, "unavailable.html", message="This session is not available.")

    return render(
        request,
        "public_session.html",
        sess=sess,
        token=token,
    )


def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int] | None:
    if not range_header.startswith("bytes="):
        return None
    spec = range_header[6:].split(",", 1)[0].strip()
    if "-" not in spec:
        return None
    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "":
            # suffix: bytes=-N → last N bytes
            length = int(end_s)
            if length <= 0:
                return None
            start = max(file_size - length, 0)
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
    except ValueError:
        return None
    if start < 0 or end < start or start >= file_size:
        return None
    end = min(end, file_size - 1)
    return start, end


def _iter_file(path: Path, start: int, end: int):
    remaining = end - start + 1
    with open(path, "rb") as f:
        f.seek(start)
        while remaining > 0:
            chunk = f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/stream/{token}")
def stream_audio(token: str, request: Request, db: Session = Depends(get_db)):
    sess = _load_session(db, token)
    teacher = sess.owner if sess else None
    decision = evaluate_session(db, sess, teacher, count_for_max=True)

    if not decision.allowed or sess is None:
        if not decision.allowed:
            log_event(
                db,
                session_id=sess.id if sess else None,
                event_type=decision.deny_event or EventType.DENIED_MISSING,
                ip_address=_client_ip(request),
                user_agent=_user_agent(request),
            )
        # Generic 404 to avoid leaking state
        return Response(status_code=status.HTTP_404_NOT_FOUND, content="Not Found")

    audio = sess.audio_file
    try:
        path = absolute_path_for(audio.stored_filename)
    except ValueError:
        return Response(status_code=status.HTTP_404_NOT_FOUND, content="Not Found")
    if not path.exists() or not path.is_file():
        return Response(status_code=status.HTTP_404_NOT_FOUND, content="Not Found")

    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    is_first_byte_request = not range_header or range_header.strip() in {"bytes=0-", "bytes=0-0"}
    if is_first_byte_request:
        log_event(
            db,
            session_id=sess.id,
            event_type=EventType.STREAM_START,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )

    common_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }

    if range_header:
        rng = _parse_range_header(range_header, file_size)
        if rng is None:
            return Response(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                headers={"Content-Range": f"bytes */{file_size}", **common_headers},
            )
        start, end = rng
        length = end - start + 1
        headers = {
            **common_headers,
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
        }
        return StreamingResponse(
            _iter_file(path, start, end),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=audio.content_type,
            headers=headers,
        )

    headers = {**common_headers, "Content-Length": str(file_size)}
    return StreamingResponse(
        _iter_file(path, 0, file_size - 1),
        status_code=status.HTTP_200_OK,
        media_type=audio.content_type,
        headers=headers,
    )
