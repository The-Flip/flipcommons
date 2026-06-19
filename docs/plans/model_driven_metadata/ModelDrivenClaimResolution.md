# Claim Resolution

## Context

One goal we have for Flipcommons is to make it the steel thread proving out a new, reusable category of collaborative encyclopedia wiki software. We want to be able to replace the catalog app with an entirely different domain than pinball -- like baseball or medicine -- to create an entirely different collaborative encyclopedia wiki on a different subject. Ideally we'd even have a low code / AI-driven layer that lets non-technical people do the data modeling, though that's in the future.

So we want to move everything that's not directly related to the pinball domain out of catalog, and ensure that no other app has anything about the pinball domain. This is basically the [ModelDrivenMetadata.md](ModelDrivenMetadata.md) vision.

## Resolution should move out of the catalog app

Resolution lives in catalog today — the catalog app materializes denormalized fields and through-tables from claims, and the concrete resolvers bind concrete tables, so they can't move until declarations rich enough to drive a generic engine exist. But that's a statement about where the _concrete_ resolvers live, not proof they're domain logic.

For the most part, resolvers are NOT pinball-specific. The resolver _mechanism_ is largely domain-agnostic; what's pinball-specific is the schema, a relationship config table, and two compound shapes. Resolution is a generic **projection pattern** — claims are the source of truth, and a resolver materializes them into the denormalized fields and through-tables that make the catalog queryable. Every claim-based domain needs that projection; only the target tables differ.

## What's in `catalog/resolve/` today, by tier

### Tier 1 — scalar resolution: already fully generic

`_entities.py` (`resolve_entity[T: ClaimControlledModel]`, `resolve_all_entities`) iterates `get_claim_fields(model_class)`, picks the winning claim per field, and `setattr`s it onto the model, coercing through `model_class._meta.get_field(attr)`. No concrete model is named anywhere — it is model-driven today. This is substrate that merely happens to live in catalog; nothing about it is pinball-specific. An import-linter contract already pins that: `_entities`, `_helpers` and `_claim_values` may not import the catalog domain (the catalog-agnostic rule in [AppBoundaries.md](../../AppBoundaries.md)), so the property can't silently regress and the eventual hoist stays a near-trivial move. `_relationships.py`/`_dispatch.py` still bind `MachineModel` and are excluded, as is `_media.py` (it imports `apps.media.models`).

### Tier 2 — M2M relationship resolution: generic algorithm + pinball config

`_resolve_machine_model_m2m(spec)` (`_relationships.py:101`) is a generic diff-and-write-through-table loop: read the claims for a field, diff against `getattr(owner, spec.m2m_attr).through`, then `bulk_create` / `delete`. The _algorithm_ is domain-agnostic. What's pinball is purely **configuration**:

- the hardcoded `M2M_SPECS = {"theme": …, "reward_type": …, "tag": …}` table (`_relationships.py:90-92`), and
- the owner pinned to `MachineModel` (the content-type lookup and `getattr` are hardcoded to it).

A different domain would supply a different spec table over its own models and run the same loop unchanged.

### Tier 3 — compound / payload shapes: genuinely domain-specific

Two resolvers don't fit the plain-M2M mold:

- `resolve_all_gameplay_features` (`_relationships.py:210`) — the through-table (`MachineModelGameplayFeature`) carries a `count`, so it's M2M-with-payload.
- `resolve_all_credits` (`_relationships.py:327`) — `Credit` is a `(person, role)` compound identity, explicitly "not amenable to generic M2M" (`:323`).

These are still _instances of a pattern_ (a through-table with extra columns, or a compound key), but their specific shape is pinball.

### The dispatch special-case

`resolve_after_mutation` (`_dispatch.py:106`) branches on `isinstance(entity, MachineModel)` (`:127`) and `resolve_relationships_bulk` on `issubclass(model_class, MachineModel)` (`:293`). The dispatch inversion — folding both into per-model registration at `ready()` — retires them, independent of the generic-engine work here. The dispatch is analyzed in full — its patterns, the design ladder it climbs, and the alternatives rejected — under [Dispatch design](#dispatch-design) below.

## What's irreducibly pinball

Narrow: **the concrete model definitions themselves** — `Title`, `MachineModel`, `Theme`, `Credit`, the through-tables and their columns. That is the domain by definition; you cannot hoist the schema. Everything else is _mechanism_ (generic) plus _config_ (declarable) plus a couple of _bespoke shapes_.

So the honest answer to "are the resolvers pinball-specific?" is **no, not the resolvers — only the schema they project into, the table of which-field-maps-to-which-through-table, and two compound materializations.**

## The model-driven-resolver opportunity

This is the read/projection analog of the model-driven write surface. The relationship-schema registry (provenance) already declares relationship _shapes_ model-drivenly for the bulk write path. If those declarations carried enough metadata for resolution too — _field → through-table → target model → payload columns / identity shape_ — then a **generic resolver engine** could drive Tiers 1–2 and most of Tier 3 off declarations, leaving only the genuinely-bespoke materializations hand-written. Part of that declaration is already designed: [ModelDrivenCatalogRelationshipMetadata.md](ModelDrivenCatalogRelationshipMetadata.md)'s `CatalogRelationshipSpec` ("given a claim namespace, what through-model does it live on, and how do I build/resolve/validate it") is exactly the spec a generic resolver would consume. That doc is **deferred pending a second independent consumer** — and this read-side engine is that consumer, so this is the work that would revive it. The FK-resolution half already shipped as the `claim_fk_lookups` ClassVar (`public_id → pk`); a generic resolver builds on what's there.

The end state: catalog shrinks toward **schema + declarations + a handful of custom resolvers**:

- **Schema** — the concrete models (irreducible).
- **Declarations** — relationship and derived-field metadata, ideally as ClassVars on the models (the same model-driven channel `soft_delete_cascade_relations` and the linkable registry already use), not as resolver code.
- **Custom resolvers** — only where a materialization genuinely defies a declarative shape (compound identity like `Credit`, computed fields like `Location.location_path`).

The generic engine — scalar projection, plain-M2M projection, payload-M2M projection — hoists to the substrate, driven entirely by the declarations. That is precisely the [ModelDrivenMetadata.md](ModelDrivenMetadata.md) endgame applied to resolution.

It's a **large lift**, gated on two things. The declaration vocabulary that would drive the engine — payload columns, compound identity, coercion rules — doesn't exist yet, and designing it is its own hard design problem. And the interactive write path's hand-written per-relationship planners and the resolvers are two halves of the same per-relationship hand-coding, so a model-driven pass should likely address both together, widening the scope beyond resolution alone.

### Where the engine lives: provenance, not a new app

The substrate target is **provenance** — not a new `claim_resolve` app peer to `claim_edit`/`claim_ingest`. The deciding test is **bridge vs. closed-over**, the same line that keeps `revert` in provenance while the two write engines are their own apps: the write engines _bridge_ external input (HTTP edits, YAML patches) into claims; revert takes an existing ChangeSet and computes its inverse, never leaving provenance's vocabulary. Resolution is on revert's side of that line — it bridges no external input, it reads claims already written and projects them. Revert computes the inverse ChangeSet; resolution computes the materialized view. They are the two intrinsic operations over the claim store, both closed over provenance's own vocabulary (`Claim`, `ranked_claims`, `get_claim_fields`).

A separate app would be a false parallel to the write engines. `claim_edit` and `claim_ingest` earned their own apps because they carry dependencies provenance should not — `claim_edit` is HTTP-aware (raises 422s), `claim_ingest` binds `LinkableClaimModel` for addressing and depends on citation plus the patch machinery. The generic resolver carries none of these: its entire static dependency surface is provenance + core, which an existing import-linter contract already enforces — the generic resolver core imports zero catalog domain (the catalog-agnostic rule in [AppBoundaries.md](../../AppBoundaries.md)). An app whose whole dependency surface is provenance, existing solely to operate on provenance's central model, is provenance code in exile; worse, because `provenance.revert` calls resolution, that app would have to sit _above_ provenance, forcing revert to reach it through the dispatch-registry indirection for no benefit. It also fits provenance's stated charter directly: the **resolve-dispatch registry** is already a provenance responsibility (relocated there by the dispatch inversion). Putting the generic engine _behind_ the registry already going there is the natural completion, not a charter expansion.

So the end-state homes are a three-way split, not one resolution app:

| Piece                                                                                                          | Home                                                                       | Why                                                                                                                                                               |
| -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Generic projection engine (scalar, plain-M2M, payload-M2M) + dispatch registry                                 | **provenance**                                                             | closed-over claim operation; imports only provenance + core                                                                                                       |
| Relationship / derived-field **declarations** (the `CatalogRelationshipSpec`-style ClassVars the engine reads) | **catalog**                                                                | the domain schema; read model-drivenly via introspection                                                                                                          |
| Bespoke materializations — `Credit` compound identity, `Location.location_path`, cache invalidation            | **catalog**                                                                | irreducible domain shapes, registered at `CatalogConfig.ready()`                                                                                                  |
| `media_attachment` resolution (today `resolve/_media.py`)                                                      | **media**, registered into provenance's dispatch seam at media's `ready()` | the media wall forbids `provenance → media`; media already owns `EntityMedia` / `MediaSupportedModel` and the sanctioned `media.models → provenance.models` crack |

The last row is the wrinkle a "single resolution app" framing gets wrong: `_media.py` imports `apps.media.models`, and the "Data apps do not depend on media" contract bars it from provenance. Media-attachment projection therefore belongs in `media` — which already depends on provenance — not lumped with the claim-closed engine. This is also why that contract deliberately leaves `_media.py` out of its source list: its hoist target differs from the rest of the generic core.

### It lands as a `provenance/resolution/` package — keep it whole

The engine arrives in provenance as a **`resolution/` sub-package**, not as a handful of new modules scattered at the provenance root. It is already a cohesive multi-module subsystem in `catalog/resolve/` (`_entities` scalar/bulk projection, `_helpers` coercion/FK/constraints, `_claim_values` read-side payload types) and gains the dispatch registry that the dispatch inversion relocates to provenance. That is exactly the "cohesive subsystem → package" case; dissolving it into root modules would be a regression. The hoist is a near-`git mv` precisely because the catalog-agnostic contract already proves the trio imports zero catalog domain, so its imports already point only at provenance + core.

This is the one new package the hoist forces, and it earns its keep. Provenance is otherwise a flat app whose only existing package is `models/` (the store). Two groupings are worth boxing — `models/` (data) and `resolution/` (a distinct subsystem with its own dispatch registry) — and no more. In particular, **do not box the shared claim-logic modules** (`claims` construction, `claim_ranking_in_db`, `claim_presence`, `validation`) under a `claims/` folder: the whole app is about claims, so that name carries no information and falsely implies the rest isn't claim-related. The meaningful axis in an all-claims app is the _operation_, which the module names already carry; those modules are peer utilities, not a subsystem, and stay flat. (If a grouping is ever genuinely warranted, name it for the role — `semantics/`, the shared rules for interpreting claims — never `rules/`, which collides with `authz`'s activity rules. But the difficulty of naming it cleanly is itself a signal it does not need boxing.)

The clean target is therefore: `models/` + `resolution/` + flat claim-logic + flat `revert.py`. `revert` stays a flat module and is **not** co-located with `resolution` under a shared "closed-over operations" parent — their kinship (both intrinsic operations over the claim store) is documented, not enforced by a folder that would add a layer for one extra module.

Carry the contract forward to the new home: once `resolution/` lands, its catalog-free property is re-enforced one app down as an intra-provenance rule (`apps.provenance.resolution ⊄` the catalog domain) — the same guarantee the catalog-agnostic contract makes today on `catalog/resolve`, restated against the new path. Provenance can express it with the same exhaustive intra-app layering catalog already uses for its internal stack.

## Dispatch design

The dispatch seam (`catalog/resolve/_dispatch.py`) is worth analyzing on its own terms, because the inversion above reads as mere code-motion when it is really a move up a well-known design ladder. Naming the constructs keeps the generalization honest — it pins which properties to preserve and which alternatives were considered and rejected.

### Patterns that stay

The seam is a **facade** (`resolve_after_mutation` / `resolve_relationships_bulk` — one entry point for "claims changed, fix the projection"), routing through a **registry of strategies** (the `field_name → resolver` dispatch tables) selected by a **predicate over `(entity type × claim namespace)`**, with **fail-fast** on an unregistered namespace (`raise ValueError`, not a silent no-op) and a small **adapter** normalizing every resolver to the uniform `subject_ids` signature so they are table-dispatchable. These are the correct shape — the [rejected alternatives](#rejected-alternatives) are worse.

### Smells the inversion removes

Three smells — the `isinstance(MachineModel)` / `issubclass` **type-switch**, the **`getattr`-by-string-name** reflection (`resolver_function_name`), and the **`global X is None` lazy-init singletons** — share one root cause: there is no registration phase, and one entity type is privileged. They are artifacts, not design choices: the table is built lazily-on-first-call (hence `global None`), stored by name to defer touching `_relationships` past import (hence `getattr`), and branches on a hardcoded type because `MachineModel` got a hand-tuned mega-resolver before the generic path existed. Registering concrete handlers at `CatalogConfig.ready()`, keyed by model class, deletes all three at once — no lazy-init (a defined registration time), no reflection (register the callable, not its name), no type-switch (every model registers, `MachineModel` included).

### The routing ladder

The decision that matters is who owns the registrations — a ladder:

| Rung | Mechanism                                             | Property                                                                                                                             |
| ---- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| 1    | central conditional (`if isinstance …`)               | closed; edit the dispatcher per entity                                                                                               |
| 2    | hand-maintained central registry (today)              | open-ish, but the dispatcher still enumerates every entity/namespace by hand                                                         |
| 3    | owner-registered registry (`ready()`) — the inversion | open/closed; removes the three smells above                                                                                          |
| 4    | declaration-derived dispatch — the endgame            | the table is computed from model metadata; the engine is a generic interpreter over a few shape-handlers + a registered escape hatch |

The plan climbs 2 → 3 → 4. That reframes the inversion as a rung change (who registers), not a rewrite, and rung 4 as the model-driven endgame this doc scopes.

#### Rung 4: resolution is reconciliation

Rung 4 is designable because the bespoke resolvers are not ad-hoc — each is a **desired-state reconciliation loop**: read the active claims, compute the desired materialized set, diff against the DB, then create / delete / update. `_resolve_machine_model_m2m` already is one (read claims → desired set → diff through-table → `bulk_create` / `delete`). So the rung-4 engine is not "a better registry" but **a generic reconciler + a per-shape desired-state function**, where the desired-state shape (field → through-model → target → payload columns / identity) is mostly declarable — exactly the `CatalogRelationshipSpec` vocabulary. Naming it reconciliation (rather than "generic resolver") is what makes the hard declaration-vocabulary design tractable: you declare the desired-state shape and the generic differ does the writes.

#### Invariants to preserve

A naive "auto-discover everything" rewrite tends to drop these; keep them: fail-fast on the unhandled namespace (a derived table must still raise, not silently skip); the two cardinalities with distinct invalidation contracts (per-entity `on_commit(invalidate_all)` vs. bulk's once-after-run — generalize the routing, not the cardinality split); the registered **escape hatch** for materializations that defy a declarative shape (`Credit`, `location_path` — declare the 90%, register the rest); and explicit, ordered stages (ordering stays first-class, not an emergent property of registration order).

### Rejected alternatives

The fundamental alternatives the patterns above beat:

- **Polymorphism on the model (`entity.resolve()`).** The textbook fix for a type-switch: a virtual method, dynamic dispatch replacing `isinstance`. Rejected — it scatters projection logic across every domain model, recoupling the schema to the mechanism, which is the exact opposite of the model-driven goal (generic engine + declarations, no per-model resolver code). It optimizes for "no central dispatcher"; this project wants "no per-model code." Different axis.
- **Signals / pub-sub** (emit "claims changed," resolvers subscribe). Rejected — it destroys **fail-fast** (no subscriber is a silent no-op), makes the **required ordering** implicit and fragile (scalars must resolve last; some derived rows depend on relationship rows existing first), and makes the bulk path's **batching** awkward. Resolution is a correctness-critical projection that wants explicitness; signals trade exactly that away for decoupling it does not need.
- **`match`/`case` structural matching.** Rejected as cosmetic — nicer syntax for the same centralized type-switch; it does not move up the ladder.
