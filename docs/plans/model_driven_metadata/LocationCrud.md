# Location CRUD

This plan implements Location create, edit, delete, restore, edit-history, sources, and frontend routes. It will be the first full multi-segment `LinkableModel` CRUD surface, and prove out the changes.

## Context

This is the second of three sequential plans in the Location-promotion chain:

1. The Location → `CatalogModel` promotion + walk collapse (the small structural prep). - DONE
2. **This plan** — the full Location CRUD surface (write router, frontend, tests).
3. [ModelDrivenWikilinkableMetadata.md](ModelDrivenWikilinkableMetadata.md) — the wikilink picker mixin (Location stays out by absent inheritance).

## Status (as of last handoff)

Foundations + the entire backend write surface are committed on this branch. The next session picks up at the **frontend write routes**. The following are done:

- `backend/apps/catalog/services/location_paths.py` exists with `compute_location_path`, `derive_child_location_type`, and `lookup_child_division`. `derive_child_location_type` raises `StructuredValidationError(form_errors=[...])` directly; Ninja's existing 422 handler converts it. See §"Path and type helpers" for why no domain exception / no `try_*` variant.
- `Location` model carries `soft_delete_usage_blockers = frozenset({"corporate_entities"})` and the `corporate_entities` M2M with `through="CorporateEntityLocation"` and `related_name="+"`. Migration `0008_location_corporate_entities` is generated and applied (no-op on Postgres, identity-preserving table-rebuild on SQLite — see §"Migration sanity check").
- `LocationDetailSchema` has `expected_child_type: str | None = None`. The read serializer in `locations.py` derives it from the cached tree (`_LocationNode.divisions`) via `lookup_child_division`. Empty-path root returns `"country"`. Backend tests pinning all five cases live in `TestExpectedChildType` in `test_api_locations.py`.
- **Read-route consolidation**: `locations.py` collapsed five hand-fanout routes into two (`/` + `/{path:location_path}`). Frontend `+layout.server.ts` collapsed from 5-way segment dispatch to a single `path === ''` branch.
- **`public_id_form_field` override**: `Location.public_id_form_field = "slug"`. `assert_public_id_available` keys errors under the form field with the form value; `create_entity_with_claims`'s `IntegrityError` fallback honors the same override.
- `_AliasEntity` union in `apps.catalog.api.edit_claims` includes `Location`.
- Frontend `newChildLabel` rewritten to prefer existing children's `location_type`, fall back to `profile.expected_child_type`, return `null` otherwise. `EXPECTED_CHILD` deleted; `location-helpers.test.ts` asserts the server-driven path.
- **Walker audit done.** `apps/catalog/api/soft_delete.py` `_record` already dedups by `(entity_key, relation)` — no `.distinct()` needed. The "CE linked twice via two CELs" scenario is DB-impossible (`catalog_corporateentitylocation_unique_pair`), so the proposed dedup test was deleted as dead weight. See §"Tests" for the walker note.
- **Backend write router shipped.** `backend/apps/catalog/api/locations_write.py` carries:
  - `POST /api/locations/` (top-level country create) — `LocationTopLevelCreateSchema` with required `divisions`.
  - `POST /api/locations/{parent_public_id}/children/` (child create) — `LocationChildCreateSchema`; server derives `location_type`. Uses the new `op_id_suffix="_child"` factory kwarg to avoid colliding with the top-level route's `location_create` op_id.
  - `PATCH /api/locations/{public_id}/claims/` — single `LocationPatchClaimSchema` with `extra=forbid`. Handler rejects `parent`/`slug`/`location_type` in `data.fields` and rejects top-level `divisions` when `loc.location_type != "country"`. See §"PATCH claims" for why this is one schema, not two.
  - Delete / preview / restore via `register_entity_delete_restore` with `parent_field="parent"`, `child_related_name="children"`.
- **Factory addition.** `register_entity_create` gained an `op_id_suffix: str = ""` kwarg — Location's child-create call is the only caller; every other entity keeps its stable `{entity}_create` op_id byte-identical. See §"Create-factory hooks".
- **Schema-boundary test amended.** `test_openapi_changeset_input_consolidation` now allows components with `additionalProperties: false` (i.e. `extra=forbid` tightenings) to share the `EntityCreateInputSchema` shape — `LocationChildCreateSchema` is the legitimate occupant of that carve-out.
- **Backend tests for create / PATCH / delete / restore live in `test_api_locations_write.py`** (44 cases). Helper unit tests for `compute_location_path` / `derive_child_location_type` / `lookup_child_division` are in the same file.

Remaining work (next session):

- Frontend write routes per §"Frontend": `/locations/new`, `/locations/[...path]/new`, `/edit`, `/edit/[section]`, `/edit-history`, `/sources`, `/delete`. Editor wiring (`location-edit-sections.ts`, `LocationEditorSwitch.svelte`, `save-location-claims.ts`). Drop `'location'` from `catalog-meta.test.ts` `DEFERRED_KEYS`.
- Frontend tests per §"Tests" minus the helper tests (already done): `saveLocationClaims` sends `public_id` not `slug`; delete page renders blocked + unblocked states; `catalog-meta.test.ts` parity for Location.
- `make codegen && make lint && make test`.

For reference, the cross-cutting prework was:

1. Backend: extension hooks on `register_entity_create` — see §"Create-factory hooks" below for the API Location uses.
2. Frontend: `client.ts` preserves slashes in `public_id` path params (decodes `%2F` → `/` in `URL.pathname` via the existing `onRequest` middleware). Invisible to callers; Location's multi-segment `public_id` reaches the server as `/api/locations/usa/il/chicago/…` automatically.
3. Frontend: `catalog-meta.test.ts` is segment-aware (`ROUTE_DIR_TO_KEY` carries `{ key, segment }`; both `[slug]` and `[...path]` are discovered). `'location'` remains in `DEFERRED_KEYS` and the Location PR drops it.
4. Shared delete / provenance / DeletePage layer was renamed `slug` → `public_id`. Location's wrappers pass `public_id={path}`.

Foundational work landed earlier in [ModelDrivenLinkability.md](ModelDrivenLinkability.md): generic URL identity and shared CRUD-factory contracts (`public_id_field`, `public_id`, `:path` route params, page-level edit-history / sources lookup by `(entity_type, public_id)`, and factory support for non-`slug` public IDs).

Location CRUD needs to be the proof that that work actually generalized. Location is the first model that needs a multi-segment `public_id` (`location_path`) and a non-`slug` FK claim lookup (`claim_fk_lookups = {"parent": "location_path"}`). If Location can reach create, restore, edit-history, and sources through the shared factories/endpoints without Location-specific overrides, the Linkability abstraction is doing real work.

The validation criterion:

- Location create uses `register_entity_create` for both top-level countries and child locations.
- Location delete, delete-preview, and restore use `register_entity_delete_restore`. Subtree cascade and active-CorporateEntityLocation blocking are driven by `soft_delete_cascade_relations` / `soft_delete_usage_blockers` class attributes — no bespoke delete handler.
- Location edit-history and sources use the generic `/api/pages/edit-history/{entity_type}/{public_id:path}/` and `/api/pages/sources/{entity_type}/{public_id:path}/` endpoints.
- The only Location-specific write code is the PATCH-claims route (no shared PATCH-claims factory yet).

## Decisions

- Location is a `CatalogModel` (post chain step 1) and declares `entity_type = "location"`, `entity_type_plural = "locations"`, `public_id_field = "location_path"`, `claim_fk_lookups = {"parent": "location_path"}`, and `claims_exempt = frozenset({"location_path"})` — `location_path` is a derived field written into `row_kwargs` at create time, not through a claim.
- **Re-parenting and slug-renaming are not supported.** `location_path` is computed from `parent.location_path + slug` and materialized on the row, so changing `parent` _or_ `slug` would invalidate the path on every descendant and every reference. The model-level enforcement (`immutable_after_create = frozenset({"parent", "slug"})`) is deferred per [ModelDrivenLinkability.md](ModelDrivenLinkability.md)'s "Deferred: re-parenting protection" section. **For this PR, the protection is UI- and route-level**:
  - The Location editor does **not** register `NameEditor` (which edits `name` + `slug` together) and provides no replacement: name editing is omitted from this PR. It returns once `NameEditor` learns to render name-only when slug is frozen (driven by `immutable_after_create` or an equivalent profile bit), at which point Location registers the same shared editor as every other entity.
  - **Do not ask the user whether to include name editing in this PR. The answer is NO. This decision is final and has been re-litigated enough.** Name editing arrives in the follow-up PR that teaches `NameEditor` name-only mode. Do not propose adding it here; do not propose blocking this PR on it; do not raise it as an open question.
  - The PATCH-claims route below explicitly rejects `parent`, `slug`, and `location_type` in the body.
  - When `immutable_after_create` lands later, drop both workarounds and let the model enforce.
- Top-level Location create always creates a `country`.
- Child Location create derives `location_type` from the country ancestor's `divisions`, using `country.divisions[parent_depth - 1]`.
- Name and slug are sibling-scoped at every tier, enforced at the DB by four partial `UniqueConstraint`s on `Location`: `catalog_location_unique_slug_per_parent` and `catalog_location_unique_name_per_parent` (for `parent IS NOT NULL`), and `catalog_location_unique_slug_at_root` and `catalog_location_unique_name_at_root` (for `parent IS NULL`). Name constraints use `Lower("name")`, so name uniqueness is case-insensitive. The sibling set is rows sharing the same `parent`, including the root tier where the siblings are all countries. The route does not need `scope_filter_builder` for either field — the DB is the source of truth; the route layer just surfaces violations as 422s instead of `IntegrityError`s.
- Universal catalog delete and cascade policy is described in [Cascade Rules](../../RecordLifecycle.md#cascade-rules).
- Location delete follows the universal catalog rule: **active direct child Locations block delete**, same as every other entity (Series, Manufacturer, etc.). Enforced by passing `child_related_name="children"` to `register_entity_delete_restore`. Practically: deleting a country requires walking the tree bottom-up, leaf-first.
- Location delete is **additionally** blocked by active `CorporateEntityLocation` rows on this Location. Enforced by listing `corporate_entities` (a new M2M through `CorporateEntityLocation`) in `Location.soft_delete_usage_blockers`; `manager.active()` filters by the CorporateEntity's status, matching Theme's existing pattern. The blocker is row-local (active CELs on _this_ row), not subtree-aggregated — descendants surface their own CEL blockers as the user walks down.
- Delete never cascades to descendants. There is no `soft_delete_cascade_relations` on Location. Soft-deletion is a status claim with provenance, not a structural cleanup, and cascading would silently soft-delete arbitrary numbers of rows under one user action.

## Backend

### Model setup

Add to `Location`:

```python
class Location(CatalogModel, TimeStampedModel):
    soft_delete_usage_blockers: ClassVar[frozenset[str]] = frozenset({"corporate_entities"})

    # Reverse accessor intentionally suppressed (`related_name="+"`); CorporateEntity
    # already reaches Location through `CorporateEntityLocation` directly.
    corporate_entities = models.ManyToManyField(
        "catalog.CorporateEntity",
        through="CorporateEntityLocation",
        related_name="+",
    )
```

The M2M is the join-table reverse manager Theme uses for `machine_models` — `location.corporate_entities.active()` resolves through `CorporateEntityLocation` and filters by the CE's status. The blocker is **row-local**: it returns only the CEs whose CELs point at _this_ Location row, not at descendants. That matches the row-local delete semantics in §"Decisions" — descendants surface their own CEL blockers as the user walks down the tree. No data migration is required (the through table already exists); only the Django-side relationship descriptor is added.

**Migration sanity check:** `makemigrations` will emit a state-only `AddField` migration for the M2M relationship descriptor. Because `through` is set, no schema change is needed. On Postgres `sqlmigrate` will be a true no-op; on SQLite the renderer emits a verbose table-rebuild (`CREATE TABLE new__catalog_location` → `INSERT … SELECT` → `DROP` → `RENAME`) because SQLite has no in-place `ALTER TABLE` support — that rebuild is identity-preserving and adds no new columns or join tables, so it's the expected SQLite behavior, not a sign that `through=` was lost. The real check is that no new join table (`catalog_location_corporate_entities`) is created and no new column is added to `catalog_location`. If either appears, regenerate the migration.

### Create-factory hooks

API available to Location's create routes on the shared factory at [`entity_crud.py`](../../../backend/apps/catalog/api/entity_crud.py):

- `body_schema: type[EntityCreateInputSchema] | None` — replaces the request body type. Subclass-checked at registration. Used by Location top-level (carries `divisions`) and child create.
- `extra_create_fields_builder: (data, parent) -> (row_kwargs, claim_specs)` — derived columns + matching claims, merged into the standard row/claim trio. One builder, not two, so callers derive shared values (e.g. `location_type`) once.
- `scope_filter_builder(data, parent) -> Q` — narrows the name-uniqueness scan. Now signature `(data, parent)` (was `(parent,)`); works in both parented and unparented modes (the parented-only gate was dropped). Used by Location for sibling/root scoping.
- `assert_public_id_available(model_cls, value, *, form_value=None)` (renamed from `assert_slug_available`) in [`entity_create.py`](../../../backend/apps/catalog/api/entity_create.py) — checks uniqueness on `model_cls.public_id_field`, surfaces collisions under `model_cls.public_id_form_field` (falling back to `public_id_field`). The factory passes `form_value=row_kwargs.get(form_field, public_id_value)` so the echoed error reads `"slug 'chicago'"` not `"slug 'usa/il/chicago'"`. For every shipped model both fields coincide on `slug`; Location's `public_id_form_field = "slug"` is the only override today.
- `validate_create_input(data, model_cls, *, scope_filter, include_deleted_name_check)` — composite primitive (name + slug validation + name uniqueness check) extracted from the factory. Available to any future outlier that needs a custom create handler instead of the factory.

The factory's docstring documents the **hooks discipline**: convergence-enforcement is the factory's value (every catalog create routes through one pipeline, so callers can't drift), so a single-caller hook is justified when the alternative is a parallel handler that copies 80%+ of the factory's pipeline. Hooks are NOT justified for hypothetical future callers. Structurally-different entities (different transactional shape, different side effects) should write a custom handler over the primitives instead of extending the factory. Each existing hook carries a "Callers: …" comment with a re-evaluation trigger when a second caller appears with a different extension pattern.

The factory's `scope_filter_builder` lambdas Location passes are temporary — see §"Follow-ups: Derive uniqueness scope from `model._meta.constraints`" for the model-driven replacement.

### Path and type helpers — DONE

`backend/apps/catalog/services/location_paths.py` exists with this shape:

```python
def compute_location_path(parent: Location | None, slug: str) -> str:
    return slug if parent is None else f"{parent.location_path}/{slug}"


def lookup_child_division(
    divisions: Sequence[str] | None, parent_depth: int
) -> str | None:
    """``divisions[parent_depth]`` if in range, else ``None``. Shared
    by the read serializer (wants ``None``) and ``derive_child_location_type``
    (raises on the same condition)."""
    ...


def derive_child_location_type(parent: Location) -> str:
    """Raises StructuredValidationError(form_errors=[...]) when divisions
    are missing or the tree is too deep."""
    ...
```

`derive_child_location_type` walks from `parent.location_path` to the country ancestor (`_country_ancestor`, with a 10-iteration safety break against malformed deep chains), then indexes the country's `divisions` by `parent.location_path.count("/")`. The user-facing messages are part of the contract — pin them in the test:

- No divisions declared: `"Country '{country.name}' has no divisions declared; cannot create child locations under it. Edit the country and add divisions first."`
- Tree too deep: `"Country '{country.name}' declares {len(divisions)} division level(s) ({', '.join(divisions)}); cannot create a level-{parent_depth + 1} child under '{parent.location_path}'."`

**Error shape:** `form_errors`, not `field_errors`. This is a structural problem with the parent's tree, not an error on a specific input field the user typed. Ninja's existing exception handler converts `StructuredValidationError` to a 422 with the body shape every other create route uses — the create builder does **not** need a try/except wrapper.

**Why no domain exception class:** YAGNI. There is exactly one caller (the child-create builder) and Ninja's 422 handler is exactly the integration we want. A domain exception would just add a translation step in the route plus a foot-gun (forgotten wrap → 500). If a non-API caller appears later — a CLI validator, an ingest checker — refactor to a domain exception then.

**Why no `try_derive_child_location_type` variant:** the read serializer derives `expected_child_type` from the cached tree directly (see §"Read API"), so there is no caller for a non-raising soft variant.

### Write router — DONE

Shipped in `backend/apps/catalog/api/locations_write.py`, registered under `/locations/`. The shape below documents the as-shipped routes; treat it as reference rather than a TODO.

Two sibling body schemas, both `extra=forbid`, so "client-supplied `location_type`" and "client-supplied `divisions` on child create" are rejected by schema validation before any handler code runs:

```python
class LocationTopLevelCreateSchema(EntityCreateInputSchema):
    divisions: list[str]  # required, non-empty, validated

class LocationChildCreateSchema(EntityCreateInputSchema):
    pass  # name, slug, note, citation only — server derives location_type
```

The OpenAPI split also gives the generated TS client a typed `divisions` field on `/locations/new` and not on `/locations/[...path]/new`, instead of one optional field on both forms.

Top-level create:

- Route: `POST /api/locations/`
- Factory: `register_entity_create`
- `public_id_field="location_path"`
- `body_schema=LocationTopLevelCreateSchema`
- `scope_filter_builder=lambda data, parent: Q(parent__isnull=True)` — pre-check is scoped to the country tier, matching the `parent IS NULL` partial UNIQUE constraints on `Location`. `parent` is `None` here.
- `extra_create_fields_builder` returns:
  - row kwargs: `location_type="country"`, `divisions=data.divisions`, `location_path=compute_location_path(None, data.slug)`
  - claims: `location_type="country"`, `divisions=data.divisions`

Child create:

- Route: `POST /api/locations/{parent_public_id:path}/children/`
- Factory: `register_entity_create` in parented mode
- `parent_field="parent"`
- `parent_model=Location`
- `route_suffix="children"`
- `body_schema=LocationChildCreateSchema` (may be omitted if identical to the factory default)
- `scope_filter_builder=lambda data, parent: Q(parent=parent)` — pre-check is scoped to siblings of the resolved `parent`, matching the `parent IS NOT NULL` partial UNIQUE constraints on `Location`. Both lambdas are temporary; see §"Follow-ups: Derive uniqueness scope from `model._meta.constraints`".
- `extra_create_fields_builder` returns (with `location_type = derive_child_location_type(parent)` computed once):
  - row kwargs: `location_type`, `location_path=compute_location_path(parent, data.slug)`
  - claims: `location_type`
- `derive_child_location_type` raises `StructuredValidationError(form_errors=[...])` on missing/exhausted divisions; Ninja's existing handler turns that into a 422 with no wrapping needed in the builder.

PATCH claims:

- Route: `PATCH /api/locations/{public_id:path}/claims/`
- Bespoke for now because there is no shared PATCH-claims factory.
- Body allows scalar edits for `name`, `description`, `short_name`, `code`, plus aliases, note, and citation.
- Single body schema (`LocationPatchClaimSchema`) with `extra=forbid`, accepting `fields`, `aliases`, `divisions`, plus `note`/`citation` from `ChangeSetInputSchema`. Field-level rejection lives in the handler:
  - `parent`, `slug`, `location_type` rejected when present in `data.fields` (immutable after create).
  - `divisions` rejected when present at the top level and `loc.location_type != "country"` (only meaningful on countries).
- Earlier drafts split this into two sibling schemas dispatched by `location_type` so `divisions` was schema-rejected. Implementation cost was high — Pydantic's union resolution silently bypasses `extra=forbid` when the first variant fails, forcing a permissive base + manual re-validate + custom Pydantic-error remapping. Handler-level rejection of one field for a row-tier reason matches how `parent`/`slug`/`location_type` are already handled, costs ~3 lines, and produces a clearer error message. The single-schema path is the canonical shape; schema-level dispatch is the deferred option if a stronger reason emerges.
- The PATCH route accepts `name` edits even though the frontend in this PR does not surface them (no `NameEditor` registered — see Decisions §"Re-parenting and slug-renaming are not supported"). This asymmetry is deliberate: `name` is editable on the model, just not yet exposed in the UI. Add a one-line comment on the PATCH handler noting this so a future reader doesn't "tighten" the schema by removing `name`.
- Use the same primitives as themes: `validate_scalar_fields`, `plan_alias_claims`, and `execute_claims`.

Delete, delete-preview, and restore:

- Single call to `register_entity_delete_restore(router, Location, ..., parent_field="parent", child_related_name="children")`.
- `child_related_name="children"` activates the standard "block on active direct children" check — identical to every other catalog entity. Active child Locations populate `active_children_count` in the preview and produce a 422 on attempted delete.
- Mounts the standard wire shape used by every other entity:
  - `GET /api/locations/{public_id:path}/delete-preview/` returning `TaxonomyDeletePreviewSchema` (`active_children_count` for direct child Locations + `blocked_by` for active-CEL referrers).
  - `POST /api/locations/{public_id:path}/delete/` returning 200 on success or 422 when blocked by either active children or active CELs.
  - `POST /api/locations/{public_id:path}/restore/` rejecting restore while the parent is deleted (via `parent_field="parent"`).
- Blocker semantics ride on the model-level class attributes (see §"Model setup").
- Delete and restore are both row-only and symmetric — same as every other catalog entity. Deleting `usa` requires deleting every state and city under it first; restoring `usa` (after some descendants are independently restored) does not touch descendants.
- The frontend gets `createDeleteSubmitter('locations')` and the shared `DeletePage.svelte` for free once `make codegen` regenerates `schema.d.ts`.

### Read API — DONE

`LocationDetailSchema` carries `expected_child_type: str | None = None`, populated by the cached-tree path in `_get_location_detail`:

- `_LocationNode` carries `divisions: tuple[str, ...]` (empty on non-country rows; populated for country rows from `loc.divisions or ()`).
- The detail serializer finds the country ancestor at `ancestors[0]` (or `node` itself for country rows) and calls `lookup_child_division(country.divisions, location_path.count("/"))`.
- Empty-path root returns `expected_child_type="country"` directly — top-level "+ New …" always creates a country, and the form has its own `divisions` input.
- Cache invalidation is already wired: `transaction.on_commit(invalidate_all)` runs after every claim resolve, so a `divisions` PATCH refreshes the tree on next read.

The five-route hand-fanout (`/`, `/{s1}`, `/{s1}/{s2}`, …) has been collapsed to two: `/` for the root and `/{path:location_path}` for any concrete location. Frontend `+layout.server.ts` updated to match.

This intentionally does **not** call `derive_child_location_type` (or a soft variant) per request — the original plan's approach added a per-detail DB hit that the cache-driven path avoids. Result is the same `str | None` shape, sourced from `LOCATIONS_TREE_KEY`.

## Frontend

### Routes and components

Add the missing write routes under `frontend/src/routes/locations/`.

- `/locations/new` creates a top-level country. It asks for name, slug, note, citation, and comma-separated divisions. Redirect target is `/locations/{slug}`.
- `/locations/[...path]/new` creates a child location. It uses the parent detail's `expected_child_type` for labels such as "New State" or "New Region". It sends only name, slug, note, and citation; the server derives type. If `expected_child_type` is `null`, render an explanatory state instead of a form.
- `/locations/[...path]/edit` and `/edit/[section]` reuse the shared taxonomy edit base components.
- `/locations/[...path]/edit-history` uses the generic edit-history loader with `entity_type="location"` and `public_id=path`.
- `/locations/[...path]/sources` uses the generic sources loader.
- `/locations/[...path]/delete` reuses the shared `DeletePage.svelte` component and `createDeleteSubmitter('locations')` (the wire shape matches every other entity once `make codegen` regenerates `schema.d.ts`), but still needs the standard per-entity wrapper that every existing delete route has — see [`series-delete.ts`](../../../frontend/src/routes/series/[slug]/delete/series-delete.ts) and [`+page@.svelte`](../../../frontend/src/routes/series/[slug]/delete/+page@.svelte) for the canonical shape. Concretely:
  - `frontend/src/routes/locations/[...path]/delete/location-delete.ts` exporting `submitDelete = createDeleteSubmitter('locations')`.
  - `frontend/src/routes/locations/[...path]/delete/+page.ts` (or `+page.server.ts`) — load `params.path` (a string for `[...path]`), fetch the delete-preview, and pass `{ preview, path }` to the page.
  - `frontend/src/routes/locations/[...path]/delete/+page@.svelte` — builds `BlockedState` from `preview.blocked_by` with a Location-specific lead ("This location can't be deleted because active corporate-entity locations still point at it") and `renderReferrerHref: (r) => r.slug ? '/corporate-entities/' + r.slug : null`. The standard `active_children_count` blocked state (provided by the shared `DeletePage`) covers the "delete child Locations first" path with no Location-specific text needed. Builds `impact` for the row-only delete ("this location only — child locations are unaffected"); wires `cancelHref` and `editHistoryHref` from `path` (not `slug`); and chooses `redirectAfterDelete` per tier — for a country, redirect to `/locations`; for a child, redirect to the parent's detail page (`/locations/{parent_path}`, computed by stripping the last segment of `path`).
  - The wrapper is ~40 lines and structurally a copy of the Series version; the Location-specific decisions above are the only meaningful work.

Add Location editor wiring:

- `frontend/src/lib/components/editors/location-edit-sections.ts` — registers the Location-editable sections. **Do not register `NameEditor`** here; `NameEditor` edits `name` and `slug` together, and `slug` is frozen for Location (see Decisions §"Re-parenting and slug-renaming are not supported"). No replacement is provided in this PR — name editing is unavailable until `NameEditor` is taught to render name-only when slug is frozen.
- `frontend/src/lib/components/editors/LocationEditorSwitch.svelte`
- `frontend/src/routes/locations/[...path]/save-location-claims.ts`

The edit menu does **not** offer `name`, `parent`, `slug`, or `location_type` edits. `name` is omitted in this PR (see above); the others are frozen by design. `divisions` is editable only on top-level country rows. Other scalars (`description`, `short_name`, `code`) and aliases edit normally.

### Child labels — DONE

`EXPECTED_CHILD` is deleted. `newChildLabel(profile)` prefers:

1. The first existing child's `location_type`, when children exist.
2. `profile.expected_child_type`, when there are no children.
3. `null`, which suppresses the "+ New ..." action rather than showing a wrong label.

Updated tests live in `frontend/src/routes/locations/[...path]/location-helpers.test.ts`.

### Un-defer Location in `catalog-meta.test.ts`

The test is already segment-aware and `locations: { key: 'location', segment: '[...path]' }` is registered in `ROUTE_DIR_TO_KEY`. Drop `'location'` from `DEFERRED_KEYS` once Location's edit-history and sources subroutes exist so parity is enforced like every other entity.

## Tests

Backend tests:

- `compute_location_path` covers top-level, child, and deeper paths.
- `derive_child_location_type` covers USA, France, missing divisions, and too-deep trees.
- Top-level create succeeds, rejects another country with the same slug (DB `catalog_location_unique_slug_at_root`), rejects another country with the same name case-insensitively — e.g. `Georgia` vs `georgia` — (DB `catalog_location_unique_name_at_root` over `Lower("name")`), and rejects missing divisions.
- Top-level create _allows_ a country whose name or slug matches a non-sibling descendant — e.g. creating country `Georgia` succeeds when a state `Georgia` already exists under USA. Verifies the root-tier `scope_filter_builder` lambda is wired (without it, the pre-check would do an unscoped global scan and falsely reject).
- Top-level create rejects extra fields such as a client-supplied `location_type` (schema-level, via `extra=forbid` on `LocationTopLevelCreateSchema`).
- Child create rejects a client-supplied `divisions` (schema-level, via `extra=forbid` on `LocationChildCreateSchema`).
- Child create succeeds, rejects sibling slug collisions (DB `catalog_location_unique_slug_per_parent`), rejects sibling name collisions case-insensitively (DB `catalog_location_unique_name_per_parent` over `Lower("name")`), allows same slug and same name under different parents, and writes the parent FK claim using `parent.location_path`.
- Child create derives country-specific child types.
- PATCH edits name, description, and aliases on a country and on a child row.
- PATCH rejects `parent`, `slug`, and `location_type` inside `data.fields` (handler-level immutable check).
- PATCH on a country accepts top-level `divisions`; PATCH on any non-country row rejects top-level `divisions` with a field-level 422 ("only editable on countries"). Rejected via handler dispatch on `loc.location_type`, not via per-tier schemas — see §"PATCH claims" for the rationale.
- PATCH rejects `divisions` inside `data.fields` (the canonical path is the top-level body field).
- **DONE**: Detail `expected_child_type` cases — `TestExpectedChildType` in `test_api_locations.py` pins all five (root → `"country"`; USA with `divisions=["state","city"]` → `"state"`; USA/IL → `"city"`; USA/IL/Chicago → `null` (exhausted); Netherlands with no divisions → `null` (missing)). Catches `_LocationNode.divisions` regressions and `lookup_child_division` regressions.
- Delete is blocked when the row has any active direct child Location (standard `child_related_name="children"` behavior). Verified by attempting to delete `usa` while `usa/il` is active and asserting 422 with `active_children_count > 0`.
- Delete-preview reports active `CorporateEntityLocation`-reachable CEs on the row as `blocked_by`. **Walker audit done**: `apps/catalog/api/soft_delete.py` `_record` already dedups by `(entity_key, relation)`, so M2M-through duplicates collapse correctly. The "same CE linked twice" scenario the original plan called for turned out to be DB-impossible — `catalog_corporateentitylocation_unique_pair` forbids two CELs with the same `(corporate_entity, location)` pair — so the proposed dedup test was deleted as dead weight (it documented an unreachable scenario). The standard "active CEL blocks" test (single CE, single CEL) is what we ship; row-local dedup is exercised by the walker's existing test suite.
- `POST /delete/` returns 422 with `blocked_by` populated when blocked by active CELs, and 422 with `active_children_count` populated when blocked by active children. Unblocked delete soft-deletes only the requested row in one `ChangeSet` (no descendants touched, since delete never cascades).
- Restore reactivates only the requested row and is rejected when the parent is deleted.
- Generic edit-history and sources endpoints resolve Location by multi-segment public ID.

Frontend tests:

- **DONE**: Location helper tests in `location-helpers.test.ts` cover existing-child label, server-supplied `expected_child_type`, and `null` suppression.
- `saveLocationClaims` sends `public_id`, not `slug`.
- Delete page renders blocked and unblocked states.
- `catalog-meta.test.ts` passes Location parity: `'location'` is dropped from `DEFERRED_KEYS` and Location's edit-history/sources subroutes are discovered under `[...path]`.

## Verification

Run the smallest useful set while implementing, then finish with:

```bash
make codegen
make lint
make test
```

Manual smoke test against `make dev` with a logged-in superuser:

- `/locations`, `/locations/usa`, and `/locations/usa/il/chicago` still render.
- Create a new country at `/locations/new`.
- Create a child from the new country's action menu.
- Edit description and aliases (name editing is intentionally absent in this PR).
- Visit edit-history and sources for the new child.
- Delete the child.
- Confirm deleting `/locations/usa` is blocked by active child Locations (states/cities), surfaced as `active_children_count` on the standard delete page.
- Confirm deleting a leaf Location with active `CorporateEntityLocation` referrers is blocked, surfaced via `blocked_by` on the standard delete page.
- Confirm existing single-segment entities such as themes and manufacturers still handle edit, edit-history, sources, and delete (regression check that Location's factory hooks haven't disturbed shipped callers).
- Confirm `catalog-meta.test.ts` discovers Location via the new `[...path]` segment and asserts the same edit-history/sources parity as every other entity (`'location'` absent from `DEFERRED_KEYS`).

## Follow-ups

### Derive uniqueness scope from `model._meta.constraints`

Location's create routes pass explicit `scope_filter_builder` lambdas (`Q(parent__isnull=True)` for top-level, `Q(parent=data.parent)` for child). Those lambdas restate information already declared on the model — the partial `UniqueConstraint`s `catalog_location_unique_slug_per_parent`, `catalog_location_unique_slug_at_root`, etc. encode exactly the same scoping. Per [ModelDrivenMetadata.md](ModelDrivenMetadata.md), the model is the source of truth; the route layer should read the constraint declaration rather than duplicate it.

The shape of the follow-up:

1. In `assert_name_available` and the public-id-aware availability check, walk `model_cls._meta.constraints` for `UniqueConstraint`s whose `fields` include the field being checked.
2. For each matching constraint, derive a scope `Q` from `(fields ∪ condition)` and the new row's values: a constraint `fields=["parent", "slug"], condition=Q(parent__isnull=False)` against a row with `parent=X` yields `Q(parent=X)`; `fields=["slug"], condition=Q(parent__isnull=True)` yields `Q(parent__isnull=True)`.
3. Apply the union of derived scopes to the availability query. If no partial constraint matches, fall back to the existing global check — Manufacturer / Theme / etc. stay byte-identical, since none of them have partial UNIQUE constraints today.
4. Add a startup system check (per [ModelDrivenMetadata.md](ModelDrivenMetadata.md)'s "Enforce at startup, not at first request" rule) that verifies every model whose create route runs `assert_*_available` has a coherent constraint set on the checked fields — either fully global (no partial constraints) or a complete partition (every row covered by some partial UNIQUE). Catches gaps at boot rather than at first 422.
5. Delete Location's two `scope_filter_builder` lambdas and confirm Location's existing tests still pass — that's the proof the constraint-derived path is wired correctly. Keep `scope_filter_builder` as the documented escape hatch for cases that don't fit constraint derivation (none in the catalog today).

Tests for the follow-up:

- A model with a partial `UniqueConstraint` on `parent IS NULL` produces the right root-scoped pre-check.
- A model with `(parent, slug)` UNIQUE on `parent IS NOT NULL` produces the right sibling-scoped pre-check.
- A model with no partial constraints (e.g. Theme) produces the existing global check unchanged — regression check that the 10+ shipped callers stay byte-identical.
- The startup system check fails fast on a deliberately-broken model with a partial constraint that doesn't cover every row.
- Location's existing sibling-collision and root-collision tests pass after removing the lambdas.

Splitting this out lets Location land with contained, reviewable scoping (two five-line lambdas), and gives constraint derivation its own focused PR where the "complete partition" verification logic and the system check can be reviewed against more than one concrete caller.

### Consolidate PATCH-claims handlers into a shared factory

Each catalog model with editable claims today has its own hand-rolled PATCH-claims route — themes, manufacturers, franchises, corporate-entities, gameplay-features, series, taxonomy, and (after this PR) locations. They all do roughly the same work: parse the body, validate scalar fields, plan alias claims, and call `execute_claims`. The duplication is real but not yet uniform enough to factor cleanly — name/slug rules, alias shapes, and which scalars are editable vary per model.

Location's PATCH route adds one more instance to the pile. Once it lands, the next consolidation target is a `register_entity_patch_claims` factory in `entity_crud.py` that mirrors the create / delete-restore factories. Likely shape:

- Generic body-parsing for `name`, scalar fields, aliases, note, citation.
- `editable_scalar_fields: frozenset[str]` per model (drives both schema validation and the claim list).
- `immutable_after_create: frozenset[str]` per model (rejected from the body — folds in the Location-specific rejection of `parent`, `slug`, `location_type`).
- Hooks for model-specific extras (Location: `divisions` editable only on top-level rows).

Doing it now would be scope creep — the factory's right shape will be clearer with N+1 concrete callers than with N. Doing it never means accepting hand-rolled PATCH handlers as the steady state.

### Split `apps/catalog/api/helpers.py` by concern

[`apps/catalog/api/helpers.py`](../../../backend/apps/catalog/api/helpers.py) is a kitchen-sink module that grew by accretion. Many of its functions are nominally underscore-private (e.g. `_build_rich_text`, `_first_thumbnail`, `_extract_image_urls`, `_serialize_title_machine`) but are imported across most siblings in `apps/catalog/api/`. The underscore is a lie — Python convention reads it as "private to this module," and the actual usage pattern is "shared across the whole API surface." Symptom: a fresh reader can't tell which functions are local helpers vs. de facto public utilities.

Don't fix it as a rename. The underscore is a symptom of the kitchen-sink shape; the right fix is to split the module by concern and let each function's natural home dictate its visibility. Roughly three clusters:

1. **Image / media extraction** — `_first_thumbnail`, `_extract_image_urls`, `_extract_image_attribution`, `_uploaded_image_urls`, `_serialize_uploaded_media`, `_media_prefetch`. Cohesive set with one well-defined consumer pattern (every entity's detail serializer that surfaces thumbnails). Lift into `apps/catalog/api/images.py` (or `media_helpers.py`); the functions that actually are shared across siblings get public names; the truly-local ones keep their underscore.
2. **Rich-text rendering** — `_build_rich_text`, `_extract_description_attribution`. Explicitly shared across every entity's detail serializer. Lift into `apps/catalog/api/rich_text.py` and rename to `build_rich_text` / `extract_description_attribution`. This is the cluster Location's caching change in this PR adds another caller to.
3. **Per-entity serialization fragments** — `_serialize_credit`, `_serialize_title_ref`, `_serialize_title_machine`, `_collect_titles`, `_location_ancestors`, `_serialize_locations`. These shouldn't be in a shared helpers module at all — each belongs next to its primary owner (`titles.py` for the title fragments, `locations.py` for the location fragments, the people/credit surface for credits). Once each lives next to its owner, the cross-import disappears: a sibling module that wants a title ref reaches the one in `titles.py` through a published function, not by snooping into helpers.

Note: `apps/catalog` is at the top of [AppBoundaries.md](../../AppBoundaries.md)'s dependency graph — only `media.api` (a structural exception) depends on it. So this split is purely a catalog-internal organizational change; no cross-app contracts move. Behavior-preserving, validated by the existing test suite.

Doing it now is scope creep — it touches every entity's detail serializer file, and the split is much clearer with Location's rich-text caller in the pile. Right shape for a focused standalone PR after this one lands.

### Consolidate per-entity delete-page wrappers

Every entity's `[entity]/[id]/delete/+page@.svelte` is ~40–60 lines of formulaic `BlockedState` construction. The template is uniform across themes, manufacturers, series, corporate-entities, gameplay-features, taxonomy, and (after this PR) locations:

- Lead: `"This {label} can't be deleted because active {referrer-type} still point at it:"`
- Hint: `"references this {label} via {relation}"`
- Footer: `"Resolve these references, then try again."`
- Href builder: `(r) => r.slug ? '/{plural}/' + r.slug : null`

The only per-entity bits are the entity label, the plural URL segment for hrefs, and the impact copy. Backend delete-preview already returns the data the page needs (`blocked_by`, `active_children_count`, `changeset_count`); the frontend is just templating it.

The follow-up:

1. Add a `BlockedStateBuilder` (or a `defaultBlockedState` helper) to `$lib/components/delete-page` that takes `entityLabel`, `pluralRouteSegment`, and `preview`, and returns a `BlockedState | null` covering both the `active_children_count > 0` branch and the `blocked_by` branch.
2. Optionally extend the helper with overrides — Location's "child locations are unaffected" impact line, the tier-dependent `redirectAfterDelete`, and any other per-entity lead-copy variations.
3. Per-entity wrappers shrink to ~15 lines: `entityLabel`, `entityName`, `cancelHref`, `redirectAfterDelete`, `editHistoryHref`, plus a one-line call to the builder. Location's tier-dependent redirect stays as a `$derived.by` in the wrapper — it's the only non-formulaic piece across the catalog today.

Doing this in the Location PR would mean refactoring every shipped delete page in the same diff. The right shape is clearer once Location is in the pile (8 wrappers) than before (7) — same logic as the PATCH-claims factory follow-up. Touch every wrapper in one focused PR with the same `delete-page.dom.test.ts` running before/after to prove parity.

### Switch `catalog-meta.test.ts` route enumeration from `import.meta.glob` to `node:fs`

The test currently casts a broad Vite glob (`/src/routes/**/+*`) and re-narrows with a regex because `import.meta.glob` treats `[` / `]` as character classes — useless when the directory names you're hunting for are literally `[slug]` and `[...path]`. The workaround is documented in a comment, but a reader has to reconstruct it every time.

The job the test is doing is a directory enumeration, not a Vite-bundling concern. Vitest runs in Node, so `node:fs` does what's wanted directly:

```ts
import { existsSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

const ROUTES_DIR = resolve(__dirname, "../../routes");
const PARAM_DIRS = new Set(["[slug]", "[...path]"]);

const routeDirs = readdirSync(ROUTES_DIR, { withFileTypes: true })
  .filter((d) => d.isDirectory())
  .filter((d) =>
    readdirSync(resolve(ROUTES_DIR, d.name)).some((c) => PARAM_DIRS.has(c)),
  )
  .map((d) => d.name);
```

That reads as "entity directories with a detail route" without commentary. Same for the subroute scan: `existsSync(resolve(ROUTES_DIR, dir, segment, subroute, '+page.svelte'))` replaces the second broadened glob.

Why deferred: the project's `package.json` doesn't depend directly on `@types/node` (it's a transitive only), so tightening this test currently fails type-check on `node:fs` / `node:path` / `__dirname`. The follow-up is the rewrite **plus** adding `@types/node` as a dev dependency.

### Drop redundant `note: ''` / `fields: {}` defaults from `save-*-claims.ts`

Every catalog `save-*-claims.ts` file (locations, themes, manufacturers, corporate-entities, people, titles, models, plus the shared `save-claims-shared.ts`) PATCHes with `body: { fields: {}, note: '', ...body }`. Both defaults are duplicating backend-side defaults:

- `note: ''` is set by `ChangeSetInputSchema.note: str = ""` ([`apps/provenance/schemas.py`](../../../backend/apps/provenance/schemas.py)) — every PATCH-claims schema inherits it. Omitting `note` and sending `note: ''` are wire-identical.
- `fields: {}` is set by every PATCH-claims subclass (`HierarchyClaimPatchSchema`, `CorporateEntityClaimPatchSchema`, `ModelClaimPatchSchema`, `TitleClaimPatchSchema`, plus Location's). The base `ClaimPatchSchema` keeps `fields: dict[str, Any]` _required_, so `fields: {}` stays needed on routes that bind directly to the base.

The follow-up:

1. Drop `note: ''` from every `save-*-claims.ts` (uniformly safe).
2. Drop `fields: {}` from each save-claims file whose backend schema defaults `fields` — audit per file via the generated `LocationPatchClaimSchema` / `HierarchyClaimsBody` / etc. types in `schema.d.ts` (they expose the optional/required boundary directly).
3. Update each file's `*.test.ts` to drop the corresponding keys from the asserted `body` shape — these assertions currently pin the redundant defaults rather than the contract.

Doing it now is scope creep: it touches ~10 files plus their tests, and the redundancy is harmless. Worth doing as its own focused cleanup PR — small, mechanical, and the tests get cleaner (each assertion describes only what the caller actually sent).

### Rename `SectionEditorProps.slug` → `publicId`

The shared editor contract at [`editor-contract.ts`](../../../frontend/src/lib/components/editors/editor-contract.ts) declares `slug: string` on `SectionEditorProps<TData>`, consumed by ~10 shared editors (`BasicsEditor`, `AliasesSectionEditor`, `PeopleEditor`, `ExternalDataEditor`, `TitleFranchiseEditor`, `RelatedModelsEditor`, `DisplayOrderEditor`, `SystemManufacturerEditor`, `FeaturesEditor`, `TitleExternalDataEditor`). For every shipped entity the value _is_ a slug, so the name is accurate. Location is the first entity where the value is a multi-segment `location_path`; its local editors (`LocationBasicsEditor`, `LocationDivisionsEditor`) implement the contract and rename the prop locally via `slug: publicId` in `$props()`, then pass `slug={publicId}` back into shared editors from `LocationEditorSwitch`.

This works but documents nothing at the contract layer. The follow-up:

1. Rename `SectionEditorProps.slug` → `SectionEditorProps.publicId` in [`editor-contract.ts`](../../../frontend/src/lib/components/editors/editor-contract.ts).
2. Update each of the ~10 shared editors and their per-entity switch components to use `publicId`.
3. Drop Location's local `slug: publicId` aliases in `LocationBasicsEditor` and `LocationDivisionsEditor`.
4. The same `SaveResult` contract carries `updatedSlug` (returned by `saveLocationClaims` and friends) — rename to `updatedPublicId` in the same sweep.

## Out of Scope

- **Model-level `immutable_after_create` enforcement.** Re-parenting and slug-renaming are blocked at the UI / route level in this PR (see Decisions). The model-level frozen-fields enforcement is its own follow-up; once it lands, drop the UI/route workarounds.
- Re-parenting Location.
- Restore UI on deleted-entity pages.
- Rich divisions editor UI.
- Undoing a specific past delete `ChangeSet`.
- Switching generic href consumers to call `entity.get_absolute_url()` directly.
- Adding Location to the wikilink picker. Location is a `CatalogModel` but explicitly suppressed from the picker (today via the `link_autocomplete_serialize = None` sentinel; replaced in [ModelDrivenWikilinkableMetadata.md](ModelDrivenWikilinkableMetadata.md) by absent `WikilinkableModel` inheritance). Location refs in markdown still render and validate — only the authoring picker excludes them.
