from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.storage import LocalFileStorage, get_storage_provider


def test_local_provider_settings_do_not_require_cloud_secrets(tmp_path: Path) -> None:
    settings = Settings(storage_path=tmp_path, data_provider="local", storage_provider="local")
    assert get_storage_provider(settings).exists("missing/object.png") is False


@pytest.mark.parametrize("field", ["data_provider", "storage_provider"])
def test_unknown_provider_is_rejected_clearly(field: str) -> None:
    values = {"data_provider": "local", "storage_provider": "local", field: "unknown"}
    with pytest.raises(ValidationError, match="Unsupported JOURNALME"):
        Settings(**values)


def test_local_storage_provider_contract(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    key = storage.put(uuid4(), "chart.png", b"journalme")
    assert storage.exists(key) is True
    assert storage.get(key) == b"journalme"
    storage.delete(key)
    assert storage.exists(key) is False
    with pytest.raises(ValueError, match="Invalid storage key"):
        storage.get("../../outside")
