# Citation system audit (beyond the write layer)

A full-system audit of the citation surfaces the write-layer audit didn't cover. [CitationWriteLayerDebt.md](CitationWriteLayerDebt.md) inventoried the **source-side write paths** (minting `CitationSource`/`CitationSourceLink`/`CitationSourceRootDomain`). This covers the rest: the **data model itself**, the **read/display path**, the **authoring frontend**, **extraction/autogeneration** and **ingest/attachment**. Purpose: confirm we've found all the debt before committing to a build sequence — convert an open-ended worry into a finite list.

Severity: 🔴 foundation · 🟠 bites now · 🟡 latent · 🟢 cosmetic. Migration = does fixing it force a schema migration on `CitationInstance` / `Claim` / `ChangeSet`. Coverage = already in a design sketch ([CitationUrlModel.md](CitationUrlModel.md) / [CitationModelUnification.md](CitationModelUnification.md)) or **NEW**.

## Headline

**No new _surface_ turned up.** Every finding lands in one of three altitudes already circled by existing docs — nothing surfaced in a corner no one had looked at. The reassuring conclusion: the set is closed.

**The center of gravity is `CitationInstance`.** The costly, migration-forcing debt concentrates on one table, and **two independent sketches rewrite it in the same migration** (`CitationUrlModel` adds `access_url`; `CitationModelUnification` adds `quote` + a `changeset` FK and retires `Claim.citation`). That coupling — one column, one migration — is the thing that wasn't sequenced before this audit.

The three altitudes:

- **A. Write layer** (source minting) — [CitationWriteLayerDebt.md](CitationWriteLayerDebt.md); behavior-preserving; the [CitationsCleanup.md](CitationsCleanup.md) work.
- **B. `CitationInstance` shape** — the migration cluster (access_url, quote, attachment reshape). Deferred; two sketches converge here.
- **C. Recognition / extraction** — archive-URL peeling (unbuilt), child-URL fragmentation (D10/D11). Partly in [CitationDomainGovernance.md](CitationDomainGovernance.md), partly deferred.

## The current `CitationInstance` shape (the load-bearing fact)

`provenance/models/citation_instance.py`. Fields: `slug` (8-char, unique, immutable), `citation_source` (FK PROTECT, required), `claim` (FK PROTECT, **nullable**), `locator` (char, blank), `created_at` (`auto_now_add`). Row is **immutable** — `save()` rejects updates, so corrections mint a fresh row (old one orphaned). **Absent:** `quote`, `changeset` FK, `access_url`, `accessed_at`.

Three things the sketches assume but the model doesn't have today:

- **Access URL lives on `CitationSourceLink`** (the child's `reference` link), not the instance — `CitationUrlModel` moves it.
- **Archive URL is a sibling `CitationSourceLink`** (`link_type="archive"`), not hanging off the access URL — the deferred archive tier moves it.
- **`Claim` → `CitationInstance` is one-to-many with no owner guard** — a claim can carry N instances; nothing says which (if any) owns the citation. `CitationModelUnification`'s `changeset`-XOR-`claim` ownership is what closes this.

## Inventory by surface

### Data model

| id  | finding                                                                       | anchor                                    | sev | migration                | coverage                    |
| --- | ----------------------------------------------------------------------------- | ----------------------------------------- | --- | ------------------------ | --------------------------- |
| DM1 | `access_url` lives on the child's `reference` link, not on `CitationInstance` | `citation/models.py` (CitationSourceLink) | 🟠  | yes (move to instance)   | CitationUrlModel            |
| DM2 | `archive_url` is a sibling link (`link_type="archive"`), not hung off access  | `citation/models.py`; `extractors.py:376` | 🟡  | yes (later archive tier) | CitationUrlModel (deferred) |
| DM3 | `Claim.citation` free-text, ingest-only, never set interactively              | `provenance/models/claim.py`              | 🔴  | yes (retire)             | CitationModelUnification    |
| DM4 | `ChangeSet.note` dual-semantics (edit summary vs smuggled quote)              | `provenance/models/changeset.py`          | 🔴  | no (reframe)             | CitationModelUnification    |
| DM5 | `Claim`→`CitationInstance` one-to-many, no owner guard                        | `provenance/models/claim.py`              | 🔴  | yes (ownership)          | CitationModelUnification    |
| DM6 | `created_at` doubles as access date; fabricated for ingest                    | `citation_instance.py`                    | 🟡  | no (v1 accepts)          | CitationUrlModel (deferred) |

### Read / display

| id  | finding                                                                                                             | anchor                                                                   | sev | migration          | coverage                                    |
| --- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ | --- | ------------------ | ------------------------------------------- |
| RD1 | `is_abstract`/`skip_locator` are derived hints that hardcode `source_type`                                          | `citation/models.py:255,259`                                             | 🟠  | no                 | CitationsCleanup C4 (strategy)              |
| RD2 | no `access_url`/`quote` slot in any output schema or the markdown footnote metadata                                 | `citation/schemas.py`; `provenance/apps.py:28`; `provenance/evidence.py` | 🟠  | follows B          | CitationUrlModel / CitationModelUnification |
| RD3 | description attribution reads `Claim.citation` free-text                                                            | `catalog/engine/rich_text.py`                                            | 🟠  | yes (model change) | CitationModelUnification                    |
| RD4 | `build_sources` reads per-claim citations; needs changeset-level lookup after reshape                               | `provenance/helpers.py`                                                  | 🟠  | yes (model change) | CitationModelUnification                    |
| RD5 | inline footnotes (`claim=null`) invisible in edit history (history follows the claim FK) — **by design, not a bug** | `provenance/history.py`                                                  | 🟢  | no (owner fix)     | CitationModelUnification                    |
| RD6 | child-URL fragmentation re-surfaces from the read side (D10/D11)                                                    | `extractors.py:179,342`                                                  | 🟡  | no                 | deferred (DomainGovernance home)            |

### Frontend authoring

| id  | finding                                                                                                                                                                        | anchor                                                        | sev | migration | coverage                   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------- | --- | --------- | -------------------------- |
| FE1 | no quote input anywhere; authors smuggle the quote into `note`                                                                                                                 | `NotesAndCitationsDetails.svelte`                             | 🔴  | —         | CitationModelUnification   |
| FE2 | note label "Why are you making this change?" contradicts its evidence use                                                                                                      | `NotesAndCitationsDetails.svelte`; `SectionEditorForm.svelte` | 🟠  | —         | partial (relabel)          |
| FE3 | `citation-types.ts` hand-maps three overlapping schemas (D16)                                                                                                                  | `citation-types.ts`                                           | 🟡  | —         | CitationWriteLayerDebt D16 |
| FE4 | quote field is the expensive frontend change (state machine, source-type-aware validity, ~5 components); access_url is cheap (one field); retire `Claim.citation` is a relabel | —                                                             | 🟠  | —         | NEW (sizing)               |

### Extraction / autogeneration

| id  | finding                                                                                                                                                   | anchor                                       | sev | migration           | coverage                                        |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- | --- | ------------------- | ----------------------------------------------- |
| EX1 | **archive-URL peeling is unbuilt** in both `recognize_url` and extraction — a Wayback URL recognizes against `web.archive.org`, not the embedded original | `extractors.py:119`; `url_extraction.py`     | 🔴  | no (additive logic) | **NEW** (CitationUrlModel assumes it)           |
| EX2 | extract draft is a **pickled dataclass** cached `extract:v2:*`; shape change needs a manual `v3` bump or stale drafts deserialize wrong                   | `extraction.py:130`; `url_extraction.py:162` | 🟡  | no                  | **NEW** (D17 names the cache, not the landmine) |
| EX3 | `safe_fetch` is correctly scoped (SSRF guard, no normalization) — no debt                                                                                 | `safe_fetch.py`                              | 🟢  | no                  | OK                                              |
| EX4 | extraction produces no quote — correct by design (quotes are cite-time hand-entry, not extracted)                                                         | `extraction.py`                              | 🟢  | no                  | OK                                              |

### Ingest / attachment

| id  | finding                                                                                                                                             | anchor                                | sev | migration       | coverage                                      |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | --- | --------------- | --------------------------------------------- |
| AT1 | `_attach_citation` **fan-out** clones one `CitationInstance` per claim in the changeset                                                             | `claim_edit/claim_write.py:240`       | 🟠  | yes (de-fanout) | CitationModelUnification                      |
| AT2 | `create_citation_instance` returns `claim_id=None` → orphaned footnotes, no post-hoc attach path                                                    | `provenance/api.py:332`               | 🟠  | maybe           | CitationModelUnification (partial)            |
| AT3 | patch `note:`/`cite:` parsing has no `quote:`; the quote is smuggled into `note` free text                                                          | `claim_ingest/patches/parsing.py:457` | 🔴  | yes             | **NEW** (no extraction/backfill rule drafted) |
| AT4 | `ChangeSet.action` (`action iff user`) does not conflict with a new `changeset` FK; `PROTECT` means a changeset holding a citation can't be deleted | `provenance/models/changeset.py`      | 🟢  | yes (add FK)    | CitationModelUnification                      |

## The surprises (not captured by the two sketches)

1. **`CitationUrlModel`'s "archive-cited pages work day one" is false (EX1).** Wayback-peeling is the v1 prerequisite and it's entirely unbuilt. Corrected in CitationUrlModel.md; the peeling itself is deferred (a `DomainGovernance`-adjacent additive follow-up).
2. **The quote migration is bigger than "add a field" (AT3/FE1).** Quotes are smuggled into `ChangeSet.note` as free text (`'<source> says "…"'`). There's no extraction heuristic and no backfill strategy to lift them into a `quote` column — `CitationModelUnification` says "the quote moves to `quote:`" and stops.
3. **"One ChangeSet = one citation" is _not_ a UI collision — correcting an earlier overstatement.** The editor already presents exactly one citation per save (a singular `citation` input, [claim_write.py:273](backend/apps/claim_edit/claim_write.py#L273)), and a warning enforces the discipline ("This citation will apply to all changed fields in this save. Split unrelated edits if needed.", [EditCitationField.svelte:68](frontend/src/lib/components/input/citation/EditCitationField.svelte#L68)). The only mismatch is **internal storage**: `_attach_citation` realizes that one citation by cloning a `CitationInstance` per claim (AT1). `CitationModelUnification`'s de-fan-out makes storage match the model the UI already implements — alignment, not conflict.
4. **Orphaned interactive footnotes have no fix path (AT2).** The sketch says "give them an owner" but there's no interactive flow to attach an orphaned instance post-hoc or prevent orphaning at creation.
5. **The `changeset`-FK backfill is ambiguous (AT1/DM5).** Flipping existing field-level cites to changeset-level by joining `claim.changeset` isn't provably correct.
6. **Pickle-cache versioning is a latent landmine (EX2).** Any `ExtractionDraft` shape change silently corrupts cached drafts unless the hand-maintained `v2` string is bumped in two places.

## What this means for sequencing

- **Altitude A is independent and safe to go first** — the write-layer cleanup touches `CitationInstance` nowhere. It's [CitationsCleanup.md](CitationsCleanup.md).
- **Altitude B is one decision, not two** — `access_url` and the attachment reshape rewrite the same rows. Settle the `CitationInstance` target shape once (reconciling the two sketches and answering surprises 2, 4, 5) before migrating, or you migrate twice. Deferred; not yet planned.
- **Altitude C splits** — enabling subdomain matching + the public-suffix guard is [CitationDomainGovernance.md](CitationDomainGovernance.md); archive peeling (EX1) and child-URL fragmentation (D10/D11) are deferred, with `DomainGovernance`'s recognizer as their future home.
- **The big migration is medium-weight, not trivial** — `CitationModelUnification` (changeset FK + backfill + de-fan-out + quote column + wiring inline-footnote owners) is on the order of ~200–250 lines of migration plus ~150–200 of app code, with no architectural dead ends.
