# JournalMe Companion v0.5.0

JournalMe Companion can now connect to the hosted JournalMe web session and save captures into the same cloud account used by the web app.

## Hosted connection

1. Load the `extension` folder as an unpacked Chrome extension.
2. Open the Companion side panel.
3. Choose `Connect web`.
4. JournalMe opens a one-time connection page.
5. Approve `Connect Companion` while signed in.
6. Return to the chart. The Companion now shows the connected JournalMe account.

The connection stores the Supabase browser session inside Chrome extension storage and refreshes it when needed. The service-role key is never used by the extension.

## Capture flow

- `Alt+C` captures the current chart and opens the side panel.
- Choose the JournalMe account, capture type, side, context, execution notes, state, and optional free text.
- `Save capture` writes to the configured JournalMe API with the hosted bearer token when connected.
- After save, an existing JournalMe web tab is routed in the background to the exact capture. If no JournalMe tab exists, one is created in the background.
- `Open saved` brings that capture to the foreground.
- Recent captures in the side panel open the matching item in the web Capture workspace.

## Local mode

`Use local` returns the Companion to the local API at `http://127.0.0.1:8066`. Hosted and local modes remain separate.

## Development origins

The current external connection allow-list supports:

- `http://localhost:3070/*`
- `http://127.0.0.1:3070/*`

Add the final production JournalMe web origin to `externally_connectable.matches` before publishing the extension.
