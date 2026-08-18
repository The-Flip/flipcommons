-- Catalog self-test — the invariants for catalog.sql.
--
-- Not a standalone analysis: analytics.sql loads this after the layers, and
-- foundation_checks.sql folds `_catalog_checks` into `foundation_checks`, so there is
-- ONE gate and one mutation-harness entry point. Private (`_` prefix) for that reason —
-- a public `*_checks` view would ALSO be discovered by the runner's sweep and every
-- failure would report twice. The same arrangement as provenance_checks.sql and
-- data_patches_checks.sql.
--
-- Same contract as the rest of the self-test: a row means something broke, empty means
-- healthy, and every check_name here needs a line in catalog_mutations.tsv proving it
-- fires. The house rule — compare with IS DISTINCT FROM, never <>, and null-test
-- operands before any ordering operator — is stated in full above foundation_checks
-- (foundation_checks.sql) and applies to every branch here.

-- ─── Check-only scaffolding ─────────────────────────────────────────────────
-- Private views that exist ONLY so a check has something to read. They live here
-- rather than in catalog.sql for one reason: nothing a consumer can query depends on
-- them, and they were sitting in front of the foundation's first public view.
--
-- Why they must be VIEWS at all: `fc` is attached READ_ONLY and its tables cannot be
-- shadowed, so a check written directly against `raw.` could never be mutation-tested —
-- it would be a check nobody could prove fires. Each of these restates a slice of the
-- physical layer as something check-mutations can break on purpose.
--
-- The test for whether something belongs here rather than in catalog.sql: does any
-- PUBLIC view consume it? _ce_location and _title_live_n feed models, so they stay
-- there. These do not.


-- _ce_location_n — live locations per CE. catalog.sql's `_ce_location` collapses a CE
-- to ONE row on the assumption that every CE has exactly one live location; this states
-- that assumption as a number so ce_multi_location can test it.

CREATE OR REPLACE VIEW _ce_location_n AS
  SELECT corporate_entity_id, count(*) AS n
  FROM corporate_entity_locations
  GROUP BY corporate_entity_id;

-- ─── Dimension liveness scaffolding ───────────────────────────────────────
-- These three views exist so that check can read a VIEW instead of the `raw.` tables:
-- `fc` is READ_ONLY and unshadowable, so a check written against it could never be
-- mutation-tested (same reasoning as _ce_location_n above).
--   _model_dim_ref       (live model, dim column, target id) — UNPIVOT drops the NULLs,
--                        so only dims the model actually sets appear.
--   _dim_status          (dim column, id, status) for every dim table. Keyed by the FK
--                        COLUMN name so the two lists join, and so the coverage
--                        meta-check (uncovered_model_dim) can compare this against the
--                        real column list of raw.catalog_machinemodel — a new dim FK on
--                        MachineModel fails loudly here instead of going uncovered.
--   _model_dim_liveness  the violations: a live model on a soft-deleted dim.
-- Split wide-then-UNPIVOT rather than UNPIVOT-over-a-subquery so the dim set is a
-- COLUMN LIST a check can read off duckdb_columns(). Read off the DATA instead and the
-- check is only as good as the catalog: display_subtype_id has exactly ONE live row
-- today, so one edit away a data-derived dim list would drop it and the check would
-- report a hole that isn't there. Structural beats data-dependent for a coverage claim.
CREATE OR REPLACE VIEW _model_dim_wide AS
  SELECT m.id AS model_id,
         m.title_id, m.corporate_entity_id, ce.manufacturer_id,
         m.game_format_id,
         m.technology_generation_id, m.technology_subgeneration_id,
         m.display_type_id, m.display_subtype_id,
         m.system_id, m.cabinet_id, m.production_status_id
  FROM raw.catalog_machinemodel m
  LEFT JOIN raw.catalog_corporateentity ce ON ce.id = m.corporate_entity_id
  WHERE m.status IS DISTINCT FROM 'deleted';

-- COLUMNS(* EXCLUDE (model_id)), not a written-out ON list: the list above is the ONE
-- place the dim set is stated, so it cannot disagree with a second copy here.
CREATE OR REPLACE VIEW _model_dim_ref AS
  UNPIVOT _model_dim_wide
  ON COLUMNS(* EXCLUDE (model_id))
  INTO NAME dim VALUE target_id;

-- manufacturer_id is reached through corporate_entity (it is not a column on
-- MachineModel), which is why it appears here but not in the coverage meta-check's
-- column sweep.
CREATE OR REPLACE VIEW _dim_status AS
            SELECT 'title_id'                     AS dim, id, status FROM raw.catalog_title
  UNION ALL SELECT 'corporate_entity_id',         id, status FROM raw.catalog_corporateentity
  UNION ALL SELECT 'manufacturer_id',             id, status FROM raw.catalog_manufacturer
  UNION ALL SELECT 'game_format_id',              id, status FROM raw.catalog_gameformat
  UNION ALL SELECT 'technology_generation_id',    id, status FROM raw.catalog_technologygeneration
  UNION ALL SELECT 'technology_subgeneration_id', id, status FROM raw.catalog_technologysubgeneration
  UNION ALL SELECT 'display_type_id',             id, status FROM raw.catalog_displaytype
  UNION ALL SELECT 'display_subtype_id',          id, status FROM raw.catalog_displaysubtype
  UNION ALL SELECT 'system_id',                   id, status FROM raw.catalog_system
  UNION ALL SELECT 'cabinet_id',                  id, status FROM raw.catalog_cabinet
  UNION ALL SELECT 'production_status_id',        id, status FROM raw.catalog_productionstatus;

CREATE OR REPLACE VIEW _model_dim_liveness AS
  SELECT r.model_id, r.dim, r.target_id
  FROM _model_dim_ref r
  JOIN _dim_status d ON d.dim = r.dim AND d.id = r.target_id
  WHERE d.status = 'deleted';

-- _status_domain — every status value in use, across the lifecycle tables this file
-- filters on. Exists for ONE check (status_unknown), which is what licenses the
-- liveness spelling used throughout this file. See the EDITING.md note: `IS DISTINCT
-- FROM 'deleted'` (a denylist) and the ORM's `.active()` (an allowlist, `status =
-- 'active' OR status IS NULL`) are identical ONLY while the domain is exactly
-- {active, deleted, NULL}. A third EntityStatus member splits them — this file would
-- start INCLUDING the new status where the read APIs exclude it — and nothing else
-- here would notice, because both spellings stay silent. So the domain assumption is
-- asserted rather than assumed.
-- Reuses _dim_status for the eleven dim tables rather than re-listing them.
CREATE OR REPLACE VIEW _status_domain AS
            SELECT 'machine_model'    AS entity, status FROM raw.catalog_machinemodel
  UNION ALL SELECT 'location',         status FROM raw.catalog_location
  UNION ALL SELECT 'theme',            status FROM raw.catalog_theme
  UNION ALL SELECT 'gameplay_feature', status FROM raw.catalog_gameplayfeature
  UNION ALL SELECT 'reward_type',      status FROM raw.catalog_rewardtype
  UNION ALL SELECT 'tag',              status FROM raw.catalog_tag
  UNION ALL SELECT dim,                status FROM _dim_status;

-- _dim_vocab — the live slug vocabularies, one hand-written UNION because a view cannot
-- iterate table names. Both directions are
-- checked: a documented dim missing here fails unmapped_vocab_dim, one listed here that
-- the doc never defines fails stale_vocab_dim. Carries status so the live filter is the
-- consumer's, matching the rest of this file.
CREATE OR REPLACE VIEW _dim_vocab AS
            SELECT 'technologygeneration'    AS dim, slug, status FROM raw.catalog_technologygeneration
  UNION ALL SELECT 'technologysubgeneration', slug, status FROM raw.catalog_technologysubgeneration
  UNION ALL SELECT 'displaytype',             slug, status FROM raw.catalog_displaytype
  UNION ALL SELECT 'displaysubtype',          slug, status FROM raw.catalog_displaysubtype
  UNION ALL SELECT 'cabinet',                 slug, status FROM raw.catalog_cabinet
  UNION ALL SELECT 'productionstatus',        slug, status FROM raw.catalog_productionstatus
  UNION ALL SELECT 'gameformat',              slug, status FROM raw.catalog_gameformat
  UNION ALL SELECT 'rewardtype',              slug, status FROM raw.catalog_rewardtype
  UNION ALL SELECT 'tag',                     slug, status FROM raw.catalog_tag;

CREATE OR REPLACE VIEW _live_dim_vocab AS
  SELECT dim, slug FROM _dim_vocab WHERE status IS DISTINCT FROM 'deleted';

-- _catalog_checks — the catalog layer's invariants. EMPTY = healthy; any row is a
-- violation with a check_name and a diagnostic detail.
CREATE OR REPLACE VIEW _catalog_checks AS
  -- The mirrored edge set, evaluated ONCE: three checks consume it, one of them
  -- twice (a self anti-join), and it is the widest view in the foundation. DuckDB
  -- re-runs a referenced view per reference, so materializing at use is what stops the
  -- cost scaling with the number of consuming checks.
  WITH bidir AS MATERIALIZED (SELECT * FROM model_edges_bidir),
  -- ...and for every foundation view the checks below share. DuckDB re-evaluates a
  -- view once PER REFERENCE, and ~30 checks referencing a dozen views means the same
  -- decode runs dozens of times: no single check is slow, the repetition is. These CTEs
  -- SHADOW the same-named views (hence `main.` on the right-hand side), so the checks
  -- read them by their ordinary names with no edit at the call site.
  models              AS MATERIALIZED (SELECT * FROM main.models),
  manufacturers       AS MATERIALIZED (SELECT * FROM main.manufacturers),
  model_edges         AS MATERIALIZED (SELECT * FROM main.model_edges),
  model_lineage       AS MATERIALIZED (SELECT * FROM main.model_lineage),
  model_relationships AS MATERIALIZED (SELECT * FROM main.model_relationships),
  model_theme_names              AS MATERIALIZED (SELECT * FROM main.model_theme_names),
  model_themes        AS MATERIALIZED (SELECT * FROM main.model_themes),
  themes         AS MATERIALIZED (SELECT * FROM main.themes),
  model_gameplay_features AS MATERIALIZED (SELECT * FROM main.model_gameplay_features),
  gameplay_features  AS MATERIALIZED (SELECT * FROM main.gameplay_features),
  model_number_collisions AS MATERIALIZED (SELECT * FROM main.model_number_collisions),
  _ce_location_n      AS MATERIALIZED (SELECT * FROM main._ce_location_n),
  model_export_markets    AS MATERIALIZED (SELECT * FROM main.model_export_markets),
  credits             AS MATERIALIZED (SELECT * FROM main.credits),
  -- The credit population counted off the PHYSICAL tables — an INDEPENDENT restatement
  -- of what `credits` selects, so `credit_rows_dropped` below compares two derivations
  -- instead of comparing the view against itself. Keep the four liveness tests in step
  -- with the view's joins: a rule added there and not here reports as a dropped row.
  _credit_physical    AS MATERIALIZED (
    SELECT count(*) AS n
    FROM raw.catalog_credit c
    WHERE EXISTS (SELECT 1 FROM raw.catalog_person p
                  WHERE p.id = c.person_id AND p.status IS DISTINCT FROM 'deleted')
      AND EXISTS (SELECT 1 FROM raw.catalog_creditrole r
                  WHERE r.id = c.role_id   AND r.status IS DISTINCT FROM 'deleted')
      AND (EXISTS (SELECT 1 FROM raw.catalog_machinemodel m
                   WHERE m.id = c.model_id AND m.status IS DISTINCT FROM 'deleted')
        OR EXISTS (SELECT 1 FROM raw.catalog_series s
                   WHERE s.id = c.series_id AND s.status IS DISTINCT FROM 'deleted'))
  )
  -- manufacturers.operating_status recomputed from corporate_entities — a second
  -- derivation of the same rollup, off the public CE view rather than the private helper
  -- reading raw. Nothing materializes the backend's answer (it is computed per request),
  -- so this is the only thing holding the precedence and the CE population honest.
  SELECT 'mfr_status_rollup_disagrees' AS check_name,
         m.slug || ': ' || m.operating_status || ' vs ' || r.expected AS detail
  FROM manufacturers m
  LEFT JOIN (
    SELECT manufacturer_id,
           CASE WHEN bool_or(operating_status = 'ongoing') THEN 'ongoing'
                WHEN bool_and(operating_status = 'ended')  THEN 'ended'
                ELSE 'unknown' END AS expected
    FROM corporate_entities WHERE manufacturer_id IS NOT NULL GROUP BY manufacturer_id
  ) r ON r.manufacturer_id = m.id
  WHERE m.operating_status IS DISTINCT FROM COALESCE(r.expected, 'unknown')
  UNION ALL
  -- manufacturers' location rungs rolled up again from corporate_entities — the same
  -- second-derivation trick as the status check above, off the public CE view rather than
  -- the private helper reading raw. It pins the SOURCE as much as the arithmetic: these
  -- were once aggregated from `models`, which reports a maker whose models are all gone or
  -- not yet seeded as location-unknown even though its CEs carry an address. That failure
  -- produces a plausible NULL, not an error, so nothing else in the sweep can see it.
  SELECT 'mfr_location_rollup_disagrees',
         m.slug || ': ' || COALESCE(m.location_path, '(null)') || '/' || m.n_locations
                || ' vs ' || COALESCE(r.location_path, '(null)') || '/'
                || COALESCE(r.n_locations, 0)
  FROM manufacturers m
  LEFT JOIN (
    SELECT manufacturer_id,
           count(DISTINCT location_path) AS n_locations,
           CASE WHEN count(DISTINCT location_path) = 1
                THEN min(location_path) END AS location_path,
           count(DISTINCT country_slug)  AS n_countries,
           CASE WHEN count(DISTINCT country_slug) = 1
                THEN min(country_slug) END AS country_slug
    FROM corporate_entities WHERE manufacturer_id IS NOT NULL GROUP BY manufacturer_id
  ) r ON r.manufacturer_id = m.id
  WHERE m.n_locations   IS DISTINCT FROM COALESCE(r.n_locations, 0)
     OR m.location_path IS DISTINCT FROM r.location_path
     OR m.n_countries   IS DISTINCT FROM COALESCE(r.n_countries, 0)
     OR m.country_slug  IS DISTINCT FROM r.country_slug
  UNION ALL
  -- model_edges is a LOSSLESS union of the two mechanism views (no dedup, no fan-out)
  SELECT 'union_integrity' AS check_name,
         'model_edges=' || (SELECT count(*) FROM model_edges)::VARCHAR
           || ' <> lineage+relationships='
           || ((SELECT count(*) FROM model_lineage)
               + (SELECT count(*) FROM model_relationships))::VARCHAR AS detail
  WHERE (SELECT count(*) FROM model_edges)
        <> (SELECT count(*) FROM model_lineage) + (SELECT count(*) FROM model_relationships)
  UNION ALL
  -- model_lineage grain: at most one row per (model, edge_kind)
  SELECT 'lineage_grain_dup',
         'model_id=' || model_id::VARCHAR || ' edge_kind=' || edge_kind
           || ' n=' || count(*)::VARCHAR
  FROM model_lineage GROUP BY model_id, edge_kind HAVING count(*) > 1
  UNION ALL
  -- live filter: models carries no soft-deleted row. Asserted against the PHYSICAL table
  -- rather than against a status column on the view, because the view no longer carries
  -- one — and comparing the view to its source is the stronger claim anyway.
  SELECT 'models_has_deleted', 'model_id=' || m.id::VARCHAR
  FROM models m
  WHERE EXISTS (SELECT 1 FROM raw.catalog_machinemodel p
                WHERE p.id = m.id AND p.status = 'deleted')
  UNION ALL
  -- design contract: license_status IS NULL  <=>  edge_source = 'lineage_fk'
  SELECT 'edge_license_contract',
         'edge_source=' || edge_source
           || ' license_status=' || COALESCE(license_status, '<null>')
  FROM model_edges
  WHERE (edge_source = 'lineage_fk') IS DISTINCT FROM (license_status IS NULL)
  UNION ALL
  -- every lineage edge carries an FK target (guards the edges CTE's IS NOT NULL
  -- filter); variant_of/remake_of are non-null self-FKs on the rows that have them.
  SELECT 'lineage_missing_target_id',
         'model_id=' || model_id::VARCHAR || ' edge_kind=' || edge_kind
  FROM model_lineage WHERE target_id IS NULL
  UNION ALL
  -- edge_kind is DERIVED from the FK column name, so the closed three-value vocabulary is
  -- a fact about how those columns are spelled rather than about literals in the view.
  -- That is what this asserts, and it is what makes the derivation safe to rely on: rename
  -- a lineage FK and the edge kind renames with it, silently, since model_edges carries
  -- the value straight through to relationship_type. One row per unrecognized value, not
  -- per edge. `IS NULL OR NOT IN` per the house rule at the top of this view.
  SELECT 'lineage_kind_unknown', coalesce(v, 'NULL')
  FROM (SELECT DISTINCT edge_kind AS v FROM model_lineage)
  WHERE v IS NULL OR v NOT IN ('variant_of', 'remake_of', 'export_edition_of')
  UNION ALL
  -- integrity: a RESOLVED target (lineage OR typed) that isn't live — target_id set
  -- but target_slug NULL, since a live model always has a slug. The app blocks soft-
  -- deleting a model that is an ACTIVE variant_of/remake_of target or an inbound typed
  -- relationship target (soft_delete_usage_blockers; see test_api_model_delete.py —
  -- test_remake_of_referrer_blocks returns 422), so a live source pointing at a
  -- soft-deleted target is unreachable unless that protection was bypassed. Both edge
  -- kinds get the same check; the LEFT JOIN de-enrich is defensive, not an expected path.
  SELECT 'lineage_target_not_live',
         'model_id=' || model_id::VARCHAR || ' target_id=' || target_id::VARCHAR
           || ' edge_kind=' || edge_kind
  FROM model_lineage WHERE target_id IS NOT NULL AND target_slug IS NULL
  UNION ALL
  SELECT 'relationship_target_not_live',
         'model_id=' || model_id::VARCHAR || ' target_id=' || target_id::VARCHAR
           || ' type=' || relationship_type
  FROM model_relationships WHERE target_id IS NOT NULL AND target_slug IS NULL
  UNION ALL
  -- integrity: a live model attributed to a soft-deleted DIMENSION (Title, corporate
  -- entity, manufacturer, game format, or any taxonomy dim). Every one of those FKs is
  -- PROTECT and the soft-delete walker blocks deleting a row an active entity still
  -- references, with Title additionally cascading to its models — so this is
  -- unreachable unless a protection was bypassed. Same class as lineage_target_not_live,
  -- and the reason models live-filters each dim join rather than reporting a retired
  -- value as current: without both halves, the analysis layer silently shows a deleted
  -- Title's name on a live model, which no row-level invariant would notice.
  SELECT 'model_dim_not_live',
         'model_id=' || model_id::VARCHAR || ' dim=' || dim
           || ' target_id=' || target_id::VARCHAR
  FROM _model_dim_liveness
  UNION ALL
  -- coverage: a dim FK added to MachineModel that _dim_status doesn't cover would go
  -- unchecked AND unfiltered, silently. Swept from the physical column list, so the
  -- hand-maintained dim list can't fall behind the model. Only the forward direction
  -- is checked — a _dim_status entry naming nothing is harmless, and manufacturer_id
  -- legitimately has no column here (it is reached through corporate_entity).
  -- Exempt: the three lineage self-FKs (model_lineage covers them, and
  -- lineage_target_not_live is their liveness check) and the external source ids,
  -- which are not FKs at all despite the _id suffix.
  SELECT 'uncovered_model_dim', column_name
  FROM duckdb_columns()
  WHERE database_name = current_database() AND schema_name = 'raw' AND table_name = 'catalog_machinemodel'
    AND column_name LIKE '%\_id' ESCAPE '\'
    AND column_name NOT IN (SELECT DISTINCT dim FROM _dim_status)
    AND column_name NOT IN (
      'variant_of_id', 'remake_of_id', 'export_edition_of_id',
      'ipdb_id', 'opdb_id', 'pinside_id'
    )
  UNION ALL
  -- export-market targets are always live countries: the app restricts the FK to
  -- root Locations (COUNTRY_TARGET_FILTER) and blocks soft-deleting a targeted
  -- location (export_market_models usage blocker), so a set target_location_id
  -- that doesn't enrich through `countries` means one of those protections was
  -- bypassed (or the location was re-parented under another).
  SELECT 'export_market_target_not_country',
         'model_id=' || model_id::VARCHAR
           || ' target_location_id=' || target_location_id::VARCHAR
  FROM model_export_markets
  WHERE target_location_id IS NOT NULL AND target_country_slug IS NULL
  UNION ALL
  -- vocabulary: `status` is a CLOSED set — EntityStatus (core/models/mixins.py), with
  -- NULL meaning "never set", i.e. live. This is the check the whole file's liveness
  -- spelling RESTS ON. `IS DISTINCT FROM 'deleted'` here and the ORM's `.active()`
  -- (`status = 'active' OR status IS NULL`) agree only while the domain is exactly
  -- {active, deleted, NULL}: a denylist and an allowlist over the same two values.
  -- Add a third member and they diverge SILENTLY and in opposite directions — this
  -- file starts including the new status, the read APIs keep excluding it — with no
  -- error and no row-level invariant able to see it. So the precondition is asserted.
  -- When this fires, do NOT mechanically port the spelling: what the new status MEANS
  -- decides whether an analysis wants those rows (finding an odd cohort is often the
  -- whole job) or not. That is a judgment to make with the semantics in hand.
  SELECT 'status_unknown', 'entity=' || entity || ' status=' || status
  FROM (SELECT DISTINCT entity, status FROM _status_domain)
  WHERE status IS NOT NULL AND status NOT IN ('active', 'deleted')
  UNION ALL
  -- vocabulary: relationship_type and license_status are CLOSED sets, DB-enforced
  -- (catalog_modelrelationship_type_valid / _license_status_valid). These checks pin
  -- the foundation's "closed set" docs to the model — a new backend value fails here
  -- and forces the comment/README update, instead of the docs silently rotting.
  SELECT 'relationship_type_unknown',
         'model_id=' || model_id::VARCHAR || ' type=' || relationship_type
  FROM model_relationships
  WHERE relationship_type NOT IN ('conversion', 'conversion_kit', 'copy', 'retheme')
  UNION ALL
  SELECT 'license_status_unknown',
         'model_id=' || model_id::VARCHAR || ' license=' || license_status
  FROM model_relationships
  WHERE license_status NOT IN ('licensed', 'unlicensed', 'unknown')
  UNION ALL
  -- edge discriminator + type are always populated from a known shape
  SELECT 'edge_source_unknown', 'edge_source=' || edge_source
  FROM model_edges WHERE edge_source NOT IN ('lineage_fk', 'relationship')
  UNION ALL
  SELECT 'edge_relationship_type_null',
         'model_id=' || model_id::VARCHAR || ' edge_source=' || edge_source
  FROM model_edges WHERE relationship_type IS NULL
  UNION ALL
  -- model_gameplay_features grain: at most one row per (model, feature)
  SELECT 'gpf_grain_dup',
         'model_id=' || model_id::VARCHAR || ' feature_id=' || feature_id::VARCHAR
           || ' n=' || count(*)::VARCHAR
  FROM model_gameplay_features GROUP BY model_id, feature_id HAVING count(*) > 1
  UNION ALL
  -- grain guard: models.location_path / country_slug (and their target_* twins) come
  -- from _ce_location, which assumes CE -> live location is 1:1 (true across the whole
  -- catalog today). If a CE ever carries more than one live location _ce_location
  -- silently picks one and those columns turn lossy — so flag it here and add a
  -- model_locations grain view rather than let the scalar quietly drop a location.
  SELECT 'ce_multi_location',
         'corporate_entity_id=' || corporate_entity_id::VARCHAR || ' n=' || n::VARCHAR
  FROM _ce_location_n WHERE n > 1
  UNION ALL
  -- target genre propagates: a RESOLVED edge target's game_format matches the model's
  -- own (guards the new target_game_format_* facet on _model_target). Only checks
  -- resolved targets — target_slug NULL means de-enriched, already covered elsewhere.
  SELECT 'target_genre_mismatch',
         'model_id=' || model_id::VARCHAR || ' target_id=' || target_id::VARCHAR
  FROM model_edges e
  WHERE target_id IS NOT NULL AND target_slug IS NOT NULL
    AND target_game_format_slug IS DISTINCT FROM
        (SELECT game_format_slug FROM models m WHERE m.id = e.target_id)
  UNION ALL
  -- model_themes grain: at most one row per (model, theme) — mirrors gpf_grain_dup
  SELECT 'theme_grain_dup',
         'model_id=' || model_id::VARCHAR || ' theme_id=' || theme_id::VARCHAR
           || ' n=' || count(*)::VARCHAR
  FROM model_themes GROUP BY model_id, theme_id HAVING count(*) > 1
  UNION ALL
  -- the tag family, mirroring the three theme checks above. `model_tag_slugs` and `tags` are
  -- both built from model_tags, so these guard the one definition they share.
  SELECT 'tag_grain_dup',
         'model_id=' || model_id::VARCHAR || ' tag_id=' || tag_id::VARCHAR
           || ' n=' || count(*)::VARCHAR
  FROM model_tags GROUP BY model_id, tag_id HAVING count(*) > 1
  UNION ALL
  -- and the reward family, same two guards
  SELECT 'reward_grain_dup',
         'model_id=' || model_id::VARCHAR || ' reward_type_id=' || reward_type_id::VARCHAR
           || ' n=' || count(*)::VARCHAR
  FROM model_rewards GROUP BY model_id, reward_type_id HAVING count(*) > 1
  UNION ALL
  -- ── credits: the polymorphic subject, in both of the ways it can go wrong ──
  -- `credits` is the one grain view whose subject is not a machine model: it is a live
  -- MachineModel XOR a live Series, decoded into subject_type/subject_id. Two checks,
  -- because the decode and the population fail differently and neither implies the other.
  --
  -- RESOLUTION — a row whose subject names nothing live. Three failure modes in one
  -- predicate: a NULL subject_id (the XOR resolved on neither side), a subject_type
  -- outside the two-value vocabulary, and a decoded id that isn't in the view its type
  -- names. `ELSE true` makes an unrecognized type fail CLOSED rather than skip the
  -- lookup, and the NULL test has to LEAD because `NOT IN` returns NULL on a NULL
  -- left-hand side, which selects nothing — the house rule at the top of this view.
  SELECT 'credit_subject_not_live',
         'credit_id=' || credit_id::VARCHAR
           || ' ' || coalesce(subject_type, 'NULL')
           || ':' || coalesce(subject_id::VARCHAR, 'NULL')
  FROM credits
  WHERE subject_id IS NULL
     OR CASE subject_type
          WHEN 'model' THEN subject_id NOT IN (SELECT id FROM models)
          WHEN 'series'       THEN subject_id NOT IN (SELECT id FROM series)
          ELSE true
        END

  -- VOCABULARY — the subject types `credits` emits are types this layer knows. Not the
  -- guard: the resolution check above already fails closed on an unrecognized value. This
  -- is the DIAGNOSIS, one row naming the value against 7,251 naming individual credits.
  -- `IS NULL OR NOT IN` per the house rule at the top of this view.
  UNION ALL
  SELECT 'unregistered_subject_type', coalesce(v, 'NULL')
  FROM (SELECT DISTINCT subject_type AS v FROM credits)
  WHERE v IS NULL OR v NOT IN (SELECT entity_type FROM entity_registry)

  -- POPULATION — every credit whose subject, person and role are all live is HERE,
  -- compared against the independent physical count above. This is the check for the
  -- failure the view is shaped to avoid: 7 of 7251 credits hang off a Series, so a grain
  -- narrowed to the model half stays plausible under every spot check and is quietly
  -- short by a tenth of a percent. A tiny minority is the dangerous case, not the safe
  -- one. The same comparison catches the opposite defect, a join that fanned out.
  UNION ALL
  SELECT 'credit_rows_dropped',
         'physical=' || (SELECT n FROM _credit_physical)::VARCHAR
           || ' view=' || (SELECT count(*) FROM credits)::VARCHAR
  WHERE (SELECT n FROM _credit_physical)
        IS DISTINCT FROM (SELECT count(*) FROM credits)
  UNION ALL
  -- model_edges_bidir mirrors exactly the resolved edges and nothing else: one 'out'
  -- row per edge, plus one 'in' row per edge that has a model at the far end
  SELECT 'bidir_mirror_broken',
         'bidir=' || (SELECT count(*) FROM bidir)::VARCHAR
           || ' expected=' || ((SELECT count(*) FROM model_edges)
                             + (SELECT count(*) FROM model_edges WHERE target_id IS NOT NULL))::VARCHAR
  WHERE (SELECT count(*) FROM bidir)
        <> (SELECT count(*) FROM model_edges)
         + (SELECT count(*) FROM model_edges WHERE target_id IS NOT NULL)

  -- ...and the mirror is symmetric: every 'in' row has its 'out' twin, and vice versa.
  -- This is what makes the view answer "is this pair connected" from either end — the
  -- whole reason it exists — so it is worth proving rather than assuming.
  UNION ALL
  SELECT 'bidir_asymmetric',
         'model_id=' || model_id::VARCHAR || ' target_id=' || target_id::VARCHAR
           || ' direction=' || direction
  FROM bidir b
  WHERE target_id IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM bidir r
      WHERE r.model_id = b.target_id AND r.target_id = b.model_id
        AND r.relationship_type = b.relationship_type
        AND r.direction <> b.direction)

  -- the 'in' side re-enriches target_* to the OTHER end. If it were left pointing at
  -- the original target the view would quietly answer every neighbour question wrong,
  -- and no row count would notice.
  UNION ALL
  SELECT 'bidir_target_mismatch', 'model_id=' || model_id::VARCHAR
  FROM bidir b
  WHERE target_id IS NOT NULL
    AND target_slug IS DISTINCT FROM (SELECT slug FROM models m WHERE m.id = b.target_id)
  UNION ALL
  -- models.title_size and titles.n_models are the same number (both off _title_live_n;
  -- this catches one being rewired to a different definition).
  -- LEFT joined on purpose, and it asserts TWO things because `titles` holds live Titles
  -- only. Disagreement is one path drifting from the other. ABSENCE is a live model whose
  -- Title is not live — which an INNER join would drop from the comparison rather than
  -- report, and which title_size_zero_on_live cannot see either, since that reads the
  -- independently-populated model column.
  SELECT 'title_size_disagree',
         'title_id=' || m.title_id::VARCHAR || ' model=' || m.title_size::VARCHAR
           || ' titles=' || COALESCE(t.n_models::VARCHAR, '<no live Title>')
  FROM models m LEFT JOIN titles t ON t.id = m.title_id
  WHERE t.id IS NULL OR m.title_size IS DISTINCT FROM t.n_models

  -- a live model always has a live Title-mate: itself. title_size = 0 is only
  -- structurally impossible unless the _title_live_n join breaks, which is the point.
  UNION ALL
  SELECT 'title_size_zero_on_live', 'model_id=' || id::VARCHAR
  FROM models WHERE title_size IS NULL OR title_size < 1
  UNION ALL
  -- models.namesake_count is what a consumer tests before trusting a name match, so a
  -- count that drifts low is the one defect that matters: it reads as "this name is
  -- unique, go ahead" on a name that isn't. Recomputed here off `models` rather than
  -- off _namesake_live_n, which is the point — the column comes from the helper, so
  -- comparing it against the helper would prove nothing. Same LEFT-join reasoning as
  -- title_size_disagree: a name_key MISSING from the recomputation and one that
  -- disagrees are the same defect, and an INNER join would pass the former silently.
  SELECT 'namesake_count_disagree',
         'name_key=' || name_key(m.name) || ' model=' || m.namesake_count::VARCHAR
           || ' recomputed=' || COALESCE(r.n::VARCHAR, '<no row>')
  FROM models m
  LEFT JOIN (SELECT name_key(name) AS k, count(*) AS n FROM models GROUP BY name_key(name)) r
    ON r.k = name_key(m.name)
  WHERE r.k IS NULL OR m.namesake_count IS DISTINCT FROM r.n

  -- a live model is always its own namesake: it shares its name_key with itself.
  -- namesake_count = 0 is structurally impossible unless the join breaks, since a
  -- name no live model carries. Reads the model column independently of the
  -- disagreement check above, which compares it against a recomputation.
  UNION ALL
  SELECT 'namesake_count_zero_on_live', 'model_id=' || id::VARCHAR
  FROM models WHERE namesake_count IS NULL OR namesake_count < 1
  UNION ALL
  -- manufacturers.country_slug is set IFF the manufacturer's models agree on one country —
  -- the guard against a multi-country manufacturer being silently collapsed to one value
  SELECT 'manufacturer_country_collapsed',
         slug || ' n_countries=' || n_countries::VARCHAR
  FROM manufacturers
  WHERE n_countries IS NULL
     OR (n_countries = 1) IS DISTINCT FROM (country_slug IS NOT NULL)
  UNION ALL
  -- The year pair is set IFF the manufacturer has a dated non-variant model, and is a
  -- well-formed span. BOTH ends are tested for presence: `first > last` goes NULL when
  -- the last is NULL, so a first-only row would otherwise pass a comparison that never
  -- ran. The n_dated <= n_nonvariant_models <= n_models ladder pins n_dated to the year
  -- pair's variant scope.
  SELECT 'manufacturer_year_span_malformed',
         slug || ' n_dated=' || n_dated::VARCHAR
           || ' span=' || COALESCE(year_of_first_model::VARCHAR, 'NULL')
           || '..'     || COALESCE(year_of_last_model::VARCHAR, 'NULL')
  FROM manufacturers
  WHERE n_dated IS NULL OR n_models IS NULL OR n_nonvariant_models IS NULL
     OR (n_dated > 0) IS DISTINCT FROM (year_of_first_model IS NOT NULL)
     OR (n_dated > 0) IS DISTINCT FROM (year_of_last_model IS NOT NULL)
     OR year_of_first_model > year_of_last_model
     OR n_dated > n_nonvariant_models
     OR n_nonvariant_models > n_models
  UNION ALL
  -- every collision row is a real collision (n > 1) and its lists match the count
  SELECT 'collision_grain_broken',
         manufacturer_slug || ' #' || model_number || ' n=' || n::VARCHAR
  FROM model_number_collisions
  WHERE n IS NULL OR n < 2
     OR len(model_ids) IS DISTINCT FROM n
     OR len(labels)    IS DISTINCT FROM n
     OR n_titles IS NULL OR n_titles > n
  UNION ALL
  -- every term a model carries is in its vocabulary (guards the _stg_* filter being
  -- applied to the grain view and not the vocab view, or vice versa)
  SELECT DISTINCT 'theme_not_in_vocab', 'theme_id=' || theme_id::VARCHAR
  FROM model_themes WHERE theme_id NOT IN (SELECT id FROM themes)

  UNION ALL
  SELECT DISTINCT 'feature_not_in_vocab', 'feature_id=' || feature_id::VARCHAR
  FROM model_gameplay_features WHERE feature_id NOT IN (SELECT id FROM gameplay_features)
  UNION ALL
  -- vocab DAG edges point at rows in the vocab on BOTH ends — parents and children are
  -- derived from one table, so a live filter applied unevenly shows up here as a slug
  -- that parents nothing back
  SELECT 'vocab_dag_asymmetric', v || ' ' || slug || '→' || p
  FROM (
    SELECT 'themes' AS v, slug, unnest(parents) AS p FROM themes
    UNION ALL
    SELECT 'gameplay_features', slug, unnest(parents) FROM gameplay_features
  ) e
  WHERE NOT EXISTS (
    SELECT 1 FROM (
      SELECT 'themes' AS v, slug, unnest(children) AS c FROM themes
      UNION ALL
      SELECT 'gameplay_features', slug, unnest(children) FROM gameplay_features
    ) r WHERE r.v = e.v AND r.slug = e.p AND r.c = e.slug
  )
  UNION ALL
  -- ── the two dim hand-lists must agree ──
  -- _model_dim_wide names the dims a live model POINTS AT; _dim_status names the dims
  -- whose liveness is looked up. model_dim_not_live is their join, so a dim in one and
  -- not the other is silently outside the liveness guarantee — and uncovered_model_dim
  -- does not catch it: satisfying that check by adding the new FK to _dim_status ALONE
  -- leaves _model_dim_wide short, the join yields nothing for it, and the self-test
  -- stays green. Structural, so it holds whatever the catalog contains.
  SELECT 'dim_not_liveness_checked', column_name
  FROM duckdb_columns()
  WHERE database_name = current_database() AND table_name = '_model_dim_wide'
    AND column_name <> 'model_id'
    AND column_name NOT IN (SELECT DISTINCT dim FROM _dim_status)
  UNION ALL
  SELECT 'dim_status_unreferenced', d.dim
  FROM (SELECT DISTINCT dim FROM _dim_status) d
  WHERE d.dim NOT IN (
    SELECT column_name FROM duckdb_columns()
    WHERE database_name = current_database() AND table_name = '_model_dim_wide'
      AND column_name <> 'model_id')
  UNION ALL
  -- ── domain vocabulary: DomainModel.md and the catalog must agree ──
  -- domain_vocab is grain (one row per term), so a term defined TWICE under one dim
  -- fans out every join to it while all four agreement checks stay green — both rows
  -- match a live term, so nothing is undocumented and nothing is stale. Same grain
  -- guard theme_grain_dup / gpf_grain_dup / lineage_grain_dup carry.
  SELECT 'vocab_grain_dup', dim || '.' || slug
  FROM domain_vocab GROUP BY dim, slug HAVING count(*) > 1

  -- A live catalog term the doc never defines. Found `one-ball` (26 models) and
  -- `rolldown` (9) on its first run, plus a dead `export` tag the doc explicitly ruled
  -- out — drift runs in both directions, so both are checked.
  UNION ALL
  SELECT 'undocumented_vocab', v.dim || '.' || v.slug
  FROM _live_dim_vocab v
  WHERE v.dim IN (SELECT dim FROM domain_vocab)   -- a wholly-missing dim is stale_vocab_dim's
    AND NOT EXISTS (SELECT 1 FROM domain_vocab d WHERE d.dim = v.dim AND d.slug = v.slug)

  -- ...and a definition for a term that is not live: a typo, or a term retired from the
  -- catalog whose documentation nobody removed.
  UNION ALL
  SELECT 'stale_vocab_doc', d.dim || '.' || d.slug
  FROM domain_vocab d
  WHERE NOT EXISTS (SELECT 1 FROM _live_dim_vocab v WHERE v.dim = d.dim AND v.slug = d.slug)

  -- Both directions on the _dim_vocab hand-list, so it can't rot the way an unchecked
  -- enumeration does. A documented vocabulary with no entry here would be silently
  -- unverified; an entry the doc never defines means a renamed heading or a dropped
  -- section, which detaches every bullet under it.
  UNION ALL
  SELECT 'unmapped_vocab_dim', d.dim
  FROM (SELECT DISTINCT dim FROM domain_vocab) d
  WHERE d.dim NOT IN (SELECT dim FROM _dim_vocab)
  UNION ALL
  SELECT 'stale_vocab_dim', v.dim
  FROM (SELECT DISTINCT dim FROM _dim_vocab) v
  WHERE v.dim NOT IN (SELECT dim FROM domain_vocab);
