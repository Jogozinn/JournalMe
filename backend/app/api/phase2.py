from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.domain import TradeSide
from app.models import (
    AccountGroup,
    AccountGroupMember,
    Attachment,
    AuditEvent,
    CaptureEvent,
    DailyBalance,
    DailyJournal,
    Fill,
    Goal,
    ManualAdjustment,
    MonthlyReview,
    Order,
    Playbook,
    PlaybookChecklistItem,
    PropPayoutCycle,
    PropPayoutRecord,
    PropRuleProfile,
    RuleViolation,
    Tag,
    Trade,
    TradeChecklistResponse,
    TradeJournal,
    TradePlaybook,
    TradingAccount,
    TradingEpisode,
    User,
    UserPreference,
    WeeklyReview,
    utcnow,
)
from app.schemas import (
    AccountGroupCreate,
    ChecklistResponsesUpdate,
    ManualAdjustmentCreate,
    ManualAdjustmentUpdate,
    ManualDeleteRequest,
    ManualTradeCreate,
    ManualTradeUpdate,
    PeriodReviewUpdate,
    PlaybookCreate,
    PlaybookUpdate,
    PropPayoutCreate,
    PropPayoutUpdate,
    RuleViolationCreate,
    TradePlaybookUpdate,
    UserPreferenceUpdate,
)
from app.services.balance import resolve_account_balance, resolve_account_balances
from app.services.prop_rules import (
    calculate_prop_status,
    create_profile_version,
    ensure_open_cycle,
    latest_profile_version,
)
from app.services.review import day_review_status, review_rules, trade_review_statuses
from app.storage import get_storage_provider

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _account(db: Session, user: User, account_id: UUID) -> TradingAccount:
    account = db.scalar(
        select(TradingAccount).where(
            TradingAccount.id == account_id,
            TradingAccount.user_id == user.id,
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Trading account not found.")
    return account


def _trade(db: Session, user: User, trade_id: UUID) -> Trade:
    trade = db.scalar(
        select(Trade)
        .join(TradingAccount)
        .options(selectinload(Trade.tags), selectinload(Trade.journal))
        .where(Trade.id == trade_id, TradingAccount.user_id == user.id)
    )
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found.")
    return trade


def _playbook(db: Session, user: User, playbook_id: UUID) -> Playbook:
    playbook = db.scalar(
        select(Playbook)
        .options(selectinload(Playbook.checklist_items))
        .where(Playbook.id == playbook_id, Playbook.user_id == user.id)
    )
    if playbook is None:
        raise HTTPException(status_code=404, detail="Playbook not found.")
    return playbook


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    return value


def _model_dict(item: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    excluded = exclude or set()
    return {
        column.name: _json_value(getattr(item, column.name))
        for column in item.__table__.columns
        if column.name not in excluded
    }


def _trade_summary(trade: Trade, review: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": str(trade.id),
        "account_id": str(trade.account_id),
        "symbol": trade.symbol,
        "root_symbol": trade.root_symbol,
        "side": trade.side.value,
        "quantity": str(trade.contract_quantity),
        "entry_timestamp": _as_utc(trade.entry_timestamp).isoformat(),
        "exit_timestamp": _as_utc(trade.exit_timestamp).isoformat(),
        "gross_pnl": str(trade.gross_pnl),
        "fees": str(trade.fees) if trade.fees is not None else None,
        "net_pnl": str(trade.net_pnl),
        "source": trade.source_quality,
        "grade": trade.journal.trade_grade if trade.journal else None,
        "followed_plan": trade.journal.followed_plan if trade.journal else None,
        "tags": [
            {"id": str(tag.id), "name": tag.name, "category": tag.category.value}
            for tag in trade.tags
        ],
        "review": review,
    }


def _period_bounds(account: TradingAccount, start: date, end: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo(account.timezone)
    return (
        datetime.combine(start, time.min, tzinfo=zone).astimezone(timezone.utc),
        datetime.combine(end, time.max, tzinfo=zone).astimezone(timezone.utc),
    )


def _period_metrics(trades: list[Trade], account: TradingAccount) -> dict[str, Any]:
    net = sum((item.net_pnl for item in trades), Decimal("0"))
    fees_known = all(item.fees is not None for item in trades)
    fees = sum((item.fees or Decimal("0") for item in trades), Decimal("0"))
    winners = [item.net_pnl for item in trades if item.net_pnl > 0]
    losers = [item.net_pnl for item in trades if item.net_pnl < 0]
    gross_wins = sum(winners, Decimal("0"))
    gross_losses = abs(sum(losers, Decimal("0")))
    by_day: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
    zone = ZoneInfo(account.timezone)
    for item in trades:
        by_day[_as_utc(item.entry_timestamp).astimezone(zone).date()] += item.net_pnl
    return {
        "net_pnl": str(net),
        "fees": str(fees) if fees_known else None,
        "trade_count": len(trades),
        "win_rate": str(Decimal(len(winners)) / len(trades) * 100) if trades else None,
        "profit_factor": str(gross_wins / gross_losses) if gross_losses else None,
        "expectancy": str(net / len(trades)) if trades else None,
        "average_winner": str(gross_wins / len(winners)) if winners else None,
        "average_loser": (
            str(sum(losers, Decimal("0")) / len(losers)) if losers else None
        ),
        "average_win_loss_ratio": (
            str(
                (gross_wins / len(winners))
                / abs(sum(losers, Decimal("0")) / len(losers))
            )
            if winners and losers
            else None
        ),
        "largest_gain": str(max(winners)) if winners else None,
        "largest_loss": str(min(losers)) if losers else None,
        "total_trades": len(trades),
        "best_trade": (
            _trade_summary(max(trades, key=lambda item: item.net_pnl)) if trades else None
        ),
        "worst_trade": (
            _trade_summary(min(trades, key=lambda item: item.net_pnl)) if trades else None
        ),
        "best_day": (
            {"date": max(by_day, key=by_day.get).isoformat(), "net_pnl": str(max(by_day.values()))}
            if by_day
            else None
        ),
        "worst_day": (
            {"date": min(by_day, key=by_day.get).isoformat(), "net_pnl": str(min(by_day.values()))}
            if by_day
            else None
        ),
    }


def _audit(
    db: Session,
    user: User,
    account_id: UUID,
    entity_type: str,
    entity_id: UUID,
    action: str,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            user_id=user.id,
            account_id=account_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
            before_json=before,
            after_json=after,
            reason=reason,
        )
    )


def _playbook_dict(item: Playbook, *, analytics: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        **_model_dict(item),
        "checklist_items": [_model_dict(row) for row in item.checklist_items],
        "analytics": analytics,
    }


@router.get("/playbooks")
def list_playbooks(
    db: Db,
    user: CurrentUser,
    active: bool | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(Playbook)
        .options(selectinload(Playbook.checklist_items))
        .where(Playbook.user_id == user.id)
        .order_by(Playbook.active.desc(), Playbook.name)
    )
    if active is not None:
        statement = statement.where(Playbook.active.is_(active))
    return [_playbook_dict(item) for item in db.scalars(statement).all()]


def _replace_checklist(
    db: Session, playbook: Playbook, payload: PlaybookCreate | PlaybookUpdate
) -> None:
    existing = {item.id: item for item in playbook.checklist_items}
    retained: set[UUID] = set()
    for order, input_item in enumerate(payload.checklist_items):
        item = existing.get(input_item.id) if input_item.id else None
        if item is None:
            item = PlaybookChecklistItem(playbook_id=playbook.id)
            db.add(item)
        else:
            retained.add(item.id)
        item.text = input_item.text
        item.category = input_item.category
        item.required = input_item.required
        item.sort_order = input_item.sort_order if input_item.sort_order else order
    for item_id, item in existing.items():
        if item_id not in retained:
            db.delete(item)


@router.post("/playbooks", status_code=status.HTTP_201_CREATED)
def create_playbook(payload: PlaybookCreate, db: Db, user: CurrentUser) -> dict[str, Any]:
    fields = payload.model_dump(exclude={"checklist_items"})
    item = Playbook(user_id=user.id, **fields)
    db.add(item)
    db.flush()
    _replace_checklist(db, item, payload)
    db.commit()
    return _playbook_dict(_playbook(db, user, item.id))


@router.get("/playbooks/{playbook_id}")
def playbook_detail(playbook_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    item = _playbook(db, user, playbook_id)
    trades = db.scalars(
        select(Trade)
        .join(TradePlaybook)
        .options(selectinload(Trade.tags), selectinload(Trade.journal))
        .where(TradePlaybook.playbook_id == item.id)
        .order_by(Trade.entry_timestamp.desc())
    ).all()
    statuses = trade_review_statuses(db, user.id, trades)
    metrics = _period_metrics(
        trades,
        db.scalar(
            select(TradingAccount)
            .join(Trade)
            .join(TradePlaybook)
            .where(TradePlaybook.playbook_id == item.id)
            .limit(1)
        )
        if trades
        else TradingAccount(timezone="America/New_York"),
    )
    required = [check for check in item.checklist_items if check.required]
    adherence_values = [
        statuses[trade.id]["adherence_percent"]
        for trade in trades
        if statuses[trade.id]["adherence_percent"] is not None
    ]
    metrics["adherence_percent"] = (
        round(sum(adherence_values) / len(adherence_values)) if adherence_values else None
    )
    metrics["required_checklist_items"] = len(required)
    return {
        **_playbook_dict(item, analytics=metrics),
        "linked_trades": [
            _trade_summary(trade, statuses[trade.id]) for trade in trades[:100]
        ],
        "sample_size_warning": (
            "Small sample; treat this as descriptive, not statistically proven."
            if len(trades) < 20
            else None
        ),
    }


@router.put("/playbooks/{playbook_id}")
def update_playbook(
    playbook_id: UUID,
    payload: PlaybookUpdate,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    item = _playbook(db, user, playbook_id)
    for key, value in payload.model_dump(exclude={"checklist_items"}).items():
        setattr(item, key, value)
    _replace_checklist(db, item, payload)
    db.commit()
    return _playbook_dict(_playbook(db, user, item.id))


@router.delete("/playbooks/{playbook_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_playbook(playbook_id: UUID, db: Db, user: CurrentUser) -> None:
    item = _playbook(db, user, playbook_id)
    item.active = False
    db.commit()


@router.get("/trades/{trade_id}/playbooks")
def get_trade_playbooks(trade_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    trade = _trade(db, user, trade_id)
    links = db.scalars(
        select(TradePlaybook)
        .options(selectinload(TradePlaybook.playbook).selectinload(Playbook.checklist_items))
        .where(TradePlaybook.trade_id == trade.id)
    ).all()
    responses = db.scalars(
        select(TradeChecklistResponse).where(TradeChecklistResponse.trade_id == trade.id)
    ).all()
    violations = db.scalars(
        select(RuleViolation).where(RuleViolation.trade_id == trade.id)
    ).all()
    status_payload = trade_review_statuses(db, user.id, [trade])[trade.id]
    return {
        "assignments": [
            {**_playbook_dict(link.playbook), "is_primary": link.is_primary} for link in links
        ],
        "responses": [_model_dict(item) for item in responses],
        "violations": [_model_dict(item) for item in violations],
        "review": status_payload,
    }


@router.put("/trades/{trade_id}/playbooks")
def assign_trade_playbooks(
    trade_id: UUID,
    payload: TradePlaybookUpdate,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    trade = _trade(db, user, trade_id)
    ids = set(payload.secondary_playbook_ids)
    if payload.primary_playbook_id:
        ids.add(payload.primary_playbook_id)
    if ids:
        owned = set(
            db.scalars(
                select(Playbook.id).where(Playbook.user_id == user.id, Playbook.id.in_(ids))
            ).all()
        )
        if owned != ids:
            raise HTTPException(status_code=422, detail="One or more playbooks are unavailable.")
    db.execute(delete(TradePlaybook).where(TradePlaybook.trade_id == trade.id))
    for playbook_id in ids:
        db.add(
            TradePlaybook(
                trade_id=trade.id,
                playbook_id=playbook_id,
                is_primary=playbook_id == payload.primary_playbook_id,
            )
        )
    db.commit()
    return get_trade_playbooks(trade_id, db, user)


@router.put("/trades/{trade_id}/checklist")
def save_checklist(
    trade_id: UUID,
    payload: ChecklistResponsesUpdate,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    trade = _trade(db, user, trade_id)
    assigned_ids = set(
        db.scalars(
            select(PlaybookChecklistItem.id)
            .join(TradePlaybook, TradePlaybook.playbook_id == PlaybookChecklistItem.playbook_id)
            .where(TradePlaybook.trade_id == trade.id)
        ).all()
    )
    for response in payload.responses:
        if response.checklist_item_id not in assigned_ids:
            raise HTTPException(
                status_code=422,
                detail="Checklist item is not assigned to this trade.",
            )
        row = db.get(
            TradeChecklistResponse,
            (trade.id, response.checklist_item_id),
        )
        if row is None:
            row = TradeChecklistResponse(
                trade_id=trade.id,
                checklist_item_id=response.checklist_item_id,
            )
            db.add(row)
        row.passed = response.passed
        row.note = response.note
    db.commit()
    return get_trade_playbooks(trade_id, db, user)


@router.post("/trades/{trade_id}/violations", status_code=status.HTTP_201_CREATED)
def create_violation(
    trade_id: UUID,
    payload: RuleViolationCreate,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    trade = _trade(db, user, trade_id)
    if payload.playbook_id:
        _playbook(db, user, payload.playbook_id)
    item = RuleViolation(trade_id=trade.id, **payload.model_dump())
    db.add(item)
    db.commit()
    return _model_dict(item)


@router.delete("/trades/{trade_id}/violations/{violation_id}", status_code=204)
def delete_violation(
    trade_id: UUID, violation_id: UUID, db: Db, user: CurrentUser
) -> None:
    trade = _trade(db, user, trade_id)
    item = db.scalar(
        select(RuleViolation).where(
            RuleViolation.id == violation_id,
            RuleViolation.trade_id == trade.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Rule violation not found.")
    db.delete(item)
    db.commit()


@router.get("/review-queue")
def review_queue(
    account_id: UUID,
    db: Db,
    user: CurrentUser,
    review_status: str | None = Query(default=None, pattern="^(unreviewed|partial|complete)$"),
    symbol: str | None = None,
    start: date | None = None,
    end: date | None = None,
    missing_playbook: bool = False,
    missing_tags: bool = False,
    missing_screenshot: bool = False,
    low_grade: bool = False,
    plan_violations: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    account = _account(db, user, account_id)
    statement = (
        select(Trade)
        .options(selectinload(Trade.tags), selectinload(Trade.journal))
        .where(Trade.account_id == account.id)
        .order_by(Trade.entry_timestamp)
    )
    if start or end:
        start_at, end_at = _period_bounds(
            account,
            start or date.min,
            end or date.max,
        )
        statement = statement.where(
            Trade.entry_timestamp >= start_at,
            Trade.entry_timestamp <= end_at,
        )
    if symbol:
        statement = statement.where(Trade.symbol.ilike(f"%{symbol.strip()}%"))
    trades = list(db.scalars(statement).all())
    statuses = trade_review_statuses(db, user.id, trades)
    violation_ids = set(
        db.scalars(
            select(RuleViolation.trade_id).where(
                RuleViolation.trade_id.in_([item.id for item in trades])
            )
        ).all()
    ) if trades else set()
    filtered = []
    for item in trades:
        review = statuses[item.id]
        if review_status and review["status"] != review_status:
            continue
        if missing_playbook and review["primary_playbook_id"] is not None:
            continue
        if missing_tags and item.tags:
            continue
        if missing_screenshot and review["has_screenshot"]:
            continue
        if low_grade and (not item.journal or item.journal.trade_grade not in {"C", "D", "F"}):
            continue
        if plan_violations and item.id not in violation_ids:
            continue
        filtered.append(item)
    counts = {
        key: sum(payload["status"] == key for payload in statuses.values())
        for key in ("unreviewed", "partial", "complete")
    }
    offset = (page - 1) * page_size
    return {
        "items": [
            _trade_summary(item, statuses[item.id])
            for item in filtered[offset : offset + page_size]
        ],
        "total": len(filtered),
        "page": page,
        "counts": counts,
        "completion_percent": (
            round(counts["complete"] / len(statuses) * 100) if statuses else 0
        ),
    }


@router.get("/review-summary")
def review_summary(account_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    account = _account(db, user, account_id)
    trades = list(
        db.scalars(
            select(Trade)
            .options(selectinload(Trade.tags), selectinload(Trade.journal))
            .where(Trade.account_id == account.id)
            .order_by(Trade.entry_timestamp)
        ).all()
    )
    statuses = trade_review_statuses(db, user.id, trades)
    counts = {
        key: sum(payload["status"] == key for payload in statuses.values())
        for key in ("unreviewed", "partial", "complete")
    }
    zone = ZoneInfo(account.timezone)
    by_day: dict[date, list[Trade]] = defaultdict(list)
    for item in trades:
        by_day[_as_utc(item.entry_timestamp).astimezone(zone).date()].append(item)
    journals = {
        item.trading_date: item
        for item in db.scalars(
            select(DailyJournal).where(DailyJournal.account_id == account.id)
        ).all()
    }
    rules = review_rules(db, user.id)
    day_statuses = {
        day: day_review_status(
            journals.get(day),
            [statuses[item.id] for item in day_trades],
            rules,
        )
        for day, day_trades in by_day.items()
    }
    completed_days = sorted(
        [day for day, payload in day_statuses.items() if payload["status"] == "complete"],
        reverse=True,
    )
    streak = 0
    for day in completed_days:
        if streak == 0:
            streak = 1
            previous = day
        elif (previous - day).days <= 3:
            streak += 1
            previous = day
        else:
            break
    return {
        "trade_counts": counts,
        "trades_awaiting_review": counts["unreviewed"] + counts["partial"],
        "days_awaiting_recap": sum(
            payload["status"] != "complete" for payload in day_statuses.values()
        ),
        "review_streak": streak,
        "completion_percent": (
            round(counts["complete"] / len(trades) * 100) if trades else 0
        ),
    }


@router.get("/trading-days")
def trading_days(
    account_id: UUID,
    db: Db,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=31, ge=1, le=366),
) -> dict[str, Any]:
    account = _account(db, user, account_id)
    trades = list(
        db.scalars(
            select(Trade)
            .options(selectinload(Trade.tags), selectinload(Trade.journal))
            .where(Trade.account_id == account.id)
            .order_by(Trade.entry_timestamp.desc())
        ).all()
    )
    statuses = trade_review_statuses(db, user.id, trades)
    zone = ZoneInfo(account.timezone)
    grouped: dict[date, list[Trade]] = defaultdict(list)
    for item in trades:
        grouped[_as_utc(item.entry_timestamp).astimezone(zone).date()].append(item)
    journals = {
        item.trading_date: item
        for item in db.scalars(
            select(DailyJournal).where(DailyJournal.account_id == account.id)
        ).all()
    }
    all_dates = sorted(set(grouped) | set(journals), reverse=True)
    rules = review_rules(db, user.id)
    rows = []
    for day in all_dates:
        day_trades = grouped.get(day, [])
        net = sum((item.net_pnl for item in day_trades), Decimal("0"))
        rows.append(
            {
                "date": day.isoformat(),
                "net_pnl": str(net),
                "trade_count": len(day_trades),
                "review": day_review_status(
                    journals.get(day),
                    [statuses[item.id] for item in day_trades],
                    rules,
                ),
                "day_grade": journals[day].day_grade if day in journals else None,
            }
        )
    offset = (page - 1) * page_size
    return {"items": rows[offset : offset + page_size], "total": len(rows), "page": page}


def _period_review_payload(
    db: Session,
    user: User,
    account: TradingAccount,
    start: date,
    end: date,
    review: WeeklyReview | MonthlyReview | None,
) -> dict[str, Any]:
    start_at, end_at = _period_bounds(account, start, end)
    trades = list(
        db.scalars(
            select(Trade)
            .options(selectinload(Trade.tags), selectinload(Trade.journal))
            .where(
                Trade.account_id == account.id,
                Trade.entry_timestamp >= start_at,
                Trade.entry_timestamp <= end_at,
            )
            .order_by(Trade.entry_timestamp)
        ).all()
    )
    statuses = trade_review_statuses(db, user.id, trades)
    completed = sum(item["status"] == "complete" for item in statuses.values())
    metrics = _period_metrics(trades, account)
    metrics["journal_completion_percent"] = (
        round(completed / len(trades) * 100) if trades else 0
    )
    playbook_counts = db.execute(
        select(Playbook.name, func.count())
        .join(TradePlaybook, TradePlaybook.playbook_id == Playbook.id)
        .join(Trade, Trade.id == TradePlaybook.trade_id)
        .where(
            Trade.account_id == account.id,
            Trade.entry_timestamp >= start_at,
            Trade.entry_timestamp <= end_at,
            TradePlaybook.is_primary.is_(True),
        )
        .group_by(Playbook.name)
        .order_by(func.count().desc())
    ).all()
    metrics["most_used_playbook"] = (
        {"name": playbook_counts[0][0], "trades": playbook_counts[0][1]}
        if playbook_counts
        else None
    )
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "metrics": metrics,
        "review": _model_dict(review) if review else None,
    }


@router.get("/reviews/weekly/{week_start}")
def get_weekly_review(
    week_start: date, account_id: UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    account = _account(db, user, account_id)
    normalized = week_start - timedelta(days=week_start.weekday())
    item = db.scalar(
        select(WeeklyReview).where(
            WeeklyReview.account_id == account.id,
            WeeklyReview.week_start == normalized,
        )
    )
    return _period_review_payload(
        db, user, account, normalized, normalized + timedelta(days=6), item
    )


@router.put("/reviews/weekly/{week_start}")
def save_weekly_review(
    week_start: date,
    payload: PeriodReviewUpdate,
    account_id: UUID,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    account = _account(db, user, account_id)
    normalized = week_start - timedelta(days=week_start.weekday())
    item = db.scalar(
        select(WeeklyReview).where(
            WeeklyReview.account_id == account.id,
            WeeklyReview.week_start == normalized,
        )
    )
    if item is None:
        item = WeeklyReview(account_id=account.id, week_start=normalized)
        db.add(item)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    return get_weekly_review(normalized, account.id, db, user)


@router.get("/reviews/monthly/{month_start}")
def get_monthly_review(
    month_start: date, account_id: UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    account = _account(db, user, account_id)
    normalized = month_start.replace(day=1)
    next_month = (normalized.replace(day=28) + timedelta(days=4)).replace(day=1)
    item = db.scalar(
        select(MonthlyReview).where(
            MonthlyReview.account_id == account.id,
            MonthlyReview.month_start == normalized,
        )
    )
    return _period_review_payload(
        db, user, account, normalized, next_month - timedelta(days=1), item
    )


@router.put("/reviews/monthly/{month_start}")
def save_monthly_review(
    month_start: date,
    payload: PeriodReviewUpdate,
    account_id: UUID,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    account = _account(db, user, account_id)
    normalized = month_start.replace(day=1)
    item = db.scalar(
        select(MonthlyReview).where(
            MonthlyReview.account_id == account.id,
            MonthlyReview.month_start == normalized,
        )
    )
    if item is None:
        item = MonthlyReview(account_id=account.id, month_start=normalized)
        db.add(item)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    return get_monthly_review(normalized, account.id, db, user)


@router.get("/account-groups")
def list_account_groups(db: Db, user: CurrentUser) -> list[dict[str, Any]]:
    groups = db.scalars(
        select(AccountGroup)
        .options(selectinload(AccountGroup.members))
        .where(AccountGroup.user_id == user.id)
        .order_by(AccountGroup.name)
    ).all()
    return [
        {
            **_model_dict(item),
            "account_ids": [str(member.account_id) for member in item.members],
        }
        for item in groups
    ]


@router.post("/account-groups", status_code=status.HTTP_201_CREATED)
def create_account_group(
    payload: AccountGroupCreate, db: Db, user: CurrentUser
) -> dict[str, Any]:
    owned = set(
        db.scalars(
            select(TradingAccount.id).where(
                TradingAccount.user_id == user.id,
                TradingAccount.id.in_(payload.account_ids),
            )
        ).all()
    )
    if owned != set(payload.account_ids):
        raise HTTPException(status_code=422, detail="One or more accounts are unavailable.")
    item = AccountGroup(
        user_id=user.id,
        name=payload.name,
        description=payload.description,
    )
    db.add(item)
    db.flush()
    item.members = [
        AccountGroupMember(group_id=item.id, account_id=account_id)
        for account_id in payload.account_ids
    ]
    db.commit()
    return {
        **_model_dict(item),
        "account_ids": [str(member.account_id) for member in item.members],
    }


@router.put("/account-groups/{group_id}")
def update_account_group(
    group_id: UUID,
    payload: AccountGroupCreate,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    item = db.scalar(
        select(AccountGroup)
        .options(selectinload(AccountGroup.members))
        .where(AccountGroup.id == group_id, AccountGroup.user_id == user.id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Account group not found.")
    for account_id in payload.account_ids:
        _account(db, user, account_id)
    item.name = payload.name
    item.description = payload.description
    item.members = [
        AccountGroupMember(group_id=item.id, account_id=account_id)
        for account_id in payload.account_ids
    ]
    db.commit()
    return {
        **_model_dict(item),
        "account_ids": [str(member.account_id) for member in item.members],
    }


@router.delete("/account-groups/{group_id}", status_code=204)
def delete_account_group(group_id: UUID, db: Db, user: CurrentUser) -> None:
    item = db.scalar(
        select(AccountGroup).where(
            AccountGroup.id == group_id,
            AccountGroup.user_id == user.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Account group not found.")
    db.delete(item)
    db.commit()


@router.get("/preferences")
def get_preferences(db: Db, user: CurrentUser) -> dict[str, Any]:
    item = db.get(UserPreference, user.id)
    if item is None:
        item = UserPreference(user_id=user.id)
        db.add(item)
        db.commit()
    return _model_dict(item)


@router.put("/preferences")
def update_preferences(
    payload: UserPreferenceUpdate, db: Db, user: CurrentUser
) -> dict[str, Any]:
    item = db.get(UserPreference, user.id)
    if item is None:
        item = UserPreference(user_id=user.id)
        db.add(item)
    updates = payload.model_dump(exclude_unset=True)
    if "default_account_id" in updates and updates["default_account_id"]:
        _account(db, user, updates["default_account_id"])
    for key, value in updates.items():
        setattr(item, key, value)
    db.commit()
    return _model_dict(item)


@router.post("/manual-trades", status_code=status.HTTP_201_CREATED)
def create_manual_trade(
    payload: ManualTradeCreate, db: Db, user: CurrentUser
) -> dict[str, Any]:
    account = _account(db, user, payload.account_id)
    if payload.primary_playbook_id:
        _playbook(db, user, payload.primary_playbook_id)
    tags = list(
        db.scalars(
            select(Tag).where(Tag.user_id == user.id, Tag.id.in_(payload.tag_ids))
        ).all()
    )
    token = uuid4()
    trade = Trade(
        account_id=account.id,
        duplicate_fingerprint=hashlib.sha256(f"manual:{token}".encode()).hexdigest(),
        symbol=payload.symbol.strip().upper(),
        root_symbol=payload.root_symbol.strip().upper() if payload.root_symbol else None,
        contract_quantity=payload.quantity,
        side=TradeSide(payload.side),
        entry_price=payload.entry_price,
        exit_price=payload.exit_price,
        gross_pnl=payload.gross_pnl,
        fees=payload.fees,
        net_pnl=payload.net_pnl,
        currency=account.currency,
        entry_timestamp=payload.entry_timestamp.astimezone(timezone.utc),
        exit_timestamp=payload.exit_timestamp.astimezone(timezone.utc),
        duration_seconds=int((payload.exit_timestamp - payload.entry_timestamp).total_seconds()),
        source_quality="manual",
        reconciliation_status="manual",
        source_payload={"source": "manual", "created_by": "user"},
        tags=tags,
    )
    db.add(trade)
    db.flush()
    if payload.notes:
        db.add(TradeJournal(trade_id=trade.id, custom_notes=payload.notes))
    if payload.primary_playbook_id:
        db.add(
            TradePlaybook(
                trade_id=trade.id,
                playbook_id=payload.primary_playbook_id,
                is_primary=True,
            )
        )
    after = _model_dict(trade)
    _audit(
        db,
        user,
        account.id,
        "trade",
        trade.id,
        "create",
        after=after,
        reason="Manual trade entry",
    )
    db.commit()
    return _trade_summary(_trade(db, user, trade.id))


@router.patch("/manual-trades/{trade_id}")
def update_manual_trade(
    trade_id: UUID,
    payload: ManualTradeUpdate,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    trade = _trade(db, user, trade_id)
    if trade.source_quality != "manual":
        raise HTTPException(status_code=409, detail="Imported trades cannot be manually edited.")
    before = _model_dict(trade)
    updates = payload.model_dump(exclude_unset=True, exclude={"notes", "reason"})
    if "side" in updates:
        updates["side"] = TradeSide(updates["side"])
    if "quantity" in updates:
        updates["contract_quantity"] = updates.pop("quantity")
    for key, value in updates.items():
        if isinstance(value, datetime):
            value = value.astimezone(timezone.utc)
        setattr(trade, key, value)
    if "entry_timestamp" in updates or "exit_timestamp" in updates:
        trade.duration_seconds = int(
            (_as_utc(trade.exit_timestamp) - _as_utc(trade.entry_timestamp)).total_seconds()
        )
    if payload.notes is not None:
        journal = trade.journal or TradeJournal(trade_id=trade.id)
        journal.custom_notes = payload.notes
        if trade.journal is None:
            db.add(journal)
    after = _model_dict(trade)
    _audit(
        db,
        user,
        trade.account_id,
        "trade",
        trade.id,
        "update",
        before=before,
        after=after,
        reason=payload.reason,
    )
    db.commit()
    return _trade_summary(_trade(db, user, trade.id))


@router.delete("/manual-trades/{trade_id}", status_code=204)
def delete_manual_trade(
    trade_id: UUID,
    payload: ManualDeleteRequest,
    db: Db,
    user: CurrentUser,
) -> None:
    trade = _trade(db, user, trade_id)
    if trade.source_quality != "manual":
        raise HTTPException(status_code=409, detail="Imported trades cannot be deleted here.")
    if payload.confirmation != "DELETE MANUAL TRADE":
        raise HTTPException(status_code=422, detail="Type DELETE MANUAL TRADE to confirm.")
    before = _model_dict(trade)
    _audit(
        db,
        user,
        trade.account_id,
        "trade",
        trade.id,
        "delete",
        before=before,
        reason=payload.reason,
    )
    db.delete(trade)
    db.commit()


@router.get("/manual-adjustments")
def list_manual_adjustments(
    account_id: UUID, db: Db, user: CurrentUser
) -> list[dict[str, Any]]:
    account = _account(db, user, account_id)
    return [
        _model_dict(item)
        for item in db.scalars(
            select(ManualAdjustment)
            .where(ManualAdjustment.account_id == account.id)
            .order_by(ManualAdjustment.effective_at.desc())
        ).all()
    ]


@router.post("/manual-adjustments", status_code=status.HTTP_201_CREATED)
def create_manual_adjustment(
    payload: ManualAdjustmentCreate, db: Db, user: CurrentUser
) -> dict[str, Any]:
    account = _account(db, user, payload.account_id)
    item = ManualAdjustment(
        account_id=account.id,
        adjustment_type=payload.adjustment_type,
        amount=payload.amount,
        effective_at=payload.effective_at.astimezone(timezone.utc),
        reason=payload.reason,
        status=payload.status,
        approved_at=utcnow() if payload.status == "approved" else None,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        user,
        account.id,
        "manual_adjustment",
        item.id,
        "create",
        after=_model_dict(item),
        reason=item.reason,
    )
    db.commit()
    return _model_dict(item)


@router.patch("/manual-adjustments/{adjustment_id}")
def update_manual_adjustment(
    adjustment_id: UUID,
    payload: ManualAdjustmentUpdate,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    item = db.scalar(
        select(ManualAdjustment)
        .join(TradingAccount)
        .where(
            ManualAdjustment.id == adjustment_id,
            TradingAccount.user_id == user.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Manual adjustment not found.")
    if item.status == "approved" and payload.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="Approved adjustments cannot be reversed; add a correcting adjustment.",
        )
    before = _model_dict(item)
    item.status = payload.status
    item.approved_at = utcnow() if payload.status == "approved" else None
    _audit(
        db,
        user,
        item.account_id,
        "manual_adjustment",
        item.id,
        "approval",
        before=before,
        after=_model_dict(item),
        reason=payload.reason,
    )
    db.commit()
    return _model_dict(item)


@router.get("/audit-events")
def audit_events(
    db: Db,
    user: CurrentUser,
    account_id: UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    statement = (
        select(AuditEvent)
        .where(AuditEvent.user_id == user.id)
        .order_by(AuditEvent.created_at.desc())
    )
    if account_id:
        _account(db, user, account_id)
        statement = statement.where(AuditEvent.account_id == account_id)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(statement.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_model_dict(item) for item in rows], "total": total, "page": page}


@router.get("/data-quality")
def data_quality(account_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    account = _account(db, user, account_id)
    balance = resolve_account_balance(db, account)
    missing_commissions = db.scalar(
        select(func.count())
        .select_from(Fill)
        .where(Fill.account_id == account.id, Fill.commission.is_(None))
    ) or 0
    unmatched_fills = db.scalar(
        select(func.count())
        .select_from(Fill)
        .where(Fill.account_id == account.id, Fill.trade_id.is_(None))
    ) or 0
    filled_order_ids = set(
        db.scalars(
            select(Order.external_order_id).where(
                Order.account_id == account.id,
                Order.status == "filled",
            )
        ).all()
    )
    linked_order_ids = set(
        db.scalars(
            select(Fill.external_order_id).where(
                Fill.account_id == account.id,
                Fill.external_order_id.is_not(None),
            )
        ).all()
    )
    warnings = list(
        db.scalars(
            select(Trade)
            .options(selectinload(Trade.tags), selectinload(Trade.journal))
            .where(
                Trade.account_id == account.id,
                Trade.reconciliation_status != "reconciled",
            )
        ).all()
    )
    return {
        "unmatched_fills": unmatched_fills,
        "unmatched_filled_orders": len(filled_order_ids - linked_order_ids),
        "canceled_orders_retained": db.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.account_id == account.id, Order.status != "filled")
        )
        or 0,
        "missing_commissions": missing_commissions,
        "reconciliation_warnings": [_trade_summary(item) for item in warnings],
        "imported_balance": balance.as_dict()["imported_balance"],
        "calculated_balance": balance.as_dict()["calculated_balance"],
        "balance_difference": balance.as_dict()["reconciliation_difference"],
        "balance_resolution": balance.as_dict(),
    }


def _prop_context(
    db: Session,
    account: TradingAccount,
    profile: PropRuleProfile,
) -> tuple[Any, PropPayoutCycle]:
    version = latest_profile_version(db, profile.id)
    if version is None:
        version = create_profile_version(db, profile, [])
    earliest = db.scalar(
        select(func.min(Trade.entry_timestamp)).where(Trade.account_id == account.id)
    )
    fallback_start = (
        _as_utc(earliest).astimezone(ZoneInfo(account.timezone)).date()
        if earliest
        else date.today()
    )
    cycle = ensure_open_cycle(db, account, profile, version, fallback_start)
    return version, cycle


def _calculate_account_prop_status(
    db: Session,
    account: TradingAccount,
    profile: PropRuleProfile,
) -> dict[str, Any]:
    version, cycle = _prop_context(db, account, profile)
    trades = list(
        db.scalars(
            select(Trade)
            .where(Trade.account_id == account.id)
            .order_by(Trade.entry_timestamp)
        ).all()
    )
    balances = list(
        db.scalars(
            select(DailyBalance)
            .where(DailyBalance.account_id == account.id)
            .order_by(DailyBalance.trade_date)
        ).all()
    )
    adjustments = list(
        db.scalars(
            select(ManualAdjustment)
            .where(
                ManualAdjustment.account_id == account.id,
                ManualAdjustment.status == "approved",
            )
            .order_by(ManualAdjustment.effective_at)
        ).all()
    )
    payouts = list(
        db.scalars(
            select(PropPayoutRecord)
            .where(PropPayoutRecord.account_id == account.id)
            .order_by(PropPayoutRecord.request_date)
        ).all()
    )
    balance = resolve_account_balance(db, account)
    hard_breach = bool(
        db.scalar(
            select(func.count())
            .select_from(RuleViolation)
            .join(Trade, Trade.id == RuleViolation.trade_id)
            .where(
                Trade.account_id == account.id,
                func.lower(RuleViolation.severity).in_(["hard", "critical"]),
            )
        )
    )
    return calculate_prop_status(
        account,
        profile,
        trades,
        balances,
        adjustments,
        cycle,
        version,
        payouts,
        balance,
        hard_breach,
    )


@router.get("/prop-rules/{account_id}/status")
def prop_status(account_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any] | None:
    account = _account(db, user, account_id)
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account.id)
    )
    if profile is None or not profile.enabled:
        return None
    payload = _calculate_account_prop_status(db, account, profile)
    db.commit()
    return payload


@router.get("/prop-rules/{account_id}/payouts")
def list_prop_payouts(
    account_id: UUID, db: Db, user: CurrentUser
) -> list[dict[str, Any]]:
    account = _account(db, user, account_id)
    return [
        _model_dict(item)
        for item in db.scalars(
            select(PropPayoutRecord)
            .where(PropPayoutRecord.account_id == account.id)
            .order_by(
                PropPayoutRecord.request_date.desc(),
                PropPayoutRecord.created_at.desc(),
            )
        ).all()
    ]


@router.post("/prop-rules/{account_id}/payouts", status_code=201)
def create_prop_payout(
    account_id: UUID,
    payload: PropPayoutCreate,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    account = _account(db, user, account_id)
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account.id)
    )
    if profile is None or not profile.enabled:
        raise HTTPException(status_code=422, detail="Enable prop rules first.")
    status_payload = _calculate_account_prop_status(db, account, profile)
    payout = status_payload["payout_cycle"]
    requestable = payout["requestable_payout"]
    if requestable is None:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "This payout cycle is not currently eligible.",
                "reasons": payout["ineligibility_reasons"],
            },
        )
    if payload.requested_amount > Decimal(requestable):
        raise HTTPException(
            status_code=422,
            detail=(
                f"requested_amount cannot exceed the available payout of "
                f"{requestable}."
            ),
        )
    _, cycle = _prop_context(db, account, profile)
    item = PropPayoutRecord(
        cycle_id=cycle.id,
        account_id=account.id,
        request_date=payload.request_date,
        requested_amount=payload.requested_amount,
        status="pending",
        notes=payload.notes,
    )
    db.add(item)
    db.flush()
    _audit(
        db,
        user,
        account.id,
        "prop_payout",
        item.id,
        "create",
        after=_model_dict(item),
        reason=payload.notes,
    )
    db.commit()
    return _model_dict(item)


@router.patch("/prop-rules/{account_id}/payouts/{payout_id}")
def update_prop_payout(
    account_id: UUID,
    payout_id: UUID,
    payload: PropPayoutUpdate,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    account = _account(db, user, account_id)
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account.id)
    )
    item = db.scalar(
        select(PropPayoutRecord).where(
            PropPayoutRecord.id == payout_id,
            PropPayoutRecord.account_id == account.id,
        )
    )
    if profile is None or item is None:
        raise HTTPException(status_code=404, detail="Payout record not found.")
    if item.status == "approved" and payload.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="An approved payout cannot be reopened or rejected.",
        )
    before = _model_dict(item)
    if payload.status == "approved" and item.status != "approved":
        status_payload = _calculate_account_prop_status(db, account, profile)
        available_text = status_payload["payout_cycle"]["gross_available_payout"]
        if (
            not status_payload["payout_cycle"]["eligible_for_payout"]
            or available_text is None
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "This payout cycle is not eligible for approval.",
                    "reasons": status_payload["payout_cycle"][
                        "ineligibility_reasons"
                    ],
                },
            )
        available = Decimal(available_text)
        gross = payload.approved_gross_amount or item.requested_amount
        if gross > available:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"approved_gross_amount cannot exceed the available payout "
                    f"of {available_text}."
                ),
            )
        if profile.minimum_payout is not None and gross < profile.minimum_payout:
            raise HTTPException(
                status_code=422,
                detail=f"approved_gross_amount must be at least {profile.minimum_payout}.",
            )
        trader_percent = profile.profit_split_trader_percent or Decimal("100")
        trader_amount = (
            gross * trader_percent / Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        item.approved_date = payload.approved_date or date.today()
        item.approved_gross_amount = gross
        item.trader_amount = trader_amount
        item.firm_amount = gross - trader_amount
        cycle = db.get(PropPayoutCycle, item.cycle_id)
        if cycle is None or cycle.status != "open":
            raise HTTPException(status_code=409, detail="Payout cycle is already closed.")
        cycle.status = "closed"
        cycle.end_date = item.approved_date
        cycle.closed_at = utcnow()
        profile.payouts_completed = (profile.payouts_completed or 0) + 1
        profile.qualifying_days_since_last_payout = 0
        profile.payout_cycle_start_date = item.approved_date
        version = latest_profile_version(db, profile.id)
        if version is None:
            version = create_profile_version(db, profile, [])
        db.add(
            PropPayoutCycle(
                account_id=account.id,
                profile_version_id=version.id,
                start_date=item.approved_date,
                status="open",
            )
        )
    item.status = payload.status
    if payload.notes is not None:
        item.notes = payload.notes
    _audit(
        db,
        user,
        account.id,
        "prop_payout",
        item.id,
        "update",
        before=before,
        after=_model_dict(item),
        reason=payload.reason,
    )
    db.commit()
    return _model_dict(item)


@router.delete(
    "/prop-rules/{account_id}/payouts/{payout_id}",
    status_code=204,
)
def delete_prop_payout(
    account_id: UUID,
    payout_id: UUID,
    payload: ManualDeleteRequest,
    db: Db,
    user: CurrentUser,
) -> None:
    account = _account(db, user, account_id)
    item = db.scalar(
        select(PropPayoutRecord).where(
            PropPayoutRecord.id == payout_id,
            PropPayoutRecord.account_id == account.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Payout record not found.")
    if payload.confirmation != "DELETE PAYOUT":
        raise HTTPException(
            status_code=422,
            detail="Type DELETE PAYOUT to confirm.",
        )
    if item.status == "approved":
        raise HTTPException(
            status_code=409,
            detail="Approved payouts cannot be deleted because they close a cycle.",
        )
    before = _model_dict(item)
    _audit(
        db,
        user,
        account.id,
        "prop_payout",
        item.id,
        "delete",
        before=before,
        reason=payload.reason,
    )
    db.delete(item)
    db.commit()


@router.get("/analytics/advanced")
def advanced_analytics(
    account_id: UUID,
    db: Db,
    user: CurrentUser,
    start: date | None = None,
    end: date | None = None,
    symbol: str | None = None,
    side: str | None = Query(default=None, pattern="^(long|short)$"),
    reviewed_status: str | None = Query(
        default=None, pattern="^(unreviewed|partial|complete)$"
    ),
) -> dict[str, Any]:
    account = _account(db, user, account_id)
    statement = (
        select(Trade)
        .options(selectinload(Trade.tags), selectinload(Trade.journal))
        .where(Trade.account_id == account.id)
        .order_by(Trade.entry_timestamp)
    )
    if start or end:
        start_at, end_at = _period_bounds(account, start or date.min, end or date.max)
        statement = statement.where(
            Trade.entry_timestamp >= start_at,
            Trade.entry_timestamp <= end_at,
        )
    if symbol:
        statement = statement.where(Trade.symbol.ilike(f"%{symbol.strip()}%"))
    if side:
        statement = statement.where(Trade.side == TradeSide(side))
    trades = list(db.scalars(statement).all())
    statuses = trade_review_statuses(db, user.id, trades)
    if reviewed_status:
        trades = [item for item in trades if statuses[item.id]["status"] == reviewed_status]
    metrics = _period_metrics(trades, account)
    running = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    curve = []
    winning_streak = losing_streak = max_winning = max_losing = 0
    for item in trades:
        running += item.net_pnl
        peak = max(peak, running)
        max_drawdown = min(max_drawdown, running - peak)
        curve.append(
            {
                "at": _as_utc(item.exit_timestamp).isoformat(),
                "net_pnl": str(running),
                "drawdown": str(running - peak),
            }
        )
        if item.net_pnl > 0:
            winning_streak += 1
            losing_streak = 0
        elif item.net_pnl < 0:
            losing_streak += 1
            winning_streak = 0
        max_winning = max(max_winning, winning_streak)
        max_losing = max(max_losing, losing_streak)
    metrics.update(
        {
            "max_drawdown": str(max_drawdown),
            "average_duration_seconds": (
                round(
                    sum(item.duration_seconds or 0 for item in trades)
                    / sum(item.duration_seconds is not None for item in trades)
                )
                if any(item.duration_seconds is not None for item in trades)
                else None
            ),
            "winning_streak": max_winning,
            "losing_streak": max_losing,
            "total_fees": str(
                sum((item.fees or Decimal("0") for item in trades), Decimal("0"))
            ),
            "fees_percent_of_gross": (
                str(
                    sum((item.fees or Decimal("0") for item in trades), Decimal("0"))
                    / abs(sum((item.gross_pnl for item in trades), Decimal("0")))
                    * 100
                )
                if sum((item.gross_pnl for item in trades), Decimal("0")) != 0
                else None
            ),
        }
    )
    zone = ZoneInfo(account.timezone)

    def groups(key) -> list[dict[str, Any]]:
        grouped: dict[str, list[Trade]] = defaultdict(list)
        for row in trades:
            grouped[str(key(row))].append(row)
        return [
            {"label": label, **_period_metrics(rows, account)}
            for label, rows in sorted(grouped.items())
        ]

    return {
        "metrics": metrics,
        "equity_and_drawdown": curve,
        "by_symbol": groups(lambda item: item.symbol),
        "by_root_symbol": groups(lambda item: item.root_symbol or item.symbol),
        "by_weekday": groups(
            lambda item: _as_utc(item.entry_timestamp).astimezone(zone).strftime("%A")
        ),
        "by_hour": groups(
            lambda item: _as_utc(item.entry_timestamp).astimezone(zone).strftime("%H:00")
        ),
        "by_side": groups(lambda item: item.side.value),
        "by_grade": groups(
            lambda item: item.journal.trade_grade if item.journal else "Unreviewed"
        ),
        "by_review_status": groups(lambda item: statuses[item.id]["status"]),
        "filters": {
            "account_id": str(account.id),
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "symbol": symbol,
            "side": side,
            "reviewed_status": reviewed_status,
            "timezone": account.timezone,
        },
    }


def _csv_response(filename: str, rows: list[dict[str, Any]]) -> StreamingResponse:
    buffer = io.StringIO(newline="")
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    content = io.BytesIO(buffer.getvalue().encode("utf-8-sig"))
    return StreamingResponse(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exports/trades.csv")
def export_trades_csv(account_id: UUID, db: Db, user: CurrentUser) -> StreamingResponse:
    account = _account(db, user, account_id)
    balance = resolve_account_balance(db, account)
    trades = db.scalars(
        select(Trade)
        .where(Trade.account_id == account.id)
        .order_by(Trade.entry_timestamp)
    ).all()
    rows = [
        {
            "id": str(item.id),
            "symbol": item.symbol,
            "side": item.side.value,
            "quantity": str(item.contract_quantity),
            "entry_timestamp_utc": _as_utc(item.entry_timestamp).isoformat(),
            "exit_timestamp_utc": _as_utc(item.exit_timestamp).isoformat(),
            "entry_price": str(item.entry_price),
            "exit_price": str(item.exit_price),
            "gross_pnl": str(item.gross_pnl),
            "fees": str(item.fees) if item.fees is not None else "",
            "net_pnl": str(item.net_pnl),
            "source": item.source_quality,
            "resolved_current_balance": (
                str(balance.resolved_current_balance)
                if balance.resolved_current_balance is not None
                else ""
            ),
        }
        for item in trades
    ]
    return _csv_response(f"journalme-{account.name}-trades.csv", rows)


@router.get("/exports/analytics.csv")
def export_analytics_csv(
    account_id: UUID,
    db: Db,
    user: CurrentUser,
    start: date | None = None,
    end: date | None = None,
    symbol: str | None = None,
    side: str | None = Query(default=None, pattern="^(long|short)$"),
    reviewed_status: str | None = Query(
        default=None, pattern="^(unreviewed|partial|complete)$"
    ),
) -> StreamingResponse:
    account = _account(db, user, account_id)
    balance = resolve_account_balance(db, account)
    statement = (
        select(Trade)
        .options(selectinload(Trade.journal))
        .where(Trade.account_id == account.id)
        .order_by(Trade.entry_timestamp)
    )
    if start or end:
        start_at, end_at = _period_bounds(account, start or date.min, end or date.max)
        statement = statement.where(
            Trade.entry_timestamp >= start_at,
            Trade.entry_timestamp <= end_at,
        )
    if symbol:
        statement = statement.where(Trade.symbol.ilike(f"%{symbol.strip()}%"))
    if side:
        statement = statement.where(Trade.side == TradeSide(side))
    trades = list(db.scalars(statement).all())
    statuses = trade_review_statuses(db, user.id, trades)
    if reviewed_status:
        trades = [
            item
            for item in trades
            if statuses[item.id]["status"] == reviewed_status
        ]
    rows = [
        {
            "date": _as_utc(item.entry_timestamp)
            .astimezone(ZoneInfo(account.timezone))
            .date()
            .isoformat(),
            "symbol": item.symbol,
            "root_symbol": item.root_symbol or "",
            "side": item.side.value,
            "quantity": str(item.contract_quantity),
            "gross_pnl": str(item.gross_pnl),
            "fees": str(item.fees) if item.fees is not None else "",
            "net_pnl": str(item.net_pnl),
            "duration_seconds": item.duration_seconds or "",
            "review_status": statuses[item.id]["status"],
            "grade": item.journal.trade_grade if item.journal else "",
            "followed_plan": (
                item.journal.followed_plan
                if item.journal and item.journal.followed_plan is not None
                else ""
            ),
            "source": item.source_quality,
            "resolved_current_balance": (
                str(balance.resolved_current_balance)
                if balance.resolved_current_balance is not None
                else ""
            ),
        }
        for item in trades
    ]
    return _csv_response("journalme-filtered-analytics.csv", rows)


@router.get("/exports/journals.json")
def export_journals(account_id: UUID, db: Db, user: CurrentUser) -> Response:
    account = _account(db, user, account_id)
    balance = resolve_account_balance(db, account)
    trade_journals = db.scalars(
        select(TradeJournal)
        .join(Trade)
        .where(Trade.account_id == account.id)
        .order_by(Trade.entry_timestamp)
    ).all()
    daily = db.scalars(
        select(DailyJournal)
        .where(DailyJournal.account_id == account.id)
        .order_by(DailyJournal.trading_date)
    ).all()
    payload = {
        "export_schema_version": 1,
        "generated_at": utcnow().isoformat(),
        "account_id": str(account.id),
        "balance_resolution": balance.as_dict(),
        "trade_journals": [_model_dict(item) for item in trade_journals],
        "daily_journals": [_model_dict(item) for item in daily],
    }
    return Response(
        content=json.dumps(payload, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="journalme-{account.name}-journals.json"'
        },
    )


@router.get("/exports/archive.zip")
def export_archive(db: Db, user: CurrentUser) -> StreamingResponse:
    accounts = list(
        db.scalars(
            select(TradingAccount).where(TradingAccount.user_id == user.id)
        ).all()
    )
    account_balances = resolve_account_balances(db, accounts)
    account_ids = [item.id for item in accounts]
    trades = list(
        db.scalars(select(Trade).where(Trade.account_id.in_(account_ids))).all()
    ) if account_ids else []
    trade_ids = [item.id for item in trades]
    tables: dict[str, list[Any]] = {
        "accounts": accounts,
        "trades": trades,
        "trade_journals": list(
            db.scalars(select(TradeJournal).where(TradeJournal.trade_id.in_(trade_ids))).all()
        ) if trade_ids else [],
        "daily_journals": list(
            db.scalars(select(DailyJournal).where(DailyJournal.account_id.in_(account_ids))).all()
        ) if account_ids else [],
        "playbooks": list(
            db.scalars(select(Playbook).where(Playbook.user_id == user.id)).all()
        ),
        "weekly_reviews": list(
            db.scalars(select(WeeklyReview).where(WeeklyReview.account_id.in_(account_ids))).all()
        ) if account_ids else [],
        "monthly_reviews": list(
            db.scalars(select(MonthlyReview).where(MonthlyReview.account_id.in_(account_ids))).all()
        ) if account_ids else [],
        "goals": list(
            db.scalars(select(Goal).where(Goal.account_id.in_(account_ids))).all()
        ) if account_ids else [],
        "manual_adjustments": list(
            db.scalars(
                select(ManualAdjustment).where(ManualAdjustment.account_id.in_(account_ids))
            ).all()
        ) if account_ids else [],
        "audit_events": list(
            db.scalars(select(AuditEvent).where(AuditEvent.user_id == user.id)).all()
        ),
        "trading_episodes": list(
            db.scalars(select(TradingEpisode).where(TradingEpisode.user_id == user.id)).all()
        ),
        "capture_events": list(
            db.scalars(select(CaptureEvent).where(CaptureEvent.user_id == user.id)).all()
        ),
    }
    attachments = list(
        db.scalars(
            select(Attachment).where(
                (Attachment.trade_id.in_(trade_ids) if trade_ids else False)
                | (Attachment.daily_journal_id.in_(
                    select(DailyJournal.id).where(DailyJournal.account_id.in_(account_ids))
                ) if account_ids else False)
                | Attachment.playbook_id.in_(
                    select(Playbook.id).where(Playbook.user_id == user.id)
                )
            )
        ).all()
    )
    archive = io.BytesIO()
    storage = get_storage_provider(get_settings())
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "manifest.json",
            json.dumps(
                {
                    "product": "JournalMe",
                    "export_schema_version": 1,
                    "generated_at": utcnow().isoformat(),
                    "user_id": str(user.id),
                },
                indent=2,
            ),
        )
        for name, values in tables.items():
            bundle.writestr(
                f"data/{name}.json",
                json.dumps([_model_dict(item) for item in values], indent=2),
            )
        bundle.writestr(
            "data/account_balances.json",
            json.dumps(
                [
                    {
                        "account_id": str(account.id),
                        **account_balances[account.id].as_dict(),
                    }
                    for account in accounts
                ],
                indent=2,
            ),
        )
        for item in attachments:
            safe_name = Path(item.original_filename).name
            try:
                bundle.writestr(
                    f"attachments/{item.id}-{safe_name}",
                    storage.get(item.storage_key),
                )
            except FileNotFoundError:
                continue
        bundle.writestr(
            "data/attachments.json",
            json.dumps([_model_dict(item) for item in attachments], indent=2),
        )
        capture_events = tables["capture_events"]
        for item in capture_events:
            if not item.screenshot_storage_key:
                continue
            safe_name = Path(item.screenshot_original_filename or "capture.png").name
            try:
                bundle.writestr(
                    f"companion/{item.id}-{safe_name}",
                    storage.get(item.screenshot_storage_key),
                )
            except FileNotFoundError:
                continue
    archive.seek(0)
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="journalme-full-backup.zip"'
        },
    )


@router.get("/exports/waverr-research.zip")
def export_waverr_research_pack(
    account_id: UUID,
    db: Db,
    user: CurrentUser,
) -> StreamingResponse:
    """Export time-aligned Companion episodes for WaveRR research.

    Live observations are kept distinct from post-outcome data so downstream
    research can avoid hindsight leakage. This is a research export only; it
    does not modify WaveRR or any production trading behavior.
    """
    account = _account(db, user, account_id)
    episodes = list(
        db.scalars(
            select(TradingEpisode)
            .where(
                TradingEpisode.user_id == user.id,
                TradingEpisode.account_id == account.id,
            )
            .order_by(TradingEpisode.started_at.asc())
        ).all()
    )
    storage = get_storage_provider(get_settings())
    archive = io.BytesIO()
    episode_index: list[dict[str, Any]] = []
    legacy_captures = list(
        db.scalars(
            select(CaptureEvent)
            .where(
                CaptureEvent.user_id == user.id,
                CaptureEvent.account_id == account.id,
                CaptureEvent.episode_id.is_(None),
            )
            .order_by(CaptureEvent.captured_at.asc())
        ).all()
    )

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for episode in episodes:
            moments = list(
                db.scalars(
                    select(CaptureEvent)
                    .where(CaptureEvent.episode_id == episode.id)
                    .order_by(CaptureEvent.captured_at.asc(), CaptureEvent.created_at.asc())
                ).all()
            )
            folder = f"episodes/{episode.id}"
            moment_payloads: list[dict[str, Any]] = []
            for position, moment in enumerate(moments, start=1):
                payload = _model_dict(
                    moment,
                    exclude={"screenshot_storage_key", "screenshot_original_filename", "screenshot_mime"},
                )
                payload["knowledge_stage"] = "decision_time" if moment.recorded_live else "retrospective_addition"
                payload["sequence"] = position
                payload["has_screenshot"] = bool(moment.screenshot_storage_key)
                payload["screenshot_path"] = None
                if moment.screenshot_storage_key:
                    original = Path(moment.screenshot_original_filename or "capture.png")
                    suffix = original.suffix.lower() if original.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
                    phase = (moment.phase or moment.event_type or "moment").replace("/", "-")
                    screenshot_path = f"{folder}/screenshots/{position:03d}_{phase}_{moment.id}{suffix}"
                    try:
                        bundle.writestr(screenshot_path, storage.get(moment.screenshot_storage_key))
                        payload["screenshot_path"] = screenshot_path
                    except FileNotFoundError:
                        payload["screenshot_missing"] = True
                moment_payloads.append(payload)

            trade = db.get(Trade, episode.matched_trade_id) if episode.matched_trade_id else None
            fills: list[Fill] = []
            orders: list[Order] = []
            trade_payload: dict[str, Any] | None = None
            review_payload: dict[str, Any] | None = None
            if trade is not None and trade.account_id == account.id:
                fills = list(
                    db.scalars(
                        select(Fill)
                        .where(Fill.trade_id == trade.id)
                        .order_by(Fill.timestamp.asc())
                    ).all()
                )
                external_order_ids = {fill.external_order_id for fill in fills if fill.external_order_id}
                if external_order_ids:
                    orders = list(
                        db.scalars(
                            select(Order)
                            .where(
                                Order.account_id == account.id,
                                Order.external_order_id.in_(external_order_ids),
                            )
                            .order_by(Order.submitted_timestamp.asc())
                        ).all()
                    )
                trade_payload = _model_dict(trade)
                trade_payload["knowledge_stage"] = "outcome"
                trade_payload["tags"] = [
                    {"id": str(tag.id), "name": tag.name, "category": tag.category.value}
                    for tag in trade.tags
                ]
                journal = db.get(TradeJournal, trade.id)
                if journal is not None:
                    review_payload = _model_dict(journal)
                    review_payload["knowledge_stage"] = "post_outcome_review"

            local_date = _as_utc(episode.started_at).astimezone(ZoneInfo(account.timezone)).date()
            daily_journal = db.scalar(
                select(DailyJournal).where(
                    DailyJournal.account_id == account.id,
                    DailyJournal.trading_date == local_date,
                )
            )
            daily_payload = _model_dict(daily_journal) if daily_journal is not None else None
            if daily_payload is not None:
                daily_payload["knowledge_stage"] = "mixed_session_context_and_review"

            episode_payload = _model_dict(episode)
            episode_payload.update(
                {
                    "knowledge_model": {
                        "decision_time": "recorded_live moments and their screenshots; safe as contemporaneous human evidence",
                        "retrospective_addition": "added later; do not feed backward into entry-time evaluation without an explicit hindsight flag",
                        "outcome": "trade/fill/order results known after execution",
                        "post_outcome_review": "review/reflection written with outcome knowledge",
                    },
                    "moment_count": len(moment_payloads),
                    "matched_trade_id": str(trade.id) if trade is not None else None,
                }
            )
            bundle.writestr(f"{folder}/episode.json", json.dumps(episode_payload, indent=2))
            bundle.writestr(
                f"{folder}/moments.jsonl",
                "".join(json.dumps(item) + "\n" for item in moment_payloads),
            )
            if trade_payload is not None:
                bundle.writestr(f"{folder}/trade.json", json.dumps(trade_payload, indent=2))
                bundle.writestr(f"{folder}/fills.json", json.dumps([_model_dict(item) for item in fills], indent=2))
                bundle.writestr(f"{folder}/orders.json", json.dumps([_model_dict(item) for item in orders], indent=2))
            if review_payload is not None:
                bundle.writestr(f"{folder}/review.json", json.dumps(review_payload, indent=2))
            if daily_payload is not None:
                bundle.writestr(f"{folder}/daily_journal.json", json.dumps(daily_payload, indent=2))

            episode_index.append(
                {
                    "episode_id": str(episode.id),
                    "status": episode.status,
                    "symbol": episode.symbol,
                    "side": episode.side,
                    "started_at": _as_utc(episode.started_at).isoformat(),
                    "ended_at": _as_utc(episode.ended_at).isoformat() if episode.ended_at else None,
                    "moment_count": len(moment_payloads),
                    "screenshot_count": sum(1 for item in moment_payloads if item.get("screenshot_path")),
                    "matched_trade_id": str(trade.id) if trade is not None else None,
                    "folder": folder,
                }
            )

        # Preserve pre-timeline Companion history too. These records are
        # intentionally not mutated into database episodes; the export labels
        # them as legacy single moments and keeps any trade match for grouping.
        legacy_index: list[dict[str, Any]] = []
        for capture in legacy_captures:
            folder = f"legacy_captures/{capture.id}"
            payload = _model_dict(
                capture,
                exclude={"screenshot_storage_key", "screenshot_original_filename", "screenshot_mime"},
            )
            payload["knowledge_stage"] = "legacy_timing_unverified"
            payload["legacy_single_moment"] = True
            payload["has_screenshot"] = bool(capture.screenshot_storage_key)
            payload["screenshot_path"] = None
            if capture.screenshot_storage_key:
                original = Path(capture.screenshot_original_filename or "capture.png")
                suffix = original.suffix.lower() if original.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
                screenshot_path = f"{folder}/screenshot{suffix}"
                try:
                    bundle.writestr(screenshot_path, storage.get(capture.screenshot_storage_key))
                    payload["screenshot_path"] = screenshot_path
                except FileNotFoundError:
                    payload["screenshot_missing"] = True
            bundle.writestr(f"{folder}/moment.json", json.dumps(payload, indent=2))
            legacy_index.append(
                {
                    "capture_id": str(capture.id),
                    "captured_at": _as_utc(capture.captured_at).isoformat(),
                    "symbol": capture.symbol,
                    "event_type": capture.event_type,
                    "matched_trade_id": str(capture.matched_trade_id) if capture.matched_trade_id else None,
                    "folder": folder,
                }
            )

        manifest = {
            "product": "JournalMe",
            "export_type": "waverr_research_pack",
            "schema_version": 1,
            "generated_at": utcnow().isoformat(),
            "account": {
                "id": str(account.id),
                "name": account.name,
                "provider": account.provider,
                "timezone": account.timezone,
                "currency": account.currency,
            },
            "research_contract": {
                "purpose": "Time-aligned human trading observations for WaveRR research and hypothesis generation.",
                "production_change": "None. Importing this pack must not directly alter live/canary production behavior.",
                "hindsight_rule": "Respect knowledge_stage and recorded_live. Outcome/review data must not be treated as information available at decision time.",
                "episode_definition": "An observation timeline that may contain one or many moments and may or may not have a trade.",
            },
            "episodes": episode_index,
            "legacy_captures": legacy_index,
            "legacy_capture_count": len(legacy_index),
        }
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        bundle.writestr(
            "README.txt",
            "JournalMe -> WaveRR Research Pack\n\n"
            "Each episode preserves chronological human observations, optional screenshots, and any matched canonical trade evidence.\n"
            "Pre-timeline Companion captures are included under legacy_captures so existing research data is not lost.\n"
            "Use recorded_live/knowledge_stage to prevent hindsight leakage. A WAIT/no-trade episode is valid research data.\n"
            "This package is for research only and should flow through WaveRR hypothesis/testing/governance before any production change.\n",
        )

    archive.seek(0)
    safe_account = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in account.name).strip("-") or "account"
    filename = f"journalme-waverr-research-{safe_account}.zip"
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/backup-status")
def backup_status(db: Db, user: CurrentUser) -> dict[str, Any]:
    settings = get_settings()
    account_count = db.scalar(
        select(func.count())
        .select_from(TradingAccount)
        .where(TradingAccount.user_id == user.id)
    ) or 0
    database_location = (
        "local SQLite database"
        if settings.data_provider == "local"
        else "managed database"
    )
    return {
        "mode": settings.data_provider,
        "database_location": database_location,
        "attachment_location": f"{settings.storage_provider} private storage",
        "account_count": account_count,
        "export_schema_version": 1,
        "status": "ready",
        "recommendation": "Back up the database and attachment directory together.",
    }
