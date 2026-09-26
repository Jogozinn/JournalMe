# JournalMe Companion v0.6.0

JournalMe Companion signs directly into JournalMe cloud and can save captures even when the JournalMe website has never been opened in the current browser session.

## Cloud sign-in

1. Load the `extension` folder as an unpacked Chrome extension.
2. Open the Companion side panel.
3. Sign in with the same JournalMe email and password used on the web app.
4. The Companion loads that user's JournalMe accounts and recent captures.
5. The stored Supabase user session refreshes automatically in Chrome extension storage.

The extension never uses the Supabase service-role key or database credentials. It obtains only browser-safe hosted auth configuration from the JournalMe API and sends the signed-in user's bearer token with JournalMe API requests.

## Capture flow

- `Alt+C` captures the current chart and opens the side panel.
- Choose the JournalMe account, capture type, side, context, execution notes, state, and optional free text.
- `Save capture` writes directly to the hosted JournalMe API.
- The JournalMe website does not need to be open for capture or sync.
- `Open JournalMe` and `Open saved` are optional shortcuts to the full web journal.
- A new user with no trading accounts can still save captures to their JournalMe user record. The Companion clearly indicates that no trading account exists yet.

## Production defaults

- Web app: `https://journalme-beige.vercel.app`
- API root: `https://p01--journalme-api--z928s7lw8hps.code.run`

## Local development

Open the extension options page and switch Connection mode to `Local development`. Local development can continue to use:

- API: `http://127.0.0.1:8066`
- Web: `http://localhost:3070`

Existing users upgrading from the old untouched localhost defaults are migrated to the hosted production defaults. Explicit custom settings are preserved.
