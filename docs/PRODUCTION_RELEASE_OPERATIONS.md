# Production release operations

## Startup and migrations

Hosted PostgreSQL/Supabase startup is read-only. The backend checks that
`alembic_version` is a known head for its release, then fails with an actionable
error if the database is missing a version, behind, on an unsupported branch, or
ahead of the application. It does not run Alembic or create the local desktop
user, tags, or starter playbooks. Supabase mode rejects
`JOURNALME_AUTO_MIGRATE=true` and `JOURNALME_BOOTSTRAP_LOCAL_DATA=true`.

SQLite development retains automatic migration and starter-data bootstrap.
Local PostgreSQL development can explicitly set `JOURNALME_AUTO_MIGRATE=true`;
set `JOURNALME_BOOTSTRAP_LOCAL_DATA=true` only when the local database needs the
desktop seed data.

Run these commands from `backend/` in the release environment:

```powershell
python -m app.migrations revision   # read-only installed revision and release heads
python -m app.migrations check      # read-only compatibility gate
python -m app.migrations upgrade   # explicit apply to this release's Alembic head
python -m app.migrations check      # verify after apply
```

Use the direct PostgreSQL URL for the migration job. Set
`JOURNALME_AUTO_MIGRATE=false` and `JOURNALME_BOOTSTRAP_LOCAL_DATA=false` on the
API service. Do not deploy if the pre-migration revision is not the reviewed
expected revision.

## Rollback release

The migration is additive. Keep 0016 installed when rolling back application
code. The old API code must be packaged with the migration-aware startup gate
and the complete current Alembic migration directory; an unmodified old image
does not know revision 0016 and is not a valid rollback target.

Build that compatibility release from the exact prior working backend commit:

```powershell
python backend/tools/assemble_rollback_release.py `
  --base-ref <prior-working-backend-commit> `
  --output-dir <new-private-build-directory>
```

The assembler exports tracked files from that commit, then overlays only the
current startup/configuration gate and migration graph. Its Docker context omits
untracked environment files. Build the image from the printed `backend/`
context. Test its read-only `python -m app.migrations check` and API startup
against a disposable database already at 0016 before retaining it as the
rollback image. During rollback, set automatic migration and local bootstrap to
false; do not downgrade 0016.

## Database and private Storage backup

Run from `backend/` using a private, encrypted destination with enough free
space. Set the database and Storage environment values in the local secret
manager or shell environment; never put them in command arguments, source,
reports, or logs. Use `JOURNALME_DATA_PROVIDER=supabase`,
`JOURNALME_STORAGE_PROVIDER=supabase`, `SUPABASE_DB_URL`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, and `SUPABASE_STORAGE_BUCKET`.

```powershell
python -m app.backup inspect-db
python -m app.backup backup-db --output-dir <new-private-directory>\database
python -m app.backup verify-db `
  --dump <new-private-directory>\database\database.dump `
  --report <new-private-directory>\database\database-report.json
python -m app.backup export-storage --output-dir <new-private-directory>\storage
python -m app.backup verify-storage --directory <new-private-directory>\storage
```

The logical PostgreSQL archive includes all dumpable database schemas rather
than selecting `public`; the report captures the installed Alembic revision,
table counts, schemas, extensions, RLS policy count, identity checks, storage
reference counts, and whether `auth` and `storage` are present in the archive.
It separately stores password-free role definitions. The archive includes
Auth rows, custom database objects/policies, and Storage metadata when the
configured PostgreSQL role can read them. Credentials and role passwords are
not exported. Failed access to any schema fails the backup command; do not
reinterpret a partial dump as complete.

Supabase's platform backup/clone is the preferred full-project recovery point.
Its database copy covers Auth database records, but Supabase Storage object
bytes are separate. The Storage exporter verifies that the configured bucket is
private, downloads every listed object, and records key, byte count, and
SHA-256 in a manifest. Keep the report, archive, role file, object tree, and
manifest together. Supabase does not include custom role passwords in its
backups; recreate/reset any custom login-role passwords using the provider's
supported process. Do not replay password-free role SQL over Supabase-managed
roles without reviewing it.

Restore the database only into a new empty loopback PostgreSQL database. The
command rejects remote or non-empty targets and compares revision, schemas,
extensions, policies, table counts, and identity checks after restore:

```powershell
$env:JOURNALME_RESTORE_DATABASE_URL = '<loopback disposable PostgreSQL URL>'
python -m app.backup restore-db `
  --dump <new-private-directory>\database\database.dump `
  --report <new-private-directory>\database\database-report.json
```

To rehearse object recovery, point the Storage environment at a disposable
local Supabase instance with a private bucket, then run:

```powershell
python -m app.backup restore-storage --directory <new-private-directory>\storage
$env:JOURNALME_RESTORE_DATABASE_URL = '<loopback restored PostgreSQL URL>'
python -m app.backup reconcile-storage `
  --directory <new-private-directory>\storage --restored-database
```

Storage restore is loopback-only and create-only: it never overwrites an
existing object, and identical existing bytes are safe to resume. Reconciliation
checks attachment keys, capture screenshot keys, and stored import-file keys
against the exported object manifest.

## Bridge release sequence

1. Read the production Alembic revision and deployed application revisions.
   Confirm the selected project, database, API, and frontend match each other.
2. Create the provider-native database recovery point and the logical database
   archive; export the private Storage bucket and verify every manifest checksum.
3. Restore into an isolated Supabase project or compatible local Supabase stack.
   Validate counts, identities, RLS policies, Auth records, extensions, storage
   metadata, screenshots, and the reference reconciliation. Do not use the live
   project as a rehearsal target.
4. Confirm production is at the reviewed parent revision, then run the explicit
   migration command once. Verify revision 0016 and run the read-only check.
5. Deploy the new backend with automatic migration/bootstrap disabled, then
   deploy the matching frontend. Verify health, authenticated Connections UI,
   and the new source discovery/authorization endpoints.
6. Before changing the Windows installation, preserve both queue files and its
   current config privately. Drain `bridge-queue.txt` and
   `bridge-queue-v2.txt` with the original legacy key and `account_name`; require
   zero queued uploads and no unresolved failures. Keep positions flat.
7. Install the compiled AddOn and configure one installation key without
   `-AccountName`. Pair the installation, then explicitly map each discovered
   Lucid account to its JournalMe account. Stop if source names are ambiguous.
8. Validate heartbeats, balances, and account-specific execution synchronization
   with simulation where available, then observe normal trading activity. No
   trade is required solely for testing.
9. After successful verification, revoke/disconnect the legacy connector. Keep
   migration 0016 in place. The old connector's historical records remain in
   JournalMe.

Steps 1–3 are evidence gates, not assumed completed work. Step 4 changes
production schema; steps 5–9 affect deployed application or the NinjaTrader
installation and require explicit owner authorization when performed by an
operator.
