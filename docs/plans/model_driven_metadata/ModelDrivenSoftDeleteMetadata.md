# Model-Driven Soft-Delete Metadata

## Context

This work is an instance of the broader pattern in [ModelDrivenMetadata.md](ModelDrivenMetadata.md): encode per-model behavior on the model itself, consume it generically from shared infrastructure.

`LifecycleStatusModel` is the base for soft-deletable catalog entities. Its soft-delete behavior has two per-model knobs that today live as bare `ClassVar`s on individual subclasses, read via `getattr` from the soft-delete machinery in [`apps/catalog/api/soft_delete.py`](../../backend/apps/catalog/api/soft_delete.py). This doc covers the hoist of both knobs onto `LifecycleStatusModel` in a single step — same shape, same recipe, no reason to split.

For catalog record lifecycle cascade rules, see [Cascade Rules](../../RecordLifecycle.md#cascade-rules).

## Family of plans (Soft-Delete Metadata)

This is one of three coordinated plans that put soft-delete-related metadata on `LifecycleStatusModel` and consume it generically. Each ships independently along a different layer:

- **[ModelDrivenSoftDeleteMetadata.md](ModelDrivenSoftDeleteMetadata.md) (this doc) — data layer.** Cascade and block declarations consumed by the soft-delete planner (`apps/catalog/api/soft_delete.py`).
- [ModelDrivenDeleteRoutes.md](ModelDrivenDeleteRoutes.md) — **API layer.** Route registration for the delete-preview / delete / restore trio, with `__subclasses__()`-driven discovery.
- [ModelDrivenDeletePage.md](ModelDrivenDeletePage.md) — **frontend layer.** Per-entity copy strings exported via `ENTITY_META`, consumed by a single dynamic delete-page route.

The three docs share a base class but consume different things and ship in any order.

### Prefix convention

Two prefixes are intentional, not drift:

- `soft_delete_*` — data-layer / DB-mechanism declarations: how the cascade walks, what blocks the soft-delete write at the model layer. Lives in this doc.
- `delete_*` — API and presentation declarations: which routes to expose, what copy to render, where to redirect, what FK ties to the parent for breadcrumb / redirect. Lives in the API and frontend docs.

When in doubt, ask: is this a fact about the soft-delete cascade machinery, or a fact about the API/presentation delete experience? The answer picks the prefix.

## The contracts

`LifecycleStatusModel` declares both as typed ClassVars with empty defaults:

```python
class LifecycleStatusModel(models.Model):
    soft_delete_cascade_relations: ClassVar[frozenset[str]] = frozenset()
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset()
    # ...
    class Meta:
        abstract = True
```

| Attr                            | Default       | Purpose                                                                                                  |
| ------------------------------- | ------------- | -------------------------------------------------------------------------------------------------------- |
| `soft_delete_cascade_relations` | `frozenset()` | Reverse-manager names whose related rows should soft-delete alongside the parent.                        |
| `soft_delete_usage_blockers`    | `frozenset()` | Reverse-manager names whose presence blocks soft-delete (M2M through-rows, self-ref hierarchy children). |

Default empty — every existing subclass without an explicit declaration is unaffected. Subclasses with cascade or block requirements override:

```python
class Title(ClaimControlledModel, LifecycleStatusModel):
    soft_delete_cascade_relations: ClassVar[frozenset[str]] = frozenset({"machine_models", ...})

class Theme(ClaimControlledModel, LifecycleStatusModel):
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset({...})
```

The soft-delete machinery in `apps/catalog/api/soft_delete.py` reads each attr directly from `type(entity)` — no fallback needed because the contract lives on the base.

## Current state and hoist plan

Today both attrs are typed (`ClassVar[frozenset[str]]`, per [ModelDrivenMetadataCleanup.md](ModelDrivenMetadataCleanup.md)) but only declared on subclasses that need them. Consumers in `apps/catalog/api/soft_delete.py` read via:

- `getattr(type(entity), "soft_delete_cascade_relations", frozenset())` (one call site, `soft_delete.py:148`).
- `getattr(type(entity), "soft_delete_usage_blockers", frozenset())` (one call site, `soft_delete.py:212`).

This is the [field-on-model antipattern](ModelDrivenMetadata.md#antipattern-field-on-model) shape — typed declarations on subclasses, untyped reads on the consumer side.

Declarations today:

- `soft_delete_cascade_relations`: declared on Title only.
- `soft_delete_usage_blockers`: declared on Theme, GameplayFeature, and three taxonomy models (System, Series, Franchise via the shared taxonomy base).

Hoist:

1. Add both ClassVars to `LifecycleStatusModel` in `apps/core/models.py` with `frozenset()` defaults.
2. Subclass declarations remain — they become typed overrides of the base default rather than ad-hoc additions.
3. Replace the two `getattr(type(entity), "<attr>", frozenset())` reads in `apps/catalog/api/soft_delete.py` with direct attribute access (`type(entity).<attr>`).
4. Update the module docstring in `soft_delete.py` (lines 9, 22, 29) to describe the attrs as `LifecycleStatusModel` ClassVars rather than "opt-in attributes on the model."
5. No semantic change. Existing soft-delete cascade and blocker tests carry over.

## Why this lives on `LifecycleStatusModel`

Both attrs are meaningful only for models that participate in the soft-delete lifecycle. `LifecycleStatusModel` is the smallest base that captures the audience — every soft-deletable entity inherits from it, and nothing else does. Hoisting puts the contract on the class the consumer already knows about, lets the type checker enforce the shape, and brings soft-delete metadata in line with the rest of the model-driven metadata work (see [ModelDrivenClaimsMetadata.md](ModelDrivenClaimsMetadata.md) for the parallel hoists in the claims family).
