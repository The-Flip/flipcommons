-- Roll-up card counts and catalog shape for ModelFilteringPlan.md.
--
-- The product rule lives in ModelFiltering.md § "Title > Model > Variant roll-up".
-- This file is its executable form: feed it (dimension, value, model) triples and
-- it returns the cards a `/games` listing would render under that rule, so the
-- plan's numbers are a rendering of a query rather than hand-counted prose.
--
-- The rule, restated only as far as the SQL needs it:
--   * a Title cards when EVERY live Model under it (Variants included) matches
--   * otherwise each matching Model cards, EXCEPT a Variant whose parent matches
-- Title-only dimensions (franchise, series) are absent here on purpose: they bind
-- their Models rather than partitioning them, so they never split a Title.

-- ═══════════════════════════════════════════════════════════════════════════
-- ANALYSIS
-- ═══════════════════════════════════════════════════════════════════════════

-- Ancestor closure over the two taxonomy DAGs. Filtering by a parent theme
-- matches child-tagged Models — the backend's _expand_taxonomy does this, and
-- omitting it silently undercounts every theme and feature (fantasy reads 276
-- direct against 371 expanded). Reflexive, so a leaf maps to itself.
-- Materialized, not views: the roll-up joins these several times over, and a
-- recursive CTE reached through that many layers of correlated view trips a
-- DuckDB planner assertion. Freezing them is also simply faster.
CREATE OR REPLACE TABLE _mf_theme_closure AS
  WITH RECURSIVE d(ancestor, descendant) AS (
    SELECT slug, slug FROM theme_vocab
    UNION
    SELECT d.ancestor, c.child FROM d
    JOIN (SELECT slug AS parent, unnest(children) AS child FROM theme_vocab) c
      ON c.parent = d.descendant)
  SELECT * FROM d;

CREATE OR REPLACE TABLE _mf_feature_closure AS
  WITH RECURSIVE d(ancestor, descendant) AS (
    SELECT slug, slug FROM gameplay_feature_vocab
    UNION
    SELECT d.ancestor, c.child FROM d
    JOIN (SELECT slug AS parent, unnest(children) AS child FROM gameplay_feature_vocab) c
      ON c.parent = d.descendant)
  SELECT * FROM d;

-- Live Models per Title, Variants INCLUDED — the denominator of the "every
-- Model matches" test. Deliberately not titles.n_models, which is the same count but
-- reads as a Title property; here it is the roll-up threshold.
CREATE OR REPLACE TABLE _mf_title_size AS
  SELECT title_id, count(*) AS n_models FROM models GROUP BY title_id;

-- One row per (dimension, value, Model): every model-only filter the listing
-- offers or would offer, in one long relation so the roll-up is written once.
-- Multi-valued dimensions (theme, feature, reward, person, edge) contribute
-- several rows per Model; single-valued ones contribute at most one.
--
-- NULLs are dropped, so an unclassified Model matches no value of that
-- dimension. That is what a bare `?game_format=pinball` means, and it means it
-- on every surface. The three sparse dimensions ALSO get a `_bucket` twin
-- below: the widened reading the listing's sidebar control selects, where
-- unclassified joins the value a reader would assume. Both are modelled
-- because ModelFilteringPlan.md publishes card counts for both and they differ
-- by an order of magnitude — game_format is 619 cards raw, 6,181 bucketed.
CREATE OR REPLACE TABLE mf_dimension_values AS
  SELECT 'manufacturer' AS dimension, manufacturer_slug AS value, id AS model_id
    FROM models WHERE manufacturer_slug IS NOT NULL
  UNION ALL SELECT 'tech_gen', technology_generation_slug, id
    FROM models WHERE technology_generation_slug IS NOT NULL
  UNION ALL SELECT 'display_type', display_type_slug, id
    FROM models WHERE display_type_slug IS NOT NULL
  UNION ALL SELECT 'system', system_slug, id
    FROM models WHERE system_slug IS NOT NULL
  UNION ALL SELECT 'year', year::VARCHAR, id
    FROM models WHERE year IS NOT NULL
  UNION ALL SELECT 'player_count', player_count::VARCHAR, id
    FROM models WHERE player_count IS NOT NULL
  UNION ALL SELECT 'game_format', game_format_slug, id
    FROM models WHERE game_format_slug IS NOT NULL
  UNION ALL SELECT 'production_status', production_status_slug, id
    FROM models WHERE production_status_slug IS NOT NULL
  UNION ALL SELECT 'cabinet', cabinet_slug, id
    FROM models WHERE cabinet_slug IS NOT NULL
  UNION ALL SELECT 'country', country_slug, id
    FROM models WHERE country_slug IS NOT NULL
  -- The widened reading of the sparse three: unclassified joins the assumed
  -- default. No WHERE clause, deliberately — that is what makes each of these
  -- a total function over the catalog, so the buckets partition it exactly.
  -- That partition is the property the decision rests on, and it is checked in
  -- model_filtering_checks rather than left as prose.
  UNION ALL SELECT 'game_format_bucket', coalesce(game_format_slug, 'pinball'), id
    FROM models
  UNION ALL SELECT 'production_status_bucket', coalesce(production_status_slug, 'produced'), id
    FROM models
  UNION ALL SELECT 'cabinet_bucket', coalesce(cabinet_slug, 'floor'), id
    FROM models
  -- Taxonomy dimensions carry every ancestor of what the Model is tagged with,
  -- so filtering by `fantasy` matches a Model tagged only `dragons`.
  UNION ALL SELECT 'theme', c.ancestor, mt.model_id
    FROM model_themes mt JOIN _mf_theme_closure c ON c.descendant = mt.theme_slug
  UNION ALL SELECT 'feature', c.ancestor, mf.model_id
    FROM model_gameplay_features mf JOIN _mf_feature_closure c ON c.descendant = mf.feature_slug
  UNION ALL SELECT 'person', person_slug, model_id FROM model_credits
  -- Relationship keys, outbound. Direction is a separate axis in the product
  -- vocabulary; the inbound half is mf_edge_keys below, which does not roll up
  -- because an inbound edge is a property of the target Model.
  UNION ALL SELECT 'edge', relationship_type, model_id FROM model_edges
  -- The one declared composite: no introspection yields "bootleg" for
  -- (copy, unlicensed). Kept here so the ledger can cite its card count.
  UNION ALL SELECT 'edge', 'bootleg', model_id
    FROM model_edges WHERE relationship_type = 'copy' AND license_status = 'unlicensed';

-- The matching Models of each (dimension, value), carrying what the roll-up
-- needs: which Title absorbs them, and whether a parent Model can.
CREATE OR REPLACE TABLE _mf_match AS
  SELECT DISTINCT dv.dimension, dv.value, m.id AS model_id,
         m.title_id, m.variant_of_id
  FROM mf_dimension_values dv JOIN models m ON m.id = dv.model_id;

-- Rung 1 — the Title cards. Every live Model under the Title matches.
CREATE OR REPLACE TABLE mf_title_cards AS
  SELECT mm.dimension, mm.value, mm.title_id
  FROM _mf_match mm JOIN _mf_title_size ts USING (title_id)
  GROUP BY mm.dimension, mm.value, mm.title_id, ts.n_models
  HAVING count(*) = ts.n_models;

-- Rungs 2 and 3 — the Model cards. A matching Model cards when its Title did
-- not, and a Variant additionally needs its parent not to have carded. Inside
-- this branch the Title is known not to be showing, so "parent is showing"
-- reduces to "parent matches".
CREATE OR REPLACE TABLE mf_model_cards AS
  SELECT mm.dimension, mm.value, mm.model_id, mm.title_id,
         mm.variant_of_id IS NOT NULL AS is_variant
  FROM _mf_match mm
  WHERE NOT EXISTS (
          SELECT 1 FROM mf_title_cards tc
          WHERE tc.dimension = mm.dimension AND tc.value = mm.value
            AND tc.title_id = mm.title_id)
    AND NOT EXISTS (
          SELECT 1 FROM _mf_match p
          WHERE p.model_id = mm.variant_of_id
            AND p.dimension = mm.dimension AND p.value = mm.value);

-- Every card the listing renders, one row each — the heterogeneous result set.
CREATE OR REPLACE VIEW mf_cards AS
  SELECT dimension, value, 'title' AS card_type, title_id AS entity_id, title_id
    FROM mf_title_cards
  UNION ALL
  SELECT dimension, value, 'model', model_id, title_id FROM mf_model_cards;

-- The headline table: what each filter value returns under the roll-up, beside
-- what it returns today.
--
-- `cards_today` reproduces today's semantics for the eleven any-Model
-- dimensions: one card per Title holding a matching ACTIVE NON-VARIANT Model
-- (the backend's _MODEL guard). Verified against the running dev API —
-- theme=fantasy 371, tech_gen=solid-state 1407. It does NOT reproduce
-- `manufacturer`, which is pinned to the representative Model today and so
-- returns fewer (williams 469 live against 475 here); reproducing that pin
-- would mean re-implementing an ordering rule this plan deletes.
CREATE OR REPLACE VIEW mf_card_counts AS
  WITH matched AS (
    SELECT dimension, value,
           count(DISTINCT model_id) AS matching_models,
           count(DISTINCT title_id) FILTER (WHERE variant_of_id IS NULL) AS cards_today
    FROM _mf_match GROUP BY dimension, value),
  carded AS (
    SELECT dimension, value,
           count(*) FILTER (WHERE card_type = 'title') AS title_cards,
           count(*) FILTER (WHERE card_type = 'model') AS model_cards,
           count(*)                                    AS cards
    FROM mf_cards GROUP BY dimension, value)
  SELECT m.dimension, m.value,
         coalesce(c.title_cards, 0) AS title_cards,
         coalesce(c.model_cards, 0) AS model_cards,
         coalesce(c.cards, 0)       AS cards,
         m.matching_models, m.cards_today
  FROM matched m LEFT JOIN carded c USING (dimension, value);

-- How far one Title can shatter under a single filter — the reason the row set
-- stops being the Title set, and with it Title-grain pagination and counts.
--
-- One reading per dimension: the `_bucket` twins are excluded because they are
-- an alternate reading of three dimensions already counted here, not three more
-- dimensions, and counting both would tally the same conceptual filter twice.
-- The raw reading is the one kept, and it is the conservative choice — a
-- bucketed dimension is a total function, so it shatters only where Models
-- genuinely disagree and can never shatter more than its raw twin.
CREATE OR REPLACE VIEW mf_shatter AS
  SELECT dimension, value, title_id, count(*) AS cards_from_this_title
  FROM mf_model_cards
  WHERE dimension NOT IN ('game_format_bucket','production_status_bucket','cabinet_bucket')
  GROUP BY dimension, value, title_id HAVING count(*) > 1;

-- Which dimensions can shatter a Title, and how often. A Title shatters on a
-- dimension when SOME value is carried by some of its Models but not all — the
-- exact negation of the roll-up test. Counting distinct values per Title would
-- be wrong for the multi-valued dimensions, where one Model carrying three
-- themes is agreement, not disagreement.
CREATE OR REPLACE VIEW mf_dimension_disagreement AS
  SELECT dimension, count(DISTINCT title_id) AS titles_shattered FROM (
    SELECT mm.dimension, mm.title_id
    FROM _mf_match mm JOIN _mf_title_size ts USING (title_id)
    GROUP BY mm.dimension, mm.value, mm.title_id, ts.n_models
    HAVING count(*) < ts.n_models)
  GROUP BY dimension;

-- Why `q` needs Model names: a Model whose name is not a substring of its
-- Title's cannot be reached by any query that works today.
CREATE OR REPLACE VIEW mf_unreachable_models AS
  SELECT id AS model_id, slug, name, title_slug, title_name,
         manufacturer_name, year, variant_of_id IS NOT NULL AS is_variant
  FROM models
  WHERE NOT contains(lower(title_name), lower(name));

-- The relationship key space, both directions. Inbound is not derivable from
-- mf_dimension_values: it is a property of the Model at the far end.
CREATE OR REPLACE VIEW mf_edge_keys AS
  SELECT relationship_type AS key,
         count(DISTINCT model_id) FILTER (WHERE direction = 'out') AS outbound,
         count(DISTINCT model_id) FILTER (WHERE direction = 'in')  AS inbound
  FROM model_edges_bidir GROUP BY relationship_type;

-- The type × licensing cross product the named composites carve cells out of.
CREATE OR REPLACE VIEW mf_edge_licensing AS
  SELECT relationship_type, coalesce(license_status, 'n/a') AS license_status,
         count(DISTINCT model_id) AS models
  FROM model_edges GROUP BY 1, 2;

-- The three dimensions whose null means "unclassified", never "the default" —
-- and `country`, which is the one whose gaps are honest and so has no assumed
-- default and no bucket columns.
--
-- `classified_as_default` beside `unclassified` is the whole argument in two
-- columns: 108 Models are recorded as pinball against 6,279 nobody classified,
-- so a badge reading the raw value misleads about a catalog that is
-- overwhelmingly pinball. `default_bucket + other_classified = live_models` is
-- the partition the design rests on.
CREATE OR REPLACE VIEW mf_sparse_dimensions AS
  SELECT 'game_format' AS dimension, 'pinball' AS assumed_default,
         count(*) FILTER (WHERE game_format_slug IS NULL) AS unclassified,
         count(*) FILTER (WHERE game_format_slug = 'pinball') AS classified_as_default,
         count(*) FILTER (WHERE game_format_slug IS NULL
                             OR game_format_slug = 'pinball') AS default_bucket,
         count(*) FILTER (WHERE game_format_slug IS NOT NULL
                            AND game_format_slug <> 'pinball') AS other_classified,
         count(*) AS live_models FROM models
  UNION ALL SELECT 'production_status', 'produced',
         count(*) FILTER (WHERE production_status_slug IS NULL),
         count(*) FILTER (WHERE production_status_slug = 'produced'),
         count(*) FILTER (WHERE production_status_slug IS NULL
                             OR production_status_slug = 'produced'),
         count(*) FILTER (WHERE production_status_slug IS NOT NULL
                            AND production_status_slug <> 'produced'),
         count(*) FROM models
  UNION ALL SELECT 'cabinet', 'floor',
         count(*) FILTER (WHERE cabinet_slug IS NULL),
         count(*) FILTER (WHERE cabinet_slug = 'floor'),
         count(*) FILTER (WHERE cabinet_slug IS NULL OR cabinet_slug = 'floor'),
         count(*) FILTER (WHERE cabinet_slug IS NOT NULL AND cabinet_slug <> 'floor'),
         count(*) FROM models
  UNION ALL SELECT 'country', NULL::VARCHAR,
         count(*) FILTER (WHERE country_slug IS NULL),
         NULL::BIGINT, NULL::BIGINT, NULL::BIGINT,
         count(*) FROM models;

-- ═══════════════════════════════════════════════════════════════════════════
-- SUMMARY & CHECKS
-- ═══════════════════════════════════════════════════════════════════════════

-- Every headline number ModelFilteringPlan.md publishes.
CREATE OR REPLACE VIEW model_filtering_summary AS
  SELECT 'titles' AS metric, count(*) AS value FROM titles
  UNION ALL SELECT 'live_models', count(*) FROM models
  UNION ALL SELECT 'variant_models', count(*) FROM models WHERE variant_of_id IS NOT NULL
  UNION ALL SELECT 'multi_model_titles',
    (SELECT count(*) FROM _mf_title_size WHERE n_models > 1)
  UNION ALL SELECT 'models_named_differently_than_their_title',
    (SELECT count(*) FROM models WHERE name <> title_name)
  UNION ALL SELECT 'models_unreachable_by_title_name',
    (SELECT count(*) FROM mf_unreachable_models)
  UNION ALL SELECT 'models_unreachable_by_title_name_excluding_variants',
    (SELECT count(*) FROM mf_unreachable_models WHERE NOT is_variant)
  UNION ALL SELECT 'titles_holding_an_unreachable_model',
    (SELECT count(DISTINCT title_slug) FROM mf_unreachable_models)
  UNION ALL SELECT 'model_abbreviations_consulted_by_nothing',
    (SELECT count(*) FROM model_abbreviations)
  UNION ALL SELECT 'models_with_an_inbound_edge_only', (SELECT count(*) FROM (
    SELECT model_id FROM model_edges_bidir GROUP BY model_id
    HAVING count(*) FILTER (WHERE direction = 'out') = 0))
  -- Worked anchors the plan quotes by name.
  UNION ALL SELECT 'cards_manufacturer_vifico',
    (SELECT cards FROM mf_card_counts WHERE dimension='manufacturer' AND value='vifico')
  UNION ALL SELECT 'cards_manufacturer_chicago_gaming',
    (SELECT cards FROM mf_card_counts WHERE dimension='manufacturer' AND value='chicago-gaming')
  UNION ALL SELECT 'cards_manufacturer_williams',
    (SELECT cards FROM mf_card_counts WHERE dimension='manufacturer' AND value='williams')
  UNION ALL SELECT 'cards_edge_remake_of',
    (SELECT cards FROM mf_card_counts WHERE dimension='edge' AND value='remake_of')
  UNION ALL SELECT 'cards_edge_bootleg',
    (SELECT cards FROM mf_card_counts WHERE dimension='edge' AND value='bootleg')
  -- game_format under both readings, and the two grains kept apart by name.
  -- `sum_over_values` is the whole dimension added up, which is what the plan's
  -- aggregate table publishes; `cards_click_*` is what one filter click
  -- actually returns. The two differ by a factor of sixty for this dimension,
  -- and conflating them is exactly how these figures were misread once already,
  -- so neither metric is allowed a name that could mean the other.
  UNION ALL SELECT 'game_format_raw_sum_over_values',
    (SELECT sum(cards) FROM mf_card_counts WHERE dimension='game_format')
  UNION ALL SELECT 'game_format_bucketed_sum_over_values',
    (SELECT sum(cards) FROM mf_card_counts WHERE dimension='game_format_bucket')
  UNION ALL SELECT 'game_format_bucketed_model_cards_sum_over_values',
    (SELECT sum(model_cards) FROM mf_card_counts WHERE dimension='game_format_bucket')
  UNION ALL SELECT 'cards_click_game_format_pinball_bare',
    (SELECT cards FROM mf_card_counts WHERE dimension='game_format' AND value='pinball')
  UNION ALL SELECT 'cards_click_game_format_pinball_widened',
    (SELECT cards FROM mf_card_counts
      WHERE dimension='game_format_bucket' AND value='pinball')
  -- The structural finding: a Title can yield several cards, so the row set is
  -- no longer the Title set.
  UNION ALL SELECT 'filter_values_that_shatter_a_title_into_several_cards',
    (SELECT count(*) FROM mf_shatter)
  UNION ALL SELECT 'most_cards_one_title_yields_under_one_filter',
    (SELECT coalesce(max(cards_from_this_title), 0) FROM mf_shatter);

CREATE OR REPLACE VIEW model_filtering_checks AS
  -- Structural: a Title and one of its own Models must never both card for the
  -- same filter value. That is the roll-up's core promise.
  SELECT 'title_and_its_model_both_carded' AS check_name,
         tc.dimension || '/' || tc.value || ' title=' || tc.title_id::VARCHAR AS detail
  FROM mf_title_cards tc JOIN mf_model_cards mc
    ON mc.dimension = tc.dimension AND mc.value = tc.value AND mc.title_id = tc.title_id
  UNION ALL
  -- Structural: a Variant and its parent must never both card.
  SELECT 'variant_and_parent_both_carded',
         v.dimension || '/' || v.value || ' model=' || v.model_id::VARCHAR
  FROM mf_model_cards v JOIN models m ON m.id = v.model_id
  JOIN mf_model_cards p ON p.model_id = m.variant_of_id
    AND p.dimension = v.dimension AND p.value = v.value
  UNION ALL
  -- Structural: every matching Model is accounted for — it cards itself, or it
  -- is absorbed by its Title or by its parent. Nothing may fall through.
  SELECT 'matching_model_neither_carded_nor_absorbed',
         mm.dimension || '/' || mm.value || ' model=' || mm.model_id::VARCHAR
  FROM _mf_match mm
  WHERE NOT EXISTS (SELECT 1 FROM mf_model_cards mc
                    WHERE mc.model_id = mm.model_id
                      AND mc.dimension = mm.dimension AND mc.value = mm.value)
    AND NOT EXISTS (SELECT 1 FROM mf_title_cards tc
                    WHERE tc.title_id = mm.title_id
                      AND tc.dimension = mm.dimension AND tc.value = mm.value)
    AND NOT EXISTS (SELECT 1 FROM _mf_match p
                    WHERE p.model_id = mm.variant_of_id
                      AND p.dimension = mm.dimension AND p.value = mm.value)
  UNION ALL
  -- Structural: a filter can never return more cards than it has matching
  -- Models. Roll-up only ever absorbs.
  SELECT 'more_cards_than_matching_models',
         dimension || '/' || value
  FROM mf_card_counts WHERE cards > matching_models
  UNION ALL
  -- Vocabulary: every dimension in play is one the listing knows about.
  SELECT 'unknown_dimension', dimension
  FROM (SELECT DISTINCT dimension FROM mf_dimension_values)
  WHERE dimension NOT IN (
    'manufacturer','tech_gen','display_type','system','year','player_count',
    'game_format','production_status','cabinet','country','theme','feature',
    'person','edge',
    'game_format_bucket','production_status_bucket','cabinet_bucket')
  UNION ALL
  -- Structural: the widened reading makes each sparse dimension a total
  -- function, so every live Model lands in exactly one bucket and the bucket
  -- rows number exactly the catalog. That partition is the argument for
  -- default-bucketing over raw selection or exclusion; if it ever fails, the
  -- decision in ModelFilteringPlan.md has lost its footing rather than merely
  -- its numbers.
  SELECT 'sparse_bucket_does_not_partition_the_catalog',
         dimension || ' bucket_rows=' || bucket_rows::VARCHAR
           || ' live_models=' || (SELECT count(*) FROM models)::VARCHAR
  FROM (SELECT dimension, count(*) AS bucket_rows
        FROM mf_dimension_values
        WHERE dimension IN ('game_format_bucket','production_status_bucket','cabinet_bucket')
        GROUP BY dimension)
  WHERE bucket_rows <> (SELECT count(*) FROM models)
  UNION ALL
  -- Reserved word: `unclassified` is the filter API's spelling of "the field
  -- is unset" (PR.SPARSE), translated to an IS NULL predicate before any slug
  -- comparison — so a real vocabulary row carrying that slug would be
  -- shadowed: unreachable by filter, its detail page pinned to true nulls.
  -- Nothing in the data model forbids the row (PR.SPARSE deliberately touched
  -- no models or migrations); this check is the guard.
  SELECT 'reserved_slug_unclassified_absent', vocabulary || '/' || slug
  FROM (          SELECT 'game_format' AS vocabulary, slug FROM fc.catalog_gameformat
        UNION ALL SELECT 'production_status', slug FROM fc.catalog_productionstatus
        UNION ALL SELECT 'cabinet', slug FROM fc.catalog_cabinet)
  WHERE slug = 'unclassified'
  UNION ALL
  -- Anchor: VIFICO represents no Title, so it must card as 13 Models and no
  -- Title. This is the bug the whole plan exists to fix; if it ever reads as a
  -- Title card the roll-up has regressed.
  SELECT 'anchor_vifico_is_all_model_cards',
         'title_cards=' || title_cards::VARCHAR || ' model_cards=' || model_cards::VARCHAR
  FROM mf_card_counts
  WHERE dimension = 'manufacturer' AND value = 'vifico'
    AND NOT (title_cards = 0 AND model_cards > 0)
  UNION ALL
  -- Anchor: Chicago Gaming's remakes share a Title with the Williams original,
  -- so that Title must never card — the remakes must surface individually.
  SELECT 'anchor_chicago_gaming_remakes_surface_as_models',
         'model_cards=' || model_cards::VARCHAR
  FROM mf_card_counts
  WHERE dimension = 'manufacturer' AND value = 'chicago-gaming' AND model_cards = 0
  UNION ALL
  -- Anchor: the roll-up must be visible somewhere. If no filter value anywhere
  -- absorbs a Model into a Title card, the rule has gone dark.
  SELECT 'anchor_rollup_absorbs_nothing', 'no title cards anywhere'
  FROM (SELECT count(*) AS n FROM mf_title_cards) WHERE n = 0;
