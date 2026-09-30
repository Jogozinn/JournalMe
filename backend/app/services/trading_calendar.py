from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fill, Trade, TradingAccount

# CME equity index futures reopen at 18:00 Eastern for the next trade date.
# JournalMe keeps this configurable at the service boundary so a future account
# or instrument-specific session calendar can replace the fallback without
# changing API consumers.
DEFAULT_TRADING_DAY_ROLLOVER_HOUR = 18


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calendar_date_for_timestamp(value: datetime, timezone_name: str) -> date:
    zone = ZoneInfo(timezone_name)
    return _as_utc(value).astimezone(zone).date()


def fallback_trading_date_for_timestamp(
    value: datetime,
    timezone_name: str,
    *,
    rollover_hour: int = DEFAULT_TRADING_DAY_ROLLOVER_HOUR,
) -> date:
    local = _as_utc(value).astimezone(ZoneInfo(timezone_name))
    day = local.date()
    if local.hour >= rollover_hour:
        day += timedelta(days=1)
    return day


def fill_trade_date_map(db: Session, trade_ids: Iterable[UUID]) -> dict[UUID, date]:
    ids = list(dict.fromkeys(trade_ids))
    if not ids:
        return {}
    rows = db.execute(
        select(Fill.trade_id, Fill.trade_date)
        .where(Fill.trade_id.in_(ids), Fill.trade_id.is_not(None))
        .order_by(Fill.timestamp.asc())
    ).all()
    # The first linked fill's broker trade date is authoritative for the
    # flat-to-flat lifecycle. A properly reconciled lifecycle should not span
    # broker trade dates; choosing the first keeps behavior deterministic if
    # historical data is imperfect.
    result: dict[UUID, date] = {}
    for trade_id, trade_date in rows:
        if trade_id is not None and trade_id not in result:
            result[trade_id] = trade_date
    return result


def trade_day_for_trade(
    trade: Trade,
    account: TradingAccount,
    *,
    mode: str = "trading",
    fill_dates: dict[UUID, date] | None = None,
) -> date:
    if mode == "calendar":
        return calendar_date_for_timestamp(trade.entry_timestamp, account.timezone)
    if mode != "trading":
        raise ValueError(f"Unsupported date mode: {mode}")
    if fill_dates and trade.id in fill_dates:
        return fill_dates[trade.id]
    return fallback_trading_date_for_timestamp(trade.entry_timestamp, account.timezone)


def group_trades_by_day(
    db: Session,
    account: TradingAccount,
    trades: Iterable[Trade],
    *,
    mode: str = "trading",
) -> dict[date, list[Trade]]:
    items = list(trades)
    fill_dates = fill_trade_date_map(db, [item.id for item in items]) if mode == "trading" else {}
    grouped: dict[date, list[Trade]] = defaultdict(list)
    for item in items:
        grouped[trade_day_for_trade(item, account, mode=mode, fill_dates=fill_dates)].append(item)
    return dict(grouped)


def current_day_for_account(account: TradingAccount, *, mode: str = "trading") -> date:
    now = datetime.now(timezone.utc)
    if mode == "calendar":
        return calendar_date_for_timestamp(now, account.timezone)
    return fallback_trading_date_for_timestamp(now, account.timezone)
