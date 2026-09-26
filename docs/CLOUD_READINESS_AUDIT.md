# Cloud Readiness audit — v0.1

| Coupling found | Severity | Action tonight | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` defaults to relative SQLite `./journalme.db` | Medium | Documented/config-validated | Local remains intentional; no database migration. |
| Local storage root uses relative `./storage` and `pathlib` | High | Fixed boundary | `StorageProvider` and factory now isolate byte storage. |
| Routes/services directly constructed `LocalFileStorage` | High | Fixed in capture, core attachment, import/export seams | Provider factory now owns selection. |
| Backup status returned physical database/storage paths | Medium | Fixed | API returns provider descriptions, not machine paths. |
| Local identity resolves configured local user | Medium | Boundary documented/strengthened | `get_current_user` remains one authoritative adapter. |
| Frontend local API fallback | Medium | Centralized existing seam | `NEXT_PUBLIC_JOURNALME_API_URL` is the primary frontend API-origin setting; `NEXT_PUBLIC_API_URL` remains a legacy fallback. |
| Electron starts local backend/frontend | Medium | Centralized runtime seam | Default remains local; cloud mode explicitly rejected, not faked. |
| Desktop frontend identity at 3066 | Low | Preserved | `/api/desktop-health` prevents unrelated localhost loading. |
| PWA uses origin-relative manifest/service worker | Low | Documented | Suitable for hosted origin; no offline sync. |
| Import fixture/tests use SQLite and local paths | Low | Deferred | Test implementation detail, not client contract. |

No API inspected exposes raw attachment storage keys as an operating-system path. `ImportFile.stored_path` and attachment/capture keys are opaque relative keys; future migrations must preserve that property.
