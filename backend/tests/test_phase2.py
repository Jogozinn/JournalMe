from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.phase2 import router
from app.api.router import router as core_router
from app.auth import get_current_user
from app.database import Base, get_db
from app.domain import TradeSide
from app.models import (
    AuditEvent,
    DailyJournal,
    Playbook,
    PlaybookChecklistItem,
    PropRuleProfile,
    PropRuleProfileVersion,
    PropScalingTier,
    Tag,
    TagCategory,
    Trade,
    TradeChecklistResponse,
    TradeJournal,
    TradePlaybook,
    TradingAccount,
    User,
)
from app.schemas import PropRuleUpdate
from app.services.prop_rules import calculate_prop_status
from app.services.review import day_review_status, review_rules, trade_review_statuses


def _trade(
    account: TradingAccount,
    *,
    pnl: str = "100",
    symbol: str = "MESU6",
    at: datetime | None = None,
) -> Trade:
    entry_at = at or datetime(2026, 7, 29, 14, tzinfo=timezone.utc)
    return Trade(
        account_id=account.id,
        duplicate_fingerprint=f"{symbol}-{pnl}-{datetime.now(timezone.utc).timestamp()}",
        symbol=symbol,
        root_symbol="MES",
        contract_quantity=Decimal("2"),
        side=TradeSide.LONG,
        entry_price=Decimal("5000"),
        exit_price=Decimal("5001"),
        gross_pnl=Decimal(pnl) + Decimal("2"),
        fees=Decimal("2"),
        net_pnl=Decimal(pnl),
        entry_timestamp=entry_at,
        exit_timestamp=entry_at.replace(minute=entry_at.minute + 5),
        duration_seconds=300,
    )


def test_review_completion_is_explicit_and_shared() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="review@journalme.local", display_name="Review")
        db.add(user)
        db.flush()
        account = TradingAccount(user_id=user.id, name="Review account")
        playbook = Playbook(user_id=user.id, name="Opening plan")
        tag = Tag(user_id=user.id, name="ORB", category=TagCategory.SETUP)
        db.add_all([account, playbook, tag])
        db.flush()
        checklist = PlaybookChecklistItem(
            playbook_id=playbook.id,
            text="Waited for confirmation",
            required=True,
        )
        trade = _trade(account)
        trade.tags = [tag]
        trade.journal = TradeJournal(
            thesis="Continuation",
            entry_reason="Confirmed range break",
            exit_reason="Target reached",
            lesson_learned="Keep risk fixed",
            trade_grade="A",
            followed_plan=True,
        )
        db.add_all([checklist, trade])
        db.flush()
        db.add_all(
            [
                TradePlaybook(
                    trade_id=trade.id,
                    playbook_id=playbook.id,
                    is_primary=True,
                ),
                TradeChecklistResponse(
                    trade_id=trade.id,
                    checklist_item_id=checklist.id,
                    passed=True,
                ),
            ]
        )
        db.commit()
        status_payload = trade_review_statuses(db, user.id, [trade])[trade.id]
        assert status_payload["status"] == "complete"
        assert status_payload["missing"] == []
        assert status_payload["adherence_percent"] == 100

        journal = DailyJournal(
            account_id=account.id,
            trading_date=date(2026, 7, 29),
            reflection="Strong process",
            focus_for_next_session="Repeat it",
            day_grade="A",
            followed_rules=True,
        )
        rules = review_rules(db, user.id)
        assert day_review_status(journal, [status_payload], rules)["status"] == "complete"


def test_prop_calculation_shows_formula_inputs_and_buffers() -> None:
    user = User(email="prop@journalme.local", display_name="Prop")
    account = TradingAccount(
        user_id=user.id,
        name="Evaluation",
        starting_balance=Decimal("50000"),
        timezone="America/New_York",
    )
    trades = [_trade(account, pnl="1000"), _trade(account, pnl="500", symbol="MNQU6")]
    profile = PropRuleProfile(
        account_id=account.id,
        firm_name="Configurable Firm",
        starting_balance=Decimal("50000"),
        profit_target=Decimal("3000"),
        max_loss=Decimal("2000"),
        daily_loss_limit=Decimal("1000"),
        consistency_percent=Decimal("50"),
        minimum_trading_days=3,
    )
    payload = calculate_prop_status(account, profile, trades, [])
    assert payload["status"]["current_balance"] == "51500.00"
    assert payload["status"]["net_profit"] == "1500.00"
    assert payload["status"]["profit_remaining"] == "1500.00"
    assert payload["status"]["maximum_loss_buffer"] == "3500.00"
    assert payload["status"]["estimated_pass"] is False
    assert "current balance" in payload["formulas"]["net_profit"]


def test_prop_optional_values_normalize_without_losing_zero() -> None:
    payload = PropRuleUpdate.model_validate(
        {
            "firm_name": "Lucid Trading",
            "profit_target": " ",
            "max_loss": "2000",
            "daily_loss_limit": "",
            "consistency_percent": "0",
            "payout_buffer": "0",
            "minimum_trading_days": "  ",
        }
    )
    assert payload.profit_target is None
    assert payload.daily_loss_limit is None
    assert payload.minimum_trading_days is None
    assert payload.consistency_percent == Decimal("0")
    assert payload.payout_buffer == Decimal("0")

    try:
        PropRuleUpdate.model_validate(
            {
                "firm_name": "Lucid Trading",
                "profit_target": "not-a-number",
                "max_loss": "2000",
            }
        )
    except ValidationError as exc:
        assert exc.errors()[0]["loc"] == ("profit_target",)
    else:
        raise AssertionError("Invalid non-empty profit target should fail validation.")


def test_lucidflex_real_data_payout_and_scaling_status() -> None:
    user = User(email="lucid-status@journalme.local", display_name="Lucid")
    account = TradingAccount(
        user_id=user.id,
        name="Lucid Flex",
        starting_balance=Decimal("50000"),
        timezone="America/New_York",
    )
    profile = PropRuleProfile(
        account_id=account.id,
        firm_name="Lucid Trading",
        profile_account_type="LucidFlex Funded",
        starting_balance=Decimal("50000"),
        profit_target=None,
        max_loss=Decimal("2000"),
        daily_loss_limit=None,
        consistency_percent=None,
        drawdown_type="end_of_day_trailing",
        drawdown_amount=Decimal("2000"),
        payout_buffer=None,
        minimum_trading_days=None,
        qualifying_profit_days_required=5,
        minimum_profit_per_qualifying_day=Decimal("150"),
        payout_cycle_net_profit_required=True,
        minimum_payout=Decimal("500"),
        payout_profit_percentage=Decimal("50"),
        maximum_payout=Decimal("2000"),
        maximum_payout_count=5,
        profit_split_trader_percent=Decimal("90"),
        profit_split_firm_percent=Decimal("10"),
        qualifying_days_since_last_payout=0,
        payouts_completed=0,
    )
    version = PropRuleProfileVersion(
        profile_id=profile.id,
        version_number=1,
        effective_date=date(2026, 7, 27),
        rules_json={},
    )
    version.scaling_tiers = [
        PropScalingTier(
            lower_profit_bound=Decimal("0"),
            upper_profit_bound=Decimal("999.99"),
            max_mini_contracts=2,
            max_micro_contracts=20,
        ),
        PropScalingTier(
            lower_profit_bound=Decimal("1000"),
            upper_profit_bound=Decimal("1999.99"),
            max_mini_contracts=3,
            max_micro_contracts=30,
        ),
        PropScalingTier(
            lower_profit_bound=Decimal("2000"),
            upper_profit_bound=Decimal("2999.99"),
            max_mini_contracts=4,
            max_micro_contracts=40,
        ),
    ]
    trades = [
        _trade(
            account,
            pnl="-25",
            symbol="MCLU6",
            at=datetime(2026, 7, 27, 14, tzinfo=timezone.utc),
        ),
        _trade(
            account,
            pnl="-385",
            symbol="MNQU6",
            at=datetime(2026, 7, 28, 14, tzinfo=timezone.utc),
        ),
        _trade(
            account,
            pnl="2531.70",
            symbol="MESU6",
            at=datetime(2026, 7, 29, 14, tzinfo=timezone.utc),
        ),
    ]
    payload = calculate_prop_status(
        account,
        profile,
        trades,
        [],
        version=version,
    )
    assert payload["status"]["current_balance"] == "52121.70"
    assert payload["configured"]["profit_target"] is None
    assert payload["configured"]["payout_buffer"] is None
    assert payload["payout_cycle"]["qualifying_day_count"] == 1
    assert payload["payout_cycle"]["qualifying_day_dates"] == ["2026-07-29"]
    assert payload["payout_cycle"]["cycle_net_profit"] == "2121.70"
    assert payload["payout_cycle"]["gross_available_payout"] == "1060.85"
    assert payload["payout_cycle"]["estimated_trader_share"] == "954.77"
    assert payload["payout_cycle"]["eligible_for_payout"] is False
    assert payload["scaling"]["current"]["max_mini_contracts"] == 4
    assert payload["scaling"]["current"]["max_micro_contracts"] == 40

    threshold_payload = calculate_prop_status(
        account,
        profile,
        [
            _trade(
                account,
                pnl="100",
                symbol="MES1",
                at=datetime(2026, 8, 1, 14, tzinfo=timezone.utc),
            ),
            _trade(
                account,
                pnl="-25",
                symbol="MES2",
                at=datetime(2026, 8, 2, 14, tzinfo=timezone.utc),
            ),
            _trade(
                account,
                pnl="200",
                symbol="MES3",
                at=datetime(2026, 8, 3, 14, tzinfo=timezone.utc),
            ),
        ],
        [],
        version=version,
    )
    assert threshold_payload["payout_cycle"]["qualifying_day_count"] == 1

    capped = calculate_prop_status(
        account,
        profile,
        [_trade(account, pnl="5000")],
        [],
        version=version,
    )
    assert capped["payout_cycle"]["gross_available_payout"] == "2000.00"
    assert capped["payout_cycle"]["estimated_trader_share"] == "1800.00"

    below_minimum = calculate_prop_status(
        account,
        profile,
        [_trade(account, pnl="800")],
        [],
        version=version,
    )
    assert below_minimum["payout_cycle"]["gross_available_payout"] == "400.00"
    assert below_minimum["payout_cycle"]["minimum_payout_met"] is False
    assert below_minimum["payout_cycle"]["requestable_payout"] is None


def test_payout_cycle_only_resets_after_approval_and_versions_stay_immutable() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    user = User(email="payout@journalme.local", display_name="Payout")
    db.add(user)
    db.flush()
    account = TradingAccount(
        user_id=user.id,
        name="Lucid Flex",
        starting_balance=Decimal("50000"),
        timezone="America/New_York",
    )
    db.add(account)
    db.flush()
    for index in range(5):
        db.add(
            _trade(
                account,
                pnl="200",
                symbol=f"MES{index}",
                at=datetime(2026, 7, index + 1, 14, tzinfo=timezone.utc),
            )
        )
    db.commit()

    app = FastAPI()
    app.include_router(core_router, prefix="/api/v1")
    app.include_router(router, prefix="/api/v1")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)

    preset = client.post(
        f"/api/v1/prop-rules/{account.id}/preset/lucidflex-funded-50k"
    )
    assert preset.status_code == 200, preset.text
    initial = client.get(f"/api/v1/prop-rules/{account.id}/status").json()
    assert initial["payout_cycle"]["qualifying_day_count"] == 5
    assert initial["payout_cycle"]["eligible_for_payout"] is True
    assert initial["payout_cycle"]["gross_available_payout"] == "500.00"
    initial_cycle_id = initial["payout_cycle"]["id"]

    pending = client.post(
        f"/api/v1/prop-rules/{account.id}/payouts",
        json={
            "request_date": "2026-07-06",
            "requested_amount": "500",
            "notes": "First request",
        },
    )
    assert pending.status_code == 201, pending.text
    rejected = client.patch(
        f"/api/v1/prop-rules/{account.id}/payouts/{pending.json()['id']}",
        json={
            "status": "rejected",
            "reason": "Rejected for regression test.",
        },
    )
    assert rejected.status_code == 200, rejected.text
    after_rejection = client.get(
        f"/api/v1/prop-rules/{account.id}/status"
    ).json()
    assert after_rejection["payout_cycle"]["id"] == initial_cycle_id
    assert after_rejection["payout_cycle"]["qualifying_day_count"] == 5

    approved_request = client.post(
        f"/api/v1/prop-rules/{account.id}/payouts",
        json={
            "request_date": "2026-07-07",
            "requested_amount": "500",
        },
    )
    approved = client.patch(
        f"/api/v1/prop-rules/{account.id}/payouts/{approved_request.json()['id']}",
        json={
            "status": "approved",
            "approved_date": "2026-07-10",
            "reason": "Approved for regression test.",
        },
    )
    assert approved.status_code == 200, approved.text
    assert Decimal(approved.json()["trader_amount"]) == Decimal("450")
    assert Decimal(approved.json()["firm_amount"]) == Decimal("50")
    after_approval = client.get(
        f"/api/v1/prop-rules/{account.id}/status"
    ).json()
    assert after_approval["payout_cycle"]["id"] != initial_cycle_id
    assert after_approval["payout_cycle"]["qualifying_day_count"] == 0
    assert after_approval["payout_cycle"]["payouts_completed"] == 1

    update = client.put(
        f"/api/v1/prop-rules/{account.id}",
        json={
            "firm_name": "Lucid Trading",
            "profit_target": None,
            "max_loss": "2500",
            "qualifying_profit_days_required": 5,
            "minimum_profit_per_qualifying_day": "150",
            "minimum_payout": "500",
            "payout_profit_percentage": "50",
            "maximum_payout": "2000",
            "maximum_payout_count": 5,
            "profit_split_trader_percent": "90",
            "profit_split_firm_percent": "10",
            "payout_cycle_start_date": "2026-07-10",
            "payouts_completed": 1,
            "scaling_tiers": [
                {
                    "lower_profit_bound": "0",
                    "upper_profit_bound": "999.99",
                    "max_mini_contracts": 2,
                    "max_micro_contracts": 20,
                }
            ],
        },
    )
    assert update.status_code == 200, update.text
    versions = client.get(
        f"/api/v1/prop-rules/{account.id}/versions"
    ).json()
    assert len(versions) == 2
    assert versions[0]["rules"]["max_loss"] == "2500"
    assert versions[1]["rules"]["max_loss"] == "2000"
    db.close()


def test_manual_trade_is_labeled_audited_and_exportable() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    user = User(email="manual@journalme.local", display_name="Manual")
    db.add(user)
    db.flush()
    account = TradingAccount(user_id=user.id, name="Personal")
    db.add(account)
    db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    response = client.post(
        "/api/v1/manual-trades",
        json={
            "account_id": str(account.id),
            "symbol": "MESU6",
            "side": "long",
            "quantity": "1",
            "entry_timestamp": "2026-07-30T10:00:00-04:00",
            "exit_timestamp": "2026-07-30T10:05:00-04:00",
            "entry_price": "5000",
            "exit_price": "5001",
            "gross_pnl": "5.00",
            "fees": "1.00",
            "net_pnl": "4.00",
            "notes": "Manual regression record",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["source"] == "manual"
    assert db.scalar(select(AuditEvent)).action == "create"

    exported = client.get(
        "/api/v1/exports/trades.csv",
        params={"account_id": str(account.id)},
    )
    assert exported.status_code == 200
    assert "source" in exported.text
    assert "manual" in exported.text

    analytics_export = client.get(
        "/api/v1/exports/analytics.csv",
        params={"account_id": str(account.id), "symbol": "MES"},
    )
    assert analytics_export.status_code == 200
    assert "review_status" in analytics_export.text
    assert "MESU6" in analytics_export.text

    group = client.post(
        "/api/v1/account-groups",
        json={
            "name": "Personal accounts",
            "description": "Kept separate, reviewed together",
            "account_ids": [str(account.id)],
        },
    )
    assert group.status_code == 201
    assert group.json()["account_ids"] == [str(account.id)]

    adjustment = client.post(
        "/api/v1/manual-adjustments",
        json={
            "account_id": str(account.id),
            "adjustment_type": "deposit",
            "amount": "100.00",
            "effective_at": "2026-07-30T12:00:00-04:00",
            "reason": "Test deposit",
        },
    )
    assert adjustment.status_code == 201
    events = client.get(
        "/api/v1/audit-events",
        params={"account_id": str(account.id)},
    )
    assert events.status_code == 200
    assert events.json()["total"] == 2
    db.close()
