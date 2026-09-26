# Data Export and Backup

JournalMe provides synchronous exports for the current local/personal scale:

- account trades as CSV
- journals and daily reviews as JSON
- filtered analytics tables as CSV
- a ZIP archive containing schema metadata, accounts, execution records,
  journals, playbooks, reviews, preferences, and attachment files

Every export applies the authenticated user and account ownership boundary.
Archive metadata contains an `export_schema_version`, generation time, and
product version. External broker identifiers and source payloads are included
only in the full archive because it is intended as a private backup.

For local mode, back up `journalme.db` and `storage/` together while the API is
stopped. Restore both to the configured paths before starting the API. The API
runs Alembic upgrades at startup. A future restore importer must validate the
archive schema and stage changes transactionally; Phase 2 does not silently
merge an archive into a live ledger.

Destructive reset is intentionally separate from export and requires typed
confirmation. A backup should be created before reset.
