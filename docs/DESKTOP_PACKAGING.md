# JournalMe Desktop packaging

The Windows build command is:

```powershell
cd D:\PythonProjects\JournalMe\desktop
npm run package:win
```

It produces NSIS and portable Windows targets in `desktop/release/`. Before packaging, prepare the Next standalone output:

```powershell
cd ..\frontend
npm run build
```

Electron Builder includes the resulting standalone frontend and static/public assets. In a packaged app, Electron starts that bundled Next server with `ELECTRON_RUN_AS_NODE` only when no verified JournalMe frontend is already available on port 3066. This v0.1 package deliberately does **not** bundle FastAPI/Python: the installed desktop app requires a healthy compatible local API at port 8066 and gives a clear startup error when it is absent. Development remains able to start the existing backend from `backend/`. This is intentional until Python bundling can be made data-safe and fully tested; packaging must not silently create, relocate, or overwrite the SQLite database.

For a standalone v0.2 installer, package the existing Python virtual environment or a PyInstaller backend executable, configure explicit data/storage locations, migrate only after backup, and retain the same health/ownership protocol.
