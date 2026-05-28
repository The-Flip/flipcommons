# Model-Driven Linkability

> **Status: DONE** — main body landed; only [§Follow-ups](#follow-ups) remain. Location proved the abstraction via [LocationCrud.md](LocationCrud.md).

## Context

### The Ultimate Goal

This doc is one facet of the broader goal described in [ModelDrivenMetadata.md](ModelDrivenMetadata.md): make the system as model-agnostic as possible. We do that by encoding what varies between models on the models themselves and reading it generically from shared infrastructure.

### Sub-goal: Generic Linkability

For all the catalog models that are URL-addressable, we want that capability to be handled generically. Right now this is partly accomplished via `LinkableModel`: if the model has a slug that's unique within that entity type, it works. The problem is that `LinkableModel` does NOT currently work for `Location`, which is only unique within its parent Location.

This doc outlines an architecture that will support a `LinkableModel` that works for ALL URL-addressable models.

The follow-on implementation plan is [LocationCrud.md](LocationCrud.md). It should land after this work and serves as the proof that the abstraction held: Location must be able to use `register_entity_create` and `register_entity_delete_restore` and the generic edit-history / sources page endpoints while reserving bespoke code only for true hierarchy semantics.

## The Contracts

- **[`LinkableModel`](#linkablemodel)**: declares URL identity.

### Deferred: re-parenting protection

In a fully-baked design, Location's `parent` field would be frozen via `ClaimControlledModel.immutable_after_create` (see [ModelDrivenImmutableAfterCreate.md](ModelDrivenImmutableAfterCreate.md)) — re-parenting would invalidate the materialized `location_path` on the row and every descendant. We are landing this plan _before_ `immutable_after_create` exists. The interim workaround: the Location editing UI simply omits the `NameEditor` (and any other parent-mutating control) when it ships. This is not a long-term fix — once `immutable_after_create` lands, drop the UI workaround and freeze `parent` at the model layer.

## LinkableModel

A linkable catalog model inherits `LinkableModel` and declares three ClassVars:

- `entity_type: ClassVar[str]` — the singular entity-type token (e.g. `"theme"`, `"location"`).
- `entity_type_plural: ClassVar[str]` — the URL-segment plural (e.g. `"themes"`, `"locations"`).
- `public_id_field: ClassVar[str] = "slug"` — the name of the field that carries URL identity. Defaults to `"slug"` so existing models declare nothing. Location overrides to `"location_path"`.

`LinkableModel` provides, for free:

- `public_id` — `@property` returning `getattr(self, self.public_id_field)`.
- `get_absolute_url()` — formats `link_url_pattern` with `{public_id}`.
- `link_url_pattern` — derived in `__init_subclass__` as `/{entity_type_plural}/{{public_id}}`. Today the same hook hardcodes `{{slug}}` ([`apps/core/models.py:331`](../../../backend/apps/core/models.py#L331)); flipping that placeholder to `{{public_id}}` is the one-line change at the heart of this plan. Pre-launch — we are not preserving the old `{slug}` placeholder anywhere.

This is a [base class / mixin](ModelDrivenMetadata.md#pattern-base-class--mixin) — discovery is `LinkableModel.__subclasses__()`, no hand-maintained registry of who participates.

Location is currently `LifecycleStatusModel, ClaimControlledModel` only ([`apps/catalog/models/location.py:23`](../../../backend/apps/catalog/models/location.py#L23)) — adding `LinkableModel` to its bases (with `entity_type = "location"`, `entity_type_plural = "locations"`, `public_id_field = "location_path"`) is part of this plan.

Wikilink-picker presentation (label, sort order, autocomplete config) is a separate, opt-in capability layered on top of `LinkableModel` — see [ModelDrivenWikilinkableMetadata.md](ModelDrivenWikilinkableMetadata.md). A `LinkableModel` subclass that doesn't mix in `WikilinkableModel` simply doesn't appear in the wikilink picker.

## `public_id` is a presentation alias, not a stored column

`public_id` is **not a new field** and **not claim-controlled**. It's a computed alias over whichever field already carries URL identity for that model:

- Most models: `public_id` resolves to `self.slug`.
- Location: `public_id` resolves to `self.location_path` — already materialized on the row because Location's slug is only unique within its parent, so the path-encoded form is what's globally unique.

Consequences:

- No new migrations, no denormalization, no slug↔public_id sync logic.
- The underlying field keeps whatever claim-control status it already has. `slug` stays claim-controlled; `location_path` stays claims-exempt (it's derived from `parent` + `slug` at create time).
- A model whose URL identity is multi-segment plugs in by materializing the path into a single `unique=True` field and pointing `public_id_field` at it. The linkability layer doesn't know or care about segment count.

## URL convention

Every LinkableModel-aware route uses Django's `:path` converter and the uniform param name `public_id`:

- Page-level provenance: `/api/pages/edit-history/{entity_type}/{path:public_id}/`, `/api/pages/sources/{entity_type}/{path:public_id}/`
- Per-entity write: `PATCH /api/{plural}/{path:public_id}/claims/`, `DELETE /api/{plural}/{path:public_id}/`, `POST /api/{plural}/{path:public_id}/restore/`
- Parented create: `POST /api/{plural}/{path:parent_public_id}/children/`

Ninja's curly-brace converter syntax is `{converter:name}` (converter first, then name) — the inverse of Django's `<converter:name>`. So `{path:public_id}` in Ninja, not `{public_id:path}`.

The `:path` converter matches single-segment ids without ceremony, so existing single-segment entities aren't affected. It also widens to multi-segment automatically — `/api/pages/edit-history/location/usa/il/chicago/` resolves the same way `/api/pages/edit-history/theme/sci-fi/` does.

A widened route must 404 cleanly when a single-segment model is hit with extra segments (the lookup misses), not 500. Concrete test: `GET /api/pages/edit-history/theme/sci-fi/extra/` returns 404 — same `get_object_or_404` path that any unknown-id request hits — never 500.

## Backend call sites to migrate

Pre-launch: every site that today binds a `{slug}` URL or does a `slug=`-keyed lookup against a `LinkableModel` flips to `{path:public_id}` / `**{model.public_id_field: public_id}`. No backwards-compat — the old shape is removed in the same change.

**Routes that bind `{slug}` (rename URL param to `{public_id}` and use the `:path` converter where the parser supports it):**

- [`apps/provenance/page_endpoints.py:112`](../../../backend/apps/provenance/page_endpoints.py#L112) — `/edit-history/{entity_type}/{slug}/`
- [`apps/provenance/page_endpoints.py:136`](../../../backend/apps/provenance/page_endpoints.py#L136) — `/sources/{entity_type}/{slug}/`
- [`apps/catalog/api/entity_crud.py:132,194,237,364`](../../../backend/apps/catalog/api/entity_crud.py#L132) — `{slug}/delete-preview/`, `{slug}/delete/`, `{slug}/restore/`, `{parent_slug}/<route_suffix>/`
- [`apps/catalog/api/themes.py:139`](../../../backend/apps/catalog/api/themes.py#L139), [`systems.py:217`](../../../backend/apps/catalog/api/systems.py#L217), [`series.py:162`](../../../backend/apps/catalog/api/series.py#L162), [`machine_models.py:939,1026,1048,1095`](../../../backend/apps/catalog/api/machine_models.py#L939) — per-entity `{slug}/claims/` and bespoke delete/restore mounts
- Per-entity page endpoints in [`apps/catalog/api/page_endpoints.py`](../../../backend/apps/catalog/api/page_endpoints.py) (multiple `slug=slug` lookups, lines 106–137+)

**Lookup sites (flip `slug=slug` / `slug=value` to `**{model.public_id_field: ...}`):\*\*

- All `get_object_or_404(..., slug=slug)` and `.objects.filter(slug=slug)` calls in the catalog API package (entity_crud, themes, systems, series, corporate_entities, franchises, machine_models, people, page_endpoints)
- [`apps/media/api.py:115`](../../../backend/apps/media/api.py#L115) — `_resolve_entity` does `model_class._default_manager.filter(slug=slug)`; rename the `slug` arg to `public_id` and look up via `public_id_field`
- [`apps/provenance/api.py:63`](../../../backend/apps/provenance/api.py#L63) — Title-specific `Title.objects.get(slug=value)` (Title's `public_id_field` is `slug`, so semantics don't change; switch to the generic form for consistency)

**Wikilink rendering:**

- [`apps/core/markdown_links.py:96`](../../../backend/apps/core/markdown_links.py#L96) — comment + `url_pattern` consumer; verify the `{slug}` → `{public_id}` flip flows through the wikilink resolver and update [`apps/core/tests/test_markdown_links.py:82,87`](../../../backend/apps/core/tests/test_markdown_links.py#L82).

## Frontend call-sites to migrate

Run `make codegen` first — `schema.d.ts` regenerates with the new param name (`public_id`) on every migrated route, and the TypeScript compiler surfaces the call sites. Triage upfront, because the surface splits into two categories that want different treatment:

- **Mechanical (bulk)**: typed-client invocations whose path template or `params.path` destructure named the URL param `slug`. The fix is the literal find-and-replace `'{slug}' → '{path:public_id}'` (or `'{public_id}'` for non-path single-segment) plus rename of the destructure. One pattern, no judgment.
- **Per-site judgment (review each)**: UI strings, comments, form-field names, and error messages where `slug` was being used as a domain concept rather than as the API param name. Mechanical replace here silently breaks copy that should stay "slug" for slug-keyed entities, or change to "URL path" for Location.

Concrete mechanical sites (~30 — exact count after regen):

- ~22 SvelteKit per-entity detail loaders: [`src/routes/<entity>/[slug]/+layout.server.ts`](../../../frontend/src/routes/) — each calls `client.GET('/api/pages/<entity>/{slug}', { params: { path: { slug }}})`. Flip both occurrences. (The route-directory name `[slug]` itself is a separate decision — see Per-site below.)
- [`src/lib/provenance-loaders.ts:23,36`](../../../frontend/src/lib/provenance-loaders.ts#L23) — edit-history and sources loaders using `'/api/pages/edit-history/{entity_type}/{slug}/'`.
- [`src/lib/delete-flow.ts:39,50`](../../../frontend/src/lib/delete-flow.ts#L39) and its test — `type DeleteEndpoint = '/api/${string}/{slug}/delete/'` template-literal type and the `client.POST` call.
- [`src/lib/components/editors/save-title-claims.ts:21`](../../../frontend/src/lib/components/editors/save-title-claims.ts#L21) and the shared `saveSimpleTaxonomyClaims` callers in `save-claims-shared.test.ts`.
- Media-upload typed-client wrappers in `src/lib/media-upload.svelte.ts` (and the multipart form-field name `slug` if the form is hand-built rather than typed-client-driven — verify).

Per-site judgment sites:

- **SvelteKit `[slug]` route directory names** (`src/routes/titles/[slug]/`, `src/routes/manufacturers/[slug]/`, etc.): the URL param's name in SvelteKit is independent of the API param name. Renaming `[slug]` → `[public_id]` would change the route segment seen by `$page.params` and any cross-references. Likely keep `[slug]` for slug-keyed entities (the value still IS a slug) and accept the small naming dissonance with the backend's `public_id`. Location already uses `[...path]`, which is correct.
- **Wikilink builder UI**: any picker that renders "Insert a slug" / "Find by slug" copy should consider the Location case (path-shaped id) when the picker is open on Location.
- **Form labels and error messages**: "URL slug" labels on create/edit forms — keep where the field is genuinely a slug; reword for Location forms once they ship in [LocationCrud.md](LocationCrud.md).

## Startup enforcement

`apps.core.checks` walks `LinkableModel.__subclasses__()` at boot and verifies, for each subclass:

- `entity_type` and `entity_type_plural` are declared, non-empty strings.
- `entity_type` and `entity_type_plural` are unique across all `LinkableModel` subclasses (no two models claim the same URL segment or registry key).
- `public_id_field` resolves to a real field on the model with `unique=True`.

Missing declarations, typos, collisions, or non-unique target fields fail `manage.py check` — not at first request. New linkable models inherit the check by virtue of subclassing.

This is the [base class / mixin + startup check](ModelDrivenMetadata.md#pattern-base-class--mixin) pattern: the model class itself is the contract, and the contract is enforced before any request lands.

## The generic write surface

The shared write factories — `register_entity_create` and `register_entity_delete_restore` (which mounts delete-preview, delete, and restore) at [`apps/catalog/api/entity_crud.py`](../../../backend/apps/catalog/api/entity_crud.py) — must be model-agnostic against the linkability contract. Concretely:

- **Lookups go through `public_id_field`**, not a hardcoded `slug` kwarg. Today the factory and every per-entity router uses `slug=slug` (e.g. [`entity_crud.py:106,143,210,232,350,359`](../../../backend/apps/catalog/api/entity_crud.py#L106), `themes.py:151`, `systems.py:226`, `series.py:171`, `corporate_entities.py:177`, `franchises.py:128`, `machine_models.py:1071,1117`, `people.py:304,419,458,521`). All flip to `**{model_cls.public_id_field: public_id}`.
- **FK claim values respect `claim_fk_lookups`**. The ClassVar already exists on `ClaimControlledModel` ([`apps/provenance/models/base.py:50`](../../../backend/apps/provenance/models/base.py#L50)) and Location already declares `{"parent": "location_path"}` ([`apps/catalog/models/location.py:36`](../../../backend/apps/catalog/models/location.py#L36)) — the resolve and provenance-validation paths already honor it. The remaining gap is `register_entity_create` at [`entity_crud.py:339`](../../../backend/apps/catalog/api/entity_crud.py#L339), which hardcodes `parent.slug`. Replace with `getattr(parent, model_cls.claim_fk_lookups.get(parent_field, "slug"))`. Hardcoding `parent.slug` anywhere in the write path is a [field-on-model antipattern](ModelDrivenMetadata.md#antipattern-field-on-model) waiting to happen.
- **Extension hooks** (new in this plan) let models with derived fields plug in without forking the factory:
  - `extra_claim_specs_builder(data, parent) -> list[ClaimSpec]` — additional claims (Location: `location_type`, `divisions`).
  - `extra_row_kwargs_builder(data, parent) -> dict` — non-claim row kwargs computed from input (Location: `location_path`).
  - `body_schema` — alternate Pydantic schema for endpoints that accept extra fields.

Bespoke handlers are acceptable only where semantics genuinely differ from the linkability contract. Location's delete-preview subtree walk and DELETE cascade are hierarchy semantics, not linkability gaps.

## Acceptance criterion: zero model-specific overrides

The headline test for this work: a new linkable model reaches create / delete-preview / delete / restore through the shared factories, and edit-history / sources through the shared page endpoints, with **zero model-specific overrides** beyond the ClassVar declarations (`entity_type`, `entity_type_plural`, `public_id_field`, optional `claim_fk_lookups`, optional extension-hook callables).

If a new model can't, the factory or endpoint has a gap and _that_ gets fixed — not the model. Location is the proving ground: if Location requires bespoke create/restore/delete-preview/edit-history/sources code for anything other than true hierarchy semantics (subtree walks, cascade), the abstraction has failed and the plan is not done.

### Concrete acceptance tests

The "zero overrides" criterion lands as enforceable tests, not prose:

1. **Discovery test** — iterate `LinkableModel.__subclasses__()`. For each subclass, assert there is no per-entity router file declaring its own `{slug}/claims/`, `{slug}/delete/`, `{slug}/restore/`, or `{slug}/delete-preview/` route. The only legal sources for those routes are `register_entity_create` and `register_entity_delete_restore`. Implementation: inspect the entity's mounted Ninja router and check that the path operations for those suffixes resolve to the shared factory's inner functions (compare `__qualname__` or `__module__`). New entity = new test row, automatic.
2. **Round-trip test for Location** — once Location is wired as `LinkableModel`, a single parametrized test creates / fetches / soft-deletes / restores / reads edit-history / reads sources for a Location through the generic endpoints. Same test body that already runs for Theme/System/Series, just with a path-shaped `public_id`. If anything fails, the factory has a hole.
3. **Path-converter widening test** — `GET /api/pages/edit-history/theme/sci-fi/extra/` returns 404 (not 500). Same for `/api/pages/sources/`. Asserts that a single-segment model hit with extra segments misses cleanly via `get_object_or_404`. Trailing-slash and empty-segment variants covered in the same test.
4. **Startup-check test** — instantiate a deliberately broken `LinkableModel` subclass (missing `entity_type_plural`, or `public_id_field` pointing at a non-`unique=True` column) and assert `apps.core.checks` raises during `manage.py check`. Mirrors the existing `__init_subclass__` test for `entity_type`/`entity_type_plural`.

## The generic read/provenance surface

`/api/pages/edit-history/{entity_type}/{path:public_id}/` and `/api/pages/sources/{entity_type}/{path:public_id}/` resolve the entity via `get_linkable_model(entity_type)` + `get_object_or_404(model, **{model.public_id_field: public_id})`. No per-model branches, no per-model endpoint files.

The same shape applies to any future page-level endpoint that takes an entity reference: keyed on `(entity_type, public_id)`, dispatched through the registry, looked up via `public_id_field`.

## Follow-ups

### Add write-factory extension hooks (in [LocationCrud.md](LocationCrud.md))

`register_entity_create` is currently slug-shaped: it calls `validate_slug_format`, `assert_slug_available`, and writes `row_kwargs={"slug": slug}` plus a `slug` `ClaimSpec` unconditionally. That's fine for every shipped model (all default `public_id_field = "slug"`), but Location can't plug in until the factory grows three keyword-only hooks:

- `extra_claim_specs_builder(data, parent) -> list[ClaimSpec]` — additional claims (Location: `location_type`, `divisions`).
- `extra_row_kwargs_builder(data, parent) -> dict` — non-claim row kwargs computed from input (Location: `location_path`).
- `body_schema` — alternate Pydantic schema for endpoints that accept extra fields.

Deferred to [LocationCrud.md](LocationCrud.md) because Location is the first caller that needs them — landing the hooks in this PR with no caller is dead code. The acceptance criterion above already lists them as the optional ClassVar/callable surface, so the contract holds; only the factory plumbing is deferred.

### Retype the entity registry as `type[CatalogModel]`

Once Location lands as a `LinkableModel` it also satisfies `CatalogModel` by composition (it already has `LifecycleStatusModel + ClaimControlledModel`). At that point the registry walked by `get_linkable_model` is, in fact, a `CatalogModel` registry — every entry is linkable _and_ claim-controlled _and_ status-tracked.

That makes a typing cleanup possible:

- Walk `CatalogModel.__subclasses__()` rather than `LinkableModel.__subclasses__()`.
- Return `type[CatalogModel]` and rename to match (`get_entity_model` or `get_catalog_model`).
- Delete the `issubclass(model_class, ClaimControlledModel)` guard at [`backend/config/api.py:196`](../../../backend/config/api.py#L196) — `type[CatalogModel]` is already a `type[ClaimControlledModel]`.
- Leave `LinkableModel` as a pure structural contract (no registry, no `__subclasses__()` walk), so a future linkable-but-not-CCM model can still adopt it independently.

### Migrate System's bespoke create handler off hardcoded `slug=slug`

[`apps/catalog/api/systems.py:327`](../../../backend/apps/catalog/api/systems.py#L327) does `get_object_or_404(_system_detail_qs(), slug=slug)` inside System's bespoke create handler. System's `public_id_field == "slug"` so the call is correct today, but the lookup hardcodes the field name rather than reading it from the model — exactly the [field-on-model antipattern](ModelDrivenMetadata.md#antipattern-field-on-model) §"The generic write surface" warns about ("Hardcoding `parent.slug` anywhere in the write path is a field-on-model antipattern waiting to happen").

The acceptance criterion only constrains entities reaching the shared factories; System's hand-written create is grandfathered, so this isn't a Linkability blocker. But it's a latent footgun: if System ever overrides `public_id_field`, or if this handler is copied as a template for a non-slug-keyed model, the lookup silently misses.

Two options:

1. **Cheap fix in place**: replace `slug=slug` with `**{System.public_id_field: slug}` (or the slug-named local variable). One-line change, removes the hardcoded reference, no behavior change today.
2. **Migrate System onto `register_entity_create`**: the right long-term shape — System's bespoke handler exists because the factory didn't support `extra_create_fields_builder` when it was written; that gap closed in [LocationCrud.md](LocationCrud.md). System could fold in alongside Location with the same hooks.

Option (2) is the real fix; option (1) is the holdover for as long as System keeps the bespoke handler. Worth doing one or the other before the next non-slug-keyed `LinkableModel` arrives — at that point, copy-paste from System's handler becomes a real risk.

### Drop the duplicate `entity_type` raise in `get_linkable_model._build_map`

The new system check ([`apps/core/checks.py:check_linkable_models`](../../../backend/apps/core/checks.py)) covers duplicate-`entity_type` detection earlier (at boot, with structured `Error` reporting) than the lazy `ImproperlyConfigured` in [`apps/core/entity_types.py:_build_map`](../../../backend/apps/core/entity_types.py#L40). Two error paths for the same invariant. Keep both for defense in depth, or drop the lazy one — minor judgment call, easy to do after this PR lands.

### Move `detachMedia` and `setPrimary` onto the typed client

[`frontend/src/lib/api/media-api.ts`](../../../frontend/src/lib/api/media-api.ts) is hand-written. `uploadMedia` has to be — it uses XMLHttpRequest for upload-progress events, which the typed client (openapi-fetch, fetch-based) can't expose. But `detachMedia` and `setPrimary` are plain `POST` with a JSON body and a 204/422 response — exactly the shape the typed client handles. They were written hand-rolled for symmetry with `uploadMedia`, and that symmetry is load-bearing wrong: it shielded both from the regen sweep when `slug` → `public_id` flipped, producing a P1 wire-format bug that compile-time type-checking would have caught immediately had they used the typed client.

Actions:

- Search for other hand-written clients
- Rewrite `detachMedia` and `setPrimary` on top of `client.POST('/api/media/detach/', ...)` / `client.POST('/api/media/set-primary/', ...)`.
- Leave `uploadMedia` hand-rolled (XHR is genuinely required); optionally tighten its multipart keys against `paths['/api/media/upload/']['post']['requestBody']['content']['multipart/form-data']` to schema-check the form keys without giving up XHR progress.

### Compress per-entity `+layout.server.ts` loaders

22 files in `frontend/src/routes/<entity>/[slug]/+layout.server.ts` are nearly identical:

```ts
const { data, response } = await client.GET('/api/pages/<entity>/{public_id}', {
  params: { path: { public_id: params.slug } },
});
if (!data) throw error(response.status, ...);
return { ... };
```

The backend already made these endpoints model-agnostic via `register_entity_detail_page`; the frontend hasn't caught up. Mirror the existing `loadEditHistory` / `loadSources` helpers in [`$lib/provenance-loaders.ts`](../../../frontend/src/lib/provenance-loaders.ts) with a `loadCatalogDetail<E extends CatalogEntityKey>(event, key)` so each per-entity loader collapses to one line. Same shape, same ergonomics, same tests.

### Generate `[slug]/edit-history/` and `[slug]/sources/` boilerplate

Each linkable entity must have these two subroutes ([`catalog-meta.test.ts`](../../../frontend/src/lib/api/catalog-meta.test.ts) enforces it). 19 entities × 2 subroutes × 2 files (`+page.server.ts` + `+page.svelte`) = ~76 files of pure boilerplate, varying only by entity-type string. The test's own comment acknowledges the cost: _"~10 lines of boilerplate per entity; the cost of forgetting is an invisible UX gap."_

Two options worth weighing:

- **Code-gen** alongside `make codegen` — emit the wrapper files from `CATALOG_META`. Aligns with how `model-meta.ts` is already generated. Adds a generator to maintain.
- **Lift the load into a shared `+layout.server.ts`** — the entity layout already runs `loadEntityDetail`; have it expose `loadEditHistory` / `loadSources` lazily so the subroute pages become a single `+page.svelte` referencing parent-layout data. Hits the SvelteKit caveat the existing test comment notes (parent-layout re-runs on subroute navigation), so this needs validation.

### Rename JS-side `slug` parameter to `publicId`

Holdover from before the `{slug}` → `{public_id}` URL flip in c51bb3ca3. Several JS-side names still call the URL identifier `slug`, even though it carries `public_id` on the wire and is named `public_id_field` on the model. The route directory `[slug]` stays — the plan's per-site judgment list ([§Frontend call-sites to migrate](#frontend-call-sites-to-migrate)) keeps it because the value still IS a slug for shipped entities. The misalignment is only on the JS-side names.

Surfaces to rename:

- [`loadDeletePreview`](../../../frontend/src/lib/delete-preview-loader.ts) options: `slug` → `publicId`. Returned shape `{ preview, slug }` → `{ preview, publicId }`.
- [`createDeleteSubmitter`](../../../frontend/src/lib/delete-flow.ts) returned `submit(slug, opts)` first arg → `publicId`.
- 19 `+page.ts` files: `slug: params.slug` → `publicId: params.slug` (`params.slug` stays — directory is `[slug]`).
- 19 `+page@.svelte` files: `let { preview, slug } = $derived(data)` → `publicId`, propagated to `submit(...)` calls and any `[slug]` props passed to `DeletePage`.
- [`DeletePage.svelte`](../../../frontend/src/lib/components/DeletePage.svelte) `slug` prop → `publicId`.
- Tests for both modules.

Mechanical sweep on the JS-side names; SvelteKit-side names stay.

### Type `LinkTypeSchema.flow` as a `Literal` union on the backend

`LinkTypeSchema.flow` is typed `str` in the Pydantic schema, so the generated `schema.d.ts` shape is `flow: string`. The wikilink picker only ever reads `'standard'` or `'custom'` (see [`WikilinkAutocomplete.svelte:91`](../../../frontend/src/lib/components/form/WikilinkAutocomplete.svelte#L91) — `lt.flow === 'custom'`), and the hand-written `LinkType` shape we just deleted narrowed it to `'standard' | 'custom'`. Switch the backend field to `Literal['standard', 'custom']` (or whatever the canonical set is) so the generated type carries the narrowing and frontend exhaustiveness checks become possible.

### Tighten `parseApiError` to accept the schema error union

[`parse-api-error.ts:21`](../../../frontend/src/lib/api/parse-api-error.ts#L21) takes `error: unknown` and re-discriminates the body by runtime shape checks (`'detail' in error`, `typeof detail === 'string'`, …). Every typed-client caller already has `error` narrowed to the declared error-response union (`ErrorDetailSchema | ValidationErrorSchema` for most endpoints), so the `unknown` parameter widens the type away and forces the function to redo work the type system already did.

Replace the parameter type with the schema union (or a discriminated union derived from it) so the runtime checks become exhaustiveness checks against the schema, not shape-sniffing. Touches every save/delete/create flow that calls `parseApiError`, so size it as its own PR rather than bundling.

### Normalize parent-segment naming in nested-create routes

Three nested-create routes use three different parent param names:

- `/api/manufacturers/{parent_public_id}/corporate-entities/`
- `/api/display-types/{parent_public_id}/subtypes/`
- `/api/technology-generations/{parent_public_id}/subgenerations/`
- `/api/titles/{title_public_id}/models/` ← outlier

Pick one convention (`{parent_public_id}` is the obvious default; `{title_public_id}` reads nicely but is one-off) and align. Same-PR fix when next touching the create-route surface.
