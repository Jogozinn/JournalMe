"""Isolated SQLite coverage for migration 0017; production databases are never used."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

BACKEND_PATH = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_PATH
    / "alembic"
    / "versions"
    / "0017_accounting_exclusions_and_balance_revisions.py"
)
MIGRATION_SPEC = importlib.util.spec_from_file_location(
    "accounting_revision_migration", MIGRATION_PATH
)
assert MIGRATION_SPEC and MIGRATION_SPEC.loader
migration = importlib.util.module_from_spec(MIGRATION_SPEC)
MIGRATION_SPEC.loader.exec_module(migration)

SUSPECT_TRADE_IDS = [
    UUID("00000000-0000-4000-8000-000000000001"),
    UUID("00000000-0000-4000-8000-000000000002"),
    UUID("00000000-0000-4000-8000-000000000003"),
    UUID("00000000-0000-4000-8000-000000000004"),
    UUID("00000000-0000-4000-8000-000000000005"),
]
SUSPECT_PNLS = ["9.20", "22.87", "10.37", "5.98", "24.92"]


def _run(connection: sa.Connection, direction: str) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(migration, direction)()


def _create_revision_0016_schema(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    sa.Table("trading_accounts", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    sa.Table("import_files", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    sa.Table(
        "trades",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("duplicate_fingerprint", sa.String(64), nullable=False),
        sa.Column("net_pnl", sa.Numeric(18, 4), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("account_id", "duplicate_fingerprint", name="uq_trade_fingerprint"),
    )
    sa.Table(
        "daily_balances",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("import_file_id", sa.Uuid(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("total_realized_pnl", sa.Numeric(18, 4), nullable=False),
        sa.Column("source_identity", sa.String(120), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "account_id", "trade_date", "source_identity", name="uq_daily_balance_source"
        ),
    )
    metadata.create_all(connection)


def test_upgrade_preserves_suspect_trade_values_accounts_and_snapshot_provenance() -> None:
    engine = sa.create_engine("sqlite://")
    account_006, account_007 = uuid4(), uuid4()
    archived_accounts = [uuid4() for _ in range(4)]
    import_file = uuid4()
    snapshot_id = uuid4()
    with engine.begin() as connection:
        _create_revision_0016_schema(connection)
        connection.execute(
            sa.text("INSERT INTO trading_accounts (id) VALUES (:id)"),
            [
                {"id": str(account_id)}
                for account_id in [account_006, account_007, *archived_accounts]
            ],
        )
        connection.execute(
            sa.text("INSERT INTO import_files (id) VALUES (:id)"),
            {"id": str(import_file)},
        )
        for index, (trade_id, pnl) in enumerate(zip(SUSPECT_TRADE_IDS, SUSPECT_PNLS, strict=True)):
            connection.execute(
                sa.text(
                    "INSERT INTO trades "
                    "(id, account_id, duplicate_fingerprint, net_pnl, source_payload) "
                    "VALUES (:id, :account_id, :fingerprint, :pnl, :payload)"
                ),
                {
                    "id": str(trade_id),
                    "account_id": str(account_006),
                    "fingerprint": f"overlap-{index}",
                    "pnl": pnl,
                    "payload": '{"execution_ids":["kept-source-id"]}',
                },
            )
        preserved_accounts = [("007", account_007)] + [
            (f"archived-{index}", account_id)
            for index, account_id in enumerate(archived_accounts, start=1)
        ]
        for label, account_id in preserved_accounts:
            connection.execute(
                sa.text(
                    "INSERT INTO trades "
                    "(id, account_id, duplicate_fingerprint, net_pnl, source_payload) "
                    "VALUES (:id, :account_id, :fingerprint, :pnl, :payload)"
                ),
                {
                    "id": str(uuid4()),
                    "account_id": str(account_id),
                    "fingerprint": label,
                    "pnl": "100.00",
                    "payload": '{"history":"preserve"}',
                },
            )
        connection.execute(
            sa.text(
                "INSERT INTO daily_balances "
                "(id, account_id, import_file_id, trade_date, total_amount, "
                "total_realized_pnl, source_identity, source_payload) "
                "VALUES (:id, :account_id, :file_id, '2026-10-21', 1000.00, "
                "0.00, 'tradovate:TEST-TRADOVATE-ACCOUNT', :payload)"
            ),
            {
                "id": str(snapshot_id),
                "account_id": str(account_006),
                "file_id": str(import_file),
                "payload": '{"source_report":"original","account":"TEST-TRADOVATE-ACCOUNT"}',
            },
        )

        _run(connection, "upgrade")

        trades = connection.execute(
            sa.text(
                "SELECT id, account_id, duplicate_fingerprint, net_pnl, "
                "accounting_status, source_payload "
                "FROM trades ORDER BY id"
            )
        ).mappings().all()
        assert len(trades) == 10
        for trade_id, pnl in zip(SUSPECT_TRADE_IDS, SUSPECT_PNLS, strict=True):
            row = next(item for item in trades if UUID(str(item["id"])) == trade_id)
            assert row["accounting_status"] == "included"
            assert row["net_pnl"] == float(pnl)
            assert "kept-source-id" in row["source_payload"]
        assert {str(item["account_id"]) for item in trades} == {
            str(account_006), str(account_007),
            *(str(account_id) for account_id in archived_accounts),
        }
        preserved = {
            item["duplicate_fingerprint"]: item
            for item in trades
            if str(item["account_id"]) != str(account_006)
        }
        assert len(preserved) == 5
        assert all(item["accounting_status"] == "included" for item in preserved.values())
        assert all(item["net_pnl"] == 100 for item in preserved.values())
        assert all("history" in item["source_payload"] for item in preserved.values())

        original = connection.execute(
            sa.text(
                "SELECT revision, supersedes_id, total_amount, import_file_id, source_payload "
                "FROM daily_balances WHERE id = :id"
            ),
            {"id": str(snapshot_id)},
        ).mappings().one()
        assert original["revision"] == 1
        assert original["supersedes_id"] is None
        assert original["total_amount"] == 1000.0
        assert UUID(str(original["import_file_id"])) == import_file
        assert "original" in original["source_payload"]

        revised_id = uuid4()
        connection.execute(
            sa.text(
                "INSERT INTO daily_balances "
                "(id, account_id, import_file_id, trade_date, total_amount, "
                "total_realized_pnl, source_identity, source_payload, revision, supersedes_id) "
                "VALUES (:id, :account_id, :file_id, '2026-10-21', 1012.50, "
                "12.50, 'tradovate:TEST-TRADOVATE-ACCOUNT', '{\"source_report\":\"newer\"}', "
                "2, :supersedes_id)"
            ),
            {
                "id": str(revised_id),
                "account_id": str(account_006),
                "file_id": str(import_file),
                "supersedes_id": str(snapshot_id),
            },
        )
        assert connection.execute(
            sa.text("SELECT count(*) FROM daily_balances")
        ).scalar_one() == 2


def test_downgrade_refuses_to_drop_exclusion_or_revision_history_then_rolls_back_cleanly() -> None:
    engine = sa.create_engine("sqlite://")
    account_id, import_file = uuid4(), uuid4()
    trade_id, snapshot_id = uuid4(), uuid4()
    with engine.begin() as connection:
        _create_revision_0016_schema(connection)
        connection.execute(
            sa.text("INSERT INTO trading_accounts (id) VALUES (:id)"),
            {"id": str(account_id)},
        )
        connection.execute(
            sa.text("INSERT INTO import_files (id) VALUES (:id)"),
            {"id": str(import_file)},
        )
        connection.execute(
            sa.text(
                "INSERT INTO trades "
                "(id, account_id, duplicate_fingerprint, net_pnl, source_payload) "
                "VALUES (:id, :account_id, 'one', 920.50, '{}')"
            ),
            {"id": str(trade_id), "account_id": str(account_id)},
        )
        connection.execute(
            sa.text(
                "INSERT INTO daily_balances "
                "(id, account_id, import_file_id, trade_date, total_amount, "
                "total_realized_pnl, source_identity, source_payload) "
                "VALUES (:id, :account_id, :file_id, '2026-10-21', 1000.00, "
                "0.00, 'tradovate:test-account', '{}')"
            ),
            {
                "id": str(snapshot_id),
                "account_id": str(account_id),
                "file_id": str(import_file),
            },
        )
        _run(connection, "upgrade")
        connection.execute(
            sa.text(
                "UPDATE trades SET accounting_status='superseded', "
                "accounting_exclusion_reason='overlapping execution' WHERE id=:id"
            ),
            {"id": str(trade_id)},
        )
        connection.execute(
            sa.text(
                "UPDATE daily_balances SET revision=2, supersedes_id=:prior "
                "WHERE id=:id"
            ),
            {"id": str(snapshot_id), "prior": str(snapshot_id)},
        )
        with pytest.raises(RuntimeError, match="Cannot downgrade accounting revision"):
            _run(connection, "downgrade")
        assert connection.execute(
            sa.text("SELECT net_pnl, accounting_status FROM trades WHERE id=:id"),
            {"id": str(trade_id)},
        ).one() == (920.5, "superseded")

        connection.execute(
            sa.text(
                "UPDATE trades SET accounting_status='included', "
                "accounting_exclusion_reason=NULL WHERE id=:id"
            ),
            {"id": str(trade_id)},
        )
        connection.execute(
            sa.text(
                "UPDATE daily_balances SET revision=1, supersedes_id=NULL WHERE id=:id"
            ),
            {"id": str(snapshot_id)},
        )
        _run(connection, "downgrade")
        assert "accounting_status" not in {
            item["name"] for item in sa.inspect(connection).get_columns("trades")
        }
        assert "revision" not in {
            item["name"] for item in sa.inspect(connection).get_columns("daily_balances")
        }
        assert connection.execute(
            sa.text("SELECT net_pnl FROM trades WHERE id=:id"),
            {"id": str(trade_id)},
        ).scalar_one() == 920.5
