# Citation Instance References

This doc rationalizes how Citation Instances are referenced. It replaces `CitationInstance`'s nullable `claim` foreign key with a `ClaimCitationInstance` join for scalar/edit citations — so those claims point at shared evidence instead of each instance owning one claim — while inline footnote cites stay positional markers pointing straight at the shared evidence. This fixes three data problems and frees `CitationInstance` to move into the citation app.

## The problem

Here's the current parent hierarchy for Citation Instances:

`CitationInstance.claim_id` → `Claim.changeset_id` → `ChangeSet`.

`CitationInstance` is evidence — conceptually part of Citations — yet holds a foreign key to a single owning `Claim` (part of Provenance). This FK is the root of everything here, in two independent ways:

- **Layer**: because Provenance sits above Citation in the system's architectural layers, the FK drags `CitationInstance` up into the Provenance layer. See [App Boundary](#app-boundary).
- **Cardinality**: owning evidence by one `Claim` causes the data symptoms below (#1 and #2). #3, multiple-citations, is a separate issue that will be fixed by the same solution.

### 1: `CitationInstance.claim_id` is nullable

The `CitationInstance` points at a `Claim` for scalar/field-level citation, but it's null when the `CitationInstance` is an inline markdown footnote ([[cite:id]]); its only tie to the owning markdown is the marker embedded in that claim's text.

This is inconsistent and broken: a single-owner column that's null for every inline cite. The fix isn't to make it `NOT NULL` — it's to remove it (scalar cites move to the join; inline cites keep only their marker). It was made nullable so that the UI doesn't show these claims the default way, but rather inline in the markdown. That puts the cart before the horse; the UI special-ness should be handled in the UI where it lives, not the data model.

### 2: Duplicated CitationInstances per ChangeSet

In the UI, when the user clicks 'Save' in an editor, they may be editing multiple fields, and any citation they attach is evidence for that whole save — by design it backs every field they changed. The data model should therefore share one citation across those fields. Instead it creates a `Claim` per field edited and a separate `CitationInstance` clone for each, so the single piece of evidence the contributor offered fragments into N identical rows with nothing linking them.

### 3: Cannot attach multiple citations to a ChangeSet

In the UI, when a contributor clicks 'Save' in an editor, they should be allowed to attach multiple pieces of evidence. However, right now, they can only attach one citation.

## Design

The core is a **join table** for scalar/edit citations: through `ClaimCitationInstance`, a `Claim` reaches **0..N** `CitationInstance`s and a `CitationInstance` is reached by **0..N** `Claim`s. `CitationInstance` stops referencing a single `Claim`. Inline footnote cites don't use the join at all — they stay positional `[[cite:…]]` markers pointing straight at the same shared evidence (see [Inline footnotes stay marker-native](#inline-footnotes-stay-marker-native)). This fixes all three stated problems.

```text
ChangeSet
  ▲  FK PROTECT
Claim                      immutable; one per edited field in the save
  ▲  FK CASCADE
ClaimCitationInstance      support edge for scalar/edit cites — 1 row per (claim, instance)
  ▼  FK PROTECT
________________ ⬆️ provenance app ___ citation app ⬇️ ________________
CitationInstance           a piece of evidence — shared; inline [[cite:slug]] markers point straight here
  ▼  FK PROTECT
CitationSource             the cited work — already shared by identity
```

### What this satisfies

- Each `Claim` lives in exactly one `ChangeSet` — unchanged.
- Each `Claim` is supported by **0..N** `CitationInstance`s — via the `ClaimCitationInstance` join.
- Identical clones are gone — **one row per distinct citation**, shared across the save's claims through join rows. _(#2)_
- Multiple citations attach to **the claims, not the `ChangeSet`** — which gets no citation FK. _(#3)_

### 🔁 `CitationInstance` — flip from owned to shared

- ❌ **Drop the `claim` FK.** This is the fix for "`CitationInstance.claim_id` is nullable": the instance no longer references a single claim, so there is no nullable column. Scalar cites reach it through the join; inline cites reach it through their marker.
- ↩️ **Keep `slug`** — still the author-stable handle for inline `[[cite:slug]]`.
- ↩️ **Still immutable.** Corrections create a new instance and the old one orphans (already the rule).

### 🆕 `ClaimCitationInstance` — the support edge

A join model, not a bare `ManyToManyField`: an explicit through table is what lets the instance FK be `PROTECT` (a bare M2M cascades both sides) and lets the uniqueness constraint carry an explicit name. It carries **scalar/edit citations only**.

```python
class ClaimCitationInstance(models.Model):
    claim = models.ForeignKey("provenance.Claim", on_delete=models.CASCADE, related_name="citation_links")
    citation_instance = models.ForeignKey("provenance.CitationInstance", on_delete=models.PROTECT, related_name="claim_links")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["claim", "citation_instance"], name="prov_claimcite_unique"),
        ]
```

- **No `changeset` FK.** Provenance derives through `claim.changeset` — the link is born in the same write as its claim, so a denormalized changeset would be a second source of truth.
- **No `created_at`.** Same reasoning: the link is born with its immutable claim and never added later, so its creation time is always `claim.created_at`. A timestamp here would be a derived row's timestamp, which [DataModeling.md](../../DataModeling.md) says derived rows don't carry. Both timing and provenance come through `claim`.
- **PROTECT on the instance** — shared evidence can't be deleted out from under a citing claim. **CASCADE from the claim** treats the link as wholly owned by the immutable claim.
- **Unique `(claim, citation_instance)`** — a claim citing the same evidence twice is meaningless.
- Effectively append-only, matching the claim lifecycle: superseding a claim creates a new claim with its own links; the old links remain as history.

Surface it on `Claim` as a `through` M2M, so the read side barely changes:

```python
# on Claim
citation_instances = models.ManyToManyField(
    "citation.CitationInstance", through="ClaimCitationInstance", related_name="claims"
)
```

This is the same explicit through table, not a bare M2M — it just exposes a read manager. `claim.citation_instances` keeps returning `CitationInstance`s with the prefetch shape the read helpers already use, so the read switch shrinks to almost nothing. The write path still creates `ClaimCitationInstance` rows explicitly (that's the fan-out); the M2M is read-only convenience. Transition note: the old `CitationInstance.claim` FK owns the `citation_instances` related_name until it's dropped, so introducing the M2M needs a state-only migration that first renames that reverse accessor.

### App boundary

The system has strict layers. Dropping the `CitationInstance.claim` FK changes allow us to move `CitationInstance` to the correct layer: from the `provenance` to the `citation` app.

This layering is enforced via import-linter. The import-linter spine ([pyproject.toml](../../../backend/pyproject.toml)) is, high → low: `... > provenance > citation > accounts > ...`. Higher tiers may import lower; lower may not import higher.

Once the FK is gone, `CitationInstance` moves down into the `citation` app beside `CitationSource`. The `citation` app will then own the whole evidence domain: the work (`CitationSource`) and the evidence drawn from it (`CitationInstance`). The manager, slug minting and validators move with it.

The claim ↔ evidence edge — the only thing that must know about both `Claim` and `CitationInstance` — is isolated in the **`ClaimCitationInstance`** join table, which stays in **provenance** beside `Claim` and imports `CitationInstance` _downward_ (i.e., the allowed direction) from the `citation` app. So the relocation makes the spine more honest: nothing in citation reaches up, and the single upward concern lives in the higher tier where `Claim` already is. `claim_ingest`, a top-level consumer that may import both tiers, just retargets — `CitationInstance` from citation, `ClaimCitationInstance` from provenance.

### Inline footnotes stay marker-native

An inline `[[cite:slug]]` cite is **not a claim** and gets **no join row**. A `Claim`'s two defining jobs are to _hold a fact_ and to _bear responsibility in resolution_ — and an inline footnote does neither. It holds no value (the statement lives in the markdown field's value, which _is_ the claim), and it doesn't resolve (competing footnotes coexist; they don't pick a winner). Forcing it onto the claim↔evidence join would overload the concept of a claim. An inline cite is a **positional pointer from prose to shared evidence**: the marker carries the position and resolves straight to the `CitationInstance` by pk, exactly as rendering already does (`cite` is an ordinary wikilink type — its `[[cite:slug]]` ↔ `[[cite:id:pk]]` authoring/storage split and footnote rendering live in [Markdown.md](../../Markdown.md)).

This is still the fix for problem #1: the nullable `claim` FK dies for everyone. Scalar cites move to the join; inline cites need _no_ claim column at all — the marker is their whole tie to the text. There's no `claim=NULL` channel because there's no claim column, and no second write channel because inline support was never a claim to begin with.

`CitationInstance` keeps its `slug` (the marker's target) and stays immutable. An inline instance simply has **zero join rows** — it is reached only by its marker.

**Creation and GC.** Interactive authoring mints the instance eagerly — the editor needs the slug _now_ to write `[[cite:slug]]` — via the same create primitive edit cites use; ingest mints from numeric handles (`_materialize_inline_citations`) or reuses an existing slug. None of these create a join row. An abandoned draft leaks an orphan instance — the same leak as today's stranded `claim=None` rows, reshaped. GC handles it, keyed on **marker presence, not join count** (inline instances are zero-join by construction): delete an instance that no marker references. The invariant is **never delete a marker-referenced instance** — rendering resolves marker→instance by pk, so deleting one produces a visible `[broken link]`, and that includes markers in superseded/historical claim text, which `RecordReference` (active-only, see [Markdown.md](../../Markdown.md)) doesn't see. So scope GC to recently-created, never-referenced instances — the abandoned-draft window, where marker-absence is near-certain because the draft's markdown was never persisted. The residual risk is a save-then-unmark-within-the-window row, which is persisted-and-superseded and looks marker-absent to active-only `RecordReference`; the never-blanket-delete-historical bound guards it. (GC isn't built by this plan — this is guidance for whoever does.) We won't use ingest-style temp handles (deferring the mint to save): they'd defer only the thin instance, not the **source** — whose creation (recognize / extract / cite-url) is the real machinery and runs eagerly regardless — so the source still leaks on abandon and the complexity buys nothing the GC doesn't.

### Write path and API

- Request schema: `citation: CitationReferenceInputSchema | None` → **`citations: list[...]`** (0..N), each entry a content spec (`citation_source_id, locator` — the fields that exist today; `quote` and `access_url` widen the spec as [CitationInstanceQuotes.md](CitationInstanceQuotes.md) and [CitationInstanceUrls.md](CitationInstanceUrls.md) land). This is the fix for "cannot attach multiple citations". The contributor describes the evidence and the backend mints the instance, replacing today's "pre-create an instance, reference it by id, clone it per claim" indirection.
- `_attach_citation` → `_attach_citations` ([claim_write.py](../../../backend/apps/claim_edit/claim_write.py)): for each distinct citation the contributor entered, **create one `CitationInstance`**, then **fan out** a `ClaimCitationInstance` to every claim in the changeset. One shared row per citation per save, not one clone per claim — the fix for "duplicated CitationInstances per ChangeSet". The citations land on the claims, never on the `ChangeSet`.

**One backend primitive.** Both edit and inline mint instances via a single `create_citation_instance(spec) -> CitationInstance` over one content-spec schema; every instance is slugged (as today — scalar cites already carry an unused slug). There's no slugged/slugless variant and no second validation path. The only difference is what happens next: edit cites ride the save payload (`citations: list[spec]`) and the save handler fans a **join row** to every claim; inline cites hit the standalone create endpoint eagerly (the editor needs the slug now) and get **no join row** — their marker is the link. So the create primitive is shared; only edit cites touch the join.

## Follow-ups

### Global dedup

Everything above dedups **within a ChangeSet** by write-path construction. It does **not** de-duplicate globally, across disparate ChangeSets: two separate saves citing the identical source, locator and quote currently produce two `CitationInstance` rows. This is because the row identity can't answer "what else in the catalog cites this same evidence?"

If we want to dedup globally (a question to be decided later), we'd do it via _interning_.

- 🆕 **Add `content_hash`, `unique=True`** — a fixed-length digest of the normalized identity tuple `(citation_source_id, locator, quote, access_url)`. A stored hash beats a raw-tuple UNIQUE because `quote` is long-text — a fixed-width indexed column is the cross-backend-safe way to enforce identity.
- The write path's "create one `CitationInstance`" step becomes **get-or-create by `content_hash`**, so identical evidence resolves to one row globally. `slug` is minted once at first interning and reused on every later hit.
- Adding the hash is an additive column plus a one-time merge-duplicates backfill (collapse existing rows that share a hash, repoint their join rows and inline markers to the survivor).

Two citations collapse only when all of `(source, locator, quote, access_url)` match, so the realistic payoff is narrower than "dedup all evidence". A free-text `quote` is almost never byte-identical across independent saves, so quote-bearing citations rarely dedup. The real win is citing **without a quote**: identity reduces to source + locator, and repeated quote-less citations of the same page collapse to one row — the common web case. `access_url` barely participates: in nearly all cases it equals the source's own URL, so it rarely discriminates beyond what `source_id` already does.

#### Interning must come after `quote` is populated

This is the one real ordering constraint. [CitationInstanceQuotes.md](CitationInstanceQuotes.md) backfills `quote` from `ChangeSet.note` — a per-changeset value, orthogonal to the merge key. Interning earlier, over just `(source, locator)`, would merge two saves whose quotes differ into one row, and the backfill couldn't split them apart: each quote still lived off-row on its own `ChangeSet.note` at merge time, so the survivor can hold only one. Un-merging would mean walking the join rows (claim → changeset → note) — a lossy re-partition. So quote backfill precedes interning.

`access_url` carries no such constraint and ships independently: its backfill is a function of the source, already in the merge key, so it's constant within any merge group and never splits a row. It can land before or after interning (after just means a one-time hash recompute).

## Prior art

Wikidata attaches references at the `statement` level (its analog of `Claim`), never at the edit or revision level: if one source supports five statements, the reference is repeated on all five rather than hoisted to the edit. A reference bundles its descriptive fields — reference URL, page, quote, dates — into one unit, and a statement can carry several.

It gives identical references a **shared identity** via a content hash of those fields, so it can recognize "what else cites this evidence" and, in the graph model, collapse them to a single shared vertex. Its JSON storage still repeats them inline — a known redundancy it has an open proposal to fix by hoisting them into a hash-keyed shared table.

Our model already shares at the source level: many `CitationInstance`s point at one `CitationSource`. So unlike Wikidata's JSON storage — which repeats the whole reference inline on every statement — we never duplicate the work's metadata; only the thin instance row (its `locator` and the source FK) can repeat. What we lack is identity one rung lower: two instances with the same source and locator are separate rows, so the catalog can't recognize them as the same evidence or answer "what else cites this exact page". That instance-level dedup is what interning [Global dedup](#global-dedup) would add — an enhancement on top of our existing source sharing.

## Phasing

Each section below is its own commit. We review on commit boundaries, not PRs. Stage the files then 🛑 STOP for user review before committing. Each commit is independently shippable; the user will make a call as we go on when to cut a PR.

In code comments and commit/PR messages, do not reference ephemera like EXP2 or plan docs or system state that no longer exists.

The three phases follow the expand/contract (parallel-change) migration pattern: **Expand** adds the new structure and writes both representations, **Migrate** moves data and readers across, **Contract** removes the old. Old and new coexist until Contract — so every commit is green and the schema is consistent at each boundary.

### ✅ DONE: <a id="exp">EXP</a> - Expand

#### ✅ DONE: <a id="exp1">EXP1</a> - Add ClaimCitationInstance

Add the ClaimCitationInstance join model — table, constraints, PROTECT/CASCADE, test factories, constraint tests. Pure additive, nothing uses it yet.

#### ✅ DONE: <a id="exp2">EXP2</a> - Write scalar joins

Dual-write scalar join rows, while keeping today's clone-per-claim + claim FK. `_attach_citations` (edit/scalar) fans a join row to every claim in the save. Inline cites get **no** join row — they stay marker-native — so `_materialize_inline_citations` is unchanged (it keeps minting instances from numeric handles; inline instances remain `claim=None` until the column is dropped in Contract). Behavior unchanged; new scalar data now carries join rows. (Transitional — the clone/FK half is removed in [Switch writes](#con1).)

### <a id="mig">MIG</a> - Migrate

#### ✅ DONE: <a id="mig1">MIG1</a> - Backfill scalar joins

Backfill scalar join rows from the old `CitationInstance.claim` FK — a direct, lossless 1:1 synthesis. Inline cites are `claim=None` today, get no join and need no backfill (no `RecordReference` synthesis, no markdown parsing, no winner-mapping). Must be idempotent — re-running creates no duplicate join rows (the unique `(claim, citation_instance)` constraint backstops it). Also collapse the historical per-ChangeSet scalar clones the old write path made: group instances by `(changeset, source, locator)`, keep one survivor and repoint every affected claim's join row at it — within a changeset those clones are identical by construction, so the merge is safe, and it makes problem #2 fixed retroactively rather than only for new writes. Only claim-linked scalar clones collapse; inline instances are pinned by their `[[cite:id:pk]]` markers and are left alone. Tested at the frozen migration state — backfill synthesis, clone collapse, inline (`claim=NULL`) instances untouched, idempotent re-run — with the clone fan-out reproduced through the ingest apply path rather than literal patch files.

#### ✅ DONE: <a id="mig2">MIG2</a> - Switch reads

Switch scalar reads to the join. First the name handoff: the old `CitationInstance.claim` FK still owns the `citation_instances` related_name (it isn't dropped until [Drop CitationInstance.claim](#con2)), so this commit does a **state-only migration renaming that reverse accessor**, then **adds the `through` M2M** under `citation_instances`. With that, `claim.citation_instances` (and the prefetch string in [helpers.py](../../../backend/apps/provenance/helpers.py)) now resolves through the join, so most read sites — evidence assembly, history.\_field_change_citations, API response builders, the citation_instances(claim) helper, admin — need no change; inline cites don't appear there, exactly as today (they carry no join). What actually moves is any site that traversed the old FK directly. Also reshape the citation-instance API: `CitationInstanceSchema.claim_id` (singular) is meaningless once an instance has 0..N claims — drop or replace it, and switch the `/api/citation-instances/?claim=` filter ([api.py](../../../backend/apps/provenance/api.py)) to query through the join. Codegen + frontend/test updates follow. claim FK still present but no longer the source.

### <a id="con">CON</a> - Contract

#### ✅ DONE: <a id="con1">CON1</a> - Switch writes

Rework writes + API to the shared model — request schema citation → citations: list[content-spec] (source_id, locator), \_attach_citations mints one instance per distinct citation and fans join rows, stop cloning, stop setting claim. Codegen + the frontend send-site. The fan-out is what makes the FK un-settable, which is why [Switch reads](#mig2) had to go first.

#### ✅ DONE: <a id="con2">CON2</a> - Drop CitationInstance.claim

Drop CitationInstance.claim — schema migration. The column is now unused (scalar cites reach the instance through the join; inline cites through their marker).

#### <a id="con3">CON3</a> - Relocate CitationInstance

Relocate CitationInstance → citation app — move the model (Django SeparateDatabaseAndState to preserve db_table), retarget ~7 prod + ~17 test imports, update the join's FK string ref (and `Claim`'s `citation_instances` M2M `through`/target) to citation.CitationInstance, confirm import-linter. **Not purely mechanical — two hidden data dependencies.** (1) `CitationInstance`'s Django ContentType identity is `(app_label, model)`, so the migration must **rename the `django_content_type` row in place** (`provenance` → `citation`), not let Django mint a fresh one — otherwise every inline wikilink's `RecordReference.target_type` FK dangles and "what links here" goes split-brain (the reference graph is described in [Markdown.md](../../Markdown.md)). (2) The `cite` LinkType registration (`model_path="provenance.CitationInstance"`, today in [provenance/apps.py](../../../backend/apps/provenance/apps.py)) moves to the citation app config and retargets to `citation.CitationInstance`.

#### <a id="doc1">DOC1</a> - Update docs

Update the documentation:

- Update [Citations.md](../../Citations.md) to match the new model.
  - Line 44 ("`CitationInstance` lives in the **provenance app**") is now false — it lives in citation.
  - Line 42 ("instances are **not shared** across usages") is misleading — a scalar instance is shared across a save's claims through the join, and an inline instance is shared across markers by reuse; reword to preserve the real invariant (immutability / copy-on-write), not the overstated non-sharing.
