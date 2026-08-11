-- Data patch analysis foundation — the patch lens on claims, changesets and citations.
--
-- `.read` by catalog.sql at its tail, after provenance.sql, whose `claims`, `changesets`
-- and `citation_instances` it is built from. It reads no other source: everything here
-- is a projection of what a patch already wrote into THIS database.
--
-- WHAT THIS ANSWERS. provenance.sql answers "who said so" for every actor alike. This
-- file narrows to one of them — the data patches authored in the sister flippatch repo —
-- because a patch is the only actor whose assertions are also an editable artifact. That
-- makes a second question worth asking of it and of nothing else: not just what does the
-- catalog say, but WHICH BLOCK OF WHICH FILE said it, and what evidence did that block
-- record. `patch_entries` is where that lands.
--
-- ─── Three ways to misread this layer ──────────────────────────────────────
--
-- 1. NOTHING HERE IS LIVE- OR RANK-FILTERED. `patch_claims` carries superseded and
--    retracted claims (`is_active`), claims that lost the winner-pick (`rank`), and
--    claims about soft-deleted subjects (`model_status`). All are deliberate — what a
--    patch asserted is history, and history does not stop being true when it stops
--    winning — but all are silent if you do not predicate on them.
--
-- 2. A MEMBER CLAIM MAY BE A TOMBSTONE. Membership claims are a large share of what
--    patches write, and `member_exists = FALSE` means the patch asserted the member is
--    ABSENT. Count those as assertions and you report the exact opposite of the recorded
--    fact.
--
-- 3. A PATCH THAT ASSERTS NOTHING IS STILL A PATCH. One that only declares citation or
--    website roots writes no claim, no changeset AT ALL, and appears in none of the claim
--    views NOR in `patch_entries` — five such source-only patches have run successfully
--    and none reach the entry grain. One that only retracts appears solely in
--    `patch_retractions`. Both are healthy states. So enumerating APPLIED patches starts
--    from the ingest ledger — `ingest_runs` where `patch_id` is set AND status='success'
--    (only successful runs are unique per patch_id; patch_id alone also counts failed and
--    re-run attempts). The ONLY complete roster. Not `changesets`: a source-only patch has
--    none. Not `patch_entries`: it is changeset-backed, so it holds effectful CLAIM
--    entries, not patches. Not `patch_claims`: that misses retraction-only and source-only
--    patches both.

-- ── Deriving a patch number ──────────────────────────────────────────────────
-- A patch id is the flippatch filename stem, `NNNN-slug`, and `ingest_patches` stores it
-- verbatim — so the ordinal is a string parse, not a stored column.
--
-- It exists so an OPERATOR-SUPPLIED cutoff can be applied ad hoc — `WHERE patch_number >
-- N` when someone has told you which patches are yours to change. Nothing here stores,
-- derives or guesses such a cutoff: which patches may be edited is not a fact this
-- database holds, and an analysis that decides it for itself is deciding it wrongly.
--
-- TRY_CAST, not CAST, and the difference is not stylistic: a plain CAST of a failed
-- `regexp_extract` casts '' and raises `Conversion Error: Could not convert string '' to
-- INT32`, taking down every analysis that reads this layer over one malformed id, with an
-- error naming neither the id nor the reason. NULL is the honest answer for an id that
-- does not carry an ordinal.
--
-- `[0-9]+` anchored to the SEPARATOR, not `[0-9]{4}`. Four is the width flippatch writes
-- today, and pinning it there is the one failure mode worse than the crash above: a
-- five-digit id parses to its first four digits, so `12345-slug` reads as 1234 and an
-- operator's `WHERE patch_number > N` cutoff silently admits or excludes the wrong
-- patches — no error, no NULL, just a wrong ordinal that looks like a right one. The
-- trailing `-` is what keeps the greedy `+` honest: it stops at the separator the id
-- format guarantees rather than swallowing digits out of the slug.
CREATE OR REPLACE MACRO patch_number_of(pid) AS
  TRY_CAST(regexp_extract(pid, '^([0-9]+)-', 1) AS INTEGER);
COMMENT ON MACRO patch_number_of IS
  'The leading NNNN ordinal of a patch id, as an INTEGER — NULL for an id that carries none. TRY_CAST, so one malformed id yields NULL rather than failing every query that reads this layer.';

-- ── What patches asserted ────────────────────────────────────────────────────
-- One row per claim an ingested patch wrote.
--
-- TWO SUBJECT SPELLINGS. `subject_public_id`/`subject_name`/`subject_status` come down from
-- `claims` and are populated for every subject type; `model_slug`/`model_status` are the
-- machinemodel projection of them and NULL on every other row. That narrowing is the
-- column's meaning: it is what lets `WHERE model_slug = …` join against a model without
-- admitting a Title that shares the slug. Use the subject_* set for anything else.
--
-- The status columns ride along because neither view is live-filtered, and a slug handed
-- back with no signal that its record is retired is the "right data, read the wrong way"
-- failure the liveness contract exists to prevent.
--
-- `changeset_action` is deliberately ABSENT. It looks like the patch operation and is
-- not: `provenance_changeset_action_iff_interactive` makes it non-null exactly when there
-- is no ingest run, so it is empty on every row a patch ever wrote, while its vocabulary
-- overlaps the patch file's (`retract`, `delete`). Use `patch_retractions`.
CREATE OR REPLACE VIEW patch_claims AS
  SELECT
    c.patch_id,
    patch_number_of(c.patch_id)                     AS patch_number,
    c.changeset_id,
    c.claim_id,
    c.subject_type,
    c.subject_id,
    c.subject_public_id,
    c.subject_name,
    c.subject_status,
    CASE WHEN c.subject_type = 'catalog.machinemodel' THEN c.subject_public_id END AS model_slug,
    CASE WHEN c.subject_type = 'catalog.machinemodel' THEN c.subject_status END AS model_status,
    c.field_name,
    c.claim_key,
    c.register,
    c.is_member,
    c.member_exists,
    c.value,
    c.ref_id,
    c.rank,
    c.is_active,
    c.retracted_by_patch_id,
    c.ingest_source_slug,
    c.created_at
  FROM claims c
  WHERE c.patch_id IS NOT NULL;
COMMENT ON VIEW patch_claims IS
  'One row per claim written by an ingested data patch — patch, changeset, the resolved subject (subject_public_id/name/status for any type; model_slug/model_status only for machinemodel) and the claim itself. Neither live- nor rank-filtered, and member_exists=false is a tombstone.';

-- ── What patches killed ──────────────────────────────────────────────────────
-- One row per claim a patch DEACTIVATED, which `patch_claims` cannot show: a retraction
-- writes no new claim, it flips `is_active` on an existing one and stamps the retracting
-- changeset. So the retracted claim's own `patch_id` names whoever ASSERTED it — often an
-- ingest source and no patch at all — and the patch that did the retracting appears
-- nowhere in that column.
--
-- `patch_id` here is the RETRACTING patch, to match every other view; the patch that
-- originally asserted the claim is `asserted_by_patch_id`, NULL when it was not a patch.
CREATE OR REPLACE VIEW patch_retractions AS
  SELECT
    c.retracted_by_patch_id                         AS patch_id,
    patch_number_of(c.retracted_by_patch_id)        AS patch_number,
    c.retracted_by_changeset_id                     AS changeset_id,
    c.claim_id,
    c.subject_type,
    c.subject_id,
    c.subject_public_id,
    c.subject_name,
    c.subject_status,
    CASE WHEN c.subject_type = 'catalog.machinemodel' THEN c.subject_public_id END AS model_slug,
    CASE WHEN c.subject_type = 'catalog.machinemodel' THEN c.subject_status END AS model_status,
    c.field_name,
    c.claim_key,
    c.register,
    c.is_member,
    c.member_exists,
    c.value,
    c.ref_id,
    c.patch_id          AS asserted_by_patch_id,
    c.ingest_source_slug,
    c.created_at        AS asserted_at
  FROM claims c
  WHERE c.retracted_by_patch_id IS NOT NULL;
COMMENT ON VIEW patch_retractions IS
  'One row per claim deactivated by a data patch — patch_id is the RETRACTING patch, asserted_by_patch_id whoever wrote the claim originally. The only claim view in which a retraction-only patch appears.';

-- ── The FIELD-level evidence each claim recorded ─────────────────────────────
-- One row per (claim, citation instance) reached through the `ClaimCitationInstance`
-- bridge. A claim with no such evidence does not appear — that is the M2M bridge's own
-- grain, and `patch_claims` is where you go for the claim regardless. `quote` is the
-- verbatim text the citing act rests on, empty string (never NULL) when none was
-- recorded; a citing act without a quote is a normal state.
--
-- FIELD-LEVEL, and the word is load-bearing: a CitationInstance is reachable two ways
-- (apps/citation/models.py), and this view sees only one. A scalar/edit claim attaches
-- its evidence through the bridge — that is what this JOIN traverses. But an INLINE
-- citation, the `[[cite:id:N]]` marker embedded in a description's own text, reaches its
-- instance through the marker alone and writes NO bridge row, so it is invisible here.
-- That is not a rare corner: 177 patch-written description claims across 19 patches
-- carry an inline marker today, and 352 citation instances have no bridge row at all. A
-- consumer that reads "no row in patch_cites" as "this claim is uncited" is wrong for
-- every inline-only description — do not drive an add-a-citation decision off absence
-- here. An inline grain is unbuilt (no consumer has needed one); parse the marker out of
-- `patch_claims.value` if you do.
--
-- The pairing of quote to claim is the point of this view. "This model is mentioned in a
-- patch" and "THIS claim's own field evidence says X" are different questions: a patch
-- entry may quote one sentence of a source while an adjacent sentence carries something
-- else entirely, and only the second question licenses attaching a new citation to that
-- claim.
--
-- Filter works on `root_identifier_key`, never on `citation_source_type`: the type is a
-- SHAPE, not an identity, so `= 'web'` as a proxy for "the IPDB cite" also admits every
-- other web-rooted work.
CREATE OR REPLACE VIEW patch_cites AS
  SELECT
    pc.patch_id,
    pc.patch_number,
    pc.changeset_id,
    pc.claim_id,
    pc.subject_type,
    pc.subject_id,
    pc.subject_public_id,
    pc.subject_name,
    pc.subject_status,
    pc.model_slug,
    pc.model_status,
    pc.field_name,
    pc.claim_key,
    pc.value,
    pc.ref_id,
    pc.is_active,
    pc.rank,
    ci.citation_instance_id,
    ci.quote,
    ci.locator,
    ci.citation_source_id,
    ci.citation_source_name,
    ci.citation_source_type,
    ci.root_citation_source_id,
    ci.root_citation_source_name,
    ci.root_identifier_key,
    ci.root_citation_source_slug
  FROM patch_claims pc
  JOIN claim_citations cc USING (claim_id)
  JOIN citation_instances ci USING (citation_instance_id);
COMMENT ON VIEW patch_cites IS
  'One row per (patch claim, FIELD-level citation instance) via the ClaimCitationInstance bridge — the claim plus its verbatim quote, locator and source. Inline [[cite:id:N]] citations in a description write no bridge row and are ABSENT; absence here is not "uncited". Filter on root_identifier_key, not citation_source_type.';

-- _patch_acts — every act a patch changeset performed, asserting and retracting alike,
-- flattened to one grain so `patch_entries` can reach for an entry's subject and field
-- lists in one pass. Private: the two halves are separately available above, and this
-- shape exists to be aggregated rather than read.
--
-- `patch_entry_spans_subjects` scans exactly this. A guard that reads a narrower population
-- than the thing it guards reports healthy for the case it exists to catch.
CREATE OR REPLACE VIEW _patch_acts AS
  SELECT patch_id, changeset_id, subject_type, subject_id,
         subject_public_id, subject_name, subject_status, model_slug, model_status,
         field_name, 'assert' AS act
  FROM patch_claims
  UNION ALL
  SELECT patch_id, changeset_id, subject_type, subject_id,
         subject_public_id, subject_name, subject_status, model_slug, model_status,
         field_name, 'retract'
  FROM patch_retractions;

-- ── The unit an author edits ─────────────────────────────────────────────────
-- One row per effectful authored ChangeSet — `changesets` narrowed to the patch ones.
-- A ChangeSet is what an author writes as one attributed block: either a flat entry
-- (`- entity.public-id:` with the body directly under it) or one item of a grouped
-- `changesets:` list under a shared header. So one header can produce SEVERAL rows here,
-- one per item, and the subject is any entity's public-id, not only a model slug. What
-- keeps each ChangeSet single-fielded-per-claim is the disjoint-fields rule (the same
-- field cannot appear in two items of one record); DIFFERENT fields split across items
-- on purpose, which is the whole point of the grouped form.
--
-- Driven from `changesets` rather than aggregated up from the claims, because a patch
-- entry that only retracts writes no claim and would vanish from anything built bottom-up
-- — along with every patch composed entirely of such entries. The counts come from the
-- base view for the same reason.
--
-- Subject arrives through `any_value` rather than the GROUP BY on purpose: grouping by it
-- would split a changeset that ever spanned two subjects into two rows, quietly halving
-- the blast radius of a citation, which is the one thing this view exists to state
-- correctly. `patch_entry_spans_subjects` asserts the assumption out loud instead.
--
-- ONE SUBJECT PER PATCH CHANGESET is an assumption, and here is why it holds. A patch CAN
-- write a multi-subject changeset — DataPatches.md documents that `delete:` cascades
-- status=deleted to the deleted entity's lifecycle children in a single ChangeSet (a
-- Title delete carries it for the Title and each of its Models). It is a supported
-- feature, not something the format forbids. What holds the assumption is an AUTHORING
-- policy, not a system guard: we do not author cascade deletes in data patches (they are
-- done in the app), so no patch ChangeSet has ever spanned subjects, and none is
-- expected to. `patch_entry_spans_subjects` is the sentinel on that policy: if it ever
-- fires, a patch cascade-deleted after all and `any_value` is now picking one of several
-- real subjects — the entry grain needs rethinking, and the check firing is the correct
-- signal, not a false positive to suppress.
--
-- The CONVERSE — a subject a patch asserted about, later soft-deleted in the app — is
-- not this problem and is handled elsewhere: these views are deliberately not
-- live-filtered (a patch's assertion is history) and carry `model_status`, so the entry
-- stays visible with its subject flagged deleted. The delete is a different changeset;
-- it does not join back into this one.
--
-- Aggregating to this grain is what keeps a rewrite honest: a citation added to an entry
-- attaches to EVERY claim in it, so the entry — not the claim, and certainly not the
-- model — is the unit a decision is made about.
CREATE OR REPLACE VIEW patch_entries AS
  WITH acts AS (
    SELECT
      changeset_id,
      any_value(subject_type)                                   AS subject_type,
      any_value(subject_id)                                     AS subject_id,
      any_value(subject_public_id)                                   AS subject_public_id,
      any_value(subject_name)                                   AS subject_name,
      any_value(subject_status)                                 AS subject_status,
      any_value(model_slug)                                     AS model_slug,
      any_value(model_status)                                   AS model_status,
      -- Split rather than one merged list: merged, they equate asserting a field with
      -- removing it, the one distinction a rewrite decision turns on.
      string_agg(DISTINCT field_name, ', ' ORDER BY field_name)
        FILTER (act = 'assert')                                 AS asserted_fields,
      string_agg(DISTINCT field_name, ', ' ORDER BY field_name)
        FILTER (act = 'retract')                                AS retracted_fields
    FROM _patch_acts
    GROUP BY changeset_id
  )
  SELECT
    cs.patch_id,
    patch_number_of(cs.patch_id)      AS patch_number,
    cs.changeset_id,
    a.subject_type,
    a.subject_id,
    a.subject_public_id,
    a.subject_name,
    a.subject_status,
    a.model_slug,
    a.model_status,
    cs.n_claims,
    cs.n_retracted                    AS n_retractions,
    a.asserted_fields,
    a.retracted_fields,
    cs.created_at
  FROM changesets cs
  LEFT JOIN acts a USING (changeset_id)
  WHERE cs.patch_id IS NOT NULL;
COMMENT ON VIEW patch_entries IS
  'One row per effectful authored ChangeSet — a flat entry or one grouped changesets: item, any entity as subject — with its subject resolved to subject_public_id/subject_name, asserted and retracted claim counts, and their two separate field lists. The unit a citation attaches to, since a cite reaches every claim in its entry.';

-- ── An entry and the FIELD-level evidence it already carries ──────────────────
-- One row per (entry, citation instance): the grain a rewrite is decided at, since the
-- question "may this entry carry a new reference?" is answered by the entry's OWN
-- recorded quote. Aggregated here rather than left to each consumer because doing it by
-- hand invites collapsing an entry's evidence with `any_value`: an entry may carry
-- several distinct citation instances, and picking one arbitrarily can report a quote
-- other than the one that satisfied the consumer's own test.
--
-- Built on `patch_cites`, so it inherits that view's field-level limit: an entry whose
-- only evidence is an inline `[[cite:id:N]]` in a description carries no bridge row and
-- appears here with NO citation. An entry absent from this view is not an uncited entry.
--
-- This is where the two subject spellings `patch_claims` documents diverge most: an
-- entry's subject is any entity's public-id, so `model_slug` is NULL for every entry
-- about a person, theme or location. Read `subject_public_id`/`subject_name`.
--
-- The status columns ride along for the reason they do on `patch_claims`, and it matters
-- MORE here: this is the grain a rewrite is decided at, so a slug handed over with no
-- signal that the record is retired is not a misreading waiting to happen, it is a patch
-- waiting to be authored against a soft-deleted record. One entry in the corpus is in
-- exactly that state today.
CREATE OR REPLACE VIEW patch_entry_cites AS
  SELECT
    patch_id,
    any_value(patch_number)                 AS patch_number,
    changeset_id,
    any_value(subject_type)                 AS subject_type,
    any_value(subject_id)                   AS subject_id,
    any_value(subject_public_id)                 AS subject_public_id,
    any_value(subject_name)                 AS subject_name,
    any_value(subject_status)               AS subject_status,
    any_value(model_slug)                   AS model_slug,
    any_value(model_status)                 AS model_status,
    citation_instance_id,
    any_value(quote)                        AS quote,
    any_value(locator)                      AS locator,
    any_value(citation_source_id)           AS citation_source_id,
    any_value(citation_source_name)         AS citation_source_name,
    any_value(citation_source_type)         AS citation_source_type,
    any_value(root_citation_source_id)      AS root_citation_source_id,
    any_value(root_citation_source_name)    AS root_citation_source_name,
    any_value(root_identifier_key)          AS root_identifier_key,
    any_value(root_citation_source_slug)    AS root_citation_source_slug,
    count(DISTINCT claim_id)                AS n_cited_claims,
    string_agg(DISTINCT field_name, ', ' ORDER BY field_name) AS fields
  FROM patch_cites
  GROUP BY patch_id, changeset_id, citation_instance_id;
COMMENT ON VIEW patch_entry_cites IS
  'One row per (patch entry, FIELD-level citation instance) — the entry plus one piece of bridged evidence it records, its subject resolved to subject_public_id/subject_name whatever its type, and the claims it covers. Inherits patch_cites''s limit: inline [[cite:id:N]] evidence is absent, so an entry missing here is not uncited. The grain a citation rewrite is decided at.';
