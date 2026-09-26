# Review Completion

Review status is deterministic and centralized.

## Trade defaults

A complete trade review requires:

- thesis
- entry reason
- exit reason
- lesson learned
- trade grade
- followed-plan answer
- one primary playbook
- at least one tag
- every required playbook checklist item answered

A trade with none of these is `unreviewed`. A trade with some requirements met
is `partial`. A trade with no missing requirements is `complete`. Screenshots
are a separate queue filter and are not required by default.

## Trading-day defaults

A complete day recap requires:

- reflection
- focus for next session
- day grade
- followed-rules answer
- all trades on that account-local date complete

Non-trading journal days may be complete without fake trades.

The required trade/day field lists and screenshot policy are stored in
`UserPreference.review_rules_json`. Every Home, queue, Trade Review, Trading
Day, and period-review completion number must call the same service.

