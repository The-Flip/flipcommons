# Model filtering — implementation plan

How to build what [ModelFiltering.md](ModelFiltering.md) asks for: a listing whose cards are Titles and Models, a search that finds a Model by its own name, and a filter vocabulary that reaches the catalog's Model-to-Model relationships.

The product doc owns sequencing and scope. This document is organized to match it — [PR.HET](ModelFiltering.md#PR.HET), [PR.DETAIL](ModelFiltering.md#PR.DETAIL), [PR.REL](ModelFiltering.md#PR.REL), [PR.SPARSE](ModelFiltering.md#PR.SPARSE), [PR.MOVE](ModelFiltering.md#PR.MOVE) — and where the two disagree, the product doc is correct.

## How the numbers here are sourced

Every figure is re-derivable, by one of three routes, and each is labelled where it appears:

- **From [`model_filtering.sql`](model_filtering.sql)**, which encodes the roll-up rule as SQL and publishes its headline figures through `model_filtering_summary`. Do NOT use it to measure query performance: it runs on DuckDB and says nothing about Postgres.
- **Ad-hoc**, meaning a one-off query over `catalog.sql` or `model_filtering.sql` rather than a named view. Each states the predicate it counted, so it can be re-run.
- **From the running dev API**, by request.

```bash
scripts/analysis/analysis run docs/plans/filtering_and_search/model_filtering.sql model_filtering
```

Measured against the local dev catalog at patch `0188-model-lineage`: 6,180 Titles, 6,913 live Models, 139 of them Variants, 455 Titles holding more than one Model.

A number carrying no label is an assertion nobody can check. This document has shipped three of those; do not add a fourth.

## What is broken today

Five defects, all reproducible against the dev server, and all one defect underneath: **the listing answers Model-shaped questions at Title grain.**

### Filters return the wrong records, or none

`manufacturer` and the search term are pinned to the Title's representative Model through `_MFR_SLUG_SQ` / `_MFR_NAME_SQ`. `first_model_candidates()` deliberately sorts subordinate Models last — the Big Ben rule — so a manufacturer that only ever built copies represents no Title and is invisible to its own filter.

| today                          | returns | should return                              |
| ------------------------------ | ------- | ------------------------------------------ |
| `?manufacturer=vifico`         | **0**   | 13 VIFICO Models                           |
| `?manufacturer=chicago-gaming` | **2**   | 15, including the Medieval Madness remakes |
| `?manufacturer=williams`       | 469     | 487                                        |

The other eleven dimensions use any-Model semantics instead, which fails the other way: a Title matches through a Model whose card is never shown.

### Model names are searched nowhere

The search predicate reaches exactly three fields: `Title.name`, `Title.abbreviations.value` and the representative Model's manufacturer name.

```text
GET /api/titles/?q=Godzilla (Pro)   → count 0     ← an exact, character-for-character Model name
GET /api/titles/?q=Rock Encore      → count 0
GET /api/titles/?q=Remake           → count 0
```

825 Models are named differently from their Title. **523 of them (386 excluding Variants), across 264 Titles, are not reachable by any substring of their Title's name** — you must already know that Rock Encore lives under Rock. Meanwhile **430 `ModelAbbreviation` rows are consulted by nothing at all.**

### A Title can match through several different Models

`apply_dimension` issues one `.filter()` per dimension, so Django emits a fresh join each time. The semantics are _AND across dimensions, OR across a Title's Models_: `alien-poker` holds Alien Poker (Williams 1980), Lunelle (Taito do Brasil 1981) and Space Poker (LTD do Brasil 1982), and filtering Williams × 1981 returns it — Williams through one Model, 1981 through another — carding a 1980 machine that is in neither the year asked for nor the manufacturer's own row.

That is coherent only while every card is a Title card. The moment a card can be a Model, the rule needs a Model to point at and there may not be one. The product doc's [multi-select section](ModelFiltering.md#multi-select) settles it: one Model must satisfy everything.

`alien-poker` is the readable case, but it is not a rarity. **Ad-hoc**, counting Titles that match a dimension pair today where no single Model satisfies both, restricted to pairs where both values are recorded on both Models — so this is genuine disagreement rather than a missing value:

| dimension pair              | Titles | value combinations |
| --------------------------- | ------ | ------------------ |
| manufacturer × year         | 102    | 309                |
| manufacturer × player_count | 32     | 74                 |
| tech_gen × display_type     | 32     | 60                 |
| manufacturer × tech_gen     | 19     | 37                 |
| system × display_type       | 1      | 2                  |
| tech_gen × system           | 0      | 0                  |

Conflicts cluster on manufacturer and year, which are the dimensions along which a Title's Models genuinely differ rather than differ only in what has been recorded. `tech_gen × system` is zero because those Models really do agree.

Drop the both-recorded restriction and the same counts run far higher — manufacturer × player_count goes from 32 Titles to 386 — because an unrecorded value makes a Model fail the pair. That is the same effect as [sparse data shattering](#sparse-data-shatters-and-that-is-wanted) seen across two dimensions instead of one, and it is wanted for the same reason: the rule never asserts a Model carries a property nobody recorded.

### Almost every browse surface excludes Variants

The same defect one rung lower, and the one most likely to be mistaken for a design choice.

Every taxonomy and manufacturer detail page filters `variant_of__isnull=True` into its queryset — [`themes.py:92`](../../../backend/apps/catalog/api/themes.py:92), and the same line again in `franchises.py`, `corporate_entities.py`, `locations.py` and `manufacturers.py`. So a Variant appears on the Title detail page, on its own Model page, and almost nowhere else.

The one exception is worth knowing because it is a considered decision rather than an oversight, and the rule should not quietly overturn it: `/production-statuses/<slug>` passes `include_variants: true`, on the stated grounds that production status genuinely varies between a Model and its Variants — an announced Limited Edition beside a shipped Premium — so collapsing them there would hide the distinction the page exists to show. It is the only route in the frontend that passes the flag.

That loses real information, because a Variant is not a copy of its parent: of 139 Variants, **10 carry a theme that no non-Variant Model under their Title carries** — 19 tag rows in total. Those Models are tagged with a theme, and no page on the site lists them under it.

Separate the mechanism from the policy, because the difference decides the size of the fix. It is **not** a prefetch that someone forgot: it is an explicit exclusion, written deliberately — `variant_of__isnull=True` appears ~24 times across 13 files under `backend/apps/catalog/`, and within `_title_facets.py` alone the guard is spelled three ways: `_MODEL`, `_MODEL_COUNT_GUARD` and hand-written inline in `_count_player` and `_count_hierarchical` ([PRE.GUARD](#pre-guard) unifies those spellings before the policy split is attempted). Variant exclusion elsewhere in the backend does two other jobs — count hygiene on taxonomy pages, and representative selection — and **neither may change**, or a theme starts counting Godzilla three times. Only the list exclusion is the policy the rule overturns.

### Relationship filtering does not exist, and three ordinary dimensions are missing

Nothing anywhere asks for bootlegs, conversion kits, remakes or the machines that have been copied. Separately, `game_format`, `production_status` and `cabinet` are live on `/api/models/` but none is on the listing, so questions needing no relationship at all — every bingo-pinball the catalog knows of, say — are unanswerable purely for want of an ordinary facet.

## What the rule changes

### A row is a card, not a Title

Under the rule a Title that fails to roll up contributes **one card per matching Model**. Measured across every dimension and value, **1,430 filter values shatter at least one Title into several cards, and one Title yields as many as seven.** A row is therefore a card, not a Title, and everything the listing counts or orders moves to card grain with it: `count`, offset pagination, the sort, the create-prompt gate and every facet count.

This is where the risk is concentrated. It is inherent to the rule rather than to any particular implementation of it, and everything else assumes it has landed.

### Sparse data shatters, and that is wanted

A Title rolls up only when **every** live Model matches, so an unrecorded value on one Model is enough to break it — the Model does not match, and the Title stops being unanimous. Which means the dimensions that shatter most are not the ones whose Models genuinely differ:

| dimension      | Titles shattered | why                                             |
| -------------- | ---------------- | ----------------------------------------------- |
| `feature`      | 259              | recorded per Model, unevenly                    |
| `edge`         | 256              | genuine — a copy sits under the Title it copies |
| `display_type` | 218              | mostly unrecorded on one Model of a pair        |
| `year`         | 193              | genuine                                         |
| `theme`        | 187              | recorded per Model, unevenly                    |
| `manufacturer` | 187              | genuine                                         |
| `tech_gen`     | 80               | genuine                                         |

`display_type` outranking `manufacturer` is the tell: those 218 Titles are not disagreeing about anything, they are missing a value on one Model of a pair.

Shattering is intended. Today the gap is invisible — the Title card answers for Models that were never asked, so an unrecorded `display_type` reads exactly like a recorded one. Under the rule the Title stops speaking for them and the shard is where the hole was. The rule treats missing as not-matching, so it is under-inclusive and never asserts something false, and the shard count falls as the catalog fills in.

Two limits on how much light this casts. A shard says _something under here is incomplete_; it does not say which Model or which field, and it only reads as a signal to someone who knows the rule. And it fires only under an active filter on that dimension, so nothing surfaces for a dimension nobody filters by.

Both are cheap to close and neither is on the critical path: `mf_dimension_disagreement` already computes the shattered set exactly, per dimension and per Title, so the curator-facing version of this is a worklist query rather than a feature. Open it as a data-campaign item once the rule ships.

### In aggregate, the listing barely moves

Summed over every value of each dimension, comparing today's cards against the rule's:

| dimension      | cards today | cards under the rule | share that are Model cards |
| -------------- | ----------- | -------------------- | -------------------------- |
| `display_type` | 1,739       | 1,854                | 20.1%                      |
| `system`       | 632         | 665                  | 19.8%                      |
| `person`       | 5,230       | 5,541                | 16.5%                      |
| `feature`      | 26,051      | 27,072               | 10.1%                      |
| `year`         | 5,236       | 5,377                | 9.7%                       |
| `manufacturer` | 6,026       | 6,147                | 8.6%                       |
| `theme`        | 11,479      | 11,730               | 7.7%                       |
| `player_count` | 6,095       | 6,170                | 5.1%                       |
| `tech_gen`     | 6,037       | 6,086                | 2.8%                       |
| `edge`         | —           | **706**              | **50.8%**                  |
| `game_format`  | —           | **6,181**            | 0.03%                      |

`edge` and `game_format` carry no "today" figure because neither dimension exists on the listing. There is no baseline to compare against, and a number in that column would be a counterfactual wearing a measurement's clothes.

`edge` is the dimension the roll-up was built for — half its cards are Model cards, against 8.6% for manufacturer. It arrives in [PR.REL](#prrel--the-relationship-vocabulary), so PR.HET builds the machinery and PR.REL is where it visibly pays off.

`game_format`'s figure is the [default-bucket](#game_format-and-production_status-unclassified-joins-the-default-bucket) reading. **Every number in this table is a sum over all of a dimension's values, not what one filter click returns** — the column heading says so, and for `game_format` the distinction is a factor of sixty, so it is worth restating here. Summed over values: 6,181 bucketed against 619 raw. The single click a reader actually makes:

| the reader clicks "Pinball"     | Title cards | Model cards | cards     |
| ------------------------------- | ----------- | ----------- | --------- |
| bare `?game_format=pinball`     | 91          | 6           | **97**    |
| the widened preset, both values | 5,658       | 1           | **5,659** |

That gap — 97 against 5,659 — is the whole argument of the default-bucket section, and it is the number to quote when arguing it. `mf_dimension_values` carries the two readings side by side as `game_format` and `game_format_bucket`, and `model_filtering_summary` publishes both the sums and the two single-click results.

Result sets grow by single-digit percentages, and Model cards are a small minority everywhere except relationships — which is exactly the point of the feature. The unfiltered listing is unchanged at 6,180 cards, because with no filter active every Title is trivially unanimous.

Worked cases, all from `mf_card_counts`:

| filter                        | today | Title cards | Model cards | total     |
| ----------------------------- | ----- | ----------- | ----------- | --------- |
| `manufacturer=vifico`         | 0     | 0           | 13          | **13**    |
| `manufacturer=chicago-gaming` | 2     | 2           | 13          | **15**    |
| `manufacturer=segasa`         | 12    | 3           | 12          | **15**    |
| `manufacturer=williams`       | 469   | 442         | 45          | **487**   |
| `tech_gen=solid-state`        | 1,407 | 1,332       | 100         | **1,432** |
| `theme=fantasy`               | 371   | 326         | 70          | **396**   |
| `edge=copy`                   | —     | 80          | 92          | **172**   |
| `edge=remake_of`              | —     | 1           | 18          | **19**    |

### But it moves most where readers look most

The aggregate understates the change, because multi-model Titles are not spread evenly across the catalog. **Ad-hoc**, Titles bucketed by their earliest Model's year:

| decade | Titles | holding >1 Model | share     |
| ------ | ------ | ---------------- | --------- |
| 2020s  | 84     | 45               | **53.6%** |
| 2010s  | 113    | 42               | **37.2%** |
| 2000s  | 68     | 6                | 8.8%      |
| 1990s  | 236    | 14               | 5.9%      |
| 1970s  | 715    | 178              | 24.9%     |
| all    | 6,180  | 455              | 7.4%      |

Over half of 2020s Titles and better than a third of 2010s Titles can shatter, against 7.4% catalog-wide. That is the product doc's point that roll-up "doesn't affect _that_ much, but it's the most modern looked-at portion", quantified. The 1970s figure is the other spike, and it is the copy-and-export era rather than the edition-tier one.

## Consumer inventory

Answering "there are surely other consumers than the following, we need to do an inventory" from [ModelFiltering.md → Consumers](ModelFiltering.md#consumers). Three were named there; these are all of them.

| surface                                                     | state                                                                                         | what happens to it                                                                               |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `GET /api/titles/`, `GET /api/pages/titles`                 | `TitleFilterQuerySchema` → `TitleFilters` → `DIMENSIONS` / `apply_dimension` → `facet_counts` | PR.HET. This is the work, and the route is renamed `/api/games/`                                 |
| `GET /api/pages/search`                                     | composes `ordered_titles()` with `_serialize_card`                                            | PR.HET — same predicate, same serializer, same rule                                              |
| `GET /api/pages/manufacturer/<slug>`, corporate entities    | `collect_titles` with any-Model semantics                                                     | PR.DETAIL                                                                                        |
| the other 15 dimension detail routes                        | four card schemas, two list mechanisms, no shared path                                        | PR.DETAIL                                                                                        |
| `GET /api/pages/manufacturers`                              | `MfrFilters`, already carries `location`                                                      | unchanged                                                                                        |
| `GET /api/models/` (the list route)                         | internal API, **eight** detail-route consumers, one blessed external consumer                 | freed by PR.DETAIL, then becomes [the public filtering API](#after-v1--the-public-filtering-api) |
| `GET /api/export/models/`                                   | the documented public API. Ships every edge unfiltered, rate-limited per IP                   | **unchanged.** A bulk export is not a filter surface                                             |
| [Articles](../catalog_data_model/Articles.md) dynamic lists | unbuilt                                                                                       | a stored filter over the same key space                                                          |

The export API stays out of it deliberately. It already carries `model_relationships[]` and `export_markets[]` in full, so nothing here is missing from it — what The Flip lacks is not data but a way to ask a question, which is the filtering API's job and not the export's.

## ✅ DONE: <a id="pr-pre"></a>Pre-refactors

Four commits, each separately reviewable, each shrinking PR.HET's blast radius without changing what any query returns — all landed on main (PR #669) ahead of the proving commit:

### ✅ DONE: <a id="pre-guard"></a>PRE.GUARD

One spelling per guard in `_title_facets.py`. `_count_player` and `_count_hierarchical` re-spell the count-hygiene guard by hand (`variant_of__isnull=True` plus active), invisible to a grep for `_MODEL` or `_MODEL_COUNT_GUARD`. Route them through `_MODEL_COUNT_GUARD`, so PR.HET's "list exclusion comes off, count hygiene stays" split becomes a symbol-level edit instead of a per-site judgement call.

### ✅ DONE: <a id="pre-abbrev"></a>PRE.ABBREV

The title-abbreviation predicate arm becomes an `Exists`. Behaviourally identical today, and it is what makes `title_own_match_q` single-valued so the same object can later serve as a row-level boolean. Landing it separately de-risks the name-predicate commit.

### ✅ DONE: <a id="pre-vocab"></a>PRE.VOCAB

No non-ORM identifier says "machine" when it means Model. `TitleDetailSchema.machines` → `models`, `serialize_title_machine` → `serialize_title_model`, plus locals and frontend consumers. The theme/taxonomy page schemas keep their `machines` field because PR.DETAIL deletes those payloads; the ORM layer (`MachineModel`, `machine_models`, `target_machine` and its published export mirror, with their frontend mirrors like `machineTarget`) keeps its names per the CLAUDE.md rule.

### ✅ DONE: <a id="pre-card"></a>PRE.CARD

`GameCard` replaces `TitleCard` and `MachineCard`. Pure frontend: the unified styling and the registry-derived href, with every call site passing a literal `entity_type` until the wire carries one. 21 importing files change appearance and deserve eyeballing in their own diff, not inside PR.HET's. Its specification lived in this document until it shipped; `GameCard.svelte` and `GameCard.dom.test.ts` are the source of truth.

## ✅ DONE:<a id="pr-het"></a>PR.HET — heterogenous results

Everything in this section ships in one PR — except the card unification, extracted to [PRE.CARD](#pre-card) — because the card schema forces it. Change the schema and `_serialize_card` moves; `title_search_section` composes `ordered_titles()` with `_serialize_card`, so global search moves with it; the frontend consumes that schema, so the cards move, and 13 files import `MachineCard`.

### ✅ DONE: <a id="commit-het-prove"></a>COMMIT.HET.PROVE — prove the foundation

Three decisions carried the risk, because everything else is built on them and reversing any one means rewriting the seam the rest sits on: the **row shape** (`.union()` or a Python merge — `count`, offset pagination, hydration and the base each facet counts over all read off it), the **facet grain** (card counts or Model counts, the difference between one facet engine and two), and **how each Title's live-Model total is obtained**, the denominator a card count needs. All three were settled by measurement, and the answers are recorded below.

#### <a id="prove-answers"></a>The answers

The proving work lives in `apps/catalog/api/_game_rows.py` (the two-set split, the three rungs, the row seam), `test_game_rows.py` (every rung, the two-set split's three traps, multi-select, the badge == result-count invariant including under an active `q`, and the two lifecycle states the Title-grain listing never faced: empty active Titles, and live Models under deleted Titles), and the harness `apps/catalog/tests/benchmark_game_rows.py` (run from `backend/` as `uv run python -m apps.catalog.tests.benchmark_game_rows`; it lives in the exempt tests layer because a management command may not import the api layer), which prints these figures for whatever `DATABASE_URL` points at — re-run it rather than trusting these numbers. It survives PR.HET as the standing instrument, minus the union arm and the Title-grain baseline, both of which went when the code they timed was deleted. Every correctness prediction in this document is checked by the harness on both backends — the listing counts (6,180 unfiltered, vifico 13, chicago-gaming 15, williams 487, solid-state 1,432, fantasy 396, `q=godzilla` 3) and the no-filter badge sum of 6,147 per totals method.

**[The production figures](#railway) are the live ones; the figures in this subsection are a dev host against a scrubbed prod-shaped Postgres** (6,180 Titles / 6,913 live Models — the same catalog as this document's other figures), medians of 5 after a warmup. They are kept because two of them can no longer be reproduced anywhere: the merge-vs-union head-to-head, since the union is deleted, and the Title-grain baseline below, since `_title_facets.py` and `ordered_titles` went with the old listing. Those two comparisons exist only here.

**This is slower than the Title-grain system, by design — but the cost lands on filtered requests, not the unfiltered page.** The rule computes something the old system never computed at all — a per-Title unanimity count over the Model join — and card rows need a Model query beside the Title query. But the unanimity aggregates run only when a Model-only dimension is active (the vacuity conditional in `title_rows_qs`), so the unfiltered listing stays a plain active-Titles query plus one cheap Model-rows query. Head-to-head on the same container, row layer only:

| path (no filter)     | Title grain today | card grain             | delta     |
| -------------------- | ----------------- | ---------------------- | --------- |
| listing page + count | 16.4 ms           | 22.7 ms (merge)        | **+38%**  |
| manufacturer facet   | 17.3 ms           | 36.0 ms (grouped join) | **+108%** |

So the hottest path — the unfiltered listing — is barely slower, the facet fan-out is about 2× (and its no-filter case is cached, rebuilt only on catalog edits), and filtered listing requests run 15–21 ms against a 16.4 ms unfiltered baseline. Roughly 1.4–2× at the row layer where the new work actually runs is the price of the feature, not an implementation accident, and the user-visible delta is smaller still because the row layer is only part of a request — hydration, serialization and HTTP are unchanged between the systems. The ratios did survive the hardware change: Railway measured 1.6–2.2× this host on every path, [below](#railway).

**1. Row shape: the Python merge — confirmed on Railway, [below](#railway).** Both seams work on both backends, so this was decided on speed and simplicity rather than survival, and the picture is mixed rather than one-sided. On filtered requests — where the row algebra actually runs — the merge wins clearly (Postgres page+count: `tech_gen=solid-state` 21.1 ms vs 31.2, `manufacturer=williams` 15.0 vs 26.6), because the union runs the whole algebra twice per request (once for the page, once for `count`) while the merge materializes the four-column rows once and `count` is the list's length (the `_count_manufacturer` precedent, and the same ~6k-row ceiling). On the unfiltered fast path the union wins (17.0 ms vs 22.7): with no aggregates to run twice, the union's page query is nearly free while the merge still materializes all ~6.2k rows. The merge takes it — the filtered gap is the larger one and the filtered path is what the feature exists for — and the split result is what sent the decision to Railway before it was called final. Findings that stay true for whoever revisits this: `.union()` demands `.order_by()` cleared on both arms (SQLite rejects ORDER BY inside compound arms) and then takes the full `nulls_last` ordering on both backends; the union's `count()` was verified to wrap the identical combined subquery the page slices (membership predicates intact, ordering dropped); and the two seams order ties differently — the union inherits each backend's collation (Postgres `en_US` sorts "De Luxe" after "Deluxe"; SQLite is code-point), while the merge sorts on a diacritic/case-folded name key, backend-independent, which is the ordering that ships.

This was the one decision of the three that trades database work against app work — the merge moves every matching row's four columns per request (~6.2k rows, 200–400 KB) and sorts them in Python, where the union moves one page plus a count — so it shipped at medium confidence and went to production for the real numbers. **Revisiting it means writing the union again.** It is not recoverable from history: the commits that carried it were squashed into the single engine commit, whose tree holds only the merge. What outlived the code is the paragraph above, and that is the half that was expensive to learn — so a re-do is an afternoon's work rather than a rescue, and [the production measurement](#railway) is the reason not to spend it.

#### <a id="railway"></a>The Railway re-measurement

Run in-container against the production database, on the whole branch deployed to the live service, medians of 5 after a warmup. Railway comes in at **1.6–2.2× the benchmark host, uniformly** — no path degraded out of band, and all seven predicted listing counts plus the 6,147 badge sum reproduced against the live catalog:

| path                             | dev host | Railway    | ratio     |
| -------------------------------- | -------- | ---------- | --------- |
| listing, no filter               | 22.7 ms  | 36.2 ms    | **1.60×** |
| listing, `tech_gen=solid-state`  | 21.1 ms  | 43.2 ms    | 2.05×     |
| listing, `manufacturer=williams` | 15.0 ms  | 26.2 ms    | 1.75×     |
| fan-out, no filter               | 192 ms   | 358.7 ms   | 1.87×     |
| fan-out, filtered                | 60–98 ms | 102–213 ms | ~1.7–2.2× |

**That table answers the question the head-to-head was going to answer, so the head-to-head was not run.** The two costs the provisional flag was hedging against — row transfer and the app-side parse-and-sort — are both maximized by the unfiltered listing, which moves all ~6.2k rows and sorts them. If either carried a penalty specific to Railway's hardware or its app-to-database network, that path would have degraded worst. It degraded **best**, and by less than the facet fan-out, which is pure database work with no transfer and no app-side sort. The app-CPU and transfer side therefore scales no worse than the database side does, which is exactly what the flag was uncertain about. Applying the measured 1.6–2× band to the head-to-head figures above leaves the trade where it was: the union still takes the unfiltered path by ~9 ms and still loses the filtered paths by ~16–23 ms. **The merge is final; a flip would need new evidence, not this measurement.**

End-to-end confirmation from outside, TTFB against a ~565 ms network floor: `/api/games/?page=1` costs ~65 ms of server work against 36.2 ms at the row layer, and `/api/pages/games?manufacturer=williams` ~145 ms against 128 ms — so hydration, serialization and the wire add ~17–29 ms on top of the row layer, and the whole system reconciles with the harness. The no-filter `/api/pages/games` costs ~15 ms against the 358.7 ms it would take to compute, which is the facets cache doing its job.

**2. Facet grain: card counts.** The no-filter manufacturer facet at card grain costs 36–42 ms on Postgres against 17.3 ms for the Title-grain rollup it replaced, on the same container — about 2×, and an order of magnitude under the ~280 ms failure mode it had to clear — the correlated first-model subquery that `_count_manufacturer` ran ~2× per Title before an ordered-scan rollup replaced it at ~11 ms. The filtered fan-out — the one that is actually served live, since the no-filter payload is cached — costs 13–16 ms. The badge == result-count invariant holds at card grain and is pinned by tests, including the two-set-split cases where unanimity reads `model_only` while contributions read `carding`. The complexity price was ~120 lines including all three totals methods, so card counts are affordable and the badges mean what the page shows. Unlike the seam decision, this one is environment-robust — both sides of the 2× are database work — and the ratio did travel: 1.87× on Railway. The twelve-facet fan-out it implies is the number to watch as dimensions are added, measured at 358.7 ms unfiltered (cached) and 102–213 ms filtered; the shared totals dict below is the first lever if that needs shaving.

**3. Live-Model totals: the grouped join.** All three methods return identical results everywhere (pinned by a test) and land close together — Postgres no-filter: aggregate 36.4 ms, grouped join 36.0, scan 41.7; filtered: 13.3 / 15.5 / 22.1. Decided for the grouped join on a structural property the timings don't show: its totals query (`Model` grouped by `title_id`, no filter inputs) is the same for every facet, so the twelve-facet fan-out computes it once and shares the dict, where the aggregate method recomputes totals inside each facet's own `GROUP BY`. The scan stays the fallback shape; **denormalization is rejected** — the measurement it was waiting on came back three ways affordable, so it buys nothing for the price of a migration plus an invalidation path.

Two ancillary questions this section carried are settled by the shape that won. The `ExpressionWrapper`-accepts-`Exists` question is moot: nothing needs a row-level boolean annotation, because rung 2's "its Title did not card" is `exclude(title__in=<rung-1 queryset>.values("pk"))` — a grouped-`HAVING` subquery that compiles on both backends. And "what `count` counts" is the final card-row algebra, verified on both seams as above.

### Outcome — where it landed

Everything below this PR's proving commit is implemented on the branch; the code and its tests are the source of truth now. The detailed subsections this document used to carry (the two-set split, the name predicate, the three rungs, rows at card grain, facet counts, serialization, global search, the frontend, the renames, the deletion list, the done condition) were removed when they landed — git history has them if the reasoning behind a line ever needs excavating. The map:

| what                                                       | where                                                                                                                                                                                                                                                                                                                   |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| filters, the two sets, the three rungs, row production     | `apps/catalog/api/_game_rows.py` — the two-set split, the empty-Title vacuity rule and the closed `ModelDimension` / `TitleDimension` key vocabularies are documented in its docstrings                                                                                                                                 |
| the facet fan-out at card grain                            | `apps/catalog/api/_game_facets.py` — one cell algebra for all eleven counted facets, the Title-only vacuous branch, hierarchical ancestor explosion, shared per-request inputs                                                                                                                                          |
| wire contract, hydration, endpoints, global-search section | `apps/catalog/api/games.py` — `GET /api/games/`, `GET /api/pages/games`, `GameCardSchema` discriminated by `entity_type`, the description-tier carve-out                                                                                                                                                                |
| behavior pins                                              | `test_game_rows.py` (rungs, shared class, the dimension-activation registry), `test_game_facets.py` (badge == result-count across every dimension, plus the completeness and fixture-coverage guards), `test_api_games.py` (wire shape, create gate, N+1 guard), `test_api_search.py` (the heterogeneous games section) |
| shared test fixtures                                       | `apps/catalog/tests/game_builders.py` (extracted from the deleted `test_title_facets.py`)                                                                                                                                                                                                                               |

Done condition, audited at completion: 1 listing card schema (`GameCardSchema`), 1 card component (`GameCard`), 0 components branching on `entity_type` (two pre-existing delete-page href builders are tracked as a separate cleanup), 1 function producing listing rows (`game_rows_merged`), 1 name/alias predicate family, representative Model display-only, 0 occurrences of `TitleCardSchema`, `GET /api/titles/` and `GET /api/pages/titles` gone. Grep survivors that are **not** missed deletions: `model_count` lives on the Manufacturer/System/TitleRef schemas, `YearBoundsSchema` on the manufacturers facet payload and `apply_dimension` in `_manufacturer_facets.py` — different surfaces, out of scope by the product doc's own line.

Verification results are recorded in [Verification](#verification).

Three landings that weren't in the spec, worth knowing before touching the engine:

- **`.filter(isnull=False)`, never `.exclude(isnull=True)`, on multivalued paths.** Django compiles the exclude form to a NOT-IN subquery; on the person and theme facets that measured ~40× slower (no-filter fan-out 1,437 ms → 192 ms on the proving host). The query sites carry comments.
- **`Title.entity_type` and `MachineModel.entity_type` are `ClassVar[Literal[...]]`** so the wire contract's `Literal` is satisfied from the registry ClassVars, with no casts and no re-spelled literals.
- **The facets cache is rekeyed** to `catalog:games:*` (`games_facets_key` in `cache.py`), and the create prompt deliberately still says "title" — what it creates is a Title.

## ✅ DONE: <a id="pr-detail"></a>PR.DETAIL — the dimension detail pages

The product doc scopes this by criterion: every dimension detail page carrying a Title or Model listing, which excludes `credit-roles` because it lists People. `locations` is out for the same reason — it lists manufacturers, and manufacturer location is not a dimension here.

### ✅ DONE: <a id="pre-detail-refactors"></a>Pre-refactors

Two zero-behavior-change commits landed ahead of PR.DETAIL, in the PRE.GUARD tradition:

- **PRE.ID** — the games card identifies by `public_id`, not `slug`. `GameCardSchema.slug` → `public_id`, the `GameCard` prop and every consumer. Byte-identical values (Title and Model both default `public_id_field = "slug"`), but `public_id` is the URL-identity abstraction that works for every entity type, and PR.DETAIL multiplies the card's consumers by seventeen. The card-grid loader host (`PaginatedCardLoader`) split from the row host in the same commit — only row lists link by `slug`, so only they constrain on it.
- **PRE.SPEC** — the `FilterDimension` registry, pulled forward from [PR.REL's plan](#the-dimension-cost-and-what-to-do-about-it) because PR.DETAIL is the largest single dimension expansion in the program (~7 keys) and wiring them through the hand-built chain only to re-migrate them one PR later pays the per-dimension tax twice. One declaration per Model-only dimension — activeness, narrower, facet binding, `surfaced` flag — in `MODEL_DIMENSION_SPECS` (`_game_rows.py`); the facet fan-out dispatches value-rows shapes from it, and registry-completeness tests pin bindings to the payload fields and the test vocabulary. All 11 existing dimensions migrated; `surfaced` is `True` for all of them and exists for PR.DETAIL's hidden dimensions.

### Outcome — where it landed (2026-07-31)

Everything in this PR is implemented on the branch; the code and its tests are the source of truth. The planning subsections this document carried (the dimension additions, the embedded-listing shape, the card-set directions, the hierarchy fix, the deletion list) were removed when they landed — git history has them, and the working execution plan lived outside the repo. The map:

| what                        | where                                                                                                                                                                                                                                           |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| the seven hidden dimensions | `MODEL_DIMENSION_SPECS` in `_game_rows.py` — `surfaced=False`, `facet=None`, honored from the query string; wire params on `GameFilterQuerySchema`. The sparse three entered **raw**; bucket semantics remain PR.SPARSE's                       |
| the embed seam              | `register_entity_detail_page` serializes via `(entity, DetailPageContext)`; `with_games()` + `game_list_page()` in `games.py` produce every embed through the listing code path, so an embedded list cannot drift from the listing              |
| page/edit-response split    | `XDetailPageSchema = XDetailSchema + games: GameListSchema` per entity; create/claims-PATCH/delete responses stay slim (pinned by the flipped response-shape tests)                                                                             |
| person roles                | `GameCardSchema.roles`, hydration-populated only under the `person` dimension, pages 2+ included — the pattern PR.REL's relationship-context annotation inherits                                                                                |
| the frontend host           | `GamesSection.svelte` (`pages/record/detail/`): SSR-seeded page 1, pages 2+ from `GET /api/games/` with the pin applied, threshold-gated debounced `?q=` search round-tripping through the URL                                                  |
| behavior pins               | `test_page_endpoints.py` (embed == listing, `q` passthrough, subgeneration OR-arm, the production-status variant case, game-format raw semantics), `test_api_games.py` (roles, hidden dimensions), the flipped response-shape and restore tests |

Decisions taken in flight with the product owner (2026-07-30/31):

- **Search box on all 17 routes**, threshold-gated (`count >= 12`) — uniform, so no per-route search flag exists.
- **No flat pages remain.** Every route embeds page 1 (`DEFAULT_PAGE_SIZE`) + count; a short list fits inside page 1 and behaves exactly like the flat page it replaced.
- **Converged copy**: heading "Games (N)", empty state "No games…".
- **Naming**: detail-page payloads are `XDetailPageSchema`; the paginated card wrapper joined the `<Entity>ListSchema` family as `GameListSchema` — "Page" in a schema name now only ever means a detail page's payload.
- Two of the nine client-paginated routes needed **no new dimension**, only call-site renames (`technology-generations` `type` → `tech_gen`; `gameplay-features` `feature` single → repeated).
- The person page's undocumented liveness gap — credits on deleted Models and on Variants carded — closed by construction under the listing semantics, and is pinned.

Done condition, audited at completion: the eight axes of [the variation being removed](#the-variation-being-removed) read 1 — one card schema, one card component, one grain rule, one list source (the embedded page 1), one pagination path, one hierarchy behavior, one variant policy, one sort. The deletion grep is clean (`collect_titles`, `serialize_title_ref`, `RelatedTitleSchema`, `PersonTitleSchema`, `TitleRef`, both accumulators, `TitleList.svelte`, `PaginatedSection.svelte`, the nine per-route loaders, `SearchableGrid` on manufacturers/people/corporate-entities, the `include_variants` fetch flag). The frontend has **zero** consumers of the `GET /api/models/` list route, which is now freed for [the public filtering API](#public-filtering-api). The surviving `variant_of` guards are count hygiene and representative selection only — the two jobs the rule deliberately leaves untouched.

Verification, live at the dev API: every migrated page's embed equals its pinned listing exactly. `/themes/racing` 337 (was 10 — the hierarchy fix), `/themes/sports` 1,422 (was 1,163), `/themes/medieval` 27, `manufacturer/vifico` 13 Model cards linking to Model pages (was 13 Gottlieb Title cards), `chicago-gaming` 15, `technology-generation/solid-state` 1,432 — the predicted count exactly — and `q` composes with every pin.

### The variation being removed

The point is not fewer lines, it is fewer things that can disagree. Eight axes, each now reading 1 (this table was the specification and is kept as the done condition's ledger):

| axis                    | was                                                                                     | now                                               |
| ----------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------- |
| backend card schema     | 4 (`TitleModelSchema`, `RelatedTitleSchema`, `PersonTitleSchema`, `TitleRef`) + listing | 1 — `GameCardSchema`                              |
| frontend card component | 2 (collapsed by PRE.CARD)                                                               | 1 — `GameCard`                                    |
| grain                   | mixed, untracked                                                                        | 1 — the roll-up                                   |
| list source             | embedded (8) vs second client call (9)                                                  | 1 — embedded page 1                               |
| pagination              | none (8) vs `createPaginatedLoader` (9)                                                 | 1 — seeded loader continuing on `GET /api/games/` |
| hierarchy               | listing expands descendants; detail pages direct tags only                              | 1 — the listing's                                 |
| variant policy          | `variant_of__isnull=True` hand-written per queryset                                     | 1 — rung 3                                        |
| sort                    | accumulator/prefetch order, franchises/series undefined                                 | 1 — the listing's                                 |

## <a id="pr-rel"></a>PR.REL — the relationship vocabulary

The catalog stores these relationships three different ways and the split should be invisible at the read layer. It already is in the editing interface.

**An edge is `(subject, relationship_type, direction, target)`, with `license_status` as an orthogonal payload axis.** Two operators here — select and flip direction — over one closed key set. Exclusion is [not in V1](ModelFiltering.md#exclude-relationships).

| question                     | predicate                                       |
| ---------------------------- | ----------------------------------------------- |
| only bootlegs                | `EXISTS out-edge (copy, unlicensed)`            |
| Models that have been copied | `EXISTS in-edge (copy)`                         |
| Variants of Godzilla         | `EXISTS out-edge (variant_of, target=godzilla)` |

### The key space

| keys                                              | source                        | kind                 |
| ------------------------------------------------- | ----------------------------- | -------------------- |
| `variant_of`, `remake_of`, `export_edition_of`    | `MachineModel` lineage fields | derived from `_meta` |
| `conversion`, `conversion_kit`, `copy`, `retheme` | `RelationshipType`            | derived              |
| `bootleg`, `licensed_build`                       | type × `license_status` cells | **declared**         |

`export_market` is **not** in this key space — see [Deferred](#deferred). It targets a Location rather than a Model, so it has no direction axis and does not compose with the three operators above.

Nearly all of this is already introspectable and should be introspected rather than described a second time. The lineage fields carry both forward and reverse names in `_meta`; `RELATIONSHIP_TYPE_BEHAVIOR` is already a per-value forcing table with an exhaustiveness test, so a new relationship type must classify itself before it can reach the vocabulary; the licensing axis is `LicenseStatus.choices`. **The composites are the only irreducible declaration**, because no introspection yields the word "bootleg" for `(copy, unlicensed)`. So the whole thing is one small registry plus two introspections behind a single `edge_q(key, direction) -> Q`.

**Read commit `51b9f90b` before rebuilding this.** It removed `RelationshipChip` — a `NamedTuple(slug, label, relationship_type, license_status)`, a `RELATIONSHIP_CHIPS` tuple and a `relationship_chip_exists(chip) -> Q` helper wired to a `?relationship=` param, about 60 lines. It was deleted for having no frontend consumer, **not** for being the wrong shape. It was right about the hard part and incomplete in two ways: it covered only the edge table, not the three lineage fields, and only the outbound direction. One behaviour of it to carry forward: an unknown relationship slug returned `qs.none()` — the same feel as filtering by a nonexistent tag — rather than a validation error.

`scripts/analysis/catalog.sql` defines `model_edges` and `model_edges_bidir`, the same abstraction worked out once already against real questions. Read them for the modeling and the traps in their comments. They are not a contract — the two vocabularies serve different consumers and may diverge.

**Do not reconcile overlapping edges.** A Model can carry both a lineage FK and a typed edge pointing at the same target; `model_edges` deliberately keeps those as two rows rather than merging them, and the ORM vocabulary should inherit that refusal. Deciding they are one relationship is an analysis-local judgement, and making it here would mean the read layer quietly asserting something the catalog does not record. The consequence to hold: a predicate is an existence test per key, so a Model satisfying two keys is carded once by each — which is correct, and is why the facet counts must tally distinct Models rather than edge rows.

### Direction is load-bearing

**470 live Models have an inbound edge and no outbound one.** A vocabulary without a direction axis returns a confident false for every one of them.

| type                | outbound | inbound |
| ------------------- | -------- | ------- |
| `copy`              | 172      | 147     |
| `conversion_kit`    | 141      | 96      |
| `variant_of`        | 139      | 103     |
| `conversion`        | 137      | 103     |
| `export_edition_of` | 57       | 55      |
| `retheme`           | 38       | 38      |
| `remake_of`         | 24       | 10      |

One asymmetry to encode: 29 of 504 edges name a free-text target because the donor is not seeded, and those exist outbound only.

Both directions are include-shaped, so both ship here.

### The licensing axis is never exposed on its own

Every option names its relationship; licensing appears only as a qualifier on a type that has one.

| type             | licensed | unknown | unlicensed |
| ---------------- | -------- | ------- | ---------- |
| `copy`           | 45       | 122     | 5          |
| `conversion`     | 1        | 136     | 0          |
| `conversion_kit` | 1        | 140     | 0          |
| `retheme`        | 1        | 36      | 1          |

`unknown` dominates because licensing is asserted only where a source proves it — copies made in Spain and Italy carry no `unlicensed` marking at all, not because nobody suspects it but because nobody has sourced it. That refusal to launder an assumption is right, and it means **bootleg returns 5 today**.

Three properties this gives the panel. **No orphan option**: "Authorized (48)" on its own says a machine has _some_ authorized relationship with _some_ other machine, which is not a thought anyone had. **The word does not collide**: "licensed" in a pinball catalog reads as theme licensing first, so the reader-facing qualifier is _authorized_ or _official_, chosen per cell — "official copy" is an oxymoron where "authorized copy" is not. **The named cells need not partition**: 5 + 45 falls 122 short of 172, and that reads as fine because a `(all)` catch-all is sitting there saying the set is bigger. Closing the gap would mean inventing a name for "copy nobody has researched" — a worklist, not a thing to browse.

Only `copy` and `retheme` get qualifiers. The lineage keys have no licensing column at all.

**Rejected: exposing `license_status` as a filter axis of its own**, orthogonal to type — `?edge=copy&license=licensed` rather than only the named composites. The composites are needed for the domain words regardless, so the raw axis is strictly additional surface; it produces the orphan option above as a legal query, it puts a second spelling of "bootleg" in the URL space, and a stored filter would then have two ways to serialize one idea. **This is a reversible call** — the composite registry already resolves to a `(type, status)` pair internally, so exposing the axis later is additive rather than a re-design.

**Define a composite by the predicate it means, then let the data fill in.** `(copy, unlicensed)` and `(copy, NOT licensed)` are both defensible readings of "bootleg" and they differ by more than a hundred Models right now. Pick on domain grounds and hold it, rather than picking whichever currently returns a satisfying number — otherwise the key's meaning changes silently under future ingest. A composite whose cell is nearly empty is still a legal key: returning five results is a correct answer about what the catalog currently knows.

### The panel

A flat checkbox list, one entry per key, composing with every other dimension exactly as any facet does — `edge=copy` crossed with `manufacturer=` or `year=` needs no new concept.

Reader-facing copy is largely done. [`relationship-phrase.ts`](../../../frontend/src/lib/entities/relationship-phrase.ts) is the declared single source, carrying every (edge kind × license) cell with four slots each, and the three lineage relations have their headings in `model-lineage.ts`. Both already ship on the Model detail page, so the filter renders from them rather than spelling a second vocabulary. What it needs is one more slot per cell: neither existing form works as a checkbox, because the outbound lead dangles ("Bootleg of" — of what?) and the inbound heading reads as outbound in a sidebar, where "Bootlegs" looks like _is a bootleg_ rather than _has been bootlegged_.

### Subordination does per-type semantic work

`copy` and `retheme` subordinate; `conversion` and `conversion_kit` do not. Subordination plays no part in filtering — the roll-up never consults the representative — but it still decides which Model heads a Title card, so `edge=conversion_kit` cards the kit's donor Title whenever every Model under it matches. Test this explicitly: the display consequence varies by type through a derived property rather than a declared one.

The lineage fields are the asymmetric half of this, and one of them is a surprise: `variant_of` excludes a Model from representative candidacy entirely, `export_edition_of` subordinates, and `remake_of` does **neither** — `_is_subordinate_copy` keys on `export_edition_of` and the subordinating edge types only. The Chicago Gaming remakes lose representative status today on the year tiebreak alone (2015 against 1997), a weaker cause than the VIFICO one. Whether `remake_of` should subordinate is a product call to raise; PR.REL must not change it quietly.

### The dimension cost, and what to do about it

**✅ The `FilterDimension` spec exists** — built as [PRE.SPEC](#pre-detail-refactors) ahead of PR.DETAIL rather than mid-PR.REL as this section originally planned, because PR.DETAIL's seven hidden dimensions made it the larger migration. `MODEL_DIMENSION_SPECS` in `_game_rows.py` carries one declaration per Model-only dimension — activeness, narrower, facet binding, `surfaced` — with all eleven existing dimensions migrated; the facet fan-out dispatches value-rows shapes from it and registry-completeness tests pin bindings to the payload fields and the test vocabulary. The structural hole it closes: per-dimension wiring passing valid-but-possibly-wrong string keys — the Literals make an _invalid_ key a type error but could not catch a _wrong valid_ one (review found `series` wired everywhere yet exercised by no test, meaning a `fk="franchise"` transposition would have passed the whole suite). `MULTI_DIMENSIONS` (accumulate vs replace) remains a derived property beside the registry, from `GameFilters`' tuple arity, so a new multi-valued dimension classifies itself; `edge` accumulates (repeated `edge=` params AND, per the coverage ledger). PR.SPARSE's designated-default belongs on the spec when it lands.

Adding a dimension now touches, on the backend: the `ModelDimension` Literal → a `MODEL_DIMENSION_SPECS` entry → `GameFilters` + `GameFilterQuerySchema` + `to_filters()` → and, when surfaced, `GameFacetOptions` + the payload dict + schema in `games.py`. On the frontend (surfaced dimensions only): `FilterState` → `emptyFilterState()` → `PARAM_MAP` → `hasActiveFilters` → `TitlesQuery` / `queryFromUrl` → the chip builder → the sidebar. `edge` is one dimension slot with a key registry and a direction axis behind it — its facet needs a shape the registry doesn't carry yet (per-key existence over the edge relations), added as its first new `FacetBinding` variant.

Do **not** generate the TypeScript half from it. Cross-language codegen here is the giant new subsystem the product doc is afraid of, and the project's own escalation order puts codegen last, after a `_meta` walk and a typed spec. Take the rung that fits and leave the frontend hand-written until it hurts.

One mapping note for `edge`: in the card-grain facet engine a relationship key is an ordinary **multi-valued Model dimension** — value rows distinct per `(model pk, key)`, the reward-types shape — which is what makes "a Model satisfying two keys is carded once by each" fall out of the existing tally with no edge-row de-duplication of its own.

### Stored filters constrain the syntax

[Articles.md](../catalog_data_model/Articles.md) requires a dynamic list to be a stored filter that validates against the real listing-filter vocabulary. That is a live constraint on the syntax: a stored filter has to round-trip against a vocabulary that has since gained keys, and it has to **fail legibly** when a key disappears — a retired relationship type should surface as a broken stored filter with a nameable cause rather than a list that silently goes empty. That is the argument for named keys over raw `(type, status)` tuples, since a key can be deprecated with a message. It also pushes toward flat serializable params over nested target-attribute predicates.

## <a id="pr-sparse"></a>PR.SPARSE — the sparse dimensions

Three dimensions, none needing a relationship predicate. All three enter the listing vocabulary in [PR.DETAIL](#the-dimension-additions) as raw, hidden dimensions (their detail pages need the pin); what this PR adds is the semantics and the visibility — the reserved `unclassified` value, the default-bucket presets and the surfaced sidebar controls.

**Manufacturer location is not among them** — see [Deferred](#deferred), along with export markets. Where a machine was _built_ and where it was _sold_ are different questions over different relations.

**All three are classified only where someone did the work.** Their null means _unclassified_, and the value a reader would assume is barely present:

| dimension           | unclassified, of 6,913 | the value a reader would assume | its actual count |
| ------------------- | ---------------------- | ------------------------------- | ---------------- |
| `cabinet`           | 6,871 (99.4%)          | `floor`                         | 8                |
| `production_status` | 6,737 (97.5%)          | `produced`                      | 10               |
| `game_format`       | 6,279 (90.8%)          | `pinball`                       | 108              |

Read naively, `game_format=pinball` returns 108 against a catalog that is overwhelmingly pinball, and a badge carrying that number misleads.

### `game_format` and `production_status`: unclassified joins the default bucket

**Decided.** All three are visible sidebar filters. The split is between **what the data means** and **what a particular control asks for**, not between one page and another:

- **Stored and displayed semantics are unchanged, everywhere.** Null goes on meaning _unclassified_ — in the export API, the detail serializers, the claims layer, the analytics views and the edit forms. Per the product doc, the read-only detail view still shows nothing at all for the default case, and the edit pages still treat these as nulls. Nothing about this decision writes, displays or infers a value.
- **Designated query presets request both buckets.** A control that offers "Pinball" sends `pinball` _and_ the unset marker. That applies to the `/games` sidebar **and to the dimension detail page** — the product doc names `/game_format/pinball` alongside `/games` as the second thing this fixes, and a detail page is the listing pinned to a dimension, so it inherits the preset rather than being an exception to it.

Stating it as "the listing controls only" would be wrong twice over: it would exclude the detail page the product doc explicitly names, and it would contradict the `FilterDimension` declaration below, which drives the sidebar control, the facet count and the detail page from one place.

The decisive property is that the buckets then **partition the catalog exactly**, which neither raw selection nor exclusion gives. From `mf_sparse_dimensions`:

| dimension           | default bucket, unclassified joined | other classified values | total     |
| ------------------- | ----------------------------------- | ----------------------- | --------- |
| `game_format`       | `pinball` — **6,387**               | 526                     | **6,913** |
| `production_status` | `produced` — **6,747**              | 166                     | **6,913** |
| `cabinet`           | `floor` — **6,879**                 | 34                      | **6,913** |

Every Model lands in exactly one bucket and the reader gets the set they meant. That partition is what the decision rests on, so it is a `model_filtering_checks` invariant rather than an assertion here — `sparse_bucket_does_not_partition_the_catalog` fails the analysis run if any of the three ever stops being a total function.

**The partition is a Model-grain property and does not carry to the badges.** At card grain `game_format`'s badges sum to 6,181 against an unfiltered listing of 6,180 — one over, because a single Title genuinely mixes formats and shatters into two cards. Roll-up absorbs, so a badge sum can exceed the card total whenever any Title disagrees with itself; the buckets partitioning the 6,913 Models is what is being claimed, and it is what the check verifies. Do not restate this as "the badges add up to the catalog" — it is the Models that do. It is also tighter than exclusion: unchecking bingo-pinball would leave shuffle, gun games and rolldowns in the results, where selecting the pinball bucket does not.

**The widening is explicit in the query, not implied by which surface you are on.** The filter vocabulary gains a reserved value meaning _is unset_, and the preset selects two values: `?game_format=pinball&game_format=unclassified`. That is what keeps the two halves from colliding — the bare param `game_format=pinball` goes on meaning exactly `pinball` everywhere, a shared URL round-trips, and a stored [Article](../catalog_data_model/Articles.md) filter serializes the reader's actual intent rather than a surface-dependent reading of it. It is also what the product doc asks for when it says the API must stay able to find true nulls.

**Repeatable params are new work here, not something already in place.** PR.DETAIL adds these three to the listing vocabulary as single-valued raw dimensions, and on `/api/models/` `game_format` is a single `str` — as is every other field on `ModelFilterQuerySchema`. The preset's two-value selection (`?game_format=pinball&game_format=unclassified`) therefore needs `list[str]` handling added for the three, on both surfaces if the shared narrower is to serve both. Not difficult, but it is a line item rather than a free ride on an existing mechanism.

**The designated default belongs on the `FilterDimension` spec**, beside `surfaced` — one declaration driving the sidebar control, the facet count and the detail page, rather than the mapping being spelled in each.

Two consequences to write down at the code site, because both look like bugs to someone reading only half the panel:

- **The null treatment inverts against every other dimension.** Everywhere else missing is not-matching — that is the whole [sparse data shatters](#sparse-data-shatters-and-that-is-wanted) argument, and its virtue is never asserting something unrecorded. These treat missing as matching-the-default. Both are right for their case; the asymmetry is deliberate and needs a comment, like the description-tier one in `_search_sections.py`.
- **It reduces shattering rather than causing it.** Under the mapping `game_format` is a total function, so a Title shatters only when its Models genuinely disagree about format — 6,181 cards over the whole dimension, of which 2 are Model cards, against 619 cards and 7 Model cards for the raw reading. A bucketed dimension can never shatter more than its raw twin, which is why `mf_shatter` counts the raw one.

All three ship. Selecting the default bucket is **not** a no-op — it excludes the minority values, which is the point of offering it: picking "Pinball" drops the 526 Models that are bingo-pinball, shuffle, gun games and the rest. It is simply a small exclusion, because the minority is small:

| dimension           | records outside the default bucket | share |
| ------------------- | ---------------------------------- | ----- |
| `game_format`       | 526                                | 7.6%  |
| `production_status` | 166                                | 2.4%  |
| `cabinet`           | 34                                 | 0.5%  |

Backfilling remains rejected in all three cases: every user-inputtable catalog field is claims-based, so writing `game_format=pinball` onto 6,279 Models asserts a per-Model claim nobody verified per Model. The mapping is a reading applied at query time by one control; it never becomes a stored value.

`game_format` is multi-select — bingo-pinball, slot-machine and video-game are separately meaningful. **No dimension excludes anything by default**; the listing hides nothing until asked.

## <a id="pr-move"></a>PR.MOVE — the route rename

The Svelte listing route moves to `/games`. Detail routes do not, so `routes/titles/` keeps `[slug]` and `new` while the listing files move; `/games` needs no `[slug]` route of its own, because a card links to `/titles/<slug>` or `/models/<slug>`.

Everything else the rename used to carry — the API path, the card schema, the reader-facing labels — landed in [PR.HET](#pr-het). What is left is the route, the redirect, the sitemap and the SEO tails — plus the route-co-located frontend identifiers that still say titles (`TitlesQuery` / `titles-query.ts`, `titleFilterChips`, `TitleFilterSidebar`): they rename to game terms here, when the directory moves anyway, so the files are touched once instead of twice. Their doc comments already say `/api/games/` / `GameFilterQuerySchema`; only the identifiers wait.

**`/titles` would otherwise 404 rather than redirect.** Moving `routes/titles/+page.*` out while keeping `[slug]` and `new` leaves `/titles` as a route segment with children and no index page. The product doc calls for the redirect.

`resolve()` is typed against the generated route tree, so every internal link to the listing fails at compile time rather than at runtime. That is the safety net that makes this a mechanical change.

## <a id="post-v1"></a>After V1

### <a id="public-filtering-api"></a>Public filtering API

The follow-up the product doc names under [Consumers → Public API](ModelFiltering.md#public-api), and the "To discuss" item The Flip left at [mfgtimeline.md item 8](../the_flip/mfgtimeline.md): filtering the catalog is a lot of work to do client-side, because a consumer must first understand the relationships and only then design the filtering.

**Decided: it is `GET /api/models/` repurposed, not a new endpoint** — but **only after PR.DETAIL**, and that dependency is load-bearing rather than incidental.

| today                                                                                                                                                                                            | consequence                                                        |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| On the internal `NinjaAPI`, built `openapi_url=None, docs_url=None` — deliberately not an integration target                                                                                     | unpublished, so nothing is committed to yet                        |
| `ModelFilterQuerySchema` already carries 17 params, including `game_format`, `production_status` and `cabinet`                                                                                   | most of the vocabulary is built                                    |
| **Eight detail routes consume the list route today** — cabinets, display-subtypes, game-formats, gameplay-features, production-statuses, tags, technology-generations, technology-subgenerations | it cannot change shape until PR.DETAIL moves them to `/api/games/` |
| One blessed external consumer: [mfgtimeline.md](../the_flip/mfgtimeline.md) points The Flip at it and says the unpublished endpoints are fine to hit                                             | not a greenfield surface; changes are visible to someone           |

The frontend consumers are the reason the [response shape](#response-shape) below can go from a display shape to an identity-only one at all. While those eight routes render cards off it, it has to keep carrying `thumbnail_url` and the rest. So this is a follow-on to **all three** V1 PRs that touch it: PR.DETAIL frees the consumers, PR.REL supplies the relationship keys, PR.SPARSE completes the shared dimension vocabulary.

**It carries no vocabulary the UI does not have.** The product doc's rule is that the API does not run in advance of the UI, so this endpoint exposes include-only relationship keys for as long as the sidebar does. The conversion-kit exclusion at the top of The Flip's list therefore waits on the exclusion UX, not on this endpoint.

#### It does not apply the roll-up

The load-bearing design point, and it runs the opposite way from the listing.

The roll-up is a **reader-facing display rule** — show the highest-level grouping that satisfies the query, so a browsing human sees one Godzilla rather than four. A machine consumer counting commercially produced machines wants the matching set, flat, at Model grain. Rolling four Models into one Title card would corrupt exactly the count The Flip is building.

So the seam is: **the predicate is shared, the roll-up is not.** The dimension narrowers and the edge vocabulary are one implementation used by both surfaces; the listing applies the roll-up on top and `/api/models/` does not.

That leaves the codebase with two Model filter vocabularies, which is only defensible if they differ by grain rather than by spelling. Today they differ by both: `ModelFilterQuerySchema` says `type`, `display` and `subgeneration` with a single-valued `feature`, where the listing says `tech_gen`, `display_type` and a repeatable `theme`. **Converge the param names when this is published** — and note that doing so is a breaking change for the one blessed external consumer, which is an argument for doing it before publication rather than after.

#### Response shape

Today's `ModelListItemSchema` is a **display** shape: `thumbnail_url` is resolved through `get_minimum_display_rank()`, which means nothing to a consumer joining against its own cached export.

The published shape is identity only — the Model slug plus its Title slug, so a consumer can join at either grain — against their cached copy of `/api/export/models/`. The two surfaces are companions by design: the export carries the records, this one carries the answer to "which ones".

#### Decisions publishing forces, not taken here

- **Whether it moves to `export_api`.** Publishing is what makes it a documented contract, and the internal API's OpenAPI is disabled precisely so external systems get no real-time target. A filtering API is a partial reversal of that posture, so it should be argued rather than assumed.
- **The rate-limit budget.** The export API is 120 requests/hour per IP shared across all export endpoints. Whether a filter API shares that pool or gets its own is a policy call — and note the export's own published description tells consumers to save their copy and work locally, which this endpoint quietly invites them to stop doing.
- **What hardens into contract.** `include_variants` and `ordering` become promises the moment they are documented.

## Coverage ledger

One row per example in [ModelFiltering.md → Examples](ModelFiltering.md#examples), in that document's order, so the two can be read side by side.

**Tier** is what a request hands back. **Filter** returns a set of entities, **Sort** returns the same set ranked, **Distribute** returns counts per value over that set, **Novel shape** returns rows that are not catalog entities. The first three take one filtered set as input, so they are three views of one query and compose for free; a novel shape changes what a row _is_, which is the one place scope has a natural edge.

**Status** is one of four. A PR name and **post-V1** are the plan. **Won't do** is a rejection on the merits. **Elsewhere** means the question is real and this is the wrong surface for it.

Dropping a row is not a status. Cutting something means changing its status to won't-do with a reason beside it.

| example                                               | tier        | status    | covered by                                                                                                                     |
| ----------------------------------------------------- | ----------- | --------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Conversion kits                                       | Filter      | PR.REL    | `edge=conversion_kit` — 139 cards                                                                                              |
| Conversions                                           | Filter      | PR.REL    | `edge=conversion` — 137 cards                                                                                                  |
| Rethemes                                              | Filter      | PR.REL    | `edge=retheme` — 38 cards                                                                                                      |
| Copies                                                | Filter      | PR.REL    | `edge=copy` — 172 cards                                                                                                        |
| Bootlegs                                              | Filter      | PR.REL    | `edge=bootleg`, the `(copy, unlicensed)` composite — 5 cards                                                                   |
| Licensed copies                                       | Filter      | PR.REL    | `edge=licensed_build`                                                                                                          |
| Remakes                                               | Filter      | PR.REL    | `edge=remake_of` — 19 cards                                                                                                    |
| Export editions                                       | Filter      | PR.REL    | `edge=export_edition_of` — 57 cards                                                                                            |
| Filter OUT bootlegs                                   | Filter      | post-V1   | `edge=-bootleg`; [exclusion is not in V1](ModelFiltering.md#exclude-relationships)                                             |
| Filter out conversion kits                            | Filter      | post-V1   | `edge=-conversion_kit`. The Flip's ask — they filter client-side meanwhile                                                     |
| Models that have had bootlegs made of them            | Filter      | PR.REL    | `edge=bootleg:in`                                                                                                              |
| Models that have been copied at all                   | Filter      | PR.REL    | `edge=copy:in` — 147 Models                                                                                                    |
| All the variants of one game                          | Filter      | PR.REL    | `edge=variant_of` + a search term; the roll-up surfaces Variants. No target picker in the panel                                |
| …the same list composed by an Article                 | Filter      | post-V1   | `target=` on the edge subquery — a column on the edge row, no join                                                             |
| Models that have been remade                          | Filter      | PR.REL    | `edge=remake_of:in` — 10 Models                                                                                                |
| Italian bootlegs                                      | Filter      | post-V1   | `edge=bootleg` × manufacturer location, which is deferred                                                                      |
| Bootlegs everywhere                                   | Filter      | PR.REL    | `edge=bootleg` on its own — the unqualified list is the whole ask                                                              |
| The Chicago bingo-pinball industry                    | Filter      | post-V1   | `game_format=bingo-pinball` ships in PR.SPARSE; the Chicago half needs manufacturer location                                   |
| Spanish EM manufacturers                              | Filter      | post-V1   | `tech_gen=electromechanical` ships; the Spanish half needs manufacturer location                                               |
| Models copied across a national boundary              | Filter      | post-V1   | far-end country constraint                                                                                                     |
| One manufacturer's whole output                       | Filter      | PR.HET    | `manufacturer=`                                                                                                                |
| All the variants for a specific manufacturer          | Filter      | PR.REL    | `edge=variant_of` × `manufacturer=`                                                                                            |
| The rise of the remake industry                       | Distribute  | post-V1   | needs a decade dimension; `year` is a min/max range today, not a counted value list                                            |
| How export models were adapted to different laws      | Distribute  | post-V1   | the reward-type sidebar over `export_market=italy`, once export markets ship                                                   |
| All the Williams models copied by other firms         | Filter      | post-V1   | negated far-end manufacturer                                                                                                   |
| Models copied by Spanish firms                        | Filter      | post-V1   | far-end country                                                                                                                |
| Conversions built from Gottlieb donors                | Filter      | post-V1   | far-end manufacturer                                                                                                           |
| Conversion kits that fit an EM model                  | Filter      | post-V1   | far-end technology generation                                                                                                  |
| Models that are both a copy and a conversion          | Filter      | PR.REL    | repeated `edge=`, ANDed                                                                                                        |
| Models that were both remade and copied               | Filter      | PR.REL    | `edge=remake_of:in` + `edge=copy:in`                                                                                           |
| The most copied models of all time                    | Sort        | post-V1   | inbound-copy `Count` annotation plus a `sort` param. Tops out at 4 today, with ties                                            |
| The most copied titles of all time                    | Sort        | post-V1   | the same annotation rolled to Title grain                                                                                      |
| The manufacturers that have been copied the most      | Distribute  | post-V1   | target-side facet count rooted at `ModelRelationship`. The engine supports it; nothing exposes it                              |
| The first variant ever created                        | Sort        | post-V1   | `edge=variant_of&sort=year`                                                                                                    |
| The widest gap between an original and its copy       | Sort        | post-V1   | target year minus subject year, annotated onto the edge. Becomes a novel shape if it cannot be                                 |
| The average variant count per model, per manufacturer | Novel shape | won't do  | a per-manufacturer average is not a catalog row                                                                                |
| Manufacturer pairings                                 | Novel shape | won't do  | both marginals come free from Distribute; only the pairing is missing, and it wants a matrix or chord diagram. Author as prose |
| Models whose donor is unknown                         | Filter      | elsewhere | 29 label-only edges. A predicate over what the catalog _doesn't_ know — a curator worklist, not a reader-facing facet          |
| Export editions with no export market recorded        | Filter      | elsewhere | same, and a `NOT EXISTS` across two relations. Currently 0 rows — the catalog is clean here                                    |
| Copies with no licensing status                       | Filter      | elsewhere | 122. A research to-do; the `(all)` catch-all means the panel doesn't need it to make its counts add up                         |

Forty rows against thirty-nine examples: "all the variants of one game" splits, because the reader-browsing form and the stored-list form have different costs and only the first is free.

**The one row still genuinely undecided** is the widest original-to-copy gap. If the year delta annotates onto the edge it is an ordinary sort key; if it cannot, the question wants a row per _pair_ and lands with the manufacturer pairings as a won't-do.

## ✅ DONE: <a id="tests"></a>Tests

Landed as specified; the suites in the [PR.HET outcome map](#pr-het) are the source of truth. The three exact-key-set assertions flipped in both directions as predicted (`entity_type` arriving, `model_count` leaving). Review then added the completeness and fixture-coverage guards described under [the dimension cost](#the-dimension-cost-and-what-to-do-about-it), after finding `series` wired everywhere but exercised nowhere.

## ✅ DONE: <a id="verification"></a>Verification

All executed at completion, live at the API and in the browser. Every predicted value reproduced exactly: `q=Godzilla (Pro)` and `q=Rock Encore` return their Model rows, `?manufacturer=vifico` 13 (was 0), `?manufacturer=chicago-gaming` 15 (was 2), `manufacturer=williams` 487, `tech_gen=solid-state` 1,432, `theme=fantasy` 396, the unfiltered listing 6,180 and `q=Godzilla` 3, unchanged. `q=Remake` returns 14 (the plan guessed "about six"; the catalog had more).

The eyeball tokens, and the judgement call on them: `q=pro` 106 → 91 (Model `(Pro)` names arrive, Pro-something manufacturer matches leave); `q=rock` 95 → 42 (the Rock-Ola catalog belongs to the manufacturer facet, not the search box); `q=williams` 470 → **0** — checked against the data and not a bug: no Title or Model name or abbreviation contains "williams", so every old match was the representative-manufacturer arm. The new predicate reads as intended.

## <a id="deferred"></a>Deferred

- **Exclusion on relationship keys** — `edge=-bootleg`, as a visually separate group rather than a hidden third state on the same checkbox. [Not in V1 by product decision.](ModelFiltering.md#exclude-relationships) Open when it gets designed: whether it ships as one negative key per type, or as a named preset, since "not a copy, not a re-theme, not a conversion kit" is really the single idea _distinct original machines_.
- **Relationship context on a Model card.** Under a relationship filter the interesting fact about a copy is what it _copies_, and that is the edge target rather than the parent Title — so `edge=copy` returns a page of Model cards that do not say what any of them copied. Deliberately not solved by naming the parent Title, which is a different fact and often the wrong one. Revisit once PR.REL ships and the page can be looked at.
- **Far-end constraints.** Target _identity_ is a column on the edge row and nearly free; target _attributes_ need a join. Their absence is why the four far-end rows in the ledger sit at post-V1.
- **Manufacturer location as a dimension** — where a machine was _built_, via `MachineModel → CorporateEntity → CorporateEntityLocation → Location`. Deferred by product decision; the manufacturers listing already filters on it. Its absence holds three ledger rows at post-V1: Italian bootlegs, Chicago bingo-pinball, Spanish EM manufacturers.
- **Export markets as a filter.** `ModelExportMarket` targets a Location rather than a Model, so it stays outside the PR.REL edge vocabulary and carries no direction axis. The Model-to-Model half of the export story ships as the `export_edition_of` lineage key.
- **Sort and distribute.** Ranking needs a `sort` param and a per-key annotation; remakes-by-decade needs a decade dimension; manufacturers-copied-most is a target-side facet count rooted at `ModelRelationship`. Every Sort and Distribute row in the ledger waits on these.
- **Token and punctuation-insensitive matching**, then **edition synonyms** (LE ↔ Limited Edition and a small closed set like it). The naming convention is `Name (Edition)`, so substring matching can never match `"<name> <edition>"` — a single colon is enough on its own, and the Model "The Getaway High Speed II" does not substring-match its Title "The Getaway: High Speed II". Additional to the existing diacritic folding, which is Postgres-only and whose dev/prod gap should not be widened.
- **Trigram indexing** on Model and Title names, if search latency regresses at full catalog scale. Today's `ILIKE '%x%'` cannot use a btree index either, so this is not a new problem being introduced.
- **A public filtering API** for consumers like The Flip. Shaped in [After V1](#after-v1--the-public-filtering-api): `GET /api/models/` repurposed, at Model grain with no roll-up. It depends on **all three** of PR.DETAIL, PR.REL and PR.SPARSE — DETAIL frees its eight existing consumers so the response shape can change, REL supplies the relationship keys and SPARSE completes the shared dimension vocabulary.
- **The 128 edition-tier clusters.** Chicago Gaming's Medieval Madness remake tiers are not recorded as Variants where Stern's LE tiers are, so they card individually. A data campaign, not a code change; the rule returns fewer cards as it lands.

## <a id="not-doing"></a>Explicitly not doing

- **Converting the relationship enums into claims-controlled vocabulary entities.** Relationship types are behaviour-heavy, so patch-authorable behaviour columns would hand Title-representative decisions to any contributor, and the privileged-edit protection that would mitigate that is unbuilt. The conversion remains the escape hatch if type growth ever outpaces release cadence.
- **Autogenerated pages keyed on a relationship-type vocabulary** (`/relationship_type/<slug>`). Reaches only four of the ten concepts: it cannot reach the three lineage fields, which have no vocabulary table behind them, nor the composites. It would create two tiers of concept page where filter-backed pages serve all ten uniformly.
- **Editorial pages over the vocabulary, built now.** The long-term home for "every unlicensed copy" is a written page whose prose carries what a bare list cannot — that unlicensed copying was widespread across Spain, Italy and Brazil, and that only a handful of cases are sourced so far. That mechanism is [Articles](../catalog_data_model/Articles.md), and building interim filter-pages with hardcoded prose creates something Articles then replaces. The vocabulary lands first and the packaging follows; the filter ships either way.
