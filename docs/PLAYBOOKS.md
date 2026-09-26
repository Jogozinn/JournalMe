# Playbooks

A playbook describes a setup the trader intends to execute. It is an editable
plan, not a claim of profitability and not an automatically detected signal.

Each playbook can define instrument and direction scope, preferred session,
entry and confirmation criteria, invalidation, stop and target logic,
management rules, prohibited conditions, and a minimum confluence count.
Ordered checklist items are either required or optional and may be grouped by
category.

Trades can have one primary playbook and additional secondary playbooks.
Checklist responses and rule violations are recorded per trade. Adherence is:

`answered required items that passed / total required items × 100`

When a playbook has no required items, adherence is unavailable rather than
reported as a perfect score. Analytics always display sample size and avoid
labeling combinations as proven.

The optional starter set—ORB continuation, RSI divergence reversal, VWAP
reclaim/rejection, liquidity sweep reversal, and FVG/IFVG continuation—is only
a starting template. Starter playbooks are editable, archivable, and removable.

