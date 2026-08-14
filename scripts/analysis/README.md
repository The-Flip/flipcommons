# Data analysis tool

This is how to use our DuckDB analytics layer to explore the Flipcommons localhost dev database — both ad-hoc, and via analysis files that back planning docs and data patch campaigns with reproducible queries.

## What this layer is

**A curated semantic layer over the catalog, not a mirror of it.** Every view encodes the liveness rule, declares its grain, decodes foreign keys to stable slugs and states the specific way it would otherwise hand you a confident wrong answer. That is the value, and it is why a catalog question answered with `manage.py shell` or raw sqlite3 against `db.sqlite3` is answered wrong more often than it looks. Consequences:

- **A view is not its table.** `models` is live-filtered and denormalized across four joins; `countries` is the parentless slice of `locations`; `tags` is keyed by model while `tag_vocab` is keyed by tag. Matching names do not mean matching columns or matching grain.
- **A view may not carry all fields.** Absence may mean nobody has promoted it yet. Inspect the Django model and promote fields when required.

## Quick start

```bash
# Do a query
scripts/analysis/analysis query scripts/analysis/catalog.sql "FROM models WHERE year = 1977 ORDER BY name;" # takes `--format json|csv|table` default `table`

# Describe every public view and macro
scripts/analysis/analysis describe

# Look up a view or macro
scripts/analysis/analysis describe model_edges  # Exact match prints its description and, for views, its columns
scripts/analysis/analysis describe edge         # Otherwise, list all partial matches in name or description

# Get the map — what areas exist, when you don't have a term yet
grep '═══' scripts/analysis/catalog.sql scripts/analysis/provenance.sql scripts/analysis/data_patches.sql

# Get the block comment for one view — grain, liveness rule, the plausible wrong answer
grep -B12 'CREATE OR REPLACE VIEW model_edges AS' scripts/analysis/catalog.sql   # Widen -B if the block runs long
```

In `catalog.sql`, two headings say where to start: `MODELS — the spine; start here` and `MODEL-TO-MODEL RELATIONSHIPS — start with model_edges`.

`query` and `describe` put only data on stdout; diagnostics — including DuckDB's grey `-- Loading resources` notice — go to stderr.

Use a CTE for intermediate steps that still fit comfortably in one query. When you need named intermediate views, manual reference data, durable checks or repeated execution, use an [analysis file](#analysis-files).

## Working with the data model

Guidance that belongs to no single view.

### Model vs Title

When a user asks a question about "models" (aka `MachineModel`) they often mean Titles, or models-as-users-see-them — and for a Title with exactly one Model the UI collapses the two (see `SingleModelTitles.md`). Decide which grain the question wants before counting. title_size on the model row is the test: title_size = 1 is a model that is its own Title in the UI. When the Title is the grain rather than the qualifier, `titles` is the entity view — franchise and series groupings live there and nowhere else.

### Matching source records to models

Match models on `name_key(name)`, `manufacturer_slug` and `year`; a name alone is often ambiguous. No result means unresolved, not absent — a missing year or an alternate manufacturer name can prevent a match.

If manufacturer or year is unavailable, use `namesake_count`: `1` means the `name_key` is unique among live models; greater than `1` requires another signal or manual review. The count already uses `name_key`. Read it after a match succeeds too — greater than `1` means the manufacturer or year carried the match alone, so an uncertain one makes the result uncertain.

### Matching free text source wording

Before maintaining a manual mapping, check the alias views. They map source wording to stable catalog keys:

| view                                         | resolves                                                                  |
| -------------------------------------------- | ------------------------------------------------------------------------- |
| `country_aliases`                            | West Germany, Holland, England, R.O.C. → the modelled country             |
| `location_aliases`                           | the same at any level — regions and cities too (Firenze, Milano)          |
| `manufacturer_aliases`                       | native-script, accented and trade-name manufacturer names                 |
| `corporate_entity_aliases`                   | the legal entity below the manufacturer                                   |
| `person_aliases`                             | aka / maiden forms on a credit                                            |
| `reward_type_aliases`                        | a payout phrasing → the reward type                                       |
| `theme_aliases`, `gameplay_feature_aliases`  | a source's wording → the controlled term                                  |
| `model_abbreviations`, `title_abbreviations` | community shorthand (LTBR, ACDC Prem VE) — shorthand, not alternate names |

Match canonical names and aliases as one pool — most records have no alias row, so searching aliases alone resolves almost nothing. Alias views contain one row per alias of a live parent, keyed by parent ID and its stable key. `location_aliases` uses `location_path` because a location slug is unique only within its parent; abbreviation views name their value column `abbreviation` because shorthand is not an alternate name. Values are stored as entered, so choose normalization locally and count distinct target records before accepting a match.

Found a phrasing the catalog lacks? Add it with a [data patch](../../docs/DataPatches.md), not a lookup table in your analysis.

### A subject of any type resolves without branching on the type

Claims and patch entries name their subject polymorphically — `subject_type` plus a bare integer `subject_id` — and models are only the dominant type, not the only one. `entity_subjects` resolves the pair, so `claims` and everything built on it carry `subject_public_id`, `subject_name` and `subject_status` for a person, theme or location subject exactly as for a model. A per-type entity view can't do that job: joining one needs the type known in advance.

`model_slug` / `model_status` on the `patch_*` views are the narrower pair and stay narrow: NULL on every non-model row, by design, so `WHERE model_slug = …` can't admit a Title that happens to share the slug. Reach for `subject_*` unless the query is specifically about models.

### Liveness is the default

Catalog records are soft-deleted (see [RecordLifecycle.md](../../docs/RecordLifecycle.md)). `models` excludes them, matching the read APIs; `all_models` is the escape hatch. Liveness applies to what a model _points at_ too: every dim is soft-deleted independently, so a dead dim **de-enriches to NULL** rather than being reported as current. The one deliberate exception is `claims`, which is not live-filtered — provenance of a deleted record is legitimate history. Use `model_claims` for the live-model lens.

The `patch_*` views inherit that exception and are not live-filtered either, for the same reason: what a patch asserted is history. They carry `model_status` instead, so predicate on it rather than assuming the subject is current.

### What our own patches did

`data_patches.sql` is the patch lens on the provenance layer — the same claims, narrowed to the data patches authored in [flippatch](https://github.com/deanmoses/flippatch) and re-grained around the file an author actually edits. It answers a question no other layer does: not what the catalog says, but **which block of which patch file said it, and what evidence that block recorded**.

- `patch_claims` / `patch_retractions` — what a patch asserted, and what it deactivated. They are separate views because a retraction writes no claim: it flips `is_active` on someone else's, so the retracting patch appears nowhere in `patch_claims.patch_id`. A patch that only retracts is invisible to every claim-derived view.
- `patch_entries` — one row per **effectful authored ChangeSet**: a flat entry or one item of a grouped `changesets:` list, on any entity (not only a model). **The unit a decision is made about**, since a citation added to an entry reaches every claim in it. Driven from `changesets`, so retraction-only entries survive. Not a patch roster: a source-only patch writes no ChangeSet and has no row here.
- `patch_cites` / `patch_entry_cites` — the **field-level** evidence, at claim grain and at entry grain. They traverse the `ClaimCitationInstance` bridge, so an inline `[[cite:id:N]]` citation embedded in a description is **absent** — an entry missing here is not an uncited entry. Filter these on `root_identifier_key`, never on `citation_source_type`: the type is a shape, so `= 'web'` as a proxy for "the IPDB cite" also admits every other web-rooted work.

Three traps. A membership claim with `member_exists = false` is a **tombstone** — the patch asserted the member is absent — so counting it as an assertion reports the opposite of the record. Absence from `patch_cites` means no _bridged_ citation, not no citation. And to **enumerate applied patches**, start from the ingest ledger — `ingest_runs` where `patch_id` is set **and `status = 'success'`** (the applied set is the successful runs; only those are unique per `patch_id`, so `patch_id` alone counts failed and re-run attempts too). It is the only complete roster; `patch_entries`, `changesets` and `patch_claims` each miss source-only, retraction-only or both.

### Model relationship shapes

The foundation surfaces a model's relationships in three shapes, plus a fourth for the controlled vocabularies behind them. Reach for the one that fits:

- **Flat name-list** — `rewards`, `themes`, `tags`. One row per model, a sorted list of the related names (or, for `tags`, slugs). Pure enrichment: join to a model view and display, or test membership. Use when the relationship has no per-edge payload and you only need _which ones_. A name-list **cannot** answer anything about the vocabulary itself — it carries no id, no slug, no DAG. When that's the question, use the vocabulary shape below rather than reaching past the foundation into `fc.catalog_*`.
- **Resolved-edge grain** — `model_edges` and its `model_lineage` / `model_relationships` components. One row per edge, the far end resolved into the shared `target_*` block. Use when each edge points at another model you need to identify.
- **Counted-payload grain** — `model_gameplay_features`. One row per edge that carries a payload (here, the feature `count`: Flippers ×2, Trap Holes ×25). Use when flattening to a name-list would drop a per-edge value.
- **Vocabulary** — `theme_vocab` / `theme_aliases` / `model_themes`, and `gameplay_feature_vocab` / `gameplay_feature_aliases` / `model_gameplay_features`. Not a model relationship at all: one row per _term_, with its usage count (`n`), its place in the DAG and its aliases. Reach for it when the subject is the controlled vocabulary rather than the models — auditing near-duplicates, finding unparented or unused terms, checking whether an alias collides with a live term. The alias views are their own grain so you can join and compare on an alias. `countries` is the same shape minus the DAG, with its aliases in `country_aliases`; `game_formats` has neither.

### `model_edges` is outbound only

`model_edges` answers "what does this model point at", not "is this pair connected". An edge is stored once, on the end that states it, so a model whose only relationship is something else pointing _at_ it has no rows at all — **hundreds of live models are in exactly that position today**, and a connectedness test written against `model_edges` returns `false` for every one of them. Use `model_edges_bidir` for that question: it mirrors each resolved edge and adds a `direction` column. Two rules come with it — `relationship_type` is always the edge _as stated_ and is never re-pointed, so read it together with `direction`; and never aggregate from it, since every edge is counted twice by construction.

### Joining out to other sources

Two mechanisms cross the foundation's edge, both documented where they are defined:

- **What a slug means** — `domain_vocab` parses [DomainModel.md](../../docs/DomainModel.md) at query time, so definitions are never copied into this layer. `LEFT JOIN domain_vocab d ON d.dim = 'gameformat' AND d.slug = g.slug`.
- **Which work a URL belongs to** — `citation_root_for_url(u)`. Not equality or `LIKE`: registered hosts nest, so the rule is a longest label-boundary suffix — and on a shared multi-tenant CDN host (`img1.wsimg.com`) the registered row is scoped to a tenant path prefix, so the URL's path participates too. `citation_root_for_host(h)` remains for a bare host with no URL, and deliberately returns NULL for a shared CDN host, where host-only attribution is unanswerable.

## Analysis files

An **analysis file** is a SQL program built on the foundation. The Flippatch project uses them for data patch campaigns; this project uses them for planning docs under `docs/plans/`. [`catalog_checks.sql`](catalog_checks.sql) is a local worked example.

An analysis file has the following sections; only the third is shaped by the question:

1. **Foundation** — `.read scripts/analysis/catalog.sql`. One line.
2. **Reference** — analysis-local hand-maintained lookups: adjective maps, exception lists, constant vocab. Not derived from the DB. Often empty; that's fine.
3. **Analysis** — the actual work. A candidate hunt might run _detect → assemble → enrich → review_; a different question might _classify_, _aggregate_ or _diff_.
4. **Summary & checks** — the `<prefix>_summary` and `<prefix>_checks` views. The summary computes every headline number the analysis publishes. The checks express invariants so that an empty result means healthy. Three useful check classes are:
   - **Structural** — joins preserve grain; a classification is complete and mutually exclusive; the detector set covers the candidates with nothing left over.
   - **Vocabulary** — a parsed or reviewed value belongs to a closed set.
   - **Anchors** — a known example still triggers each heuristic. This is the only class that catches a whole detector going dark when, for example, a regex rots or a column is renamed. Anchors are essential for free-text detectors.

Start with this shape and keep the file beside its campaign or planning doc:

```sql
-- <purpose>
.read scripts/analysis/catalog.sql

CREATE OR REPLACE VIEW my_finding AS
  SELECT id, name, label FROM models WHERE /* … */;

CREATE OR REPLACE VIEW my_analysis_summary AS
  SELECT 'findings' AS metric, count(*) AS value FROM my_finding;

CREATE OR REPLACE VIEW my_analysis_checks AS
  SELECT 'duplicate_finding' AS check_name, id::VARCHAR AS detail
  FROM my_finding GROUP BY id HAVING count(*) > 1;
```

## Runner

The runner is location-independent: the analysis-file path resolves against your current directory, while its relative `.read`s resolve against flipcommons. This is what lets a data patch campaign in Flippatch consume the foundation without copying it.

```bash
# describe: the view reference — every public view with its one-line description
scripts/analysis/analysis describe <analysis>.sql  # include an analysis file's views

# run: context + <prefix>_summary, then fail nonzero if any *_checks view has rows
scripts/analysis/analysis run <analysis>.sql <prefix>

# render the summary as Markdown for a planning doc or campaign README
scripts/analysis/analysis run <analysis>.sql <prefix> --markdown

# pure data on stdout; --check runs the gate before a generator reads it
scripts/analysis/analysis query <analysis>.sql "FROM my_finding;" --format json --check <prefix>

# GUI: browse every view live in the local DuckDB UI (localhost:4213)
scripts/analysis/analysis ui <analysis>.sql

# Desktop GUI: freeze every public view and table into a standalone database for TablePlus,
# DBeaver, Beekeeper Studio or another DuckDB client
scripts/analysis/analysis browse <analysis>.sql

# snapshot: freeze selected views as real tables into a standalone <analysis>.duckdb
scripts/analysis/analysis snapshot <analysis>.sql my_finding another_view
```

`<prefix>` names the analysis's summary/checks pair (`export` → `export_summary`, `export_checks`), and both must exist for `run` — an analysis that ships a summary with no checks is rejected rather than reported clean.

What's reproducible are _queries_, not _results_: the catalog is a live, moving target. So `run` opens with an `analysis_context` watermark (DuckDB version, live model count, migration point, latest successful data patch + fingerprint, latest changeset), which lets a later reader tell "same query, newer catalog" apart from a broken reproduction.

The **gate is not limited to that pair**: `run` discovers every public `*_checks` view in the session and fails on a row from any of them, and prints every public `*_context` view alongside `analysis_context`. Any SQL file the analysis `.read`s therefore contributes its own invariants and watermark automatically. Private `_underscore` views are excluded from both sweeps, so an intermediate helper can be named `_foo_checks` without joining the gate.

For a generator or pipeline, pass `--check <prefix>` to `query` so the same gate as `run` executes before any data is emitted. The runner is a convenience: raw `duckdb -init <analysis>.sql :memory: "FROM my_finding LIMIT 20;"` from the repo root still works.

`browse` writes `<analysis>.browse.duckdb` beside the analysis file and replaces it atomically on every run. It discovers and materializes every public relation — both views and deliberately materialized tables — including relations contributed by the foundation or another `.read` file, while excluding private `_underscore` helpers. Macros do not travel: a view comment pointing you at `citation_root_for_host()` describes something only the live session has. The result is static: disconnect the desktop client, rerun `browse`, then reconnect whenever the localhost catalog or analysis changes. Any edits made through the client are disposable and disappear on the next rebuild.

`*.duckdb` is gitignored — browse databases and snapshots are throwaways to inspect or hand to someone who can't run the pipeline, never committed artifacts.

## Conventions

- **The runner works from anywhere; raw `duckdb` commands must run from the repo root.** Only the runner does the path resolution described above.
- **`_underscore` = private helper view; unprefixed = public.** Public views are the ones a document quotes and other analyses build on. Keep intermediate parsing private.
- **Published numbers come from `<prefix>_summary`, never hand-counted.** The query is the source of truth, the prose a rendering of it. When the numbers move, update the prose.
- **Predicate on stable keys, display names.** Filter and join on `slug` / `*_id` / `game_format_slug`; use `name` / `manufacturer_name` / `game_format_name` only for output. A renamed value silently zeroes a count with no error; a slug or id doesn't.
- **Join on the id, emit the slug.** Between the two stable keys: a join takes the FK, because it's the relationship the schema actually holds and not every slug stands alone (`locations.slug` is unique only within its parent, which is why `location_path` exists). Anything that _leaves_ the session takes the slug instead — a PK is machine-local, and a data patch addresses records by slug. `model_claims` and `model_credits` carry `model_slug` beside `model_id` so a campaign needn't detour through `models` to project one.
- **A count this layer derives is `n_<what>`; a count the product stored keeps the product's spelling.** `n_claims`, `n_cited_claims`, `n_models`, `n_titles` are computed here. `ingest_runs` is the exception — `claims_asserted`, `claims_retracted`, `records_parsed` are columns on `IngestRun`, passed through verbatim so the view and the ingest can't disagree by name.
- **Ingested source free-text is a plain column.** `ipdb_notes`, `ipdb_notable_features`, `ipdb_toys`, `ipdb_marketing_slogans` and `opdb_features` (the editions and flags list, e.g. `Export edition`) sit on `models` directly, so never hand-roll a `json_extract`. Wanting a raw `extra_data` field that isn't there is a foundation change: see [EDITING.md](EDITING.md#what-belongs-in-the-foundation).
- **Read-only, always.** The catalog is never mutated from an analysis script.

### Making manual judgment checkable (optional)

Sometimes an analysis cites numbers that come from human classification, not a query — "34 of these are bingos, 7 are slot machines." Rather than leave those as hand-counted prose, encode the judgment as a Reference (section 2) lookup table and let it flow through the summary and checks like anything else:

```sql
CREATE OR REPLACE VIEW _orphan_class AS
  SELECT * FROM (VALUES (123,'bingo'), (456,'slot'), (789,'other')) AS t(model_id, category);
```

Then `<prefix>_checks` can catch a classification that's missing a candidate, one that names a model no longer in the set, a duplicate or a `category` outside the allowed vocabulary. Reach for this only when the manual split is worth keeping honest; a one-off count in prose is fine otherwise.

## The engine: DuckDB over an import of the catalog

We query the catalog with the DuckDB CLI. The CLI must already be on the machine, it's not a project dependency.

`backend/db.sqlite3` is **imported** into `backend/db.analytics.duckdb` — DuckDB's own storage — and the foundation defines its views over that. Nothing is ever written to the localhost product DB.

The import is not a step you take. `scripts/analysis/analysis` compares the source's mtime and size against the copy before every command and re-imports only when they differ, which in practice means after a prod refresh or `make ingest-patches`. It takes under a second for the whole database. Everything in between skips it and runs against native storage, which is roughly twice as fast as reading SQLite in place.

Two things follow that the old arrangement didn't have:

- **Your answers hold still inside a session.** A rule that reported 29 hits does not report 3 an hour later because someone ingested a patch underneath you. `analysis_context.snapshot_imported_at` says which copy you measured, and it's printed above every run.
- **`db.analytics.duckdb` is an artifact.** It's gitignored and disposable — delete it and the next command rebuilds it. If you invoke `duckdb -init` directly instead of going through `analysis`, you get whatever the last import produced, with nothing to re-check it; that's the reason the runner is the supported entry point.

Reading the SQLite file in place is what this avoids, and the reason is correctness rather than speed — see [EDITING.md](EDITING.md#never-union-all-two-aggregates-over-different-fc-tables).

## Editing the foundation

For **changing** the foundation — adding a view, editing a check — see [EDITING.md](EDITING.md).
