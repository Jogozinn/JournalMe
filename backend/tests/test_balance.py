from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.domain import TradeSide
from app.models import (
    Attachment,
    BrokerConnection,
    CashTransaction,
    DailyBalance,
    ManualAdjustment,
    Trade,
    TradeJournal,
    TradingAccount,
    User,
)
from app.services.balance import resolve_account_balance


def _account(db: Session) -> TradingAccount:
    user = User(email=f"{uuid4()}@journalme.local", display_name="Balance")
    db.add(user)
    db.flush()
    account = TradingAccount(
        user_id=user.id,
        name="Ledger",
        starting_balance=Decimal("50000"),
        timezone="America/New_York",
    )
    db.add(account)
    db.flush()
    return account


def _trade(account: TradingAccount, pnl: str, at: datetime) -> Trade:
    return Trade(
        account_id=account.id,
        duplicate_fingerprint=str(uuid4()),
        symbol="MESU6",
        contract_quantity=Decimal("1"),
        side=TradeSide.LONG,
        entry_price=Decimal("5000"),
        exit_price=Decimal("5001"),
        gross_pnl=Decimal(pnl),
        fees=Decimal("0"),
        net_pnl=Decimal(pnl),
        entry_timestamp=at,
        exit_timestamp=at,
    )


def _db() -> tuple[Session, TradingAccount]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    return db, _account(db)


def test_no_snapshot_uses_canonical_ledger_without_double_counting_cash() -> None:
    db, account = _db()
    at = datetime(2026, 7, 30, 15, tzinfo=timezone.utc)
    db.add(_trade(account, "1748.25", at))
    db.add_all(
        [
            CashTransaction(
                account_id=account.id,
                import_file_id=uuid4(),
                external_transaction_id="fund",
                timestamp=datetime(2026, 7, 30, 1, tzinfo=timezone.utc),
                trade_date=date(2026, 7, 30),
                delta=Decimal("50000"),
                amount=Decimal("50000"),
                cash_change_type="Fund Transaction",
                currency="USD",
            ),
            CashTransaction(
                account_id=account.id,
                import_file_id=uuid4(),
                external_transaction_id="paired",
                timestamp=at,
                trade_date=date(2026, 7, 30),
                delta=Decimal("1748.25"),
                amount=Decimal("51748.25"),
                cash_change_type="Trade Paired",
                currency="USD",
            ),
        ]
    )
    db.flush()

    result = resolve_account_balance(db, account)

    assert result.resolved_current_balance == Decimal("51748.25")
    assert result.calculated_balance == Decimal("51748.25")
    assert result.external_cash_movements == Decimal("0")
    assert result.resolution_method == "calculated_from_ledger"
    db.close()


def test_stale_snapshot_rolls_forward_newer_activity() -> None:
    db, account = _db()
    db.add(
        DailyBalance(
            account_id=account.id,
            import_file_id=uuid4(),
            trade_date=date(2026, 7, 29),
            total_amount=Decimal("51000"),
            total_realized_pnl=Decimal("1000"),
            source_identity="test",
        )
    )
    db.add(
        _trade(
            account,
            "250",
            datetime(2026, 7, 30, 15, tzinfo=timezone.utc),
        )
    )
    db.add(
        ManualAdjustment(
            account_id=account.id,
            adjustment_type="deposit",
            amount=Decimal("100"),
            effective_at=datetime(2026, 7, 30, 16, tzinfo=timezone.utc),
            reason="Approved deposit",
            status="approved",
        )
    )
    db.flush()

    result = resolve_account_balance(db, account)

    assert result.stale_snapshot is True
    assert result.resolution_method == "stale_snapshot_roll_forward"
    assert result.resolved_current_balance == Decimal("51350")
    db.close()


def test_current_snapshot_wins_but_preserves_reconciliation_difference() -> None:
    db, account = _db()
    at = datetime(2026, 7, 30, 15, tzinfo=timezone.utc)
    db.add(_trade(account, "200", at))
    db.add(
        DailyBalance(
            account_id=account.id,
            import_file_id=uuid4(),
            trade_date=date(2026, 7, 30),
            total_amount=Decimal("50190"),
            total_realized_pnl=Decimal("190"),
            source_identity="test",
        )
    )
    db.flush()

    result = resolve_account_balance(db, account)

    assert result.resolved_current_balance == Decimal("50190")
    assert result.calculated_balance == Decimal("50200")
    assert result.reconciliation_difference == Decimal("-10")
    assert result.stale_snapshot is False
    db.close()


def test_rejected_adjustment_is_not_balance_activity() -> None:
    db, account = _db()
    db.add(
        ManualAdjustment(
            account_id=account.id,
            adjustment_type="deposit",
            amount=Decimal("100"),
            effective_at=datetime(2026, 7, 30, 16, tzinfo=timezone.utc),
            reason="Awaiting approval",
            status="rejected",
        )
    )
    db.flush()

    result = resolve_account_balance(db, account)

    assert result.resolved_current_balance == Decimal("50000")
    assert result.resolution_method == "starting_balance_no_activity"
    db.close()


def test_opening_funding_not_duplicated_when_foreign_broker_trade_predates_funding() -> None:
    """Synthetic account had a 003 execution incorrectly dated before its first funding."""
    db, account = _db()
    account.external_account_id = "006"
    db.add(_trade(account, "100", datetime(2026, 9, 29, 15, tzinfo=timezone.utc)))
    db.add(CashTransaction(
        account_id=account.id,
        import_file_id=uuid4(),
        external_transaction_id="start-006",
        timestamp=datetime(2026, 10, 16, 18, tzinfo=timezone.utc),
        trade_date=date(2026, 10, 16),
        delta=Decimal("50000"),
        amount=Decimal("50000"),
        cash_change_type="Fund Transaction",
        currency="USD",
        source_payload={"Account": "006"},
    ))
    db.flush()
    result = resolve_account_balance(db, account)
    assert result.external_cash_movements == Decimal("0")
    assert result.calculated_balance == Decimal("50100")
    db.close()


def test_only_first_opening_funding_suppressed_not_later_matching_deposit() -> None:
    db, account = _db()
    account.external_account_id = "006"
    for transaction_id, day in [("initial", 16), ("extra", 20)]:
        db.add(CashTransaction(
            account_id=account.id,
            import_file_id=uuid4(),
            external_transaction_id=transaction_id,
            timestamp=datetime(2026, 10, day, 18, tzinfo=timezone.utc),
            trade_date=date(2026, 10, day),
            delta=Decimal("50000"),
            amount=Decimal("50000"),
            cash_change_type="Fund Transaction",
            currency="USD",
            source_payload={"Account": "006"},
        ))
    db.flush()
    result = resolve_account_balance(db, account)
    assert result.external_cash_movements == Decimal("50000")
    assert result.calculated_balance == Decimal("100000")
    db.close()


def test_fresh_authorized_broker_snapshot_is_reported_separately_and_selected() -> None:
    db, account = _db()
    account.external_account_id = "funded-1"
    connection = BrokerConnection(
        user_id=account.user_id,
        account_id=account.id,
        provider="ninjatrader",
        connection_type="desktop_bridge",
        display_name="Funded bridge source",
        source_account_name="funded-1",
        metadata_json={
            "account_snapshot": {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "cash_value": "50205.50",
                "net_liquidation": "50204.75",
            }
        },
    )
    db.add(connection)
    db.add(_trade(account, "205.50", datetime.now(timezone.utc)))
    db.flush()

    result = resolve_account_balance(db, account)

    assert result.resolved_current_balance == Decimal("50205.50")
    assert result.calculated_balance == Decimal("50205.50")
    assert result.broker_reported_cash_value == Decimal("50205.50")
    assert result.broker_reported_net_liquidation == Decimal("50204.75")
    assert result.broker_snapshot_fresh is True
    assert result.resolution_method == "broker_reported_snapshot"
    assert result.reconciliation_difference == Decimal("0.00")
    db.close()


def test_stale_or_other_accounts_broker_snapshots_are_not_authoritative() -> None:
    db, account = _db()
    foreign_account = _account(db)
    db.add(BrokerConnection(
        user_id=foreign_account.user_id,
        account_id=foreign_account.id,
        provider="ninjatrader",
        connection_type="desktop_bridge",
        display_name="Other account bridge source",
        metadata_json={
            "account_snapshot": {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "cash_value": "99999",
            }
        },
    ))
    db.add(BrokerConnection(
        user_id=account.user_id,
        account_id=account.id,
        provider="ninjatrader",
        connection_type="desktop_bridge",
        display_name="Stale bridge source",
        metadata_json={
            "account_snapshot": {
                "captured_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
                "cash_value": "50100",
            }
        },
    ))
    db.add(_trade(account, "100", datetime.now(timezone.utc)))
    db.flush()

    result = resolve_account_balance(db, account)

    assert result.resolved_current_balance == Decimal("50100")
    assert result.resolution_method == "calculated_from_ledger"
    assert result.broker_reported_cash_value == Decimal("50100")
    assert result.broker_snapshot_fresh is False
    db.close()


def test_mismatched_opening_funding_source_is_not_silently_discarded() -> None:
    db, account = _db()
    account.external_account_id = "006"
    db.add(CashTransaction(
        account_id=account.id,
        import_file_id=uuid4(),
        external_transaction_id="foreign-funding",
        timestamp=datetime(2026, 10, 16, 18, tzinfo=timezone.utc),
        trade_date=date(2026, 10, 16),
        delta=Decimal("50000"),
        amount=Decimal("50000"),
        cash_change_type="Fund Transaction",
        currency="USD",
        source_payload={"Account": "003"},
    ))
    db.flush()
    result = resolve_account_balance(db, account)
    assert result.external_cash_movements == Decimal("50000")
    db.close()


def test_superseded_trade_is_excluded_from_ledger_without_losing_journal_or_amount() -> None:
    db, account = _db()
    trade = _trade(account, "73.35", datetime(2026, 10, 20, 15, tzinfo=timezone.utc))
    trade.accounting_status = "superseded"
    trade.accounting_exclusion_reason = "Overlapping broker execution allocation"
    original_pnl = trade.net_pnl
    trade.journal = TradeJournal(custom_notes="Keep this review with the source row")
    db.add(trade)
    db.flush()
    attachment = Attachment(
        trade_id=trade.id,
        storage_key="evidence/source.pdf",
        original_filename="source.pdf",
        mime_type="application/pdf",
    )
    db.add(attachment)
    other_account = TradingAccount(
        user_id=account.user_id,
        name="Account 007",
        starting_balance=Decimal("25000"),
    )
    db.add(other_account)
    db.flush()
    other_trade = _trade(
        other_account, "10", datetime(2026, 10, 20, 15, tzinfo=timezone.utc)
    )
    db.add(other_trade)
    db.flush()

    result = resolve_account_balance(db, account)

    assert result.calculated_balance == Decimal("50000")
    assert db.scalar(select(Trade).where(Trade.id == trade.id)) is None
    preserved = db.scalar(
        select(Trade)
        .where(Trade.id == trade.id)
        .execution_options(include_excluded_accounting=True)
    )
    assert preserved is not None
    assert preserved.net_pnl == original_pnl == Decimal("73.35")
    assert preserved.journal.custom_notes == "Keep this review with the source row"
    assert db.get(Attachment, attachment.id) is not None
    other_result = resolve_account_balance(db, other_account)
    assert other_result.calculated_balance == Decimal("25010")
    db.close()


def test_futures_evening_fill_rolls_forward_by_trading_date() -> None:
    db, account = _db()
    db.add(
        DailyBalance(
            account_id=account.id,
            import_file_id=uuid4(),
            trade_date=date(2026, 10, 21),
            total_amount=Decimal("1012.50"),
            total_realized_pnl=Decimal("12.50"),
            source_identity="tradovate:test-account",
        )
    )
    # 22:30 UTC is 18:30 Eastern, which belongs to the next futures date.
    db.add(_trade(account, "-32.50", datetime(2026, 10, 21, 22, 30, tzinfo=timezone.utc)))
    db.flush()

    result = resolve_account_balance(db, account)

    assert result.stale_snapshot is True
    assert result.resolved_current_balance == Decimal("980.00")
    db.close()


def test_seventeen_october_22_23_trades_apply_fill_commissions_once() -> None:
    db, account = _db()
    db.add(
        DailyBalance(
            account_id=account.id,
            import_file_id=uuid4(),
            trade_date=date(2026, 10, 21),
            total_amount=Decimal("1012.50"),
            total_realized_pnl=Decimal("12.50"),
            source_identity="tradovate:test-account",
        )
    )
    # Reconstructed from account 006's Tradovate exports. The broker reports
    # paired lots at close-fill timestamps, which aggregate to these
    # flat-to-flat trades; fill-ID commissions are allocated once.
    daily_groups = [
        (
            date(2026, 10, 22),
            datetime(2026, 10, 22, 16, tzinfo=timezone.utc),
            [
                (
                    "10.00", "1",
                    "test-fill-001,test-fill-002,test-fill-003,test-fill-006",
                    "test-fill-004,test-fill-005,test-fill-007",
                ),
                ("20.00", "1", "test-fill-008,test-fill-009", "test-fill-010"),
                (
                    "30.00", "1",
                    "test-fill-011,test-fill-012,test-fill-013",
                    "test-fill-014,test-fill-015",
                ),
                (
                    "-10.00", "1", "test-fill-016,test-fill-017,test-fill-019",
                    "test-fill-018,test-fill-020",
                ),
                ("-20.00", "1", "test-fill-021,test-fill-022", "test-fill-023"),
                ("40.00", "1", "test-fill-024,test-fill-025", "test-fill-026"),
                (
                    "50.00", "1", "test-fill-027,test-fill-028,test-fill-030",
                    "test-fill-029,test-fill-031",
                ),
                (
                    "60.00", "1",
                    "test-fill-032,test-fill-033,test-fill-034,test-fill-035,test-fill-036",
                    "test-fill-037,test-fill-038,test-fill-039,test-fill-040",
                ),
            ],
        ),
        (
            date(2026, 10, 23),
            datetime(2026, 10, 23, 16, tzinfo=timezone.utc),
            [
                (
                    "-5.00", "1", "test-fill-041,test-fill-042,test-fill-043",
                    "test-fill-044,test-fill-045",
                ),
                (
                    "15.00", "1",
                    "test-fill-046,test-fill-047,test-fill-048,test-fill-049",
                    "test-fill-050,test-fill-051,test-fill-052",
                ),
                (
                    "-25.00", "1",
                    "test-fill-053,test-fill-054,test-fill-055,test-fill-056,test-fill-057",
                    "test-fill-058,test-fill-059,test-fill-060,test-fill-061",
                ),
                ("35.00", "1", "test-fill-062,test-fill-063", "test-fill-064"),
                (
                    "-30.00", "1",
                    "test-fill-065,test-fill-066,test-fill-067,test-fill-069",
                    "test-fill-068,test-fill-070",
                ),
                ("-10.00", "1", "test-fill-071,test-fill-072", "test-fill-073"),
                ("45.00", "1", "test-fill-074,test-fill-075", "test-fill-076"),
                ("55.00", "1", "test-fill-077,test-fill-078", "test-fill-079"),
                (
                    "65.00", "1",
                    "test-fill-080,test-fill-081,test-fill-082,test-fill-083",
                    "test-fill-084,test-fill-085,test-fill-086",
                ),
            ],
        ),
    ]
    trade_count = 0
    fill_ids: set[str] = set()
    paired_cash_ids: set[str] = set()
    gross_total = Decimal("0")
    trade_fee_total = Decimal("0")
    for trading_date, timestamp, values in daily_groups:
        for gross, fees, executions, paired in values:
            execution_ids = set(executions.split(","))
            paired_ids = set(paired.split(","))
            assert fill_ids.isdisjoint(execution_ids)
            assert paired_cash_ids.isdisjoint(paired_ids)
            fill_ids.update(execution_ids)
            paired_cash_ids.update(paired_ids)
            gross_total += Decimal(gross)
            trade_fee_total += Decimal(fees)
            trade = _trade(account, str(Decimal(gross) - Decimal(fees)), timestamp)
            trade.gross_pnl = Decimal(gross)
            trade.fees = Decimal(fees)
            trade.source_payload = {
                "execution_ids": sorted(execution_ids),
                "paired_cash_transaction_ids": sorted(paired_ids),
            }
            db.add(trade)
            trade_count += 1
        db.add(CashTransaction(
            account_id=account.id,
            import_file_id=uuid4(),
            external_transaction_id=f"commission-{trading_date.isoformat()}",
            timestamp=timestamp,
            trade_date=trading_date,
            delta=Decimal("-8") if trading_date.day == 22 else Decimal("-9"),
            amount=Decimal("0"),
            cash_change_type="Commission",
            currency="USD",
        ))
    db.flush()

    result = resolve_account_balance(db, account)

    assert trade_count == 17
    assert len(fill_ids) == 52
    assert len(paired_cash_ids) == 34
    assert gross_total == Decimal("325")
    assert trade_fee_total == Decimal("17")
    assert result.canonical_trade_net_pnl == Decimal("308.0000")
    assert result.external_cash_movements == Decimal("0")
    assert result.resolved_current_balance == Decimal("1320.5000")
    db.close()


def test_latest_balance_revision_is_used_without_mutating_original_snapshot() -> None:
    db, account = _db()
    original = DailyBalance(
        account_id=account.id,
        import_file_id=uuid4(),
        trade_date=date(2026, 10, 21),
        total_amount=Decimal("1000.00"),
        total_realized_pnl=Decimal("0.00"),
        source_identity="tradovate:test-account",
        revision=1,
    )
    db.add(original)
    db.flush()
    revised = DailyBalance(
        account_id=account.id,
        import_file_id=uuid4(),
        trade_date=date(2026, 10, 21),
        total_amount=Decimal("1012.50"),
        total_realized_pnl=Decimal("12.50"),
        source_identity="tradovate:test-account",
        revision=2,
        supersedes_id=original.id,
    )
    db.add(revised)
    db.flush()

    result = resolve_account_balance(db, account)
    db.expire_all()

    assert result.resolved_current_balance == Decimal("1012.50")
    assert db.get(DailyBalance, original.id).total_amount == Decimal("1000.00")
    assert db.get(DailyBalance, revised.id).supersedes_id == original.id
    db.close()
