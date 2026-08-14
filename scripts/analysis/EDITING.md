# Editing the foundation

For changing [`catalog.sql`](catalog.sql) or its self-test [`catalog_checks.sql`](catalog_checks.sql). If you're writing an analysis on top of the foundation, you want [README.md](README.md) instead — this file is about the foundation itself.

## What this layer is

**A semantic layer, not a staging layer.** A staging layer mirrors its source one view per table, exists to give downstream a stable name and adds no meaning. This is the other kind: a view earns its place by applying the liveness rule, decoding (FK to slug, JSON to column, polymorphic id to typed subject), declaring a grain, deriving a measure, or documenting the trap that would otherwise return a confident wrong answer.

**Join the live-filtered view, never re-filter the physical table.** If `X` has a view, join it: `AND x.status IS DISTINCT FROM 'deleted'` on a join is a second copy of the liveness rule, which belongs in the view's own `WHERE` and nowhere else. Where a join stays physical it is because composing would be circular, and it carries a comment naming the cycle — a physical join without that comment is a miss, not a decision. Circularity is narrow: `titles`, `manufacturers` and `corporate_entities` aggregate over `models`, so `models` joins their tables directly.

This file used to claim the opposite — that "a passthrough view would buy nothing" — and that claim shaped the layer: the liveness rule reached 61 restatements in `catalog.sql`, with four checks (`model_dim_not_live`, `uncovered_model_dim`, `dim_not_liveness_checked`, `dim_status_unreferenced`) built to police the copies. Composing brought it to 44 with byte-identical output. Don't reinstate it.

Two things follow. Adding a view is not free bookkeeping to be minimized, and neither is it automatic per table — the [entity/derived split](#what-belongs-in-the-foundation) below is what governs which get one. And **a column absent from a view says nothing about the Django model**; it means nobody promoted it. That is the assumption to correct on arrival, because the default guess runs the other way and has produced wrong answers twice.

## What belongs in the foundation

**The foundation carries counts and mechanics; consumers carry thresholds and semantics.**

The recurring temptation when an analysis finds a gap is to fold its judgment into the foundation alongside the fact — a manufacturer "era" that quietly requires 3 dated models, an `alone_in_title` boolean, a stem macro encoding one manufacturer's numbering convention. Each is right for the consumer that needs it and lossy for the next one, which inherits a cutoff it never chose and can't see.

So: if a proposed column encodes a cutoff, a per-manufacturer convention or a yes/no a query could express in one predicate, surface the underlying number instead and let the caller write the predicate. `title_size.n` is the pattern — the foundation gives `n`, the analysis writes `n = 1`. `manufacturers` gives `year_of_first_model`/`year_of_last_model` **and** `n_dated`, so a consumer can demand whatever evidence it wants. Judgment belongs in an analysis's Reference lookup table, where the checks can see it, not in a macro that answers confidently for inputs it was never calibrated on.

The same rule sets the bar for **macros**, of which there are few: the name-normalization block (`name_norm`, `name_strip_paren`, `name_key`) exists because every cross-record comparison needs one and hand-rolled copies drift. Matching _strategy_ — plural collapsing, token subsets, edit distance — stays analysis-local.

Macros are invisible to the generated column sweep, so each carries a data-independent smoke check in `catalog_checks.sql`, including those defined in `provenance.sql` and `data_patches.sql` so a missing one shows as a gap in one block. **This is the only coverage rule with no meta-check behind it** — `check-mutations` enforces check↔mutation both ways, but nothing enforces macro↔smoke-check, and the first macro to ship without one shipped unnoticed. Pin the behaviour the macro is _relied on_ for, not the shape it happens to have: `patch_number_of` was written against a four-digit width and silently truncated a five-digit id until its smoke check said what the parse was for.

**Source free-text earns a column; a field the catalog already models does not.** `ipdb_notes`, `ipdb_notable_features`, `ipdb_toys`, `ipdb_marketing_slogans` and `opdb_features` are plain columns on `models` because they're genuine unmodeled signal — fields IPDB/OPDB carry that flipcommons doesn't surface, and mining them is common analysis work, so a hand-rolled `json_extract` in every consumer is the thing to prevent. The test for any other raw `extra_data` field is whether it _shadows something the catalog already models_: if so, use the modeled form and leave the source buried — the IPDB trade name defers to `manufacturer_name`, `opdb.keywords` defers to the canonical `themes` view. The long tail (`opdb.common_name`, `opdb.description`, …) stays unsurfaced until an analysis needs it; promoting one is a single line here.

**Physical columns are no longer promoted on demand — they are exposed by default.** Entity and vocabulary views select `alias.* EXCLUDE (…)`, so a new Django field appears on its own and the only way it stays out is an EXCLUDE entry saying why. That was the fix for a specific failure: with an explicit column list, a field deliberately left out and a field nobody noticed are the same text — none — so the layer had no way to record an omission as a decision. The demand-driven rule below still governs derived VIEWS; it never should have governed columns.

When adding a new relationship view, match it to one of the [model relationship shapes](README.md#model-relationship-shapes) rather than inventing a fifth. A payload-bearing relationship should follow the counted-payload grain of `model_gameplay_features` rather than be flattened to a name-list, which would drop the payload.

**Entity views are the other exception, and they are exhaustive.** Every first-class catalog entity gets a view whether or not anyone has asked for one, because the argument that carves aliases out of demand-driven promotion is not about aliases — it is about absence being indistinguishable from non-existence. That failure recurred on entities: two sessions running analyses read a missing view as a missing Django field and reported `Actor` and `ChangeSet` as concepts the system did not have. Neither raised a promotion request, for the same reason the country-map and reward-type campaigns didn't.

So the split is by KIND of view, not by demand:

- **Entity grain — exhaustive, with no exemptions.** One view per first-class entity. `unexposed_entity` derives the entity set structurally (a `catalog_*` table carrying both `slug` and `status`, which selects exactly the concrete `LinkableModel`s) and fails for one that is not exposed, with `stale_entity_view` and `missing_entity_view` closing the other two directions. There are no exemptions: `_entity_view` has no way to opt out.
- **Derived, relationship and measure views — demand-driven.** `model_edges_bidir`, `model_number_collisions`, the vocabulary DAG columns. There is no bound on the questions these answer, so inventing them speculatively is how a foundation grows surface nobody reads. This applies to whole views that compute something new, not to a table's own columns — those are covered by `* EXCLUDE` above.

A projection that reads the physical table independently is a second definition waiting to drift, so build it over the entity view instead — `_ce_location` reads `locations`, not `catalog_location`. A one-predicate slice usually shouldn't be a view at all: `countries` and `country_aliases` were deleted once `locations.is_country` existed, because narrowing columns and renaming keys made them traps rather than conveniences.

**`entity_subjects` must list every entity, so adding a model means adding a branch.** It resolves a polymorphic `(subject_type, subject_id)` reference for `claims` and everything downstream, and it is a hand-written `UNION ALL` because SQL cannot iterate table names — the same limit `_dim_vocab` works around. `unresolved_claim_subject` is what stands behind the hand-list, and it is enough: a forgotten branch, one keyed to the wrong constant and a vanished subject row all surface there on the first claim about the entity, which is also the first moment any of them can mislead anyone. A structural check over the branch set was tried and removed — it only moved the same failure earlier, into a window where nothing references the entity yet. Demand is not a reason to skip a branch: an unlisted type resolves to NULL, which reads as "this subject has no name".

Alias lookups are the exception to demand-driven promotion: expose every concrete `AliasModel` so an undiscoverable catalog mapping is not rebuilt in consumer SQL. Each alias view has one row per alias of a live parent, includes the parent id and stable key, and leaves the stored value unnormalized; `location_aliases` uses `location_path` because location slugs are only parent-scoped. Keep abbreviations separate because they are community shorthand, not alternate names. `unexposed_alias_table` catches a new physical alias table with no view, but it cannot detect a view that exposes only part of that table, so review must verify complete exposure.

## The provenance layer

`catalog.sql` `.read`s [`provenance.sql`](provenance.sql) at its tail; `catalog_checks.sql` `.read`s [`provenance_checks.sql`](provenance_checks.sql) and folds `_provenance_checks` into `foundation_checks`.

- **The agreement checks are the price of the `rank` column.** It reimplements the winner-pick, so the only thing keeping it honest is comparing it against what the resolver materialized — `gameplay_feature_resolution_disagrees`, `theme_resolution_disagrees`, `year_resolution_disagrees`, covering both the membership and scalar register shapes. A fourth register in the ranking needs a fourth agreement check; dropping one drops the justification for the column.
- **Derive the member/scalar split structurally.** A `|` in the `claim_key` means identity parts, which means a relationship member. The value shape can't be used — `claim_presence.py` documents that a claim-controlled JSON scalar may itself be a dict with an `exists` key. `member_claim_nondict_value` and `scalar_claim_exists_flag` assert both directions.
- **`_provenance_checks` is private** so the runner's sweep doesn't report every provenance failure twice, once on its own and once through `foundation_checks`.
- **`.read provenance_checks.sql` sits immediately above `foundation_checks`.** `check-mutations` collects declared check names from the first checks view to end-of-file; read it any earlier and `foundation_summary`'s view-name literals land in that range as check names that don't exist.
- **Views bind at `CREATE`**, so `citation_roots` must follow the views it aggregates.
- **`changesets` is built on `fc.provenance_changeset`, and must stay that way.** Deriving it from `claims` would be shorter and is wrong: 739 changesets wrote no claim at all — they only retracted — and `claims.changeset_id` names only changesets that wrote, so every one of them would vanish. That is the gap the view exists to close, and it closes silently if someone "simplifies" the FROM clause. `changeset_rows_dropped` compares the view against the physical count, and `inert_changeset` asserts the other half (a changeset that neither wrote nor retracted did nothing at all). The same reasoning applies to anything else built on top: aggregate from `changesets`, not from `claims` grouped by `changeset_id`.
- **An actor is an ingest source XOR a user, and `actors` is where that is stated.** `actor_name`/`actor_slug` coalesce across the two kinds so nothing downstream branches on `actor_kind` to attribute a claim — which is only safe while the XOR holds, hence `actor_backing_unresolved` (exactly one backing row) and `actor_slug_collision` (the two namespaces share `actor_slug`). `_claim_actor` is a projection of `actors` rather than a second decode, so the two cannot drift; keep it that way, and keep the count columns out of it so a `claims` scan doesn't pay for them.
- **The `root_*` family travels together, and `root_family_incomplete` enforces it.** Any view carrying `root_citation_source_id` carries the name, the slug and `root_identifier_key` too. This is a coverage rule rather than a style preference because a partial family fails in the direction of a confident wrong answer: a consumer that can reach the root's id and display name but not its stable key does not go and join, it substitutes `citation_source_type`, and filtering IPDB as `type = 'web'` sweeps in every other web-rooted work. Three views were partial when the rule was written, in three different ways — a missing column, a column spelled without the prefix (so grepping the family name found nothing and read as "it doesn't exist"), and a grain view that only ever carried two of the four.

## The data patch layer

`catalog.sql` `.read`s [`data_patches.sql`](data_patches.sql) after `provenance.sql`; `catalog_checks.sql` `.read`s [`data_patches_checks.sql`](data_patches_checks.sql) beside `provenance_checks.sql` and folds `_data_patch_checks` into `foundation_checks`. Same private-view arrangement, same reasons.

- **It is a projection of provenance, not a second source.** Every view here reads `claims`, `changesets` or `citation_instances`. It reads nothing from `fc` directly and must stay that way — the patch lens narrowing to a different population than the provenance layer describes is the drift this ordering exists to prevent.
- **The read order is a three-link chain now.** `data_patches.sql` binds provenance views, which bind `models`. Views bind at `CREATE`, so a reorder fails loudly — but a layer added on top of this one inherits the whole chain, not just the last link.
- **A layer's checks read its own views and the ones below.** `patch_entry_spans_subjects` scans `_patch_acts`, which this layer defines, so it lives in this layer's checks file. Putting it in `provenance_checks.sql` left the provenance self-test binding a view from the layer above it, and meant `provenance_checks.sql` could no longer be read by anything that had read only `provenance.sql`.
- **`patch_entries` is the grain that matters, and `any_value` is load-bearing there.** A patch entry is one ChangeSet, so the view reaches for its subject rather than grouping by it — grouping would split a changeset that ever spanned two subjects into two rows and quietly halve the blast radius of a citation, which is the one thing the view exists to state correctly. `patch_entry_spans_subjects` asserts the assumption instead of the view assuming it. It must scan `_patch_acts` and not `patch_claims`: narrowed to assertions it goes blind to retraction-only entries, which is the same defect `changesets` was repaired for.
- **Aggregate from `changesets`, never from `claims` grouped by changeset.** The rule from the provenance layer applies here with teeth: an entries view built from assertions alone misses 737 of 4798 entries and seven whole patches.
- **Nothing here derives an edit cutoff.** `patch_number_of` exists so an _operator-supplied_ one can be applied ad hoc. Which patches may be edited is not a fact this database holds, and an analysis that decides it for itself decides it wrongly.

## Every public view declares its own one-liner

A public view ships with a `COMMENT ON VIEW` immediately after its `CREATE`:

```sql
CREATE OR REPLACE VIEW title_size AS …;
COMMENT ON VIEW title_size IS
  'One row per Title with a live model — Title identity plus n, the live model count. …';
```

That comment **is** the view reference. `scripts/analysis/analysis describe` reads it from the session, so README.md does not duplicate the view list — and a term naming nothing exactly searches these one-liners, so the words you choose are how the view gets found at all. `undocumented_view` fails the self-test for any public view without a comment; review remains responsible for keeping the comment accurate, while `DESCRIBE` supplies the live column list.

Two mechanics worth knowing:

- **The `COMMENT ON` must immediately follow its own `CREATE OR REPLACE`, not precede it and not sit in a block with its neighbours'.** Replacing a view or macro drops its comment, silently. Keeping each pair adjacent is what makes that a non-issue.
- **Write the grain first, then the guidance** — `describe` prints these as a list, and the grain is what tells `model_edges` from `model_edges_bidir` at a glance. Reasoning that needs more than a sentence goes in the comment block above the `CREATE`, not here.

Macros work the same way and carry the same obligation: a `COMMENT ON MACRO` under each `CREATE OR REPLACE MACRO`, enforced by `undocumented_macro`. `describe` lists them after the views, with their signatures.

Private `_underscore` helpers take no comment; they aren't reference surface.

`model_edges` being outbound-only is stated in both its comment block and README, deliberately — it is the one trap that returns a confident wrong answer rather than an error. Don't trim it as a duplicate.

## Public and runtime surfaces are contracts

Analyses outside this repo rely on the surfaces below — Flippatch's data patch campaign files are the current consumers, and none of them are exercised by anything here. Changing one can break those consumers while the self-test and mutation harness remain clean.

- **Public view and column names.** `models`, `model_edges`, `target_*` and the rest. Treat a rename the way you'd treat one in an API: it needs the consumers updated in the same breath, not discovered later by a campaign that returns zero rows.
- **The `patch_*` views specifically.** They were promoted out of a campaign-local layer in flippatch, which deleted its copy in the same breath. The campaign that drove the promotion (0189, print citations) has since finished, so as of 2026-08-13 there is no known live consumer — but the general hazard stands: a column dropped here surfaces as a campaign emitting nothing, in the other repo, with nothing in this one failing. Re-check who is reading them before treating that as freedom; "no consumer" is a claim with a date on it.
- **ATTACH aliases.** `catalog.sql` owns **`fc`** (the read-only catalog) and `snapshot` owns **`snap`** (its output file). Those two are reserved; everything else in the `ATTACH` namespace belongs to the layers above, which claim their own — Flippatch's evidence bridge takes `ev` for pinexplore's web-scrape cache. Don't add a third foundation attachment without checking it against what the consumers have already claimed, and don't assume an alias is free because nothing in this repo uses it.

The runner discovers public `*_checks` and `*_context` views by name, so those suffixes are load-bearing across repos. A foundation view that happened to end in `_checks` would silently join every consumer's gate.

`snapshot` copies tables into its attached output file, so the `.duckdb` holds plain tables — not the session's views, which reference the `fc` attachment and would dangle once it's gone. For the same reason the analytical views stay non-`TEMP`: the DuckDB UI runs each query cell on its own connection, and `TEMP` views aren't visible across connections. Don't "tidy" them to `TEMP`.

## Domain semantics belong to DomainModel.md, not here

`domain_vocab` **reads** [DomainModel.md](../../docs/DomainModel.md) at query time — one row per controlled-vocabulary term, with the prose definition — so an analyst filtering `production_status_slug = 'one-off'` can join to find out what that means, and the doc stays the only place a domain fact is written.

The division of labour is worth holding onto, because the pull is always toward restating: **DomainModel.md owns what a term means; `catalog.sql` owns what will mislead your query.** Grain, liveness spelling, non-uniqueness, outbound-only — those are properties of the lens, true nowhere else, and they belong here. If a comment you're about to write could be a sentence in DomainModel.md, link to it rather than copying it down; a second copy is a second thing to keep true.

Four checks hold the two in agreement, in both directions — `undocumented_vocab` catches a live term the doc never defines, `stale_vocab_doc` catches a definition for a term that isn't live, and `unmapped_vocab_dim` / `stale_vocab_dim` guard the `_dim_vocab` hand-list.

The doc shape relied on is a bullet of the form **`-` + backticked slug + `:` + definition**, grouped by the nearest bold entity lead-in or `##`/`###` heading, with the group snake-stripped to the `catalog_<dim>` table suffix. Rename a heading and every bullet under it detaches — which surfaces as every slug in that vocabulary reported undocumented at once, plus `stale_vocab_dim`. Loud, never silent.

## Liveness is spelled in the opposite dialect from the ORM, on purpose

`catalog.sql` writes live as `status IS DISTINCT FROM 'deleted'` — a **denylist**. The ORM's `.active()` writes it as `status = 'active' OR status IS NULL` — an **allowlist**. README says `models` matches how the read APIs behave, and today that is true, but it is true by _coincidence_: the two spellings are extensionally identical only while the `EntityStatus` domain is exactly `{active, deleted, NULL}`.

A third member splits them, silently and in opposite directions — the denylist fails **open** (the new status appears in `models`), the allowlist fails **closed** (it vanishes). Neither spelling errors, and no row-level invariant can see it, which is why `status_unknown` exists: it asserts the domain rather than assuming it, and it is what licenses the spelling used here. Don't remove it to "simplify" the liveness filters.

If it ever fires, **don't mechanically port `catalog.sql` to the allowlist.** The right answer depends on what the new status means: an archived cohort may well belong in `models` for analysis even though the product hides it — surfacing the odd cohort is often the whole job — or it may not. Deciding now, in the abstract, would bake in exactly the kind of unchosen cutoff the section above warns against. The check preserves that choice; porting early spends it.

Coverage of the liveness filter is generated rather than trusted: the dim list `catalog.sql` live-filters is swept against the physical column list of `catalog_machinemodel`, so **a new dim FK on the model fails `uncovered_model_dim`** instead of silently going unfiltered and unchecked. Adding a dim means adding its live-filtered join, not just its column.

## Why the catalog is imported rather than attached

`fc` is `backend/db.analytics.duckdb`, an import of `backend/db.sqlite3` into DuckDB's own storage, refreshed by the runner whenever the source changes. It would be simpler to `ATTACH` the SQLite file directly, and that is what this layer did until it produced two silent wrong answers.

DuckDB's sqlite scanner gets the following wrong, and the liveness predicate is what makes the shape common enough to matter.

```sql
-- WRONG. Returns cabinets' count for BOTH rows; the second table is never scanned.
SELECT 'cabinets' AS v, count(*) FROM fc.catalog_cabinet WHERE status IS DISTINCT FROM 'deleted'
UNION ALL SELECT 'game_formats', count(*) FROM fc.catalog_gameformat WHERE status IS DISTINCT FROM 'deleted';
```

When two branches of one query aggregate over different attached-SQLite tables and their pushed-down projection and filter are textually identical, the optimizer treats the scans as equivalent and evaluates one of them. `SET sqlite_debug_show_queries=true` shows a single `SELECT "status" FROM "a" WHERE ROWID BETWEEN ? AND ?` issued for both branches. Every simple dim view is that shape, because every one of them selects the same columns under the same liveness predicate.

Measured on DuckDB v1.5.5 / `sqlite_scanner` f79b1db: it hits any aggregate, not just `count`; every branch, not only the second; and scalar subqueries, `OFFSET 0`, `threads=1` and `disabled_optimizers` all fail to avoid it. Two things are safe, and between them they explain why it stayed hidden: **row-level unions** (`SELECT slug FROM a … UNION ALL SELECT slug FROM b …` is correct, which is why `entity_subjects` and `_dim_status` were never affected), and **branches whose filter literals differ** — it needs the branches to agree, and the liveness predicate is the one thing every view spells identically.

**Importing removes the class entirely.** The hazard remains only for a SQLite file you attach yourself — an evidence bridge, a scratch comparison. Two shapes are safe there: aggregate over a union of labelled rows (what `foundation_summary` does — don't "simplify" it back, though note a zero-row relation then drops out rather than reporting 0), or wrap each branch in `WITH x AS MATERIALIZED (…)`, which is close to free.

It was found in two places, both publishing wrong numbers with every check green: `foundation_summary` reported one vocabulary's count for another's, and `_anchor_scan` reported one view's liveness for three others — the dark-column detector unable to see a dark column. Assume any analysis in a sister repo that tabulates per-table counts this way has the same defect.

## Editing the foundation? Run its self-test

```bash
scripts/analysis/analysis run scripts/analysis/catalog_checks.sql foundation
```

Prints a row-count-per-view health readout, then fails if any invariant broke — three classes: data-independent structural checks (union integrity, grain, the live filter, the `model_edges` license/source contract, subject + target resolution), generated dark anchors and coverage meta-checks. It has the same shape as a reusable analysis file, so no check logic leaks into `catalog.sql`.

## Editing the checks? Mutation-test them

```bash
scripts/analysis/check-mutations          # all mutations
scripts/analysis/check-mutations title    # only those whose name matches
```

`scripts/analysis/check-mutations` breaks the catalog on purpose — one way per line of [`catalog_mutations.tsv`](catalog_mutations.tsv) — and asserts the check that should notice actually does. Takes well under a minute.

This exists because of a failure mode specific to check code: **a broken check and a passing check both return zero rows.** "It returned nothing on healthy data" is not evidence a check works — it is exactly what a no-op does, so a green self-test can sit on top of guarantees that quietly evaporated. NULL comparisons are a common cause, hence the house rule at the top of `foundation_checks`: compare with `IS DISTINCT FROM`, never `<>`, and null-test operands before any ordering operator. The harness proves what the rule can only ask for.

Adding a check? Add a line breaking what it guards — the harness **enforces** that, in both directions, so a check can't ship unproven and the spec can't rot after a rename. It also fails on a filter that matches nothing (otherwise a typo yields a green run that tested nothing).

A dirty baseline doesn't abort the run — the checks split into two temperaments, and the harness respects the line. Structural checks fire only when foundation code breaks; domain-sync checks (`undocumented_vocab`, `stale_vocab_doc`, `expired_anchor_skip`) fire on healthy-data drift, and a drifted doc says nothing about whether `union_integrity` would notice a broken join. So a check already firing at baseline **BLOCKS** its own mutations — it would "confirm" them even if their SQL did nothing — and its noise is subtracted from every other probe, leaving the rest of the suite trustworthy. A blocked check is loudly reported and stays unproven until `analysis run` is green again; the everyday gate is where drift keeps its teeth.

The mutation should fail _before_ your check exists. Write it first, watch it report `SURVIVED — defect unnoticed`, then add the check and watch it turn `ok`. A mutation written after the check, against the check, tends to describe what the check does rather than what the defect is.

`CREATE OR REPLACE VIEW` drops the view's comment, so nearly every mutation trips `undocumented_view` as a side effect rather than as the defect under test. `check-mutations` excludes that check from its miss-path diagnostic; the filtered fast path is untouched, so `view comment dropped` still proves it fires. Don't add `COMMENT ON VIEW` boilerplate to mutations.

## Dark anchors

**A facet is "dark" when no row holds a usable value — all-NULL _or_ all-zero.** Both indicate the same failure: a broken join. They don't look alike to a checker, and a plain `COUNT()` only sees the first. A derived count whose join collapsed still produces non-NULL rows of zero, so the sweep's measure is `live` (neither NULL nor zero). That covers every derived count in the foundation at once (`title_size`, the vocabulary `n`s, `manufacturers.n_*`) instead of needing a per-column check for each.

**Anchors are generated, not hand-written.** An anchor fires when a decoded facet goes silently dark — a broken join or a renamed source key (`model` → `models`, `notes` → `ipdb_notes`) zeroes a whole column with no error, the one failure a row-level invariant can't see. `catalog_checks.sql` derives these from the views themselves: `_anchor_scan` sweeps every column of every public view, counting the rows whose value is neither NULL nor zero, so **adding a decoded facet anchors it for free** — there is no per-facet anchor to write. Adding a whole view, or a new list-typed facet of any element type (`VARCHAR[]`, `BIGINT[]`, …), is caught by the `unanchored_view` / `unanchored_array` coverage meta-checks.

Two short hand-lists remain, both with a safe default — forgetting an entry over-anchors loudly rather than under-anchoring silently — and both checked in **both directions**, because an exemption is a hole in the coverage and has to be as hard to leave lying around as it was to open.

- **`_anchor_skip`** — columns allowed to be entirely empty, each tagged `sparse` (a genuinely-sparse dim like `technology_subgeneration` / `display_subtype`, no expiry) or `pending` (empty only until data lands, so it **must** expire). A `pending` entry whose facet goes live fails `expired_anchor_skip`; an entry naming no swept column fails `stale_anchor_skip`; and a `kind` outside those two values fails `unknown_anchor_skip_kind`. The exemption is applied on `col` alone, so an unknown kind would otherwise exempt the column without participating in expiry checks. Entries are matched bare when the column name is unique to its facet, qualified `view.column` when it isn't.
- **`_anchor_array`** — the list-typed facets, qualified `view.column`, since an empty list is a value and the sweep measure can't see it go empty. A new array fails `unanchored_array` and a renamed one fails `stale_anchor_array`. Each entry gets its **own** explicit anchor — a superset's does not stand in for its parts. `model_edges` is a `UNION ALL`, so one component's array can go entirely empty while the union stays non-empty from the other side; `union_integrity` proves the union is lossless, which is a different claim from each side being populated.

`analysis_context` is swept out on purpose — a watermark whose NULLs (e.g. no successful patch yet) are legitimate.

## Cost

**Adding views to the foundation is effectively free; the self-test is where cost lands.** Views are lazy DDL — loading all of `catalog.sql` costs the same no matter how many views it defines, and a query pays only for the ones it touches. The one place a new view costs something is `catalog_checks.sql`, whose column sweep is the most expensive thing in the analysis layer.

`foundation_checks` therefore opens with a block of **`WITH … AS MATERIALIZED` CTEs** that shadow the foundation views by name, so each is decoded once for all the checks rather than once per reference. Build new checks on those names, not on `main.`-qualified views. The rationale for lazy-view-plus-materialized-at-use (rather than a real table at initialization) is in the comment there.
