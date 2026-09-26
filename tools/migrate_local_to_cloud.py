"""Safe, resumable local SQLite -> Supabase PostgreSQL migration rehearsal.

The default is an inspect-only dry run.  --apply is intentionally explicit and
requires both a reviewed local JournalMe user UUID and a Supabase Auth subject.
It never writes to the source SQLite database or deletes local object files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import MetaData, create_engine, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings
from app.database import Base
from app.models import AuthIdentity
from app.storage import LocalFileStorage, SupabaseStorageProvider


class MigrationBlocked(RuntimeError):
    """An unsafe or incomplete rehearsal request."""


def json_default(value: object) -> str:
    if isinstance(value, (UUID, Decimal, datetime)):
        return str(value)
    raise TypeError(f"Cannot JSON encode {type(value).__name__}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="Validate only (the default)."
    )
    mode.add_argument(
        "--apply", action="store_true", help="Copy after all preflight checks pass."
    )
    parser.add_argument("--local-database-url", default="sqlite:///./journalme.db")
    parser.add_argument("--local-storage-path", default="./storage")
    parser.add_argument(
        "--local-user-id", default=os.getenv("JOURNALME_MIGRATION_LOCAL_USER_ID")
    )
    parser.add_argument(
        "--supabase-auth-subject", default=os.getenv("SUPABASE_AUTH_USER_ID")
    )
    parser.add_argument(
        "--report", type=Path, default=Path("migration_validation.json")
    )
    return parser.parse_args()


def require_uuid(value: str | None, label: str) -> UUID:
    try:
        return UUID(value or "")
    except ValueError as exc:
        raise MigrationBlocked(
            f"{label} must be an explicit UUID; no ownership mapping was inferred."
        ) from exc


def table_counts(connection: Connection, tables: Iterable) -> dict[str, int]:
    return {
        table.name: int(connection.scalar(select(func.count()).select_from(table)) or 0)
        for table in tables
    }


def source_preflight(connection: Connection, local_user_id: UUID) -> None:
    users = Base.metadata.tables["users"]
    user_count = int(connection.scalar(select(func.count()).select_from(users)) or 0)
    if user_count != 1:
        raise MigrationBlocked(
            "This rehearsal only supports a single-user local source. Refuse to infer mappings for other users."
        )
    if connection.scalar(select(users.c.id).where(users.c.id == local_user_id)) is None:
        raise MigrationBlocked(
            "The explicit local user does not exist in the source database."
        )


def financial_totals(connection: Connection) -> dict[str, str]:
    trades = Base.metadata.tables["trades"]
    # Keep numeric arithmetic in the database and serialize Decimal exactly.
    totals: dict[str, str] = {}
    for column in ("net_pnl", "gross_pnl", "commission"):
        if column in trades.c:
            totals[f"trades.{column}"] = str(
                connection.scalar(select(func.coalesce(func.sum(trades.c[column]), 0)))
                or 0
            )
    return totals


def object_records(connection: Connection) -> list[tuple[str, UUID, str, str, str]]:
    """Return (table, id, local key, filename, mime) records that own bytes."""
    attachments = Base.metadata.tables["attachments"]
    captures = Base.metadata.tables["capture_events"]
    records = [
        ("attachments", row.id, row.storage_key, row.original_filename, row.mime_type)
        for row in connection.execute(select(attachments)).mappings()
    ]
    records.extend(
        (
            "capture_events",
            row.id,
            row.screenshot_storage_key,
            row.screenshot_original_filename,
            row.screenshot_mime,
        )
        for row in connection.execute(select(captures)).mappings()
    )
    import_files = Base.metadata.tables["import_files"]
    records.extend(
        ("import_files", row.id, row.stored_path, row.filename, "text/csv")
        for row in connection.execute(select(import_files)).mappings()
    )
    return records


def stable_object_key(user_id: UUID, table: str, record_id: UUID, filename: str) -> str:
    suffix = Path(filename).suffix.lower()[:16]
    return f"users/{user_id}/{table}/{record_id}/original{suffix or '.bin'}"


def copy_rows(
    source: Connection,
    target: Connection,
    table_name: str,
    replacements: dict[tuple[str, UUID], str],
) -> int:
    table = Base.metadata.tables[table_name]
    rows = []
    for row in source.execute(select(table)).mappings():
        values = dict(row)
        record_id = values.get("id")
        if isinstance(record_id, UUID):
            if table_name == "attachments" and (
                key := replacements.get((table_name, record_id))
            ):
                values["storage_key"] = key
            elif table_name == "capture_events" and (
                key := replacements.get((table_name, record_id))
            ):
                values["screenshot_storage_key"] = key
            elif table_name == "import_files" and (
                key := replacements.get((table_name, record_id))
            ):
                values["stored_path"] = key
        rows.append(values)
    if rows:
        statement = (
            insert(table).prefix_with("OR IGNORE")
            if target.dialect.name == "sqlite"
            else pg_insert(table).on_conflict_do_nothing()
        )
        target.execute(statement, rows)
    return len(rows)


def verify_or_upload(
    provider: SupabaseStorageProvider, key: str, content: bytes, mime: str
) -> None:
    if provider.exists(key):
        existing = provider.get(key)
        if hashlib.sha256(existing).digest() != hashlib.sha256(content).digest():
            raise MigrationBlocked(f"Cloud object collision has different bytes: {key}")
        return
    provider.put_at(key, content, mime or "application/octet-stream")
    if not provider.exists(key):
        raise MigrationBlocked(
            f"Cloud object could not be verified after upload: {key}"
        )


def run() -> int:
    args = parse_args()
    apply = bool(args.apply)
    report: dict[str, object] = {
        "mode": "apply" if apply else "dry-run",
        "started_at": datetime.now(UTC).isoformat(),
        "ok": False,
    }
    try:
        local_user_id = require_uuid(args.local_user_id, "--local-user-id")
        subject = require_uuid(args.supabase_auth_subject, "--supabase-auth-subject")
        source_engine = create_engine(args.local_database_url)
        with source_engine.connect() as source:
            source_preflight(source, local_user_id)
            tables = list(Base.metadata.sorted_tables)
            report["source_counts"] = table_counts(source, tables)
            report["source_financial_totals"] = financial_totals(source)
            assets = object_records(source)
            local_storage = LocalFileStorage(Path(args.local_storage_path))
            missing = [
                key for _, _, key, _, _ in assets if not local_storage.exists(key)
            ]
            report["assets"] = {"total": len(assets), "missing": missing}
            if missing:
                raise MigrationBlocked(
                    "Source objects are missing; apply is blocked so no cloud copy is partial."
                )
            if not apply:
                report["ok"] = True
                return 0

            settings = Settings(data_provider="supabase", storage_provider="supabase")
            target_engine = create_engine(settings.database_url, pool_pre_ping=True)
            with target_engine.begin() as target:
                # Alembic must have installed the current schema before any copy.
                target_metadata = MetaData()
                target_metadata.reflect(bind=target)
                target_tables = set(target_metadata.tables)
                absent = [
                    table.name for table in tables if table.name not in target_tables
                ]
                if absent:
                    raise MigrationBlocked(
                        "Target schema is not at JournalMe head; missing: "
                        + ", ".join(absent)
                    )
                replacements: dict[tuple[str, UUID], str] = {}
                provider = SupabaseStorageProvider(
                    settings.supabase_url or "",
                    settings.supabase_service_role_key or "",
                    settings.supabase_storage_bucket or "",
                )
                for table, record_id, source_key, filename, mime in assets:
                    key = stable_object_key(local_user_id, table, record_id, filename)
                    verify_or_upload(provider, key, local_storage.get(source_key), mime)
                    replacements[(table, record_id)] = key
                for table in tables:
                    copy_rows(source, target, table.name, replacements)
                target.execute(
                    pg_insert(AuthIdentity.__table__).on_conflict_do_nothing(),
                    [
                        {
                            "id": uuid4(),
                            "user_id": local_user_id,
                            "provider": "supabase",
                            "subject": str(subject),
                            "created_at": datetime.now(UTC),
                        }
                    ],
                )
                report["target_counts"] = table_counts(target, tables)
                report["target_financial_totals"] = financial_totals(target)
                report["identity_mapping"] = {
                    "local_user_id": str(local_user_id),
                    "supabase_subject": str(subject),
                }

                # auth_identities intentionally gains the Supabase identity mapping,
                # so it is not expected to have the same count as the local source.
                source_counts_for_validation = dict(report["source_counts"])
                target_counts_for_validation = dict(report["target_counts"])

                source_counts_for_validation.pop("auth_identities", None)
                target_counts_for_validation.pop("auth_identities", None)

                identity = target.execute(
                    select(AuthIdentity.id).where(
                        AuthIdentity.provider == "supabase",
                        AuthIdentity.subject == str(subject),
                        AuthIdentity.user_id == local_user_id,
                    )
                ).scalar_one_or_none()

                if identity is None:
                    raise MigrationBlocked(
                        "Supabase auth identity mapping was not created."
                    )

                if (
                    source_counts_for_validation != target_counts_for_validation
                    or report["source_financial_totals"]
                    != report["target_financial_totals"]
                ):
                    raise MigrationBlocked(
                        "Target validation differs from source; transaction has been rolled back."
                    )
            report["ok"] = True
            return 0
    except Exception as exc:  # noqa: BLE001 - a rehearsal must always leave a report.
        report["error"] = str(exc)
        return 2
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, default=json_default), encoding="utf-8"
        )
        args.report.with_suffix(".md").write_text(
            "# JournalMe cloud migration rehearsal\n\n"
            f"- Mode: {report['mode']}\n- Result: {'passed' if report['ok'] else 'blocked'}\n"
            f"- Source assets: {report.get('assets', {})}\n"
            f"- Error: {report.get('error', 'none')}\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    raise SystemExit(run())
