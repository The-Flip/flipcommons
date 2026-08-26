-- Catalog audit — deterministic lint rules over the live catalog.
--
--     scripts/analysis/audit 0240   -- the report; `audit` alone for per-rule counts
--
--     scripts/analysis/analysis query "FROM audit_findings;"
--     scripts/analysis/analysis query "FROM audit_since(240);"
--
-- One view per rule, named `audit_<rule>`, each emitting the same five columns —
-- severity, entity_type, entity_id, public_id, message — and `audit_findings` unions
-- them. Adding a rule is that view plus a line in the union and in `audit_summary`.
--
-- Severity is per FINDING, not per rule, so a rule computes it per row.
--
-- Catalog defects go in `audit_findings`; the layer's own invariants go in
-- `audit_checks`. Only the second gates. `analysis run` and `--check` fail on a row from
-- any `*_checks` view, so a standing backlog of catalog defects put there would exit
-- nonzero forever and the gate would stop meaning anything.
--
-- Loads late (see analytics.sql): the rules read the whole foundation — catalog,
-- prose and patch layers alike.

-- ═══ §190 AUDIT — lint rules over the live catalog ═════════════════════════

-- ─── shared: vocabulary carriage ────────────────────────────────────────────
-- One row per (vocabulary record, model that carries it), across every channel by which a
-- model carries a vocabulary term: the M2M attachments (gameplay features, themes, tags,
-- reward types) and the single-valued dims (system, game format). For the two DAG
-- vocabularies an attachment to a DESCENDANT carries every ancestor — a machine attached
-- to bash-toys carries interactive-toys — because the DAG means the child IS a kind of
-- the parent, and a rule reading direct edges alone would demand a double attachment
-- the product never writes.
--
-- Two rules read this and must agree: uncarried-link reports a prose link to a machine
-- that carries nothing under the description's own record, and wrong-grain-link reads
-- carriage as evidence that a model-grain link is deliberate. Disagreement would have
-- one rule flag the exact link the other justifies.
--
-- The dim branches join `systems`/`game_formats` on slug, not id: `models` decodes those
-- FKs to slugs and does not surface the id, and both slugs are globally unique.
CREATE OR REPLACE VIEW _vocab_carriage AS
  WITH RECURSIVE
  -- UNION, not UNION ALL: a DAG reaches a node once per path, and this closure's
  -- contract is one row per (root, node).
  feature_desc AS (
    SELECT id AS root_id, id AS node_id FROM gameplay_features
    UNION
    SELECT d.root_id, c.id
    FROM feature_desc d
    JOIN gameplay_features p ON p.id = d.node_id
    JOIN gameplay_features c ON list_contains(p.children, c.slug)
  ),
  theme_desc AS (
    SELECT id AS root_id, id AS node_id FROM themes
    UNION
    SELECT d.root_id, c.id
    FROM theme_desc d
    JOIN themes p ON p.id = d.node_id
    JOIN themes c ON list_contains(p.children, c.slug)
  )
            SELECT _entity_type_of('catalog_gameplayfeature') AS entity_type,
                   d.root_id AS entity_id, a.model_id
            FROM feature_desc d
            JOIN model_gameplay_features a ON a.feature_id = d.node_id
  UNION     SELECT _entity_type_of('catalog_theme'), d.root_id, a.model_id
            FROM theme_desc d
            JOIN model_themes a ON a.theme_id = d.node_id
  UNION     SELECT _entity_type_of('catalog_tag'), tag_id, model_id FROM model_tags
  UNION     SELECT _entity_type_of('catalog_rewardtype'), reward_type_id, model_id
            FROM model_rewards
  UNION     SELECT _entity_type_of('catalog_system'), s.id, m.id
            FROM systems s JOIN models m ON m.system_slug = s.slug
  UNION     SELECT _entity_type_of('catalog_gameformat'), g.id, m.id
            FROM game_formats g JOIN models m ON m.game_format_slug = g.slug;

-- ─── self-link ─────────────────────────────────────────────────────────────
-- A `[[cite:N]]` edge has a NULL target_entity_type, and comparing anything to NULL
-- yields NULL rather than true, so cites drop out of the WHERE unmentioned.
CREATE OR REPLACE VIEW audit_self_link AS
  SELECT 'error'            AS severity,
         source_entity_type AS entity_type,
         source_id          AS entity_id,
         source_public_id   AS public_id,
         'prose links to itself' AS message
  FROM record_references
  WHERE source_entity_type = target_entity_type AND source_id = target_id;
COMMENT ON VIEW audit_self_link IS
  'ERROR — one row per live record whose prose wikilinks itself.';

-- ─── wrong-grain-link ──────────────────────────────────────────────────────
-- A collapsed model is the same thing as its Title in the UI (SingleModelTitles.md), so
-- linking the model is simply wrong. Where the Title does not collapse, both grains reach
-- a real page and the choice can be deliberate, hence a warning rather than an error.
--
-- One deliberateness signal is mechanical, so the warning does not fire on it: a
-- vocabulary record whose prose links a model CARRYING that record (the limited-edition
-- tag naming the LE builds it attaches to) has chosen the model grain on evidence the
-- catalog itself holds. Only the warning branch reads it — a collapsed model's Title is
-- its page, so that link stays an error no matter what the model carries.
CREATE OR REPLACE VIEW audit_wrong_grain_link AS
  SELECT CASE WHEN c.id IS NOT NULL THEN 'error' ELSE 'warning' END AS severity,
         r.source_entity_type AS entity_type,
         r.source_id          AS entity_id,
         r.source_public_id   AS public_id,
         -- By slug: models of one Title can share a name, so a name would render two
         -- distinct findings identically. It is also how a data patch addresses a record.
         CASE WHEN c.id IS NOT NULL
              THEN format('links [[model:{}]], the only model of its Title — link [[title:{}]] instead',
                          m.slug, m.title_slug)
              -- Several models is the ordinary reason a Title does not collapse and is
              -- worth naming. A Title holding ONE model that still does not collapse is a
              -- variant relationship, which a count cannot describe, so the count clause
              -- is omitted rather than printed as "one of 1 models".
              ELSE format('links [[model:{}]] ("{}"), which Title [[title:{}]] does not collapse into{} — confirm the model grain is deliberate',
                          m.slug, m.name, m.title_slug,
                          CASE WHEN m.title_size > 1
                               THEN format(' ({} models)', m.title_size) ELSE '' END)
         END AS message
  FROM record_references r
  JOIN models m ON m.id = r.target_id
  LEFT JOIN collapsed_models c ON c.id = m.id
  WHERE r.target_entity_type = 'model'
    -- A Title naming its own models is the one place the model grain is unambiguously
    -- deliberate. It is also the corner the advice cannot survive: for a collapsed model,
    -- "link the Title instead" would name the source itself.
    AND NOT (r.source_entity_type = 'title' AND m.title_id = r.source_id)
    AND NOT (c.id IS NULL AND EXISTS (
      SELECT 1 FROM _vocab_carriage v
      WHERE v.entity_type = r.source_entity_type AND v.entity_id = r.source_id
        AND v.model_id = m.id));
COMMENT ON VIEW audit_wrong_grain_link IS
  'ERROR when prose links a model its Title collapses into (link the Title instead); WARNING when the Title does not collapse, where both grains reach a real page and the choice may be deliberate. No warning when the source is a vocabulary record the linked model carries — that model grain is deliberate on the catalog''s own evidence.';

-- ─── linkless-description ──────────────────────────────────────────────────
-- GRAIN: record_references stores no field, so "has a link" is answered per RECORD while
-- this rule reports per FIELD. They are the same question only while an entity declares a
-- single MarkdownField; a second one would mask an unlinked field behind a linked sibling.
-- Closing that means the link graph carrying a field, not a change here.
CREATE OR REPLACE VIEW audit_linkless_description AS
  SELECT 'error'      AS severity,
         p.entity_type,
         p.entity_id,
         p.public_id,
         format('{} has no wikilinks', p.field) AS message
  FROM entity_prose p
  WHERE p.text IS NOT NULL
    AND p.entity_type NOT IN ('franchise', 'production-status')
    AND NOT EXISTS (
      SELECT 1 FROM record_references r
      WHERE r.source_entity_type = p.entity_type AND r.source_id = p.entity_id
        -- A [[cite:N]] is a reference but not a link to a catalog record, so prose
        -- carrying only citations is as linkless as prose carrying none.
        AND r.target_entity_type IS NOT NULL);
COMMENT ON VIEW audit_linkless_description IS
  'ERROR — one row per authored prose field with no wikilink to any catalog record. Franchise and production status are exempt.';

-- ─── unlinked-mention ──────────────────────────────────────────────────────
-- Precision is the hard part. The catalog is full of records named with ordinary English
-- — Pinball, It, Flipper, Target — so an unrestricted match drowns in them. Requiring a
-- capitalized multi-word span replaces a stopword list, which is also why spans keep their
-- case and match through name_norm rather than name_key: name_key would fold away the one
-- signal separating the game Pinball from the word pinball. The cost is sentence-initial
-- mentions, which a warning can afford.
--
-- A span naming several records is reported as "N candidates" rather than filtered out;
-- the collision itself is duplicate-name's business.
CREATE OR REPLACE VIEW audit_unlinked_mention AS
  WITH pool AS (
    -- Location is URL-addressable but absent from the wikilink picker, so
    -- `is_wikilinkable` is what keeps the rule from demanding an impossible edit.
    --
    -- What a span NAMES and what the reader should LINK are two different records for a
    -- collapsed model, which is its Title in the UI (SingleModelTitles.md). Suggesting the
    -- model there would name the exact link audit_wrong_grain_link reports as an error, so
    -- the suggestion is resolved to the Title through the predicate both rules read.
    SELECT n.entity_type AS target_type, n.entity_id AS target_id,
           CASE WHEN c.id IS NOT NULL THEN 'title'    ELSE n.entity_type END AS suggest_type,
           CASE WHEN c.id IS NOT NULL THEN c.title_id ELSE n.entity_id   END AS suggest_id,
           CASE WHEN c.id IS NOT NULL THEN 'title:' || c.title_slug
                ELSE n.entity_type || ':' || n.public_id END AS suggest_link,
           name_norm(n.name) AS match_key
    FROM entity_names n
    JOIN entity_registry r ON r.entity_type = n.entity_type
    -- Only a collapsed model joins, so every CASE above falls through for an uncollapsed
    -- model and for each of the other twenty types alike.
    LEFT JOIN collapsed_models c ON n.entity_type = 'model' AND c.id = n.entity_id
    WHERE r.is_wikilinkable
  ),
  -- One row per span OCCURRENCE in the shared tokenization (prose_words, which is what
  -- keeps quoted wordings from seeding spans) — lo/hi are word positions, kept so an
  -- occurrence can be judged by where it sits (inside an own-name occurrence, below).
  -- The report's unit stays the span TEXT: occurrences regroup in the final aggregate.
  -- The floor is the precision rule above; the ceiling bounds the span count, and a name
  -- longer than it is found by a shorter prefix or not at all.
  spans AS (
    SELECT entity_type, entity_id, public_id, field, s.span AS span, s.lo AS lo, s.hi AS hi
    FROM (
      SELECT entity_type, entity_id, public_id, field,
             UNNEST(flatten([[{'span': array_to_string(w[i : i + n - 1], ' '),
                               'lo': i, 'hi': i + n - 1}
                              for i in range(1, len(w) + 1) if i + n - 1 <= len(w)]
                             for n in range(2, 6)])) AS s
      FROM prose_words)
  ),
  -- Every normalized spelling of the record's own identity, at BOTH grains of a collapsed
  -- pair — a Title and the model it collapses into are one thing in the UI, so each owns
  -- the other's names. Each name contributes its paren-stripped form too: the trailing
  -- parenthetical is the catalog's disambiguator — Big Dryvers (EM), New World Series
  -- (ニューワールドシリーズ) — and prose never spells it, so without the stripped form
  -- the lead sentence fails to read as the record's own name and its sub-spans leak.
  -- Multi-word only: a one-word name cannot contain a two-word span.
  own_names AS (
    SELECT DISTINCT entity_type, entity_id, nn FROM (
      SELECT entity_type, entity_id, UNNEST([name_norm(name), name_key(name)]) AS nn
      FROM (
                  SELECT entity_type, entity_id, name FROM entity_names
        UNION ALL SELECT 'model', cm.id, n.name
                  FROM collapsed_models cm
                  JOIN entity_names n ON n.entity_type = 'title' AND n.entity_id = cm.title_id
        UNION ALL SELECT 'title', cm.title_id, n.name
                  FROM collapsed_models cm
                  JOIN entity_names n ON n.entity_type = 'model' AND n.entity_id = cm.id))
  ),
  -- Word ranges where the prose spells the record's own name — through the word array,
  -- not the span machinery, because a name longer than the span ceiling ("Teenage Mutant
  -- Ninja Turtles: Battle in the Sewer") still owns its sub-spans.
  own_ranges AS (
    SELECT entity_type, entity_id, field, r.lo AS lo, r.hi AS hi
    FROM (
      SELECT wd.entity_type, wd.entity_id, wd.field,
             UNNEST([{'lo': j, 'hi': j + o.k - 1}
                     for j in range(1, len(wd.w) - o.k + 2)
                     if name_norm(array_to_string(wd.w[j : j + o.k - 1], ' ')) = o.nn]) AS r
      FROM prose_words wd
      JOIN (SELECT entity_type, entity_id, nn, len(str_split(nn, ' ')) AS k
            FROM own_names WHERE nn LIKE '% %') o
        ON o.entity_type = wd.entity_type AND o.entity_id = wd.entity_id)
  ),
  candidates AS (
    SELECT * FROM spans sp
    -- Every word starts with a capital or a digit. One lowercase word rejects the span.
    WHERE NOT list_contains(
      [regexp_matches(x, '^[\p{Lu}\p{N}]') for x in str_split(span, ' ')], false)
    -- An occurrence inside the record's own name is the name, not a mention of whatever
    -- record a piece of it happens to match — "Stern SPIKE" inside "Stern SPIKE 3" names
    -- no SPIKE. Judged per occurrence, which is what the positions are for: the same
    -- words standing free elsewhere in the prose still seed a span, so New Crazy 15's
    -- description naming the original Crazy 15 is still found.
    AND NOT EXISTS (
      SELECT 1 FROM own_ranges o
      WHERE o.entity_type = sp.entity_type AND o.entity_id = sp.entity_id
        AND o.field = sp.field AND o.lo <= sp.lo AND sp.hi <= o.hi)
  ),
  -- One row per (span, record that span could name), carrying the two ways a span can
  -- already be accounted for. Computed per candidate, judged per span below.
  matched AS (
    SELECT c.entity_type, c.entity_id, c.public_id, c.field, c.span, p.suggest_link,
           -- Prose naming its own subject is not a missing link, and for a collapsed pair
           -- the subject wears two identities. The first two tests cover the span
           -- resolving to the record itself or to the Title suggested in its place; the
           -- third is the reverse grain, a model's prose naming the Title that collapses
           -- into it, which no pool row can equate because the pool row belongs to the
           -- Title.
           (c.entity_type = p.target_type  AND c.entity_id = p.target_id)
             OR (c.entity_type = p.suggest_type AND c.entity_id = p.suggest_id)
             OR EXISTS (SELECT 1 FROM collapsed_models cm
                        WHERE c.entity_type = 'model' AND cm.id = c.entity_id
                          AND p.target_type = 'title' AND p.target_id = cm.title_id) AS is_self,
           -- Linked anywhere in this record's prose, not only at this span: one link
           -- accounts for every mention of the same record. Either grain settles it —
           -- prose that linked the model did link the mention, and having linked it at the
           -- wrong grain is audit_wrong_grain_link's finding to report, not this rule's.
           EXISTS (
             SELECT 1 FROM record_references r
             WHERE r.source_entity_type = c.entity_type AND r.source_id = c.entity_id
               AND ((r.target_entity_type = p.target_type  AND r.target_id = p.target_id)
                 OR (r.target_entity_type = p.suggest_type AND r.target_id = p.suggest_id))
           ) AS linked
    FROM candidates c
    JOIN pool p ON p.match_key = name_norm(c.span)
  )
  SELECT 'warning' AS severity,
         entity_type,
         entity_id,
         public_id,
         -- One aggregate over the composed link, never two over its halves: independent
         -- aggregates can be satisfied from different rows and render a link that does not
         -- exist. The ranking ends in the link itself, so it holds still between runs,
         -- which a diffable report needs.
         format('{} names "{}" without linking it ({})', field, span,
                CASE WHEN count(DISTINCT suggest_link) = 1
                     THEN '[[' || min(suggest_link) || ']]'
                     ELSE format('{} candidates, e.g. [[{}]]',
                                 count(DISTINCT suggest_link),
                                 -- A model sorts last: every surviving one belongs to a
                                 -- Title holding several, so linking it draws a warning
                                 -- from audit_wrong_grain_link. An example that draws
                                 -- nothing is the one worth following.
                                 min_by(suggest_link,
                                        CASE WHEN suggest_link LIKE 'model:%'
                                             THEN '1' ELSE '0' END || suggest_link))
                END) AS message
  FROM matched
  GROUP BY entity_type, entity_id, public_id, field, span
  -- A span is accounted for if ANY record it names is the source itself or already
  -- linked, so the whole group goes. Judged here rather than filtered per candidate
  -- because records commonly share a name across types: filtering one candidate leaves
  -- its namesakes behind and warns about prose that is not wrong.
  HAVING NOT bool_or(is_self OR linked);
COMMENT ON VIEW audit_unlinked_mention IS
  'WARNING — one row per (record, prose field, capitalized 2-5 word span) naming a linkable record the prose never links. Matches canonical names and aliases alike; a span naming several records renders as "N candidates". The link in the message is the one to WRITE, not the record the span named: a model alone in its Title resolves to the Title, so following the suggestion never authors a wrong-grain error. Quoted wordings and spans inside the record''s own name do not fire; a warning rather than an error because prose may still legitimately shorthand a record it has no reason to link.';

-- ─── parenthetical-fact ────────────────────────────────────────────────────
-- The house pattern _[[model:x]]_ (1997, [[manufacturer:williams]]) restates two claims
-- the catalog already holds, so a disagreement means the prose or the record is wrong.
-- The parse is prose_parentheticals (prose.sql); this rule owns only the judgment
-- over it.

-- How well ONE model answers the stated facts: a point for the year, a point for the
-- maker, and no point for a maker the parenthetical never stated. Both scored on the same
-- model, so a Title is judged by its best-fitting model rather than by its models
-- collectively — the correlation `pair_wrong` exists to enforce.
--
-- A macro because the linked record and each namesake must be scored by identical rules.
-- Two scores computed two ways are not comparable, and comparing them is the whole test.
CREATE OR REPLACE MACRO paren_fit(year, maker, stated_year, stated_maker) AS
  (year IS NOT DISTINCT FROM stated_year)::INTEGER
  + (stated_maker IS NOT NULL AND maker IS NOT DISTINCT FROM stated_maker)::INTEGER;
COMMENT ON MACRO paren_fit IS
  'How many of a parenthetical''s stated facts one model carries — 0, 1 or 2. The shared scorer for "does a same-named record fit this parenthetical better than the linked one".';

CREATE OR REPLACE VIEW audit_parenthetical_fact AS
  WITH parsed AS (FROM prose_parentheticals),
  -- Both link kinds resolved to one shape: the name, and the years and makers the catalog
  -- allows. Empty lists rather than [NULL], so `len(...) = 0` reads as "the catalog says
  -- nothing here, so nothing is contradicted".
  -- `makers_at_stated_year` is the third list, and the one that keeps the year and the
  -- maker from being judged as if they were independent facts. See `correlated` below.
  facts AS (
    SELECT p.*, m.name AS target_name,
           CASE WHEN m.year IS NULL THEN []::BIGINT[] ELSE [m.year] END AS years,
           CASE WHEN m.manufacturer_id IS NULL THEN []::BIGINT[] ELSE [m.manufacturer_id] END AS makers,
           -- A model holds ONE (year, maker) pair, so this is its maker when the stated
           -- year is that model's and nothing otherwise — never a fact the dimension tests
           -- have not already reached.
           CASE WHEN m.year IS NOT DISTINCT FROM p.stated_year AND m.manufacturer_id IS NOT NULL
                THEN [m.manufacturer_id] ELSE []::BIGINT[] END AS makers_at_stated_year,
           -- The Title the link lands in, whichever grain it was written at, so the
           -- namesake search below can exclude the record already linked.
           m.title_id AS linked_title_id
    FROM parsed p JOIN models m ON m.id = p.link_id
    WHERE p.link_type = 'model'
    UNION ALL
    -- A Title has no year or maker of its own, so it takes its models' and a stated value
    -- is wrong only when it matches none of them.
    SELECT p.*, t.name,
           (SELECT COALESCE(list(m.year), []) FROM models m
             WHERE m.title_id = t.id AND m.year IS NOT NULL),
           (SELECT COALESCE(list(m.manufacturer_id), []) FROM models m
             WHERE m.title_id = t.id AND m.manufacturer_id IS NOT NULL),
           -- Correlated on the STATED year, so it answers "who made this Title's models
           -- that year" rather than "who made any of them".
           (SELECT COALESCE(list(m.manufacturer_id), []) FROM models m
             WHERE m.title_id = t.id AND m.year = p.stated_year
               AND m.manufacturer_id IS NOT NULL),
           t.id
    FROM parsed p JOIN titles t ON t.id = p.link_id
    WHERE p.link_type = 'title'
  ),
  judged AS (
    SELECT f.*,
           mk.name AS stated_maker_name,
           len(f.years) > 0 AND NOT list_contains(f.years, f.stated_year) AS year_wrong,
           f.stated_maker IS NOT NULL AND len(f.makers) > 0
             AND NOT list_contains(f.makers, f.stated_maker) AS maker_wrong,
           -- Named here so the SELECT below stays a rendering step.
           (SELECT string_agg(DISTINCT m.name, '/' ORDER BY m.name) FROM manufacturers m
             WHERE list_contains(f.makers, m.id)) AS catalog_makers,
           (SELECT string_agg(DISTINCT m.name, '/' ORDER BY m.name) FROM manufacturers m
             WHERE list_contains(f.makers_at_stated_year, m.id)) AS makers_that_year
    FROM facts f
    LEFT JOIN manufacturers mk ON mk.id = f.stated_maker
  ),
  -- A Title carries its models' years and makers as two lists, and testing them
  -- independently accepts a pair no single model holds: given a 1997 Williams model and a
  -- 2015 Chicago Gaming one, both halves of "(1997, Chicago Gaming)" are in the catalog
  -- and the parenthetical still describes nothing that exists. Only a Title reaches this
  -- — a model holds one pair, so its dimension tests already cover it.
  --
  -- Guarded on both dimension tests passing, so a parenthetical already reported for its
  -- year or its maker is not reported a second time for the combination.
  correlated AS (
    SELECT j.*,
           j.stated_maker IS NOT NULL AND NOT j.year_wrong AND NOT j.maker_wrong
             -- Empty means no model carries BOTH the stated year and any maker at all, so
             -- the catalog states nothing about the pair and nothing is contradicted.
             AND len(j.makers_at_stated_year) > 0
             AND NOT list_contains(j.makers_at_stated_year, j.stated_maker) AS pair_wrong
    FROM judged j
  ),
  -- Filtered before the namesake search below, which is the expensive part: it joins every
  -- Title by normalized name, and only a parenthetical already known to disagree is worth
  -- asking about.
  reported AS (
    SELECT * FROM correlated WHERE year_wrong OR maker_wrong OR pair_wrong
  ),
  -- WHICH record the parenthetical describes is itself in doubt whenever a same-named
  -- record fits the stated facts better than the linked one. "Star Trek (1979)" pointing at
  -- the 1991 Data East game is not a wrong year — the prose is right, the catalog is right,
  -- and the LINK is wrong. Told the year disagrees, an author corrects the one thing that
  -- was already true.
  --
  -- Strictly-more-facts, never a bare OR on year-or-maker: a namesake sharing the stated
  -- maker proves nothing when the linked record shares it too, so an off-by-one year on a
  -- game with a same-named sibling by the same maker would be blamed on the link.
  classified AS (
    SELECT r.*,
           (SELECT COALESCE(max(paren_fit(m.year, m.manufacturer_id,
                                          r.stated_year, r.stated_maker)), 0)
            FROM models m
            WHERE CASE WHEN r.link_type = 'model' THEN m.id = r.link_id
                                                  ELSE m.title_id = r.link_id END) AS linked_fit,
           -- Grouped by Title before the max, so a Title scores as its best single model
           -- and not as the union of what its models happen to carry.
           (SELECT COALESCE(max(x.fit), 0) FROM (
              SELECT max(paren_fit(m.year, m.manufacturer_id,
                                   r.stated_year, r.stated_maker)) AS fit
              FROM titles t JOIN models m ON m.title_id = t.id
              WHERE name_key(t.name) = name_key(r.target_name)
                AND t.id <> r.linked_title_id
              GROUP BY t.id) x) AS namesake_fit
    FROM reported r
  ),
  described AS (
    SELECT c.*,
           -- Re-derived rather than carried out of `classified`: the fit is an aggregate
           -- over models and this is a list of Titles, so one query cannot be both grains.
           (SELECT string_agg(DISTINCT '[[title:' || t.slug || ']]', ', '
                              ORDER BY '[[title:' || t.slug || ']]')
            FROM titles t
            WHERE name_key(t.name) = name_key(c.target_name)
              AND t.id <> c.linked_title_id
              AND (SELECT COALESCE(max(paren_fit(m.year, m.manufacturer_id,
                                                 c.stated_year, c.stated_maker)), 0)
                   FROM models m WHERE m.title_id = t.id) = c.namesake_fit) AS namesake_links,
           (SELECT count(*)
            FROM titles t
            WHERE name_key(t.name) = name_key(c.target_name)
              AND t.id <> c.linked_title_id
              AND (SELECT COALESCE(max(paren_fit(m.year, m.manufacturer_id,
                                                 c.stated_year, c.stated_maker)), 0)
                   FROM models m WHERE m.title_id = t.id) = c.namesake_fit) AS namesake_n
    FROM classified c
  )
  -- DISTINCT because the unit is the defect, not the occurrence: one description stating
  -- the same wrong parenthetical twice is one thing to fix. Two different ones differ in
  -- `message` and both survive.
  SELECT DISTINCT
         'error' AS severity,
         entity_type,
         entity_id,
         public_id,
         -- Every piece is non-NULL by construction: format() propagates NULL, so one NULL
         -- argument blanks the whole message and the finding reads as broken rather than
         -- as a defect. An unresolvable maker falls back to its raw id.
         CASE WHEN namesake_fit > linked_fit
              THEN format('{} says {} ({}) but links a same-named record the catalog dates {} — {} {} the stated facts',
                          field, target_name, stated,
                          COALESCE(NULLIF(array_to_string(list_sort(list_distinct(years)), '/'), ''),
                                   'no year'),
                          COALESCE(namesake_links, 'another record of that name'),
                          CASE WHEN namesake_n = 1 THEN 'fits' ELSE 'fit' END)
              ELSE format('{} says {} ({}) but the catalog says {}', field, target_name, stated,
                concat_ws(' and ',
                  CASE WHEN year_wrong
                       -- Sorted, so the same defect renders identically between runs.
                       THEN 'year ' || array_to_string(list_sort(list_distinct(years)), '/') END,
                  CASE WHEN maker_wrong
                       THEN 'maker ' || COALESCE(catalog_makers, 'unknown') END,
                  -- Both halves are in the catalog, so naming either alone would read as a
                  -- denial of something true. What is wrong is the pairing.
                  CASE WHEN pair_wrong
                       THEN stated_year || ' was ' || COALESCE(makers_that_year, 'unknown') END))
         END AS message
  FROM (SELECT *, stated_year || COALESCE(', ' || COALESCE(stated_maker_name,
                                                           'manufacturer ' || stated_maker), '')
                  AS stated
        FROM described);
COMMENT ON VIEW audit_parenthetical_fact IS
  'ERROR — one row per _[[link]]_ (year, [[manufacturer]]) parenthetical whose year or maker disagrees with the catalog, or which pairs a year and a maker the catalog holds but never together (a Title with a 1997 Williams model and a 2015 Chicago Gaming one states neither "1997, Chicago Gaming" nor "2015, Williams"). Either the prose is wrong or the record is; both want fixing.';

-- ─── broken-link ───────────────────────────────────────────────────────────
-- Two halves because a target can be dead in two ways. Soft-deleted carries status
-- 'deleted'. Hard-deleted carries no status at all — a GenericForeignKey has no
-- on_delete, so the edge outlives its target, entity_subjects resolves nothing and
-- is_live() reads that NULL as live — so it is caught by its unresolvable public id.
--
-- The NULL target_entity_type test excludes cite edges, and also keeps the second half
-- from firing on one.
CREATE OR REPLACE VIEW audit_broken_link AS
  SELECT 'error'            AS severity,
         source_entity_type AS entity_type,
         source_id          AS entity_id,
         source_public_id   AS public_id,
         -- Concatenated from non-NULL pieces rather than format()ed: a dead record is
         -- the kind most likely to be missing a name, and one NULL blanks the message.
         'links [[' || target_entity_type || ':'
           || COALESCE(target_public_id, target_id::VARCHAR) || ']]'
           || COALESCE(' ("' || target_name || '")', '')
           || ', which has been deleted' AS message
  FROM record_references
  WHERE target_entity_type IS NOT NULL
    AND (NOT is_live(target_status) OR target_public_id IS NULL);
COMMENT ON VIEW audit_broken_link IS
  'ERROR — one row per wikilink whose target is deleted or missing. Either the link should go, or the record should not have gone.';

-- ─── uncarried-link ────────────────────────────────────────────────────────
-- The catalog holds two independent assertions about the same fact: the prose ("The
-- first Mystic Lines game was [[title:border-beauty]]") and the attachment data (model
-- border-beauty ⋈ feature mystic-lines). This rule cross-checks them: a machine
-- wikilinked from a vocabulary record's prose should carry that record, per
-- _vocab_carriage — so either the attachment is missing or the prose names the wrong
-- machine. A warning either way, because prose may legitimately name a non-carrier
-- ("the last Gottlieb before they switched to this feature").
--
-- For the two single-valued dims the message names what the machine DOES carry, because
-- that value is the triage: a sibling generation (williams-system-11a under a
-- williams-system-11 description) is usually deliberate prose, a foreign one (a
-- Zaccaria system under a Williams one) is usually a same-named wrong machine linked.
-- The M2M kinds get no such clause — a model's full feature list explains nothing.
--
-- Dead targets are skipped: broken-link already reports those, and this rule could say
-- nothing about them that isn't the deletion itself.
CREATE OR REPLACE VIEW audit_uncarried_link AS
  -- DISTINCT because the unit is the (record, linked machine) pair, however many times
  -- the prose links it.
  WITH links AS (
    SELECT DISTINCT r.source_entity_type, r.source_id, r.source_public_id,
           r.target_entity_type, r.target_id, r.target_public_id, r.target_name
    FROM record_references r
    WHERE r.source_entity_type IN (SELECT entity_type FROM _vocab_carriage)
      AND r.target_entity_type IN ('model', 'title')
      AND is_live(r.target_status) AND r.target_public_id IS NOT NULL
  ),
  -- The models a link puts in scope: the model itself, or every live model of the Title.
  -- LEFT so a Title holding no live models keeps its row and reports as uncarried.
  judged AS (
    SELECT l.*,
           COALESCE(bool_or(EXISTS (
             SELECT 1 FROM _vocab_carriage v
             WHERE v.entity_type = l.source_entity_type AND v.entity_id = l.source_id
               AND v.model_id = m.id)), false) AS carried,
           -- The dim values actually carried, for the message. Both computed on every
           -- row and picked by source type at render — a CASE choosing between
           -- aggregates does not bind. Aggregated because a Title link scopes several
           -- models; sorted so the same defect renders identically between runs.
           string_agg(DISTINCT m.system_slug, '/' ORDER BY m.system_slug)           AS systems_carried,
           string_agg(DISTINCT m.game_format_slug, '/' ORDER BY m.game_format_slug) AS formats_carried
    FROM links l
    LEFT JOIN models m
      ON (l.target_entity_type = 'model' AND m.id = l.target_id)
      OR (l.target_entity_type = 'title' AND m.title_id = l.target_id)
    GROUP BY ALL
  )
  SELECT 'warning'          AS severity,
         source_entity_type AS entity_type,
         source_id          AS entity_id,
         source_public_id   AS public_id,
         format('links [[{}:{}]] ("{}"), {}',
                target_entity_type, target_public_id,
                -- A live record can still be missing a name; format() propagates NULL and
                -- would blank the message.
                COALESCE(target_name, target_public_id),
                CASE WHEN source_entity_type IN ('system', 'game-format') THEN
                       CASE WHEN carried_dims IS NULL
                            THEN format('which carries no {}', replace(source_entity_type, '-', ' '))
                            ELSE format('which carries {} {}', replace(source_entity_type, '-', ' '), carried_dims)
                       END
                     WHEN target_entity_type = 'title'
                     THEN format('no model of which is attached to this {}', replace(source_entity_type, '-', ' '))
                     ELSE format('which is not attached to this {}', replace(source_entity_type, '-', ' '))
                END) AS message
  FROM (SELECT *, CASE source_entity_type WHEN 'system'      THEN systems_carried
                                          WHEN 'game-format' THEN formats_carried END AS carried_dims
        FROM judged)
  WHERE NOT carried;
COMMENT ON VIEW audit_uncarried_link IS
  'WARNING — one row per wikilink from a vocabulary record''s prose (gameplay feature, theme, tag, reward type, system, game format) to a machine that does not carry that record, DAG descendants counted. Either the attachment is missing or the prose names the wrong machine; for system and game format the message names what the machine does carry, which is the triage. Prose may legitimately name a non-carrier, hence a warning.';

-- ─── duplicate-name ────────────────────────────────────────────────────────
-- Names and aliases are one pool: the collision that matters is between the strings a
-- reader or an importer would use, not between the columns they live in.
--
-- Three types are exempt, each for a reason in the data model. Model and Title names
-- legitimately repeat across makers and eras — `namesake_count` exists on `models`
-- because that is normal, and including them would bury every other rule. A location slug
-- is unique only within its parent, which is why `location_path` exists.
--
-- Both sides of a collision are reported, since either may be the one to merge away.
CREATE OR REPLACE VIEW audit_duplicate_name AS
  WITH keys AS (
    SELECT entity_type, entity_id, public_id, name AS text, name_norm(name) AS k, kind
    FROM entity_names
  ),
  shared AS (
    SELECT entity_type, k FROM keys
    WHERE entity_type NOT IN ('model', 'title', 'location')
    GROUP BY ALL HAVING count(DISTINCT entity_id) > 1
  )
  SELECT 'warning' AS severity,
         k.entity_type,
         k.entity_id,
         k.public_id,
         -- Ordered, like every aggregate that reaches a message: identity is
         -- (rule, record, message), so an unordered list renders the same defect
         -- differently between runs.
         format('{} "{}" also identifies {}', k.kind, k.text,
                (SELECT string_agg(DISTINCT o.entity_type || '.' || o.public_id, ', '
                                   ORDER BY o.entity_type || '.' || o.public_id)
                 FROM keys o
                 WHERE o.entity_type = k.entity_type AND o.k = k.k
                   AND o.entity_id <> k.entity_id)) AS message
  FROM keys k
  JOIN shared s ON s.entity_type = k.entity_type AND s.k = k.k;
COMMENT ON VIEW audit_duplicate_name IS
  'WARNING — one row per live record whose name or alias also identifies another record of the same type, usually a record created twice. Model, Title and Location are exempt: repeated names are normal for all three.';

-- ─── ambiguous-alias ───────────────────────────────────────────────────────
-- One alias string that names two records of the same type. Everything resolving source
-- wording through the alias tables inherits the ambiguity, and nothing downstream can
-- settle it from the alias alone.
--
-- Compared on lower(), which is the PRODUCT's alias key: every AliasModel declares
-- UNIQUE(Lower(value)), so on all but one type this asserts a constraint the database
-- already holds. The exception is LocationAlias, whose constraint is scoped per location
-- — which makes Location, whose place names repeat by nature, the one type where the
-- collision is writable at all.
--
-- The boundary with duplicate-name is exact, so the two cannot report the same row:
-- duplicate-name pools names and aliases under name_norm and exempts Location, while
-- this rule reads aliases alone under the stricter key, where a collision is impossible
-- for every type duplicate-name covers.
--
-- Both sides are reported, as in duplicate-name: either alias may be the one to drop.
-- Every instance today is a province beside the city inside it (Milano naming both
-- italy/mi and italy/mi/milan), which is the shape to expect and still a real ambiguity:
-- a resolver handed "Milano" cannot tell which grain the source meant.
CREATE OR REPLACE VIEW audit_ambiguous_alias AS
  WITH al AS (
    SELECT entity_type, entity_id, public_id, name, lower(name) AS k
    FROM entity_names WHERE kind = 'alias'
  ),
  shared AS (
    SELECT entity_type, k FROM al GROUP BY ALL HAVING count(DISTINCT entity_id) > 1
  )
  SELECT 'error' AS severity,
         a.entity_type,
         a.entity_id,
         a.public_id,
         -- Ordered for the reason duplicate-name orders its list: a finding's identity
         -- includes its message.
         format('alias "{}" also names {}', a.name,
                (SELECT string_agg(DISTINCT o.entity_type || '.' || o.public_id, ', '
                                   ORDER BY o.entity_type || '.' || o.public_id)
                 FROM al o
                 WHERE o.entity_type = a.entity_type AND o.k = a.k
                   AND o.entity_id <> a.entity_id)) AS message
  FROM al a
  JOIN shared s ON s.entity_type = a.entity_type AND s.k = a.k;
COMMENT ON VIEW audit_ambiguous_alias IS
  'ERROR — one row per alias of a live record that also names another live record of the same type, leaving every resolver a choice it cannot make. Location is where this happens; elsewhere the alias table''s own unique constraint forbids it.';

-- ─── redundant-alias ───────────────────────────────────────────────────────
-- An alias that only re-cases its own record's name. Alias lookup is case-insensitive by
-- construction — UNIQUE(Lower(value)) on every alias table — so the row cannot match
-- anything the name does not already match.
--
-- lower(), not name_norm: name_norm also collapses punctuation and folds accents, and
-- both distinguish alias forms the product genuinely stores. "Kick-targets" beside "Kick
-- targets", "Malaga" beside the canonical "Málaga" — in each pair the alias is the whole
-- reason the row exists, and it is a source spelling this one would stop matching. Case
-- alone is dead weight.
CREATE OR REPLACE VIEW audit_redundant_alias AS
  SELECT 'warning' AS severity,
         a.entity_type,
         a.entity_id,
         a.public_id,
         format('alias "{}" only re-cases the record''s own name "{}"', a.name, n.name) AS message
  FROM entity_names a
  JOIN entity_names n
    ON n.entity_type = a.entity_type AND n.entity_id = a.entity_id AND n.kind = 'name'
  WHERE a.kind = 'alias' AND lower(a.name) = lower(n.name);
COMMENT ON VIEW audit_redundant_alias IS
  'WARNING — one row per alias that differs from its own record''s name only in case, which a case-insensitive lookup can never need. Punctuation and accent variants are real match keys and are not reported.';

-- ─── variant-chain ─────────────────────────────────────────────────────────
-- A variant points at the base model, never at another variant. A variant is the same
-- gameplay in different dress (DomainModel.md), so a chain asserts a dress of a dress —
-- and the Title collapse rule reads the shape directly: collapsed_models wants one
-- active non-variant model, itself without live variants, so a chain moves a Title's page.
--
-- Nothing in the schema forbids it: self_fk_not_self('variant_of') stops a model being
-- its OWN variant, and a two-hop chain satisfies that constraint and every other one on
-- the column.
--
-- Reported on the CHILD, the end that can be repointed; the middle model's own edge is
-- correct. variant_of only: remake_of chains across eras legitimately, and
-- export_edition_of is 1:1 with a domestic original.
CREATE OR REPLACE VIEW audit_variant_chain AS
  SELECT 'error' AS severity,
         _entity_type_of('catalog_machinemodel') AS entity_type,
         child.model_id   AS entity_id,
         child.model_slug AS public_id,
         format('variant of {}, which is itself a variant of {} — point it at the base model',
                child.target_slug, parent.target_slug) AS message
  FROM model_lineage child
  JOIN model_lineage parent ON parent.model_id = child.target_id
  WHERE child.edge_kind = 'variant_of' AND parent.edge_kind = 'variant_of';
COMMENT ON VIEW audit_variant_chain IS
  'ERROR — one row per model whose variant_of target is itself a variant. A variant names the base model, so the chain has to be flattened; the finding sits on the end that moves.';

-- ─── cross-manufacturer-variant ────────────────────────────────────────────
-- A variant_of edge whose two ends were built by different manufacturers. A variant is
-- the same gameplay in different dress — cabinet art, plaques, toppers, colored plastics
-- (DomainModel.md) — and a second factory does not produce different dress, it produces a
-- copy, a remake or an export edition. Of the seven relationship types this is the ONLY
-- one that cannot cross: the other six describe one company taking up another's design,
-- which is the normal case for four of them.
--
-- Nothing in the schema forbids it. self_fk_not_self('variant_of') stops a model being its
-- OWN variant and the column carries no other constraint, so a cross-manufacturer variant
-- is writable today and would land silently.
--
-- It matters because variants collapse. `first_model_candidates` filters
-- `variant_of__isnull=True`, so a mislabelled foreign build vanishes from its Title's model
-- list instead of standing beside the original — the Title stops showing that a second
-- company ever built the game, and the copy's own manufacturer, year and provenance stop
-- being reachable from the page.
--
-- Both manufacturers must be known: NULL is no signal, not a difference. See
-- unlinked-foreign-model for why that costs nothing here.
CREATE OR REPLACE VIEW audit_cross_manufacturer_variant AS
  SELECT 'error' AS severity,
         _entity_type_of('catalog_machinemodel') AS entity_type,
         m.id   AS entity_id,
         m.slug AS public_id,
         format('variant of {}, which {} built — a variant is the same game in different dress, so another manufacturer''s build is a copy, remake or export edition',
                l.target_slug, l.target_manufacturer_name) AS message
  FROM model_lineage l
  JOIN models m ON m.id = l.model_id
  WHERE l.edge_kind = 'variant_of'
    AND m.manufacturer_slug IS NOT NULL
    AND l.target_manufacturer_slug IS NOT NULL
    AND m.manufacturer_slug IS DISTINCT FROM l.target_manufacturer_slug;
COMMENT ON VIEW audit_cross_manufacturer_variant IS
  'ERROR — one row per model whose variant_of target was built by a different manufacturer. Variants cannot cross that boundary; the edge wants retyping as copy, remake or export edition. Reported on the variant, the end that moves.';

-- ─── unlinked-foreign-model ────────────────────────────────────────────────
-- A Title can span manufacturers — Eight Ball Deluxe holds the Bally original, a Taito do
-- Brasil copy and a Bell Games conversion kit — and when it does, every model outside the
-- originating company got there by taking up someone else's design. That act is what the
-- six non-variant relationship types name, and Eight Ball Deluxe states one on each
-- foreign build, so it is silent here. A foreign model stating none of them asserts that
-- two companies arrived at one game independently, which is not a thing that happens.
--
-- The Title is the scope because it is what makes the omission legible: a lone foreign
-- model with no edge is just an under-described record, while one sharing a Title with
-- another company's build has a specific missing fact and usually a specific target.
--
-- WHICH end is the original comes from the earliest year in the Title, and ties keep every
-- manufacturer that shares that year, so an undated or same-year pair is not accused. The
-- heuristic is deliberate rather than merely cheap: where it picks wrong it does so because
-- the years are wrong or absent, so the finding is a real defect either way — just not
-- always the one the rule is named for. Darling and Jubilee both surfaced that way,
-- Williams originals ranked behind their Segasa copies.
--
-- Which is why the message states the EVIDENCE and not the conclusion. "Segasa originated
-- the Title" is simply false on Darling, and a finding that asserts it is wrong even
-- though it is pointing at something real. Naming the earliest year instead gives the
-- reader the number to check and names both repairs, since the rule cannot tell which one
-- it is looking at.
--
-- OUTBOUND edges only. An edge is stated on the end that took up the design, so pointing
-- at the original is exactly what a derivative owes; a model with only an INBOUND edge has
-- had its relationship described by someone else and still says nothing itself. Accepting
-- inbound would also silence on unrelated evidence — Jubilee's one edge is a conversion in
-- another Title entirely, which says nothing about who built the game.
--
-- The edge need not point inside the Title or across a manufacturer: a conversion names a
-- donor from a different game, and copies chain (a second Taito build copying the first).
-- Any of the six is enough to say the record knows where it came from.
--
-- A variant inherits its base's edges, since a variant states dress and the base states
-- origin. One hop is the whole walk — deeper chains are variant-chain's finding, and
-- cross-manufacturer-variant guarantees the base is same-manufacturer.
--
-- Manufacturer must be known at both ends, which today costs nothing: of the 377 live
-- models with no manufacturer, 376 are the only model in their own Title and so can never
-- be in a cross-manufacturer one. The exception is Metallica (Retheme), which shares
-- Earthshaker's Title and already states its retheme edge.
CREATE OR REPLACE VIEW audit_unlinked_foreign_model AS
  WITH cross_title AS (
    SELECT title_id FROM models GROUP BY title_id
    HAVING count(DISTINCT manufacturer_slug) > 1
  ),
  -- The manufacturers sharing the Title's earliest year. A Title reaches here only if some
  -- model in it is dated, so this is never empty for a Title the rule considers.
  originator AS (
    SELECT m.title_id, list(DISTINCT m.manufacturer_slug) AS mfrs,
           string_agg(DISTINCT m.manufacturer_name, ' / ') AS names,
           -- Every row here shares the Title's earliest year, so min() just reads it back.
           min(m.year) AS year
    FROM models m
    JOIN cross_title c ON c.title_id = m.title_id
    WHERE m.year IS NOT NULL
      AND m.manufacturer_slug IS NOT NULL
      AND m.year = (SELECT min(m2.year) FROM models m2 WHERE m2.title_id = m.title_id)
    GROUP BY m.title_id
  ),
  origin_stated AS (
    SELECT DISTINCT model_id FROM model_edges
    WHERE relationship_type IN ('remake_of', 'export_edition_of', 'copy',
                                'conversion', 'conversion_kit', 'retheme')
  )
  SELECT 'warning' AS severity,
         _entity_type_of('catalog_machinemodel') AS entity_type,
         m.id   AS entity_id,
         m.slug AS public_id,
         format('{} built this, but the Title''s earliest model is {} ({}) — either say how this derives (copy, remake, conversion, conversion kit, re-theme or export edition), or correct the dates if this is the original',
                m.manufacturer_name, o.names, o.year) AS message
  FROM models m
  JOIN originator o ON o.title_id = m.title_id
  WHERE m.manufacturer_slug IS NOT NULL
    AND NOT list_contains(o.mfrs, m.manufacturer_slug)
    -- A variant answers through its base; every other model answers for itself.
    AND COALESCE(m.variant_of_id, m.id) NOT IN (SELECT model_id FROM origin_stated);
COMMENT ON VIEW audit_unlinked_foreign_model IS
  'WARNING — one row per model in a cross-manufacturer Title, built by neither of the Title''s originating manufacturers, that states no relationship explaining how it derives. The originator comes from the Title''s earliest year, so a wrong one is usually a date defect.';

-- ─── vocabulary-cycle ──────────────────────────────────────────────────────
-- A theme or gameplay feature whose parent chain returns to itself. Nothing forbids one:
-- ThemeParent and GameplayFeatureParent carry a unique pair and nothing else, so a
-- self-parent and a longer loop are both writable today.
--
-- An error rather than a curiosity because this layer walks those DAGs to answer
-- questions about them. _vocab_carriage rolls an attachment up to every ancestor, so a
-- loop makes every member an ancestor of every other and each one silently inherits all
-- their machines — and uncarried-link and wrong-grain-link both read it.
--
-- UNION, not UNION ALL, for the reason _vocab_carriage gives and one more: the closure is
-- one row per (record, ancestor) either way, but on the cyclic data this rule exists to
-- find, UNION ALL enumerates paths that never terminate. Deduplicating against the
-- accumulated result reaches a fixpoint instead — and a walk that hangs on a cycle
-- reports no cycles at all.
--
-- The cost is the step count, which a set closure cannot carry. A direct self-edge is the
-- half of that triage worth keeping: one row to delete, versus a chain to trace.
CREATE OR REPLACE VIEW audit_vocabulary_cycle AS
  WITH RECURSIVE parent_edge AS (
              SELECT _entity_type_of('catalog_theme') AS entity_type, id, slug,
                     unnest(parents) AS parent_slug
              FROM themes
    UNION ALL SELECT _entity_type_of('catalog_gameplayfeature'), id, slug, unnest(parents)
              FROM gameplay_features
  ),
  ancestor AS (
    SELECT entity_type, id, slug AS root, parent_slug AS ancestor_slug
    FROM parent_edge
    UNION
    SELECT a.entity_type, a.id, a.root, e.parent_slug
    FROM ancestor a
    JOIN parent_edge e ON e.entity_type = a.entity_type AND e.slug = a.ancestor_slug
  )
  SELECT 'error' AS severity,
         a.entity_type,
         a.id   AS entity_id,
         a.root AS public_id,
         CASE WHEN EXISTS (SELECT 1 FROM parent_edge e
                           WHERE e.entity_type = a.entity_type
                             AND e.slug = a.root AND e.parent_slug = a.root)
              THEN 'is its own parent — the vocabulary DAG must stay acyclic'
              ELSE 'is its own ancestor — the vocabulary DAG must stay acyclic'
         END AS message
  FROM ancestor a
  WHERE a.ancestor_slug = a.root;
COMMENT ON VIEW audit_vocabulary_cycle IS
  'ERROR — one row per live theme or gameplay feature that is its own ancestor. Every member of a loop is reported, since any edge in it may be the one to cut.';

-- ─── orphan-title ──────────────────────────────────────────────────────────
-- A Title with no live models. It survives its last model's deletion by design — `titles`
-- carries n_models = 0 to say so — leaving a page with nothing on it and a name still
-- competing in every match against the catalog. Either a deletion stopped halfway or the
-- models were never written.
CREATE OR REPLACE VIEW audit_orphan_title AS
  SELECT 'warning' AS severity,
         _entity_type_of('catalog_title') AS entity_type,
         id   AS entity_id,
         slug AS public_id,
         'no live models — a Title exists to group them' AS message
  FROM titles
  WHERE n_models = 0;
COMMENT ON VIEW audit_orphan_title IS
  'WARNING — one row per live Title with no live model under it, which renders as an empty page.';

-- ─── bare-shared-cdn-host ──────────────────────────────────────────────────
-- A shared multi-tenant CDN host carries only path-scoped registration rows — on such a
-- host the path names the tenant, so a bare row would attribute every tenant's files to
-- one work. The backend's clean() refuses to write one and the recognition macros refuse
-- to match one (citation_domain_eligible), so a row here slipped in through a validation
-- bypass and sits inert until it is path-scoped or deleted.
--
-- The subject is the citation SOURCE that owns the registration — not a catalog entity,
-- so this finding never joins entity_subjects and never appears in a patch-scoped report;
-- the unscoped audit is what surfaces it.
CREATE OR REPLACE VIEW audit_shared_cdn_bare_host AS
  SELECT 'error'                   AS severity,
         'citation-source'         AS entity_type,
         d.root_citation_source_id AS entity_id,
         -- The root's stable key, not its slug: a slug is optional on a citation source
         -- (Facebook's is NULL) while root_identifier_key is the key this layer already
         -- tells consumers to filter on.
         d.root_identifier_key     AS public_id,
         format('registers shared CDN host {} with no tenant path prefix — path-scope or delete the row', d.host) AS message
  FROM citation_root_domains d
  WHERE d.path_prefix = '' AND _shared_cdn_host(d.host);
COMMENT ON VIEW audit_shared_cdn_bare_host IS
  'ERROR — one row per bare registration of a shared multi-tenant CDN host, on which only a path-scoped row attributes honestly. The row is inert (recognition refuses to match it) until path-scoped or deleted.';

-- ─── findings ──────────────────────────────────────────────────────────────
-- Columns listed rather than `*`: every column but entity_id is VARCHAR, so a rule that
-- reordered its own SELECT could swap message into severity without a type error.
--
-- A TABLE, not a view: this file runs at snapshot build time, so the union of every
-- rule is evaluated once per build instead of once per query — and it cannot go stale,
-- because the catalog data it reads only changes on the rebuild that re-runs it. The
-- rule views stay views; they are the per-rule lens and the freshness question never
-- arises for them separately.
CREATE OR REPLACE TABLE audit_findings AS
            SELECT 'self-link'             AS rule, severity, entity_type, entity_id, public_id, message FROM audit_self_link
  UNION ALL SELECT 'wrong-grain-link',          severity, entity_type, entity_id, public_id, message FROM audit_wrong_grain_link
  UNION ALL SELECT 'linkless-description',      severity, entity_type, entity_id, public_id, message FROM audit_linkless_description
  UNION ALL SELECT 'unlinked-mention',          severity, entity_type, entity_id, public_id, message FROM audit_unlinked_mention
  UNION ALL SELECT 'parenthetical-fact',        severity, entity_type, entity_id, public_id, message FROM audit_parenthetical_fact
  UNION ALL SELECT 'duplicate-name',            severity, entity_type, entity_id, public_id, message FROM audit_duplicate_name
  UNION ALL SELECT 'broken-link',               severity, entity_type, entity_id, public_id, message FROM audit_broken_link
  UNION ALL SELECT 'uncarried-link',            severity, entity_type, entity_id, public_id, message FROM audit_uncarried_link
  UNION ALL SELECT 'ambiguous-alias',           severity, entity_type, entity_id, public_id, message FROM audit_ambiguous_alias
  UNION ALL SELECT 'redundant-alias',           severity, entity_type, entity_id, public_id, message FROM audit_redundant_alias
  UNION ALL SELECT 'variant-chain',             severity, entity_type, entity_id, public_id, message FROM audit_variant_chain
  UNION ALL SELECT 'cross-manufacturer-variant', severity, entity_type, entity_id, public_id, message FROM audit_cross_manufacturer_variant
  UNION ALL SELECT 'unlinked-foreign-model',    severity, entity_type, entity_id, public_id, message FROM audit_unlinked_foreign_model
  UNION ALL SELECT 'vocabulary-cycle',          severity, entity_type, entity_id, public_id, message FROM audit_vocabulary_cycle
  UNION ALL SELECT 'orphan-title',              severity, entity_type, entity_id, public_id, message FROM audit_orphan_title
  UNION ALL SELECT 'shared-cdn-bare-host',      severity, entity_type, entity_id, public_id, message FROM audit_shared_cdn_bare_host;
COMMENT ON TABLE audit_findings IS
  'One row per catalog defect across every rule — rule, severity, the record it is about and a human-readable message. Catalog content, not a health gate. Materialized at build; the per-rule audit_* views are the live spelling.';

-- ─── scoping ───────────────────────────────────────────────────────────────
--   FROM audit_since(240);
--
-- A macro rather than a view because the scoped result must be two things a view cannot
-- be at once: filterable by patch number, and one row per DEFECT. Taking the bound as an
-- argument lets the grain collapse after the filter; left at (finding, patch) grain a
-- record several patches touched prints the same defect once per patch.
--
-- The patch is a FILTER, not an attribution. The rules read current catalog state and
-- know nothing about patches, so a row means a patch in range touched this record, never
-- that it caused the finding — the defect is usually older than the patch. The converse
-- gap: a patch can create findings on records it never wrote to, by renaming something
-- that prose elsewhere names, and no scoped query will show those.
CREATE OR REPLACE MACRO audit_since(n) AS TABLE
  SELECT f.*,
         -- Zero-padded: it is how a patch is named, and it makes the lexical sort numeric.
         string_agg(DISTINCT lpad(e.patch_number::VARCHAR, 4, '0'), ', '
                    ORDER BY lpad(e.patch_number::VARCHAR, 4, '0')) AS patches
  FROM audit_findings f
  JOIN patch_entries e
    ON e.subject_type = f.entity_type AND e.subject_id = f.entity_id
  WHERE e.patch_number >= n
  -- patch_entries is one row per ChangeSet and a grouped `changesets:` block writes
  -- several to one record, so the aggregate keeps that off the finding count.
  GROUP BY ALL;
COMMENT ON MACRO TABLE audit_since IS
  'audit_since(240) — one row per DEFECT on a record that patch 240 or later wrote to, with those patch numbers aggregated into `patches`. The patch-scoped lens; scope is a filter, never a claim that the patch caused the finding.';

-- ─── checks ────────────────────────────────────────────────────────────────
-- Invariants of the LAYER, not of the catalog: a row here means the audit is broken. Each
-- branch guards something only execution reveals. The CTE is what keeps three reads of
-- `f` from being three full evaluations of every rule.
CREATE OR REPLACE VIEW audit_checks AS
  WITH f AS (FROM audit_findings)
  -- format() propagates NULL, so one NULL argument blanks the whole message and the
  -- finding prints as an empty line — broken-looking rather than wrong-looking. It needs
  -- its own branch because NULL slips every other test: `NULL NOT IN (…)` is unknown
  -- rather than true. public_id is absent because the report falls back to the id.
  SELECT 'finding_null_required' AS check_name,
         rule || ' -> ' || col AS detail
  FROM f,
       LATERAL (VALUES ('severity', f.severity), ('entity_type', f.entity_type),
                       ('entity_id', f.entity_id::VARCHAR), ('message', f.message))
              AS v(col, val)
  WHERE v.val IS NULL

  UNION ALL
  -- Severity is computed per finding, and a CASE that loses its ELSE returns something
  -- nothing downstream knows how to rank or colour.
  SELECT 'unknown_severity', rule || ' -> ' || severity
  FROM f WHERE severity NOT IN ('error', 'warning')

  UNION ALL
  -- A finding's subject vocabulary is closed: catalog entity types, plus the one
  -- non-entity subject a rule reports on (a citation source, for shared-cdn-bare-host).
  -- Without this, a typo'd entity_type would skip the liveness test below unnoticed —
  -- membership in the registry is what routes a finding into it.
  SELECT 'unknown_entity_type', rule || ' -> ' || entity_type
  FROM f
  WHERE entity_type <> 'citation-source'
    AND entity_type NOT IN (SELECT entity_type FROM entity_registry)

  UNION ALL
  -- Not redundant with the foundation: rules reading entity_subjects and entity_aliases
  -- apply liveness themselves, since those views are not live-filtered. This guards a
  -- filter the rules own rather than inherit. Registry types only: entity_subjects
  -- cannot resolve a citation-source subject, whose rule inherits liveness from
  -- citation_sources instead.
  SELECT 'finding_subject_not_live',
         rule || ' -> ' || entity_type || ':' || entity_id::VARCHAR
  FROM f
  WHERE entity_type IN (SELECT entity_type FROM entity_registry)
    AND NOT EXISTS (
      SELECT 1 FROM entity_subjects s
      WHERE s.subject_type = f.entity_type AND s.subject_id = f.entity_id
        AND is_live(s.subject_status));
COMMENT ON VIEW audit_checks IS
  'The audit layer''s own invariants — a row means the AUDIT is broken, never that the catalog is. Empty is healthy. Catalog defects live in audit_findings and are deliberately not gated.';

-- Counted per rule VIEW rather than grouped from audit_findings, so a rule finding nothing
-- keeps its row. These detectors fail by returning nothing, which is what a clean catalog
-- also looks like, so a rule at zero is the state most worth seeing.
CREATE OR REPLACE VIEW audit_summary AS
            SELECT 'self-link'            AS metric, count(*) AS value FROM audit_self_link
  UNION ALL SELECT 'wrong-grain-link',         count(*) FROM audit_wrong_grain_link
  UNION ALL SELECT 'linkless-description',     count(*) FROM audit_linkless_description
  UNION ALL SELECT 'unlinked-mention',         count(*) FROM audit_unlinked_mention
  UNION ALL SELECT 'parenthetical-fact',       count(*) FROM audit_parenthetical_fact
  UNION ALL SELECT 'duplicate-name',           count(*) FROM audit_duplicate_name
  UNION ALL SELECT 'broken-link',              count(*) FROM audit_broken_link
  UNION ALL SELECT 'uncarried-link',           count(*) FROM audit_uncarried_link
  UNION ALL SELECT 'ambiguous-alias',          count(*) FROM audit_ambiguous_alias
  UNION ALL SELECT 'redundant-alias',          count(*) FROM audit_redundant_alias
  UNION ALL SELECT 'variant-chain',            count(*) FROM audit_variant_chain
  UNION ALL SELECT 'cross-manufacturer-variant', count(*) FROM audit_cross_manufacturer_variant
  UNION ALL SELECT 'unlinked-foreign-model',    count(*) FROM audit_unlinked_foreign_model
  UNION ALL SELECT 'vocabulary-cycle',         count(*) FROM audit_vocabulary_cycle
  UNION ALL SELECT 'orphan-title',             count(*) FROM audit_orphan_title
  UNION ALL SELECT 'shared-cdn-bare-host',     count(*) FROM audit_shared_cdn_bare_host
  UNION ALL SELECT 'TOTAL errors', count(*) FILTER (severity = 'error') FROM audit_findings
  UNION ALL SELECT 'TOTAL warnings', count(*) FILTER (severity = 'warning') FROM audit_findings
  UNION ALL SELECT 'records affected',
                   count(DISTINCT entity_type || ':' || entity_id) FROM audit_findings;
COMMENT ON VIEW audit_summary IS
  'One row per rule with its finding count, plus totals — the headline readout. Every rule keeps a row at zero, which is the state worth noticing.';

-- ─── the report ────────────────────────────────────────────────────────────
-- One row per line, for `--format lines`. Rendered in SQL so the wording lives beside the
-- data it counts and cannot drift from it, and so every caller prints the same thing.
--
-- Header, findings, footer. The header is two lines because scope and result read alike as
-- bare counts: every number on the first line is what was examined, every number on the
-- second is what was found, so neither can be mistaken for the other.
--
-- The result line appears twice on purpose: output read by a tool is truncated at the tail,
-- so a total BEFORE the findings separates "I saw 40 of 240" from "there were 40", and a
-- header with no footer under it means the output was cut. Only that line repeats — a
-- second copy of the scope line would prove nothing about whether findings were lost.
CREATE OR REPLACE MACRO plural(n, one, many) AS
  n::VARCHAR || ' ' || CASE WHEN n = 1 THEN one ELSE many END;
COMMENT ON MACRO plural IS
  'plural(1, ''patch'', ''patches'') -> ''1 patch''; plural(0, …) -> ''0 patches''. Both forms given — appending ''s'' is not English.';

CREATE OR REPLACE MACRO audit_report(since) AS TABLE (
  WITH f AS (FROM audit_since(since)),
  -- From the patch LEDGER, not from the findings: a patch that applied cleanly and one
  -- that never applied both contribute nothing to `f`, and a stale database would
  -- otherwise read as a clean one.
  --
  -- The record count is the denominator the result line is read against, so it carries the
  -- liveness filter the rules apply to their own subjects. Without it a soft-deleted record
  -- would enlarge the set audited while being structurally unable to contribute a finding.
  --
  -- The span comes from the data rather than from `since`, which names a patch that need
  -- not exist. Both ends, so a clean run still names what it examined.
  scope AS (
    SELECT n_patches, n_records,
           -- Falls back to the bound only when nothing matched, which is the run that has
           -- no span to name. Outside the aggregate: `since` is a parameter, and an
           -- aggregating SELECT will not read it beside min() and max().
           lpad(COALESCE(lo_n, since)::VARCHAR, 4, '0') AS lo,
           lpad(COALESCE(hi_n, since)::VARCHAR, 4, '0') AS hi
    FROM (
      SELECT count(DISTINCT patch_number)                     AS n_patches,
             count(DISTINCT subject_type || ':' || subject_id)
               FILTER (is_live(subject_status))               AS n_records,
             min(patch_number)                                AS lo_n,
             max(patch_number)                                AS hi_n
      FROM patch_entries WHERE patch_number >= since
    )
  ),
  tally AS (
    SELECT plural(count(*) FILTER (severity = 'error'), 'error', 'errors') AS errs,
           plural(count(*) FILTER (severity = 'warning'), 'warning', 'warnings') AS warns,
           plural(count(DISTINCT entity_type || ':' || entity_id), 'record', 'records') AS recs
    FROM f
  ),
  summary AS (
    SELECT s.n_patches,
           CASE WHEN s.n_patches = 0
                THEN 'NOTHING WAS AUDITED — no patch >= ' || s.lo
                     || ' is in this database; run make ingest-patches'
                ELSE 'Audited ' || plural(s.n_records, 'record', 'records')
                     || ' touched by ' || plural(s.n_patches, 'patch', 'patches')
                     || ', ' || s.lo || '-' || s.hi || '.'
           END AS scope_line,
           t.errs || ' and ' || t.warns || ' in ' || t.recs AS result_line
    FROM tally t, scope s
  ),
  rendered AS (
    SELECT CASE severity WHEN 'error' THEN 0 ELSE 1 END AS rank,
           CASE severity WHEN 'error' THEN '❌' ELSE '⚠️' END
           || ' ' || severity
           || ' ・ ' || entity_type || '.' || COALESCE(public_id, entity_id::VARCHAR)
           || ' (' || patches || ')'
           || ' ・ ' || rule || ': ' || message AS line
    FROM f
  )
  SELECT line FROM (
    SELECT 0 AS section, NULL::INTEGER AS k1, '' AS k2, scope_line AS line FROM summary
    -- Header and footer carry the same sentence; the endings tell them apart, so neither
    -- needs a label.
    UNION ALL SELECT 1, NULL, '', result_line || ', errors first:'
      FROM summary WHERE n_patches > 0
    UNION ALL SELECT 2, NULL, '', '' FROM summary WHERE n_patches > 0
    -- Rank leads rather than the line, which would sort on the emoji: ⚠ is U+26A0 and
    -- ❌ is U+274C, so warnings would come first.
    UNION ALL SELECT 3, rank, line, line FROM rendered
    UNION ALL SELECT 4, NULL, '', '' FROM summary WHERE n_patches > 0
    UNION ALL SELECT 5, NULL, '', result_line || '.' FROM summary WHERE n_patches > 0
  ) ORDER BY section, k1, k2
);
COMMENT ON MACRO TABLE audit_report IS
  'audit_report(240) — the rendered lint report for patches >= 240, one row per line: header, findings (errors first), footer. Read with --format lines; scripts/analysis/audit is the entry point.';
