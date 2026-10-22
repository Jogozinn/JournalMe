"""Local-only Supabase/PostgreSQL and private Storage backup utilities.

Credentials are read from environment variables and passed to child processes
through their environment, never command-line arguments or generated reports.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import create_engine, inspect, make_url, text
from sqlalchemy.engine import URL, Connection

from app.config import get_settings


class BackupError(RuntimeError):
    """A backup action failed without exposing connection credentials."""


def _json_write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _protect_new_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=False)
    if os.name == "nt":
        username = os.environ.get("USERNAME", "")
        domain = os.environ.get("USERDOMAIN", "")
        user = f"{domain}\\{username}" if domain else username
        if user:
            result = subprocess.run(
                [
                    "icacls.exe",
                    str(path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{user}:(OI)(CI)F",
                    "SYSTEM:(OI)(CI)F",
                    "Administrators:(OI)(CI)F",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if result.returncode:
                raise BackupError("Could not restrict access to the backup directory.")
    else:
        path.chmod(0o700)


def _pg_env(url: URL) -> dict[str, str]:
    if url.get_backend_name() != "postgresql":
        raise BackupError("This operation requires a PostgreSQL database URL.")
    if not url.host or not url.database:
        raise BackupError("The PostgreSQL URL must include a host and database name.")
    env = os.environ.copy()
    env["PGHOST"] = url.host
    env["PGPORT"] = str(url.port or 5432)
    env["PGDATABASE"] = url.database
    if url.username:
        env["PGUSER"] = url.username
    if url.password is not None:
        env["PGPASSWORD"] = url.password
    query = dict(url.query)
    env["PGSSLMODE"] = str(
        query.get("sslmode")
        or ("disable" if url.host in {"localhost", "127.0.0.1", "::1"} else "require")
    )
    return env


def _database_url() -> URL:
    settings = get_settings()
    raw = (
        settings.supabase_db_url if settings.data_provider == "supabase" else settings.database_url
    )
    if not raw:
        raise BackupError("No database URL is configured.")
    try:
        return make_url(raw)
    except Exception as exc:
        raise BackupError("The configured database URL is invalid.") from exc


def _pg_tool(name: str) -> str:
    found = shutil.which(name) or shutil.which(f"{name}.exe")
    if found:
        return found
    postgres_bin = Path(r"C:\Program Files\PostgreSQL\17\bin") / f"{name}.exe"
    if postgres_bin.is_file():
        return str(postgres_bin)
    raise BackupError(f"Required PostgreSQL client {name} was not found on PATH.")


def _run_silent(argv: list[str], env: dict[str, str], operation: str) -> str:
    result = subprocess.run(argv, env=env, capture_output=True, text=True, check=False)
    if result.returncode:
        # Driver errors may echo database or role names. Keep tool output generic.
        raise BackupError(
            f"{operation} failed with exit code {result.returncode}; details were suppressed to protect credentials."
        )
    return result.stdout


def _table_names(connection: Connection) -> list[tuple[str, str]]:
    rows = connection.execute(
        text(
            "SELECT schemaname, tablename FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
            "AND schemaname NOT LIKE 'pg_toast%' ORDER BY schemaname, tablename"
        )
    )
    return [(str(row[0]), str(row[1])) for row in rows]


def _identity_checksums(connection: Connection, tables: list[tuple[str, str]]) -> dict[str, str]:
    inspector = inspect(connection)
    checksums: dict[str, str] = {}
    for schema, table in tables:
        primary_key = (
            inspector.get_pk_constraint(table, schema=schema).get("constrained_columns") or []
        )
        if not primary_key:
            continue
        qualified = (
            f'"{schema.replace(chr(34), chr(34) * 2)}"."{table.replace(chr(34), chr(34) * 2)}"'
        )
        columns = [f'"{column.replace(chr(34), chr(34) * 2)}"' for column in primary_key]
        order = ", ".join(columns)
        digest = hashlib.sha256()
        result = connection.execution_options(stream_results=True).execute(
            text(f"SELECT {order} FROM {qualified} ORDER BY {order}")
        )
        for row in result:
            digest.update(
                "\x1f".join("<null>" if value is None else str(value) for value in row).encode()
            )
            digest.update(b"\n")
        checksums[f"{schema}.{table}"] = digest.hexdigest()
    return checksums


def _database_audit(
    connection: Connection, *, include_storage_references: bool = False
) -> dict[str, Any]:
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        revision = None
    else:
        versions = sorted(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
        revision = versions[0] if len(versions) == 1 else versions

    counts: dict[str, int] = {}
    for schema, table in _table_names(connection):
        qualified = (
            f'"{schema.replace(chr(34), chr(34) * 2)}"."{table.replace(chr(34), chr(34) * 2)}"'
        )
        counts[f"{schema}.{table}"] = int(
            connection.execute(text(f"SELECT count(*) FROM {qualified}")).scalar_one()
        )

    schemas = sorted(
        connection.execute(
            text(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema' "
                "ORDER BY nspname"
            )
        ).scalars()
    )
    policies = int(
        connection.execute(
            text(
                "SELECT count(*) FROM pg_policies WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
            )
        ).scalar_one()
    )
    extensions = sorted(
        connection.execute(text("SELECT extname FROM pg_extension ORDER BY extname")).scalars()
    )

    identity_checks: dict[str, int] = {}
    checks = {
        "trade_account_orphans": "SELECT count(*) FROM public.trades t LEFT JOIN public.trading_accounts a ON a.id=t.account_id WHERE a.id IS NULL",
        "execution_account_orphans": "SELECT count(*) FROM public.broker_execution_events e LEFT JOIN public.trading_accounts a ON a.id=e.account_id WHERE e.account_id IS NOT NULL AND a.id IS NULL",
        "execution_connection_orphans": "SELECT count(*) FROM public.broker_execution_events e LEFT JOIN public.broker_connections c ON c.id=e.connection_id WHERE c.id IS NULL",
        "connection_account_user_mismatches": "SELECT count(*) FROM public.broker_connections c JOIN public.trading_accounts a ON a.id=c.account_id WHERE c.user_id <> a.user_id",
    }
    existing = set(_table_names(connection))
    for name, sql in checks.items():
        required = {
            "trade_account_orphans": {("public", "trades"), ("public", "trading_accounts")},
            "execution_account_orphans": {
                ("public", "broker_execution_events"),
                ("public", "trading_accounts"),
            },
            "execution_connection_orphans": {
                ("public", "broker_execution_events"),
                ("public", "broker_connections"),
            },
            "connection_account_user_mismatches": {
                ("public", "broker_connections"),
                ("public", "trading_accounts"),
            },
        }[name]
        if required.issubset(existing):
            identity_checks[name] = int(connection.execute(text(sql)).scalar_one())

    if {("public", "broker_execution_events"), ("public", "trading_accounts")} <= existing:
        identity_checks["execution_account_user_mismatches"] = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM public.broker_execution_events e JOIN public.trading_accounts a ON a.id=e.account_id WHERE e.user_id <> a.user_id"
                )
            ).scalar_one()
        )
    if {("public", "broker_execution_events"), ("public", "broker_connections")} <= existing:
        identity_checks["execution_connection_user_mismatches"] = int(
            connection.execute(
                text(
                    "SELECT count(*) FROM public.broker_execution_events e JOIN public.broker_connections c ON c.id=e.connection_id WHERE e.user_id <> c.user_id"
                )
            ).scalar_one()
        )
    if ("public", "broker_connections") in existing:
        connection_columns = {
            item["name"] for item in inspector.get_columns("broker_connections", schema="public")
        }
        if "installation_id" in connection_columns:
            identity_checks["bridge_installation_orphans"] = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM public.broker_connections child LEFT JOIN public.broker_connections parent ON parent.id=child.installation_id WHERE child.installation_id IS NOT NULL AND parent.id IS NULL"
                    )
                ).scalar_one()
            )
            identity_checks["bridge_child_user_mismatches"] = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM public.broker_connections child JOIN public.broker_connections parent ON parent.id=child.installation_id WHERE child.user_id <> parent.user_id"
                    )
                ).scalar_one()
            )
            if {"source_namespace", "source_account_name"} <= connection_columns:
                identity_checks["duplicate_bridge_source_mappings"] = int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM (SELECT installation_id, source_namespace, source_account_name FROM public.broker_connections WHERE installation_id IS NOT NULL GROUP BY installation_id, source_namespace, source_account_name HAVING count(*) > 1) duplicates"
                        )
                    ).scalar_one()
                )

    storage_reference_counts: dict[str, int] = {}
    storage_references: dict[str, list[str]] = {}
    reference_columns = {
        ("public", "attachments"): "storage_key",
        ("public", "capture_events"): "screenshot_storage_key",
        ("public", "import_files"): "stored_path",
    }
    for (schema, table), column in reference_columns.items():
        if (schema, table) not in existing:
            continue
        columns = {item["name"] for item in inspector.get_columns(table, schema=schema)}
        if column not in columns:
            continue
        qualified = f'"{schema}"."{table}"'
        column_sql = f'"{column}"'
        query = f"SELECT {column_sql} FROM {qualified} WHERE {column_sql} IS NOT NULL"
        name = f"{schema}.{table}.{column}"
        if include_storage_references:
            storage_references[name] = [
                str(value) for value in connection.execute(text(query)).scalars()
            ]
            storage_reference_counts[name] = len(storage_references[name])
        else:
            storage_reference_counts[name] = int(
                connection.execute(
                    text(f"SELECT count(*) FROM {qualified} WHERE {column_sql} IS NOT NULL")
                ).scalar_one()
            )

    roles = [
        {"name": str(row[0]), "can_login": bool(row[1]), "is_superuser": bool(row[2])}
        for row in connection.execute(
            text(
                "SELECT rolname, rolcanlogin, rolsuper FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY rolname"
            )
        )
    ]
    table_names = _table_names(connection)
    return {
        "database_revision": revision,
        "schemas_with_tables": schemas,
        "table_counts": counts,
        "primary_key_checksums": _identity_checksums(connection, table_names),
        "policy_count": policies,
        "extensions": extensions,
        "roles_without_passwords": roles,
        "identity_checks": identity_checks,
        "storage_reference_counts": storage_reference_counts,
        **({"storage_references": storage_references} if include_storage_references else {}),
    }


def inspect_database() -> dict[str, Any]:
    url = _database_url()
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execution_options(isolation_level="REPEATABLE READ")
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                return _database_audit(connection)
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(
            "Read-only database inspection failed; connection details were suppressed."
        ) from exc
    finally:
        engine.dispose()


def _archive_toc(path: Path) -> str:
    output = _run_silent(
        [_pg_tool("pg_restore"), "--list", str(path)],
        os.environ.copy(),
        "Backup archive verification",
    )
    if not output.strip() or "TABLE DATA" not in output:
        raise BackupError("The archive has no restorable table data entries.")
    return output


def backup_database(directory: Path) -> dict[str, Any]:
    _protect_new_directory(directory)
    dump_path = directory / "database.dump"
    roles_path = directory / "roles.sql"
    report_path = directory / "database-report.json"
    url = _database_url()
    env = _pg_env(url)
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                snapshot = str(connection.execute(text("SELECT pg_export_snapshot()")).scalar_one())
                _run_silent(
                    [
                        _pg_tool("pg_dump"),
                        "--format=custom",
                        f"--snapshot={snapshot}",
                        f"--file={dump_path}",
                    ],
                    env,
                    "PostgreSQL backup",
                )
                _run_silent(
                    [
                        _pg_tool("pg_dumpall"),
                        "--roles-only",
                        "--no-role-passwords",
                        f"--file={roles_path}",
                    ],
                    env,
                    "PostgreSQL role backup",
                )
                audit = _database_audit(connection)
        toc = _archive_toc(dump_path)
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("PostgreSQL backup failed; connection details were suppressed.") from exc
    finally:
        engine.dispose()

    audit["backup"] = {
        "format": "pg_dump custom archive",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "file": dump_path.name,
        "bytes": dump_path.stat().st_size,
        "sha256": _file_hash(dump_path),
        "archive_entries": sum(1 for line in toc.splitlines() if re.match(r"^\d+;", line)),
        "contains_auth_schema": bool(re.search(r"\bSCHEMA\s+-\s+auth\b", toc)),
        "contains_storage_schema": bool(re.search(r"\bSCHEMA\s+-\s+storage\b", toc)),
        "role_file": roles_path.name,
        "role_file_bytes": roles_path.stat().st_size,
        "role_file_sha256": _file_hash(roles_path),
        "role_file_omits_passwords": True,
    }
    role_sql = roles_path.read_text(encoding="utf-8", errors="replace")
    if re.search(r"\bPASSWORD\s+(?:'[^']*'|\"[^\"]*\"|NULL)", role_sql, re.IGNORECASE):
        raise BackupError("The password-free role export unexpectedly contains a password clause.")
    if not audit["backup"]["bytes"]:
        raise BackupError("The database backup is empty.")
    _json_write(report_path, audit)
    return {"directory": str(directory), "report": audit}


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_storage_key(key: str) -> PurePosixPath:
    path = PurePosixPath(key)
    if (
        not key.startswith("users/")
        or path.is_absolute()
        or "\\" in key
        or ":" in key
        or "\x00" in key
        or any(part in {"", ".", ".."} or part.endswith((".", " ")) for part in path.parts)
    ):
        raise BackupError("Storage returned an unsafe object key.")
    return path


def verify_database_backup(dump_path: Path, report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    backup = report.get("backup", {})
    actual = {"bytes": dump_path.stat().st_size, "sha256": _file_hash(dump_path)}
    if actual["bytes"] != backup.get("bytes") or actual["sha256"] != backup.get("sha256"):
        raise BackupError("The database archive does not match its integrity report.")
    roles_path = dump_path.parent / backup.get("role_file", "roles.sql")
    if (
        not roles_path.is_file()
        or roles_path.stat().st_size != backup.get("role_file_bytes")
        or _file_hash(roles_path) != backup.get("role_file_sha256")
    ):
        raise BackupError("The password-free role archive does not match its integrity report.")
    toc = _archive_toc(dump_path)
    schemas = set(report.get("schemas_with_tables", []))
    for schema in ("auth", "storage"):
        if schema in schemas and not re.search(rf"\bSCHEMA\s+-\s+{schema}\b", toc):
            raise BackupError(f"The archive is missing the expected {schema} schema.")
    return {"status": "verified", **actual, "archive_entries": backup.get("archive_entries")}


def _ensure_local_empty_database(url: URL) -> None:
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise BackupError(
            "Restore target must be a loopback PostgreSQL database; remote restore is disabled."
        )
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            tables = _table_names(connection)
            if tables:
                raise BackupError("Restore target is not empty; no objects were changed.")
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("Could not verify that the local restore target is empty.") from exc
    finally:
        engine.dispose()


def restore_database(dump_path: Path, report_path: Path, target_url: str) -> dict[str, Any]:
    verify_database_backup(dump_path, report_path)
    try:
        url = make_url(target_url)
    except Exception as exc:
        raise BackupError("The restore target URL is invalid.") from exc
    _ensure_local_empty_database(url)
    _run_silent(
        [
            _pg_tool("pg_restore"),
            "--exit-on-error",
            "--single-transaction",
            "--dbname",
            str(url.database),
            str(dump_path),
        ],
        _pg_env(url),
        "Isolated database restore",
    )
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            restored = _database_audit(connection)
    except Exception as exc:
        raise BackupError(
            "Restored database validation failed; connection details were suppressed."
        ) from exc
    finally:
        engine.dispose()
    source = json.loads(report_path.read_text(encoding="utf-8"))
    for key in (
        "database_revision",
        "schemas_with_tables",
        "table_counts",
        "primary_key_checksums",
        "policy_count",
        "extensions",
        "identity_checks",
        "storage_reference_counts",
    ):
        if restored.get(key) != source.get(key):
            raise BackupError(
                f"Restored database validation mismatch in {key}; review the isolated restore before rollout."
            )
    return {
        "status": "restored-and-verified",
        "database_revision": restored["database_revision"],
        "table_count": len(restored["table_counts"]),
        "policy_count": restored["policy_count"],
        "identity_checks": restored["identity_checks"],
    }


def _storage_client(
    settings, client: httpx.Client | None = None
) -> tuple[httpx.Client, dict[str, str], str]:
    if (
        not settings.supabase_url
        or not settings.supabase_service_role_key
        or not settings.supabase_storage_bucket
    ):
        raise BackupError(
            "Supabase URL, service-role key, and private bucket must be configured in the local environment."
        )
    http = client or httpx.Client(timeout=60.0)
    key = settings.supabase_service_role_key
    headers = {"apikey": key}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {key}"
    return http, headers, settings.supabase_url.rstrip("/")


def _list_storage_objects(
    client: httpx.Client, headers: dict[str, str], base_url: str, bucket: str
) -> dict[str, dict[str, Any]]:
    endpoint = f"{base_url}/storage/v1/object/list/{quote(bucket, safe='')}"
    pending = [""]
    seen_prefixes: set[str] = set()
    files: dict[str, dict[str, Any]] = {}
    while pending:
        prefix = pending.pop()
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        offset = 0
        while True:
            try:
                response = client.post(
                    endpoint,
                    json={"prefix": prefix, "limit": 1000, "offset": offset},
                    headers=headers,
                )
                response.raise_for_status()
                rows = response.json()
            except Exception as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
                raise BackupError(
                    f"Storage inventory failed with HTTP status {status_code}; response details were suppressed."
                ) from exc
            if not isinstance(rows, list):
                raise BackupError("Storage inventory returned an unexpected response shape.")
            for row in rows:
                name = row.get("name") if isinstance(row, dict) else None
                if (
                    not isinstance(name, str)
                    or not name
                    or name in {".", ".."}
                    or "/" in name
                    or "\\" in name
                    or ":" in name
                    or "\x00" in name
                ):
                    raise BackupError("Storage inventory returned an invalid object name.")
                key = f"{prefix}/{name}" if prefix else name
                if row.get("metadata") is None and row.get("id") is None:
                    pending.append(key)
                else:
                    metadata = row.get("metadata")
                    files[key] = metadata if isinstance(metadata, dict) else {}
            if len(rows) < 1000:
                break
            offset += 1000
    return dict(sorted(files.items()))


def export_storage(directory: Path, client: httpx.Client | None = None) -> dict[str, Any]:
    _protect_new_directory(directory)
    settings = get_settings()
    http, headers, base_url = _storage_client(settings, client)
    bucket = settings.supabase_storage_bucket or ""
    try:
        try:
            bucket_response = http.get(
                f"{base_url}/storage/v1/bucket/{quote(bucket, safe='')}", headers=headers
            )
            bucket_response.raise_for_status()
            bucket_metadata = bucket_response.json()
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
            raise BackupError(
                f"Private bucket verification failed with HTTP status {status_code}; response details were suppressed."
            ) from exc
        if bucket_metadata.get("public") is not False:
            raise BackupError(
                "The configured bucket is public or its privacy status could not be verified."
            )
        objects = _list_storage_objects(http, headers, base_url, bucket)
        root = directory / "objects"
        root.mkdir()
        manifest_objects: list[dict[str, Any]] = []
        for key, object_metadata in objects.items():
            posix = _safe_storage_key(key)
            try:
                response = http.get(
                    f"{base_url}/storage/v1/object/authenticated/{quote(bucket, safe='')}/{quote(key, safe='/')}",
                    headers=headers,
                )
                response.raise_for_status()
                content = response.content
            except Exception as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
                raise BackupError(
                    f"Storage object export failed with HTTP status {status_code}; response details were suppressed."
                ) from exc
            target = root.joinpath(*posix.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            try:
                target.chmod(0o600)
            except OSError:
                pass
            manifest_objects.append(
                {
                    "key": key,
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "content_type": object_metadata.get("mimetype") or "application/octet-stream",
                    "cache_control": object_metadata.get("cacheControl"),
                }
            )
    finally:
        if client is None:
            http.close()
    manifest = {
        "bucket": bucket,
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "object_count": len(manifest_objects),
        "total_bytes": sum(item["bytes"] for item in manifest_objects),
        "objects": manifest_objects,
    }
    _json_write(directory / "storage-manifest.json", manifest)
    return {
        "object_count": manifest["object_count"],
        "total_bytes": manifest["total_bytes"],
        "manifest": str(directory / "storage-manifest.json"),
    }


def verify_storage_export(directory: Path) -> dict[str, Any]:
    manifest_path = directory / "storage-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checked = 0
    total_bytes = 0
    objects_root = (directory / "objects").resolve()
    for item in manifest.get("objects", []):
        posix = _safe_storage_key(item["key"])
        path = directory / "objects" / Path(*posix.parts)
        if path.is_symlink() or objects_root not in path.resolve().parents:
            raise BackupError(
                "Storage export contains a symlink or path outside the object directory."
            )
        if (
            not path.is_file()
            or path.stat().st_size != item["bytes"]
            or _file_hash(path) != item["sha256"]
        ):
            raise BackupError(
                "Storage export verification failed; a file is missing or its checksum differs."
            )
        checked += 1
        total_bytes += item["bytes"]
    if checked != manifest.get("object_count") or total_bytes != manifest.get("total_bytes"):
        raise BackupError("Storage export verification failed; manifest totals do not match.")
    expected_paths = {
        (directory / "objects" / Path(*_safe_storage_key(item["key"]).parts)).resolve()
        for item in manifest.get("objects", [])
    }
    actual_paths = {path.resolve() for path in (directory / "objects").rglob("*") if path.is_file()}
    if (
        any(path.is_symlink() for path in (directory / "objects").rglob("*"))
        or expected_paths != actual_paths
    ):
        raise BackupError(
            "Storage export verification failed; unlisted or missing files exist in the export."
        )
    return {"status": "verified", "object_count": checked, "total_bytes": total_bytes}


def restore_storage(directory: Path, client: httpx.Client | None = None) -> dict[str, Any]:
    """Restore into a local private Supabase bucket without overwriting objects."""
    verify_storage_export(directory)
    settings = get_settings()
    http, headers, base_url = _storage_client(settings, client)
    if httpx.URL(base_url).host not in {"localhost", "127.0.0.1", "::1"}:
        if client is None:
            http.close()
        raise BackupError("Storage restore is restricted to a loopback Supabase instance.")
    bucket = settings.supabase_storage_bucket or ""
    try:
        try:
            response = http.get(
                f"{base_url}/storage/v1/bucket/{quote(bucket, safe='')}", headers=headers
            )
            response.raise_for_status()
            if response.json().get("public") is not False:
                raise BackupError("Storage restore requires a verified private target bucket.")
        except BackupError:
            raise
        except Exception as exc:
            raise BackupError(
                "Target private bucket verification failed; response details were suppressed."
            ) from exc

        manifest = json.loads((directory / "storage-manifest.json").read_text(encoding="utf-8"))
        restored = 0
        for item in manifest["objects"]:
            key = item["key"]
            source = directory / "objects" / Path(*_safe_storage_key(key).parts)
            content = source.read_bytes()
            object_url = (
                f"{base_url}/storage/v1/object/{quote(bucket, safe='')}/{quote(key, safe='/')}"
            )
            try:
                response = http.post(
                    object_url,
                    content=content,
                    headers={
                        **headers,
                        "x-upsert": "false",
                        "Content-Type": item.get("content_type") or "application/octet-stream",
                        **(
                            {"cacheControl": str(item["cache_control"])}
                            if item.get("cache_control") is not None
                            else {}
                        ),
                    },
                )
                if response.status_code not in {200, 201}:
                    if response.status_code not in {400, 409}:
                        response.raise_for_status()
                    existing = http.get(
                        f"{base_url}/storage/v1/object/authenticated/{quote(bucket, safe='')}/{quote(key, safe='/')}",
                        headers=headers,
                    )
                    existing.raise_for_status()
                    if hashlib.sha256(existing.content).hexdigest() != item["sha256"]:
                        raise BackupError(
                            "A target object exists with different bytes; no overwrite was attempted."
                        )
                check = http.get(
                    f"{base_url}/storage/v1/object/authenticated/{quote(bucket, safe='')}/{quote(key, safe='/')}",
                    headers=headers,
                )
                check.raise_for_status()
            except BackupError:
                raise
            except Exception as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", "unknown")
                raise BackupError(
                    f"Private object restore failed with HTTP status {status_code}; response details were suppressed."
                ) from exc
            if (
                len(check.content) != item["bytes"]
                or hashlib.sha256(check.content).hexdigest() != item["sha256"]
            ):
                raise BackupError(
                    "Restored object verification failed; downloaded bytes differ from the manifest."
                )
            restored += 1
    finally:
        if client is None:
            http.close()
    return {
        "status": "restored-and-verified",
        "object_count": restored,
        "total_bytes": sum(item["bytes"] for item in manifest["objects"]),
    }


def reconcile_storage(directory: Path, database_url: str | None = None) -> dict[str, Any]:
    verify_storage_export(directory)
    url = make_url(database_url) if database_url else _database_url()
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            audit = _database_audit(connection, include_storage_references=True)
    except Exception as exc:
        raise BackupError(
            "Storage reconciliation failed; database details were suppressed."
        ) from exc
    finally:
        engine.dispose()
    manifest = json.loads((directory / "storage-manifest.json").read_text(encoding="utf-8"))
    objects = {item["key"] for item in manifest["objects"]}
    missing_by_reference: dict[str, int] = {}
    for source, keys in audit["storage_references"].items():
        missing_by_reference[source] = sum(key not in objects for key in keys)
    return {
        "database_revision": audit["database_revision"],
        "object_count": len(objects),
        "reference_counts": audit["storage_reference_counts"],
        "missing_objects_by_reference": missing_by_reference,
        "status": "verified" if not any(missing_by_reference.values()) else "missing-references",
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="JournalMe local PostgreSQL and private Storage recovery tools."
    )
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser(
        "inspect-db", help="Read database revision, counts, schemas, policies, and identities."
    )
    db_backup = sub.add_parser(
        "backup-db", help="Create a restricted, checksummed custom PostgreSQL archive."
    )
    db_backup.add_argument("--output-dir", type=Path, required=True)
    verify = sub.add_parser("verify-db", help="Verify archive checksum and restore catalog.")
    verify.add_argument("--dump", type=Path, required=True)
    verify.add_argument("--report", type=Path, required=True)
    restore = sub.add_parser(
        "restore-db", help="Restore and compare into an empty loopback-only database."
    )
    restore.add_argument("--dump", type=Path, required=True)
    restore.add_argument("--report", type=Path, required=True)
    storage = sub.add_parser(
        "export-storage", help="Inventory and export private bucket bytes with SHA-256 manifest."
    )
    storage.add_argument("--output-dir", type=Path, required=True)
    verify_storage = sub.add_parser(
        "verify-storage", help="Verify every exported object against its manifest."
    )
    verify_storage.add_argument("--directory", type=Path, required=True)
    storage_restore = sub.add_parser(
        "restore-storage",
        help="Create-only restore and checksum verification into loopback Supabase Storage.",
    )
    storage_restore.add_argument("--directory", type=Path, required=True)
    reconcile = sub.add_parser(
        "reconcile-storage", help="Compare database object references with an export manifest."
    )
    reconcile.add_argument("--directory", type=Path, required=True)
    reconcile.add_argument(
        "--restored-database",
        action="store_true",
        help="Use JOURNALME_RESTORE_DATABASE_URL to reconcile against the isolated restored database.",
    )
    args = parser.parse_args()

    if args.operation == "inspect-db":
        result = inspect_database()
    elif args.operation == "backup-db":
        result = backup_database(args.output_dir)
    elif args.operation == "verify-db":
        result = verify_database_backup(args.dump, args.report)
    elif args.operation == "restore-db":
        target_url = os.getenv("JOURNALME_RESTORE_DATABASE_URL")
        if not target_url:
            raise BackupError(
                "Set JOURNALME_RESTORE_DATABASE_URL to a disposable loopback PostgreSQL database."
            )
        result = restore_database(args.dump, args.report, target_url)
    elif args.operation == "export-storage":
        result = export_storage(args.output_dir)
    elif args.operation == "verify-storage":
        result = verify_storage_export(args.directory)
    elif args.operation == "restore-storage":
        result = restore_storage(args.directory)
    else:
        target = os.getenv("JOURNALME_RESTORE_DATABASE_URL") if args.restored_database else None
        if args.restored_database and not target:
            raise BackupError(
                "JOURNALME_RESTORE_DATABASE_URL must point to the isolated restored database."
            )
        result = reconcile_storage(args.directory, target)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_cli())
    except BackupError as exc:
        print(f"backup error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
