from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.domain import TradeSide

MONEY = Numeric(18, 4)
PRICE = Numeric(18, 8)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AccountType(str, PyEnum):
    EVALUATION = "evaluation"
    FUNDED = "funded"
    PERSONAL = "personal"
    SIMULATED = "simulated"


class AccountLifecycleStatus(str, PyEnum):
    ACTIVE = "active"
    PASSED = "passed"
    FUNDED = "funded"
    BLOWN = "blown"
    CLOSED = "closed"


class ImportStatus(str, PyEnum):
    PENDING = "pending"
    READY = "ready"
    COMMITTED = "committed"
    CANCELED = "canceled"
    FAILED = "failed"


class TagCategory(str, PyEnum):
    SETUP = "setup"
    CONFLUENCE = "confluence"
    MISTAKE = "mistake"
    EMOTION = "emotion"
    CUSTOM = "custom"


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    accounts: Mapped[list[TradingAccount]] = relationship(back_populates="user")


class AuthIdentity(Base):
    __tablename__ = "auth_identities"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    subject: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_auth_identity_subject"),)


class TradingAccount(Base):
    __tablename__ = "trading_accounts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    external_account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    provider: Mapped[str] = mapped_column(String(60), default="tradovate")
    account_type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, native_enum=False), default=AccountType.SIMULATED
    )
    starting_balance: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), default="America/New_York")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    include_in_learning: Mapped[bool] = mapped_column(Boolean, default=True)
    lifecycle_status: Mapped[AccountLifecycleStatus] = mapped_column(
        Enum(
            AccountLifecycleStatus,
            native_enum=False,
            length=20,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=AccountLifecycleStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="accounts")
    trades: Mapped[list[Trade]] = relationship(back_populates="account")

    __table_args__ = (
        UniqueConstraint("user_id", "provider", "external_account_id", name="uq_account_external"),
    )


class BrokerConnection(Base):
    __tablename__ = "broker_connections"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(60))
    connection_type: Mapped[str] = mapped_column(String(40), default="desktop_bridge")
    display_name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="disconnected", index=True)
    external_account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    bridge_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bridge_token_prefix: Mapped[str | None] = mapped_column(String(24), nullable=True)
    bridge_token_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", "connection_type", "external_account_id",
            name="uq_broker_connection_external",
        ),
    )


class BrokerExecutionEvent(Base):
    __tablename__ = "broker_execution_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("broker_connections.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(60), index=True)
    external_execution_id: Mapped[str] = mapped_column(String(160))
    external_order_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    symbol: Mapped[str] = mapped_column(String(80), index=True)
    side: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    price: Mapped[Decimal] = mapped_column(PRICE)
    commission: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    point_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingest_status: Mapped[str] = mapped_column(String(30), default="received", index=True)
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint(
            "connection_id", "external_execution_id", name="uq_broker_execution_external"
        ),
        Index("ix_broker_execution_account_time", "account_id", "executed_at"),
    )


class ImportSession(Base):
    __tablename__ = "import_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_provider: Mapped[str] = mapped_column(String(60), default="tradovate")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, native_enum=False), default=ImportStatus.PENDING
    )
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    files: Mapped[list[ImportFile]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ImportFile(Base):
    __tablename__ = "import_files"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    import_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    detected_report_type: Mapped[str] = mapped_column(String(80))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="ready")
    stored_path: Mapped[str] = mapped_column(String(512))
    header_signature: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ImportSession] = relationship(back_populates="files")

    __table_args__ = (
        UniqueConstraint("import_session_id", "content_hash", name="uq_session_file_hash"),
    )


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    primary_import_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("import_sessions.id", ondelete="SET NULL"), nullable=True
    )
    external_position_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_pair_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_buy_fill_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_sell_fill_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    duplicate_fingerprint: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(80), index=True)
    root_symbol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    product: Mapped[str | None] = mapped_column(String(80), nullable=True)
    product_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contract_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide, native_enum=False))
    entry_price: Mapped[Decimal] = mapped_column(PRICE)
    exit_price: Mapped[Decimal] = mapped_column(PRICE)
    gross_pnl: Mapped[Decimal] = mapped_column(MONEY)
    fees: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    net_pnl: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    exit_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tick_size: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    source_quality: Mapped[str] = mapped_column(String(40), default="paired_report")
    reconciliation_status: Mapped[str] = mapped_column(String(40), default="reconciled")
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    account: Mapped[TradingAccount] = relationship(back_populates="trades")
    fills: Mapped[list[Fill]] = relationship(back_populates="trade")
    journal: Mapped[TradeJournal | None] = relationship(
        back_populates="trade", uselist=False, cascade="all, delete-orphan"
    )
    tags: Mapped[list[Tag]] = relationship(secondary="trade_tags", back_populates="trades")
    playbooks: Mapped[list[TradePlaybook]] = relationship(
        back_populates="trade", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("account_id", "duplicate_fingerprint", name="uq_trade_fingerprint"),
        Index("ix_trade_account_entry", "account_id", "entry_timestamp"),
    )


class Fill(Base):
    __tablename__ = "fills"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    import_file_id: Mapped[UUID] = mapped_column(ForeignKey("import_files.id"))
    external_fill_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    trade_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"), nullable=True, index=True
    )
    symbol: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    price: Mapped[Decimal] = mapped_column(PRICE)
    commission: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trade_date: Mapped[date] = mapped_column(Date)
    product: Mapped[str | None] = mapped_column(String(80), nullable=True)
    product_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    trade: Mapped[Trade | None] = relationship(back_populates="fills")

    __table_args__ = (
        UniqueConstraint("account_id", "external_fill_id", name="uq_fill_external"),
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    import_file_id: Mapped[UUID] = mapped_column(ForeignKey("import_files.id"))
    external_order_id: Mapped[str] = mapped_column(String(120))
    side: Mapped[str] = mapped_column(String(10))
    symbol: Mapped[str] = mapped_column(String(80))
    order_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(40))
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    filled_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6), nullable=True
    )
    limit_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    average_fill_price: Mapped[Decimal | None] = mapped_column(PRICE, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(80), nullable=True)
    submitted_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fill_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("account_id", "external_order_id", name="uq_order_external"),
    )


class CashTransaction(Base):
    __tablename__ = "cash_transactions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    import_file_id: Mapped[UUID] = mapped_column(ForeignKey("import_files.id"))
    external_transaction_id: Mapped[str] = mapped_column(String(120))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trade_date: Mapped[date] = mapped_column(Date)
    delta: Mapped[Decimal] = mapped_column(MONEY)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    cash_change_type: Mapped[str] = mapped_column(String(80))
    currency: Mapped[str] = mapped_column(String(3))
    contract: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("account_id", "external_transaction_id", name="uq_cash_external"),
    )


class DailyBalance(Base):
    __tablename__ = "daily_balances"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    import_file_id: Mapped[UUID] = mapped_column(ForeignKey("import_files.id"))
    trade_date: Mapped[date] = mapped_column(Date)
    total_amount: Mapped[Decimal] = mapped_column(MONEY)
    total_realized_pnl: Mapped[Decimal] = mapped_column(MONEY)
    source_identity: Mapped[str] = mapped_column(String(120), default="tradovate")
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "account_id", "trade_date", "source_identity", name="uq_daily_balance_source"
        ),
    )


class TradeJournal(Base):
    __tablename__ = "trade_journals"

    trade_id: Mapped[UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True
    )
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_went_well: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_went_wrong: Mapped[str | None] = mapped_column(Text, nullable=True)
    lesson_learned: Mapped[str | None] = mapped_column(Text, nullable=True)
    best_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    worst_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discipline_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    patience_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trade_grade: Mapped[str | None] = mapped_column(String(3), nullable=True)
    followed_plan: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pre_trade_emotion: Mapped[str | None] = mapped_column(String(80), nullable=True)
    post_trade_emotion: Mapped[str | None] = mapped_column(String(80), nullable=True)
    market_condition: Mapped[str | None] = mapped_column(String(120), nullable=True)
    session_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    custom_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    trade: Mapped[Trade] = relationship(back_populates="journal")


class DailyJournal(Base):
    __tablename__ = "daily_journals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    trading_date: Mapped[date] = mapped_column(Date)
    pre_session_mindset: Mapped[str | None] = mapped_column(Text, nullable=True)
    pre_session_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    daily_bias: Mapped[str | None] = mapped_column(Text, nullable=True)
    important_events: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_daily_loss: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    daily_goal: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_trades: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allowed_playbook_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    prohibited_behaviors: Mapped[list[str]] = mapped_column(JSON, default=list)
    checklist_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    quick_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quick_focus_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    quick_emotion_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    quick_behavior_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    quick_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_depth: Mapped[str] = mapped_column(String(20), default="quick")
    post_session_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day_grade: Mapped[str | None] = mapped_column(String(3), nullable=True)
    best_decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    biggest_mistake: Mapped[str | None] = mapped_column(Text, nullable=True)
    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_worked: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_did_not_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    lesson_learned: Mapped[str | None] = mapped_column(Text, nullable=True)
    focus_for_next_session: Mapped[str | None] = mapped_column(Text, nullable=True)
    followed_rules: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tomorrow_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("account_id", "trading_date", name="uq_daily_journal_date"),
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[TagCategory] = mapped_column(Enum(TagCategory, native_enum=False))
    display_token: Mapped[str] = mapped_column(String(40), default="sage")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    trades: Mapped[list[Trade]] = relationship(secondary="trade_tags", back_populates="tags")

    __table_args__ = (UniqueConstraint("user_id", "name", "category", name="uq_tag_name"),)


class TradeTag(Base):
    __tablename__ = "trade_tags"

    trade_id: Mapped[UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    trade_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), nullable=True
    )
    daily_journal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("daily_journals.id", ondelete="CASCADE"), nullable=True
    )
    playbook_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("playbooks.id", ondelete="CASCADE"), nullable=True
    )
    storage_key: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    caption: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TradingEpisode(Base):
    __tablename__ = "trading_episodes"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    matched_trade_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"), nullable=True, index=True
    )
    symbol: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    source: Mapped[str] = mapped_column(String(80), default="journalme_companion")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    moments: Mapped[list[CaptureEvent]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_trading_episodes_user_started", "user_id", "started_at"),
        Index("ix_trading_episodes_user_status", "user_id", "status"),
    )


class CaptureEvent(Base):
    __tablename__ = "capture_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    episode_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_episodes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event_type: Mapped[str] = mapped_column(String(20), index=True)
    phase: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    recorded_live: Mapped[bool] = mapped_column(Boolean, default=True)
    symbol: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    side: Mapped[str | None] = mapped_column(String(10), nullable=True)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    setup_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    execution_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    emotion_tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    platform: Mapped[str | None] = mapped_column(String(80), nullable=True)
    page_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    page_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="journalme_chrome_extension")
    screenshot_storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    screenshot_original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    screenshot_mime: Mapped[str | None] = mapped_column(String(120), nullable=True)
    match_status: Mapped[str] = mapped_column(String(30), default="unmatched", index=True)
    matched_trade_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trades.id", ondelete="SET NULL"), nullable=True, index=True
    )
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    match_method: Mapped[str | None] = mapped_column(String(80), nullable=True)

    episode: Mapped[TradingEpisode | None] = relationship(back_populates="moments")

    __table_args__ = (
        Index("ix_capture_events_user_captured", "user_id", "captured_at"),
        Index("ix_capture_events_user_match", "user_id", "match_status"),
    )


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    period_type: Mapped[str] = mapped_column(String(20))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    target_pnl: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    target_journal_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    custom_goal_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    goal_type: Mapped[str] = mapped_column(String(40), default="pnl_target")
    target_value: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active")


class PropPreset(Base):
    __tablename__ = "prop_presets"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    preset_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(80))
    plan_family: Mapped[str] = mapped_column(String(80))
    account_phase: Mapped[str] = mapped_column(String(40))
    account_size: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    display_name: Mapped[str] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    versions: Mapped[list[PropPresetVersion]] = relationship(
        back_populates="preset",
        cascade="all, delete-orphan",
        order_by="PropPresetVersion.version_number",
    )


class PropPresetVersion(Base):
    __tablename__ = "prop_preset_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    preset_id: Mapped[UUID] = mapped_column(
        ForeignKey("prop_presets.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    effective_date: Mapped[date] = mapped_column(Date)
    source_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    required_fields_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    optional_fields_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    preset: Mapped[PropPreset] = relationship(back_populates="versions")
    scaling_tiers: Mapped[list[PropPresetScalingTier]] = relationship(
        back_populates="preset_version",
        cascade="all, delete-orphan",
        order_by="PropPresetScalingTier.lower_profit_bound",
    )

    __table_args__ = (
        UniqueConstraint(
            "preset_id", "version_number", name="uq_prop_preset_version"
        ),
    )


class PropPresetScalingTier(Base):
    __tablename__ = "prop_preset_scaling_tiers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    preset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("prop_preset_versions.id", ondelete="CASCADE"), index=True
    )
    lower_profit_bound: Mapped[Decimal] = mapped_column(MONEY)
    upper_profit_bound: Mapped[Decimal | None] = mapped_column(
        MONEY, nullable=True
    )
    max_mini_contracts: Mapped[int] = mapped_column(Integer)
    max_micro_contracts: Mapped[int] = mapped_column(Integer)

    preset_version: Mapped[PropPresetVersion] = relationship(
        back_populates="scaling_tiers"
    )


class PropRuleProfile(Base):
    __tablename__ = "prop_rule_profiles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), unique=True
    )
    firm_name: Mapped[str] = mapped_column(String(160))
    account_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    profile_account_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    starting_balance: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    profit_target: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    max_loss: Mapped[Decimal] = mapped_column(MONEY)
    daily_loss_limit: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    consistency_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    drawdown_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    drawdown_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    drawdown_lock_behavior: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payout_buffer: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    minimum_trading_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qualifying_profit_days_required: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    minimum_profit_per_qualifying_day: Mapped[Decimal | None] = mapped_column(
        MONEY, nullable=True
    )
    payout_cycle_net_profit_required: Mapped[bool] = mapped_column(
        Boolean, default=True
    )
    minimum_payout: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    payout_profit_percentage: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    maximum_payout: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    maximum_payout_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profit_split_trader_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    profit_split_firm_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    no_fixed_payout_window: Mapped[bool] = mapped_column(Boolean, default=False)
    payout_cycle_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    qualifying_days_since_last_payout: Mapped[int] = mapped_column(Integer, default=0)
    payouts_completed: Mapped[int] = mapped_column(Integer, default=0)
    preset_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    preset_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prop_preset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    configuration_state: Mapped[str] = mapped_column(
        String(30), default="configured"
    )
    evaluation_drawdown_choice: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    daily_loss_limit_enabled: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    daily_loss_limit_amount: Mapped[Decimal | None] = mapped_column(
        MONEY, nullable=True
    )
    initial_trail_balance: Mapped[Decimal | None] = mapped_column(
        MONEY, nullable=True
    )
    locked_mll_balance: Mapped[Decimal | None] = mapped_column(
        MONEY, nullable=True
    )
    payout_buffer_balance_threshold: Mapped[Decimal | None] = mapped_column(
        MONEY, nullable=True
    )
    max_daily_simulated_profit: Mapped[Decimal | None] = mapped_column(
        MONEY, nullable=True
    )
    news_restriction_note: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    live_transition_note: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    purchase_configuration_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    rules_enabled_json: Mapped[dict[str, bool]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    versions: Mapped[list[PropRuleProfileVersion]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="PropRuleProfileVersion.version_number",
    )


class PropRuleProfileVersion(Base):
    __tablename__ = "prop_rule_profile_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("prop_rule_profiles.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    effective_date: Mapped[date] = mapped_column(Date)
    source_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    preset_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prop_preset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    purchase_configuration_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profile: Mapped[PropRuleProfile] = relationship(back_populates="versions")
    scaling_tiers: Mapped[list[PropScalingTier]] = relationship(
        back_populates="profile_version",
        cascade="all, delete-orphan",
        order_by="PropScalingTier.lower_profit_bound",
    )

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "version_number",
            name="uq_prop_rule_profile_version",
        ),
    )


class PropScalingTier(Base):
    __tablename__ = "prop_scaling_tiers"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("prop_rule_profile_versions.id", ondelete="CASCADE"), index=True
    )
    lower_profit_bound: Mapped[Decimal] = mapped_column(MONEY)
    upper_profit_bound: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    max_mini_contracts: Mapped[int] = mapped_column(Integer)
    max_micro_contracts: Mapped[int] = mapped_column(Integer)

    profile_version: Mapped[PropRuleProfileVersion] = relationship(
        back_populates="scaling_tiers"
    )


class PropPayoutCycle(Base):
    __tablename__ = "prop_payout_cycles"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    profile_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("prop_rule_profile_versions.id", ondelete="RESTRICT"), index=True
    )
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    payouts: Mapped[list[PropPayoutRecord]] = relationship(
        back_populates="cycle", cascade="all, delete-orphan"
    )


class PropPayoutRecord(Base):
    __tablename__ = "prop_payout_records"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    cycle_id: Mapped[UUID] = mapped_column(
        ForeignKey("prop_payout_cycles.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    request_date: Mapped[date] = mapped_column(Date)
    approved_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    requested_amount: Mapped[Decimal] = mapped_column(MONEY)
    approved_gross_amount: Mapped[Decimal | None] = mapped_column(
        MONEY, nullable=True
    )
    trader_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    firm_amount: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    cycle: Mapped[PropPayoutCycle] = relationship(back_populates="payouts")


class Playbook(Base):
    __tablename__ = "playbooks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    market_scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direction_scope: Mapped[str | None] = mapped_column(String(40), nullable=True)
    preferred_session: Mapped[str | None] = mapped_column(String(80), nullable=True)
    minimum_confluences: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ideal_entry_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmation_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidation_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_logic: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_logic: Mapped[str | None] = mapped_column(Text, nullable=True)
    management_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    prohibited_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_grade_expectations: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    checklist_items: Mapped[list[PlaybookChecklistItem]] = relationship(
        back_populates="playbook",
        cascade="all, delete-orphan",
        order_by="PlaybookChecklistItem.sort_order",
    )
    trades: Mapped[list[TradePlaybook]] = relationship(
        back_populates="playbook", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_playbook_name"),)


class PlaybookChecklistItem(Base):
    __tablename__ = "playbook_checklist_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    playbook_id: Mapped[UUID] = mapped_column(
        ForeignKey("playbooks.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(80), default="entry")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    playbook: Mapped[Playbook] = relationship(back_populates="checklist_items")
    responses: Mapped[list[TradeChecklistResponse]] = relationship(
        back_populates="checklist_item", cascade="all, delete-orphan"
    )


class TradePlaybook(Base):
    __tablename__ = "trade_playbooks"

    trade_id: Mapped[UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True
    )
    playbook_id: Mapped[UUID] = mapped_column(
        ForeignKey("playbooks.id", ondelete="CASCADE"), primary_key=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    trade: Mapped[Trade] = relationship(back_populates="playbooks")
    playbook: Mapped[Playbook] = relationship(back_populates="trades")

    __table_args__ = (Index("ix_trade_playbook_primary", "trade_id", "is_primary"),)


class TradeChecklistResponse(Base):
    __tablename__ = "trade_checklist_responses"

    trade_id: Mapped[UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), primary_key=True
    )
    checklist_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("playbook_checklist_items.id", ondelete="CASCADE"), primary_key=True
    )
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    checklist_item: Mapped[PlaybookChecklistItem] = relationship(back_populates="responses")


class RuleViolation(Base):
    __tablename__ = "rule_violations"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    trade_id: Mapped[UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), index=True
    )
    playbook_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("playbooks.id", ondelete="SET NULL"), nullable=True
    )
    rule_text: Mapped[str] = mapped_column(String(500))
    severity: Mapped[str] = mapped_column(String(30), default="medium")
    estimated_cost: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WeeklyReview(Base):
    __tablename__ = "weekly_reviews"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    week_start: Mapped[date] = mapped_column(Date)
    written_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_worked: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_failed: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_period_focus: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_period_goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("account_id", "week_start", name="uq_weekly_review_period"),
    )


class MonthlyReview(Base):
    __tablename__ = "monthly_reviews"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    month_start: Mapped[date] = mapped_column(Date)
    written_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_worked: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_failed: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_period_focus: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_period_goals: Mapped[str | None] = mapped_column(Text, nullable=True)
    grade: Mapped[str | None] = mapped_column(String(3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("account_id", "month_start", name="uq_monthly_review_period"),
    )


class AccountGroup(Base):
    __tablename__ = "account_groups"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[list[AccountGroupMember]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_account_group_name"),)


class AccountGroupMember(Base):
    __tablename__ = "account_group_members"

    group_id: Mapped[UUID] = mapped_column(
        ForeignKey("account_groups.id", ondelete="CASCADE"), primary_key=True
    )
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), primary_key=True
    )

    group: Mapped[AccountGroup] = relationship(back_populates="members")


class ManualAdjustment(Base):
    __tablename__ = "manual_adjustments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="CASCADE"), index=True
    )
    adjustment_type: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reason: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(30), default="manual")
    status: Mapped[str] = mapped_column(String(30), default="approved", index=True)
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subscription_hash: Mapped[str] = mapped_column(String(64))
    endpoint: Mapped[str] = mapped_column(Text)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "subscription_hash", name="uq_push_subscription_user_endpoint"
        ),
    )


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="SET NULL"), nullable=True
    )
    notice_key: Mapped[str] = mapped_column(String(220))
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text)
    target_url: Mapped[str] = mapped_column(String(500))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("user_id", "notice_key", name="uq_notification_delivery_notice"),
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    timezone: Mapped[str] = mapped_column(String(80), default="America/New_York")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    week_start: Mapped[int] = mapped_column(Integer, default=1)
    default_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="SET NULL"), nullable=True
    )
    default_date_range: Mapped[str] = mapped_column(String(40), default="this_month")
    pnl_display: Mapped[str] = mapped_column(String(20), default="net")
    density: Mapped[str] = mapped_column(String(20), default="comfortable")
    reduced_motion: Mapped[bool] = mapped_column(Boolean, default=False)
    session_definitions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    review_rules_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notification_preferences_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("trading_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(30))
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
