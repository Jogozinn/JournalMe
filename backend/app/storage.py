from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx

if TYPE_CHECKING:
    from app.config import Settings


class StorageProvider(Protocol):
    """Opaque binary-object boundary; future providers must not expose machine paths."""

    def put(self, owner_id: UUID, filename: str, content: bytes) -> str: ...

    def get(self, storage_key: str) -> bytes: ...

    def delete(self, storage_key: str) -> None: ...

    def exists(self, storage_key: str) -> bool: ...

    def signed_read_url(self, storage_key: str, expires_in: int = 300) -> str | None: ...


class FileStorage(StorageProvider, Protocol):
    """Compatibility contract for current import services."""

    def save(self, session_id: UUID, filename: str, content: bytes) -> str: ...

    def read(self, storage_key: str) -> bytes: ...

    def delete(self, storage_key: str) -> None: ...


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, owner_id: UUID, filename: str, content: bytes) -> str:
        basename = Path(filename).name.replace("\x00", "")
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", basename).strip(". ")
        safe_name = safe_name or "report.csv"
        folder = self.root / str(owner_id)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / safe_name
        counter = 1
        while target.exists():
            target = folder / f"{target.stem}-{counter}{target.suffix}"
            counter += 1
        target.write_bytes(content)
        return str(target.relative_to(self.root))

    def save(self, session_id: UUID, filename: str, content: bytes) -> str:
        return self.put(session_id, filename, content)

    def get(self, storage_key: str) -> bytes:
        target = (self.root / storage_key).resolve()
        if self.root not in target.parents:
            raise ValueError("Invalid storage key")
        return target.read_bytes()

    def read(self, storage_key: str) -> bytes:
        return self.get(storage_key)

    def exists(self, storage_key: str) -> bool:
        try:
            target = (self.root / storage_key).resolve()
            return self.root in target.parents and target.exists()
        except (OSError, ValueError):
            return False

    def delete(self, storage_key: str) -> None:
        target = (self.root / storage_key).resolve()
        if self.root in target.parents and target.exists():
            target.unlink()

    def signed_read_url(self, storage_key: str, expires_in: int = 300) -> str | None:
        return None


class SupabaseStorageProvider:
    """Private Supabase Storage adapter; service-role credentials remain server-side."""

    def __init__(
        self,
        url: str,
        service_role_key: str,
        bucket: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = url.rstrip("/")
        self.bucket = bucket
        self.client = client or httpx.Client(timeout=20.0)
        self.headers = {"apikey": service_role_key}

        # Legacy service_role keys are JWTs and may be used as Bearer tokens.
        # New sb_secret_* keys are opaque API keys and must not be sent as Bearer JWTs.
        if not service_role_key.startswith("sb_secret_"):
            self.headers["Authorization"] = f"Bearer {service_role_key}"

    def put(self, owner_id: UUID, filename: str, content: bytes) -> str:
        safe_name = _safe_filename(filename)
        key = f"users/{owner_id}/objects/{uuid4()}-{safe_name}"
        self.put_at(key, content)
        return key

    def put_at(
        self,
        storage_key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Write a caller-selected opaque key for resumable migration tooling."""
        key = self._validated_key(storage_key)
        response = self.client.post(
            self._object_url(key),
            content=content,
            headers={
                **self.headers,
                "x-upsert": "false",
                "Content-Type": content_type,
            },
        )
        response.raise_for_status()

    # Import sessions predate the provider boundary and use these names.
    # Keep them as aliases so their opaque storage-key contract is provider-neutral.
    def save(self, session_id: UUID, filename: str, content: bytes) -> str:
        return self.put(session_id, filename, content)

    def get(self, storage_key: str) -> bytes:
        response = self.client.get(
            self._authenticated_object_url(storage_key),
            headers=self.headers,
        )
        response.raise_for_status()
        return response.content

    def read(self, storage_key: str) -> bytes:
        return self.get(storage_key)

    def delete(self, storage_key: str) -> None:
        response = self.client.request(
            "DELETE",
            f"{self.base_url}/storage/v1/object/{quote(self.bucket, safe='')}",
            json={"prefixes": [self._validated_key(storage_key)]},
            headers=self.headers,
        )
        response.raise_for_status()

    def exists(self, storage_key: str) -> bool:
        response = self.client.get(
            self._authenticated_object_url(storage_key),
            headers=self.headers,
        )

        if response.status_code == 200:
            return True

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if payload.get("code") == "NoSuchKey":
            return False

        response.raise_for_status()
        return False

    def signed_read_url(self, storage_key: str, expires_in: int = 300) -> str:
        if not 1 <= expires_in <= 3600:
            raise ValueError("Signed URL expiry must be between 1 and 3600 seconds.")
        object_url = self._object_url(self._validated_key(storage_key))
        signed_url = object_url.replace("/object/", "/object/sign/")
        response = self.client.post(
            signed_url,
            json={"expiresIn": expires_in},
            headers=self.headers,
        )
        response.raise_for_status()
        signed_url = response.json().get("signedURL")
        if not isinstance(signed_url, str):
            raise RuntimeError("Supabase did not return a signed object URL.")
        return (
            f"{self.base_url}/storage/v1{signed_url}"
            if signed_url.startswith("/")
            else signed_url
        )

    def _object_url(self, storage_key: str) -> str:
        bucket = quote(self.bucket, safe="")
        key = quote(self._validated_key(storage_key), safe="/")
        return f"{self.base_url}/storage/v1/object/{bucket}/{key}"

    def _authenticated_object_url(self, storage_key: str) -> str:
        bucket = quote(self.bucket, safe="")
        key = quote(self._validated_key(storage_key), safe="/")
        return f"{self.base_url}/storage/v1/object/authenticated/{bucket}/{key}"

    @staticmethod
    def _validated_key(storage_key: str) -> str:
        if not storage_key.startswith("users/") or ".." in storage_key.split("/"):
            raise ValueError("Invalid storage key")
        return storage_key


def _safe_filename(filename: str) -> str:
    basename = Path(filename).name.replace("\x00", "")
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", basename).strip(". ")
    return safe_name or "attachment.bin"


def get_storage_provider(settings: "Settings") -> StorageProvider:
    """Return the configured binary-storage provider; no cloud fallback is implicit."""
    if getattr(settings, "storage_provider", "local") == "local":
        return LocalFileStorage(settings.storage_path)
    if settings.storage_provider == "supabase":
        return SupabaseStorageProvider(
            settings.supabase_url or "",
            settings.supabase_service_role_key or "",
            settings.supabase_storage_bucket or "",
        )
    raise RuntimeError(f"Unsupported storage provider: {settings.storage_provider}")
