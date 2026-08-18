-- Catalog analysis foundation
--
-- README.md to do analysis; EDITING.md to change this file.
--
-- Conventions:
--   * `_underscore` = private, do not use to do analysis.
--   * Views omit soft-deleted records (RecordLifecycle.md); live means
--     `status IS DISTINCT FROM 'deleted'`, matching the read APIs.
--   * A dim or edge target is soft-deleted independently of its subject, so a dead one
--     DE-ENRICHES TO NULL rather than being reported as current; catalog_checks flags
--     every occurrence.
--   * Join on ids, predicate on ids or slugs, display the names — and what LEAVES the
--     session takes the slug.
--

-- Execution context: this file runs at snapshot BUILD time, inside the catalog the
-- runner is building (see `ensure_snapshot` in scripts/analysis/analysis). Three
-- schemas, all names CATALOG-RELATIVE — nothing here may ATTACH or name a catalog,
-- because the same files must load into the snapshot, a scratch copy or an in-memory
-- session unchanged:
--   raw  — the imported Django tables, already there before this runs. Reads nothing.
--   stg  — the staging views, created here. Read only raw.
--   main — the public surface (and its _underscore private helpers), the default.
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

-- ═══ ENTITY VOCABULARY — what this layer calls each kind of thing ═══════════
-- entity_registry (entity_type ↔ content-type label ↔ table), entity_subjects (the
-- polymorphic subject resolver) and entity_prose (the authored-prose corpus), GENERATED by
-- `manage.py export_entity_registry` (`make codegen`) — `machinemodel` → `model` is a
-- declaration on the model class, and SQL cannot iterate table names.
.read scripts/analysis/sql/entity_registry.sql

-- Key on the physical table, not the public spelling: a view emitting a subject type has
-- already joined that table, while the spelling can move under it.
CREATE OR REPLACE MACRO _entity_type_of(physical_table) AS
  (SELECT entity_type FROM entity_registry WHERE db_table = physical_table);
COMMENT ON MACRO _entity_type_of IS
  '_entity_type_of(''catalog_series'') — the subject type a view should emit for rows of that physical table, read from entity_registry rather than spelled as a literal. NULL if the table is not an entity.';

-- ═══ §200 NAME NORMALIZATION — comparing names across records ═══════════════
-- The key for comparing a catalog name against another record's — a source's game title,
-- a sibling model, an alias. Split so an analysis picks the JUDGMENT deliberately:
-- name_norm is mechanical, name_strip_paren is a judgment, name_key composes both.
-- Matching STRATEGY — plural collapsing, stopwords, token subsets, edit distance — is
-- tuned to a corpus and belongs to the analysis that needs it.

-- Two limits: ordinal indicators survive as letters ('1ª División' -> '1ª division', so a
-- source writing '1a' won't match), and strip_accents folds Japanese dakuten (バ and パ
-- onto ハ), so distinct kana can share a key.
CREATE OR REPLACE MACRO name_norm(s) AS
  trim(regexp_replace(lower(strip_accents(COALESCE(s, ''))), '[^\p{L}\p{N}]+', ' ', 'g'));
COMMENT ON MACRO name_norm IS
  'Normalized name key: fold Latin diacritics, lowercase, collapse every run of non-letter/non-digit to one space. Unicode-aware, so a non-Latin name never collapses to the empty string.';

CREATE OR REPLACE MACRO name_strip_paren(s) AS
  regexp_replace(COALESCE(s, ''), '\s*\([^()]*\)\s*$', '', 'g');
COMMENT ON MACRO name_strip_paren IS
  'Drop ONE trailing parenthetical — On Beam (Italy) -> On Beam. Cuts both ways: it also collapses KISS (Limited Edition) onto KISS, so record whether a match needed it.';

CREATE OR REPLACE MACRO name_key(s) AS name_norm(name_strip_paren(s));
COMMENT ON MACRO name_key IS
  'name_norm(name_strip_paren(s)) — the name comparison key for the common case. Use name_norm alone when a trailing parenthetical distinguishes the records.';

-- ═══ §80 DIMENSIONS — what a model points at ════════════════════════════════
-- locations — one row per live geographic Location.
--   location_path : the stable key ('usa/il/chicago') and the one to join on. `slug` is
--             unique only WITHIN a parent — there is more than one 'victoria' in the
--             world — so a join on slug silently merges places. The path is also the
--             hierarchy: country_slug is its first segment, and a place's descendants are
--             the rows whose path starts with its path plus '/'.
--   location_type : an OPEN vocabulary, not a 3-level ladder — country, state, province,
--             department, community, region, prefecture, constituent_country, district,
--             city. Only `country` is structurally guaranteed (exactly the parentless
--             rows), so an analysis assuming country/state/city silently drops the live
--             places that are none of those. Predicate on path depth when you mean depth.
--   code / short_name / divisions : sparse by construction, each carried at one level —
--             `code` is the subdivision's own code (VIC, WA), `divisions` names how a
--             country subdivides, `short_name` is rarer still.
CREATE OR REPLACE VIEW locations AS
  SELECT
    l.*,
    split_part(l.location_path, '/', 1)      AS country_slug,
    l.parent_id IS NULL                      AS is_country
  FROM _staging('raw.catalog_location') l;
COMMENT ON VIEW locations IS
  'One row per live Location at EVERY level — THE entity; a country is just a row with is_country. Join on location_path, never slug: slug is unique only within a parent.';

-- corporate_entity_locations — one row per (live corporate entity, live location) it is
-- based in. The bridge is owned by CorporateEntity, so the count of CEs per location lives
-- here rather than on `locations`: GROUP BY location_id for it.
CREATE OR REPLACE VIEW corporate_entity_locations AS
  SELECT
    cel.corporate_entity_id,
    ce.slug          AS corporate_entity_slug,
    l.id             AS location_id,
    l.location_path,
    l.country_slug,
    l.is_country
  FROM raw.catalog_corporateentitylocation cel
  JOIN locations l ON l.id = cel.location_id
  JOIN stg.corporate_entity ce ON ce.id = cel.corporate_entity_id;
COMMENT ON VIEW corporate_entity_locations IS
  'One row per (live corporate entity, live location) — THE CE-to-Location bridge and the only reader of the through table; group by location_id for corporate entities per place.';

-- location_aliases — every alias of every live Location: countries, regions and cities.
-- Keyed on location_path, not slug (see `locations`). Filter is_country for the country slice.
CREATE OR REPLACE VIEW location_aliases AS
  SELECT
    la.location_id,
    l.location_path,
    l.country_slug,
    l.is_country,
    la.value AS alias
  FROM raw.catalog_locationalias la
  JOIN locations l ON l.id = la.location_id;
COMMENT ON VIEW location_aliases IS
  'One row per alias of a live Location at any level — alias GRAIN, keyed on location_path because Location.slug is unique only within a parent. Filter is_country for countries.';

-- game_formats — the machine-genre vocabulary.
CREATE OR REPLACE VIEW game_formats AS SELECT * FROM _staging('raw.catalog_gameformat');
COMMENT ON VIEW game_formats IS
  'One row per live game format — the machine-genre vocabulary';

-- ─── Taxonomy dims, at entity grain ─────────────────────────────────────────
-- One view per taxonomy dim, for questions about the VOCABULARY itself — `models` carries
-- only the slug, which is all a model row needs to predicate and group on.
-- Uniform shape: id, slug, name, description, plus the decoded parent where the dim has one.
CREATE OR REPLACE VIEW technology_generations AS SELECT * FROM _staging('raw.catalog_technologygeneration');
COMMENT ON VIEW technology_generations IS
  'One row per live technology generation — the major-era vocabulary (Electromechanical, Solid State).';

CREATE OR REPLACE VIEW technology_subgenerations AS
  SELECT
    tsg.*,
    tg.slug AS technology_generation_slug
  FROM _staging('raw.catalog_technologysubgeneration') tsg
  LEFT JOIN technology_generations tg ON tg.id = tsg.technology_generation_id;
COMMENT ON VIEW technology_subgenerations IS
  'One row per live technology subgeneration — the subdivision vocabulary, carrying its parent generation decoded to a slug.';

CREATE OR REPLACE VIEW display_types AS SELECT * FROM _staging('raw.catalog_displaytype');
COMMENT ON VIEW display_types IS
  'One row per live display type — the display-technology vocabulary (Score Reels, DMD, LCD).';

CREATE OR REPLACE VIEW display_subtypes AS
  SELECT
    dst.*,
    dt.slug AS display_type_slug
  FROM _staging('raw.catalog_displaysubtype') dst
  LEFT JOIN display_types dt ON dt.id = dst.display_type_id;
COMMENT ON VIEW display_subtypes IS
  'One row per live display subtype — the subdivision vocabulary, carrying its parent display type decoded to a slug.';

-- The one dim whose name the slug mangles (`Bally AS-2518-35`), so `models` carries
-- system_name alongside system_slug.
CREATE OR REPLACE VIEW systems AS
  SELECT
    s.*,
    mf.slug AS manufacturer_slug, mf.name AS manufacturer_name,
    tsg.slug AS technology_subgeneration_slug
  FROM _staging('raw.catalog_system') s
  LEFT JOIN stg.manufacturer mf ON mf.id = s.manufacturer_id
  LEFT JOIN technology_subgenerations tsg ON tsg.id = s.technology_subgeneration_id
;
COMMENT ON VIEW systems IS
  'One row per live system — the hardware-generation vocabulary (WPC-95, SAM, SPIKE) with its manufacturer and technology subgeneration decoded.';

CREATE OR REPLACE VIEW cabinets AS SELECT * FROM _staging('raw.catalog_cabinet');
COMMENT ON VIEW cabinets IS
  'One row per live cabinet — the form-factor vocabulary (floor, countertop, cocktail).';

-- production_statuses is the ProductionStatus vocabulary, NOT soft-delete status
CREATE OR REPLACE VIEW production_statuses AS SELECT * FROM _staging('raw.catalog_productionstatus');
COMMENT ON VIEW production_statuses IS
  'One row per live production status — the commercial-production vocabulary (produced, announced, one-off).';

-- ═══ §10 MODELS ═════════════════════════════════════
-- _ce_location — the manufacturer's home location per corporate entity, collapsed to ONE
-- row per CE so joining it can't fan out the one-row-per-model grain. CorporateEntityLocation
-- is 1:N, but every CE has exactly one location today; ce_multi_location fires if that stops.
CREATE OR REPLACE VIEW _ce_location AS
  SELECT
    corporate_entity_id,
    min(location_path)                            AS location_path,
    -- min_by, not min: reads country_slug off the SAME row min(location_path) picks, so a
    -- CE that ever carries two locations can't quietly report a mix of the two.
    min_by(country_slug, location_path)           AS country_slug
  FROM corporate_entity_locations
  GROUP BY corporate_entity_id;

-- _title_live_n — live models per Title. Reads the staging layer because `models` consumes
-- it, so reading `models` would be circular.
-- The single source for `models.title_size` here AND `titles.n_models` further down, so
-- changing the grain or the name moves both, plus the checks that compare them.
CREATE OR REPLACE VIEW _title_live_n AS
  SELECT title_id, count(*) AS n
  FROM stg.machine_model
  GROUP BY title_id;

-- _namesake_live_n — live models per name_key, staging-layer read for the same reason.
CREATE OR REPLACE VIEW _namesake_live_n AS
  SELECT name_key(name) AS name_key, count(*) AS n
  FROM stg.machine_model
  GROUP BY name_key(name);

-- models — one row per LIVE MachineModel. `analysis describe models` prints
-- the full column list; these notes cover only what ISN'T obvious.
--   title_* : the model's Title — the spine of the hierarchy; every model has one.
--   title_size : LIVE models sharing this model's Title, itself included — so >= 1, and
--             `title_size = 1` is "alone in its Title". The model-keyed `titles.n_models`.
--   namesake_count : LIVE models sharing this model's `name_key`, itself included. 1 means
--             unique; > 1 is ambiguous and needs another signal. Trailing-parenthetical
--             variants count together. README.md#matching-source-records-to-models.
--   manufacturer_model_identifier : the MANUFACTURER's own model number (Gottlieb '654',
--             Stern 'PINBALL I-00M1 * JURAS. PARK PRO'). NOT unique, and NOT unique paired
--             with manufacturer_id either: makers number independently from 1, and the
--             catalog splits finer than they numbered, so one number spans several models
--             — within a Title (Gottlieb 409 = Cleopatra + Cleopatra (EM)) or across them
--             for a re-theme family (Williams 394 = Zodiac + Planets). Some collisions are
--             just bad data (Bally 868 = Safari 1969 + Mysterian 1982). GROUP BY
--             (manufacturer_id, identifier) before treating it as an identity, or use
--             `model_number_collisions`. NULL on most live models.
--   year / month : a precision ladder — a NULL month is "dated to the year", never a month
--             lost from a fuller date (`catalog_machinemodel_month_requires_year`). Nothing
--             above the year is modelled, so a named quarter or season arrives as a month
--             or as nothing.
--   production_quantity : TEXT, not a number, and nothing validates it — TRY_CAST for
--             arithmetic and keep the NULLs it produces. Blank is unknown, not zero.
--   manufacturer : manufacturer_name is the canonical name on the cabinet — display and
--             group by it.
--   location: where the MANUFACTURER was based (model -> corporate_entity -> location).
--             Its ORIGIN, not an export-market destination — those are
--             `model_export_markets`. location_path ('usa/il/chicago') is the most-specific
--             known place and the stable key; country_slug ('usa') is its root, the field
--             to join and group by (-> locations, is_country, for the name).
--   game_format_*   : machine genre, id/slug, NULL if untyped; `game_formats` has the name.
--   taxonomy dims   : technology_generation / technology_subgeneration, display_type /
--             display_subtype, system, cabinet, production_status — SLUG ONLY (DomainModel
--             "Taxonomy & Classification"), the slug being both the readable label and the
--             join key back to raw.catalog_<dim>. `system` also keeps system_name, which the
--             slug mangles. production_status is the ProductionStatus FK, NOT the
--             soft-delete `status`. The subgeneration/subtype dims are mostly NULL today.
--   variant_of_id / remake_of_id / export_edition_of_id : bare self-FKs to the origin
--             model. Resolving the far end is `model_lineage`'s job — join it on model_id
--             and edge_kind, then read target_slug.
--   source free-text : ipdb_notes, ipdb_notable_features, ipdb_toys,
--             ipdb_marketing_slogans (prose) and opdb_features (VARCHAR[], empty never
--             NULL; 'Export edition', 'Cocktail', …) — source fields the product doesn't
--             surface. The prose ones are sparse: NULL is a fact about source coverage.
--   NOT surfaced : the extra_data long tail (opdb.keywords — use `model_themes` —
--             opdb.common_name, opdb.description, …). EDITING.md to promote one.
--   label   : "Name (Manufacturer Year)", CE name then '?' as fallbacks; year omitted if
--             unknown.
CREATE OR REPLACE VIEW models AS
  SELECT
    -- `m.*` rather than a column list, so a new field on the Django model surfaces here on
    -- its own and the only way one stays out is an EXCLUDE entry saying why.
    m.* EXCLUDE (
      ipdb_rating,      -- third-party ratings: not ours to republish, and not wanted
      pinside_rating,
      flipper_count     -- near-empty scalar; model_gameplay_features.count is the signal
    ),
    t.slug AS title_slug, t.name AS title_name,
    COALESCE(tn.n, 0) AS title_size,
    COALESCE(nk.n, 0) AS namesake_count,
    ce.slug AS corporate_entity_slug,
    ce.manufacturer_id, mf.slug AS manufacturer_slug, mf.name AS manufacturer_name,
    cel.location_path, cel.country_slug,
    gf.slug AS game_format_slug,
    tg.slug  AS technology_generation_slug,
    tsg.slug AS technology_subgeneration_slug,
    dt.slug  AS display_type_slug,
    dst.slug AS display_subtype_slug,
    sys.slug AS system_slug,   sys.name AS system_name,
    cab.slug AS cabinet_slug,
    ps.slug  AS production_status_slug,
    json_extract_string(m.extra_data, '$."ipdb.notes"')             AS ipdb_notes,
    json_extract_string(m.extra_data, '$."ipdb.notable_features"')  AS ipdb_notable_features,
    json_extract_string(m.extra_data, '$."ipdb.toys"')              AS ipdb_toys,
    json_extract_string(m.extra_data, '$."ipdb.marketing_slogans"') AS ipdb_marketing_slogans,
    COALESCE(json_extract(m.extra_data, '$."opdb.features"')::VARCHAR[], []::VARCHAR[]) AS opdb_features,
    m.name || ' ('
      || COALESCE(NULLIF(mf.name, ''), NULLIF(ce.name, ''), '?')
      || COALESCE(' ' || m.year::VARCHAR, '')
      || ')' AS label
  FROM stg.machine_model m
  LEFT JOIN stg.title t              ON t.id  = m.title_id
  LEFT JOIN _title_live_n tn           ON tn.title_id = m.title_id
  LEFT JOIN _namesake_live_n nk        ON nk.name_key = name_key(m.name)
  LEFT JOIN stg.corporate_entity ce  ON ce.id = m.corporate_entity_id
  LEFT JOIN stg.manufacturer mf      ON mf.id = ce.manufacturer_id
  LEFT JOIN _ce_location cel           ON cel.corporate_entity_id = m.corporate_entity_id
  LEFT JOIN game_formats               gf  ON gf.id  = m.game_format_id
  LEFT JOIN technology_generations     tg  ON tg.id  = m.technology_generation_id
  LEFT JOIN technology_subgenerations  tsg ON tsg.id = m.technology_subgeneration_id
  LEFT JOIN display_types              dt  ON dt.id  = m.display_type_id
  LEFT JOIN display_subtypes           dst ON dst.id = m.display_subtype_id
  LEFT JOIN systems                    sys ON sys.id = m.system_id
  LEFT JOIN cabinets                   cab ON cab.id = m.cabinet_id
  LEFT JOIN production_statuses        ps  ON ps.id  = m.production_status_id;
COMMENT ON VIEW models IS
  'One row per LIVE MachineModel — THE spine; build analyses on this. Soft-deleted models are not here and are not anywhere: read `claims` for the history of one.';

-- ═══ §40 MANUFACTURERS AND CORPORATE ENTITIES ═══════════════════════════════
-- presumed_producing — the still-producing verdict the SITE publishes, which is not
-- operating_status alone: an 'unknown' subject with a recent model reads as producing
-- ("1990–present"), one without reads as closed. The window is a product fact
-- (UNKNOWN_RECENCY_YEARS in frontend/src/lib/utils.ts). Not stable across runs — it moves
-- with the calendar.
CREATE OR REPLACE MACRO presumed_producing(operating_status, year_of_last_model) AS
  operating_status = 'ongoing'
  OR (operating_status = 'unknown'
      AND year_of_last_model IS NOT NULL
      AND year_of_last_model > year(current_date) - 6);
COMMENT ON MACRO presumed_producing IS
  'The site''s still-producing verdict: ongoing, or unknown with a model inside the 6-year recency window (frontend UNKNOWN_RECENCY_YEARS). False is not ended — see manufacturers.';

-- _mfr_status — OperatingStatus.rollup over a manufacturer's live corporate entities,
-- precedence ONGOING > UNKNOWN > ENDED. Read it through manufacturers.operating_status.
-- No CE at all rolls up to unknown, never ended: empty bool_and is NULL, so the ELSE
-- catches it, matching the backend.
CREATE OR REPLACE VIEW _mfr_status AS
  SELECT manufacturer_id,
         CASE WHEN bool_or(operating_status = 'ongoing') THEN 'ongoing'
              WHEN bool_and(operating_status = 'ended')  THEN 'ended'
              ELSE 'unknown' END AS operating_status
  FROM stg.corporate_entity
  WHERE manufacturer_id IS NOT NULL
  GROUP BY manufacturer_id;

-- _mfr_location — a manufacturer's place rolled up over its LIVE corporate entities, at
-- both rungs. Read it through manufacturers.location_path / country_slug.
-- Rolled up from the CEs, not from `models`: a location is a fact about the COMPANY, so a
-- maker whose models are all gone or not yet seeded still reports the address its CEs
-- carry. DISTINCT ignores NULL, so a CE with no location lowers neither count.
CREATE OR REPLACE VIEW _mfr_location AS
  SELECT ce.manufacturer_id,
         count(DISTINCT cel.location_path)  AS n_locations,
         CASE WHEN count(DISTINCT cel.location_path) = 1
              THEN min(cel.location_path) END AS location_path,
         count(DISTINCT cel.country_slug)   AS n_countries,
         CASE WHEN count(DISTINCT cel.country_slug) = 1
              THEN min(cel.country_slug) END  AS country_slug
  FROM stg.corporate_entity ce
  LEFT JOIN _ce_location cel ON cel.corporate_entity_id = ce.id
  WHERE ce.manufacturer_id IS NOT NULL
  GROUP BY ce.manufacturer_id;

-- corporate_entities — one row per live CorporateEntity: the LEGAL entity one level
-- below the manufacturer, the grain `models.corporate_entity_id` actually points at.
-- Reach for it when the question is about a corporate incarnation (D. Gottlieb &
-- Company vs Premier Technology) rather than about the manufacturer you display.
--
--   year_of_first_model / year_of_last_model, and the n_* counts : exactly as on
--                 `manufacturers`, scoped to the one entity.
--   operating_status / presumed_producing : the stored column for the ONE incarnation, not
--                 a rollup — ask `manufacturers` unless the incarnation is the subject.
--                 UNKNOWN IS THE COLUMN DEFAULT, so counting 'ended' is sound and reading
--                 anything into the size of the 'unknown' bucket is not.
--   location_path / country_slug : this incarnation's own place, spelled as on `models`.
--                 The grain to use when a manufacturer spans places — `manufacturers`
--                 collapses those to NULL, while this view keeps each CE's separate.
--                 Both NULL when the CE carries no location, a common state.
--   ipdb_manufacturer_id : IPDB's ManufacturerId, the join key back to an IPDB scrape. It
--                 lives here and `opdb_manufacturer_id` on `manufacturers` because the two
--                 source databases split the manufacturer at different grains.
CREATE OR REPLACE VIEW corporate_entities AS
  WITH agg AS (
    SELECT
      corporate_entity_id,
      count(*)                                    AS n_models,
      count(*) FILTER (variant_of_id IS NULL)     AS n_nonvariant_models,
      count(year) FILTER (variant_of_id IS NULL)  AS n_dated,
      min(year) FILTER (variant_of_id IS NULL)    AS year_of_first_model,
      max(year) FILTER (variant_of_id IS NULL)    AS year_of_last_model
    FROM models WHERE corporate_entity_id IS NOT NULL
    GROUP BY corporate_entity_id
  )
  SELECT
    ce.* EXCLUDE (
      -- "DEAD FIELD — do not read or write" on the Django model: a company can incorporate
      -- years before its first machine and linger years after its last. Surfacing them
      -- beside year_of_first_model/year_of_last_model, which they disagree with on most
      -- entities, would be worse than not having them at all.
      year_start,
      year_end
    ),
    mf.slug AS manufacturer_slug, mf.name AS manufacturer_name,
    presumed_producing(ce.operating_status, a.year_of_last_model) AS presumed_producing,
    cel.location_path, cel.country_slug,
    COALESCE(a.n_models, 0)            AS n_models,
    COALESCE(a.n_nonvariant_models, 0) AS n_nonvariant_models,
    COALESCE(a.n_dated, 0)             AS n_dated,
    a.year_of_first_model, a.year_of_last_model
  FROM stg.corporate_entity ce
  LEFT JOIN stg.manufacturer mf ON mf.id = ce.manufacturer_id
  LEFT JOIN _ce_location cel ON cel.corporate_entity_id = ce.id
  LEFT JOIN agg a            ON a.corporate_entity_id = ce.id;
COMMENT ON VIEW corporate_entities IS
  'One row per live corporate entity — the LEGAL entity below the manufacturer, with the same derived span, counts, location and producing verdict as manufacturers, scoped to the one incarnation. operating_status defaults to unknown, so that bucket means unasked, not unknowable.';

-- manufacturers — one row per live manufacturer: identity, where it was based, how much it
-- made and WHEN. The span columns matter because a MODEL with no year often has its
-- manufacturer's span as the only evidence available.
--
-- Grain: the physical chain is model -> CorporateEntity -> Manufacturer, and a manufacturer
-- can own more than one CE. This is the MANUFACTURER level, the name on the cabinet; drop
-- to models.corporate_entity_* for the legal entity.
--
--   n_models    : live models attributed here, VARIANTS INCLUDED. 0 is normal — the
--                 catalog carries manufacturers with no models yet.
--   n_nonvariant_models : the same count with variants excluded — what
--                 /api/export/manufacturers/ publishes as `model_count`.
--   n_dated     : non-variant models carrying a year — THE denominator for the year pair:
--                 a span resting on 2 models is not the claim a span resting on 40 is.
--   year_of_first_model / year_of_last_model : min/max year over those models, published
--                 under these names by /api/export/manufacturers/. NO minimum applied, so
--                 the caller sets its own bar (`WHERE n_dated >= 3`). Gaps are invisible —
--                 active 1932-1935 and again 1975-1979 reads as a 47-year span, so treat
--                 it as an outer bound, not a continuous run.
--   operating_status / presumed_producing : the site's answer to "is this manufacturer
--                 still making pinball". operating_status is the rollup over its live CEs
--                 (ONGOING > UNKNOWN > ENDED), matching /api/export/manufacturers/;
--                 presumed_producing applies the recency macro to that rollup, which is not
--                 the same as asking whether any one CE qualifies — an entity marked ended
--                 can still carry the manufacturer's most recent model. FALSE IS NOT
--                 'ENDED': it pools the known-ended with the unknown-and-not-recent.
--   location_path / country_slug, with n_locations / n_countries : where the manufacturer
--                 was based, at both rungs (both spelled as on `models`). The rungs resolve
--                 INDEPENDENTLY, each NULL when its own disagrees — a maker with two
--                 Chicago-area plants is country_slug 'usa' and location_path NULL. Read
--                 location_path first and fall back to country.
--                 A NULL HAS TWO CAUSES AND THE COUNT SEPARATES THEM: n = 0 is no known
--                 location, n > 1 is a maker genuinely spanning places. Drop to
--                 `corporate_entities` to enumerate a plural maker's places.
--                 Rolled up over live CEs (_mfr_location), not over models like the counts
--                 beside them, so a maker with n_models = 0 still reports its CEs' address.
--   website / wikidata_id : the two outbound handles for enriching from outside the
--                 catalog. Both sparse, both absent as NULL.
CREATE OR REPLACE VIEW manufacturers AS
  -- Rolled up from `corporate_entities`, not recounted over `models`: a model reaches a
  -- manufacturer only through a CE, so recounting would be a second definition of the same
  -- five measures. The casts hold the published types — sum() widens where count() does not.
  WITH agg AS (
    SELECT
      manufacturer_id,
      sum(n_models)::BIGINT            AS n_models,
      sum(n_nonvariant_models)::BIGINT AS n_nonvariant_models,
      sum(n_dated)::BIGINT             AS n_dated,
      min(year_of_first_model)         AS year_of_first_model,
      max(year_of_last_model)          AS year_of_last_model
    FROM corporate_entities WHERE manufacturer_id IS NOT NULL
    GROUP BY manufacturer_id
  )
  SELECT
    mf.*,
    COALESCE(a.n_models, 0)            AS n_models,
    COALESCE(a.n_nonvariant_models, 0) AS n_nonvariant_models,
    COALESCE(a.n_dated, 0)             AS n_dated,
    a.year_of_first_model, a.year_of_last_model,
    COALESCE(s.operating_status, 'unknown')                            AS operating_status,
    presumed_producing(COALESCE(s.operating_status, 'unknown'),
                       a.year_of_last_model)                           AS presumed_producing,
    COALESCE(l.n_locations, 0) AS n_locations,
    l.location_path,
    COALESCE(l.n_countries, 0) AS n_countries,
    l.country_slug
  FROM stg.manufacturer mf
  LEFT JOIN agg a           ON a.manufacturer_id = mf.id
  LEFT JOIN _mfr_status s   ON s.manufacturer_id = mf.id
  LEFT JOIN _mfr_location l ON l.manufacturer_id = mf.id;
COMMENT ON VIEW manufacturers IS
  'One row per live manufacturer — identity, home location/country, model counts, the year_of_first_model/year_of_last_model span and the site''s operating_status/presumed_producing verdict. Read location and country each with its n_ count (0 = unknown, >1 = plural), and the span with n_dated.';

-- ═══ §60 REWARDS, THEMES, TAGS — model attributes ═══════════════════════════
-- model_rewards — one row per (live model, live reward type), and the only reader of the
-- through table. Reward types are MULTI-VALUED — a machine can pay out several — so they
-- get a grain view rather than a slug column on `models` like the single-FK dims.
CREATE OR REPLACE VIEW model_rewards AS
  SELECT mr.machinemodel_id AS model_id, s.slug AS model_slug,
         rt.id AS reward_type_id, rt.slug AS reward_type_slug
  FROM raw.catalog_machinemodel_reward_types mr
  JOIN stg.reward_type rt ON rt.id = mr.rewardtype_id
  JOIN models s ON s.id = mr.machinemodel_id;
COMMENT ON VIEW model_rewards IS
  'One row per (live model, live reward type) — the grain twin of model_reward_names; predicate and join on reward_type_slug. Flat, no DAG.';

-- reward_types — what a machine pays out: the VOCABULARY, with `n` the live-model usage
-- count as on the other multi-valued vocabularies.
CREATE OR REPLACE VIEW reward_types AS
  SELECT rt.*, count(mr.model_id) AS n
  FROM stg.reward_type rt
  LEFT JOIN model_rewards mr ON mr.reward_type_id = rt.id
  GROUP BY ALL;
COMMENT ON VIEW reward_types IS
  'One row per live reward type — the payout VOCABULARY with usage count n; join reward_type_aliases to resolve a source phrasing into it.';

-- model_reward_names — sorted reward-type names per live model (only models that have
-- any), keyed model_id.
CREATE OR REPLACE VIEW model_reward_names AS
  SELECT mr.model_id, list_sort(list(rt.name)) AS reward_names
  FROM model_rewards mr
  JOIN stg.reward_type rt ON rt.id = mr.reward_type_id
  GROUP BY mr.model_id;
COMMENT ON VIEW model_reward_names IS
  'One row per LIVE model with any — sorted reward-type NAMES for display, keyed model_id. Pure enrichment; carries no reward-type ids or slugs.';

-- ─── Theme vocabulary ───────────────────────────────────────────────────────
-- Four views per multi-valued vocabulary, the gameplay-feature block below mirroring them:
--   model_<terms>       slug-keyed model↔term grain — the only reader of the through table
--   <term>_aliases      alias GRAIN, so you can join and compare on an alias
--   <terms>             one row per live term — identity, usage count, DAG, aliases
--   model_<term>_names  the flattened display list, built from the grain
-- Defined in that order: the vocabulary counts the grain and flattens the aliases.

-- model_themes — one row per (live model, live theme); the display name is in themes.
-- Direct attachments ONLY, DAG not rolled up: a model tagged `black-magic` does NOT gain
-- `occult`. Resolve ancestors analysis-locally via themes.parents.
CREATE OR REPLACE VIEW model_themes AS
  SELECT mt.machinemodel_id AS model_id, s.slug AS model_slug,
         t.id AS theme_id, t.slug AS theme_slug
  FROM raw.catalog_machinemodel_themes mt
  JOIN stg.theme t ON t.id = mt.theme_id
  JOIN models s ON s.id = mt.machinemodel_id;
COMMENT ON VIEW model_themes IS
  'One row per (live model, live theme) — the grain twin of model_theme_names; predicate and join on theme_slug. Direct attachments only, DAG not rolled up.';

-- theme_aliases — one row per alias of a live theme. GRAIN rather than the flat list in
-- themes.aliases, because consumers join and compare on an alias — an alias colliding with
-- a live theme's own name is this corpus's dominant defect.
CREATE OR REPLACE VIEW theme_aliases AS
  SELECT ta.theme_id, t.slug AS theme_slug, ta.value AS alias
  FROM raw.catalog_themealias ta
  JOIN stg.theme t ON t.id = ta.theme_id;
COMMENT ON VIEW theme_aliases IS
  'One row per alias of a live theme — alias GRAIN, so you can join and compare on one. Values as entered, not normalized.';

-- themes — one row per live theme: the vocabulary itself.
--   n        : LIVE-model usage count; 0 for an unused theme, which is a kept row.
--   parents  : slugs this theme hangs under (a DAG, so several are possible); [] for a
--              root, which much of this corpus is.
--   children : the inverse, off the same table so the two can't disagree.
--   aliases  : alias VALUES flattened for display; use theme_aliases to join on one.
-- Live on BOTH ends of the DAG, and DIRECT edges only — no transitive closure; a caller
-- wanting every descendant writes the recursive CTE analysis-locally.
CREATE OR REPLACE VIEW themes AS
  WITH usage AS (
    SELECT theme_id, count(*) AS n FROM model_themes GROUP BY theme_id
  ), parents AS (
    SELECT tp.from_theme_id AS theme_id, list_sort(list(p.slug)) AS parents
    FROM raw.catalog_theme_parents tp
    JOIN stg.theme p ON p.id = tp.to_theme_id
    GROUP BY tp.from_theme_id
  ), children AS (
    SELECT tp.to_theme_id AS theme_id, list_sort(list(c.slug)) AS children
    FROM raw.catalog_theme_parents tp
    JOIN stg.theme c ON c.id = tp.from_theme_id
    GROUP BY tp.to_theme_id
  ), aliases AS (
    SELECT theme_id, list_sort(list(alias)) AS aliases FROM theme_aliases GROUP BY theme_id
  )
  SELECT
    t.*,
    COALESCE(u.n, 0)                  AS n,
    COALESCE(p.parents,  []::VARCHAR[]) AS parents,
    COALESCE(c.children, []::VARCHAR[]) AS children,
    COALESCE(a.aliases,  []::VARCHAR[]) AS aliases
  FROM stg.theme t
  LEFT JOIN usage    u ON u.theme_id = t.id
  LEFT JOIN parents  p ON p.theme_id = t.id
  LEFT JOIN children c ON c.theme_id = t.id
  LEFT JOIN aliases  a ON a.theme_id = t.id;
COMMENT ON VIEW themes IS
  'One row per live theme — the theme VOCABULARY: usage count n, DAG parents/children, aliases. Reach for it when the subject is the themes rather than the models.';

-- model_theme_names — sorted theme names per live model (only models that have any).
-- Display only: no id, no slug, no DAG.
CREATE OR REPLACE VIEW model_theme_names AS
  SELECT mt.model_id, list_sort(list(t.name)) AS theme_names
  FROM model_themes mt
  JOIN stg.theme t ON t.id = mt.theme_id
  GROUP BY mt.model_id;
COMMENT ON VIEW model_theme_names IS
  'One row per LIVE model with any — sorted theme NAMES for display, keyed model_id. Use model_themes to predicate on a theme, themes for questions about the vocabulary itself.';

-- The only reader of the tag through table.
CREATE OR REPLACE VIEW model_tags AS
  SELECT mt.machinemodel_id AS model_id, s.slug AS model_slug,
         tg.id AS tag_id, tg.slug AS tag_slug
  FROM raw.catalog_machinemodel_tags mt
  JOIN stg.tag tg ON tg.id = mt.tag_id
  JOIN models s ON s.id = mt.machinemodel_id;
COMMENT ON VIEW model_tags IS
  'One row per (live model, live tag) — the grain twin of model_tag_slugs; predicate and join on tag_slug. Flat, no DAG.';

-- Much of the tag vocabulary is soft-deleted, so check a hardcoded slug against this view
-- before trusting it.
CREATE OR REPLACE VIEW tags AS
  SELECT
    tg.*,
    count(mt.model_id) AS n
  FROM stg.tag tg
  LEFT JOIN model_tags mt ON mt.tag_id = tg.id
  GROUP BY ALL;
COMMENT ON VIEW tags IS
  'One row per live tag — the tag VOCABULARY with usage count n, the entity twin of the model-keyed tag list. Flat, no DAG.';

-- model_tag_slugs — sorted TAG SLUGS per tagged live model (only models with any), keyed
-- model_id. Slugs, not names, because tags are the vocabulary you PREDICATE on
-- (`'widebody' IN tag_slugs`). `conversion_kit` and re-themes are ModelRelationship types,
-- not tags, and won't appear here.
CREATE OR REPLACE VIEW model_tag_slugs AS
  SELECT model_id, list_sort(list(tag_slug)) AS tag_slugs
  FROM model_tags
  GROUP BY model_id;
COMMENT ON VIEW model_tag_slugs IS
  'One row per tagged LIVE model — sorted list of tag SLUGS (the stable key you predicate on), keyed model_id. conversion_kit and re-themes are ModelRelationship types, not tags.';

-- ═══ §70 GAMEPLAY FEATURES ══════════════════════════════════════════════════
-- model_gameplay_features — one row per (model, directly-attached gameplay feature) with
-- its optional count. No display-list twin, unlike the other attribute families: most of
-- these rows carry a count and most of those exceed 1 (Flippers x2; Trap Holes x25, the
-- 5x5 bingo card), so a flat name list would drop the payload and read as a confident
-- wrong answer.
-- Direct attachments ONLY: the GameplayFeature DAG (2-Ball Multiball under Multiball) is
-- NOT rolled up — resolve parents analysis-locally, as with themes. Predicate and display
-- on feature_slug ('trap-holes', 'flippers'); feature_name is not surfaced.
--   count : the M2M's optional count, NULL for a bare membership. The real "how many
--           flippers" signal — the raw scalar flipper_count is near-empty and not surfaced.
CREATE OR REPLACE VIEW model_gameplay_features AS
  SELECT
    mgf.machinemodel_id AS model_id,
    s.slug              AS model_slug,
    gf.id               AS feature_id,
    gf.slug             AS feature_slug,
    mgf.count           AS count
  FROM raw.catalog_machinemodelgameplayfeature mgf
  JOIN stg.gameplay_feature gf ON gf.id = mgf.gameplayfeature_id
  JOIN models s ON s.id = mgf.machinemodel_id;
COMMENT ON VIEW model_gameplay_features IS
  'One row per (live model, gameplay feature) with its optional count (Flippers x2, Trap Holes x25) — the counted grain. Direct attachments only, DAG not rolled up.';

-- ─── Gameplay-feature vocabulary ────────────────────────────────────────────
-- The theme block's mirror; `model_gameplay_features` is already the grain, so only the
-- vocabulary and its alias grain are new.
-- The difference from themes is DEPTH: this DAG is genuinely deep — kickback-lanes →
-- right-kickback-lanes → upper-right-kickback-lanes — with interior nodes that carry no
-- models by design.

-- gameplay_feature_aliases — one row per alias of a live feature, for resolving a source's
-- phrasing ("Autoplunger", "Left-Side Kickback Lane") to the canonical feature.
CREATE OR REPLACE VIEW gameplay_feature_aliases AS
  SELECT ga.feature_id, f.slug AS feature_slug, ga.value AS alias
  FROM raw.catalog_gameplayfeaturealias ga
  JOIN stg.gameplay_feature f ON f.id = ga.feature_id;
COMMENT ON VIEW gameplay_feature_aliases IS
  'One row per alias of a live gameplay feature — alias GRAIN, for resolving a source phrasing ("Autoplunger") to the canonical feature. Not normalized.';

-- gameplay_features — one row per live gameplay feature: the vocabulary itself.
-- Columns match themes exactly; two notes specific to this DAG:
--   n        : ALWAYS read WITH `children`. n = 0 on a leaf is an orphan or a detector gone
--              dark; n = 0 on a node with children is expected — the models hang off its
--              descendants.
--   parents  : several are possible — an Upper Right Ball Return Gate is both upper and
--              right-side.
CREATE OR REPLACE VIEW gameplay_features AS
  WITH usage AS (
    SELECT feature_id, count(*) AS n FROM model_gameplay_features GROUP BY feature_id
  ), parents AS (
    SELECT fp.from_gameplayfeature_id AS feature_id, list_sort(list(p.slug)) AS parents
    FROM raw.catalog_gameplayfeature_parents fp
    JOIN stg.gameplay_feature p ON p.id = fp.to_gameplayfeature_id
    GROUP BY fp.from_gameplayfeature_id
  ), children AS (
    SELECT fp.to_gameplayfeature_id AS feature_id, list_sort(list(c.slug)) AS children
    FROM raw.catalog_gameplayfeature_parents fp
    JOIN stg.gameplay_feature c ON c.id = fp.from_gameplayfeature_id
    GROUP BY fp.to_gameplayfeature_id
  ), aliases AS (
    SELECT feature_id, list_sort(list(alias)) AS aliases
    FROM gameplay_feature_aliases GROUP BY feature_id
  )
  SELECT
    f.id, f.slug, f.name, f.description,
    COALESCE(u.n, 0)                    AS n,
    COALESCE(p.parents,  []::VARCHAR[]) AS parents,
    COALESCE(c.children, []::VARCHAR[]) AS children,
    COALESCE(a.aliases,  []::VARCHAR[]) AS aliases
  FROM stg.gameplay_feature f
  LEFT JOIN usage    u ON u.feature_id = f.id
  LEFT JOIN parents  p ON p.feature_id = f.id
  LEFT JOIN children c ON c.feature_id = f.id
  LEFT JOIN aliases  a ON a.feature_id = f.id;
COMMENT ON VIEW gameplay_features IS
  'One row per live gameplay feature — the feature VOCABULARY, columns matching themes. Read n WITH children: n = 0 on an interior node is by design.';

-- ═══ §20 MODEL-TO-MODEL RELATIONSHIPS — start with model_edges ══════════════
-- `model_edges` is the DEFAULT — every edge out of a model, lineage + typed, so one
-- `WHERE model_id = ?` returns everything and no source is missed. Drop to a component
-- view when you want ONE mechanism:
--
--   model_lineage        single-valued structured self-FKs: variant_of, remake_of,
--                        export_edition_of. At most ONE of each per model; the target is
--                        always a resolved catalog model. Fixed semantics, no payload.
--   model_relationships  the multi-valued typed edge table (ModelRelationship): MANY per
--                        model, a CLOSED four-value type vocabulary (conversion,
--                        conversion_kit, copy, retheme — DB-enforced), a license_status,
--                        and a target that may be an unresolved free-text label instead of
--                        a catalog model.
--
-- All three follow ONE rule for the far end: an edge KEEPS its row and de-enriches to NULL
-- target_* rather than being dropped. The only LEGITIMATE de-enrich is a typed free-text
-- label (target_label, no catalog model). A resolved-but-de-enriched target (target_id set,
-- target_slug NULL) is a soft-deleted target the app should have protected — an integrity
-- violation catalog_checks flags, not a normal path.
-- model_edges CONCATENATES the two and does NOT reconcile overlaps: a variant_of FK and a
-- typed edge to the same target are two rows; deciding they're one is analysis-local.
-- ─────────────────────────────────────────────────────────────────────────────

-- _model_target — the far end of an edge: identity, year, genre, reward types, player
-- count, manufacturer and location, named target_* so both edge views pull the whole block
-- via `* EXCLUDE (id)`. Add a facet here and both gain it.
CREATE OR REPLACE VIEW _model_target AS
  SELECT
    m.id,
    m.slug                              AS target_slug,
    m.name                              AS target_name,
    m.manufacturer_model_identifier     AS target_manufacturer_model_identifier,
    m.year                              AS target_year,
    COALESCE(rw.reward_names, []::VARCHAR[]) AS target_reward_types,
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
  LEFT JOIN model_reward_names rw ON rw.model_id = m.id;

-- model_lineage — variant_of + remake_of + export_edition_of as row-grain edges: one row
-- per (model, edge_kind), 0..1 per kind. The target LEFT JOIN is defensive only — the app
-- blocks soft-deleting a live lineage target, so target_* always enriches here and a
-- de-enriched one means that protection was bypassed (lineage_target_not_live).
--   edge_kind : 'variant_of' | 'remake_of' | 'export_edition_of'
--   target_*  : the origin model — see _model_target
CREATE OR REPLACE VIEW model_lineage AS
  -- UNPIVOT drops NULL values, which is the 0..1-per-kind filter. edge_kind comes off the
  -- COLUMN NAME with `_id` stripped, so renaming a lineage FK renames the edge kind with
  -- it; lineage_kind_unknown is what says so.
  WITH edges AS (
    UNPIVOT (SELECT id AS model_id, slug AS model_slug,
                    variant_of_id, remake_of_id, export_edition_of_id
             FROM models)
    ON variant_of_id, remake_of_id, export_edition_of_id
    INTO NAME fk_column VALUE target_id
  )
  SELECT
    e.model_id,
    e.model_slug,
    regexp_replace(e.fk_column, '_id$', '') AS edge_kind,
    e.target_id,
    tgt.* EXCLUDE (id)
  FROM edges e
  LEFT JOIN _model_target tgt ON tgt.id = e.target_id;
COMMENT ON VIEW model_lineage IS
  'One row per (model, lineage edge) — the three single-valued self-FKs (variant_of, remake_of, export_edition_of) as row grain, target resolved. A component of model_edges.';

-- model_relationships — the typed ModelRelationship edge table, one row per edge.
-- Multi-valued (many per model), unlike model_lineage's single-valued self-FKs. The target
-- is EITHER a resolved catalog model (target_id set, target_* enriched) OR a free-text
-- label (target_label set, target_id NULL). Same target_* shape as model_lineage.
--   relationship_type : conversion | conversion_kit | copy | retheme — a CLOSED set
--                       (DB CHECK catalog_modelrelationship_type_valid)
--   license_status    : licensed | unlicensed | unknown — a CLOSED set
--                       (DB CHECK catalog_modelrelationship_license_status_valid)
--   target_label      : free-text origin when the donor isn't a catalog model
CREATE OR REPLACE VIEW model_relationships AS
  SELECT
    r.machine_model_id         AS model_id,
    s.slug                     AS model_slug,
    r.relationship_type,
    r.license_status,
    r.target_machine_id        AS target_id,
    NULLIF(r.target_label, '') AS target_label,
    tgt.* EXCLUDE (id)
  FROM raw.catalog_modelrelationship r
  JOIN models s ON s.id = r.machine_model_id
  LEFT JOIN _model_target tgt ON tgt.id = r.target_machine_id;  -- resolved target, if live
COMMENT ON VIEW model_relationships IS
  'One row per typed ModelRelationship edge — multi-valued, closed relationship_type and license_status vocabularies, target either a resolved model or a free-text label. A component of model_edges.';

-- model_export_markets — one row per export destination of a live model. NOT part of
-- model_edges: the target is a Location, not a model (the model↔model half of the export
-- story is the export_edition_of lineage FK). The target ladder is OPTIONAL — a country
-- (target_location_id + country columns), a free-text region label (target_label), or
-- neither, the unknown-market row whose existence alone says "built for export". The app
-- restricts location targets to countries, so a de-enriched one is an integrity violation
-- (export_market_target_not_country).
CREATE OR REPLACE VIEW model_export_markets AS
  SELECT
    em.machine_model_id                 AS model_id,
    s.slug                              AS model_slug,
    em.target_market_location_id        AS target_location_id,
    c.slug                              AS target_country_slug,
    c.name                              AS target_country_name,
    NULLIF(em.target_market_label, '')  AS target_label
  FROM raw.catalog_modelexportmarket em
  JOIN models s ON s.id = em.machine_model_id
  LEFT JOIN locations c ON c.id = em.target_market_location_id AND c.is_country;
COMMENT ON VIEW model_export_markets IS
  'One row per export destination of a live model — the target is a LOCATION, not a model, so this is NOT part of model_edges. The target ladder is optional: a country, a free-text region, or neither.';

-- model_edges — the DEFAULT relationships view: every edge out of a model, lineage and
-- typed, in one row-grain set. A UNION ALL over model_lineage + model_relationships.
--   edge_source       : 'lineage_fk' (variant_of/remake_of/export_edition_of)
--                       | 'relationship' (typed)
--   relationship_type : variant_of | remake_of | export_edition_of | conversion |
--                       conversion_kit | copy | retheme — lineage's edge_kind and the typed
--                       table's relationship_type unified: a CLOSED 7-value set.
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
  -- BY NAME, so reordering either projection can't silently misalign the shared
  -- _model_target block the two branches end in.
  UNION ALL BY NAME
  SELECT
    model_id,
    'relationship' AS edge_source,
    relationship_type,
    license_status,
    target_id,
    target_label,
    * EXCLUDE (model_id, relationship_type, license_status, target_id, target_label)
  FROM model_relationships;
COMMENT ON VIEW model_edges IS
  'One row per model edge, lineage + typed — THE DEFAULT relationships view, and OUTBOUND ONLY. For "is this pair connected?" use model_edges_bidir; hundreds of live models have only an inbound edge and are invisible here.';

-- model_edges_bidir — every edge from BOTH ends. `model_edges` is OUTBOUND ONLY: right for
-- "what does this model point at", silently wrong for "is this pair connected" — hundreds
-- of live models have an inbound edge and no outbound one, so a connectedness test written
-- against model_edges returns a confident false for every one of them. Use
-- `WHERE model_id = ? AND target_id = ?`, or `WHERE model_id = ?` for a model's full
-- neighbourhood in either direction.
--
-- The mirror does NOT re-point the edge: `relationship_type` always describes the edge AS
-- STATED, because the direction IS the fact — a variant points at its base, and the base is
-- not a variant of the variant. Read the type together with `direction`, and aggregate from
-- `model_edges`, never here, since every edge is counted twice by construction.
--   direction : 'out' (this model states the edge) | 'in' (the other end states it)
--   target_*  : always the FAR end from `model_id`, re-enriched per direction.
-- Label-only typed edges have no model at the far end, so they appear 'out' only.
CREATE OR REPLACE VIEW model_edges_bidir AS
  SELECT 'out' AS direction, * FROM model_edges
  UNION ALL BY NAME
  SELECT
    'in'                AS direction,
    e.target_id         AS model_id,
    e.target_slug       AS model_slug,
    e.edge_source,
    e.relationship_type,
    e.license_status,
    e.model_id          AS target_id,
    NULL::VARCHAR       AS target_label,
    t.* EXCLUDE (id)
  FROM model_edges e
  JOIN _model_target t ON t.id = e.model_id
  WHERE e.target_id IS NOT NULL;
COMMENT ON VIEW model_edges_bidir IS
  'Two rows per resolved edge, one per end — the CONNECTEDNESS view, with a direction column. relationship_type is always the edge AS STATED, so read it with direction. Never aggregate here: every edge is counted twice.';

-- ═══ §30 TITLES AND MODEL NUMBERS ═══════════════════════════════════════════
-- franchises / series — the two Title-grouping vocabularies at entity grain, for which
-- groupings EXIST and which are used by nothing. Both flat and both curator-maintained, so
-- `n_titles = 0` is the interesting row rather than a defect — a grouping someone created
-- and never attached, invisible from `titles` alone.
-- The Title side stays a _staging() read: `titles` decodes franchise and series onto each
-- Title, so composing it here would close a cycle. Hence also the position ahead of
-- `titles` — views bind at CREATE.
CREATE OR REPLACE VIEW franchises AS
  SELECT f.*,
         count(t.id) AS n_titles
  FROM _staging('raw.catalog_franchise') f
  LEFT JOIN stg.title t ON t.franchise_id = f.id
  GROUP BY ALL;
COMMENT ON VIEW franchises IS
  'One row per live Franchise — the IP grouping (Star Trek), spanning manufacturers and eras, with n_titles. Curator-maintained, never ingested, so n_titles = 0 is a real state.';

CREATE OR REPLACE VIEW series AS
  SELECT s.*,
         count(t.id) AS n_titles
  FROM stg.series s
  LEFT JOIN stg.title t ON t.series_id = s.id
  GROUP BY ALL;
COMMENT ON VIEW series IS
  'One row per live Series — a curated thematic lineage (Eight Ball -> Eight Ball Deluxe), with n_titles. Not the same thing as a Franchise, which is the IP.';

-- titles — one row per live Title: the entity grain behind `models.title_*`. Reach for it
-- when the Title itself is the subject.
--   franchise / series : the two optional Title groupings, resolved to slug and name. Both
--             sparse by design, and they mean different things: a franchise is the IP (Star
--             Trek, spanning manufacturers and eras), a series is a curated thematic
--             lineage (Eight Ball -> Eight Ball Deluxe). Neither is ingested, so an absent
--             grouping is "not yet curated", never "does not belong".
--   opdb_id / fandom_page_id : the outbound handles. opdb_id is OPDB's "group" — the Title
--             is the grain OPDB models identity at, so this and `models.opdb_id` are
--             different namespaces and must not be compared.
--   description : SingleModelTitles.md governs how this splits against the model's own
--             description.
CREATE OR REPLACE VIEW titles AS
  SELECT
    t.*,
    f.slug  AS franchise_slug, f.name  AS franchise_name,
    se.slug AS series_slug,    se.name AS series_name,
    COALESCE(tn.n, 0) AS n_models
  FROM stg.title t
  LEFT JOIN _title_live_n tn ON tn.title_id = t.id
  LEFT JOIN franchises f     ON f.id  = t.franchise_id
  LEFT JOIN series se        ON se.id = t.series_id;
COMMENT ON VIEW titles IS
  'One row per LIVE Title — identity, franchise/series grouping and n_models. A Title with no live models stays, at n_models = 0.';

-- collapsed_models — one row per model that its Title collapses into: the model a reader
-- reaches by the Title's URL, because the Title page renders its detail inline instead of
-- a model list (SingleModelTitles.md).
--
-- This is the product's rule, not an approximation of it: `titles.py` collapses when the
-- Title has exactly one active NON-VARIANT model and that model has no live variants.
-- `title_size` cannot express it. That column counts every live model in the Title,
-- variants included, so it answers a different question in both directions — a Title whose
-- sole model is a variant of a model in ANOTHER Title reads as size 1 while the product
-- shows a model list, and a Title holding one model plus its variants reads as size 3
-- while the product still refuses to collapse.
--
-- Reach for this whenever the question is which PAGE a link or mention lands on — a
-- collapsed model and its Title are one thing in the UI, and consumers that resolve one
-- grain to the other must all do it through this predicate or they will disagree.
CREATE OR REPLACE VIEW collapsed_models AS
  SELECT m.id, m.slug, m.name, m.title_id, m.title_slug
  FROM models m
  WHERE m.variant_of_id IS NULL
    -- Live variants only, which `models` already guarantees: a soft-deleted variant does
    -- not stop the product collapsing, so it must not stop this either.
    AND NOT EXISTS (SELECT 1 FROM models v WHERE v.variant_of_id = m.id)
    AND NOT EXISTS (SELECT 1 FROM models o
                    WHERE o.title_id = m.title_id AND o.variant_of_id IS NULL
                      AND o.id <> m.id);
COMMENT ON VIEW collapsed_models IS
  'One row per model whose Title collapses into it — the product rule from titles.py (one active non-variant model, itself without live variants), not the title_size = 1 approximation. The pair are one page in the UI, so resolve link/mention grain through this view.';

-- model_number_collisions — one row per (manufacturer, model number) that more than one
-- live model claims, so an analysis matching a source's model number can see up front
-- whether its key resolves. `n_titles` is the cheap discriminator: 1 means the collision is
-- contained in one Title and is probably a legitimate catalog split; > 1 wants a look.
-- EXACT numbers only, no stem matching. A suffix convention is a fact about ONE
-- manufacturer, not about the column — Bally's trailing letter marks a different game
-- (#634 'Fun Way' vs #634-A 'Lotta Fun'), which holds for nobody else.
CREATE OR REPLACE VIEW model_number_collisions AS
  SELECT
    manufacturer_id,
    manufacturer_slug,
    manufacturer_name,
    manufacturer_model_identifier   AS model_number,
    count(*)                        AS n,
    count(DISTINCT title_id)        AS n_titles,
    list_sort(list(id))             AS model_ids,
    list_sort(list(label))          AS labels
  FROM models
  WHERE manufacturer_id IS NOT NULL AND manufacturer_model_identifier IS NOT NULL
  GROUP BY ALL
  HAVING count(*) > 1;
COMMENT ON VIEW model_number_collisions IS
  'One row per (manufacturer, model number) claimed by more than one live model — exact numbers only. n_titles = 1 is usually a legitimate catalog split, not bad data.';

-- ═══ §50 PEOPLE AND CREDITS ═════════════════════════════════════════════════
-- credits — one row per credit: a Person, in a CreditRole, on a subject. THE grain, and the
-- definition `people` and `credit_roles` both aggregate.
--   THE SUBJECT IS POLYMORPHIC, and the minority half is the trap. A Credit hangs off a
--             MachineModel XOR a Series (`catalog_credit_model_xor_series`), and the Series
--             half is tiny — so a model-only grain would look complete, agree with every
--             spot check and silently miss a whole KIND of credit. Both halves are spelled
--             the way `claims` spells its subject types, so a join across needs no
--             translation. For the model half use `model_credits`, not a subject_type
--             predicate you wrote yourself.
--   subject_name : the subject's plain name. `models.label` is the disambiguated form
--             ("Name (Manufacturer Year)"), one join from `model_credits.model_id`.
--   provenance: Credit is a compound claim whose claim_key names two entities
--             (`credit|person:100|role:4`), so `claims.ref_id` is NULL and there is no
--             single-column join — go `claims` (subject_type/subject_id, field_name =
--             'credit') → `claim_identity_parts`, once per part.
CREATE OR REPLACE VIEW credits AS
  SELECT
    c.id                                        AS credit_id,
    -- Every subject_* column reads off the SAME joined row, never the raw FK columns, so
    -- they cannot end up describing two different subjects.
    CASE WHEN m.id IS NOT NULL THEN _entity_type_of('catalog_machinemodel')
         ELSE _entity_type_of('catalog_series') END AS subject_type,
    COALESCE(m.id,   s.id)                      AS subject_id,
    COALESCE(m.slug, s.slug)                    AS subject_slug,
    COALESCE(m.name, s.name)                    AS subject_name,
    c.person_id, p.slug AS person_slug, p.name AS person_name,
    c.role_id,   r.slug AS role_slug,   r.name AS role_name
  FROM raw.catalog_credit c
  JOIN stg.person p      ON p.id = c.person_id
  JOIN stg.credit_role r ON r.id = c.role_id
  -- Two LEFT JOINs plus "at least one resolved": exactly one side of the XOR can resolve,
  -- so the WHERE keeps the row on either and drops it when the side it names is dead.
  LEFT JOIN models m         ON m.id = c.model_id
  LEFT JOIN stg.series s   ON s.id = c.series_id
  WHERE m.id IS NOT NULL OR s.id IS NOT NULL;
COMMENT ON VIEW credits IS
  'One row per credit (person, role, live subject) — the credit GRAIN, and the definition people/credit_roles count. Subject is a model XOR a series, decoded into subject_type/id/slug/name; model_credits is the model half.';

-- model_credits — the model-attached half of `credits`, keyed model_id to join and
-- model_slug to emit. A handful of credits hang off a Series instead and are reachable only
-- from `credits`, so a total taken here is not a total.
CREATE OR REPLACE VIEW model_credits AS
  SELECT c.*, c.subject_id AS model_id, c.subject_slug AS model_slug
  FROM credits c
  WHERE c.subject_type = 'model';
COMMENT ON VIEW model_credits IS
  'One row per credit on a LIVE machine model, keyed model_id to join and model_slug to emit — the model half of credits; Series-attached credits appear only there.';

-- credit_roles — the credit-role vocabulary (designer, artist, …) at entity grain, with
-- usage. count(c.credit_id), never count(*): the LEFT JOIN would count an unused role as 1.
CREATE OR REPLACE VIEW credit_roles AS
  SELECT
    r.*,
    count(c.credit_id) AS n_credits
  FROM stg.credit_role r
  LEFT JOIN credits c ON c.role_id = r.id
  GROUP BY ALL;
COMMENT ON VIEW credit_roles IS
  'One row per live CreditRole — the credit vocabulary (designer, artist) with n_credits over live subjects. The role-keyed counterpart to people.n_roles; credits is the grain.';

-- people — one row per live Person, with how much of the catalog they are credited on.
--   n_credits : rows of `credits` — model- and series-attached together. Nearly but not
--             exactly n_credited_models, and treating either as the other drops the series
--             credits.
--   n_credited_models : distinct LIVE MODELS, hence the subject_type filter rather than a
--             count of subject_id: Model and Series pks are separate namespaces that
--             overlap freely, so an undistinguished count merges a series into the model
--             sharing its number.
--   n_roles : distinct roles held. A person credited as designer and artist on one machine
--             has n_credits = 2, n_credited_models = 1, n_roles = 2.
--   birth_year / death_year : claim-resolved biography, all but empty. Month and day exist
--             on the Django model and are entirely unpopulated, so the year is the full
--             precision on offer.
CREATE OR REPLACE VIEW people AS
  WITH agg AS (
    SELECT
      person_id,
      count(*)                AS n_credits,
      count(DISTINCT CASE WHEN subject_type = 'model'
                          THEN subject_id END)  AS n_credited_models,
      count(DISTINCT role_id) AS n_roles
    FROM credits
    GROUP BY person_id
  )
  SELECT
    p.*,
    COALESCE(a.n_credits, 0)         AS n_credits,
    COALESCE(a.n_credited_models, 0) AS n_credited_models,
    COALESCE(a.n_roles, 0)           AS n_roles
  FROM stg.person p
  LEFT JOIN agg a ON a.person_id = p.id;
COMMENT ON VIEW people IS
  'One row per live Person — identity, birth/death year and credit counts over live subjects. Counts only: `credits` is the grain that says WHICH models.';

-- ═══ §90 ALIASES & ABBREVIATIONS — matching source wording ══════════════════
-- Every alias view: one row per alias of a live parent, keyed by the parent's stable slug
-- (location_aliases uses location_path — Location slugs are parent-scoped). Values are
-- stored AS ENTERED, mixed case included; whether 'Playing Cards' should match
-- 'playing-cards' is the consuming analysis's call, and name_norm(alias) is the usual
-- starting point. location_aliases, theme_aliases and gameplay_feature_aliases sit beside
-- their vocabularies above.

CREATE OR REPLACE VIEW reward_type_aliases AS
  SELECT ra.reward_type_id, rt.slug AS reward_type_slug, ra.value AS alias
  FROM raw.catalog_rewardtypealias ra
  JOIN stg.reward_type rt ON rt.id = ra.reward_type_id;
COMMENT ON VIEW reward_type_aliases IS
  'One row per alias of a live reward type — alias GRAIN, for resolving a payout phrasing to the modelled type.';

CREATE OR REPLACE VIEW manufacturer_aliases AS
  SELECT ma.manufacturer_id, mf.slug AS manufacturer_slug, ma.value AS alias
  FROM raw.catalog_manufactureralias ma
  JOIN manufacturers mf ON mf.id = ma.manufacturer_id;
COMMENT ON VIEW manufacturer_aliases IS
  'One row per alias of a live manufacturer — alias GRAIN, for resolving a source name (native-script, accented, trade name) to the canonical Manufacturer.';

-- Corporate entity, not manufacturer: the legal entity below the manufacturer. An alias
-- resolved here may be finer-grained than the manufacturer used for grouping.
CREATE OR REPLACE VIEW corporate_entity_aliases AS
  SELECT ca.corporate_entity_id, ce.slug AS corporate_entity_slug, ca.value AS alias
  FROM raw.catalog_corporateentityalias ca
  JOIN corporate_entities ce ON ce.id = ca.corporate_entity_id;
COMMENT ON VIEW corporate_entity_aliases IS
  'One row per alias of a live corporate entity — alias GRAIN. The LEGAL entity, one level finer than manufacturer_aliases.';

CREATE OR REPLACE VIEW person_aliases AS
  SELECT pa.person_id, p.slug AS person_slug, pa.value AS alias
  FROM raw.catalog_personalias pa
  JOIN people p ON p.id = pa.person_id;
COMMENT ON VIEW person_aliases IS
  'One row per alias of a live person — alias GRAIN, carrying aka/maiden forms; resolve a credit name here before treating it as a new Person.';

-- ── Abbreviations ───────────────────────────────────────────────────────────
-- Abbreviations are community shorthand, NOT alternate names — use them for forum or
-- marketplace prose and keep them out of name-alias matching. The value column is named
-- `abbreviation` to keep the two families distinct.
CREATE OR REPLACE VIEW model_abbreviations AS
  SELECT ab.machine_model_id AS model_id, m.slug AS model_slug, ab.value AS abbreviation
  FROM raw.catalog_modelabbreviation ab
  JOIN models m ON m.id = ab.machine_model_id;
COMMENT ON VIEW model_abbreviations IS
  'One row per community abbreviation of a live model (LTBR, ACDC Prem VE) — shorthand, NOT an alternate name; use it for forum/marketplace prose.';

CREATE OR REPLACE VIEW title_abbreviations AS
  SELECT ab.title_id, t.slug AS title_slug, ab.value AS abbreviation
  FROM raw.catalog_titleabbreviation ab
  JOIN titles t ON t.id = ab.title_id;
COMMENT ON VIEW title_abbreviations IS
  'One row per community abbreviation of a live Title — the Title-grain twin of model_abbreviations.';

-- entity_names — every string that names a live record, canonical names and aliases as
-- ONE pool. That pool is how name matching must be done — most records have no alias row,
-- so searching aliases alone resolves almost nothing — and before this view existed every
-- consumer wrote the same two-branch union by hand, which is how copies drift.
--
-- Live-filtered, unlike entity_subjects and entity_aliases, because a matching pool that
-- resolves prose or source wording to a deleted record hands back a link nobody can
-- follow. Values as entered; choose normalization locally (name_norm / name_key).
-- Abbreviations are deliberately absent: community shorthand is not an alternate name,
-- which is why the abbreviation views name their column differently.
CREATE OR REPLACE VIEW entity_names AS
            SELECT s.subject_type      AS entity_type,
                   s.subject_id        AS entity_id,
                   s.subject_public_id AS public_id,
                   s.subject_name      AS name,
                   'name'              AS kind
            FROM entity_subjects s
            WHERE is_live(s.subject_status) AND s.subject_name IS NOT NULL
  UNION ALL SELECT a.entity_type, a.entity_id, s.subject_public_id, a.alias, 'alias'
            FROM entity_aliases a
            JOIN entity_subjects s ON s.subject_type = a.entity_type
                                  AND s.subject_id = a.entity_id
            WHERE is_live(s.subject_status) AND a.alias IS NOT NULL;
COMMENT ON VIEW entity_names IS
  'One row per string that names a LIVE record — canonical names and aliases as one pool (kind tells them apart), keyed (entity_type, entity_id) with the public id carried. The pool to match prose or source wording against; values as entered, so normalize locally. Abbreviations are shorthand, not names, and are not here.';

-- ═══ §110 THE WIKILINK GRAPH ════════════════════════════════════════════════
-- record_references — the `[[type:public-id]]` wikilink graph, one row per stored edge.
-- Django materializes it on every save (core.RecordReference, synced by
-- `sync_references`), so a link question is an indexed join and never a regex over prose.
--
-- LIVE ON THE SOURCE, not on the target, hence a target_status and no source_status. A
-- soft-deleted record's prose is not catalog content, so it is filtered here once. An edge
-- POINTING AT a soft-deleted record is the opposite — it is what a broken-link audit exists
-- to find, and dropping it would report the source as linkless instead.
--
-- THE TRAP: an inline `[[cite:N]]` is also a row here, and its target is a CitationInstance
-- — not a catalog entity, so it resolves to no entity_subjects row. `target_entity_type IS
-- NULL` marks them (target_django_label says which non-entity kind it was), so anything
-- counting a record's outbound links MUST decide whether cites count before it filters.
-- Hence the LEFT target joins, along with a second reason: a GenericForeignKey has no
-- on_delete, so a hard-deleted target leaves a dangling edge, which belongs here as a NULL
-- target rather than a vanished row.
-- The SOURCE join is INNER because `is_live()` reads a NULL status as live, so a LEFT join
-- would admit a hard-deleted source as a row with no identity.
CREATE OR REPLACE VIEW record_references AS
  SELECT
    src.entity_type          AS source_entity_type,
    r.source_id,
    s.subject_public_id      AS source_public_id,
    s.subject_name           AS source_name,
    tgt.entity_type          AS target_entity_type,
    r.target_id,
    t.subject_public_id      AS target_public_id,
    t.subject_name           AS target_name,
    t.subject_status         AS target_status,
    tct.app_label || '.' || tct.model AS target_django_label
  FROM raw.core_recordreference r
  JOIN raw.django_content_type sct ON sct.id = r.source_type_id
  JOIN raw.django_content_type tct ON tct.id = r.target_type_id
  JOIN entity_registry src ON src.django_label = sct.app_label || '.' || sct.model
  LEFT JOIN entity_registry tgt ON tgt.django_label = tct.app_label || '.' || tct.model
  JOIN entity_subjects s
    ON s.subject_type = src.entity_type AND s.subject_id = r.source_id
  LEFT JOIN entity_subjects t
         ON t.subject_type = tgt.entity_type AND t.subject_id = r.target_id
  WHERE is_live(s.subject_status);
COMMENT ON VIEW record_references IS
  'One row per stored wikilink edge from a LIVE record, both ends decoded to (entity_type, public id, name). Django materializes this on save, so ANY question about what prose links is a join here, never a regex over entity_prose.text. Live on the source only — target_status is carried, because an edge to a soft-deleted record is a broken link worth finding. An inline [[cite:N]] is a row whose target_entity_type IS NULL; filter it or count it deliberately.';

-- ═══ §115 PROSE TEXT — the corpus as matching material ══════════════════════
-- entity_prose is the raw authored corpus. These views are its mention-bearing reading:
-- what the prose says in its OWN voice, with wikilink markup and quoted wordings
-- separated out rather than left to each consumer's regex.

-- The one definition of a quoted run, shared by the view that extracts them and the view
-- that excludes them — two copies would disagree about which text is which. Straight and
-- curly doubles alike; bounded and single-line so an unbalanced quote can swallow at
-- most 80 characters of one line, never the rest of the description.
CREATE OR REPLACE MACRO _quoted_run() AS '["“”][^"“”\n]{0,80}["“”]';

-- prose_quotes — the wordings prose QUOTES rather than says: a machine's nickname, a
-- feature name as a source spelled it, a marketing slogan. A name in here is legitimately
-- unwikilinked, which is exactly why these runs are absent from prose_words.
CREATE OR REPLACE VIEW prose_quotes AS
  SELECT entity_type, entity_id, public_id, field,
         UNNEST([regexp_replace(q, '^["“”]|["“”]$', '', 'g')
                 for q in regexp_extract_all(text, _quoted_run())]) AS quote
  FROM entity_prose WHERE text IS NOT NULL;
COMMENT ON VIEW prose_quotes IS
  'One row per double-quoted run in a live record''s prose (straight or curly, marks stripped) — the wordings prose quotes rather than says. The complement of prose_words, which excludes these runs.';

-- prose_words — each prose field as a word array: wikilink markup and quoted runs
-- removed, accents folded, punctuation collapsed, CASE KEPT so a consumer can still
-- distinguish the game Pinball from the word pinball. Word position in this array is the
-- shared coordinate system: every consumer that matches spans against prose reads this
-- one tokenization, or its positions disagree with its neighbours'.
CREATE OR REPLACE VIEW prose_words AS
  SELECT entity_type, entity_id, public_id, field,
         str_split(trim(regexp_replace(
           strip_accents(regexp_replace(
             regexp_replace(text, '\[\[[^\]]*\]\]', ' ', 'g'),
             _quoted_run(), ' ', 'g')),
           '[^\p{L}\p{N}]+', ' ', 'g')), ' ') AS w
  FROM entity_prose WHERE text IS NOT NULL;
COMMENT ON VIEW prose_words IS
  'One row per prose field of a live record — the text as a word array, wikilink markup and quoted runs removed, accents folded, case kept. The shared tokenization: match spans against this so word positions agree across consumers; quoted wordings live in prose_quotes instead.';

-- ═══ §120 DOMAIN VOCABULARY — what a slug MEANS ═════════════════════════════
-- The catalog's controlled vocabularies (game formats, cabinets, production statuses, …)
-- are DEFINED in docs/DomainModel.md — what separates `one-off` from `unreleased`,
-- `shuffle` from `rolldown`. The DB carries only the slug and display name, so
-- `domain_vocab` parses those definition bullets at query time, leaving the doc the only
-- place a domain fact is written.
--
-- The doc shape relied on: a bullet `- \`slug\`: definition`, grouped by the nearest
-- preceding `**EntityName**` lead-in, else by the `##`/`###` heading. The group is
-- snake-stripped to a dim name (`Production Status` -> `productionstatus`), which is
-- exactly the catalog table suffix, so the doc->table mapping needs no hand-maintained
-- list. Renaming a heading detaches every bullet under it, surfacing at once as
-- undocumented_vocab for every slug in that vocabulary plus stale_vocab_dim.
CREATE OR REPLACE VIEW _dm_lines AS
  WITH raw AS (SELECT content FROM read_text('docs/DomainModel.md'))
  SELECT generate_subscripts(str_split(content, chr(10)), 1) AS i,
         unnest(str_split(content, chr(10)))                 AS t
  FROM raw;

-- The group each bullet belongs to: a bold lead-in when the section has one (Display Type
-- documents DisplayType AND DisplaySubtype under one heading), else the heading itself.
CREATE OR REPLACE VIEW _dm_marked AS
  SELECT i, t,
         CASE WHEN regexp_matches(t, '^\*\*[A-Za-z]+\*\* ') THEN regexp_extract(t, '^\*\*([A-Za-z]+)\*\*', 1)
              WHEN regexp_matches(t, '^#{2,3} ')            THEN regexp_extract(t, '^#{2,3} (.*)$', 1)
         END AS group_raw
  FROM _dm_lines;

-- domain_vocab — one row per documented vocabulary term.
-- The bullet filter is a QUALIFY and must stay one: the group window has to run over EVERY
-- line, and a WHERE runs FIRST, stripping the heading rows the window reads — every group
-- then comes back NULL and the view silently returns nothing.
-- Restricted to groups naming a real raw.catalog_<dim> table, which keeps non-vocabulary
-- bullet lists out ("Fields Common to All Catalog Entities" uses this exact shape). A newly
-- documented vocabulary needs no edit here, only a _dim_vocab entry; unmapped_vocab_dim
-- says so.
CREATE OR REPLACE VIEW domain_vocab AS
  SELECT lower(replace(last_value(group_raw IGNORE NULLS) OVER (ORDER BY i), ' ', '')) AS dim,
         regexp_extract(t, '^- `([a-z0-9-]+)`: ', 1)    AS slug,
         regexp_extract(t, '^- `[a-z0-9-]+`: (.*)$', 1) AS definition,
         i AS doc_line
  FROM _dm_marked
  QUALIFY regexp_matches(t, '^- `[a-z0-9-]+`: ')
      AND dim IN (SELECT replace(table_name, 'catalog_', '')
                  FROM duckdb_tables() WHERE database_name = current_database() AND schema_name = 'raw');
COMMENT ON VIEW domain_vocab IS
  'One row per controlled-vocabulary term defined in docs/DomainModel.md — dim, slug and the prose definition, parsed from the doc at query time. Join it to a vocabulary view to read what a slug MEANS; the doc stays the only place domain semantics are written.';

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
    (SELECT patch_id FROM raw.provenance_ingestrun
       WHERE status = 'success' AND patch_id IS NOT NULL ORDER BY id DESC LIMIT 1) AS latest_patch,
    (SELECT input_fingerprint FROM raw.provenance_ingestrun
       WHERE status = 'success' AND patch_id IS NOT NULL ORDER BY id DESC LIMIT 1) AS patch_fingerprint,
    (SELECT max(id) FROM raw.provenance_changeset) AS latest_changeset,
    (SELECT imported_at FROM raw._import_stamp)    AS snapshot_imported_at;
COMMENT ON VIEW analysis_context IS
  'One row — the input watermark: DuckDB version, live model count, migration point, latest successful patch + fingerprint, latest changeset id, and when the catalog was imported. Printed by every analysis run.';

-- ═══ PROVENANCE — who said so (provenance.sql) ══════════════════════════════
-- The attribution and citation layer — claims, ingest sources, ingest runs, citation
-- sources. Its own file, `.read` here so "the foundation" stays ONE `.read` line for every
-- consumer, sister repos included.
.read scripts/analysis/sql/provenance.sql

-- ═══ DATA PATCHES — what our own patches did (data_patches.sql) ═════════════
-- The patch lens on the provenance layer: which patch asserted a fact, which retracted
-- one, and what evidence each data patch entry recorded.
.read scripts/analysis/sql/data_patches.sql
