-- Provenance analysis foundation — the attribution and citation layer.
--
-- `.read` by catalog.sql at its tail, so any analysis that reads the foundation gets
-- these for free. It needs `models` (for the live-model lens) so it cannot load first.
--
-- WHAT THIS ANSWERS. catalog.sql shows the catalog's RESOLVED state — the value that
-- won. This file shows WHO SAID SO: which ingest source asserted a fact, in which
-- ingest run / data patch, whether it won, and what external evidence was cited.
--
-- ─── "Source" is two different things. Never write the bare word. ───────────
-- The single biggest source of wrong answers in this area, so the naming rule is
-- mechanical: every view, column and comment says INGEST SOURCE or CITATION SOURCE,
-- never `source` alone.
--
--   INGEST SOURCE   (provenance_source -> actors_actor) — WHO ASSERTED the fact.
--                   `ipdb`, `opdb`, `flipcommons-catalog`, `flip-museum`, the 21
--                   per-entity AI-description sources. Carries the `priority` that
--                   decides conflicts. Present on EVERY claim, no exceptions.
--   CITATION SOURCE (citation_citationsource) — EXTERNAL EVIDENCE for the fact.
--                   A book, a magazine, an IPDB page. Present on ~2% of claims.
--
-- They are unrelated tables with unrelated cardinality, and the failure they invite is
-- specific: an analysis asks "is this cited?", gets no citation and concludes the fact
-- is unsourced — when it is in fact fully attributed to an ingest source. A claim with
-- no citation is the NORM, not a defect.
--
-- ─── This layer RANKS; it does not RESOLVE ─────────────────────────────────
-- Resolution proper (apps/catalog/resolve/*, ~2,300 lines: through-row projection,
-- media, aliases, coercion, diffing, writes) materializes claims into the catalog
-- tables. NONE of it is reimplemented here, and it must not be — the resolved state
-- already sits in the physical tables that catalog.sql reads.
--
-- What IS reproduced is the winner-pick that precedes it, which is small and stable:
-- apps/provenance/claim_ranking_in_db.ranked_claims (eligible claims ordered by
-- priority, then recency, then pk) plus claim_presence.member_is_present (a member
-- claim with exists=false is a tombstone). That is the `rank` column and the
-- `member_exists` column below — roughly ten lines of SQL.
--
-- So the division is deliberate: **the CATALOG states the outcome, this file states a
-- RANKING**. The column is `rank`, not `is_winner`, because an analysis must never
-- treat this file as authoritative for what a value IS — read the catalog for that and
-- join here for who said it. provenance_checks asserts the two agree over every
-- resolved gameplay-feature edge and theme edge, which is what keeps the ranking
-- honest against the real resolver.

-- ═══ CLAIMS — who asserted what, and how claims compete ══════════════════
-- Claims compete within a REGISTER — the grouping key the winner-pick partitions on.
-- pick_winners groups membership sets on `claim_key` but scalar registers on
-- `field_name`, and those two are NOT always the same string, so getting it wrong
-- silently changes the winner with no error anywhere.
--
-- They coincide for most scalars because make_claim_key returns field_name unchanged
-- when there are no identity parts. Exactly one field diverges in the catalog today:
--   field_name                     claim_key            n
--   manufacturer_model_identifier  ipdb.model_number    2322
-- Group THAT by claim_key and IPDB's key becomes its own private register instead of
-- competing with the other assertions of the same field — a different, wrong winner.
--
-- The split is derived STRUCTURALLY rather than from a registry: make_claim_key emits
-- `field|part:value|…` for a relationship member and a bare field_name for a scalar, so
-- a `|` in the claim_key means "has identity parts" means "member". Two invariants hold
-- it up, both asserted by provenance_checks rather than assumed —
-- `member_claim_nondict_value` (every member claim's value is a JSON object) and
-- `scalar_claim_exists_flag` (no non-member claim carries an `exists` key). The second
-- is the one that matters: claim_presence.py warns that a claim-controlled JSON SCALAR
-- can itself be a dict with an `exists` key (Location.divisions), so sniffing the VALUE
-- shape would be unsafe. Sniffing the KEY is not, and the check proves it stays that way.
CREATE OR REPLACE VIEW _claim_key_parts AS
  SELECT
    c.id                                                        AS claim_id,
    contains(c.claim_key, '|')                                  AS is_member,
    CASE WHEN contains(c.claim_key, '|') THEN c.claim_key
         ELSE c.field_name END                                  AS register,
    -- Explicit len() end, NOT a NULL end: list_slice(l, 2, NULL) returns NULL rather
    -- than "to the end", which silently empties every identity part in the file.
    list_slice(str_split(c.claim_key, '|'), 2,
               len(str_split(c.claim_key, '|')))                AS raw_parts
  FROM fc.provenance_claim c;

-- claim_identity_parts — the decoded identity parts of a claim_key, one row per part.
-- The general form of `claims.ref_id`, for the compound claims ref_id cannot express
-- (`credit|person:100|role:4` names two entities; `abbreviation|value:$6M` names none).
-- Un-escapes the three reserved characters make_claim_key percent-escapes, %25 LAST so
-- an escaped literal '%7C' in a value survives instead of decoding to '|'.
CREATE OR REPLACE VIEW _claim_identity_parts AS
  SELECT
    p.claim_id,
    regexp_extract(part, '^([^:]*):', 1)                        AS part_name,
    replace(replace(replace(
      regexp_extract(part, '^[^:]*:(.*)$', 1),
      '%7C', '|'), '%3A', ':'), '%25', '%')                     AS part_value
  FROM _claim_key_parts p, unnest(p.raw_parts) AS u(part)
  WHERE p.is_member;

-- _claim_ref — the single-entity-reference shortcut. Populated only when the claim has
-- exactly ONE identity part whose value is all digits, which covers the dominant
-- membership shape (gameplay_feature, theme, reward_type, location, …). A compound
-- claim or a literal-keyed one gets NULL and belongs in claim_identity_parts.
CREATE OR REPLACE VIEW _claim_ref AS
  SELECT claim_id, try_cast(min(part_value) AS BIGINT) AS ref_id
  FROM _claim_identity_parts
  GROUP BY claim_id
  HAVING count(*) = 1 AND bool_and(regexp_matches(part_value, '^[0-9]+$'));

-- _claim_actor — the actor behind a claim, decoded. One row per actor.
-- `actors_actor` is the uniform attribution column: an actor backs EITHER an ingest
-- source (25 today) or a user (2), carries the `priority` that drives the winner-pick
-- and the `resolution_status` kill switch. ingest_source_* is NULL for a user actor;
-- read actor_kind before reading them.
CREATE OR REPLACE VIEW _claim_actor AS
  SELECT
    a.id                  AS actor_id,
    a.backing_model       AS actor_kind,
    a.priority            AS actor_priority,
    a.resolution_status   AS actor_resolution_status,
    s.slug                AS ingest_source_slug,
    s.name                AS ingest_source_name,
    s.source_type         AS ingest_source_type,
    l.slug                AS ingest_source_default_license_slug
  FROM fc.actors_actor a
  LEFT JOIN fc.provenance_source s ON s.actor_id = a.id
  LEFT JOIN fc.core_license l      ON l.id = s.default_license_id;

-- ─── claims ────────────────────────────────────────────────────────────────
-- The spine of this file. One row per claim across EVERY subject type — 21 of them, so
-- the content-type decode is generic (subject_type = 'catalog.machinemodel') and no
-- per-entity list appears anywhere here.
--
-- NOT LIVE-FILTERED, deliberately, and the one place this file departs from the rest of
-- the foundation. Provenance of a soft-deleted record is legitimate history (39 claims
-- sit on deleted models today), and liveness is not even expressible uniformly across
-- 21 subject types without a hand-list of tables. `model_claims` below is the live lens
-- for the dominant subject; anything counting claims per ingest source off `claims`
-- itself is counting dead subjects too, which is usually not what was meant.
--
--   register / is_member : see the register block above. Predicate on `register` when
--             asking "what competed"; `field_name` when asking "what kind of fact".
--   value   : the raw asserted JSON, as stored.
--   member_exists : NULL for a scalar. For a member, FALSE means a TOMBSTONE — this
--             actor asserts the member is ABSENT. 119 active claims say this today, and
--             a membership query that ignores it reports the exact opposite of the
--             recorded fact. Combined with the ranking this makes membership
--             remove-wins: a higher-priority tombstone drops the member.
--   ref_id  : the referenced entity's pk for a single-reference member claim, else
--             NULL — the join key back to a catalog grain view. Compound claims
--             (credit) need claim_identity_parts instead.
--   rank    : 1 = top-ranked for this (subject, register). NULL = INELIGIBLE, i.e.
--             inactive or from a suppressed actor, which is a different thing from
--             "ranked last" and is why this is NULL rather than a large number.
--             A RANKING, not a verdict — read the catalog for the outcome.
--   license_slug : the per-claim license OVERRIDE only. NULL means "inherits", and the
--             inheritance chain (source field license, then ingest source default) is
--             not resolved here; ingest_source_default_license_slug is the tail of it,
--             so a consumer that needs the effective license can express its own rule.
--   patch_id : the data patch this claim arrived in, NULL for an interactive edit —
--             the column a flippatch campaign asks "what did patch NNNN actually do".
--   retracted_by_changeset_id / retracted_by_patch_id : the changeset that DEACTIVATED
--             this claim, and the patch that changeset belonged to (NULL for a user
--             revert). Note the asymmetry against `patch_id`, which names the patch that
--             WROTE the claim: a patch that only retracts writes no claims at all, so
--             `patch_id` never mentions it and it is invisible to anything grouping on
--             that column alone. 780 claims are retracted by a patch today across ten
--             patches, seven of which assert nothing whatsoever. Always NULL on an active
--             claim — `provenance_claim_retracted_requires_inactive` constrains the FK to
--             is_active=false, so this is a strictly narrower signal than `is_active`,
--             which also goes false on ordinary supersession.
CREATE OR REPLACE VIEW claims AS
  SELECT
    c.id                                          AS claim_id,
    ct.app_label || '.' || ct.model               AS subject_type,
    c.object_id                                   AS subject_id,
    c.field_name                                  AS field_name,
    c.claim_key                                   AS claim_key,
    p.register                                    AS register,
    p.is_member                                   AS is_member,
    c.value                                       AS value,
    CASE WHEN p.is_member
         THEN coalesce(json_extract_string(c.value, '$.exists'), 'true') <> 'false'
    END                                           AS member_exists,
    r.ref_id                                      AS ref_id,
    CASE WHEN c.is_active
          AND a.actor_resolution_status IS DISTINCT FROM 'suppressed'
         THEN row_number() OVER (
                PARTITION BY c.content_type_id, c.object_id, p.register
                ORDER BY a.actor_priority DESC, c.created_at DESC, c.id DESC)
    END                                           AS rank,
    c.is_active                                   AS is_active,
    a.actor_id, a.actor_kind, a.actor_priority, a.actor_resolution_status,
    a.ingest_source_slug, a.ingest_source_name, a.ingest_source_type,
    a.ingest_source_default_license_slug,
    l.slug                                        AS license_slug,
    c.changeset_id                                AS changeset_id,
    cs.action                                     AS changeset_action,
    cs.ingest_run_id                              AS ingest_run_id,
    ir.patch_id                                   AS patch_id,
    c.retracted_by_changeset_id                   AS retracted_by_changeset_id,
    ir_r.patch_id                                 AS retracted_by_patch_id,
    c.created_at                                  AS created_at
  FROM fc.provenance_claim c
  JOIN fc.django_content_type ct   ON ct.id = c.content_type_id
  JOIN _claim_key_parts p          ON p.claim_id = c.id
  JOIN fc.provenance_changeset cs  ON cs.id = c.changeset_id
  JOIN _claim_actor a              ON a.actor_id = c.actor_id
  LEFT JOIN _claim_ref r           ON r.claim_id = c.id
  LEFT JOIN fc.core_license l      ON l.id = c.license_id
  LEFT JOIN fc.provenance_ingestrun ir ON ir.id = cs.ingest_run_id
  LEFT JOIN fc.provenance_changeset cs_r ON cs_r.id = c.retracted_by_changeset_id
  LEFT JOIN fc.provenance_ingestrun ir_r ON ir_r.id = cs_r.ingest_run_id;
COMMENT ON VIEW claims IS
  'One row per claim, every subject type — who asserted what, with rank, member_exists, ref_id, ingest source, changeset and patch_id, plus the changeset/patch that later retracted it. NOT live-filtered; use model_claims for the live-model lens.';

-- model_claims — claims about LIVE machine models, keyed model_id so it joins straight
-- to `models` and the grain views. The live-only lens `claims` deliberately isn't, and
-- the shape 90% of analysis wants.
--
-- The canonical attribution join — which ingest source attributed a gameplay feature:
--
--   SELECT m.slug, f.feature_slug, c.ingest_source_slug, c.patch_id, c.rank
--   FROM models m
--   JOIN model_gameplay_features f ON f.model_id = m.id
--   JOIN model_claims c ON c.model_id = f.model_id
--                      AND c.field_name = 'gameplay_feature'
--                      AND c.ref_id = f.feature_id
--   WHERE m.slug = 'medieval-madness'
--   ORDER BY f.feature_slug, c.rank NULLS LAST;
--
-- Note what that returns: EVERY ingest source that asserted the edge, not just the one
-- that won. Starting from `model_gameplay_features` means the edge is known to have
-- resolved; `rank = 1` names the attribution and the rest are the corroboration (or the
-- disagreement), which is exactly the question a data patch campaign is asking.
CREATE OR REPLACE VIEW model_claims AS
  SELECT c.*, c.subject_id AS model_id
  FROM claims c
  WHERE c.subject_type = 'catalog.machinemodel'
    AND EXISTS (SELECT 1 FROM models m WHERE m.id = c.subject_id);
COMMENT ON VIEW model_claims IS
  'One row per claim about a LIVE machine model, keyed model_id — the live lens on claims. Join to a model grain view on (model_id, field_name, ref_id) to attribute a resolved fact to its ingest source.';

-- claim_identity_parts — the public projection of the parse above. Defined HERE rather
-- than beside it so `claims` leads this block in definition order, which is the order
-- `analysis describe` lists them in: the spine first, its long-tail helper after.
CREATE OR REPLACE VIEW claim_identity_parts AS
  SELECT claim_id, part_name, part_value FROM _claim_identity_parts;
COMMENT ON VIEW claim_identity_parts IS
  'One row per (claim, identity part) decoded from claim_key — part_name/part_value, un-escaped. The general form of claims.ref_id; use it for compound claims like credit (person + role) that name more than one entity.';

-- ═══ INGEST SOURCES AND RUNS — who and when ═════════════════════════════════
-- ingest_sources — the vocabulary shape (one row per term, with usage counts), for the
-- ingest-source side of the "two sources" split at the top of this file.
--   n_claims / n_active_claims : everything this source has ever asserted.
--   n_top_ranked : claims where rank = 1 — how much this source actually DECIDES, which
--             is the number that separates a high-volume source from an influential one.
--             A low-priority source can assert a great deal and win almost none of it.
--   is_enabled / resolution_status : the SAME kill switch in two spellings, and the
--             pair is carried deliberately. `is_enabled` is the authored toggle on
--             Source; `resolution_status` is the Actor mirror of it, and the mirror is
--             what the winner-pick actually reads (`claim_ranking_in_db._annotate_
--             priority` excludes suppressed ACTORS, not disabled sources). So the two
--             can only disagree if a Source was written without its Actor resyncing,
--             and in that state resolution follows `resolution_status` while a human
--             reading the admin sees `is_enabled`. Predicate on resolution_status;
--             `ingest_source_enabled_desyncs` fails if they ever part company.
-- Counts are over `claims`, so they include deleted subjects; that is the honest count
-- of what the source asserted. Filter through model_claims for a live-only figure.
CREATE OR REPLACE VIEW ingest_sources AS
  SELECT
    s.id                    AS ingest_source_id,
    s.slug                  AS ingest_source_slug,
    s.name                  AS ingest_source_name,
    s.source_type           AS ingest_source_type,
    a.actor_priority        AS priority,
    a.actor_resolution_status AS resolution_status,
    s.is_enabled            AS is_enabled,
    s.url                   AS url,
    a.ingest_source_default_license_slug AS default_license_slug,
    count(c.claim_id)                                          AS n_claims,
    count(*) FILTER (c.is_active)                              AS n_active_claims,
    count(*) FILTER (c.rank = 1)                               AS n_top_ranked
  FROM fc.provenance_source s
  JOIN _claim_actor a ON a.actor_id = s.actor_id
  LEFT JOIN claims c  ON c.actor_id = s.actor_id
  GROUP BY ALL;
COMMENT ON VIEW ingest_sources IS
  'One row per INGEST SOURCE (who asserted a fact — ipdb, opdb, flipcommons-catalog) with priority and claim counts; n_top_ranked is how much it actually decides. Not to be confused with citation_sources (external evidence).';

-- ingest_runs — one row per IngestRun: the patch-level ledger. `patch_id` is the
-- flippatch `NNNN-slug` file, NULL for a non-patch run. Interactive edits have no run
-- at all and appear here not at all — they are ChangeSets with action set instead.
CREATE OR REPLACE VIEW ingest_runs AS
  SELECT
    ir.id               AS ingest_run_id,
    ir.patch_id         AS patch_id,
    s.slug              AS ingest_source_slug,
    ir.status           AS status,
    ir.started_at       AS started_at,
    ir.finished_at      AS finished_at,
    ir.input_fingerprint AS input_fingerprint,
    ir.records_parsed, ir.records_matched, ir.records_created,
    ir.claims_asserted, ir.claims_retracted, ir.claims_rejected,
    ir.citation_sources_created, ir.citation_source_links_created,
    ir.note             AS note
  FROM fc.provenance_ingestrun ir
  LEFT JOIN fc.provenance_source s ON s.id = ir.source_id;
COMMENT ON VIEW ingest_runs IS
  'One row per ingest run — patch_id, ingest source, status, fingerprint and the asserted/retracted/rejected claim counts. Reach for it when the subject is a patch rather than what the patch wrote.';

-- ═══ CITATION SOURCES — external evidence ═══════════════════════════════════
-- The EVIDENCE side. A citation source is a two-level tree: a ROOT (the work — a book,
-- a magazine, a website) and its children (the specific cited item — IPDB page #5235).
-- Exactly two levels today, and `citation_tree_too_deep` asserts it: root resolution
-- here is a single self-join, so a grandchild would silently attribute to the middle
-- node rather than the real root.
--
-- "What citation root sources exist?" is the question this layer exists to make
-- answerable in one query — `FROM citation_roots ORDER BY n_instances DESC`.
-- _citation_parent_chain — each citation source with its parent AND grandparent, so
-- `citation_tree_too_deep` can read a VIEW rather than reaching into `fc` itself. `fc`
-- is attached READ_ONLY and its tables cannot be shadowed, so a check written against
-- them could never be mutation-tested — the one check that could never be proven to
-- fire. Same reasoning as _ce_location_n and _dim_status in catalog.sql.
CREATE OR REPLACE VIEW _citation_parent_chain AS
  SELECT c.id AS citation_source_id, c.parent_id, p.parent_id AS grandparent_id
  FROM fc.citation_citationsource c
  LEFT JOIN fc.citation_citationsource p ON p.id = c.parent_id;

CREATE OR REPLACE VIEW _citation_root_domains AS
  SELECT source_id, list_sort(list(host)) AS root_domains
  FROM fc.citation_citationsourcerootdomain
  GROUP BY source_id;

-- citation_sources — every citation source, root and child alike, with its root
-- resolved. A root resolves to itself, which is what lets a consumer group by
-- root_citation_source_id without special-casing.
--
--   year / month / day : a PRECISION LADDER, not three independent columns. The DB
--             enforces the chain (`citation_citationsource_month_requires_year` and
--             `..._day_requires_month`), so a NULL month means the source is dated to
--             the YEAR — never that a month went missing from an otherwise full date.
--             That is what licenses `month IS NULL` as a statement about the source
--             rather than about our record of it. `day` holds no value at all today.
--   date_note : the free-text remainder no ladder can hold — 'Published 1974–2018',
--             'First issue May 1991'. Empty string, never NULL. It sits BESIDE the
--             ladder rather than instead of it, so a row with both has an approximate
--             date, not a missing one.
--   THE DATE COLUMNS MEAN DIFFERENT THINGS ON A ROOT AND ON A CHILD, and nothing in
--             the schema separates them. On a child (an issue, an edition) they date
--             the cited ITEM. On a root they date the WORK — for a magazine that is
--             its publication RUN, which is why every populated `date_note` today
--             reads like 'Published September 1974 – late 1990s' and why `year` on a
--             magazine root is a founding year, not an issue year. Averaging or
--             range-testing `year` across both grains silently mixes the two: filter
--             on `is_root` first, and take the run's real endpoints from `date_note`,
--             which is the only column that carries the end.
CREATE OR REPLACE VIEW citation_sources AS
  SELECT
    c.id                                      AS citation_source_id,
    c.name                                    AS citation_source_name,
    c.source_type                             AS citation_source_type,
    coalesce(c.parent_id, c.id)               AS root_citation_source_id,
    coalesce(r.name, c.name)                  AS root_citation_source_name,
    c.parent_id IS NULL                       AS is_root,
    c.author, c.publisher,
    c.year, c.month, c.day, c.date_note,
    c.isbn,
    c.identifier_key                          AS identifier_key,
    c.identifier                              AS identifier,
    -- The root's stable key, resolved the same way its name and slug are. A child
    -- normally repeats its root's key, but reading it off the ROOT is what makes
    -- `root_identifier_key = 'ipdb'` a claim about the WORK rather than about one cited
    -- item, and it keeps the root_* family complete: carrying the root's display name
    -- but not its stable key pushes consumers onto the name or onto a type proxy.
    coalesce(r.identifier_key, c.identifier_key) AS root_identifier_key,
    -- Authored cite handle, present exactly on slug-addressed types (magazine).
    -- root_citation_source_slug reassembles the patch cite ref: a child's
    -- '<root_slug>:<slug>' (billboard:1945-09-29). The read path the flippatch
    -- issue-normalizing utility queries.
    c.slug                                    AS slug,
    coalesce(r.slug, c.slug)                  AS root_citation_source_slug
  FROM fc.citation_citationsource c
  LEFT JOIN fc.citation_citationsource r ON r.id = c.parent_id;
COMMENT ON VIEW citation_sources IS
  'One row per CITATION SOURCE (external evidence), root and child alike, with its root resolved — a root resolves to itself. slug/root_citation_source_slug are the authored cite handles on slug-addressed (magazine) rows, null elsewhere. year/month/day is a precision ladder that dates the WORK on a root and the cited ITEM on a child. Not to be confused with ingest_sources (who asserted the fact).';

-- citation_instances — one row per CitationInstance: a specific act of citing, with a
-- `locator` (a page number, a timestamp) narrowing the work. Both the immediate citation
-- source and its root are carried, because a consumer almost always wants to group by
-- the root while displaying the child.
--
-- `quote` is the verbatim source text the citing claim rests on — empty string, never
-- NULL, when none was recorded. It is here because the evidence question a consumer
-- actually asks is "what did the source SAY", and answering it from `locator` alone is
-- impossible: a locator narrows the work, the quote is the work's own words. Flippatch's
-- citation campaigns were reading `fc.provenance_citationinstance` directly to get it,
-- which is the documented promotion signal in EDITING.md. Note the quote belongs to the
-- CITING ACT, not to the source: two claims citing the same page carry two instances
-- with two quotes, which is why it lives here and not on `citation_sources`.
--
-- `root_identifier_key` / `root_citation_source_slug` are the STABLE handles on the work
-- being cited, and they are here so that "which work is this instance citing?" needs no
-- second join. Without them the honest filter is unreachable from an instance and
-- consumers reach for `citation_source_type` instead — which is a shape, not an identity:
-- filtering IPDB's instances as `citation_source_type = 'web'` also picks up every other
-- web-rooted work, about a third of the web-typed rows in the patch corpus. Non-keyed
-- roots (a book, most magazines) carry '', not NULL, exactly as on `citation_sources`.
CREATE OR REPLACE VIEW citation_instances AS
  SELECT
    ci.id                             AS citation_instance_id,
    ci.slug                           AS citation_instance_slug,
    ci.locator                        AS locator,
    ci.quote                          AS quote,
    s.citation_source_id              AS citation_source_id,
    s.citation_source_name            AS citation_source_name,
    s.root_citation_source_id         AS root_citation_source_id,
    s.root_citation_source_name       AS root_citation_source_name,
    s.root_identifier_key             AS root_identifier_key,
    s.root_citation_source_slug       AS root_citation_source_slug,
    s.citation_source_type            AS citation_source_type,
    ci.created_at                     AS created_at
  FROM fc.provenance_citationinstance ci
  JOIN citation_sources s ON s.citation_source_id = ci.citation_source_id;
COMMENT ON VIEW citation_instances IS
  'One row per citation instance — a specific act of citing, with its locator (page, timestamp) and the verbatim quote it rests on, plus both the immediate and the ROOT citation source, including the root stable key/slug to filter on.';

-- claim_citations — the (claim, citation instance) bridge, M2M in both directions.
-- ~2% of claims have a row here: an ABSENT row means "no external evidence recorded",
-- NOT "unattributed". The ingest source on `claims` is the attribution.
CREATE OR REPLACE VIEW claim_citations AS
  SELECT claim_id, citation_instance_id
  FROM fc.provenance_claimcitationinstance;
COMMENT ON VIEW claim_citations IS
  'One row per (claim, citation instance) — the evidence bridge. Most claims have no row: that means no external evidence was recorded, NOT that the claim is unattributed.';

-- citation_roots — the vocabulary shape over the roots alone: one row per WORK, with
-- its registered root domains and its usage. This is the discovery view — the thing to
-- read before writing anything that filters on a citation source.
--   root_domains : the hosts registered to this work (ipdb.org, opdb.org, …), for
--             matching a bare URL back to the work that owns it. Empty for a book.
--   n_instances : CitationInstances hung off this work or any of its children.
--   n_cited_claims : distinct claims those instances cite. Lower than n_instances
--             whenever one instance is reused, and 0 for a work cited nowhere yet.
--   root_identifier_key / root_citation_source_slug : the work's two stable handles,
--             carrying the same names they carry on `citation_sources` and
--             `citation_instances`. The row IS the root here, so the prefix is
--             redundant on its face — it is kept because the alternative is a
--             consumer joining three views on root identity and finding the column
--             renamed under it on one of them. `root_identifier_key` was spelled bare
--             `identifier_key` until the family was completed; nothing consumed it.
--             `root_citation_source_slug` was absent entirely, and flippatch's
--             print-citations campaign documents reading `citation_sources` filtered
--             to roots instead — the promotion signal EDITING.md names, now closed.
CREATE OR REPLACE VIEW citation_roots AS
  SELECT
    s.citation_source_id                      AS root_citation_source_id,
    s.citation_source_name                    AS root_citation_source_name,
    s.citation_source_type                    AS citation_source_type,
    s.identifier_key                          AS root_identifier_key,
    s.slug                                    AS root_citation_source_slug,
    coalesce(d.root_domains, []::VARCHAR[])   AS root_domains,
    count(DISTINCT ch.citation_source_id) FILTER (NOT ch.is_root) AS n_children,
    count(DISTINCT ci.citation_instance_id)   AS n_instances,
    count(DISTINCT cc.claim_id)               AS n_cited_claims
  FROM citation_sources s
  LEFT JOIN _citation_root_domains d ON d.source_id = s.citation_source_id
  LEFT JOIN citation_sources ch      ON ch.root_citation_source_id = s.citation_source_id
  LEFT JOIN citation_instances ci    ON ci.root_citation_source_id = s.citation_source_id
  LEFT JOIN claim_citations cc       ON cc.citation_instance_id = ci.citation_instance_id
  WHERE s.is_root
  GROUP BY ALL;
COMMENT ON VIEW citation_roots IS
  'One row per ROOT citation source (the work — a book, a magazine, a website) with its registered root_domains and usage counts. Reach for it when the subject is what evidence exists rather than what a claim cites.';

-- ─── Recognizing a host: which work does this URL belong to? ────────────────
-- citation_roots.root_domains carries the hosts as a LIST, which displays well and
-- tests membership, but consumers JOIN and COMPARE on a host — matching a scraped URL
-- back to the work that owns it is the whole point of the table. That is the same
-- argument theme_aliases makes for being its own grain rather than a list column, so
-- the hosts get a grain view too, plus the mechanics for matching them.
--
-- THE MATCH IS A LONGEST LABEL-BOUNDARY SUFFIX, NOT AN EQUALITY. This is the trap: a
-- stored host can sit UNDER another stored host, and two do today —
--   twip.kineticist.com   under kineticist.com   (This Week in Pinball vs Kineticist)
--   en.ilsole24ore.com    under ilsole24ore.com
-- so `list_contains(root_domains, h)` misses every subdomain, and a plain
-- `h LIKE '%' || host` gets two things wrong at once: it attributes
-- twip.kineticist.com to BOTH works with no way to choose, and it matches
-- evil-american-pinball.com to american-pinball.com because the boundary isn't a label.
-- The backend implements the real rule in apps/citation/hosts.py (normalize_host +
-- label_suffixes + longest_suffix_match); these macros mirror it, because a hand-rolled
-- copy in each analysis silently misattributes rather than erroring.

-- host_norm — mirrors hosts.normalize_host: lowercase, trim, drop a trailing FQDN dot,
-- then strip EVERY leading `www.` label. All of them, so the result can't shadow the
-- bare domain (a single strip leaves www.foo.com, a different stored host). Whole
-- labels only — `wwworld.example.com` keeps its first label.
CREATE OR REPLACE MACRO host_norm(h) AS
  regexp_replace(regexp_replace(lower(trim(h)), '\.+$', ''), '^(www\.)+', '');
COMMENT ON MACRO host_norm IS
  'Normalize a host for citation recognition: lowercase, drop a trailing FQDN dot, strip every leading www. label. Call it on a bare host; url_host() applies it to a URL.';

-- url_host — the authority of a URL, normalized. The backend takes a host and leaves
-- URL parsing to its callers (urlparse), but an analysis almost always starts from a
-- URL — pinexplore's web-scrape cache, a CitationSourceLink — so the parse lives here
-- rather than being re-derived. Strips scheme, any userinfo, path/query/fragment and a
-- :port. Returns '' for something with no recognizable authority.
CREATE OR REPLACE MACRO url_host(u) AS
  host_norm(regexp_extract(coalesce(u, ''), '^(?:[a-z][a-z0-9+.-]*:)?//(?:[^/@]*@)?([^/?#:]*)', 1));
COMMENT ON MACRO url_host IS
  'A URL authority as a normalized host — scheme, userinfo, port, path, query and fragment removed. Empty string when there is no // authority to read, rather than a guessed host.';

-- citation_root_domains — one row per (root citation source, registered host). The
-- grain twin of citation_roots.root_domains: predicate and join on `host`. Carries the
-- full root_* family, so recognizing a URL lands on the work's stable key in one step
-- rather than on an id needing a second join — `root_family_incomplete` enforces that.
CREATE OR REPLACE VIEW citation_root_domains AS
  SELECT
    rd.source_id      AS root_citation_source_id,
    s.citation_source_name AS root_citation_source_name,
    s.slug            AS root_citation_source_slug,
    s.identifier_key  AS root_identifier_key,
    rd.host           AS host
  FROM fc.citation_citationsourcerootdomain rd
  JOIN citation_sources s ON s.citation_source_id = rd.source_id;
COMMENT ON VIEW citation_root_domains IS
  'One row per (root citation source, registered host) — the grain twin of citation_roots.root_domains, for joining a URL back to its work. Match with citation_root_for_host(), NOT equality: the rule is longest label-boundary suffix.';

-- citation_root_for_host — the recognition entry point: the root citation source id
-- owning this host, or NULL. Mirrors hosts.longest_suffix_match.
--   `= d.host`                      the host itself is a registered root
--   `ends_with(h, '.' || d.host)`   it is a SUBdomain of one — the leading dot is the
--                                   label boundary, which is what excludes
--                                   evil-american-pinball.com
--   ORDER BY length DESC LIMIT 1    most-specific wins, so twip.kineticist.com resolves
--                                   to This Week in Pinball and not to Kineticist
-- Takes a host; wrap a URL in url_host() first. Normalizes its argument, so a raw
-- `www.IPDB.org` matches — the stored side is already normalized by the model's clean().
CREATE OR REPLACE MACRO citation_root_for_host(h) AS (
  SELECT d.root_citation_source_id
  FROM citation_root_domains d
  WHERE host_norm(h) = d.host
     OR ends_with(host_norm(h), '.' || d.host)
  ORDER BY length(d.host) DESC
  LIMIT 1
);
COMMENT ON MACRO citation_root_for_host IS
  'The root citation source id owning this host, else NULL. Longest label-boundary suffix, so the most specific registered host wins and a lookalike domain matches nothing. Wrap a URL in url_host() first.';



-- provenance_context — the watermark for this layer, printed alongside analysis_context
-- by every run (the runner discovers public *_context views by name).
--
-- IT IS NOT THE WHOLE PROVENANCE WATERMARK. `latest_patch`, `patch_fingerprint` and
-- `latest_changeset` are provenance facts that live in `analysis_context` in
-- catalog.sql, and they stay there: that view is the REPRODUCIBILITY watermark, and
-- telling "same query, newer catalog" from a broken reproduction needs the patch and
-- changeset point in the same row as the schema point. Splitting it to group by topic
-- would break every consumer that records the watermark and buy nothing at runtime,
-- since both views print together above every result. This layer's counts are here;
-- the run's position in patch and changeset history is there.
CREATE OR REPLACE VIEW provenance_context AS
  SELECT
    (SELECT count(*) FROM fc.provenance_claim)                  AS claims_total,
    (SELECT count(*) FROM fc.provenance_claim WHERE is_active)  AS claims_active,
    (SELECT count(*) FROM fc.provenance_ingestrun)              AS ingest_runs,
    (SELECT count(*) FROM fc.provenance_source)                 AS ingest_sources,
    (SELECT count(*) FROM citation_roots)                       AS citation_roots,
    (SELECT count(*) FROM fc.provenance_citationinstance)       AS citation_instances;
COMMENT ON VIEW provenance_context IS
  'One row — the provenance watermark: claim totals, ingest run and ingest source counts, citation root and instance counts. Printed by every analysis run.';
