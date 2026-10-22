from __future__ import annotations

import pytest

from app import main, migrations
from app.config import Settings
from app.migrations import DatabaseRevisionError


def test_postgres_defaults_to_read_only_startup(monkeypatch) -> None:
    monkeypatch.delenv("JOURNALME_AUTO_MIGRATE", raising=False)
    monkeypatch.delenv("JOURNALME_BOOTSTRAP_LOCAL_DATA", raising=False)
    settings = Settings(database_url="postgresql+psycopg://local/trading")
    assert settings.auto_migrate is False
    assert settings.bootstrap_local_data is False


def test_sqlite_keeps_local_auto_migration_and_bootstrap_defaults(monkeypatch) -> None:
    monkeypatch.delenv("JOURNALME_AUTO_MIGRATE", raising=False)
    monkeypatch.delenv("JOURNALME_BOOTSTRAP_LOCAL_DATA", raising=False)
    settings = Settings(database_url="sqlite:///./journalme.db")
    assert settings.auto_migrate is True
    assert settings.bootstrap_local_data is True


def test_supabase_mode_rejects_auto_migration_and_local_bootstrap() -> None:
    required = {
        "data_provider": "supabase",
        "supabase_db_url": "postgresql+psycopg://local/trading",
        "supabase_url": "https://example.supabase.co",
        "supabase_anon_key": "local-test-only",
    }
    with pytest.raises(ValueError, match="Automatic migrations are disabled"):
        Settings(**required, auto_migrate=True)
    with pytest.raises(ValueError, match="bootstrap is disabled"):
        Settings(**required, auto_migrate=False, bootstrap_local_data=True)


def test_hosted_startup_checks_revision_without_migrating_or_seeding(monkeypatch) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://local/trading",
        auto_migrate=False,
        bootstrap_local_data=False,
    )
    calls: list[str] = []
    monkeypatch.setattr(main, "upgrade_database", lambda **_: calls.append("upgrade"))
    monkeypatch.setattr(main, "validate_database_revision", lambda _: calls.append("check"))
    monkeypatch.setattr(
        main, "SessionLocal", lambda: pytest.fail("hosted startup opened a write session")
    )

    main.prepare_database(settings)

    assert calls == ["check"]


def test_explicit_local_migration_and_bootstrap_can_be_enabled(monkeypatch) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://local/trading",
        auto_migrate=True,
        bootstrap_local_data=False,
    )
    calls: list[str] = []
    monkeypatch.setattr(main, "upgrade_database", lambda **_: calls.append("upgrade"))
    monkeypatch.setattr(main, "validate_database_revision", lambda _: calls.append("check"))

    main.prepare_database(settings)

    assert calls == ["upgrade"]


def test_unversioned_or_ahead_database_is_rejected_before_startup(monkeypatch) -> None:
    settings = Settings(database_url="sqlite:///./unused.db")
    monkeypatch.setattr(migrations, "read_database_revision", lambda _: None)
    with pytest.raises(DatabaseRevisionError, match="no Alembic revision"):
        migrations.validate_database_revision(settings)

    monkeypatch.setattr(migrations, "read_database_revision", lambda _: "0099")
    with pytest.raises(
        DatabaseRevisionError, match="not present in this release's migration graph"
    ):
        migrations.validate_database_revision(settings)


def test_pre_0016_database_is_reported_as_pending_without_upgrading(monkeypatch) -> None:
    settings = Settings(database_url="sqlite:///./unused.db")
    monkeypatch.setattr(migrations, "read_database_revision", lambda _: "0015")
    with pytest.raises(DatabaseRevisionError, match="does not match this release's head"):
        migrations.validate_database_revision(settings)
