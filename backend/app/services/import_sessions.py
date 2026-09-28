from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccountType,
    Attachment,
    CaptureEvent,
    CashTransaction,
    DailyBalance,
    Fill,
    ImportFile,
    ImportSession,
    ImportStatus,
    Order,
    RuleViolation,
    Trade,
    TradeChecklistResponse,
    TradeJournal,
    TradePlaybook,
    TradeTag,
    TradingAccount,
    TradingEpisode,
    User,
    utcnow,
)
from app.services.importer import (
    ImportReportValidationError,
    NormalizedBalanceRow,
    NormalizedCashRow,
    NormalizedFillRow,
    NormalizedOrderRow,
    ParsedReport,
    ReportType,
    detected_accounts,
    exact_duplicate_count,
    report_date_coverage,
    row_get,
)
from app.services.capture_matching import reconcile_unmatched_captures
from app.services.instrument_identity import canonical_contract_key, root_symbol
from app.services.reconciliation import CanonicalTrade, reconcile_completed_trades
from app.services.trade_ledger import reconcile_trade_ledger
from app.storage import FileStorage


MATCH_TIME_TOLERANCE_SECONDS = 3.0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _split_external_ids(value: str | None) -> set[str]:
    return {item.strip() for item in (value or "").split(",") if item.strip()}


def _trade_fill_ids(trade: Trade) -> set[str]:
    ids = _split_external_ids(trade.external_buy_fill_id) | _split_external_ids(
        trade.external_sell_fill_id
    )
    payload = trade.source_payload or {}
    for key in ("fill_ids",):
        values = payload.get(key)
        if isinstance(values, list):
            ids.update(str(value) for value in values if value)
    tradovate = payload.get("tradovate_reconciliation")
    if isinstance(tradovate, dict):
        values = tradovate.get("fill_ids")
        if isinstance(values, list):
            ids.update(str(value) for value in values if value)
    return ids


def _is_live_trade(trade: Trade) -> bool:
    payload = trade.source_payload or {}
    return (
        trade.source_quality in {"broker_live", "multi_source_reconciled"}
        or payload.get("source") == "broker_live"
    )


def _same_lifecycle(trade: Trade, item: CanonicalTrade) -> bool:
    if trade.source_quality == "manual":
        return False
    if trade.side is not item.side or Decimal(trade.contract_quantity) != item.quantity:
        return False
    if canonical_contract_key(trade.symbol, trade.entry_timestamp) != canonical_contract_key(
        item.symbol, item.entry_timestamp
    ):
        return False
    price_tolerance = (item.tick_size or Decimal("0.00000001")) / Decimal("2")
    if abs(Decimal(trade.entry_price) - item.entry_price) > price_tolerance:
        return False
    if abs(Decimal(trade.exit_price) - item.exit_price) > price_tolerance:
        return False
    if abs((_as_utc(trade.entry_timestamp) - _as_utc(item.entry_timestamp)).total_seconds()) > MATCH_TIME_TOLERANCE_SECONDS:
        return False
    if abs((_as_utc(trade.exit_timestamp) - _as_utc(item.exit_timestamp)).total_seconds()) > MATCH_TIME_TOLERANCE_SECONDS:
        return False
    return True


def _legacy_components(trades: list[Trade], item: CanonicalTrade) -> list[Trade]:
    result: list[Trade] = []
    for trade in trades:
        if _is_live_trade(trade) or trade.source_quality == "manual":
            continue
        fill_ids = _trade_fill_ids(trade)
        if fill_ids and fill_ids.issubset(item.fill_ids):
            result.append(trade)
    return result


def _find_preferred_existing_trade(
    trades: list[Trade], item: CanonicalTrade
) -> tuple[Trade | None, list[Trade]]:
    lifecycle_matches = [trade for trade in trades if _same_lifecycle(trade, item)]
    live_matches = [trade for trade in lifecycle_matches if _is_live_trade(trade)]
    exact = next(
        (trade for trade in trades if trade.duplicate_fingerprint == item.fingerprint),
        None,
    )
    components = _legacy_components(trades, item)
    if live_matches:
        return live_matches[0], components
    if exact is not None:
        return exact, components
    if lifecycle_matches:
        return lifecycle_matches[0], components
    if components:
        # Keep an already-existing imported trade ID where possible. The chosen row
        # is promoted to the flat-to-flat lifecycle and the other lot-pair rows are
        # safely collapsed into it during commit.
        return components[0], components
    return None, components


def _has_user_trade_content(db: Session, trade_id: Any) -> bool:
    checks = (
        TradeJournal,
        TradeTag,
        TradePlaybook,
        TradeChecklistResponse,
        Attachment,
        RuleViolation,
    )
    for model in checks:
        if db.scalar(select(model).where(model.trade_id == trade_id).limit(1)) is not None:
            return True
    return False


def _merge_disposable_trade(db: Session, target: Trade, duplicate: Trade) -> bool:
    if target.id == duplicate.id:
        return True
    if _has_user_trade_content(db, duplicate.id):
        return False
    for fill in db.scalars(select(Fill).where(Fill.trade_id == duplicate.id)).all():
        fill.trade_id = target.id
    for capture in db.scalars(
        select(CaptureEvent).where(CaptureEvent.matched_trade_id == duplicate.id)
    ).all():
        capture.matched_trade_id = target.id
    for episode in db.scalars(
        select(TradingEpisode).where(TradingEpisode.matched_trade_id == duplicate.id)
    ).all():
        episode.matched_trade_id = target.id
    db.delete(duplicate)
    db.flush()
    return True


def _join_external_ids(values: set[str]) -> str | None:
    joined = ",".join(sorted(values))
    return joined if joined and len(joined) <= 120 else None


def _enrich_trade_from_import(
    trade: Trade, item: CanonicalTrade, import_session: ImportSession
) -> None:
    was_live = _is_live_trade(trade)
    payload = dict(trade.source_payload or {})
    import_sessions = payload.get("import_session_ids")
    if not isinstance(import_sessions, list):
        import_sessions = []
    session_id = str(import_session.id)
    if session_id not in import_sessions:
        import_sessions.append(session_id)
    warnings = list(
        dict.fromkeys(
            [
                *(payload.get("warnings") if isinstance(payload.get("warnings"), list) else []),
                *item.warnings,
            ]
        )
    )
    payload.update(
        {
            "import_session_ids": import_sessions,
            "tradovate_reconciliation": item.source_payload,
            "canonical_contract": canonical_contract_key(item.symbol, item.entry_timestamp),
            "warnings": warnings,
        }
    )

    if not was_live:
        trade.primary_import_session_id = trade.primary_import_session_id or import_session.id
        trade.duplicate_fingerprint = item.fingerprint
        trade.symbol = item.symbol
    trade.external_position_id = item.external_position_id or trade.external_position_id
    trade.external_pair_id = item.external_pair_id or trade.external_pair_id
    trade.external_buy_fill_id = _join_external_ids(item.buy_fill_ids)
    trade.external_sell_fill_id = _join_external_ids(item.sell_fill_ids)
    trade.root_symbol = root_symbol(item.symbol)
    trade.product = item.product or trade.product
    trade.product_description = item.product_description or trade.product_description
    trade.contract_quantity = item.quantity
    trade.side = item.side
    trade.entry_price = item.entry_price
    trade.exit_price = item.exit_price
    paired_rows = item.source_payload.get("paired_rows")
    has_pnl_evidence = isinstance(paired_rows, list) and bool(paired_rows)
    if has_pnl_evidence or not was_live:
        trade.gross_pnl = item.gross_pnl
    trade.fees = item.fees
    trade.net_pnl = (
        trade.gross_pnl - item.fees
        if item.fees is not None
        else (item.net_pnl if has_pnl_evidence or not was_live else trade.gross_pnl)
    )
    trade.currency = item.currency
    trade.entry_timestamp = item.entry_timestamp
    trade.exit_timestamp = item.exit_timestamp
    trade.duration_seconds = item.duration_seconds
    trade.tick_size = item.tick_size or trade.tick_size
    trade.source_quality = "multi_source_reconciled" if was_live else item.source_quality
    trade.reconciliation_status = item.reconciliation_status
    trade.source_payload = payload



def build_preview(
    reports: list[ParsedReport],
    db: Session,
    account: TradingAccount | None,
) -> dict[str, Any]:
    accounts = sorted({value for report in reports for value in detected_accounts(report)})
    starts, ends = zip(*(report_date_coverage(report) for report in reports), strict=False)
    coverage_start = min((value for value in starts if value), default=None)
    coverage_end = max((value for value in ends if value), default=None)
    warnings = [warning for report in reports for warning in report.warnings]
    errors = [
        error.as_dict() for report in reports for error in report.errors
    ]
    if len(accounts) > 1:
        warnings.append("Multiple source accounts were detected; select a destination account.")
    if (
        account
        and account.external_account_id
        and accounts
        and accounts != [account.external_account_id]
    ):
        warnings.append(
            "The detected broker account does not match the selected JournalMe account."
        )
    account_identity = (
        account.external_account_id
        if account
        else (accounts[0] if accounts else "unknown")
    )
    commit_safe_reports = [report for report in reports if not report.errors]
    canonical = reconcile_completed_trades(
        commit_safe_reports,
        account_identity or str(account.id) if account else account_identity,
        account.timezone if account else "America/New_York",
    )
    existing_trade_rows: list[Trade] = []
    if account:
        existing_trade_rows = list(
            db.scalars(select(Trade).where(Trade.account_id == account.id)).all()
        )
    existing_flags = [
        _find_preferred_existing_trade(existing_trade_rows, trade)[0] is not None
        for trade in canonical
    ]

    paired_fill_ids = {fill_id for trade in canonical for fill_id in trade.fill_ids}
    all_fill_ids = {
        row_get(row, "Fill ID", "_id")
        for report in reports
        if report.report_type is ReportType.FILLS
        for row in report.rows
        if row_get(row, "Fill ID", "_id")
    }
    fill_order_ids = {
        row_get(row, "Order ID", "_orderId")
        for report in reports
        if report.report_type is ReportType.FILLS
        for row in report.rows
        if row_get(row, "Order ID", "_orderId")
    }
    normalized_orders = [
        row
        for report in reports
        if report.report_type is ReportType.ORDERS
        for row in report.normalized_rows
        if isinstance(row, NormalizedOrderRow)
    ]
    linked_filled_orders = sum(
        order.status == "filled" and order.external_order_id in fill_order_ids
        for order in normalized_orders
    )
    canceled_unfilled_orders = sum(
        order.status != "filled" for order in normalized_orders
    )
    unmatched_filled_orders = sum(
        order.status == "filled" and order.external_order_id not in fill_order_ids
        for order in normalized_orders
    )
    if unmatched_filled_orders:
        warnings.append(
            f"{unmatched_filled_orders} filled order(s) could not be linked to fills."
        )
    exact_duplicates = sum(exact_duplicate_count(report.rows) for report in reports)
    paired_source_counts = []
    for report in reports:
        if report.report_type in {
            ReportType.PERFORMANCE,
            ReportType.POSITION_HISTORY,
        }:
            paired_source_counts.append(
                len(
                    {
                        json.dumps(row, sort_keys=True, separators=(",", ":"))
                        for row in report.rows
                    }
                )
            )
    lifecycle_consolidations = max(
        0, max(paired_source_counts, default=0) - len(canonical)
    )
    duplicate_rows = exact_duplicates
    if lifecycle_consolidations:
        warnings.append(
            f"{lifecycle_consolidations} paired lot row(s) were consolidated into flat-to-flat trade lifecycles."
        )
    return {
        "reports": [
            {
                "filename": report.filename,
                "type": report.report_type.value,
                "rows": len(report.rows),
                "duplicate_rows": exact_duplicate_count(report.rows),
                "status": "skipped"
                if report.report_type is ReportType.ORDER_DETAILS_EMPTY
                else ("error" if report.errors else "recognized"),
            }
            for report in reports
        ],
        "coverage": {
            "start": coverage_start.isoformat() if coverage_start else None,
            "end": coverage_end.isoformat() if coverage_end else None,
        },
        "detected_accounts": accounts,
        "canonical_trades": len(canonical),
        "new_trades": sum(not flag for flag in existing_flags),
        "existing_trades": sum(existing_flags),
        "paired_rows_consolidated": lifecycle_consolidations,
        "duplicate_rows": duplicate_rows,
        "unmatched_fills": len(all_fill_ids - paired_fill_ids),
        "linked_filled_orders": linked_filled_orders,
        "canceled_unfilled_orders": canceled_unfilled_orders,
        "unmatched_filled_orders": unmatched_filled_orders,
        # Retained for older clients; now means genuinely unmatched filled orders.
        "unmatched_orders": unmatched_filled_orders,
        "warnings": warnings + [warning for trade in canonical for warning in trade.warnings],
        "errors": errors,
    }


def load_session_reports(import_session: ImportSession, storage: FileStorage) -> list[ParsedReport]:
    from app.services.importer import parse_report

    return [
        parse_report(file.filename, storage.read(file.stored_path))
        for file in import_session.files
    ]


def resolve_account(
    db: Session,
    user: User,
    import_session: ImportSession,
    reports: list[ParsedReport],
) -> TradingAccount:
    if import_session.account_id:
        account = db.get(TradingAccount, import_session.account_id)
        if account and account.user_id == user.id:
            external_ids = sorted(
                {value for report in reports for value in detected_accounts(report)}
            )
            if len(external_ids) > 1:
                raise ValueError("A single import cannot contain multiple broker accounts.")
            if external_ids and account.external_account_id not in {None, external_ids[0]}:
                raise ValueError(
                    "The detected broker account does not match the selected account."
                )
            if external_ids and account.external_account_id is None:
                account.external_account_id = external_ids[0]
            return account
        raise ValueError("The selected account is unavailable.")
    external_ids = sorted(
        {value for report in reports for value in detected_accounts(report)}
    )
    if len(external_ids) != 1:
        raise ValueError("Select an account when reports contain zero or multiple account IDs.")
    external_id = external_ids[0]
    account = db.scalar(
        select(TradingAccount).where(
            TradingAccount.user_id == user.id,
            TradingAccount.provider == "tradovate",
            TradingAccount.external_account_id == external_id,
        )
    )
    if account:
        return account
    account = TradingAccount(
        user_id=user.id,
        external_account_id=external_id,
        name=f"Tradovate ••••{external_id[-4:]}",
        provider="tradovate",
        account_type=AccountType.SIMULATED,
    )
    db.add(account)
    db.flush()
    return account


def commit_import(
    db: Session,
    user: User,
    import_session: ImportSession,
    storage: FileStorage,
) -> dict[str, int]:
    if import_session.status is ImportStatus.COMMITTED:
        return import_session.summary_json.get("commit", {})
    if import_session.status not in {ImportStatus.PENDING, ImportStatus.READY}:
        raise ValueError("Only a pending import can be committed.")
    reports = load_session_reports(import_session, storage)
    validation_errors = [
        error for report in reports for error in report.errors
    ]
    if validation_errors:
        raise ImportReportValidationError(validation_errors)
    account = resolve_account(db, user, import_session, reports)
    import_session.account_id = account.id
    counts = {
        "trades": 0,
        "fills": 0,
        "orders": 0,
        "cash_transactions": 0,
        "daily_balances": 0,
    }

    canonical = reconcile_completed_trades(
        reports, account.external_account_id or str(account.id), account.timezone
    )
    trade_by_fill: dict[str, Trade] = {}
    existing_trades = list(
        db.scalars(select(Trade).where(Trade.account_id == account.id)).all()
    )
    reconciled_trades = 0
    collapsed_legacy_trades = 0
    reconciliation_warnings: list[str] = []

    for item in canonical:
        trade, components = _find_preferred_existing_trade(existing_trades, item)
        if trade is None:
            trade = Trade(
                account_id=account.id,
                primary_import_session_id=import_session.id,
                external_position_id=item.external_position_id,
                external_pair_id=item.external_pair_id,
                external_buy_fill_id=_join_external_ids(item.buy_fill_ids),
                external_sell_fill_id=_join_external_ids(item.sell_fill_ids),
                duplicate_fingerprint=item.fingerprint,
                symbol=item.symbol,
                root_symbol=root_symbol(item.symbol),
                product=item.product,
                product_description=item.product_description,
                contract_quantity=item.quantity,
                side=item.side,
                entry_price=item.entry_price,
                exit_price=item.exit_price,
                gross_pnl=item.gross_pnl,
                fees=item.fees,
                net_pnl=item.net_pnl,
                currency=item.currency,
                entry_timestamp=item.entry_timestamp,
                exit_timestamp=item.exit_timestamp,
                duration_seconds=item.duration_seconds,
                tick_size=item.tick_size,
                source_quality=item.source_quality,
                reconciliation_status=item.reconciliation_status,
                source_payload={
                    **item.source_payload,
                    "canonical_contract": canonical_contract_key(
                        item.symbol, item.entry_timestamp
                    ),
                    "import_session_ids": [str(import_session.id)],
                },
            )
            db.add(trade)
            db.flush()
            existing_trades.append(trade)
            counts["trades"] += 1
        else:
            # The preferred target may be an existing live trade or one of the old
            # Tradovate lot-pair rows. Collapse only duplicate rows that do not
            # contain user-authored JournalMe content.
            for component in list(components):
                if component.id == trade.id:
                    continue
                if _merge_disposable_trade(db, trade, component):
                    collapsed_legacy_trades += 1
                    existing_trades = [
                        candidate
                        for candidate in existing_trades
                        if candidate.id != component.id
                    ]
                else:
                    reconciliation_warnings.append(
                        "A legacy imported trade with journal content was preserved instead "
                        "of being auto-collapsed. Review it manually after import."
                    )
            _enrich_trade_from_import(trade, item, import_session)
            db.flush()
            reconciled_trades += 1

        for fill_id in item.fill_ids:
            trade_by_fill[fill_id] = trade

    for report, import_file in zip(reports, import_session.files, strict=True):
        if report.report_type is ReportType.FILLS:
            counts["fills"] += _persist_fills(
                db, account, import_file, report, trade_by_fill
            )
        elif report.report_type is ReportType.ORDERS:
            counts["orders"] += _persist_orders(db, account, import_file, report)
        elif report.report_type is ReportType.CASH_HISTORY:
            counts["cash_transactions"] += _persist_cash(
                db, account, import_file, report
            )
        elif report.report_type is ReportType.BALANCE_HISTORY:
            counts["daily_balances"] += _persist_balances(
                db, account, import_file, report
            )

    import_session.status = ImportStatus.COMMITTED
    import_session.committed_at = utcnow()
    import_session.summary_json = {
        **import_session.summary_json,
        "commit": counts,
        "account_id": str(account.id),
        "reconciled_trades": reconciled_trades,
        "collapsed_legacy_trades": collapsed_legacy_trades,
        "reconciliation_warnings": list(dict.fromkeys(reconciliation_warnings)),
    }
    db.flush()
    # One final account-wide pass makes old lot-pair rows obey the same flat ->
    # position -> flat trade definition used by new imports and live ingestion.
    ledger_report = reconcile_trade_ledger(db, account)
    import_session.summary_json = {
        **import_session.summary_json,
        "ledger_reconciliation": ledger_report,
    }
    # Newly imported canonical trades may resolve Companion captures recorded earlier.
    reconcile_unmatched_captures(db, user.id, account_id=account.id)
    db.flush()
    return counts


def _persist_fills(
    db: Session,
    account: TradingAccount,
    import_file: ImportFile,
    report: ParsedReport,
    trade_by_fill: dict[str, Trade],
) -> int:
    created = 0
    for row in report.normalized_rows:
        if not isinstance(row, NormalizedFillRow):
            continue
        existing_fill = db.scalar(
            select(Fill).where(
                Fill.account_id == account.id,
                Fill.external_fill_id == row.external_fill_id,
            )
        )
        if existing_fill is not None:
            target_trade = trade_by_fill.get(row.external_fill_id)
            if target_trade is not None and existing_fill.trade_id != target_trade.id:
                existing_fill.trade_id = target_trade.id
            if existing_fill.commission is None and row.commission is not None:
                existing_fill.commission = row.commission
            continue
        fill = Fill(
            account_id=account.id,
            import_file_id=import_file.id,
            external_fill_id=row.external_fill_id,
            external_order_id=row.external_order_id,
            trade_id=(
                trade_by_fill[row.external_fill_id].id
                if row.external_fill_id in trade_by_fill
                else None
            ),
            symbol=row.symbol,
            action=row.action,
            quantity=row.quantity,
            price=row.price,
            commission=row.commission,
            timestamp=row.timestamp,
            trade_date=row.trade_date,
            product=row.product,
            product_description=row.product_description,
            source_payload=row.source_payload,
        )
        db.add(fill)
        created += 1
    return created


def _persist_orders(
    db: Session,
    account: TradingAccount,
    import_file: ImportFile,
    report: ParsedReport,
) -> int:
    created = 0
    for row in report.normalized_rows:
        if not isinstance(row, NormalizedOrderRow):
            continue
        if db.scalar(
            select(Order.id).where(
                Order.account_id == account.id,
                Order.external_order_id == row.external_order_id,
            )
        ):
            continue
        order = Order(
            account_id=account.id,
            import_file_id=import_file.id,
            external_order_id=row.external_order_id,
            side=row.side,
            symbol=row.symbol,
            order_type=row.order_type,
            status=row.status,
            requested_quantity=row.requested_quantity,
            filled_quantity=row.filled_quantity,
            limit_price=row.limit_price,
            stop_price=row.stop_price,
            average_fill_price=row.average_fill_price,
            venue=row.venue,
            submitted_timestamp=row.submitted_timestamp,
            fill_timestamp=row.fill_timestamp,
            source_payload=row.source_payload,
        )
        db.add(order)
        created += 1
    return created


def _persist_cash(
    db: Session,
    account: TradingAccount,
    import_file: ImportFile,
    report: ParsedReport,
) -> int:
    created = 0
    for row in report.normalized_rows:
        if not isinstance(row, NormalizedCashRow):
            continue
        if db.scalar(
            select(CashTransaction.id).where(
                CashTransaction.account_id == account.id,
                CashTransaction.external_transaction_id
                == row.external_transaction_id,
            )
        ):
            continue
        db.add(
            CashTransaction(
                account_id=account.id,
                import_file_id=import_file.id,
                external_transaction_id=row.external_transaction_id,
                timestamp=row.timestamp,
                trade_date=row.trade_date,
                delta=row.delta,
                amount=row.amount,
                cash_change_type=row.cash_change_type,
                currency=row.currency or account.currency,
                contract=row.contract,
                source_payload=row.source_payload,
            )
        )
        created += 1
    return created


def _persist_balances(
    db: Session,
    account: TradingAccount,
    import_file: ImportFile,
    report: ParsedReport,
) -> int:
    created = 0
    for row in report.normalized_rows:
        if not isinstance(row, NormalizedBalanceRow):
            continue
        source_identity = (
            f"tradovate:{row.source_account_id or row.source_account_name or 'unknown'}"
        )
        if db.scalar(
            select(DailyBalance.id).where(
                DailyBalance.account_id == account.id,
                DailyBalance.trade_date == row.trade_date,
                DailyBalance.source_identity == source_identity,
            )
        ):
            continue
        db.add(
            DailyBalance(
                account_id=account.id,
                import_file_id=import_file.id,
                trade_date=row.trade_date,
                total_amount=row.total_amount,
                total_realized_pnl=row.total_realized_pnl,
                source_identity=source_identity,
                source_payload=row.source_payload,
            )
        )
        created += 1
    return created
