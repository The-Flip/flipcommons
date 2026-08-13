# Catalog linting

We want a way of deterministically checking that the catalog is in a coherent state. It's kind of like catalog structure linting rules. One way we'd use it is to decide what data patches to author, like what vocabulary words are missing descriptions? Another way is to vet just-written data patches: did it fully fill in that model or model family, or fill it in incorrectly?

The immediate impetus is that we've authored a lot of data patches in `/Users/moses/dev/flippatch/campaigns/0215-frontier-2026/README.md` and want to vet them before shipping them to prod, which turns them immutable. The priority is linting rules that vet the unshipped patches.

Here are [potential linting rules](#rules).

## Where this lives

Architecturally, this would be a layer on top of the Flipcommons analytics foundation.

The analytics foundation already defines a lint contract: an analysis file exposes `<prefix>_summary` and `<prefix>_checks`, and the runner "fail[s] nonzero if any `*_checks` view has rows" (`README.md:152`). Empty checks = healthy. There's even a meta-gate — check-mutations requires every check to have an entry in `catalog_mutations.tsv` proving it actually fires, enforced in both directions.

This would NOT go in `catalog_checks.sql`; that's the foundation self-test.

Dependency-wise, I imagine this is a layer above the analytics core: it consumes `catalog.sql` but `catalog.sql` is unaware of it.

This whole thing is a Flipcommons not Flippatch concern: it's about overall database coherence, not specifically data patches. It lives in Flipcommons.

### This would NOT check unapplied patches

This isn't a pre-flight tool to check YAML patch files before they are applied to the database. This linting would happen over the live database. We'd apply the data patches, vet the results, fix the patches, roll back db, re-apply patches, re-vet results.

If a linting concept can be achieved by linting a YAML patch file without the database, we should do that. Those go in Flippatch's `lint_patches.py` or even better, `patch.schema.json`. The rule might additionally go in analytics if we want to build a backlog of data quality issues to address.

## Features

These features are off the top of my head: not exhaustive, not well-thought-out, subject to revision, feel free to push back.

### Whitelisting

I would imagine some rules will need to permanently whitelist exceptions, like "Alexandre Dumas is not a credit" or "yes we're not going to document gameplay feature X".

This could be implemented many ways, such as a rule might carry an inline VALUES exception list, every row with a reason, ala `ref_opdb_manufacturer_exceptions`.

Don't build anything in advance of actually needing it.

### Easy to author

Let's make it easy to add new rules. AI sessions should be able to do this as a side errand without it being their primary job. All the stuff around a rule to be self-contained and not spread out all over the place. Self-documenting. Understandable without reading the entire system. Like maybe each one is its own file like `lint/rules/<rule>.sql`? Just a thought, don't over-index on it.

### Lint a particular area

For authoring a data patch it's probably useful to scope the linting info, such as:

- to claims written by patches ≥ some patch number
- to a particular model, title or manufacturer

I imagine those are just various SELECTs?

## Pinexplore

Before we decide anything, let's evaluate Pinexplore's DuckDB analytics architecture, such as the layers, the checks, the way it prints out errors in a later layer. What should we learn or borrow from it?

Preliminary AI analysis of Pinexplore found the following. This is NOT a user analysis, it could easily be wrong.

### Severity split

`05_error_checks.sql` aborts the build; `06_warning_checks.sql` reports and continues. Two tables, different shapes:

```text
CREATE TEMP TABLE _violations (category VARCHAR, check_name VARCHAR, detail VARCHAR);
CREATE TEMP TABLE _warnings   (check_name VARCHAR, cnt BIGINT);
```

This error/warning split is about build integrity. Some linting rules would produce a third thing — a gap that is legitimate today and authorable later. 540 themes without descriptions is not a warning, it's a backlog. I'd suggest violation (incoherent, gates), review (suspicious but possibly correct — the 525 conflicts), gap (expected nonzero, tracked as a trend, never gates). Only violation fails the build. A layer that reports 540+ rows on every run teaches people to skip the output, which costs you the 29 rows that actually matter.

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

`_anchor_skip` answers your whitelist question, and corrects its premise. It distinguishes two kinds of exemption:

- `sparse` — allowed to be empty indefinitely (a genuinely optional dimension)
- `pending` — expected empty only until data lands, so it must expire

with `expired_anchor_skip` retiring a `pending` entry the moment its facet goes live, and `stale_anchor_skip` catching an entry that names nothing at all. The comment at `catalog_checks.sql:408` is worth reading in full — both pending entries the list has ever carried outlived their reason silently, which is why there's a check instead of a comment asking someone to remember.

`stale_exception` matters more here than it does there, because your exceptions will be keyed by slug and patches rename slugs — 0232 renamed yukon-yeti and its corporate entity mid-campaign. A misspelled or orphaned exception exempts nothing while looking like it exempts something.

**The mutation gate is the single highest-value thing in either repo**, and I'd argue it's more necessary for your lint layer than for the foundation self-test. The reasoning from catalog_mutations.tsv: a check that is broken and a check that is passing both return zero rows, and every defect ever found in that suite was a check that had silently become a no-op, usually via a comparison going NULL. Nearly every rule on your list is a NOT EXISTS / LEFT JOIN … IS NULL shape — precisely the shape that goes quietly no-op. And unlike the foundation, this layer runs against a catalog that patches are actively reshaping underneath it.

## Rules

Here's some candidate linting rules. This is us noodling on what would be useful. It is NOT exhaustive, it is NOT a MUST DO list, it is NOT prioritized. Some are AI-generated in Flippatch, may be YAML centric (and thus invalid), and show numbers scoped to a particluar data patch campaign. I have not vetted and approved them all.

### Variants

Variants should carry all the credits / features (and maybe other fields) of its parent model.

### Missing persons

A person name in cited quotes not credited on that model.

### Missing vocabulary descriptions

A bounded vocabulary record without a description. That's cabinet, display type, display subtype, game format, production status, reward type, tag, technology generation, technology subgeneration.

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
tags                 1 of   4
```

The rule already sketched at the top of this doc covers the **bounded** vocabularies (cabinet, display type, display subtype, game format, production status, reward type, tag, technology generation, technology subgeneration). The open, DAG-shaped vocabularies are the larger backlog by an order of magnitude, and themes are effectively undocumented as a vocabulary. For the "decide what data patches to author" use case this is the single richest source in the catalog.

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

`production_status: announced` on a model whose `year` is now in the past. These claims were correct when written and rot silently — nothing in the current design expires except `pending` entries in `_anchor_skip`.

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

Measured: **it returns zero rows today**. That does not settle whether the constraint is enforced or the data merely happens to be clean, and either way the rule is nearly free to keep.

It is, however, the exact profile the mutation gate exists for — a rule born at zero rows, where a passing check and a silently broken one are indistinguishable.
