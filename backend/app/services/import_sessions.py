from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AccountType,
    CashTransaction,
    DailyBalance,
    Fill,
    ImportFile,
    ImportSession,
    ImportStatus,
    Order,
    Trade,
    TradingAccount,
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
from app.services.reconciliation import reconcile_completed_trades
from app.storage import FileStorage


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
    existing: set[str] = set()
    if account:
        existing = set(
            db.scalars(
                select(Trade.duplicate_fingerprint).where(Trade.account_id == account.id)
            ).all()
        )

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
    identity_merges = max(
        0, max(paired_source_counts, default=0) - len(canonical)
    )
    duplicate_rows = exact_duplicates + identity_merges
    if identity_merges:
        warnings.append(
            f"{identity_merges} completed-trade row(s) were merged by shared fill identity."
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
        "new_trades": sum(trade.fingerprint not in existing for trade in canonical),
        "existing_trades": sum(trade.fingerprint in existing for trade in canonical),
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
    for item in canonical:
        trade = db.scalar(
            select(Trade).where(
                Trade.account_id == account.id,
                Trade.duplicate_fingerprint == item.fingerprint,
            )
        )
        if trade is None:
            trade = Trade(
                account_id=account.id,
                primary_import_session_id=import_session.id,
                external_position_id=item.external_position_id,
                external_pair_id=item.external_pair_id,
                external_buy_fill_id=",".join(sorted(item.buy_fill_ids)) or None,
                external_sell_fill_id=",".join(sorted(item.sell_fill_ids)) or None,
                duplicate_fingerprint=item.fingerprint,
                symbol=item.symbol,
                root_symbol=_root_symbol(item.symbol),
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
                source_payload=item.source_payload,
            )
            db.add(trade)
            db.flush()
            counts["trades"] += 1
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
    }
    db.flush()
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
        if db.scalar(
            select(Fill.id).where(
                Fill.account_id == account.id,
                Fill.external_fill_id == row.external_fill_id,
            )
        ):
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

def _root_symbol(symbol: str) -> str:
    return re.sub(r"[FGHJKMNQUVXZ]\d{1,2}$", "", symbol) or symbol
