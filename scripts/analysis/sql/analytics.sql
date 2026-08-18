-- The analytics schema, one entry point — everything `ensure_snapshot` bakes into
-- db.analytics.duckdb. The runner never loads this per-query; it loads once per build,
-- which is why a change to any file under scripts/analysis/sql/ triggers a rebuild.
--
-- Order matters only as far as the `.read` chains express it: catalog_checks.sql pulls
-- in the foundation (catalog.sql and the layers it reads) before defining the self-test,
-- and audit.sql re-reads catalog.sql, which is idempotent — every definition is CREATE
-- OR REPLACE — and costs a moment at build time, never at query time.
.read scripts/analysis/sql/catalog_checks.sql
.read scripts/analysis/sql/audit.sql
