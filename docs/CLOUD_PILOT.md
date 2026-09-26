# Cloud Pilot v0.1

Local SQLite/filesystem remains authoritative. Supabase is opt-in only when
both provider variables are `supabase`; misconfiguration stops startup.

## Provisioning order

1. Create a Supabase project and a **private** `journalme-assets` bucket.
2. Set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
   `SUPABASE_STORAGE_BUCKET`, and a direct `SUPABASE_DB_URL` outside source
   control. Use a direct SSL PostgreSQL URL for Alembic; use a reviewed pooler
   URL only for runtime if its transaction behavior is compatible.
3. Run `alembic upgrade head` with `JOURNALME_DATA_PROVIDER=supabase` against
   an empty target. Never point it at the local SQLite database.
4. Review and apply `supabase/rls.sql` in the Supabase SQL editor. It is
   defense-in-depth; FastAPI remains the authorization boundary.
5. Create the intended Supabase Auth user, then pass its UUID explicitly to
   the rehearsal tool. The tool creates the matching `auth_identities` record.

## Migration rehearsal

Default mode is non-mutating: it reads SQLite and validates a single explicit
local-user mapping plus every local object byte. It produces JSON and Markdown
reports. `--apply` requires the empty/previously resumed PostgreSQL target to
already be at Alembic head and preserves UUIDs, timestamps, decimals, hashes,
and source identifiers. It copies private objects under deterministic opaque
keys, verifies bytes by SHA-256, and changes storage keys only in PostgreSQL.
SQLite and local storage are never modified or deleted.

```powershell
& D:\PythonProjects\JournalMe.venv\Scripts\python.exe tools\migrate_local_to_cloud.py `
  --dry-run --local-user-id <journalme-user-uuid> `
  --supabase-auth-subject <supabase-auth-user-uuid> --report migration_validation.json
```

Use `--apply` only after reviewing the generated report and backup. The tool
blocks multi-user sources, missing objects, omitted mappings, non-head targets,
and mismatched counts or P&L totals. It is restart-safe: PostgreSQL inserts use
conflict-ignore and existing cloud objects must hash-identically.

## Auth and clients

Cloud mode accepts only a bearer token verified against Supabase's JWKS with
issuer and audience validation. Its `sub` must be explicitly mapped to a
JournalMe user; no request-supplied `user_id` is trusted. The service-role key
is backend-only. Browser/PWA login UI and Electron cloud mode are intentionally
not enabled yet; local desktop continues on frontend `3066` and backend `8066`.
