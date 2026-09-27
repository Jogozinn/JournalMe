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
