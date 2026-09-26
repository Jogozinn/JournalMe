# JournalMe Desktop development

Prerequisites: Node 22+, the existing `frontend/node_modules`, and the project Python environment at `D:\PythonProjects\JournalMe\.venv`.

From `D:\PythonProjects\JournalMe\desktop`:

```powershell
npm install
npm run dev
```

`npm run dev` compiles Electron, starts/reuses the FastAPI backend at `http://127.0.0.1:8066`, then starts/reuses only a verified JournalMe Next.js frontend at `http://127.0.0.1:3066`. It requires `GET /api/desktop-health` to return the JournalMe identity marker. A different application on port 3066 is not loaded and produces a clear port-conflict error. The backend child always runs with `backend/` as its CWD. Use `npm run start` for a compiled Electron run with an already available frontend.

Equivalent commands from `frontend/` are `npm run desktop:dev`, `npm run desktop:start`, and `npm run desktop:build`.

Validation:

```powershell
cd desktop; npm run typecheck; npm test
cd ..\backend; ..\.venv\Scripts\python.exe -m pytest tests/test_capture_matching.py
cd ..\frontend; npm run typecheck; npm test
```

Manual smoke test: start desktop, close its full window, press `Alt+C` over another application, fill Entry/MNQ/side/tag/note, save, check the Recent captures list and API result, restore the full window from the tray, then quit from the tray. A running backend discovered before startup remains running after quit; an Electron-owned child is stopped.

If Alt+C is owned by another application, JournalMe logs the conflict and the tray companion remains usable. Logs are at Electron's user-data `logs/desktop.log` path and intentionally exclude screenshot bytes and note contents.
