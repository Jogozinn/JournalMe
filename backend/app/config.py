import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


def _optional_bool_environment(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


class Settings(BaseModel):
    app_name: str = os.getenv("JOURNALME_APP_NAME", "JournalMe")
    api_prefix: str = os.getenv("JOURNALME_API_PREFIX", "/api/v1")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./journalme.db")
    auto_migrate: bool | None = Field(
        default_factory=lambda: _optional_bool_environment("JOURNALME_AUTO_MIGRATE")
    )
    bootstrap_local_data: bool | None = Field(
        default_factory=lambda: _optional_bool_environment("JOURNALME_BOOTSTRAP_LOCAL_DATA")
    )
    storage_path: Path = Path(os.getenv("JOURNALME_STORAGE_PATH", "./storage"))
    data_provider: str = os.getenv("JOURNALME_DATA_PROVIDER", "local")
    storage_provider: str = os.getenv("JOURNALME_STORAGE_PROVIDER", "local")
    supabase_url: str | None = os.getenv("SUPABASE_URL")
    supabase_anon_key: str | None = os.getenv("SUPABASE_ANON_KEY")
    supabase_service_role_key: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    supabase_storage_bucket: str | None = os.getenv("SUPABASE_STORAGE_BUCKET")
    supabase_db_url: str | None = os.getenv("SUPABASE_DB_URL")
    supabase_jwt_audience: str = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    cors_origins: str = os.getenv(
        "JOURNALME_CORS_ORIGINS", "http://localhost:3070,http://127.0.0.1:3066"
    )
    max_upload_bytes: int = int(os.getenv("JOURNALME_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    local_user_email: str = os.getenv("JOURNALME_LOCAL_USER_EMAIL", "trader@journalme.local")
    local_user_name: str = os.getenv("JOURNALME_LOCAL_USER_NAME", "Trader")
    vapid_public_key: str | None = os.getenv("JOURNALME_VAPID_PUBLIC_KEY")
    vapid_private_key: str | None = os.getenv("JOURNALME_VAPID_PRIVATE_KEY")
    vapid_private_key_b64: str | None = os.getenv("JOURNALME_VAPID_PRIVATE_KEY_B64")
    vapid_subject: str | None = os.getenv("JOURNALME_VAPID_SUBJECT")
    push_interval_seconds: int = int(os.getenv("JOURNALME_PUSH_INTERVAL_SECONDS", "900"))

    @model_validator(mode="after")
    def validate_supported_providers(self) -> "Settings":
        if self.data_provider not in {"local", "supabase"}:
            raise ValueError(
                "Unsupported JOURNALME_DATA_PROVIDER. Supported values are 'local' and 'supabase'."
            )
        if self.storage_provider not in {"local", "supabase"}:
            raise ValueError(
                "Unsupported JOURNALME_STORAGE_PROVIDER. Supported values are 'local' and 'supabase'."
            )
        if self.data_provider == "supabase":
            if not self.supabase_db_url or not self.supabase_db_url.startswith("postgresql"):
                raise ValueError(
                    "SUPABASE_DB_URL must be a PostgreSQL URL when data provider is supabase."
                )
            if not self.supabase_url or not self.supabase_anon_key:
                raise ValueError(
                    "SUPABASE_URL and SUPABASE_ANON_KEY are required when data provider is supabase."
                )
            self.database_url = self.supabase_db_url
        if self.storage_provider == "supabase":
            if not all(
                [self.supabase_url, self.supabase_service_role_key, self.supabase_storage_bucket]
            ):
                raise ValueError(
                    "SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and SUPABASE_STORAGE_BUCKET are required when storage provider is supabase."
                )
        is_local_database = self.database_url.startswith("sqlite:")
        if self.auto_migrate is None:
            self.auto_migrate = is_local_database
        if self.bootstrap_local_data is None:
            self.bootstrap_local_data = is_local_database
        if self.data_provider == "supabase" and self.auto_migrate:
            raise ValueError(
                "Automatic migrations are disabled for Supabase mode; run `python -m app.migrations upgrade` as a controlled release step."
            )
        if self.data_provider == "supabase" and self.bootstrap_local_data:
            raise ValueError("Local user and starter-data bootstrap is disabled for Supabase mode.")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        # Browser Origin headers never include a trailing slash. Normalize the
        # deployment setting so an otherwise-correct Vercel origin still
        # matches if it was entered with one.
        origins: list[str] = []
        for raw in self.cors_origins.split(","):
            value = raw.strip()
            if not value:
                continue
            normalized = value.rstrip("/")
            if normalized and normalized not in origins:
                origins.append(normalized)
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
