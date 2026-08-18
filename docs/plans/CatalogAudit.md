# Catalog audit

We want to be able to audit / lint the catalog to find data gaps and bugs.

## Use cases

### Most urgent

From flippatch, after applying patch(es) to the db. Only shows problems with a specific set of patches.

Right now, flippatch's [patch validator](~/dev/flippatch/scripts/patch_validation/lint_patches.py) that runs in precommit only does static analyis of the patches. I'd like to additionally run a db-aware analysis in precommit. If the db isn't available it notes that and precommit succeeds. It should show warnings for gaps, not errors.

The immediate impetus is that we are in the middle of authoring a lot of data patches in `~/dev/flippatch/campaigns/0239-descriptions/README.md` and want to vet them as we create them, before shipping them to prod, which turns them immutable. The priority is rules that vet the unshipped patches, meaning implementing just the [rules that need the DB](#rules-that-need-the-db), because static validation exists and works.

### Next in priority

From flippatch, looking at what records fail lint more generally, in order to drive a campaign, such as:

- "all active manufacturers failing lint"
- "all 1970's Bally models failing lint"
- "all rule X errors"

### Not for v1

- From live site, admins (and eventually trusted contributors) can get reports of violations in order to find things to fix, much like flippatch but also scoped to the user: "all records I have touched", "all active manufacturers failing lint", "all 1970's Bally models failing lint"
- From live site, when a user makes edits to a record, let them know issues with it: "Saved. Ways this record could be improved: fill in System, Gameplay Features..."
- From live site, maybe mark a record as thin on the detail page: "This record is a stub". I'm not sure if it would calculate that live, or there'd be some sort of out of band process that annotates it.

## Rules

Think of them as audit or linting rules for catalog structure. Rules must be deterministic, not AI-based. I would imagine we translate all the existing flippatch linting rules into this system, so that we can lint the entire catalog.

## Warnings stand; no acknowledgment mechanism

A warning the author has confirmed as deliberate re-appears on every run, and the first field session asked for a way to record the confirmation (a suppression file keyed on rule + entity + link target, or similar). Decided against, deliberately:

- The analytics layer is derived, read-only and stateless. "This link is deliberate" is an assertion about catalog content, and catalog assertions are claims-based and live in the catalog — a suppression file in either repo is a shadow catalog with no stable key surface (findings carry no structured target column, so it would key on message text and rot on any wording or slug change).
- The noise self-limits in the primary use case: `audit-patches` scopes to the mutable patch window, so a campaign's confirmed warnings leave the pre-commit report when the campaign ships. Standing warnings persist only in the full-catalog lens, which is not operational yet.
- Where the catalog itself holds evidence that a flagged choice is deliberate, the rule reads that evidence instead of asking a human to file a confirmation — see the carriage suppression under [wrong-grain machine wikilinks](#wrong-grain-machine-wikilinks-in-a-description). Suppression by evidence is a rule refinement; suppression by acknowledgment is unaccountable state.

If the full-catalog use case someday accumulates confirmed warnings that no evidence can dissolve, the direction is a claims-based confirmation resident in the catalog, not a file.

## This lives in Flipcommons

This system would live in Flipcommons, Flippatch: it's about overall database coherence, not specifically data patches. Flippatch would invoke it but not own it.

### This would NOT check unapplied patches

This isn't a pre-flight tool to check YAML patch files before they are applied to the database. This linting would happen over the live database. We'd apply the data patches, vet the results, fix the patches, roll back db, re-apply patches, re-vet results.

If a rule could be achieved by linting a YAML patch file without the database, we should do that. Those go in Flippatch's `lint_patches.py` or even better, `patch.schema.json`. The rule might additionally go into this system if we want to build a backlog of data quality issues to address.

These features are off the top of my head: not exhaustive, not well-thought-out, subject to revision, feel free to push back.

## Should we sunset the static patch validator?

This DB-aware linter should contain all the rules of the flippatch static [patch validator](~/dev/flippatch/scripts/patch_validation/lint_patches.py). I don't super want to double-maintain linting rules. Putting them ONLY in this new tool would seem to make the most sense. We'd lose the ability to lint before they go into the database, meaning you couldn't write patches effectively on a machine that did not have the database, but that's pretty much already the case. I think I'm willing to accept that.

I'm NOT saying that the rules in the patch validator have to be automatically applied to the new system. I'm assuming we'll have to rewrite them.

This would not be for v1. V1 is only [DB-aware rules](#rules-that-need-the-db).

## Easy to author

Let's make it easy to add new rules. AI sessions should be able to do this as a side errand without it being their primary job. All the stuff around a rule to be self-contained and not spread out all over the place. Self-documenting. Understandable without reading the entire system. Hard to do the wrong thing, come up with a confidently wrong answer.

## Is this analytics or something else?

Architecturally, I was initially thinking this would be a layer on top of the Flipcommons analytics foundation. However, if we're going to eventually do these checks on prod, I assume DuckDB is a nonstarter in prod because it would load all the Postgres data into the web tier. How important is DuckDB to doing analyses like this? I'm wondering if that means using Django? Raw SQL?

If it IS analytics, here's some thoughts:

- The analytics foundation already defines a check contract: an analysis file exposes `<prefix>_summary` and `<prefix>_checks`, and the runner "fail[s] nonzero if any `*_checks` view has rows" (`README.md:152`). Empty checks = healthy. There's even a meta-gate — check-mutations requires every check to have an entry in `catalog_mutations.tsv` proving it actually fires, enforced in both directions.
- This would NOT go in `catalog_checks.sql`; that's the foundation self-test.
- Dependency-wise, I imagine this would be a layer above the analytics core: it consumes `catalog.sql` but `catalog.sql` is unaware of it.
- If we decide to use analytics let's evaluate Pinexplore's DuckDB analytics architecture, such as the layers, the checks, the way it prints out errors in a later layer. Should we learn or borrow from it?

## Rules that need the DB

This is incomplete.

### Unlinked records in descriptions

In prose (mostly descriptions), entities that are mentioned but not wikilinked. Titles, manufacturers, gameplay features etc. Looks at both name and aliases.

Two mention classes are excluded mechanically rather than left to the reader's judgment:

- **A name inside quotation marks** (straight or curly doubles) is prose quoting a wording, not naming a record, and does not count as a mention.
- **A span inside an occurrence of the record's own name** does not count — "Stern SPIKE" inside "Stern SPIKE 3 is the third generation..." names no sibling SPIKE record. Judged per occurrence, so the same words standing free elsewhere in the prose still count; the record's aliases and paren-stripped name ("Big Dryvers (EM)" appears in prose as "Big Dryvers") own their occurrences too, and a Title and the model it collapses into own each other's names in both directions.

This is a warning not error: what survives can still be legitimate shorthand for something contextually present (a description saying "two months after the Star Wars debut" needn't link the franchise).

### Parenthetical fact cross-check in descriptions

The house pattern when referencing a title or model is "_[[title_or_model:x]]_ (1997, [[manufacturer:williams]])". Error when the year or maker disagrees with the catalog. The error could indicate:

- The year is wrong
- The manufacturer is wrong
- The title/model is wrong (the description wanted `star-trek-data-east` but linked to `star-trek-bally`). This happens a lot when the titles/models are similarly named. We can figure this out deterministically: is there a similarly named title/model that strictly matches more of the stated facts (manufacturer, year) than the linked title/model?

This is an error not warning.

## Feature-carrier consistency in descriptions

The catalog can have two independent assertions about the same fact:

- **The prose**: a gameplay feature's description names a title or model — "The first Mystic Lines game was [[title:border-beauty]] (1965)".
- **The attachment data**: `model_gameplay_features` rows — "model `border-beauty` has feature `mystic-lines`".

The rule: for every title or model wikilinked from a vocabulary record's prose, warn if the linked model — or, for a Title, every model of it — does not carry that record. "Carry" spans every channel by which a model carries a vocabulary term: the M2M attachments (gameplay features, themes, tags, reward types) and the single-valued dims (system, game format). For the DAG vocabularies an attachment to a descendant carries every ancestor — a machine attached to `bash-toys` satisfies a link from `interactive-toys`. A finding means either the attachment is missing or the prose names the wrong machine.

For system and game format the message names the value the machine does carry, because that value is the triage: a sibling generation (`williams-system-11a` under the System 11 description) is usually deliberate prose, a foreign one (a Zaccaria system under a Williams one) is usually a same-named wrong machine linked.

Warning not error. Prose can mention unattachable titles -- like "Model X was the last Gottlieb before they switched to this feature".

### Earliest / first statements

When a gameplay feature or reward type or tag (or probably other record type)'s description says "first machine that...", it's an error: our catalog isn't complete and we have no buisiness making such a statement. Even if it says "first machine in our catalog that...", it's sensationalist. The only time it's acceptable is when accompanied by a citation where someone said that fact somewhere else.

### Repeated-gloss across multiple descriptions

When several descriptions gloss the same term in bare prose — "in-line scoring" is now explained in three places, "backglass" in one — that's the deterministic signature of a missing vocabulary record.

Warning not error. Gap driver, not a defect rule.

### Self-link in a description

A record's description should not wikilink to itself. I don't believe the static lint enforces this rule. It's trivial in the DB: a record whose FK edges include its own record.

Error not warning.

### Wrong-grain machine wikilinks in a description

A description linking [[model:X]] where X's Title collapses into it (the product rule from `titles.py`, not the `title_size = 1` approximation) — should be [[title:X]]. This is an error. If the Title does not collapse, it should be a warning -- there are legitimate cases to link to a model, but the AI should be asked to think about whether it's valid.

One deliberateness signal is mechanical, and the warning does not fire on it: a vocabulary record whose prose links a model that **carries** that record (the limited-edition tag naming the LE builds it attaches to, a gameplay feature naming an attached machine build) has chosen the model grain on evidence the catalog itself holds. Carriage is the same relation the [feature-carrier rule](#feature-carrier-consistency-in-descriptions) checks, so the two rules cannot disagree — one never flags the link the other justifies. Only the warning is suppressed: linking a collapsed model stays an error no matter what the model carries, because its Title is its page.

AIs get this badly wrong, often. This is an important one.

### Duplicate people records

We've had recent cases of creating duplicate people because their names don't match exactly:

- **maiden names**: Ann Baden-Smith vs Ann Smith
- **initials**: Ann E Smith vs Ann Smith
- **middle names**: Ann Emory Smith vs Ann Smith
- **slight misspellings**: Ann Palintin vs Ann Pallintin
- **other forms**: Ann Smith vs Annie Smith
- **nicknames**: Neutrino Smith vs Ann Smith

The people name matching algorithm needs careful design. It should probably over-match, but simply comparing first and last names separately is probably too noisy. This should NOT restrict to the same manufacturer; people switch employers.

Warning not error. People _do_ have the same last names.

### Duplicate non-people records

I'm not sure if this is super helpful outside of people -- models have awfully similar names. We haven't had a problem with manufacturers... but maybe we should? Maybe gameplay features would be useful?

For ANY record type we should warn if:

- exact same name
- exact same alias

Warning not error. Models _do_ have the same name.

### Ambiguous aliases

The same alias string resolving to two records of the same type. Worth doing before the unlinked-records rule, because unlinked-records matches prose against the alias tables and inherits any ambiguity in them.

Error.

### Parentless gameplay feature varieties

Gameplay features whose name is a positional/count/material modifier of another feature's name ("left-X", "upper-right-X", "dual-X", "mirrored-X") with no DAG edge to X.

This is pure name-pattern inference, deterministic, and it would have pre-found two gaps: bally-hole↛trap-holes and mirrored/lenticular-backglasses with no parent to exist under.

### Linkless descriptions

Descriptions with zero wikilinks. Statically checkable but I don't believe we check it, so I'd rather simply implement it here. The DB scan is what would find the backlog: existing system and series descriptions carry no links at all, and that's a ready-made campaign query (second priority).

Exempt: franchise and production status are allowed to not have wikilinks. Not even a warning for these.

Error for all other record types.

### Unlikely facts in scalar fields

Unlikely facts like:

- A PM game in the EM era
- A PM or EM game in the modern era

Warning not error. These CAN happen but they're rare. They don't need the DB, but the static check system doesn't support warnings right now, and I'd rather build this into the new system rather than build warnings into the old system.

### Non-winning claim

A claim in the patches being linted did not win resolution; the author believes they changed the catalog but didn't.

Error not warning. Don't author a claim that does nothing. Except retractions - that is an exemption from the rul.

### Thin records

Things like:

- a model without year or maker
- a person with no credit

Warning not error.

### Model variants that differ

A model that has different facts (tech generation, themes, credits etc) than its parent or sibling variants. A different year is okay.

Warning not error.
