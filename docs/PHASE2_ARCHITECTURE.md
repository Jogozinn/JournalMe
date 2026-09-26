# Phase 2 Architecture

## Data ownership

Imported `Trade`, `Fill`, `Order`, `CashTransaction`, and `DailyBalance` rows
remain the execution ledger. User-created context lives in journal, playbook,
review, goal, preference, and adjustment tables. A manual trade is a normal
`Trade` whose `source_quality` is `manual`; it carries no import-session link.

`AuditEvent` stores before/after snapshots for manual financial creates, edits,
and deletes. Audit rows are append-only. Manual balance and cash corrections
are represented by `ManualAdjustment`; they do not mutate imported balances or
cash history.

## Review completion

Review state is computed by `app.services.review` from explicit required fields,
playbook assignment, tags, and day recap fields. This avoids stale denormalized
queue rows. User preferences may change the required-field lists. The API
returns `unreviewed`, `partial`, or `complete` plus missing requirements.

## Playbooks

`Playbook` owns ordered `PlaybookChecklistItem` rows. `TradePlaybook` is the
many-to-many assignment and permits exactly one application-level primary
playbook per trade. `TradeChecklistResponse` stores the response against the
versioned checklist row. Deleting a playbook cascades its checklist and
assignments but never deletes a trade.

## Period reviews

Weekly and monthly review records use an account plus canonical period key.
Metrics are calculated from trades at read time; stored rows contain authored
reflection, focus, goals, and grade. This keeps financial summaries consistent
with the canonical ledger.

## API boundaries

The Phase 1 router remains responsible for imports, canonical trades, basic
analytics, journals, and attachments. The Phase 2 router owns playbooks,
review queue, period reviews, groups, preferences, manual records, quality,
exports, and advanced summaries. Both use the same current-user dependency and
account ownership boundary.

Potentially large collections are paginated and filtered server-side. Relationship
loads use `selectinload`; aggregate screens request dedicated summary endpoints
instead of loading the full trade history into the browser.

## Migration strategy

Migration `0003` only adds nullable/defaulted columns and new normalized tables.
It does not transform imported financial rows. Upgrade is tested against a copy
of the existing schema, while the financial regression suite verifies canonical
counts, commissions, daily totals, and balance after upgrade.

