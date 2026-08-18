-- Provenance self-test — the invariants for provenance.sql.
--
-- Not a standalone analysis: catalog_checks.sql `.read`s this and folds
-- `_provenance_checks` into `foundation_checks`, so there is ONE gate and one mutation
-- harness entry point. Private (`_` prefix) for that reason — a public `*_checks` view
-- would ALSO be discovered by the runner's sweep and every failure would report twice.
--
-- Same contract as the rest of the self-test: a row means something broke, empty means
-- healthy, and every check_name here needs a line in catalog_mutations.tsv proving it
-- fires. Same house rule too: compare with IS DISTINCT FROM, never <>, and null-test
-- operands before any ordering operator — a NULL comparison is how a check silently
-- becomes a no-op.
--
-- Three classes, and the first is the one that carries the file:
--
--   AGREEMENT   the ranking in provenance.sql reproduces what the real resolver
--               (apps/catalog/resolve/*) actually materialized. This is the price of
--               reimplementing the winner-pick in SQL, and it is what makes that
--               reimplementation defensible rather than a second source of truth
--               quietly drifting from the first. Three registers are compared, chosen
--               to cover both shapes: two membership sets (gameplay_feature, theme) and
--               one scalar (year). ~34k resolved rows, all three exact today.
--               If one of these fires, the SQL is wrong and the catalog is right.
--   CLASSIFIER  the structural member/scalar split the register logic rests on.
--   VOCABULARY  closed enum domains, asserted rather than assumed — the same reasoning
--               as status_unknown in catalog_checks.sql.

-- _changeset_action — every changeset's action AS STORED, at full changeset grain.
-- Check-only scaffolding, because no public view carries both halves a vocabulary check
-- needs. `claims` holds the raw value but names only changesets that WROTE a claim, so
-- the retraction-only ones are outside it entirely — the population `changesets` exists
-- to reach. `changesets` is that complete grain but reads through _blanks_null, which
-- folds a stored '' onto the NULL that legitimately marks an ingest changeset, making
-- the defect indistinguishable from the healthy shape.
-- A VIEW and not a read of `fc`, so check-mutations can break it: `fc` is attached
-- READ_ONLY and its tables cannot be shadowed. Same reasoning as _citation_parent_chain.
CREATE OR REPLACE VIEW _changeset_action AS
  SELECT id AS changeset_id, action FROM fc.provenance_changeset;

CREATE OR REPLACE VIEW _provenance_checks AS
  -- `claims` decoded ONCE for the branches below, on foundation_checks' reasoning and
  -- with its shadowing trick — DuckDB re-evaluates a view per REFERENCE, and this is the
  -- widest decode in the layer.
  WITH claims AS MATERIALIZED (SELECT * FROM main.claims)

  -- ─── AGREEMENT ───────────────────────────────────────────────────────────
  -- Membership: the set of top-ranked, non-tombstoned member claims must equal the set
  -- of through-rows the resolver wrote. FULL OUTER on both keys so BOTH directions are
  -- reported — a claim that should have materialized and didn't, and a through-row with
  -- no claim behind it — from one scan. The side that is NULL names the direction.
  --
  -- Both sides are restricted to LIVE models, because model_gameplay_features is
  -- (`claims` is not), and comparing across that filter would report every claim on a
  -- soft-deleted model as a phantom disagreement.
  SELECT 'gameplay_feature_resolution_disagrees' AS check_name,
         'model_id=' || coalesce(r.model_id, c.model_id)::VARCHAR
           || ' feature_id=' || coalesce(r.feature_id, c.ref_id)::VARCHAR
           || ' missing_from=' || CASE WHEN r.model_id IS NULL THEN 'catalog'
                                       ELSE 'ranking' END AS detail
  FROM (SELECT model_id, feature_id FROM model_gameplay_features) r
  FULL OUTER JOIN (
    SELECT model_id, ref_id FROM model_claims
    WHERE field_name = 'gameplay_feature' AND rank = 1 AND member_exists
  ) c ON c.model_id = r.model_id AND c.ref_id = r.feature_id
  WHERE r.model_id IS NULL OR c.model_id IS NULL

  UNION ALL
  SELECT 'theme_resolution_disagrees',
         'model_id=' || coalesce(r.model_id, c.model_id)::VARCHAR
           || ' theme_id=' || coalesce(r.theme_id, c.ref_id)::VARCHAR
           || ' missing_from=' || CASE WHEN r.model_id IS NULL THEN 'catalog'
                                       ELSE 'ranking' END
  FROM (SELECT model_id, theme_id FROM model_themes) r
  FULL OUTER JOIN (
    SELECT model_id, ref_id FROM model_claims
    WHERE field_name = 'theme' AND rank = 1 AND member_exists
  ) c ON c.model_id = r.model_id AND c.ref_id = r.theme_id
  WHERE r.model_id IS NULL OR c.model_id IS NULL

  -- Scalar register: the top-ranked `year` claim must equal the resolved models.year.
  -- Covers the OTHER half of the register split — a membership-only agreement check
  -- would pass even if scalar registers were grouped on entirely the wrong key.
  -- Joined (not FULL OUTER) on models: a model with no year claim at all is not a
  -- disagreement, it is a model nobody has dated.
  UNION ALL
  SELECT 'year_resolution_disagrees',
         'model_id=' || m.id::VARCHAR || ' catalog=' || coalesce(m.year::VARCHAR, 'NULL')
           || ' top_ranked=' || coalesce(w.yr::VARCHAR, 'NULL')
  FROM models m
  JOIN (
    SELECT model_id, try_cast(json_extract_string(value, '$') AS BIGINT) AS yr
    FROM model_claims WHERE field_name = 'year' AND rank = 1
  ) w ON w.model_id = m.id
  WHERE m.year IS DISTINCT FROM w.yr

  -- ─── CLASSIFIER ──────────────────────────────────────────────────────────
  -- The two invariants that license deriving member-vs-scalar from the claim_key
  -- rather than from a registry export. See the register block in provenance.sql.
  --
  -- A member claim's value is always a JSON object — member_exists reads `$.exists` off
  -- it, and a non-object value would read as "present" no matter what it says.
  UNION ALL
  SELECT 'member_claim_nondict_value',
         'claim_id=' || claim_id::VARCHAR || ' claim_key=' || claim_key
  FROM claims
  WHERE is_member AND json_type(value) IS DISTINCT FROM 'OBJECT'

  -- ...and the converse, which is the one that would actually break us: a claim with NO
  -- identity parts carrying an `exists` flag would mean a relationship member whose key
  -- has no parts, so the `|` test would misfile it as a scalar and its tombstone would
  -- be ignored. claim_presence.py documents that a claim-controlled JSON scalar may
  -- legitimately be a dict, which is exactly why the VALUE shape can't be the test.
  UNION ALL
  SELECT 'scalar_claim_exists_flag',
         'claim_id=' || claim_id::VARCHAR || ' field_name=' || field_name
  FROM claims
  WHERE NOT is_member AND json_extract_string(value, '$.exists') IS NOT NULL

  -- Exactly one top-ranked claim per (subject, register). row_number() guarantees this
  -- structurally, so a row here means the PARTITION lost a key — the failure mode that
  -- would make every attribution answer plausibly wrong rather than obviously broken.
  UNION ALL
  SELECT 'multiple_top_ranked',
         'subject=' || subject_type || ':' || subject_id::VARCHAR || ' register=' || register
  FROM claims WHERE rank = 1
  GROUP BY subject_type, subject_id, register
  HAVING count(*) > 1

  -- ...and the other half: a partition with eligible claims has a rank 1 AT ALL. This is
  -- the silent direction — too many winners fans a join out, while none makes `rank = 1`
  -- return nothing, which reads as "no claim here" and drops the subject from an
  -- attribution answer. Asserted as DENSITY, not `min(rank) = 1`: ranks come from one
  -- sequence, so whether the hole lands at the front or the middle is an accident of sort.
  UNION ALL
  SELECT 'rank_not_dense',
         'subject=' || subject_type || ':' || subject_id::VARCHAR || ' register=' || register
           || ' ranked=' || count(rank)::VARCHAR || ' max_rank=' || max(rank)::VARCHAR
  FROM claims
  GROUP BY subject_type, subject_id, register
  HAVING count(rank) > 0 AND max(rank) IS DISTINCT FROM count(rank)

  -- A suppressed actor never ranks — that is the kill switch ranked_claims implements
  -- by excluding them, and `rank` is NULL for exactly that reason.
  UNION ALL
  SELECT 'suppressed_actor_ranked', 'claim_id=' || claim_id::VARCHAR
  FROM claims
  WHERE rank IS NOT NULL AND actor_resolution_status = 'suppressed'

  -- ─── Row preservation ────────────────────────────────────────────────────
  -- `claims` inner-joins content type, changeset and actor; `citation_instances` inner-
  -- joins its citation source. An inner join that stops matching DROPS rows silently —
  -- an analysis then reports a smaller, confidently wrong universe. Compare against the
  -- physical tables so a lost row is loud.
  UNION ALL
  SELECT 'claim_rows_dropped',
         'physical=' || (SELECT count(*) FROM fc.provenance_claim)::VARCHAR
           || ' view=' || (SELECT count(*) FROM claims)::VARCHAR
  WHERE (SELECT count(*) FROM fc.provenance_claim) IS DISTINCT FROM (SELECT count(*) FROM claims)

  UNION ALL
  SELECT 'citation_instance_rows_dropped',
         'physical=' || (SELECT count(*) FROM fc.provenance_citationinstance)::VARCHAR
           || ' view=' || (SELECT count(*) FROM citation_instances)::VARCHAR
  WHERE (SELECT count(*) FROM fc.provenance_citationinstance)
        IS DISTINCT FROM (SELECT count(*) FROM citation_instances)

  UNION ALL
  SELECT 'changeset_rows_dropped',
         'physical=' || (SELECT count(*) FROM fc.provenance_changeset)::VARCHAR
           || ' view=' || (SELECT count(*) FROM changesets)::VARCHAR
  WHERE (SELECT count(*) FROM fc.provenance_changeset)
        IS DISTINCT FROM (SELECT count(*) FROM changesets)

  -- ─── Subject resolution ──────────────────────────────────────────────────
  -- Every claim's subject resolves through `entity_subjects`. Both joins in `claims` are
  -- LEFT, so failure costs no rows — it NULLs subject_type and subject_public_id/name/
  -- status, and a consumer gets an anonymous claim rather than an error. Two ways in: a
  -- content type absent from `entity_registry`, and a subject row that no longer exists.
  -- Zero today.
  --
  -- NOT EXISTS, not `subject_public_id IS NULL`: the claim is that the SUBJECT resolves, and
  -- the cheaper spelling stops meaning that as soon as a nullable column joins the set —
  -- `subject_status` already is one.
  --
  -- The fallback names the content type because `entity_registry` has no name for an
  -- unregistered subject. A scalar subquery, so it runs per reported row, not per scan.
  -- A NULL anywhere in the concatenation blanks the whole detail, hence both coalesces.
  UNION ALL
  SELECT 'unresolved_claim_subject',
         'claim_id=' || c.claim_id::VARCHAR
           || ' subject=' || coalesce(
                c.subject_type,
                'UNREGISTERED[' || coalesce((SELECT ct.app_label || '.' || ct.model
                                             FROM fc.provenance_claim pc
                                             JOIN fc.django_content_type ct
                                               ON ct.id = pc.content_type_id
                                             WHERE pc.id = c.claim_id), '?') || ']')
           || ':' || c.subject_id::VARCHAR
  FROM claims c
  WHERE NOT EXISTS (SELECT 1 FROM entity_subjects e
                    WHERE e.subject_type = c.subject_type
                      AND e.subject_id = c.subject_id)

  -- ─── Actors and changesets ───────────────────────────────────────────────
  -- An actor backs an ingest source XOR a user, and `actor_name`/`actor_slug` coalesce
  -- across the two. That coalesce is only safe while the XOR holds: an actor backed by
  -- NEITHER table yields NULL handles that group into one anonymous bucket, and one
  -- backed by BOTH silently prefers the source. Either way attribution goes quietly
  -- wrong rather than loudly missing, which is why the XOR is asserted and not assumed.
  UNION ALL
  SELECT 'actor_backing_unresolved',
         'actor_id=' || actor_id::VARCHAR || ' kind=' || coalesce(actor_kind, 'NULL')
  FROM actors
  WHERE actor_name IS NULL OR actor_slug IS NULL
     OR (ingest_source_slug IS NOT NULL AND username IS NOT NULL)

  -- Source slugs and usernames share one namespace in `actor_slug`. Nothing in the
  -- schema stops a source slugged `moses`, and if one lands, actor_slug stops being a
  -- key: two actors would group as one. Cheap to assert, impossible to notice otherwise.
  UNION ALL
  SELECT 'actor_slug_collision', 'actor_slug=' || actor_slug
  FROM actors
  WHERE actor_slug IS NOT NULL
  GROUP BY actor_slug
  HAVING count(*) > 1

  -- The DB constraint provenance_changeset_action_iff_interactive, restated where an
  -- analysis can see it. It matters because `is_interactive` is what consumers filter
  -- on while `action` is what they display. Absent is NULL, as everywhere in this layer,
  -- so `coalesce` in the detail: concatenating a NULL action yields a NULL detail, and
  -- 34,000 findings that all read NULL name nothing at all.
  UNION ALL
  SELECT 'changeset_action_iff_interactive',
         'changeset_id=' || changeset_id::VARCHAR
           || ' is_interactive=' || is_interactive::VARCHAR
           || ' action=[' || coalesce(action, '<NULL>') || ']'
  FROM changesets
  WHERE is_interactive IS DISTINCT FROM (action IS NOT NULL)

  -- A changeset that neither wrote nor retracted a claim did nothing at all. Zero of
  -- 32,126 today. One would mean a write path recording the grouping record and then
  -- failing to record the work — and because `claims` can't see a changeset with no
  -- claims, it would be invisible everywhere except here.
  UNION ALL
  SELECT 'inert_changeset', 'changeset_id=' || changeset_id::VARCHAR
  FROM changesets
  WHERE n_claims = 0 AND n_retracted = 0

  -- ─── Citation structure ──────────────────────────────────────────────────
  -- The citation source tree is exactly two levels — a root (the work) and its children
  -- (the cited items). citation_sources resolves the root with a SINGLE self-join, so a
  -- grandchild would resolve to the middle node and silently attribute to the wrong
  -- work. Zero grandchildren today; this is what keeps that true.
  UNION ALL
  SELECT 'citation_tree_too_deep',
         'citation_source_id=' || citation_source_id::VARCHAR
           || ' parent_id=' || parent_id::VARCHAR
  FROM _citation_parent_chain
  WHERE grandparent_id IS NOT NULL

  -- A root resolves to itself — what lets a consumer GROUP BY root_citation_source_id
  -- without special-casing roots.
  UNION ALL
  SELECT 'citation_root_not_self', 'citation_source_id=' || citation_source_id::VARCHAR
  FROM citation_sources
  WHERE is_root AND root_citation_source_id IS DISTINCT FROM citation_source_id

  -- A registered recognition host hangs off a ROOT citation source, never off a child.
  -- citation_root_domains names its column root_citation_source_id and citation_roots
  -- aggregates on that basis, so a host on a child would be reported under a work that
  -- does not own it — and citation_root_for_host would hand back an id that
  -- citation_roots has no row for.
  UNION ALL
  SELECT 'root_domain_on_non_root',
         'citation_source_id=' || d.root_citation_source_id::VARCHAR || ' host=' || d.host
  FROM citation_root_domains d
  JOIN citation_sources s ON s.citation_source_id = d.root_citation_source_id
  WHERE NOT s.is_root

  -- A path prefix lives on a shared host ONLY. A prefixed row on an ordinary host (a
  -- validation bypass — clean() refuses to write one) would split a normal site into
  -- path-scoped roots; the recognition macros already refuse to match it, so this is
  -- the visibility half. The inverse — a bare row on a shared host, which would
  -- attribute every tenant's files to one maker — is a data condition rather than a
  -- layer invariant, and the audit's shared-cdn-bare-host rule owns it.
  UNION ALL
  SELECT 'path_scoped_row_on_ordinary_host',
         'host=' || d.host || d.path_prefix || ' root=' || d.root_citation_source_name
  FROM citation_root_domains d
  WHERE d.path_prefix IS DISTINCT FROM '' AND NOT _shared_cdn_host(d.host)

  -- ─── The root_* family travels together ──────────────────────────────────
  -- Any view that identifies a root citation source carries ALL FOUR of the family —
  -- id, name, slug, identifier_key — and this asserts it structurally rather than by
  -- review. The failure it prevents is not a broken query but a confidently wrong one:
  -- a consumer that can reach the root's id and display name but not its stable key
  -- does not go and join, it reaches for `citation_source_type` instead, and filtering
  -- IPDB as type = 'web' silently sweeps in every other web-rooted work. Both holes
  -- this closes were found that way — citation_instances had no key at all, and
  -- citation_roots spelled it `identifier_key`, so a grep for the family name across
  -- the layer returned nothing and read as "the column doesn't exist".
  --
  -- Reads information_schema, like `unanchored_view` above it, and carries the same
  -- assumption: foundation_checks is only ever loaded by the self-test, so `main` holds
  -- the foundation's views and not a consumer's.
  UNION ALL
  SELECT 'root_family_incomplete', v.table_name || ' missing ' || f.col
  FROM (SELECT DISTINCT table_name FROM information_schema.columns
        WHERE table_schema = 'main' AND column_name = 'root_citation_source_id') v
  CROSS JOIN (SELECT unnest(['root_citation_source_name',
                             'root_citation_source_slug',
                             'root_identifier_key']) AS col) f
  WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.columns c
    WHERE c.table_schema = 'main'
      AND c.table_name = v.table_name
      AND c.column_name = f.col)

  -- ─── The Source kill switch has two spellings; they must agree ───────────
  -- `is_enabled` is authored on Source, `resolution_status` is the Actor mirror that
  -- the winner-pick actually reads. They are synced by Source.save(), so a disagreement
  -- means an Actor row written around it — and in that state the catalog resolves one
  -- way while every human-facing surface says the other. Carrying both columns on
  -- ingest_sources is what makes the drift visible at all.
  UNION ALL
  SELECT 'ingest_source_enabled_desyncs',
         'ingest_source_slug=' || ingest_source_slug
           || ' is_enabled=' || is_enabled::VARCHAR
           || ' resolution_status=' || resolution_status
  FROM ingest_sources
  WHERE resolution_status IS DISTINCT FROM
        CASE WHEN is_enabled THEN 'active' ELSE 'suppressed' END

  -- The evidence bridge names a claim and an instance that both exist. A dangling side
  -- would make claim_citations over-report coverage relative to what can be joined.
  UNION ALL
  SELECT 'orphan_claim_citation',
         'claim_id=' || cc.claim_id::VARCHAR
           || ' citation_instance_id=' || cc.citation_instance_id::VARCHAR
  FROM claim_citations cc
  WHERE NOT EXISTS (SELECT 1 FROM claims c WHERE c.claim_id = cc.claim_id)
     OR NOT EXISTS (SELECT 1 FROM citation_instances ci
                    WHERE ci.citation_instance_id = cc.citation_instance_id)

  -- ─── VOCABULARY ──────────────────────────────────────────────────────────
  -- Closed enums, asserted rather than assumed. A new member is a silent behaviour
  -- change everywhere this file branches on one — the same reasoning that makes
  -- status_unknown load-bearing for catalog.sql's liveness spelling. Notably
  -- actor_resolution_status: a third member would join neither the "ranks" nor the
  -- "suppressed" branch, and `rank` would keep looking right.
  --
  -- EACH ONE TESTS FOR ABSENCE SEPARATELY, because the two ways an enum goes wrong are
  -- different defects and only one of them is loud. `v NOT IN (…)` is NULL on a NULL v
  -- and a NULL predicate selects nothing, so an enum arriving blank passes the very
  -- check written to police it. Three of these views read through _blanks_null, which
  -- turns a '' in the table into exactly that NULL — and none of these columns has a
  -- CHECK constraint behind it, since `choices` is enforced by full_clean() alone.
  -- A closed enum has no absent state: the five below are NOT NULL with a default, so a
  -- NULL here is a blank that reached the view, never a value nobody set.
  UNION ALL
  SELECT 'unknown_actor_kind', coalesce(v, 'NULL')
  FROM (SELECT DISTINCT actor_kind AS v FROM claims)
  WHERE v IS NULL OR v NOT IN ('source', 'user')

  UNION ALL
  SELECT 'unknown_actor_resolution_status', coalesce(v, 'NULL')
  FROM (SELECT DISTINCT actor_resolution_status AS v FROM claims)
  WHERE v IS NULL OR v NOT IN ('active', 'suppressed')

  -- ChangeSetAction, and the one branch where NULL is CORRECT rather than a defect:
  -- `action` is nullable, and provenance_changeset_action_iff_interactive makes it null
  -- exactly when there is no ingest run, so every ingest changeset carries one. `''` is
  -- NOT that state — it satisfies the constraint's interactive half while naming no
  -- action at all — so absence is admitted by an explicit NULL test and nothing wider.
  --
  -- Scanned over _changeset_action, the scaffolding, and not over `claims`: this is a
  -- fact about CHANGESETS, and `claims.changeset_id` names only the ones that wrote,
  -- leaving the retraction-only rows — the population `changesets` exists to reach —
  -- outside a check that claims to police the whole vocabulary.
  UNION ALL
  SELECT 'unknown_changeset_action', coalesce(v, 'NULL')
  FROM (SELECT DISTINCT action AS v FROM _changeset_action)
  WHERE v IS NOT NULL AND v NOT IN ('create', 'edit', 'delete', 'revert')

  UNION ALL
  SELECT 'unknown_ingest_run_status', coalesce(v, 'NULL')
  FROM (SELECT DISTINCT status AS v FROM ingest_runs)
  WHERE v IS NULL OR v NOT IN ('running', 'success', 'failed')

  UNION ALL
  SELECT 'unknown_ingest_source_type', coalesce(v, 'NULL')
  FROM (SELECT DISTINCT ingest_source_type AS v FROM ingest_sources)
  WHERE v IS NULL OR v NOT IN ('database', 'wiki', 'book', 'editorial', 'other')

  UNION ALL
  SELECT 'unknown_citation_source_type', coalesce(v, 'NULL')
  FROM (SELECT DISTINCT citation_source_type AS v FROM citation_sources)
  WHERE v IS NULL OR v NOT IN ('book', 'periodical', 'web', 'video', 'document');
