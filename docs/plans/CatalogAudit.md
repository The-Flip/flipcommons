# Catalog audit

We want a way of deterministically checking that the catalog is in a coherent state. Some use cases:

- **Decide what data patches to author**, like what vocabulary words are missing descriptions?
- **Vet just-written data patches**: did the patch(es) fully fill in that model or model family, or fill them in incorrectly?

The immediate impetus is that we've authored a lot of data patches in `/Users/moses/dev/flippatch/campaigns/0215-frontier-2026/README.md` and want to vet them before shipping them to prod, which turns them immutable. The priority is rules that vet the unshipped patches.

Think of them as audit or linting rules for catalog structure. Here are some [candidate rules](#rules).

## Where this lives

Architecturally, this would be a layer on top of the Flipcommons analytics foundation.

The analytics foundation already defines a check contract: an analysis file exposes `<prefix>_summary` and `<prefix>_checks`, and the runner "fail[s] nonzero if any `*_checks` view has rows" (`README.md:152`). Empty checks = healthy. There's even a meta-gate — check-mutations requires every check to have an entry in `catalog_mutations.tsv` proving it actually fires, enforced in both directions.

This would NOT go in `catalog_checks.sql`; that's the foundation self-test.

Dependency-wise, I imagine this is a layer above the analytics core: it consumes `catalog.sql` but `catalog.sql` is unaware of it.

This whole thing is a Flipcommons not Flippatch concern: it's about overall database coherence, not specifically data patches. It lives in Flipcommons.

### This would NOT check unapplied patches

This isn't a pre-flight tool to check YAML patch files before they are applied to the database. This linting would happen over the live database. We'd apply the data patches, vet the results, fix the patches, roll back db, re-apply patches, re-vet results.

If a rule could be achieved by linting a YAML patch file without the database, we should do that. Those go in Flippatch's `lint_patches.py` or even better, `patch.schema.json`. The rule might additionally go into this system if we want to build a backlog of data quality issues to address.

## Features

These features are off the top of my head: not exhaustive, not well-thought-out, subject to revision, feel free to push back.

### Whitelisting

I would imagine some rules will need to permanently whitelist exceptions, like "Alexandre Dumas is not a credit" or "yes we're not going to document gameplay feature X".

This could be implemented many ways, such as a rule might carry an inline VALUES exception list, every row with a reason, ala `ref_opdb_manufacturer_exceptions`.

Don't build anything in advance of actually needing it.

### Easy to author

Let's make it easy to add new rules. AI sessions should be able to do this as a side errand without it being their primary job. All the stuff around a rule to be self-contained and not spread out all over the place. Self-documenting. Understandable without reading the entire system. Hard to do the wrong thing, come up with a confidently wrong answer.

### Apply rules to a particular area

For authoring a data patch it's probably useful to scope the findings, such as:

- to claims written by patches ≥ some patch number
- to a particular model, title or manufacturer

I imagine those are just various SELECTs?

## Pinexplore?

Before we decide anything, let's evaluate Pinexplore's DuckDB analytics architecture, such as the layers, the checks, the way it prints out errors in a later layer. What should we learn or borrow from it?

---

⬆️ ABOVE: USER-WRITTEN PRODUCT SPEC.
⬇️ BELOW: AI-GENERATED. TAKE WITH A GRAIN OF SALT.

---

## Pinexplore analysis

Preliminary AI analysis of Pinexplore found the following. This is NOT a user analysis, it could easily be wrong.

### Severity split

`05_error_checks.sql` aborts the build; `06_warning_checks.sql` reports and continues. Two tables, different shapes:

```text
CREATE TEMP TABLE _violations (category VARCHAR, check_name VARCHAR, detail VARCHAR);
CREATE TEMP TABLE _warnings   (check_name VARCHAR, cnt BIGINT);
```

This error/warning split is about build integrity. Some audit rules would produce a third thing — a gap that is legitimate today and authorable later. 540 themes without descriptions is not a warning, it's a backlog. I'd suggest violation (incoherent, gates), review (suspicious but possibly correct — the 525 conflicts), gap (expected nonzero, tracked as a trend, never gates). Only violation fails the build. A layer that reports 540+ rows on every run teaches people to skip the output, which costs you the 29 rows that actually matter.

The report shape should differ per severity, for the same reason. Violations print rows, with the true total counted before the `LIMIT`. Review unscoped is 525 rows — printing them is the same failure as printing 540 gaps — so it prints counts per rule plus the view name to go query. Gaps print counts ordered by usage weight, so the worklist leads with the terms attached to the most models.

### Checks live next to their logic, but report in one place

`_warnings` is an accumulator — `07_compare.sql` inserts 6 more rows into it long after `06` created it — and `90_print_warnings.sql` is five lines that always run last. It means a rule can sit in whatever layer has the data without fragmenting the report.

### The runner digs the rows out

`rebuild_explore.py:100` exists because `_violations` is a temp table that dies with the connection — so the abort message's advice to go query it is useless by the time you read it. It prints up to 50 offending rows to stderr, with the true total via `count(*) OVER ()` taken before the `LIMIT`. Small, and the difference between a usable gate and "3 contract violation(s) found."

### Exception lists are views in the reference layer, with reasons

`ref_opdb_manufacturer_exceptions` is a VALUES list of `(opdb_id, slug, reason)` where every row also carries a comment explaining the research behind it, consumed by a single NOT EXISTS in the check. That's the right shape for your "Alexandre Dumas is not a credit" list.

### Things to not copy

`_warnings` stores only a count, so finding the actual rows depends on a hand-written -- Details: SELECT \* FROM ... comment above each insert. That comment isn't runnable and nothing keeps it honest. For your gaps — which are the worklist — row-level detail isn't a nicety, it's the whole product.

### What flipcommons already has that's better

Mechanisms there are more evolved than pinexplore's:

`stale_exception` matters more here than it does there, because your exceptions will be keyed by slug and patches rename slugs — 0232 renamed yukon-yeti and its corporate entity mid-campaign. A misspelled or orphaned exception exempts nothing while looking like it exempts something.

#### `_anchor_skip` was the model for whitelisting here, and it has been retired — don't port it

An earlier draft held up `_anchor_skip`'s two-kind exemption split (`sparse` = empty indefinitely, `pending` = empty until data lands, so it must expire) as the answer to the [Whitelisting](#whitelisting) question. The whole anchor apparatus was retired in `43074efe1` — `_dark_cols`, `_anchor_scan`, `_anchor_skip`, `_anchor_array`, seven checks and 51 exemption entries. `anchor_dark` fired only at `live = 0`, so a join breaking for half its rows passed silently, while a total break on a well-populated column would be caught by ordinary use. Its coverage was inversely correlated with its value, and six of its seven checks existed only to police the exemption list of the one doing the work.

**The reason it needed an exemption list at all is the part that matters here, and it is not a lesson about exemptions.** A `sparse` entry meant "this facet is legitimately empty" — which in this doc's taxonomy is not an exemption, it is a **`gap` finding**. The list existed because the foundation has exactly one severity: a thing either gates or does not exist. Give the same finding a severity that never gates and the entry evaporates.

The `pending` half dissolves the same way, and more sharply. `pending` meant "empty only until data lands", which required `expired_anchor_skip` to retire the entry once the facet went live. Under a non-gating severity none of that is needed: when the data lands the rule stops matching and the gap disappears on its own. `expired_anchor_skip` was machinery for un-suppressing something that a `gap` severity would never have suppressed.

So the idea was not wrong, it was a workaround for gating a concern that should not gate — and the three-severity split is the better version of it. Exemptions genuinely remain for `violation` rules with real known-good exceptions, the "Alexandre Dumas is not a credit" case, where `stale_exception` above still applies. Expect those lists to be short, and treat one getting long as a signal about the rule rather than about the data.

**The mutation gate is the single highest-value thing in either repo**, and I'd argue it's more necessary for this layer than for the foundation self-test. The reasoning from catalog_mutations.tsv: a check that is broken and a check that is passing both return zero rows, and every defect ever found in that suite was a check that had silently become a no-op, usually via a comparison going NULL. Nearly every rule on your list is a NOT EXISTS / LEFT JOIN … IS NULL shape — precisely the shape that goes quietly no-op. And unlike the foundation, this layer runs against a catalog that patches are actively reshaping underneath it.

## Rules

Here's some candidate rules. This is us noodling on what would be useful. It is NOT exhaustive, it is NOT a MUST DO list, it is NOT prioritized. Some are AI-generated in Flippatch, may be YAML centric (and thus invalid), and show numbers scoped to a particluar data patch campaign. I have not vetted and approved them all.

**Treat every count below as a campaign-scoped sample, and stale.** Most were measured against campaign 0215 rather than the whole catalog, and the two the prototype re-measured unscoped came out an order of magnitude or more off — one rule went from 85 to 61,224. The catalog also moves: `scalar_type_disagreement` measured 29 hits and 3 hits an hour apart on the same day, because the flippatch session fixed 26 of them in between. Re-measure before designing a report format around any number here.

### Variants

Variants should carry all the credits / features (and maybe other fields) of its parent model.

### Missing persons

A person name in cited quotes not credited on that model.

### Missing vocabulary descriptions

A bounded vocabulary record without a description. That's cabinet, display type, display subtype, game format, production status, reward type, tag, technology generation, technology subgeneration.

**Measured, and the two halves are backwards from how this doc presents them.** The bounded vocabularies contribute **5** findings — game formats `one-ball` and `rolldown`, systems `fast-pinball` and `stern-spike-3`, and the tag `limited-edition`. The open vocabularies contribute **692** (themes 540, gameplay features 142, credit roles 10) for a catalog-wide total of 697. The bounded rule is very nearly a no-op; see [Description coverage on the open vocabularies](#description-coverage-on-the-open-vocabularies) for the rule that actually carries the backlog.

The list above is missing one: **`system` is a tenth bounded vocabulary**, 75 live rows, and it holds two of the five findings. It reads as a dim rather than a vocabulary because a model points at it the same way it points at cabinet, but a System is an authored record with a manufacturer and a description like any other.

**The promotion this rule was blocked on is done** (2026-08-13). It could not ship before then: those dims have a physical `description` column, but no foundation view exposed it — `game_formats` and `reward_types` omitted it and the other seven had no view at all, which is exactly the case `EDITING.md` warns about, where a column absent from a view says nothing about the Django model. `catalog.sql` now carries `description` on `game_formats` and `reward_types` plus an entity view per taxonomy dim (`cabinets`, `display_types`, `display_subtypes`, `systems`, `production_statuses`, `technology_generations`, `technology_subgenerations`), and `_entity_view`'s `dim` exemption is retired, so entity-grain coverage is exhaustive with no opt-out.

### Missing themes

A model without themes. I'm sure there's a 1000 models without themes, but when we touch a model, we should be adding themes

### Scalar claims with type disagreements

The same fact gets stored two ways: `production_quantity` is the JSON string `"100"` on 2,766 claims and the number `100` on 21. Since "100" != 100, duplicate detection and every cross-source comparison silently miss the mismatch.

**Severity: violation. 29 live hits, 26 of them written by campaign 0215's patches.**

```text
player_count          7 stored as JSON strings   vs 15,006 as numbers
year                  1 stored as a JSON string  vs 12,988 as numbers
production_quantity  21 stored as JSON numbers   vs  2,766 as strings (including all of ipdb's)
```

The offenders span 13 of the campaign's 24 patches — `"4"` on `houdini-100th-anniversary`, `"2"` on `transformers-the-pin`, `700` on `bon-jovi`, `750` on `pokemon-limited-edition`. Three more (`evil-dead-collectors-edition`, `freak-out`, `james-bond-007-60th-anniversary-limited-edition`) predate the campaign.

This is not cosmetic. `campaigns/0215-frontier-2026/model-families/houdini/Houdini.md` records the cost: an exact duplicate (same actor + key + value) is silently swallowed by the apply and leaves no `patch_claims` row, but a type mismatch defeats that match, so the same fact from two sources survives as two competing claims and the priority ladder picks between them. That is exactly how Houdini's `production_quantity` duplicate stayed invisible — 0215 asserted the number `100`, the emitter wrote the string `"100"`.

The diagnostic form:

```sql
SELECT field_name,
       CASE WHEN value LIKE '"%' THEN 'json-string' ELSE 'json-number/other' END AS kind,
       count(*) AS n, string_agg(DISTINCT ingest_source_slug, ',') AS who
FROM model_claims
WHERE is_active = 1 AND field_name IN ('year','month','player_count','production_quantity')
GROUP BY 1, 2 ORDER BY 1, 2;
```

Make the shipped rule **self-tuning** rather than hardcoding a per-field expectation: derive each field's majority JSON type from the corpus and flag the minority. It then needs no maintenance as fields are added, and it cannot go stale against a field whose convention legitimately changes.

### Cross-actor disagreement

Two actors assert different values for the same single-valued field: IPDB says transformers-the-pin is 2-player, OPBD says 4. The catalog silently shows whichever source outranks the other, so the conflict never surfaces to anyone.

**Severity: review. 525 models live.**

```text
month 229 · name 144 · year 113 · player_count 19 · technology_generation 16 · title 2 · variant_of 1 · display_type 1
```

These are not errors — the source-priority ladder resolves a winner by design, and `Provenance.md` is explicit that superseding is the intended mechanism. They are the review worklist.

What makes this a **patch-vetting gate** rather than a standing report is the scoped form. Restricted to claims written by patches ≥ 0215 it returns exactly **3 rows**, and all three are conflicts the family notes had already flagged by hand: `transformers-the-pin`'s 4-vs-2 player count, and the two Peter Brock KOTM year corrections to 2024. It fires precisely on "this patch asserted a value that another source already claims" — campaign rule 3 ("Don't overwrite data on existing models. Only assert missing facts. If you think an existing fact is wrong, get user approval before correcting it") expressed as a query.

```sql
WITH conf AS (
  SELECT model_id, field_name FROM model_claims
  WHERE is_active = 1 AND field_name IN ('year','month','player_count','production_quantity',
        'production_status','game_format','cabinet','display_type','system',
        'technology_generation','variant_of','title','name')
  GROUP BY 1, 2 HAVING count(DISTINCT value) > 1)
SELECT c.model_slug, c.field_name,
       string_agg(c.ingest_source_slug || '=' || c.value || ' (r' || c.rank || ')', ' | ' ORDER BY c.rank) AS vals
FROM model_claims c JOIN conf USING (model_id, field_name)
WHERE c.is_active = 1 AND c.patch_id IS NOT NULL AND patch_number_of(c.patch_id) >= 215
GROUP BY 1, 2 ORDER BY 1, 2;
```

The unscoped version is the `review` backlog; the patch-scoped version belongs in the per-patch vetting run, where three rows is a reviewable number.

### Description coverage on the open vocabularies

**Severity: gap. 692 records live.**

```text
themes             540 of 540 missing a description
gameplay features  142 of 319
credit roles        10 of 10
```

The rule already sketched at the top of this doc covers the **bounded** vocabularies (cabinet, display type, display subtype, game format, production status, reward type, tag, technology generation, technology subgeneration, system). Tags belong to that rule and are counted there, not here — an earlier version of this block listed them in both and summed to 693. The open, DAG-shaped vocabularies are the larger backlog by an order of magnitude, and themes are effectively undocumented as a vocabulary. For the "decide what data patches to author" use case this is the single richest source in the catalog.

Worth splitting the metric by usage count (`theme_vocab.n`, `gameplay_feature_vocab.n`) so the worklist leads with the terms attached to the most models rather than the alphabetically first.

### A credit whose citation quote never names the person

**Severity: review. 16 of 347 credit pairs in campaign 0215; 13 are one real class.**

This is the converse of the rule already listed ("a person name in cited quotes not credited on that model"). That one catches **recall** — evidence naming someone who never became a credit. This catches **precision** — a credit whose own supporting quote does not contain the person's name.

Thirteen of the sixteen are a single failure class, **speaker-attributed credits**, where the quote is first-person and the person is identified by _who was talking_ rather than by name in the text:

```text
0233 monster-league-hockey  austin-carrigan software  "i did the coding for the game."
0238 obsidian-high          ellie-corcoran  art       "i drew everything here except the hair and uniforms…"
0225 fish-tales-kit         james-cardona   design    "he writes the code, designs the games, and has brought in…"
```

`verify-quote-verbatim` passes all of these — the text really is in the source. The recall rule cannot see them either, because there is no name in the quote to match. The attribution rests entirely on the author having correctly identified the speaker of a forum post or the antecedent of a pronoun, and nothing checks it. This is the most exposed claim class the 0215 campaign produced.

The remaining three are heuristic noise from stage names (`saul-slash-hudson` against a quote reading "guitar solos from Slash"), which the next rule addresses.

### Name matching must resolve through aliases

**Severity: implementation constraint on every name-matching rule above.**

Not a standalone rule but a hard requirement, because getting it wrong inverts the result: the rule fires false positives on precisely the entries where an author did the _most_ careful work.

`0224-bon-jovi.yaml` credits `josh-clay` with `person_alias: [Joshua Clay]` and a note reading "'Joshua Clay' is an alias of Josh Clay." A slug-level comparison against an external roster listing `joshua-clay` reports a missing credit that is not missing. Stage names do the same thing in the other direction — `saul-slash-hudson` against a quote that says only "Slash".

Any rule comparing a person to text must go through the person alias table, and should compare on `name_key()` rather than raw slugs. The same applies to themes, gameplay features and locations, all of which expose alias views for exactly this reason.

### A factual field set with no citation at all

**Severity: review. ~85 in `0215-new-2026-models.yaml` alone.**

`year`, `theme`, `title` and `corporate_entity` at 21–22 entries each, all uncited. Distinct from the rule above: there is no citation instance whatsoever, not merely a citation without a quote.

Needs a **definitional/factual split** or it drowns in false positives — the same scan counts 128 uncited `name` values, but a `name` on an entity create is definitional (the create _is_ the naming) and should never fire. `year`, `production_quantity`, `player_count` and `month` are claims about the world and should. Note that `claim_citations` carries the caveat that most claims have no row and that this means no external evidence was _recorded_, not that the claim is unattributed — so this rule reports an evidence gap, not a provenance defect.

**Measured unscoped: 61,224.** The split by actor is `flipcommons-catalog` 26,244, `ipdb` 24,404, `opdb` 10,554, `user` 20. Restricting to the actors we expect to cite does not rescue it, because the authored source is itself the largest contributor. Only **300** of the 61,224 carry a `patch_id` at all, and 21 come from patches ≥ 0215.

What the rule is really measuring is that the seed predates the citation requirement. The defensible scope is therefore provenance or time — claims asserted once citations were expected — not actor and not patch. Without that it is a gap-tier coverage number and never a review worklist.

### Title siblings that disagree on field presence

**Severity: review.**

The rule already listed covers variants against their parent. Generalize it to **all live models under one Title**: a field set on some editions and absent on others, with no `variant_of` edge to explain the asymmetry.

This is the only shape that catches **right-fact-wrong-edition** — a correct value attached to the Pro when the evidence described the Premium. A per-entry check cannot see it by construction, because each entry is individually well-formed, correctly cited, and verbatim-verified. Only the comparison across siblings exposes it.

`model_edges` is outbound-only; use `model_edges_bidir` when asking whether two editions are connected at all, since hundreds of live models carry only an inbound edge.

### A variant carrying a field its parent lacks

**Severity: review.**

The reverse-carry case. Under the campaign's variant rule (user decision 2026-08-07, recorded in `RULEBOOK.md`), a variant carries every credit of its base and the shared design's hardware, cited to the base's evidence with a note explaining the carry. Data therefore flows **downward**, from base to variant.

A field present on the variant and absent on its base is usually one of: a claim attached to the wrong end of the edge, a `variant_of` pointing the wrong way, or a genuine edition-specific fact that should be confirmed as such. All three are worth a look, and the third is common enough that this cannot be a `violation`.

### Facts that decay with time

**Severity: review. 3 live hits.**

`production_status: announced` on a model whose `year` is now in the past. These claims were correct when written and rot silently, and nothing in the current design expires. (An earlier draft said "except `pending` entries in `_anchor_skip`" — that mechanism is [retired](#_anchor_skip-was-the-model-for-whitelisting-here-and-it-has-been-retired--dont-port-it), so there is now no expiry anywhere in the stack.)

```sql
SELECT slug, name, year, production_status_slug FROM models
WHERE production_status_slug = 'announced' AND year < year(current_date);
```

Worth generalizing to any status-like field whose value asserts a point in an unfinished process. The class matters more than the count: three rows today is small, but the campaign just created a batch of 2026 models whose statuses will all need re-examination in 2027, and no one will remember.

### Orphan vocabulary — leaf nodes only

**Severity: gap.**

A gameplay feature (or theme) created and attached to nothing. 24 of the 73 features campaign 0215 created are currently unattached.

The rule is only clean **restricted to leaves**. `gameplay_feature_vocab`'s own description says it outright — _"Read n WITH children: n = 0 on an interior node is by design"_ — and the unattached set is full of deliberate interior nodes (`interactive-lighting`, `toys`, `spotlights`). Unrestricted, this rule is mostly noise; leaf-only, it finds vocabulary created for a patch that then didn't use it.

### Missing parents

A tech sub-generation set without the parent generation being set. Or maybe this is already structurally impossible b/c of DB validation?

**Answered: nothing prevents it.** `technology_generation` and `technology_subgeneration` are independently nullable FKs on `MachineModel` (`machine_model.py:231`, `:239`) with no paired constraint. The rule returns zero rows today because the data happens to be clean, not because the defect can't occur — so unlike the cite-root rule it survives the [engine pre-check](#this-would-not-check-unapplied-patches).

It is also the exact profile the mutation gate exists for — a rule born at zero rows, where a passing check and a silently broken one are indistinguishable. It cannot ship without its proof.

## Flippatch feedback

Notes from a flippatch session (2026-08-13) that hand-ran most of these rules as ad-hoc SQL against the dev catalog, to vet campaign 0215's 24 patches. It found and fixed 26 mistyped claims, two duplicate person records and five theme gaps. Everything below is what that run actually hit, not prediction. The lessons are mostly about **rule precision**, not which rules to write.

### Two of the session's own queries silently returned the wrong answer

The most important item here, because it happened twice in one sitting to someone actively hunting for exactly this failure:

- `WHERE system_slug IN ('','unknown')` reported **0** campaign models missing a system. The true answer was **31** — `NULL IN (...)` evaluates to NULL, so NULL rows silently fail the predicate and vanish from a `count(*) FILTER`.
- `WHERE subject_type='person'` returned **zero rows**. The stored value is `catalog.person`, so the real answer was **56**.

Both read as clean passes. Nothing distinguished them from a rule that was working. This is the argument for the mutation gate, and it lands harder here than in the foundation self-test for two reasons: nearly every rule in this doc is a `NOT EXISTS` / `LEFT JOIN … IS NULL` / `count(*) FILTER` shape, which is exactly the shape that goes quietly no-op; and this layer runs against a catalog that patches are actively reshaping underneath it. **Every rule should ship with a known-failing fixture**, and the rules born at zero rows (like [Missing parents](#missing-parents)) need it most, since for them a green result is indistinguishable from a broken query.

A third instance turned up while promoting the vocabulary `description` field (2026-08-13), and it is the worst of the three because no author wrote anything wrong. `foundation_summary` had been reporting **`game_formats` as 6** for a vocabulary holding **11** live rows — it had taken `reward_types`' count. The cause is upstream: DuckDB's sqlite scanner collapses two branches of a `UNION ALL` that aggregate over different attached tables when the pushed-down projection and filter are identical, and `WHERE status IS DISTINCT FROM 'deleted'` makes them identical across every simple dim view. It affects `max` and `sum` as well as `count`, and with three branches all three take the first's value. The same defect had also silently disabled `_anchor_scan` for those views — it reported `cabinets`, `display_types` and `technology_generations` as 11 live rows each, all inheriting `game_formats`, which is the dark-column detector unable to see a dark column. The foundation's own health dashboard and its own safety net both published wrong numbers and every check stayed green, because the rows were all present and only the aggregates were wrong. Details and the four verified workarounds are in `EDITING.md`; the shape never to write is a `UNION ALL` of aggregates over `fc.` tables. **Assume any rule in this layer that tabulates a count per dim has this defect until it is written the other way.**

### Rule precision is where the work is

The "person named in a cited quote but not credited on that model" rule went through three revisions, two orders of magnitude apart in noise:

| approach                                                                    | hits | usable                                                                                               |
| --------------------------------------------------------------------------- | ---- | ---------------------------------------------------------------------------------------------------- |
| extract capitalized bigrams from quote text                                 | 595  | ~5% — drowned in feature names ("Steamer Trunk", "Dot Matrix") and character names ("Optimus Prime") |
| match against the known person vocabulary (`people`)                        | 11   | most                                                                                                 |
| …and diff against `model_credits`, not against credits written by the patch | 5    | all                                                                                                  |

Two generalizable rules came out of that:

- **Match against a controlled vocabulary the catalog already holds** rather than trying to recognize entities in free text. "Does this string look like a person's name" is unbounded; "is this string one of our 671 people" is exact.
- **Diff against catalog state, not patch state.** Filtering only against what the patch wrote produced a false positive for every person the seed already credited. This bites any rule comparing a patch's output to what "should" be there.

The same precision gap showed up in duplicate-person detection: matching on shared surname produced **56 rows** that were nearly all genuinely distinct people (seven unrelated Johnsons; `P3Modules.md` explicitly records Tyson and Eli Silver as two people). Matching on **token containment** — one name's tokens a subset of another's — produced **3 pairs, all real**: `Zofia Bil` / `Zofia Bil Ryan` / `Zofia Ryan` (one engineer, three records, 14 credits split) and `Jack E. Haeger` / `Jack Haeger` (one art director, 10 credits split).

### Query the catalog for precedent instead of encoding judgment

The most useful technique found, and not yet represented in the rules above. Rather than hardcoding an editorial rule ("baseball implies sports"), ask what the catalog already does:

```text
pitch-and-bat models carrying baseball        16 / 17
wizards models also carrying magic            39 / 45
basketball models also carrying sports        31 / 32
aliens models also carrying science-fiction    0 / 21
```

Each of those took seconds and turned an argument into a measurement. The 16/17 justified adding a theme; the 0/21 stopped an unevidenced one from being written into a patch that was about to become immutable.

A rule shaped as **"this row deviates from N of M comparable rows"** needs no maintenance, adapts as the catalog grows, produces an argument a reviewer can independently check, and carries no author's opinion frozen at authoring time. Worth considering as a rule _template_ rather than a one-off — much of what the rules above express as fixed expectations could be expressed as deviation from observed convention instead.

### One rule, scoped two ways, is two different products

The [cross-actor disagreement](#cross-actor-disagreement) rule unscoped returns **525 models** — a backlog nobody reads. Scoped to claims written by patches ≥ 0215 it returns **3 rows**, and all three were conflicts the campaign's family notes had already flagged by hand. Identical SQL, one predicate different.

That is the concrete case for [Audit a particular area](#audit-a-particular-area), and it suggests the scope predicate should be **one shared mechanism every rule consumes** rather than something each rule reimplements — both because copy-pasted predicates diverge subtly, and because per-rule scoping fights the [Easy to author](#easy-to-author) goal.

### Check whether the apply engine already prevents it — but don't trust a guard's coverage

One proposed rule turned out structurally impossible: cite URLs resolving to no citation root. There are **4,693 citation instances and 0 unresolved**, because `ingest_patches` rejects a cite it cannot resolve. The failure can't reach the database. Dead rule — worth checking for this before building any rule whose defect the engine already refuses to admit.

The inverse is the trap. `DataPatches.md` documents that `create: true` on a ref that already resolves is an error, so duplicate entities _look_ covered — and patch 0222 still created a second Jack Haeger, because the existing record's slug was `jack-e-haeger`. The guard works exactly as documented and keys on exact slug identity, which is not the defect. **A working guard is not coverage; ask what it keys on.**

### Row-level detail is where findings actually come from

The known-person check flagged `Zofia Bil` on five GTF models, which looked like a substring false positive — the quote reads "Zofia Bil Ryan" and matched a _different_ person record whose name is a substring. Reading that row led to three person records for one human, which led to finding Jack Haeger, which led to two real bugs fixed before shipping.

**The rule that found the bugs was not the rule designed to find them.** A count would have printed "5 warnings" and been dismissed. This is the concrete case behind [Things to not copy](#things-to-not-copy) — for anything a human is meant to act on, the rows _are_ the product.

### Know the ceiling

Some defects no deterministic rule reaches, and the doc should say so rather than let the layer be mistaken for full coverage. Campaign 0215 contains 13 **speaker-attributed credits** — quotes like `"i did the coding for the game."` where the person is identified by _who was speaking_, not by name in the text. The verbatim gate passes them (the text is real), name matching passes vacuously (there is no name to match), and correctness rests entirely on the author having correctly identified the speaker of a forum post or the antecedent of a pronoun.

### One practical note

The dev catalog is a moving target: several checks in that session reported stale values because they ran against an ingest that predated the patch edits, and only became true after a snapshot rebuild. Whatever the runner prints should name **which patch state it measured** — the provenance watermark in `provenance_context` is probably the right thing to stamp on every run.

This already works and nobody had said so: `analysis run` prints every public `*_context` view alongside `analysis_context`, and `provenance_context` is one of them, so a run already emits claims_total, claims_active, ingest_runs, citation_roots and citation_instances unprompted. No new work — a documentation gap.

## Prototype: four rules, measured

A throwaway analysis file (2026-08-13) implementing four rules at four deliberately different grains, to measure unscoped magnitudes and test whether one output shape fits. Not code to keep — no per-rule layout, no mutations, no gating. Watermark: 6,938 live models, 229,623 active claims, latest patch `0238-obsidian-high`.

| rule                        | severity  | unscoped findings | subject types |
| --------------------------- | --------- | ----------------- | ------------- |
| `vocab_description_missing` | gap       | 695               | 5             |
| `title_sibling_gap`         | review    | 712               | 1             |
| `uncited_factual_claim`     | review    | 61,224            | 3             |
| `scalar_type_disagreement`  | violation | 4                 | 1             |

Scoped to patches ≥ 0215 — the vetting use case — the same four rules return 21 findings in total.

### The output spine mostly works

One shape carried all four rules across claim grain, vocabulary grain and title grain: `(rule, severity, subject_type, subject_public_id, subject_name, patch_id, detail)`. Severity filtering, patch scoping and same-grain area scoping are all plain predicates over it. `subject_public_id` is the polymorphic key — `claims` and `entity_subjects` carry `subject_type` + `subject_public_id` and there is no `subject_slug`.

**It breaks on findings whose subject isn't what they're about.** A `title_sibling_gap` row reading `production_quantity set on 1, absent on 3 (jurassic-park-pro, jurassic-park-premium, jurassic-park-30th-anniversary)` is filed under the Title, `jurassic-park-stern`. Asking the spine for everything about `jurassic-park-pro` returns nothing at all. The finding is about four models and subject to one title, so a finding needs an affected-entities relation rather than a single subject — see [Findings are keyed by a relation](#findings-are-keyed-by-a-relation-not-a-column).

**Detail strings can't be rendered generically.** Claim values are raw FK ids, so a generic detail reads `display_type = 1`, `system = 47`. Decoding is per-field, so each rule should render its own detail and the union carry it opaque — which also preserves the row-level detail that pinexplore's count-only `_warnings` loses.

### Two mechanical traps

**`UNION ALL BY NAME` fails silently**, and the union is this layer's central artifact. The first spine attempt used it; branches whose literal columns were unaliased contributed auto-named columns matching nothing, and the summary came back `rule = NULL, severity = NULL, n = 62,631` — three of four rules merged into one anonymous bucket, no error. Positional `UNION ALL` with a cast per column fails loudly instead. Same family as the `NULL IN (...)` and `catalog.person` failures the flippatch session hit: the answer looks like an answer.

**`json_type()` splits JSON numbers into `UBIGINT` and `DOUBLE`**, which is a storage artifact rather than a disagreement. A self-tuning type rule keyed on it directly reports false positives; it needs a type class (number / string / array / object).

### What the self-tuning form bought

Run over every scalar field rather than the four this doc enumerates, `scalar_type_disagreement` found `louis-vuitton` carrying `variant_of = ""` — an empty JSON string where the field's other 146 values are numeric FK ids. No hand-written field list would have covered it. That is the [deviation template](#deviation-from-observed-convention-as-the-default-rule-shape) at field grain, and the reason to prefer it as the default shape.

### Sizes worth knowing

`title_sibling_gap` breaks down as production_quantity 203, display_type 183, month 114, system 91, player_count 36, technology_generation 34, year 34, production_status 9, game_format 6, cabinet 2. The `variant_of` / `remake_of` / `export_edition_of` edge explains fewer of them than expected — 13 of the 203 production_quantity findings, 55 of the 183 display_type ones — so "no edge to explain the asymmetry" is not the noise filter this doc assumes it is.

### Not tested

Mutation-proving a rule, the file-per-rule layout, exception lists, `*_checks` discovery against a nonzero violation baseline, and any rule needing alias resolution or quote text.

## Open questions from the prototype

Decisions a designer still needs to make.

- **Gaps are described as "tracked as a trend" and this layer has nowhere to keep a trend.** Nothing is persisted, `*.duckdb` is gitignored, and `analysis_context` exists precisely because what's reproducible is queries and not results. Either drop the trend and treat gaps as a worklist you query, or introduce a committed summary artifact — a new artifact class for this layer.
- **What does the spine call an entity type?** `subject_type` holds Django's `catalog.person`, and a session guessing `'person'` got zero rows and read it as a clean pass. Expose the project's own entity key, or carry both.
- **Is the exemption count a diagnosis or a design-time test?** See [the two caveats](#two-caveats-on-the-exemption-count).

### Answered

- **A finding's subject is not the entity it is about** — answered, and the answer is a relation rather than a column: [Findings are keyed by a relation](#findings-are-keyed-by-a-relation-not-a-column).
- **Fixture or mutation as a rule's proof** — neither; [they are a pair](#proof-fixtures-and-mutations-are-a-pair).
- **Which severity gets the `_checks` suffix, and how the file stays opt-in** — confirmed against the current runner, which is untouched: `run` still sweeps every public `*_checks` and `*_context` view. See below.
- **`check-mutations` is still hardcoded** (`plan=`/`spec=` at lines 20-21) and is not on the foundation's list, so **this layer owns that change**. One constraint travels with it: the harness collects declared check names from the first checks view to end-of-file, so where a file `.read`s its sub-modules is load-bearing.

**The three severities need no new mechanism, only naming discipline: exactly one of them may be named `*_checks`.** Violations get the suffix and gate; review and gaps are ordinary public views the summary reports and the runner never fails on. Two consequences follow, and both are easy to get wrong:

- **The runner's discovery is transitive**, so this file must never be `.read` by `catalog.sql` or the foundation. The moment it is, a nonzero violation baseline fails every consumer's run — including Flippatch campaigns, in the other repo, with nothing here reporting a problem. Opt-in only, invoked by name.
- **"Empty = healthy" applies to one severity out of three.** The other two are permanently nonzero by design. That's a legitimate use of the summary/checks contract but not the one it was built for, so it should be deliberate rather than discovered.

**Before writing any rule, check whether the apply engine already refuses to admit the defect.** A defect the engine rejects cannot reach the database, so the rule is dead on arrival — the cite-root rule was cut for exactly this ([flippatch feedback](#check-whether-the-apply-engine-already-prevents-it--but-dont-trust-a-guards-coverage), confirmed at 4,740 citation instances and 0 unresolved). The inverse is the trap in the same note: a guard that works as documented is not coverage, because it may key on something narrower than the defect.

Cost is not an argument against per-rule files: the prototype's four rules ran in 0.28–0.74s each and ~1.0s unioned, with process startup dominating. `foundation_checks` needs its materialized preamble because of the all-column anchor sweep, not because check SQL is inherently expensive.

## Severity belongs to the predicate, not to how bad the finding sounds

From the analytics-foundation session (2026-08-14), and the single most useful piece of guidance received. The rule:

**A rule can gate when its predicate is derived from something the system already asserts structurally. It cannot gate when the predicate is a heuristic over a population containing legitimate variety.** In the second case the discrimination the predicate failed to make gets hand-encoded, and an exemption list is where it goes.

Measured both directions against the current `catalog_checks.sql`:

| check                           | predicate keyed on                     | exemptions |
| ------------------------------- | -------------------------------------- | ---------- |
| `entity_view_leaks_bookkeeping` | the derived lifecycle entity set       | 0          |
| `models_has_deleted`            | a view compared against its own source | 0          |
| the `live()` fixtures           | input the fixture supplies itself      | 0          |
| `anchor_dark` (retired)         | "is this column entirely empty"        | 51         |

`anchor_dark` could not tell a broken join from a facet nobody populates, and 51 entries is what that costs. A second probe: pinning "no public view column may hold `''`" needs ~60 entries, and a differently-formulated attempt at the same underlying concern — a text match for a bare `fc.` reference — needs 38, because 38 of 68 views legitimately carry one.

Running this doc's candidates through it, that session's read:

- **`Missing parents` is the one clean `violation`** — a real structural invariant the DB does not enforce, no legitimate exception expected. Born at zero rows, so it needs its proof regardless.
- **`scalar_type_disagreement` reads like a violation but isn't.** Its self-tuning form is minority-flagging over a population, so `review`.
- **Everything else is `review` or `gap`** — vocabulary descriptions, cross-actor disagreement, uncited claims, title-sibling gaps, variant carry, orphan leaves, decaying facts. The prototype's own measurement supports the title-sibling one: "no edge to explain the asymmetry" turned out not to be the noise filter this doc assumed.

### Two caveats on the exemption count

The principle holds. The count is a good symptom of it and a poor test, for two reasons worth knowing before leaning on it:

- **It conflates two failure modes with opposite prescriptions.** A long exemption list can mean the predicate is a bad proxy for the rule (reformulate it) or that the population genuinely contains legitimate variety (downgrade the severity). The `''`-versus-`fc.` probe above is offered as one concern in two formulations hitting one wall, but 38 of 68 views legitimately referencing `fc.` in a semantic layer over an attached database reads more like a mis-aimed predicate than like irreducible variety. Same count, different fix.
- **It cannot classify a rule that has no exemptions yet.** The count is observable only after someone writes the exemptions, so a rule born at zero rows scores zero and the test says nothing. That is exactly `Missing parents`, nominated above as the one clean violation — on judgment ("no legitimate exception expected"), not on the metric. A related gap: narrowing a rule's population makes exemptions vanish without improving the predicate at all, which is what `anchor_dark` restricted to non-sparse columns would have looked like.

Use it to diagnose a rule that is already misbehaving. Don't use it to decide a new rule's severity — for that, ask the structural-versus-heuristic question directly.

## Proof: fixtures and mutations are a pair

This doc previously treated the "known-failing fixture" the flippatch session asked for and the existing mutation harness as alternatives. They are not:

- **A fixture proves the mechanism and cannot prove it was applied.**
- **An outcome check proves application and cannot prove the mechanism.**

The foundation hit this directly. `live()` now carries both, after a sequence where its smoke check was deleted as redundant with `anchor_dark` and `anchor_dark` was deleted in the same breath — two individually defensible changes, one uncovered contract.

For a rule born at zero rows, a fixture supplying the defect is worth more than a mutation, because a mutation against a clean catalog can only break the query and watch it fire.

## Findings are keyed by a relation, not a column

The answer to the prototype's one real break, and the precedent is already in the foundation.

`subject_public_id` is a column, and what the prototype found is that a finding has a _set_ of affected entities. A column cannot hold a set without becoming a list nothing can join on.

`model_edges` is outbound-only, and `model_edges_bidir` exists because "is this model connected to that one" needs both directions — hundreds of live models carry only an inbound edge, so the outbound view answers confidently and wrongly. The spine is outbound-only from its subject in exactly the same way: `jurassic-park-stern` reaches its finding, `jurassic-park-pro` does not, and the query returns nothing rather than erroring.

So keep the spine at one-row-per-finding with its single subject, and add a companion `audit_findings_affected` at one-row-per-(finding, affected entity) — with the subject-grain view contributing to it too, so a finding about its own subject isn't a special case. "Audit this model" joins the fan-out; "what did this rule find" reads the spine. It also gives each rule a place to declare its blast radius, which the detail string can't do and shouldn't try to, since claim values render as raw FK ids.

## Deviation from observed convention, as the default rule shape

The strongest idea to come out of either the [flippatch feedback](#query-the-catalog-for-precedent-instead-of-encoding-judgment) or the [prototype](#prototype-four-rules-measured), and they arrived at it independently at two different grains: rather than encode an expectation, ask what the catalog already does and flag the deviation.

- Relationship grain: 16 of 17 pitch-and-bat models carry `baseball`, so the 17th is a finding; 0 of 21 aliens models carry `science-fiction`, so nothing is.
- Field grain: deriving each field's expected JSON type from the corpus rather than an enumerated field list found `louis-vuitton` carrying `variant_of = ""` against 146 numeric values — a defect no hand-written field list covered.

A rule shaped this way needs no maintenance, adapts as the catalog grows, produces an argument a reviewer can check independently and carries no author's opinion frozen at authoring time. One constraint: 16/17 is a threshold, and `EDITING.md` puts thresholds with the consumer. The template surfaces N and M; each rule picks its own cutoff.
