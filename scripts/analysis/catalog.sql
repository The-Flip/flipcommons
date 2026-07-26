-- Catalog analysis foundation — shared, reusable decode layer over the live DB.
--
-- `.read` this from any analysis file to get a connected, decoded
-- catalog. It ATTACHes backend/db.sqlite3 READ-ONLY and defines a small set of
-- clean analytical views over the awkward physical schema (JSON extra_data,
-- the model -> corporate_entity -> manufacturer label chain, reward M2M). Every
-- analysis wants these, so they live here instead of being re-derived in each one.
--
-- Run scripts from the REPO ROOT: both the ATTACH path below and the `.read`
-- that pulls this file in are resolved relative to the current directory.
--
--     duckdb -init <analysis>.sql :memory: "FROM <a_view> LIMIT 5;"
--
-- Convention: an UNPREFIXED view name is public API you may build on and query;
-- a `_underscore` name is a private helper, not meant to be consumed directly.
-- See scripts/analysis/README.md for the full template, and EDITING.md before
-- changing THIS file — what belongs down here, and the two harnesses that verify it.
--
-- Mostly views, plus a few MACROS (the name-normalization block below). A macro is
-- admitted only when it encodes a decode or a mechanical transform that more than one
-- analysis needs; policy an analysis should choose for itself stays analysis-local. Note
-- macros are invisible to catalog_checks' generated column sweep — it walks views —
-- so each one carries a data-independent smoke check there instead.

INSTALL sqlite;
LOAD sqlite;
ATTACH IF NOT EXISTS 'backend/db.sqlite3' AS fc (TYPE sqlite, READ_ONLY);

-- Catalog records are soft-deleted (RecordLifecycle.md): a record is live unless
-- its resolved `status` is 'deleted'. Read APIs treat soft-deleted rows as
-- not-found, so `models` (and everything built on it) is LIVE-ONLY by default —
-- the semantics an analysis almost always wants. Reach for `all_models` only when
-- you specifically need the deleted rows too; it carries the same `status` column.

-- ═══ NAME NORMALIZATION — macros for comparing names across records ═════════
-- Comparing a catalog name against another record's — a source's game title, a
-- sibling model, an alias — needs a normalized key, and every analysis doing it was
-- writing its own. Two copies drift, so the mechanics live here. They are split at the
-- one clause that is a JUDGMENT rather than a mechanic, so an analysis picks deliberately
-- instead of inheriting:
--
--   name_norm         fold Latin diacritics, lowercase, collapse every run of
--                     non-letter/non-digit to one space, trim. Nothing that
--                     distinguishes two games survives in punctuation or case.
--                     Diacritic folding is FOR the cross-source case: sources disagree
--                     about accents on the same name ('München' / 'Munchen'), and
--                     folding is what makes those match. The character class is
--                     Unicode-aware (\p{L}\p{N}), NOT [a-z0-9] — an ASCII-only class
--                     treats every non-ASCII letter as punctuation, which does not just
--                     lose the letter, it invents a word break ('Ätomik' -> 'tomik')
--                     and collapses a wholly non-Latin name to the EMPTY string, where
--                     it would then match every other such name. This is not
--                     hypothetical: 'Pokémon' keyed as 'pok mon' and 'Competición
--                     Penalty' as 'competici n penalty' — a couple of dozen model
--                     names, mostly the Spanish-maker cohort that the export and
--                     bingo campaigns work in.
--                     Known limits, both preferable to the word-break they replace:
--                     ordinal indicators survive as letters ('1ª División' ->
--                     '1ª division', so a source writing '1a' will not match), and
--                     strip_accents also folds Japanese dakuten/handakuten (バ and パ
--                     onto ハ), so distinct kana strings can share a key.
--   name_strip_paren  drop ONE trailing parenthetical. This one CUTS BOTH WAYS. It is
--                     what lets an export edition find its original ('On Beam (Italy)'
--                     -> 'On Beam'); it is also what collapses 'KISS (Limited Edition)'
--                     onto 'KISS'. An analysis using it should record whether a match
--                     was exact or needed the strip, and let a reviewer weigh it.
--   name_key          the composition, for the common case.
--
-- What is deliberately NOT here: plural collapsing, stopword removal, token-subset
-- matching, edit distance. Those are matching STRATEGY, they are tuned against a
-- specific corpus, and an analysis that needs one should own it and be able to see it.
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

-- ═══ MODELS — the spine; start here ═════════════════════════════════════════
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

-- _title_live_n — live models per Title, read straight off the physical table rather
-- than off `models`, because `all_models` consumes it and the other direction would be
-- circular. The public `title_size` view is a projection of this, so the two cannot
-- disagree about what a Title's size is.
CREATE OR REPLACE VIEW _title_live_n AS
  SELECT title_id, count(*) AS n
  FROM fc.catalog_machinemodel
  WHERE status IS DISTINCT FROM 'deleted'
  GROUP BY title_id;

-- _namesake_live_n — live models per name_key. Read the physical table because
-- all_models consumes this view; reading models would be circular. name_key deliberately
-- groups trailing-parenthetical variants: over-counting abstains, while under-counting
-- can produce a confident wrong match.
CREATE OR REPLACE VIEW _namesake_live_n AS
  SELECT name_key(name) AS name_key, count(*) AS n
  FROM fc.catalog_machinemodel
  WHERE status IS DISTINCT FROM 'deleted'
  GROUP BY name_key(name);

-- all_models — every MachineModel, live or deleted. Column names/types are in the
-- SELECT below (`analysis describe all_models` prints them live); these notes cover
-- only what ISN'T obvious.
-- Convention throughout: predicate and join on ids/slugs, display the names.
--   title_* : the model's Title — the spine of the hierarchy (every model has one;
--             the FK is NOT NULL). title_id/title_slug/title_name decoded inline so
--             title-mate analyses read identity off the model row instead of reaching
--             for catalog_title.
--   title_size : how many LIVE models share this model's Title — the same number the
--             `title_size` VIEW carries, projected onto the model row so the "alone in
--             its Title?" test is `title_size = 1` instead of a correlated subquery.
--             The view is the title-keyed form and adds Title identity; this is the
--             model-keyed one. Deliberately the raw count and not an `alone_in_title`
--             flag: n = 1 is the caller's threshold to pick, and other analyses want
--             n = 2 or n > 1. Always >= 1 on `models`; can be 0 on `all_models`, for a
--             deleted model whose Title has no live models left.
--   namesake_count : LIVE models sharing this model's `name_key`, including itself.
--             1 means unique; greater than 1 is ambiguous. Uses name_key, so trailing
--             parenthetical variants count together. Always >= 1 on `models`; can be 0
--             on `all_models` when no live model carries a deleted model's name key.
--             See README.md#matching-source-records-to-models for the procedure.
--   status  : 'active' | 'deleted' | NULL — live is anything but 'deleted'.
--   manufacturer_model_identifier : the MAKER's own model number (Gottlieb '654',
--             Stern 'PINBALL I-00M1 * JURAS. PARK PRO'). NOT unique — and not unique
--             paired with manufacturer_id either, for two different reasons: makers
--             number independently from 1 (low integers collide across makers), AND the
--             catalog splits finer than they numbered, so one number spans several
--             of our models — within a Title (Gottlieb 409 = Cleopatra + Cleopatra
--             (EM)) or across Titles for a re-theme family (Williams 394 = Zodiac +
--             Planets). Some collisions are just bad data (Bally 868 = Safari 1969 +
--             Mysterian 1982). GROUP BY (manufacturer_id, identifier) before
--             treating it as an identity. NULL on most live models.
--   year / month : the release date, as a precision ladder — `catalog_machinemodel_
--             month_requires_year` means a NULL month is "dated to the year", never a
--             month lost from a fuller date. Roughly two thirds of live models carry
--             one. Nothing above the year is modelled, so a model released in a named
--             quarter or season arrives here as a month or as nothing.
--   maker   : manufacturer_name is the canonical maker (Manufacturer.name via
--             corporate_entity) — display/group by it.
--   location: where the MAKER was based, model -> corporate_entity -> location. This
--             is the maker's ORIGIN, NOT an export-market destination — those are
--             `model_export_markets`. location_path ('usa/il/chicago') is the most-
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
--             `status` column. The subgeneration/subtype dims are mostly NULL today.
--   variant_of_id / remake_of_id / export_edition_of_id : bare self-FKs to the
--             origin model — the `model_lineage` view expands them (see its
--             "two homes" note).
--   source free-text : ipdb_notes, ipdb_notable_features (prose) and opdb_features
--             (VARCHAR[], empty never NULL; 'Export edition', 'Cocktail', …) are the
--             fields the product doesn't surface. Mining them is common analysis
--             work, so they're first-class columns, not hand-rolled json_extract.
--   NOT surfaced : the extra_data long tail (opdb.keywords — use `themes` —
--             ipdb.marketing_slogans, opdb.common_name, …). Promote one the day an
--             analysis needs it; that's a single line here.
--   label   : "Name (Manufacturer Year)", CE name then '?' as fallbacks; year
--             omitted if unknown.
CREATE OR REPLACE VIEW all_models AS
  SELECT
    m.id, m.name, m.slug,
    m.title_id, t.slug AS title_slug, t.name AS title_name,
    COALESCE(tn.n, 0) AS title_size,
    COALESCE(nk.n, 0) AS namesake_count,
    m.variant_of_id, m.remake_of_id, m.export_edition_of_id,
    m.opdb_id, m.ipdb_id, m.manufacturer_model_identifier,
    m.year, m.month, m.player_count,
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
  -- Each dim join is LIVE-FILTERED. Every dimension a model points at is soft-deleted
  -- independently of the model, so a deleted dim DE-ENRICHES TO NULL rather than being
  -- reported as though it were current — the same contract the edge views follow for a
  -- dead target, and for the same reason: showing a retired value with no signal that
  -- it is retired is the "right data, read the wrong way" failure this layer exists to
  -- prevent. It should never bite (the FKs are PROTECT and the soft-delete walker
  -- blocks deleting a row an active entity references), and model_dim_not_live fires
  -- if it ever does, so the NULL is never left unexplained.
  FROM fc.catalog_machinemodel m
  LEFT JOIN fc.catalog_title t             ON t.id  = m.title_id
                                          AND t.status  IS DISTINCT FROM 'deleted'
  LEFT JOIN _title_live_n tn               ON tn.title_id = m.title_id
  LEFT JOIN _namesake_live_n nk            ON nk.name_key = name_key(m.name)
  LEFT JOIN fc.catalog_corporateentity ce ON ce.id = m.corporate_entity_id
                                          AND ce.status IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_manufacturer mf     ON mf.id = ce.manufacturer_id
                                          AND mf.status IS DISTINCT FROM 'deleted'
  LEFT JOIN _ce_location cel               ON cel.corporate_entity_id = m.corporate_entity_id
  LEFT JOIN fc.catalog_gameformat gf       ON gf.id = m.game_format_id
                                          AND gf.status IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_technologygeneration    tg  ON tg.id  = m.technology_generation_id
                                          AND tg.status  IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_technologysubgeneration tsg ON tsg.id = m.technology_subgeneration_id
                                          AND tsg.status IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_displaytype             dt  ON dt.id  = m.display_type_id
                                          AND dt.status  IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_displaysubtype          dst ON dst.id = m.display_subtype_id
                                          AND dst.status IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_system                  sys ON sys.id = m.system_id
                                          AND sys.status IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_cabinet                 cab ON cab.id = m.cabinet_id
                                          AND cab.status IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_productionstatus        ps  ON ps.id  = m.production_status_id
                                          AND ps.status  IS DISTINCT FROM 'deleted';
COMMENT ON VIEW all_models IS
  'One row per MachineModel, live AND deleted — the escape hatch; filter on status yourself. Use models unless you specifically want the deleted rows.';

-- models — live models only. The default view; build analyses on this.
CREATE OR REPLACE VIEW models AS
  SELECT * FROM all_models WHERE status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW models IS
  'One row per LIVE MachineModel — the default view; build analyses on this.';

-- ═══ DIMENSIONS — what a model points at ════════════════════════════════════
-- locations — one row per live Location, at EVERY level. THE ENTITY; `countries` below
-- is a projection over it and not a peer, which is why it is defined from this view
-- rather than beside it. A country is simply a Location with no parent — there is no
-- separate country table, and treating the two as different things is the mistake this
-- ordering exists to prevent.
--
--   location_path : the stable key ('usa/il/chicago'), and the one to join on.
--             `slug` is unique only WITHIN a parent — there is more than one 'victoria'
--             in the world — so a join on slug silently merges places. The path is also
--             the hierarchy: `country_slug` is its first segment, and descendants of a
--             place are the rows whose path starts with its path plus '/'.
--   location_type : the level, and it is a 10-value open vocabulary, not a 3-level
--             ladder — country, state, province, department, community, region,
--             prefecture, constituent_country, district, city. Only `country` is
--             structurally guaranteed (it is exactly the parentless rows); the rest
--             reflect how each country subdivides itself, so any analysis that assumes
--             country/state/city will silently drop the 57 live places that are none of
--             those — provinces, departments, communities, prefectures and the rest.
--             Predicate on path depth when you mean depth.
--   code / short_name / divisions : sparse by construction. `code` is the subdivision's
--             own code (VIC, WA) and is empty on every country and every city;
--             `divisions` is populated on countries alone (all 22), naming how that
--             country subdivides; `short_name` on 2 rows. None is a general-purpose
--             identifier — read them at the level that carries them.
--   n_corporate_entities : live corporate entities based here, DIRECTLY — a country
--             does not inherit the count of its cities. Use the location_path prefix
--             for a rolled-up figure, deliberately not precomputed because the rollup a
--             caller wants (this place, or this place and below) is theirs to choose.
CREATE OR REPLACE VIEW locations AS
  WITH ce_n AS (
    SELECT cel.location_id, count(*) AS n
    FROM fc.catalog_corporateentitylocation cel
    JOIN fc.catalog_corporateentity ce
      ON ce.id = cel.corporate_entity_id AND ce.status IS DISTINCT FROM 'deleted'
    GROUP BY cel.location_id
  )
  SELECT
    l.id, l.slug, l.name,
    l.location_path,
    split_part(l.location_path, '/', 1)      AS country_slug,
    l.location_type,
    l.parent_id,
    l.parent_id IS NULL                      AS is_country,
    l.code, l.short_name, l.divisions,
    COALESCE(n.n, 0)                         AS n_corporate_entities,
    l.description
  FROM fc.catalog_location l
  LEFT JOIN ce_n n ON n.location_id = l.id
  WHERE l.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW locations IS
  'One row per live Location at EVERY level — the entity; countries is the parentless projection of it. Join on location_path, never slug: slug is unique only within a parent.';

-- countries — the country slice of `locations`: the parentless rows. A projection, not
-- a peer entity — kept as its own view because `models.country_slug` and
-- `target_country_slug` join here for the name, and because joining a region or city by
-- accident is the failure it prevents. Columns are deliberately unchanged from when this
-- read the physical table directly; consumers outside this repo select from it by name.
-- Add an `all_countries` twin the day an analysis needs the deleted rows.
CREATE OR REPLACE VIEW countries AS
  SELECT id, slug, name FROM locations WHERE is_country;
COMMENT ON VIEW countries IS
  'One row per live country (a root Location) — join models.country_slug or target_country_slug here for the name. The parentless projection of locations.';

-- location_aliases — every alias of every live Location, including countries, regions
-- and cities. country_aliases below is the country-only slice. Uses location_path as its
-- stable key because Location.slug is unique only within a parent; country_slug is the
-- path's root segment.
CREATE OR REPLACE VIEW location_aliases AS
  SELECT
    la.location_id,
    l.location_path,
    split_part(l.location_path, '/', 1) AS country_slug,
    la.value                            AS alias
  FROM fc.catalog_locationalias la
  JOIN fc.catalog_location l
    ON l.id = la.location_id AND l.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW location_aliases IS
  'One row per alias of a live Location at any level — alias GRAIN, keyed on location_path because Location.slug is unique only within a parent. country_aliases is the country slice.';

-- country_aliases — the country slice of location_aliases. Joining through countries
-- prevents a region or city alias from resolving as a country.
-- Values are stored as entered and are not normalized here; choose the comparison key
-- in the consuming analysis. name_norm(alias) is the usual starting point.
CREATE OR REPLACE VIEW country_aliases AS
  SELECT la.location_id AS country_id, c.slug AS country_slug, la.value AS alias
  FROM fc.catalog_locationalias la
  JOIN countries c ON c.id = la.location_id;
COMMENT ON VIEW country_aliases IS
  'One row per alias of a live country — alias GRAIN, for resolving a source phrasing ("West Germany", "England") to the modelled country. The country slice of location_aliases.';

-- game_formats — the machine-genre vocabulary (live). Join models.game_format_id to
-- it, or use it to check that a format slug/name you hardcode still exists.
CREATE OR REPLACE VIEW game_formats AS
  SELECT id, slug, name FROM fc.catalog_gameformat
  WHERE status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW game_formats IS
  'One row per live game format — the machine-genre vocabulary; join models.game_format_id, or check that a slug you hardcode still exists.';

-- reward_types — what a machine pays out (live). The VOCABULARY behind the `rewards`
-- name-list: `rewards` tells you which reward types a model has, this tells you what
-- the closed set is, and `reward_type_aliases` resolves a source's phrasing into it.
CREATE OR REPLACE VIEW reward_types AS
  SELECT id, slug, name FROM fc.catalog_rewardtype
  WHERE status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW reward_types IS
  'One row per live reward type — the payout vocabulary behind the rewards name-list; join reward_type_aliases to resolve a source phrasing into it.';

-- manufacturers — one row per live maker: identity, where it was based, how much it
-- made and WHEN. "When was this maker active" turns out to be a question most
-- campaigns ask, usually because a MODEL has no year and its maker's span is the only
-- evidence available — so the derived columns below are the ones worth having.
--
-- Grain note: the physical chain is model -> CorporateEntity -> Manufacturer, and a
-- maker can own more than one CE. This view is at the MANUFACTURER level (the brand you
-- group and display by); drop to models.corporate_entity_* for the legal entity.
--
--   n_models    : live models attributed to this maker, VARIANTS INCLUDED. 0 is normal
--                 — the catalog carries makers it has no models for yet.
--   n_nonvariant_models : the same count with variants excluded — what
--                 /api/export/manufacturers/ publishes as `model_count`. 25 makers
--                 disagree with n_models.
--   n_dated     : non-variant models carrying a year — the year pair's own scope, and
--                 THE denominator for it: a span resting on 2 models is not the same
--                 claim as one resting on 40, and only this column tells them apart.
--   year_of_first_model / year_of_last_model : min/max year over those models — the span
--                 the maker's output occupies, and the same values
--                 /api/export/manufacturers/ publishes under these names.
--                 NOT filtered by any minimum: a 1-model span is reported as exactly
--                 that, n_dated = 1, and the CALLER decides what it will accept
--                 (`WHERE n_dated >= 3` is a reasonable bar, and is the analysis's to
--                 set, not this view's). Gaps are invisible — a maker active 1932-1935
--                 and again 1975-1979 reads as a 47-year span, so treat it as an outer
--                 bound, not a continuous run.
--   country_slug: the maker's home country, and NULL when its models disagree — 3
--                 makers do. n_countries is carried alongside so an ambiguous home is
--                 visible rather than silently collapsed to one of its values.
--   website / wikidata_id : the maker's own site and its Wikidata QID — the two
--                 outbound handles for enriching a maker from outside the catalog,
--                 which is why they are here rather than left to a raw join. Both
--                 sparse: 24 makers have a website and NOTHING carries a QID yet, so
--                 wikidata_id is a `pending` anchor skip that expires the day one does.
--                 An empty website is '' and an absent QID is NULL — the model spells
--                 them differently, and this view does not paper over that.
CREATE OR REPLACE VIEW manufacturers AS
  WITH agg AS (
    SELECT
      manufacturer_id,
      count(*)                                    AS n_models,
      count(*) FILTER (variant_of_id IS NULL)     AS n_nonvariant_models,
      count(year) FILTER (variant_of_id IS NULL)  AS n_dated,
      min(year) FILTER (variant_of_id IS NULL)    AS year_of_first_model,
      max(year) FILTER (variant_of_id IS NULL)    AS year_of_last_model,
      count(DISTINCT country_slug)                AS n_countries,
      CASE WHEN count(DISTINCT country_slug) = 1
           THEN min(country_slug) END             AS country_slug
    FROM models WHERE manufacturer_id IS NOT NULL
    GROUP BY manufacturer_id
  )
  SELECT
    mf.id, mf.slug, mf.name,
    COALESCE(a.n_models, 0)            AS n_models,
    COALESCE(a.n_nonvariant_models, 0) AS n_nonvariant_models,
    COALESCE(a.n_dated, 0)             AS n_dated,
    a.year_of_first_model, a.year_of_last_model,
    COALESCE(a.n_countries, 0) AS n_countries,
    a.country_slug,
    mf.website, mf.wikidata_id
  FROM fc.catalog_manufacturer mf
  LEFT JOIN agg a ON a.manufacturer_id = mf.id
  WHERE mf.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW manufacturers IS
  'One row per live maker — identity, home country, the model counts and the year_of_first_model/year_of_last_model span of its dated models. Span carries no minimum: apply your own n_dated >= k.';

-- corporate_entities — one row per live CorporateEntity: the LEGAL entity one level
-- below the brand, the grain `models.corporate_entity_id` actually points at. Reach
-- for it when the question is about a corporate incarnation (D. Gottlieb & Company vs
-- Premier Technology) rather than about the brand you display.
--
--   year_of_first_model / year_of_last_model, and the n_* counts behind them : exactly
--                 as on `manufacturers`, scoped to the one entity rather than the brand.
--   operating_status : 'ongoing' | 'ended' | 'unknown', and UNKNOWN IS THE COLUMN
--                 DEFAULT — 734 of 777 entities sit on it because nobody has said
--                 otherwise, not because the answer was investigated and lost. Counting
--                 'ended' entities is sound; concluding anything from the size of the
--                 'unknown' bucket is not. Brand-level rollup is ONGOING > UNKNOWN >
--                 ENDED (OperatingStatus.rollup in the model), deliberately not
--                 precomputed here: it is a judgment a consumer should reach for
--                 knowingly.
--   ipdb_manufacturer_id : IPDB's ManufacturerId, the join key back to an IPDB scrape.
--                 This is the level IPDB models makers at, which is why it lives here
--                 and `opdb_manufacturer_id` lives on `manufacturers` — the two source
--                 databases split the maker at different grains.
--   location      : the entity's own place, via _ce_location — the same single-valued
--                 assumption `models.location_path` rests on, stated in its note.
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
    ce.id, ce.slug, ce.name,
    ce.manufacturer_id, mf.slug AS manufacturer_slug, mf.name AS manufacturer_name,
    ce.operating_status,
    ce.ipdb_manufacturer_id,
    cel.location_path, cel.country_slug,
    COALESCE(a.n_models, 0)            AS n_models,
    COALESCE(a.n_nonvariant_models, 0) AS n_nonvariant_models,
    COALESCE(a.n_dated, 0)             AS n_dated,
    a.year_of_first_model, a.year_of_last_model
  FROM fc.catalog_corporateentity ce
  LEFT JOIN fc.catalog_manufacturer mf ON mf.id = ce.manufacturer_id
                                      AND mf.status IS DISTINCT FROM 'deleted'
  LEFT JOIN _ce_location cel           ON cel.corporate_entity_id = ce.id
  LEFT JOIN agg a                      ON a.corporate_entity_id = ce.id
  WHERE ce.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW corporate_entities IS
  'One row per live corporate entity — the LEGAL entity below the brand, with the same derived span and counts as manufacturers. operating_status defaults to unknown, so that bucket means unasked, not unknowable.';

-- ═══ REWARDS, THEMES, TAGS — model attributes ═══════════════════════════════
-- rewards — sorted reward-type names per model (only models that have any). Keyed
-- by id, so it inherits live/all semantics from whichever model view you join to.
-- Live reward types only, like `themes` — a soft-deleted reward type doesn't count.
CREATE OR REPLACE VIEW rewards AS
  SELECT rt2.machinemodel_id AS id, list_sort(list(rt.name)) AS rewards
  FROM fc.catalog_machinemodel_reward_types rt2
  JOIN fc.catalog_rewardtype rt ON rt.id = rt2.rewardtype_id AND rt.status IS DISTINCT FROM 'deleted'
  GROUP BY rt2.machinemodel_id;
COMMENT ON VIEW rewards IS
  'One row per model with any — sorted reward-type NAMES for display, keyed by id. Pure enrichment; carries no ids or slugs.';

-- themes — sorted theme names per model (only models that have any). Keyed by id,
-- like `rewards`, and the canonical home for theme data. Live themes only.
CREATE OR REPLACE VIEW themes AS
  SELECT mt.machinemodel_id AS id, list_sort(list(t.name)) AS themes
  FROM fc.catalog_machinemodel_themes mt
  JOIN fc.catalog_theme t ON t.id = mt.theme_id AND t.status IS DISTINCT FROM 'deleted'
  GROUP BY mt.machinemodel_id;
COMMENT ON VIEW themes IS
  'One row per model with any — sorted theme NAMES for display, keyed by id. Use model_themes to predicate on a theme, theme_vocab for questions about the vocabulary itself.';

-- ─── Theme vocabulary ───────────────────────────────────────────────────────
-- `themes` above is a per-model DISPLAY list of NAMES: right for enrichment, useless
-- for questions about the vocabulary ITSELF ("which themes are near-duplicates?",
-- "what hangs under fantasy?", "does this alias collide with a live theme?"), which
-- need the slug, the DAG and the aliases. Three views cover that shape; the
-- gameplay-feature vocabulary below mirrors them one-for-one:
--   <term>_vocab     one row per live term — identity, usage count, DAG, aliases
--   <term>_aliases   alias GRAIN, so you can join and compare on an alias
--   model_<terms>    slug-keyed model↔term grain (the twin of the display list)
-- Without them these questions reach past the foundation into fc.catalog_*, against
-- the predicate-on-stable-keys rule. `themes` is unchanged and stays the display path.
--
-- Live themes only, like `countries` / `game_formats` — add an `all_themes` twin the
-- day an analysis wants the soft-deleted rows.
CREATE OR REPLACE VIEW _live_theme AS
  SELECT id, slug, name, description FROM fc.catalog_theme
  WHERE status IS DISTINCT FROM 'deleted';

-- model_themes — one row per (live model, live theme). The GRAIN twin of `themes`:
-- predicate and join on theme_slug, the stable key. Display name lives in theme_vocab,
-- not here — the same lean-grain call model_gameplay_features makes for feature_name.
-- Direct attachments ONLY, DAG not rolled up: a model tagged `black-magic` does NOT
-- gain `occult`. Resolve ancestors analysis-locally via theme_vocab.parents.
CREATE OR REPLACE VIEW model_themes AS
  SELECT mt.machinemodel_id AS model_id, t.id AS theme_id, t.slug AS theme_slug
  FROM fc.catalog_machinemodel_themes mt
  JOIN _live_theme t ON t.id = mt.theme_id
  WHERE EXISTS (SELECT 1 FROM models s WHERE s.id = mt.machinemodel_id);  -- live subjects
COMMENT ON VIEW model_themes IS
  'One row per (live model, live theme) — the grain twin of themes; predicate and join on theme_slug. Direct attachments only, DAG not rolled up.';

-- theme_aliases — one row per alias of a live theme. GRAIN, not the flat list
-- theme_vocab.aliases carries, because consumers JOIN and COMPARE on an alias: an
-- alias colliding with a live theme's own name is the corpus's dominant defect (the
-- merge was declared, the source theme never retired), and a list column would make
-- every such query unnest first. Alias rows carry no status of their own — the join
-- to _live_theme is the live filter.
-- NB values arrive as entered, mixed case included, and are NOT normalized here:
-- whether 'Playing Cards' matches 'playing-cards', or plurals collapse, is the
-- DETECTOR's call and belongs analysis-local, not in a decode.
CREATE OR REPLACE VIEW theme_aliases AS
  SELECT ta.theme_id, t.slug AS theme_slug, ta.value AS alias
  FROM fc.catalog_themealias ta
  JOIN _live_theme t ON t.id = ta.theme_id;
COMMENT ON VIEW theme_aliases IS
  'One row per alias of a live theme — alias GRAIN, so you can join and compare on one. Values as entered, not normalized.';

-- theme_vocab — one row per live theme: the vocabulary itself.
--   n        : LIVE-model usage count, the "is this theme carrying its weight?"
--              signal — same derived-count role `n` plays in title_size. 0 for an
--              unused theme (COALESCE, not a dropped row: an orphan vocabulary entry
--              is exactly what a cleanup wants to see).
--   parents  : slugs this theme hangs under (a DAG, so several are possible); [] for
--              a root — which much of this corpus is.
--   children : the inverse. Derived from the same table, so the two can't disagree.
--   aliases  : this theme's alias VALUES, flattened for display; use theme_aliases
--              when you need to join on one.
-- Live-only on BOTH ends of the DAG: a soft-deleted parent doesn't parent anything.
-- Direct edges only — no transitive closure; a caller wanting every descendant writes
-- the recursive CTE analysis-locally.
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
    t.id, t.slug, t.name, t.description,
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

-- tags — sorted list of TAG SLUGS per tagged model (only models with any). Keyed by
-- id like rewards/themes, so it inherits live/all from whichever model view you join
-- to. Deliberately lists SLUGS, not names: unlike rewards/themes (display lists),
-- tags are the classification vocabulary you PREDICATE on (`'widebody' IN tags`), and
-- the slug is the stable key. Live tags only. NB `conversion_kit` and re-themes are
-- NOT tags and won't appear here — they're ModelRelationship types.
CREATE OR REPLACE VIEW tags AS
  SELECT mt.machinemodel_id AS id, list_sort(list(tg.slug)) AS tags
  FROM fc.catalog_machinemodel_tags mt
  JOIN fc.catalog_tag tg ON tg.id = mt.tag_id AND tg.status IS DISTINCT FROM 'deleted'
  GROUP BY mt.machinemodel_id;
COMMENT ON VIEW tags IS
  'One row per tagged model — sorted list of tag SLUGS (the stable key you predicate on), keyed by id. conversion_kit and re-themes are ModelRelationship types, not tags.';

-- tag_vocab — one row per live TAG, the vocabulary behind the `tags` name-list. The
-- entity grain: `tags` is keyed by MODEL and answers "what is this tagged", this is
-- keyed by tag and answers "what tags exist, and how much is each used". Four live tags
-- of eight rows — half the vocabulary is soft-deleted, so a hardcoded slug that used to
-- work is a live possibility and checking it against this view is how you find out.
-- No DAG: unlike themes and gameplay features, tags are flat.
CREATE OR REPLACE VIEW tag_vocab AS
  SELECT
    tg.id, tg.slug, tg.name, tg.description,
    -- count(m.id), not count(mt.machinemodel_id): the through-row survives its model's
    -- soft-delete, so counting the link would report dead models as usage.
    count(m.id) AS n
  FROM fc.catalog_tag tg
  LEFT JOIN fc.catalog_machinemodel_tags mt ON mt.tag_id = tg.id
  LEFT JOIN fc.catalog_machinemodel m
    ON m.id = mt.machinemodel_id AND m.status IS DISTINCT FROM 'deleted'
  WHERE tg.status IS DISTINCT FROM 'deleted'
  GROUP BY ALL;
COMMENT ON VIEW tag_vocab IS
  'One row per live tag — the tag VOCABULARY with usage count n, the entity twin of the model-keyed tags name-list. Flat, no DAG.';

-- ═══ GAMEPLAY FEATURES ══════════════════════════════════════════════════════
-- model_gameplay_features — one row per (model, directly-attached gameplay feature)
-- with its optional count. A grain view like model_relationships (many rows per
-- model), NOT a flattened name-list like rewards/themes — because the vast majority
-- of these rows carry a count (Flippers x2; Trap Holes x25, the 5x5 bingo card), so
-- flattening to names would drop the dominant signal. Live subjects only, like the
-- other grain views. Direct attachments ONLY: the GameplayFeature DAG (e.g. 2-Ball
-- Multiball under Multiball) is NOT rolled up to ancestors here — resolve parents
-- analysis-locally if a query needs them, exactly as themes leaves its DAG unrolled.
-- Predicate and display on feature_slug (a controlled vocab: 'trap-holes', 'flippers');
-- the redundant display feature_name is not surfaced. feature_id keys the grain.
--   count : the M2M's optional count (Flippers x2); NULL for a bare membership. This
--           is the real "how many flippers" signal — the raw table's scalar
--           flipper_count is near-empty and deliberately not surfaced.
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

-- ─── Gameplay-feature vocabulary ────────────────────────────────────────────
-- The theme trio's mirror (see the Theme vocabulary block above for the shape).
-- `model_gameplay_features` above is already the grain, so only two views are new:
-- the vocabulary and its alias grain. Live features only.
--
-- The difference from themes is depth. This vocabulary is deliberately built rather
-- than bulk-imported, and the DAG is genuinely deep — kickback-lanes →
-- right-kickback-lanes → upper-right-kickback-lanes — with interior nodes that carry
-- no models of their own by design. See the note on `n` below.
CREATE OR REPLACE VIEW _live_gameplay_feature AS
  SELECT id, slug, name, description FROM fc.catalog_gameplayfeature
  WHERE status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW model_gameplay_features IS
  'One row per (live model, gameplay feature) with its optional count (Flippers x2, Trap Holes x25) — the counted grain. Direct attachments only, DAG not rolled up.';

-- gameplay_feature_aliases — one row per alias of a live feature. GRAIN for the same
-- reason theme_aliases is: consumers JOIN and COMPARE on an alias, here to resolve a
-- source's phrasing ("Autoplunger", "Left-Side Kickback Lane") to the canonical
-- feature. Not normalized — that's the detector's call, analysis-local.
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

-- _model_target — the distinguishing facts surfaced for the OTHER end of a
-- relationship edge (a lineage or relationship target): identity (including the maker's
-- own model number), year, genre (game_format), reward types, player count, maker and
-- where the maker was based (location) — the pieces a reviewer uses to tell two models
-- apart, and genre is the most fundamental ("is my target a bingo?").
-- A pure projection of `models` (live-only) + `rewards`, with columns named
-- target_* so both edge views pull the whole block via `* EXCLUDE (id)` and never
-- restate the list. Private: read it through model_lineage / model_relationships.
-- Add a facet here once and both edge views gain it.
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
  LEFT JOIN rewards rw ON rw.id = m.id;

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
-- All three build on `models` (live-only), and follow ONE rule for the far end: an
-- edge KEEPS its row and de-enriches to NULL target_* rather than being dropped when
-- the target can't resolve. The only LEGITIMATE de-enrich is a typed free-text label
-- (target_label, no catalog model). A resolved-but-de-enriched target (target_id set,
-- target_slug NULL) is a soft-deleted target the app should have protected — an
-- integrity violation catalog_checks flags for BOTH mechanisms, not a normal path.
-- model_edges CONCATENATES the two; it does NOT reconcile overlaps — a variant_of FK
-- and a typed edge to the same target are two rows, deciding they're one is analysis-local.
-- ─────────────────────────────────────────────────────────────────────────────

-- model_lineage — variant_of + remake_of + export_edition_of as row-grain edges:
-- one row per (model, edge_kind), 0..1 per kind. Target enriched inline via a LEFT
-- JOIN, which is defensive only: the app blocks soft-deleting a live lineage target,
-- so target_* always enriches here. A de-enriched one means that protection was
-- bypassed — catalog_checks flags it (lineage_target_not_live).
--   edge_kind : 'variant_of' | 'remake_of' | 'export_edition_of'
--   target_*  : the origin model's identity (incl. manufacturer_model_identifier),
--               year, genre, reward types, player count
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
COMMENT ON VIEW model_lineage IS
  'One row per (model, lineage edge) — the three single-valued self-FKs (variant_of, remake_of, export_edition_of) as row grain, target resolved. A component of model_edges.';

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

COMMENT ON VIEW model_relationships IS
  'One row per typed ModelRelationship edge — multi-valued, closed relationship_type and license_status vocabularies, target either a resolved model or a free-text label. A component of model_edges.';
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
COMMENT ON VIEW model_export_markets IS
  'One row per export destination of a live model — the target is a LOCATION, not a model, so this is NOT part of model_edges. The target ladder is optional: a country, a free-text region, or neither.';

-- model_edges — the DEFAULT relationships view: every edge out of a model, lineage
-- and typed, in one row-grain set. A UNION ALL over model_lineage + model_
-- relationships — no new joins, since both already carry the target_* block — so
-- one predicate returns all of a model's edges and none is missed. Concatenates,
-- does NOT reconcile (overlapping FK + typed edges are two rows; that's analysis-local).
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

-- model_edges_bidir — every edge from BOTH ends. `model_edges` is OUTBOUND ONLY, which
-- is right for "what does this model point at" and silently wrong for "is this pair
-- connected" — hundreds of live models have an inbound edge and no outbound one, so a
-- connectedness test written against model_edges returns a confident false for all of
-- them. That question wants this view: `WHERE model_id = ? AND target_id = ?` with no
-- hand-written OR of two EXISTS, and `WHERE model_id = ?` for a model's full
-- neighbourhood in either direction.
--
-- The mirror does NOT re-point the edge. `relationship_type` always describes the edge
-- AS STATED, from `model_id` when direction = 'out' and from `target_id` when
-- direction = 'in' — because the direction IS the fact. A variant points at its base;
-- the base is not a variant of the variant, and rewriting the type to make the mirror
-- read naturally would assert exactly that. So always read the type together with
-- `direction`, and use `model_edges` (not this) whenever you are aggregating edges —
-- every row here is counted twice by construction.
--   direction : 'out' (this model states the edge) | 'in' (the other end states it)
--   target_*  : always the FAR end from `model_id`, re-enriched per direction.
-- Label-only typed edges have no model at the far end, so they appear 'out' only —
-- there is no second perspective to take.
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
--   IT IS NOT `title_size` WITH MORE COLUMNS. `title_size` is built from
--             `_title_live_n` and so holds only Titles that HAVE a live model; this
--             view holds every live Title and reports the ones with none at
--             `n_models = 0` rather than dropping them. The two agree row-for-row
--             today — every live Title has a live model — so the difference is
--             structural and will stay invisible until a Title outlives its last
--             model, which soft-deleting one model of a one-model Title produces
--             immediately. That is why `n_models` is a COALESCEd 0 and not the NULL a
--             plain join to `title_size` would give: zero is the answer, not "unknown".
--   franchise / series : the two optional Title groupings, resolved to slug and name
--             like any other dim and live-filtered the same way, so a soft-deleted
--             grouping de-enriches to NULL instead of being reported as current. Both
--             are sparse by design — 210 Titles carry a franchise, 16 a series — and
--             they mean different things: a franchise is the IP (Star Trek, spanning
--             makers and eras), a series is a curated thematic lineage (Eight Ball ->
--             Eight Ball Deluxe). Nothing ingests either; both are curator-maintained,
--             so an absent grouping is "not yet curated", never "does not belong".
--             The groupings themselves have no vocabulary view — GROUP BY the slug
--             here for their membership, and promote a `franchises` view the day an
--             analysis needs a franchise that no Title points at.
--   opdb_id / fandom_page_id : the outbound handles. opdb_id is OPDB's "group" — the
--             Title is the grain OPDB models identity at, which is why it sits here
--             and `models.opdb_id` is the machine-level one; they are different
--             namespaces and must not be compared.
--   description : SingleModelTitles.md governs how this splits against the model's
--             own description. Populated on 12 Titles today.
CREATE OR REPLACE VIEW titles AS
  SELECT
    t.id, t.slug, t.name,
    t.opdb_id,
    t.franchise_id, f.slug  AS franchise_slug, f.name  AS franchise_name,
    t.series_id,    se.slug AS series_slug,    se.name AS series_name,
    t.fandom_page_id,
    COALESCE(tn.n, 0) AS n_models,
    t.description
  FROM fc.catalog_title t
  LEFT JOIN _title_live_n tn         ON tn.title_id = t.id
  LEFT JOIN fc.catalog_franchise f   ON f.id  = t.franchise_id
                                    AND f.status  IS DISTINCT FROM 'deleted'
  LEFT JOIN fc.catalog_series se     ON se.id = t.series_id
                                    AND se.status IS DISTINCT FROM 'deleted'
  WHERE t.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW titles IS
  'One row per LIVE Title — identity, franchise/series grouping and n_models. Unlike title_size it keeps Titles with no live models, at n_models = 0.';

-- franchises / series — the two Title-grouping vocabularies, entity grain. `titles`
-- decodes each onto the Title row; these answer the questions that needs a second view:
-- which groupings EXIST, and which are used by nothing. 140 franchises against 210
-- grouped Titles, 6 series against 16 — so the average franchise holds one or two
-- Titles and the shape is nothing like a themes DAG.
--
-- Neither is ingested. Both are curator-maintained (Series' docstring says so
-- outright), which is what makes `n_titles = 0` the interesting row rather than a
-- defect: it is a grouping someone created and never attached, and it is invisible from
-- `titles` alone because a Title that points at nothing produces no row to notice.
CREATE OR REPLACE VIEW franchises AS
  SELECT f.id, f.slug, f.name, f.description,
         count(t.id) AS n_titles
  FROM fc.catalog_franchise f
  LEFT JOIN fc.catalog_title t
    ON t.franchise_id = f.id AND t.status IS DISTINCT FROM 'deleted'
  WHERE f.status IS DISTINCT FROM 'deleted'
  GROUP BY ALL;
COMMENT ON VIEW franchises IS
  'One row per live Franchise — the IP grouping (Star Trek), spanning makers and eras, with n_titles. Curator-maintained, never ingested, so n_titles = 0 is a real state.';

CREATE OR REPLACE VIEW series AS
  SELECT s.id, s.slug, s.name, s.description,
         count(t.id) AS n_titles
  FROM fc.catalog_series s
  LEFT JOIN fc.catalog_title t
    ON t.series_id = s.id AND t.status IS DISTINCT FROM 'deleted'
  WHERE s.status IS DISTINCT FROM 'deleted'
  GROUP BY ALL;
COMMENT ON VIEW series IS
  'One row per live Series — a curated thematic lineage (Eight Ball -> Eight Ball Deluxe), with n_titles. Six of them; not the same thing as a Franchise, which is the IP.';

-- title_size — one row per Title with a live model: its identity (title_slug/
-- title_name) plus n, the count of LIVE models in it (the "alone in its Title?"
-- signal — n = 1). A soft-deleted sibling doesn't keep a model company.
-- The TITLE-keyed form of the same number `models.title_size` carries per model, off
-- one helper so they can't disagree. Reach for this when the Title is the grain you
-- are iterating; read the model column when you already have a model row.
CREATE OR REPLACE VIEW title_size AS
  SELECT tn.title_id, t.slug AS title_slug, t.name AS title_name, tn.n
  FROM _title_live_n tn
  LEFT JOIN fc.catalog_title t ON t.id = tn.title_id;
COMMENT ON VIEW title_size IS
  'One row per Title with a live model — Title identity plus n, the live model count. The "alone in its Title?" signal is n = 1.';

-- model_number_collisions — one row per (maker, model number) that more than one live
-- model claims. `models.manufacturer_model_identifier` is documented as not unique;
-- this is that fact made queryable, so an analysis matching a source's model number
-- can see up front whether its key resolves.
--
-- The column doc lists the three reasons a number repeats — the catalog splitting
-- finer than the maker numbered (within a Title, or across Titles for a re-theme
-- family), and plain bad data. `n_titles` is the cheap discriminator: 1 means the
-- collision is contained in one Title and is probably a legitimate split; >1 wants a
-- look. Reported, never judged — deciding which kind a row is needs a human.
--
-- EXACT numbers only, no stem matching. A maker's suffix convention is a fact about
-- THAT MAKER, not about the column: Bally's trailing letter marks a different game
-- (#634 'Fun Way' vs #634-A 'Lotta Fun'), which is not something to assume of anyone
-- else. An analysis needing loose matching should own the rule, and record the maker
-- it holds for, rather than inherit a stem macro that would answer confidently for
-- makers it was never calibrated on.
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
  'One row per (maker, model number) claimed by more than one live model — exact numbers only. n_titles = 1 is usually a legitimate catalog split, not bad data.';

-- ═══ PEOPLE AND CREDITS ════════════════════════════════════════════════════
-- credits — one row per credit: a Person, in a CreditRole, on a subject. THE grain, and
-- the single definition of what a live credit is — `people` and `credit_roles` below are
-- both aggregates OF THIS VIEW, so the three cannot disagree about the population they
-- describe. They used to carry a copy of the liveness rule each, which is how "how many
-- machines is Roy Parker credited on" (299) had an answer and "which ones" had none.
--
--   THE SUBJECT IS POLYMORPHIC, and the minority half is the trap. A Credit hangs off a
--             MachineModel XOR a Series (`catalog_credit_model_xor_series`), 7244 to 7
--             today. A model-only grain would look complete, agree with every spot check
--             and silently be missing a whole KIND of credit — the failure `changesets`
--             was repaired for, where 739 rows were invisible because the view was
--             derived from the convenient side. So both halves are carried, decoded the
--             way `claims` decodes its 21 subject types and spelled the same:
--             subject_type is 'catalog.machinemodel' / 'catalog.series', so a join
--             across to `claims` needs no translation. Want the model half? Use
--             `model_credits`, not a subject_type predicate you wrote yourself.
--   subject_name : the subject's plain name — `models.label` is the disambiguated form
--             ("Name (Maker Year)") and is one join from `model_credits.model_id`.
--   liveness: all four ends are live-filtered — both halves of the XOR, the person and
--             the role. A credit on a soft-deleted model is not a credit on the live
--             catalog, and the far end of a grain edge has to be live for the same
--             reason it does in `model_gameplay_features`. None of the four drops a row
--             today; the FKs are PROTECT and the soft-delete walker blocks the rest.
--   provenance: Credit is the compound claim `claim_identity_parts` exists for. Its
--             claim_key names two entities (`credit|person:100|role:4`), so
--             `claims.ref_id` is NULL and there is no single-column join — go
--             `claims` (subject_type/subject_id, field_name = 'credit') →
--             `claim_identity_parts`, once per part.
CREATE OR REPLACE VIEW credits AS
  SELECT
    c.id                                        AS credit_id,
    -- Every subject_* column is read off the SAME joined row rather than off the raw
    -- FK columns, so they cannot describe different subjects: a row that resolved on
    -- both sides (the constraint forbids it) still reports one subject consistently
    -- instead of splicing a model's type onto a series' slug.
    CASE WHEN m.id IS NOT NULL THEN 'catalog.machinemodel'
         ELSE 'catalog.series' END              AS subject_type,
    COALESCE(m.id,   s.id)                      AS subject_id,
    COALESCE(m.slug, s.slug)                    AS subject_slug,
    COALESCE(m.name, s.name)                    AS subject_name,
    c.person_id, p.slug AS person_slug, p.name AS person_name,
    c.role_id,   r.slug AS role_slug,   r.name AS role_name
  -- Read off the PHYSICAL tables rather than off `models` / `series`, which is the one
  -- place this file allows the second-definition-of-live pattern it otherwise refuses.
  -- Two reasons it is safe here and nowhere else: `models` is `all_models` filtered on
  -- the identical predicate and `all_models` is LEFT JOINs throughout, so neither view
  -- can drop or add a row relative to this; and `credit_subject_not_live` resolves every
  -- subject against `models` / `series` themselves, so the moment the two definitions
  -- disagree the check fires rather than the count quietly shifting. Joining `series`
  -- here would also drag its n_titles aggregate onto a 7k-row grain for two columns.
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

-- model_credits — the model-attached half of `credits`, keyed model_id so it joins
-- straight to `models` and the other model grain views. The same move `model_claims` is
-- on the provenance side, and defined OVER `credits` for the reason `countries` is
-- defined over `locations`: a projection that re-read `fc.catalog_credit` would be a
-- second definition of a live credit, waiting to drift from the first.
--
-- 7244 of the 7251 credits. The other 7 hang off a Series and are reachable only from
-- `credits`, so a total taken here is not a total.
CREATE OR REPLACE VIEW model_credits AS
  SELECT c.*, c.subject_id AS model_id
  FROM credits c
  WHERE c.subject_type = 'catalog.machinemodel';
COMMENT ON VIEW model_credits IS
  'One row per credit on a LIVE machine model, keyed model_id — the model half of credits (7244 of 7251; the 7 Series credits appear only there).';

-- credit_roles — the credit-role vocabulary (designer, artist, …), entity grain with
-- usage. Ten live roles. The role-keyed counterpart to `people`: that view carries
-- n_roles per person, this one n_credits per role, and `credits` is where either goes
-- to say WHICH machine.
--
-- `n_credits` counts rows of `credits`, so it is the same population `people` counts,
-- by construction rather than by two matching predicates. Reading it against
-- `people.n_roles` is how you tell a broad vocabulary from a narrow one: 7 roles are in
-- use across 589 credited people, so three exist and are attached to nothing.
-- count(c.credit_id), never count(*): a role with no credits must read 0, and the
-- LEFT JOIN would otherwise count its own unmatched row as one.
CREATE OR REPLACE VIEW credit_roles AS
  SELECT
    r.id, r.slug, r.name, r.description,
    count(c.credit_id) AS n_credits
  FROM fc.catalog_creditrole r
  LEFT JOIN credits c ON c.role_id = r.id
  WHERE r.status IS DISTINCT FROM 'deleted'
  GROUP BY ALL;
COMMENT ON VIEW credit_roles IS
  'One row per live CreditRole — the credit vocabulary (designer, artist) with n_credits over live subjects. The role-keyed counterpart to people.n_roles; credits is the grain.';

-- people — one row per live Person, with how much of the catalog they are credited on.
-- The entity grain behind `person_aliases`, which was for a while the only place a
-- Person appeared at all: an analysis resolving a credit name had the alias table and
-- no way to get from the match to the person.
--
--   n_credits : rows of `credits` — model- and series-attached together, since that is
--             what the grain holds. Nearly but not exactly n_credited_models, and
--             treating either as the other drops the series credits.
--   n_credited_models : distinct LIVE MODELS, which is why it filters subject_type
--             rather than counting subject_id. Model and Series pks are separate
--             namespaces that overlap freely, so an undistinguished count would merge a
--             series with the model that happens to share its number.
--   n_roles : distinct roles held. A person credited as designer and artist on one
--             machine has n_credits = 2, n_credited_models = 1, n_roles = 2.
--   birth_year / death_year : claim-resolved biography, and all but empty — ONE live
--             person carries each today. Anchoring them is what will make that visible
--             if a source ever lands them in bulk. The month and day fields exist on
--             the model and are entirely unpopulated, so they stay unsurfaced under
--             the demand-driven rule; promoting them is a line here, and the year is
--             the full precision on offer until then.
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
    p.id, p.slug, p.name,
    COALESCE(a.n_credits, 0)         AS n_credits,
    COALESCE(a.n_credited_models, 0) AS n_credited_models,
    COALESCE(a.n_roles, 0)           AS n_roles,
    p.birth_year, p.death_year
  FROM fc.catalog_person p
  LEFT JOIN agg a ON a.person_id = p.id
  WHERE p.status IS DISTINCT FROM 'deleted';
COMMENT ON VIEW people IS
  'One row per live Person — identity, birth/death year and credit counts over live subjects. Counts only: `credits` is the grain that says WHICH models.';

-- ═══ ALIASES & ABBREVIATIONS — matching source wording ══════════════════════
-- Alias views contain one row per alias of a live parent, keyed by its stable slug.
-- location_aliases uses location_path instead because Location slugs are parent-scoped.
-- Values are stored as entered; normalization belongs in the consuming analysis.
-- location_aliases, country_aliases, theme_aliases and gameplay_feature_aliases live
-- beside their vocabularies above.

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
  'One row per alias of a live maker — alias GRAIN, for resolving a source name (native-script, accented, trade name) to the canonical Manufacturer.';

-- Corporate entity, not manufacturer: the legal entity below the brand. An alias
-- resolved here may be finer-grained than the maker used for grouping.
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
-- Abbreviations are community shorthand, not alternate names. Use them for forum or
-- marketplace prose, and keep them out of name-alias matching. The value column is
-- named abbreviation to keep the two families distinct.
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
-- The catalog's controlled vocabularies (game formats, cabinets, production statuses,
-- …) are DEFINED in docs/DomainModel.md — what separates `one-off` from `unreleased`,
-- `shuffle` from `rolldown`. The DB carries the slug and the display name; the meaning
-- lives only in that doc, and an analyst filtering on a slug needs the meaning.
--
-- So the doc is READ, not restated. `domain_vocab` parses its definition bullets at
-- query time, which keeps DomainModel.md the single source of truth for domain
-- semantics and keeps this layer to what it is good at — the query-level facts (grain,
-- liveness, non-uniqueness) that no domain document should have to carry. Copying the
-- definitions down here would make the analysis layer a second place to maintain them,
-- and the whole point is that there isn't one.
--
-- No build step and no generated artifact, matching the rest of this file: read_text
-- runs when the view is queried, so it is always current and costs nothing to a session
-- that never touches it.
--
-- The doc shape it relies on — stable, and everything in DomainModel.md already follows
-- it — is a bullet `- \`slug\`: definition`, grouped by the nearest preceding
-- `**EntityName**` lead-in, else by the `##`/`###` heading. The group is snake-stripped
-- to a dim name (`Production Status` -> `productionstatus`), which is exactly the
-- catalog table suffix, so the doc->table mapping is mechanical rather than a list
-- somebody maintains.
--
-- Failure is loud, never silent. A renamed heading detaches every bullet under it, and
-- catalog_checks then reports every slug in that vocabulary as undocumented at once
-- (undocumented_vocab) plus the dim itself as missing (stale_vocab_dim) — you cannot
-- lose a vocabulary quietly.
CREATE OR REPLACE VIEW _dm_lines AS
  WITH raw AS (SELECT content FROM read_text('docs/DomainModel.md'))
  SELECT generate_subscripts(str_split(content, chr(10)), 1) AS i,
         unnest(str_split(content, chr(10)))                 AS t
  FROM raw;

-- The group each bullet belongs to: a bold lead-in when the section has one (Display
-- Type documents DisplayType AND DisplaySubtype under a single heading), else the
-- heading itself (Cabinet, Tag, GameFormat and friends have no lead-in).
CREATE OR REPLACE VIEW _dm_marked AS
  SELECT i, t,
         CASE WHEN regexp_matches(t, '^\*\*[A-Za-z]+\*\* ') THEN regexp_extract(t, '^\*\*([A-Za-z]+)\*\*', 1)
              WHEN regexp_matches(t, '^#{2,3} ')            THEN regexp_extract(t, '^#{2,3} (.*)$', 1)
         END AS group_raw
  FROM _dm_lines;

-- domain_vocab — one row per documented vocabulary term.
-- The group window must run over EVERY line and the bullet filter applied outside it;
-- filtering first strips the heading rows the window reads, and every group comes back
-- NULL (the view silently returns nothing, which is how this was first written).
-- Restricted to groups that name a real fc.catalog_<dim> table, which is what keeps
-- non-vocabulary bullet lists out — "Fields Common to All Catalog Entities" documents
-- `name` and `description` in this exact shape and is not a vocabulary. That test is
-- mechanical, so a new documented vocabulary needs no edit here; it needs a _dim_vocab
-- entry, and unmapped_vocab_dim says so.
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

-- ═══ RUN WATERMARK ══════════════════════════════════════════════════════════
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
-- The last three are provenance facts sitting in the catalog watermark on purpose:
-- what makes a reproduction checkable is having the schema point, the patch point and
-- the changeset point in ONE row. `provenance_context` in provenance.sql carries that
-- layer's counts and deliberately does not restate these; read the two together.
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
COMMENT ON VIEW analysis_context IS
  'One row — the input watermark: DuckDB version, live model count, migration point, latest successful patch + fingerprint, latest changeset id. Printed by every analysis run.';

-- ═══ PROVENANCE — who said so (provenance.sql) ══════════════════════════════
-- The attribution and citation layer — claims, ingest sources, ingest runs, citation
-- sources. Split into its own file because it is a distinct concern with its own
-- vocabulary (and because this one is long enough), but `.read` here rather than left
-- for each analysis to remember, so "the foundation" stays ONE `.read` line for every
-- consumer including the sister repos.
.read scripts/analysis/provenance.sql

-- ═══ DATA PATCHES — what our own patches did (data_patches.sql) ═════════════
-- The patch lens on the provenance layer: which patch asserted a fact, which retracted
-- one, and what evidence each data patch entry recorded.
.read scripts/analysis/data_patches.sql
