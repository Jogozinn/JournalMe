# Phase 1 Scope

## Included

- Local single-user account setup behind an authentication interface
- Atomic, multi-file Tradovate import with header detection and preview
- Performance, Position History, Fills, Orders, Cash History, Account Balance
  History, and empty Order Details handling
- Deterministic reconciliation, warnings, source preservation, and idempotency
- API-backed home, import, trades, trade review, calendar, daily timeline,
  journals, attachments, and basic analytics
- Manual setup, confluence, mistake, emotion, and custom tags
- Dark-first responsive shell and installable PWA metadata
- PostgreSQL/SQLite configuration and Docker Compose

## Deliberately deferred

- Automatic chart-pattern detection (ORB, RSI, FVG, and related strategies)
- Direct broker synchronization
- Multi-user hosted authentication and subscription billing
- Week/year calendar views
- Native iOS packaging

Manual strategy tags are the supported Phase 1 classification mechanism.

