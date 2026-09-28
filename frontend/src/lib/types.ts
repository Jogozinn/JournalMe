export type Account = {
  id: string;
  name: string;
  external_account_id: string | null;
  provider: string;
  account_type: string;
  starting_balance: string | null;
  timezone: string;
  currency: string;
  active: boolean;
  include_in_learning: boolean;
  notes: string | null;
  current_balance: string | null;
  net_pnl: string | null;
  lifecycle_status: "active" | "passed" | "funded" | "blown" | "closed";
  configuration_required: boolean;
  active_plan: {
    preset_key: string;
    plan_family: string;
    phase: string;
    account_size: string | null;
  } | null;
  balance_resolution: {
    starting_balance: string | null;
    imported_balance: string | null;
    imported_balance_as_of: string | null;
    calculated_balance: string | null;
    calculated_balance_as_of: string | null;
    resolved_current_balance: string | null;
    resolution_method: string;
    reconciliation_difference: string | null;
    stale_snapshot: boolean;
  };
};

export type Tag = {
  id: string;
  name: string;
  category: "setup" | "confluence" | "mistake" | "emotion" | "custom";
};

export type Trade = {
  id: string;
  account_id: string;
  symbol: string;
  root_symbol: string | null;
  side: "long" | "short";
  quantity: string;
  entry_price: string;
  exit_price: string;
  gross_pnl: string;
  fees: string | null;
  net_pnl: string;
  currency: string;
  entry_timestamp: string;
  exit_timestamp: string;
  duration_seconds: number | null;
  reconciliation_status: string;
  tags: Tag[];
  journaled: boolean;
  source?: string;
  grade?: string | null;
  followed_plan?: boolean | null;
  review?: ReviewStatus | null;
};

export type ReviewStatus = {
  status: "unreviewed" | "partial" | "complete";
  missing: string[];
  completed_requirements: number;
  total_requirements: number;
  primary_playbook_id: string | null;
  has_screenshot: boolean;
  adherence_percent: number | null;
};

export type ChecklistItem = {
  id: string;
  playbook_id: string;
  text: string;
  category: string;
  required: boolean;
  sort_order: number;
};

export type Playbook = {
  id: string;
  name: string;
  description: string | null;
  active: boolean;
  market_scope: string | null;
  direction_scope: string | null;
  preferred_session: string | null;
  minimum_confluences: number | null;
  ideal_entry_criteria: string | null;
  confirmation_criteria: string | null;
  invalidation_criteria: string | null;
  stop_logic: string | null;
  target_logic: string | null;
  management_rules: string | null;
  prohibited_conditions: string | null;
  default_grade_expectations: string | null;
  checklist_items: ChecklistItem[];
};

export type Metrics = {
  net_pnl: string;
  win_rate: string | null;
  profit_factor: string | null;
  average_winner: string | null;
  average_loser: string | null;
  average_win_loss_ratio: string | null;
  largest_gain: string | null;
  largest_loss: string | null;
  expectancy: string | null;
  total_trades: number;
};

export type CompanionMomentPhase =
  | "pre_entry"
  | "confirmation"
  | "entry"
  | "management"
  | "exit"
  | "wait"
  | "post_trade"
  | "general";

export type CompanionMoment = {
  id: string;
  episode_id: string | null;
  account_id: string | null;
  captured_at: string;
  created_at: string;
  event_type: "entry" | "exit" | "update" | "wait";
  phase: CompanionMomentPhase | null;
  recorded_live: boolean;
  symbol: string | null;
  side: "long" | "short" | null;
  note: string | null;
  setup_tags: string[];
  execution_tags: string[];
  emotion_tags: string[];
  platform: string | null;
  page_url: string | null;
  page_title: string | null;
  source: string;
  match_status: string;
  matched_trade_id: string | null;
  match_score: number | null;
  matched_at: string | null;
  match_method: string | null;
  has_screenshot: boolean;
  screenshot_url: string | null;
};

export type TradingEpisode = {
  id: string;
  account_id: string | null;
  symbol: string | null;
  side: "long" | "short" | null;
  title: string | null;
  status: "active" | "complete" | "wait" | "archived";
  source: string;
  started_at: string;
  ended_at: string | null;
  created_at: string;
  updated_at: string;
  matched_trade_id: string | null;
  moment_count: number;
  screenshot_count: number;
  last_moment_at: string | null;
  last_note: string | null;
  matched_trade: {
    id: string;
    symbol: string;
    side: string;
    net_pnl: string;
    entry_timestamp: string;
    exit_timestamp: string;
  } | null;
  moments?: CompanionMoment[];
};

export type CompanionMomentCreateResponse = CompanionMoment & {
  episode: TradingEpisode;
};
