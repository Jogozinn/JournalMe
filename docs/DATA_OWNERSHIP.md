# Data ownership audit

Direct user ownership: `TradingAccount`, `Tag`, `CaptureEvent`, `Playbook`, `AccountGroup`, `UserPreference`, and `AuditEvent` carry `user_id` and are scoped in current API queries.

Ownership via `TradingAccount`: imports/files, trades, fills, orders, cash transactions, daily balances, daily journals, goals, prop profiles/versions/tiers/payout cycles/payout records, reviews, and manual adjustments. Ownership via `Trade`: trade journals, trade tags, trade/playbook joins, checklist responses, rule violations, and trade attachments. Ownership via `Playbook`: checklist items and playbook attachments. Account-group membership is owned through its group and account.

`Attachment` deliberately has no `user_id`: it inherits from exactly one owned parent (`trade_id`, `daily_journal_id`, or `playbook_id`) and current routes resolve those parents through the current user. `CaptureEvent` owns its screenshot directly through `user_id`. `ImportSession` now has nullable direct `user_id`; migration `0007` backfills it only from each existing account owner. Historical accountless sessions remain unowned/invisible rather than receiving an invented user ID.

Global/shared records: `PropPreset`, `PropPresetVersion`, and `PropPresetScalingTier` are application-managed reference data, not user content. This is intentional; future hosted write access must be service-role/admin only. No ownership migration is required tonight. Future PostgreSQL constraints should require exactly one attachment parent and validate account-group members belong to the group owner.
