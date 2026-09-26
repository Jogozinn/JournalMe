from __future__ import annotations

import calendar as month_calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user
from app.config import get_settings
from app.database import get_db
from app.domain import TradeSide
from app.models import (
    Attachment,
    CashTransaction,
    DailyBalance,
    DailyJournal,
    Fill,
    Goal,
    ImportFile,
    ImportSession,
    ImportStatus,
    Order,
    Playbook,
    PropRuleProfile,
    PropRuleProfileVersion,
    Tag,
    Trade,
    TradeJournal,
    TradingAccount,
    User,
)
from app.schemas import (
    AccountCreate,
    AccountFromPresetCreate,
    AccountUpdate,
    DailyJournalUpdate,
    GoalCreate,
    GoalUpdate,
    PropPresetApply,
    PropRuleUpdate,
    TagCreate,
    TagUpdate,
    TradeJournalUpdate,
)
from app.seed import seed_default_tags
from app.services.balance import (
    BalanceResolution,
    resolve_account_balance,
    resolve_account_balances,
)
from app.services.import_sessions import build_preview, commit_import
from app.services.importer import (
    ImportReportValidationError,
    ParsedReport,
    ReportType,
    exact_duplicate_count,
    parse_report,
)
from app.services.presets import (
    PresetConfigurationError,
    PresetReplacementRequired,
    apply_preset,
    list_preset_catalog,
)
from app.services.prop_rules import (
    create_profile_version,
    ensure_open_cycle,
    latest_profile_version,
    lucidflex_funded_50k_preset,
)
from app.services.review import day_review_status, review_rules, trade_review_statuses
from app.storage import StorageProvider, get_storage_provider

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def _storage() -> StorageProvider:
    return get_storage_provider(get_settings())


def _account_or_404(db: Session, user: User, account_id: UUID) -> TradingAccount:
    account = db.scalar(
        select(TradingAccount).where(
            TradingAccount.id == account_id, TradingAccount.user_id == user.id
        )
    )
    if account is None:
        raise HTTPException(status_code=404, detail="Trading account not found.")
    return account


def _import_session_or_404(db: Session, user: User, session_id: UUID) -> ImportSession:
    item = db.scalar(
        select(ImportSession).where(
            ImportSession.id == session_id, ImportSession.user_id == user.id
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Import session not found.")
    return item


def _trade_or_404(db: Session, user: User, trade_id: UUID) -> Trade:
    trade = db.scalar(
        select(Trade)
        .join(TradingAccount)
        .options(selectinload(Trade.tags), selectinload(Trade.journal))
        .where(Trade.id == trade_id, TradingAccount.user_id == user.id)
    )
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found.")
    return trade


def _daily_journal_or_404(
    db: Session, user: User, journal_id: UUID
) -> DailyJournal:
    journal = db.scalar(
        select(DailyJournal)
        .join(TradingAccount)
        .where(
            DailyJournal.id == journal_id,
            TradingAccount.user_id == user.id,
        )
    )
    if journal is None:
        raise HTTPException(status_code=404, detail="Daily journal not found.")
    return journal


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _as_utc(value: datetime) -> datetime:
    """SQLite drops offsets; persisted timestamps are defined as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime | None) -> str | None:
    return _as_utc(value).isoformat() if value else None


def _account_dict(
    account: TradingAccount,
    balance: BalanceResolution | None = None,
    profile: PropRuleProfile | None = None,
    net_pnl: Decimal | None = None,
) -> dict[str, Any]:
    result = {
        "id": str(account.id),
        "name": account.name,
        "external_account_id": account.external_account_id,
        "provider": account.provider,
        "account_type": account.account_type.value,
        "starting_balance": _decimal(account.starting_balance),
        "timezone": account.timezone,
        "currency": account.currency,
        "notes": account.notes,
        "active": account.active,
        "lifecycle_status": account.lifecycle_status.value,
        "net_pnl": _decimal(net_pnl),
    }
    if balance is not None:
        result["current_balance"] = _decimal(balance.resolved_current_balance)
        result["balance_resolution"] = balance.as_dict()
    result["configuration_required"] = bool(
        profile is not None and profile.configuration_state == "required"
    )
    result["active_plan"] = (
        {
            "preset_key": profile.preset_key,
            "plan_family": (
                "LucidFlex"
                if profile.preset_key == "lucidflex-funded-50k"
                else "LucidDaily"
                if profile.preset_key
                in {"lucid_daily_eval_50k", "lucid_daily_funded_50k"}
                else "Custom"
            ),
            "phase": (
                "Evaluation"
                if profile.preset_key == "lucid_daily_eval_50k"
                else "Funded"
            ),
            "account_size": _decimal(profile.starting_balance),
        }
        if profile is not None
        and profile.enabled
        and profile.configuration_state == "configured"
        else None
    )
    return result


def _trade_dict(trade: Trade, *, detail: bool = False) -> dict[str, Any]:
    result = {
        "id": str(trade.id),
        "account_id": str(trade.account_id),
        "symbol": trade.symbol,
        "root_symbol": trade.root_symbol,
        "side": trade.side.value,
        "quantity": _decimal(trade.contract_quantity),
        "entry_price": _decimal(trade.entry_price),
        "exit_price": _decimal(trade.exit_price),
        "gross_pnl": _decimal(trade.gross_pnl),
        "fees": _decimal(trade.fees),
        "net_pnl": _decimal(trade.net_pnl),
        "currency": trade.currency,
        "entry_timestamp": _timestamp(trade.entry_timestamp),
        "exit_timestamp": _timestamp(trade.exit_timestamp),
        "duration_seconds": trade.duration_seconds,
        "reconciliation_status": trade.reconciliation_status,
        "source": trade.source_quality,
        "tags": [
            {"id": str(tag.id), "name": tag.name, "category": tag.category.value}
            for tag in trade.tags
        ],
        "journaled": trade.journal is not None,
    }
    if detail:
        result.update(
            {
                "product": trade.product,
                "product_description": trade.product_description,
                "source_quality": trade.source_quality,
                "primary_import_session_id": (
                    str(trade.primary_import_session_id)
                    if trade.primary_import_session_id
                    else None
                ),
                "reconciliation_warnings": trade.source_payload.get("warnings", []),
                "journal": _journal_dict(trade.journal) if trade.journal else None,
            }
        )
    return result


def _journal_dict(journal: TradeJournal) -> dict[str, Any]:
    return {
        column.name: getattr(journal, column.name)
        for column in TradeJournal.__table__.columns
        if column.name not in {"trade_id", "created_at", "updated_at"}
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "product": "JournalMe"}


@router.get("/public-config")
def public_config() -> dict[str, str | None]:
    """Browser-safe configuration for JournalMe web/Companion clients."""
    settings = get_settings()
    return {
        "auth_mode": "hosted" if settings.data_provider == "supabase" else "local",
        "supabase_url": settings.supabase_url if settings.data_provider == "supabase" else None,
        "supabase_anon_key": settings.supabase_anon_key if settings.data_provider == "supabase" else None,
    }


@router.get("/accounts")
def list_accounts(
    db: Db, user: CurrentUser, include_archived: bool = False
) -> list[dict[str, Any]]:
    statement = select(TradingAccount).where(TradingAccount.user_id == user.id)
    if not include_archived:
        statement = statement.where(TradingAccount.active.is_(True))
    accounts = db.scalars(statement.order_by(TradingAccount.created_at)).all()
    profiles = {
        item.account_id: item
        for item in db.scalars(
            select(PropRuleProfile).where(
                PropRuleProfile.account_id.in_([item.id for item in accounts])
            )
        ).all()
    }
    balances = resolve_account_balances(db, list(accounts))
    net_pnls = dict(
        db.execute(
            select(Trade.account_id, func.coalesce(func.sum(Trade.net_pnl), 0))
            .where(Trade.account_id.in_([item.id for item in accounts]))
            .group_by(Trade.account_id)
        ).all()
    ) if accounts else {}
    return [
        _account_dict(
            account,
            balances[account.id],
            profiles.get(account.id),
            net_pnls.get(account.id),
        )
        for account in accounts
    ]


@router.post("/accounts", status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, db: Db, user: CurrentUser) -> dict[str, Any]:
    account = TradingAccount(user_id=user.id, **payload.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return _account_dict(account, resolve_account_balance(db, account), None, Decimal("0"))


@router.post("/accounts/from-preset", status_code=status.HTTP_201_CREATED)
def create_account_from_preset(
    payload: AccountFromPresetCreate, db: Db, user: CurrentUser
) -> dict[str, Any]:
    if payload.preset.preset_key == "custom":
        return create_account(payload.account, db, user)
    account = TradingAccount(user_id=user.id, **payload.account.model_dump())
    db.add(account)
    db.flush()
    try:
        profile, version, _ = apply_preset(db, account, payload.preset)
    except PresetConfigurationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return {
        "account": _account_dict(
            account, resolve_account_balance(db, account), profile
        ),
        "profile_id": str(profile.id),
        "profile_version": version.version_number,
    }


@router.get("/accounts/{account_id}")
def account_detail(account_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account.id)
    )
    return _account_dict(
        account,
        resolve_account_balance(db, account),
        profile,
        db.scalar(select(func.coalesce(func.sum(Trade.net_pnl), 0)).where(Trade.account_id == account.id)),
    )


@router.patch("/accounts/{account_id}")
def update_account(
    account_id: UUID, payload: AccountUpdate, db: Db, user: CurrentUser
) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, key, value)
    db.commit()
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account.id)
    )
    return _account_dict(
        account,
        resolve_account_balance(db, account),
        profile,
        db.scalar(select(func.coalesce(func.sum(Trade.net_pnl), 0)).where(Trade.account_id == account.id)),
    )


@router.post("/accounts/{account_id}/archive")
def archive_account(account_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    account.active = False
    db.commit()
    return _account_dict(
        account,
        resolve_account_balance(db, account),
        db.scalar(select(PropRuleProfile).where(PropRuleProfile.account_id == account.id)),
        db.scalar(select(func.coalesce(func.sum(Trade.net_pnl), 0)).where(Trade.account_id == account.id)),
    )


@router.post("/accounts/{account_id}/restore")
def restore_account(account_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    account.active = True
    db.commit()
    return _account_dict(
        account,
        resolve_account_balance(db, account),
        db.scalar(select(PropRuleProfile).where(PropRuleProfile.account_id == account.id)),
        db.scalar(select(func.coalesce(func.sum(Trade.net_pnl), 0)).where(Trade.account_id == account.id)),
    )


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_account(account_id: UUID, db: Db, user: CurrentUser) -> None:
    account = _account_or_404(db, user, account_id)
    account.active = False
    db.commit()


@router.post("/imports/preview", status_code=status.HTTP_201_CREATED)
async def preview_import(
    db: Db,
    user: CurrentUser,
    files: Annotated[list[UploadFile], File(description="Tradovate CSV reports")],
    account_id: UUID | None = None,
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=422, detail="Select at least one CSV report.")
    account = _account_or_404(db, user, account_id) if account_id else None
    incoming: list[tuple[ParsedReport, bytes]] = []
    seen_hashes: set[str] = set()
    warnings: list[str] = []
    for upload in files:
        if Path(upload.filename or "").suffix.lower() != ".csv":
            raise HTTPException(
                status_code=415, detail=f"{upload.filename} is not a CSV file."
            )
        content = await upload.read()
        if len(content) > get_settings().max_upload_bytes:
            raise HTTPException(
                status_code=413, detail=f"{upload.filename} exceeds 10 MB."
            )
        report = parse_report(upload.filename or "report.csv", content)
        if report.content_hash in seen_hashes:
            warnings.append(
                f"{report.filename} duplicates another selected file and was skipped."
            )
            continue
        seen_hashes.add(report.content_hash)
        incoming.append((report, content))

    import_session = ImportSession(
        user_id=user.id,
        account_id=account.id if account else None,
        status=ImportStatus.PENDING,
        file_count=0,
    )
    db.add(import_session)
    db.flush()
    storage = _storage()
    reports = []
    for report, content in incoming:
        storage_key = storage.save(import_session.id, report.filename, content)
        import_file = ImportFile(
            import_session_id=import_session.id,
            filename=report.filename,
            detected_report_type=report.report_type.value,
            content_hash=report.content_hash,
            row_count=len(report.rows),
            valid_count=len(report.normalized_rows),
            duplicate_count=exact_duplicate_count(report.rows),
            error_count=len(report.errors),
            status="skipped"
            if report.report_type is ReportType.ORDER_DETAILS_EMPTY
            else ("error" if report.errors else "ready"),
            stored_path=storage_key,
            header_signature=report.header_signature,
        )
        db.add(import_file)
        reports.append(report)
    db.flush()
    preview = build_preview(reports, db, account)
    preview["warnings"] = warnings + preview["warnings"]
    import_session.file_count = len(reports)
    import_session.warning_count = len(preview["warnings"])
    import_session.error_count = len(preview["errors"])
    import_session.status = (
        ImportStatus.PENDING if preview["errors"] else ImportStatus.READY
    )
    import_session.summary_json = {"preview": preview}
    db.commit()
    return {"session_id": str(import_session.id), "status": import_session.status.value, **preview}


@router.get("/imports")
def import_history(db: Db, user: CurrentUser) -> list[dict[str, Any]]:
    sessions = db.scalars(
        select(ImportSession)
        .options(selectinload(ImportSession.files))
        .where(ImportSession.user_id == user.id)
        .order_by(ImportSession.started_at.desc())
    ).all()
    return [
        {
            "id": str(item.id),
            "account_id": str(item.account_id) if item.account_id else None,
            "status": item.status.value,
            "started_at": _timestamp(item.started_at),
            "committed_at": _timestamp(item.committed_at),
            "file_count": item.file_count,
            "warnings": item.warning_count,
            "errors": item.error_count,
            "filenames": [file.filename for file in item.files],
            "report_types": [file.detected_report_type for file in item.files],
            "summary": item.summary_json,
        }
        for item in sessions
    ]


@router.get("/imports/{session_id}")
def import_detail(session_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    item = _import_session_or_404(db, user, session_id)
    if item.account_id:
        _account_or_404(db, user, item.account_id)
    return {
        "id": str(item.id),
        "status": item.status.value,
        "files": [
            {
                "id": str(file.id),
                "filename": file.filename,
                "type": file.detected_report_type,
                "rows": file.row_count,
                "valid_rows": file.valid_count,
                "duplicate_rows": file.duplicate_count,
                "error_rows": file.error_count,
                "status": file.status,
                "content_hash": file.content_hash,
                "header_signature": file.header_signature,
            }
            for file in item.files
        ],
        "summary": item.summary_json,
    }


@router.post("/imports/{session_id}/commit")
def commit_import_session(session_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    item = _import_session_or_404(db, user, session_id)
    if item.account_id:
        _account_or_404(db, user, item.account_id)
    try:
        counts = commit_import(db, user, item, _storage())
        db.commit()
    except ImportReportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=exc.as_detail()) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"session_id": str(item.id), "status": "committed", "created": counts}


@router.post("/imports/{session_id}/cancel")
def cancel_import(session_id: UUID, db: Db, user: CurrentUser) -> dict[str, str]:
    item = _import_session_or_404(db, user, session_id)
    if item.account_id:
        _account_or_404(db, user, item.account_id)
    if item.status is ImportStatus.COMMITTED:
        raise HTTPException(status_code=409, detail="Committed imports cannot be canceled.")
    item.status = ImportStatus.CANCELED
    db.commit()
    return {"status": "canceled"}


@router.get("/trades")
def list_trades(
    db: Db,
    user: CurrentUser,
    account_id: UUID,
    start: date | None = None,
    end: date | None = None,
    search: str | None = None,
    result: str | None = Query(default=None, pattern="^(winner|loser|breakeven)$"),
    side: str | None = Query(default=None, pattern="^(long|short)$"),
    sort: str = Query(default="date", pattern="^(date|pnl|duration|quantity)$"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    account_zone = ZoneInfo(account.timezone)
    statement = (
        select(Trade)
        .options(selectinload(Trade.tags), selectinload(Trade.journal))
        .where(Trade.account_id == account_id)
    )
    if start:
        statement = statement.where(
            Trade.entry_timestamp
            >= datetime.combine(start, time.min, tzinfo=account_zone).astimezone(
                timezone.utc
            )
        )
    if end:
        statement = statement.where(
            Trade.entry_timestamp
            <= datetime.combine(end, time.max, tzinfo=account_zone).astimezone(
                timezone.utc
            )
        )
    if search:
        statement = statement.where(Trade.symbol.ilike(f"%{search.strip()}%"))
    if result == "winner":
        statement = statement.where(Trade.net_pnl > 0)
    elif result == "loser":
        statement = statement.where(Trade.net_pnl < 0)
    elif result == "breakeven":
        statement = statement.where(Trade.net_pnl == 0)
    if side:
        statement = statement.where(Trade.side == TradeSide(side))
    sort_column = {
        "date": Trade.entry_timestamp,
        "pnl": Trade.net_pnl,
        "duration": Trade.duration_seconds,
        "quantity": Trade.contract_quantity,
    }[sort]
    statement = statement.order_by(
        sort_column.asc() if direction == "asc" else sort_column.desc()
    )
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    trades = db.scalars(
        statement.offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [_trade_dict(trade) for trade in trades], "total": total, "page": page}


@router.get("/trades/{trade_id}")
def trade_detail(trade_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    trade = _trade_or_404(db, user, trade_id)
    previous_id = db.scalar(
        select(Trade.id)
        .where(
            Trade.account_id == trade.account_id,
            Trade.entry_timestamp < trade.entry_timestamp,
        )
        .order_by(Trade.entry_timestamp.desc())
        .limit(1)
    )
    next_id = db.scalar(
        select(Trade.id)
        .where(
            Trade.account_id == trade.account_id,
            Trade.entry_timestamp > trade.entry_timestamp,
        )
        .order_by(Trade.entry_timestamp.asc())
        .limit(1)
    )
    payload = _trade_dict(trade, detail=True)
    payload["previous_trade_id"] = str(previous_id) if previous_id else None
    payload["next_trade_id"] = str(next_id) if next_id else None
    return payload


@router.put("/trades/{trade_id}/journal")
def update_trade_journal(
    trade_id: UUID, payload: TradeJournalUpdate, db: Db, user: CurrentUser
) -> dict[str, Any]:
    trade = _trade_or_404(db, user, trade_id)
    journal_data = payload.model_dump(
        exclude={"tag_ids", "mark_reviewed"}, exclude_unset=True
    )
    journal = trade.journal or TradeJournal(trade_id=trade.id)
    for key, value in journal_data.items():
        setattr(journal, key, value)
    if trade.journal is None:
        db.add(journal)
    if payload.tag_ids is not None:
        trade.tags = list(
            db.scalars(
                select(Tag).where(Tag.user_id == user.id, Tag.id.in_(payload.tag_ids))
            ).all()
        )
    if payload.mark_reviewed is True:
        journal.reviewed_at = datetime.now(timezone.utc)
    elif payload.mark_reviewed is False:
        journal.reviewed_at = None
    db.commit()
    return _trade_dict(_trade_or_404(db, user, trade_id), detail=True)


@router.get("/trades/{trade_id}/executions")
def trade_executions(trade_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    trade = _trade_or_404(db, user, trade_id)
    fills = db.scalars(
        select(Fill).where(Fill.trade_id == trade.id).order_by(Fill.timestamp)
    ).all()
    order_ids = [fill.external_order_id for fill in fills if fill.external_order_id]
    orders = db.scalars(
        select(Order).where(
            Order.account_id == trade.account_id, Order.external_order_id.in_(order_ids)
        )
    ).all()
    return {
        "fills": [
            {
                "id": str(fill.id),
                "external_fill_id": fill.external_fill_id,
                "action": fill.action,
                "quantity": _decimal(fill.quantity),
                "price": _decimal(fill.price),
                "commission": _decimal(fill.commission),
                "timestamp": _timestamp(fill.timestamp),
            }
            for fill in fills
        ],
        "orders": [
            {
                "id": str(order.id),
                "external_order_id": order.external_order_id,
                "type": order.order_type,
                "status": order.status,
                "limit_price": _decimal(order.limit_price),
                "stop_price": _decimal(order.stop_price),
            }
            for order in orders
        ],
    }


@router.get("/journals/daily/{trading_date}")
def get_daily_journal(
    trading_date: date, account_id: UUID, db: Db, user: CurrentUser
) -> dict[str, Any] | None:
    _account_or_404(db, user, account_id)
    journal = db.scalar(
        select(DailyJournal).where(
            DailyJournal.account_id == account_id,
            DailyJournal.trading_date == trading_date,
        )
    )
    return _daily_journal_dict(journal) if journal else None


@router.put("/journals/daily/{trading_date}")
def upsert_daily_journal(
    trading_date: date,
    payload: DailyJournalUpdate,
    account_id: UUID,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    _account_or_404(db, user, account_id)
    journal = db.scalar(
        select(DailyJournal).where(
            DailyJournal.account_id == account_id,
            DailyJournal.trading_date == trading_date,
        )
    )
    if journal is None:
        journal = DailyJournal(account_id=account_id, trading_date=trading_date)
        db.add(journal)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "allowed_playbook_ids" and value is not None:
            value = [str(item) for item in value]
        setattr(journal, key, value)
    db.commit()
    db.refresh(journal)
    return _daily_journal_dict(journal)


@router.get("/timeline/{trading_date}")
def session_timeline(
    trading_date: date, account_id: UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    account_zone = ZoneInfo(account.timezone)
    day_start = datetime.combine(trading_date, time.min, tzinfo=account_zone).astimezone(
        timezone.utc
    )
    day_end = datetime.combine(trading_date, time.max, tzinfo=account_zone).astimezone(
        timezone.utc
    )
    trades = db.scalars(
        select(Trade)
        .options(selectinload(Trade.tags), selectinload(Trade.journal))
        .where(
            Trade.account_id == account_id,
            Trade.entry_timestamp >= day_start,
            Trade.entry_timestamp <= day_end,
        )
        .order_by(Trade.entry_timestamp)
    ).all()
    journal = db.scalar(
        select(DailyJournal).where(
            DailyJournal.account_id == account_id,
            DailyJournal.trading_date == trading_date,
        )
    )
    review_statuses = trade_review_statuses(db, user.id, list(trades))
    running = Decimal("0")
    high = Decimal("0")
    low = Decimal("0")
    events = []
    for trade in trades:
        running += trade.net_pnl
        high, low = max(high, running), min(low, running)
        events.append(
            {
                **_trade_dict(trade),
                "running_net_pnl": _decimal(running),
                "review": review_statuses[trade.id],
            }
        )
    total_fees = (
        sum((trade.fees or Decimal("0")) for trade in trades) if trades else Decimal("0")
    )
    return {
        "account": _account_dict(account),
        "trading_date": trading_date.isoformat(),
        "journal": _daily_journal_dict(journal) if journal else None,
        "trades": events,
        "review": day_review_status(
            journal,
            [review_statuses[trade.id] for trade in trades],
            review_rules(db, user.id),
        ),
        "navigation": _trading_day_navigation(db, account, trading_date),
        "summary": {
            "gross_pnl": _decimal(sum((trade.gross_pnl for trade in trades), Decimal("0"))),
            "fees": (
                _decimal(total_fees)
                if all(trade.fees is not None for trade in trades)
                else None
            ),
            "net_pnl": _decimal(running),
            "trade_count": len(trades),
            "win_rate": _decimal(
                Decimal(sum(trade.net_pnl > 0 for trade in trades)) / Decimal(len(trades)) * 100
            )
            if trades
            else None,
            "high_water_pnl": _decimal(high),
            "low_water_pnl": _decimal(low),
            "best_trade": (
                _trade_dict(max(trades, key=lambda item: item.net_pnl)) if trades else None
            ),
            "worst_trade": (
                _trade_dict(min(trades, key=lambda item: item.net_pnl)) if trades else None
            ),
        },
    }


@router.get("/dashboard")
def dashboard(
    account_id: UUID,
    db: Db,
    user: CurrentUser,
    period: str = Query(default="all", pattern="^(today|week|month|all|custom)$"),
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    all_trades = list(db.scalars(
        select(Trade)
        .options(selectinload(Trade.tags), selectinload(Trade.journal))
        .where(Trade.account_id == account_id)
        .order_by(Trade.entry_timestamp)
    ).all())
    all_journals = list(db.scalars(
        select(DailyJournal).where(DailyJournal.account_id == account_id)
    ).all())
    account_zone = ZoneInfo(account.timezone)
    today = datetime.now(timezone.utc).astimezone(account_zone).date()
    if period == "today":
        range_start = range_end = today
    elif period == "week":
        range_start = today - timedelta(days=today.weekday())
        range_end = range_start + timedelta(days=6)
    elif period == "month":
        range_start = today.replace(day=1)
        final_day = month_calendar.monthrange(today.year, today.month)[1]
        range_end = date(today.year, today.month, final_day)
    elif period == "custom" and start and end:
        range_start, range_end = start, end
    else:
        range_start = range_end = None
    if range_start and range_end:
        trades = [
            trade
            for trade in all_trades
            if range_start
            <= _as_utc(trade.entry_timestamp).astimezone(account_zone).date()
            <= range_end
        ]
        journals = [
            journal
            for journal in all_journals
            if range_start <= journal.trading_date <= range_end
        ]
    else:
        trades = all_trades
        journals = all_journals
    metrics = _metrics(trades)
    balance = resolve_account_balance(db, account)
    dashboard_profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account.id)
    )
    running = Decimal("0")
    curve = []
    for trade in trades:
        running += trade.net_pnl
        curve.append({"at": _timestamp(trade.exit_timestamp), "value": _decimal(running)})
    trading_days = {
        _as_utc(trade.entry_timestamp).astimezone(account_zone).date()
        for trade in trades
    }
    return {
        "account": _account_dict(account, balance, dashboard_profile),
        "balance": _decimal(balance.resolved_current_balance),
        "balance_as_of": (
            balance.imported_balance_as_of.isoformat()
            if balance.resolution_method == "imported_snapshot"
            and balance.imported_balance_as_of
            else balance.calculated_balance_as_of.isoformat()
            if balance.calculated_balance_as_of
            else None
        ),
        "balance_resolution": balance.as_dict(),
        "metrics": metrics,
        "equity_curve": curve,
        "recent_trades": [_trade_dict(trade) for trade in reversed(trades[-5:])],
        "journal_completion": {
            "completed": len(journals),
            "trading_days": len(trading_days),
            "percent": round(len(journals) / len(trading_days) * 100)
            if trading_days
            else 0,
        },
        "latest_insight": _latest_insight(trades),
        "period": {
            "value": period,
            "start": range_start.isoformat() if range_start else None,
            "end": range_end.isoformat() if range_end else None,
            "timezone": account.timezone,
        },
    }


@router.get("/calendar")
def calendar_summary(
    account_id: UUID,
    year: int,
    db: Db,
    user: CurrentUser,
    month: int = Query(ge=1, le=12),
) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    _, last_day = month_calendar.monthrange(year, month)
    start, end = date(year, month, 1), date(year, month, last_day)
    account_zone = ZoneInfo(account.timezone)
    start_at = datetime.combine(start, time.min, tzinfo=account_zone).astimezone(
        timezone.utc
    )
    end_at = datetime.combine(end, time.max, tzinfo=account_zone).astimezone(
        timezone.utc
    )
    trades = db.scalars(
        select(Trade).where(
            Trade.account_id == account_id,
            Trade.entry_timestamp >= start_at,
            Trade.entry_timestamp <= end_at,
        )
    ).all()
    journals = {
        item.trading_date
        for item in db.scalars(
            select(DailyJournal).where(
                DailyJournal.account_id == account_id,
                DailyJournal.trading_date.between(start, end),
            )
        ).all()
    }
    grouped: dict[date, list[Trade]] = defaultdict(list)
    for trade in trades:
        grouped[_as_utc(trade.entry_timestamp).astimezone(account_zone).date()].append(
            trade
        )
    days = [
        {
            "date": day.isoformat(),
            "net_pnl": _decimal(sum((trade.net_pnl for trade in values), Decimal("0"))),
            "trade_count": len(values),
            "journaled": day in journals,
        }
        for day, values in sorted(grouped.items())
    ]
    day_totals = [
        sum((trade.net_pnl for trade in values), Decimal("0"))
        for values in grouped.values()
    ]
    return {
        "year": year,
        "month": month,
        "days": days,
        "summary": {
            **_metrics(trades),
            "trading_days": len(grouped),
            "journaled_days": len(journals & set(grouped)),
            "best_day": _decimal(max(day_totals)) if day_totals else None,
            "worst_day": _decimal(min(day_totals)) if day_totals else None,
        },
    }


@router.get("/analytics")
def analytics(account_id: UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    balance_resolution = resolve_account_balance(db, account)
    trades = db.scalars(
        select(Trade)
        .options(selectinload(Trade.tags))
        .where(Trade.account_id == account_id)
        .order_by(Trade.entry_timestamp)
    ).all()
    balances = db.scalars(
        select(DailyBalance)
        .where(DailyBalance.account_id == account_id)
        .order_by(DailyBalance.trade_date)
    ).all()
    account_zone = ZoneInfo(account.timezone)
    starting_cash = db.scalar(
        select(func.sum(CashTransaction.delta)).where(
            CashTransaction.account_id == account_id,
            func.lower(CashTransaction.cash_change_type).notin_(
                ["commission", "trade paired"]
            ),
        )
    )
    balance_comparisons = []
    for balance in balances:
        running = sum(
            (
                trade.net_pnl
                for trade in trades
                if _as_utc(trade.exit_timestamp).astimezone(account_zone).date()
                <= balance.trade_date
            ),
            Decimal("0"),
        )
        base = (
            account.starting_balance
            if account.starting_balance is not None
            else starting_cash
        )
        calculated = base + running if base is not None else None
        balance_comparisons.append(
            {
                "date": balance.trade_date.isoformat(),
                "amount": _decimal(balance.total_amount),
                "realized_pnl": _decimal(balance.total_realized_pnl),
                "calculated_amount": _decimal(calculated),
                "difference": _decimal(balance.total_amount - calculated)
                if calculated is not None
                else None,
            }
        )
    return {
        "balance_resolution": balance_resolution.as_dict(),
        "metrics": _metrics(trades),
        "by_symbol": _group_performance(trades, lambda trade: trade.root_symbol or trade.symbol),
        "by_weekday": _group_performance(
            trades,
            lambda trade: _as_utc(trade.entry_timestamp)
            .astimezone(account_zone)
            .strftime("%A"),
        ),
        "by_hour": _group_performance(
            trades,
            lambda trade: (
                f"{_as_utc(trade.entry_timestamp).astimezone(account_zone).hour:02d}:00"
            ),
        ),
        "by_side": _group_performance(trades, lambda trade: trade.side.value),
        "by_setup": _tag_performance(trades, "setup"),
        "by_mistake": _tag_performance(trades, "mistake"),
        "imported_balances": balance_comparisons,
    }


@router.get("/reconciliation-warnings")
def reconciliation_warnings(
    account_id: UUID, db: Db, user: CurrentUser
) -> list[dict[str, Any]]:
    _account_or_404(db, user, account_id)
    trades = db.scalars(
        select(Trade)
        .where(
            Trade.account_id == account_id,
            Trade.reconciliation_status != "reconciled",
        )
        .order_by(Trade.entry_timestamp.desc())
    ).all()
    return [
        {
            "trade_id": str(trade.id),
            "symbol": trade.symbol,
            "entry_timestamp": _timestamp(trade.entry_timestamp),
            "status": trade.reconciliation_status,
            "warnings": trade.source_payload.get("warnings", []),
        }
        for trade in trades
    ]


@router.get("/tags")
def list_tags(db: Db, user: CurrentUser) -> list[dict[str, Any]]:
    seed_default_tags(db, user)
    db.commit()
    tags = db.scalars(
        select(Tag)
        .where(Tag.user_id == user.id, Tag.active.is_(True))
        .order_by(Tag.category, Tag.name)
    ).all()
    return [
        {
            "id": str(tag.id),
            "name": tag.name,
            "category": tag.category.value,
            "display_token": tag.display_token,
        }
        for tag in tags
    ]


@router.post("/tags", status_code=status.HTTP_201_CREATED)
def create_tag(payload: TagCreate, db: Db, user: CurrentUser) -> dict[str, Any]:
    tag = Tag(user_id=user.id, **payload.model_dump())
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return {"id": str(tag.id), "name": tag.name, "category": tag.category.value}


@router.patch("/tags/{tag_id}")
def update_tag(
    tag_id: UUID, payload: TagUpdate, db: Db, user: CurrentUser
) -> dict[str, Any]:
    tag = db.scalar(select(Tag).where(Tag.id == tag_id, Tag.user_id == user.id))
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(tag, key, value)
    db.commit()
    return {
        "id": str(tag.id),
        "name": tag.name,
        "category": tag.category.value,
        "display_token": tag.display_token,
        "active": tag.active,
    }


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: UUID, db: Db, user: CurrentUser) -> None:
    tag = db.scalar(select(Tag).where(Tag.id == tag_id, Tag.user_id == user.id))
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found.")
    tag.active = False
    db.commit()


@router.post("/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    db: Db,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
    trade_id: UUID | None = None,
    daily_journal_id: UUID | None = None,
    playbook_id: UUID | None = None,
    caption: str | None = None,
) -> dict[str, Any]:
    if sum(bool(item) for item in (trade_id, daily_journal_id, playbook_id)) != 1:
        raise HTTPException(
            status_code=422,
            detail="Choose exactly one trade, daily journal, or playbook.",
        )
    if trade_id:
        _trade_or_404(db, user, trade_id)
    if daily_journal_id:
        _daily_journal_or_404(db, user, daily_journal_id)
    if playbook_id:
        owned_playbook = db.scalar(
            select(Playbook).where(
                Playbook.id == playbook_id,
                Playbook.user_id == user.id,
            )
        )
        if owned_playbook is None:
            raise HTTPException(status_code=404, detail="Playbook not found.")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="Attachments must be images.")
    content = await file.read()
    if len(content) > get_settings().max_upload_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds 10 MB.")
    owner_id = trade_id or daily_journal_id or playbook_id
    storage_key = _storage().put(owner_id, file.filename or "screenshot", content)
    attachment = Attachment(
        trade_id=trade_id,
        daily_journal_id=daily_journal_id,
        playbook_id=playbook_id,
        storage_key=storage_key,
        original_filename=Path(file.filename or "screenshot").name,
        mime_type=file.content_type or "application/octet-stream",
        caption=caption,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return {"id": str(attachment.id), "filename": attachment.original_filename, "caption": caption}


@router.get("/trades/{trade_id}/attachments")
def list_trade_attachments(
    trade_id: UUID, db: Db, user: CurrentUser
) -> list[dict[str, Any]]:
    _trade_or_404(db, user, trade_id)
    attachments = db.scalars(
        select(Attachment)
        .where(
            Attachment.trade_id == trade_id,
            ~Attachment.original_filename.like("companion-%"),
        )
        .order_by(Attachment.created_at)
    ).all()
    return [
        {
            "id": str(item.id),
            "filename": item.original_filename,
            "mime_type": item.mime_type,
            "caption": item.caption,
            "content_url": f"{get_settings().api_prefix}/attachments/{item.id}/content",
        }
        for item in attachments
    ]


@router.get("/attachments/{attachment_id}/content")
def attachment_content(
    attachment_id: UUID, db: Db, user: CurrentUser
) -> Response:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    if attachment.trade_id:
        _trade_or_404(db, user, attachment.trade_id)
    elif attachment.daily_journal_id:
        _daily_journal_or_404(db, user, attachment.daily_journal_id)
    elif attachment.playbook_id:
        if db.scalar(
            select(Playbook.id).where(
                Playbook.id == attachment.playbook_id,
                Playbook.user_id == user.id,
            )
        ) is None:
            raise HTTPException(status_code=404, detail="Attachment not found.")
    content = _storage().get(attachment.storage_key)
    return Response(
        content=content,
        media_type=attachment.mime_type,
        headers={
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(attachment_id: UUID, db: Db, user: CurrentUser) -> None:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    if attachment.trade_id:
        _trade_or_404(db, user, attachment.trade_id)
    elif attachment.daily_journal_id:
        _daily_journal_or_404(db, user, attachment.daily_journal_id)
    elif attachment.playbook_id:
        if db.scalar(
            select(Playbook.id).where(
                Playbook.id == attachment.playbook_id,
                Playbook.user_id == user.id,
            )
        ) is None:
            raise HTTPException(status_code=404, detail="Attachment not found.")
    _storage().delete(attachment.storage_key)
    db.delete(attachment)
    db.commit()


@router.get("/goals")
def list_goals(account_id: UUID, db: Db, user: CurrentUser) -> list[dict[str, Any]]:
    account = _account_or_404(db, user, account_id)
    goals = db.scalars(select(Goal).where(Goal.account_id == account_id)).all()
    return [
        {
            "id": str(goal.id),
            "period_type": goal.period_type,
            "start_date": goal.start_date.isoformat(),
            "end_date": goal.end_date.isoformat(),
            "target_pnl": _decimal(goal.target_pnl),
            "target_journal_days": goal.target_journal_days,
            "custom_goal_text": goal.custom_goal_text,
            "goal_type": goal.goal_type,
            "target_value": _decimal(goal.target_value),
            "status": goal.status,
            **_goal_progress(db, account, goal),
        }
        for goal in goals
    ]


@router.post("/goals", status_code=status.HTTP_201_CREATED)
def create_goal(payload: GoalCreate, db: Db, user: CurrentUser) -> dict[str, str]:
    _account_or_404(db, user, payload.account_id)
    goal = Goal(**payload.model_dump())
    db.add(goal)
    db.commit()
    return {"id": str(goal.id), "status": goal.status}


@router.patch("/goals/{goal_id}")
def update_goal(
    goal_id: UUID, payload: GoalUpdate, db: Db, user: CurrentUser
) -> dict[str, Any]:
    goal = db.scalar(
        select(Goal)
        .join(TradingAccount)
        .where(Goal.id == goal_id, TradingAccount.user_id == user.id)
    )
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, key, value)
    db.commit()
    return {"id": str(goal.id), "status": goal.status}


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: UUID, db: Db, user: CurrentUser) -> None:
    goal = db.scalar(
        select(Goal)
        .join(TradingAccount)
        .where(Goal.id == goal_id, TradingAccount.user_id == user.id)
    )
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found.")
    db.delete(goal)
    db.commit()


@router.get("/prop-rules/{account_id}")
def get_prop_rules(
    account_id: UUID, db: Db, user: CurrentUser
) -> dict[str, Any] | None:
    _account_or_404(db, user, account_id)
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account_id)
    )
    if profile is None:
        return None
    version = latest_profile_version(db, profile.id)
    return {
        "id": str(profile.id),
        "firm_name": profile.firm_name,
        "account_label": profile.account_label,
        "profile_account_type": profile.profile_account_type,
        "starting_balance": _decimal(profile.starting_balance),
        "profit_target": _decimal(profile.profit_target),
        "max_loss": _decimal(profile.max_loss),
        "daily_loss_limit": _decimal(profile.daily_loss_limit),
        "consistency_percent": _decimal(profile.consistency_percent),
        "drawdown_type": profile.drawdown_type,
        "drawdown_amount": _decimal(profile.drawdown_amount),
        "drawdown_lock_behavior": profile.drawdown_lock_behavior,
        "payout_buffer": _decimal(profile.payout_buffer),
        "minimum_trading_days": profile.minimum_trading_days,
        "qualifying_profit_days_required": profile.qualifying_profit_days_required,
        "minimum_profit_per_qualifying_day": _decimal(
            profile.minimum_profit_per_qualifying_day
        ),
        "payout_cycle_net_profit_required": profile.payout_cycle_net_profit_required,
        "minimum_payout": _decimal(profile.minimum_payout),
        "payout_profit_percentage": _decimal(profile.payout_profit_percentage),
        "maximum_payout": _decimal(profile.maximum_payout),
        "maximum_payout_count": profile.maximum_payout_count,
        "profit_split_trader_percent": _decimal(
            profile.profit_split_trader_percent
        ),
        "profit_split_firm_percent": _decimal(profile.profit_split_firm_percent),
        "no_fixed_payout_window": profile.no_fixed_payout_window,
        "payout_cycle_start_date": (
            profile.payout_cycle_start_date.isoformat()
            if profile.payout_cycle_start_date
            else None
        ),
        "qualifying_days_since_last_payout": (
            profile.qualifying_days_since_last_payout
        ),
        "payouts_completed": profile.payouts_completed,
        "preset_key": profile.preset_key,
        "effective_date": (
            profile.effective_date.isoformat() if profile.effective_date else None
        ),
        "source_note": profile.source_note,
        "version": (
            {
                "id": str(version.id),
                "version_number": version.version_number,
                "effective_date": version.effective_date.isoformat(),
                "source_note": version.source_note,
            }
            if version
            else None
        ),
        "scaling_tiers": (
            [
                {
                    "lower_profit_bound": _decimal(item.lower_profit_bound),
                    "upper_profit_bound": _decimal(item.upper_profit_bound),
                    "max_mini_contracts": item.max_mini_contracts,
                    "max_micro_contracts": item.max_micro_contracts,
                }
                for item in version.scaling_tiers
            ]
            if version
            else []
        ),
        "rules_enabled_json": profile.rules_enabled_json,
        "enabled": profile.enabled,
        "configuration_state": profile.configuration_state,
        "evaluation_drawdown_choice": profile.evaluation_drawdown_choice,
        "daily_loss_limit_enabled": profile.daily_loss_limit_enabled,
        "daily_loss_limit_amount": _decimal(profile.daily_loss_limit_amount),
        "initial_trail_balance": _decimal(profile.initial_trail_balance),
        "locked_mll_balance": _decimal(profile.locked_mll_balance),
        "payout_buffer_balance_threshold": _decimal(
            profile.payout_buffer_balance_threshold
        ),
        "max_daily_simulated_profit": _decimal(
            profile.max_daily_simulated_profit
        ),
        "news_restriction_note": profile.news_restriction_note,
        "live_transition_note": profile.live_transition_note,
        "purchase_configuration": profile.purchase_configuration_json,
    }


@router.put("/prop-rules/{account_id}")
def upsert_prop_rules(
    account_id: UUID, payload: PropRuleUpdate, db: Db, user: CurrentUser
) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account_id)
    )
    values = payload.model_dump(
        exclude={"scaling_tiers"},
        exclude_unset=True,
    )
    if profile is None:
        profile = PropRuleProfile(account_id=account_id, **values)
        db.add(profile)
    else:
        for key, value in values.items():
            setattr(profile, key, value)
    db.flush()
    version = create_profile_version(db, profile, payload.scaling_tiers)
    earliest = db.scalar(
        select(func.min(Trade.entry_timestamp)).where(Trade.account_id == account.id)
    )
    fallback_start = (
        _as_utc(earliest).astimezone(ZoneInfo(account.timezone)).date()
        if earliest
        else date.today()
    )
    ensure_open_cycle(db, account, profile, version, fallback_start)
    db.commit()
    return {
        "id": str(profile.id),
        "enabled": profile.enabled,
        "version_number": version.version_number,
    }


@router.post("/prop-rules/{account_id}/preset/lucidflex-funded-50k")
def apply_lucidflex_funded_50k_preset(
    account_id: UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    earliest = db.scalar(
        select(func.min(Trade.entry_timestamp)).where(
            Trade.account_id == account.id
        )
    )
    cycle_start = (
        _as_utc(earliest).astimezone(ZoneInfo(account.timezone)).date()
        if earliest
        else date.today()
    )
    values, tiers = lucidflex_funded_50k_preset(cycle_start)
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account_id)
    )
    if profile is None:
        profile = PropRuleProfile(account_id=account_id, **values)
        db.add(profile)
    else:
        for key, value in values.items():
            setattr(profile, key, value)
    db.flush()
    version = create_profile_version(db, profile, tiers)
    ensure_open_cycle(db, account, profile, version, cycle_start)
    db.commit()
    return {
        "id": str(profile.id),
        "preset_key": profile.preset_key,
        "version_number": version.version_number,
    }


@router.get("/prop-presets")
def prop_preset_catalog(db: Db, user: CurrentUser) -> list[dict[str, Any]]:
    del user
    return list_preset_catalog(db)


@router.post("/prop-rules/{account_id}/apply-preset")
def apply_account_prop_preset(
    account_id: UUID,
    payload: PropPresetApply,
    db: Db,
    user: CurrentUser,
) -> dict[str, Any]:
    account = _account_or_404(db, user, account_id)
    try:
        profile, version, created = apply_preset(db, account, payload)
    except PresetReplacementRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PresetConfigurationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return {
        "id": str(profile.id),
        "preset_key": profile.preset_key,
        "configuration_state": profile.configuration_state,
        "version_number": version.version_number,
        "created_version": created,
    }


@router.get("/prop-rules/{account_id}/versions")
def list_prop_rule_versions(
    account_id: UUID, db: Db, user: CurrentUser
) -> list[dict[str, Any]]:
    _account_or_404(db, user, account_id)
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account_id)
    )
    if profile is None:
        return []
    versions = db.scalars(
        select(PropRuleProfileVersion)
        .options(selectinload(PropRuleProfileVersion.scaling_tiers))
        .where(PropRuleProfileVersion.profile_id == profile.id)
        .order_by(PropRuleProfileVersion.version_number.desc())
    ).all()
    return [
        {
            "id": str(item.id),
            "version_number": item.version_number,
            "effective_date": item.effective_date.isoformat(),
            "source_note": item.source_note,
            "rules": item.rules_json,
            "scaling_tiers": [
                {
                    "lower_profit_bound": _decimal(tier.lower_profit_bound),
                    "upper_profit_bound": _decimal(tier.upper_profit_bound),
                    "max_mini_contracts": tier.max_mini_contracts,
                    "max_micro_contracts": tier.max_micro_contracts,
                }
                for tier in item.scaling_tiers
            ],
        }
        for item in versions
    ]


@router.delete("/prop-rules/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prop_rules(account_id: UUID, db: Db, user: CurrentUser) -> None:
    _account_or_404(db, user, account_id)
    profile = db.scalar(
        select(PropRuleProfile).where(PropRuleProfile.account_id == account_id)
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Prop rule profile not found.")
    db.delete(profile)
    db.commit()


def _daily_journal_dict(journal: DailyJournal) -> dict[str, Any]:
    return {
        column.name: (
            _decimal(value)
            if isinstance(value := getattr(journal, column.name), Decimal)
            else _timestamp(value)
            if isinstance(value, datetime)
            else value.isoformat()
            if isinstance(value, date)
            else str(value)
            if isinstance(value, UUID)
            else value
        )
        for column in DailyJournal.__table__.columns
    }


def _trading_day_navigation(
    db: Session, account: TradingAccount, current: date
) -> dict[str, str | None]:
    zone = ZoneInfo(account.timezone)
    timestamps = db.scalars(
        select(Trade.entry_timestamp).where(Trade.account_id == account.id)
    ).all()
    journal_dates = db.scalars(
        select(DailyJournal.trading_date).where(DailyJournal.account_id == account.id)
    ).all()
    dates = sorted(
        {
            _as_utc(timestamp).astimezone(zone).date() for timestamp in timestamps
        }
        | set(journal_dates)
    )
    previous = max((value for value in dates if value < current), default=None)
    following = min((value for value in dates if value > current), default=None)
    return {
        "previous": previous.isoformat() if previous else None,
        "next": following.isoformat() if following else None,
    }


def _metrics(trades: list[Trade]) -> dict[str, Any]:
    if not trades:
        return {
            "net_pnl": "0",
            "win_rate": None,
            "profit_factor": None,
            "average_winner": None,
            "average_loser": None,
            "average_win_loss_ratio": None,
            "largest_gain": None,
            "largest_loss": None,
            "expectancy": None,
            "total_trades": 0,
        }
    winners = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
    losers = [trade.net_pnl for trade in trades if trade.net_pnl < 0]
    gross_wins = sum(winners, Decimal("0"))
    gross_losses = abs(sum(losers, Decimal("0")))
    average_winner = gross_wins / len(winners) if winners else None
    average_loser = sum(losers, Decimal("0")) / len(losers) if losers else None
    net = sum((trade.net_pnl for trade in trades), Decimal("0"))
    return {
        "net_pnl": _decimal(net),
        "win_rate": _decimal(Decimal(len(winners)) / Decimal(len(trades)) * 100),
        "profit_factor": _decimal(gross_wins / gross_losses) if gross_losses else None,
        "average_winner": _decimal(average_winner),
        "average_loser": _decimal(average_loser),
        "average_win_loss_ratio": _decimal(
            average_winner / abs(average_loser)
        )
        if average_winner is not None and average_loser
        else None,
        "largest_gain": _decimal(max(winners)) if winners else None,
        "largest_loss": _decimal(min(losers)) if losers else None,
        "expectancy": _decimal(net / len(trades)),
        "total_trades": len(trades),
    }


def _group_performance(trades: list[Trade], key):
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        grouped[str(key(trade))].append(trade)
    return [
        {"label": label, **_metrics(values)}
        for label, values in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _tag_performance(trades: list[Trade], category: str):
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        for tag in trade.tags:
            if tag.category.value == category:
                grouped[tag.name].append(trade)
    return [{"label": label, **_metrics(values)} for label, values in sorted(grouped.items())]


def _latest_insight(trades: list[Trade]) -> str | None:
    if len(trades) < 3:
        return None
    recent = trades[-3:]
    total = sum((trade.net_pnl for trade in recent), Decimal("0"))
    if total < 0:
        return (
            "Your last three imported trades were net negative. "
            "Review the session before the next open."
        )
    return "Your last three imported trades were net positive. Capture what stayed repeatable."


def _goal_progress(
    db: Session, account: TradingAccount, goal: Goal
) -> dict[str, Any]:
    zone = ZoneInfo(account.timezone)
    start_at = datetime.combine(goal.start_date, time.min, tzinfo=zone).astimezone(
        timezone.utc
    )
    end_at = datetime.combine(goal.end_date, time.max, tzinfo=zone).astimezone(
        timezone.utc
    )
    trades = list(
        db.scalars(
            select(Trade)
            .options(selectinload(Trade.journal), selectinload(Trade.tags))
            .where(
                Trade.account_id == account.id,
                Trade.entry_timestamp >= start_at,
                Trade.entry_timestamp <= end_at,
            )
        ).all()
    )
    target = goal.target_value or goal.target_pnl
    current: Decimal | int | None
    lower_is_better = goal.goal_type in {
        "max_daily_loss",
        "max_weekly_loss",
        "max_trades_per_day",
        "mistake_reduction",
    }
    if goal.goal_type == "journal_completion":
        journaled = db.scalar(
            select(func.count())
            .select_from(DailyJournal)
            .where(
                DailyJournal.account_id == account.id,
                DailyJournal.trading_date >= goal.start_date,
                DailyJournal.trading_date <= goal.end_date,
                DailyJournal.reflection.is_not(None),
            )
        ) or 0
        current = journaled
        target = target or (
            Decimal(goal.target_journal_days) if goal.target_journal_days else None
        )
    elif goal.goal_type == "a_grade_trades":
        current = sum(
            bool(item.journal and item.journal.trade_grade in {"A+", "A"})
            for item in trades
        )
    elif goal.goal_type == "plan_adherence":
        answered = [
            item.journal.followed_plan
            for item in trades
            if item.journal and item.journal.followed_plan is not None
        ]
        current = (
            Decimal(sum(answered)) / Decimal(len(answered)) * 100
            if answered
            else Decimal("0")
        )
    elif goal.goal_type == "max_trades_per_day":
        counts: dict[date, int] = defaultdict(int)
        for item in trades:
            counts[_as_utc(item.entry_timestamp).astimezone(zone).date()] += 1
        current = max(counts.values(), default=0)
    elif goal.goal_type == "mistake_reduction":
        current = sum(
            any(tag.category.value == "mistake" for tag in item.tags) for item in trades
        )
    elif goal.goal_type in {"max_daily_loss", "max_weekly_loss"}:
        current = abs(min((item.net_pnl for item in trades), default=Decimal("0")))
    else:
        current = sum((item.net_pnl for item in trades), Decimal("0"))
    numeric_current = Decimal(current) if current is not None else None
    progress = (
        min(round(numeric_current / target * 100), 100)
        if numeric_current is not None and target and target != 0 and not lower_is_better
        else 100
        if numeric_current is not None and target and lower_is_better and numeric_current <= target
        else 0
    )
    on_track = (
        numeric_current <= target
        if lower_is_better and numeric_current is not None and target is not None
        else numeric_current >= target
        if numeric_current is not None and target is not None
        else None
    )
    return {
        "current_value": _decimal(numeric_current),
        "effective_target": _decimal(target),
        "progress_percent": progress,
        "on_track": on_track,
    }
