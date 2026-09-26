# Architecture

JournalMe is a monorepo with a Next.js App Router client and a FastAPI API.
PostgreSQL is the production system of record; SQLite is supported for local
development and tests.

## Boundaries

- `frontend/` owns presentation, responsive navigation, PWA metadata, and typed
  API access. Production screens do not contain demo trade arrays.
- `backend/app/api/` is the HTTP boundary.
- `backend/app/services/importer.py` detects and parses source reports.
- `backend/app/services/reconciliation.py` turns report rows into canonical
  records without discarding source evidence.
- `backend/app/models.py` is the relational system of record.
- `backend/app/storage.py` is the local file-storage implementation behind a
  small storage interface.

The local authentication adapter resolves a seeded single user. The dependency
is intentionally isolated so Auth.js, Clerk, or Supabase Auth can replace it
without changing domain services.

## Data flow

1. A multi-file upload creates one pending `ImportSession`.
2. Files are hashed, safely stored, detected by headers, and previewed.
3. Commit reparses all files and executes reconciliation inside one database
   transaction.
4. Unique constraints and stable fingerprints make overlapping imports
   idempotent.
5. Dashboard, calendar, analytics, trade review, and timeline queries read the
   normalized records and journals.

Money and prices use `Decimal` end to end. Source timestamps are interpreted in
the trading account timezone and stored as timezone-aware UTC values.

