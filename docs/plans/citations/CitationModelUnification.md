# Citation Model Unification (sketch)

High-level sketch for review by other AI sessions. Not a full plan. The goal is to agree on the **model shape** before anyone writes a migration.

## The problem

We have multiple free-form text channels competing during an edit, and the UI doesn't match the data model:

- **`ChangeSet.note`** — one free-text note per edit. The in-app editor labels it _"Why are you making this change?"_ (rationale), but in practice — and per [DataPatchAuthoring.md](../../DataPatchAuthoring.md) — it's been used to hold the **verbatim source quote**. Evidence smuggled through a rationale field.
- **`Claim.citation`** — a second free-text field, per claim. Populated only by ingest (source attribution); the interactive editor never sets it. Read for description attribution and the Sources UI.
- **`CitationInstance`** — the structured reference (→ `CitationSource` + `locator`). The editor's "Add citation" creates one but gives **no place for the supporting quote**, which is why authors fall back to the note.

Net: the "evidence note" and the "citation reference" are conceptually one unit (and are authored as a pair in patch YAML — `note:` + `cite:`), but storage splits them across three places with no link, and the UI splits them worse. Even the designer has been misusing it; contributors have no chance.

## Decided

- **`CitationInstance` keeps its name** even though it now carries a quote. No rename.
- **Editing granularity is the ChangeSet.** One click of Save = one ChangeSet = one citation. We do **not** support different citations for different fields in a single editing session — fields needing distinct evidence are distinct saves (distinct ChangeSets). This already matches the patch model, which splits distinct evidence across entries, each its own ChangeSet with its own `cite:`. So the edit-level citation attaches **once to the ChangeSet**, not duplicated per-claim (the current `_attach_citation` fan-out is removed); a claim reaches its evidence via `claim.changeset`. **Exception:** inline prose footnotes are per-marker (see below) — the rule governs the edit-level citation panel, not footnotes.

## Target model — the Wikidata reference shape

Wikipedia and Wikidata both keep two things separate on purpose, and we should too:

- **Edit summary** — per-revision free text about the _edit act_ ("merged duplicate", "fixed typo"). Optional, often empty. → stays as **`ChangeSet.note`**.
- **Reference** — typed evidence about a _fact_, attached to the claim. Wikidata models this as `stated in` + `reference URL` + `page` + **`quotation` (P1683)** — a typed, verbatim quote field, not a free-form catch-all.

So a citation becomes three typed fields, **zero free-form**:

```text
Citation = source pointer (→ CitationSource)   [required]
         + locator (page / timestamp)           [optional]
         + quote (verbatim excerpt)              [optional]
```

Only the **source pointer is required** — matching Wikipedia and Wikidata, neither of which requires a locator. The bar is _independently checkable_, and what achieves that depends on source granularity:

- **Web page** (the dominant case): the URL _is_ the locator. The pointer alone is checkable; no locator or quote needed.
- **Book / magazine**: the source is a whole volume, so it needs a **locator or quote** to be checkable.

So the rule is source-type-dependent: source pointer always; locator-or-quote required only for coarse-grained sources.

The verbatim-quote contract is the key move: it's exactly what we've been asking authors to put in the note, but with a tight contract ("paste the source's exact words") a reviewer can ctrl-F. It replaces the free-form text instead of adding to it.

This leaves **one free-form field in the whole flow** — the edit summary — and it's unambiguously about the edit, not the evidence.

## Changes implied

- **`ChangeSet.note`** — keep, reframe as edit summary. Also absorbs the sourceless case (typo, merge, "name contains 'prototype'"): no citation, just a summary.
- **`Claim.citation`** (free text) — retire. Its description-attribution role derives from the claim's `CitationSource` / license instead.
- **`CitationInstance`** — add **`quote`** (verbatim); keep `locator` and `citation_source`. This is the Wikidata reference.
- **Attachment** — a `CitationInstance` is owned by exactly one of two things: the **ChangeSet** (the edit-level citation, one per save — per the granularity decision) or a **Claim** (an inline footnote). The per-claim fan-out (`_attach_citation`) is removed; a structured field reaches its evidence via `claim.changeset`. This likely means a `changeset` FK on `CitationInstance` alongside the existing `claim` FK, with exactly one set.
- **Inline footnotes** — the same `CitationInstance`, but with `claim` set to the description claim instead of `claim=null`. Today they're orphaned (`claim=null`) on **both** paths — ingest and the interactive editor (`create_citation_instance` in `provenance/api.py` returns `claim_id=None`) — which is why they don't appear in edit history; history follows the `claim` FK. Giving them a real owner fixes that for free, for both paths.
- **Editor "Add citation" panel** — source picker + locator + quote. The quote field is the missing piece.
- **[DataPatchAuthoring.md](../../DataPatchAuthoring.md)** — `note:` stops being `'<source> says "<quote>"'`. The quote moves to a `quote:` on the `cite:`; `note:` becomes a real (rarely-needed) edit summary.

## What this resolves

- One free-form field, clearly scoped to the edit. The "multiple competing notes" nonstarter goes away.
- Evidence travels with the fact — a structured field reaches its citation via `claim.changeset`, an inline footnote via the claim it sits on. Both survive future changesets.
- Inline description footnotes become visible in edit history.
- Structured-field citations and prose footnotes (Wikipedia `<ref>`) are the _same_ `CitationInstance`, differing only by owner: a ChangeSet (edit-level) or a Claim (inline).

## Prior art in this repo

- [CitationsDesign.md](CitationsDesign.md) — current high-level citation design (inline markers, contributor flow).
- [CitationDecisions.md](CitationDecisions.md) — earlier decisions.
- [CitationAutogenerationDesign.md](CitationAutogenerationDesign.md) — autogeneration.

This sketch supersedes the storage split those assume; it does not change the inline-marker authoring UX.
