from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from uuid import UUID
from zoneinfo import ZoneInfo

from app.models import DailyJournal, Trade, TradingAccount

ZERO = Decimal("0")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _metrics(trades: list[Trade]) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0,
            "net_pnl": "0",
            "expectancy": None,
            "win_rate": None,
            "average_size": None,
        }
    net = sum((trade.net_pnl for trade in trades), ZERO)
    wins = sum(trade.net_pnl > 0 for trade in trades)
    avg_size = sum((trade.contract_quantity for trade in trades), ZERO) / len(trades)
    return {
        "trades": len(trades),
        "net_pnl": _decimal(net),
        "expectancy": _decimal(net / len(trades)),
        "win_rate": str(Decimal(wins * 100) / Decimal(len(trades))),
        "average_size": _decimal(avg_size),
    }


@dataclass(frozen=True)
class FeatureRow:
    trade: Trade
    account_id: UUID
    trade_number: int
    previous_pnl: Decimal | None
    minutes_since_previous: Decimal | None
    previous_quantity: Decimal | None


def _feature_rows(accounts: list[TradingAccount], trades: list[Trade]) -> list[FeatureRow]:
    account_map = {account.id: account for account in accounts}
    grouped: dict[UUID, list[Trade]] = defaultdict(list)
    for trade in trades:
        if trade.account_id in account_map:
            grouped[trade.account_id].append(trade)

    rows: list[FeatureRow] = []
    for account_id, account_trades in grouped.items():
        account = account_map[account_id]
        zone = ZoneInfo(account.timezone)
        account_trades.sort(key=lambda item: _utc(item.entry_timestamp))
        per_day: dict[str, int] = defaultdict(int)
        previous: Trade | None = None
        previous_day: str | None = None
        for trade in account_trades:
            local_day = _utc(trade.entry_timestamp).astimezone(zone).date().isoformat()
            if previous_day != local_day:
                previous = None
            per_day[local_day] += 1
            gap = None
            if previous is not None:
                seconds = (_utc(trade.entry_timestamp) - _utc(previous.exit_timestamp)).total_seconds()
                gap = Decimal(str(max(seconds, 0))) / Decimal("60")
            rows.append(
                FeatureRow(
                    trade=trade,
                    account_id=account_id,
                    trade_number=per_day[local_day],
                    previous_pnl=previous.net_pnl if previous is not None else None,
                    minutes_since_previous=gap,
                    previous_quantity=previous.contract_quantity if previous is not None else None,
                )
            )
            previous = trade
            previous_day = local_day
    return rows


def _group_metrics(rows: list[FeatureRow]) -> dict[str, Any]:
    return _metrics([row.trade for row in rows])


def _expectancy(rows: list[FeatureRow]) -> Decimal | None:
    if not rows:
        return None
    return sum((row.trade.net_pnl for row in rows), ZERO) / len(rows)


def _evidence(
    a: list[FeatureRow],
    b: list[FeatureRow],
    selector: Callable[[FeatureRow], bool],
    all_rows: list[FeatureRow],
) -> tuple[str, int, str]:
    min_n = min(len(a), len(b))
    if min_n < 5:
        return "insufficient", 0, "Too little data to treat this as a stable pattern."

    exp_a = _expectancy(a)
    exp_b = _expectancy(b)
    if exp_a is None or exp_b is None or exp_a == exp_b:
        return "early_signal", 25, "The samples are usable, but the observed difference is small."
    direction = 1 if exp_a > exp_b else -1

    by_account: dict[UUID, list[FeatureRow]] = defaultdict(list)
    for row in all_rows:
        by_account[row.account_id].append(row)
    comparable = 0
    aligned = 0
    for account_rows in by_account.values():
        aa = [row for row in account_rows if selector(row)]
        bb = [row for row in account_rows if not selector(row)]
        if len(aa) < 3 or len(bb) < 3:
            continue
        account_a = _expectancy(aa)
        account_b = _expectancy(bb)
        if account_a is None or account_b is None or account_a == account_b:
            continue
        comparable += 1
        if (1 if account_a > account_b else -1) == direction:
            aligned += 1
    stability = aligned / comparable if comparable else 0

    if min_n >= 20 and comparable >= 3 and stability >= 0.75:
        return (
            "strong_evidence",
            min(95, 70 + min(min_n, 50) // 2),
            f"The relationship has a substantial sample and points the same way in {aligned} of {comparable} comparable accounts.",
        )
    if min_n >= 10 and comparable >= 2 and stability >= 0.66:
        return (
            "repeated_pattern",
            min(80, 50 + min(min_n, 40)),
            f"The relationship repeats across {aligned} of {comparable} comparable accounts.",
        )
    return (
        "early_signal",
        min(55, 25 + min_n),
        "There is enough data to watch this relationship, but it needs more repetition before JournalMe treats it as stable.",
    )


def _comparison_insight(
    *,
    key: str,
    title_when_a_weaker: str,
    title_when_a_stronger: str,
    condition_a: str,
    condition_b: str,
    rows: list[FeatureRow],
    selector: Callable[[FeatureRow], bool],
) -> dict[str, Any] | None:
    a = [row for row in rows if selector(row)]
    b = [row for row in rows if not selector(row)]
    if not a or not b:
        return None
    exp_a = _expectancy(a)
    exp_b = _expectancy(b)
    if exp_a is None or exp_b is None:
        return None
    label, score, explanation = _evidence(a, b, selector, rows)
    diff = exp_a - exp_b
    title = title_when_a_stronger if diff > 0 else title_when_a_weaker
    return {
        "key": key,
        "title": title,
        "evidence": label,
        "evidence_score": score,
        "explanation": explanation,
        "difference_in_expectancy": _decimal(diff),
        "condition": {"label": condition_a, **_group_metrics(a)},
        "comparison": {"label": condition_b, **_group_metrics(b)},
    }




@dataclass(frozen=True)
class JournalDayRow:
    account_id: UUID
    pnl: Decimal
    rating: str | None
    focus_tags: tuple[str, ...]
    emotion_tags: tuple[str, ...]
    behavior_tags: tuple[str, ...]


def _journal_day_rows(
    accounts: list[TradingAccount],
    trades: list[Trade],
    journals: list[DailyJournal],
) -> list[JournalDayRow]:
    account_map = {account.id: account for account in accounts}
    daily_pnl: dict[tuple[UUID, str], Decimal] = defaultdict(lambda: ZERO)
    for trade in trades:
        account = account_map.get(trade.account_id)
        if account is None:
            continue
        zone = ZoneInfo(account.timezone)
        local_day = _utc(trade.entry_timestamp).astimezone(zone).date().isoformat()
        daily_pnl[(account.id, local_day)] += trade.net_pnl

    rows: list[JournalDayRow] = []
    for journal in journals:
        key = (journal.account_id, journal.trading_date.isoformat())
        if key not in daily_pnl:
            continue
        rows.append(
            JournalDayRow(
                account_id=journal.account_id,
                pnl=daily_pnl[key],
                rating=journal.quick_rating,
                focus_tags=tuple(journal.quick_focus_tags_json or []),
                emotion_tags=tuple(journal.quick_emotion_tags_json or []),
                behavior_tags=tuple(journal.quick_behavior_tags_json or []),
            )
        )
    return rows


def _journal_tag_insights(rows: list[JournalDayRow]) -> list[dict[str, Any]]:
    if len(rows) < 6:
        return []
    candidates: list[dict[str, Any]] = []
    categories = {
        "focus": lambda row: row.focus_tags,
        "emotion": lambda row: row.emotion_tags,
        "behavior": lambda row: row.behavior_tags,
    }
    for category, getter in categories.items():
        tags = sorted({tag for row in rows for tag in getter(row)})
        for tag in tags:
            with_tag = [row for row in rows if tag in getter(row)]
            without_tag = [row for row in rows if tag not in getter(row)]
            if len(with_tag) < 3 or len(without_tag) < 3:
                continue
            avg_with = sum((row.pnl for row in with_tag), ZERO) / len(with_tag)
            avg_without = sum((row.pnl for row in without_tag), ZERO) / len(without_tag)
            difference = avg_with - avg_without
            comparable_accounts = 0
            aligned_accounts = 0
            overall_direction = 1 if difference > 0 else -1 if difference < 0 else 0
            for account_id in {row.account_id for row in rows}:
                account_rows = [row for row in rows if row.account_id == account_id]
                aa = [row for row in account_rows if tag in getter(row)]
                bb = [row for row in account_rows if tag not in getter(row)]
                if len(aa) < 2 or len(bb) < 2:
                    continue
                account_diff = (
                    sum((row.pnl for row in aa), ZERO) / len(aa)
                    - sum((row.pnl for row in bb), ZERO) / len(bb)
                )
                if account_diff == 0 or overall_direction == 0:
                    continue
                comparable_accounts += 1
                if (1 if account_diff > 0 else -1) == overall_direction:
                    aligned_accounts += 1
            min_n = min(len(with_tag), len(without_tag))
            stability = aligned_accounts / comparable_accounts if comparable_accounts else 0
            if min_n >= 10 and comparable_accounts >= 2 and stability >= .75:
                evidence = "strong_evidence"
                score = min(92, 68 + min_n)
                explanation = f"This tag points the same way in {aligned_accounts} of {comparable_accounts} comparable accounts."
            elif min_n >= 5 and (comparable_accounts == 0 or stability >= .5):
                evidence = "repeated_pattern"
                score = min(72, 45 + min_n)
                explanation = "This relationship has repeated enough to track, but it should not be treated as causal."
            else:
                evidence = "early_signal"
                score = min(48, 25 + min_n)
                explanation = "There are enough reviewed days to notice the difference, but not enough to trust it yet."
            candidates.append(
                {
                    "key": f"{category}:{tag.lower().replace(' ', '_')}",
                    "category": category,
                    "tag": tag,
                    "title": f"Days tagged {tag} have {'higher' if difference > 0 else 'lower'} average P&L",
                    "evidence": evidence,
                    "evidence_score": score,
                    "explanation": explanation,
                    "difference_in_average_day_pnl": _decimal(difference),
                    "tagged": {
                        "days": len(with_tag),
                        "average_day_pnl": _decimal(avg_with),
                        "positive_day_rate": str(Decimal(sum(row.pnl > 0 for row in with_tag) * 100) / Decimal(len(with_tag))),
                    },
                    "other_reviewed_days": {
                        "days": len(without_tag),
                        "average_day_pnl": _decimal(avg_without),
                        "positive_day_rate": str(Decimal(sum(row.pnl > 0 for row in without_tag) * 100) / Decimal(len(without_tag))),
                    },
                }
            )
    candidates.sort(
        key=lambda item: (item["evidence_score"], abs(Decimal(item["difference_in_average_day_pnl"] or "0"))),
        reverse=True,
    )
    return candidates[:8]


def build_intelligence_overview(
    accounts: list[TradingAccount],
    trades: list[Trade],
    journals: list[DailyJournal],
    *,
    current_account_id: UUID | None = None,
) -> dict[str, Any]:
    account_map = {account.id: account for account in accounts}
    trades = [trade for trade in trades if trade.account_id in account_map]
    rows = _feature_rows(accounts, trades)

    journal_by_account: dict[UUID, list[DailyJournal]] = defaultdict(list)
    for journal in journals:
        if journal.account_id in account_map:
            journal_by_account[journal.account_id].append(journal)

    account_summaries: list[dict[str, Any]] = []
    total_trading_days: set[tuple[UUID, str]] = set()
    for account in accounts:
        account_trades = [trade for trade in trades if trade.account_id == account.id]
        zone = ZoneInfo(account.timezone)
        days = {
            _utc(trade.entry_timestamp).astimezone(zone).date().isoformat()
            for trade in account_trades
        }
        total_trading_days.update((account.id, day) for day in days)
        account_journals = journal_by_account[account.id]
        quick_days = sum(bool(item.quick_rating) for item in account_journals)
        mindset_days = sum(
            bool(item.pre_session_mindset or item.quick_emotion_tags_json)
            for item in account_journals
        )
        account_summaries.append(
            {
                "id": str(account.id),
                "name": account.name,
                "provider": account.provider,
                "account_type": account.account_type.value,
                "lifecycle_status": account.lifecycle_status.value,
                "active": account.active,
                "include_in_learning": account.include_in_learning,
                "metrics": _metrics(account_trades),
                "coverage": {
                    "trading_days": len(days),
                    "journal_days": len(account_journals),
                    "quick_review_days": quick_days,
                    "mindset_days": mindset_days,
                    "journal_percent": round(len(account_journals) / len(days) * 100, 1) if days else 0,
                },
            }
        )

    insights: list[dict[str, Any]] = []
    candidates = [
        _comparison_insight(
            key="trade_number",
            title_when_a_weaker="Your first three trades are weaker than later trades",
            title_when_a_stronger="Your first three trades outperform later trades",
            condition_a="Trades 1–3 of the day",
            condition_b="Trade 4+ of the day",
            rows=rows,
            selector=lambda row: row.trade_number <= 3,
        ),
        _comparison_insight(
            key="after_loss",
            title_when_a_weaker="Your next trade after a loss is weaker",
            title_when_a_stronger="Your next trade after a loss is stronger",
            condition_a="Immediately after a losing trade",
            condition_b="After a non-losing trade",
            rows=[row for row in rows if row.previous_pnl is not None],
            selector=lambda row: bool(row.previous_pnl is not None and row.previous_pnl < 0),
        ),
        _comparison_insight(
            key="rapid_reentry",
            title_when_a_weaker="Rapid re-entry is hurting expectancy",
            title_when_a_stronger="Rapid re-entry has historically helped expectancy",
            condition_a="Entered within 5 minutes of the prior exit",
            condition_b="Waited more than 5 minutes",
            rows=[row for row in rows if row.minutes_since_previous is not None],
            selector=lambda row: bool(row.minutes_since_previous is not None and row.minutes_since_previous <= 5),
        ),
        _comparison_insight(
            key="size_after_loss",
            title_when_a_weaker="Increasing size after a loss is a weak state",
            title_when_a_stronger="Increasing size after a loss has historically held up",
            condition_a="Size increased at least 25% after a loss",
            condition_b="Size held or reduced after a loss",
            rows=[row for row in rows if row.previous_pnl is not None and row.previous_pnl < 0 and row.previous_quantity is not None],
            selector=lambda row: bool(
                row.previous_quantity is not None
                and row.previous_quantity > 0
                and row.trade.contract_quantity >= row.previous_quantity * Decimal("1.25")
            ),
        ),
    ]
    insights.extend(item for item in candidates if item is not None)
    insights.sort(key=lambda item: item["evidence_score"], reverse=True)
    mindset_insights = _journal_tag_insights(_journal_day_rows(accounts, trades, journals))

    current_vs_history = None
    if current_account_id in account_map:
        current_trades = [trade for trade in trades if trade.account_id == current_account_id]
        history_trades = [trade for trade in trades if trade.account_id != current_account_id]
        current_vs_history = {
            "current_account_id": str(current_account_id),
            "current": _metrics(current_trades),
            "history": _metrics(history_trades),
        }

    journal_count = len(journals)
    quick_review_count = sum(bool(journal.quick_rating) for journal in journals)
    mindset_count = sum(
        bool(journal.pre_session_mindset or journal.quick_emotion_tags_json)
        for journal in journals
    )
    return {
        "selected_account_ids": [str(account.id) for account in accounts],
        "summary": _metrics(trades),
        "coverage": {
            "accounts": len(accounts),
            "trading_days": len(total_trading_days),
            "journal_days": journal_count,
            "quick_review_days": quick_review_count,
            "mindset_days": mindset_count,
            "psychology_scope": (
                "objective_plus_mindset"
                if mindset_count >= 5
                else "objective_plus_limited_journal"
                if journal_count
                else "objective_only"
            ),
        },
        "accounts": account_summaries,
        "current_vs_history": current_vs_history,
        "insights": insights,
        "mindset_insights": mindset_insights,
    }
