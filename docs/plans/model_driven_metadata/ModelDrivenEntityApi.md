# Model-Driven Entity API — a domain-neutral `engine/` inside catalog

## Context

A north star of the project ([ModelDrivenMetadata.md](ModelDrivenMetadata.md)) is to make the catalog swappable for an entirely different domain — baseball, medicine — reusing the same write path, audit trail, patch format and HTTP surface. [ModelDrivenClaimWrite.md](ModelDrivenClaimWrite.md) did this for the **write engines**, extracting `claim_edit` (interactive) and `claim_ingest` (bulk) out of catalog. This doc does it for the **HTTP surface**: the generic create / list / detail / delete-restore / export machinery currently smeared across `apps/catalog/api/`.

That machinery is already substantially domain-agnostic — it drives off `LinkableClaimModel`, `_meta`, the entity-type registry and capability markers, not concrete pinball models. But it's tangled with the domain through a handful of substrate helpers and a hard binding to `CatalogModel`, so nothing today enforces the boundary and a new domain can't reuse it.

**The boundary is drawn _inside_ catalog.** The machinery becomes a domain-neutral `catalog/engine/` package, governed by the intra-app import-linter machinery that already polices catalog's internal stack: the exhaustive `Catalog internal layers` contract (a new submodule left unplaced fails the build) and the catalog-agnostic forbidden pattern that already keeps `catalog/resolve/` from importing the domain. `catalog/engine/` joins both — a layer in that stack, plus a forbidden contract asserting `engine ⊄ catalog-domain`.

The engine is built **in place**. Lifting it to its own top-level app is deferred to domain-swap time; the boundary work here is what makes that a `git mv` (see [Deferred: app extraction](#deferred-app-extraction)).

**This is the boundary axis, not the declaration axis.** [ModelDrivenApi.md](ModelDrivenApi.md) is about models declaring _which_ endpoints they expose via a `CatalogApiSpec`, killing per-entity route files. That rides _on top of_ a clean generic engine — it assumes the registrars exist. This doc is what makes them domain-neutral first. The two are independent (either can land first) and synergistic.

## What it is

A domain-neutral `catalog/engine/` package owning the generic HTTP surface over any `LinkableClaimModel` (internal layout in [Package shape](#package-shape)):

- generic registrars: `register_entity_create`, `register_entity_delete_restore`, `register_entity_detail_page`, `paginated_list_response`
- the generic soft-delete engine (already delegating to `core.soft_delete` + `claim_edit.execute_multi_entity_claims`)
- the generic export transforms (schema-gen, serialization, link resolution) — domain registry stays catalog-side
- the generic request/response schema bases

Each registrar **binds the minimal capability base its surface needs** — a static type bound, with `issubclass` dispatch for the genuinely discovered capabilities — never concrete models:

- **read (list, detail) + create** → `LinkableClaimModel` (addressable + claim-controlled). create needs nothing more: its lifecycle touch — collision/parent lookups filtered through `.active()` — is a _refinement_ branched on `has_lifecycle` at runtime, not a precondition (a non-lifecycle entity simply has no soft-deleted rows to exclude).
- **delete / restore** → `LinkableLifecycleClaimModel` — a new ABC = `LifecycleStatusModel` + `LinkableClaimModel`. Soft-delete _is_ writing the `status` claim, so lifecycle is a hard precondition here; making it a base turns what would otherwise be a runtime `AttributeError` smeared across the manager (`.active()`), the field (`.status`) and the operation's semantics into one compile-time error at the registration site.
- `MediaSupportedModel` — discovered (gates own-media gallery + own thumbnail/hero).
- `has_lifecycle` stays a genuinely _discovered_ capability — but only for **cascade members** (a referrer may or may not be soft-deletable, and the walk branches on it), never for the delete root.

Outside `engine/`, catalog keeps every per-entity router that _calls_ these registrars, the export domain registry (`_build_registry`, `_annotate_*`, `_register`+router), the domain schema variants, the domain thumbnail hooks, and the concrete models + the `CatalogModel` base.

```text
catalog/<domain>   concrete models · CatalogModel · per-entity routers · export registry · thumbnail hooks
        │  routers mount the engine registrars; declare per-entity querysets/serializers/hooks
        ▼
catalog/engine/   (domain-neutral HTTP surface)
   register_entity_{create,delete_restore,detail_page} · paginated_list_response
   soft-delete engine · export transforms · generic schema bases
   binds LinkableClaimModel (read/create) / LinkableLifecycleClaimModel (delete) / MediaSupportedModel (discovered)
   ── import-linter: catalog.engine ⊄ catalog-domain ──
        ▼
claim_edit (interactive writes)   provenance/resolution (read projection)   media.{models,selectors}   core
```

## Boundary

The layering is now _within_ catalog, sitting on the unchanged spine below it:

```text
catalog/<domain>      concrete models · CatalogModel · per-entity routers · export registry · thumbnail hooks
catalog/engine        generic HTTP surface  ← new internal boundary
claim_edit
provenance | media.{models,storage,schemas,selectors} | citation
accounts
core
```

- **`catalog/engine` depends on** `claim_edit` (writes), `provenance`, `core`, and the `media` low tiers (export + own-media). catalog already uses media freely, so there's no forbid to amend — engine using media is unproblematic.
- **`catalog/<domain>` depends on `catalog/engine`** — the per-entity routers mount the registrars. This downward direction is exactly what makes the eventual extraction clean.
- **Enforcement is intra-app, on the existing machinery.** `catalog.engine` joins the exhaustive `Catalog internal layers` contract as a layer below the domain modules, and a forbidden contract asserts `catalog.engine ⊄ catalog-domain` — the same shape that keeps `catalog/resolve/` domain-agnostic. The `exhaustive` layering means a new engine submodule left unplaced fails the build.

## Package shape

```text
catalog/
  engine/
    __init__.py        # engine public API — the registrars + shared types, with __all__
    schemas.py         # cross-cutting wire bases (EntityRef, EntityDetailSchema, …), shared by both surfaces
    entity_api/        # the private internal API surface (the site's own UI)
      create/          # register_entity_create; persist (validate/assert_public_id/create_with_claims); schemas
      detail/          # register_entity_detail_page  (thin — registrar only)
      listing/         # paginated_list_response
      delete/          # register_entity_delete_restore; engine (plan/execute/count); serialize; schemas
      field_constraints/  # get_field_constraints + FieldConstraintSchema (read-side introspection)
    export_api/        # the public bulk-export surface — separate NinjaAPI, own OpenAPI doc + rate limit
      schema.py        # claim-field → pydantic schema generation
      serialize.py     # row / relation / description serialization
      links.py         # [[type:id]] link resolution
    query/             # generic list-query fold (+ generic facet helpers); per-entity facet configs stay domain-side
  models/              # concrete domain models + the CatalogModel base   (domain-side — NOT in engine)
  api/                 # per-entity routers · export registry · thumbnail hooks   (domain-side)
```

Rationale and the deliberate asymmetries:

- **`entity_api/` vs `export_api/` = private vs public API surface.** The real seam is the private internal API (read + write, the site's own UI) vs the public API (own OpenAPI doc, rate limit, external stability contract) — the two `NinjaAPI` instances in `config/api.py`. Export is the public surface's sole resident _today_; the boundary is durable even though the label is concrete. They sit as sibling subpackages under `engine/`, split by audience/contract, enforced by an intra-app contract (`entity_api ⊄ export_api`; both may use `engine/schemas.py`). `export_api`'s _route registration_ stays domain-side in catalog while its transforms live here. If a second public surface appears, it joins `export_api`'s tier.
- **No `engine/models/`.** The generic bases (`LinkableClaimModel`, `LinkableLifecycleClaimModel`) live in `provenance`; `CatalogModel` is the bundle the _concrete domain_ models inherit, so it stays in `catalog/models/`. The engine is code, not Django models. (If a genuinely generic catalog-level base ever surfaces that isn't in provenance and isn't domain-specific, it'd be a single `engine/models.py` module — name it before creating it.)
- **`update/` is deliberately absent.** PATCH `.../claims/` is not yet consolidated — it's hand-wired in the catalog routers (calling `claim_edit` + the domain planners). A generic update registrar is `ModelDrivenApi.md`'s work; when it lands it slots in beside `create`/`delete` inside `entity_api/`.
- **No `cud/` / `read/` sub-grouping yet — by design.** create/update/delete _do_ share a mutation envelope, but the shared primitives already live one layer down (`ChangeSetInputSchema` in provenance, claim execution in `claim_edit`); the one engine-level shared thing — a unified mutation-registrar pipeline — does not exist today. Introducing `cud/`+`read/` now would mean near-empty shared modules. Deepen only when `update` lands _and_ a shared pipeline materializes; until then the families stay flat under `entity_api/`.
- **`detail/` is an honest thin package** (`__init__.py` only) — a single registrar that delegates serialization to a caller-injected hook. Not padded with a hollow `serialize.py` for symmetry.
- **`field_constraints/` is its own thin family, not folded into `create/`.** `get_field_constraints` feeds both the create form _and_ the (not-yet-consolidated) edit form, so it isn't create-specific — it's cross-cutting read-side field metadata. It migrates here from `claim_edit` during Phase C (`ModelDrivenClaimWrite.md` Step 5 leaves it in place precisely because this is its home).
- **`schemas.py` stays at `engine/` root** because the wire bases (`EntityRef`, the detail bases) are shared across both surfaces; only family-specific schemas (`EntityCreateInputSchema`, `BlockingReferrer`) live inside a family package.

## Findings that shape the plan

**1. The real work is rebinding the registrars off `CatalogModel` — not the file move.** Every registrar is billed as domain-agnostic but is actually bound to `catalog.models.CatalogModel`: type bounds (`register_entity_*[ModelT: CatalogModel]`), ~7 signatures `model_cls: type[CatalogModel]` in `entity_create.py`, and a runtime narrowing (`_require_catalog`, `isinstance(…, CatalogModel)`) in `soft_delete.py`. `catalog.engine` may import no catalog-domain symbol — and `CatalogModel` lives in `catalog/models/` — so this rebind, not the relocation into `engine/`, is the extraction. It is **not** mechanical, and it's mostly tractable once measured: `CatalogModel = DescribedModel + SitemappedModel + LifecycleStatusModel + LinkableClaimModel`, and the registrars touch none of the two domain mixins (no `.description`/sitemap access). The true per-surface minimal bound:

| Surface                               | Bind to                                 | Why                                                                                     |
| ------------------------------------- | --------------------------------------- | --------------------------------------------------------------------------------------- |
| `list`                                | `Model` (already)                       | looser than `LinkableClaimModel`; leave as-is                                           |
| `detail`                              | `LinkableClaimModel` + freshness        | needs `lastmod_expression()` — on `LastUpdatedModel`, not in `LinkableClaimModel`'s MRO |
| `create`                              | `LinkableClaimModel`                    | queryset is caller-injected; `.active()` calls become `has_lifecycle`-branched          |
| `delete_restore` + soft-delete engine | `LinkableLifecycleClaimModel` (new ABC) | soft-delete writes the `status` claim — lifecycle is a precondition                     |

Done in place (Phase B), the existing suite is a behavior-preserving oracle for each step.

**2. The two surfaces have nearly disjoint heavy deps.** `entity_api` → `claim_edit`, no media. `export_api` → `media`, no `claim_edit`. They share no code — only the introspection substrate (which lives below, in core/provenance). They co-locate in `engine/`, as sibling subpackages, because they're the same architectural tier (generic HTTP surface over `LinkableClaimModel`) split by **audience/contract** — private internal API vs public API — with an anticipated future edge (the public surface reusing the generic transforms). The seam is real but intra-package, enforced by an import-linter contract.

**3. Media is a model-driven capability, with one honest seam.** Of 4 `MediaSupportedModel`s (Person, Manufacturer, MachineModel, GameplayFeature):

- **Own media** — gallery (`serialize_uploaded_media(all_media(x))`) + own thumbnail/hero — is uniform across all four and gated purely on `issubclass(model, MediaSupportedModel)`. **The engine absorbs this; declaring the marker is enough.** This is the baseball-ready promise, and it holds exactly.
- **Borrowed/derived thumbnails** — Title→its Models, Manufacturer→its Models, Person→credited Models, Series→Titles→Models, Location→Manufacturers→entities — are bespoke domain traversals. **Irreducibly domain**; the engine exposes an optional `thumbnail_source(entity)` hook and catalog wires the per-entity paths. Not a `MediaSupportedModel` concern (Manufacturer borrows a display thumbnail but its own gallery is separate).

**4. The substrate tendrils are prerequisites, not side-quests.** Each must leave the engine's forbidden set before `catalog.engine ⊄ catalog-domain` can pass. With the engine living _inside_ catalog, each tendril has a new degree of freedom: it moves to the **lowest tier all its consumers can reach** — down to `core`/`provenance` if anything below catalog uses it, otherwise into `catalog/engine/` itself (a generic-but-catalog-flavored home that the domain may still import downward).

| Tendril                                                      | Reached by                         | Move                                                                                                               |
| ------------------------------------------------------------ | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `catalog.naming.normalize_catalog_name` (5 importers)        | entity_create                      | → `core` (generic folding; the frontend mirror + broad use argue for the lowest tier)                              |
| `catalog._alias_registry` + `_walks._catalog_app_subclasses` | entity_list, export, entity_create | → `core`/`provenance` (generic introspection; widen the catalog-scoped walk to `app_subclasses(app_label, base)`)  |
| `catalog.api.schemas` generic bases                          | entity_crud, soft_delete           | split generic bases (EntityRef, detail bases, patch bases) out of the domain variants → `core` or `engine/schemas` |
| image helpers (two groups — see A4)                          | export, per-entity routers         | pure-`EntityMedia` helpers → low `media` tier; `extra_data` extractors → `engine/export_api` (not media)           |
| `catalog.cache` export response-cache                        | export `_register` only            | **no move** — `_register` stays domain-side and calls the moved transforms                                         |

**5. Export splits at one clean line; cache is a non-issue.** Generic transforms (`_build_schema`, `_build_qs`, `_serialize_row`, `_serialize_relation`, `_serialize_description`, link resolution, `_scalar_py_type`, `ExportSpec`/`RelationSpec`/`DerivedField`, `EntityExportSchema`/`DescriptionExportSchema`, rate-limit spec) → `engine/export_api`. Domain (`_build_registry`, `_annotate_*`, `CreditExportSchema`, `_register` + `export_router` + cache, `EXPORT_ENTITY_TYPES`) → stays in catalog. The transforms call `extract_image_urls`/`extract_image_attribution`, which carry `extra_data` schema knowledge and therefore land in `engine/export_api` too — _not_ the low media tier (see A4).

## Phasing

Each phase is its own commit (or small commit series). 🛑 STOP for user review before committing each. Ordered by dependency: the substrate relocations (A) and the in-place `CatalogModel` rebind (B) are prerequisites; relocating into `engine/` (C) is genuinely mechanical only once they land; export (D) is last because it's the most domain-entangled. The intra-app contract machinery these plug into already exists — the exhaustive `Catalog internal layers` contract and the catalog-agnostic forbidden pattern.

### Phase A — substrate relocations (prerequisites)

Sever the tendrils (Finding 4) so the engine is import-clean. Each is independently shippable. Per tendril, pick the lowest tier all consumers can reach — `core`/`provenance` if anything below catalog needs it, else `catalog/engine/`.

- **A1 `catalog.naming` → `core`.** `normalize_catalog_name` + `MAX_CATALOG_NAME_LENGTH` are generic; move to `core` (e.g. `core/naming.py`), repoint 5 importers. Verify the article-stripping (`the/a/an`) is acceptable as generic English folding.
- **A2 alias + walk introspection → `core`/`provenance`.** Generalize `_walks._catalog_app_subclasses` to `core.app_subclasses(app_label, base)`; keep catalog's scoped wrappers as thin adapters. Move `_alias_registry` (AliasType, `discover_alias_types`, `alias_type_for`) **and the `AliasModel` abstract base** to `core` or `provenance` (both relate to `ClaimControlledModel` parents, so provenance is defensible) — `entity_create._resolve_alias_relation` does `issubclass(related_model, AliasModel)` and returns `type[AliasModel]`, so the base must move with the registry or the carved engine keeps an `apps.catalog.models` import (or drops alias-collision). Concrete alias models (`ThemeAlias`, …) stay in catalog and subclass the moved base; confirm `AliasModel`'s abstract definition names no concrete catalog model. Widen too-narrow `CatalogModel` hints.
- **A3 split `catalog.api.schemas`.** Generic bases (EntityRef, LinkableDetailSchema, DescribedDetailSchema, LastModifiedDetailSchema, CatalogDetailSchema→rename EntityDetailSchema, EntityCreateInputSchema, ClaimPatchSchema, HierarchyClaimPatchSchema) → `core.schemas` or seed them in `engine/schemas.py`. Domain variants (ModelClaimPatchSchema, TitleClaimPatchSchema, …) stay in catalog.
- **A4 image helpers — split by what they actually know.** Not one move, two:
  - **Pure `EntityMedia`** (`media_prefetch`, `serialize_uploaded_media`, `_uploaded_image_urls`, `all_media`) → `media/selectors.py`, a new media internal tier above `{models,storage,schemas}`, below `media.authz/api`. This inserts a tier into the existing **layered** "Media internal layers" contract — a real contract edit, not a footnote.
  - **`extra_data` extractors** (`extract_image_urls`, `extract_image_attribution`) reach into external-source keys (`opdb.images`, `ipdb.image_urls`, `.__permissiveness_rank`, `.__license_slug`) — the catalog's third-party-image provenance convention, _not_ media-storage logic. Pushing them into the low media tier would invert the dependency and drag `core.licensing` + `provenance.schemas.AttributionSchema` down with them. They move to `engine/export_api` (Phase D) alongside the transforms that call them.
  - Domain fetchers (`fetch_model_media_map`, `fetch_title_media_map`, `first_thumbnail`) import concrete models → stay catalog as thumbnail-hook inputs. The pure-`EntityMedia` helpers are already imported by `kiosk` and `media` tests, confirming that half of the move.

### Phase B — decouple the registrars from `CatalogModel` (the big rock)

The actual extraction (Finding 1). Do it **in place, inside `catalog/api/`, before relocating anything into `engine/`**: behavior must not change, so the existing full suite is a behavior-preserving oracle, and each step is a ~20-line diff whose failure is unambiguous — an oracle you'd lose if a file move and import churn rode along in the same commit. Sequenced smallest-gap-first so the approach is proven on the cheap cases before the hard one:

1. **Introduce the delete base.** Add `LinkableLifecycleClaimModel(LifecycleStatusModel, LinkableClaimModel)` to `provenance/models/base.py` (provenance sits below catalog and already pairs the two ingredients in `LinkableClaimModel`). Re-parent `CatalogModel` onto it: `CatalogModel(DescribedModel, SitemappedModel, LinkableLifecycleClaimModel)`. **Base order matches `CatalogModel`'s current declaration**, so its MRO, default manager (`ManagerFromLifecycleQuerySet`) and field layout are byte-identical — a structural no-op, confirmed by an empty migration. (Name order ≠ base order, deliberately; the `…ClaimModel` suffix keeps it in the family. The combined ABC linearizes safely because only `LifecycleStatusModel` declares a manager — the whole `LinkableClaimModel` chain declares none — so `.active()` survives regardless of order.)
2. **`list`** — already bound to `Model`; confirm no-op.
3. **`detail_page`** — widen the bound off `CatalogModel`, but **not to bare `LinkableClaimModel`**: the body calls `model_cls.lastmod_expression()`, which lives on `LastUpdatedModel` — reached in `CatalogModel` via the `SitemappedModel` branch, _not_ via `LinkableClaimModel` (it's absent from `LinkableClaimModel`'s MRO, so a bare bound fails typing and crashes for any linkable-claim model without the freshness capability). Fix: inject the lastmod expression (or a pre-annotated `detail_qs`) from the caller — consistent with the already-injected `detail_qs`/`serialize_detail`, and the right home anyway since `Title` overrides `lastmod_expression`. detail then binds cleanly to `LinkableClaimModel`. (Alternatively bind a combined `LinkableClaimModel + LastUpdatedModel` base and keep the polymorphic call.)
4. **`create`** — rebind every `type[CatalogModel] → type[LinkableClaimModel]` across `entity_create.py` and `register_entity_create` (in `entity_crud.py`). Two `.active()` sites become lifecycle-conditional, since a non-lifecycle creatable entity has no soft-deleted rows to exclude: the duplicate-name guard (`entity_create.py` collision check) and the parent lookup (`register_entity_create`'s `parent_model.objects.active()`) become `manager.active() if has_lifecycle(m) else manager.all()`. The `else` is correct behavior, not dead code — cover each branch with a throwaway non-lifecycle test model.
5. **`delete_restore` + soft-delete engine** — rebind `register_entity_delete_restore`, `plan_soft_delete`, `execute_soft_delete` from `CatalogModel → LinkableLifecycleClaimModel` (`count_entity_changesets` needs only `LinkableClaimModel` — it touches `.pk` and claims, not lifecycle). `_require_catalog` narrows to the new base, or disappears: `soft_delete_walk` already returns `LifecycleStatusModel`-typed members, so the narrowing it performs is now upward-compatible.

After Phase B, no registrar references `catalog.models.CatalogModel`; the files still live in `catalog/api/`, still mounted by the same per-entity routers, still green on the full suite. The relocation that follows is then a pure `git mv`.

### Phase C — relocate the generic registrars into `catalog/engine/entity_api/`

With tendrils cut (A) and the registrars rebound (B), move them under `engine/` — an intra-catalog `git mv` + import repoint, then flip the layered contract on. Source → destination follows [Package shape](#package-shape):

- Move the families: the create registrar `register_entity_create` (in `entity_crud.py`) + its helpers (`entity_create.py`) → `engine/entity_api/create/`; the delete registrar `register_entity_delete_restore` (in `entity_crud.py`) + the `soft_delete.py` engine/wire types → `engine/entity_api/delete/`; `entity_detail_page.py` → `engine/entity_api/detail/`; `entity_list.paginated_list_response` + list-query helpers → `engine/entity_api/listing/` (the generic list-query fold may instead land in `engine/query/`). Generic schema bases land in `engine/schemas.py` (if not already in core per A3). Note `entity_crud.py` houses _both_ registrars, so it splits across `create/` and `delete/` rather than moving as a unit.
- **Absorb the field-constraints read endpoint.** Move `get_field_constraints` + `FieldConstraintSchema` out of `claim_edit` (where `ModelDrivenClaimWrite.md` Step 5 parked them as the read-side outlier) into `engine/entity_api/field_constraints/`, and repoint the `GET /field-constraints/{entity_type}` route in `config/api.py`. Model-driven numeric-constraint introspection over any `LinkableClaimModel` — the read sibling of the create form, out of place in a write engine. Pure code move; the wire URL is unchanged.
- **Media in detail/list registrars:** the generic registrar serializes own-media when `issubclass(model, MediaSupportedModel)` (calls `media.selectors`), and accepts an optional `thumbnail_source(entity)` hook for borrowed thumbnails. catalog's per-entity specs pass the domain traversal (`fetch_model_media_map`, `fetch_title_media_map`, `first_thumbnail`) into that hook. Consolidates today's per-router media wiring into the engine for the automatic case while keeping derived thumbnails domain-owned.
- catalog's per-entity routers keep mounting the registrars and passing querysets/serializers/hooks; only import paths change.
- **Contract:** add `catalog.engine` to the existing exhaustive `Catalog internal layers` contract (below the domain) and add a forbidden contract `catalog.engine ⊄ catalog-domain`, mirroring the resolver-core rule; add the `entity_api ⊄ export_api` seam. Record the additions in `docs/AppBoundaries.md`. No `INSTALLED_APPS`/spine change — this is one app.

### Phase D — export engine into `catalog/engine/export_api/` (last; most entangled)

Move the generic transforms (Finding 5) plus the `extra_data` extractors (`extract_image_urls`/`extract_image_attribution`, per A4) into `engine/export_api/`. `_build_registry`, `_annotate_*`, `CreditExportSchema`, `_register`, `export_router` and cache wiring stay in catalog — they hand-list the concrete models, so they're domain, exactly like a per-entity router. catalog's `_register` calls the moved transforms (downward, domain → engine); the transforms import `media.{models,selectors}` for the own-image branches.

Sequenced **last** because it's the most domain-entangled piece — not because it's optional. Phases A–C are shippable milestones that deliver the CRUD/list/detail/delete surface on their own; export is part of the engine's final surface.

### Deferred: app extraction

When a domain swap actually arrives, lift `catalog/engine/` to a top-level app. Because the intra-app contract already guarantees the engine imports nothing domain-specific, this is a `git mv` + an `INSTALLED_APPS`/spine entry — the decoupling this doc front-loads is exactly what makes it mechanical. The app's name (`entity_api`? `catalog_engine`?) is decided then, against a real second domain, not speculatively now.

## Critical files

- `apps/catalog/naming.py`, `apps/catalog/_walks.py`, `apps/catalog/_alias_registry.py`, `apps/catalog/models/base.py` (`AliasModel` move), `apps/catalog/api/schemas.py`, `apps/catalog/api/images.py` (Phase A)
- `apps/provenance/models/base.py` (new `LinkableLifecycleClaimModel`) + `apps/catalog/models/base.py` (re-parent `CatalogModel`) + in-place rebind of `apps/catalog/api/{entity_crud,entity_detail_page,entity_list,soft_delete,entity_create}.py` (Phase B)
- `apps/catalog/api/{entity_crud,entity_detail_page,entity_list,soft_delete,entity_create}.py` → `apps/catalog/engine/entity_api/` (Phase C)
- `apps/claim_edit/claim_write.py` (`get_field_constraints` + `FieldConstraintSchema`) + `config/api.py` field-constraints route → `apps/catalog/engine/entity_api/field_constraints/` (Phase C)
- `apps/catalog/api/export.py` → `apps/catalog/engine/export_api/` (transforms) + stays partial in catalog (registry) (Phase D)
- `backend/pyproject.toml` (extend `Catalog internal layers`, add the `catalog.engine` forbidden contract — Phase C), `docs/AppBoundaries.md`

## Verification

- After each phase: `make lint` (incl. `uv run lint-imports` — the intra-app contracts green, no new baselines), `make mypy`, and a step-scoped pytest (`apps/catalog apps/core apps/provenance apps/claim_edit`).
- **Phase B specifically:** `CatalogModel`'s re-parent migration is empty (`makemigrations` produces nothing) — proof the ABC insertion is a structural no-op; the full suite stays green with the registrars _still in `catalog/api/`_; and a `grep` confirms no symbol in `entity_create/entity_crud/entity_detail_page/entity_list/soft_delete` still names `catalog.models.CatalogModel` (only the `has_lifecycle` branches in create remain). This is what makes the Phase C relocation a pure move.
- After Phase C/D: **full** backend suite green (per-entity routers, signals, export, admin all reach `catalog/engine`); `make codegen` produces no consumer-facing route churn (wire URLs unchanged — the relocation is a code move, not a route change).
- End-to-end on a dev DB: a create, a scalar claim PATCH, a delete-preview/delete/restore, a detail page with own-media (a `MediaSupportedModel`) and with a borrowed thumbnail (e.g. Manufacturer), and a bulk export — all behaving identically to pre-move.
- Boundary complete when `lint-imports` enforces `catalog.engine ⊄ catalog-domain` (and `entity_api ⊄ export_api`), and the substrate tendrils (naming, alias, generic schemas, image helpers) no longer resolve into the catalog domain layer. At that point the [deferred app extraction](#deferred-app-extraction) is a `git mv`.

## Relationship to other docs

- **[ModelDrivenClaimWrite.md](ModelDrivenClaimWrite.md)** — sibling; extracted the write engines (`claim_edit`/`claim_ingest`) as their own apps. This builds the HTTP surface engine that consumes them, in place inside catalog, and picks up the read-side `get_field_constraints` endpoint that its Step 5 leaves parked in `claim_edit`.
- **[ModelDrivenApi.md](ModelDrivenApi.md)** — the declaration axis (model-declared `CatalogApiSpec`, generic route registry). Rides on top of this engine; independent. Once both land, a model declares its endpoints and the registry mounts them against the `engine/entity_api` registrars.
- **[ModelDrivenClaimResolution.md](ModelDrivenClaimResolution.md)** — the read-projection engine (`provenance/resolution/`); export's read path is its HTTP consumer.

## Out of scope

- Extracting `catalog/engine/` into its own top-level app — deferred to domain-swap time (see [Deferred: app extraction](#deferred-app-extraction)); the boundary work here is what makes it cheap then.
- The `CatalogApiSpec` declaration mechanism / killing per-entity route files (that's `ModelDrivenApi.md`).
- Converging the interactive relationship-claim planners onto the bulk registry (deferred per `ModelDrivenClaimWrite.md`).
- Genericizing the borrowed-thumbnail traversals — they stay domain hooks by design.
