from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Exam Audio Relay"
    DATABASE_URL: str = "postgresql+psycopg://exam:exam_password@db:5432/exam_audio"

    INITIAL_ADMIN_USERNAME: str = "admin"
    INITIAL_ADMIN_PASSWORD: str = "change_me_now"
    INITIAL_ADMIN_EMAIL: str | None = None

    DATA_DIR: str = "/data"
    UPLOAD_DIR: str = "/data/uploads"
    MAX_UPLOAD_MB: int = 250

    HOST: str = "0.0.0.0"
    PORT: int = 8080

    SECRET_KEY: str = "replace_me"
    SESSION_COOKIE_SECURE: bool = False

    BASE_URL: str | None = None
    TZ: str = "Europe/Rome"

    @property
    def upload_path(self) -> Path:
        return Path(self.UPLOAD_DIR)

    @property
    def data_path(self) -> Path:
        return Path(self.DATA_DIR)

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.TZ)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
