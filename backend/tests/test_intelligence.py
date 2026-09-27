from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.domain import TradeSide
from app.models import (
    AccountLifecycleStatus,
    AccountType,
    DailyJournal,
    Trade,
    TradingAccount,
)
from app.services.intelligence import build_intelligence_overview
from app.services.review import day_review_status


def make_account(name: str, *, active: bool = True) -> TradingAccount:
    return TradingAccount(
        id=uuid4(),
        user_id=uuid4(),
        name=name,
        provider="tradovate",
        account_type=AccountType.EVALUATION,
        starting_balance=Decimal("50000"),
        timezone="America/New_York",
        currency="USD",
        active=active,
        include_in_learning=True,
        lifecycle_status=AccountLifecycleStatus.ACTIVE if active else AccountLifecycleStatus.CLOSED,
    )


def make_trade(
    account: TradingAccount,
    when: datetime,
    pnl: str,
    quantity: str = "1",
) -> Trade:
    value = Decimal(pnl)
    return Trade(
        id=uuid4(),
        account_id=account.id,
        duplicate_fingerprint=str(uuid4()),
        symbol="MNQZ6",
        root_symbol="MNQ",
        contract_quantity=Decimal(quantity),
        side=TradeSide.LONG,
        entry_price=Decimal("25000"),
        exit_price=Decimal("25001"),
        gross_pnl=value,
        fees=Decimal("0"),
        net_pnl=value,
        currency="USD",
        entry_timestamp=when,
        exit_timestamp=when + timedelta(minutes=1),
        duration_seconds=60,
        source_quality="test",
        reconciliation_status="reconciled",
        source_payload={},
    )


def test_intelligence_combines_multiple_accounts_and_keeps_current_comparison() -> None:
    first = make_account("Old account", active=False)
    current = make_account("Current account")
    start = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)
    trades: list[Trade] = []
    for account_index, account in enumerate((first, current)):
        for day in range(6):
            base = start + timedelta(days=day + account_index * 10)
            trades.extend(
                [
                    make_trade(account, base, "80"),
                    make_trade(account, base + timedelta(minutes=10), "60"),
                    make_trade(account, base + timedelta(minutes=20), "40"),
                    make_trade(account, base + timedelta(minutes=30), "-100"),
                ]
            )
    journals = [
        DailyJournal(
            account_id=current.id,
            trading_date=(start + timedelta(days=day + 10)).date(),
            quick_rating="good",
            quick_emotion_tags_json=["focused"],
            quick_focus_tags_json=["patience"],
            quick_behavior_tags_json=[],
            review_depth="quick",
            followed_rules=True,
        )
        for day in range(5)
    ]
    result = build_intelligence_overview(
        [first, current], trades, journals, current_account_id=current.id
    )
    assert result["coverage"]["accounts"] == 2
    assert result["summary"]["trades"] == 48
    assert result["current_vs_history"]["current_account_id"] == str(current.id)
    assert result["coverage"]["psychology_scope"] == "objective_plus_mindset"
    trade_number = next(item for item in result["insights"] if item["key"] == "trade_number")
    assert Decimal(trade_number["difference_in_expectancy"]) > 0
    assert trade_number["condition"]["trades"] == 36
    assert trade_number["comparison"]["trades"] == 12


def test_quick_daily_review_can_complete_without_essay_fields() -> None:
    account = make_account("Quick")
    journal = DailyJournal(
        account_id=account.id,
        trading_date=datetime(2026, 9, 26).date(),
        quick_rating="mixed",
        quick_focus_tags_json=["risk"],
        quick_emotion_tags_json=["frustrated"],
        quick_behavior_tags_json=["overtraded"],
        quick_note=None,
        review_depth="quick",
        followed_rules=False,
    )
    status = day_review_status(
        journal,
        [],
        {"day_fields": ["reflection", "focus_for_next_session", "day_grade", "followed_rules"]},
    )
    assert status["status"] == "complete"
    assert status["missing"] == []
