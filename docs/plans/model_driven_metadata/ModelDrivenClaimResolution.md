# Claim Resolution

## Context

One goal we have for Flipcommons is to make it the steel thread proving out a new, reusable category of collaborative encyclopedia wiki software. We want to be able to replace the catalog app with an entirely different domain than pinball -- like baseball or medicine -- to create an entirely different collaborative encyclopedia wiki on a different subject. Ideally we'd even have a low code / AI-driven layer that lets non-technical people do the data modeling, though that's in the future.

So we want to move everything that's not directly related to the pinball domain out of catalog, and ensure that no other app has anything about the pinball domain. This is basically the docs/plans/model_driven_metadata/ModelDrivenMetadata.md vision.

## The question

Resolution is the one piece the claim-write plan ([ModelDrivenClaimWrite.md](ModelDrivenClaimWrite.md)) deliberately leaves in catalog: "resolution must stay in catalog — it is catalog's job to materialize denormalized fields and through-tables from claims." That's the right conservative call for that plan (the concrete resolvers bind concrete tables, so they can't move until the declarations that would drive a generic engine exist). But it raises the deeper question this doc answers: **are the resolvers really pinball-specific, or is there a generic engine hiding inside them?**

Mostly the latter. The resolver _mechanism_ is largely domain-agnostic; what's pinball-specific is the schema, a relationship config table, and two compound shapes. Resolution is a generic **projection pattern** — claims are the source of truth, and a resolver materializes them into the denormalized fields and through-tables that make the catalog queryable. Every claim-based domain needs that projection; only the target tables differ.

## What's in `catalog/resolve/` today, by tier

### Tier 1 — scalar resolution: already fully generic

`_entities.py` (`resolve_entity[T: ClaimControlledModel]`, `resolve_all_entities`) iterates `get_claim_fields(model_class)`, picks the winning claim per field, and `setattr`s it onto the model, coercing through `model_class._meta.get_field(attr)`. No concrete model is named anywhere — it is model-driven today. This is substrate that merely happens to live in catalog; nothing about it is pinball-specific.

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

`resolve_after_mutation` (`_dispatch.py:106`) branches on `isinstance(entity, MachineModel)` (`:127`) and `resolve_relationships_bulk` on `issubclass(model_class, MachineModel)` (`:293`). The claim-write plan's "Invert resolution" step already retires both by folding them into per-model registration — independent of anything here.

## What's irreducibly pinball

Narrow: **the concrete model definitions themselves** — `Title`, `MachineModel`, `Theme`, `Credit`, the through-tables and their columns. That is the domain by definition; you cannot hoist the schema. Everything else is _mechanism_ (generic) plus _config_ (declarable) plus a couple of _bespoke shapes_.

So the honest answer to "are the resolvers pinball-specific?" is **no, not the resolvers — only the schema they project into, the table of which-field-maps-to-which-through-table, and two compound materializations.**

## The model-driven-resolver opportunity

This mirrors what the claim-write plan did to the write surface, applied to the read/projection side. The relationship-schema registry (provenance) already declares relationship _shapes_ model-drivenly for the bulk write path. If those declarations carried enough metadata for resolution too — _field → through-table → target model → payload columns / identity shape_ — then a **generic resolver engine** could drive Tiers 1–2 and most of Tier 3 off declarations, leaving only the genuinely-bespoke materializations hand-written. Part of that declaration is already designed: [ModelDrivenCatalogRelationshipMetadata.md](ModelDrivenCatalogRelationshipMetadata.md)'s `CatalogRelationshipSpec` ("given a claim namespace, what through-model does it live on, and how do I build/resolve/validate it") is exactly the spec a generic resolver would consume. That doc is **deferred pending a second independent consumer** — and this read-side engine is that consumer, so this is the work that would revive it. The FK-resolution half already shipped as the `claim_fk_lookups` ClassVar (`public_id → pk`); a generic resolver builds on what's there.

The end state: catalog shrinks toward **schema + declarations + a handful of custom resolvers**:

- **Schema** — the concrete models (irreducible).
- **Declarations** — relationship and derived-field metadata, ideally as ClassVars on the models (the same model-driven channel `soft_delete_cascade_relations` and the linkable registry already use), not as resolver code.
- **Custom resolvers** — only where a materialization genuinely defies a declarative shape (compound identity like `Credit`, computed fields like `Location.location_path`).

The generic engine — scalar projection, plain-M2M projection, payload-M2M projection — hoists to the substrate (provenance or a resolution app), driven entirely by the declarations. That is precisely the [ModelDrivenMetadata.md](ModelDrivenMetadata.md) endgame applied to resolution.

## Scope and sequencing

This is a **separate, larger refactor than the claim-write plan, and the next one after it** — not part of it. Two reasons it can't ride along:

1. You can't drive resolvers from declarations until the declarations are rich enough to express every shape resolution needs (payload columns, compound identity, coercion rules). Designing that declaration vocabulary _is_ the hard part, and it's its own design problem.
2. It's the same class of work as the relationship-claim-construction convergence the claim-write plan calls out as its "seam to watch" — the interactive write path's hand-written per-relationship planners and the resolvers are two halves of the same per-relationship hand-coding, and a model-driven pass should likely address both together.

The claim-write plan's "resolution stays in catalog" is therefore a statement about where the _concrete_ resolvers live today and which seam it inverts (the dispatch) — **not** a claim that resolution is irreducibly domain logic. It isn't. It's a generic projection engine wearing pinball configuration, and making that separation explicit is the work this doc scopes for later.
