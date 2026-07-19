-- Foundation self-test — run this after editing catalog.sql to confirm it still
-- holds its invariants. NOT part of the foundation (catalog.sql stays pure views);
-- this is a separate consumer that .reads it, exactly like a plan file, with the
-- same summary/checks contract the runner gates on.
--
--     scripts/analysis/analysis run scripts/analysis/catalog_checks.sql foundation
--
-- Prints foundation_summary (row count per view — a health readout), then fails
-- nonzero if foundation_checks returns any row. EMPTY foundation_checks = healthy.
-- Three classes:
--   structural — data-independent invariants; a row means the SQL logic broke, not
--                that the catalog changed. These make evolving the foundation safe.
--   anchor     — a decoded facet went unexpectedly all-empty (a join/extract broke) —
--                the one failure a row-level invariant can't see. GENERATED from the
--                views themselves (see the _anchor_scan block), so the anchor set can't
--                drift behind the columns; data-dependent but decisive on a populated DB.
--   coverage   — meta-checks that fail when a new VIEW or array facet is added without
--                being anchored, so the generated sweep can't be silently out-run.
.read scripts/analysis/catalog.sql

-- foundation_summary — row count per public view; doubles as a health dashboard.
CREATE OR REPLACE VIEW foundation_summary AS
  SELECT 'models'              AS view_name, count(*) AS n_rows FROM models
  UNION ALL SELECT 'all_models',          count(*) FROM all_models
  UNION ALL SELECT 'model_lineage',       count(*) FROM model_lineage
  UNION ALL SELECT 'model_relationships', count(*) FROM model_relationships
  UNION ALL SELECT 'model_edges',         count(*) FROM model_edges
  UNION ALL SELECT 'rewards',             count(*) FROM rewards
  UNION ALL SELECT 'themes',              count(*) FROM themes
  UNION ALL SELECT 'tags',                count(*) FROM tags
  UNION ALL SELECT 'model_gameplay_features', count(*) FROM model_gameplay_features
  UNION ALL SELECT 'model_export_markets', count(*) FROM model_export_markets
  UNION ALL SELECT 'countries',           count(*) FROM countries
  UNION ALL SELECT 'game_formats',        count(*) FROM game_formats
  UNION ALL SELECT 'title_size',          count(*) FROM title_size
  ORDER BY view_name;

-- ─── Generated dark anchors ─────────────────────────────────────────────────
-- The anchor set used to be a hand-written list — one `WHERE count(col) = 0` line per
-- decoded facet — kept in sync with the view columns by memory. That list drifted every
-- time a column was added (the reason facets kept "going dark" unnoticed). These three
-- objects replace it with a sweep that derives the anchors from the views themselves:
--   _dark_cols(view)  a table macro: COUNT(COLUMNS(*)) over the view, UNPIVOTed to one
--                     row per column — so a column that decodes to all-NULL surfaces as
--                     non_null = 0, with NO per-column list to maintain.
--   _anchor_scan      that sweep run over every public decode view. Adding a column to
--                     any of them anchors it for free; adding a whole VIEW without
--                     listing it here is caught by the `unanchored_view` meta-check.
--   _anchor_skip      the only hand-input left: columns ALLOWED to be entirely empty
--                     (genuinely-sparse optional facets that would false-positive). It
--                     is a short EXCEPTION list with a safe default — forgetting an
--                     entry over-anchors (loud), it never silently under-anchors.
CREATE OR REPLACE MACRO _dark_cols(vn) AS TABLE
  UNPIVOT (SELECT COUNT(COLUMNS(*)) FROM query_table(vn))
    ON COLUMNS(*) INTO NAME col VALUE non_null;

CREATE OR REPLACE VIEW _anchor_scan AS
            SELECT 'all_models'              AS view_name, col, non_null FROM _dark_cols('all_models')
  UNION ALL SELECT 'models',                 col, non_null FROM _dark_cols('models')
  UNION ALL SELECT 'countries',              col, non_null FROM _dark_cols('countries')
  UNION ALL SELECT 'game_formats',           col, non_null FROM _dark_cols('game_formats')
  UNION ALL SELECT 'rewards',                col, non_null FROM _dark_cols('rewards')
  UNION ALL SELECT 'themes',                 col, non_null FROM _dark_cols('themes')
  UNION ALL SELECT 'tags',                   col, non_null FROM _dark_cols('tags')
  UNION ALL SELECT 'model_gameplay_features',col, non_null FROM _dark_cols('model_gameplay_features')
  UNION ALL SELECT 'model_edges',            col, non_null FROM _dark_cols('model_edges')
  UNION ALL SELECT 'model_lineage',          col, non_null FROM _dark_cols('model_lineage')
  UNION ALL SELECT 'model_relationships',    col, non_null FROM _dark_cols('model_relationships')
  UNION ALL SELECT 'title_size',             col, non_null FROM _dark_cols('title_size');

CREATE OR REPLACE VIEW _anchor_skip AS
  -- Matched by column name (these names are unique to their facet). Sparse dims the app
  -- barely populates today; anchoring them would false-positive the moment the last one
  -- is edited away. Remove an entry here once its dim is broadly populated.
  -- export_edition_of_id is data-pending: the column shipped ahead of the export
  -- data patches (Exports.md), so it is legitimately all-NULL until they land —
  -- remove the entry (and anchor the model_lineage export_edition_of
  -- subpopulation) once they do.
  SELECT unnest([
    'technology_subgeneration_slug',
    'display_subtype_slug',
    'export_edition_of_id'
  ]) AS col;

-- foundation_checks — invariants. EMPTY = healthy; any row is a violation with a
-- check_name and a diagnostic detail.
CREATE OR REPLACE VIEW foundation_checks AS
  -- ── structural: data-independent; a row means the SQL logic broke ──

  -- model_edges is a LOSSLESS union of the two mechanism views (no dedup, no fan-out)
  SELECT 'union_integrity' AS check_name,
         'model_edges=' || (SELECT count(*) FROM model_edges)::VARCHAR
           || ' <> lineage+relationships='
           || ((SELECT count(*) FROM model_lineage)
               + (SELECT count(*) FROM model_relationships))::VARCHAR AS detail
  WHERE (SELECT count(*) FROM model_edges)
        <> (SELECT count(*) FROM model_lineage) + (SELECT count(*) FROM model_relationships)

  -- model_lineage grain: at most one row per (model, edge_kind)
  UNION ALL
  SELECT 'lineage_grain_dup',
         'model_id=' || model_id::VARCHAR || ' edge_kind=' || edge_kind
           || ' n=' || count(*)::VARCHAR
  FROM model_lineage GROUP BY model_id, edge_kind HAVING count(*) > 1

  -- live filter: models carries no soft-deleted row
  UNION ALL
  SELECT 'models_has_deleted', 'model_id=' || id::VARCHAR
  FROM models WHERE status = 'deleted'

  -- live filter: models is a subset of all_models
  UNION ALL
  SELECT 'models_not_subset_of_all', 'model_id=' || id::VARCHAR
  FROM models WHERE id NOT IN (SELECT id FROM all_models)

  -- design contract: license_status IS NULL  <=>  edge_source = 'lineage_fk'
  UNION ALL
  SELECT 'edge_license_contract',
         'edge_source=' || edge_source
           || ' license_status=' || COALESCE(license_status, '<null>')
  FROM model_edges
  WHERE (edge_source = 'lineage_fk') IS DISTINCT FROM (license_status IS NULL)

  -- subject integrity: every edge belongs to a live model
  UNION ALL
  SELECT 'edge_subject_not_live', 'model_id=' || model_id::VARCHAR
  FROM model_edges WHERE model_id NOT IN (SELECT id FROM models)

  -- every lineage edge carries an FK target (guards the edges CTE's IS NOT NULL
  -- filter); variant_of/remake_of are non-null self-FKs on the rows that have them.
  UNION ALL
  SELECT 'lineage_missing_target_id',
         'model_id=' || model_id::VARCHAR || ' edge_kind=' || edge_kind
  FROM model_lineage WHERE target_id IS NULL

  -- integrity: a RESOLVED target (lineage OR typed) that isn't live — target_id set
  -- but target_slug NULL, since a live model always has a slug. The app blocks soft-
  -- deleting a model that is an ACTIVE variant_of/remake_of target or an inbound typed
  -- relationship target (soft_delete_usage_blockers; see test_api_model_delete.py —
  -- test_remake_of_referrer_blocks returns 422), so a live source pointing at a
  -- soft-deleted target is unreachable unless that protection was bypassed. Both edge
  -- kinds get the same check; the LEFT JOIN de-enrich is defensive, not an expected path.
  UNION ALL
  SELECT 'lineage_target_not_live',
         'model_id=' || model_id::VARCHAR || ' target_id=' || target_id::VARCHAR
           || ' edge_kind=' || edge_kind
  FROM model_lineage WHERE target_id IS NOT NULL AND target_slug IS NULL
  UNION ALL
  SELECT 'relationship_target_not_live',
         'model_id=' || model_id::VARCHAR || ' target_id=' || target_id::VARCHAR
           || ' type=' || relationship_type
  FROM model_relationships WHERE target_id IS NOT NULL AND target_slug IS NULL

  -- export-market targets are always live countries: the app restricts the FK to
  -- root Locations (COUNTRY_TARGET_FILTER) and blocks soft-deleting a targeted
  -- location (export_market_models usage blocker), so a set target_location_id
  -- that doesn't enrich through `countries` means one of those protections was
  -- bypassed (or the location was re-parented under another).
  UNION ALL
  SELECT 'export_market_target_not_country',
         'model_id=' || model_id::VARCHAR
           || ' target_location_id=' || target_location_id::VARCHAR
  FROM model_export_markets
  WHERE target_location_id IS NOT NULL AND target_country_slug IS NULL

  -- vocabulary: relationship_type and license_status are CLOSED sets, DB-enforced
  -- (catalog_modelrelationship_type_valid / _license_status_valid). These checks pin
  -- the foundation's "closed set" docs to the model — a new backend value fails here
  -- and forces the comment/README update, instead of the docs silently rotting.
  UNION ALL
  SELECT 'relationship_type_unknown',
         'model_id=' || model_id::VARCHAR || ' type=' || relationship_type
  FROM model_relationships
  WHERE relationship_type NOT IN ('conversion', 'conversion_kit', 'copy', 'retheme')
  UNION ALL
  SELECT 'license_status_unknown',
         'model_id=' || model_id::VARCHAR || ' license=' || license_status
  FROM model_relationships
  WHERE license_status NOT IN ('licensed', 'unlicensed', 'unknown')

  -- edge discriminator + type are always populated from a known shape
  UNION ALL
  SELECT 'edge_source_unknown', 'edge_source=' || edge_source
  FROM model_edges WHERE edge_source NOT IN ('lineage_fk', 'relationship')
  UNION ALL
  SELECT 'edge_relationship_type_null',
         'model_id=' || model_id::VARCHAR || ' edge_source=' || edge_source
  FROM model_edges WHERE relationship_type IS NULL

  -- model_gameplay_features grain: at most one row per (model, feature)
  UNION ALL
  SELECT 'gpf_grain_dup',
         'model_id=' || model_id::VARCHAR || ' feature_id=' || feature_id::VARCHAR
           || ' n=' || count(*)::VARCHAR
  FROM model_gameplay_features GROUP BY model_id, feature_id HAVING count(*) > 1

  -- model_gameplay_features subjects are live (mirrors edge_subject_not_live)
  UNION ALL
  SELECT 'gpf_subject_not_live', 'model_id=' || model_id::VARCHAR
  FROM model_gameplay_features WHERE model_id NOT IN (SELECT id FROM models)

  -- grain guard: models.location_path / country_slug (and their target_* twins) come
  -- from _ce_location, which assumes CE -> live location is 1:1 (true across the whole
  -- catalog today). If a CE ever carries more than one live location _ce_location
  -- silently picks one and those columns turn lossy — so flag it here and add a
  -- model_locations grain view rather than let the scalar quietly drop a location.
  UNION ALL
  SELECT 'ce_multi_location',
         'corporate_entity_id=' || corporate_entity_id::VARCHAR || ' n=' || n::VARCHAR
  FROM (
    SELECT cel.corporate_entity_id, count(*) AS n
    FROM fc.catalog_corporateentitylocation cel
    JOIN fc.catalog_location l
      ON l.id = cel.location_id AND l.status IS DISTINCT FROM 'deleted'
    GROUP BY cel.corporate_entity_id
    HAVING count(*) > 1
  )

  -- target genre propagates: a RESOLVED edge target's game_format matches the model's
  -- own (guards the new target_game_format_* facet on _model_target). Only checks
  -- resolved targets — target_slug NULL means de-enriched, already covered elsewhere.
  UNION ALL
  SELECT 'target_genre_mismatch',
         'model_id=' || model_id::VARCHAR || ' target_id=' || target_id::VARCHAR
  FROM model_edges e
  WHERE target_id IS NOT NULL AND target_slug IS NOT NULL
    AND target_game_format_slug IS DISTINCT FROM
        (SELECT game_format_slug FROM models m WHERE m.id = e.target_id)

  -- ── anchors: a decoded facet went unexpectedly all-empty (a join/extract broke) ──
  -- GENERATED from _anchor_scan (see the macro block above), so every column of every
  -- public view is dark-anchored automatically — including whole-view-empty, which
  -- shows up as ALL its columns reading zero. Nothing to keep in sync per column.
  UNION ALL
  SELECT 'anchor_dark', view_name || '.' || col
  FROM _anchor_scan
  WHERE non_null = 0 AND col NOT IN (SELECT col FROM _anchor_skip)

  -- Array facets (VARCHAR[], empty never NULL) can't dark via COUNT — an all-empty
  -- array still counts as non-null — so the two that exist get an explicit non-empty
  -- sweep. The `unanchored_array` meta-check below fails if a third appears unlisted.
  UNION ALL SELECT 'anchor_dark', 'all_models.opdb_features (all empty)'
    WHERE (SELECT count(*) FROM all_models WHERE len(opdb_features) > 0) = 0
  UNION ALL SELECT 'anchor_dark', 'model_edges.target_reward_types (all empty)'
    WHERE (SELECT count(*) FROM model_edges WHERE len(target_reward_types) > 0) = 0

  -- Subpopulation anchors the column sweep CAN'T see: a filtered subset going dark
  -- while the column still has values from the other subset. One per lineage kind.
  UNION ALL SELECT 'anchor_dark', 'model_lineage variant_of is empty'
    WHERE (SELECT count(*) FROM model_lineage WHERE edge_kind = 'variant_of') = 0
  UNION ALL SELECT 'anchor_dark', 'model_lineage remake_of is empty'
    WHERE (SELECT count(*) FROM model_lineage WHERE edge_kind = 'remake_of') = 0

  -- ── coverage: close the last hand-lists so a NEW view/array can't slip in unanchored ──
  -- A public foundation view not swept by _anchor_scan (added without being anchored).
  -- analysis_context is excluded on purpose — a watermark whose NULLs are legitimate.
  -- model_export_markets is excluded as data-pending: the table shipped ahead of
  -- the export data patches (Exports.md), so the view is legitimately empty and a
  -- column sweep would dark-anchor every column (and its target_label / model_id
  -- names collide with populated facets in other views, so _anchor_skip can't
  -- carry them). Move it into _anchor_scan once the patches land.
  UNION ALL
  SELECT 'unanchored_view', table_name
  FROM information_schema.tables
  WHERE table_schema = 'main' AND table_type = 'VIEW'
    AND table_name NOT LIKE '\_%' ESCAPE '\'
    AND table_name NOT IN (
      'foundation_summary', 'foundation_checks', 'analysis_context',
      'model_export_markets'
    )
    AND table_name NOT IN (SELECT DISTINCT view_name FROM _anchor_scan)

  -- A VARCHAR[] facet in a swept view that isn't accounted for would silently escape
  -- the dark check (COUNT can't see an array empty), so flag any new one for a home.
  -- Two need an explicit non-empty anchor (above): opdb_features / target_reward_types,
  -- whose row exists regardless of the array, so all-empty is a distinct dark state.
  -- The flat-list views (rewards/themes/tags) do NOT — a row exists only when the list
  -- is non-empty, so their scalar `id` column already anchors view-emptiness for free.
  UNION ALL
  SELECT 'unanchored_array', table_name || '.' || column_name
  FROM information_schema.columns
  WHERE table_schema = 'main' AND data_type LIKE '%[]%'
    AND table_name IN (SELECT DISTINCT view_name FROM _anchor_scan)
    AND column_name NOT IN ('opdb_features', 'target_reward_types', 'rewards', 'themes', 'tags');
