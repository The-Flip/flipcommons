-- Run context — the input watermark for an analysis run.
--
-- README.md to do analysis; EDITING.md to change this file.
--
-- Its own manifest entry, loaded after everything it summarizes. It belongs to no layer:
-- the row spans the schema point, the catalog, the ingest ledger and the import stamp,
-- and no single layer owns that mix. Loading late is what lets it read the PUBLIC views
-- of what it summarizes (`ingest_runs`, `changesets`) rather than reaching into the
-- `raw.` tables those layers exist to decode, and it leaves the checks and the audit
-- available to a future field.
--
-- Not last, though: relation_index.sql indexes the relations that exist WHEN IT RUNS, so
-- anything defined after it is missing from `describe` and from `analysis columns`.
--
-- Each layer contributes its own `<layer>_context` view alongside this one; the runner
-- discovers them by name and prints them together above the results. This one is the
-- run's, not a layer's.

-- ═══ §230 RUN WATERMARK ═════════════════════════════════════════════════════
-- analysis_context — the input watermark for a run, printed by every runner above the
-- results. Enough identity to tell "same query, newer catalog" apart from a broken
-- reproduction: a query is reproducible, but its RESULTS only are when this row matches.
--   migrations_applied / latest_migration : the schema point — count + newest name, not
--       the raw max(id) insertion sequence (which is neither a head nor comparable).
--   latest_patch / patch_fingerprint : the newest SUCCESSFULLY-applied data patch and its
--       content hash, filtered to status='success' with a non-null patch_id so a
--       failed/running/interactive ingest can't misreport it.
--   latest_changeset : catches interactive edits — the drift a patch id can't see.
--   snapshot_imported_at : when `fc` was last imported from db.sqlite3. Every other field
--       here is read THROUGH that import, so it dates all of them.
-- `provenance_context` carries that layer's counts and does not restate these; read the two
-- together.
CREATE OR REPLACE VIEW analysis_context AS
  SELECT
    version()                                    AS duckdb_version,
    (SELECT count(*) FROM models)                AS live_models,
    (SELECT count(*) FROM raw.django_migrations)  AS migrations_applied,
    (SELECT app || '.' || name FROM raw.django_migrations ORDER BY id DESC LIMIT 1) AS latest_migration,
    (SELECT patch_id FROM ingest_runs
       WHERE status = 'success' AND patch_id IS NOT NULL ORDER BY ingest_run_id DESC LIMIT 1) AS latest_patch,
    (SELECT input_fingerprint FROM ingest_runs
       WHERE status = 'success' AND patch_id IS NOT NULL ORDER BY ingest_run_id DESC LIMIT 1) AS patch_fingerprint,
    (SELECT max(changeset_id) FROM changesets)   AS latest_changeset,
    (SELECT imported_at FROM raw._import_stamp)  AS snapshot_imported_at;
COMMENT ON VIEW analysis_context IS
  'One row — the input watermark: DuckDB version, live model count, migration point, latest successful patch + fingerprint, latest changeset id, and when the catalog was imported. Printed by every analysis run.';
