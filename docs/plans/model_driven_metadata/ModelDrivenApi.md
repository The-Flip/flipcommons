# Model-Driven API

## Status

This is an exploratory alternative, not committed implementation direction. Do not cite this doc from umbrella roadmaps as the chosen endpoint-ownership plan until the API seam is reconciled.

[ModelDrivenEntityContract.md](ModelDrivenEntityContract.md) describes the competing framework-neutral direction: models declare content shape and write surface, while the API adapter owns schemas, routes, and wire formats. If that direction is accepted, this document should either move under an alternatives/rejected section or be rewritten to describe the adapter that consumes the framework-neutral contract.

## Context

This work is an instance of the broader pattern in [ModelDrivenMetadata.md](ModelDrivenMetadata.md): encode per-model behavior on the model itself, consume it generically from shared infrastructure.

The goal is not "generic CRUD" in the narrow REST sense. The API surface for a catalog entity includes list data, detail-page data, claim patching, create, delete-preview, delete, restore, edit history, sources, and sometimes supporting option endpoints. Some entities need custom querysets, serializers, validation, or relationship planners. That is fine.

What should disappear is per-entity route ownership.

Today an entity often owns a file in `apps/catalog/api/` with route decorators for endpoints whose shape is mostly universal:

- `GET /api/{collection}/`
- `GET /api/pages/{entity_type}/{public_id}/`
- `PATCH /api/{collection}/{public_id}/claims/`
- `POST /api/{collection}/`
- `GET /api/{collection}/{public_id}/delete-preview/`
- `POST /api/{collection}/{public_id}/delete/`
- `POST /api/{collection}/{public_id}/restore/`
- `GET /api/pages/edit-history/{entity_type}/{public_id}/`
- `GET /api/pages/sources/{entity_type}/{public_id}/`

The query for a detail page may be custom. The response schema may be custom. The claim planner may be custom. But the route itself should not be.

## Principle: entities declare capabilities, shared code owns routes

A catalog entity should declare the API surfaces it participates in. Shared API infrastructure should discover those declarations, mount the routes, resolve `(entity_type, public_id)`, run the common request pipeline, and call the declared query / serializer / planner hooks only at the points where behavior genuinely varies.

The split:

- **Model-owned:** identity, endpoint participation, response schemas, queryset builders, serializers, create body schemas, claim planner hooks, lifecycle blockers/cascades.
- **Shared-infrastructure-owned:** router creation, URL patterns, auth, rate limiting, object lookup, `public_id_field` handling, claim execution, delete/restore plumbing, edit-history and sources endpoints, OpenAPI route registration.

Per-entity API modules may still exist during migration, but in the end they should be behavior libraries, not route owners. A module that exports `theme_detail_qs` and `serialize_theme_detail` is acceptable. A module that decorates `@themes_router.get(...)` for a route the generic registrar can own is a violation.

## Contract shape

This should be one narrow API axis, not a grab-bag model profile. The central spec answers one question: which standard API endpoints does this model expose, and what hooks do those endpoints need?

Sketch:

```python
@dataclass(frozen=True)
class CatalogApiSpec:
    list: ListEndpointSpec | None = None
    detail: DetailEndpointSpec | None = None
    create: CreateEndpointSpec | None = None
    claims: ClaimPatchEndpointSpec | None = None
    lifecycle: LifecycleEndpointSpec | None = None
```

Concrete models opt in by assigning the spec:

```python
class Theme(CatalogModel):
    entity_type = "theme"
    entity_type_plural = "themes"

    catalog_api = CatalogApiSpec(
        list=ListEndpointSpec(
            response_schema=ThemeListItemSchema,
            queryset=theme_list_qs,
            serialize=serialize_theme_list_item,
        ),
        detail=DetailEndpointSpec(
            response_schema=ThemeDetailSchema,
            queryset=theme_detail_qs,
            serialize=serialize_theme_detail,
        ),
        claims=ClaimPatchEndpointSpec(
            body_schema=HierarchyClaimPatchSchema,
            extra_planners=(plan_theme_parent_claims, plan_theme_alias_claims),
        ),
        create=CreateEndpointSpec(),
        lifecycle=LifecycleEndpointSpec(delete=True, restore=True),
    )
```

Default specs should cover the common entity shape:

- list/detail queryset: `model.objects.active()`
- lookup: `model.public_id_field`
- create fields: `name`, `slug`, `status`, plus optional declared hooks
- scalar claim patching: `plan_scalar_field_claims(model, data.fields, entity=obj)`
- lifecycle: existing soft-delete machinery

Entities override only the behavior that differs.

## Route registry

A central registrar walks concrete `CatalogModel` subclasses after apps are ready, reads `model.catalog_api`, validates the spec, and mounts routes. The route mount is derived from model identity:

- collection prefix: `/{model.entity_type_plural}/`
- page-detail prefix: `/pages/{model.entity_type}/{path:public_id}`
- provenance page endpoints: `/pages/edit-history/{entity_type}/{path:public_id}/` and `/pages/sources/{entity_type}/{path:public_id}/`

Example flow:

```python
def register_catalog_api(router: Router) -> None:
    for model in catalog_app_subclasses(CatalogModel):
        spec = model.catalog_api
        if spec.list is not None:
            register_list_endpoint(router, model, spec.list)
        if spec.detail is not None:
            register_detail_page_endpoint(router, model, spec.detail)
        if spec.claims is not None:
            register_claim_patch_endpoint(router, model, spec.claims)
        if spec.create is not None:
            register_create_endpoint(router, model, spec.create)
        if spec.lifecycle is not None:
            register_lifecycle_endpoints(router, model, spec.lifecycle)
```

The important invariant: a new entity should not require adding a tuple to `apps/catalog/api/__init__.py` or a call to `register_entity_detail_page(...)` in `page_endpoints.py`. Discovery plus the model-owned spec should be enough.

## Endpoint families

### List

The standard list route is `GET /api/{collection}/`.

The spec owns the response schema, queryset builder, serializer, and optional query params. Simple list endpoints should be derived from `_meta` and defaults. Rich list endpoints can provide explicit hooks.

Open question for implementation: Ninja needs static function annotations for request/response models. Existing registrar functions already solve this with closure-bound schema classes and eager annotations. The API registrar should reuse that pattern.

### Detail Page

The standard detail-page route is `GET /api/pages/{entity_type}/{path:public_id}`.

The entity owns the detail queryset and serializer. Shared code owns the route and lookup:

```python
obj = get_object_or_404(detail_qs(), **{model.public_id_field: public_id})
return serialize_detail(obj)
```

The current `register_entity_detail_page` is the right primitive. The model-driven API work moves the registration data out of `page_endpoints.py` and onto the entity spec.

### Claim Patch

The standard write route is `PATCH /api/{collection}/{path:public_id}/claims/`.

Shared code owns:

- auth
- rate limiting
- lookup via `public_id_field`
- structured validation error handling
- scalar field planning through `plan_scalar_field_claims`
- `execute_claims(..., action=ChangeSetAction.EDIT)`
- refresh via the declared detail queryset and serializer

The entity spec owns:

- body schema
- extra claim planners for aliases, parents, relationship sections, or other non-scalar edit groups
- optional field allow/deny behavior for temporary migration states

The default patch endpoint should handle the simple case: `fields` only, scalar claims only.

### Create

The standard create route is `POST /api/{collection}/`, with parented variants declared by spec rather than custom route files.

Shared code owns the existing create pipeline:

- auth
- create rate limiting
- name validation
- slug/public-id validation
- uniqueness pre-checks
- atomic row creation plus initial `ChangeSetAction.CREATE` claims
- `IntegrityError` translation
- response serialization

The entity spec owns:

- body schema
- parent lookup, if any
- scope filters for name uniqueness, until those can be derived from model constraints
- extra row kwargs for derived fields
- extra initial claims
- response detail queryset / serializer

This keeps `register_entity_create` as the execution primitive but removes the need for every entity to own the route call site.

### Lifecycle

The standard lifecycle routes are:

- `GET /api/{collection}/{path:public_id}/delete-preview/`
- `POST /api/{collection}/{path:public_id}/delete/`
- `POST /api/{collection}/{path:public_id}/restore/`

Shared code owns the route and execution. Model-level declarations like `soft_delete_cascade_relations`, `soft_delete_usage_blockers`, parent fields, and child blockers provide behavior.

This is already close to model-driven through `register_entity_delete_restore`. The missing step is discovery: the entity spec should declare lifecycle participation, and the registrar should mount it.

### Edit History and Sources

These endpoints are already naturally model-agnostic:

- `GET /api/pages/edit-history/{entity_type}/{path:public_id}/`
- `GET /api/pages/sources/{entity_type}/{path:public_id}/`

They should be available for every entity that satisfies the required contracts (`CatalogModel` / `ClaimControlledModel` / `LinkableModel`). No per-entity declaration should be needed unless an entity explicitly opts out, and opt-out should be rare enough to require a comment and test.

## Startup checks

The spec should be validated during Django system checks, not at first request.

Checks:

- every `CatalogModel` either has a valid `catalog_api` spec or is listed in a temporary migration allowlist
- every declared schema is a Ninja `Schema`
- queryset builders return a queryset for the declared model
- serializers accept the declared model type and return the declared schema type where this can be checked
- declared fields resolve through `_meta`
- declared parent fields resolve through `_meta` and target the expected model
- no two models mount the same collection prefix or page detail route
- generated route set matches the expected entity registry

The migration allowlist is intentionally temporary. Every entry should name the missing capability and the doc/issue that removes it.

## Tests

Backend:

- registry discovery walks `CatalogModel` subclasses and builds one route set per declared spec
- every entity in the registry has list/detail/claims/lifecycle routes when its spec says it should
- generic detail lookup uses `public_id_field`, including multi-segment `Location.location_path`
- generic claim patch writes user `ChangeSet` rows with `action=edit`
- generic create writes user `ChangeSet` rows with `action=create`
- generic lifecycle routes use the shared soft-delete machinery
- edit-history and sources work for every claim-controlled catalog entity
- no per-entity API router owns a route that the model-driven registrar owns

Frontend / generated API:

- `make codegen` emits stable route types for generated endpoints
- catalog metadata parity tests fail when an entity has backend API capability but no matching frontend route handling
- dynamic frontend pages consume `(entity_type, public_id)` instead of per-entity loader files where possible

## Migration plan

This should land incrementally. Do not try to replace every route family in one PR.

1. Define `CatalogApiSpec` and endpoint spec classes with startup validation.
2. Move detail-page registrations from `page_endpoints.py` into model-owned detail specs, still using `register_entity_detail_page` underneath.
3. Move lifecycle registrations into model-owned lifecycle specs, still using `register_entity_delete_restore` underneath.
4. Add the generic claim-patch registrar for scalar-only entities, then extend it with planner hooks for aliases / parents / relationship groups.
5. Move create registrations into model-owned create specs once the Location create hooks have proved the shape.
6. Collapse list endpoints last. Lists have the most presentation-specific behavior and should move only after the detail/write path is stable.
7. Remove per-entity routers whose remaining endpoints are all covered by the registrar.
8. Replace temporary allowlists with parity tests.

Suggested first proof:

- Pick a simple taxonomy entity with a normal slug, scalar fields, and shared lifecycle behavior.
- Move only its detail-page and lifecycle route ownership to `CatalogApiSpec`.
- Keep the wire URLs identical.
- Prove `make codegen` produces no consumer-facing route churn beyond operation names.

Suggested steel thread:

- After the simple entity, move `Location` detail and lifecycle. That proves `public_id_field` and `{path:public_id}` are not slug-shaped assumptions.

## Relationship to frontend route consolidation

This doc is backend/API route ownership. It enables frontend route consolidation but does not replace those plans.

[ModelDrivenDeletePage.md](ModelDrivenDeletePage.md) is the frontend delete-page slice: one dynamic SvelteKit page driven by catalog metadata. The same pattern should later apply to frontend edit-history and sources pages.

The backend and frontend should converge on the same identity tuple:

```text
(entity_type, public_id)
```

The collection route segment (`entity_type_plural`) is derived metadata, not a second independent identity.

## Out of scope

- Replacing Django models with a DSL.
- Generating Django models.
- Forcing all detail/list responses into one universal schema.
- Removing genuinely custom query/serialization behavior.
- Solving frontend editor section registration. That is related, but it is a separate UI metadata axis.

## Acceptance criteria

- Adding a simple catalog entity requires no new route decorators.
- A new entity's list/detail/claims/create/lifecycle participation is declared on the model or a model-owned spec.
- Edit-history and sources are automatic for every eligible catalog entity.
- Per-entity API modules contain behavior hooks only; route registration lives in shared infrastructure.
- Startup checks catch malformed endpoint specs before the first request.
- Parity tests fail when a model declares API participation but the route registry or generated frontend metadata does not reflect it.
