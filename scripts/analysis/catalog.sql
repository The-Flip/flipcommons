-- Catalog analysis foundation — the shared decode layer over the live DB.
--
-- `.read` this from an analysis file to get a connected, decoded catalog: it ATTACHes the
-- catalog READ-ONLY and defines views over the awkward physical schema (JSON extra_data,
-- the model -> corporate_entity -> manufacturer chain, reward M2M). Run from the REPO
-- ROOT — the ATTACH path and every `.read` resolve against the current directory.
--
--     scripts/analysis/analysis query <analysis>.sql "FROM <a_view> LIMIT 5;"
--
-- What `fc` attaches is db.analytics.duckdb, an IMPORT of backend/db.sqlite3 into
-- DuckDB's own storage — not the SQLite file itself. The runner re-imports whenever the
-- source changes, so going through it is the supported entry point; a bare `duckdb -init`
-- attaches whatever the last import produced (`analysis_context.snapshot_imported_at`).
--
-- Conventions that hold throughout and are NOT restated per view:
--   * `_underscore` = private helper.
--   * Views omit soft-deleted records (see RecordLifecycle.md) and
--     live means `status IS DISTINCT FROM 'deleted'`, matching the read APIs.
--   * A dim or edge target is soft-deleted independently of its subject, so a dead one
--     DE-ENRICHES TO NULL rather than being reported as current. catalog_checks flags
--     every occurrence; per-view notes name only the check.
--   * Predicate and join on ids/slugs; display the names.
--
-- README.md to write an analysis; EDITING.md to change this file.

-- Not the SQLite file in place: DuckDB's sqlite scanner collapses two aggregates into
-- one under our liveness predicate. EDITING.md, "Why the catalog is imported rather
-- than attached".
ATTACH IF NOT EXISTS 'backend/db.analytics.duckdb' AS fc (READ_ONLY);

-- ═══ NAME NORMALIZATION — macros for comparing names across records ═════════
-- The key for comparing a catalog name against another record's — a source's game title,
-- a sibling model, an alias. Split at the one clause that is a JUDGMENT rather than a
-- mechanic, so an analysis picks deliberately:
--
--   name_norm         fold Latin diacritics, lowercase, collapse every run of
--                     non-letter/non-digit to one space, trim. Folding is what makes
--                     cross-source spellings match ('München' / 'Munchen'). The character
--                     class is Unicode-aware (\p{L}\p{N}), so a non-Latin name keys to
--                     itself instead of collapsing to the empty string and matching every
--                     other such name. Two limits: ordinal indicators survive as letters
--                     ('1ª División' -> '1ª division', so a source writing '1a' won't
--                     match), and strip_accents folds Japanese dakuten (バ and パ onto
--                     ハ), so distinct kana can share a key.
--   name_strip_paren  drop ONE trailing parenthetical. CUTS BOTH WAYS: it lets an export
--                     edition find its original ('On Beam (Italy)' -> 'On Beam') and it
--                     collapses 'KISS (Limited Edition)' onto 'KISS'. Record whether a
--                     match was exact or needed the strip, and let a reviewer weigh it.
--   name_key          the composition, for the common case.
--
-- Matching STRATEGY is deliberately absent — plural collapsing, stopwords, token subsets,
-- edit distance are tuned to a corpus and belong to the analysis that needs them.
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

-- ═══ LIVE — the one place the liveness rule is written ══════════════════════
-- live('fc.catalog_x') is the live rows of a lifecycle table, minus the three columns
-- every entity view drops for the same reason. It exists so neither the rule nor that
-- reason is retyped per view: `status` is redundant on a view that IS the live rows, and
-- created_at/updated_at are row bookkeeping that differs between any two copies of the
-- catalog, so they describe the local db state rather than catalog state.
-- Use it for the BASE read only — joins go through the joined entity's own view, so its
-- liveness stays stated once too. It has no opinion about columns beyond those three: a
-- view that drops more says so itself, which is what keeps an EXCLUDE list meaningful.
-- Fails loudly (Binder Error on `status`) against a table with no lifecycle, which is
-- correct: alias tables are not live-filtered and must not pretend to be.
-- blanks_null is the other half of the same idea, split out because tables with no
-- lifecycle need it too. Django spells an unset CharField(blank=True) as '' and an unset
-- nullable field as NULL, and both used to reach the views untouched — so `description
-- IS NULL` was ALWAYS FALSE on 6,828 models while `year IS NULL` was correct, with
-- nothing in either column to say which spelling applied. One spelling now reaches a
-- consumer: absent is NULL.
-- The `::VARCHAR` cast is inside the comparison and not around the value, which is what
-- makes this safe to apply to every column at once — `NULLIF(COLUMNS(*), '')` fails with
-- a conversion error on the first integer, while CASE returns the column untouched and
-- preserves its type.
-- Apply it BY NAME, never by testing whether a table has the columns for it: '' is a real
-- value in citation_citationsourcerootdomain.path_prefix, where it means "whole host"
-- rather than "no host", and folding it to NULL there would be a semantic error.
CREATE OR REPLACE MACRO blanks_null(tbl) AS TABLE
  SELECT CASE WHEN COLUMNS(*)::VARCHAR = '' THEN NULL ELSE COLUMNS(*) END
  FROM query_table(tbl);
COMMENT ON MACRO TABLE blanks_null IS
  'blanks_null(''fc.x'') — every column of a table with '''' folded to NULL, types preserved. The base read for a table with no lifecycle; live() already includes it.';

CREATE OR REPLACE MACRO live(tbl) AS TABLE
  SELECT * EXCLUDE (status, created_at, updated_at)
  FROM blanks_null(tbl)
  WHERE status IS DISTINCT FROM 'deleted';
COMMENT ON MACRO TABLE live IS
  'live(''fc.catalog_x'') — the live rows of a lifecycle table minus status/created_at/updated_at, with '''' folded to NULL. The base read for every entity view; joins use the joined entity''s view instead.';

-- ═══ DIMENSIONS — what a model points at ════════════════════════════════════
-- locations — one row per live Location, at EVERY level. THE entity: a country is simply
-- a Location with no parent (`is_country`), and there is no separate country table or
-- country view — filter this one.
--
--   location_path : the stable key ('usa/il/chicago'), and the one to join on. `slug` is
--             unique only WITHIN a parent — there is more than one 'victoria' in the
--             world — so a join on slug silently merges places. The path is also the
--             hierarchy: country_slug is its first segment, and a place's descendants are
--             the rows whose path starts with its path plus '/'.
--   location_type : an OPEN vocabulary, not a 3-level ladder — country, state,
--             province, department, community, region, prefecture, constituent_country,
--             district, city. Only `country` is structurally guaranteed (exactly the
--             parentless rows); the rest reflect how each country subdivides itself, so
--             an analysis assuming country/state/city silently drops the live places that
--             are none of those. Predicate on path depth when you mean depth.
--   code / short_name / divisions : sparse by construction. `code` is the subdivision's
--             own code (VIC, WA), empty on every country and city; `divisions` is on
--             countries alone, naming how that country subdivides; `short_name` is rarer
--             still. Read each at the level that carries it.
--   n_corporate_entities : live corporate entities based here DIRECTLY — a country does
--             not inherit its cities' counts. Roll up with a location_path prefix.
CREATE OR REPLACE VIEW locations AS
  SELECT
    l.*,
    split_part(l.location_path, '/', 1)      AS country_slug,
    l.parent_id IS NULL                      AS is_country
  FROM live('fc.catalog_location') l;
-- corporate_entity_locations — one row per (live corporate entity, live location) it is
-- based in. THE bridge: CorporateEntityLocation is a through model owned by
-- CorporateEntity ("existence is controlled by `location` relationship claims on
-- CorporateEntity"), which is why the count of CEs per location does NOT live on
-- `locations` — a Location knows nothing about corporate entities, and having the entity
-- view reach across a relationship it doesn't own is what made three separate views read
-- this table. Group this by location_id for that count.
-- The CE join is physical because `corporate_entities` aggregates over `models`, so
-- composing it here would be circular; the location side goes through `locations`.
CREATE OR REPLACE VIEW corporate_entity_locations AS
  SELECT
    cel.corporate_entity_id,
    ce.slug          AS corporate_entity_slug,
    l.id             AS location_id,
    l.location_path,
    l.country_slug,
    l.is_country
  FROM fc.catalog_corporateentitylocation cel
  JOIN locations l ON l.id = cel.location_id
  -- Physical, not `corporate_entities`: that view aggregates over `models`, which reaches
  -- back here through _ce_location. The location side composes; this side cannot.
  JOIN fc.catalog_corporateentity ce
    ON ce.id = cel.corporate_entity_id AND ce.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW corporate_entity_locations IS
  'One row per (live corporate entity, live location) — THE CE-to-Location bridge and the only reader of the through table; group by location_id for corporate entities per place.';

COMMENT ON VIEW locations IS
  'One row per live Location at EVERY level — THE entity; a country is just a row with is_country. Join on location_path, never slug: slug is unique only within a parent.';
-- location_aliases — every alias of every live Location: countries, regions and cities.
-- Keyed on location_path, not slug (see `locations`). Filter is_country for the country slice.
CREATE OR REPLACE VIEW location_aliases AS
  SELECT
    la.location_id,
    l.location_path,
    l.country_slug,
    l.is_country,
    la.value AS alias
  FROM fc.catalog_locationalias la
  JOIN locations l ON l.id = la.location_id;
COMMENT ON VIEW location_aliases IS
  'One row per alias of a live Location at any level — alias GRAIN, keyed on location_path because Location.slug is unique only within a parent. Filter is_country for countries.';

-- game_formats — the machine-genre vocabulary.
CREATE OR REPLACE VIEW game_formats AS SELECT * FROM live('fc.catalog_gameformat');
COMMENT ON VIEW game_formats IS
  'One row per live game format — the machine-genre vocabulary';

-- reward_types — what a machine pays out: the VOCABULARY behind `rewards`.
-- `rewards` says which types a model has, this says what the closed set is, and
-- `reward_type_aliases` resolves a source's phrasing into it.
CREATE OR REPLACE VIEW reward_types AS SELECT * FROM live('fc.catalog_rewardtype');
COMMENT ON VIEW reward_types IS
  'One row per live reward type — the payout vocabulary behind rewards; join reward_type_aliases to resolve a source phrasing into it.';

-- ─── Taxonomy dims, at entity grain ─────────────────────────────────────────
-- One view per taxonomy dim. `models` carries these as SLUG ONLY and still does — these
-- are the other half of that decision rather than a reversal of it. The slug is what you
-- predicate and group on, so it is all a model row needs; the rest of the RECORD lives
-- here, where the subject is the vocabulary itself.
--
-- `description` is the field that forced them. It is authored prose that no `models`
-- column could carry, and while these tables were reachable only by raw-joining
-- fc.catalog_<dim>, "which vocabulary terms are still undocumented" had no answer in the
-- foundation at all — the shape EDITING.md warns about, where a column missing from a
-- view gets read as a field the Django model does not have.
--
-- Uniform shape: id, slug, name, description, plus the decoded parent where the dim has
-- one. Live rows only, and every parent join live-filtered, as everywhere else here.
CREATE OR REPLACE VIEW technology_generations AS SELECT * FROM live('fc.catalog_technologygeneration');
COMMENT ON VIEW technology_generations IS
  'One row per live technology generation — the major-era vocabulary (Electromechanical, Solid State).';

CREATE OR REPLACE VIEW technology_subgenerations AS
  SELECT
    tsg.*,
    tg.slug AS technology_generation_slug
  FROM live('fc.catalog_technologysubgeneration') tsg
  LEFT JOIN technology_generations tg ON tg.id = tsg.technology_generation_id;
COMMENT ON VIEW technology_subgenerations IS
  'One row per live technology subgeneration — the subdivision vocabulary, carrying its parent generation decoded to a slug.';

CREATE OR REPLACE VIEW display_types AS SELECT * FROM live('fc.catalog_displaytype');
COMMENT ON VIEW display_types IS
  'One row per live display type — the display-technology vocabulary (Score Reels, DMD, LCD).';

CREATE OR REPLACE VIEW display_subtypes AS
  SELECT
    dst.*,
    dt.slug AS display_type_slug
  FROM live('fc.catalog_displaysubtype') dst
  LEFT JOIN display_types dt ON dt.id = dst.display_type_id;
COMMENT ON VIEW display_subtypes IS
  'One row per live display subtype — the subdivision vocabulary, carrying its parent display type decoded to a slug.';

-- systems — the one dim whose name is not a mangled slug (`Bally AS-2518-35`), which is
-- why `models` keeps system_name alongside system_slug. Manufacturer is a required FK:
-- a system belongs to whoever built it.
CREATE OR REPLACE VIEW systems AS
  SELECT
    s.*,
    mf.slug AS manufacturer_slug, mf.name AS manufacturer_name,
    tsg.slug AS technology_subgeneration_slug
  FROM live('fc.catalog_system') s
  -- Physical, not `manufacturers`: that view aggregates over `models`, which joins
  -- `systems`, so composing it here would close a cycle.
  LEFT JOIN fc.catalog_manufacturer mf ON mf.id = s.manufacturer_id
                                      AND mf.status IS DISTINCT FROM 'deleted'
  LEFT JOIN technology_subgenerations tsg ON tsg.id = s.technology_subgeneration_id
;
COMMENT ON VIEW systems IS
  'One row per live system — the hardware-generation vocabulary (WPC-95, SAM, SPIKE) with its manufacturer and technology subgeneration decoded.';

CREATE OR REPLACE VIEW cabinets AS SELECT * FROM live('fc.catalog_cabinet');
COMMENT ON VIEW cabinets IS
  'One row per live cabinet — the form-factor vocabulary (floor, countertop, cocktail).';

-- production_statuses is the ProductionStatus vocabulary, NOT the soft-delete `status`
-- every other view here filters on. Same trap as the column on `models`.
-- NB the `status` live() drops here is the SOFT-DELETE flag, not the production status
-- this view is about — carrying it would have been doubly confusing.
CREATE OR REPLACE VIEW production_statuses AS SELECT * FROM live('fc.catalog_productionstatus');
COMMENT ON VIEW production_statuses IS
  'One row per live production status — the commercial-production vocabulary (produced, announced, one-off).';

-- ═══ MODELS — the spine; start here ═════════════════════════════════════════
-- _ce_location — the MANUFACTURER's home location per corporate entity, collapsed to ONE
-- row per CE so joining it can't fan out the one-row-per-model grain. CorporateEntity-
-- Location is 1:N, but every CE has exactly one location today: while that holds this is
-- exact, and ce_multi_location fires the day it stops. location_path is the most-specific
-- known place AND the stable key; country_slug is its root segment, the join key.
CREATE OR REPLACE VIEW _ce_location AS
  SELECT
    corporate_entity_id,
    min(location_path)                            AS location_path,
    -- country_slug comes from `locations`, which is the one place location_path is split.
    -- min_by, not min: it reads country_slug off the SAME row min(location_path) picks,
    -- so the pair stays coherent if a CE ever carries two locations (ce_multi_location
    -- fires then, but this shouldn't quietly mix two places in the meantime).
    min_by(country_slug, location_path)           AS country_slug
  FROM corporate_entity_locations
  GROUP BY corporate_entity_id;

-- _title_live_n — live models per Title. Reads the physical table because `models`
-- consumes it; reading `models` would be circular.
CREATE OR REPLACE VIEW _title_live_n AS
  SELECT title_id, count(*) AS n
  FROM fc.catalog_machinemodel
  WHERE status IS DISTINCT FROM 'deleted'
  GROUP BY title_id;

-- _namesake_live_n — live models per name_key, physical-table-read for the same reason.
CREATE OR REPLACE VIEW _namesake_live_n AS
  SELECT name_key(name) AS name_key, count(*) AS n
  FROM fc.catalog_machinemodel
  WHERE status IS DISTINCT FROM 'deleted'
  GROUP BY name_key(name);

-- models — one row per LIVE MachineModel. `analysis describe models` prints
-- the full column list; these notes cover only what ISN'T obvious.
--   title_* : the model's Title — the spine of the hierarchy (every model has one; the
--             FK is NOT NULL), decoded inline so title-mate analyses never reach for
--             catalog_title.
--   title_size : how many LIVE models share this model's Title — the model-keyed form of
--             the `title_size` VIEW, off one helper so they can't disagree. "Alone in its
--             Title?" is `title_size = 1`. Always >= 1, since the model counts itself —
--             a 0 here means the join broke, which title_size_zero_on_live asserts.
--   namesake_count : LIVE models sharing this model's `name_key`, including itself. 1
--             means unique; > 1 is ambiguous and needs another signal. Trailing-
--             parenthetical variants count together (it uses name_key). Always >= 1 for
--             the same reason as title_size. See README.md#matching-source-records-to-models.
--   manufacturer_model_identifier : the MANUFACTURER's own model number (Gottlieb '654',
--             Stern 'PINBALL I-00M1 * JURAS. PARK PRO'). NOT unique, and NOT unique
--             paired with manufacturer_id either: manufacturers number independently from
--             1, AND the catalog splits finer than they numbered, so one number spans
--             several models — within a Title (Gottlieb 409 = Cleopatra + Cleopatra (EM))
--             or across Titles for a re-theme family (Williams 394 = Zodiac + Planets).
--             Some collisions are just bad data (Bally 868 = Safari 1969 + Mysterian
--             1982). GROUP BY (manufacturer_id, identifier) before treating it as an
--             identity; `model_number_collisions` is the ready-made view. NULL on most
--             live models.
--   year / month : the release date as a precision ladder — `catalog_machinemodel_month_
--             requires_year` means a NULL month is "dated to the year", never a month
--             lost from a fuller date. Nothing above the year is modelled, so a named
--             quarter or season arrives as a month or as nothing.
--   production_quantity : text, not a number — a CharField whose empty state is ''
--             (`= ''`, not `IS NULL`) and whose values nothing validates, so TRY_CAST
--             for arithmetic and keep the NULLs it produces. Blank is unknown, not zero.
--   manufacturer : manufacturer_name is the canonical name on the cabinet — display and
--             group by it.
--   location: where the MANUFACTURER was based (model -> corporate_entity -> location).
--             Its ORIGIN, NOT an export-market destination — those are
--             `model_export_markets`. location_path ('usa/il/chicago') is the most-
--             specific known place and the stable key; country_slug ('usa') is its root,
--             the field to join/group by (-> locations, is_country, for the name).
--   game_format_*   : machine genre, id/slug, NULL if untyped; `game_formats` has the name.
--   taxonomy dims   : technology_generation / technology_subgeneration, display_type /
--             display_subtype, system, cabinet, production_status — SLUG ONLY (DomainModel
--             "Taxonomy & Classification"). The slug ('solid-state', 'dot-matrix', 'floor')
--             is both the readable label and the join key back to fc.catalog_<dim>, so
--             neither the FK id nor the display name is carried. `system` is the exception
--             and keeps system_name: a hardware designation like 'Bally AS-2518-35' that
--             the slug mangles. production_status is the ProductionStatus FK, NOT the
--             soft-delete `status`. The subgeneration/subtype dims are mostly NULL today.
--   variant_of_id / remake_of_id / export_edition_of_id : bare self-FKs to the origin
--             model. No matching _slug columns, deliberately — resolving the far end is
--             `model_lineage`'s job (join it on model_id and edge_kind, then read
--             target_slug), and one facet copied here starts a second target_* block to
--             keep in step with that one.
--   source free-text : ipdb_notes, ipdb_notable_features, ipdb_toys,
--             ipdb_marketing_slogans (prose) and opdb_features (VARCHAR[], empty never
--             NULL; 'Export edition', 'Cocktail', …) — source fields the product doesn't
--             surface, promoted so mining them needs no hand-rolled json_extract. The
--             prose ones are sparse: NULL is a fact about the source's coverage.
--   NOT surfaced : the extra_data long tail (opdb.keywords — use `themes` —
--             opdb.common_name, opdb.description, …). Promoting one is a single
--             line here; see EDITING.md.
--   label   : "Name (Manufacturer Year)", CE name then '?' as fallbacks; year omitted if
--             unknown.
CREATE OR REPLACE VIEW models AS
  SELECT
    -- Every MachineModel column, minus the ones named below. `m.*` rather than a list on
    -- purpose: with a list, a field deliberately left out and a field nobody noticed look
    -- identical — both are simply absent — so the layer had no way to record an omission
    -- as a decision. EXCLUDE is that record. A new field on the model now surfaces here on
    -- its own, and the only way it stays out is if someone writes down why, right here.
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
    -- Single-FK taxonomy dims — the SLUG is the join key and the label; the raw FK id
    -- rides along from m.* and is not the column to predicate on.
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
  -- Every dim join is live-filtered, so a deleted dim de-enriches to NULL. It should
  -- never bite (the FKs are PROTECT and the soft-delete walker blocks it) and
  -- model_dim_not_live fires if it does.
  FROM live('fc.catalog_machinemodel') m
  -- Title, corporate entity and manufacturer stay PHYSICAL joins on purpose: `titles`,
  -- `corporate_entities` and `manufacturers` all aggregate over `models`, so composing
  -- them here would be circular. Only the leaf dims below can be composed.
  LEFT JOIN fc.catalog_title t             ON t.id  = m.title_id
                                          AND t.status  IS DISTINCT FROM 'deleted'
  LEFT JOIN _title_live_n tn               ON tn.title_id = m.title_id
  LEFT JOIN _namesake_live_n nk            ON nk.name_key = name_key(m.name)
  LEFT JOIN fc.catalog_corporateentity ce ON ce.id = m.corporate_entity_id
                                          AND ce.status IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_manufacturer mf     ON mf.id = ce.manufacturer_id
                                          AND mf.status IS DISTINCT FROM 'deleted'
  LEFT JOIN _ce_location cel               ON cel.corporate_entity_id = m.corporate_entity_id
  -- The dim joins go through the dim VIEWS, which are defined above and are already
  -- live-only, so the liveness rule for each dimension is stated once — in that view —
  -- rather than restated here. A soft-deleted dim still de-enriches to NULL, unchanged,
  -- because the view simply does not contain the row.
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

-- ═══ MANUFACTURERS AND CORPORATE ENTITIES ═══════════════════════════════════
-- presumed_producing — the still-producing verdict the SITE publishes, which is not
-- operating_status alone: an 'unknown' subject with a recent model reads as producing
-- ("1990–present"), one without reads as closed. The window is a product fact
-- (UNKNOWN_RECENCY_YEARS in frontend/src/lib/utils.ts); rewriting it locally drifts from
-- what the site shows. Not stable across runs — it moves with the calendar.
CREATE OR REPLACE MACRO presumed_producing(operating_status, year_of_last_model) AS
  operating_status = 'ongoing'
  OR (operating_status = 'unknown'
      AND year_of_last_model IS NOT NULL
      AND year_of_last_model > year(current_date) - 6);
COMMENT ON MACRO presumed_producing IS
  'The site''s still-producing verdict: ongoing, or unknown with a model inside the 6-year recency window (frontend UNKNOWN_RECENCY_YEARS). False is not ended — see manufacturers.';

-- _mfr_status — OperatingStatus.rollup over a manufacturer's live corporate entities,
-- precedence ONGOING > UNKNOWN > ENDED. Read it through manufacturers.operating_status.
-- No CE at all rolls up to unknown, NEVER ended (empty bool_and is NULL, so the ELSE
-- catches it) — the branch is unreachable today and is the backend's stated behaviour.
CREATE OR REPLACE VIEW _mfr_status AS
  SELECT manufacturer_id,
         CASE WHEN bool_or(operating_status = 'ongoing') THEN 'ongoing'
              WHEN bool_and(operating_status = 'ended')  THEN 'ended'
              ELSE 'unknown' END AS operating_status
  FROM fc.catalog_corporateentity
  WHERE status IS DISTINCT FROM 'deleted' AND manufacturer_id IS NOT NULL
  GROUP BY manufacturer_id;

-- _mfr_location — a manufacturer's place rolled up over its LIVE corporate entities, at
-- both rungs. Read it through manufacturers.location_path / country_slug.
-- Derived from the CEs and NOT from `models`, same shape as _mfr_status above and for the
-- same reason: a location is a fact about the COMPANY, and models are only the
-- denormalization path that usually reaches it. Aggregating models instead reports any
-- maker whose models are all gone or not yet seeded as location-unknown, though its CEs
-- carry an address. DISTINCT ignores NULL, so a CE with no location lowers neither count.
CREATE OR REPLACE VIEW _mfr_location AS
  SELECT ce.manufacturer_id,
         count(DISTINCT cel.location_path)  AS n_locations,
         CASE WHEN count(DISTINCT cel.location_path) = 1
              THEN min(cel.location_path) END AS location_path,
         count(DISTINCT cel.country_slug)   AS n_countries,
         CASE WHEN count(DISTINCT cel.country_slug) = 1
              THEN min(cel.country_slug) END  AS country_slug
  FROM live('fc.catalog_corporateentity') ce
  LEFT JOIN _ce_location cel ON cel.corporate_entity_id = ce.id
  WHERE ce.manufacturer_id IS NOT NULL
  GROUP BY ce.manufacturer_id;

-- manufacturers — one row per live manufacturer: identity, where it was based, how much
-- it made and WHEN. The span columns matter because a MODEL with no year often has its
-- manufacturer's span as the only evidence available.
--
-- Grain: the physical chain is model -> CorporateEntity -> Manufacturer, and a
-- manufacturer can own more than one CE. This view is at the MANUFACTURER level (the name
-- on the cabinet, what you group and display by); drop to models.corporate_entity_* for
-- the legal entity.
--
--   n_models    : live models attributed here, VARIANTS INCLUDED. 0 is normal — the
--                 catalog carries manufacturers with no models yet.
--   n_nonvariant_models : the same count with variants excluded — what
--                 /api/export/manufacturers/ publishes as `model_count`.
--   n_dated     : non-variant models carrying a year — the year pair's scope and THE
--                 denominator for it: a span resting on 2 models is not the claim a span
--                 resting on 40 is, and only this column tells them apart.
--   year_of_first_model / year_of_last_model : min/max year over those models, published
--                 under these names by /api/export/manufacturers/. NO minimum applied: a
--                 1-model span is reported as itself at n_dated = 1, and the caller sets
--                 its own bar (`WHERE n_dated >= 3`). Gaps are invisible — active
--                 1932-1935 and again 1975-1979 reads as a 47-year span, so treat it as
--                 an outer bound, not a continuous run.
--   operating_status / presumed_producing : the site's answer to "is this manufacturer
--                 still making pinball", at the grain the site asks it. operating_status
--                 is the rollup over its live CEs (ONGOING > UNKNOWN > ENDED), matching
--                 what /api/export/manufacturers/ publishes; presumed_producing then
--                 applies the recency macro to it. Compute both HERE rather than
--                 per-CE: rolling the status up first and applying recency to the
--                 manufacturer's own span is not the same as asking whether any one CE
--                 qualifies — an entity marked ended can still carry the manufacturer's
--                 most recent model. FALSE IS NOT 'ENDED'; it pools the known-ended with
--                 the unknown-and-not-recent, and unknown is a default nobody set.
--   location_path / country_slug, with n_locations / n_countries : where the manufacturer
--                 was based, at both rungs (both spelled as on `models`). The rungs
--                 resolve INDEPENDENTLY, each NULL when its own disagrees — a maker with
--                 two Chicago-area plants is country_slug 'usa' and location_path NULL,
--                 which answers both questions honestly instead of letting one paper over
--                 the other. Most makers resolve at both, so read location_path first and
--                 fall back to country.
--                 A NULL HAS TWO CAUSES AND THE COUNT SEPARATES THEM: n = 0 is no known
--                 location, n > 1 is a maker genuinely spanning places. Unrecorded vs
--                 recorded-and-plural are opposite states, and the bare NULL conflates
--                 them. Drop to `corporate_entities` to enumerate a plural maker's places
--                 rather than collapse them.
--                 Rolled up over live CEs (_mfr_location), NOT over models like the
--                 counts and span beside them — so a maker with n_models = 0 still
--                 reports the address its CEs carry.
--   website / wikidata_id : the two outbound handles for enriching from outside the
--                 catalog. Both sparse.
--                 Both absent as NULL: the Django model spells an unset website '' and
--                 an unset QID NULL, and `live` folds the difference away.
CREATE OR REPLACE VIEW manufacturers AS
  WITH agg AS (
    SELECT
      manufacturer_id,
      count(*)                                    AS n_models,
      count(*) FILTER (variant_of_id IS NULL)     AS n_nonvariant_models,
      count(year) FILTER (variant_of_id IS NULL)  AS n_dated,
      min(year) FILTER (variant_of_id IS NULL)    AS year_of_first_model,
      max(year) FILTER (variant_of_id IS NULL)    AS year_of_last_model
    FROM models WHERE manufacturer_id IS NOT NULL
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
  FROM live('fc.catalog_manufacturer') mf
  LEFT JOIN agg a           ON a.manufacturer_id = mf.id
  LEFT JOIN _mfr_status s   ON s.manufacturer_id = mf.id
  LEFT JOIN _mfr_location l ON l.manufacturer_id = mf.id;
COMMENT ON VIEW manufacturers IS
  'One row per live manufacturer — identity, home location/country, model counts, the year_of_first_model/year_of_last_model span and the site''s operating_status/presumed_producing verdict. Read location and country each with its n_ count (0 = unknown, >1 = plural), and the span with n_dated.';

-- corporate_entities — one row per live CorporateEntity: the LEGAL entity one level
-- below the manufacturer, the grain `models.corporate_entity_id` actually points at.
-- Reach for it when the question is about a corporate incarnation (D. Gottlieb &
-- Company vs Premier Technology) rather than about the manufacturer you display.
--
--   year_of_first_model / year_of_last_model, and the n_* counts : exactly as on
--                 `manufacturers`, scoped to the one entity.
--   operating_status / presumed_producing : as on `manufacturers`, but for the ONE
--                 incarnation — the stored column, not a rollup. Ask the manufacturer
--                 view unless the incarnation is the subject; that is the grain the
--                 site's verdict is published at. UNKNOWN IS THE COLUMN DEFAULT — most
--                 entities sit on it because nobody has said otherwise, so counting
--                 'ended' is sound and reading anything into the size of the 'unknown'
--                 bucket is not.
--   location_path / country_slug : this incarnation's own place, spelled as on `models`.
--                 The grain to use when a manufacturer spans places — `manufacturers`
--                 collapses those to NULL, while this view keeps each CE's separate.
--                 Both NULL when the CE carries no location, a common state.
--   ipdb_manufacturer_id : IPDB's ManufacturerId, the join key back to an IPDB scrape.
--                 It lives here and `opdb_manufacturer_id` lives on `manufacturers`
--                 because the two source databases split the manufacturer at different
--                 grains.
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
      -- RETIRED on the Django model, whose help_text reads "DEAD FIELD — do not read or
      -- write": a company can incorporate years before its first machine and linger years
      -- after its last, so these answer the wrong question. The rows survive only to keep
      -- the cited claims behind them. Exposing them here would be worse than not having
      -- them, because they sit beside year_of_first_model/year_of_last_model under nearly
      -- the same name and disagree with them on 22 of 35 and 16 of 30 entities.
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
  FROM live('fc.catalog_corporateentity') ce
  LEFT JOIN fc.catalog_manufacturer mf ON mf.id = ce.manufacturer_id
                                      AND mf.status IS DISTINCT FROM 'deleted'
  LEFT JOIN _ce_location cel           ON cel.corporate_entity_id = ce.id
  LEFT JOIN agg a                      ON a.corporate_entity_id = ce.id;
COMMENT ON VIEW corporate_entities IS
  'One row per live corporate entity — the LEGAL entity below the manufacturer, with the same derived span, counts, location and producing verdict as manufacturers, scoped to the one incarnation. operating_status defaults to unknown, so that bucket means unasked, not unknowable.';

-- ═══ REWARDS, THEMES, TAGS — model attributes ═══════════════════════════════
-- rewards — sorted reward-type names per model (only models that have any). Keyed
-- model_id; the reward types are live-filtered but the models are not, so it inherits
-- live/all from whichever model view you join to.
CREATE OR REPLACE VIEW rewards AS
  SELECT rt2.machinemodel_id AS model_id, list_sort(list(rt.name)) AS rewards
  FROM fc.catalog_machinemodel_reward_types rt2
  JOIN reward_types rt ON rt.id = rt2.rewardtype_id
  GROUP BY rt2.machinemodel_id;
COMMENT ON VIEW rewards IS
  'One row per model with any — sorted reward-type NAMES for display, keyed model_id. Pure enrichment; carries no reward-type ids or slugs.';

CREATE OR REPLACE VIEW _live_theme AS SELECT * FROM live('fc.catalog_theme');

-- themes — sorted theme names per model (only models that have any). Keyed model_id like
-- `rewards`, and the canonical home for theme data.
CREATE OR REPLACE VIEW themes AS
  SELECT mt.machinemodel_id AS model_id, list_sort(list(t.name)) AS themes
  FROM fc.catalog_machinemodel_themes mt
  JOIN _live_theme t ON t.id = mt.theme_id
  GROUP BY mt.machinemodel_id;
COMMENT ON VIEW themes IS
  'One row per model with any — sorted theme NAMES for display, keyed model_id. Use model_themes to predicate on a theme, theme_vocab for questions about the vocabulary itself.';

-- ─── Theme vocabulary ───────────────────────────────────────────────────────
-- `themes` above is a per-model DISPLAY list of NAMES — right for enrichment, useless for
-- questions about the vocabulary ITSELF ("which themes are near-duplicates?", "what hangs
-- under fantasy?", "does this alias collide with a live theme?"), which need the slug, the
-- DAG and the aliases. Three views cover that shape, and the gameplay-feature vocabulary
-- below mirrors them one-for-one:
--   <term>_vocab     one row per live term — identity, usage count, DAG, aliases
--   <term>_aliases   alias GRAIN, so you can join and compare on an alias
--   model_<terms>    slug-keyed model↔term grain (the twin of the display list)
-- model_themes — one row per (live model, live theme). The GRAIN twin of `themes`; the
-- display name is in theme_vocab, not here. Direct attachments ONLY, DAG not rolled up: a
-- model tagged `black-magic` does NOT gain `occult`. Resolve ancestors analysis-locally
-- via theme_vocab.parents.
CREATE OR REPLACE VIEW model_themes AS
  SELECT mt.machinemodel_id AS model_id, t.id AS theme_id, t.slug AS theme_slug
  FROM fc.catalog_machinemodel_themes mt
  JOIN _live_theme t ON t.id = mt.theme_id
  WHERE EXISTS (SELECT 1 FROM models s WHERE s.id = mt.machinemodel_id);  -- live subjects
COMMENT ON VIEW model_themes IS
  'One row per (live model, live theme) — the grain twin of themes; predicate and join on theme_slug. Direct attachments only, DAG not rolled up.';

-- theme_aliases — one row per alias of a live theme. GRAIN rather than the flat list in
-- theme_vocab.aliases, because consumers JOIN and COMPARE on an alias — an alias colliding
-- with a live theme's own name is this corpus's dominant defect, and a list column would
-- make every such query unnest first.
CREATE OR REPLACE VIEW theme_aliases AS
  SELECT ta.theme_id, t.slug AS theme_slug, ta.value AS alias
  FROM fc.catalog_themealias ta
  JOIN _live_theme t ON t.id = ta.theme_id;
COMMENT ON VIEW theme_aliases IS
  'One row per alias of a live theme — alias GRAIN, so you can join and compare on one. Values as entered, not normalized.';

-- theme_vocab — one row per live theme: the vocabulary itself.
--   n        : LIVE-model usage count — the "is this theme carrying its weight?" signal.
--              0 for an unused theme (a kept row, not a dropped one: an orphan vocabulary
--              entry is exactly what a cleanup wants to see).
--   parents  : slugs this theme hangs under (a DAG, so several are possible); [] for a
--              root, which much of this corpus is.
--   children : the inverse, off the same table so the two can't disagree.
--   aliases  : alias VALUES flattened for display; use theme_aliases to join on one.
-- Live on BOTH ends of the DAG, and DIRECT edges only — no transitive closure; a caller
-- wanting every descendant writes the recursive CTE analysis-locally.
CREATE OR REPLACE VIEW theme_vocab AS
  WITH usage AS (
    SELECT theme_id, count(*) AS n FROM model_themes GROUP BY theme_id
  ), parents AS (
    SELECT tp.from_theme_id AS theme_id, list_sort(list(p.slug)) AS parents
    FROM fc.catalog_theme_parents tp
    JOIN _live_theme p ON p.id = tp.to_theme_id
    GROUP BY tp.from_theme_id
  ), children AS (
    SELECT tp.to_theme_id AS theme_id, list_sort(list(c.slug)) AS children
    FROM fc.catalog_theme_parents tp
    JOIN _live_theme c ON c.id = tp.from_theme_id
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
  FROM _live_theme t
  LEFT JOIN usage    u ON u.theme_id = t.id
  LEFT JOIN parents  p ON p.theme_id = t.id
  LEFT JOIN children c ON c.theme_id = t.id
  LEFT JOIN aliases  a ON a.theme_id = t.id;
COMMENT ON VIEW theme_vocab IS
  'One row per live theme — the theme VOCABULARY: usage count n, DAG parents/children, aliases. Reach for it when the subject is the themes rather than the models.';

-- tag_vocab — one row per live TAG: the vocabulary behind `tags`. `tags` is
-- keyed by MODEL and answers "what is this tagged"; this is keyed by tag and answers "what
-- tags exist, and how much is each used". Much of the vocabulary is soft-deleted, so check
-- a hardcoded slug against this view before trusting it. Flat, no DAG.
CREATE OR REPLACE VIEW tag_vocab AS
  SELECT
    tg.*,
    -- count(m.id), not the link: the through-row survives its model's soft-delete.
    count(m.id) AS n
  FROM live('fc.catalog_tag') tg
  LEFT JOIN fc.catalog_machinemodel_tags mt ON mt.tag_id = tg.id
  LEFT JOIN fc.catalog_machinemodel m
    ON m.id = mt.machinemodel_id AND m.status IS DISTINCT FROM 'deleted'
  GROUP BY ALL;
COMMENT ON VIEW tag_vocab IS
  'One row per live tag — the tag VOCABULARY with usage count n, the entity twin of model-keyed tags. Flat, no DAG.';

-- tags — sorted list of TAG SLUGS per tagged model (only models with any). Keyed model_id
-- like rewards/themes. SLUGS, not names: unlike those display lists, tags are the
-- classification vocabulary you PREDICATE on (`'widebody' IN tags`). NB `conversion_kit`
-- and re-themes are NOT tags and won't appear here — they're ModelRelationship types.
CREATE OR REPLACE VIEW tags AS
  SELECT mt.machinemodel_id AS model_id, list_sort(list(tg.slug)) AS tags
  FROM fc.catalog_machinemodel_tags mt
  JOIN tag_vocab tg ON tg.id = mt.tag_id
  GROUP BY mt.machinemodel_id;
COMMENT ON VIEW tags IS
  'One row per tagged model — sorted list of tag SLUGS (the stable key you predicate on), keyed model_id. conversion_kit and re-themes are ModelRelationship types, not tags.';

-- ═══ GAMEPLAY FEATURES ══════════════════════════════════════════════════════
CREATE OR REPLACE VIEW _live_gameplay_feature AS SELECT * FROM live('fc.catalog_gameplayfeature');

-- model_gameplay_features — one row per (model, directly-attached gameplay feature) with
-- its optional count. A grain view, NOT a flattened like rewards/themes, because
-- most of these rows carry a count (Flippers x2; Trap Holes x25, the 5x5 bingo card) that
-- flattening would drop. Direct attachments ONLY: the GameplayFeature DAG (2-Ball
-- Multiball under Multiball) is NOT rolled up — resolve parents analysis-locally, as with
-- themes. Predicate and display on feature_slug ('trap-holes', 'flippers'); feature_name
-- is not surfaced.
--   count : the M2M's optional count; NULL for a bare membership. This is the real "how
--           many flippers" signal — the raw scalar flipper_count is near-empty and
--           deliberately not surfaced.
CREATE OR REPLACE VIEW model_gameplay_features AS
  SELECT
    mgf.machinemodel_id AS model_id,
    gf.id               AS feature_id,
    gf.slug             AS feature_slug,
    mgf.count           AS count
  FROM fc.catalog_machinemodelgameplayfeature mgf
  JOIN _live_gameplay_feature gf ON gf.id = mgf.gameplayfeature_id
  WHERE EXISTS (SELECT 1 FROM models s WHERE s.id = mgf.machinemodel_id);  -- live subjects
COMMENT ON VIEW model_gameplay_features IS
  'One row per (live model, gameplay feature) with its optional count (Flippers x2, Trap Holes x25) — the counted grain. Direct attachments only, DAG not rolled up.';

-- ─── Gameplay-feature vocabulary ────────────────────────────────────────────
-- The theme trio's mirror (see the Theme vocabulary block above for the shape).
-- `model_gameplay_features` is already the grain, so only two views are new: the
-- vocabulary and its alias grain.
--
-- The difference from themes is DEPTH. This vocabulary is curated rather than imported and
-- the DAG is genuinely deep — kickback-lanes → right-kickback-lanes →
-- upper-right-kickback-lanes — with interior nodes that carry no models by design.
-- gameplay_feature_aliases — one row per alias of a live feature. GRAIN for the same
-- reason theme_aliases is, here to resolve a source's phrasing ("Autoplunger",
-- "Left-Side Kickback Lane") to the canonical feature.
CREATE OR REPLACE VIEW gameplay_feature_aliases AS
  SELECT ga.feature_id, f.slug AS feature_slug, ga.value AS alias
  FROM fc.catalog_gameplayfeaturealias ga
  JOIN _live_gameplay_feature f ON f.id = ga.feature_id;
COMMENT ON VIEW gameplay_feature_aliases IS
  'One row per alias of a live gameplay feature — alias GRAIN, for resolving a source phrasing ("Autoplunger") to the canonical feature. Not normalized.';

-- gameplay_feature_vocab — one row per live gameplay feature: the vocabulary itself.
-- Columns match theme_vocab exactly; two notes specific to this DAG:
--   n        : ALWAYS read WITH `children`. n=0 on a leaf is an orphan or a detector
--              gone dark; n=0 on a node with children is correct and expected — the
--              models hang off its descendants.
--   parents  : several are possible — an Upper Right Ball Return Gate is both upper
--              and right-side.
CREATE OR REPLACE VIEW gameplay_feature_vocab AS
  WITH usage AS (
    SELECT feature_id, count(*) AS n FROM model_gameplay_features GROUP BY feature_id
  ), parents AS (
    SELECT fp.from_gameplayfeature_id AS feature_id, list_sort(list(p.slug)) AS parents
    FROM fc.catalog_gameplayfeature_parents fp
    JOIN _live_gameplay_feature p ON p.id = fp.to_gameplayfeature_id
    GROUP BY fp.from_gameplayfeature_id
  ), children AS (
    SELECT fp.to_gameplayfeature_id AS feature_id, list_sort(list(c.slug)) AS children
    FROM fc.catalog_gameplayfeature_parents fp
    JOIN _live_gameplay_feature c ON c.id = fp.from_gameplayfeature_id
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
  FROM _live_gameplay_feature f
  LEFT JOIN usage    u ON u.feature_id = f.id
  LEFT JOIN parents  p ON p.feature_id = f.id
  LEFT JOIN children c ON c.feature_id = f.id
  LEFT JOIN aliases  a ON a.feature_id = f.id;
COMMENT ON VIEW gameplay_feature_vocab IS
  'One row per live gameplay feature — the feature VOCABULARY, columns matching theme_vocab. Read n WITH children: n = 0 on an interior node is by design.';

-- _model_target — the facts surfaced for the OTHER end of a relationship edge: identity
-- (incl. the manufacturer's model number), year, genre, reward types, player count,
-- manufacturer and location — what a reviewer uses to tell two models apart. A projection
-- of `models` + `rewards` with columns named target_*, so both edge views pull the whole
-- block via `* EXCLUDE (id)`; add a facet here and both gain it.
CREATE OR REPLACE VIEW _model_target AS
  SELECT
    m.id,
    m.slug                              AS target_slug,
    m.name                              AS target_name,
    m.manufacturer_model_identifier     AS target_manufacturer_model_identifier,
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
  LEFT JOIN rewards rw ON rw.model_id = m.id;

-- ═══ MODEL-TO-MODEL RELATIONSHIPS — start with model_edges ══════════════════
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
-- All three follow ONE rule for the far end: an edge KEEPS its row and de-enriches to NULL
-- target_* rather than being dropped. The only LEGITIMATE de-enrich is a typed free-text
-- label (target_label, no catalog model). A resolved-but-de-enriched target (target_id set,
-- target_slug NULL) is a soft-deleted target the app should have protected — an integrity
-- violation catalog_checks flags for both mechanisms, not a normal path.
-- model_edges CONCATENATES the two and does NOT reconcile overlaps: a variant_of FK and a
-- typed edge to the same target are two rows; deciding they're one is analysis-local.
-- ─────────────────────────────────────────────────────────────────────────────

-- model_lineage — variant_of + remake_of + export_edition_of as row-grain edges: one row
-- per (model, edge_kind), 0..1 per kind. The target LEFT JOIN is defensive only — the app
-- blocks soft-deleting a live lineage target, so target_* always enriches here and a
-- de-enriched one means that protection was bypassed (lineage_target_not_live).
--   edge_kind : 'variant_of' | 'remake_of' | 'export_edition_of'
--   target_*  : the origin model — see _model_target
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
    r.relationship_type,
    r.license_status,
    r.target_machine_id        AS target_id,
    NULLIF(r.target_label, '') AS target_label,
    tgt.* EXCLUDE (id)
  FROM fc.catalog_modelrelationship r
  LEFT JOIN _model_target tgt ON tgt.id = r.target_machine_id   -- resolved target, if live
  WHERE EXISTS (SELECT 1 FROM models s WHERE s.id = r.machine_model_id);  -- live subjects only

COMMENT ON VIEW model_relationships IS
  'One row per typed ModelRelationship edge — multi-valued, closed relationship_type and license_status vocabularies, target either a resolved model or a free-text label. A component of model_edges.';
-- model_export_markets — one row per export destination of a live model. NOT part of
-- model_edges: the target is a Location, not a model (the model↔model half of the export
-- story is the export_edition_of lineage FK). The target ladder is OPTIONAL — a country
-- (target_location_id + country columns), a free-text region label (target_label), or
-- neither, the unknown-market row whose existence alone says "built for export". The app
-- restricts location targets to countries (COUNTRY_TARGET_FILTER), so the `countries` join
-- always enriches; a de-enriched one is an integrity violation
-- (export_market_target_not_country).
CREATE OR REPLACE VIEW model_export_markets AS
  SELECT
    em.machine_model_id                 AS model_id,
    em.target_market_location_id        AS target_location_id,
    c.slug                              AS target_country_slug,
    c.name                              AS target_country_name,
    NULLIF(em.target_market_label, '')  AS target_label
  FROM fc.catalog_modelexportmarket em
  LEFT JOIN locations c ON c.id = em.target_market_location_id AND c.is_country
  WHERE EXISTS (SELECT 1 FROM models s WHERE s.id = em.machine_model_id);
COMMENT ON VIEW model_export_markets IS
  'One row per export destination of a live model — the target is a LOCATION, not a model, so this is NOT part of model_edges. The target ladder is optional: a country, a free-text region, or neither.';

-- model_edges — the DEFAULT relationships view: every edge out of a model, lineage and
-- typed, in one row-grain set, so one predicate returns all of a model's edges and none is
-- missed. A UNION ALL over model_lineage + model_relationships.
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
COMMENT ON VIEW model_edges IS
  'One row per model edge, lineage + typed — THE DEFAULT relationships view, and OUTBOUND ONLY. For "is this pair connected?" use model_edges_bidir; hundreds of live models have only an inbound edge and are invisible here.';

-- model_edges_bidir — every edge from BOTH ends. `model_edges` is OUTBOUND ONLY: right for
-- "what does this model point at", silently wrong for "is this pair connected" — hundreds
-- of live models have an inbound edge and no outbound one, so a connectedness test written
-- against model_edges returns a confident false for every one of them. Use this instead:
-- `WHERE model_id = ? AND target_id = ?`, or `WHERE model_id = ?` for a model's full
-- neighbourhood in either direction.
--
-- The mirror does NOT re-point the edge. `relationship_type` always describes the edge AS
-- STATED, because the direction IS the fact: a variant points at its base, and the base is
-- not a variant of the variant. So read the type together with `direction` — and aggregate
-- from `model_edges`, never here, since every edge is counted twice by construction.
--   direction : 'out' (this model states the edge) | 'in' (the other end states it)
--   target_*  : always the FAR end from `model_id`, re-enriched per direction.
-- Label-only typed edges have no model at the far end, so they appear 'out' only.
CREATE OR REPLACE VIEW model_edges_bidir AS
  SELECT 'out' AS direction, * FROM model_edges
  UNION ALL BY NAME
  SELECT
    'in'                AS direction,
    e.target_id         AS model_id,
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

-- ═══ TITLES AND MODEL NUMBERS ═══════════════════════════════════════════════
-- titles — one row per live Title: the entity grain behind `models.title_*`. Reach for
-- it when the Title itself is the subject; read the decoded columns off a model row
-- when you already have one.
--
--   IT IS NOT `title_size` WITH MORE COLUMNS. `title_size` holds only Titles that HAVE
--             a live model; this holds every live Title and reports the rest at
--             `n_models = 0` rather than dropping them. The two agree row-for-row today,
--             so the difference stays invisible until a Title outlives its last model —
--             which soft-deleting the one model of a one-model Title produces at once.
--   franchise / series : the two optional Title groupings, resolved to slug and name.
--             Both sparse by design, and they mean different things: a franchise is the
--             IP (Star Trek, spanning manufacturers and eras), a series is a curated
--             thematic lineage (Eight Ball -> Eight Ball Deluxe). Neither is ingested, so
--             an absent grouping is "not yet curated", never "does not belong".
--             `franchises` / `series` below are the entity views.
--   opdb_id / fandom_page_id : the outbound handles. opdb_id is OPDB's "group" — the
--             Title is the grain OPDB models identity at, so this and `models.opdb_id`
--             are different namespaces and must not be compared.
--   description : SingleModelTitles.md governs how this splits against the model's own
--             description.
CREATE OR REPLACE VIEW titles AS
  SELECT
    t.*,
    f.slug  AS franchise_slug, f.name  AS franchise_name,
    se.slug AS series_slug,    se.name AS series_name,
    COALESCE(tn.n, 0) AS n_models
  FROM live('fc.catalog_title') t
  LEFT JOIN _title_live_n tn         ON tn.title_id = t.id
  LEFT JOIN fc.catalog_franchise f   ON f.id  = t.franchise_id
                                    AND f.status  IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_series se     ON se.id = t.series_id
                                    AND se.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW titles IS
  'One row per LIVE Title — identity, franchise/series grouping and n_models. Unlike title_size it keeps Titles with no live models, at n_models = 0.';

-- franchises / series — the two Title-grouping vocabularies at entity grain. `titles`
-- decodes each onto the Title row; these answer what needs a second view: which groupings
-- EXIST, and which are used by nothing. Both flat, nothing like a themes DAG, and both
-- curator-maintained — which makes `n_titles = 0` the interesting row rather than a
-- defect: a grouping someone created and never attached, invisible from `titles` alone.
CREATE OR REPLACE VIEW franchises AS
  SELECT f.*,
         count(t.id) AS n_titles
  FROM live('fc.catalog_franchise') f
  LEFT JOIN fc.catalog_title t
    ON t.franchise_id = f.id AND t.status IS DISTINCT FROM 'deleted'
  GROUP BY ALL;
COMMENT ON VIEW franchises IS
  'One row per live Franchise — the IP grouping (Star Trek), spanning manufacturers and eras, with n_titles. Curator-maintained, never ingested, so n_titles = 0 is a real state.';

CREATE OR REPLACE VIEW series AS
  SELECT s.*,
         count(t.id) AS n_titles
  FROM live('fc.catalog_series') s
  LEFT JOIN fc.catalog_title t
    ON t.series_id = s.id AND t.status IS DISTINCT FROM 'deleted'
  GROUP BY ALL;
COMMENT ON VIEW series IS
  'One row per live Series — a curated thematic lineage (Eight Ball -> Eight Ball Deluxe), with n_titles. Not the same thing as a Franchise, which is the IP.';

-- title_size — one row per Title with a live model: identity plus n, the count of LIVE
-- models in it (the "alone in its Title?" signal — n = 1; a soft-deleted sibling doesn't
-- keep a model company). The TITLE-keyed form of `models.title_size`. Use it when the
-- Title is the grain you iterate; read the model column when you already have a model row.
CREATE OR REPLACE VIEW title_size AS
  SELECT tn.title_id, t.slug AS title_slug, t.name AS title_name, tn.n
  FROM _title_live_n tn
  LEFT JOIN fc.catalog_title t ON t.id = tn.title_id;
COMMENT ON VIEW title_size IS
  'One row per Title with a live model — Title identity plus n, the live model count. The "alone in its Title?" signal is n = 1.';

-- model_number_collisions — one row per (manufacturer, model number) that more than one
-- live model claims: `models.manufacturer_model_identifier`'s non-uniqueness made
-- queryable, so an analysis matching a source's model number can see up front whether its
-- key resolves. `n_titles` is the cheap discriminator: 1 means the collision is contained
-- in one Title and is probably a legitimate catalog split; >1 wants a look. Reported,
-- never judged.
--
-- EXACT numbers only, no stem matching. A suffix convention is a fact about ONE
-- manufacturer, not about the column — Bally's trailing letter marks a different game
-- (#634 'Fun Way' vs #634-A 'Lotta Fun'), which holds for nobody else. An analysis needing
-- loose matching should own the rule and record which manufacturer it holds for.
CREATE OR REPLACE VIEW model_number_collisions AS
  SELECT
    manufacturer_id,
    max(manufacturer_slug)          AS manufacturer_slug,
    max(manufacturer_name)          AS manufacturer_name,
    manufacturer_model_identifier   AS model_number,
    count(*)                        AS n,
    count(DISTINCT title_id)        AS n_titles,
    list_sort(list(id))             AS model_ids,
    list_sort(list(label))          AS labels
  FROM models
  WHERE manufacturer_id IS NOT NULL AND manufacturer_model_identifier IS NOT NULL
  GROUP BY manufacturer_id, manufacturer_model_identifier
  HAVING count(*) > 1;
COMMENT ON VIEW model_number_collisions IS
  'One row per (manufacturer, model number) claimed by more than one live model — exact numbers only. n_titles = 1 is usually a legitimate catalog split, not bad data.';

-- ═══ PEOPLE AND CREDITS ════════════════════════════════════════════════════
-- credits — one row per credit: a Person, in a CreditRole, on a subject. THE grain, and
-- the single definition of a live credit — `people` and `credit_roles` below are both
-- aggregates OF THIS VIEW, so the three cannot disagree about the population.
--
--   THE SUBJECT IS POLYMORPHIC, and the minority half is the trap. A Credit hangs off a
--             MachineModel XOR a Series (`catalog_credit_model_xor_series`), and the
--             Series half is tiny — so a model-only grain would look complete, agree with
--             every spot check and silently miss a whole KIND of credit. Both halves are
--             spelled the way `claims` spells its subject types —
--             'catalog.machinemodel' / 'catalog.series' — so a join across needs no
--             translation. For the model half use `model_credits`, not a subject_type
--             predicate you wrote yourself.
--   subject_name : the subject's plain name. `models.label` is the disambiguated form
--             ("Name (Manufacturer Year)"), one join from `model_credits.model_id`.
--   provenance: Credit is the compound claim `claim_identity_parts` exists for. Its
--             claim_key names two entities (`credit|person:100|role:4`), so
--             `claims.ref_id` is NULL and there is no single-column join — go `claims`
--             (subject_type/subject_id, field_name = 'credit') → `claim_identity_parts`,
--             once per part.
CREATE OR REPLACE VIEW credits AS
  SELECT
    c.id                                        AS credit_id,
    -- Every subject_* column reads off the SAME joined row, never the raw FK columns, so
    -- they cannot end up describing two different subjects.
    CASE WHEN m.id IS NOT NULL THEN 'catalog.machinemodel'
         ELSE 'catalog.series' END              AS subject_type,
    COALESCE(m.id,   s.id)                      AS subject_id,
    COALESCE(m.slug, s.slug)                    AS subject_slug,
    COALESCE(m.name, s.name)                    AS subject_name,
    c.person_id, p.slug AS person_slug, p.name AS person_name,
    c.role_id,   r.slug AS role_slug,   r.name AS role_name
  -- Reads the PHYSICAL tables, not `models` / `series` — the one place this file allows a
  -- second spelling of live, because `credit_subject_not_live` resolves every subject
  -- against those views and fires the moment the two disagree.
  FROM fc.catalog_credit c
  JOIN fc.catalog_person p     ON p.id = c.person_id
                              AND p.status IS DISTINCT FROM 'deleted'
  JOIN fc.catalog_creditrole r ON r.id = c.role_id
                              AND r.status IS DISTINCT FROM 'deleted'
  -- Two LEFT JOINs plus "at least one resolved", not two UNIONed branches: exactly one
  -- side of the XOR can resolve, so the WHERE keeps the row on either and drops it when
  -- the side it names is dead.
  LEFT JOIN fc.catalog_machinemodel m ON m.id = c.model_id
                                     AND m.status IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_series s       ON s.id = c.series_id
                                     AND s.status IS DISTINCT FROM 'deleted'
  WHERE m.id IS NOT NULL OR s.id IS NOT NULL;
COMMENT ON VIEW credits IS
  'One row per credit (person, role, live subject) — the credit GRAIN, and the definition people/credit_roles count. Subject is a model XOR a series, decoded into subject_type/id/slug/name; model_credits is the model half.';

-- model_credits — the model-attached half of `credits`, keyed model_id to join and
-- model_slug to emit (the same move `model_claims` is on the provenance side). A handful
-- of credits hang off a Series instead and are reachable only from `credits`, so a total
-- taken here is not a total.
CREATE OR REPLACE VIEW model_credits AS
  SELECT c.*, c.subject_id AS model_id, c.subject_slug AS model_slug
  FROM credits c
  WHERE c.subject_type = 'catalog.machinemodel';
COMMENT ON VIEW model_credits IS
  'One row per credit on a LIVE machine model, keyed model_id to join and model_slug to emit — the model half of credits; Series-attached credits appear only there.';

-- credit_roles — the credit-role vocabulary (designer, artist, …) at entity grain with
-- usage. The role-keyed counterpart to `people`; `credits` is where either goes to say
-- WHICH machine.
-- count(c.credit_id), never count(*): the LEFT JOIN would count an unused role as 1.
CREATE OR REPLACE VIEW credit_roles AS
  SELECT
    r.*,
    count(c.credit_id) AS n_credits
  FROM live('fc.catalog_creditrole') r
  LEFT JOIN credits c ON c.role_id = r.id
  GROUP BY ALL;
COMMENT ON VIEW credit_roles IS
  'One row per live CreditRole — the credit vocabulary (designer, artist) with n_credits over live subjects. The role-keyed counterpart to people.n_roles; credits is the grain.';

-- people — one row per live Person, with how much of the catalog they are credited on.
-- The entity grain behind `person_aliases`.
--
--   n_credits : rows of `credits` — model- and series-attached together. Nearly but not
--             exactly n_credited_models, and treating either as the other drops the
--             series credits.
--   n_credited_models : distinct LIVE MODELS, hence the subject_type filter rather than a
--             count of subject_id: Model and Series pks are separate namespaces that
--             overlap freely, so an undistinguished count merges a series into the model
--             sharing its number.
--   n_roles : distinct roles held. A person credited as designer and artist on one machine
--             has n_credits = 2, n_credited_models = 1, n_roles = 2.
--   birth_year / death_year : claim-resolved biography, all but empty. The month and day
--             fields exist on the model and are entirely unpopulated, so the year is the
--             full precision on offer.
CREATE OR REPLACE VIEW people AS
  WITH agg AS (
    SELECT
      person_id,
      count(*)                AS n_credits,
      count(DISTINCT CASE WHEN subject_type = 'catalog.machinemodel'
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
  FROM live('fc.catalog_person') p
  LEFT JOIN agg a ON a.person_id = p.id;
COMMENT ON VIEW people IS
  'One row per live Person — identity, birth/death year and credit counts over live subjects. Counts only: `credits` is the grain that says WHICH models.';

-- ═══ ALIASES & ABBREVIATIONS — matching source wording ══════════════════════
-- Every alias view: one row per alias of a live parent, keyed by the parent's stable slug
-- (location_aliases uses location_path — Location slugs are parent-scoped). Values are
-- stored AS ENTERED, mixed case included; whether 'Playing Cards' should match
-- 'playing-cards' is the consuming analysis's call, and name_norm(alias) is the usual
-- starting point. location_aliases, theme_aliases and
-- gameplay_feature_aliases sit beside their vocabularies above.

CREATE OR REPLACE VIEW reward_type_aliases AS
  SELECT ra.reward_type_id, rt.slug AS reward_type_slug, ra.value AS alias
  FROM fc.catalog_rewardtypealias ra
  JOIN reward_types rt ON rt.id = ra.reward_type_id;
COMMENT ON VIEW reward_type_aliases IS
  'One row per alias of a live reward type — alias GRAIN, for resolving a payout phrasing to the modelled type.';

CREATE OR REPLACE VIEW manufacturer_aliases AS
  SELECT ma.manufacturer_id, mf.slug AS manufacturer_slug, ma.value AS alias
  FROM fc.catalog_manufactureralias ma
  JOIN manufacturers mf ON mf.id = ma.manufacturer_id;
COMMENT ON VIEW manufacturer_aliases IS
  'One row per alias of a live manufacturer — alias GRAIN, for resolving a source name (native-script, accented, trade name) to the canonical Manufacturer.';

-- Corporate entity, not manufacturer: the legal entity below the manufacturer. An alias
-- resolved here may be finer-grained than the manufacturer used for grouping.
CREATE OR REPLACE VIEW corporate_entity_aliases AS
  SELECT ca.corporate_entity_id, ce.slug AS corporate_entity_slug, ca.value AS alias
  FROM fc.catalog_corporateentityalias ca
  JOIN fc.catalog_corporateentity ce
    ON ce.id = ca.corporate_entity_id AND ce.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW corporate_entity_aliases IS
  'One row per alias of a live corporate entity — alias GRAIN. The LEGAL entity, one level finer than manufacturer_aliases.';

CREATE OR REPLACE VIEW person_aliases AS
  SELECT pa.person_id, p.slug AS person_slug, pa.value AS alias
  FROM fc.catalog_personalias pa
  JOIN fc.catalog_person p
    ON p.id = pa.person_id AND p.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW person_aliases IS
  'One row per alias of a live person — alias GRAIN, carrying aka/maiden forms; resolve a credit name here before treating it as a new Person.';

-- ── Abbreviations ───────────────────────────────────────────────────────────
-- Abbreviations are community shorthand, NOT alternate names — use them for forum or
-- marketplace prose and keep them out of name-alias matching. The value column is named
-- `abbreviation` to keep the two families distinct.
CREATE OR REPLACE VIEW model_abbreviations AS
  SELECT ab.machine_model_id AS model_id, m.slug AS model_slug, ab.value AS abbreviation
  FROM fc.catalog_modelabbreviation ab
  JOIN models m ON m.id = ab.machine_model_id;
COMMENT ON VIEW model_abbreviations IS
  'One row per community abbreviation of a live model (LTBR, ACDC Prem VE) — shorthand, NOT an alternate name; use it for forum/marketplace prose.';

CREATE OR REPLACE VIEW title_abbreviations AS
  SELECT ab.title_id, t.slug AS title_slug, ab.value AS abbreviation
  FROM fc.catalog_titleabbreviation ab
  JOIN fc.catalog_title t
    ON t.id = ab.title_id AND t.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW title_abbreviations IS
  'One row per community abbreviation of a live Title — the Title-grain twin of model_abbreviations.';

-- ═══ DOMAIN VOCABULARY — what a slug MEANS ══════════════════════════════════
-- The catalog's controlled vocabularies (game formats, cabinets, production statuses, …)
-- are DEFINED in docs/DomainModel.md — what separates `one-off` from `unreleased`,
-- `shuffle` from `rolldown`. The DB carries only the slug and display name, so an analyst
-- filtering on a slug has to go there for the meaning. `domain_vocab` parses those
-- definition bullets at query time — no build step, always current — so the doc stays the
-- only place a domain fact is written.
--
-- The doc shape relied on: a bullet `- \`slug\`: definition`, grouped by the nearest
-- preceding `**EntityName**` lead-in, else by the `##`/`###` heading. The group is
-- snake-stripped to a dim name (`Production Status` -> `productionstatus`), which is
-- exactly the catalog table suffix, so the doc->table mapping needs no hand-maintained
-- list. Renaming a heading detaches every bullet under it — which surfaces at once as
-- undocumented_vocab for every slug in that vocabulary plus stale_vocab_dim. Loud, never
-- silent.
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
-- The group window must run over EVERY line, with the bullet filter applied OUTSIDE it:
-- filtering first strips the heading rows the window reads, every group comes back NULL
-- and the view silently returns nothing.
-- Restricted to groups naming a real fc.catalog_<dim> table, which keeps non-vocabulary
-- bullet lists out ("Fields Common to All Catalog Entities" uses this exact shape). The
-- test is mechanical, so a newly documented vocabulary needs no edit here — it needs a
-- _dim_vocab entry, and unmapped_vocab_dim says so.
CREATE OR REPLACE VIEW domain_vocab AS
  SELECT dim, slug, definition, doc_line FROM (
    SELECT lower(replace(last_value(group_raw IGNORE NULLS) OVER (ORDER BY i), ' ', '')) AS dim,
           regexp_extract(t, '^- `([a-z0-9-]+)`: ', 1)    AS slug,
           regexp_extract(t, '^- `[a-z0-9-]+`: (.*)$', 1) AS definition,
           t, i AS doc_line
    FROM _dm_marked)
  WHERE regexp_matches(t, '^- `[a-z0-9-]+`: ')
    AND dim IN (SELECT replace(table_name, 'catalog_', '')
                FROM duckdb_tables() WHERE database_name = 'fc');
COMMENT ON VIEW domain_vocab IS
  'One row per controlled-vocabulary term defined in docs/DomainModel.md — dim, slug and the prose definition, parsed from the doc at query time. Join it to a vocabulary view to read what a slug MEANS; the doc stays the only place domain semantics are written.';

-- ═══ ENTITY SUBJECTS — resolving a polymorphic reference ════════════════════
-- entity_subjects — one row per catalog entity of ANY type, keyed as a polymorphic
-- reference names it: `(subject_type, subject_id)`, the type spelled as a Django content
-- type. The `subject_` prefix makes the join `USING (subject_type, subject_id)` and
-- lands the columns under the names `claims` and `credits` already use.
--
-- `subject_public_id`, NOT a slug: it is whatever the model declares as
-- `public_id_field`, which is `slug` for twenty of the twenty-one and `location_path`
-- for Location. Naming it for the majority would make it silently ambiguous on the one
-- exception, where several live places share the slug `victoria`.
--
-- `catalog` is the whole set: a claim subject is a `ClaimControlledModel`, and every one
-- of those lives in that app. The provenance entities `_entity_view` also names (Actor,
-- ChangeSet, Source) are never a subject.
--
-- ADDING A CATALOG ENTITY MEANS ADDING A BRANCH. SQL cannot iterate table names, so this
-- is a hand-written list; forget one and `unresolved_claim_subject` fires on the first
-- claim about it. `slug`/`name`/`status` exist on every branch by construction —
-- `LinkableModel` requires `name`, and the entity set is derived on the other two.
--
-- NOT LIVE-FILTERED, matching `claims`, the consumer it exists for: dropping a
-- soft-deleted row would turn a retired subject into an unresolvable one. Predicate on
-- `subject_status`.
CREATE OR REPLACE VIEW entity_subjects AS
  SELECT
    subject_type,
    id        AS subject_id,
    public_id AS subject_public_id,
    name      AS subject_name,
    status    AS subject_status
  FROM (
              SELECT 'catalog.machinemodel'  AS subject_type, id, slug AS public_id, name, status FROM fc.catalog_machinemodel
    UNION ALL SELECT 'catalog.title',            id, slug, name, status FROM fc.catalog_title
    UNION ALL SELECT 'catalog.manufacturer',     id, slug, name, status FROM fc.catalog_manufacturer
    UNION ALL SELECT 'catalog.corporateentity',  id, slug, name, status FROM fc.catalog_corporateentity
    UNION ALL SELECT 'catalog.person',           id, slug, name, status FROM fc.catalog_person
    -- location_path, not slug: a Location's slug is unique only within its parent, so it
    -- is not an identifier. `public_id_field` on the model says the same.
    UNION ALL SELECT 'catalog.location',         id, location_path, name, status FROM fc.catalog_location
    UNION ALL SELECT 'catalog.franchise',        id, slug, name, status FROM fc.catalog_franchise
    UNION ALL SELECT 'catalog.series',           id, slug, name, status FROM fc.catalog_series
    UNION ALL SELECT 'catalog.creditrole',       id, slug, name, status FROM fc.catalog_creditrole
    UNION ALL SELECT 'catalog.tag',              id, slug, name, status FROM fc.catalog_tag
    UNION ALL SELECT 'catalog.theme',            id, slug, name, status FROM fc.catalog_theme
    UNION ALL SELECT 'catalog.gameplayfeature',  id, slug, name, status FROM fc.catalog_gameplayfeature
    UNION ALL SELECT 'catalog.rewardtype',       id, slug, name, status FROM fc.catalog_rewardtype
    UNION ALL SELECT 'catalog.gameformat',       id, slug, name, status FROM fc.catalog_gameformat
    -- The seven taxonomy dims: slug-only on `models`, but a patch edits them like any
    -- other entity, so they are subjects like any other.
    UNION ALL SELECT 'catalog.cabinet',          id, slug, name, status FROM fc.catalog_cabinet
    UNION ALL SELECT 'catalog.displaytype',      id, slug, name, status FROM fc.catalog_displaytype
    UNION ALL SELECT 'catalog.displaysubtype',   id, slug, name, status FROM fc.catalog_displaysubtype
    UNION ALL SELECT 'catalog.system',           id, slug, name, status FROM fc.catalog_system
    UNION ALL SELECT 'catalog.productionstatus', id, slug, name, status FROM fc.catalog_productionstatus
    UNION ALL SELECT 'catalog.technologygeneration',    id, slug, name, status FROM fc.catalog_technologygeneration
    UNION ALL SELECT 'catalog.technologysubgeneration', id, slug, name, status FROM fc.catalog_technologysubgeneration
  );
COMMENT ON VIEW entity_subjects IS
  'One row per catalog entity of ANY type, keyed (subject_type, subject_id) the way a polymorphic reference names it — public id, name and status for resolving a claim, changeset or patch entry subject without branching on its type. NOT live-filtered; predicate on subject_status.';

-- ═══ RUN WATERMARK ══════════════════════════════════════════════════════════
-- analysis_context — the input watermark for a run, printed by every runner above the
-- results. Enough identity to tell "same query, newer catalog" apart from a broken
-- reproduction: a query is reproducible, but its RESULTS only are when this row matches.
--   migrations_applied / latest_migration : the schema point — count + newest name, not
--       the raw max(id) insertion sequence (which is neither a head nor comparable).
--   latest_patch / patch_fingerprint : the newest SUCCESSFULLY-applied data patch and its
--       content hash, filtered to status='success' with a non-null patch_id so a
--       failed/running/interactive ingest can't misreport it.
--   latest_changeset : catches interactive edits — the drift a patch id can't see.
-- The schema point, the patch point and the changeset point belong in ONE row, which is
-- why the provenance facts sit here. `provenance_context` carries that layer's counts and
-- does not restate these; read the two together.
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
    (SELECT max(id) FROM fc.provenance_changeset) AS latest_changeset,
    (SELECT imported_at FROM fc._import_stamp)    AS snapshot_imported_at;
COMMENT ON VIEW analysis_context IS
  'One row — the input watermark: DuckDB version, live model count, migration point, latest successful patch + fingerprint, latest changeset id, and when the catalog was imported. Printed by every analysis run.';

-- ═══ PROVENANCE — who said so (provenance.sql) ══════════════════════════════
-- The attribution and citation layer — claims, ingest sources, ingest runs, citation
-- sources. Its own file, `.read` here so "the foundation" stays ONE `.read` line for every
-- consumer, sister repos included.
.read scripts/analysis/provenance.sql

-- ═══ DATA PATCHES — what our own patches did (data_patches.sql) ═════════════
-- The patch lens on the provenance layer: which patch asserted a fact, which retracted
-- one, and what evidence each data patch entry recorded.
.read scripts/analysis/data_patches.sql
