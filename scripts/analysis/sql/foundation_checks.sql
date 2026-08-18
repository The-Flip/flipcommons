-- Foundation self-test — the one gate over every layer's invariants, plus the
-- cross-layer checks that belong to no single layer: the macro smoke tests (gathered
-- in one place so a missing one is noticeable), the staging fixtures, and the coverage
-- meta-checks that fail when a new entity, alias table or view is added without the
-- exposure the layer promises.
--
-- NOT part of the foundation (no check logic lives in the layer files); this is a
-- separate consumer, with the same summary/checks contract the runner gates on. It
-- runs at snapshot BUILD time — every edit to a sql/ file triggers a rebuild, and the
-- rebuild evaluates every checks view and stores the verdicts — so there is no
-- separate self-test step:
--
--     scripts/analysis/analysis run foundation
--
-- prints foundation_summary (row count per view — a health readout) and the stored
-- verdicts, failing nonzero on any failing check. EMPTY foundation_checks = healthy.
--
-- Loads last of the checks files (see analytics.sql): `foundation_checks` folds in the
-- per-layer checks views — `_catalog_checks`, `_prose_checks`, `_provenance_checks`,
-- `_data_patch_checks` — so there is ONE gate and one mutation-harness entry point.
--
-- Adding or changing a check? Read scripts/analysis/EDITING.md first — every check
-- needs a mutation in catalog_mutations.tsv proving it fires, and check-mutations
-- enforces that in both directions.
-- Two classes:
--   structural — data-independent invariants; a row means the SQL logic broke, not
--                that the catalog changed. These make evolving the foundation safe.
--   coverage   — meta-checks that fail when a new entity, alias table or view is added
--                without the exposure the layer promises.

-- ═══ §240 FOUNDATION SELF-TEST — invariants of this layer ══════════════════

-- Check-only scaffolding, same rules as the per-layer checks files: private views a
-- check can read (and check-mutations can break), consumed by no public view.

-- _alias_tables — the physical alias/abbreviation lookup tables, derived from the
-- attached catalog rather than hand-listed. Every `AliasModel` subclass gets a
-- `catalog_<parent>alias` table and the two abbreviation through-models get
-- `catalog_<parent>abbreviation`, so the naming convention IS the registry as far as
-- SQL can see it. Feeds `unexposed_alias_table`.
CREATE OR REPLACE VIEW _alias_tables AS
  SELECT table_name FROM duckdb_tables()
  WHERE database_name = current_database() AND schema_name = 'raw'
    AND (table_name LIKE 'catalog\_%alias' ESCAPE '\'
      OR table_name LIKE 'catalog\_%abbreviation' ESCAPE '\');

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
  WHERE database_name = current_database() AND schema_name = 'raw' AND table_name LIKE 'catalog\_%' ESCAPE '\'
  GROUP BY table_name
  HAVING bool_or(column_name = 'slug') AND bool_or(column_name = 'status');

-- _entity_view — hand-input: which view exposes each entity. Only the MAPPING is
-- hand-maintained; the entity set above is derived, so the hand-list can fall behind in
-- exactly one direction and `unexposed_entity` catches that.
--
-- There are no exemptions, and the absence of an exemption column is the point. The
-- seven taxonomy dims used to be listed here as deliberately-unexposed, on the argument
-- that their slug on `models` is both the readable label and the raw-join key back to
-- raw.catalog_<dim>. That argument holds for the model row and does not extend to the
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
    ('catalog_tag',                     'tags'),
    ('catalog_theme',                   'themes'),
    ('catalog_gameplayfeature',         'gameplay_features'),
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
-- depends on what the data happens to hold. That is how a `_staging()` smoke check keyed to a
-- vocabulary with no deleted rows passed while proving nothing. These tables supply the
-- cases instead of hoping for them.
-- The schema is taken from the real table with LIMIT 0, so a fixture cannot drift from
-- its source the way a hand-declared one would; only the rows are ours.
CREATE OR REPLACE TABLE _fx_lifecycle AS SELECT * FROM raw.catalog_cabinet LIMIT 0;
INSERT INTO _fx_lifecycle (id, slug, name, description, display_order, status, created_at, updated_at)
VALUES (1, 'live-null-status', 'A', '',    0, NULL,      '2020-01-01', '2020-01-01'),
       (2, 'live-active',      'B', 'has', 1, 'active',  '2020-01-01', '2020-01-01'),
       (3, 'soft-deleted',     'C', 'has', 2, 'deleted', '2020-01-01', '2020-01-01');

-- _fx_claim_value — the JSON shapes a claim value comes in, for _json_scalar_text.
CREATE OR REPLACE TABLE _fx_claim_value AS
  SELECT id, value FROM raw.provenance_claim LIMIT 0;
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
-- `SELECT id, slug, name, description FROM raw.catalog_<x> WHERE status IS DISTINCT FROM
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
    UNION ALL SELECT 'model_reward_names'             FROM model_reward_names
    UNION ALL SELECT 'model_theme_names'              FROM model_theme_names
    UNION ALL SELECT 'model_tag_slugs'                FROM model_tag_slugs
    UNION ALL SELECT 'model_gameplay_features' FROM model_gameplay_features
    UNION ALL SELECT 'gameplay_features'   FROM gameplay_features
    UNION ALL SELECT 'gameplay_feature_aliases' FROM gameplay_feature_aliases
    UNION ALL SELECT 'model_themes'        FROM model_themes
    UNION ALL SELECT 'model_tags'          FROM model_tags
    UNION ALL SELECT 'model_rewards'       FROM model_rewards
    UNION ALL SELECT 'themes'         FROM themes
    UNION ALL SELECT 'theme_aliases'       FROM theme_aliases
    UNION ALL SELECT 'model_export_markets' FROM model_export_markets
    UNION ALL SELECT 'corporate_entity_locations' FROM corporate_entity_locations
    UNION ALL SELECT 'locations'           FROM locations
    UNION ALL SELECT 'tags'           FROM tags
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
    UNION ALL SELECT 'domain_vocab'        FROM domain_vocab
    UNION ALL SELECT 'entity_registry'     FROM entity_registry
    UNION ALL SELECT 'entity_subjects'     FROM entity_subjects
    UNION ALL SELECT 'entity_prose'        FROM entity_prose
    UNION ALL SELECT 'entity_aliases'      FROM entity_aliases
    UNION ALL SELECT 'entity_names'        FROM entity_names
    UNION ALL SELECT 'collapsed_models'    FROM collapsed_models
    UNION ALL SELECT 'record_references'   FROM record_references
    UNION ALL SELECT 'prose_words'         FROM prose_words
    UNION ALL SELECT 'prose_quotes'        FROM prose_quotes
    UNION ALL SELECT 'prose_parentheticals' FROM prose_parentheticals
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

  -- The house-parenthetical parse (prose.sql), pinned on literals so the regex rotting
  -- cannot go dark: the failure mode is every consumer quietly finding zero
  -- parentheticals, which is also what a clean catalog looks like.
  SELECT 'macro_paren_pattern',
         regexp_extract('_[[model:id:123]]_ (1997, [[manufacturer:id:45]])', _paren_pattern(),
                        ['link_type', 'link_id', 'stated_year', 'stated_maker'])::VARCHAR
  WHERE regexp_extract('_[[model:id:123]]_ (1997, [[manufacturer:id:45]])', _paren_pattern(),
                       ['link_type', 'link_id', 'stated_year', 'stated_maker'])
        IS DISTINCT FROM {link_type: 'model', link_id: '123', stated_year: '1997', stated_maker: '45'}
     -- the no-maker form matches with an EMPTY maker group, which prose_parentheticals
     -- folds to NULL
     OR regexp_extract('[[title:id:7]] (2001)', _paren_pattern(),
                       ['link_type', 'link_id', 'stated_year', 'stated_maker'])
        IS DISTINCT FROM {link_type: 'title', link_id: '7', stated_year: '2001', stated_maker: ''}
     -- only a model or title link anchors a parenthetical
     OR len(regexp_extract_all('[[person:id:9]] (1997)', _paren_pattern())) IS DISTINCT FROM 0
     -- a two-digit year is prose, not a stated fact
     OR len(regexp_extract_all('[[model:id:1]] (97)', _paren_pattern())) IS DISTINCT FROM 0
     -- a WORD between the link and the parenthetical makes it a sentence, not the
     -- convention: admitting one turns correct prose into a parenthetical-fact error
     OR len(regexp_extract_all('[[title:id:7]] Remake (2014)', _paren_pattern())) IS DISTINCT FROM 0
     -- ...while the emphasis markers the convention itself writes must still anchor one
     OR len(regexp_extract_all('*[[title:id:7]]* (2014)', _paren_pattern())) IS DISTINCT FROM 1
  UNION ALL
  -- The quoted-run definition (prose.sql). Both directions are pinned because one macro
  -- serves both: prose_quotes EXTRACTS with it and prose_words EXCLUDES with it, so a
  -- rot empties the first while handing every quoted wording to the second as ordinary
  -- prose — two silent failures, neither distinguishable from a clean catalog.
  SELECT 'macro_quoted_run',
         regexp_extract_all('He called it "The Machine" once', _quoted_run())::VARCHAR
  WHERE regexp_extract_all('He called it "The Machine" once', _quoted_run())
        IS DISTINCT FROM ['"The Machine"']
     -- curly doubles are the same run
     OR regexp_extract_all('a “Curly Name” here', _quoted_run()) IS DISTINCT FROM ['“Curly Name”']
     -- a long quote is still a quote; a cap below one drops it from prose_quotes AND
     -- leaves it in prose_words, which is the direction that fabricates mentions
     OR len(regexp_extract_all('"' || repeat('x', 229) || '"', _quoted_run())) IS DISTINCT FROM 1
     -- an unclosed mark yields nothing rather than swallowing the line below it
     OR len(regexp_extract_all('say "unclosed' || chr(10) || 'next line', _quoted_run())) IS DISTINCT FROM 0
     -- the exclusion direction, which is what prose_words applies
     OR regexp_replace('say "quoted" here', _quoted_run(), ' ', 'g') IS DISTINCT FROM 'say   here'
     -- INCH MARKS ARE NOT QUOTES: pairing two of them deletes every word between from
     -- prose_words, and losing text raises no finding anywhere
     OR len(regexp_extract_all('The 3" flipper and Attack From Mars and a 5" ramp',
                               _quoted_run())) IS DISTINCT FROM 0
     -- ...while a genuine quote may still open on a digit or close on one
     OR regexp_extract_all('a "2.0" upgrade', _quoted_run()) IS DISTINCT FROM ['"2.0"']
     OR regexp_extract_all('"Attack From Mars 2" here', _quoted_run())
        IS DISTINCT FROM ['"Attack From Mars 2"']
  UNION ALL
  -- The shared tokenization (prose.sql), stated against input we control. Every strip
  -- here fails the same silent way: the rows survive, the WORDS are wrong, and a corpus
  -- with no markup left in it looks exactly like a corpus that was tokenized correctly.
  SELECT 'macro_prose_tokens', _prose_tokens('See [[title:id:5]] here')::VARCHAR
     -- wikilink markup goes; the prose around it stays
  WHERE _prose_tokens('See [[title:id:5]] here') IS DISTINCT FROM ['See', 'here']
     -- a markdown link contributes its visible text, never its destination: the URL
     -- path would otherwise read as a catalog name no author wrote
     OR _prose_tokens('See [IPDB](https://x.org/Attack_From_Mars) here')
        IS DISTINCT FROM ['See', 'IPDB', 'here']
     -- quoted wordings belong to prose_quotes, not to the span coordinate system
     OR _prose_tokens('a "Quoted Name" b') IS DISTINCT FROM ['a', 'b']
     -- accents fold, CASE IS KEPT — the game Pinball stays distinct from the word
     OR _prose_tokens('Pokémon Pinball') IS DISTINCT FROM ['Pokemon', 'Pinball']
     -- punctuation collapses to one break rather than to empty words, which would
     -- shift every position downstream
     OR _prose_tokens('Foo, bar; baz!') IS DISTINCT FROM ['Foo', 'bar', 'baz']
     -- a destination may carry balanced parentheses (CommonMark allows them, Wikipedia
     -- disambiguators use them); stopping at the first one leaks the rest as prose
     OR _prose_tokens('See [source](https://x.org/(Attack)_From_Mars) here')
        IS DISTINCT FROM ['See', 'source', 'here']
     OR _prose_tokens('See [w](https://en.wikipedia.org/wiki/Medieval_Madness_(pinball)) x')
        IS DISTINCT FROM ['See', 'w', 'x']
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
  -- ── _staging() and _blanks_null(), proven against fixture input ──
  -- Data-independent: these assert the three halves of the contract on rows that exist
  -- because we put them there, so none of it rides on the catalog happening to contain a
  -- soft-deleted cabinet or a blank description.
  SELECT 'fixture_staging_liveness',
         'expected ids 1,2 — got ' || coalesce((SELECT string_agg(id::VARCHAR, ',' ORDER BY id)
                                                FROM _staging('_fx_lifecycle')), '<none>')
  WHERE (SELECT string_agg(id::VARCHAR, ',' ORDER BY id) FROM _staging('_fx_lifecycle'))
        IS DISTINCT FROM '1,2'

  UNION ALL
  SELECT 'fixture_staging_excludes_bookkeeping', column_name
  FROM (DESCRIBE SELECT * FROM _staging('_fx_lifecycle'))
  WHERE column_name IN ('status', 'created_at', 'updated_at')

  -- _blanks_null folds '' to NULL and leaves a real value alone. Asserted through _staging(),
  -- which composes it, so the composition is covered too.
  UNION ALL
  SELECT 'fixture_blanks_null',
         'id1=' || coalesce((SELECT description FROM _staging('_fx_lifecycle') WHERE id = 1), '<NULL>')
      || ' id2=' || coalesce((SELECT description FROM _staging('_fx_lifecycle') WHERE id = 2), '<NULL>')
  WHERE (SELECT description FROM _staging('_fx_lifecycle') WHERE id = 1) IS NOT NULL
     OR (SELECT description FROM _staging('_fx_lifecycle') WHERE id = 2) IS DISTINCT FROM 'has'

  -- One expected-vs-actual string, so a regression names what it produced.
  UNION ALL
  SELECT 'fixture_json_scalar_text',
         (SELECT string_agg(coalesce(_json_scalar_text(value), '<NULL>'), ',' ORDER BY id)
          FROM _fx_claim_value)
  WHERE (SELECT string_agg(coalesce(_json_scalar_text(value), '<NULL>'), ',' ORDER BY id)
         FROM _fx_claim_value)
        IS DISTINCT FROM '500,500,<NULL>,<NULL>,<NULL>,<NULL>'
  UNION ALL
  -- ── the OUTCOME, asserted across every entity view at once ──
  -- The fixtures prove the macro; these prove it was actually applied. A view that
  -- hand-rolls its own projection and forgets is caught here regardless of how it is
  -- written, which is the failure that got past us: `macro_live` was deleted as redundant
  -- with `anchor_dark`, and `anchor_dark` was deleted in the same breath.
  SELECT 'entity_view_leaks_bookkeeping', c.table_name || '.' || c.column_name
  FROM duckdb_columns() c
  JOIN _entity_view e ON e.view_name = c.table_name
  WHERE c.database_name = current_database()
    AND c.column_name IN ('status', 'created_at', 'updated_at')
    -- provenance entities have no lifecycle and carry these legitimately
    -- Lifecycle entities only. Not "the source has a status column": provenance_ingestrun
    -- has one and it is the RUN's status, nothing to do with soft-delete. _entity_table is
    -- the derived set, so provenance entities fall out structurally.
    AND e.entity_table IN (SELECT table_name FROM _entity_table)
  UNION ALL
  -- Every entity view over a LIFECYCLE table reaches its rows through _staging(), directly or
  -- through a stg.* leaf that does. Keyed on the source table carrying `status`, so
  -- provenance entities fall out structurally rather than by exemption.
  SELECT 'entity_view_not_live_filtered', e.view_name
  FROM _entity_view e
  JOIN duckdb_views() v ON v.view_name = e.view_name AND v.database_name = current_database()
  WHERE e.entity_table IN (SELECT table_name FROM _entity_table)
    -- A TEXT match, with the limit that implies: it catches a view that forgot to filter,
    -- not one that mentions _staging() or a stg.* leaf without reading through it. Naming
    -- the leaves instead of wildcarding does not change that — a bypass smuggling the token
    -- through a no-op subquery passes either way. An exact check is not available:
    -- query_table() takes literals only, so "compare each view against _staging() of its
    -- source" cannot be written once over the entity set.
    AND v.sql NOT LIKE '%_staging(%'
    AND v.sql NOT LIKE '%stg.%'
  UNION ALL
  -- The staging layer's one property: a `stg.*` view is a bare read of a single table. No
  -- join, no aggregate, no derived column — which is what leaves it with no outgoing edge,
  -- and what makes a cycle THROUGH it impossible rather than merely absent today. A join
  -- added here restores the hazard the layer exists to remove, and restores it silently:
  -- the view still returns the right rows, and the cycle only appears later, in whichever
  -- unrelated view next tries to compose. A text match, with the limits of one — it catches
  -- the shape going wrong, not a bare read that is somehow still wrong. The stg SCHEMA is
  -- the layer's boundary, so membership is by schema, not by name prefix.
  SELECT 'staging_view_not_flat', v.view_name
  FROM duckdb_views() v
  WHERE v.database_name = current_database()
    AND v.schema_name = 'stg'
    AND (v.sql ILIKE '%join%' OR v.sql ILIKE '%group by%')
  UNION ALL
  -- A public view missing from every `*_summary` — the same coverage claim the entity
  -- and alias coverage checks make, for the other hand-list. It drifted the first time
  -- it could: a whole layer's five views went unsummarized, so the health readout
  -- silently stopped describing the foundation while the self-test stayed green. Every
  -- layer in the session carries its own summary (foundation_summary, audit_summary),
  -- so the claim is "counted in SOME public summary", not in one named view. The
  -- summary / checks / context families are excluded by suffix — a summary does not
  -- summarize itself, and a watermark's NULLs are legitimate on a fresh DB.
  --
  -- Matched against the summary's own SQL rather than by selecting from it, the way
  -- `unexposed_alias_table` matches view text. Reading `SELECT view_name FROM
  -- foundation_summary` would be the direct statement and costs ~1.7s — it evaluates
  -- every count in the summary. This claim is structural and shouldn't be paying for
  -- row counts to make it.
  --
  -- BOTH the quoted label and the FROM clause, because neither is exact alone. The
  -- label is quote-delimited so a short view name cannot match inside a longer one; the FROM
  -- test is a bare prefix so `FROM model_edges` does match inside `FROM
  -- model_edges_bidir`. ANDing them takes the label's exactness and adds the assertion
  -- that the view is actually COUNTED rather than merely named. The label has a second
  -- accepted spelling, taken only from the summary sharing the view's prefix: audit_summary
  -- labels `audit_wrong_grain_link` as 'wrong-grain-link' — the prefix dropped, hyphens for
  -- underscores — and only the layer's own summary may vouch for a view that way.
  SELECT 'unsummarized_view', v.table_name
  FROM information_schema.tables v
  WHERE v.table_schema = 'main' AND v.table_type = 'VIEW'
    AND v.table_name NOT LIKE '\_%' ESCAPE '\'
    AND NOT ends_with(v.table_name, '_summary')
    AND NOT ends_with(v.table_name, '_checks')
    AND NOT ends_with(v.table_name, '_context')
    AND NOT EXISTS (
      SELECT 1 FROM duckdb_views() s
      WHERE s.database_name = current_database() AND s.schema_name = 'main'
        AND ends_with(s.view_name, '_summary')
        AND NOT starts_with(s.view_name, '_')
        AND s.sql LIKE '%FROM ' || v.table_name || '%'
        AND (s.sql LIKE '%''' || v.table_name || '''%'
             OR (s.view_name = split_part(v.table_name, '_', 1) || '_summary'
                 AND s.sql LIKE '%''' || replace(regexp_replace(v.table_name, '^[a-z0-9]+_', ''), '_', '-') || '''%'))
    )
  UNION ALL
  -- ── every first-class entity is exposed or exempted on the record ──
  -- See the _entity_table / _entity_view block above for why this is structural rather
  -- than left to review. Three directions, because a one-directional list rots: an
  -- entity nobody listed, a listing for a table that no longer exists, and a listing
  -- naming a view that was never created or has since been renamed.
  SELECT 'unexposed_entity', t.table_name
  FROM _entity_table t
  WHERE t.table_name NOT IN (SELECT entity_table FROM _entity_view)

  UNION ALL
  SELECT 'stale_entity_view', e.entity_table
  FROM _entity_view e
  WHERE NOT EXISTS (SELECT 1 FROM duckdb_tables()
                    WHERE database_name = current_database() AND schema_name = 'raw' AND table_name = e.entity_table)

  UNION ALL
  SELECT 'missing_entity_view',
         e.entity_table || ' -> ' || coalesce(e.view_name, 'NULL')
  FROM _entity_view e
  WHERE e.view_name IS NULL
     OR NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'main' AND table_name = e.view_name)
  UNION ALL
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
  SELECT 'unexposed_alias_table', t.table_name
  FROM _alias_tables t
  WHERE NOT EXISTS (
    SELECT 1 FROM duckdb_views() v
    WHERE v.schema_name = 'main'
      AND v.view_name NOT LIKE '\_%' ESCAPE '\'
      AND v.sql LIKE '%' || t.table_name || '%'
  )
  UNION ALL
  -- A public view with no COMMENT ON VIEW. That comment IS the view reference —
  -- `analysis describe` reads it out of the session, so an undocumented view is a view
  -- nobody can find. It replaced a hand-maintained prose table in README.md, which had
  -- no check on it and was incomplete from the day it was written: models.description
  -- is selected by models and named in neither the comment block nor that table.
  -- Same both-directions logic as the other coverage lists: the docs are only trustworthy
  -- while every view is obliged to carry one.
  -- Reads duckdb_views() rather than information_schema.tables, which has no `comment`.
  -- foundation_summary / foundation_checks are THIS file's views, not the foundation's.
  SELECT 'undocumented_view', view_name
  FROM duckdb_views()
  WHERE database_name = current_database() AND schema_name = 'main'
    AND NOT starts_with(view_name, '_')
    AND view_name NOT IN ('foundation_summary', 'foundation_checks')
    AND comment IS NULL

  -- Macros are reference surface too — `analysis describe` lists them, and a view
  -- comment can send you to one (citation_root_domains names citation_root_for_host).
  -- `internal` excludes DuckDB's own built-ins.
  UNION ALL
  SELECT DISTINCT 'undocumented_macro', function_name
  FROM duckdb_functions()
  WHERE database_name = current_database() AND schema_name = 'main'
    AND NOT internal AND NOT starts_with(function_name, '_')
    AND comment IS NULL

  -- ─── The per-layer folds ───────────────────────────────────────────────────
  -- Each layer's checks view, private in its own *_checks.sql so the runner's sweep
  -- doesn't also discover it and report every failure twice. Same (check_name, detail)
  -- shape, so these read as more branches of this UNION.
  UNION ALL
  SELECT check_name, detail FROM _catalog_checks
  UNION ALL
  SELECT check_name, detail FROM _prose_checks
  UNION ALL
  SELECT check_name, detail FROM _provenance_checks
  UNION ALL
  SELECT check_name, detail FROM _data_patch_checks;
