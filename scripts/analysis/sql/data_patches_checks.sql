-- Data patch self-test — the invariants for data_patches.sql.
--
-- Not a standalone analysis: catalog_checks.sql `.read`s this and folds
-- `_data_patch_checks` into `foundation_checks`, so there is ONE gate and one mutation
-- harness entry point. Private (`_` prefix) for that reason — a public `*_checks` view
-- would ALSO be discovered by the runner's sweep and every failure would report twice.
-- Exactly the arrangement provenance_checks.sql is in, for exactly the same reasons.
--
-- It exists as its own file rather than as a tail on provenance_checks.sql because the
-- check below reads `_patch_acts`, which data_patches.sql defines — and data_patches.sql
-- is built ON provenance.sql. Folding it upward would leave the provenance layer's own
-- self-test binding a view from the layer above it, so `provenance_checks.sql` could no
-- longer be read by anything that had read only `provenance.sql`. A layer's checks read
-- its own views and the ones below; this file is where the patch layer's do.
--
-- Same contract as the rest of the self-test: a row means something broke, empty means
-- healthy, and every check_name here needs a line in catalog_mutations.tsv proving it
-- fires. Same house rule too: compare with IS DISTINCT FROM, never <>, and null-test
-- operands before any ordering operator — a NULL comparison is how a check silently
-- becomes a no-op.

CREATE OR REPLACE VIEW _data_patch_checks AS

  -- A patch changeset acting on more than one subject. `patch_entries` treats a changeset
  -- as one entry with one subject and reaches for the subject with any_value; if this
  -- fires, that reach is picking one of several and the entry grain needs rethinking
  -- before anything trusts it. Must scan `_patch_acts`, the exact population
  -- `patch_entries` aggregates: narrowed to `patch_claims` it goes blind to retractions.
  --
  -- Named for the grain it guards, not for `changesets`: the population is patch acts
  -- alone, so an INTERACTIVE changeset spanning two subjects would never fire it. A
  -- check whose name claims a wider population than it scans reports healthy for cases
  -- it was never looking at.
  --
  -- coalesce before concatenating, per the house rule. `||` yields NULL if either side
  -- is, and count(DISTINCT) drops NULLs — so a changeset holding one real subject and
  -- one unresolved would count 1 and pass, which is precisely the state worth catching.
  -- Both columns are non-NULL upstream today; the check does not get to assume that.
  SELECT 'patch_entry_spans_subjects' AS check_name,
         CAST(changeset_id AS VARCHAR) AS detail
  FROM (
    SELECT changeset_id FROM _patch_acts
    GROUP BY changeset_id
    HAVING count(DISTINCT coalesce(subject_type, '?') || ':'
                          || coalesce(CAST(subject_id AS VARCHAR), '?')) > 1
  );
