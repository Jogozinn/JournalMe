# Phase 2: Professional Journal

Phase 2 turns the verified Phase 1 importer and journal into a daily trading
operating system. The imported execution ledger remains authoritative and is
not rewritten by journal, playbook, goal, or manual-adjustment features.

## Product outcomes

- Home prioritizes planning, review work, account health, and stored-data
  reminders.
- Trading Day is the primary workspace for pre-session planning, chronological
  execution review, and the closing reflection.
- Trade Review combines immutable execution evidence with editable journal,
  playbook, checklist, violation, tag, and screenshot context.
- Review Queue uses explicit completion rules shared by every API and screen.
- Weekly and monthly reviews persist user-authored conclusions beside
  deterministic summaries.
- Playbooks are reusable plans with ordered checklist items and per-trade
  adherence.
- Account, prop-rule, goal, import-quality, preference, and data-export tools
  are first-class settings workflows.
- Manual financial records are visibly marked and audited.

## Non-goals

Phase 2 does not infer strategies from charts, reconstruct intratrade market
data, calculate MAE/MFE, provide paid-model coaching, or sync live broker APIs.
No statistical claim is made from small samples.

## Compatibility requirements

- Existing Tradovate imports remain atomic and idempotent.
- Imported rows and source payloads are preserved.
- Money and prices remain `Decimal`.
- Existing account ownership checks protect every new route.
- Schema changes are additive and reversible.
- SQLite remains supported locally and PostgreSQL remains the production target.

## Delivery slices

1. Schema, migrations, review completion, prop calculation, and exports.
2. Playbooks, queue, reviews, manual records, groups, preferences, and quality
   APIs.
3. Navigation, Home, Trading Day, Trade Review, review and settings workflows.
4. Advanced analytical breakdowns, responsive polish, regression tests, and
   real-data visual acceptance.

