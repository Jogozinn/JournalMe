# Prop Account Rules

Prop tracking combines verified account results with user-configured rules.
JournalMe does not treat a preset as a contractual or legal source.

Phase 2.2 preset-catalog and balance-resolution details are documented in
`PHASE22_STABILIZATION.md`.

## Nullable rules

Profit target, daily loss limit, consistency percentage, payout buffer, and
minimum trading days are optional. Blank input is stored as `null`, while an
explicit numeric zero remains zero. Status responses preserve nullability so
the UI can show **Not applicable** rather than a fabricated zero.

## Versions and payout cycles

The account retains one editable profile identity. Every save creates an
immutable `PropRuleProfileVersion` snapshot and normalized scaling tiers.
Payout cycles reference the version used for their calculation. Closed cycles
and approved payout records therefore retain their historical rule boundary.

Only an approved payout closes the open cycle. Pending, rejected, and canceled
records do not change the cycle start or qualifying-day progress. Payout edits
and deletions are audited; approved payouts cannot be deleted or reopened.

## LucidFlex Funded 50K preset

The editable preset configures:

- $2,000 maximum loss and end-of-day trailing drawdown
- no profit target, daily loss limit, consistency rule, payout buffer, or
  generic minimum-trading-days rule
- 5 distinct qualifying profit days, each at least $150
- positive payout-cycle net profit
- $500 minimum payout request
- 50% of cycle profit available, capped at $2,000
- 90% trader / 10% firm split
- 5 approved payouts before the configured transition limit
- no fixed payout window
- scaling tiers of 2 minis / 20 micros at $0, 3 / 30 at $1,000, and
  4 / 40 at $2,000

Cycle net profit is canonical trade net P&L after fees plus audited manual
adjustments within the open cycle. A qualifying day is a distinct account-local
date whose combined trade net P&L meets the threshold.

For end-of-day trailing drawdown, the displayed loss floor is the highest
available imported end-of-day balance minus the configured drawdown amount.
This remains an estimate when firm-side or intraday events are absent from the
broker export.
