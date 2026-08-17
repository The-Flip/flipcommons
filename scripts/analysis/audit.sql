-- Catalog audit — deterministic lint rules over the live catalog.
--
--     scripts/analysis/audit 0240   -- the report; `audit` alone for per-rule counts
--
--     scripts/analysis/analysis query scripts/analysis/audit.sql "FROM audit_findings;"
--     scripts/analysis/analysis query scripts/analysis/audit.sql "FROM audit_since(240);"
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
.read scripts/analysis/catalog.sql

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
-- A model alone in its Title is the same thing as that Title in the UI
-- (SingleModelTitles.md), so linking the model is simply wrong. With several models in
-- the Title the choice can be deliberate, hence a warning rather than an error.
CREATE OR REPLACE VIEW audit_wrong_grain_link AS
  SELECT CASE WHEN m.title_size = 1 THEN 'error' ELSE 'warning' END AS severity,
         r.source_entity_type AS entity_type,
         r.source_id          AS entity_id,
         r.source_public_id   AS public_id,
         -- By slug: models of one Title can share a name, so a name would render two
         -- distinct findings identically. It is also how a data patch addresses a record.
         CASE WHEN m.title_size = 1
              THEN format('links [[model:{}]], the only model of its Title — link [[title:{}]] instead',
                          m.slug, m.title_slug)
              ELSE format('links [[model:{}]] ("{}"), one of {} models in Title [[title:{}]] — confirm the model grain is deliberate',
                          m.slug, m.name, m.title_size, m.title_slug)
         END AS message
  FROM record_references r
  JOIN models m ON m.id = r.target_id
  WHERE r.target_entity_type = 'model'
    -- A Title naming its own models is the one place the model grain is unambiguously
    -- deliberate. It is also the corner the advice cannot survive: for a single-model
    -- Title, "link the Title instead" would name the source itself.
    AND NOT (r.source_entity_type = 'title' AND m.title_id = r.source_id);
COMMENT ON VIEW audit_wrong_grain_link IS
  'ERROR when prose links a model alone in its Title (link the Title instead); WARNING when the Title holds several and the grain may be deliberate.';

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
    SELECT s.subject_type AS target_type, s.subject_id AS target_id,
           s.subject_type || ':' || s.subject_public_id AS target_link,
           name_norm(n.name) AS match_key
    FROM entity_subjects s
    JOIN entity_registry r ON r.entity_type = s.subject_type
    JOIN names n ON n.entity_type = s.subject_type AND n.entity_id = s.subject_id
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
    SELECT c.entity_type, c.entity_id, c.public_id, c.field, c.span, p.target_link,
           -- Prose naming its own subject is not a missing link.
           (c.entity_type = p.target_type AND c.entity_id = p.target_id) AS is_self,
           -- Linked anywhere in this record's prose, not only at this span: one link
           -- accounts for every mention of the same record.
           EXISTS (
             SELECT 1 FROM record_references r
             WHERE r.source_entity_type = c.entity_type AND r.source_id = c.entity_id
               AND r.target_entity_type = p.target_type AND r.target_id = p.target_id
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
         -- exist. min() also holds still between runs, which a diffable report needs.
         format('{} names "{}" without linking it ({})', field, span,
                CASE WHEN count(DISTINCT target_link) = 1
                     THEN '[[' || min(target_link) || ']]'
                     ELSE format('{} candidates, e.g. [[{}]]',
                                 count(DISTINCT target_link), min(target_link))
                END) AS message
  FROM matched
  GROUP BY entity_type, entity_id, public_id, field, span
  -- A span is accounted for if ANY record it names is the source itself or already
  -- linked, so the whole group goes. Judged here rather than filtered per candidate
  -- because records commonly share a name across types: filtering one candidate leaves
  -- its namesakes behind and warns about prose that is not wrong.
  HAVING NOT bool_or(is_self OR linked);
COMMENT ON VIEW audit_unlinked_mention IS
  'WARNING — one row per (record, prose field, capitalized 2-5 word span) naming a linkable record the prose never links. Matches canonical names and aliases alike; a span naming several records renders as "N candidates". A name inside a quotation is legitimately unlinked, which is why this is not an error.';

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

CREATE OR REPLACE VIEW audit_parenthetical_fact AS
  -- Two passes because regexp_extract_all returns whole matches and no groups: find, then
  -- read the groups off each match. Both take the pattern from the macro, since two copies
  -- that drift would find a different set of parentheticals than they parse, silently.
  --
  -- NULLIF is load-bearing: the named-group form of regexp_extract returns '' for a group
  -- that did not participate where the group-index form returns NULL. Normalizing once
  -- here lets everything below test IS NULL and mean it.
  WITH hits AS (
    SELECT entity_type, entity_id, public_id, field,
           UNNEST(regexp_extract_all(text, paren_pattern())) AS hit
    FROM entity_prose WHERE text IS NOT NULL
  ),
  parsed AS (
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
      FROM hits)
  ),
  -- Both link kinds resolved to one shape: the name, and the years and makers the catalog
  -- allows. Empty lists rather than [NULL], so `len(...) = 0` reads as "the catalog says
  -- nothing here, so nothing is contradicted".
  facts AS (
    SELECT p.*, m.name AS target_name,
           CASE WHEN m.year IS NULL THEN []::BIGINT[] ELSE [m.year] END AS years,
           CASE WHEN m.manufacturer_id IS NULL THEN []::BIGINT[] ELSE [m.manufacturer_id] END AS makers
    FROM parsed p JOIN models m ON m.id = p.link_id
    WHERE p.link_type = 'model'
    UNION ALL
    -- A Title has no year or maker of its own, so it takes its models' and a stated value
    -- is wrong only when it matches none of them.
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
           -- Named here so the SELECT below stays a rendering step.
           (SELECT string_agg(DISTINCT m.name, '/' ORDER BY m.name) FROM manufacturers m
             WHERE list_contains(f.makers, m.id)) AS catalog_makers
    FROM facts f
    LEFT JOIN manufacturers mk ON mk.id = f.stated_maker
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

-- ─── findings ──────────────────────────────────────────────────────────────
-- Columns listed rather than `*`: every column but entity_id is VARCHAR, so a rule that
-- reordered its own SELECT could swap message into severity without a type error.
CREATE OR REPLACE VIEW audit_findings AS
            SELECT 'self-link'             AS rule, severity, entity_type, entity_id, public_id, message FROM audit_self_link
  UNION ALL SELECT 'wrong-grain-link',          severity, entity_type, entity_id, public_id, message FROM audit_wrong_grain_link
  UNION ALL SELECT 'linkless-description',      severity, entity_type, entity_id, public_id, message FROM audit_linkless_description
  UNION ALL SELECT 'unlinked-mention',          severity, entity_type, entity_id, public_id, message FROM audit_unlinked_mention
  UNION ALL SELECT 'parenthetical-fact',        severity, entity_type, entity_id, public_id, message FROM audit_parenthetical_fact
  UNION ALL SELECT 'duplicate-name',            severity, entity_type, entity_id, public_id, message FROM audit_duplicate_name
  UNION ALL SELECT 'broken-link',               severity, entity_type, entity_id, public_id, message FROM audit_broken_link;
COMMENT ON VIEW audit_findings IS
  'One row per catalog defect across every rule — rule, severity, the record it is about and a human-readable message. Catalog content, not a health gate.';

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
  -- Not redundant with the foundation: rules reading entity_subjects and entity_aliases
  -- apply liveness themselves, since those views are not live-filtered. This guards a
  -- filter the rules own rather than inherit.
  SELECT 'finding_subject_not_live',
         rule || ' -> ' || entity_type || ':' || entity_id::VARCHAR
  FROM f
  WHERE NOT EXISTS (
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
-- Header, findings, footer. The counts appear twice on purpose: output read by a tool is
-- truncated at the tail, so a total BEFORE the findings separates "I saw 40 of 240" from
-- "there were 40", and a header with no footer under it means the output was cut.
CREATE OR REPLACE MACRO plural(n, one, many) AS
  n::VARCHAR || ' ' || CASE WHEN n = 1 THEN one ELSE many END;
COMMENT ON MACRO plural IS
  'plural(1, ''patch'', ''patches'') -> ''1 patch''; plural(0, …) -> ''0 patches''. Both forms given — appending ''s'' is not English.';

CREATE OR REPLACE MACRO audit_report(since) AS TABLE (
  WITH f AS (FROM audit_since(since)),
  -- From the patch LEDGER, not from the findings: a patch that applied cleanly and one
  -- that never applied both contribute nothing to `f`, and a stale database would
  -- otherwise read as a clean one.
  applied AS (SELECT count(DISTINCT patch_number) AS n
              FROM patch_entries WHERE patch_number >= since),
  -- The newest patch in scope, so a clean run still names the span it examined.
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
    -- Header and footer carry the same sentence; the endings tell them apart, so neither
    -- needs a label.
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
