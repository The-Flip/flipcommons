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

.read scripts/analysis/sql/catalog.sql

-- ═══ §190 AUDIT — lint rules over the live catalog ═════════════════════════

-- ─── shared: the collapsed model ───────────────────────────────────────────
-- One row per model that its Title collapses into — the model a reader reaches by the
-- Title's URL, because the Title page renders its detail inline instead of a model list.
--
-- This is the product's rule, not an approximation of it: `titles.py` collapses when the
-- Title has exactly one active NON-VARIANT model and that model has no live variants.
-- `title_size` cannot express it. That column counts every live model in the Title,
-- variants included, so it answers a different question in both directions — a Title whose
-- sole model is a variant of a model in ANOTHER Title reads as size 1 while the product
-- shows a model list, and a Title holding one model plus its variants reads as size 3
-- while the product still refuses to collapse.
--
-- Two rules read this and must agree: one reports linking a collapsed model as an error,
-- the other resolves a mention of one to its Title. Disagreement would have the audit
-- prescribe the link it flags.
CREATE OR REPLACE VIEW _collapsed_models AS
  SELECT m.id, m.slug, m.name, m.title_id, m.title_slug
  FROM models m
  WHERE m.variant_of_id IS NULL
    -- Live variants only, which `models` already guarantees: a soft-deleted variant does
    -- not stop the product collapsing, so it must not stop this either.
    AND NOT EXISTS (SELECT 1 FROM models v WHERE v.variant_of_id = m.id)
    AND NOT EXISTS (SELECT 1 FROM models o
                    WHERE o.title_id = m.title_id AND o.variant_of_id IS NULL
                      AND o.id <> m.id);
COMMENT ON VIEW _collapsed_models IS
  'One row per model whose Title collapses into it — the product rule from titles.py (one active non-variant model, itself without live variants), not the title_size = 1 approximation.';

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
  LEFT JOIN _collapsed_models c ON c.id = m.id
  WHERE r.target_entity_type = 'model'
    -- A Title naming its own models is the one place the model grain is unambiguously
    -- deliberate. It is also the corner the advice cannot survive: for a collapsed model,
    -- "link the Title instead" would name the source itself.
    AND NOT (r.source_entity_type = 'title' AND m.title_id = r.source_id);
COMMENT ON VIEW audit_wrong_grain_link IS
  'ERROR when prose links a model its Title collapses into (link the Title instead); WARNING when the Title does not collapse, where both grains reach a real page and the choice may be deliberate.';

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
  WITH names AS (
              SELECT subject_type AS entity_type, subject_id AS entity_id,
                     subject_name AS name
              FROM entity_subjects
    UNION ALL SELECT entity_type, entity_id, alias FROM entity_aliases
  ),
  pool AS (
    -- Location is URL-addressable but absent from the wikilink picker, so
    -- `is_wikilinkable` is what keeps the rule from demanding an impossible edit.
    --
    -- What a span NAMES and what the reader should LINK are two different records for a
    -- collapsed model, which is its Title in the UI (SingleModelTitles.md). Suggesting the
    -- model there would name the exact link audit_wrong_grain_link reports as an error, so
    -- the suggestion is resolved to the Title through the predicate both rules read.
    SELECT s.subject_type AS target_type, s.subject_id AS target_id,
           CASE WHEN c.id IS NOT NULL THEN 'title'    ELSE s.subject_type END AS suggest_type,
           CASE WHEN c.id IS NOT NULL THEN c.title_id ELSE s.subject_id   END AS suggest_id,
           CASE WHEN c.id IS NOT NULL THEN 'title:' || c.title_slug
                ELSE s.subject_type || ':' || s.subject_public_id END AS suggest_link,
           name_norm(n.name) AS match_key
    FROM entity_subjects s
    JOIN entity_registry r ON r.entity_type = s.subject_type
    JOIN names n ON n.entity_type = s.subject_type AND n.entity_id = s.subject_id
    -- Only a collapsed model joins, so every CASE above falls through for an uncollapsed
    -- model and for each of the other twenty types alike.
    LEFT JOIN _collapsed_models c ON s.subject_type = 'model' AND c.id = s.subject_id
    -- entity_subjects and entity_aliases are not live-filtered, so liveness is applied here.
    WHERE is_live(s.subject_status) AND n.name IS NOT NULL AND r.is_wikilinkable
  ),
  -- Markup stripped first, so an already-linked name contributes no span at all.
  words AS (
    SELECT entity_type, entity_id, public_id, field,
           str_split(trim(regexp_replace(
             strip_accents(regexp_replace(text, '\[\[[^\]]*\]\]', ' ', 'g')),
             '[^\p{L}\p{N}]+', ' ', 'g')), ' ') AS w
    FROM entity_prose WHERE text IS NOT NULL
  ),
  -- The floor is the precision rule above; the ceiling bounds the span count, and a name
  -- longer than it is found by a shorter prefix or not at all.
  spans AS (
    SELECT entity_type, entity_id, public_id, field,
           UNNEST(flatten([[array_to_string(w[i : i + n - 1], ' ')
                            for i in range(1, len(w) + 1) if i + n - 1 <= len(w)]
                           for n in range(2, 6)])) AS span
    FROM words
  ),
  candidates AS (
    SELECT * FROM spans
    -- Every word starts with a capital or a digit. One lowercase word rejects the span.
    WHERE NOT list_contains(
      [regexp_matches(x, '^[\p{Lu}\p{N}]') for x in str_split(span, ' ')], false)
  ),
  -- One row per (span, record that span could name), carrying the two ways a span can
  -- already be accounted for. Computed per candidate, judged per span below.
  matched AS (
    SELECT c.entity_type, c.entity_id, c.public_id, c.field, c.span, p.suggest_link,
           -- Prose naming its own subject is not a missing link. Both grains are tested
           -- because they differ for a collapsed model, and a Title whose own prose names
           -- its sole model must not be told to link itself.
           (c.entity_type = p.target_type  AND c.entity_id = p.target_id)
             OR (c.entity_type = p.suggest_type AND c.entity_id = p.suggest_id) AS is_self,
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
  'WARNING — one row per (record, prose field, capitalized 2-5 word span) naming a linkable record the prose never links. Matches canonical names and aliases alike; a span naming several records renders as "N candidates". The link in the message is the one to WRITE, not the record the span named: a model alone in its Title resolves to the Title, so following the suggestion never authors a wrong-grain error. A name inside a quotation is legitimately unlinked, which is why this is not an error.';

-- ─── parenthetical-fact ────────────────────────────────────────────────────
-- The house pattern _[[model:x]]_ (1997, [[manufacturer:williams]]) restates two claims
-- the catalog already holds, so a disagreement means the prose or the record is wrong.
--
-- A macro rather than the CTE this looks like it wants: the named-group form of
-- regexp_extract requires a CONSTANT pattern, and a column reference is not one.
CREATE OR REPLACE MACRO paren_pattern() AS
  '\[\[(model|title):id:(\d+)\]\][^(\[]{0,8}\((\d{4})(?:,\s*\[\[manufacturer:id:(\d+)\]\])?\)';
COMMENT ON MACRO paren_pattern IS
  'The house parenthetical, _[[link]]_ (year, [[manufacturer]]), as a regex with four capture groups: link type, link id, year, manufacturer id.';

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

-- Every house parenthetical in the corpus, parsed once. Two rules read it, and a second
-- copy of this parse would drift from the first without either one failing.
--
-- Two passes because regexp_extract_all returns whole matches and no groups: find, then
-- read the groups off each match. Both take the pattern from the macro, since two copies
-- that drift would find a different set of parentheticals than they parse, silently.
--
-- NULLIF is load-bearing: the named-group form of regexp_extract returns '' for a group
-- that did not participate where the group-index form returns NULL. Normalizing once here
-- lets every consumer test IS NULL and mean it.
CREATE OR REPLACE VIEW _paren_links AS
  WITH hits AS (
    SELECT entity_type, entity_id, public_id, field,
           UNNEST(regexp_extract_all(text, paren_pattern())) AS hit
    FROM entity_prose WHERE text IS NOT NULL
  )
  SELECT entity_type, entity_id, public_id, field,
         g.link_type,
         -- TRY_CAST, not ::BIGINT: the id groups are `\d+` with no length bound, so one
         -- malformed link would otherwise throw and take the whole audit down.
         TRY_CAST(g.link_id AS BIGINT)                  AS link_id,
         g.stated_year::BIGINT                          AS stated_year,
         TRY_CAST(NULLIF(g.stated_maker, '') AS BIGINT) AS stated_maker
  FROM (
    SELECT entity_type, entity_id, public_id, field,
           regexp_extract(hit, paren_pattern(),
             ['link_type', 'link_id', 'stated_year', 'stated_maker']) AS g
    FROM hits);
COMMENT ON VIEW _paren_links IS
  'One row per house parenthetical _[[link]]_ (year, [[manufacturer]]) in any prose field — the link it names and the facts it states. Parsed once for every rule that reads the pattern.';

CREATE OR REPLACE VIEW audit_parenthetical_fact AS
  WITH parsed AS (FROM _paren_links),
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
              SELECT s.subject_type AS entity_type, s.subject_id AS entity_id,
                     s.subject_public_id AS public_id, s.subject_name AS text,
                     name_norm(s.subject_name) AS k, 'name' AS kind
              FROM entity_subjects s
              WHERE is_live(s.subject_status) AND s.subject_name IS NOT NULL
    UNION ALL SELECT a.entity_type, a.entity_id, s.subject_public_id, a.alias,
                     name_norm(a.alias), 'alias'
              FROM entity_aliases a
              JOIN entity_subjects s ON s.subject_type = a.entity_type
                                    AND s.subject_id = a.entity_id
              WHERE is_live(s.subject_status) AND a.alias IS NOT NULL
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
