# JournalMe web authentication

JournalMe has two intentionally separate client modes. The mode check lives in
the frontend auth/session boundary rather than individual pages.

## Local desktop development

Local mode requires no Supabase browser configuration and keeps the existing
SQLite backend on `127.0.0.1:8066` plus the identity-verified Next.js frontend
on `127.0.0.1:3066`.

```powershell
Set-Location D:\PythonProjects\JournalMe\desktop
npm run dev
```

Electron explicitly sets `NEXT_PUBLIC_AUTH_MODE=local`; inherited hosted-web
settings cannot force its window to the login screen.

## Local browser web development

JournalMe browser development uses `http://localhost:3070` permanently. It
must not share WaveRR's `http://localhost:3000` origin. Start the existing
local backend separately on `127.0.0.1:8066`, then run:

```powershell
Set-Location D:\PythonProjects\JournalMe\frontend
npm run dev
```

Verify the served frontend identity at
`http://localhost:3070/api/desktop-health`; it returns the JournalMe frontend
identity marker used by Electron as well.

## Cloud backend development

Set these server-only environment variables in the launching shell or a secure
process manager: `JOURNALME_DATA_PROVIDER`, `JOURNALME_STORAGE_PROVIDER`,
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
`SUPABASE_STORAGE_BUCKET`, `SUPABASE_DB_URL`, `SUPABASE_JWT_AUDIENCE`, and
`JOURNALME_CORS_ORIGINS`. Never put the service-role or database credentials in
the frontend environment.

```powershell
Set-Location D:\PythonProjects\JournalMe\backend
& D:\PythonProjects\JournalMe\.venv\Scripts\python.exe -m uvicorn app.main:app `
  --host 127.0.0.1 --port 8067
```

The cloud backend continues to enforce Bearer JWT validation and JournalMe
ownership. Supabase RLS remains defense-in-depth.

## Cloud web development

Create `frontend/.env.local` outside source control with only:

```text
NEXT_PUBLIC_AUTH_MODE=hosted
NEXT_PUBLIC_JOURNALME_API_URL=http://127.0.0.1:8067/api/v1
NEXT_PUBLIC_SUPABASE_URL=<project URL>
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable key>
```

Set the backend development CORS origin to exactly
`http://localhost:3070` (plus `http://127.0.0.1:3066` only when Electron is in
scope); do not use `*`.

Then run:

```powershell
Set-Location D:\PythonProjects\JournalMe\frontend
npm run dev
```

The official Supabase browser client persists and refreshes its user session.
Its storage key is explicitly namespaced as `journalme-supabase-auth`.
JournalMe API calls, private image reads, and exports flow through FastAPI with
the current access token. There is no public signup screen and no direct
browser-to-database application path.

For an older Supabase project, `NEXT_PUBLIC_SUPABASE_ANON_KEY` is accepted as a
fallback name instead of `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.

For hosted deployment, configure the exact HTTPS frontend origin in
`JOURNALME_CORS_ORIGINS`; do not use `*`. Add that origin and redirect URLs to
the Supabase Auth URL allow-list. PWA manifest, safe-area styling, and service
worker registration remain unchanged.
