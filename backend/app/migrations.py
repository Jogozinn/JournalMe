"""Explicit Alembic operations and read-only schema compatibility checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.config import Settings, get_settings


class DatabaseRevisionError(RuntimeError):
    """The database schema cannot be safely used by this application revision."""


def _alembic_config(settings: Settings) -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    # Alembic's ConfigParser treats percent signs as interpolation markers.
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    return config


def known_heads(settings: Settings | None = None) -> tuple[str, ...]:
    config = _alembic_config(settings or get_settings())
    return tuple(sorted(ScriptDirectory.from_config(config).get_heads()))


def read_database_revision(settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if not inspect(connection).has_table("alembic_version"):
                return None
            rows = connection.execute(text("SELECT version_num FROM alembic_version"))
            revisions = sorted(row[0] for row in rows)
            if len(revisions) > 1:
                raise DatabaseRevisionError(
                    "The database has multiple Alembic revisions; resolve the migration branches before startup."
                )
            return revisions[0] if revisions else None
    finally:
        engine.dispose()


def validate_database_revision(settings: Settings | None = None) -> str:
    """Read-only check that the DB is at a supported application head."""
    settings = settings or get_settings()
    config = _alembic_config(settings)
    scripts = ScriptDirectory.from_config(config)
    revision = read_database_revision(settings)
    if revision is None:
        raise DatabaseRevisionError(
            "The database has no Alembic revision. Run `python -m app.migrations upgrade` explicitly before starting this backend."
        )
    try:
        scripts.get_revision(revision)
    except Exception as exc:
        heads = ", ".join(scripts.get_heads()) or "none"
        raise DatabaseRevisionError(
            f"Database revision {revision!r} is not present in this release's migration graph (supported head: {heads}). "
            "Use a release that includes the database revision; no migration was run."
        ) from exc

    heads = set(scripts.get_heads())
    if revision not in heads:
        heads_text = ", ".join(sorted(heads)) or "none"
        raise DatabaseRevisionError(
            f"Database revision {revision!r} does not match this release's head ({heads_text}). "
            "Run the explicit migration command or deploy a compatible application release."
        )
    return revision


def upgrade_database(target: str = "head", settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    current = read_database_revision(settings)
    if current is not None:
        scripts = ScriptDirectory.from_config(_alembic_config(settings))
        try:
            scripts.get_revision(current)
        except Exception as exc:
            raise DatabaseRevisionError(
                f"Database revision {current!r} is not present in this release's migration graph; no migration was run."
            ) from exc
    config = _alembic_config(settings)
    command.upgrade(config, target)


def _cli() -> int:
    parser = argparse.ArgumentParser(description="JournalMe's explicit Alembic migration gate.")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("revision", help="Read the installed and supported revisions.")
    subparsers.add_parser("check", help="Require the database to match this release's head.")
    subparsers.add_parser("upgrade", help="Apply all pending migrations to this release's head.")
    args = parser.parse_args()
    settings = get_settings()

    if args.operation == "revision":
        print(
            json.dumps(
                {
                    "database_revision": read_database_revision(settings),
                    "supported_heads": known_heads(settings),
                }
            )
        )
    elif args.operation == "check":
        revision = validate_database_revision(settings)
        print(json.dumps({"database_revision": revision, "status": "compatible"}))
    else:
        upgrade_database("head", settings)
        revision = validate_database_revision(settings)
        print(json.dumps({"database_revision": revision, "status": "migrated"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
