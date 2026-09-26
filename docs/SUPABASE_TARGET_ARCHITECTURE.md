# Supabase target architecture (future design, not implemented)

The existing SQLAlchemy tables map one-for-one to PostgreSQL: `users`, `trading_accounts`, import/import-file tables, trades/fills/orders/cash/daily-balances, journals/tags/attachments/captures, goals/prop tables, playbook tables, reviews, account groups, manual adjustments, preferences, and audit events. UUID primary keys are already portable and should be retained.

Map `users.id` to an application profile keyed by `auth.users.id`; backfill local users through an explicit reviewed mapping table, never fabricated IDs. RLS should permit a row when `user_id = auth.uid()` for direct-owned tables. Account-owned tables should use an `EXISTS` policy through `trading_accounts.user_id`; trade- and playbook-owned tables should use the corresponding parent. Prop preset reference data is read-only to authenticated users and writable only by service role.

Use a private `journalme-assets` bucket. Opaque keys should be `users/{user_uuid}/captures/{capture_uuid}/original.{ext}`, `users/{user_uuid}/trades/{trade_uuid}/{attachment_uuid}.{ext}`, and equivalent import/playbook/day paths. FastAPI remains the authorization layer and creates short-lived signed reads after ownership checks; never expose a public bucket or OS path.

Migration ordering: provision Auth/Postgres/bucket/RLS; deploy provider implementations behind current interfaces; migrate users/accounts, then transactional data, then journals/reviews/playbooks, then attachment metadata and bytes; validate row counts, UUIDs, account ownership, fingerprints, hashes, and sampled attachment reads before cutover. Keep SQLite read-only backup and object checksums for rollback; do not dual-write without idempotency keys. Existing account/provider and trade-fingerprint uniqueness constraints remain duplicate-prevention anchors.

Electron transition: retain local mode; add a real authenticated cloud mode only after FastAPI validates hosted tokens. Web/PWA transition: set hosted API origin, HTTPS CORS, and authenticated session propagation. No client should query Supabase directly for journal data.
