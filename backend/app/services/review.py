from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Attachment,
    CaptureEvent,
    DailyJournal,
    PlaybookChecklistItem,
    Trade,
    TradeChecklistResponse,
    TradePlaybook,
    UserPreference,
)

DEFAULT_TRADE_FIELDS = {
    "thesis": "thesis",
    "entry_reason": "entry reason",
    "exit_reason": "exit reason",
    "lesson_learned": "lesson learned",
    "trade_grade": "trade grade",
    "followed_plan": "followed-plan answer",
}
DEFAULT_DAY_FIELDS = {
    "reflection": "reflection",
    "focus_for_next_session": "focus for next session",
    "day_grade": "day grade",
    "followed_rules": "followed-rules answer",
}


def review_rules(db: Session, user_id: UUID) -> dict[str, Any]:
    preference = db.get(UserPreference, user_id)
    configured = preference.review_rules_json if preference else {}
    return {
        "trade_fields": configured.get("trade_fields", list(DEFAULT_TRADE_FIELDS)),
        "day_fields": configured.get("day_fields", list(DEFAULT_DAY_FIELDS)),
        "require_primary_playbook": configured.get("require_primary_playbook", True),
        "require_tag": configured.get("require_tag", True),
        "require_required_checklist": configured.get("require_required_checklist", True),
        "require_screenshot": configured.get("require_screenshot", False),
    }


def trade_review_statuses(
    db: Session,
    user_id: UUID,
    trades: list[Trade],
) -> dict[UUID, dict[str, Any]]:
    if not trades:
        return {}
    rules = review_rules(db, user_id)
    trade_ids = [trade.id for trade in trades]
    primary_rows = db.execute(
        select(TradePlaybook.trade_id, TradePlaybook.playbook_id).where(
            TradePlaybook.trade_id.in_(trade_ids),
            TradePlaybook.is_primary.is_(True),
        )
    ).all()
    primary_by_trade = {trade_id: playbook_id for trade_id, playbook_id in primary_rows}

    required_by_trade: dict[UUID, set[UUID]] = defaultdict(set)
    if primary_by_trade:
        required_rows = db.execute(
            select(TradePlaybook.trade_id, PlaybookChecklistItem.id)
            .join(
                PlaybookChecklistItem,
                PlaybookChecklistItem.playbook_id == TradePlaybook.playbook_id,
            )
            .where(
                TradePlaybook.trade_id.in_(trade_ids),
                TradePlaybook.is_primary.is_(True),
                PlaybookChecklistItem.required.is_(True),
            )
        ).all()
        for trade_id, checklist_id in required_rows:
            required_by_trade[trade_id].add(checklist_id)

    answered_by_trade: dict[UUID, dict[UUID, bool]] = defaultdict(dict)
    responses = db.execute(
        select(
            TradeChecklistResponse.trade_id,
            TradeChecklistResponse.checklist_item_id,
            TradeChecklistResponse.passed,
        ).where(TradeChecklistResponse.trade_id.in_(trade_ids))
    ).all()
    for trade_id, checklist_id, passed in responses:
        if passed is not None:
            answered_by_trade[trade_id][checklist_id] = passed

    screenshot_trade_ids = set(
        db.scalars(
            select(Attachment.trade_id).where(
                Attachment.trade_id.in_(trade_ids),
                Attachment.trade_id.is_not(None),
                ~Attachment.original_filename.like("companion-%"),
            )
        ).all()
    )
    screenshot_trade_ids.update(
        trade_id
        for trade_id in db.scalars(
            select(CaptureEvent.matched_trade_id).where(
                CaptureEvent.user_id == user_id,
                CaptureEvent.match_status == "matched",
                CaptureEvent.matched_trade_id.in_(trade_ids),
                CaptureEvent.matched_trade_id.is_not(None),
                CaptureEvent.screenshot_storage_key.is_not(None),
            )
        ).all()
        if trade_id is not None
    )

    statuses: dict[UUID, dict[str, Any]] = {}
    for trade in trades:
        missing: list[str] = []
        journal = trade.journal
        for field_name in rules["trade_fields"]:
            if field_name not in DEFAULT_TRADE_FIELDS:
                continue
            value = getattr(journal, field_name, None) if journal else None
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(DEFAULT_TRADE_FIELDS[field_name])
        if rules["require_primary_playbook"] and trade.id not in primary_by_trade:
            missing.append("primary playbook")
        if rules["require_tag"] and not trade.tags:
            missing.append("tag")
        required_items = required_by_trade[trade.id]
        answered_items = answered_by_trade[trade.id]
        unanswered = required_items.difference(answered_items)
        if rules["require_required_checklist"] and unanswered:
            missing.append(f"{len(unanswered)} required checklist response(s)")
        if rules["require_screenshot"] and trade.id not in screenshot_trade_ids:
            missing.append("screenshot")

        total_requirements = len(rules["trade_fields"])
        total_requirements += int(rules["require_primary_playbook"])
        total_requirements += int(rules["require_tag"])
        total_requirements += len(required_items) if rules["require_required_checklist"] else 0
        total_requirements += int(rules["require_screenshot"])
        complete_requirements = max(total_requirements - len(missing), 0)
        status = (
            "complete"
            if not missing
            else "unreviewed"
            if complete_requirements == 0
            else "partial"
        )
        passed_required = sum(
            answered_items.get(checklist_id) is True for checklist_id in required_items
        )
        adherence = (
            round(passed_required / len(required_items) * 100)
            if required_items
            else None
        )
        statuses[trade.id] = {
            "status": status,
            "missing": missing,
            "completed_requirements": complete_requirements,
            "total_requirements": total_requirements,
            "primary_playbook_id": (
                str(primary_by_trade[trade.id]) if trade.id in primary_by_trade else None
            ),
            "has_screenshot": trade.id in screenshot_trade_ids,
            "adherence_percent": adherence,
        }
    return statuses


def day_review_status(
    journal: DailyJournal | None,
    trade_statuses: list[dict[str, Any]],
    rules: dict[str, Any],
) -> dict[str, Any]:
    missing: list[str] = []
    quick_complete = bool(
        journal
        and journal.review_depth == "quick"
        and journal.quick_rating
    )
    if quick_complete:
        if journal.followed_rules is None:
            missing.append("followed-rules answer")
        total = 2 + int(bool(trade_statuses))
        complete = 2 - int(journal.followed_rules is None)
    else:
        for field_name in rules["day_fields"]:
            if field_name not in DEFAULT_DAY_FIELDS:
                continue
            value = getattr(journal, field_name, None) if journal else None
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(DEFAULT_DAY_FIELDS[field_name])
        total = len(rules["day_fields"]) + int(bool(trade_statuses))
        complete = max(len(rules["day_fields"]) - len(missing), 0)

    incomplete_trades = sum(item["status"] != "complete" for item in trade_statuses)
    if not quick_complete:
        if incomplete_trades:
            missing.append(f"{incomplete_trades} incomplete trade review(s)")
        elif trade_statuses:
            complete += 1
    elif trade_statuses:
        # Quick day reviews deliberately do not force an essay-style review for every trade.
        total -= 1
    complete = max(total - len(missing), complete, 0)
    return {
        "status": "complete" if not missing else "unreviewed" if complete == 0 else "partial",
        "missing": missing,
        "completed_requirements": min(complete, total),
        "total_requirements": total,
    }
