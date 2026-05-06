from __future__ import annotations

import os
import secrets
from pathlib import Path

from app.config import get_settings


ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg"}

EXTENSION_CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
}


def ensure_upload_dir() -> Path:
    settings = get_settings()
    path = settings.upload_path
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_allowed_extension(original_filename: str) -> bool:
    return Path(original_filename).suffix.lower() in ALLOWED_EXTENSIONS


def content_type_for(original_filename: str) -> str:
    return EXTENSION_CONTENT_TYPES.get(Path(original_filename).suffix.lower(), "application/octet-stream")


def generate_stored_filename(original_filename: str) -> str:
    ext = Path(original_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"extension not allowed: {ext}")
    return f"{secrets.token_hex(16)}{ext}"


def absolute_path_for(stored_filename: str) -> Path:
    """Return the absolute path under UPLOAD_DIR; reject any traversal attempts."""
    upload_dir = ensure_upload_dir().resolve()
    candidate = (upload_dir / stored_filename).resolve()
    try:
        candidate.relative_to(upload_dir)
    except ValueError as exc:
        raise ValueError("path traversal detected") from exc
    return candidate


def delete_file(stored_filename: str) -> None:
    try:
        path = absolute_path_for(stored_filename)
    except ValueError:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
