# Citation Instance Quotes

This is the plan for rationalizing how evidence is quoted on a citation.

## The problem

When creating ChangeSets and Citations, there are multiple competing text fields:

- `ChangeSet.note`: the editor labels it _"Why are you making this change?"_ (rationale), but in practice it's misused. Per [DataPatchAuthoring.md](../../DataPatchAuthoring.md), it carries a **verbatim source quote**: hundreds of data-patch notes embed a quoted excerpt (`<source> says "…"`). Measured against the dev DB (a close prod copy), notes actually mix **three** kinds of content: verbatim quotes, editorial rationale and _paraphrased evidence_ — source facts restated in the author's words (`… lists "Pinball and electro-mechanical games released as Allied Leisure (1968-1979)," and states they renamed it Centuri in 1980`). The design gives the first two a home each; paraphrase stays in the note, which is fine — "what the source states, in my words, and why the value follows" _is_ rationale. Separately, 96.6% of non-empty notes (16,834 of 17,426) are the literal string `Seed import (backfilled).` stamped by the `provenance/0011` backfill migration — pure noise, deleted as part of [the strip](#decision-strip-phased-before-public-launch).
- `CitationInstance.quote`: doesn't exist but should. The fact that it's missing is why people are falling back to the note.
- `Claim.citation`: a free-text field. No live write path populates it — neither the interactive editor (`_assert_claim` is the only code that writes the column, but its caller never passes a value, so it always lands `""`) nor ingest (`_build_claims` constructs `Claim`s without it). Both paths route evidence to `CitationInstance` rows instead. And there is no legacy data either: the dev DB (a close prod copy) has **zero** non-empty values across its 222,118 claims. It's read in three places, but nothing surfaces: (1) description attribution — `rich_text.py` feeds it into `AttributionSchema.attribution_text`, which `AttributionLine.svelte` renders, but only when the license requires attribution and the string is non-empty, so in practice nothing ever displays; (2) the Sources UI — `helpers.py` serializes it onto `ClaimSchema.citation`, but `EntitySources.svelte` never renders that field (it shows `CitationInstance` evidence instead), so it rides the wire unused; (3) `export.py` (data export, not UI). So deleting it is safe on the write side and a pure delete on the read side too: when the text is gone, `AttributionLine` falls back to `Source: <name>` — still gated on `requires_attribution`, so the license is honoured — and the other two readers are unused. The legacy free-text override is intentionally dropped, not migrated; there's no data to preserve.

The "quote" and the "citation reference" are conceptually one unit, but aren't modeled as such. Even the designer of the system has been misusing it; contributors have no chance.

## Design

### Data model

#### 🆕 `CitationInstance.quote`

New field. A verbatim excerpt from the citation source material: only exact source text and ellipsis ("[...]") belong in it. A reviewer should be able to follow the citation's URL and ctrl-F find it (each span, when the quote joins several).

Multi-span policy: a note quoting several passages (~20% of the quoted corpus) becomes one `quote` — the spans joined by `[...]` in source order. Everything non-verbatim stays in the note: connective paraphrase between spans, translations of non-English quotes (the gloss is interpretation, not source text) and inferences drawn from the quote.

Shape: optional (`blank`, default `""`), `validate_no_mojibake` like its neighbour `locator`, and immutable — it rides the already-immutable `CitationInstance`, set once at mint or once by the backfill's `update()`. Its `max_length` must clear the longest historical note-quote so the backfill can't truncate: the old `note` cap was 1,000 and `Claim.citation` was 2,000, so 2,000 is the safe pick.

Not claims-based, despite being user-input. The [claims-based rule](../../../CLAUDE.md) governs _catalog-entity_ fields; `CitationInstance` is evidence _about_ claims, not a catalog entity, so `quote` follows `locator` — also user-input, also unclaimed — as provenance metadata. (The "could a user input this?" test misleads here; the real test is "is it a field of a catalog entity?")

#### ↩️ `ChangeSet.note`

Existing field, re-dedicated purpose. Should not contain quotes, but instead editorial rationale, uncertainty, cleanup comments, merge explanations and paraphrased source evidence — interpretation is rationale; only verbatim text moves to `quote`.

#### ❌ `Claim.citation`

Delete this field.

### Editor "Add citation" panel

Source picker + locator + quote. The quote field is the missing piece.

Adding `quote` to the citation input spec widens the write paths' identity tuple: both the interactive save (`_attach_citations` dedupes specs by `(source_id, locator)`) and ingest (one shared instance per distinct cite per changeset) must treat quotes as part of citation identity — same source and locator with different quotes is two pieces of evidence, not one. This is the same tuple the [References plan's interning](CitationInstanceReferences.md#global-dedup) later hashes.

### Display

The Sources page renders the quote alongside the citation's locator (`EntitySources.svelte` already shows `citation.locator`; the quote joins it). Shipping the field without a reader would defeat the point — the quote exists so a reviewer can follow the citation's URL and ctrl-F it.

### Data patches

[DataPatchAuthoring.md](../../DataPatchAuthoring.md)
— `note:` stops being `'<source> says "<quote>"'`. The quote moves to a `quote:` on the `cite:`; `note:` becomes a real (rarely-needed) edit summary.

`cite:` widens from a scalar to _scalar-or-mapping_: the mapping's `ref:` key takes the exact scalar grammar (`scheme:identifier` or `http(s)://` URL — most quote-bearing cites in the corpus are `ipdb:NNNN`, so the mapping can't be URL-only), plus optional `locator:` and `quote:`. The scalar form stays valid when there's nothing to attach:

```yaml
note: Optional edit summary, rarely needed
cite:
  ref: ipdb:4443 # same grammar as the scalar form
  locator: Optional section or page
  quote: Exact quoted source text
```

The inline `cites:` map (description footnotes, `{url, archive}`) does **not** gain `quote` in this plan — descriptions cite whole articles and per-footnote quoting is a different authoring burden; widen it later if the need materializes.

## Migration

Two complementary data sets, one shared transform. **Unshipped patches** (~50, in [flippatch](https://github.com/deanmoses/flippatch)) are _future_ data for prod — not yet ingested there, so fix them at the source: move each quote out of `note:` and onto the `cite:` before they apply. (Localhost is ahead of prod and has already applied most of them; there the same notes are covered by the DB migration instead — the [equivalence oracle](#the-shared-transform) is exactly the check that both routes converge.) **Already-ingested notes** (in the DB) are _past_ data — fix them in place with a Django data migration. The only thing both halves share is the parser. The load is lopsided: of the 414 quote-notes in the local DB, 401 come from patches already in prod (≤0038) and only 13 from unshipped ones, so the DB migration does nearly all the work and the patch rewrite is small.

### The shared transform

A pure recognizer — no DB, no field dependency:

```
extract_quote(note) -> (quote, residual) | None
```

- Returns `None` for notes that aren't source quotes — the own-data notes (`"Its name contains the word 'prototype'"`), scaffolding, and merge/rationale notes ([DataPatchAuthoring.md](../../DataPatchAuthoring.md)). This is the safety valve: only `<source> says "…"`-shaped notes are touched.
- On a match, returns the verbatim `quote` (the `"…"` span) and the `residual` note (usually empty). Applies the normalizations the convention already mandates — straighten smart quotes, `…` → `[...]`, preserve non-ASCII.

All the real risk lives here, and the corpus is messier than `<source> says "…"`. Measured across the full patch directory (~487 quoted notes): `says` covers 410; the rest use _lists, dates, gives, credits, records, describes, attributes, places, reports_ or no verb at all; ~20% quote **multiple spans** with connective paraphrase between them; and the single most frequent quote-note (46 rows) contains **nested unescaped quotes** (`IPDB says "Also called a "flasher type" slot machine."` — match to the outermost closing quote). So it's the first thing to build (pure, buildable ahead of the field) and is honed on real data before either consumer is wired up. It can't cross the repo boundary (flipcommons ⊥ flippatch), so the ~30-line function is **duplicated** in each rather than shared via a runtime dependency.

The corpus is also _small_ — ~450 distinct DB notes, ~590 patch notes — so the recognizer doesn't need to be complete, only conservative (`None` on any doubt): **every proposed rewrite gets human review** via a generated before/after diff, and the unrecognized tail is fixed by hand. Eyeballing ~300 strings is cheaper and safer than perfecting a grammar.

**Hone on the patches, then reuse on the DB — they're the same strings.** Ingest stores `note:` verbatim (`_parse_provenance` length-checks it but never transforms it), so for every ingest-origin changeset `ChangeSet.note` is byte-identical to its patch file's `note:`. The characterization corpus is therefore the **full** flippatch `patches/` directory, shipped _and_ unshipped: the shipped notes are exactly what the DB migration will encounter, and the ~50 unshipped are just the subset that also gets rewritten at source. Two caveats: the DB additionally holds **interactive** edit notes that no patch sampled (freeform, rarely `says "…"`), so the migration wants a final validation pass against a real DB note dump — low-risk, since `None`-on-no-match leaves an unrecognized note alone rather than mangling it. And the two consumers share a correctness oracle: a rewritten-then-ingested unshipped patch and a migrated shipped patch must reach the **identical** end state — same quote on the instance, same residual note — so `rewrite-then-ingest ≡ ingest-then-migrate` is a property test that catches any strip-rule or transform divergence between the two paths.

### Rewriting the unshipped patches (flippatch)

Per entry, `note:` and `cite:` are co-located, so there's no source-matching: for each entry with both, run the transform and — on a match — attach the quote to that entry's cite, replacing the note with the residual. An entry with a quote-shaped note but no `cite:` (the own-data case) is left alone. This is what widens `cite:` to the mapping form shown under [Data patches](#data-patches). A one-off script rewrites `patches/*.yaml` in place — a flippatch-side change.

### The DB migration (flipcommons)

A data migration over already-ingested notes:

- For each `ChangeSet` with a non-empty note, run the transform; skip on `None`.
- Write the quote to the changeset's field-level `CitationInstance`s (`claims__changeset=cs` through the `ClaimCitationInstance` join — inline description instances have no join rows, so they're naturally excluded). An instance is shared _within_ a changeset (both write paths mint one instance per distinct cite and fan join rows across the save's claims) but never _across_ changesets — verified on the dev DB: no instance's claims span two changesets, let alone two notes — so the quote lands on the changeset's instances with **no disambiguation needed**. The migration only ever touches _historical_ changesets, so this holds regardless of when it runs relative to the References plan's multi-citation writes; it should still assert the invariant (skip + report any changeset whose instances resolve to more than one source) rather than assume it.
- **Write via `QuerySet.update()`, not `save()`** — `CitationInstance` is immutable and its `save()` rejects a row that already has a pk. Retro-filling a newly-added column on immutable rows is a fine one-time migration; superseding instances instead would break their slugs and inline markers.
- Quote-notes with no instance, and unparseable `says`-notes, are **reported, not silently dropped**.
- Measured on the dev DB, the scary cases are empty: all 414 quote-shaped notes have field-level instances, every one resolves to exactly one distinct source, and the longest note is 831 chars — so the no-instance and disambiguation paths should report nothing and the 2,000 cap can't truncate.

### Decision: strip, phased (before public launch)

Strip — rewrite each migrated note to its residual: empty for a pure-quote note, the leftover editorial text for a mixed one. Do it in two migrations so we keep leave's safety and still reach strip's clean end-state:

1. **Populate + leave.** Write `quote`, don't touch the note. Verify against the [equivalence oracle](#the-shared-transform) and a real DB-note dump.
2. **Strip.** Once the transform is proven, blank the notes to their residual. This step also deletes the 16,834 `Seed import (backfilled).` notes (96.6% of all non-empty notes) — `provenance/0011` backfill boilerplate, redundant with the changeset's ingest-run linkage. The recognizer never sees them (not quote-shaped); they go by exact-match update.

Both land **before the public announcement**, and that timing is the whole justification. `ChangeSet.note` _is_ an immutable historical record in principle — but the entire current corpus is Flipcommons-authored scaffolding — overwhelmingly seed-import boilerplate, the rest quote-scaffolding (`<source> says "…"`) — not third-party audit history, so there is nothing to preserve and the immutability objection doesn't yet bite. The bar becomes real the moment the public starts contributing, which is exactly why this must ship first: we're cleaning up our own bootstrapping data before it becomes history others build on. Expected outcome: nearly every existing note blanks; what survives is genuine rationale (merge explanations, disambiguations, paraphrased evidence).

Strip is also what makes the equivalence oracle hold on the note field — a rewritten-then-ingested patch yields an empty note, so the migrated historical note must strip to the same. Leaving would make the two paths permanently disagree there. (The step-4 lint that rejects quote-shaped notes stays forward-only regardless; it guards new writes, not migrated history.)

## Prior art

Wikipedia and Wikidata both keep two things separate, and we should too:

- **Edit summary** — per-revision free text about the _edit act_ ("merged duplicate", "fixed typo"). Optional, often empty. This is **`ChangeSet.note`**.
- **Reference** — typed evidence about a _fact_. Wikidata models this as `stated in` + `reference URL` + `page` + **`quotation` (P1683)** — a typed, verbatim quote field, not a free-form catch-all.

## Phasing

Mostly additive — a new field, a backfill, and the removal of a field nothing writes — so this needs no expand/contract cutover. The ordering that matters is small:

1. **Add `CitationInstance.quote`.** New field; widen the citation input spec (`CitationInstanceCreateSchema`, `cite:`'s new mapping form) with an optional `quote`. Additive, unused.
2. **Write quotes.** The editor "Add citation" panel gains the quote field, the write paths persist it and widen their dedup keys to include it (see [Editor "Add citation" panel](#editor-add-citation-panel)), data patches accept the `cite:` mapping form, and the Sources page displays it. _(Needs 1. Must **deploy** before any rewritten patch reaches R2 — a flipcommons without the widened parser can't ingest the mapping form.)_
3. **Backfill historical quotes.** Move quotes out of `ChangeSet.note` into `CitationInstance.quote`, delete the seed-import boilerplate notes, and rewrite the unshipped flippatch patches — the quote moves driven by one shared recognizer. See [Migration](#migration) for the transform, the immutability gotcha, and the phased strip (must land before public launch). _(Needs 1; independent of 2. This is the backfill [CitationInstanceReferences.md](CitationInstanceReferences.md#interning-must-come-after-quote-is-populated)'s interning waits on.)_
4. **Retire `note`-as-quote.** Once authors have the quote field (2) and history is migrated (3), `note` becomes the edit summary: update its editor label and [DataPatchAuthoring.md](../../DataPatchAuthoring.md), optionally with a flippatch lint rejecting quote-shaped notes so it can't regress. The lint slots into flippatch's existing `RULE_SINCE` per-rule cutoff: patches already shipped to prod keep their historical `note:` text as-authored (their DB rows are fixed by the migration, not the files). Two existing lint rules move with it: `note-required` must accept a cite-with-quote as the unit's explanation (else authors are forced to keep writing notes), and `note-typography` (straight quotes, `…` → `[...]`) extends to `quote:` values.
5. **Delete `Claim.citation`** — independent of 1–4, shippable on its own. Nothing writes it and nothing needs preserving: the attribution line falls back to `Source: <name>` (still honouring `requires_attribution`) once `rich_text.py` stops passing it, and the other two readers (`ClaimSchema.citation` in `helpers.py`, `export.py`) are unused. Remove the three references and drop the column.
