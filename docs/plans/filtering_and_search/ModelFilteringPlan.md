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

## Open questions

**None block starting.** The two that used to sit here — whether facet badges count cards or Models, and what shape produces card-grain rows — are owned by [COMMIT.HET.PROVE](#commithetprove--prove-the-foundation), which exists to answer them with a measurement rather than an argument.

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

That is coherent only while every card is a Title card. The moment a card can be a Model, the rule needs a Model to point at and there may not be one. The product doc's [Multi-select](ModelFiltering.md#multi-select) section settles it: one Model must satisfy everything.

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

Separate the mechanism from the policy, because the difference decides the size of the fix. It is **not** a prefetch that someone forgot: it is an explicit exclusion, written deliberately — `variant_of__isnull=True` appears ~24 times across 13 files under `backend/apps/catalog/`, and within `_title_facets.py` alone the guard is spelled three ways: `_MODEL`, `_MODEL_COUNT_GUARD` and hand-written inline in `_count_player` and `_count_hierarchical` ([PRE.GUARD](#pre-refactors) unifies those spellings before the policy split is attempted). Variant exclusion elsewhere in the backend does two other jobs — count hygiene on taxonomy pages, and representative selection — and **neither may change**, or a theme starts counting Godzilla three times. Only the list exclusion is the policy the rule overturns.

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

## Pre-refactors

Three commits land on the branch before [COMMIT.HET.PROVE](#commithetprove--prove-the-foundation), each separately reviewable, each shrinking PR.HET's blast radius without changing what any query returns:

- **PRE.GUARD — one spelling per guard in `_title_facets.py`.** `_count_player` and `_count_hierarchical` re-spell the count-hygiene guard by hand (`variant_of__isnull=True` plus active), invisible to a grep for `_MODEL` or `_MODEL_COUNT_GUARD`. Route them through `_MODEL_COUNT_GUARD`, so PR.HET's "list exclusion comes off, count hygiene stays" split becomes a symbol-level edit instead of a per-site judgement call.
- **PRE.ABBREV — the title-abbreviation predicate arm becomes an `Exists`.** Behaviourally identical today, and it is what makes `title_own_match_q` single-valued so the same object can later serve as a row-level boolean. Landing it separately de-risks the name-predicate commit.
- **PRE.VOCAB — no non-ORM identifier says "machine" when it means Model.** `TitleDetailSchema.machines` → `models`, `serialize_title_machine` → `serialize_title_model`, plus locals and frontend consumers. The theme/taxonomy page schemas keep their `machines` field because PR.DETAIL deletes those payloads; the ORM layer (`MachineModel`, `machine_models`, `target_machine` and its published export mirror, with their frontend mirrors like `machineTarget`) keeps its names per the CLAUDE.md rule.
- **PRE.CARD — `GameCard` replaces `TitleCard` and `MachineCard`.** Pure frontend: the unified styling and the registry-derived href, with every call site passing a literal `entity_type` until the wire carries one. 21 importing files change appearance and deserve eyeballing in their own diff, not inside PR.HET's. The specification stays in [The frontend](#the-frontend) below.

## PR.HET — heterogenous results

Everything in this section ships in one PR — except the card unification, extracted to [PRE.CARD](#pre-refactors) — because the card schema forces it. Change the schema and `_serialize_card` moves; `title_search_section` composes `ordered_titles()` with `_serialize_card`, so global search moves with it; the frontend consumes that schema, so the cards move, and 13 files import `MachineCard`.

### COMMIT.HET.PROVE — prove the foundation

Three decisions qualify as the riskiest bits, because everything else is built on top of them and reversing any one means rewriting the seam the rest sits on.

**1. Row shape — `.union()` or a Python merge.** `count`, offset pagination, hydration and the base each facet counts over all read off this seam.

**2. Facet grain — card counts or Model counts.** The difference between one facet engine and two. Decided late, every badge changes meaning after the frontend has been built against the other reading. (3) is the cost input to this one, not a separate feature.

**3. How each Title's live-Model total is obtained.** A card count needs that denominator, and there are at least four ways to get it. Measure them against each other:

- a `Count("machine_models", filter=_ACTIVE)` aggregate on the same `GROUP BY` the facet already does — `model_filtering.sql`'s `_mf_title_size` is exactly this shape and it is trivial there;
- a join against a subquery grouping the Model table once;
- the ~7,000-row scan plus Python rollup that `_count_manufacturer` already uses for its own values;
- a denormalized `Title.live_model_count`.

**Do not treat the 280 ms figure as evidence for the last one.** That measurement belongs to `_MFR_SLUG_SQ` / `_MFR_NAME_SQ` ([`_title_facets.py:152`](../../../backend/apps/catalog/api/_title_facets.py:152)) — correlated subqueries that resolve a Title's _representative manufacturer_, which means running the whole `first_model_candidates()` ordering with its subordination `Exists` per Title, twice. A live-child count is a plain aggregate with none of that in it, so the two are not the same query and the old number says nothing about the new one.

Denormalization may still win, but it costs a migration plus an invalidation path on Model create, delete and soft-delete, so it should be the conclusion of the measurement rather than its premise. If it does win, note that it is system-generated like `Location.location_path` and so sits outside the claims layer.

Two things belong in the commit that are not decisions. The **two-set split and the three rungs**, because measuring the wrong semantics produces a worthless number — and because the way that fails is a plausible-looking card rather than an error. And a **benchmark** printing three figures: the no-filter listing page, the no-filter `manufacturer` facet, and a filtered facet fan-out.

Count exactly one facet at card grain — `manufacturer`. It is the only facet with a documented Postgres profile to compare against: `_count_manufacturer` records the correlated first-model subquery running ~2× per Title and dominating the no-filter fan-out at **~280 ms, against ~11 ms** for the ordered-scan rollup that replaced it. Card counts have to come in at that order, at no-filter fan-out. No other facet has a yardstick, so no other facet's timing means anything yet.

Keep out: serialization, the wire contract, `entity_type`, the frontend, global search, the other eleven facets, and every rename. None of them can surprise anyone, and including them delays the answer.

**Performance on Postgres, feasibility on both backends.** The row-shape question is not only which is faster. Django orders a combined query only by columns in its select list, and `nulls_last` compiles to a `CASE` expression on SQLite rather than native syntax — so if `.union()` cannot take the ordering there, the shape is dead regardless of its Postgres timing, because SQLite is what dev and CI run.

Two other things to settle here, both cheap and both shape-deciding. That `ExpressionWrapper(Q(...), output_field=BooleanField())` accepts an `Exists` inside the `Q` and resolves a reference to a sibling annotation — if not, the fallback is a self-correlated `Exists` over `Title` with the annotations applied inside, same single-source property, one extra correlated subquery per output row. And **what `count` actually counts**. (An earlier draft claimed the codebase advises counting before annotating; no such advice exists anywhere in the code — `list_titles` already counts the annotated, `.distinct()` queryset.) Under card grain the annotations and `Exists` expressions _are_ the row-set definition, so there is no earlier unannotated queryset that means the same thing, and stripping them would count a different set. Count the final card-row algebra, then verify it directly: on the union path, read the emitted count SQL and confirm it selects the same set the page slices; on the merge path, `count` is the merged list's length and there is no count SQL to check. Ordering may be dropped before counting; membership predicates may not.

**Write the three answers into this section when it lands.** A proving commit that merges without them recorded did not prove anything.

### Record-local shared dimensions

The product doc's [Dimensions are tested on the record that owns it](ModelFiltering.md#dimensions-are-tested-on-the-record-that-owns-it) sorts every dimension into three classes, and the engine has to keep them apart:

| class                   | dimensions                              | tested on                                                  |
| ----------------------- | --------------------------------------- | ---------------------------------------------------------- |
| **Title-only**          | franchise, series                       | the Title, binding all of its Models                       |
| **Model-only**          | manufacturer, year, tech gen, themes, … | the Model; a Title passes only when every Model passes     |
| **record-local shared** | name, abbreviations                     | the record being decided, propagating in neither direction |

The third is the class an implementation loses, and it is a **class** rather than a quirk of the search predicate. Name and abbreviations are shared because `Title` and `MachineModel` both carry them. If a dimension were ever added to both records — themes on Title, say — it would join this class, and the engine would need an entry rather than a restructuring.

The class has exactly two members, name and abbreviations. `description` is **not** one of them, and naming the class is what makes that legible: description is a field both records carry, but the product doc rules it a tier rather than a dimension, so it never enters the shared predicate at all. Its matches live in the search page's section builders instead, which is why a description match can never suppress the record-creation prompt. `_search_sections.py`'s module docstring already says so — keep that true through the refactor, because a shared field deliberately kept out of the shared class looks like an oversight, and someone will eventually try to "fix" it.

So the engine takes a set, not a search string:

```python
model_only = MachineModel.objects.active().filter(...)      # Model-only dimensions, chained
carding    = model_only.filter(shared_dimension_q(filters)) # + the record-local shared class
```

`carding` is `model_only` plus one conjunct, so this is one queryset built twice rather than two predicates that can disagree. With no shared dimension active the two are the same object and every reference below collapses to one set.

Chaining is **mandatory** for the multi-select dimensions — `.filter(themes=A, themes=B)` joins once, so a single theme row would have to be both, and the result is always empty. Chaining from the `MachineModel` root gives both properties at once: multi-select works, and every dimension lands on the same Model, which is what [Multi-select](ModelFiltering.md#multi-select) requires.

**The candidate set is active Models including Variants**, per the rule. `_MODEL`'s `variant_of__isnull=True` is a policy guard and it comes off. `first_model_candidates()` keeps its own exclusion, so the representative is still always a non-Variant.

### The name predicate

A Model's own name and its `ModelAbbreviation` values join the Title fields already matched. A name is a name: Model names belong in the same tier as Title names, in the same shared predicate the listing and the record-creation gate both consume.

**Two silent Django traps**, both found by measurement, and the obvious implementation hits both. _Annotating across the join creates a second alias_ — `Lower(_Unaccent(F("machine_models__name")))` on the Title queryset gets its own join alias, separate from the one `_MODEL` guards, so the active guard can land on a different Model row than the name match. And _a `Q` traversing `machine_models__abbreviations__value` duplicates rows_ — on the Title queryset that yields two rows per Title with different flag values, which `.distinct()` cannot collapse, breaking `count` and pagination; on the prefetch it duplicates entries in the prefetched Model list, so the card can render the same Model twice.

Use `Exists` throughout, behind a shared name-or-alias helper carrying the existing vendor split (Postgres `Lower(_Unaccent(...))` against `_fold(q)`, SQLite `icontains`):

- `title_own_match_q(q) -> Q` rooted at `Title` — name fold, abbreviation `Exists`
- `model_match_q(q) -> Q` rooted at `MachineModel` — name fold, abbreviation `Exists`

Converting the existing `Q(abbreviations__value__icontains=q)` arm to an `Exists` is behaviourally identical today and is what makes `title_own_match_q` single-valued, so the same object can be reused as a row-level boolean.

**Drop the representative-manufacturer arm entirely.** It exists to serve the parity trap, and the parity trap is a representative-model artefact the roll-up removes. Searching a manufacturer name is what the manufacturer facet is for.

**Broadening the predicate rarely doubles up a Title.** The worry is that a query matching two Models under one Title returns two near-identical Model cards, which can only happen where their names overlap. **Ad-hoc**, counting Titles holding two Models that both differ from the Title's name and where one Model name contains the other: **12 Titles**, of which 3 are a parent and its own Variant — absorbed at rung 3 — leaving **9** that can card twice. The cases are ordinary: _Grande Domino_ beside _Domino_, _Super Soccer_ beside _Soccer_, _Jungle King_ beside _Jungle_. Search therefore never buries a second match behind a first, and needs no de-duplication rung beyond the three the rule already has.

#### The create-prompt gate moves with it, and should

`_query_only_count` counts Titles matching the search term alone, ignoring active facets, and the listing shows "create this title?" when it is zero. It is built as `filtered_titles(TitleFilters(q=filters.q)).count()` — the same predicate search uses, so the two cannot drift. Broadening the predicate therefore moves the gate with no separate change, which is the wanted behaviour: **a search that finds a Model must not offer to create it.**

Today it does. `q=Rock Encore` and `q=Godzilla (Pro)` both return `query_count` 0 against machines the catalog holds, so an authenticated user is invited to create a duplicate of the Model they just failed to find.

The narrow cost is that the prompt creates a _Title_ while what suppresses it may be a _Model_: someone who wants a Title named "Rock Encore" — which exists only as a Model, under the Title _Rock_ — reaches `/titles/new` directly instead of being prompted. That is a curation operation, not a reader failing to find a game.

### The three rungs

Unanimity is measured over `model_only`, never over `carding`:

```python
n_models = Count("machine_models", filter=_ACTIVE, distinct=True)
n_match  = Count("machine_models", filter=_ACTIVE & Q(machine_models__in=model_only), distinct=True)
```

**Rung 1 — a Title cards** when `n_match == n_models`, `n_models > 0`, its Title-only dimensions hold and its own record-local shared values match.

**Rung 2 — a Model cards** when it is in `carding`, its Title did not card and its Title satisfies every Title-only dimension. That last clause is the binding half of the Title-only class and it is easy to drop: without it, `franchise=harley-davidson&manufacturer=sega` returns Sega Models from every franchise.

**Rung 3 — a Variant cards** only when its parent Model is not in `carding`. Inside this branch the Title is known not to be showing and the parent shares the Title's franchise, so "the parent is showing" reduces to "the parent is in `carding`" — which is what makes rung 3 a one-line `NOT EXISTS` rather than a recursion.

Feeding `carding` into the unanimity count silently inverts the product doc's own worked examples rather than erroring. Under one set, `q=Ice Fever` sees the sibling Model _Ice Mania_ fail the name test, loses unanimity and drops to rung 2 — returning the _Ice Fever_ **Model** card where the Title card is specified. `q=Karate Fight` likewise returns the Karate Fight Model instead of the "Black Belt / Karate Fight" Title. Both look reasonable on screen, which is what makes them expensive to find later.

Worked, in the order the product doc lists them:

| filter                                        | rung 1                                                         | result                                                                            |
| --------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `q=Ice Fever`                                 | no Model-only dimension, unanimity vacuous; Title name matches | the _Ice Fever_ Title card                                                        |
| `q=Ice Mania`                                 | Title name fails                                               | the _Ice Mania_ Model card                                                        |
| `q=Ice Fever&theme=X`                         | unanimity over `theme=X` fails                                 | nothing — `carding` is empty, because the only theme-carrier is named _Ice Mania_ |
| `franchise=harley-davidson&manufacturer=sega` | unanimity over manufacturer fails                              | the Sega Models, bound to the franchise at rung 2                                 |
| `theme=monster` over Godzilla                 | unanimity fails                                                | the 70th Anniversary Variant, its parent not in `carding`                         |
| `manufacturer=vifico`                         | unanimity fails on every Title                                 | 13 Model cards                                                                    |

The first three are the whole argument for the split: the shared class decides rungs 1 and 2 independently and constrains neither.

**`Title.first_model_subquery()`, `_MFR_SLUG_SQ` and `_MFR_NAME_SQ` stop being filter inputs.** The representative Model returns to deciding one thing only: which backglass and year a Title card shows.

### Rows at card grain

Two different entity types have to arrive as one ordered, paginated list. The shape that works without materializing the catalog:

1. Two `.values("kind", "pk", "sort_year", "name")` querysets — one for rung 1, one covering rungs 2 and 3, which differ by a clause rather than by shape — each with a literal discriminator.
2. Combine them, ordered by `(sort_year desc nulls last, name, kind, pk)` — the product doc's [Sorting](ModelFiltering.md#sorting) rule, with `kind` and `pk` as the tie-break that gives offset pagination a total order.
3. Slice the page, then hydrate each kind by id with its own prefetch.

`sort_year` is `Max(model year)` for a Title row, matching today's `latest_year`, and the Model's own year for a Model row. It is selected rather than derived because the ordering keys have to be in the select list.

Whether step 2 is `.union()` or a Python merge is [COMMIT.HET.PROVE](#commithetprove--prove-the-foundation)'s first decision. The precedent for the merge is `_count_manufacturer`, which pulls ~7k rows and rolls up in Python precisely because the clever SQL was 25× slower. Hydration is unchanged either way.

### Facet counts

Each facet keeps the N-1 rule and changes what it tallies. Per dimension: group the matching Models by facet value and Title, compare each group against that Title's live-Model total, tally unanimous Titles as one card and the rest as one card per Model, less absorbed Variants. `mf_card_counts` is that computation in SQL and is the reference for what the badges should say.

**The two-set split survives into the facet counts.** A record-local shared dimension is a dimension like any other under N-1, so it stays active while the others are counted — which means the unanimity comparison runs over `model_only` less the excluded dimension while the per-Model contribution runs over `carding` less the same. Counting both off one set makes every badge disagree with the result page for exactly the queries the split exists to get right. `mf_card_counts` does not model the shared class at all, so it is silent on this and cannot be the reference for it.

Count hygiene still holds — a Title whose three Variants all carry a theme counts once, because it either rolls up to one card or contributes only the Models that matched.

**The fan-out is twelve, and eleven of those carry counts.** `DIMENSIONS` has thirteen entries, but the search term is never excluded or counted; `facet_counts` makes twelve `_facet_base` calls, and of the twelve `FilterOptions` fields `year` returns `Bounds` rather than a counted list. Size the measurement against twelve. One dead wire to resolve while the schema is open: nothing on the frontend consumes those year bounds — `YearRangeInput` takes only its bound min/max props — so PR.HET either wires them into the control or deletes the field, rather than carrying dead weight through the schema rename.

The no-filter payload is cached under `titles_facets_key()`, which is scoped by audience alone — **not** by the active filter set, since `title_facets_response` consults the cache only when `filters == TitleFilters()`. So the cached path costs once per catalog edit and the live cost is the filtered fan-out. Measure that one.

The two facet modules in service — `_title_facets.py` and `_manufacturer_facets.py` — are near-clones already. Counting at card grain makes three, which is where the shared engine gets extracted rather than a third module written.

### Serialization and the wire contract

`_serialize_card` reads `models[0]` off `card_models`. `_card_models_prefetch()` already loads each Title's full ordered Model list with manufacturer and media attached, so **rendering a different Model costs no queries.** That is the cost argument for the whole feature.

The one real addition is that the prefetch is built on `first_model_candidates()` and carries no Variants today. If a card can be a Variant the prefetch has to load them, ordered so non-Variants still come first.

**`model_count` comes off the schema.** It has no answer at card grain — a Model row would have to report its Title's non-Variant count, or 1, or 0, and every option is a different lie — and it turns out nothing needs one: **no component reads a listing card's `model_count`.** The only consumers of a field by that name are `Manufacturer`, `System` and `TitleRef`, which are different schemas on different pages. The card renders name, year, manufacturer and thumbnail, which is what the schema's own docstring says it is for — slim by design, only the fields list rows render. Removing it is the deletion rule applied to a field that was already dead weight rather than a loss.

The card schema gains `entity_type: Literal["title", "model"]`. Not `kind`: the codebase has exactly one channel for "which entity is this and where does it live" — `LinkableModel.entity_type`, codegen'd into `entity-meta.ts` — so the frontend resolves it through the same registry every other polymorphic surface uses, by lookup rather than by branch. **The serializer reads `Title.entity_type` / `MachineModel.entity_type` off the ClassVars and never writes the literals**; the `Literal[...]` is the narrowed wire contract, not a second source of truth.

Two shapes to avoid. A **schema union** forces `anyOf` into the OpenAPI and makes every consumer narrow, for the same information. An **optional `matched_model` ref** leaves `year` / `manufacturer` / `thumbnail_url` describing the representative, so a row reads "Rock Encore · Gottlieb · 1986" with _Rock_'s year — fixing which means moving those onto the ref too, a union in disguise.

`TitleCardSchema` is renamed. A card is either a Title or a Model, which is the either/both case the product doc reserves the word "game" for, so `GameCardSchema` is the right name and `GameCard` the right component. That reverses this document's earlier advice, which read the naming rule as barring "game" anywhere outside URLs and reader copy; the rule is narrower — it bars the word where we mean one specific record type, which this is not. Avoid `CatalogCardSchema`, which overclaims: it does not cover Person or Manufacturer.

### Global search

`title_search_section` composes `ordered_titles()` with `_serialize_card` so name matches rank exactly as the listing does. **It keeps one section rather than gaining a Models section** — a sectioned interface plus an absorption rule fights itself, since suppressing Models whose Title already appears leaves a Models section mysteriously empty for the commonest queries, and not suppressing them makes "Godzilla" appear twice under two headings.

**`tiered_search_rows` needs a new contract, and this is not free.** It is generic over `ModelT: Model`: it slices a `QuerySet`, gates the description tier on `issubclass(ordered_base.model, DescribedModel)`, and de-duplicates with `.exclude(pk__in=seen)`. None of that survives a heterogeneous card list — there is no single `.model`, and `pk__in` de-duplicates within one table when the collision is now across two. It is the same duplicate-key hazard the frontend has at `SearchResults.svelte:42`, sitting somewhere that looks type-safe.

The description tier needs one carve-out to match the product doc: a Title added by a description match must not suppress its own Models, because that Title is not showing _by dimension match_. That is a matter of not routing the description tier through the roll-up rather than new logic.

### The frontend

The card unification itself ships early, as [PRE.CARD](#pre-refactors); its specification lives here so the design and the rule stay together.

**A Model card and a Title card must be visually identical**, per the product doc's card UX call. A Model card that reads as a different kind of object puts us back to teaching the reader our data model.

`TitleCard.svelte` and `MachineCard.svelte` have drifted three ways: `--font-size-1` versus `--font-size-0`, `", "` versus `·` as the separator, and a `showManufacturer` prop plus `UNKNOWN_MANUFACTURER_LABEL` fallback that only `TitleCard` has. Unifying those is the point of the extraction — and once they are unified, **the only thing left that differs between the two cards is the href**, which means there is nothing to branch on.

**`GameCard` branches on `entity_type` zero times.** The link comes out of the registry:

```svelte
href={resolveHref(`/${ENTITY_META[entity_type].entity_type_plural}/${slug}`)}
```

That is the pattern the codebase already uses in seven places — `route-metadata.server.ts:308`, `schema-org.ts:48`, `FacetedCatalogListing.svelte:82`, `CatalogListing.svelte:68` and others — and it is what the project rule against branching on type in shared code actually asks for. `resolveHref` rather than `resolve` is correct here for the documented reason: the route _pattern_ is not known at the call site, which is the one case the wrapper exists for.

So `TitleCard` and `MachineCard` are **deleted**, not kept as href suppliers. Every one of their 21 importing files (23 render sites) changes appearance anyway under the unified styling, so passing `entity_type` alongside `slug` is the same edit either way. An earlier draft of this document said to keep both leaves and put a single branch in the discriminating component; that left three components where the done condition says one, and put an `entity_type ===` test in shared code for a value the registry already resolves.

One interim state to expect rather than work around: the non-listing call sites are detail pages fed by `TitleModelSchema`, `RelatedTitleSchema`, `PersonTitleSchema` and `TitleRef`, **none of which carries `entity_type`**, so those sites pass a literal — `entity_type="title"` — until [PR.DETAIL](#prdetail--the-dimension-detail-pages) converges the schemas and it arrives on the wire. That is a call site stating what it holds, not shared code testing what it was handed, so the zero-branch property is intact. It is also the moment someone will be tempted to keep `TitleCard` as a one-line wrapper "so the call sites don't change". Don't: that is the parallel path the PR exists to remove, reintroduced as convenience.

**A Model card does not name its parent Title**, per the product doc. Of the non-Variant Models, 2,973 share a name with another Model but only 31 stay ambiguous once manufacturer and year are shown — and nearly all of those are apparent duplicate records under identically-named Titles, which the parent Title would not disambiguate either.

Blast radius: 13 files import `MachineCard` and 8 import `TitleCard`; all of them change appearance. The font-size and separator deltas are _required_ for visual identity. Adopting "Unknown Manufacturer" is _chosen_, affects 378 of 6,913 Models (5.5%), and is not a new concept — the listing already shows it for Titles whose representative has none. Eyeball before merge.

#### The shared card must keep `showManufacturer`

It is a capability, not drift. Manufacturer and corporate-entity detail pages do not print the manufacturer on their cards, because every card on the page has the same one and repeating it 487 times is noise. Both routes pass `showManufacturer={false}` today — `manufacturers/[slug]/+page.svelte:111` and `corporate-entities/[slug]/+page.svelte:36`.

**Suppress by not rendering, never by nulling the field.** This is the trap: `manufacturer: null` already means _this record genuinely has no manufacturer_ and renders as "Unknown Manufacturer" for the 378 Models that have none. Encode "don't show it here" the same way and every card on the VIFICO page reads "Unknown Manufacturer". Two meanings, one encoding, and the failure is silent and site-wide on the exact pages this work is fixing.

Suppression stays correct under the roll-up, on both card types: a Title cards on a manufacturer page only when **every** one of its Models matches, so its representative is that manufacturer too, and a Model card is by construction the matching Model. Test it — the property comes from the rule rather than from anything visible at the call site.

Manufacturer is the only field this applies to. Of the four things a card displays — name, year, manufacturer, thumbnail — it is the only one that is also a dimension with a detail page of its own.

#### Two hazards to pin

**The global-search section will throw a duplicate-key error.** `SearchResults.svelte:42` keys on `title.slug`. Slugs are unique per table but not across tables — 5,945 slugs exist in both — so a mixed section can produce two rows with the same key. Key on `entity_type` and slug together.

**JSON-LD is safe only by coincidence.** `buildListingJsonLd` builds `@id`s as `/${entity_type_plural}/${item.slug}` from the _listing's_ key, which is wrong for a Model row — but it emits the `ItemList` only when `pageUrl.search === ''`, and Model rows only exist under an active filter. The guard, an invariant comment and a regression test already exist (`schema-org.ts` and the filtered-URL case in `schema-org.test.ts`); the comment argues from canonicalization, so extend it with the Model-row half of the invariant — under a filter a Model row would otherwise be emitted with a Title-listing `@id`. Nothing else to add.

### The renames in this PR

The product doc requires the system not be left half-migrated. Three renames land here, and none of them is the Svelte route.

**The listing endpoint becomes `GET /api/games/`. The Title resource API stays where it is.**

This is a split, not a wholesale router rename, because `titles_router` is mounted at `/titles/` and owns both:

| route                                                | what it is                   | after PR.HET                    |
| ---------------------------------------------------- | ---------------------------- | ------------------------------- |
| `GET /api/titles/`                                   | the heterogeneous listing    | **moves** to `GET /api/games/`  |
| `GET /api/pages/titles`                              | that listing's page payload  | **moves** to `/api/pages/games` |
| `POST /api/titles/`                                  | create a Title               | stays                           |
| `POST /api/titles/{id}/models/`                      | create a Model under a Title | stays                           |
| `PATCH /api/titles/{id}/claims/`                     | edit a Title                 | stays                           |
| the `{id}` delete-preview, delete and restore routes | Title lifecycle              | stays                           |

Renaming the router wholesale would make `POST /api/games/` create a **Title**, which is the same lie in the other direction — a "game" is not a record type anything can be created as. So the listing GET and the page endpoint move to a new `games_router`, and everything left under `/api/titles/` is genuinely Title-grain. `GET /api/titles/` then ceases to exist, which is correct: there is no Title collection any more, because the collection is not Title-grain.

The move is cheap and unpublished — the internal `NinjaAPI` is built `openapi_url=None, docs_url=None`, so there is no contract and no external consumer, and the listing has five call sites today. It happens now rather than in PR.MOVE because [PR.DETAIL](#prdetail--the-dimension-detail-pages) points every detail page at it; deferring means renaming twenty-odd call sites instead of five.

**The card schema**, per [the wire contract](#serialization-and-the-wire-contract).

**The reader-facing labels.** Add `itemLabel` / `itemLabelPlural` to `ListingInfo` in `frontend/src/lib/entities/types.ts` and set them in `title.ts`, alongside the existing `heading: 'Pinball Machines'` override. `FacetedCatalogListing.svelte` feeds four strings from there (count line, search placeholder, filter drawer, create prompt); `schema-org.ts` already prefers the override; `/manufacturers` shares the component and falls back untouched. Three tails move with it — `routes/titles/new/+page.svelte` hardcodes `entityLabel="Title"`, `search/+page.svelte` hardcodes its placeholder, and `manufacturers/[slug]/+page.svelte:25` builds `Titles (${mfr.titles.length})`. This does not touch the generated `label` / `label_plural`, which come from Django `verbose_name` and reach the admin.

### The deletion list

The product doc's rule is _delete the things that you replace_. This is that list, so it is a grep rather than a judgement call. None of these may exist when PR.HET merges:

| symbol                                                     | why it goes                                                                           |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `TitleCardSchema` (the name)                               | a card is not a Title                                                                 |
| `_MFR_SLUG_SQ`, `_MFR_NAME_SQ`                             | the representative stops being a filter input                                         |
| the `_q_mfr_name` annotation and its arm of the predicate  | the parity trap goes with the representative pin                                      |
| `_MODEL`'s `variant_of__isnull=True`                       | the **list-exclusion** half only — see below                                          |
| `test_q_matches_first_model_manufacturer_not_later_models` | it pins the behaviour being removed                                                   |
| `TitleCard.svelte`, `MachineCard.svelte` and their tests   | `GameCard` replaces both in [PRE.CARD](#pre-refactors); neither survives as a wrapper |
| `model_count` on the listing card                          | no answer at card grain, and no component read it                                     |
| `GET /api/titles/` and `GET /api/pages/titles`             | moved to `games_router`, not aliased                                                  |

Two qualifications, because each looks like the same symbol as something that stays:

- **`_MODEL_COUNT_GUARD` stays.** Variant exclusion does three jobs — list exclusion, count hygiene and representative selection — and only the first is the policy being overturned. Delete the count guard and a theme starts counting Godzilla three times. After [PRE.GUARD](#pre-refactors) it is also the only other spelling in the module, so the split really is a symbol-level edit.
- **`Title.first_model_subquery()` survives as a method** and stops being a filter input. It still decides which backglass and year a Title card shows.

One conditional deletion: `_count_manufacturer`'s bespoke ordered-scan-plus-Python rollup should collapse into the same shared count every other facet uses, but it carries the documented 280 ms → 11 ms history. Delete it only once the replacement is measured at no-filter fan-out.

### Done condition

Each of these reads 1 when the PR is ready. They are countable, which is the point — "consolidated" is not.

| axis                                           | at merge     |
| ---------------------------------------------- | ------------ |
| listing card schemas                           | 1            |
| listing card components                        | 1            |
| components branching on `entity_type`          | 0            |
| functions producing listing rows               | 1            |
| name/alias predicates                          | 1            |
| consumers of the representative Model          | display only |
| occurrences of `TitleCardSchema`               | 0            |
| `GET /api/titles/` and `GET /api/pages/titles` | gone         |

## PR.DETAIL — the dimension detail pages

The product doc scopes this by criterion: every dimension detail page carrying a Title or Model listing, which excludes `credit-roles` because it lists People. `locations` is out for the same reason — it lists manufacturers, and manufacturer location is not a dimension here.

### The variation being removed

The point is not fewer lines, it is fewer things that can disagree. Eight axes, each verified against the routes as they stand, each collapsing to one:

| axis                    | today                                                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| backend card schema     | 4 — `TitleModelSchema`, `RelatedTitleSchema`, `PersonTitleSchema`, `TitleRef` — plus the listing card                                 |
| frontend card component | `TitleCard` imported by 8 files, `MachineCard` by 13 — **collapsed by [PRE.CARD](#pre-refactors)**, which deletes both for `GameCard` |
| grain                   | some list Titles, some Models, and it does not track which record owns the dimension                                                  |
| list source             | embedded in the page payload (8 routes) vs a second client call (9 routes)                                                            |
| pagination              | none (8) vs `createPaginatedLoader` (9)                                                                                               |
| hierarchy               | the listing expands to descendants; detail pages list direct tags only                                                                |
| variant policy          | `variant_of__isnull=True` hand-written per queryset                                                                                   |
| sort                    | `_franchise_titles_qs()` and its series twin never order the Titles at all — only the prefetched Models                               |

That table is the specification and the done condition. "Onto a shared substrate" has no edge; "these eight read 1" does. Seven of the eight are PR.DETAIL's work — the card component collapses one PR earlier, and it is listed here so the axis is not re-opened by a detail page reaching for a Title-shaped card it no longer needs.

### What is actually there today

An earlier version of this document inventoried the backend schemas and inferred the pages, which was wrong in both directions. What the routes actually do:

| pattern                                                                    | routes                                                                                                                                                   |
| -------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **client-paginated** via a second call to `/api/models/` or `/api/titles/` | cabinets, display-subtypes, display-types, game-formats, gameplay-features, production-statuses, tags, technology-generations, technology-subgenerations |
| **flat**, list embedded in the page endpoint                               | corporate-entities, franchises, manufacturers, people, reward-types, series, systems, themes                                                             |

So the pages whose schemas carry no game list mostly do show one — `/game-formats/pinball` paginates against `/api/models/` today. The work is migration and consolidation rather than construction, and "none of them paginate" is false for half of them. One of the nine client-paginated routes is already at Title grain: `display-types/[slug]` paginates `/api/titles/` and renders Title cards, so for that route the change is the roll-up itself rather than a grain flip.

One addition is genuine: `display_subtype`, `tag` and `technology_subgeneration` have no listing param yet and need one, which is what the product doc's [Hidden dimensions](ModelFiltering.md#hidden-dimensions) section supplies. A detail page that _is_ the listing pinned to a dimension cannot exist for a dimension the listing cannot express. That is why hidden dimensions belong to this PR rather than to PR.SPARSE.

### The card set moves in both directions

A reader will otherwise assume the rule only ever adds Model cards.

**Title-dimension pages — franchises and series — keep the cards they have.** Franchise and series are Title-only dimensions, so on those pages no Model-only dimension is active and the unanimity clause is vacuous: every Title trivially satisfies "every one of its Models matches every Model-only dimension" because there are none to match. Same mechanism that makes the unfiltered listing all Title cards. The one condition that could break it never fires — **0 Titles in the catalog have zero live Models.**

**Most Model-dimension pages roll _up_, and return fewer cards.** Themes, systems, reward types, gameplay features and people list games today; under the rule a Title absorbs its Models whenever all of them match.

**Manufacturer and corporate-entity pages roll _down_, and it is a correction rather than a refinement.** They list Titles today through `collect_titles` with any-Model semantics. `/api/pages/manufacturer/vifico` returns 13 cards — Arena, Bad Girls, Chicago Cubs 'Triple Play', Diamond Lady, Excalibur, Genesis and the rest — every one a Gottlieb game, because VIFICO built copies and a copy never heads its Title. Under the rule those become 13 VIFICO Model cards linking to VIFICO Model pages. These two pages carry the [`showManufacturer`](#the-shared-card-must-keep-showmanufacturer) requirement the others do not.

The backend half of today's manufacturer suppression goes away with `collect_titles`, and should. `include_manufacturer` defaults to `False` and **no caller anywhere passes `True`**, so the field is unconditionally omitted server-side and the frontend prop is what actually makes the pages correct. Suppression is applied twice today, and it is the second one doing the work.

### An unchanged card set is not an unchanged page

Franchises and series get the same treatment as everything else. Three things change even though the cards do not.

**Their card schema converges.** `TitleRef` is closer to the listing card than the other three — it already carries `year`, `manufacturer_name` and `thumbnail_url`, and a `model_count` the games card does not have and does not need. It differs in three ways that matter: it identifies by `public_id` where the listing card uses `slug`, it carries `manufacturer_name: str | None` flagged as "display-only, no paired slug", so **the card cannot link to the manufacturer** where a listing card can, and it has no `entity_type`, so it structurally cannot carry a Model card if one ever belonged there.

**Their sort becomes defined.** `_franchise_titles_qs()` and its series twin order the _prefetched Models_ (`.order_by("year", "name")`) and never order the Titles at all, so the card order is whatever the database returns. It currently comes out newest-first and matches the listing by luck. Unspecified order is survivable on a flat list and is not survivable under pagination, where it means rows can repeat or vanish across page boundaries.

**They move onto the shared path**, which is what stops all of the above from drifting back.

**Model detail pages are unchanged**, so a Model card always has somewhere to link.

### Hierarchy, not just grain

A theme detail page and the listing filtered by that theme are one question, and today they give two answers differing on **two** axes rather than one. Read from the dev API:

```text
/api/pages/theme/medieval    → 15 cards
/api/titles/?theme=medieval  → 24 cards
```

Grain is the visible half. The other half is that the listing dimension rolls the taxonomy hierarchy up and the detail page lists **direct tags only** — `medieval` has six child themes, so the listing counts them and the page does not. The product doc calls that an oversight and fixes it by definition: the detail page's list _is_ the listing's, descendants included.

That is the larger half of the change, and on some pages it dominates:

| page              | cards today | the listing pinned to the same value | why the gap                                    |
| ----------------- | ----------- | ------------------------------------ | ---------------------------------------------- |
| `/themes/racing`  | **10**      | **335**                              | almost everything is tagged under child themes |
| `/themes/sports`  | 1,163       | 1,401                                | broad direct tagging plus 58 direct children   |
| `/themes/fantasy` | 324         | 371                                  | mostly tagged directly                         |

`/themes/racing` showing 10 machines for a catalog holding 335 racing games is the clearest single argument for the change. Note also that the theme hierarchy is a **DAG rather than a tree** — `horse-racing` has parents `racing` _and_ `sports`, `bicycle-racing` has three — so descendant traversal has to de-duplicate. It already does: the listing returns 1,401 for `sports` today. That is what makes "no new filtering logic" literally true rather than aspirational.

### The shape: an embedded listing, in one call

The product doc settles this: every route fetches its first page of games embedded in the initial page API call, and subsequent pages call the shared games endpoint. [ApiDesign.md](../../ApiDesign.md#core-rule) makes one page endpoint returning one page model the standard, so the detail endpoint returns the record's own data **plus page 1 of the rolled-up cards plus a count**, in the games card schema, produced by the games code path. The client's pagination loader continues from page 2 against `/api/games/` with the dimension pinned.

The listing itself is the deliberate exception to the one-call rule, not the pattern to copy: it awaits the cards on the critical path (~16 ms) and returns facet options as an unawaited promise streamed after (~107 ms). Detail pages need no facets, so they collapse to the single call cleanly.

This is what makes the embedded listing safe: it cannot drift from the listing, because it _is_ the listing.

The frontend machinery already exists and is what every taxonomy _index_ page uses — `CatalogListing` → `PaginatedListPage` → `PaginatedListLoader`. Nine detail routes have their own loader against a different endpoint; those converge onto it rather than keeping a second mechanism.

### The facet work does not grow

**Facet counts exist on exactly two surfaces.** `facet_counts` is imported by `titles.py` and `manufacturers.py` and nowhere else; `FacetedCatalogListing.svelte` is imported by two routes and nowhere else. **Not one dimension detail page has a facet sidebar.** So the card-grain facet counts stay a listing problem exactly as they are today, and COMMIT.HET.PROVE's measurement is unaffected by how far the rule travels.

## PR.REL — the relationship vocabulary

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

Adding a dimension touches `TitleFilters` → `DIMENSIONS` → `apply_dimension` → the query schema → `to_filters()` → `FilterOptions` → `facet_counts()` → `FilterState` → `emptyFilterState()` → `PARAM_MAP` → `hasActiveFilters` → the query type → `queryFromUrl` → the chip builder → the sidebar. Five are near-clones of each other, and a parallel set exists for manufacturers. `edge` is one dimension slot with a key registry and a direction axis behind it, so it pays this in full.

**Declare a `FilterDimension` spec on the backend — the narrower, the facet binding and the `surfaced` flag in one place — and stop there.** That collapses the five backend near-clones and gives hidden dimensions somewhere to live. Do **not** generate the TypeScript half from it. Cross-language codegen here is the giant new subsystem the product doc is afraid of, and the project's own escalation order puts codegen last, after a `_meta` walk and a typed spec. Take the rung that fits and leave the frontend hand-written until it hurts.

### Stored filters constrain the syntax

[Articles.md](../catalog_data_model/Articles.md) requires a dynamic list to be a stored filter that validates against the real listing-filter vocabulary. That is a live constraint on the syntax: a stored filter has to round-trip against a vocabulary that has since gained keys, and it has to **fail legibly** when a key disappears — a retired relationship type should surface as a broken stored filter with a nameable cause rather than a list that silently goes empty. That is the argument for named keys over raw `(type, status)` tuples, since a key can be deprecated with a message. It also pushes toward flat serializable params over nested target-attribute predicates.

## PR.SPARSE — the sparse dimensions

Three dimensions, all already implemented on `/api/models/` and none needing a relationship predicate.

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

**Repeatable params are new work here, not something already in place.** These three dimensions are absent from the listing filter vocabulary entirely, and on `/api/models/` `game_format` is a single `str` — as is every other field on `ModelFilterQuerySchema`. So this PR adds `list[str]` handling for the three, on both surfaces if the shared narrower is to serve both. Not difficult, but it is a line item rather than a free ride on an existing mechanism.

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

## PR.MOVE — the route rename

The Svelte listing route moves to `/games`. Detail routes do not, so `routes/titles/` keeps `[slug]` and `new` while the listing files move; `/games` needs no `[slug]` route of its own, because a card links to `/titles/<slug>` or `/models/<slug>`.

Everything else the rename used to carry — the API path, the card schema, the reader-facing labels — landed in [PR.HET](#the-renames-in-this-pr). What is left is the route, the redirect, the sitemap and the SEO tails.

**`/titles` would otherwise 404 rather than redirect.** Moving `routes/titles/+page.*` out while keeping `[slug]` and `new` leaves `/titles` as a route segment with children and no index page. The product doc calls for the redirect.

`resolve()` is typed against the generated route tree, so every internal link to the listing fails at compile time rather than at runtime. That is the safety net that makes this a mechanical change.

## After V1 — the public filtering API

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

### It does not apply the roll-up

The load-bearing design point, and it runs the opposite way from the listing.

The roll-up is a **reader-facing display rule** — show the highest-level grouping that satisfies the query, so a browsing human sees one Godzilla rather than four. A machine consumer counting commercially produced machines wants the matching set, flat, at Model grain. Rolling four Models into one Title card would corrupt exactly the count The Flip is building.

So the seam is: **the predicate is shared, the roll-up is not.** The dimension narrowers and the edge vocabulary are one implementation used by both surfaces; the listing applies the roll-up on top and `/api/models/` does not.

That leaves the codebase with two Model filter vocabularies, which is only defensible if they differ by grain rather than by spelling. Today they differ by both: `ModelFilterQuerySchema` says `type`, `display` and `subgeneration` with a single-valued `feature`, where the listing says `tech_gen`, `display_type` and a repeatable `theme`. **Converge the param names when this is published** — and note that doing so is a breaking change for the one blessed external consumer, which is an argument for doing it before publication rather than after.

### Response shape

Today's `ModelListItemSchema` is a **display** shape: `thumbnail_url` is resolved through `get_minimum_display_rank()`, which means nothing to a consumer joining against its own cached export.

The published shape is identity only — the Model slug plus its Title slug, so a consumer can join at either grain — against their cached copy of `/api/export/models/`. The two surfaces are companions by design: the export carries the records, this one carries the answer to "which ones".

### Decisions publishing forces, not taken here

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

## Tests

PR.HET is a bug fix, so the failing tests go in first.

**Backend.** Extend the search class in `test_title_facets.py` near `test_q_matches_first_model_manufacturer_not_later_models` — which itself is deleted, since the behaviour it pins is the representative pin being removed. Add: Model name match, Model abbreviation match, a Variant Model matches when named specifically, a retired Model does not match.

The roll-up wants a test per rung and per boundary: a Title whose every Model matches yields one Title card; a Title where one Model fails yields one card per matching Model; a Variant is absorbed when its parent matches and surfaces when it does not. Multi-select needs the case a single Model must carry both values, since that inverts today's behaviour.

**The two-set split needs three tests of its own**, because getting it wrong produces plausible cards rather than an error. A record-local shared dimension must not break unanimity — `q=Ice Fever` returns the Title even though the sibling Model is named _Ice Mania_, and `q=Karate Fight` returns the "Black Belt / Karate Fight" Title rather than the Karate Fight Model. It must still gate rung 2 — `q=Ice Fever&theme=X` returns nothing when only _Ice Mania_ carries the theme. And a Title-only dimension must bind at rung 2 — `franchise=harley-davidson&manufacturer=sega` returns no Sega Model outside the franchise.

In `test_api_titles.py`, update the key set, assert a Model row carries the _matched_ Model's year, manufacturer and thumbnail, and wrap a search request in `django_assert_num_queries` to pin that the card-grain rows add no per-row query. In `test_api_search.py`, update `CARD_KEYS`, add a Model-name match, and pin that **a description-only match still yields `entity_type == "title"` and does not suppress a Model row under the same Title**.

Facet counts keep the existing "badge equals result count" invariant, which is now a stronger statement than it was — assert it at card grain for at least one shattering value such as `manufacturer=chicago-gaming`.

**Three exact-key-set assertions will fail**, and they fail in both directions — `entity_type` arriving and `model_count` leaving: `CARD_KEYS` in `test_api_search.py:25`, the `set(item) ==` assertion in `test_api_titles.py:53`, and `CARD` in `frontend/src/routes/titles/page-server-load.test.ts:4`. That is what makes them useful here rather than merely noisy: an exact key set is the one assertion that catches a field being dropped.

**Frontend.** The manufacturer-line cases move to `GameCard`, which is the point of the extraction. `GameCard` gets one case per `entity_type` asserting the registry-derived href resolves to `/titles/…` and `/models/…`, plus one asserting the two render an **identical subtitle** — that pair is the regression guard against the drift being removed, and against anyone reintroducing a branch to restore it. Add `entity_type` to the `CARD` fixture, add a Model-row fixture to the search page tests asserting the `/models/` href, and pin that a listing URL bearing a query emits no `ItemList`. The `TitleCard` and `MachineCard` test files are deleted with their components.

## Verification

Run `make codegen` first — the typed client will not see the new field until you do, and `schema.d.ts` is gitignored so do not stage it. Then `make quality` and `make test`.

These must go from empty or wrong to right: `q=Godzilla (Pro)` returns the Stern Pro Model row with `entity_type: "model"`; `q=Rock Encore` returns a row linking to `/models/rock-encore`; `q=Remake` returns about six rows; `?manufacturer=vifico` returns 13 cards against today's 0; `?manufacturer=chicago-gaming` returns 15 against today's 2.

These must move to the values `mf_card_counts` predicts: `manufacturer=williams` 469 → 487, `tech_gen=solid-state` 1,407 → 1,432, `theme=fantasy` 371 → 396. Re-run the analysis file rather than trusting the numbers printed here — the catalog moves.

These must be unchanged: the unfiltered listing at 6,180 cards, and `q=Godzilla` at 3.

**Eyeball a short common token before merging.** The predicate moves in both directions at once — Model names and abbreviations widen it, dropping the representative-manufacturer arm narrows it — so a net figure hides two large offsetting changes. `q=pro` is **106** today and is the case to look at: substring matching on three letters hits `(Pro)` across many Stern Models on the widening side, while every Title reached today only through a manufacturer name called Pro-something falls off the narrowing side. `q=rock` (95 today) and `q=williams` (470 today) are the other two worth reading by eye, the last because it is almost entirely manufacturer-arm matches and should collapse to near nothing. None of these has a predicted value — they are a judgement call about whether the new predicate reads better than the old one, not an assertion to pin with a test.

## Deferred

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

## Explicitly not doing

- **Converting the relationship enums into claims-controlled vocabulary entities.** Relationship types are behaviour-heavy, so patch-authorable behaviour columns would hand Title-representative decisions to any contributor, and the privileged-edit protection that would mitigate that is unbuilt. The conversion remains the escape hatch if type growth ever outpaces release cadence.
- **Autogenerated pages keyed on a relationship-type vocabulary** (`/relationship_type/<slug>`). Reaches only four of the ten concepts: it cannot reach the three lineage fields, which have no vocabulary table behind them, nor the composites. It would create two tiers of concept page where filter-backed pages serve all ten uniformly.
- **Editorial pages over the vocabulary, built now.** The long-term home for "every unlicensed copy" is a written page whose prose carries what a bare list cannot — that unlicensed copying was widespread across Spain, Italy and Brazil, and that only a handful of cases are sourced so far. That mechanism is [Articles](../catalog_data_model/Articles.md), and building interim filter-pages with hardcoded prose creates something Articles then replaces. The vocabulary lands first and the packaging follows; the filter ships either way.
