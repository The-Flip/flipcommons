-- Staging layer — the live rows of each lifecycle table, and the macros that
-- spell liveness and absence exactly once.
--
-- README.md to do analysis; EDITING.md to change this file.
--
-- Loaded first (see analytics.sql, the manifest): every later layer reads these
-- macros, and the `stg` schema created here is the layer boundary the self-test
-- polices (`staging_view_not_flat`).
CREATE SCHEMA IF NOT EXISTS stg;

-- ═══ §210 LIVENESS — how to hide soft-deleted records ═══════════════════════
CREATE OR REPLACE MACRO is_live(status) AS status IS DISTINCT FROM 'deleted';
COMMENT ON MACRO is_live IS
  'is_live(status) — the liveness rule as a scalar, for a view that carries a status column instead of being live-filtered. Never retype the predicate.';

-- ═══ §220 STAGING LAYER — the live rows of a table ════════
-- These private views drop soft-deleted rows and bookkeeping columns, spell absence one way.
-- One `stg.x` view per lifecycle table. No joins, no derived columns, no measures, so
-- nothing here has an outgoing edge and no cycle can run through it.
-- An entity view carries measures over the models beneath it (`titles.n_models`), so
-- reaching through one for a neighbour's slug drags its aggregate along — `models` joining
-- `titles` would close a loop. Hence the rule: join the STAGING view to decode an
-- identity, the ENTITY view to read a measure.
-- A table read from ONE place gets none — `cabinets` IS `_staging('raw.catalog_cabinet')`.

-- The `::VARCHAR` cast is inside the comparison, not around the value, so this is safe to
-- apply to every column at once: `NULLIF(COLUMNS(*), '')` fails with a conversion error on
-- the first integer, while CASE returns the column untouched and preserves its type.
-- Apply BY NAME, never by testing whether a table has the columns for it: '' is a real
-- value in citation_citationsourcerootdomain.path_prefix, where it means "whole host".
CREATE OR REPLACE MACRO _blanks_null(tbl) AS TABLE
  SELECT CASE WHEN COLUMNS(*)::VARCHAR = '' THEN NULL ELSE COLUMNS(*) END
  FROM query_table(tbl);
COMMENT ON MACRO TABLE _blanks_null IS
  '_blanks_null(''raw.x'') — every column of a table with '''' folded to NULL, types preserved. The source read for a table with no lifecycle; _staging() already includes it.';

-- A claim value is a JSONField, so `"500"` and `500` are different values and both are in
-- the data: of the 73 claims asserting production_quantity 500, `value = '500'` finds one.
-- The OBJECT/ARRAY guard: json_extract_string serializes a member payload back to
-- `{"exists":true,…}`, which would read as a scalar on rows that have none.
CREATE OR REPLACE MACRO _json_scalar_text(v) AS
  CASE WHEN json_type(v) NOT IN ('OBJECT', 'ARRAY')
       THEN NULLIF(json_extract_string(v, '$'), '')
  END;
COMMENT ON MACRO _json_scalar_text IS
  '_json_scalar_text(value) — a JSON scalar as text, with "500" and 500 folded to the same value and '''' folded to NULL. NULL for an object or array, which have no scalar to report.';

-- _staging('raw.catalog_x') is how analytics reads source tables.
-- Drops soft-deleted rows and bookkeeping columns, spells absence one way.
--
-- Use it for the SOURCE read only — joins through the joined entity's own view.
-- Fails loudly (Binder Error on `status`) against a table with no lifecycle.
CREATE OR REPLACE MACRO _staging(tbl) AS TABLE
  SELECT * EXCLUDE (status, created_at, updated_at)
  FROM _blanks_null(tbl)
  WHERE is_live(status);
COMMENT ON MACRO TABLE _staging IS
  '_staging(''raw.catalog_x'') — the live rows of a lifecycle table minus status/created_at/updated_at, with '''' folded to NULL. The source read for every entity view; joins use the joined entity''s view instead.';

CREATE OR REPLACE VIEW stg.machine_model     AS SELECT * FROM _staging('raw.catalog_machinemodel');
CREATE OR REPLACE VIEW stg.title             AS SELECT * FROM _staging('raw.catalog_title');
CREATE OR REPLACE VIEW stg.corporate_entity  AS SELECT * FROM _staging('raw.catalog_corporateentity');
CREATE OR REPLACE VIEW stg.manufacturer      AS SELECT * FROM _staging('raw.catalog_manufacturer');
CREATE OR REPLACE VIEW stg.reward_type       AS SELECT * FROM _staging('raw.catalog_rewardtype');
CREATE OR REPLACE VIEW stg.series            AS SELECT * FROM _staging('raw.catalog_series');
CREATE OR REPLACE VIEW stg.person            AS SELECT * FROM _staging('raw.catalog_person');
CREATE OR REPLACE VIEW stg.credit_role       AS SELECT * FROM _staging('raw.catalog_creditrole');
CREATE OR REPLACE VIEW stg.tag               AS SELECT * FROM _staging('raw.catalog_tag');
CREATE OR REPLACE VIEW stg.theme             AS SELECT * FROM _staging('raw.catalog_theme');
CREATE OR REPLACE VIEW stg.gameplay_feature  AS SELECT * FROM _staging('raw.catalog_gameplayfeature');
