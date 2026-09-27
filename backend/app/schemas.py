from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.models import AccountLifecycleStatus, AccountType, TagCategory


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    external_account_id: str | None = Field(default=None, max_length=120)
    provider: str = Field(default="tradovate", max_length=60)
    account_type: AccountType = AccountType.SIMULATED
    starting_balance: Decimal | None = None
    timezone: str = "America/New_York"
    currency: str = Field(default="USD", min_length=3, max_length=3)
    notes: str | None = Field(default=None, max_length=5000)
    include_in_learning: bool = True


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    account_type: AccountType | None = None
    starting_balance: Decimal | None = None
    timezone: str | None = None
    active: bool | None = None
    lifecycle_status: AccountLifecycleStatus | None = None
    include_in_learning: bool | None = None
    notes: str | None = Field(default=None, max_length=5000)


class DailyJournalUpdate(BaseModel):
    pre_session_mindset: str | None = None
    pre_session_plan: str | None = None
    daily_bias: str | None = None
    important_events: str | None = None
    max_daily_loss: Decimal | None = None
    daily_goal: Decimal | None = None
    confidence_score: int | None = Field(default=None, ge=1, le=5)
    sleep_quality: int | None = Field(default=None, ge=1, le=5)
    energy_score: int | None = Field(default=None, ge=1, le=5)
    max_trades: int | None = Field(default=None, ge=1, le=100)
    allowed_playbook_ids: list[UUID] | None = None
    prohibited_behaviors: list[str] | None = Field(default=None, max_length=50)
    checklist_json: list[dict[str, object]] | None = Field(default=None, max_length=100)
    quick_rating: Literal["great", "good", "mixed", "bad", "custom"] | None = None
    quick_focus_tags_json: list[str] | None = Field(default=None, max_length=20)
    quick_emotion_tags_json: list[str] | None = Field(default=None, max_length=20)
    quick_behavior_tags_json: list[str] | None = Field(default=None, max_length=20)
    quick_note: str | None = Field(default=None, max_length=2000)
    review_depth: Literal["quick", "deep"] | None = None
    post_session_rating: int | None = Field(default=None, ge=1, le=5)
    day_grade: Literal["A+", "A", "B", "C", "D", "F"] | None = None
    best_decision: str | None = None
    biggest_mistake: str | None = None
    reflection: str | None = None
    what_worked: str | None = None
    what_did_not_work: str | None = None
    lesson_learned: str | None = None
    focus_for_next_session: str | None = None
    followed_rules: bool | None = None
    tomorrow_note: str | None = None


class TradeJournalUpdate(BaseModel):
    thesis: str | None = None
    entry_reason: str | None = None
    exit_reason: str | None = None
    what_went_well: str | None = None
    what_went_wrong: str | None = None
    lesson_learned: str | None = None
    best_decision: str | None = None
    worst_decision: str | None = None
    confidence_score: int | None = Field(default=None, ge=1, le=5)
    discipline_score: int | None = Field(default=None, ge=1, le=5)
    patience_score: int | None = Field(default=None, ge=1, le=5)
    trade_grade: Literal["A+", "A", "B", "C", "D", "F"] | None = None
    followed_plan: bool | None = None
    pre_trade_emotion: str | None = None
    post_trade_emotion: str | None = None
    market_condition: str | None = Field(default=None, max_length=120)
    session_name: str | None = Field(default=None, max_length=80)
    custom_notes: str | None = Field(default=None, max_length=10000)
    mark_reviewed: bool | None = None
    tag_ids: list[UUID] | None = None


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    category: TagCategory
    display_token: str = Field(default="sage", max_length=40)


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    category: TagCategory | None = None
    display_token: str | None = Field(default=None, max_length=40)
    active: bool | None = None


class GoalCreate(BaseModel):
    account_id: UUID
    period_type: Literal["daily", "weekly", "monthly", "custom"]
    start_date: date
    end_date: date
    target_pnl: Decimal | None = None
    target_journal_days: int | None = Field(default=None, ge=1)
    custom_goal_text: str | None = Field(default=None, max_length=500)
    goal_type: Literal[
        "pnl_target",
        "max_daily_loss",
        "max_weekly_loss",
        "journal_completion",
        "a_grade_trades",
        "plan_adherence",
        "max_trades_per_day",
        "mistake_reduction",
        "custom",
    ] = "pnl_target"
    target_value: Decimal | None = None

    model_config = ConfigDict(str_strip_whitespace=True)


class GoalUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    target_pnl: Decimal | None = None
    target_journal_days: int | None = Field(default=None, ge=1)
    custom_goal_text: str | None = Field(default=None, max_length=500)
    goal_type: str | None = Field(default=None, max_length=40)
    target_value: Decimal | None = None
    status: Literal["active", "completed", "archived"] | None = None


class PropScalingTierInput(BaseModel):
    lower_profit_bound: Decimal = Field(ge=0)
    upper_profit_bound: Decimal | None = Field(default=None, ge=0)
    max_mini_contracts: int = Field(ge=0, le=1000)
    max_micro_contracts: int = Field(ge=0, le=10000)

    @field_validator("upper_profit_bound", mode="before")
    @classmethod
    def blank_upper_bound(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def validate_bounds(self) -> PropScalingTierInput:
        if (
            self.upper_profit_bound is not None
            and self.upper_profit_bound < self.lower_profit_bound
        ):
            raise ValueError(
                "upper_profit_bound must be greater than or equal to lower_profit_bound"
            )
        return self


class PropRuleUpdate(BaseModel):
    firm_name: str = Field(min_length=1, max_length=160)
    profit_target: Decimal | None = Field(default=None, ge=0)
    max_loss: Decimal = Field(gt=0)
    daily_loss_limit: Decimal | None = Field(default=None, ge=0)
    consistency_percent: Decimal | None = Field(default=None, ge=0, le=100)
    drawdown_type: str | None = None
    account_label: str | None = Field(default=None, max_length=160)
    profile_account_type: str | None = Field(default=None, max_length=80)
    starting_balance: Decimal | None = None
    drawdown_amount: Decimal | None = Field(default=None, ge=0)
    drawdown_lock_behavior: str | None = Field(default=None, max_length=160)
    payout_buffer: Decimal | None = Field(default=None, ge=0)
    minimum_trading_days: int | None = Field(default=None, ge=1)
    qualifying_profit_days_required: int | None = Field(default=None, ge=1)
    minimum_profit_per_qualifying_day: Decimal | None = Field(default=None, ge=0)
    payout_cycle_net_profit_required: bool = True
    minimum_payout: Decimal | None = Field(default=None, ge=0)
    payout_profit_percentage: Decimal | None = Field(default=None, ge=0, le=100)
    maximum_payout: Decimal | None = Field(default=None, ge=0)
    maximum_payout_count: int | None = Field(default=None, ge=1)
    profit_split_trader_percent: Decimal | None = Field(
        default=None, ge=0, le=100
    )
    profit_split_firm_percent: Decimal | None = Field(default=None, ge=0, le=100)
    no_fixed_payout_window: bool = False
    payout_cycle_start_date: date | None = None
    qualifying_days_since_last_payout: int | None = Field(default=None, ge=0)
    payouts_completed: int | None = Field(default=None, ge=0)
    preset_key: str | None = Field(default=None, max_length=80)
    effective_date: date = Field(default_factory=date.today)
    source_note: str | None = Field(default=None, max_length=1000)
    configuration_state: Literal["configured", "required"] = "configured"
    evaluation_drawdown_choice: Literal[
        "end_of_day_trailing", "intraday_trailing"
    ] | None = None
    daily_loss_limit_enabled: bool | None = None
    daily_loss_limit_amount: Decimal | None = Field(default=None, ge=0)
    initial_trail_balance: Decimal | None = Field(default=None, ge=0)
    locked_mll_balance: Decimal | None = Field(default=None, ge=0)
    payout_buffer_balance_threshold: Decimal | None = Field(default=None, ge=0)
    max_daily_simulated_profit: Decimal | None = Field(default=None, ge=0)
    news_restriction_note: str | None = Field(default=None, max_length=1000)
    live_transition_note: str | None = Field(default=None, max_length=1000)
    purchase_configuration_json: dict[str, object] = Field(default_factory=dict)
    scaling_tiers: list[PropScalingTierInput] = Field(
        default_factory=list, max_length=50
    )
    rules_enabled_json: dict[str, bool] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator(
        "profit_target",
        "daily_loss_limit",
        "consistency_percent",
        "payout_buffer",
        "minimum_trading_days",
        "qualifying_profit_days_required",
        "minimum_profit_per_qualifying_day",
        "minimum_payout",
        "payout_profit_percentage",
        "maximum_payout",
        "maximum_payout_count",
        "profit_split_trader_percent",
        "profit_split_firm_percent",
        "payout_cycle_start_date",
        "account_label",
        "profile_account_type",
        "starting_balance",
        "drawdown_amount",
        "drawdown_lock_behavior",
        "drawdown_type",
        "preset_key",
        "source_note",
        "evaluation_drawdown_choice",
        "daily_loss_limit_amount",
        "initial_trail_balance",
        "locked_mll_balance",
        "payout_buffer_balance_threshold",
        "max_daily_simulated_profit",
        "news_restriction_note",
        "live_transition_note",
        mode="before",
    )
    @classmethod
    def blank_optional_value(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def validate_split(self) -> PropRuleUpdate:
        if (
            self.profit_split_trader_percent is not None
            and self.profit_split_firm_percent is not None
            and self.profit_split_trader_percent
            + self.profit_split_firm_percent
            != Decimal("100")
        ):
            raise ValueError("Trader and firm profit split percentages must total 100.")
        return self


class PropPresetApply(BaseModel):
    preset_key: Literal[
        "lucidflex-eval-50k",
        "lucidflex-funded-50k",
        "lucid_daily_eval_50k",
        "lucid_daily_funded_50k",
        "custom",
    ]
    confirm_replace: bool = False
    evaluation_drawdown_choice: Literal[
        "end_of_day_trailing", "intraday_trailing"
    ] | None = None
    daily_loss_limit_enabled: bool | None = None
    inherited_profile_version_id: UUID | None = None
    effective_date: date = Field(default_factory=date.today)


class AccountFromPresetCreate(BaseModel):
    account: AccountCreate
    preset: PropPresetApply


class PropPayoutCreate(BaseModel):
    request_date: date
    requested_amount: Decimal = Field(gt=0)
    notes: str | None = Field(default=None, max_length=2000)


class PropPayoutUpdate(BaseModel):
    status: Literal["pending", "approved", "rejected", "canceled"]
    approved_date: date | None = None
    approved_gross_amount: Decimal | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=2000)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("approved_date", "approved_gross_amount", "notes", mode="before")
    @classmethod
    def blank_payout_value(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class ChecklistItemInput(BaseModel):
    id: UUID | None = None
    text: str = Field(min_length=1, max_length=500)
    category: str = Field(default="entry", min_length=1, max_length=80)
    required: bool = True
    sort_order: int = Field(default=0, ge=0, le=1000)


class PlaybookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10000)
    active: bool = True
    market_scope: str | None = Field(default=None, max_length=255)
    direction_scope: Literal["long", "short", "both"] | None = None
    preferred_session: str | None = Field(default=None, max_length=80)
    minimum_confluences: int | None = Field(default=None, ge=0, le=50)
    ideal_entry_criteria: str | None = Field(default=None, max_length=10000)
    confirmation_criteria: str | None = Field(default=None, max_length=10000)
    invalidation_criteria: str | None = Field(default=None, max_length=10000)
    stop_logic: str | None = Field(default=None, max_length=10000)
    target_logic: str | None = Field(default=None, max_length=10000)
    management_rules: str | None = Field(default=None, max_length=10000)
    prohibited_conditions: str | None = Field(default=None, max_length=10000)
    default_grade_expectations: str | None = Field(default=None, max_length=5000)
    checklist_items: list[ChecklistItemInput] = Field(default_factory=list, max_length=100)

    model_config = ConfigDict(str_strip_whitespace=True)


class PlaybookUpdate(PlaybookCreate):
    name: str = Field(min_length=1, max_length=160)


class TradePlaybookUpdate(BaseModel):
    primary_playbook_id: UUID | None = None
    secondary_playbook_ids: list[UUID] = Field(default_factory=list, max_length=20)


class ChecklistResponseInput(BaseModel):
    checklist_item_id: UUID
    passed: bool | None = None
    note: str | None = Field(default=None, max_length=500)


class ChecklistResponsesUpdate(BaseModel):
    responses: list[ChecklistResponseInput] = Field(max_length=100)


class RuleViolationCreate(BaseModel):
    playbook_id: UUID | None = None
    rule_text: str = Field(min_length=1, max_length=500)
    severity: Literal["low", "medium", "high"] = "medium"
    estimated_cost: Decimal | None = None
    note: str | None = Field(default=None, max_length=5000)


class PeriodReviewUpdate(BaseModel):
    written_review: str | None = Field(default=None, max_length=20000)
    what_worked: str | None = Field(default=None, max_length=10000)
    what_failed: str | None = Field(default=None, max_length=10000)
    next_period_focus: str | None = Field(default=None, max_length=10000)
    next_period_goals: str | None = Field(default=None, max_length=10000)
    grade: Literal["A+", "A", "B", "C", "D", "F"] | None = None


class AccountGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    account_ids: list[UUID] = Field(default_factory=list, max_length=100)


class UserPreferenceUpdate(BaseModel):
    timezone: str | None = Field(default=None, max_length=80)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    week_start: int | None = Field(default=None, ge=0, le=6)
    default_account_id: UUID | None = None
    default_date_range: str | None = Field(default=None, max_length=40)
    pnl_display: Literal["net", "gross"] | None = None
    density: Literal["comfortable", "compact"] | None = None
    reduced_motion: bool | None = None
    session_definitions_json: dict[str, object] | None = None
    review_rules_json: dict[str, object] | None = None


class ManualTradeCreate(BaseModel):
    account_id: UUID
    symbol: str = Field(min_length=1, max_length=80)
    root_symbol: str | None = Field(default=None, max_length=40)
    side: Literal["long", "short"]
    quantity: Decimal = Field(gt=0)
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl: Decimal
    fees: Decimal = Decimal("0")
    net_pnl: Decimal
    notes: str | None = Field(default=None, max_length=10000)
    primary_playbook_id: UUID | None = None
    tag_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_trade(self) -> ManualTradeCreate:
        if self.entry_timestamp.tzinfo is None or self.exit_timestamp.tzinfo is None:
            raise ValueError("Entry and exit timestamps must include a timezone.")
        if self.exit_timestamp < self.entry_timestamp:
            raise ValueError("Exit timestamp must be after the entry timestamp.")
        if self.gross_pnl - self.fees != self.net_pnl:
            raise ValueError("Net P&L must equal gross P&L minus fees.")
        return self


class ManualTradeUpdate(BaseModel):
    symbol: str | None = Field(default=None, min_length=1, max_length=80)
    root_symbol: str | None = Field(default=None, max_length=40)
    side: Literal["long", "short"] | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    entry_timestamp: datetime | None = None
    exit_timestamp: datetime | None = None
    entry_price: Decimal | None = None
    exit_price: Decimal | None = None
    gross_pnl: Decimal | None = None
    fees: Decimal | None = None
    net_pnl: Decimal | None = None
    notes: str | None = Field(default=None, max_length=10000)
    reason: str = Field(min_length=1, max_length=500)


class ManualAdjustmentCreate(BaseModel):
    account_id: UUID
    adjustment_type: Literal["deposit", "withdrawal", "fee_correction", "account_correction"]
    amount: Decimal
    effective_at: datetime
    reason: str = Field(min_length=1, max_length=500)
    status: Literal["pending", "approved", "rejected"] = "approved"

    @model_validator(mode="after")
    def validate_timestamp(self) -> ManualAdjustmentCreate:
        if self.effective_at.tzinfo is None:
            raise ValueError("Effective timestamp must include a timezone.")
        return self


class ManualAdjustmentUpdate(BaseModel):
    status: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=500)


class ManualDeleteRequest(BaseModel):
    confirmation: str
    reason: str = Field(min_length=1, max_length=500)

class BrokerConnectionCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=60)
    connection_type: Literal["desktop_bridge", "browser_session", "official_api", "file_import"]
    display_name: str = Field(min_length=1, max_length=160)
    account_id: UUID | None = None
    external_account_id: str | None = Field(default=None, max_length=120)
    metadata_json: dict[str, object] = Field(default_factory=dict)


class BrokerConnectionUpdate(BaseModel):
    account_id: UUID | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    status: Literal["connected", "disconnected", "degraded", "error"] | None = None
    external_account_id: str | None = Field(default=None, max_length=120)
    metadata_json: dict[str, object] | None = None


class BrokerExecutionIngest(BaseModel):
    connection_id: UUID
    account_id: UUID | None = None
    external_execution_id: str = Field(min_length=1, max_length=160)
    external_order_id: str | None = Field(default=None, max_length=160)
    symbol: str = Field(min_length=1, max_length=80)
    side: Literal["buy", "sell", "long", "short"]
    quantity: Decimal = Field(gt=0)
    price: Decimal
    commission: Decimal | None = None
    executed_at: datetime
    source_payload: dict[str, object] = Field(default_factory=dict)
