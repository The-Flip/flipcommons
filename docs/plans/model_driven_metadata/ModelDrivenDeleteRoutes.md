# Model-Driven Delete Routes

## Status: planned — not yet in code

The machinery this doc proposes — `register_delete_routes`, the `expose_delete_routes` / `delete_active_children_relation` / `delete_parent_field` ClassVars, `detail_queryset()`, and the registration checks — does not exist yet. A related per-entity factory, `register_entity_delete_restore` (`apps/catalog/api/entity_crud.py`), is in use today; this doc's generic route registration has not landed.

## Context

This work is an instance of the broader pattern in [ModelDrivenMetadata.md](ModelDrivenMetadata.md): encode per-model behavior on the model itself, consume it generically from shared infrastructure, replace hand-maintained registries with `__subclasses__()`-style discovery.

It is the backend slice of soft-delete HTTP route registration — the delete-preview / delete / restore trio. The handler bodies are already factored in [`entity_crud.py`](../../../backend/apps/catalog/api/entity_crud.py) via `register_entity_delete_restore`, but the **registration call** is still hand-rolled in 9 per-entity modules across 17 call sites. This plan replaces those scattered calls with model-declared metadata + `LifecycleStatusModel.__subclasses__()` discovery + a system-checked validator.

Three additional entities — Title, MachineModel, and Person — have **bespoke** delete-preview / delete / restore handlers in their own API modules ([`titles.py`](../../../backend/apps/catalog/api/titles.py), [`machine_models.py`](../../../backend/apps/catalog/api/machine_models.py), [`people.py`](../../../backend/apps/catalog/api/people.py)) that don't go through the shared factory at all. They have working delete UX today; they just predate or exceed the factory's current shape. This plan opts them out of factory auto-registration via `expose_delete_routes=False` and tracks migration as a follow-up — at which point the factory has to grow whatever hooks the bespoke handlers needed (Title's `active_model_count` field in delete-preview is the canonical example).

### Why a previous draft was rejected

A first draft (`ConsolidateDeleteRoutes.md`, deleted) proposed a hand-maintained registry list to consolidate the 17 call sites. That was rejected as a relocation, not a model-driven move — it would have replaced 17 hand-maintained call sites with one hand-maintained list, exactly the smell ModelDrivenMetadata.md calls out:

> a hand-maintained list, set, dict, or constant enumerates the same model set Django already knows about… The fix is `__subclasses__()` walk + (at most) a marker base class.

A second draft (`ModelDrivenSoftDeleteRoutes.md`, also deleted) introduced a new `SoftDeletableModel` marker base. That was rejected as redundant: every concrete catalog entity already inherits `LifecycleStatusModel` transitively (via `CatalogModel`), and adding a parallel base would split soft-delete metadata across two places. This draft puts everything on `LifecycleStatusModel`.

## Family of plans (Soft-Delete Metadata)

This is one of three coordinated plans that put soft-delete-related metadata on `LifecycleStatusModel` and consume it generically. Each ships independently along a different layer:

- [ModelDrivenSoftDeleteMetadata.md](ModelDrivenSoftDeleteMetadata.md) — **data layer.** Cascade and block declarations consumed by the soft-delete planner (`apps/catalog/api/soft_delete.py`).
- **[ModelDrivenDeleteRoutes.md](ModelDrivenDeleteRoutes.md) (this doc) — API layer.** Route registration for the delete-preview / delete / restore trio, with `__subclasses__()`-driven discovery.
- [ModelDrivenDeletePage.md](ModelDrivenDeletePage.md) — **frontend layer.** Per-entity copy strings exported via `ENTITY_META`, consumed by a single dynamic delete-page route.

The three docs share a base class but consume different things and ship in any order.

### Prefix convention

Two prefixes are intentional, not drift:

- `soft_delete_*` — data-layer / DB-mechanism declarations: how the cascade walks, what blocks the soft-delete write at the model layer. Lives in [ModelDrivenSoftDeleteMetadata.md](ModelDrivenSoftDeleteMetadata.md).
- `delete_*` — API and presentation declarations: which routes to expose, what copy to render, where to redirect, what FK ties to the parent for breadcrumb / redirect. Lives in this doc and [ModelDrivenDeletePage.md](ModelDrivenDeletePage.md).

When in doubt, ask: is this a fact about the soft-delete cascade machinery, or a fact about the API/presentation delete experience? The answer picks the prefix.

The two prefix groups don't conflict on names — the data-layer pair (`soft_delete_cascade_relations`, `soft_delete_usage_blockers`) and the API-layer pair proposed here (`delete_active_children_relation`, `delete_parent_field`) are orthogonal axes. See [Open question: derivability](#open-question-is-delete_active_children_relation-derivable) for one place they touch.

## Desired end state

- All four soft-delete-route ClassVars live on `LifecycleStatusModel` next to the existing pair from [ModelDrivenSoftDeleteMetadata.md](ModelDrivenSoftDeleteMetadata.md).
- A `detail_queryset()` `@classmethod` on the base returns the prefetch-rich queryset used to load an entity for detail-page response serialization. Default: `cls.objects.active()`. Concrete entities override to add `select_related`/`prefetch_related`.
- A separate `register_delete_routes(model_cls, *, router, serialize_detail, response_schema)` call in each entity's API module pairs the framework-aware bits (Ninja router + serializer + schema) with the model. Called once per entity at module import time. Framework-aware code stays out of the model.
- An `AppConfig.ready()` walk over `catalog_app_subclasses(LifecycleStatusModel)` filters by `expose_delete_routes` and auto-registers the route trio for every participant. No hand-maintained list anywhere.
- A `manage.py check` system check fails at startup if a participating entity has no registration (or a registration without the matching opt-in), or if declared ClassVars don't resolve via `_meta`.
- A parity test pins the auto-registered set to an explicit expected list, so accidental inclusion/exclusion triggers review.

## The contracts

### Hoist onto `LifecycleStatusModel`

Lives in `apps/core/models.py` next to the existing `LifecycleStatusModel` definition; the data-layer ClassVars from [ModelDrivenSoftDeleteMetadata.md](ModelDrivenSoftDeleteMetadata.md) sit alongside.

```python
from typing import ClassVar, Self
from django.db.models import QuerySet


class LifecycleStatusModel(models.Model):
    # … existing soft-delete data-layer ClassVars (from ModelDrivenSoftDeleteMetadata.md) …
    soft_delete_cascade_relations: ClassVar[frozenset[str]] = frozenset()
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset()

    # Soft-delete HTTP route registration (this plan).

    # Whether the delete-preview / delete / restore trio is exposed at
    # /api/{plural}/{public_id}/{delete-preview, delete, restore}/
    # via the shared factory. Default True — every concrete catalog
    # entity opts in unless it explicitly opts out. Title / MachineModel /
    # Person set this to False today because they have bespoke
    # delete handlers in their per-entity API modules that don't go
    # through the factory; "False" here means "doesn't auto-register
    # via the factory," not "no delete UX." Migrating each onto the
    # factory is tracked as follow-up work.
    expose_delete_routes: ClassVar[bool] = True

    # Reverse-accessor name on this model whose active children should
    # block delete with a structured 422 ("X has N active children;
    # delete those first") rather than the generic blocker error.
    # Used today only for self-ref hierarchy parents (TechnologyGeneration,
    # DisplayType). None means no children-block check at the API layer
    # (the data-layer soft_delete_usage_blockers may still block).
    delete_active_children_relation: ClassVar[str | None] = None

    # FK field name pointing at the parent entity, used by delete-preview
    # to surface the parent ref and by restore to guard against restoring
    # while the parent is still soft-deleted. None means unparented; nullable
    # parent FKs (Location countries) handle their own None case at runtime.
    delete_parent_field: ClassVar[str | None] = None

    @classmethod
    def detail_queryset(cls) -> QuerySet[Self]:
        """Return the prefetch-rich queryset used to load this entity for
        detail-page response serialization (e.g. after restore).

        Default: ``cls.objects.active()``. Override on concrete subclasses
        to add ``select_related`` / ``prefetch_related`` for the fields
        the detail schema reads.
        """
        return cls.objects.active()

    class Meta:
        abstract = True
```

None of these introduces a Ninja or schema-layer dependency on the model. ClassVars are pure data; the classmethod returns a Django queryset. The framework boundary lives in the registration call below.

### Per-entity registration call

Lives in a new `apps/catalog/api/delete_routes.py`.

```python
@dataclass(frozen=True)
class _DeleteRouteSpec:
    router: Router
    serialize_detail: Callable[[Any], Schema]
    response_schema: type[Schema]


_REGISTRY: dict[type[LifecycleStatusModel], _DeleteRouteSpec] = {}


def register_delete_routes[ModelT: LifecycleStatusModel, SchemaT: Schema](
    model_cls: type[ModelT],
    *,
    router: Router,
    serialize_detail: Callable[[ModelT], SchemaT],
    response_schema: type[SchemaT],
) -> None:
    """Pair a soft-delete-routed model with its router + detail serialization.

    Called once per entity at module import time, from the entity's API
    module. Actual route registration happens later, from the catalog
    AppConfig.ready() hook, after every per-entity API module has imported
    and registered.
    """
    if not model_cls.expose_delete_routes:
        raise ImproperlyConfigured(
            f"{model_cls.__name__} has expose_delete_routes=False but "
            "register_delete_routes was called for it."
        )
    if model_cls in _REGISTRY:
        raise ImproperlyConfigured(
            f"Duplicate delete-route registration for {model_cls.__name__}."
        )
    _REGISTRY[model_cls] = _DeleteRouteSpec(
        router=router,
        serialize_detail=serialize_detail,
        response_schema=response_schema,
    )


def install_all_delete_routes() -> None:
    """Walk LifecycleStatusModel subclasses and register their route trios.

    Called from CatalogConfig.ready() after all per-entity modules have
    imported. System checks (registered separately) enforce both directions:
    every opted-in subclass has a registration; every registration is for
    an opted-in subclass.
    """
    apps.check_apps_ready()
    for model_cls in catalog_app_subclasses(LifecycleStatusModel):
        if not model_cls.expose_delete_routes:
            continue
        spec = _REGISTRY[model_cls]
        register_entity_delete_restore(
            spec.router,
            model_cls,
            detail_qs=model_cls.detail_queryset,
            serialize_detail=spec.serialize_detail,
            response_schema=spec.response_schema,
            child_related_name=model_cls.delete_active_children_relation,
            parent_field=model_cls.delete_parent_field,
        )
```

### System checks

Registered via `apps.checks` from the catalog `AppConfig`:

1. Every concrete `LifecycleStatusModel` subclass with `expose_delete_routes=True` has an entry in `_REGISTRY`. Missing = `Error("E.delete_routes.missing_registration", ...)`.
2. Every entry in `_REGISTRY` is for a subclass with `expose_delete_routes=True`. (Mostly defensive — the registration helper already guards.)
3. For each opted-in subclass:
   - If `delete_active_children_relation` is set, `_meta.get_field(...)` resolves to a reverse relation accessor.
   - If `delete_parent_field` is set, `_meta.get_field(...)` resolves to a `ForeignKey`.

Failures surface at `manage.py check` and on `runserver` boot — not at first request.

### Per-entity changes

For each of the 17 currently-participating entities:

1. Move existing prefetch logic from `_*_detail_qs` into a `detail_queryset()` `@classmethod` on the model.
2. Move `child_related_name` / `parent_field` arguments from the factory call to `delete_active_children_relation` / `delete_parent_field` ClassVars on the model.
3. Replace `register_entity_delete_restore(...)` with `register_delete_routes(MyModel, router=my_router, serialize_detail=serialize_my_detail, response_schema=MyDetailSchema)`.
4. Drop the `register_entity_delete_restore` import.

For Title, MachineModel, and Person: declare `expose_delete_routes: ClassVar[bool] = False` with a one-line comment pointing at the migration follow-up. Their delete UX continues to be served by the bespoke handlers already in their per-entity API modules — the opt-out flag means "doesn't auto-register via the factory yet," not "no delete UX." Each is a documented migration target, not a silent omission.

Taxonomy specifics:

- The 8 simple taxonomy entities currently share `_taxonomy_detail_qs(model)` and `_serialize_taxonomy`. Two options for `detail_queryset()`:
  - Add a thin abstract intermediate `TaxonomyEntityModel(CatalogModel)` that overrides `detail_queryset()` once for the family. (Cleaner; allowed because `catalog_app_subclasses` is `_meta.abstract`-aware.)
  - Have each of the 8 override `detail_queryset()` with the same body. (Mechanical duplication, but no model-layer change.)
  - **Recommended:** the abstract intermediate, in the same PR.
- `serialize_taxonomy` and `TaxonomySchema` get passed identically by 8 `register_delete_routes` calls — same call count as the existing `_register_delete_restore` calls, but now framework-pairing rather than route-handler registration.

CreditRole keeps its own serializer / schema; the registration call is just specialized to it.

## Open question: is `delete_active_children_relation` derivable?

The existing data-layer `soft_delete_usage_blockers` ClassVar already lists "M2M through-rows and self-ref hierarchy children" per its docstring. `delete_active_children_relation` is _only_ used for self-ref hierarchy children today (TechnologyGeneration → subgenerations, DisplayType → subtypes). In principle the API layer could derive it by walking `soft_delete_usage_blockers`, filtering to entries that resolve via `_meta` to a reverse accessor on a self-ref FK.

But: TechnologyGeneration and DisplayType **don't currently declare `soft_delete_usage_blockers`** — only the API-layer `child_related_name` is configured for them. So derivation isn't possible without first adding the data-layer declarations. The two checks are also semantically distinct in error shape (data-layer returns populated `blocked_by`; API-layer returns empty `blocked_by` + populated `active_children_count`).

**Resolution path:**

1. Land this plan with both ClassVars declared independently — same shape as today, no behavior change.
2. As a follow-up: add `soft_delete_usage_blockers={"subgenerations"}` / `{"subtypes"}` to TechnologyGeneration / DisplayType (closing a real data-layer gap), then derive `delete_active_children_relation` automatically and remove the explicit declaration.

Splitting the work this way keeps each step minimal and makes the data-layer fix a separate, easily-reviewable change.

## What this does not do

- **Doesn't change route URLs, response shapes, or any handler behavior.** Pure refactor — `make codegen` produces no diff, all existing delete-restore tests pass.
- **Doesn't touch create routes.** `register_entity_create` has more per-entity variation (parented vs. unparented, scope filters, body schemas, extra-fields builders). Natural follow-up plan once this pattern proves out.
- **Doesn't touch PATCH-claims handlers.** Discussed and deferred separately.
- **Doesn't migrate Title / MachineModel / Person off bespoke handlers.** Their hand-rolled delete-preview / delete / restore routes in `titles.py` / `machine_models.py` / `people.py` keep working unchanged; they declare `expose_delete_routes=False` to opt out of factory auto-registration. Migration is a follow-up — the factory has to grow whatever extra hooks the bespoke handlers needed (e.g. Title's `active_model_count` in delete-preview).
- **Doesn't move detail helpers (`serialize_*`, `*DetailSchema`) onto the model.** They stay in the per-entity API module. Models stay framework-neutral.
- **Doesn't derive `delete_active_children_relation` from `soft_delete_usage_blockers` yet.** See [Open question](#open-question-is-delete_active_children_relation-derivable).

## Validation

- `make test` passes — same handler bodies, same routes, same URLs.
- `make codegen` produces no diff — schema is identical.
- `manage.py check` is clean. A probe commit deliberately breaking a registration fails the check loudly.
- Parity test in `apps/catalog/tests/test_delete_route_registry.py` asserts the auto-registered set matches an explicit list of 17 entity classes. Adding or removing a participating entity triggers the test.
- Spot-check delete / delete-preview / restore on one entity per category (one regular entity, one taxonomy entity, one parented entity, Location).
- Pre-commit hooks pass.

## Risk

Moderate, but contained.

- **Import-order.** `register_delete_routes` runs at entity-module import; `install_all_delete_routes()` runs from `CatalogConfig.ready()`. As long as `apps/catalog/api/__init__.py` imports every entity module before `ready()` fires (it does today), the registry is populated when the walk runs. System check catches any regression.
- **`detail_queryset()` semantics shift slightly.** Existing `_*_detail_qs` helpers are module-level functions; some return `cls.objects.active().select_related(...)`, others have richer prefetch chains. Moving to `@classmethod`s is mechanical, but each one needs to be re-verified against the response schema's read paths.
- **Taxonomy abstract intermediate.** Adding `TaxonomyEntityModel` is a model-layer change. Migrations should be no-op (abstract bases don't generate DDL), but the diamond-inheritance pattern in `ClaimControlledModel` is a reminder to be careful. Verify `makemigrations` is clean.
- **Two-sided declaration.** An opted-in entity needs both `expose_delete_routes=True` (the default) and a `register_delete_routes` call. Forgetting the latter is a misconfiguration. The system check makes this loud at boot, not silent at first request.

## Net effect

- Adding a new soft-delete-routed entity drops from "edit one entity-module + match a 6-line factory call site against the existing pattern" to "extend `CatalogModel` (which inherits `LifecycleStatusModel`), declare any non-default ClassVars, override `detail_queryset()` if needed, call `register_delete_routes(...)` once."
- 17 hand-maintained registration call sites collapse into per-model declarations + per-entity registration calls — same order-of-magnitude line count, but every line is now a declaration about _this_ entity rather than a copy of the factory's call signature.
- Zero hand-maintained "list of soft-delete-routed models" anywhere in the codebase.
- The three bespoke-handler entities (Title, MachineModel, Person) become explicit, documented opt-outs that point at a migration follow-up, rather than silent omissions.
- The pattern is now proven at the smallest scope, ready to be applied to create / list / detail / edit-history / sources.

## Follow-ups

After this lands and the pattern is proven:

1. **Close the `soft_delete_usage_blockers` gap** on TechnologyGeneration / DisplayType, then derive `delete_active_children_relation` from `_meta` and remove the explicit declaration. See [Open question](#open-question-is-delete_active_children_relation-derivable).
2. **Create routes.** Same pattern, with hooks for parented variants, scope filters, body schemas, and extra-fields builders kept at the registration-call layer rather than as ClassVars.
3. **List + detail + edit-history + sources routes.** Same pattern.
4. **Migrate the three bespoke handlers onto the factory.** Title / MachineModel / Person flip from `expose_delete_routes=False` to `True` once the factory grows whatever extra hooks they need (e.g. Title's `active_model_count` field in delete-preview). Their hand-rolled routes in `titles.py` / `machine_models.py` / `people.py` get deleted in the same step.
5. **Eventually**: model-driven derivation of detail response schemas. That's the [ModelDrivenApi.md](ModelDrivenApi.md) endgame and explicitly out of scope here.
