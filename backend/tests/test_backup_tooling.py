from __future__ import annotations

import hashlib
import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import make_url

from app import backup
from app.backup import BackupError


@contextmanager
def _private_test_workspace():
    path = Path(__file__).resolve().parents[2] / f".backup-test-{uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path)


def test_private_storage_export_inventory_and_checksum(monkeypatch) -> None:
    image = b"private-image-data"
    pages = {
        "": [{"name": "users", "id": None, "metadata": None}],
        "users": [{"name": "owner-1", "id": None, "metadata": None}],
        "users/owner-1": [{"name": "objects", "id": None, "metadata": None}],
        "users/owner-1/objects": [
            {
                "name": "chart.png",
                "id": "object-1",
                "metadata": {
                    "size": len(image),
                    "mimetype": "image/png",
                    "cacheControl": "3600",
                },
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/bucket/journalme-assets"):
            return httpx.Response(200, json={"id": "journalme-assets", "public": False})
        if request.method == "POST" and request.url.path.endswith("/object/list/journalme-assets"):
            prefix = json.loads(request.content)["prefix"]
            return httpx.Response(200, json=pages[prefix])
        if request.method == "GET" and request.url.path.endswith("/chart.png"):
            return httpx.Response(200, content=image)
        return httpx.Response(404)

    monkeypatch.setattr(
        backup,
        "get_settings",
        lambda: SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="local-test-only",
            supabase_storage_bucket="journalme-assets",
        ),
    )
    monkeypatch.setattr(backup, "_protect_new_directory", lambda path: path.mkdir(parents=True))
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with _private_test_workspace() as temporary:
        destination = temporary / "private-export"
        result = backup.export_storage(destination, client)

        assert result["object_count"] == 1
        assert backup.verify_storage_export(destination) == {
            "status": "verified",
            "object_count": 1,
            "total_bytes": len(image),
        }
        manifest = json.loads((destination / "storage-manifest.json").read_text())
        assert manifest["objects"][0]["key"] == "users/owner-1/objects/chart.png"
        assert manifest["objects"][0]["content_type"] == "image/png"
        assert "local-test-only" not in (destination / "storage-manifest.json").read_text()
        assert (destination / "objects/users/owner-1/objects/chart.png").read_bytes() == image

        (destination / "objects/users/owner-1/objects/chart.png").write_bytes(b"changed")
        with pytest.raises(BackupError, match="checksum differs"):
            backup.verify_storage_export(destination)
    client.close()


def test_storage_export_refuses_public_bucket(monkeypatch) -> None:
    monkeypatch.setattr(
        backup,
        "get_settings",
        lambda: SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_service_role_key="local-test-only",
            supabase_storage_bucket="journalme-assets",
        ),
    )
    monkeypatch.setattr(backup, "_protect_new_directory", lambda path: path.mkdir(parents=True))
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"id": "journalme-assets", "public": True})
        )
    )
    with _private_test_workspace() as temporary:
        with pytest.raises(BackupError, match="bucket is public"):
            backup.export_storage(temporary / "public-export", client)
    client.close()


def test_storage_restore_is_local_private_create_only_and_verified(monkeypatch) -> None:
    content = b"restore-image"
    key = "users/owner-1/objects/chart.png"
    stored: dict[str, bytes] = {}
    monkeypatch.setattr(
        backup,
        "get_settings",
        lambda: SimpleNamespace(
            supabase_url="http://127.0.0.1:54321",
            supabase_service_role_key="local-test-only",
            supabase_storage_bucket="journalme-assets",
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/bucket/journalme-assets"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST" and request.url.path.endswith(key):
            assert request.headers["x-upsert"] == "false"
            if key in stored:
                return httpx.Response(409)
            stored[key] = request.content
            return httpx.Response(200)
        if request.method == "GET" and request.url.path.endswith(key):
            return (
                httpx.Response(200, content=stored[key]) if key in stored else httpx.Response(404)
            )
        return httpx.Response(404)

    with _private_test_workspace() as temporary:
        directory = temporary / "storage-export"
        (directory / "objects/users/owner-1/objects").mkdir(parents=True)
        object_path = directory / "objects" / key
        object_path.write_bytes(content)
        (directory / "storage-manifest.json").write_text(
            json.dumps(
                {
                    "bucket": "journalme-assets",
                    "object_count": 1,
                    "total_bytes": len(content),
                    "objects": [
                        {
                            "key": key,
                            "bytes": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "content_type": "image/png",
                            "cache_control": "3600",
                        }
                    ],
                }
            )
        )
        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert backup.restore_storage(directory, client)["object_count"] == 1
        assert backup.restore_storage(directory, client)["object_count"] == 1
        stored[key] = b"different-existing-object"
        with pytest.raises(BackupError, match="no overwrite was attempted"):
            backup.restore_storage(directory, client)
        client.close()


def test_database_restore_only_accepts_loopback_targets() -> None:
    with pytest.raises(BackupError, match="loopback"):
        backup._ensure_local_empty_database(make_url("postgresql://user:secret@example.invalid/db"))


def test_storage_manifest_rejects_windows_and_parent_path_traversal() -> None:
    for key in ("users\\owner\\chart.png", "users/../outside.png", "C:/temp/chart.png"):
        with pytest.raises(BackupError, match="unsafe object key"):
            backup._safe_storage_key(key)


def test_backup_directory_acl_failure_stops_the_operation(monkeypatch) -> None:
    with _private_test_workspace() as temporary:
        destination = temporary / "restricted-output"
        monkeypatch.setattr(backup.os, "name", "nt")
        monkeypatch.setattr(
            backup.subprocess,
            "run",
            lambda *_args, **_kwargs: SimpleNamespace(returncode=5),
        )
        with pytest.raises(BackupError, match="Could not restrict access"):
            backup._protect_new_directory(destination)
