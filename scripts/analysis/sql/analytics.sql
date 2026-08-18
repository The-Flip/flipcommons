-- The analytics schema.
--
-- README.md to do analysis; EDITING.md to change this file.
--
-- Three schemas, all named catalog-relative:
--   raw  — the imported Django tables, already there before this runs.
--   stg  — the staging views (staging.sql). Read only raw.
--   main — the public surface.

-- ── layers ──────────────────────────────────────────────────────────────────
.read scripts/analysis/sql/staging.sql
.read scripts/analysis/sql/entity_registry.sql
.read scripts/analysis/sql/catalog.sql
.read scripts/analysis/sql/prose.sql
.read scripts/analysis/sql/shared_hosts.sql
.read scripts/analysis/sql/provenance.sql
.read scripts/analysis/sql/data_patches.sql

-- ── self-test ───────────────────────────────────────────────────────────────
.read scripts/analysis/sql/catalog_checks.sql
.read scripts/analysis/sql/prose_checks.sql
.read scripts/analysis/sql/provenance_checks.sql
.read scripts/analysis/sql/data_patches_checks.sql
.read scripts/analysis/sql/foundation_checks.sql

-- ── audit ───────────────────────────────────────────────────────────────────
-- Lint rules over the live catalog. Its findings are catalog content, not checks
.read scripts/analysis/sql/audit.sql

-- ── reference index ─────────────────────────────────────────────────────────
.read scripts/analysis/sql/relation_index.sql
