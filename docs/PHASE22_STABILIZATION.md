# Phase 2.2 stabilization

## Authoritative balances

`app.services.balance.resolve_account_balance` is the sole current-balance
resolver. It keeps broker snapshots and calculated ledger balances separate,
checks whether the latest snapshot covers the newest local activity date, and
rolls stale snapshots forward with later canonical trades, approved manual
adjustments, external cash movements, and approved payout deductions.

Commission and `Trade Paired` cash-history rows are evidence for canonical
trades and are not counted again. An opening `Fund Transaction` equal to the
configured starting balance is also not counted twice. Responses preserve the
imported and calculated values, reconciliation difference, method, activity
timestamp, and stale-snapshot flag.

DailyBalance currently has day precision. A snapshot for the latest activity
day is therefore treated as an end-of-day snapshot; JournalMe cannot infer a
missing intraday broker event from a date-only report.

## Preset catalog

Migration `0005` owns a normalized, versioned catalog:

- LucidFlex Funded 50K
- LucidDaily Evaluation 50K
- LucidDaily Funded 50K
- Custom

Applying a preset copies its latest catalog version into an account-owned rule
profile and creates an immutable profile version. Catalog rows are never edited
by account customization. Replacing a different active profile requires
confirmation.

LucidDaily Evaluation requires an explicit evaluation drawdown and DLL ON/OFF
choice. LucidDaily Funded always uses Intraday trailing drawdown and either
inherits the evaluation DLL fact or requires it for a standalone account.

## Navigation and payloads

The root layout keeps the app shell and account provider mounted across routes.
Primary routes are explicitly prefetched. Concurrent identical GET requests
are deduplicated, stable shared lookups use a short client cache, list endpoints
remain paginated, and the equity chart is loaded as a nonessential dynamic
chunk. A root `loading.tsx` provides route-transition skeletons.

The first visit to a route under `npm run dev` can still trigger Next.js
on-demand compilation. Production performance must be measured with
`npm run build && npm run start`; development compilation time is not treated
as production navigation time.
