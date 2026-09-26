from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.domain import TradeSide
from app.models import (
    CashTransaction,
    DailyBalance,
    ManualAdjustment,
    Trade,
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
