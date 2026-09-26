# JournalMe Desktop architecture

JournalMe Desktop is an Electron shell in `desktop/`; it does not own journal data or reconciliation.

```
Electron main process
  ├─ BackendManager → existing FastAPI (`backend/`, 127.0.0.1:8066)
  ├─ FrontendManager → existing Next.js app (127.0.0.1:3066 in development)
  ├─ full BrowserWindow → existing JournalMe frontend
  ├─ Tray + single-instance + Alt+C
  └─ secure preload → floating companion → existing /api/v1/captures
```

The backend is first checked at `/api/v1/health`. Only `{status:"ok",product:"JournalMe"}` is reused. A child backend is started only when that check fails, with its working directory set to `backend/`; this preserves its relative SQLite database and storage paths. Electron only terminates a child it started.

The frontend uses the dedicated `http://127.0.0.1:3066` development URL. Before it is reused or loaded, Electron requests `/api/desktop-health` and requires `{status:"ok",product:"JournalMe",surface:"frontend"}`. An occupied port without that identity is a hard error; Electron never loads the unrelated page.

The screenshot stays in Electron memory for 30 minutes or until a successful save. The renderer receives a preview and opaque token, never filesystem or shell access. On save, main-process code posts multipart `metadata` and screenshot bytes to the current capture endpoint with `source: journalme_desktop`. Matching remains entirely in FastAPI.

The full window hides on close. The tray menu can restore it, trigger a capture, toggle the companion, or quit. The companion follows the work area of the display under the mouse cursor and is always on top.
