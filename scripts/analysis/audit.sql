-- Catalog audit — deterministic lint rules over the live catalog.
--
--     scripts/analysis/audit 0240   -- the report; `audit` alone for per-rule counts
--
--     scripts/analysis/analysis query scripts/analysis/audit.sql "FROM audit_findings;"
--     scripts/analysis/analysis query scripts/analysis/audit.sql "FROM audit_since(240);"
--
-- An ordinary analysis file: it reads the foundation and adds nothing to it.
--
-- One view per rule, named `audit_<rule>`, each emitting the same five columns —
-- severity, entity_type, entity_id, public_id, message — and `audit_findings` unions
-- them. To add a rule: write the view, add one line to the union. That is the whole
-- mechanism.
--
-- Severity is per FINDING, not per rule: wrong-grain-link is an error when the linked
-- model is alone in its Title and a warning otherwise, so it is a CASE in the rule.
--
-- Findings are catalog defects, NOT a health gate. There is deliberately no
-- `audit_checks` view: `analysis run` fails on any `*_checks` rows, so a catalog with
-- one unlinked mention would exit nonzero forever and the gate would stop meaning
-- anything. `analysis run` therefore REJECTS this file — it requires a summary/checks
-- pair — and that is the intended answer, not an omission. Use `query`.
.read scripts/analysis/catalog.sql

-- ─── self-link ─────────────────────────────────────────────────────────────
-- A record whose prose wikilinks itself. The reader is already on the record.
--
-- target_entity_type is NULL on a `[[cite:N]]` edge, and comparing anything to NULL
-- yields NULL rather than true, so those drop out of the WHERE unmentioned.
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
-- Prose linking [[model:X]] when the reader almost certainly wants the Title. When X is
-- the only model of its Title the two are the same thing in the UI (SingleModelTitles.md)
-- and the model link is simply wrong — an error. When the Title holds several, linking one
-- of them can be deliberate, so it is a warning asking the author to confirm the grain.
CREATE OR REPLACE VIEW audit_wrong_grain_link AS
  SELECT CASE WHEN m.title_size = 1 THEN 'error' ELSE 'warning' END AS severity,
         r.source_entity_type AS entity_type,
         r.source_id          AS entity_id,
         r.source_public_id   AS public_id,
         -- Named by SLUG, not by name. Two models of one Title can share a name (two
         -- "Party Animal" rows, six "Card King"), so a message keyed on the name renders
         -- two distinct findings identically and one of them looks like a duplicate.
         -- The slug is also the form a data patch addresses a record by.
         CASE WHEN m.title_size = 1
              THEN format('links [[model:{}]], the only model of its Title — link [[title:{}]] instead',
                          m.slug, m.title_slug)
              ELSE format('links [[model:{}]] ("{}"), one of {} models in Title [[title:{}]] — confirm the model grain is deliberate',
                          m.slug, m.name, m.title_size, m.title_slug)
         END AS message
  FROM record_references r
  JOIN models m ON m.id = r.target_id
  WHERE r.target_entity_type = 'model'
    -- A Title naming its own models is the one source for which the model grain is
    -- unambiguously deliberate — that is what a Title description is for — so it is
    -- exempt rather than asked to confirm. It also removes a corner the advice could not
    -- survive: for a single-model Title linking its own model, "link the Title instead"
    -- names the source itself.
    AND NOT (r.source_entity_type = 'title' AND m.title_id = r.source_id);
COMMENT ON VIEW audit_wrong_grain_link IS
  'ERROR when prose links a model alone in its Title (link the Title instead); WARNING when the Title holds several and the grain may be deliberate.';

-- ─── linkless-description ──────────────────────────────────────────────────
-- Authored prose with no wikilink to any catalog record.
--
-- Franchise and production status are exempt by policy — they are allowed to stand alone.
--
-- GRAIN CAVEAT: record_references stores no field, so "has a link" is answered per RECORD
-- while this rule reports per FIELD. Every entity declares exactly one MarkdownField today,
-- which makes them the same question; a second one would mask an unlinked field behind a
-- linked sibling. Fixing that means the link graph carrying a field, not a change here.
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
        -- A [[cite:N]] is a reference but not a link to a catalog record, and prose
        -- carrying only citations is exactly as linkless as prose carrying none.
        AND r.target_entity_type IS NOT NULL);
COMMENT ON VIEW audit_linkless_description IS
  'ERROR — one row per authored prose field with no wikilink to any catalog record. Franchise and production status are exempt.';

-- ─── unlinked-mention ──────────────────────────────────────────────────────
-- Prose that names a catalog record without linking it.
--
-- The hard part is precision, not recall. Matching every span against every record name
-- returns ~15k hits, because the catalog is full of records named with ordinary English:
-- Pinball, It, Flipper, Contact, Target, Bingo. Requiring a span to be capitalized and at
-- least two words cuts that ~50x with no stopword list — which is why spans are normalized
-- WITHOUT lowercasing and matched through name_norm rather than name_key: name_key folds
-- away the only signal separating the game Pinball from the word pinball. The cost is
-- sentence-initial mentions, which a warning can afford.
--
-- Canonical names AND aliases, as one pool — prose writes "Cars" as readily as
-- "Automobiles". A string naming two records of one type is not filtered out here: it
-- renders as "N candidates" in the message, and audit_duplicate_name reports the
-- collision itself, which is usually the real defect behind it.
CREATE OR REPLACE VIEW audit_unlinked_mention AS
  WITH names AS (
              SELECT subject_type AS entity_type, subject_id AS entity_id,
                     subject_name AS name
              FROM entity_subjects
    UNION ALL SELECT entity_type, entity_id, alias FROM entity_aliases
  ),
  pool AS (
    -- What prose could be asked to link. Location is URL-addressable but absent from the
    -- wikilink picker, so `is_wikilinkable` keeps us from demanding an impossible edit.
    SELECT s.subject_type AS target_type, s.subject_id AS target_id,
           s.subject_type || ':' || s.subject_public_id AS target_link,
           name_norm(n.name) AS match_key
    FROM entity_subjects s
    JOIN entity_registry r ON r.entity_type = s.subject_type
    JOIN names n ON n.entity_type = s.subject_type AND n.entity_id = s.subject_id
    -- entity_subjects keeps retired subjects so a claim about one still resolves.
    WHERE is_live(s.subject_status) AND n.name IS NOT NULL AND r.is_wikilinkable
  ),
  -- Wikilink markup stripped first, so an already-linked name contributes no span at all.
  words AS (
    SELECT entity_type, entity_id, public_id, field,
           str_split(trim(regexp_replace(
             strip_accents(regexp_replace(text, '\[\[[^\]]*\]\]', ' ', 'g')),
             '[^\p{L}\p{N}]+', ' ', 'g')), ' ') AS w
    FROM entity_prose WHERE text IS NOT NULL
  ),
  -- 2 to 5 words: the floor is the precision hack above, the ceiling covers the 99th
  -- percentile of catalog name length while bounding the span count. A longer name is
  -- found by a shorter prefix or not at all.
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
  )
  SELECT 'warning' AS severity,
         c.entity_type,
         c.entity_id,
         c.public_id,
         -- ONE aggregate over the composed link, never two over its halves: independent
         -- aggregates may be satisfied from different rows, and "Star Wars" resolves to a
         -- franchise, two models and three titles, so the halves could render a link that
         -- does not exist. min() also holds still between runs, which a diffable report needs.
         format('{} names "{}" without linking it ({})', c.field, c.span,
                CASE WHEN count(DISTINCT p.target_link) = 1
                     THEN '[[' || min(p.target_link) || ']]'
                     ELSE format('{} candidates, e.g. [[{}]]',
                                 count(DISTINCT p.target_link), min(p.target_link))
                END) AS message
  FROM candidates c
  JOIN pool p ON p.match_key = name_norm(c.span)
  -- A record naming itself is audit_self_link's business, not this one.
  WHERE NOT (c.entity_type = p.target_type AND c.entity_id = p.target_id)
    -- Linked ANYWHERE in this record's prose, not just at this span: one link accounts
    -- for every mention of the same record.
    AND NOT EXISTS (
      SELECT 1 FROM record_references r
      WHERE r.source_entity_type = c.entity_type AND r.source_id = c.entity_id
        AND r.target_entity_type = p.target_type AND r.target_id = p.target_id)
  GROUP BY c.entity_type, c.entity_id, c.public_id, c.field, c.span;
COMMENT ON VIEW audit_unlinked_mention IS
  'WARNING — one row per (record, prose field, capitalized 2-5 word span) naming a linkable record the prose never links. Canonical names only, no aliases. A name inside a quotation is legitimately unlinked, which is why this is not an error.';

-- ─── parenthetical-fact ────────────────────────────────────────────────────
-- The house pattern _[[model:x]]_ (1997, [[manufacturer:williams]]) embeds two claims the
-- catalog already holds. Parse it and compare; a disagreement is either a description typo
-- or a catalog error, and both are worth an error.
--
-- A Title carries no year of its own, so a stated year is checked against the years of its
-- models and flagged only when it matches none — a multi-model Title spanning 1978-1982
-- accepts either.
CREATE OR REPLACE VIEW audit_parenthetical_fact AS
  -- Matched once, then the groups are read off the matched substring — so the pattern is
  -- written twice rather than once per group, and the four values cannot fall out of step.
  --
  -- NULLIF on the maker is load-bearing. The NAMED-GROUP form of regexp_extract returns
  -- '' for a group that did not participate, while the group-index form returns NULL —
  -- opposite conventions for the same absent value. Normalizing once here is what lets
  -- everything below test IS NULL and mean it.
  WITH hits AS (
    SELECT entity_type, entity_id, public_id, field,
           UNNEST(regexp_extract_all(
             text, '\[\[(model|title):id:(\d+)\]\][^(\[]{0,8}\((\d{4})(?:,\s*\[\[manufacturer:id:(\d+)\]\])?\)')) AS hit
    FROM entity_prose WHERE text IS NOT NULL
  ),
  parsed AS (
    SELECT entity_type, entity_id, public_id, field,
           g.link_type,
           -- TRY_CAST, not ::BIGINT: the id groups are `\d+` with no length bound, so one
           -- malformed link in one description would otherwise throw and take the whole
           -- audit down. An unparseable id joins to nothing and drops out instead.
           TRY_CAST(g.link_id AS BIGINT)                  AS link_id,
           g.stated_year::BIGINT                          AS stated_year,
           TRY_CAST(NULLIF(g.stated_maker, '') AS BIGINT) AS stated_maker
    FROM (
      SELECT entity_type, entity_id, public_id, field,
             regexp_extract(
               hit, '\[\[(model|title):id:(\d+)\]\][^(\[]{0,8}\((\d{4})(?:,\s*\[\[manufacturer:id:(\d+)\]\])?\)',
               ['link_type', 'link_id', 'stated_year', 'stated_maker']) AS g
      FROM hits)
  ),
  -- Both link kinds resolved to one shape: the record's name, and the years and makers the
  -- catalog allows. Empty lists rather than [NULL], so `len(...) = 0` reads as "the catalog
  -- says nothing here, so nothing is contradicted".
  facts AS (
    SELECT p.*, m.name AS target_name,
           CASE WHEN m.year IS NULL THEN []::BIGINT[] ELSE [m.year] END AS years,
           CASE WHEN m.manufacturer_id IS NULL THEN []::BIGINT[] ELSE [m.manufacturer_id] END AS makers
    FROM parsed p JOIN models m ON m.id = p.link_id
    WHERE p.link_type = 'model'
    UNION ALL
    -- A Title carries no year or maker of its own, so it takes its models' and a stated
    -- value is wrong only when it matches none — a Title spanning 1978-1982 accepts either.
    SELECT p.*, t.name,
           (SELECT COALESCE(list(m.year), []) FROM models m
             WHERE m.title_id = t.id AND m.year IS NOT NULL),
           (SELECT COALESCE(list(m.manufacturer_id), []) FROM models m
             WHERE m.title_id = t.id AND m.manufacturer_id IS NOT NULL)
    FROM parsed p JOIN titles t ON t.id = p.link_id
    WHERE p.link_type = 'title'
  ),
  judged AS (
    SELECT f.*,
           mk.name AS stated_maker_name,
           len(f.years) > 0 AND NOT list_contains(f.years, f.stated_year) AS year_wrong,
           f.stated_maker IS NOT NULL AND len(f.makers) > 0
             AND NOT list_contains(f.makers, f.stated_maker) AS maker_wrong,
           -- What the catalog holds, for the message. Named here so the SELECT below stays
           -- a rendering step.
           (SELECT string_agg(DISTINCT m.name, '/' ORDER BY m.name) FROM manufacturers m
             WHERE list_contains(f.makers, m.id)) AS catalog_makers
    FROM facts f
    LEFT JOIN manufacturers mk ON mk.id = f.stated_maker
  )
  -- DISTINCT because the unit is the DEFECT, not the occurrence: one description stating
  -- the same wrong parenthetical twice is one thing to fix, and two identical rows would
  -- read as a bug in the audit. Two different wrong parentheticals differ in `message`
  -- and both survive.
  SELECT DISTINCT
         'error' AS severity,
         entity_type,
         entity_id,
         public_id,
         -- Every piece is non-NULL by construction: concatenating a NULL blanks the whole
         -- message, and the finding then reads as broken rather than as a defect. The
         -- stated maker falls back to its raw id, so a link to a manufacturer that no
         -- longer resolves still says what the prose claimed.
         format('{} says {} ({}) but the catalog says {}', field, target_name,
                stated_year || COALESCE(', ' || COALESCE(stated_maker_name,
                                                         'manufacturer ' || stated_maker), ''),
                concat_ws(' and ',
                  CASE WHEN year_wrong
                       -- Sorted, so the same defect renders identically between runs.
                       THEN 'year ' || array_to_string(list_sort(list_distinct(years)), '/') END,
                  CASE WHEN maker_wrong
                       THEN 'maker ' || COALESCE(catalog_makers, 'unknown') END)) AS message
  FROM judged
  WHERE year_wrong OR maker_wrong;
COMMENT ON VIEW audit_parenthetical_fact IS
  'ERROR — one row per _[[link]]_ (year, [[manufacturer]]) parenthetical whose year or maker disagrees with the catalog. Either the prose is wrong or the record is; both want fixing.';

-- ─── duplicate-name ────────────────────────────────────────────────────────
-- Two live records of one entity type answering to the same string — as canonical names,
-- as aliases, or one of each. Usually one record that got created twice: theme
-- `automobiles` and theme `cars`, where `cars` carries the alias "Automobiles".
--
-- Names and aliases are ONE pool, because the collision that matters is between the
-- strings a reader or an importer would use, not between the columns they live in.
--
-- THREE TYPES ARE EXEMPT, and only these, each for a reason in the data model:
--   model, title — names legitimately repeat across makers and eras. `namesake_count`
--     exists on `models` precisely because this is normal; 2507 models and 2024 Titles
--     collide today, which would bury every other rule.
--   location — a location slug is unique only WITHIN its parent, which is why
--     `location_path` exists. Victoria, Australia and Victoria, Canada are not a defect.
-- Everything else is fair game, including the types with no collisions today: person is
-- the one this rule is really for, and it earns its keep the first time a maiden name
-- creates a second record.
--
-- Both sides of a collision are reported, since either record may be the one to merge
-- away and the report is read per record.
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
         format('{} "{}" also identifies {}', k.kind, k.text,
                (SELECT string_agg(DISTINCT o.entity_type || '.' || o.public_id, ', ')
                 FROM keys o
                 WHERE o.entity_type = k.entity_type AND o.k = k.k
                   AND o.entity_id <> k.entity_id)) AS message
  FROM keys k
  JOIN shared s ON s.entity_type = k.entity_type AND s.k = k.k;
COMMENT ON VIEW audit_duplicate_name IS
  'WARNING — one row per live record whose name or alias also identifies another record of the same type, usually a record created twice. Model, Title and Location are exempt: repeated names are normal for all three.';

-- ─── findings ──────────────────────────────────────────────────────────────
-- Columns are listed rather than `*` so a rule view that reorders its own SELECT cannot
-- silently swap message into severity — every column but entity_id is VARCHAR, so a swap
-- would not raise a type error.
CREATE OR REPLACE VIEW audit_findings AS
            SELECT 'self-link'             AS rule, severity, entity_type, entity_id, public_id, message FROM audit_self_link
  UNION ALL SELECT 'wrong-grain-link',          severity, entity_type, entity_id, public_id, message FROM audit_wrong_grain_link
  UNION ALL SELECT 'linkless-description',      severity, entity_type, entity_id, public_id, message FROM audit_linkless_description
  UNION ALL SELECT 'unlinked-mention',          severity, entity_type, entity_id, public_id, message FROM audit_unlinked_mention
  UNION ALL SELECT 'parenthetical-fact',        severity, entity_type, entity_id, public_id, message FROM audit_parenthetical_fact
  UNION ALL SELECT 'duplicate-name',            severity, entity_type, entity_id, public_id, message FROM audit_duplicate_name;
COMMENT ON VIEW audit_findings IS
  'One row per catalog defect across every rule — rule, severity, the record it is about and a human-readable message. Catalog content, not a health gate.';

-- ─── scoping ───────────────────────────────────────────────────────────────
-- Findings on records a given range of data patches wrote to — what a flippatch
-- pre-commit hook wants. A join, not a mechanism: the patch layer already knows every
-- subject a patch touched, so no rule needs to know data patches exist.
--
--   FROM audit_since(240);
--
-- A MACRO rather than a view, because the scoped result has to be two things a view
-- cannot be at once: filterable by patch number, and one row per DEFECT. Left at
-- (finding, patch) grain it reads as though a finding belonged to a patch, and a record
-- three patches touched prints three identical lines — 2.4x inflation across the full
-- patch range. Taking the bound as an argument lets the grain collapse after the filter.
--
-- The patch is a FILTER, not an attribution. These rules read current catalog state and
-- know nothing about patches, so a finding here means "a patch in range touched this
-- record", never "this patch caused it" — the defect is usually older than the patch.
-- The converse gap is worth knowing too: a patch can create findings on records it never
-- wrote to (rename a record and prose elsewhere now names it without linking it), and
-- nothing here will show them. Run the unscoped audit for that.
CREATE OR REPLACE MACRO audit_since(n) AS TABLE
  SELECT f.*,
         -- Zero-padded, because that is how a patch is named and tab-completed, and it
         -- makes the lexical sort the numeric one.
         string_agg(DISTINCT lpad(e.patch_number::VARCHAR, 4, '0'), ', '
                    ORDER BY lpad(e.patch_number::VARCHAR, 4, '0')) AS patches
  FROM audit_findings f
  JOIN patch_entries e
    ON e.subject_type = f.entity_type AND e.subject_id = f.entity_id
  WHERE e.patch_number >= n
  -- patch_entries is one row per ChangeSet and a grouped `changesets:` block writes
  -- several to one record, so the aggregate is what keeps that off the finding count.
  GROUP BY ALL;
COMMENT ON MACRO TABLE audit_since IS
  'audit_since(240) — one row per DEFECT on a record that patch 240 or later wrote to, with those patch numbers aggregated into `patches`. The patch-scoped lens; scope is a filter, never a claim that the patch caused the finding.';

-- Counted per rule VIEW rather than grouped from audit_findings, so a rule finding nothing
-- keeps its row. A rule dropping to zero is the failure worth seeing — these detectors read
-- authored prose and a sparse edge table, where a rotted regex returns exactly what a clean
-- catalog returns — and grouping would make it vanish from the readout instead.
CREATE OR REPLACE VIEW audit_summary AS
            SELECT 'self-link'            AS metric, count(*) AS value FROM audit_self_link
  UNION ALL SELECT 'wrong-grain-link',         count(*) FROM audit_wrong_grain_link
  UNION ALL SELECT 'linkless-description',     count(*) FROM audit_linkless_description
  UNION ALL SELECT 'unlinked-mention',         count(*) FROM audit_unlinked_mention
  UNION ALL SELECT 'parenthetical-fact',       count(*) FROM audit_parenthetical_fact
  UNION ALL SELECT 'duplicate-name',           count(*) FROM audit_duplicate_name
  UNION ALL SELECT 'TOTAL errors', count(*) FILTER (severity = 'error') FROM audit_findings
  UNION ALL SELECT 'TOTAL warnings', count(*) FILTER (severity = 'warning') FROM audit_findings
  UNION ALL SELECT 'records affected',
                   count(DISTINCT entity_type || ':' || entity_id) FROM audit_findings;
COMMENT ON VIEW audit_summary IS
  'One row per rule with its finding count, plus totals — the headline readout. Every rule keeps a row at zero, which is the state worth noticing.';

-- ─── the report ────────────────────────────────────────────────────────────
-- The rendered output of `scripts/analysis/audit <patch>`, one row per line, for
-- `--format lines`. Rendered in SQL rather than by the caller so the wording lives beside
-- the data it counts and cannot drift from it — and so flippatch's pre-commit hook and
-- this repo's runner print the same thing without either owning a second copy.
--
-- Shape: header, findings, footer. The counts appear TWICE on purpose. The reader is
-- often an AI session whose tool output gets truncated, and truncation is at the tail —
-- so a total read BEFORE the findings separates "I saw 40 of 240" from "there were 40".
-- The footer is the cheap other half: a header with no footer under it means the output
-- was cut, with nothing to count.
CREATE OR REPLACE MACRO plural(n, one, many) AS
  n::VARCHAR || ' ' || CASE WHEN n = 1 THEN one ELSE many END;
COMMENT ON MACRO plural IS
  'plural(1, ''patch'', ''patches'') -> ''1 patch''; plural(0, …) -> ''0 patches''. Both forms given — appending ''s'' is not English.';

CREATE OR REPLACE MACRO audit_report(since) AS TABLE (
  WITH f AS (FROM audit_since(since)),
  -- Counted from the patch LEDGER, not from the findings: a patch that applied cleanly
  -- and a patch that never applied both contribute nothing to f, and reporting them alike
  -- is how a stale database passes for a clean one.
  applied AS (SELECT count(DISTINCT patch_number) AS n
              FROM patch_entries WHERE patch_number >= since),
  -- The high end is the newest patch IN SCOPE, so a clean run still names the span it
  -- examined instead of an empty one.
  span AS (
    SELECT lpad(since::VARCHAR, 4, '0') AS lo,
           lpad(COALESCE((SELECT max(patch_number) FROM patch_entries
                          WHERE patch_number >= since), since)::VARCHAR, 4, '0') AS hi
  ),
  tally AS (
    SELECT plural(count(*) FILTER (severity = 'error'), 'error', 'errors') AS errs,
           plural(count(*) FILTER (severity = 'warning'), 'warning', 'warnings') AS warns,
           plural(count(DISTINCT entity_type || ':' || entity_id), 'record', 'records') AS recs
    FROM f
  ),
  summary AS (
    SELECT a.n AS n_applied,
           CASE WHEN a.n = 0
                THEN 'NOTHING WAS AUDITED — no patch >= ' || s.lo
                     || ' is in this database; run make ingest-patches'
                ELSE t.errs || ' and ' || t.warns || ' in ' || t.recs
                     || ' across ' || plural(a.n, 'patch', 'patches')
                     || ' from ' || s.lo || '-' || s.hi
           END AS text
    FROM tally t, span s, applied a
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
    -- Header and footer carry the same sentence; the endings tell them apart
    -- (', errors first:' introduces the list, '.' closes it), so neither needs a label.
    SELECT 0 AS section, NULL::INTEGER AS k1, '' AS k2,
           text || CASE WHEN n_applied = 0 THEN '' ELSE ', errors first:' END AS line
    FROM summary
    UNION ALL SELECT 1, NULL, '', '' FROM summary WHERE n_applied > 0
    -- Rank leads rather than the line, which would sort on the emoji: ⚠ is U+26A0 and
    -- ❌ is U+274C, so warnings would come first.
    UNION ALL SELECT 2, rank, line, line FROM rendered
    UNION ALL SELECT 3, NULL, '', '' FROM summary WHERE n_applied > 0
    UNION ALL SELECT 4, NULL, '', text || '.' FROM summary WHERE n_applied > 0
  ) ORDER BY section, k1, k2
);
COMMENT ON MACRO TABLE audit_report IS
  'audit_report(240) — the rendered lint report for patches >= 240, one row per line: header, findings (errors first), footer. Read with --format lines; scripts/analysis/audit is the entry point.';
