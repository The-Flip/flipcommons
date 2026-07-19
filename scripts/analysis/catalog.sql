-- Catalog analysis foundation — shared, reusable decode layer over the live DB.
--
-- `.read` this from any plan-doc analysis script to get a connected, decoded
-- catalog. It ATTACHes backend/db.sqlite3 READ-ONLY and defines a small set of
-- clean analytical views over the awkward physical schema (JSON extra_data,
-- the model -> corporate_entity -> manufacturer label chain, reward M2M). Every
-- analysis wants these, so they live here instead of being re-derived per plan.
--
-- Run scripts from the REPO ROOT: both the ATTACH path below and the `.read`
-- that pulls this file in are resolved relative to the current directory.
--
--     duckdb -init docs/plans/<area>/<plan>.sql :memory: "FROM <a_view> LIMIT 5;"
--
-- Convention: an UNPREFIXED view name is public API you may build on and query;
-- a `_underscore` name is a private helper, not meant to be consumed directly.
-- See scripts/analysis/README.md for the full template.

INSTALL sqlite;
LOAD sqlite;
ATTACH IF NOT EXISTS 'backend/db.sqlite3' AS fc (TYPE sqlite, READ_ONLY);

-- Catalog records are soft-deleted (RecordLifecycle.md): a record is live unless
-- its resolved `status` is 'deleted'. Read APIs treat soft-deleted rows as
-- not-found, so `models` (and everything built on it) is LIVE-ONLY by default —
-- the semantics an analysis almost always wants. Reach for `all_models` only when
-- you specifically need the deleted rows too; it carries the same `status` column.

-- _ce_location — the MAKER's home location per corporate entity, collapsed to ONE
-- row per CE so joining it to all_models can't fan out the one-row-per-model grain.
-- A CE MAY carry several locations (CorporateEntityLocation is 1:N), but every CE in
-- the catalog has exactly one today: while that holds this is exact, and the day it
-- stops catalog_checks fires (ce_multi_location) so we add a model_locations grain
-- view rather than silently pick. Live locations only — Location is soft-deleted
-- (status), though the through table itself isn't. location_path is the most-specific
-- known place AND the stable key; country_slug is its root segment, the join key.
-- Private: read it through models' location_path / country_slug columns.
CREATE OR REPLACE VIEW _ce_location AS
  SELECT
    cel.corporate_entity_id,
    min(l.location_path)                     AS location_path,
    split_part(min(l.location_path), '/', 1) AS country_slug
  FROM fc.catalog_corporateentitylocation cel
  JOIN fc.catalog_location l
    ON l.id = cel.location_id AND l.status IS DISTINCT FROM 'deleted'
  GROUP BY cel.corporate_entity_id;

-- all_models — every MachineModel, live or deleted. Column names/types are in the
-- SELECT below and the README table; these notes cover only what ISN'T obvious.
-- Convention throughout: predicate and join on ids/slugs, display the names.
--   title_* : the model's Title — the spine of the hierarchy (every model has one).
--             title_id/title_slug/title_name decoded inline so title-mate and
--             "alone in its Title" analyses read identity off the model row instead
--             of reaching for catalog_title; `title_size` carries the same identity
--             plus the sibling count.
--   status  : 'active' | 'deleted' | NULL — live is anything but 'deleted'.
--   maker   : manufacturer_name is the canonical maker (Manufacturer.name via
--             corporate_entity) — display/group by it. The IPDB manufacturer
--             trade-name freetext is intentionally NOT a column; it stays in raw
--             extra_data, only for auditing the trade-name -> Manufacturer mapping.
--   location: where the MAKER was based, model -> corporate_entity -> location. This
--             is the maker's ORIGIN, NOT an export-market destination (a separate,
--             freetext-parsed concept). location_path ('usa/il/chicago') is the most-
--             specific known place and doubles as the stable key; country_slug ('usa')
--             is its root, the field to join/group by (-> countries.slug for the name).
--             Single-valued via _ce_location — see its note on the 1:1 assumption.
--   game_format_*   : machine genre, id/slug, NULL if untyped; `game_formats` carries
--             the name if you need it for display.
--   taxonomy dims   : technology_generation / technology_subgeneration, display_type
--             / display_subtype, system, cabinet, production_status — slug only
--             (DomainModel "Taxonomy & Classification"). These are controlled
--             vocabularies whose slug ('solid-state', 'dot-matrix', 'floor') is the
--             readable label AND, being unique per dim table, the raw-join key back to
--             fc.catalog_<dim> — so both the FK id and the display name are dropped as
--             redundant. Predicate and display on the slug; NULL when unset. The one
--             exception is `system`, which keeps `system_name`: a hardware designation
--             like 'Bally AS-2518-35' the slug ('bally-as2518-35') mangles.
--             production_status is the ProductionStatus FK, NOT the soft-delete
--             `status` column. The subgeneration/subtype dims are sparsely populated
--             today — surfaced anyway so a future campaign keying on them (e.g. the
--             nixie DisplaySubtype) finds the column already here.
--   variant_of_id / remake_of_id / export_edition_of_id : bare self-FKs to the
--             origin model — the `model_lineage` view expands them (see its
--             "two homes" note).
--   source free-text : ipdb_notes, ipdb_notable_features (prose) and opdb_features
--             (VARCHAR[], empty never NULL; 'Export edition', 'Cocktail', …) are the
--             fields the product doesn't surface. Mining them is most of plan
--             analysis, so they're first-class columns, not hand-rolled json_extract.
--   NOT surfaced : opdb.keywords is theme data — use `themes`, not raw keywords
--             (same reason makers go through manufacturer_name). The long tail
--             (ipdb.marketing_slogans, opdb.common_name, …) stays in extra_data;
--             promote one the day an analysis needs it.
--   label   : "Name (Manufacturer Year)", CE name then '?' as fallbacks; year
--             omitted if unknown.
CREATE OR REPLACE VIEW all_models AS
  SELECT
    m.id, m.name, m.slug,
    m.title_id, t.slug AS title_slug, t.name AS title_name,
    m.variant_of_id, m.remake_of_id, m.export_edition_of_id,
    m.opdb_id, m.ipdb_id, m.year, m.player_count,
    m.corporate_entity_id, ce.slug AS corporate_entity_slug,
    ce.manufacturer_id, mf.slug AS manufacturer_slug, mf.name AS manufacturer_name,
    cel.location_path, cel.country_slug,
    m.game_format_id, gf.slug AS game_format_slug,
    -- Single-FK taxonomy dims — slug only. The slug is the readable label AND, being
    -- unique per dim table, the raw-join key, so neither the FK id nor the display
    -- name earns a column. `system` keeps its name (a hardware designation the slug
    -- mangles).
    tg.slug  AS technology_generation_slug,
    tsg.slug AS technology_subgeneration_slug,
    dt.slug  AS display_type_slug,
    dst.slug AS display_subtype_slug,
    sys.slug AS system_slug,   sys.name AS system_name,
    cab.slug AS cabinet_slug,
    ps.slug  AS production_status_slug,
    m.description, m.status,
    json_extract_string(m.extra_data, '$."ipdb.notes"')            AS ipdb_notes,
    json_extract_string(m.extra_data, '$."ipdb.notable_features"') AS ipdb_notable_features,
    COALESCE(json_extract(m.extra_data, '$."opdb.features"')::VARCHAR[], []::VARCHAR[]) AS opdb_features,
    m.extra_data,
    m.name || ' ('
      || COALESCE(NULLIF(mf.name, ''), NULLIF(ce.name, ''), '?')
      || COALESCE(' ' || m.year::VARCHAR, '')
      || ')' AS label
  FROM fc.catalog_machinemodel m
  LEFT JOIN fc.catalog_title t             ON t.id  = m.title_id
  LEFT JOIN fc.catalog_corporateentity ce ON ce.id = m.corporate_entity_id
  LEFT JOIN fc.catalog_manufacturer mf     ON mf.id = ce.manufacturer_id
  LEFT JOIN _ce_location cel               ON cel.corporate_entity_id = m.corporate_entity_id
  LEFT JOIN fc.catalog_gameformat gf       ON gf.id = m.game_format_id
  LEFT JOIN fc.catalog_technologygeneration    tg  ON tg.id  = m.technology_generation_id
  LEFT JOIN fc.catalog_technologysubgeneration tsg ON tsg.id = m.technology_subgeneration_id
  LEFT JOIN fc.catalog_displaytype             dt  ON dt.id  = m.display_type_id
  LEFT JOIN fc.catalog_displaysubtype          dst ON dst.id = m.display_subtype_id
  LEFT JOIN fc.catalog_system                  sys ON sys.id = m.system_id
  LEFT JOIN fc.catalog_cabinet                 cab ON cab.id = m.cabinet_id
  LEFT JOIN fc.catalog_productionstatus        ps  ON ps.id  = m.production_status_id;

-- models — live models only. The default view; build analyses on this.
CREATE OR REPLACE VIEW models AS
  SELECT * FROM all_models WHERE status IS DISTINCT FROM 'deleted';

-- countries — the country vocabulary: live root Locations (a country has no
-- parent). Live-only because it feeds detectors — a soft-deleted country
-- shouldn't match a name suffix or a "for the X market" note. Carries slug too, so
-- models.country_slug (and target_country_slug) joins here for the country name. Add
-- an `all_countries` twin the day an analysis actually needs deleted rows.
CREATE OR REPLACE VIEW countries AS
  SELECT id, slug, name FROM fc.catalog_location
  WHERE parent_id IS NULL AND status IS DISTINCT FROM 'deleted';

-- game_formats — the machine-genre vocabulary (live). Join models.game_format_id to
-- it, or use it to check that a format slug/name you hardcode still exists. Promoted
-- because both the export and bingo analyses independently reached past the
-- foundation to read catalog_gameformat.
CREATE OR REPLACE VIEW game_formats AS
  SELECT id, slug, name FROM fc.catalog_gameformat
  WHERE status IS DISTINCT FROM 'deleted';

-- rewards — sorted reward-type names per model (only models that have any). Keyed
-- by id, so it inherits live/all semantics from whichever model view you join to.
-- Live reward types only, like `themes` — a soft-deleted reward type doesn't count.
CREATE OR REPLACE VIEW rewards AS
  SELECT rt2.machinemodel_id AS id, list_sort(list(rt.name)) AS rewards
  FROM fc.catalog_machinemodel_reward_types rt2
  JOIN fc.catalog_rewardtype rt ON rt.id = rt2.rewardtype_id AND rt.status IS DISTINCT FROM 'deleted'
  GROUP BY rt2.machinemodel_id;

-- themes — sorted theme names per model (only models that have any). Keyed by id,
-- like `rewards`. This is the canonical home for theme data; the raw opdb.keywords
-- tags that seeded it are intentionally not surfaced (see the note above). Live
-- themes only — a soft-deleted theme doesn't count.
CREATE OR REPLACE VIEW themes AS
  SELECT mt.machinemodel_id AS id, list_sort(list(t.name)) AS themes
  FROM fc.catalog_machinemodel_themes mt
  JOIN fc.catalog_theme t ON t.id = mt.theme_id AND t.status IS DISTINCT FROM 'deleted'
  GROUP BY mt.machinemodel_id;

-- tags — sorted list of TAG SLUGS per tagged model (only models with any). Keyed by
-- id like rewards/themes, so it inherits live/all from whichever model view you join
-- to. Deliberately lists SLUGS, not names: unlike rewards/themes (display lists),
-- tags are the classification vocabulary you PREDICATE on (`'widebody' IN tags`), and
-- the slug is the stable key. Live tags only. NB `conversion_kit` and re-themes are
-- NOT tags — they're ModelRelationship types (see DomainModel); only true Tag rows
-- appear here, so this view is the honest picture of the tag vocabulary.
CREATE OR REPLACE VIEW tags AS
  SELECT mt.machinemodel_id AS id, list_sort(list(tg.slug)) AS tags
  FROM fc.catalog_machinemodel_tags mt
  JOIN fc.catalog_tag tg ON tg.id = mt.tag_id AND tg.status IS DISTINCT FROM 'deleted'
  GROUP BY mt.machinemodel_id;

-- model_gameplay_features — one row per (model, directly-attached gameplay feature)
-- with its optional count. A grain view like model_relationships (many rows per
-- model), NOT a flattened name-list like rewards/themes — because the vast majority
-- of these rows carry a count (Flippers x2; Trap Holes x25, the 5x5 bingo card), so
-- flattening to names would drop the dominant signal. Live subjects only, like the
-- other grain views. Direct attachments ONLY: the GameplayFeature DAG (e.g. 2-Ball
-- Multiball under Multiball) is NOT rolled up to ancestors here — resolve parents
-- plan-locally if a query needs them, exactly as themes leaves its DAG unrolled.
-- Predicate and display on feature_slug (a controlled vocab: 'trap-holes', 'flippers');
-- the redundant display feature_name is not surfaced. feature_id keys the grain.
--   count : the M2M's optional count (Flippers x2); NULL for a bare membership. NB the
--           scalar catalog_machinemodel.flipper_count is deliberately NOT surfaced —
--           it's populated on a tiny fraction of models while the Flippers feature
--           covers thousands, so the feature is the real "has flippers" signal; the
--           scalar would look authoritative while being near-empty.
CREATE OR REPLACE VIEW model_gameplay_features AS
  SELECT
    mgf.machinemodel_id AS model_id,
    gf.id               AS feature_id,
    gf.slug             AS feature_slug,
    mgf.count           AS count
  FROM fc.catalog_machinemodelgameplayfeature mgf
  JOIN fc.catalog_gameplayfeature gf
    ON gf.id = mgf.gameplayfeature_id AND gf.status IS DISTINCT FROM 'deleted'
  WHERE EXISTS (SELECT 1 FROM models s WHERE s.id = mgf.machinemodel_id);  -- live subjects

-- _model_target — the distinguishing facts surfaced for the OTHER end of a
-- relationship edge (a lineage or relationship target): identity, year, genre
-- (game_format), reward types, player count, maker and where the maker was based
-- (location) — the pieces a reviewer uses to tell two models apart, and genre is the
-- most fundamental ("is my target a bingo?").
-- A pure projection of `models` (live-only) + `rewards`, with columns named
-- target_* so both edge views pull the whole block via `* EXCLUDE (id)` and never
-- restate the list. Private: read it through model_lineage / model_relationships.
-- Add a facet here once and both edge views gain it.
CREATE OR REPLACE VIEW _model_target AS
  SELECT
    m.id,
    m.slug                              AS target_slug,
    m.name                              AS target_name,
    m.year                              AS target_year,
    COALESCE(rw.rewards, []::VARCHAR[]) AS target_reward_types,
    m.player_count                      AS target_player_count,
    m.game_format_id                    AS target_game_format_id,
    m.game_format_slug                  AS target_game_format_slug,
    m.corporate_entity_id               AS target_corporate_entity_id,
    m.corporate_entity_slug             AS target_corporate_entity_slug,
    m.manufacturer_id                   AS target_manufacturer_id,
    m.manufacturer_slug                 AS target_manufacturer_slug,
    m.manufacturer_name                 AS target_manufacturer_name,
    m.location_path                     AS target_location_path,
    m.country_slug                      AS target_country_slug
  FROM models m
  LEFT JOIN rewards rw ON rw.id = m.id;

-- ─── Model-to-model relationships ───────────────────────────────────────────
-- `model_edges` is the DEFAULT — every edge out of a model, lineage + typed, in one
-- view. Reach for it first when exploring relationships: one `WHERE model_id = ?`
-- returns everything, so no source is missed. It's a UNION over the two mechanism-
-- specific views below, which exist because the edges have two different physical
-- shapes; drop to them when you want just ONE mechanism:
--
--   model_lineage        single-valued structured self-FKs: variant_of, remake_of,
--                        export_edition_of. At most ONE of each per model; the
--                        target is always a resolved catalog model. Fixed
--                        semantics, no payload.
--   model_relationships  the multi-valued typed edge table (ModelRelationship):
--                        MANY per model, a CLOSED four-value type vocabulary
--                        (conversion, conversion_kit, copy, retheme — DB-enforced), a
--                        license_status, and a target that may be an unresolved
--                        free-text label instead of a catalog model.
--
-- All three build on `models` (live-only), and follow ONE rule for the far end: an
-- edge KEEPS its row and de-enriches to NULL target_* rather than being dropped when
-- the target can't resolve. The only LEGITIMATE de-enrich is a typed free-text label
-- (target_label, no catalog model). A resolved-but-de-enriched target (target_id set,
-- target_slug NULL) is a soft-deleted target the app should have protected — an
-- integrity violation catalog_checks flags for BOTH mechanisms, not a normal path.
-- model_edges CONCATENATES the two; it does NOT reconcile overlaps — a variant_of FK
-- and a typed edge to the same target are two rows, deciding they're one is plan-local.
-- ─────────────────────────────────────────────────────────────────────────────

-- model_lineage — variant_of + remake_of + export_edition_of as row-grain edges:
-- one row per (model, edge_kind), 0..1 per kind. Target enriched inline via a LEFT
-- JOIN. The app PROTECTS lineage targets the same way it protects
-- typed-relationship targets — it blocks soft-deleting a model that is an ACTIVE
-- lineage-FK target (soft_delete_usage_blockers;
-- test_api_model_delete.test_remake_of_referrer_blocks returns 422) — so with a
-- live source (this view builds on `models`) the target is always live too, and
-- target_* always enriches. The LEFT JOIN is defensive, not an expected de-enrich
-- path: a resolved-but-de-enriched lineage target means that protection was
-- bypassed, and catalog_checks flags it (lineage_target_not_live), exactly like
-- model_relationships.
--   edge_kind : 'variant_of' | 'remake_of' | 'export_edition_of'
--   target_*  : the origin model's identity, year, genre, reward types, player count
--               and maker (see _model_target; predicate on ids/slugs, display names)
CREATE OR REPLACE VIEW model_lineage AS
  WITH edges AS (
    SELECT id AS model_id, variant_of_id AS target_id, 'variant_of' AS edge_kind
      FROM models WHERE variant_of_id IS NOT NULL
    UNION ALL
    SELECT id AS model_id, remake_of_id AS target_id, 'remake_of' AS edge_kind
      FROM models WHERE remake_of_id IS NOT NULL
    UNION ALL
    SELECT id AS model_id, export_edition_of_id AS target_id, 'export_edition_of' AS edge_kind
      FROM models WHERE export_edition_of_id IS NOT NULL
  )
  SELECT
    e.model_id,
    e.edge_kind,
    e.target_id,
    tgt.* EXCLUDE (id)
  FROM edges e
  LEFT JOIN _model_target tgt ON tgt.id = e.target_id;

-- model_relationships — the typed ModelRelationship edge table, one row per edge.
-- Multi-valued (many per model), unlike the single-valued self-FKs in
-- model_lineage. Live subjects only. The target is EITHER a resolved catalog model
-- (target_id set, target_* enriched) OR a free-text label (target_label set,
-- target_id NULL); a resolved-but-soft-deleted target keeps target_id but
-- de-enriches to NULL target_slug. Same target_* shape as model_lineage.
--   relationship_type : conversion | conversion_kit | copy | retheme — a CLOSED set
--                       (DB CHECK catalog_modelrelationship_type_valid)
--   license_status    : licensed | unlicensed | unknown — a CLOSED set
--                       (DB CHECK catalog_modelrelationship_license_status_valid)
--   target_label      : free-text origin when the donor isn't a catalog model
CREATE OR REPLACE VIEW model_relationships AS
  SELECT
    r.machine_model_id         AS model_id,
    r.relationship_type,
    r.license_status,
    r.target_machine_id        AS target_id,
    NULLIF(r.target_label, '') AS target_label,
    tgt.* EXCLUDE (id)
  FROM fc.catalog_modelrelationship r
  LEFT JOIN _model_target tgt ON tgt.id = r.target_machine_id   -- resolved target, if live
  WHERE EXISTS (SELECT 1 FROM models s WHERE s.id = r.machine_model_id);  -- live subjects only

-- model_export_markets — the ModelExportMarket rows: one row per export
-- destination of a live model. NOT part of model_edges (the target is a Location,
-- not a model — the model↔model half of the export story is the
-- export_edition_of lineage FK). The target ladder is OPTIONAL: a country
-- (target_location_id + country columns), a free-text region label
-- (target_label), or neither — the unknown-market row, whose existence alone
-- says "built for export". The app restricts location targets to countries
-- (COUNTRY_TARGET_FILTER), so the `countries` join always enriches; a
-- resolved-but-de-enriched target is an integrity violation catalog_checks
-- flags (export_market_target_not_country).
CREATE OR REPLACE VIEW model_export_markets AS
  SELECT
    em.machine_model_id                 AS model_id,
    em.target_market_location_id        AS target_location_id,
    c.slug                              AS target_country_slug,
    c.name                              AS target_country_name,
    NULLIF(em.target_market_label, '')  AS target_label
  FROM fc.catalog_modelexportmarket em
  LEFT JOIN countries c ON c.id = em.target_market_location_id
  WHERE EXISTS (SELECT 1 FROM models s WHERE s.id = em.machine_model_id);

-- model_edges — the DEFAULT relationships view: every edge out of a model, lineage
-- and typed, in one row-grain set. A UNION ALL over model_lineage + model_
-- relationships — no new joins, since both already carry the target_* block — so
-- one predicate returns all of a model's edges and none is missed. Concatenates,
-- does NOT reconcile (overlapping FK + typed edges are two rows; that's plan-local).
--   edge_source       : 'lineage_fk' (variant_of/remake_of/export_edition_of)
--                       | 'relationship' (typed)
--   relationship_type : variant_of | remake_of | export_edition_of | conversion |
--                       conversion_kit | copy | retheme — lineage's edge_kind (3)
--                       and the typed table's relationship_type (4, DB-enforced)
--                       unified: a CLOSED 7-value set.
--   license_status    : NULL for lineage FKs; licensed|unlicensed|unknown for typed.
--   target_label      : NULL for lineage (always resolved); set on label-only typed.
--   target_*          : the shared enrichment block (see _model_target).
CREATE OR REPLACE VIEW model_edges AS
  SELECT
    model_id,
    'lineage_fk'  AS edge_source,
    edge_kind     AS relationship_type,
    NULL::VARCHAR AS license_status,
    target_id,
    NULL::VARCHAR AS target_label,
    * EXCLUDE (model_id, edge_kind, target_id)
  FROM model_lineage
  UNION ALL
  SELECT
    model_id,
    'relationship' AS edge_source,
    relationship_type,
    license_status,
    target_id,
    target_label,
    * EXCLUDE (model_id, relationship_type, license_status, target_id, target_label)
  FROM model_relationships;

-- title_size — one row per Title with a live model: its identity (title_slug/
-- title_name) plus n, the count of LIVE models in it (the "alone in its Title?"
-- signal — n = 1). A soft-deleted sibling doesn't keep a model company. Carries the
-- same identity as models.title_* so a title-keyed query needn't bounce back to it.
CREATE OR REPLACE VIEW title_size AS
  SELECT m.title_id, t.slug AS title_slug, t.name AS title_name, count(*) AS n
  FROM models m
  LEFT JOIN fc.catalog_title t ON t.id = m.title_id
  GROUP BY m.title_id, t.slug, t.name;

-- analysis_context — the input watermark for a run. Enough identity to tell
-- "same query, newer catalog" apart from a broken reproduction. It does NOT
-- freeze the DB: a query is reproducible, but its RESULTS are only reproducible
-- when this row also matches. Every runner prints it above the results.
--   migrations_applied / latest_migration : the schema point. count + newest name,
--       not the raw max(id) insertion sequence (which isn't a head or comparable).
--   latest_patch / patch_fingerprint : the newest SUCCESSFULLY-applied data patch
--       and its content hash — filtered to status='success' with a non-null
--       patch_id, so a failed/running/interactive ingest can't misreport it.
--   latest_changeset : catches interactive edits — the drift a patch id can't see.
CREATE OR REPLACE VIEW analysis_context AS
  SELECT
    version()                                    AS duckdb_version,
    (SELECT count(*) FROM models)                AS live_models,
    (SELECT count(*) FROM fc.django_migrations)  AS migrations_applied,
    (SELECT app || '.' || name FROM fc.django_migrations ORDER BY id DESC LIMIT 1) AS latest_migration,
    (SELECT patch_id FROM fc.provenance_ingestrun
       WHERE status = 'success' AND patch_id IS NOT NULL ORDER BY id DESC LIMIT 1) AS latest_patch,
    (SELECT input_fingerprint FROM fc.provenance_ingestrun
       WHERE status = 'success' AND patch_id IS NOT NULL ORDER BY id DESC LIMIT 1) AS patch_fingerprint,
    (SELECT max(id) FROM fc.provenance_changeset) AS latest_changeset;
