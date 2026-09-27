# JournalMe NinjaTrader probe

This is a read-only discovery probe for the first JournalMe live broker connector.

It currently does only four things:

- discovers NinjaTrader accounts;
- observes account-value changes;
- observes executions/fills;
- observes position changes.

It does **not** submit, modify, cancel, or flatten orders. It also does not send anything to JournalMe yet. Its first job is to prove that the Lucid/NinjaTrader connection produces the exact live fields JournalMe needs.

The production bridge should only be enabled after one normal execution has been observed and checked against the broker record.
