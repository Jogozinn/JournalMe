# Tradovate Import Reconciliation

## Detection

Reports are identified from normalized header sets, never filenames. An
`undefined`-only Order Details export is recognized as empty and skipped with a
non-blocking warning.

Preview and commit both use the same normalized row models. Required values
produce source-aware errors containing report type, filename, physical CSV row,
source column, normalized field, and reason. Optional blank, whitespace-only,
or `NaN` decimal values remain `null`; a real numeric zero remains zero.

## Canonical trade identity

Completed-position rows form a graph whose nodes are fill IDs. Rows sharing an
entry or exit fill belong to the same connected component. This correctly
combines scaled exits: the supplied 13 Performance rows resolve to 12 canonical
trades because two rows share an entry fill.

Identity precedence:

1. Account plus connected buy/sell fill IDs
2. Pair or position ID
3. Stable SHA-256 fingerprint of account, symbol, timestamps, quantity, prices

## Field precedence

- Direction and timing: fill actions/timestamps, then paired timestamps
- Quantity and price: fill-weighted executions, then paired report values
- Gross P&L: Position History, then Performance; calculated values are compared
  but do not silently replace imported values
- Fees: linked Fill commissions
- Net P&L: gross P&L less linked fill commissions
- Order intent: Orders enrich Fills; canceled/unfilled orders never create trades
- Balance: Account Balance History is authoritative; calculated equity remains a
  separate comparison
- Cash History: retained as ledger evidence; Commission rows do not add fees when
  the same execution has Fill commission data

Conflicts create reconciliation warnings and preserve every raw source payload.

### Valid unavailable values

- Canceled orders retain null filled quantity, average fill price, fill time,
  and notional value.
- Limit orders may omit stop price; Stop orders may omit limit price; Market
  orders may omit both.
- Closed Position History rows (`Net Pos == 0`) may omit `Net Price`.
- Non-contract cash events such as Fund Transactions may omit `Contract`.

The preview reports linked filled orders, canceled/unfilled orders retained, and
genuinely unmatched filled orders separately.

## Atomicity and idempotency

All files selected together are one `ImportSession`. Commit uses one database
transaction. Fatal errors roll back the entire batch; nonfatal row issues remain
visible as warnings. File hashes, external IDs, and trade fingerprints prevent
duplicates across repeated or overlapping uploads.
