-- Prose layer — the authored corpus as data: the wikilink graph and the
-- mention-bearing readings of entity_prose.
--
-- README.md to do analysis; EDITING.md to change this file.

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
-- curly doubles alike.
--
-- EXCLUDING \n IS THE CONTAINMENT: an unbalanced mark can never reach past its own
-- paragraph. The length cap only bounds the damage inside that line, which is why it sits
-- well above the longest quote anyone writes (229 characters in the corpus today). A cap
-- set below a genuine quote is the harmful direction, and it fails twice over: the quote
-- drops out of prose_quotes AND stays in prose_words, seeding exactly the spurious
-- mentions the exclusion exists to prevent.
--
-- AN OPENING MARK IS NEVER FOLLOWED BY A SPACE, which is what separates a quote from an
-- INCH MARK: `a 3" flipper` reads as an opening mark to anything matching on the mark
-- alone, and it then pairs with the next measurement down the line and deletes every
-- word between them — silently, since prose_words losing text produces no finding
-- anywhere. Nothing local distinguishes a CLOSING mark from an inch mark (both sit after
-- a non-space and before a break, and a genuine quote may end on a digit), so the rule
-- is stated on the opening end, where the distinction actually exists.
CREATE OR REPLACE MACRO _quoted_run() AS '["“”][^\s"“”][^"“”\n]{0,299}["“”]';

-- prose_quotes — the wordings prose QUOTES rather than says: a machine's nickname, a
-- feature name as a source spelled it, a marketing slogan. A name in here is legitimately
-- unwikilinked, which is exactly why these runs are absent from prose_words.
CREATE OR REPLACE VIEW prose_quotes AS
  SELECT entity_type, entity_id, public_id, field,
         UNNEST([regexp_replace(q, '^["“”]|["“”]$', '', 'g')
                 for q in regexp_extract_all(text, _quoted_run())]) AS quote
  FROM entity_prose WHERE text IS NOT NULL;
COMMENT ON VIEW prose_quotes IS
  'One row per double-quoted run in a live record''s prose (straight or curly, marks stripped) — the wordings prose quotes rather than says. The complement of prose_words, which excludes these runs. A run must open and close on one line and within 300 characters; a mark left unclosed yields no row rather than swallowing the paragraph.';

-- prose_words — each prose field as a word array: wikilink markup and quoted runs
-- removed, accents folded, punctuation collapsed, CASE KEPT so a consumer can still
-- distinguish the game Pinball from the word pinball. Word position in this array is the
-- shared coordinate system: every consumer that matches spans against prose reads this
-- one tokenization, or its positions disagree with its neighbours'.
--
-- A markdown link contributes its VISIBLE TEXT and not its destination. Punctuation
-- collapsing would otherwise read `/Attack_From_Mars` in a URL as three capitalized
-- words — a catalog name no author wrote and none can link, so a span consumer reports a
-- mention that exists nowhere on the page.
--
-- The destination carries ONE LEVEL OF BALANCED PARENTHESES, which CommonMark allows and
-- Wikipedia's disambiguators (`/wiki/Medieval_Madness_(pinball)`) spend constantly.
-- Stopping at the first `)` ends the match mid-URL and hands the remainder back as prose,
-- which is the same fabricated mention by another route. One level is the practical
-- bound, not a general one: RE2 has no recursion, and no real destination nests deeper.
-- A macro for the reason _quoted_run and _paren_pattern are macros: it is the only way
-- foundation_checks can state the tokenization against input we control. A view reads
-- entity_prose, so a check over one can assert what the corpus happens to contain and
-- nothing about what the strips DO — and a strip that stops stripping leaves every row
-- in place with the wrong words in it, which is indistinguishable from a clean catalog.
CREATE OR REPLACE MACRO _prose_tokens(t) AS
  str_split(trim(regexp_replace(
    strip_accents(regexp_replace(
      regexp_replace(regexp_replace(t, '\[\[[^\]]*\]\]', ' ', 'g'),
                     '\]\((?:[^()\n]|\([^()\n]*\))*\)', ' ', 'g'),
      _quoted_run(), ' ', 'g')),
    '[^\p{L}\p{N}]+', ' ', 'g')), ' ');

CREATE OR REPLACE VIEW prose_words AS
  SELECT entity_type, entity_id, public_id, field, _prose_tokens(text) AS w
  FROM entity_prose WHERE text IS NOT NULL;
COMMENT ON VIEW prose_words IS
  'One row per prose field of a live record — the text as a word array, wikilink markup, markdown link destinations and quoted runs removed, accents folded, case kept. The shared tokenization: match spans against this so word positions agree across consumers; quoted wordings live in prose_quotes instead.';

-- The house parenthetical — _[[model:x]]_ (1997, [[manufacturer:williams]]) — is an
-- authoring convention of the corpus: prose restates a year and maker the catalog
-- already holds beside the link. One definition, like _quoted_run above, so a consumer
-- that finds parentheticals and one that parses them cannot drift apart.
--
-- A macro rather than the CTE this looks like it wants: the named-group form of
-- regexp_extract requires a CONSTANT pattern, and a column reference is not one.
--
-- ONLY EMPHASIS MARKERS AND HORIZONTAL WHITESPACE separate the link from the
-- parenthetical, because the convention writes the two adjacent. A gap admitting WORDS
-- reads an ordinary sentence — `the [[title:id:N]] Remake (2014)` — as a restated
-- catalog fact, and audit_parenthetical_fact then reports the disagreement as an error
-- against prose that is right.
CREATE OR REPLACE MACRO _paren_pattern() AS
  '\[\[(model|title):id:(\d+)\]\][*_ \t]{0,8}\((\d{4})(?:,\s*\[\[manufacturer:id:(\d+)\]\])?\)';

-- prose_parentheticals — every house parenthetical in the corpus, parsed once. A second
-- copy of this parse would drift from the first without either one failing.
--
-- Two passes because regexp_extract_all returns whole matches and no groups: find, then
-- read the groups off each match. Both take the pattern from the macro, since two copies
-- that drift would find a different set of parentheticals than they parse, silently.
--
-- NULLIF is load-bearing: the named-group form of regexp_extract returns '' for a group
-- that did not participate where the group-index form returns NULL. Normalizing once here
-- lets every consumer test IS NULL and mean it.
CREATE OR REPLACE VIEW prose_parentheticals AS
  WITH hits AS (
    SELECT entity_type, entity_id, public_id, field,
           UNNEST(regexp_extract_all(text, _paren_pattern())) AS hit
    FROM entity_prose WHERE text IS NOT NULL
  )
  SELECT entity_type, entity_id, public_id, field,
         g.link_type,
         -- TRY_CAST, not ::BIGINT: the id groups are `\d+` with no length bound, so one
         -- malformed link would otherwise throw and take down every consumer.
         TRY_CAST(g.link_id AS BIGINT)                  AS link_id,
         g.stated_year::BIGINT                          AS stated_year,
         TRY_CAST(NULLIF(g.stated_maker, '') AS BIGINT) AS stated_maker
  FROM (
    SELECT entity_type, entity_id, public_id, field,
           regexp_extract(hit, _paren_pattern(),
             ['link_type', 'link_id', 'stated_year', 'stated_maker']) AS g
    FROM hits);
COMMENT ON VIEW prose_parentheticals IS
  'One row per house parenthetical _[[link]]_ (year, [[manufacturer]]) in a live record''s prose — the link it names and the facts it states, parsed once for every consumer. stated_maker is NULL when the parenthetical names no maker.';
