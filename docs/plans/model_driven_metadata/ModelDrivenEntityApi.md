# Model-Driven Entity API — extract `entity_api`

## Context

The Flipcommons north star ([ModelDrivenMetadata.md](ModelDrivenMetadata.md)) is to make the catalog swappable for an entirely different domain — baseball, medicine — reusing the same write path, audit trail, patch format and HTTP surface. [ModelDrivenClaimWrite.md](ModelDrivenClaimWrite.md) did this for the **write engines**, extracting `claim_edit` (interactive) and `claim_ingest` (bulk) out of catalog. This doc does it for the **HTTP surface**: the generic create / list / detail / delete-restore / export machinery currently smeared across `apps/catalog/api/`.

That machinery is already substantially domain-agnostic — it drives off `LinkableClaimModel`, `_meta`, the entity-type registry and capability markers, not concrete pinball models. But it lives inside catalog, tangled with the domain through a handful of substrate helpers, so today a new domain can't reuse it. The goal: lift it into a new app, **`entity_api`**, sitting between catalog and `claim_edit` in the spine — the read/write HTTP sibling to the two write engines.

**This is the boundary axis, not the declaration axis.** [ModelDrivenApi.md](ModelDrivenApi.md) (exploratory) is about models declaring _which_ endpoints they expose via a `CatalogApiSpec`, killing per-entity route files. That rides _on top of_ a clean generic engine — it assumes the registrars exist. This doc is what makes them a domain-neutral app first. The two are independent (either can land first) and synergistic.

## What it is

A new `entity_api` app owning the generic HTTP surface over any `LinkableClaimModel` (internal layout in [Package shape](#package-shape)):

- generic registrars: `register_entity_create`, `register_entity_delete_restore`, `register_entity_detail_page`, `paginated_list_response`
- the generic soft-delete engine (already delegating to `core.soft_delete` + `claim_edit.execute_multi_entity_claims`)
- the generic export transforms (schema-gen, serialization, link resolution) — domain registry stays in catalog
- the generic request/response schema bases

It **binds three capability markers** and dispatches on them by `issubclass`, never on concrete models:

- `LinkableClaimModel` — required (addressable + claim-controlled)
- `LifecycleStatusModel` — discovered (gates delete/restore; `has_lifecycle` TypeGuard)
- `MediaSupportedModel` — discovered (gates own-media gallery + own thumbnail/hero)

catalog keeps every per-entity router that _calls_ these registrars, the export domain registry (`_build_registry`, `_annotate_*`, `_register`+router), the domain schema variants, and the domain thumbnail hooks.

```text
catalog (domain)
   concrete models · per-entity routers calling the registrars · export domain registry · thumbnail hooks
        │  routers mount generic registrars; declare per-entity querysets/serializers/hooks
        ▼
entity_api (generic HTTP surface)        ← new
   register_entity_{create,delete_restore,detail_page} · paginated_list_response
   soft-delete engine · export transforms · generic schema bases
   binds LinkableClaimModel / LifecycleStatusModel / MediaSupportedModel
        │
        ▼
claim_edit (interactive writes)   provenance/resolution (read projection)   media.{models,selectors}
```

## Target architecture (spine)

```text
        kiosk | media.api
        catalog
        entity_api          ← new
        claim_edit
        provenance | media.{models,storage,schemas,selectors} | citation
        accounts
        core
```

- **entity_api depends on** `claim_edit` (writes), `provenance`, `core`, and `media` low tiers (export + own-media). It is an HTTP-surface layer like catalog — legitimately media-using, **not** added to the "Data apps do not depend on media" forbid.
- **catalog depends on** `entity_api` (its routers mount the registrars) — so entity_api sits in the spine one tier below catalog.
- Layering closes: `media.api`(top) → catalog → entity_api → `media.{models,selectors}`(bottom); `media.api ≠ media.selectors`, so no cycle.

## Package shape

Internal layout, organized by the two `NinjaAPI` surfaces it serves, then by endpoint family:

```text
entity_api/
  __init__.py           # public API — the registrars + shared types, with __all__
  apps.py
  schemas.py            # cross-cutting wire bases (EntityRef, EntityDetailSchema, …)
  interactive/          # → mounted on the private internal API (the site's own UI)
    create/
      __init__.py       # register_entity_create
      persist.py        # validate_create_input, assert_public_id_available, create_entity_with_claims
      schemas.py        # EntityCreateInputSchema + response
    detail/
      __init__.py       # register_entity_detail_page   (thin — registrar only)
    listing/
      __init__.py       # paginated_list_response
      query.py          # generic list-query helpers
    delete/
      __init__.py       # register_entity_delete_restore
      engine.py         # plan_soft_delete, execute_soft_delete, count_entity_changesets
      serialize.py      # serialize_blocking_referrer + preview
      schemas.py        # BlockingReferrer, SoftDeletePlan, SoftDeleteBlockedError
    field_constraints/
      __init__.py       # get_field_constraints + FieldConstraintSchema (read-side numeric-constraint introspection)
  export/               # → mounted on the separate public bulk-export API
    __init__.py
    schema.py           # claim-field → pydantic schema generation
    serialize.py        # row / relation / description serialization
    links.py            # [[type:id]] link resolution
```

Rationale and the deliberate asymmetries:

- **`interactive/` vs `export/` tracks the two `NinjaAPI` instances** in `config/api.py`: the private internal API (read + write, the site's own UI) and the separate public export API (its own OpenAPI doc + rate limit). A real architectural seam, not cosmetic — and the reason `export`'s registrar stays domain-side in catalog while the interactive registrars move here.
- **`update/` is deliberately absent.** PATCH `.../claims/` is not yet consolidated — it's hand-wired in the catalog routers (calling `claim_edit` + the domain planners). A generic update registrar is `ModelDrivenApi.md`'s work; when it lands it slots in beside `create`/`delete`.
- **No `cud/` / `read/` sub-grouping yet — by design.** create/update/delete _do_ share a mutation envelope, but the shared primitives already live one layer down (`ChangeSetInputSchema` in provenance, claim execution in `claim_edit`); the one entity*api-level shared thing — a unified mutation-registrar pipeline — does not exist today. Introducing `cud/`+`read/` now would mean near-empty shared modules. Deepen to that grouping only when `update` lands \_and* a shared pipeline materializes to fill it; until then the families stay flat under `interactive/`.
- **`detail/` is an honest thin package** (`__init__.py` only) — a single registrar that delegates serialization to a caller-injected hook. Not padded with a hollow `serialize.py` for symmetry; an empty file to match a pattern is worse than a thin package.
- **`field_constraints/` is its own thin family, not folded into `create/`.** `get_field_constraints` feeds both the create form _and_ the (not-yet-consolidated) edit form, so it isn't create-specific — it's cross-cutting read-side field metadata. It migrates here from `claim_edit` during the carve (`ModelDrivenClaimWrite.md` Step 5 leaves it in place precisely because this is its home). Like `detail/`, an honest thin package beats hiding it inside a family it only half-belongs to.
- **`schemas.py` stays at the package root** because the wire bases (`EntityRef`, the detail bases) are shared across families; only family-specific schemas (`EntityCreateInputSchema`, `BlockingReferrer`) live inside a family package.

## Findings that shape the plan

**1. The two halves have nearly disjoint heavy deps.** `entity_crud` → `claim_edit`, no media. `export` → `media`, no `claim_edit`. They share no code with each other — only the introspection substrate. They co-locate because the unifying axis is **transport** (expose the engines over HTTP), not read/write direction; the read/write split already lives below this layer.

**2. Media is a model-driven capability, with one honest seam.** Of 4 `MediaSupportedModel`s (Person, Manufacturer, MachineModel, GameplayFeature):

- **Own media** — gallery (`serialize_uploaded_media(all_media(x))`) + own thumbnail/hero — is uniform across all four and gated purely on `issubclass(model, MediaSupportedModel)`. **The engine absorbs this; declaring the marker is enough.** This is the baseball-ready promise, and it holds exactly.
- **Borrowed/derived thumbnails** — Title→its Models, Manufacturer→its Models, Person→credited Models, Series→Titles→Models, Location→Manufacturers→entities — are bespoke domain traversals. **Irreducibly domain**; the engine exposes an optional `thumbnail_source(entity)` hook and catalog wires the per-entity paths. Not a `MediaSupportedModel` concern (Manufacturer borrows a display thumbnail but its own gallery is separate).

**3. The substrate tendrils are prerequisites, not side-quests.** The engine can't leave catalog cleanly until these move:

| Tendril                                                      | Reached by                         | Move                                                                                                                 |
| ------------------------------------------------------------ | ---------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `catalog.naming.normalize_catalog_name` (5 importers)        | entity_create                      | → `core` (generic folding despite the name)                                                                          |
| `catalog._alias_registry` + `_walks._catalog_app_subclasses` | entity_list, export, entity_create | → `core` (generic introspection; widen the catalog-scoped walk to a parameterized `app_subclasses(app_label, base)`) |
| `catalog.api.schemas` generic bases                          | entity_crud, soft_delete           | split generic bases (EntityRef, detail bases, patch bases) out of the domain variants                                |
| generic image helpers                                        | export, per-entity routers         | → low `media` tier (`media/selectors.py`)                                                                            |
| `catalog.cache` export response-cache                        | export `_register` only            | **no move** — `_register` stays catalog-side and calls the moved transforms                                          |

**4. Export splits at one clean line; cache is a non-issue.** Generic transforms (`_build_schema`, `_build_qs`, `_serialize_row`, `_serialize_relation`, `_serialize_description`, link resolution, `_scalar_py_type`, ExportSpec/RelationSpec/DerivedField, EntityExportSchema/DescriptionExportSchema, rate-limit spec) → entity*api. Domain (`_build_registry`, `\_annotate*\*`, `CreditExportSchema`, `\_register`+`export_router`+cache, `EXPORT_ENTITY_TYPES`) → stays in catalog. The only cross-app edge the transforms add is → media; the cache stays domain-side.

## Phasing

Each phase is its own commit (or small commit series). 🛑 STOP for user review before committing each. Phases are ordered by dependency: the substrate relocations are prerequisites; the carve is near-mechanical once they land.

(An earlier draft opened with a `claim_edit` package-split phase. It's gone — it duplicated `ModelDrivenClaimWrite.md` Step 4/5, whose package split is no longer being done. `claim_edit` exposes a clean enough surface after that doc's Step 5 `__all__`, so this extraction needs no `claim_edit`-side foundation step and starts at the substrate relocations.)

### Phase A — substrate relocations (prerequisites)

Sever the tendrils so the engine carve is clean. Each is independently shippable and valuable on its own.

- **A1 `catalog.naming` → `core`.** `normalize_catalog_name` + `MAX_CATALOG_NAME_LENGTH` are generic; move to `core` (e.g. `core/naming.py`), repoint 5 importers. Verify the article-stripping (`the/a/an`) is acceptable as generic English folding.
- **A2 alias + walk introspection → `core`.** Generalize `_walks._catalog_app_subclasses` to `core.app_subclasses(app_label, base)`; keep catalog's scoped wrappers as thin adapters. Move `_alias_registry` (AliasType, `discover_alias_types`, `alias_type_for`) to `core` or `provenance` (it validates parents are `ClaimControlledModel`, so provenance is defensible). Widen too-narrow `CatalogModel` hints.
- **A3 split `catalog.api.schemas`.** Generic bases (EntityRef, LinkableDetailSchema, DescribedDetailSchema, LastModifiedDetailSchema, CatalogDetailSchema→rename EntityDetailSchema, EntityCreateInputSchema, ClaimPatchSchema, HierarchyClaimPatchSchema) → `core.schemas` or seed them in `entity_api` (`schemas.py`). Domain variants (ModelClaimPatchSchema, TitleClaimPatchSchema, …) stay in catalog.
- **A4 image helpers → low `media` tier.** Move `media_prefetch`, `serialize_uploaded_media`, `extract_image_urls`, `extract_image_attribution`, `_uploaded_image_urls`, `all_media` to `media/selectors.py` (a new media internal tier above `{models,storage,schemas}`, below `media.authz/api` — add to the "Media internal layers" contract). Domain fetchers (`fetch_model_media_map` stays generic-but-low; `fetch_title_media_map`, `first_thumbnail` are domain traversals) stay in catalog as thumbnail-hook inputs. Note: already imported by `kiosk` and `media` tests, confirming the move.

### Phase B — carve `entity_api` (CRUD / list / detail / delete-restore)

With tendrils cut, move the generic registrars into the new app — near-mechanical `git mv` + import repoint, mirroring the `claim_edit`/`claim_ingest` carves. Source → destination follows [Package shape](#package-shape):

- New app `apps/entity_api` (AppConfig, INSTALLED_APPS between catalog and claim_ingest, spine entry between `apps.catalog` and `apps.claim_edit`).
- Move into `interactive/`: `register_entity_create` + the generic create helpers from `entity_create.py` → `interactive/create/`; `register_entity_delete_restore` + `soft_delete.py` engine/wire types → `interactive/delete/`; `entity_detail_page.py` (drop the dead `CatalogModel` import — it works on `LinkableModel`) → `interactive/detail/`; `entity_list.paginated_list_response` + list-query helpers → `interactive/listing/`. Generic schema bases land in `entity_api/schemas.py` (if not already in core per A3).
- **Absorb the field-constraints read endpoint.** Move `get_field_constraints` + `FieldConstraintSchema` out of `claim_edit` (where `ModelDrivenClaimWrite.md` Step 5 parked them as the read-side outlier) into `interactive/field_constraints/`, and repoint the `GET /field-constraints/{entity_type}` route in `config/api.py` (a top-level import + a lazy in-function import). It's model-driven numeric-constraint introspection over any `LinkableClaimModel` — the read sibling of the create form, squarely entity_api's surface and out of place in a write engine. Pure code move; the wire URL is unchanged.
- **Media in detail/list registrars:** the generic detail/list registrar serializes own-media when `issubclass(model, MediaSupportedModel)` (calls `media.selectors`), and accepts an optional `thumbnail_source(entity)` hook for borrowed thumbnails. catalog's per-entity specs pass the domain traversal (`fetch_model_media_map`, `fetch_title_media_map`, `first_thumbnail`) into that hook. This consolidates today's per-router media wiring into the engine for the automatic case while keeping derived thumbnails domain-owned.
- catalog's per-entity routers keep mounting the registrars and passing querysets/serializers/hooks; only import paths change.
- **Contracts:** add `apps.entity_api` to the spine between catalog and claim_edit; it may import media (not on the data-apps media forbid); engine↔engine independence with claim_ingest if any edge is plausible (likely none). Update `docs/AppBoundaries.md`.

### Phase C — export engine into `entity_api` (last; most entangled)

Export is **in scope for `entity_api`** and follows the _same split as CRUD — the engine moves, the route definitions stay_. Move the generic transforms (Finding 4 — schema-gen, serialization, link resolution, `_scalar_py_type`, the ExportSpec/RelationSpec/DerivedField config types, EntityExportSchema/DescriptionExportSchema, the rate-limit spec) into `entity_api/export/`. `_build_registry`, `_annotate_*`, `CreditExportSchema`, `_register`, `export_router` and cache wiring stay in catalog — they hand-list the 8 concrete models, so they're domain, exactly like a per-entity router is. catalog's `_register` calls the moved transforms (downward dep); the transforms import `media.{models,selectors}` for the own-image branches — the single media edge, already opened in Phase B.

Sequenced **last** because it's the most domain-entangled piece — not because it's optional. Phases A–B are shippable milestones that deliver the CRUD/list/detail/delete surface on their own, but export's engine is part of entity_api's final surface.

## Critical files

- `apps/catalog/naming.py`, `apps/catalog/_walks.py`, `apps/catalog/_alias_registry.py`, `apps/catalog/api/schemas.py`, `apps/catalog/api/images.py` (Phase A)
- `apps/catalog/api/{entity_crud,entity_detail_page,entity_list,soft_delete,entity_create}.py` → `apps/entity_api/interactive/` (Phase B)
- `apps/claim_edit/claim_write.py` (`get_field_constraints` + `FieldConstraintSchema`) + `config/api.py` field-constraints route → `apps/entity_api/interactive/field_constraints/` (Phase B)
- `apps/catalog/api/export.py` → `apps/entity_api/export/` (transforms) + stays partial in catalog (registry) (Phase C)
- `backend/pyproject.toml` (import-linter contracts), `docs/AppBoundaries.md`, `config/settings.py` (INSTALLED_APPS)

## Verification

- After each phase: `make lint` (incl. `uv run lint-imports` — the new contracts green, no new baselines), `make mypy`, and a step-scoped pytest (`apps/catalog apps/core apps/provenance apps/claim_edit` + `apps/entity_api` once it exists).
- After the carve: **full** backend suite green (per-entity routers, signals, export, admin all reach `entity_api`); `make codegen` produces no consumer-facing route churn (wire URLs unchanged — the carve is a code move, not a route change).
- End-to-end on a dev DB: a create, a scalar claim PATCH, a delete-preview/delete/restore, a detail page with own-media (a `MediaSupportedModel`) and with a borrowed thumbnail (e.g. Manufacturer), and a bulk export — all behaving identically to pre-carve.
- Decoupling complete when catalog imports `entity_api` but `entity_api` imports no catalog symbol (spine enforces `entity_api ⊄ catalog`), and the substrate tendrils (naming, alias, generic schemas, image helpers) no longer resolve into catalog.

## Relationship to other docs

- **[ModelDrivenClaimWrite.md](ModelDrivenClaimWrite.md)** — sibling; extracted the write engines (`claim_edit`/`claim_ingest`). This extracts the HTTP surface engine that sits one tier above them, and during its carve picks up the read-side `get_field_constraints` endpoint that its Step 5 leaves parked in `claim_edit`.
- **[ModelDrivenApi.md](ModelDrivenApi.md)** — the declaration axis (model-declared `CatalogApiSpec`, generic route registry). Rides on top of this extraction; independent. Once both land, a model declares its endpoints and the registry mounts them against the `entity_api` registrars.
- **[ModelDrivenClaimResolution.md](ModelDrivenClaimResolution.md)** — the read-projection engine (`provenance/resolution/`); export's read path is its HTTP consumer.

## Out of scope

- The `CatalogApiSpec` declaration mechanism / killing per-entity route files (that's `ModelDrivenApi.md`).
- Converging the interactive relationship-claim planners onto the bulk registry (deferred per `ModelDrivenClaimWrite.md`).
- Genericizing the borrowed-thumbnail traversals — they stay domain hooks by design.
