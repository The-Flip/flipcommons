# Claim Resolution: Pick and Reconcile

## Context

Claims are the source of truth. A claim is a provenance-bearing assertion about one field of one entity ("this MachineModel's `name` is X, per source Y, at priority P"). The queryable catalog — the denormalized columns on each entity row, plus the through-tables for relationships (themes, credits, gameplay features, aliases, abbreviations, parents) — is **not** truth. It is a **materialized view** computed by a deterministic reduction over the active claims. **Resolution** is the function that maintains that view: given an entity whose claims just changed, recompute the affected part of the view so it agrees with the claims.

This document is about the machinery that drives that reduction across entities, fields, cardinalities and caches. That machinery grew one relationship at a time, by copy-pasting the nearest existing resolver and changing the keying, and it is now the hardest part of the system to reason about. Sessions stumble on it because there is no canonical resolver to reason _from_ — there are ~25 near-identical variations, one of which (MachineModel) is silently different from the rest.

The merge policy itself is **not** the problem and is **not** what this document changes. It is already single-sourced. Per `claim_key`, rank by effective priority then recency and take the winner (`ranked_claims` in `apps/provenance/claim_ranking_in_db.py`). Per relationship member, rank independently and let an `exists=false` tombstone win to remove the member (`member_is_present`). The rule "anything that needs a resolved value reuses these primitives and never reimplements the merge" holds and stays. The problem is the **loop around** the merge — group, pick, project to a desired set, diff against what's stored, write the delta — which lives nowhere and is therefore re-implemented everywhere.

A structural goal shapes the end state: the resolution _mechanism_ should live in provenance beside the claim store it operates on, leaving only pinball-specific schema and config in catalog. Flipcommons is also meant to prove out reusable collaborative-encyclopedia software, so a future domain (baseball, medicine) could replace the pinball catalog without rewriting the claim machinery. Keep two horizons distinct. **Relocating the already-domain-agnostic mechanism to provenance is a concrete goal of this effort** (it is what makes the boundary real) and the plan is structured to make it a cheap, mechanical follow-on — see [POST3](#the-plan). **Building a declaration DSL so a second domain needs no code at all is speculative generality** and is deferred until a real second domain forces its shape. The pain today is duplication and a privileged entity type, not "can't reuse for medicine" — so the mechanism is extracted and moved, but no DSL is built over it.

## Open Questions

- **Can the scalar column projection share the literal `reconcile()` body, or only its winner-picking?** A scalar field is conceptually the degenerate reconcile where the "table" is the entity row and the member set has cardinality ≤1 keyed by `field_name`. Elegant — but the write sides genuinely differ (`bulk_update` of columns vs `bulk_create`/`delete` of through-rows). Unify the _winner-picking_ for certain; treat one-literal-`reconcile`-over-both as a judgment call at implementation time, not a goal.
- **Ordering as data, or just control flow?** "Ordering" decomposes into two things that want opposite representations: (a) the **batch from-scratch rebuild** needs a global order across entity types (FK targets before dependents — because FK lookups read the target's _resolved_ natural key, [\_helpers.py:120](../../../backend/apps/catalog/resolve/_helpers.py#L120)) plus intra-type DAGs (Location tree, Theme/GameplayFeature parents); this is a ~15-line explicit sequence that runs offline once and should stay plain control flow, not a topological-sort engine. (b) The **incremental path** needs no cross-entity order — targets are already resolved — except for genuine cross-projection _cascade_ edges (projection A reads projection B's materialized output, so a change to B must re-run A). The audit found exactly one such edge (model*abbreviations ← title_abbreviations), and [the decision below](#decision-collapse-the-model-abbreviation-cross-entity-edge) removes it — so after the Before phase (PRE1) the incremental-cascade count is **zero** and no cascade-trigger mechanism is warranted. The one residual output-read anywhere is the FK natural-key lookup, and it is a \_batch-order* concern (target resolved before dependent in the rebuild), not an incremental cascade — the target's pk is stable, so a dependent never needs re-resolving when its target changes. Keep it as control flow. If a future projection ever reads another projection's _output_ incrementally, that violates [Purity](#invariants-to-preserve) and should be redesigned to read claims, not patched with a cascade edge.

## The root cause, stated precisely

**The subsystem is indexed along the wrong axis, so two primitives that should exist once were instead inlined everywhere.**

The code is organized by _(entity type × relationship name)_ — 25 named `resolve_*` functions. But the actual variation is _(projection shape × subject set)_, and there are only about four shapes:

| Shape                    | Target                                              | Examples                                                        |
| ------------------------ | --------------------------------------------------- | --------------------------------------------------------------- |
| Scalar / FK column       | a column on the entity row                          | name, slug, manufacturer FK, status                             |
| Plain through-row        | `(subject, target)` rows                            | themes, tags, reward_types, parents, corporate-entity locations |
| Payload through-row      | `(subject, target, …columns)` rows, supports update | gameplay features (`count`), aliases (display case), media      |
| Compound-key through-row | `(subject, tuplekey)` rows                          | credits `(person, role)`                                        |

String-sets (abbreviations) are plain through-rows whose target _is_ the string. Aliases are payload-rows. There are ~4 shapes instantiated ~25 times because every new relationship was added by copy-paste, since there was no primitive to call instead. That is the whole story of how a four-shape problem became a twenty-five-function one.

Underneath the wrong axis sit two un-extracted primitives. Resolution is really three layers, and only the innermost is shared:

1. **rank** — order claims by (priority, recency). Extracted: `ranked_claims`, a SQL window. ✓
2. **pick winners** — walk the ranked rows and take the first per key into a dict. Copy-pasted **13 times** across `_entities.py`, `_relationships.py` and `__init__.py`. ✗
3. **reconcile** — build the desired set, read the existing rows, diff, write create/delete/update. Copy-pasted **9 times** across `_relationships.py` (8) and `_media.py` (1). ✗

The team extracted ranking and treated that as "the merge is single-sourced." It is — but the merge people struggle with is layers 2 and 3, and those live nowhere. Because they live nowhere, there is no single place to put field-scoping, cardinality, incrementality or cache scope, so each becomes a separately hand-maintained concern and each copy drifts. The most-edited entity drifted furthest (see below).

This is the load-bearing diagnosis: **`pick_winners` and `reconcile` are two missing functions, and `pick_winners` — a ~3-line function with 13 call sites — is the cheapest, highest-leverage extraction in the subsystem.**

### The second root cause: `resolve_model` should not exist

`resolve_model` ([**init**.py:88](../../../backend/apps/catalog/resolve/__init__.py#L88)) is a hand-tuned full-entity mega-resolver for MachineModel, the single most-edited entity. It is a parallel implementation of everything the generic path already does:

- its own winner-pick loop ([**init**.py:99-105](../../../backend/apps/catalog/resolve/__init__.py#L99)),
- its own scalar apply (`_apply_resolution`, a third near-clone of `_resolve_single` / `_resolve_bulk`),
- slug/opdb_id conflict guards folded in as save-time **side effects** ([**init**.py:127-156](../../../backend/apps/catalog/resolve/__init__.py#L127)) that re-fire on edits to fields that never touched a guarded column,
- six hardcoded relationship calls ([**init**.py:160-170](../../../backend/apps/catalog/resolve/__init__.py#L160)),
- and it ignores `field_names` entirely.

It is reached through the only `isinstance(entity, MachineModel)` branch left in the dispatch ([\_dispatch.py:132](../../../backend/apps/catalog/resolve/_dispatch.py#L132)). It is why MachineModel runs a different code path from every other entity — which is most of why sessions can't form a single mental model of resolution — and it is nearly the entire content of [issue #558](https://github.com/The-Flip/flipcommons/issues/558) (per-entity resolution ignoring `field_names`).

Everything `resolve_model` does is already available generically. `resolve_all_entities` resolves its scalars and FKs; `resolve_unique_conflicts` already implements the slug/opdb_id guard for the bulk path; the six relationship resolvers already take `subject_ids`. `resolve_model` is not load-bearing — it is un-deleted history.

### Current dispatch state — accurate as of this writing

The owner-registered dispatch inversion **already shipped at the provenance seam**. `apps/provenance/resolution/_dispatch.py` holds the registry keyed by concrete model, `register_resolve_handlers`, fail-fast `ImproperlyConfigured` and the two entry points (`resolve_after_mutation`, `resolve_entities_bulk`); catalog registers a handler pair for every model at `CatalogConfig.ready()`. That part is done and correct — it is the right boundary and should be left alone.

But the inversion landed at the outer boundary and stopped. The `isinstance(MachineModel)` switch still sits _inside_ catalog's single registered per-entity handler ([\_dispatch.py:132](../../../backend/apps/catalog/resolve/_dispatch.py#L132)), because `resolve_model` is still a parallel implementation. The boundary that mattered least was inverted; the type-switch that mattered most remains. Any plan must start from this actual state.

## The design patterns and data structures

Naming the load-bearing constructs keeps the redesign honest — it pins which invariants to preserve and lets a reviewer check each pattern against its known failure modes.

| Construct                                                                | Role here                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Event-sourced projection / CQRS**                                      | Active claims are the write model (append-only, provenance-bearing). The catalog columns and through-tables are a read model. Resolution is the projection that rebuilds the read model from the claims.                                                                                                                                                                                                            |
| **Materialized view + incremental view maintenance (IVM)**               | The read model is a materialized view over the claims. The whole thesis is "do IVM with one primitive that touches only the delta," not "full-refresh-per-edit by hand across four concerns."                                                                                                                                                                                                                       |
| **Priority-ranked register (generalized LWW-Register)**                  | The scalar / FK / status merge: one winner per `claim_key` ordered by `(priority, recency)` — **priority first, recency only as tiebreak**, so a higher-priority source beats a more-recent lower-priority claim. This is LWW only under the generalized "any total order on writes" reading; classic wall-clock LWW is the degenerate case where all priorities are equal. Calling it plain "LWW" overstates time. |
| **Priority-ranked tombstoned element-set (generalized LWW-Element-Set)** | The membership merge: each member winner-picked independently by the same `(priority, recency)` order, an `exists=false` tombstone able to win and remove it. Explicitly **not** an OR-Set / add-wins set — a member _can_ lose to a later (or higher-priority) removal, which add-wins forbids.                                                                                                                    |
| **Fold / argmax reduction**                                              | `pick_winners` itself: a reduction over `ranked_claims` taking the first (max-ranked) row per key. The missing layer-2 primitive.                                                                                                                                                                                                                                                                                   |
| **Desired-state reconciliation (the Kubernetes-controller loop)**        | `reconcile`: observe desired set, observe actual set, diff, converge by create/delete/update. The missing layer-3 primitive. `_resolve_machine_model_m2m` already is one, un-extracted.                                                                                                                                                                                                                             |
| **Level-triggered (not edge-triggered)**                                 | Why the system is "always correct, just wasteful": a level-triggered reconciler recomputes desired state from the current claims regardless of what changed, so scoping by changed field is an _optimization_, never a correctness fix. `field_names` is a partial, hand-rolled edge-trigger bolted onto a level-triggered core.                                                                                    |
| **Set difference + idempotence**                                         | Convergence math: `to_create = desired − existing`, `to_delete = existing − desired`, `to_update = {k ∈ desired ∩ existing : payload differs}`. Re-running converges to the same state and writes nothing the second time.                                                                                                                                                                                          |
| **Strategy + registry, open/closed**                                     | Dispatch: a registry of per-model handlers populated by owner registration at `ready()`, so adding a domain extends the table without editing the dispatcher. Already shipped at the provenance seam.                                                                                                                                                                                                               |
| **Degenerate case (cardinality-≤1)**                                     | A scalar column is the membership reconcile with a one-element keyed set whose "table" is the entity row. Conceptually unifying; see Open Questions for the caveat on sharing the literal write body.                                                                                                                                                                                                               |
| **Inner-platform effect / Greenspun's tenth rule**                       | The failure mode to avoid: a declaration DSL that grows until it badly reinvents the programming language it replaced. The reason this plan extracts _functions_, not a metadata language.                                                                                                                                                                                                                          |

These patterns split across **two layers, and conflating them causes mistakes** (it is why `update` reads as a wart on first glance). The **merge layer** reduces a bag of claims to a winning value/membership — the priority-ranked register and element-set above, which are CRDT _semantics_ realized as a centralized argmax fold over a totally-ordered log, **not** a distributed CRDT (there are no replicas and no coordination-free convergence — the reason CRDTs exist). The **reconciliation / IVM layer** takes that merged result and materializes it into rows by diffing desired against existing. `update` lives entirely in the IVM layer, so it is not a CRDT concern and cannot violate CRDT-ness; it is the map-algebra operation of a keyed collection (see [Where the design isn't strictly cleaner](#where-the-design-isnt-strictly-cleaner)). The literal truth is the fold; CRDT is the precise name for the conflict policy; IVM is the projection.

The data structures are worth naming precisely, because every copy re-derives them untyped and the loose `dict[int, set | dict]` they amount to hides the actual design. A `Projection[K, P]` is generic over its **member key** `K` and its **payload** `P`; once parameterized, desired and existing are the _same_ shape, not a `set`-or-`dict` union:

```python
type SubjectId = int
type RowId = int
type ClaimKey = str
type Winners[G] = dict[SubjectId, dict[G, Claim]]       # group key G = field_name (scalar/register) or claim_key (membership/set)
type MemberMap[K, P] = dict[SubjectId, dict[K, P]]      # desired AND existing share this

class RowState[P](NamedTuple):       # an existing materialized row
    pk: RowId                        # needed for delete/update; desired has no pk yet
    payload: P

class Delta[K, P](NamedTuple):       # what reconcile writes
    create: list[tuple[SubjectId, K, P]]
    delete: list[RowId]
    update: list[tuple[RowId, P]]

class Projection[K, P](Protocol):
    def desired(self, winners: Winners) -> MemberMap[K, P]: ...          # ~5 lines, per-shape
    def read(self, subjects: set[SubjectId]) -> MemberMap[K, RowState[P]]: ...
    def write(self, delta: Delta[K, P]) -> None: ...
```

The `set | dict` smell is gone: a plain membership is `P = None`, a payload membership is `P = <a NamedTuple>`, and both are one `MemberMap[K, P]`. Each concrete shape is just a choice of `K` and `P`:

| Shape                                     | `K`                                                       | `P`                                                                                                           |
| ----------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| scalar / FK column                        | `str` (field name)                                        | the resolved column value                                                                                     |
| plain through-row (themes, tags, parents) | `int` (target pk)                                         | `None`                                                                                                        |
| payload through-row                       | `int` (target pk)                                         | a NamedTuple — `GameplayPayload(count: int \| None)`, `MediaPayload(category: str \| None, is_primary: bool)` |
| compound-key through-row                  | a NamedTuple key — `CreditAssignment(person_id, role_id)` | `None`                                                                                                        |

The redesign's job is to make `Winners`, `MemberMap[K, P]` and `Delta[K, P]` the _typed interface_ of two functions, not the incidental untyped locals of nine copies.

## The design

This is the design the Refactor phase builds — and it is also what you would pick designing from scratch. That those coincide is the point: the membership path already half-implements it, so reaching it is an extraction, not a rewrite. One operation, not three dimensions and not a declaration engine:

```python
def reconcile[K, P](projection: Projection[K, P], subjects: set[SubjectId]) -> Delta[K, P]:
    winners  = pick_winners(claims_for(projection, subjects))   # Winners — layer 2, shared
    desired  = projection.desired(winners)                      # MemberMap[K, P] — per-shape, ~5 lines
    existing = projection.read(subjects)                        # MemberMap[K, RowState[P]] — from the ORM
    delta    = diff(desired, existing)                          # Delta[K, P]: create / delete / update
    projection.write(delta)
    return delta                                                # returned so the caller can scope cache (POST1)
```

There are not three reconcilers — there is one `reconcile` and ~4 `Projection` strategies (scalar column, plain through-row, payload through-row, compound-key through-row), each written **once**. Cardinality is just the size of `subject_ids`: the interactive edit passes `{pk}`, bulk ingest passes the whole affected set, both run identical code. Scope and cache fall out of "which projections a changed field touches" and "what a reconcile actually wrote" — a reconcile that wrote nothing need not invalidate, and it knows exactly which entity and dimension it touched. The `(model, field) → projection` table derives from registries that already exist (`get_claim_fields`, `get_relationship_schema`, `claim_fk_lookups`, the alias registry), so it is introspected, not declared.

### Where the design isn't strictly cleaner

Stated plainly so the redesign does not oversell:

1. **`update` is the map-algebra operation — honest, not a wart.** Two collection shapes are in play, and both are legitimate. A plain membership (themes, tags, credits) is a **set**: its operations are add and remove, so `{create, delete}` suffices. An attributed relationship — gameplay `feature → count` ([\_relationships.py:271](../../../backend/apps/catalog/resolve/_relationships.py#L271)), alias `value → display` ([\_relationships.py:710](../../../backend/apps/catalog/resolve/_relationships.py#L710)), media `asset → category` ([\_media.py:260](../../../backend/apps/catalog/resolve/_media.py#L260)) — is a **map**: its operations are add-key, drop-key and change-value, so the diff is `{create, delete, update}`. The member key stays the row's **relational identity** (`(model, feature)`, the DB unique key); the attribute (`count`/`display`/`category`) is the value `P`. Do **not** fold the value into the key to force a pure set-diff — that conflates the diff key with record identity and misrepresents the domain (count is an attribute of "model has feature", not part of what that fact _is_). The simplification is that this needs only **one** generic diff: a set is the degenerate map with `P = None`, where the update branch is vacuously empty (no value to differ on), so plain through-rows get `{create, delete}` for free from the same `Delta[K, P]`. Design `update` in from the start.
2. **`desired` is not always a pure per-claim map — but the residue is exactly two hooks, audited.** All nine reconcile resolvers were checked. Seven build a claim-local desired set (the subject's own winning claims, optionally filtered against the target table's valid PKs — a uniform existence check that belongs as an engine _built-in_, not a per-resolver hook). Two need a bespoke `desired()`, of two distinct kinds:
   - **Cross-entity (exactly one):** `resolve_all_model_abbreviations` subtracts the Title's resolved abbreviations ([\_relationships.py:590](../../../backend/apps/catalog/resolve/_relationships.py#L590)). This is the only _genuinely non-claim-local_ desired set — it reads another entity's resolved rows, so it forces an ordering dependency (titles before models) and a cross-entity read the `desired(winners)` signature can't express alone. This is the one real cap on engine genericness.
   - **Sibling-coupled (exactly one):** `resolve_media_attachments` derives each attachment's `is_primary` from its _sibling_ attachments — at most one primary per category ([\_media.py:200](../../../backend/apps/catalog/resolve/_media.py#L200)), auto-promote the oldest if none ([\_media.py:221](../../../backend/apps/catalog/resolve/_media.py#L221)). Still a pure function of the entity's _own_ claims (priority and `created_at` ride on them), so it fits a `desired(winners)` hook with a group post-pass — a fat hook body, not a generality cap; it forces neither ordering nor cross-entity reads.

   So the escape hatch is small and its exact shape is known. Both non-trivial hooks are eliminated by the [Before phase](#the-plan) (PRE1, PRE2) — the cross-entity `model_abbreviations` subtraction and the sibling-coupled media primary both move to read time — leaving every resolver claim-local: **zero** bespoke `desired()` hooks and **zero** cross-entity reads, with two shared filters lifted into the engine as built-ins: `member_is_present` (tombstone-drop, run by every membership resolver) and valid-PK existence (only the FK-referencing ones).

3. **Ordering stays explicit.** Level-triggered convergence does not remove the need to resolve FK targets before dependents and relationship rows before derived rows that read them. Make ordering declared data, do not pretend registration order handles it.
4. **A database-side projection (SQL views / generated columns / triggers) is an ideal, not a plan.** It is the fastest expression of the two regular shapes, but it cannot host payload-update, cross-entity subtraction, alias case-folding or markdown-reference sync, and it raises the debugging floor for a volunteer team. Name it as a north star for the scalar and plain-membership shapes; do not gate this work on it.

### Decision: collapse the model-abbreviation cross-entity edge

The one genuinely non-claim-local `desired` (item 2 above) — `resolve_all_model_abbreviations` subtracting the Title's abbreviations — is being **removed**, not carried into the engine. That single subtraction is doing disproportionate damage: it is the engine's only cross-entity read, the only cross-projection cascade edge, and the source of a latent staleness bug — a Title abbreviation edit re-resolves `title_abbreviations` but nothing re-derives its models' abbreviations, so the materialized model set goes stale until that model is next touched or a full rebuild runs.

The product semantics (per [SingleModelTitles.md](../../SingleModelTitles.md)): a Title owns the canonical abbreviation ("MM" for Medieval Madness); a Model carries only _edition_-specific abbreviations ("TS4LE"), and in the dominant single-model case the Model's are dormant. The subtraction exists so a Model doesn't redundantly list an abbreviation its Title already has. That is a **read-time union**, not a write-time subtraction — baking it into the projection is a CQRS smell (a cross-entity join smuggled into the write side).

It is not cosmetic to remove: in the current dev corpus ~53% of Model abbreviation claims (489/928 with a Title) duplicate their Title's abbreviation, so the subtraction actively removes rows. The fix stores what's claimed and joins in the query:

- **Resolver:** `model_abbreviations` becomes claim-local — the Model's own claimed abbreviations, overlaps included. It joins the seven simple resolvers; `_get_title_abbrs_for_models` and the subtraction loop are deleted.
- **Read side:** the model-detail endpoint (`_serialize_model_detail`, [machine_models.py:303](../../../backend/apps/catalog/api/machine_models.py#L303)) subtracts the Title's _current_ abbreviations at read time via a shared `displayed_model_abbreviations()` helper in `catalog/api/helpers.py`. The Title is already loaded there; add a `title__abbreviations` prefetch to avoid N+1. (The model-abbreviation edit-diff `plan_abbreviation_claims` reuses the same helper so an unchanged save emits no spurious removals. The bulk **export** is deliberately left claim-faithful — it serializes the raw materialized rows, overlaps included.)

Net: displayed output is unchanged, the staleness bug becomes structurally impossible (the dedup is always live), this removes the engine's only cross-entity read (the media simplification [PRE2](#the-plan) removes the last sibling-coupled hook, taking the engine to zero bespoke `desired()` hooks), and no cross-projection cascade edge exists — which is most of what the "ordering as data" open question concerns. This is a cheap, self-contained simplification worth doing **before** the reconcile extraction, because it removes the single hardest case the engine would otherwise have to model. (It also grows the `ModelAbbreviation` table by ~the overlap count — claim-faithful rows the subtraction currently suppresses; storing them is the point.)

## The plan

### Dev Postgres

You can use either the default dev SQLite database for testing, but to test how Postgres behaves, a Docker Postgres container (`fc-pg`) holds a very recent copy of the localhost SQLite dev DB. `DATABASE_URL=postgres://pinbase:pinbase@localhost:5432/pinbase`. <!-- pragma: allowlist secret (local dev throwaway credentials) -->

### ✅ DONE: Before the refactor

Each pre-refactor item relocates a cross-cutting or derived concern out of the projection to where it belongs (mostly read time), making a projection claim-local or removing a special-case. They are **not** behavior-preserving (storage shape and/or failure mode changes), so each is TDD'd against its specific behavior change and ships independently. Together they take the engine to **zero** escape-hatch `desired()` hooks and **zero** cross-entity reads, and remove the slug/opdb_id and image-license special-cases — so the Refactor phase meets only uniform claim-local projections.

#### ✅ DONE: PRE1 — Model abbreviations → read-time dedup

(full rationale in the [decision below](#decision-collapse-the-model-abbreviation-cross-entity-edge)). Make `resolve_all_model_abbreviations` claim-local; move the Title dedup to read time via a shared `displayed_model_abbreviations()` helper used by both `_serialize_model_detail` and the edit-diff `plan_abbreviation_claims` (the bulk export stays claim-faithful). Removes the engine's only cross-entity read and only cascade edge. Storage changes (grows `ModelAbbreviation`); TDD against the staleness bug.

#### ✅ DONE: PRE2 — Media primary → read-time selection

Store each attachment's claimed `(category, is_primary)`; pick the displayed primary in the existing `all_media` / `primary_media` helper (highest claimed-primary per category, auto-promote oldest if none). **Tiebreak by `created_at`, not claim priority**, so no priority column is denormalized onto `EntityMedia` — trading priority-ordered primary contention (an edge case) for the simplicity. Removes the only sibling-coupled `desired()`. Near-zero product cost: `thumbnail_url` is already nullable and the helper exists.

#### ✅ DONE: PRE3 — slug/opdb_id → fail loudly, not silently

Delete the resolve-time revert guard; let those fields fall through to the DB unique constraint → `IntegrityError` → the 422 path `name` already uses (interactive), with bulk keeping `resolve_unique_conflicts`. Behavior change: claiming a taken slug returns a 422 instead of silently keeping the old value. Resolution leaves the uniqueness business entirely; this also makes REF1 purely mechanical (no guard left to relocate).

#### ✅ DONE: PRE4 — Image license → unify the write-time computation across both paths

Lift the `IMAGE_FIELDS` license-stamp branch (`resolve_effective_license` → `permissiveness_rank`/`license_slug` sidecars) into one shared helper and call it from **both** the MachineModel `_apply_resolution` path and the generic `_entities.py` `extra_data` path. This removes the **MachineModel-only divergence** — the only thing REF1 needs — with no read-side change (the read keeps reading the frozen sidecars at zero query cost). The latent source-license **staleness bug is deliberately left in place**: it is nearly theoretical (source-level license policy is a rare admin action; re-resolve heals it), and the read-time-resolution machinery that would fix it (a prefetched license index threaded through every loop caller, an N+1 guard, an old/new-shape fallback) is interim complexity [POST2](#the-plan) deletes. POST2 is the full fix — it promotes image URLs to first-class media rows and resolves license off a real FK. (Removing the unused `AttributionSchema.permissiveness_rank` wire field is a separate, independent cleanup.)

#### Stale materialized state is a completeness concern, not a correctness gate

PRE1 and PRE2 each relocate a write-time projection concern to read time, so on deploy the existing materialized rows stay in the **old shape** until each entity is next re-resolved (an edit, an ingest or a full pass). (PRE3 changes only a write-path failure mode, and PRE4 keeps the write-time stamp with no read-side change — neither has a stale-materialized-state concern.) The instinct is to gate the deploy on a global re-resolve. **Don't** — and the reason is a load-bearing invariant for the whole phase: **re-resolve is a completeness pass, never a correctness gate, _provided each Before read path is stale-tolerant_** — it degrades to the old behavior on old-shape data, never to wrong output. Hold that and no Before item is deploy-blocking.

| Item | Re-resolve required for correctness? | Why                                                                                                                                                                                                                                                                                                       |
| ---- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PRE1 | No                                   | new read = stored rows − Title abbrs; old rows already exclude the overlaps, so detail and export show exactly what they showed before. The un-fixed cold-model case _is_ the pre-existing staleness bug, not a new wrong answer; an edit self-heals.                                                     |
| PRE2 | No                                   | old stored `is_primary` is the de-conflicted one-per-category value, and the new read picks that same one. The `created_at` tiebreak only bites a category with multiple primaries, which old data never has.                                                                                             |
| PRE3 | N/A                                  | write-path failure mode only; no materialized state migrates.                                                                                                                                                                                                                                             |
| PRE4 | No                                   | both write paths now stamp identical `__license_slug`/`__permissiveness_rank` sidecars and the read path is unchanged, so existing rows read exactly as before — no materialized state migrates. (The source-level staleness PRE4 leaves in place is pre-existing, not a deploy concern; POST2 fixes it.) |

So the discipline to enforce in review is **stale-tolerant reads**, not backfill machinery. Because re-resolve isn't a correctness gate, none of the heavier options are warranted: no automatic-on-deploy backfill, no migration-triggered resolve, no pending-queue + drain, no deploy-stage coupling. The completeness pass runs **at leisure** — a global `resolve` command (which does not exist yet; the from-scratch rebuild the [Ordering open question](#open-questions) assumes is unbuilt) plus a note to run it post-deploy. Each Before item ships three small things: a stale-tolerant read, the `resolve` command/note and a regression test that converges from the old (suppressed/stale) materialized state.

A migration must **not** run the global resolve inline — it is a heavy whole-corpus fold in the migrate window (lock, timeout and ordering risk) and it couples the frozen migration DAG to resolution code the Refactor/After phases are about to move/rename. If a _scoped_ re-resolve is ever wanted, the clean split is: the **migration computes _who_ is stale** (a cheap frozen set-query over historical models — no resolver import, and a safe over-approximation is fine because the resolver is idempotent/level-triggered), while the **live resolver computes _what_ is correct** (the single-sourced winner-pick it owns). Defer that migration→scope→drain plumbing until a second customer (PRE2) forces its shape — [POST4](#the-plan)'s defer-speculative-generality rule applies.

### The refactor

With the Before phase done, this becomes a pure mechanical extraction: no product decisions, byte-identical materialized state at every step (idempotent) and entirely behind the unchanged dispatch seam, so the existing suite stays green by construction. (The cache-invalidation optimization that the new reconcile delta _enables_ is deliberately **not** here: it changes cache behavior and carries a stale-read risk, so it is the first After-phase item, [POST1](#the-plan).)

#### REF1 — Kill `resolve_model`; route MachineModel through the generic per-entity path

Collapse the divergence. Register its six relationship namespaces into the _same_ `field_name → resolver` dispatch the non-MM path already uses, scoped by `field_names`. With slug (PRE3) and image-license (PRE4) already handled, this is now purely mechanical: it deletes the `isinstance` branch, `_apply_resolution`, `_build_claims_by_model`, `_get_mm_relationship_resolvers` and the MachineModel divergence, and **resolves [#558](https://github.com/The-Flip/flipcommons/issues/558)** (field_names honored — same resolved state, less work). It also erases a silent ordering divergence — MM saves scalars then relationships ([\_\_init\_\_.py:156](../../../backend/apps/catalog/resolve/__init__.py#L156) → [:160](../../../backend/apps/catalog/resolve/__init__.py#L160)); the generic path runs relationships then scalars ([\_dispatch.py:208](../../../backend/apps/catalog/resolve/_dispatch.py#L208) → [:259](../../../backend/apps/catalog/resolve/_dispatch.py#L259)) — immaterial to correctness (relationship rows key on the subject pk, never its resolved columns) but exactly the unstated difference that defeats a single mental model. Highest leverage portion of the refactor.

Then extract the primitives, bottoms-up.

#### REF2 — Extract `pick_winners`

Replace all 13 copies. A ~3-line function (`for row in ranked_claims(...): winners.setdefault(key, row)`), 13 call sites. The cheapest win and the one that makes the rest readable. Defines the first named type — `Winners` — as its return type. The kernel is "first row per group" (the fold), **parameterized by the grouping key** — `field_name` on the scalar path (one winner per field: a register) and `claim_key` on the membership path (many winners per subject: a set). That parameter is what lets one function cover all 13 sites; register-vs-set is only how the caller consumes the groups, not a second function.

#### REF3 — Extract `reconcile`

Build it with `{create, delete, update}` and collapse the 9 copy-pasted loops onto it. Each resolver shrinks to: build queryset → `pick_winners` → build `desired_by_subject` (the only genuinely per-shape part, ~5 lines) → `reconcile`. After the Before phase **every** resolver is claim-local — no bespoke `desired()` hook remains, and the two universal filters — `member_is_present` (tombstone-drop) and valid-PK existence (for FK-referencing members) — move into the engine, so `desired()` is a pure per-shape `claim → (key, payload)` function. Deletes ~500 lines. **The typed vocabulary is born here, not in a later pass** — `Projection[K, P]`, `MemberMap[K, P]`, `RowState[P]` and `Delta[K, P]` (see [The design](#the-design)) are `reconcile`'s signature, so the generics are what make the 9 copies collapse into one; extracting with loose types and tightening afterward would reintroduce the very drift this removes. The scalar instantiation (`Projection[str, <column value>]`) firms up in REF4.

#### REF4 — Unify the scalar single/bulk split

Fold in the holdout: collapse it onto `subject_ids` the way the relationship path already is — collapsing `_resolve_single` / `_resolve_bulk` (and the now-deleted `_apply_resolution`) — _if_ it falls out cheaply. Share `pick_winners` for certain; be skeptical of forcing the literal `reconcile` write body over both columns and rows (see Open Questions).

**Load-bearing constraint across REF2–REF4:** write `pick_winners`, `reconcile` and the `Projection` Protocol **catalog-free from birth** — they may physically live in `catalog/resolve/` for now, but they import only provenance + core and name no concrete catalog model (they receive through-model classes as arguments). Add the import-linter contract that pins this _now_, while the code is still in catalog. This is the single decision that determines whether POST3 is a near-`git mv` or a painful untangle; without it the mechanism silently re-grows catalog imports.

The Refactor phase alone retires four of the five things that make this subsystem hard to reason about: the 25 near-clones (→ ~4 projections), the single/bulk split, the MachineModel special-case and the `field_names` contract that lies. The fifth — the two-file dispatch indirection — is the recently-shipped provenance seam, which is the correct boundary and stays.

### After the refactor

Each is its own PR on the clean base. None gates the refactor. Each carries behavior change or risk the behavior-preserving core does not.

#### POST1 — Scope cache invalidation

Scope it to the entity and dimension a reconcile actually touched, replacing the global `transaction.on_commit(invalidate_all)` flush that fires on every per-entity resolve today ([\_dispatch.py:137](../../../backend/apps/catalog/resolve/_dispatch.py#L137)). The immediate payoff of the new reconcile delta, and the second half of what [#558](https://github.com/The-Flip/flipcommons/issues/558#issuecomment-4797620844) gestures at — it targets the wasted _invalidation_ riding alongside the wasted _re-resolution_ that REF1 already fixes. The delta says exactly what changed, so a reconcile that wrote nothing invalidates nothing. It lives here, not in the Refactor phase, because it is **not** behavior-preserving: the global flush is brute-force safe (it over-invalidates, so it can never serve stale data), so scoped invalidation must be **tested for completeness** — a missed dependent is a stale-cache bug that "resolved state unchanged" will not catch. Not free, either: it needs the cache layer to expose per-entity / per-dimension keys. Gated on REF3 (the delta must exist).

#### POST2 — Model third-party image URLs as first-class rows

Promote `opdb.images` / `ipdb.image_urls` / `image_urls` out of `extra_data` into a real representation (likely the media system with an "external reference, not owned" kind) carrying source and license as real relations. Supersedes PRE4: license becomes a live join off a real FK (no sidecars), the hardcoded image-field list becomes a table, and `extra_data` reverts to an archival junk drawer. Sequenced _after_, not before, because it wants to _be_ a `Projection` — which does not exist until REF3, so building it earlier means building it twice — and it is too large a data-model change (table, ingest emit-target, read path) to gate the refactor. Behavior-changing; its own track.

#### POST3 — Hoist the mechanism tier into `provenance/resolution/`

The home where the dispatch seam already lives. `git mv` the catalog-free tier (kept catalog-free by the REF2–REF4 constraint) and flip the import-linter contract to the intra-provenance form. This is the _goal_ of the whole effort — leave only pinball-specific logic in catalog. See [End-state homes](#end-state-homes) for what moves vs stays.

#### POST4 — Defer the general engine and DB-side views

Defer any general [declaration-driven engine](../model_driven_metadata/ModelDrivenClaimResolution.md) and any database-side view generation until a real second domain or a measured performance need forces them. Do not build a DSL for baseball before the pinball duplication is gone.

### End-state homes

The extraction in REF2–REF4 cleaves the code along exactly the line the hoist needs, because the primitives are domain-agnostic by construction (`pick_winners` speaks only `Claim` / `ranked_claims`; `reconcile` diffs through-model classes passed in as arguments) while the projections name concrete models. POST3 then splits the result three ways:

| Piece                                                                                                                                                                                            | Home                                             | Why                                                                                                                                                                                                                                            |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pick_winners`, `reconcile`, the `Projection` Protocol, FK/coercion helpers, read-side payload types                                                                                             | **provenance** (`resolution/`)                   | closed over the claim store; imports only provenance + core. The dispatch seam (`resolve_after_mutation`, the model-keyed registry) already lives here.                                                                                        |
| Concrete `Projection` instances (Theme, Tag, Credit, parents…), registration at `ready()`, the irreducible bespoke reconcilers (`Credit` compound identity, `location_path`), cache invalidation | **catalog**                                      | irreducible pinball schema and config, registered into the seam at `CatalogConfig.ready()`.                                                                                                                                                    |
| Media-attachment projection (`_media.py`)                                                                                                                                                        | **media**, registered from media's own `ready()` | the media wall forbids `provenance → media`, and `_media.py` imports `apps.media.models`. It does **not** move with the generic core — media already owns the entity-media tables and the sanctioned `media.models → provenance.models` crack. |

## Invariants to preserve

A naive rewrite tends to drop these; the redesign must keep them:

- **Single-sourced merge.** Every projection reuses `ranked_claims` and `member_is_present`; no projection reimplements winner-picking once `pick_winners` exists.
- **Fail-fast on an unhandled namespace.** A claim field with no projection raises (as the bulk path does today with `ValueError`); it must never be a silent no-op that leaves a derived table stale.
- **Explicit ordering.** FK targets before dependents, relationship rows before derived rows, scalars in a defined position — a declared sequence, not an accident of registration order.
- **The escape hatch is first-class.** Compound identity (`Credit`) and computed fields (`Location.location_path`) register a hand-written `desired()` or a bespoke reconciler. (The two previously non-claim-local hooks — `model_abbreviations` and media primary — are removed by the [Before phase](#the-plan) (PRE1, PRE2), not escape-hatched.) The goal is "no per-shape boilerplate for the common case," not "no hand-written code ever."
- **Purity — a projection is a function of claims, never of another projection's output.** A projection reads claims and writes its view, nothing else. Reading another projection's _materialized rows_ (as `model_abbreviations` did with `TitleAbbreviation`) is the violation that creates cross-entity ordering, cascade edges and staleness — the cross-projection join belongs at read time, not in the projection. The one deliberate exception is the FK natural-key lookup (the target's resolved `slug`/`location_path`), tolerated because the resolved pk is stable and the dependency is satisfied by batch _order_, not an incremental trigger. Cross-reference uniqueness (slug, opdb_id) is **not** a projection concern at all: its source of truth is the DB unique constraint, surfaced as a 422 on the write path exactly as `name` already is ([PRE3](#the-plan)) — never a resolve-time guard that silently reverts and fires only on the single-object path.

## Alternatives considered

This plan extracts two functions and a per-shape strategy. The tempting alternatives are worth rejecting explicitly, because the mechanism it builds is exactly the kind a later session reaches for one of these to "simplify."

- **Signals / pub-sub** (emit "claims changed", projections subscribe). Rejected. It destroys **fail-fast** — a missing subscriber is a silent no-op that leaves a derived table stale, the exact opposite of the raise-on-unhandled-namespace invariant above. It makes the required cross-dimension **ordering** (FK targets before dependents, relationship rows before derived rows) implicit and fragile, an emergent property of subscription order rather than a declared sequence. And it makes the bulk path's **batching** awkward, since a per-claim signal fights the whole-subject-set pass. Resolution is a correctness-critical projection that wants explicitness; signals trade away exactly that for a decoupling the call sites do not need.
- **Polymorphism on the model (`entity.resolve()`).** The textbook fix for the `isinstance` type-switch: a virtual method per model, dynamic dispatch replacing the branch. Rejected. It scatters projection logic across every domain model, recoupling the schema to the mechanism — the precise inverse of this plan's organize-by-shape thesis and of the step-7 hoist, which depends on the mechanism naming _no_ concrete model. It optimizes for "no central dispatcher"; the goal here is "no per-entity code and a mechanism that can move to provenance." Different axis.
- **`match`/`case` structural matching on entity type.** Rejected as cosmetic — nicer syntax for the same centralized type-switch `resolve_model` already embodies. It does not remove the privileged entity or the duplication; it reformats them.

## What deliberately does not change

Most of the complexity in today's subsystem traces to one shape — **a cross-cutting or derived concern computed at write time when it is really a read-time view.** The Before phase pays down most diagnosed instances of it (PRE1 model-abbreviations, PRE2 media-primary, PRE3 slug/opdb_id). The one exception is **image-license**: PRE4 deliberately only de-duplicates the write-time computation across both paths (enough to unblock REF1) and leaves the source-level staleness in place, because the read-time-resolution machinery that would fix it is interim complexity [POST2](#the-plan) deletes — POST2 is where image-license stops being a write-time-derived view. What is left after all three phases is otherwise genuinely irreducible, and is recorded here so a later session does not "simplify" it back into a smell.

- **`update` is honest, not a smell.** An attributed relationship (gameplay `count`, alias `display`, media `category`) is a **map**, and `{create, delete, update}` is the map algebra (see [Where the design isn't strictly cleaner](#where-the-design-isnt-strictly-cleaner)). Keep it; do not chase a pure `{create, delete}` set-diff by dropping `count`/`display` or by folding the value into the member key.
- **Compound-key through-rows (`Credit` = `(person, role)`)** are the data model, not a smell — the same person can hold two roles. Stays a `Projection[CreditAssignment, None]`.
- **Scalar-column vs through-row (two write paths)** is driven by normalization: some claimed fields are columns, some are tables. The alternatives (EAV, all-JSON) are worse.

The cheapest guardrail against the _next_ such smell is the [Purity invariant](#invariants-to-preserve) itself — _a projection is a function of claims; anything cross-cutting, contextual or derived is a read-time view._ Held from the start, that one rule prevents model-abbreviation and media-primary; image-license is the same smell, deferred to POST2 rather than paid down in the Before phase.
