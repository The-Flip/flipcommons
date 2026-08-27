# Editing the analytics

This directory is the semantic layer: the SQL that turns raw dumps into relations that are safe to query. `../../README.md` is for people _using_ it; this is for people _changing_ it.

**Source-specific knowledge belongs in the file header, not here.** How Railway spells severity, which Sentry dataset omits what, which exporter truncates — each lives at the top of the file that reads it, where someone editing that reader will see it. What follows is only the conventions common to every file.

## The build

`./build` concatenates every `*.sql` here, in filename order, into a database rebuilt from scratch. There is no incremental state and nothing to migrate: change the SQL, rebuild, done. It rebuilds only when an input is newer than the database, and `--force` overrides that. The check gate runs either way, so a skipped build still evaluates `checks` and still exits nonzero on a finding.

`../../query` is the everyday entry point and builds first; `./build` is the same rebuild plus the verdict, so it is what a gate would call.

Filenames are `NN_source_thing.sql`, and `NN` is dependency order — a file may use anything defined in a lower number. Gaps are deliberate so a new file can land between two existing ones without renumbering. Paths inside the SQL are relative to this directory, so dumps are at `../../dumps/`.

The build is the test. It fails on a failing check, so a change that breaks an invariant does not quietly produce a database.

## Tables and views

**Base readers create `TABLE`s. Derived relations are `VIEW`s.**

A view over `read_json_auto('../../dumps/...')` re-reads the file on every query, resolved against whatever working directory the caller is in — so it works from here and nowhere else, including from `query`, which deliberately does not cd. Materializing the readers means the file paths are needed once, at build time. `view_reads_filesystem` enforces this rather than leaving it a convention, because the failure is not always loud: `read_csv` raises when its pattern matches nothing, but `glob` returns an empty result, so a view built on one reports "nothing pulled" with no error.

**An intermediate that should not survive the build is a `TEMP TABLE`.** Use one where a reader feeds other readers and keeping its output would store the same data twice. The build is a single connection, so a temp table lives exactly as long as it is needed, reads the dumps once instead of once per consumer, and is absent from the discovery listing because it is absent from the database.

## Every relation carries a COMMENT

State the **grain** first — _one row per what_. Then, if there is one, the specific wrong answer the relation prevents:

```sql
COMMENT ON VIEW problems IS 'GRAIN: one row per non-continuation observation at
error or worse whose severity the row itself declared. Excludes every Railway
line whose level was guessed from stdout/stderr. The stream to READ during an
incident; count summary instead.';
```

These are the discovery surface — a session lists them to learn what exists — so a relation without one is invisible. They are also the only home for a fact: if it is in a COMMENT, it does not also belong in a file header or in `../../README.md`.

## Checks

Every `checks` branch returns zero rows when healthy; any row is a finding, and `build` exits nonzero.

Guard **shape**, not values. The useful checks catch an export format drifting under the layer — a field vanishing, a service appearing unmapped, two files being read where one was intended. Data being unusual is not a defect; the layer misreading it is.

**A check that fires on an expected permanent condition is worse than no check**, because it teaches everyone to ignore the whole list. When something is expected but should not _dominate_, threshold it rather than testing for any occurrence at all.

A check also beats a comment. Where a comment would warn against doing something, prefer an invariant that fails the build, and then the warning does not need writing.

## Derive rather than declare

Reference data carries per-entity behavior; shared SQL stays uniform. A `CASE WHEN service = 'x'` in a derived relation is the smell — that knowledge belongs in a column on the reference table, so adding an entity is a row rather than an edit in three places.

Split files by **grain**, never by entity. A new file is warranted when rows mean something structurally different (a request is not a log line). Two services whose rows are both log lines share one relation and differ by a column.

## Verifying a change

Rebuild and compare `summary` against what it printed before. Row counts that move without an explanation _are_ the finding — that is how a double-read and a timezone shift were both caught here.

For a format that has no data yet, add a case to `../test`. It builds this directory against `../fixtures/dumps/` in a temp directory and asserts what comes out, so a shape can be exercised before any real dump contains it.

That suite exists because `checks` cannot cover the failures that matter most. Checks run against `../../dumps/`, which is gitignored, private and always changing, so they can only assert what happens to be true of today's production. The dangerous inputs are the ones production does not contain — an export that is **empty**, a line that is **malformed**, a field that has **vanished** — and those have to be authored on purpose. Every reader also declares its columns rather than inferring them, for the same reason: inference has no schema to find in an empty file, and the whole build fails to bind rather than reporting a quiet window.
