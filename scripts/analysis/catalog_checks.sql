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
--   anchor     — a decoded facet went unexpectedly dark: no row holds a usable value,
--                whether all-NULL or all-ZERO (a join/extract broke) — the one failure
--                a row-level invariant can't see. GENERATED from the views themselves
--                (see the _anchor_scan block), so the anchor set can't drift behind the
--                columns; data-dependent but decisive on a populated DB.
--   coverage   — meta-checks that fail when a new VIEW or list facet is added without
--                being anchored, so the generated sweep can't be silently out-run.
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
-- PUBLIC view consume it? _ce_location and _title_live_n feed all_models, so they stay
-- there. These do not.

-- _ce_location_n — live locations per CE. catalog.sql's `_ce_location` collapses a CE
-- to ONE row on the assumption that every CE has exactly one live location; this states
-- that assumption as a number so ce_multi_location can test it.
CREATE OR REPLACE VIEW _ce_location_n AS
  SELECT cel.corporate_entity_id, count(*) AS n
  FROM fc.catalog_corporateentitylocation cel
  JOIN fc.catalog_location l
    ON l.id = cel.location_id AND l.status IS DISTINCT FROM 'deleted'
  GROUP BY cel.corporate_entity_id;

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
-- iterate table names (the same limit _anchor_scan works around). Both directions are
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



-- foundation_summary — row count per public view; doubles as a health dashboard.
CREATE OR REPLACE VIEW foundation_summary AS
  SELECT 'models'              AS view_name, count(*) AS n_rows FROM models
  UNION ALL SELECT 'all_models',          count(*) FROM all_models
  UNION ALL SELECT 'model_lineage',       count(*) FROM model_lineage
  UNION ALL SELECT 'model_relationships', count(*) FROM model_relationships
  UNION ALL SELECT 'model_edges',         count(*) FROM model_edges
  UNION ALL SELECT 'model_edges_bidir',   count(*) FROM model_edges_bidir
  UNION ALL SELECT 'manufacturers',       count(*) FROM manufacturers
  UNION ALL SELECT 'model_number_collisions', count(*) FROM model_number_collisions
  UNION ALL SELECT 'rewards',             count(*) FROM rewards
  UNION ALL SELECT 'themes',              count(*) FROM themes
  UNION ALL SELECT 'tags',                count(*) FROM tags
  UNION ALL SELECT 'model_gameplay_features', count(*) FROM model_gameplay_features
  UNION ALL SELECT 'gameplay_feature_vocab',   count(*) FROM gameplay_feature_vocab
  UNION ALL SELECT 'gameplay_feature_aliases', count(*) FROM gameplay_feature_aliases
  UNION ALL SELECT 'model_themes',        count(*) FROM model_themes
  UNION ALL SELECT 'theme_vocab',         count(*) FROM theme_vocab
  UNION ALL SELECT 'theme_aliases',       count(*) FROM theme_aliases
  UNION ALL SELECT 'model_export_markets', count(*) FROM model_export_markets
  UNION ALL SELECT 'countries',           count(*) FROM countries
  UNION ALL SELECT 'country_aliases',     count(*) FROM country_aliases
  UNION ALL SELECT 'location_aliases',    count(*) FROM location_aliases
  UNION ALL SELECT 'reward_types',          count(*) FROM reward_types
  UNION ALL SELECT 'reward_type_aliases',   count(*) FROM reward_type_aliases
  UNION ALL SELECT 'manufacturer_aliases',  count(*) FROM manufacturer_aliases
  UNION ALL SELECT 'corporate_entity_aliases',  count(*) FROM corporate_entity_aliases
  UNION ALL SELECT 'person_aliases',        count(*) FROM person_aliases
  UNION ALL SELECT 'model_abbreviations',   count(*) FROM model_abbreviations
  UNION ALL SELECT 'title_abbreviations',   count(*) FROM title_abbreviations
  UNION ALL SELECT 'game_formats',        count(*) FROM game_formats
  UNION ALL SELECT 'title_size',          count(*) FROM title_size
  UNION ALL SELECT 'domain_vocab',        count(*) FROM domain_vocab
  UNION ALL SELECT 'claims',              count(*) FROM claims
  UNION ALL SELECT 'model_claims',        count(*) FROM model_claims
  UNION ALL SELECT 'claim_identity_parts', count(*) FROM claim_identity_parts
  UNION ALL SELECT 'ingest_sources',      count(*) FROM ingest_sources
  UNION ALL SELECT 'ingest_runs',         count(*) FROM ingest_runs
  UNION ALL SELECT 'citation_sources',    count(*) FROM citation_sources
  UNION ALL SELECT 'citation_roots',      count(*) FROM citation_roots
  UNION ALL SELECT 'citation_instances',  count(*) FROM citation_instances
  UNION ALL SELECT 'claim_citations',     count(*) FROM claim_citations
  UNION ALL SELECT 'citation_root_domains', count(*) FROM citation_root_domains
  ORDER BY view_name;

-- ─── Generated dark anchors ─────────────────────────────────────────────────
-- The anchor set used to be a hand-written list — one `WHERE count(col) = 0` line per
-- decoded facet — kept in sync with the view columns by memory. That list drifted every
-- time a column was added (the reason facets kept "going dark" unnoticed). These three
-- objects replace it with a sweep that derives the anchors from the views themselves:
--   _dark_cols(view)  a table macro: one row per column of the view, carrying `live` —
--                     how many rows hold a value that is neither NULL nor ZERO. No
--                     per-column list to maintain.
--                     Zero counts as dark ON PURPOSE. A derived count that collapses
--                     because its join broke goes all-ZERO, not all-NULL, so a plain
--                     COUNT() sees 601 healthy-looking rows and reports nothing — the
--                     exact blind spot that let a zeroed theme_vocab.n pass. Every
--                     derived count in the foundation (title_size, the vocab `n`s,
--                     manufacturers.n_*) shares that failure mode, so the measure
--                     handles it once here rather than by per-column checks.
--                     The '0'-as-text comparison is deliberate: it needs no type
--                     introspection, and a text column whose every value is literally
--                     "0" is both vanishingly rare and worth a look anyway.
--                     The COALESCE is load-bearing. SUM over ZERO rows returns NULL,
--                     not 0, and UNPIVOT drops NULL values — so without it an EMPTY
--                     view contributes no rows at all, silently losing the per-column
--                     anchors AND misreporting itself as `unanchored_view`.
--   _anchor_scan      that sweep run over every public decode view. Adding a column to
--                     any of them anchors it for free; adding a whole VIEW without
--                     listing it here is caught by the `unanchored_view` meta-check.
--                     It stays a VIEW so it's lazy (a `query`-mode run that never
--                     touches the checks pays nothing) and independently inspectable,
--                     but foundation_checks pulls it through a MATERIALIZED CTE — see
--                     the note there. Sweeping every column of every public view is
--                     the single most expensive thing in this file, and DuckDB
--                     re-evaluates a view once PER REFERENCE.
--   _anchor_skip      hand-input: columns ALLOWED to be entirely empty (genuinely-sparse
--                     optional facets that would false-positive). A short EXCEPTION list
--                     with a safe default — forgetting an entry over-anchors (loud), it
--                     never silently under-anchors. Entries are `sparse` (no expiry) or
--                     `pending` (expires when the data lands); see the block below.
--   _anchor_array     hand-input: the LIST-typed facets accounted for, qualified
--                     view.column — any element type (VARCHAR[], BIGINT[], …), matched
--                     on the type suffix rather than a fixed list. An empty list is a
--                     value, so the sweep reads it as live and lists fall out; this is
--                     what the `unanchored_array` meta-check measures against, so a new
--                     list facet fails loudly until it gets a home. Qualified, not bare
--                     column names — `parents` in one vocab view must not silently
--                     exempt `parents` in another.
CREATE OR REPLACE MACRO _dark_cols(vn) AS TABLE
  UNPIVOT (SELECT COALESCE(SUM(CASE WHEN COLUMNS(*) IS NULL        THEN 0
                                    WHEN COLUMNS(*)::VARCHAR = '0' THEN 0
                                    ELSE 1 END), 0)
           FROM query_table(vn))
    ON COLUMNS(*) INTO NAME col VALUE live;

CREATE OR REPLACE VIEW _anchor_scan AS
            SELECT 'all_models'              AS view_name, col, live FROM _dark_cols('all_models')
  UNION ALL SELECT 'models',                 col, live FROM _dark_cols('models')
  UNION ALL SELECT 'countries',              col, live FROM _dark_cols('countries')
  UNION ALL SELECT 'country_aliases',        col, live FROM _dark_cols('country_aliases')
  UNION ALL SELECT 'location_aliases',       col, live FROM _dark_cols('location_aliases')
  UNION ALL SELECT 'reward_types',             col, live FROM _dark_cols('reward_types')
  UNION ALL SELECT 'reward_type_aliases',      col, live FROM _dark_cols('reward_type_aliases')
  UNION ALL SELECT 'manufacturer_aliases',     col, live FROM _dark_cols('manufacturer_aliases')
  UNION ALL SELECT 'corporate_entity_aliases',  col, live FROM _dark_cols('corporate_entity_aliases')
  UNION ALL SELECT 'person_aliases',           col, live FROM _dark_cols('person_aliases')
  UNION ALL SELECT 'model_abbreviations',      col, live FROM _dark_cols('model_abbreviations')
  UNION ALL SELECT 'title_abbreviations',      col, live FROM _dark_cols('title_abbreviations')
  UNION ALL SELECT 'game_formats',           col, live FROM _dark_cols('game_formats')
  UNION ALL SELECT 'rewards',                col, live FROM _dark_cols('rewards')
  UNION ALL SELECT 'themes',                 col, live FROM _dark_cols('themes')
  UNION ALL SELECT 'tags',                   col, live FROM _dark_cols('tags')
  UNION ALL SELECT 'model_gameplay_features',col, live FROM _dark_cols('model_gameplay_features')
  UNION ALL SELECT 'gameplay_feature_vocab', col, live FROM _dark_cols('gameplay_feature_vocab')
  UNION ALL SELECT 'gameplay_feature_aliases',col, live FROM _dark_cols('gameplay_feature_aliases')
  UNION ALL SELECT 'model_themes',           col, live FROM _dark_cols('model_themes')
  UNION ALL SELECT 'theme_vocab',            col, live FROM _dark_cols('theme_vocab')
  UNION ALL SELECT 'theme_aliases',          col, live FROM _dark_cols('theme_aliases')
  UNION ALL SELECT 'model_edges',            col, live FROM _dark_cols('model_edges')
  UNION ALL SELECT 'model_edges_bidir',      col, live FROM _dark_cols('model_edges_bidir')
  UNION ALL SELECT 'manufacturers',          col, live FROM _dark_cols('manufacturers')
  UNION ALL SELECT 'model_number_collisions',col, live FROM _dark_cols('model_number_collisions')
  UNION ALL SELECT 'model_lineage',          col, live FROM _dark_cols('model_lineage')
  UNION ALL SELECT 'model_relationships',    col, live FROM _dark_cols('model_relationships')
  UNION ALL SELECT 'model_export_markets',   col, live FROM _dark_cols('model_export_markets')
  UNION ALL SELECT 'title_size',             col, live FROM _dark_cols('title_size')
  UNION ALL SELECT 'domain_vocab',          col, live FROM _dark_cols('domain_vocab')
  UNION ALL SELECT 'claims',                col, live FROM _dark_cols('claims')
  UNION ALL SELECT 'model_claims',          col, live FROM _dark_cols('model_claims')
  UNION ALL SELECT 'claim_identity_parts',  col, live FROM _dark_cols('claim_identity_parts')
  UNION ALL SELECT 'ingest_sources',        col, live FROM _dark_cols('ingest_sources')
  UNION ALL SELECT 'ingest_runs',           col, live FROM _dark_cols('ingest_runs')
  UNION ALL SELECT 'citation_sources',      col, live FROM _dark_cols('citation_sources')
  UNION ALL SELECT 'citation_roots',        col, live FROM _dark_cols('citation_roots')
  UNION ALL SELECT 'citation_instances',    col, live FROM _dark_cols('citation_instances')
  UNION ALL SELECT 'claim_citations',       col, live FROM _dark_cols('claim_citations')
  UNION ALL SELECT 'citation_root_domains', col, live FROM _dark_cols('citation_root_domains');

-- Two kinds of entry, and the difference is whether the exemption can EXPIRE:
--   sparse   allowed to be empty indefinitely — an optional dim the app barely
--            populates, where anchoring would false-positive the moment the last
--            value is edited away.
--   pending  expected to be empty only until data lands, so it MUST expire.
--            `expired_anchor_skip` retires one the moment its facet goes live.
--            Both pending entries this list has carried so far outlived their
--            reason SILENTLY — the export patches landed and nobody came back to
--            remove either — which is the same under-anchoring this whole file
--            exists to prevent, just one level up. Hence the check rather than a
--            comment asking someone to remember.
-- `col` is matched bare when the name is unique to its facet, or qualified
-- `view.column` when it isn't: `target_label` is populated on the edge views and
-- empty on model_export_markets, so only the qualified form exempts the one
-- without also exempting the others.
CREATE OR REPLACE VIEW _anchor_skip AS
  SELECT * FROM (VALUES
    ('technology_subgeneration_slug',     'sparse'),
    ('display_subtype_slug',              'sparse'),
    -- free-text region label, used only when a market isn't a resolvable country
    ('model_export_markets.target_label', 'sparse'),
    -- Licensing is modelled end to end but nothing populates it yet: no ingest source
    -- sets a default license, no claim carries an override, SourceFieldLicense is
    -- empty. `pending`, not `sparse` — the day a license is attached these must start
    -- anchoring, and expired_anchor_skip is what makes that happen without anyone
    -- remembering. Bare names: the columns are the same facet on claims and
    -- model_claims, so one entry should exempt both.
    ('license_slug',                        'pending'),
    ('ingest_source_default_license_slug',  'pending'),
    ('default_license_slug',                'pending'),
    -- no ingest run has rejected a claim yet; all-zero, not all-NULL
    ('ingest_runs.claims_rejected',         'pending')
  ) AS t(col, kind);

-- Every LIST-typed facet in a swept view (any element type), and how it is anchored.
-- Two kinds:
--   explicit — the row exists regardless of the array, so all-empty is a distinct dark
--              state needing its own `len(...) > 0` anchor in foundation_checks below.
--   implicit — the row exists ONLY when the list is non-empty (rewards/themes/tags),
--              so the view's scalar `id` column already anchors emptiness for free.
-- Every explicit entry gets its OWN anchor — a superset's is not a substitute. That
-- shortcut used to be taken here on the argument that models ⊂ all_models and that
-- union_integrity proves model_edges lossless over its two components. Losslessness is
-- not populatedness: zeroing model_relationships.target_reward_types left model_edges
-- non-empty from the lineage side and fired nothing at all.
CREATE OR REPLACE VIEW _anchor_array AS
  SELECT unnest([
    'all_models.opdb_features',            'models.opdb_features',
    'model_edges.target_reward_types',     'model_lineage.target_reward_types',
    'model_relationships.target_reward_types',
    'rewards.rewards', 'themes.themes', 'tags.tags',
    'theme_vocab.parents',            'theme_vocab.children',            'theme_vocab.aliases',
    'gameplay_feature_vocab.parents', 'gameplay_feature_vocab.children', 'gameplay_feature_vocab.aliases',
    'model_edges_bidir.target_reward_types',
    -- a collision row exists only when n > 1, so its scalar columns anchor it
    'model_number_collisions.model_ids', 'model_number_collisions.labels',
    'citation_roots.root_domains'
  ]) AS qualified_col;

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
  -- The anchor sweep, evaluated ONCE for all three checks that consume it. Without
  -- MATERIALIZED, DuckDB re-runs a referenced view per reference — three full sweeps
  -- of every column of every public view, ~1.5s of the self-test's runtime for two
  -- redundant copies of the same answer. Cost also stops scaling with the number of
  -- consuming checks, so a fourth is free. Prefer this over materializing _anchor_scan
  -- into a TABLE at init: that made the sweep EAGER, and the runner starts a fresh
  -- DuckDB per query (context, summary, checks), so every invocation paid for a sweep
  -- it mostly didn't use. Lazy view + materialized-at-use is both.
  WITH scan AS MATERIALIZED (SELECT * FROM _anchor_scan),
  -- Same reasoning, for the mirrored edge set: three checks consume it, one of them
  -- twice (a self anti-join), and it is the widest view in the foundation.
  bidir AS MATERIALIZED (SELECT * FROM model_edges_bidir),
  -- ...and for every foundation view the checks below share. DuckDB re-evaluates a
  -- view once PER REFERENCE, and ~30 checks referencing a dozen views means the same
  -- decode runs dozens of times: no single check is slow, the repetition is. These CTEs
  -- SHADOW the same-named views (hence `main.` on the right-hand side), so the checks
  -- read them by their ordinary names with no edit at the call site.
  models              AS MATERIALIZED (SELECT * FROM main.models),
  all_models          AS MATERIALIZED (SELECT * FROM main.all_models),
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
  model_export_markets    AS MATERIALIZED (SELECT * FROM main.model_export_markets)

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

  -- integrity: a live model attributed to a soft-deleted DIMENSION (Title, corporate
  -- entity, manufacturer, game format, or any taxonomy dim). Every one of those FKs is
  -- PROTECT and the soft-delete walker blocks deleting a row an active entity still
  -- references, with Title additionally cascading to its models — so this is
  -- unreachable unless a protection was bypassed. Same class as lineage_target_not_live,
  -- and the reason all_models live-filters each dim join rather than reporting a retired
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

  -- the grain view and the display list describe the SAME memberships — compared by
  -- VALUE, not by count. They're built by different paths (model_themes filters live
  -- subjects with an EXISTS and carries slugs; `themes` groups names off the raw join),
  -- so reconstructing one from the other is a real cross-view check: it catches a live
  -- filter added to one and not the other, AND a same-size mis-join that lands the
  -- right number of wrong themes on a model. Cardinality alone would miss the second,
  -- which is the one that silently corrupts every name a theme cleanup reads.
  UNION ALL
  SELECT 'theme_views_disagree',
         'model_id=' || model_id::VARCHAR || ' grain=' || COALESCE(grain::VARCHAR, '<none>')
           || ' list=' || COALESCE(list::VARCHAR, '<none>')
  FROM (
    SELECT m.id AS model_id,
           (SELECT list_sort(list(tv.name))
              FROM model_themes mt JOIN theme_vocab tv ON tv.id = mt.theme_id
             WHERE mt.model_id = m.id) AS grain,
           th.themes                   AS list
    FROM models m LEFT JOIN themes th ON th.id = m.id
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
  -- reachable on all_models, for a deleted model whose Title has no live rows left.
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
  -- namesake_count = 0 is only reachable on all_models, for a deleted model whose
  -- name no live model carries. Reads the model column independently of the
  -- disagreement check above, which compares it against a recomputation.
  UNION ALL
  SELECT 'namesake_count_zero_on_live', 'model_id=' || id::VARCHAR
  FROM models WHERE namesake_count IS NULL OR namesake_count < 1

  -- manufacturers.country_slug is set IFF the maker's models agree on one country —
  -- the guard against a multi-country maker being silently collapsed to one value
  UNION ALL
  SELECT 'manufacturer_country_collapsed',
         slug || ' n_countries=' || n_countries::VARCHAR
  FROM manufacturers
  WHERE n_countries IS NULL
     OR (n_countries = 1) IS DISTINCT FROM (country_slug IS NOT NULL)

  -- era_* is set IFF the maker has a dated model, and is a well-formed span.
  -- BOTH ends are tested for presence: `era_start > era_end` goes NULL when era_end is
  -- NULL, so an era_start-only row would otherwise pass a comparison that never ran.
  UNION ALL
  SELECT 'manufacturer_era_malformed',
         slug || ' n_dated=' || n_dated::VARCHAR
           || ' era=' || COALESCE(era_start::VARCHAR, 'NULL')
           || '..'    || COALESCE(era_end::VARCHAR, 'NULL')
  FROM manufacturers
  WHERE n_dated IS NULL OR n_models IS NULL
     OR (n_dated > 0) IS DISTINCT FROM (era_start IS NOT NULL)
     OR (n_dated > 0) IS DISTINCT FROM (era_end IS NOT NULL)
     OR era_start > era_end
     OR n_dated > n_models

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

  -- ── anchors: a decoded facet went unexpectedly dark (a join/extract broke) ──
  -- GENERATED from _anchor_scan (see the macro block above), so every column of every
  -- public view is dark-anchored automatically — including whole-view-empty, which
  -- shows up as ALL its columns reading zero. Nothing to keep in sync per column.
  -- "Dark" means no row holds a usable value: all-NULL for a decoded facet, all-ZERO
  -- for a derived count. Both are the same failure wearing different clothes.
  UNION ALL
  SELECT 'anchor_dark', view_name || '.' || col
  FROM scan
  WHERE live = 0
    AND col                       NOT IN (SELECT col FROM _anchor_skip)
    AND view_name || '.' || col   NOT IN (SELECT col FROM _anchor_skip)

  -- List facets can't go dark via the sweep: an empty list is a value, so it reads as
  -- live. The ones whose row exists regardless of the list therefore need an explicit
  -- non-empty anchor. `unanchored_array` below fails if a new one appears unlisted.
  UNION ALL SELECT 'anchor_dark', 'all_models.opdb_features (all empty)'
    WHERE (SELECT count(*) FROM all_models WHERE len(opdb_features) > 0) = 0
  UNION ALL SELECT 'anchor_dark', 'models.opdb_features (all empty)'
    WHERE (SELECT count(*) FROM models WHERE len(opdb_features) > 0) = 0
  UNION ALL SELECT 'anchor_dark', 'model_edges.target_reward_types (all empty)'
    WHERE (SELECT count(*) FROM model_edges WHERE len(target_reward_types) > 0) = 0
  -- Each COMPONENT anchored too, not just the union. model_edges is a UNION ALL, so one
  -- component's array can go entirely empty while the other keeps the union non-empty —
  -- the union anchor reads healthy and the dark half is invisible. union_integrity
  -- proves the union is LOSSLESS, which is a different claim from each side being
  -- populated, and only the latter is what an anchor is for.
  UNION ALL SELECT 'anchor_dark', 'model_lineage.target_reward_types (all empty)'
    WHERE (SELECT count(*) FROM model_lineage WHERE len(target_reward_types) > 0) = 0
  UNION ALL SELECT 'anchor_dark', 'model_relationships.target_reward_types (all empty)'
    WHERE (SELECT count(*) FROM model_relationships WHERE len(target_reward_types) > 0) = 0
  UNION ALL SELECT 'anchor_dark', 'model_edges_bidir.target_reward_types (all empty)'
    WHERE (SELECT count(*) FROM model_edges_bidir WHERE len(target_reward_types) > 0) = 0
  -- The vocab views' DAG and alias lists: a row exists for every live term regardless
  -- of them, so an all-empty list is a distinct dark state COUNT can't see (a corpus
  -- whose parenting join broke reads as healthy without these).
  UNION ALL SELECT 'anchor_dark', 'theme_vocab.parents (all empty)'
    WHERE (SELECT count(*) FROM theme_vocab WHERE len(parents) > 0) = 0
  UNION ALL SELECT 'anchor_dark', 'theme_vocab.children (all empty)'
    WHERE (SELECT count(*) FROM theme_vocab WHERE len(children) > 0) = 0
  UNION ALL SELECT 'anchor_dark', 'theme_vocab.aliases (all empty)'
    WHERE (SELECT count(*) FROM theme_vocab WHERE len(aliases) > 0) = 0
  UNION ALL SELECT 'anchor_dark', 'gameplay_feature_vocab.parents (all empty)'
    WHERE (SELECT count(*) FROM gameplay_feature_vocab WHERE len(parents) > 0) = 0
  UNION ALL SELECT 'anchor_dark', 'gameplay_feature_vocab.children (all empty)'
    WHERE (SELECT count(*) FROM gameplay_feature_vocab WHERE len(children) > 0) = 0
  UNION ALL SELECT 'anchor_dark', 'gameplay_feature_vocab.aliases (all empty)'
    WHERE (SELECT count(*) FROM gameplay_feature_vocab WHERE len(aliases) > 0) = 0
  -- A citation root exists whether or not it has registered domains (a book never
  -- will), so the row count can't anchor this one — only the web roots carry it.
  UNION ALL SELECT 'anchor_dark', 'citation_roots.root_domains (all empty)'
    WHERE (SELECT count(*) FROM citation_roots WHERE len(root_domains) > 0) = 0

  -- Subpopulation anchors the column sweep CAN'T see: a filtered subset going dark
  -- while the column still has values from the other subset. One per lineage kind.
  UNION ALL SELECT 'anchor_dark', 'model_lineage variant_of is empty'
    WHERE (SELECT count(*) FROM model_lineage WHERE edge_kind = 'variant_of') = 0
  UNION ALL SELECT 'anchor_dark', 'model_lineage remake_of is empty'
    WHERE (SELECT count(*) FROM model_lineage WHERE edge_kind = 'remake_of') = 0
  UNION ALL SELECT 'anchor_dark', 'model_lineage export_edition_of is empty'
    WHERE (SELECT count(*) FROM model_lineage WHERE edge_kind = 'export_edition_of') = 0

  -- ── coverage: close the last hand-lists so a NEW view/array can't slip in unanchored ──
  -- A public foundation view not swept by _anchor_scan (added without being anchored).
  -- The two *_context watermarks are excluded on purpose — their NULLs are legitimate
  -- (no successful patch yet, an empty provenance table on a fresh DB).
  UNION ALL
  SELECT 'unanchored_view', table_name
  FROM information_schema.tables
  WHERE table_schema = 'main' AND table_type = 'VIEW'
    AND table_name NOT LIKE '\_%' ESCAPE '\'
    AND table_name NOT IN ('foundation_summary', 'foundation_checks',
                           'analysis_context', 'provenance_context')
    AND table_name NOT IN (SELECT DISTINCT view_name FROM scan)

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

  -- _anchor_skip.kind outside its two-value vocabulary. The exemption is applied on
  -- `col` alone, so a typo'd kind still exempts the column — but expired_anchor_skip
  -- only retires `pending`, so `pendign` exempts FOREVER and nothing ever notices. An
  -- unreadable kind is a permanent silent hole in the anchor coverage, which is the one
  -- thing this list is not allowed to be.
  UNION ALL
  SELECT 'unknown_anchor_skip_kind', col || ' (' || coalesce(kind, 'NULL') || ')'
  FROM _anchor_skip
  WHERE kind IS NULL OR kind NOT IN ('sparse', 'pending')

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
  -- is selected by all_models and named in neither the comment block nor that table.
  -- Same both-directions logic as the anchor lists: the docs are only trustworthy
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

  -- A list facet in a swept view that isn't accounted for would silently escape the
  -- dark check (an empty list reads as live), so flag any new one for a home in
  -- _anchor_array — which records, per facet, whether it needs an explicit anchor or
  -- rides the view's scalar columns. Matched on the `[]` type suffix, so BIGINT[] and
  -- friends are covered, not just VARCHAR[].
  UNION ALL
  SELECT 'unanchored_array', table_name || '.' || column_name
  FROM information_schema.columns
  WHERE table_schema = 'main' AND data_type LIKE '%[]%'
    AND table_name IN (SELECT DISTINCT view_name FROM scan)
    AND table_name || '.' || column_name NOT IN (SELECT qualified_col FROM _anchor_array)

  -- ...and the inverse: an _anchor_array entry naming a facet that no longer exists
  -- (renamed or dropped), so the list can't rot into false coverage.
  UNION ALL
  SELECT 'stale_anchor_array', qualified_col
  FROM _anchor_array
  WHERE qualified_col NOT IN (
    SELECT table_name || '.' || column_name FROM information_schema.columns
    WHERE table_schema = 'main' AND data_type LIKE '%[]%'
  )

  -- The same both-directions guard for _anchor_skip, which had neither and rotted
  -- twice because of it. An exemption is a hole in the anchor coverage, so it has to
  -- be as hard to leave lying around as it was to open.
  --   expired: a `pending` entry whose facet now HAS data. Its reason is spent — the
  --            column is anchorable, and while the entry survives nothing would notice
  --            it going dark again.
  UNION ALL
  SELECT 'expired_anchor_skip', s.col
  FROM _anchor_skip s
  WHERE s.kind = 'pending'
    AND EXISTS (
      SELECT 1 FROM scan
      WHERE live > 0 AND (col = s.col OR view_name || '.' || col = s.col)
    )

  --   stale:   an entry naming no swept column at all (renamed, dropped, or a typo —
  --            a misspelled entry exempts nothing and hides that it exempts nothing).
  UNION ALL
  SELECT 'stale_anchor_skip', s.col
  FROM _anchor_skip s
  WHERE NOT EXISTS (
    SELECT 1 FROM scan WHERE col = s.col OR view_name || '.' || col = s.col
  )

  -- ─── Provenance layer ──────────────────────────────────────────────────────
  -- The attribution and citation invariants, defined in provenance_checks.sql and
  -- folded in here so the gate and the mutation harness keep a single entry point.
  -- Same (check_name, detail) shape, so these read as more branches of this UNION.
  UNION ALL
  SELECT check_name, detail FROM _provenance_checks;
