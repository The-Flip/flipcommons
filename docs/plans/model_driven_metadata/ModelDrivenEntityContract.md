# Model-Driven Entity Contract

## Status: proposed

A framework-neutral alternative to [ModelDrivenApi.md](ModelDrivenApi.md) for where the domain/delivery seam lives. Not implemented — models carry no `catalog_contract` declaration today. The two docs are competing designs; neither has landed.

## Framing

A catalog model should describe itself in terms the outside world can consume, without knowing who is consuming it. It should not know about Django Ninja, about HTTP, about routers, about response schemas, about JSON. If the project replaced Ninja with DRF, with vanilla Django views, or with a GraphQL layer tomorrow, the catalog models should not change.

What the model owes the system is its **content shape and write surface**: which fields are visible in a list, which appear on a detail view, which are editable, which are required on creation, which non-scalar edits need a custom claim planner. That is a stable, framework-neutral contract about the entity itself.

What the model does not owe the system is the _delivery mechanism_ for that contract — Schema classes, route registration, request/response wiring, OpenAPI metadata. Those are adapter concerns and live in the adapter.

This doc is an instance of the broader pattern in [ModelDrivenMetadata.md](ModelDrivenMetadata.md), separated cleanly from API route ownership: the entity declares _what_, the adapter decides _how_.

## The litmus test

> If we replaced the entire HTTP layer tomorrow, the model declarations should not move.

Every proposed addition to a model-side spec should pass that test. If the answer involves importing a Schema class, naming a serializer that returns a Schema instance, or referencing a route, the declaration is on the wrong side of the seam.

## Where the seam lives

Two layers, with one direction of dependency:

- **Model side.** Pure ORM + plain Python. Declares identity (`entity_type`, `public_id_field`, base-class participation), claim-control behavior, and a _content contract_ describing read projections and write surface. No imports from any web framework.
- **Adapter side.** Reads the contract plus Django `_meta` and synthesizes whatever the current delivery layer needs — Ninja Schemas, routes, OpenAPI metadata, codegen output. The adapter knows about the model; the model does not know about the adapter.

The dependency arrow only points one way. That is what makes the layer below replaceable.

## What the model declares

The contract is intentionally small and built from reusable primitives, not a single grab-bag spec:

- **Read projections** — for each view a consumer might want (list, detail, others as they appear), the set of field names and any computed extras. Field names resolve through `_meta`; computed extras are plain callables `(obj) -> value`. That is enough for any adapter to derive a response shape.
- **Write surface** — which fields are creatable, which are required on create, which are claim-patch editable. Plus a tuple of _planners_ for non-scalar edits (aliases, parents, relationship sections). Planners operate on the model and produce claims; they do not see HTTP.
- **Lifecycle and provenance participation** — not declared at all. Derived from base-class membership. `SoftDeletableModel` means lifecycle endpoints exist; `ClaimControlledModel` means edit-history and sources exist. Absence is default; participation is opt-in by inheriting the right mixin.

Everything else — pagination, filters, OpenAPI tags, route prefixes, response Schema classes — lives in the adapter, derivable from the contract plus `_meta` plus the model's identity ClassVars.

## A small illustration

```python
# Pure Python, no web framework.
class Theme(CatalogModel, SoftDeletableModel):
    entity_type = "theme"

    catalog_contract = CatalogEntityContract(
        list_view=FieldProjection(fields={"name", "slug", "status", "parent"}),
        detail_view=FieldProjection(
            fields={"name", "slug", "status", "parent", "description"},
            computed={"breadcrumbs": theme_breadcrumbs},
        ),
        write=WriteSurface(
            creatable={"name", "slug", "parent"},
            required_on_create={"name"},
            editable={"name", "slug", "status", "description"},
            extra_planners=(plan_theme_parent_claims, plan_theme_alias_claims),
        ),
    )
```

The model says what _is_. The adapter — somewhere in `apps/catalog/api/` or its successor — reads this and produces the Schemas, the routes, and the wire formats. Replace that adapter and the declaration above stands.

## Why this shape

Three properties matter:

- **Replaceable delivery.** The web framework is no longer load-bearing on the model layer. That is the litmus test passing.
- **Stable, narrow primitives.** `FieldProjection` and `WriteSurface` are small enough to resist drift. New concerns earn their own primitive only by passing the four-test bar in [ModelDrivenMetadata.md](ModelDrivenMetadata.md): independent consumers, orthogonal axis, stable shape, no simpler pattern available.
- **Inheritance does the rest.** Lifecycle, edit-history, and sources are not declared per model; they are consequences of which base classes the model inherits. That is fail-safe-by-construction — adding a `SoftDeletableModel` automatically gets lifecycle, and forgetting to "register" lifecycle is structurally impossible.

## Pure-function discipline for planners

The one place this architecture can leak is in the planner tuple. Planners run during a write and must remain pure: model and claim inputs in, claims out. If a planner ever needs HTTP context — the raw request, headers, anything beyond the authenticated user threaded through `ChangeSet` — that signals an adapter concern that has wandered onto the model side. The fix is to lift that work back into the adapter, not to widen the planner signature.

## Composition with the rest of the model-driven work

The contract is one axis among several. It composes with the others without absorbing them:

- **Identity** (`entity_type`, `public_id_field`) — declared once, consumed by everything including this contract.
- **Claim control** (`claims_exempt`, `claim_fk_lookups`) — owned by `ClaimControlledModel`; the contract reads through it but does not duplicate it.
- **Relationships, wikilinks, media, citations** — separate axes with their own docs. The contract does not try to subsume them.
- **API delivery** — a downstream consumer of the contract, free to evolve under it.

The discipline is the same one the umbrella doc names: one axis, one spec; absence is default; inheritance over enumeration.

## What this is not

- Not a generic CRUD framework. It is a description of entity content; the adapter still has room for genuinely custom queries, custom validation, and bespoke endpoints.
- Not a DSL above Django. The contract is plain Python over Django primitives. Models remain the source of persistence truth.
- Not a profile object. The contract is _upstream_ metadata declared on the model. UI- or API-facing profile structures, if they ever appear, are derived views composed from this plus other axes — never the source.
- Not a route registry. Routes belong to the adapter. This doc deliberately says nothing about how URLs are mounted.

## Relationship to ModelDrivenApi

[ModelDrivenApi.md](ModelDrivenApi.md) is a competing vision. It places API-shaped declarations — response Schemas, body Schemas, endpoint participation — directly on the model. That framing fails the litmus test: swap the web framework and every catalog model changes.

This doc proposes the inverse: the model declares a framework-neutral contract; the API layer is one consumer of that contract, free to be rewritten without disturbing the models. The two visions are not additive. Picking one is a decision about where the seam between domain and delivery lives.
