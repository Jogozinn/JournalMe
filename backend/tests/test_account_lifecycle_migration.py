"""Isolated SQLite coverage for migration 0009.

These tests invoke the migration against in-memory databases only; they never
read or write JournalMe's configured database.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

BACKEND_PATH = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_PATH / "alembic" / "versions" / "0009_account_lifecycle_status.py"
)
MIGRATION_SPEC = importlib.util.spec_from_file_location(
    "account_lifecycle_migration", MIGRATION_PATH
)
assert MIGRATION_SPEC and MIGRATION_SPEC.loader
migration = importlib.util.module_from_spec(MIGRATION_SPEC)
MIGRATION_SPEC.loader.exec_module(migration)


def _run_upgrade(connection: sa.Connection) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        migration.upgrade()


def _run_downgrade(connection: sa.Connection) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        migration.downgrade()


def _create_revision_0008_schema(
    connection: sa.Connection, *, lifecycle_status_exists: bool
) -> None:
    metadata = sa.MetaData()
    columns = [
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
    ]
    if lifecycle_status_exists:
        columns.append(
            sa.Column(
                "lifecycle_status",
                sa.String(length=20),
                nullable=False,
                server_default="active",
            )
        )

    sa.Table("trading_accounts", metadata, *columns)
    sa.Table(
        "alembic_version",
        metadata,
        sa.Column("version_num", sa.String(length=32), primary_key=True),
    )
    metadata.create_all(connection)
    connection.execute(
        sa.text("INSERT INTO alembic_version (version_num) VALUES ('0008')")
    )


def _column_details(connection: sa.Connection) -> dict[str, object]:
    columns = sa.inspect(connection).get_columns("trading_accounts")
    matching_columns = [column for column in columns if column["name"] == "lifecycle_status"]
    assert len(matching_columns) == 1
    return matching_columns[0]


def test_upgrade_from_0008_adds_active_lifecycle_status_and_is_idempotent() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        _create_revision_0008_schema(connection, lifecycle_status_exists=False)
        connection.execute(
            sa.text("INSERT INTO trading_accounts (id, name) VALUES (1, 'Existing')")
        )

        _run_upgrade(connection)
        column = _column_details(connection)

        assert column["type"].length == 20
        assert column["nullable"] is False
        assert str(column["default"]).strip("'\"") == "active"
        assert connection.execute(
            sa.text(
                "SELECT lifecycle_status FROM trading_accounts WHERE id = 1"
            )
        ).scalar_one() == "active"
        _run_upgrade(connection)
        _column_details(connection)


def test_upgrade_accepts_partial_0009_column_while_version_is_still_0008() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        _create_revision_0008_schema(connection, lifecycle_status_exists=True)
        connection.execute(
            sa.text("INSERT INTO trading_accounts (id, name) VALUES (1, 'Existing')")
        )

        _run_upgrade(connection)
        column = _column_details(connection)

        assert column["type"].length == 20
        assert column["nullable"] is False
        assert str(column["default"]).strip("'\"") == "active"
        assert connection.execute(
            sa.text(
                "SELECT lifecycle_status FROM trading_accounts WHERE id = 1"
            )
        ).scalar_one() == "active"
        assert connection.execute(
            sa.text("SELECT version_num FROM alembic_version")
        ).scalar_one() == "0008"

        _run_upgrade(connection)
        _column_details(connection)


def test_downgrade_uses_sqlite_safe_column_drop() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        _create_revision_0008_schema(connection, lifecycle_status_exists=False)
        _run_upgrade(connection)

        _run_downgrade(connection)

        assert "lifecycle_status" not in {
            column["name"]
            for column in sa.inspect(connection).get_columns("trading_accounts")
        }
