-- Foundation self-test — run this after editing catalog.sql to confirm it still
-- holds its invariants. NOT part of the foundation (no check logic lives in catalog.sql);
-- this is a separate consumer that .reads it, exactly like an analysis file, with the
-- same summary/checks contract the runner gates on.
--
-- Adding or changing a check? Read scripts/analysis/EDITING.md first — every check
-- here needs a mutation in catalog_mutations.tsv proving it fires, and check-mutations
-- enforces that in both directions.
--
--     scripts/analysis/analysis run scripts/analysis/catalog_checks.sql foundation
--
-- Prints foundation_summary (row count per view — a health readout), then fails
-- nonzero if foundation_checks returns any row. EMPTY foundation_checks = healthy.
-- Three classes:
--   structural — data-independent invariants; a row means the SQL logic broke, not
--                that the catalog changed. These make evolving the foundation safe.
--   coverage   — meta-checks that fail when a new entity, alias table or view is added
--                without the exposure the layer promises.
.read scripts/analysis/catalog.sql

-- ─── Check-only scaffolding ─────────────────────────────────────────────────
-- Private views that exist ONLY so a check has something to read. They live here
-- rather than in catalog.sql for one reason: nothing a consumer can query depends on
-- them, and they were sitting in front of the foundation's first public view.
--
-- Why they must be VIEWS at all: `fc` is attached READ_ONLY and its tables cannot be
-- shadowed, so a check written directly against `fc.` could never be mutation-tested —
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

-- _alias_tables — the physical alias/abbreviation lookup tables, derived from the
-- attached catalog rather than hand-listed. Every `AliasModel` subclass gets a
-- `catalog_<parent>alias` table and the two abbreviation through-models get
-- `catalog_<parent>abbreviation`, so the naming convention IS the registry as far as
-- SQL can see it. Feeds `unexposed_alias_table`.
CREATE OR REPLACE VIEW _alias_tables AS
  SELECT table_name FROM duckdb_tables()
  WHERE database_name = 'fc'
    AND (table_name LIKE 'catalog\_%alias' ESCAPE '\'
      OR table_name LIKE 'catalog\_%abbreviation' ESCAPE '\');

-- ─── Dimension liveness scaffolding ───────────────────────────────────────
-- These three views exist so that check can read a VIEW instead of the `fc.` tables:
-- `fc` is READ_ONLY and unshadowable, so a check written against it could never be
-- mutation-tested (same reasoning as _ce_location_n above).
--   _model_dim_ref       (live model, dim column, target id) — UNPIVOT drops the NULLs,
--                        so only dims the model actually sets appear.
--   _dim_status          (dim column, id, status) for every dim table. Keyed by the FK
--                        COLUMN name so the two lists join, and so the coverage
--                        meta-check (uncovered_model_dim) can compare this against the
--                        real column list of fc.catalog_machinemodel — a new dim FK on
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
  FROM fc.catalog_machinemodel m
  LEFT JOIN fc.catalog_corporateentity ce ON ce.id = m.corporate_entity_id
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
            SELECT 'title_id'                     AS dim, id, status FROM fc.catalog_title
  UNION ALL SELECT 'corporate_entity_id',         id, status FROM fc.catalog_corporateentity
  UNION ALL SELECT 'manufacturer_id',             id, status FROM fc.catalog_manufacturer
  UNION ALL SELECT 'game_format_id',              id, status FROM fc.catalog_gameformat
  UNION ALL SELECT 'technology_generation_id',    id, status FROM fc.catalog_technologygeneration
  UNION ALL SELECT 'technology_subgeneration_id', id, status FROM fc.catalog_technologysubgeneration
  UNION ALL SELECT 'display_type_id',             id, status FROM fc.catalog_displaytype
  UNION ALL SELECT 'display_subtype_id',          id, status FROM fc.catalog_displaysubtype
  UNION ALL SELECT 'system_id',                   id, status FROM fc.catalog_system
  UNION ALL SELECT 'cabinet_id',                  id, status FROM fc.catalog_cabinet
  UNION ALL SELECT 'production_status_id',        id, status FROM fc.catalog_productionstatus;

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
            SELECT 'machine_model'    AS entity, status FROM fc.catalog_machinemodel
  UNION ALL SELECT 'location',         status FROM fc.catalog_location
  UNION ALL SELECT 'theme',            status FROM fc.catalog_theme
  UNION ALL SELECT 'gameplay_feature', status FROM fc.catalog_gameplayfeature
  UNION ALL SELECT 'reward_type',      status FROM fc.catalog_rewardtype
  UNION ALL SELECT 'tag',              status FROM fc.catalog_tag
  UNION ALL SELECT dim,                status FROM _dim_status;

-- _dim_vocab — the live slug vocabularies, one hand-written UNION because a view cannot
-- iterate table names. Both directions are
-- checked: a documented dim missing here fails unmapped_vocab_dim, one listed here that
-- the doc never defines fails stale_vocab_dim. Carries status so the live filter is the
-- consumer's, matching the rest of this file.
CREATE OR REPLACE VIEW _dim_vocab AS
            SELECT 'technologygeneration'    AS dim, slug, status FROM fc.catalog_technologygeneration
  UNION ALL SELECT 'technologysubgeneration', slug, status FROM fc.catalog_technologysubgeneration
  UNION ALL SELECT 'displaytype',             slug, status FROM fc.catalog_displaytype
  UNION ALL SELECT 'displaysubtype',          slug, status FROM fc.catalog_displaysubtype
  UNION ALL SELECT 'cabinet',                 slug, status FROM fc.catalog_cabinet
  UNION ALL SELECT 'productionstatus',        slug, status FROM fc.catalog_productionstatus
  UNION ALL SELECT 'gameformat',              slug, status FROM fc.catalog_gameformat
  UNION ALL SELECT 'rewardtype',              slug, status FROM fc.catalog_rewardtype
  UNION ALL SELECT 'tag',                     slug, status FROM fc.catalog_tag;

CREATE OR REPLACE VIEW _live_dim_vocab AS
  SELECT dim, slug FROM _dim_vocab WHERE status IS DISTINCT FROM 'deleted';

-- ─── Entity coverage ────────────────────────────────────────────────────────
-- EVERY FIRST-CLASS CATALOG ENTITY IS EITHER EXPOSED AS A VIEW OR EXEMPTED ON THE
-- RECORD. This is the same argument `unexposed_alias_table` makes, one level up, and it
-- is here because the failure recurred on entities: two sessions in a row read a
-- missing view as a missing Django field and reported the concept as nonexistent.
-- Demand is the wrong signal for an entity for exactly the reason it is the wrong
-- signal for a vocabulary — not knowing it exists looks identical to not needing it,
-- and neither session raised a promotion request because neither knew there was
-- anything to promote.
--
-- _entity_table — the entity set, DERIVED. A first-class catalog entity is a
-- `catalog_*` table carrying both `slug` and `status`: slug because it is an addressable
-- thing with a stable handle, status because it participates in the soft-delete
-- lifecycle. That pair selects exactly the 21 concrete LinkableModels today and nothing
-- else — no alias table, no through table, no Django internal — so adding a model puts
-- it in scope automatically rather than depending on someone editing a list. Reads
-- duckdb_columns() rather than information_schema, which covers only the current
-- database and cannot see the attached `fc`.
CREATE OR REPLACE VIEW _entity_table AS
  SELECT table_name FROM duckdb_columns()
  WHERE database_name = 'fc' AND table_name LIKE 'catalog\_%' ESCAPE '\'
  GROUP BY table_name
  HAVING bool_or(column_name = 'slug') AND bool_or(column_name = 'status');

-- _entity_view — hand-input: which view exposes each entity. Only the MAPPING is
-- hand-maintained; the entity set above is derived, so the hand-list can fall behind in
-- exactly one direction and `unexposed_entity` catches that.
--
-- There are no exemptions, and the absence of an exemption column is the point. The
-- seven taxonomy dims used to be listed here as deliberately-unexposed, on the argument
-- that their slug on `models` is both the readable label and the raw-join key back to
-- fc.catalog_<dim>. That argument holds for the model row and does not extend to the
-- record: a dim carries an authored `description` that no `models` column can hold, and
-- with no view over it the foundation could not answer which vocabulary terms were still
-- undocumented. `catalog.sql` exposes all seven now, so every first-class entity names a
-- real view and nothing here is allowed to opt out.
--
-- Provenance entities are listed too even though they are outside the derived set
-- (their tables carry no `status`, so no structural signal picks them out). They get
-- the missing-view and stale-table checks; only the "is anything unlisted" direction is
-- catalog-only. If the provenance side grows a third entity, nothing here will notice.
CREATE OR REPLACE VIEW _entity_view AS
  SELECT * FROM (VALUES
    ('catalog_machinemodel',            'models'),
    ('catalog_title',                   'titles'),
    ('catalog_manufacturer',            'manufacturers'),
    ('catalog_corporateentity',         'corporate_entities'),
    ('catalog_person',                  'people'),
    ('catalog_location',                'locations'),
    ('catalog_franchise',               'franchises'),
    ('catalog_series',                  'series'),
    ('catalog_creditrole',              'credit_roles'),
    ('catalog_tag',                     'tag_vocab'),
    ('catalog_theme',                   'theme_vocab'),
    ('catalog_gameplayfeature',         'gameplay_feature_vocab'),
    ('catalog_rewardtype',              'reward_types'),
    ('catalog_gameformat',              'game_formats'),
    -- Taxonomy dims — slug-only on `models`, entity-grain here.
    ('catalog_cabinet',                 'cabinets'),
    ('catalog_displaytype',             'display_types'),
    ('catalog_displaysubtype',          'display_subtypes'),
    ('catalog_system',                  'systems'),
    ('catalog_productionstatus',        'production_statuses'),
    ('catalog_technologygeneration',    'technology_generations'),
    ('catalog_technologysubgeneration', 'technology_subgenerations'),
    -- Provenance entities: outside the derived set, listed so they get the same
    -- missing-view guarantee.
    ('actors_actor',                    'actors'),
    ('provenance_changeset',            'changesets'),
    ('provenance_source',               'ingest_sources'),
    ('provenance_ingestrun',            'ingest_runs'),
    ('citation_citationsource',         'citation_sources')
  ) AS t(entity_table, view_name);



-- ─── Fixtures — behaviour against input we control ──────────────────────────
-- Every other assertion in this file is a query over the real catalog, so its strength
-- depends on what the data happens to hold. That is how a `live()` smoke check keyed to a
-- vocabulary with no deleted rows passed while proving nothing. These tables supply the
-- cases instead of hoping for them.
-- The schema is taken from the real table with LIMIT 0, so a fixture cannot drift from
-- its source the way a hand-declared one would; only the rows are ours.
CREATE OR REPLACE TABLE _fx_lifecycle AS SELECT * FROM fc.catalog_cabinet LIMIT 0;
INSERT INTO _fx_lifecycle (id, slug, name, description, display_order, status, created_at, updated_at)
VALUES (1, 'live-null-status', 'A', '',    0, NULL,      '2020-01-01', '2020-01-01'),
       (2, 'live-active',      'B', 'has', 1, 'active',  '2020-01-01', '2020-01-01'),
       (3, 'soft-deleted',     'C', 'has', 2, 'deleted', '2020-01-01', '2020-01-01');

-- _fx_claim_value — the JSON shapes a claim value comes in, for json_scalar_text.
CREATE OR REPLACE TABLE _fx_claim_value AS
  SELECT id, value FROM fc.provenance_claim LIMIT 0;
INSERT INTO _fx_claim_value (id, value)
VALUES (1, '"500"'),            -- one asserted value, the two spellings both write paths
       (2, '500'),              --   produce
       (3, '""'),               -- absent, the blank= spelling
       (4, 'null'),             -- absent, the nullable spelling
       (5, '{"exists":true}'),  -- shapes with no scalar, which must not be serialized
       (6, '["Widebody"]');     --   into one

-- foundation_summary — row count per public view; doubles as a health dashboard.
--
-- The counting is done by UNIONing one LABELLED ROW per view row and grouping, rather
-- than the obvious `SELECT 'v', count(*) FROM v UNION ALL …`. The obvious form returns
-- WRONG NUMBERS here, silently, and this view is where it was caught: it reported
-- game_formats as 6 for a table holding 11 live rows, having taken reward_types' count
-- for it.
--
-- The cause is upstream, in DuckDB's sqlite scanner (v1.5.5, extension f79b1db). When
-- two branches of one query aggregate over DIFFERENT attached-SQLite tables and their
-- pushed-down projection and filter are textually identical — which
-- `SELECT id, slug, name, description FROM fc.catalog_<x> WHERE status IS DISTINCT FROM
-- 'deleted'` is for every simple dim view — the second table is never scanned at all and
-- inherits the first's aggregate. `sqlite_debug_show_queries` shows only one scan issued
-- for two branches. It is not specific to count: max() and sum() collapse the same way,
-- and a third branch takes the first branch's value too. Branches whose filter literals
-- differ are unaffected, which is why only one row was wrong rather than all of them.
--
-- Grouping over labelled rows sidesteps it because nothing is aggregated per-branch for
-- the optimizer to consider equivalent. One consequence to know: a view with ZERO rows
-- contributes nothing to the union and DROPS OUT of the summary instead of reporting 0.
-- It does mean absence from this readout reads as "empty", not "gone".
CREATE OR REPLACE VIEW foundation_summary AS
  SELECT view_name, count(*) AS n_rows
  FROM (
    SELECT 'models' AS view_name FROM models
    UNION ALL SELECT 'model_lineage'       FROM model_lineage
    UNION ALL SELECT 'model_relationships' FROM model_relationships
    UNION ALL SELECT 'model_edges'         FROM model_edges
    UNION ALL SELECT 'model_edges_bidir'   FROM model_edges_bidir
    UNION ALL SELECT 'manufacturers'       FROM manufacturers
    UNION ALL SELECT 'model_number_collisions' FROM model_number_collisions
    UNION ALL SELECT 'rewards'             FROM rewards
    UNION ALL SELECT 'themes'              FROM themes
    UNION ALL SELECT 'tags'                FROM tags
    UNION ALL SELECT 'model_gameplay_features' FROM model_gameplay_features
    UNION ALL SELECT 'gameplay_feature_vocab'   FROM gameplay_feature_vocab
    UNION ALL SELECT 'gameplay_feature_aliases' FROM gameplay_feature_aliases
    UNION ALL SELECT 'model_themes'        FROM model_themes
    UNION ALL SELECT 'theme_vocab'         FROM theme_vocab
    UNION ALL SELECT 'theme_aliases'       FROM theme_aliases
    UNION ALL SELECT 'model_export_markets' FROM model_export_markets
    UNION ALL SELECT 'corporate_entity_locations' FROM corporate_entity_locations
    UNION ALL SELECT 'locations'           FROM locations
    UNION ALL SELECT 'tag_vocab'           FROM tag_vocab
    UNION ALL SELECT 'franchises'          FROM franchises
    UNION ALL SELECT 'series'              FROM series
    UNION ALL SELECT 'credit_roles'        FROM credit_roles
    UNION ALL SELECT 'credits'             FROM credits
    UNION ALL SELECT 'model_credits'       FROM model_credits
    UNION ALL SELECT 'location_aliases'    FROM location_aliases
    UNION ALL SELECT 'reward_types'          FROM reward_types
    UNION ALL SELECT 'reward_type_aliases'   FROM reward_type_aliases
    UNION ALL SELECT 'manufacturer_aliases'  FROM manufacturer_aliases
    UNION ALL SELECT 'corporate_entity_aliases'  FROM corporate_entity_aliases
    UNION ALL SELECT 'person_aliases'        FROM person_aliases
    UNION ALL SELECT 'model_abbreviations'   FROM model_abbreviations
    UNION ALL SELECT 'title_abbreviations'   FROM title_abbreviations
    UNION ALL SELECT 'game_formats'        FROM game_formats
    UNION ALL SELECT 'cabinets'            FROM cabinets
    UNION ALL SELECT 'display_types'       FROM display_types
    UNION ALL SELECT 'display_subtypes'    FROM display_subtypes
    UNION ALL SELECT 'systems'             FROM systems
    UNION ALL SELECT 'production_statuses' FROM production_statuses
    UNION ALL SELECT 'technology_generations'    FROM technology_generations
    UNION ALL SELECT 'technology_subgenerations' FROM technology_subgenerations
    UNION ALL SELECT 'corporate_entities'  FROM corporate_entities
    UNION ALL SELECT 'titles'              FROM titles
    UNION ALL SELECT 'people'              FROM people
    UNION ALL SELECT 'title_size'          FROM title_size
    UNION ALL SELECT 'domain_vocab'        FROM domain_vocab
    UNION ALL SELECT 'entity_registry'     FROM entity_registry
    UNION ALL SELECT 'entity_subjects'     FROM entity_subjects
    UNION ALL SELECT 'claims'              FROM claims
    UNION ALL SELECT 'model_claims'        FROM model_claims
    UNION ALL SELECT 'claim_identity_parts' FROM claim_identity_parts
    UNION ALL SELECT 'actors'              FROM actors
    UNION ALL SELECT 'ingest_sources'      FROM ingest_sources
    UNION ALL SELECT 'ingest_runs'         FROM ingest_runs
    UNION ALL SELECT 'changesets'          FROM changesets
    UNION ALL SELECT 'citation_sources'    FROM citation_sources
    UNION ALL SELECT 'citation_roots'      FROM citation_roots
    UNION ALL SELECT 'citation_instances'  FROM citation_instances
    UNION ALL SELECT 'claim_citations'     FROM claim_citations
    UNION ALL SELECT 'citation_root_domains' FROM citation_root_domains
    UNION ALL SELECT 'shared_hosts'          FROM shared_hosts
    UNION ALL SELECT 'patch_claims'          FROM patch_claims
    UNION ALL SELECT 'patch_retractions'     FROM patch_retractions
    UNION ALL SELECT 'patch_cites'           FROM patch_cites
    UNION ALL SELECT 'patch_entries'         FROM patch_entries
    UNION ALL SELECT 'patch_entry_cites'     FROM patch_entry_cites
  )
  GROUP BY view_name
  ORDER BY view_name;


-- The provenance layer's own invariants. Defined as the PRIVATE `_provenance_checks`
-- and folded into foundation_checks below rather than left as a public `*_checks` view,
-- so there is one gate and one mutation-harness entry point — the runner's sweep would
-- otherwise discover it separately and report every provenance failure twice.
--
-- Read HERE, immediately above foundation_checks, not up beside `.read catalog.sql`:
-- check-mutations scans from the first checks view to end-of-file for declared check
-- names, so anything read in earlier would put foundation_summary's view-name literals
-- inside that range and invent check names that don't exist.
.read scripts/analysis/provenance_checks.sql

-- The patch layer's own invariants, `_data_patch_checks`, on the same terms and read
-- inside the same range. Its own file rather than a tail on provenance_checks.sql
-- because it binds `_patch_acts` from data_patches.sql, which sits ABOVE provenance.sql
-- — see the note at the top of it.
.read scripts/analysis/data_patches_checks.sql

-- foundation_checks — invariants. EMPTY = healthy; any row is a violation with a
-- check_name and a diagnostic detail.
--
-- HOUSE RULE, and the source of more bugs here than anything else: a check compares
-- with `IS DISTINCT FROM`, never `<>`, and tests every operand for NULL before using
-- an ordering operator. In three-valued logic `a <> b` is NULL when either side is
-- NULL, and a NULL predicate does not select the row — so the check silently passes on
-- exactly the corrupted data it exists to catch. A no-op check and a passing check both
-- return zero rows, which is what makes this class invisible: the self-test stays green
-- while the guarantee is gone. Every instance found so far was this.
CREATE OR REPLACE VIEW foundation_checks AS
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
  title_size          AS MATERIALIZED (SELECT * FROM main.title_size),
  manufacturers       AS MATERIALIZED (SELECT * FROM main.manufacturers),
  model_edges         AS MATERIALIZED (SELECT * FROM main.model_edges),
  model_lineage       AS MATERIALIZED (SELECT * FROM main.model_lineage),
  model_relationships AS MATERIALIZED (SELECT * FROM main.model_relationships),
  themes              AS MATERIALIZED (SELECT * FROM main.themes),
  model_themes        AS MATERIALIZED (SELECT * FROM main.model_themes),
  theme_vocab         AS MATERIALIZED (SELECT * FROM main.theme_vocab),
  model_gameplay_features AS MATERIALIZED (SELECT * FROM main.model_gameplay_features),
  gameplay_feature_vocab  AS MATERIALIZED (SELECT * FROM main.gameplay_feature_vocab),
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
    FROM fc.catalog_credit c
    WHERE EXISTS (SELECT 1 FROM fc.catalog_person p
                  WHERE p.id = c.person_id AND p.status IS DISTINCT FROM 'deleted')
      AND EXISTS (SELECT 1 FROM fc.catalog_creditrole r
                  WHERE r.id = c.role_id   AND r.status IS DISTINCT FROM 'deleted')
      AND (EXISTS (SELECT 1 FROM fc.catalog_machinemodel m
                   WHERE m.id = c.model_id AND m.status IS DISTINCT FROM 'deleted')
        OR EXISTS (SELECT 1 FROM fc.catalog_series s
                   WHERE s.id = c.series_id AND s.status IS DISTINCT FROM 'deleted'))
  )

  -- ── structural: data-independent; a row means the SQL logic broke ──

  -- Macro smoke tests. The generated column sweep walks VIEWS, so a macro that broke
  -- would go unnoticed until an analysis silently stopped matching. These pin the behaviour
  -- each one is relied on for, including the case that makes name_strip_paren a
  -- judgment rather than a mechanic (KISS).
  SELECT 'macro_name_norm' AS check_name,
         name_norm('  Capt. Card & Co!! ') || ' / ' || name_norm('München') AS detail
  WHERE name_norm('  Capt. Card & Co!! ') IS DISTINCT FROM 'capt card co'
     -- Latin diacritics fold rather than becoming word breaks. An ASCII-only class
     -- gave 'pok mon' / 'competici n penalty' for real catalog rows, and 'tomik' for
     -- a leading accent — tokens that match nothing and split one name into two.
     OR name_norm('Pokémon')             IS DISTINCT FROM 'pokemon'
     OR name_norm('Competición Penalty') IS DISTINCT FROM 'competicion penalty'
     OR name_norm('Ätomik')              IS DISTINCT FROM 'atomik'
     -- and a non-Latin name must not collapse to '', where it would match every other
     OR name_norm('ピンボール') = ''
  UNION ALL
  SELECT 'macro_name_strip_paren', name_strip_paren('On Beam (Italy)')
  WHERE name_strip_paren('On Beam (Italy)') IS DISTINCT FROM 'On Beam'
     -- only ONE parenthetical, and only a trailing one
     OR name_strip_paren('KISS (Limited Edition) (Italy)') IS DISTINCT FROM 'KISS (Limited Edition)'
     OR name_strip_paren('(Not) A Suffix') IS DISTINCT FROM '(Not) A Suffix'
  UNION ALL
  SELECT 'macro_name_key', name_key('On Beam (Italy)')
  WHERE name_key('On Beam (Italy)') IS DISTINCT FROM 'on beam'
     OR name_key('KISS (Limited Edition)') IS DISTINCT FROM 'kiss'   -- the documented collapse
     OR name_key(NULL) IS DISTINCT FROM ''
  UNION ALL

  SELECT 'macro_presumed_producing',
         concat_ws('/', presumed_producing('ongoing', 1932),
                        presumed_producing('unknown', year(current_date) - 5),
                        presumed_producing('unknown', year(current_date) - 6),
                        presumed_producing('unknown', NULL),
                        presumed_producing('ended', year(current_date)))
  WHERE presumed_producing('ongoing', 1932)                  IS DISTINCT FROM true
     OR presumed_producing('unknown', year(current_date) - 5) IS DISTINCT FROM true
     OR presumed_producing('unknown', year(current_date) - 6) IS DISTINCT FROM false  -- exclusive
     -- an undated entity is a plain false, not the NULL that silently drops it from
     -- both `WHERE presumed_producing` and `WHERE NOT presumed_producing`
     OR presumed_producing('unknown', NULL)                   IS DISTINCT FROM false
     -- editorial 'ended' beats recency, which is the whole point of the field
     OR presumed_producing('ended', year(current_date))       IS DISTINCT FROM false
  UNION ALL
  -- ...and its window against the frontend constant it exists to mirror. Nothing else
  -- couples them, and a change to either side is silent in the other.
  SELECT 'presumed_producing_window_drift',
         'macro=' || w.macro_years::VARCHAR || ' utils.ts=' || COALESCE(w.ts_years::VARCHAR, 'unparsed')
  FROM (SELECT
          (SELECT max(k) + 1 FROM range(0, 100) t(k)
            WHERE presumed_producing('unknown', year(current_date) - k)) AS macro_years,
          (SELECT TRY_CAST(regexp_extract(content, 'UNKNOWN_RECENCY_YEARS = ([0-9]+)', 1) AS INTEGER)
             FROM read_text('frontend/src/lib/utils.ts'))                AS ts_years
       ) w
  WHERE w.macro_years IS DISTINCT FROM w.ts_years
  UNION ALL

  -- manufacturers.operating_status recomputed from corporate_entities — a second
  -- derivation of the same rollup, off the public CE view rather than the private helper
  -- reading fc. Nothing materializes the backend's answer (it is computed per request),
  -- so this is the only thing holding the precedence and the CE population honest.
  SELECT 'mfr_status_rollup_disagrees',
         m.slug || ': ' || m.operating_status || ' vs ' || r.expected
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
  -- the private helper reading fc. It pins the SOURCE as much as the arithmetic: these
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

  -- The citation host-recognition macros (provenance.sql), pinned against
  -- apps/citation/hosts.py — these mirror backend code, so drift is the whole risk.
  SELECT 'macro_host_norm', host_norm('  WWW.WWW.IPDB.org.  ')
  WHERE host_norm('  WWW.WWW.IPDB.org.  ') IS DISTINCT FROM 'ipdb.org'  -- all www labels, FQDN dot, case
     -- a whole label only: wwworld keeps its first label
     OR host_norm('wwworld.example.com') IS DISTINCT FROM 'wwworld.example.com'
  UNION ALL
  SELECT 'macro_url_host', url_host('http://TWIP.Kineticist.com:8080/a?q=1#f')
  WHERE url_host('http://TWIP.Kineticist.com:8080/a?q=1#f')
        IS DISTINCT FROM 'twip.kineticist.com'   -- port, path, query, fragment, case
     -- the userinfo branch, exercised with an EMPTY userinfo. A populated one is the
     -- more obvious test and is deliberately avoided: a name and password ahead of the
     -- host is the literal shape of a basic-auth credential, so it trips secret scanners
     -- on every commit. An empty userinfo matches the same `[^/@]*@` group.
     OR url_host('http://@ipdb.org/x') IS DISTINCT FROM 'ipdb.org'
     OR url_host('//opdb.org/games/G0l2e') IS DISTINCT FROM 'opdb.org'  -- scheme-relative
     -- no authority means no host: a bare host+path is NOT parsed as a host, since
     -- guessing would attribute 'ipdb.org/x' and 'notes about ipdb.org' alike
     OR url_host('ipdb.org/x') IS DISTINCT FROM ''
     OR url_host(NULL)         IS DISTINCT FROM ''
  UNION ALL

  -- The patch ordinal parse (data_patches.sql), pinned in all three directions. Kept in
  -- this block with the others rather than in data_patches_checks.sql: the macros come
  -- from three different files and gathering their smoke tests in one place is what made
  -- a missing one noticeable at all.
  SELECT 'macro_patch_number_of',
         coalesce(patch_number_of('0189-print-citations')::VARCHAR, 'NULL')
  WHERE patch_number_of('0189-print-citations') IS DISTINCT FROM 189   -- leading zeros
     -- an id carrying no ordinal is NULL, not a crash. TRY_CAST is the whole reason:
     -- plain CAST raises on the '' that a failed regexp_extract returns, which takes
     -- down every analysis reading this layer over one malformed id.
     OR patch_number_of('draft-slug') IS NOT NULL
     OR patch_number_of(NULL)         IS NOT NULL
     -- and the ordinal is not truncated to flippatch's CURRENT four-digit width. A
     -- `{4}` parse reads 12345-slug as 1234 — no error, no NULL, just a wrong number
     -- feeding an operator's `WHERE patch_number > N` cutoff.
     OR patch_number_of('12345-slug') IS DISTINCT FROM 12345
  UNION ALL
  -- Data-dependent, unlike the macro checks above, because the rule only has teeth when
  -- one registered host nests inside another — and the nesting is exactly what a
  -- hand-rolled equality or LIKE gets wrong. Anchored on the pair that exists today
  -- (This Week in Pinball under Kineticist) via slug-free ids looked up by host, so it
  -- follows a re-seed. Both directions plus the label-boundary negative.
  SELECT 'macro_citation_root_for_host',
         coalesce(citation_root_for_host('twip.kineticist.com')::VARCHAR, 'NULL')
  WHERE (SELECT count(*) FROM citation_root_domains WHERE host = 'twip.kineticist.com') = 1
    AND (
         -- most-specific wins: the subdomain resolves to ITS work, not the parent's
         citation_root_for_host('twip.kineticist.com') IS DISTINCT FROM
           (SELECT root_citation_source_id FROM citation_root_domains WHERE host = 'twip.kineticist.com')
         -- ...and the parent still resolves to itself
      OR citation_root_for_host('kineticist.com') IS DISTINCT FROM
           (SELECT root_citation_source_id FROM citation_root_domains WHERE host = 'kineticist.com')
         -- an unregistered subdomain falls back to the registrable root
      OR citation_root_for_host('deep.sub.kineticist.com') IS DISTINCT FROM
           (SELECT root_citation_source_id FROM citation_root_domains WHERE host = 'kineticist.com')
         -- the boundary is a LABEL: a lookalike suffix must not match at all
      OR citation_root_for_host('evil-kineticist.com') IS NOT NULL
    )
  UNION ALL
  SELECT 'macro_url_path', url_path('http://X.com:8080/Case/PATH%20x?q=1#f')
  WHERE url_path('http://X.com:8080/Case/PATH%20x?q=1#f')
        IS DISTINCT FROM '/Case/PATH%20x'  -- port/query/fragment dropped; case and
                                           -- percent-encoding preserved (paths are
                                           -- case-sensitive, unlike url_host)
     -- no authority means no path, mirroring url_host's refusal to guess
     OR url_path('ipdb.org/x') IS DISTINCT FROM ''
     OR url_path(NULL)         IS DISTINCT FROM ''
  UNION ALL
  -- The shared candidacy rule both citation_root_for_* macros filter through —
  -- data-independent on purpose: the misattribution cases (a bare row on a shared CDN
  -- host, another tenant's path) are exactly the rows a healthy catalog never holds,
  -- so only literal-argument assertions can prove the rule at all.
  SELECT 'macro_citation_domain_eligible', 'eligibility drifted from apps/citation'
  WHERE NOT citation_domain_eligible('s4.american-pinball.com', '/x', 'american-pinball.com', '')  -- bare row, suffix host
     OR citation_domain_eligible('evil-american-pinball.com', '/x', 'american-pinball.com', '')    -- label boundary
     OR NOT citation_domain_eligible('img1.wsimg.com', '/blobby/go/T/downloads/a.pdf',
                                     'img1.wsimg.com', '/blobby/go/T')                             -- tenant prefix match
     OR citation_domain_eligible('img1.wsimg.com', '/blobby/go/T-evil/a.pdf',
                                 'img1.wsimg.com', '/blobby/go/T')                                 -- path SEGMENT boundary
     OR citation_domain_eligible('img1.wsimg.com', '/blobby/go/OTHER/a.pdf',
                                 'img1.wsimg.com', '/blobby/go/T')                                 -- another tenant
     OR citation_domain_eligible('img1.wsimg.com', '/BLOBBY/go/t/a.pdf',
                                 'img1.wsimg.com', '/blobby/go/T')                                 -- paths are case-sensitive
     OR citation_domain_eligible('img1.wsimg.com', '/blobby/go/T/../OTHER/a.pdf',
                                 'img1.wsimg.com', '/blobby/go/T')                                 -- traversal refused
     OR citation_domain_eligible('img1.wsimg.com', '/blobby/go/T/%2e%2e/OTHER/a.pdf',
                                 'img1.wsimg.com', '/blobby/go/T')                                 -- ...encoded too
     OR citation_domain_eligible('img1.wsimg.com', '/anything', 'wsimg.com', '')                   -- bare ancestor row never
                                                                                                   -- absorbs a shared-CDN URL
     OR citation_domain_eligible('wsimg.com', '', 'wsimg.com', '')                                 -- nor the bare host itself
     OR NOT citation_domain_eligible('shopify.com', '/blog', 'shopify.com', '')                    -- leaf declaration leaves
                                                                                                   -- the parent site alone
     -- every mirrored shared-host entry gets one positive assertion, so dropping or
     -- mistyping an entry in the SQL mirror fails the self-test loudly (wsimg.com is
     -- exercised throughout the cases above)
     OR NOT citation_domain_eligible('cdn.shopify.com', '/s/files/1/0001/doc.pdf',
                                     'cdn.shopify.com', '/s/files/1/0001')
     OR NOT citation_domain_eligible('storage.googleapis.com', '/maker-bucket/docs/x.pdf',
                                     'storage.googleapis.com', '/maker-bucket')
     OR citation_domain_eligible('cardonapinball.com', '/files/a.pdf',
                                 'cardonapinball.com', '/files')                                   -- a prefixed row on an
                                                                                                   -- ordinary host is a bypass
                                                                                                   -- artifact, never a match
  UNION ALL
  -- Data-dependent like macro_citation_root_for_host, anchored on the same seeded pair.
  SELECT 'macro_citation_root_for_url',
         coalesce(citation_root_for_url('https://twip.kineticist.com/article')::VARCHAR, 'NULL')
  WHERE (SELECT count(*) FROM citation_root_domains WHERE host = 'twip.kineticist.com') = 1
    AND (
         -- a URL resolves like its host, most-specific registered host winning
         citation_root_for_url('https://twip.kineticist.com/article') IS DISTINCT FROM
           (SELECT root_citation_source_id FROM citation_root_domains WHERE host = 'twip.kineticist.com')
      OR citation_root_for_url('https://www.kineticist.com/x') IS DISTINCT FROM
           (SELECT root_citation_source_id FROM citation_root_domains WHERE host = 'kineticist.com')
         -- the label-boundary negative holds through the URL form
      OR citation_root_for_url('https://evil-kineticist.com/x') IS NOT NULL
         -- an unregistered shared-CDN tenant is NULL, never a host-level guess
      OR citation_root_for_url('https://img1.wsimg.com/blobby/go/unregistered/x.pdf') IS NOT NULL
    )
  UNION ALL
  -- Longest-prefix precedence, pinned deterministically: the baseline catalog holds no
  -- nested prefixed rows, so this check supplies its own — a CTE named after the view
  -- shadows it inside the macro expansion (the provenance_checks `claims` shadowing
  -- trick, reaching through the macro), making the ordering testable with no data.
  SELECT 'macro_citation_root_for_url_prefix_order', probe.got
  FROM (
    WITH citation_root_domains AS (
      SELECT * FROM (VALUES
        (1001, 'Tenant',           NULL::VARCHAR, '', 'img1.wsimg.com', '/blobby/go/T'),
        (1002, 'Tenant downloads', NULL::VARCHAR, '', 'img1.wsimg.com', '/blobby/go/T/downloads')
      ) v(root_citation_source_id, root_citation_source_name, root_citation_source_slug,
          root_identifier_key, host, path_prefix)
    )
    SELECT
      coalesce(citation_root_for_url('https://img1.wsimg.com/blobby/go/T/downloads/x.pdf')::VARCHAR,
               'NULL') AS got,
      -- both rows are eligible for a URL under the deeper prefix; the deeper must win
      citation_root_for_url('https://img1.wsimg.com/blobby/go/T/downloads/x.pdf') AS deep,
      -- ...while a URL under only the shallow prefix still resolves to it
      citation_root_for_url('https://img1.wsimg.com/blobby/go/T/other.pdf')       AS shallow
  ) probe
  WHERE probe.deep    IS DISTINCT FROM 1002
     OR probe.shallow IS DISTINCT FROM 1001
  UNION ALL

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

  -- ── live() and blanks_null(), proven against fixture input ──
  -- Data-independent: these assert the three halves of the contract on rows that exist
  -- because we put them there, so none of it rides on the catalog happening to contain a
  -- soft-deleted cabinet or a blank description.
  UNION ALL
  SELECT 'fixture_live_liveness',
         'expected ids 1,2 — got ' || coalesce((SELECT string_agg(id::VARCHAR, ',' ORDER BY id)
                                                FROM live('_fx_lifecycle')), '<none>')
  WHERE (SELECT string_agg(id::VARCHAR, ',' ORDER BY id) FROM live('_fx_lifecycle'))
        IS DISTINCT FROM '1,2'

  UNION ALL
  SELECT 'fixture_live_excludes_bookkeeping', column_name
  FROM (DESCRIBE SELECT * FROM live('_fx_lifecycle'))
  WHERE column_name IN ('status', 'created_at', 'updated_at')

  -- blanks_null folds '' to NULL and leaves a real value alone. Asserted through live(),
  -- which composes it, so the composition is covered too.
  UNION ALL
  SELECT 'fixture_blanks_null',
         'id1=' || coalesce((SELECT description FROM live('_fx_lifecycle') WHERE id = 1), '<NULL>')
      || ' id2=' || coalesce((SELECT description FROM live('_fx_lifecycle') WHERE id = 2), '<NULL>')
  WHERE (SELECT description FROM live('_fx_lifecycle') WHERE id = 1) IS NOT NULL
     OR (SELECT description FROM live('_fx_lifecycle') WHERE id = 2) IS DISTINCT FROM 'has'

  -- One expected-vs-actual string, so a regression names what it produced.
  UNION ALL
  SELECT 'fixture_json_scalar_text',
         (SELECT string_agg(coalesce(json_scalar_text(value), '<NULL>'), ',' ORDER BY id)
          FROM _fx_claim_value)
  WHERE (SELECT string_agg(coalesce(json_scalar_text(value), '<NULL>'), ',' ORDER BY id)
         FROM _fx_claim_value)
        IS DISTINCT FROM '500,500,<NULL>,<NULL>,<NULL>,<NULL>'

  -- ── the OUTCOME, asserted across every entity view at once ──
  -- The fixtures prove the macro; these prove it was actually applied. A view that
  -- hand-rolls its own projection and forgets is caught here regardless of how it is
  -- written, which is the failure that got past us: `macro_live` was deleted as redundant
  -- with `anchor_dark`, and `anchor_dark` was deleted in the same breath.
  UNION ALL
  SELECT 'entity_view_leaks_bookkeeping', c.table_name || '.' || c.column_name
  FROM duckdb_columns() c
  JOIN _entity_view e ON e.view_name = c.table_name
  WHERE c.database_name = 'memory'
    AND c.column_name IN ('status', 'created_at', 'updated_at')
    -- provenance entities have no lifecycle and carry these legitimately
    -- Lifecycle entities only. Not "the source has a status column": provenance_ingestrun
    -- has one and it is the RUN's status, nothing to do with soft-delete. _entity_table is
    -- the derived set, so provenance entities fall out structurally.
    AND e.entity_table IN (SELECT table_name FROM _entity_table)

  -- Every entity view over a LIFECYCLE table reaches its rows through live(), directly or
  -- through a _live_* leaf that does. Keyed on the source table carrying `status`, so
  -- provenance entities fall out structurally rather than by exemption.
  UNION ALL
  SELECT 'entity_view_not_live_filtered', e.view_name
  FROM _entity_view e
  JOIN duckdb_views() v ON v.view_name = e.view_name AND v.database_name = 'memory'
  WHERE e.entity_table IN (SELECT table_name FROM _entity_table)
    -- A TEXT match, with the limit that implies: it catches a view that forgot to filter,
    -- not one that mentions live() or a _live_* leaf without reading through it. Naming the
    -- leaves instead of wildcarding does not change that — a bypass smuggling the token
    -- through a no-op subquery passes either way. An exact check is not available:
    -- query_table() takes literals only, so "compare each view against live() of its
    -- source" cannot be written once over the entity set.
    AND v.sql NOT LIKE '%live(%'
    AND v.sql NOT LIKE '%_live_%'

  -- live filter: models carries no soft-deleted row. Asserted against the PHYSICAL table
  -- rather than against a status column on the view, because the view no longer carries
  -- one — and comparing the view to its source is the stronger claim anyway.
  UNION ALL
  SELECT 'models_has_deleted', 'model_id=' || m.id::VARCHAR
  FROM models m
  WHERE EXISTS (SELECT 1 FROM fc.catalog_machinemodel p
                WHERE p.id = m.id AND p.status = 'deleted')

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

  -- integrity: a live model attributed to a soft-deleted DIMENSION (Title, corporate
  -- entity, manufacturer, game format, or any taxonomy dim). Every one of those FKs is
  -- PROTECT and the soft-delete walker blocks deleting a row an active entity still
  -- references, with Title additionally cascading to its models — so this is
  -- unreachable unless a protection was bypassed. Same class as lineage_target_not_live,
  -- and the reason models live-filters each dim join rather than reporting a retired
  -- value as current: without both halves, the analysis layer silently shows a deleted
  -- Title's name on a live model, which no row-level invariant would notice.
  UNION ALL
  SELECT 'model_dim_not_live',
         'model_id=' || model_id::VARCHAR || ' dim=' || dim
           || ' target_id=' || target_id::VARCHAR
  FROM _model_dim_liveness

  -- coverage: a dim FK added to MachineModel that _dim_status doesn't cover would go
  -- unchecked AND unfiltered, silently. Swept from the physical column list, so the
  -- hand-maintained dim list can't fall behind the model. Only the forward direction
  -- is checked — a _dim_status entry naming nothing is harmless, and manufacturer_id
  -- legitimately has no column here (it is reached through corporate_entity).
  -- Exempt: the three lineage self-FKs (model_lineage covers them, and
  -- lineage_target_not_live is their liveness check) and the external source ids,
  -- which are not FKs at all despite the _id suffix.
  UNION ALL
  SELECT 'uncovered_model_dim', column_name
  FROM duckdb_columns()
  WHERE database_name = 'fc' AND table_name = 'catalog_machinemodel'
    AND column_name LIKE '%\_id' ESCAPE '\'
    AND column_name NOT IN (SELECT DISTINCT dim FROM _dim_status)
    AND column_name NOT IN (
      'variant_of_id', 'remake_of_id', 'export_edition_of_id',
      'ipdb_id', 'opdb_id', 'pinside_id'
    )

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
  UNION ALL
  SELECT 'status_unknown', 'entity=' || entity || ' status=' || status
  FROM (SELECT DISTINCT entity, status FROM _status_domain)
  WHERE status IS NOT NULL AND status NOT IN ('active', 'deleted')

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
  FROM _ce_location_n WHERE n > 1

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

  -- model_themes grain: at most one row per (model, theme) — mirrors gpf_grain_dup
  UNION ALL
  SELECT 'theme_grain_dup',
         'model_id=' || model_id::VARCHAR || ' theme_id=' || theme_id::VARCHAR
           || ' n=' || count(*)::VARCHAR
  FROM model_themes GROUP BY model_id, theme_id HAVING count(*) > 1

  -- model_themes subjects are live (mirrors gpf_subject_not_live)
  UNION ALL
  SELECT 'theme_subject_not_live', 'model_id=' || model_id::VARCHAR
  FROM model_themes WHERE model_id NOT IN (SELECT id FROM models)

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
  UNION ALL
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

  -- the grain view and the display list describe the SAME memberships — compared by
  -- VALUE, not by count. They're built by different paths (model_themes filters live
  -- subjects with an EXISTS and carries slugs; `themes` groups names off the raw join),
  -- so reconstructing one from the other is a real cross-view check: it catches a live
  -- filter added to one and not the other, AND a same-size mis-join that lands the
  -- right number of wrong themes on a model. Cardinality alone would miss the second,
  -- which is the one that silently corrupts every name a theme cleanup reads.
  -- The key set is the UNION of both sides, not `models`: driven from `models` this sees
  -- only a membership the GRAIN view lost, because a model the DISPLAY LIST alone carries
  -- is off the key set entirely.
  UNION ALL
  SELECT 'theme_views_disagree',
         'model_id=' || model_id::VARCHAR || ' grain=' || COALESCE(grain::VARCHAR, '<none>')
           || ' list=' || COALESCE(list::VARCHAR, '<none>')
  FROM (
    SELECT k.model_id,
           (SELECT list_sort(list(tv.name))
              FROM model_themes mt JOIN theme_vocab tv ON tv.id = mt.theme_id
             WHERE mt.model_id = k.model_id) AS grain,
           th.themes                   AS list
    FROM (SELECT id AS model_id FROM models UNION SELECT model_id FROM themes) k
    LEFT JOIN themes th ON th.model_id = k.model_id
  ) WHERE grain IS DISTINCT FROM list

  -- model_edges_bidir mirrors exactly the resolved edges and nothing else: one 'out'
  -- row per edge, plus one 'in' row per edge that has a model at the far end
  UNION ALL
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

  -- models.title_size and the title_size view are the same number (both off
  -- _title_live_n; this catches one being rewired to a different definition).
  -- LEFT joined on purpose: an INNER join only compares Titles present in BOTH, so a
  -- title_size row that went MISSING would drop its models out of the comparison
  -- entirely and pass — and title_size_zero_on_live wouldn't see it either, since that
  -- reads the independently-populated model column. Absence and disagreement are the
  -- same defect here, so both are flagged.
  UNION ALL
  SELECT 'title_size_disagree',
         'title_id=' || m.title_id::VARCHAR || ' model=' || m.title_size::VARCHAR
           || ' view=' || COALESCE(t.n::VARCHAR, '<no row>')
  FROM models m LEFT JOIN title_size t ON t.title_id = m.title_id
  WHERE t.title_id IS NULL OR m.title_size IS DISTINCT FROM t.n

  -- a live model always has a live Title-mate: itself. title_size = 0 is only
  -- structurally impossible unless the _title_live_n join breaks, which is the point.
  UNION ALL
  SELECT 'title_size_zero_on_live', 'model_id=' || id::VARCHAR
  FROM models WHERE title_size IS NULL OR title_size < 1

  -- models.namesake_count is what a consumer tests before trusting a name match, so a
  -- count that drifts low is the one defect that matters: it reads as "this name is
  -- unique, go ahead" on a name that isn't. Recomputed here off `models` rather than
  -- off _namesake_live_n, which is the point — the column comes from the helper, so
  -- comparing it against the helper would prove nothing. Same LEFT-join reasoning as
  -- title_size_disagree: a name_key MISSING from the recomputation and one that
  -- disagrees are the same defect, and an INNER join would pass the former silently.
  UNION ALL
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

  -- manufacturers.country_slug is set IFF the manufacturer's models agree on one country —
  -- the guard against a multi-country manufacturer being silently collapsed to one value
  UNION ALL
  SELECT 'manufacturer_country_collapsed',
         slug || ' n_countries=' || n_countries::VARCHAR
  FROM manufacturers
  WHERE n_countries IS NULL
     OR (n_countries = 1) IS DISTINCT FROM (country_slug IS NOT NULL)

  -- The year pair is set IFF the manufacturer has a dated non-variant model, and is a
  -- well-formed span. BOTH ends are tested for presence: `first > last` goes NULL when
  -- the last is NULL, so a first-only row would otherwise pass a comparison that never
  -- ran. The n_dated <= n_nonvariant_models <= n_models ladder pins n_dated to the year
  -- pair's variant scope.
  UNION ALL
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

  -- every collision row is a real collision (n > 1) and its lists match the count
  UNION ALL
  SELECT 'collision_grain_broken',
         manufacturer_slug || ' #' || model_number || ' n=' || n::VARCHAR
  FROM model_number_collisions
  WHERE n IS NULL OR n < 2
     OR len(model_ids) IS DISTINCT FROM n
     OR len(labels)    IS DISTINCT FROM n
     OR n_titles IS NULL OR n_titles > n

  -- every term a model carries is in its vocabulary (guards the _live_* filter being
  -- applied to the grain view and not the vocab view, or vice versa)
  UNION ALL
  SELECT DISTINCT 'theme_not_in_vocab', 'theme_id=' || theme_id::VARCHAR
  FROM model_themes WHERE theme_id NOT IN (SELECT id FROM theme_vocab)

  UNION ALL
  SELECT DISTINCT 'feature_not_in_vocab', 'feature_id=' || feature_id::VARCHAR
  FROM model_gameplay_features WHERE feature_id NOT IN (SELECT id FROM gameplay_feature_vocab)

  -- vocab DAG edges point at rows in the vocab on BOTH ends — parents and children are
  -- derived from one table, so a live filter applied unevenly shows up here as a slug
  -- that parents nothing back
  UNION ALL
  SELECT 'vocab_dag_asymmetric', v || ' ' || slug || '→' || p
  FROM (
    SELECT 'theme_vocab' AS v, slug, unnest(parents) AS p FROM theme_vocab
    UNION ALL
    SELECT 'gameplay_feature_vocab', slug, unnest(parents) FROM gameplay_feature_vocab
  ) e
  WHERE NOT EXISTS (
    SELECT 1 FROM (
      SELECT 'theme_vocab' AS v, slug, unnest(children) AS c FROM theme_vocab
      UNION ALL
      SELECT 'gameplay_feature_vocab', slug, unnest(children) FROM gameplay_feature_vocab
    ) r WHERE r.v = e.v AND r.slug = e.p AND r.c = e.slug
  )

  -- A public foundation view missing from `foundation_summary` — the same coverage
  -- claim the entity and alias coverage checks make, for the other hand-list. It
  -- drifted the first time it could: a whole layer's five views went unsummarized, so
  -- the health readout silently stopped describing the foundation while the self-test
  -- stayed green. The two *_context watermarks are excluded on purpose — their NULLs
  -- are legitimate (no successful patch yet, an empty provenance table on a fresh DB).
  --
  -- Matched against the summary's own SQL rather than by selecting from it, the way
  -- `unexposed_alias_table` matches view text. Reading `SELECT view_name FROM
  -- foundation_summary` would be the direct statement and costs ~1.7s — it evaluates
  -- every count in the summary — on a checks run that is ~8s. This claim is structural
  -- and shouldn't be paying for row counts to make it.
  --
  -- BOTH the quoted label and the FROM clause, because neither is exact alone. The
  -- label is quote-delimited so a short view name cannot match inside a longer one; the FROM
  -- test is a bare prefix so `FROM model_edges` does match inside `FROM
  -- model_edges_bidir`. ANDing them takes the label's exactness and adds the assertion
  -- that the view is actually COUNTED rather than merely named.
  UNION ALL
  SELECT 'unsummarized_view', v.table_name
  FROM information_schema.tables v
  WHERE v.table_schema = 'main' AND v.table_type = 'VIEW'
    AND v.table_name NOT LIKE '\_%' ESCAPE '\'
    AND v.table_name NOT IN ('foundation_summary', 'foundation_checks',
                             'analysis_context', 'provenance_context')
    AND NOT EXISTS (
      SELECT 1 FROM duckdb_views() s
      WHERE s.database_name = 'memory' AND s.schema_name = 'main'
        AND s.view_name = 'foundation_summary'
        AND s.sql LIKE '%''' || v.table_name || '''%'
        AND s.sql LIKE '%FROM ' || v.table_name || '%'
    )

  -- ── every first-class entity is exposed or exempted on the record ──
  -- See the _entity_table / _entity_view block above for why this is structural rather
  -- than left to review. Three directions, because a one-directional list rots: an
  -- entity nobody listed, a listing for a table that no longer exists, and a listing
  -- naming a view that was never created or has since been renamed.
  UNION ALL
  SELECT 'unexposed_entity', t.table_name
  FROM _entity_table t
  WHERE t.table_name NOT IN (SELECT entity_table FROM _entity_view)

  UNION ALL
  SELECT 'stale_entity_view', e.entity_table
  FROM _entity_view e
  WHERE NOT EXISTS (SELECT 1 FROM duckdb_tables()
                    WHERE database_name = 'fc' AND table_name = e.entity_table)

  UNION ALL
  SELECT 'missing_entity_view',
         e.entity_table || ' -> ' || coalesce(e.view_name, 'NULL')
  FROM _entity_view e
  WHERE e.view_name IS NULL
     OR NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'main' AND table_name = e.view_name)

  -- ── every alias/abbreviation lookup table is exposed ──
  -- This one exists because of a PROCESS failure, not a code failure, and it's the only
  -- check here aimed at that. The foundation's "expose it when an analysis needs it"
  -- rule silently assumed a consumer who knows the table exists; twice now a campaign
  -- didn't, hand-rolled a worse lookup and shipped — a country map missing half of
  -- catalog_locationalias, and reward-type phrasings mapped by hand against a
  -- RewardTypeAlias table holding one row. Neither raised a promotion request, because
  -- neither knew there was anything to promote. Demand is the wrong signal for a
  -- vocabulary: not knowing it exists looks exactly like not needing it.
  --
  -- So coverage is asserted structurally instead. Matched against the VIEW SQL rather
  -- than a hand-kept table->view map: the map would be a second list to forget, and the
  -- claim being made is only "some public view reads this table", which the definition
  -- text answers directly. Private _underscore views don't count — a helper nothing can
  -- query is not exposure.
  UNION ALL
  SELECT 'unexposed_alias_table', t.table_name
  FROM _alias_tables t
  WHERE NOT EXISTS (
    SELECT 1 FROM duckdb_views() v
    WHERE v.schema_name = 'main'
      AND v.view_name NOT LIKE '\_%' ESCAPE '\'
      AND v.sql LIKE '%' || t.table_name || '%'
  )

  -- ── the two dim hand-lists must agree ──
  -- _model_dim_wide names the dims a live model POINTS AT; _dim_status names the dims
  -- whose liveness is looked up. model_dim_not_live is their join, so a dim in one and
  -- not the other is silently outside the liveness guarantee — and uncovered_model_dim
  -- does not catch it: satisfying that check by adding the new FK to _dim_status ALONE
  -- leaves _model_dim_wide short, the join yields nothing for it, and the self-test
  -- stays green. Structural, so it holds whatever the catalog contains.
  UNION ALL
  SELECT 'dim_not_liveness_checked', column_name
  FROM duckdb_columns()
  WHERE database_name = 'memory' AND table_name = '_model_dim_wide'
    AND column_name <> 'model_id'
    AND column_name NOT IN (SELECT DISTINCT dim FROM _dim_status)
  UNION ALL
  SELECT 'dim_status_unreferenced', d.dim
  FROM (SELECT DISTINCT dim FROM _dim_status) d
  WHERE d.dim NOT IN (
    SELECT column_name FROM duckdb_columns()
    WHERE database_name = 'memory' AND table_name = '_model_dim_wide'
      AND column_name <> 'model_id')

  -- ── domain vocabulary: DomainModel.md and the catalog must agree ──
  -- domain_vocab is grain (one row per term), so a term defined TWICE under one dim
  -- fans out every join to it while all four agreement checks stay green — both rows
  -- match a live term, so nothing is undocumented and nothing is stale. Same grain
  -- guard theme_grain_dup / gpf_grain_dup / lineage_grain_dup carry.
  UNION ALL
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
  WHERE v.dim NOT IN (SELECT dim FROM domain_vocab)

  -- A public view with no COMMENT ON VIEW. That comment IS the view reference —
  -- `analysis describe` reads it out of the session, so an undocumented view is a view
  -- nobody can find. It replaced a hand-maintained prose table in README.md, which had
  -- no check on it and was incomplete from the day it was written: models.description
  -- is selected by models and named in neither the comment block nor that table.
  -- Same both-directions logic as the other coverage lists: the docs are only trustworthy
  -- while every view is obliged to carry one.
  -- Reads duckdb_views() rather than information_schema.tables, which has no `comment`.
  -- foundation_summary / foundation_checks are THIS file's views, not the foundation's.
  UNION ALL
  SELECT 'undocumented_view', view_name
  FROM duckdb_views()
  WHERE database_name = 'memory' AND schema_name = 'main'
    AND NOT starts_with(view_name, '_')
    AND view_name NOT IN ('foundation_summary', 'foundation_checks')
    AND comment IS NULL

  -- Macros are reference surface too — `analysis describe` lists them, and a view
  -- comment can send you to one (citation_root_domains names citation_root_for_host).
  -- `internal` excludes DuckDB's own built-ins.
  UNION ALL
  SELECT DISTINCT 'undocumented_macro', function_name
  FROM duckdb_functions()
  WHERE database_name = 'memory' AND schema_name = 'main'
    AND NOT internal AND NOT starts_with(function_name, '_')
    AND comment IS NULL

  -- ─── Provenance layer ──────────────────────────────────────────────────────
  -- The attribution and citation invariants, defined in provenance_checks.sql and
  -- folded in here so the gate and the mutation harness keep a single entry point.
  -- Same (check_name, detail) shape, so these read as more branches of this UNION.
  UNION ALL
  SELECT check_name, detail FROM _provenance_checks

  -- ─── Data patch layer ──────────────────────────────────────────────────────
  -- The patch-lens invariants, from data_patches_checks.sql, folded in on the same
  -- terms. Every layer catalog.sql reads ends up in this one view.
  UNION ALL
  SELECT check_name, detail FROM _data_patch_checks;
