from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Attachment, CaptureEvent, Trade, TradingAccount, utcnow
from app.storage import get_storage_provider

MATCH_METHOD = "symbol_time_v1"
AUTO_MATCH_THRESHOLD = 0.82
SUGGEST_THRESHOLD = 0.65
MIN_AUTO_MARGIN = 0.12
ENTRY_EXIT_WINDOW_SECONDS = 600
UPDATE_WINDOW_SECONDS = 300

_FUTURES_MONTH_CODES = "FGHJKMNQUVXZ"


@dataclass(frozen=True)
class MatchCandidate:
    trade: Trade
    score: float
    seconds_from_target: float


@dataclass(frozen=True)
class MatchResult:
    status: str
    trade_id: UUID | None
    score: float | None
    candidate_count: int
    margin: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "trade_id": str(self.trade_id) if self.trade_id else None,
            "score": round(self.score, 6) if self.score is not None else None,
            "candidate_count": self.candidate_count,
            "margin": round(self.margin, 6) if self.margin is not None else None,
        }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_symbol(value: str | None) -> str | None:
    """Normalize chart/broker futures symbols to a stable root for matching.

    Examples:
    - CME_MINI:MNQ1! -> MNQ
    - MNQU6 -> MNQ
    - NQ1! -> NQ
    """
    if not value:
        return None
    symbol = value.strip().upper().split(":")[-1]
    symbol = re.sub(r"[^A-Z0-9!]", "", symbol)
    symbol = re.sub(r"\d+!$", "", symbol)
    symbol = re.sub(rf"[{_FUTURES_MONTH_CODES}]\d{{1,2}}$", "", symbol)
    return symbol or None


def _time_score(capture: CaptureEvent, trade: Trade) -> tuple[float, float] | None:
    captured = _as_utc(capture.captured_at)
    entry = _as_utc(trade.entry_timestamp)
    exit_ = _as_utc(trade.exit_timestamp)

    if capture.event_type == "entry":
        delta = abs((captured - entry).total_seconds())
    elif capture.event_type == "exit":
        delta = abs((captured - exit_).total_seconds())
    elif capture.event_type == "update":
        if entry <= captured <= exit_:
            return 0.35, 0.0
        delta = min(abs((captured - entry).total_seconds()), abs((captured - exit_).total_seconds()))
        if delta > UPDATE_WINDOW_SECONDS:
            return None
        if delta <= 30:
            return 0.28, delta
        if delta <= 60:
            return 0.24, delta
        if delta <= 180:
            return 0.18, delta
        return 0.12, delta
    else:
        return None

    if delta > ENTRY_EXIT_WINDOW_SECONDS:
        return None
    if delta <= 15:
        return 0.35, delta
    if delta <= 60:
        return 0.32, delta
    if delta <= 180:
        return 0.25, delta
    if delta <= 300:
        return 0.16, delta
    return 0.08, delta


def _candidate_query(db: Session, capture: CaptureEvent, user_id: UUID) -> list[Trade]:
    captured = _as_utc(capture.captured_at)
    if capture.event_type == "entry":
        start = captured - timedelta(seconds=ENTRY_EXIT_WINDOW_SECONDS)
        end = captured + timedelta(seconds=ENTRY_EXIT_WINDOW_SECONDS)
        conditions = [Trade.entry_timestamp >= start, Trade.entry_timestamp <= end]
    elif capture.event_type == "exit":
        start = captured - timedelta(seconds=ENTRY_EXIT_WINDOW_SECONDS)
        end = captured + timedelta(seconds=ENTRY_EXIT_WINDOW_SECONDS)
        conditions = [Trade.exit_timestamp >= start, Trade.exit_timestamp <= end]
    elif capture.event_type == "update":
        buffer = timedelta(seconds=UPDATE_WINDOW_SECONDS)
        conditions = [Trade.entry_timestamp <= captured + buffer, Trade.exit_timestamp >= captured - buffer]
    else:
        return []

    query = (
        select(Trade)
        .join(TradingAccount, TradingAccount.id == Trade.account_id)
        .where(TradingAccount.user_id == user_id, *conditions)
    )
    if capture.account_id is not None:
        query = query.where(Trade.account_id == capture.account_id)
    return list(db.scalars(query).all())


def rank_candidates(db: Session, capture: CaptureEvent, user_id: UUID) -> list[MatchCandidate]:
    capture_symbol = normalize_symbol(capture.symbol)
    if capture.event_type == "wait" or not capture_symbol:
        return []

    raw = _candidate_query(db, capture, user_id)
    symbol_matches = [
        trade
        for trade in raw
        if normalize_symbol(trade.root_symbol or trade.symbol) == capture_symbol
    ]
    unique_accounts = {trade.account_id for trade in symbol_matches}

    candidates: list[MatchCandidate] = []
    for trade in symbol_matches:
        trade_side = trade.side.value if hasattr(trade.side, "value") else str(trade.side)
        if capture.side and capture.side != trade_side:
            continue

        time = _time_score(capture, trade)
        if time is None:
            continue
        time_points, seconds_from_target = time

        score = 0.35  # normalized symbol is a mandatory exact match
        if capture.account_id is not None and trade.account_id == capture.account_id:
            score += 0.20
        elif capture.account_id is None and len(unique_accounts) == 1:
            score += 0.10

        if capture.side:
            score += 0.10
        else:
            score += 0.03

        score += time_points
        candidates.append(
            MatchCandidate(
                trade=trade,
                score=min(score, 1.0),
                seconds_from_target=seconds_from_target,
            )
        )

    candidates.sort(key=lambda item: (-item.score, item.seconds_from_target, str(item.trade.id)))
    return candidates


def _companion_attachment_name(capture: CaptureEvent) -> str:
    suffix = Path(capture.screenshot_original_filename or "capture.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    return f"companion-{capture.id}{suffix}"


def _remove_companion_attachment(db: Session, capture: CaptureEvent) -> None:
    """Remove legacy mirrored attachments created by older Companion matching code."""
    filename = _companion_attachment_name(capture)
    attachment = db.scalar(select(Attachment).where(Attachment.original_filename == filename))
    if attachment is None:
        return
    try:
        get_storage_provider(get_settings()).delete(attachment.storage_key)
    finally:
        db.delete(attachment)


def force_match_capture(
    db: Session,
    capture: CaptureEvent,
    trade: Trade,
    *,
    score: float = 1.0,
    method: str = "manual",
) -> MatchResult:
    capture.account_id = trade.account_id
    capture.match_status = "matched"
    capture.matched_trade_id = trade.id
    capture.match_score = Decimal(f"{max(0.0, min(score, 1.0)):.6f}")
    capture.matched_at = utcnow()
    capture.match_method = method
    # Companion screenshots remain CaptureEvents. Do not mirror them into manual attachments.
    _remove_companion_attachment(db, capture)
    db.flush()
    return MatchResult("matched", trade.id, float(capture.match_score), 1, None)


def clear_capture_match(db: Session, capture: CaptureEvent, *, status: str = "unmatched") -> None:
    _remove_companion_attachment(db, capture)
    capture.match_status = status
    capture.matched_trade_id = None
    capture.match_score = None
    capture.matched_at = None
    capture.match_method = None
    db.flush()


def reconcile_capture(db: Session, capture: CaptureEvent, user_id: UUID) -> MatchResult:
    if capture.event_type == "wait":
        if capture.match_status == "suggested":
            clear_capture_match(db, capture)
        return MatchResult("unmatched", None, None, 0, None)

    candidates = rank_candidates(db, capture, user_id)
    if not candidates:
        capture.match_status = "unmatched"
        capture.matched_trade_id = None
        capture.match_score = None
        capture.matched_at = None
        capture.match_method = None
        db.flush()
        return MatchResult("unmatched", None, None, 0, None)

    best = candidates[0]
    second_score = candidates[1].score if len(candidates) > 1 else None
    margin = best.score - second_score if second_score is not None else 1.0

    if best.score >= AUTO_MATCH_THRESHOLD and margin >= MIN_AUTO_MARGIN:
        result = force_match_capture(
            db,
            capture,
            best.trade,
            score=best.score,
            method=MATCH_METHOD,
        )
        return MatchResult(
            result.status,
            result.trade_id,
            result.score,
            len(candidates),
            margin,
        )

    if best.score >= SUGGEST_THRESHOLD:
        capture.match_status = "suggested"
        capture.matched_trade_id = best.trade.id
        capture.match_score = Decimal(f"{best.score:.6f}")
        capture.matched_at = None
        capture.match_method = MATCH_METHOD
        db.flush()
        return MatchResult("suggested", best.trade.id, best.score, len(candidates), margin)

    capture.match_status = "unmatched"
    capture.matched_trade_id = None
    capture.match_score = None
    capture.matched_at = None
    capture.match_method = None
    db.flush()
    return MatchResult("unmatched", None, best.score, len(candidates), margin)


def reconcile_unmatched_captures(
    db: Session,
    user_id: UUID,
    *,
    account_id: UUID | None = None,
) -> dict[str, int]:
    query = select(CaptureEvent).where(
        CaptureEvent.user_id == user_id,
        CaptureEvent.match_status.in_(["unmatched", "suggested"]),
        CaptureEvent.event_type != "wait",
    )
    if account_id is not None:
        query = query.where((CaptureEvent.account_id == account_id) | (CaptureEvent.account_id.is_(None)))

    captures = db.scalars(query.order_by(CaptureEvent.captured_at)).all()
    stats = {"checked": 0, "matched": 0, "suggested": 0, "unmatched": 0}
    for capture in captures:
        result = reconcile_capture(db, capture, user_id)
        stats["checked"] += 1
        stats[result.status] += 1
    return stats
