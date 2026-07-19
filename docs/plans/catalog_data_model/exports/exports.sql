-- Export-candidate analysis for Exports.md.
--
-- Plan-local layer: the export-specific detectors and review views. The generic
-- catalog decode (models/countries/rewards/title_size + the connection) lives in
-- the shared foundation, pulled in by the `.read` below. Run from the REPO ROOT:
--
--     # one-off: run the init then a query in the same session
--     duckdb -init docs/plans/catalog_data_model/exports/exports.sql :memory: \
--       "SELECT * FROM export_candidate_lineage WHERE NOT has_edge;"
--
--     # GUI: browse the views live in the local DuckDB UI (localhost:4213)
--     duckdb -ui -init docs/plans/catalog_data_model/exports/exports.sql :memory:
--
-- Nothing is persisted; there is no build artifact. Counts are a snapshot of
-- current DB state — re-run as candidates get reviewed. `export_summary` emits
-- the headline numbers the doc quotes; `export_checks` is empty when healthy.
--
-- The notes detectors are freetext heuristics: they over- and under-count and
-- every row needs source review before it becomes a claim (see Exports.md).
--
-- STRUCTURE — a plan file has four sections (see scripts/analysis/README.md). Three
-- are the same in every analysis; only section 3 is shaped by the question:
--   1 · FOUNDATION       .read the shared decode layer
--   2 · REFERENCE        plan-local hand-maintained lookups (often empty)
--   3 · ANALYSIS         the actual work — this file's shape is detect ->
--                        assemble -> enrich -> review; yours may differ
--   4 · SUMMARY & CHECKS the tail that keeps the prose honest — always keep it

-- ── 1 · FOUNDATION ─────────────────────────────────────────────────────────
.read scripts/analysis/catalog.sql

-- ── 2 · REFERENCE ──────────────────────────────────────────────────────────
-- Hand-maintained lookups specific to this analysis. Not derived from the DB.

-- Country resolution for the detectors. The catalog owns the country vocabulary
-- (`countries`); this maps the free-text TOKENS the detectors pull from notes and
-- names to a catalog country SLUG, so markets are stored as slugs that align with
-- each model's maker-home `country_slug`. Three token kinds aren't a catalog name and
-- need an alias: the IPDB US spellings, the acronyms/alternate names ("UK", "Holland"),
-- and the adjectives in "for the German market". Everything else resolves by name.
-- Slugs are never hardcoded — `countries` supplies them, so a country rename can't
-- silently desync this lookup. (A destination country that isn't in `countries` at all,
-- e.g. Israel, resolves the moment it's created as a Location — no alias needed.)
CREATE OR REPLACE VIEW _country_alias AS
  SELECT * FROM (VALUES
    ('USA','United States of America'), ('United States','United States of America'),
    ('UK','United Kingdom'), ('Holland','Netherlands'),
    ('Italian','Italy'), ('Spanish','Spain'), ('French','France'), ('German','Germany'),
    ('Portuguese','Portugal'), ('Japanese','Japan'), ('Brazilian','Brazil'),
    ('Belgian','Belgium'), ('British','United Kingdom'), ('American','United States of America')
  ) AS t(token, country_name);

-- token -> country slug: catalog names resolve directly, the aliases above via name.
CREATE OR REPLACE VIEW _country_lookup AS
  SELECT name AS token, slug FROM countries
  UNION ALL
  SELECT a.token, c.slug FROM _country_alias a JOIN countries c ON c.name = a.country_name;

-- Region labels for the `target_market_label` case (Exports.md): a market that is a
-- multi-country region, not a catalog country. Unlike countries these have NO catalog
-- vocabulary to draw on (a region isn't a Location), so the canonical label is
-- hand-declared here — this IS the closed set `market_kind = 'region'` validates
-- against. `pattern` is a case-insensitive regex requiring EXPORT context around the
-- region word, because the bare word is mostly noise ("European football" theme, "a
-- European distributor", a collector "in Europe"). Keep patterns tight; a false region
-- hit invents a market. Only Europe recurs in the data today; the row shape is ready
-- for Scandinavia/Benelux/Latin America if they ever surface.
CREATE OR REPLACE VIEW _region_alias AS
  SELECT * FROM (VALUES
    ('Europe',   '(?i)(for (the )?european market|made for europe|export(ed)? to europe|shipped to europe)'),
    ('Far East', '(?i)(export(ed)? to (the )?far east|for the far east(ern)? market|made for the far east)')
  ) AS t(label, pattern);

-- ── 3 · ANALYSIS ───────────────────────────────────────────────────────────
-- This analysis hunts candidate export models, so its shape is:
--   detect   surface candidates from several independent signals (the _by_*,
--            _dest_* helpers below)
--   assemble union the signals into one row per candidate (export_candidates)
--   enrich   join in existing lineage edges (export_candidate_lineage)
--   review   slice the candidates into the human-review buckets (export_*_review,
--            export_name_family)
-- A different question wants a different shape — classify, aggregate, diff, etc.
-- Keep sections 1, 2 and 4; rebuild this one for your plan.

-- detect ──
-- Detector 1 (membership): any model whose notes carry export-edition phrasing.
-- Scope is *any model built for export*, so this is NOT gated on a named market
-- (the market is parsed separately below and may be empty). The one exclusion is
-- the "quantity produced for export: N" production statistic — a sales figure
-- nearly every Williams/Gottlieb game carries — which is blanked before matching
-- so it can't create a candidate on its own, yet a note that ALSO carries real
-- export phrasing (e.g. Yukon (Special)) is still kept.
-- NOTE: "for the <X> market" phrasing was REMOVED from membership — it was mostly
-- noise. The unbounded `%for the % market%` bridged unrelated text (4-IN-1's "sell ...
-- to the home market" became a hit), and even bounded it caught domestic markets. Of
-- the 42 candidates it uniquely supplied, only ~5 were genuine foreign-market exports.
-- Those hits are now PARKED in `export_market_phrase_review` for a separate, careful
-- pass, rather than polluting the candidate set. (`_dest_market` below still parses the
-- phrase into a country for models that ARE candidates by other signals — that's fine.)
CREATE OR REPLACE VIEW _by_notes AS
  SELECT id FROM (
    SELECT id, regexp_replace(COALESCE(ipdb_notes, ''), '(?i)quantity produced for export', '', 'g') AS n
    FROM models
  )
  WHERE n ILIKE '%for export%'
     OR n ILIKE '%export to %'
     OR n ILIKE '%export edition%' OR n ILIKE '%export version%' OR n ILIKE '%export model%';

-- The _dest_* views below parse the destination MARKET from the notes/name. They
-- feed the `markets` column, not candidate membership — a by_notes candidate with
-- no parseable country simply has empty markets.

-- "export to <Country>[ and/then <Country>...]" — resolve each parsed token to a
-- country slug. Two shapes the naive single-token regex missed:
--   list      "export to Israel and Indonesia", "export to Brazil then Italy" — capture
--             the whole run (tokens chained by " and "/" then ") and split it, so the
--             tail country isn't dropped.
--   acronym   "export to the USA", "export to the UK" — the token charset allows
--             all-caps runs (USA/UK), resolved via `_country_alias`.
-- The country charset deliberately over-captures (any capitalized run); a token that
-- isn't a country simply drops at the `_country_lookup` join. A leading "the " on a
-- list tail (". . . and the UK") is stripped before lookup.
CREATE OR REPLACE VIEW _dest_export_to AS
  WITH runs AS (
    SELECT m.id, run
    FROM models m,
         UNNEST(regexp_extract_all(
           m.ipdb_notes,
           'export to (?:the )?([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)*(?: (?:and|then) (?:the )?[A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)*)*)',
           1)) AS d(run)
  ),
  toks AS (
    SELECT id, trim(regexp_replace(tok, '^the ', '')) AS token
    FROM runs, UNNEST(string_split_regex(run, ' (?:and|then) ')) AS s(tok)
  )
  SELECT t.id, cl.slug AS dest
  FROM toks t JOIN _country_lookup cl ON cl.token = t.token;

-- Detector 1b: "for the <Adjective|Country> market" (single-word token).
CREATE OR REPLACE VIEW _dest_market AS
  SELECT m.id, cl.slug AS dest
  FROM models m,
       UNNEST(regexp_extract_all(m.ipdb_notes, 'for the ([A-Z][a-z]+) market', 1)) AS d(token)
  JOIN _country_lookup cl ON cl.token = d.token;

-- Detector 2: trailing "(Country)" name suffix -> that country's slug.
CREATE OR REPLACE VIEW _dest_suffix AS
  SELECT m.id, c.slug AS dest
  FROM models m JOIN countries c ON m.name LIKE '%(' || c.name || ')';

-- Detector 3: OPDB feature flag containing "export" (today only "Export edition",
-- but the substring is insurance against other spellings). No market on its own.
CREATE OR REPLACE VIEW _by_opdb AS
  SELECT id FROM models
  WHERE len(list_filter(opdb_features, lambda f: lower(f) LIKE '%export%')) > 0;

-- Detector 2b: a nationality ADJECTIVE sitting directly on "export" — "Italian export
-- version", "German export model". The adjective is the destination, and it resolves
-- through the same `_country_alias` adjectives as "for the German market". Requiring a
-- CAPITALIZED token is what keeps this precise: it excludes the same-shaped non-markets
-- ("add-a-ball export version", "4-player export version"), and any capitalized
-- non-country simply drops at the `_country_lookup` join.
-- Caveat: the adjective could in principle name the maker's ORIGIN rather than the
-- destination ("Spanish export version" by a Spanish maker). `market_is_maker_home`
-- flags exactly that case for review; no model hits it today.
CREATE OR REPLACE VIEW _dest_adjective_export AS
  SELECT m.id, cl.slug AS dest
  FROM models m,
       UNNEST(regexp_extract_all(m.ipdb_notes, '([A-Z][a-z]+) export', 1)) AS d(token)
  JOIN _country_lookup cl ON cl.token = d.token;

-- Detector 4 (membership AND exclusion): the FORMULAIC TWIN sentence — the highest-
-- quality signal in the notes. Spanish-market makers ran paired brands, one domestic and
-- one export (Petaco/Recel, Recreativos Franco/Interflip), and IPDB writes BOTH sides:
--   domestic side: "Petaco is the name used for domestic games.
--                   The same company made an export version as Recel's 1980 'Black Magic'."
--   export side:   "Recel is the name used for export games.
--                   The same company made a domestic version as Petaco's 'Black Magic'."
-- Each model states its OWN role and NAMES its counterpart, so this needs no maker-level
-- inference and no maker lookup table: a model whose note says the TWIN is "domestic" is
-- itself the export, and vice versa. That makes it usable in both directions — it adds
-- export-side models as candidates and positively EXCLUDES the domestic side, which the
-- freetext detectors otherwise flag (a Petaco note says "export" only because it is
-- naming its Recel twin).
-- Shape notes: the qualifier floats around the keyword ("a 1-player domestic version",
-- "a domestic 4-player version", "a domestic SS version") and the article varies
-- (a/an/the), so both slots are optional word-runs. All 58 occurrences parse.
-- The independent "is the name used for <role> games" sentence is captured as
-- `declared_role` purely to cross-check the twin sentence; the two never disagree today,
-- and `export_checks` fails loudly if they ever do.
-- MATERIALIZED (a TABLE, not a view) — the one exception in this file. The regex below
-- is backtracking-heavy, and `_twin` is inlined into `export_candidates`, which
-- `export_summary` reference-expands ~20 times; as a view the parse re-runs on every one
-- of those and exhausts memory. A table computes it once at init. Nothing is persisted
-- (the database is :memory:), and like the views it stays non-TEMP so the DuckDB UI can
-- see it across connections.
CREATE OR REPLACE TABLE _twin AS
  WITH src AS (
    -- Cheap prefilter FIRST: the regex below is backtracking-heavy and this view is
    -- inlined into candidates, checks and the summary, so without this it re-scans all
    -- ~6.9k notes several times over and exhausts memory. Only these rows can match.
    SELECT id, ipdb_notes FROM models WHERE ipdb_notes ILIKE '%same company made%'
  ),
  p AS (
    SELECT id,
      regexp_extract(ipdb_notes, $$made (?:an?|the) (?:[A-Za-z0-9-]+ )*?(export|domestic) (?:[A-Za-z0-9-]+ )*?version as ([A-Z][A-Za-z. ]+?)'s (?:([0-9]{4}) )?'([^']+)'$$, 1) AS twin_kind,
      regexp_extract(ipdb_notes, $$made (?:an?|the) (?:[A-Za-z0-9-]+ )*?(export|domestic) (?:[A-Za-z0-9-]+ )*?version as ([A-Z][A-Za-z. ]+?)'s (?:([0-9]{4}) )?'([^']+)'$$, 2) AS twin_brand,
      regexp_extract(ipdb_notes, $$made (?:an?|the) (?:[A-Za-z0-9-]+ )*?(export|domestic) (?:[A-Za-z0-9-]+ )*?version as ([A-Z][A-Za-z. ]+?)'s (?:([0-9]{4}) )?'([^']+)'$$, 3) AS twin_year,
      regexp_extract(ipdb_notes, $$made (?:an?|the) (?:[A-Za-z0-9-]+ )*?(export|domestic) (?:[A-Za-z0-9-]+ )*?version as ([A-Z][A-Za-z. ]+?)'s (?:([0-9]{4}) )?'([^']+)'$$, 4) AS twin_name,
      regexp_extract(ipdb_notes, '(?i)is the name used for (export|domestic) games', 1) AS declared_role
    FROM src
  )
  SELECT
    id,
    -- this model's own role is the OPPOSITE of the twin it names
    CASE twin_kind WHEN 'domestic' THEN 'export' ELSE 'domestic' END AS role,
    twin_kind, twin_brand, NULLIF(twin_year, '') AS twin_year, twin_name,
    NULLIF(declared_role, '') AS declared_role
  FROM p
  WHERE twin_kind <> '';

-- Membership half of detector 4: the export side of a twin pair.
CREATE OR REPLACE VIEW _by_twin AS
  SELECT id FROM _twin WHERE role = 'export';

CREATE OR REPLACE VIEW _dest AS
  SELECT id, dest FROM _dest_export_to
  UNION SELECT id, dest FROM _dest_market
  UNION SELECT id, dest FROM _dest_suffix
  UNION SELECT id, dest FROM _dest_adjective_export;

-- Region detector: an export-context region phrase (see `_region_alias`) anywhere in
-- notes/notable-features. Feeds the `regions` column, NOT candidate membership — the
-- `market_kind = 'region'` case, i.e. a `target_market_label` with no country.
CREATE OR REPLACE VIEW _dest_region AS
  SELECT m.id, r.label AS region
  FROM models m
  JOIN _region_alias r
    ON regexp_matches(concat_ws(' | ', m.ipdb_notes, m.ipdb_notable_features), r.pattern);

-- assemble ──
-- One row per candidate model: which detectors fired, the parsed markets (country
-- slugs), and the maker-relative signal. "Export" is market-relative: a model built
-- for the SAME country its maker is based in is domestic, not export (Exports.md,
-- "Export is maker-relative"). market_is_maker_home flags those likely false
-- positives (e.g. Conquistador, a Portuguese maker's Portuguese-market game) for
-- review — it is a review signal, not an error, so it is NOT a check.
--   markets            : sorted country SLUGS parsed from the notes/name (may be empty)
--   regions            : sorted region LABELS parsed from the notes (the
--                        `target_market_label` case, e.g. ['Europe']); may be empty
--   market_kind        : how (if at all) the destination market is known —
--                        'country' if any country parsed, else 'region' if any region
--                        parsed, else 'unknown'. Mirrors the field the write path picks:
--                        country -> target_market_location, region -> target_market_label,
--                        unknown -> a ModelExportMarket row with neither, or no row at all.
--   maker_home_slug    : the maker's home country slug (model -> corporate_entity ->
--                        location), NULL when the maker has no located corporate entity
--   market_is_maker_home : a parsed market equals the maker's home country
-- MATERIALIZED (see the note on `_twin`). This is the hub of the file: five review views
-- build on it and `export_summary` reference-expands it ~30 times. As a view, every one
-- of those re-runs the whole detector stack (regex over ~6.9k notes, several times each)
-- and the summary exhausts memory. As a table it is computed once at init and every
-- consumer becomes a cheap scan. Still non-TEMP, so the UI sees it; nothing is persisted.
CREATE OR REPLACE TABLE export_candidates AS
  WITH ids AS (
    SELECT id FROM _by_notes
    UNION SELECT id FROM _dest_suffix
    UNION SELECT id FROM _by_opdb
    UNION SELECT id FROM _by_twin
  )
  SELECT
    m.id, m.name, m.manufacturer_name, m.opdb_id, m.label,
    EXISTS (SELECT 1 FROM _by_notes bn WHERE bn.id = m.id)          AS by_notes,
    EXISTS (SELECT 1 FROM _dest_suffix s WHERE s.id = m.id)         AS by_suffix,
    EXISTS (SELECT 1 FROM _by_opdb o WHERE o.id = m.id)             AS by_opdb,
    EXISTS (SELECT 1 FROM _by_twin t WHERE t.id = m.id)             AS by_twin,
    list_sort(list_distinct(
      COALESCE((SELECT list(d.dest) FROM _dest d WHERE d.id = m.id), []::VARCHAR[])
    )) AS markets,
    list_sort(list_distinct(
      COALESCE((SELECT list(dr.region) FROM _dest_region dr WHERE dr.id = m.id), []::VARCHAR[])
    )) AS regions,
    CASE
      WHEN EXISTS (SELECT 1 FROM _dest d WHERE d.id = m.id)        THEN 'country'
      WHEN EXISTS (SELECT 1 FROM _dest_region dr WHERE dr.id = m.id) THEN 'region'
      ELSE 'unknown'
    END AS market_kind,
    m.country_slug AS maker_home_slug,
    (SELECT name FROM countries WHERE slug = m.country_slug) AS maker_home_country,
    (m.country_slug IS NOT NULL
       AND EXISTS (SELECT 1 FROM _dest d WHERE d.id = m.id AND d.dest = m.country_slug)) AS market_is_maker_home,
    COALESCE((SELECT rewards FROM rewards rw WHERE rw.id = m.id), []::VARCHAR[]) AS rewards,
    m.ipdb_notes AS notes
  FROM models m
  WHERE m.id IN (SELECT id FROM ids)
    -- Positive exclusion: the twin sentence identifies this model as the DOMESTIC side,
    -- which outranks any freetext hit. A Petaco note says "export" only because it names
    -- its Recel twin; without this the domestic half of every pair is a false positive.
    AND m.id NOT IN (SELECT id FROM _twin WHERE role = 'domestic')
  ORDER BY m.name;

-- enrich ──
-- Candidate x lineage: does the model already carry a model->model edge? All three
-- facts read from the foundation's `model_edges` — its unified "every edge out of a
-- model" default — so a new edge mechanism added to the foundation is picked up here
-- automatically, instead of being silently missed by a hand-composed OR of sources.
--   has_variant_of : a variant_of edge exists
--   rel_types      : distinct TYPED ModelRelationship types (copy/conversion/...) —
--                    edges whose source is the relationship table, not the lineage FKs
--   has_edge       : ANY edge -> NOT "an export edition of nothing". This includes
--                    remake_of (a remake is still a model->model edge); no candidate
--                    carries one today, so it's a no-op on the current numbers.
-- MATERIALIZED for the same reason as `export_candidates` — the titlemate/orphan review
-- views and several summary rows all build on it.
CREATE OR REPLACE TABLE export_candidate_lineage AS
  SELECT
    c.id, c.name, c.label, c.by_notes, c.by_suffix, c.by_opdb, c.markets, c.rewards,
    EXISTS (SELECT 1 FROM model_edges e WHERE e.model_id = c.id AND e.relationship_type = 'variant_of') AS has_variant_of,
    COALESCE((
      SELECT list_sort(list_distinct(list(e.relationship_type)))
      FROM model_edges e WHERE e.model_id = c.id AND e.edge_source = 'relationship'
    ), []::VARCHAR[]) AS rel_types,
    EXISTS (SELECT 1 FROM model_edges e WHERE e.model_id = c.id) AS has_edge,
    (SELECT n FROM title_size ts WHERE ts.title_id = m.title_id) AS title_size,
    c.notes
  FROM export_candidates c
  JOIN models m ON m.id = c.id
  ORDER BY c.name;

-- review ──
-- Candidates that share a Title but carry no lineage edge. One row per
-- (candidate, title-mate) pair, to judge whether the candidate should be tied
-- to a mate — and, if so, how:
--   reward_differs : candidate and mate both have reward types, and they differ
--                    -> shape A, a reward-type variant_of the mate
--   same_maker     : same maker -> variant_of (family); different -> copy. Keyed
--                    on manufacturer_id — the user-facing maker brand. NOT
--                    corporate_entity_id (a single legal incarnation, which would
--                    split one brand's eras, e.g. Gottlieb, into "cross-maker"),
--                    and NOT the nullable IPDB trade-name text.
-- candidate_notes carries the FULL ipdb.notes free text for source review.
CREATE OR REPLACE VIEW export_titlemate_review AS
  SELECT
    c.id,
    c.label       AS candidate,
    c.rewards     AS candidate_rewards,
    c.markets,
    mate.label    AS titlemate,
    COALESCE((SELECT rewards FROM rewards rm WHERE rm.id = mate.id), []::VARCHAR[]) AS titlemate_rewards,
    (len(c.rewards) > 0
       AND len(COALESCE((SELECT rewards FROM rewards rm WHERE rm.id = mate.id), []::VARCHAR[])) > 0
       AND c.rewards <> COALESCE((SELECT rewards FROM rewards rm WHERE rm.id = mate.id), []::VARCHAR[])) AS reward_differs,
    (cm.manufacturer_id IS NOT NULL
       AND cm.manufacturer_id = mate.manufacturer_id) AS same_maker,
    c.notes       AS candidate_notes
  FROM export_candidate_lineage l
  JOIN export_candidates c ON c.id = l.id
  JOIN models cm            ON cm.id = c.id
  JOIN models mate          ON mate.title_id = cm.title_id AND mate.id <> c.id
  WHERE NOT l.has_edge AND l.title_size > 1
  ORDER BY c.name, mate.name;

-- Candidates with no lineage edge AND alone in their Title (no sibling in the
-- catalog). Probe whether ANY free text names an origin model. Free text scanned
-- = ipdb.notes + ipdb.notable_features + the description column (all the prose a
-- candidate carries).
--   quoted_names       : distinct 'Quoted Game Names' across that free text
--   quoted_in_catalog  : at least one of those names exists as a model today
--   relates_phrase     : free text uses a lineage phrase (copy/version/conversion
--                        of, similar to, same playfield as, made for export)
--   has_freetext       : any of the three sources is non-empty
-- Reading:
--   quoted_in_catalog            -> findable: author a copy (or variant) to it
--   quoted_names but not in cat. -> origin named but not yet a model: create it
--   has_freetext, no quoted name -> prose exists but names no model (shape C)
--   no freetext at all           -> genuine shape C: market fact, no lineage
-- freetext carries the FULL concatenated prose for source review.
CREATE OR REPLACE VIEW export_orphan_review AS
  WITH base AS (
    SELECT
      l.id, l.name AS candidate, l.label AS candidate_label, m.manufacturer_name AS candidate_maker,
      m.game_format_slug, l.markets, l.by_opdb,
      NULLIF(concat_ws(
        E'\n---\n',
        NULLIF(m.ipdb_notes, ''),
        NULLIF(m.ipdb_notable_features, ''),
        NULLIF(m.description, '')
      ), '') AS freetext
    FROM export_candidate_lineage l
    JOIN models m ON m.id = l.id
    WHERE NOT l.has_edge AND l.title_size <= 1
  ),
  scanned AS (
    SELECT
      b.*,
      -- Permissive quote class: IPDB mixes backtick/straight/curly quotes, e.g.
      -- Elite Guard's origin is written `Palace Guard' (backtick open). Surfaces
      -- some jargon too ('FunGame') — a review aid, verified against the note.
      list_distinct(regexp_extract_all(COALESCE(b.freetext, ''), '[`''‘“"]([A-Z][^`''’“”"]{1,40})[''’”"]', 1)) AS quoted_names,
      regexp_matches(COALESCE(b.freetext, ''),
        '(copy of|version of|conversion of|similar to|same (playfield )?(layout|design|game) as|made for export)') AS relates_phrase,
      (b.freetext IS NOT NULL) AS has_freetext
    FROM base b
  )
  SELECT
    s.*,
    EXISTS (
      SELECT 1 FROM models s2 WHERE list_contains(s.quoted_names, s2.name)
    ) AS quoted_in_catalog,
    CASE
      WHEN NOT s.has_freetext        THEN 'no freetext'
      WHEN len(s.quoted_names) = 0   THEN 'freetext, no origin named'
      ELSE 'origin named'
    END AS origin_lead
  FROM scanned s
  ORDER BY s.candidate;

-- Name-family regroup candidates for the alone-in-Title orphans. A candidate and
-- another model of the SAME MAKER (manufacturer_id — the brand, so a product line
-- spanning corporate eras still links) sit in separate singleton Titles but their
-- significant-name-token sets nest (one contains the other), e.g.
--   Palm Beach Club  <-  Palm Beach          Diamond Flipper Di Lusso <- Diamond Flipper
-- Token nesting (containment), not mere overlap, so 'Diamond Flipper' and
-- 'Golden Flipper' do NOT link (distinct games) while 'Circus' <- 'Super Circus'
-- does. relation reads from the MEMBER's side:
--   'member is base'      member's tokens ⊆ candidate's  (candidate adds a modifier)
--   'member extends'      candidate's tokens ⊆ member's  (member adds a modifier)
--   'same base'           identical token sets
-- Filter origin_lead='freetext, no origin named' for the shape-C set. Tiers: a
-- distinctive base theme (Palm Beach, Carrousel) is a strong regroup case; a
-- generic base (Flipper, Circus as a maker product line) is weaker — judge from
-- the note, this only narrows the field.
CREATE OR REPLACE VIEW export_name_family AS
  WITH toks AS (
    SELECT
      m.id, m.name, m.manufacturer_id AS mfr, m.title_id,
      list_sort(list_distinct(list_filter(
        string_split(lower(regexp_replace(m.name, '[^a-z0-9]+', ' ', 'g')), ' '),
        lambda t: length(t) >= 4 AND t NOT IN ('game', 'games', 'ball', 'balls', 'bingo')
      ))) AS tk
    FROM models m
  ),
  cand AS (
    SELECT o.id, o.candidate, o.candidate_label, o.origin_lead, o.markets
    FROM export_orphan_review o
  )
  SELECT
    c.candidate_label AS candidate, c.origin_lead, c.markets,
    ct.tk           AS candidate_tokens,
    (SELECT label FROM models WHERE id = n.id) AS family_member,
    n.tk            AS member_tokens,
    (n.title_id IS NOT NULL
       AND (SELECT n FROM title_size ts WHERE ts.title_id = n.title_id) = 1) AS member_alone_in_title,
    EXISTS (SELECT 1 FROM cand c2 WHERE c2.id = n.id) AS member_is_also_candidate,
    CASE
      WHEN ct.tk = n.tk                                       THEN 'same base'
      WHEN len(list_intersect(ct.tk, n.tk)) = len(n.tk)       THEN 'member is base'
      ELSE 'member extends'
    END AS relation
  FROM cand c
  JOIN toks ct ON ct.id = c.id
  JOIN toks n  ON n.mfr = ct.mfr AND n.id <> c.id
              AND len(ct.tk) > 0 AND len(n.tk) > 0
              AND (len(list_intersect(ct.tk, n.tk)) = len(n.tk)
                   OR len(list_intersect(ct.tk, n.tk)) = len(ct.tk))
  ORDER BY c.candidate, n.name;

-- Twin pairs, export side -> its named domestic counterpart. This is the most directly
-- actionable view in the file: each row is a ready-made `export_edition_of` edge
-- (export model IS the export edition of the domestic model), parsed deterministically
-- rather than guessed. `domestic_model_id IS NULL` means the note names a counterpart
-- that isn't in the catalog yet — create it, or reconcile the name.
-- Note the twin is NOT always the same title: Interflip's 'Dragon' pairs with
-- Recreativos Franco's 'Dragoon', and player counts can differ across the pair.
CREATE OR REPLACE VIEW export_twin_pairs AS
  SELECT
    t.id            AS export_model_id,
    m.label         AS export_model,
    t.twin_brand    AS domestic_brand,
    t.twin_name     AS domestic_name,
    t.twin_year     AS domestic_year,
    d.id            AS domestic_model_id,
    d.label         AS domestic_model,
    t.declared_role AS export_side_declared_role
  FROM _twin t
  JOIN models m ON m.id = t.id
  LEFT JOIN models d ON d.name = t.twin_name AND d.manufacturer_name = t.twin_brand
  WHERE t.role = 'export'
  ORDER BY m.label;

-- PARKED SET — "for the <X> market" phrasing, deliberately NOT candidates.
-- This phrasing was pulled out of `_by_notes` because it is mostly noise (see the note
-- there). These are the models it uniquely supplied: matched by the phrase, but claimed
-- by NO other detector, so removing the clause dropped them from `export_candidates`.
-- Kept here so the ~5 genuine ones aren't lost — a later pass triages this view and
-- promotes the real exports (by fixing their source data or adding a precise detector).
-- `lead` is the triage signal:
--   'foreign country'    a parsed market that is NOT the maker's home -> likely a real
--                        export (Vector/German market, Grande Domino/Italian market)
--   'maker-home country' parsed market == maker's home -> domestic, not export
--   'region'            an export-context region phrase resolved instead of a country
--   'no market'         the phrase matched but nothing resolved -> almost all noise
CREATE OR REPLACE VIEW export_market_phrase_review AS
  WITH matched AS (
    SELECT id FROM (
      SELECT id, regexp_replace(COALESCE(ipdb_notes, ''), '(?i)quantity produced for export', '', 'g') AS n
      FROM models
    ) WHERE n ILIKE '%for the % market%'
  ),
  claimed AS (
    SELECT id FROM _by_notes
    UNION SELECT id FROM _dest_suffix
    UNION SELECT id FROM _by_opdb
  )
  SELECT
    m.id,
    m.label,
    list_sort(list_distinct(
      COALESCE((SELECT list(d.dest) FROM _dest d WHERE d.id = m.id), []::VARCHAR[])
    )) AS parsed_market,
    m.country_slug AS maker_home_slug,
    CASE
      WHEN EXISTS (SELECT 1 FROM _dest d WHERE d.id = m.id
                     AND d.dest IS DISTINCT FROM m.country_slug)        THEN 'foreign country'
      WHEN EXISTS (SELECT 1 FROM _dest d WHERE d.id = m.id)             THEN 'maker-home country'
      WHEN EXISTS (SELECT 1 FROM _dest_region r WHERE r.id = m.id)      THEN 'region'
      ELSE 'no market'
    END AS lead,
    m.ipdb_notes AS notes
  FROM models m
  JOIN matched x ON x.id = m.id
  WHERE m.id NOT IN (SELECT id FROM claimed)
  ORDER BY lead, m.label;

-- Market review: one row per candidate focused on the DESTINATION market, to fill
-- the ModelExportMarket rows (Exports.md → Location). `market_kind` is the headline —
-- 'country' rows map to `target_market_location`, 'region' to `target_market_label`,
-- 'unknown' to a row with neither (or no row at all). `n_markets` > 1 flags the rare
-- multi-country build (the join table's reason for being). `notes` carries the source
-- text so a reviewer can fill or correct a market the narrow parser missed — 'unknown'
-- does NOT mean the prose names no market, only that no detector resolved one.
CREATE OR REPLACE VIEW export_market_review AS
  SELECT
    c.id, c.label AS candidate, c.manufacturer_name,
    c.market_kind,
    c.markets,
    len(c.markets)      AS n_markets,
    c.regions,
    c.maker_home_country,
    c.market_is_maker_home,
    c.notes
  FROM export_candidates c
  ORDER BY c.market_kind, c.name;

-- ── 4 · SUMMARY & CHECKS ───────────────────────────────────────────────────
-- The honest-prose tail. Every plan file keeps these two views.

-- export_summary — the headline numbers Exports.md quotes, sourced from the views
-- rather than hand-counted. Regenerate the Summary section from this; if a number
-- in the prose and a number here disagree, the prose is stale.
--
-- Every figure here has a reproducible definition. The no-origin orphans' leaf
-- split is now genre-backed: Bingo Pinball and Slot Machine are counted from the
-- game_format FK (below). Only the residual — pinball/other with no origin named —
-- stays prose, since "why is this pinball origin-less" is a per-row source read.
CREATE OR REPLACE VIEW export_summary AS
  -- Detectors and candidate set.
  SELECT 'candidates'          AS metric, count(*)                        AS value FROM export_candidates
  UNION ALL SELECT 'by_notes',           count(*) FILTER (WHERE by_notes)  FROM export_candidates
  UNION ALL SELECT 'by_suffix',          count(*) FILTER (WHERE by_suffix) FROM export_candidates
  UNION ALL SELECT 'by_opdb',            count(*) FILTER (WHERE by_opdb)   FROM export_candidates
  UNION ALL SELECT 'by_twin',            count(*) FILTER (WHERE by_twin)   FROM export_candidates
  -- Twin pairs: deterministic export_edition_of edges, and the domestic halves the twin
  -- sentence positively excludes from the candidate set.
  UNION ALL SELECT 'twin_pairs',          (SELECT count(*) FROM export_twin_pairs)
  UNION ALL SELECT 'twin_pairs_resolved', (SELECT count(*) FROM export_twin_pairs WHERE domestic_model_id IS NOT NULL)
  UNION ALL SELECT 'twin_domestic_excluded', (SELECT count(*) FROM _twin WHERE role = 'domestic')
  UNION ALL SELECT 'opdb_notes_overlap', count(*) FILTER (WHERE by_opdb AND by_notes) FROM export_candidates
  -- Maker-relative: candidates whose parsed market IS the maker's home country
  -- (likely domestic, not export — a review signal, e.g. Conquistador, Univerx).
  UNION ALL SELECT 'market_is_maker_home', count(*) FILTER (WHERE market_is_maker_home) FROM export_candidates
  -- Destination market: how often is one known, and of what kind? (Exports.md → Location.)
  -- market_kind partitions the candidate set: country + region + unknown == candidates.
  UNION ALL SELECT 'market_country',   count(*) FILTER (WHERE market_kind = 'country') FROM export_candidates
  UNION ALL SELECT 'market_region',    count(*) FILTER (WHERE market_kind = 'region')  FROM export_candidates
  UNION ALL SELECT 'market_unknown',   count(*) FILTER (WHERE market_kind = 'unknown') FROM export_candidates
  -- Cardinality of the country markets: single vs the rare multi-country build that is
  -- the ModelExportMarket join table's whole reason for being.
  UNION ALL SELECT 'market_one_country',    count(*) FILTER (WHERE len(markets) = 1) FROM export_candidates
  UNION ALL SELECT 'market_multi_country',  count(*) FILTER (WHERE len(markets) > 1) FROM export_candidates
  -- Parked "for the <X> market" hits: dropped from membership as noise, held for a
  -- later pass. `_foreign` is the subset worth rescuing (a non-maker-home market).
  UNION ALL SELECT 'market_phrase_parked',
    (SELECT count(*) FROM export_market_phrase_review)
  UNION ALL SELECT 'market_phrase_parked_foreign',
    (SELECT count(*) FROM export_market_phrase_review WHERE lead = 'foreign country')
  -- Lineage: does the candidate already carry an edge?
  UNION ALL SELECT 'has_edge',           count(*) FILTER (WHERE has_edge)      FROM export_candidate_lineage
  UNION ALL SELECT 'no_edge',            count(*) FILTER (WHERE NOT has_edge)  FROM export_candidate_lineage
  UNION ALL SELECT 'no_edge_share_title', count(*) FILTER (WHERE NOT has_edge AND title_size > 1)  FROM export_candidate_lineage
  UNION ALL SELECT 'no_edge_alone',        count(*) FILTER (WHERE NOT has_edge AND title_size <= 1) FROM export_candidate_lineage
  -- Share-a-title candidates partitioned by reward-type signal: variant / copy /
  -- need-notes sum to no_edge_share_title. same_maker keys on manufacturer_id, so
  -- 'copy' is a cross-BRAND reward-differing mate; one qualifying mate is enough.
  UNION ALL SELECT 'share_title_variant_signal',
    (SELECT count(DISTINCT id) FROM export_titlemate_review WHERE reward_differs AND same_maker)
  UNION ALL SELECT 'share_title_copy_signal',
    (SELECT count(*) FROM (SELECT id FROM export_titlemate_review GROUP BY id
       HAVING bool_or(reward_differs AND NOT same_maker) AND NOT bool_or(reward_differs AND same_maker)))
  UNION ALL SELECT 'share_title_need_notes',
    (SELECT count(*) FROM (SELECT id FROM export_titlemate_review GROUP BY id
       HAVING NOT bool_or(reward_differs)))
  -- Alone-in-title orphans, by whether their free text leads anywhere.
  UNION ALL SELECT 'alone_origin_named',      count(*) FILTER (WHERE origin_lead = 'origin named')                              FROM export_orphan_review
  UNION ALL SELECT 'alone_origin_in_catalog', count(*) FILTER (WHERE quoted_in_catalog)                                        FROM export_orphan_review
  UNION ALL SELECT 'alone_no_origin',         count(*) FILTER (WHERE origin_lead IN ('freetext, no origin named','no freetext')) FROM export_orphan_review
  -- No-origin leaf split by genre: bingos and slots have no pinball analogue.
  -- Predicated on the stable game_format_slug, not the display name.
  UNION ALL SELECT 'alone_no_origin_bingo',   count(*) FILTER (WHERE origin_lead IN ('freetext, no origin named','no freetext') AND game_format_slug = 'bingo-pinball') FROM export_orphan_review
  UNION ALL SELECT 'alone_no_origin_slot',    count(*) FILTER (WHERE origin_lead IN ('freetext, no origin named','no freetext') AND game_format_slug = 'slot-machine')  FROM export_orphan_review
  -- residual: no-origin models that are neither bingo nor slot (pinball/other, per-row read).
  -- bingo + slot + other == alone_no_origin, so the leaf split is self-checking.
  UNION ALL SELECT 'alone_no_origin_other',    count(*) FILTER (WHERE origin_lead IN ('freetext, no origin named','no freetext') AND game_format_slug IS DISTINCT FROM 'bingo-pinball' AND game_format_slug IS DISTINCT FROM 'slot-machine') FROM export_orphan_review
  -- Name-family regroup: candidates with a same-maker singleton-Title sibling, and
  -- the shape-C (no-origin) subset of those.
  UNION ALL SELECT 'name_family_candidates',
    (SELECT count(DISTINCT candidate) FROM export_name_family)
  UNION ALL SELECT 'name_family_shape_c',
    (SELECT count(DISTINCT candidate) FROM export_name_family WHERE origin_lead = 'freetext, no origin named')
  ORDER BY metric;

-- export_checks — invariants that should always hold. Empty result = healthy; any
-- row is a problem to investigate. Query `FROM export_checks;` after each re-run.
-- Three check classes (see scripts/analysis/README.md):
--   Structural : joins preserve grain; the detector set covers the candidates
--   Vocabulary : parsed values belong to a closed set (markets are countries)
--   Anchors    : each heuristic still fires on a known example — the only class
--                that catches a whole detector going dark, which a row-level
--                invariant cannot see.
CREATE OR REPLACE VIEW export_checks AS
  -- Structural: every candidate appears exactly once in the lineage view.
  SELECT 'lineage_missing_candidate' AS check, c.id, c.name AS detail
  FROM export_candidates c
  WHERE NOT EXISTS (SELECT 1 FROM export_candidate_lineage l WHERE l.id = c.id)
  UNION ALL
  -- Structural: a suffix hit always parses a country, so its markets can't be empty.
  SELECT 'suffix_without_market', c.id, c.name
  FROM export_candidates c
  WHERE c.by_suffix AND len(c.markets) = 0
  UNION ALL
  -- Vocabulary: every parsed market slug must be a known country slug.
  SELECT 'market_not_a_country', c.id, mkt
  FROM export_candidates c, UNNEST(c.markets) AS t(mkt)
  WHERE mkt NOT IN (SELECT slug FROM countries)
  UNION ALL
  -- Vocabulary: every parsed region label must belong to the declared region set.
  SELECT 'region_not_declared', c.id, rgn
  FROM export_candidates c, UNNEST(c.regions) AS t(rgn)
  WHERE rgn NOT IN (SELECT label FROM _region_alias)
  UNION ALL
  -- Structural: market_kind must partition the candidates (country|region|unknown), and
  -- must agree with the parsed lists — a 'country' kind needs a country, 'region' a region.
  SELECT 'market_kind_disagrees', c.id, c.market_kind
  FROM export_candidates c
  WHERE c.market_kind NOT IN ('country','region','unknown')
     OR (c.market_kind = 'country' AND len(c.markets) = 0)
     OR (c.market_kind = 'region'  AND (len(c.regions) = 0 OR len(c.markets) > 0))
     OR (c.market_kind = 'unknown' AND (len(c.markets) > 0 OR len(c.regions) > 0))
  UNION ALL
  -- Anchor: the region detector still fires (Phantom Haus is "made for Europe").
  SELECT 'anchor_region_dark', NULL::BIGINT, 'the export-context region detector matched zero models'
  WHERE NOT EXISTS (SELECT 1 FROM export_candidates WHERE market_kind = 'region')
  UNION ALL
  -- Vocabulary: the maker-home slug backing market_is_maker_home must be a country
  -- slug — guards the maker-relative join against a non-country location root.
  SELECT 'maker_home_not_a_country', c.id, c.maker_home_slug
  FROM export_candidates c
  WHERE c.maker_home_slug IS NOT NULL AND c.maker_home_slug NOT IN (SELECT slug FROM countries)
  UNION ALL
  -- Structural: the four detectors must cover the candidate set with nothing left over.
  SELECT 'candidate_without_detector', c.id, c.name
  FROM export_candidates c
  WHERE NOT (c.by_notes OR c.by_suffix OR c.by_opdb OR c.by_twin)
  UNION ALL
  -- Vocabulary/agreement: the twin sentence and the independent "is the name used for
  -- <role> games" sentence must never disagree. This is the whole basis for trusting the
  -- twin parse as deterministic — two independent statements of the same fact. A row here
  -- means the boilerplate changed shape and the parse can no longer be trusted.
  SELECT 'twin_role_contradiction', t.id, t.role || ' vs declared ' || t.declared_role
  FROM _twin t
  WHERE t.declared_role IS NOT NULL AND t.declared_role <> t.role
  UNION ALL
  -- Structural: every "same company made ... version as" sentence must PARSE. Coverage,
  -- not correctness — a new phrasing variant (the qualifier already floats) would
  -- silently drop a pair otherwise.
  SELECT 'twin_sentence_unparsed', m.id, m.name
  FROM models m
  WHERE m.ipdb_notes ILIKE '%same company made%'
    AND NOT EXISTS (SELECT 1 FROM _twin t WHERE t.id = m.id)
  UNION ALL
  -- Structural: the twin roles are opposites, so a model can never be both.
  SELECT 'twin_both_roles', t.id, 'model is both export and domestic side'
  FROM _twin t GROUP BY t.id HAVING count(DISTINCT t.role) > 1
  UNION ALL
  -- Structural: no domestic-side twin may survive as a candidate — that exclusion is the
  -- point of the detector.
  SELECT 'domestic_twin_is_candidate', c.id, c.name
  FROM export_candidates c
  WHERE EXISTS (SELECT 1 FROM _twin t WHERE t.id = c.id AND t.role = 'domestic')
  UNION ALL
  -- Structural: the parked market-phrase set is by definition the rows NO detector
  -- claims, so it must be disjoint from the candidates. Overlap means the clause leaked
  -- back into membership.
  SELECT 'parked_phrase_is_candidate', p.id, p.label
  FROM export_market_phrase_review p
  WHERE EXISTS (SELECT 1 FROM export_candidates c WHERE c.id = p.id)
  UNION ALL
  -- Anchor: the (Country) suffix detector still catches the plan's own example.
  SELECT 'anchor_suffix_dark', NULL::BIGINT, 'Big Ben (Italy) no longer hits by_suffix'
  WHERE NOT EXISTS (SELECT 1 FROM export_candidates WHERE by_suffix AND name = 'Big Ben (Italy)')
  UNION ALL
  -- Anchor: the ipdb.notes freetext detector still matches something.
  SELECT 'anchor_notes_dark', NULL::BIGINT, 'the ipdb.notes detector matched zero models'
  WHERE NOT EXISTS (SELECT 1 FROM export_candidates WHERE by_notes)
  UNION ALL
  -- Anchor: the opdb.features flag detector still matches something.
  SELECT 'anchor_opdb_dark', NULL::BIGINT, 'the opdb.features detector matched zero models'
  WHERE NOT EXISTS (SELECT 1 FROM export_candidates WHERE by_opdb)
  UNION ALL
  -- Vocabulary/anchor: the game_format slugs the summary counts by must still exist.
  -- A slug change would silently zero alone_no_origin_bingo / _slot with no error;
  -- only this check sees it go dark. Reads the foundation's game_formats vocabulary.
  SELECT 'game_format_vocab_dark', NULL::BIGINT, gf
  FROM (VALUES ('bingo-pinball'), ('slot-machine')) AS t(gf)
  WHERE gf NOT IN (SELECT slug FROM game_formats)
  UNION ALL
  -- Structural: the two no-edge buckets must partition no_edge. They rely on
  -- title_size being non-NULL — a null-title candidate falls out of BOTH (its
  -- title_size comparisons go NULL), and only this sum catches the silent drop.
  SELECT 'no_edge_partition_broken', NULL::BIGINT, 'share_title + alone != no_edge'
  WHERE (SELECT count(*) FROM export_candidate_lineage WHERE NOT has_edge)
     <> (SELECT count(*) FROM export_candidate_lineage WHERE NOT has_edge AND title_size > 1)
      + (SELECT count(*) FROM export_candidate_lineage WHERE NOT has_edge AND title_size <= 1);
