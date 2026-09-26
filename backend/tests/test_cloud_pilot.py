from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth import SupabaseIdentityProvider
from app.database import Base
from app.models import AuthIdentity, User
from app.storage import SupabaseStorageProvider


def test_supabase_storage_provider_uses_private_opaque_keys() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/missing.png"):
            return httpx.Response(
                400, json={"code": "NoSuchKey", "message": "Object not found"}, request=request
            )
        if "/object/sign/" in request.url.path:
            return httpx.Response(
                200, json={"signedURL": "/object/sign/journalme-assets/x"}, request=request
            )
        return httpx.Response(200, content=b"bytes", request=request)

    storage = SupabaseStorageProvider(
        "https://example.supabase.co",
        "server-only",
        "journalme-assets",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    key = storage.put(uuid4(), "../chart.png", b"bytes")
    assert key.startswith("users/")
    assert storage.get(key) == b"bytes"
    assert storage.exists("users/test/objects/missing.png") is False
    assert storage.signed_read_url(key).startswith("https://example.supabase.co/")
    with pytest.raises(ValueError, match="Invalid storage key"):
        storage.get("../../machine-path")
    assert all("server-only" not in str(call.url) for call in calls)


def test_supabase_identity_requires_explicit_mapping() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="pilot@example.com", display_name="Pilot")
        db.add(user)
        db.commit()
        provider = SupabaseIdentityProvider(lambda _: {"sub": "auth-user"})
        with pytest.raises(HTTPException) as missing:
            provider.current_user(db, "valid-token")
        assert missing.value.status_code == 403
        db.add(AuthIdentity(user_id=user.id, provider="supabase", subject="auth-user"))
        db.commit()
        assert provider.current_user(db, "valid-token").id == user.id


def test_supabase_identity_rejects_invalid_token() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        provider = SupabaseIdentityProvider(lambda _: (_ for _ in ()).throw(ValueError("bad")))
        with pytest.raises(HTTPException) as response:
            provider.current_user(db, "invalid-token")
        assert response.value.status_code == 401


def test_migration_dry_run_never_mutates_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "journalme.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="local@example.com", display_name="Local")
        db.add(user)
        db.commit()
        local_user_id = user.id
    migration_script = (
        Path(__file__).resolve().parents[2] / "tools" / "migrate_local_to_cloud.py"
    )
    assert migration_script.exists(), migration_script
    spec = importlib.util.spec_from_file_location(
        "cloud_migration", migration_script
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = tmp_path / "validation.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "migrate_local_to_cloud.py",
            "--dry-run",
            "--local-database-url",
            f"sqlite:///{database}",
            "--local-storage-path",
            str(tmp_path / "storage"),
            "--local-user-id",
            str(local_user_id),
            "--supabase-auth-subject",
            str(uuid4()),
            "--report",
            str(report),
        ],
    )
    assert module.run() == 0
    assert '"ok": true' in report.read_text(encoding="utf-8")
    with engine.connect() as source:
        assert source.execute(User.__table__.select()).fetchall()[0].email == "local@example.com"
