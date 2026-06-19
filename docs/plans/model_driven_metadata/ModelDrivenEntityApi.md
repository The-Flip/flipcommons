# Model-Driven Entity API — a domain-neutral `engine/` inside catalog

## Context

One goal we have for Flipcommons is to make it the steel thread proving out a new, reusable category of collaborative encyclopedia wiki software. We want to be able to replace the catalog app with an entirely different domain than pinball -- like baseball or medicine -- to create an entirely different collaborative encyclopedia wiki on a different subject. Ideally we'd even have a low code / AI-driven layer that lets non-technical people do the data modeling, though that's in the future.

So we want to move everything that's not directly related to the pinball domain out of catalog, and ensure that no other app has anything about the pinball domain. This is basically the [ModelDrivenMetadata.md](ModelDrivenMetadata.md) vision.

[ModelDrivenClaimWrite.md](ModelDrivenClaimWrite.md) did this for the **write engines**, extracting `claim_edit` (interactive) and `claim_ingest` (bulk) as their own apps; [ModelDrivenClaimResolution.md](ModelDrivenClaimResolution.md) plans it for the **read projection**. This doc does it for the **HTTP surface**: the generic create / list / detail / delete-restore / export machinery currently smeared across `apps/catalog/api/`.

That machinery is already substantially domain-agnostic — it drives off `LinkableClaimModel`, `_meta`, the entity-type registry and capability markers, not concrete pinball models. But it's tangled with the domain through a handful of substrate helpers and a hard binding to `CatalogModel`, so nothing today enforces the boundary and a new domain can't reuse it.

**The boundary is drawn _inside_ catalog, for now.** The machinery becomes a domain-neutral `catalog/engine/` package, governed by the intra-app import-linter machinery that already polices catalog's internal stack: the exhaustive `Catalog internal layers` contract (a new submodule left unplaced fails the build) and the catalog-agnostic forbidden pattern that already keeps `catalog/resolve/` from importing the domain. `catalog/engine/` joins both — a layer in that stack, plus a forbidden contract asserting `engine ⊄ catalog-domain`.

The engine is built **in place**. Lifting it to its own top-level app is deferred to domain-swap time; the boundary work here is what makes that a `git mv` (see [Deferred: app extraction](#deferred-app-extraction)).

**Why in place, and why now.** Drawing the boundary before a second domain exists is a bet that the seam is in the right place. Two things de-risk it. The engine ships _behind an unchanged wire contract_ — every route URL is byte-identical pre/post — so a mis-cut seam is re-cuttable without consumer churn, and the sibling extractions (`claim_edit`/`claim_ingest`) already proved the same boundary shape one layer down. The residual bet — the exact engine ↔ domain line — is paid in import-linter contract edits, not in a premature top-level app, which is exactly why the extraction (and the app's name) waits for the real second domain that can pin the requirements.

**This is the boundary axis, not the declaration axis.** [ModelDrivenApi.md](ModelDrivenApi.md) is about models declaring _which_ endpoints they expose via a `CatalogApiSpec`, killing per-entity route files. That rides _on top of_ a clean generic engine — it assumes the registrars exist. This doc is what makes them domain-neutral first. The two are independent (either can land first) and synergistic.

## What it is

A domain-neutral `catalog/engine/` package owning the generic HTTP surface over any `LinkableClaimModel` (internal layout in [Package shape](#package-shape)):

- generic registrars: `register_entity_create`, `register_entity_delete_restore`, `register_entity_detail_page`, `paginated_list_response`
- the generic soft-delete engine (already delegating to `core.soft_delete` + `claim_edit.execute_multi_entity_claims`)
- the generic export transforms (schema-gen, serialization, link resolution) — domain registry stays catalog-side
- the generic request/response schema bases

Each registrar **binds the minimal capability base its surface needs** — a static type bound, with `issubclass` dispatch for the genuinely discovered capabilities — never concrete models:

- **list** → `Model` (the queryset is caller-injected; the fold needs nothing more).
- **detail** → `SitemappedModel` (`LinkableModel` + `LastUpdatedModel`). The registrar reads only `entity_type`, `public_id_field` and `lastmod_expression()` — it never touches claims, so claim-control is not in its bound. Keeping the polymorphic `model_cls.lastmod_expression()` call preserves `Title`'s freshness override for free.
- **create + delete / restore** → `LinkableLifecycleClaimModel` — a new ABC = `LifecycleStatusModel` + `LinkableClaimModel`. Soft-delete _is_ writing the `status` claim; create _also_ writes the `status` claim, stamps the `status` column, and filters collision/parent lookups through `.active()`. Lifecycle is a hard precondition for both, so making it a base turns what would otherwise be a runtime `AttributeError` smeared across the manager (`.active()`), the field (`.status`) and the operation's semantics into one compile-time error at the registration site. (Create is lifecycle-_bound_, not lifecycle-_optional_: today every creatable entity is a `CatalogModel`, so a non-lifecycle creatable entity is hypothetical — split the bound when a real one forces it.)
- `MediaSupportedModel` — discovered (gates own-media gallery + own thumbnail/hero).
- `has_lifecycle` stays a genuinely _discovered_ capability — but only for **cascade members** (a referrer may or may not be soft-deletable, and the walk branches on it), never for the delete root or create.

Outside `engine/`, catalog keeps every per-entity router that _calls_ these registrars, the export domain registry (`_build_registry`, `_annotate_*`, `_register`+router), the domain schema variants, the domain thumbnail hooks, and the concrete models + the `CatalogModel` base.

```text
catalog/<domain>   concrete models · CatalogModel · per-entity routers · export registry · thumbnail hooks
        │  routers mount the engine registrars; declare per-entity querysets/serializers/hooks
        ▼
catalog/engine/   (domain-neutral HTTP surface)
   register_entity_{create,delete_restore,detail_page} · paginated_list_response
   soft-delete engine · export transforms · generic schema bases
   binds Model (list) / SitemappedModel (detail) / LinkableLifecycleClaimModel (create, delete) / MediaSupportedModel (discovered)
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
    __init__.py        # import-light namespace (docstring only); public API is the family subpackages (see below)
    schemas.py         # cross-cutting wire bases (EntityRef, EntityDetailSchema, …), shared by both surfaces
    models.py          # AliasModel — the one generic catalog-level model base (flat module, not a package)
    aliases.py         # alias-type registry (AliasType, discover_alias_types, alias_type_for); injection-populated at ready()
    naming.py          # normalize_catalog_name + MAX_CATALOG_NAME_LENGTH
    walks.py           # generic app_subclasses(app_label, base); catalog keeps thin scoped wrappers in _walks.py
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

- **`engine/__init__.py` stays import-light; the public API is the family subpackages.** `__init__.py` carries only a docstring, and consumers import registrars directly from their family (`from …engine.entity_api.create import register_entity_create`) — the per-entity routers do exactly this, and a second-domain consumer imports the same subpackages at [app-extraction](#deferred-app-extraction) time. Keep it that way: `engine/__init__.py` is imported during Django model setup (`catalog/models/base.py` imports `engine.models.AliasModel` at class-definition time), so re-exporting the registrars there — which pull in `claim_edit` and the ninja routers — would risk an import cycle before the app registry is ready.
- **`entity_api/` vs `export_api/` = private vs public API surface.** The real seam is the private internal API (read + write, the site's own UI) vs the public API (own OpenAPI doc, rate limit, external stability contract) — the two `NinjaAPI` instances in `config/api.py`. Export is the public surface's sole resident _today_; the boundary is durable even though the label is concrete. They sit as sibling subpackages under `engine/`, split by audience/contract, enforced by an intra-app contract (`entity_api ⊄ export_api`; both may use `engine/schemas.py`). `export_api`'s _route registration_ stays domain-side in catalog while its transforms live here. If a second public surface appears, it joins `export_api`'s tier.
- **`engine/models.py` is a single flat module, not an `engine/models/` package.** The cross-layer bases (`LinkableClaimModel`, `LinkableLifecycleClaimModel`) live in `provenance`; `CatalogModel` is the bundle the _concrete domain_ models inherit, so it stays in `catalog/models/`. The engine is mostly code, not Django models — but `AliasModel` is the one generic catalog-level base that is neither a provenance cross-layer base nor domain-specific. It's the materialized projection target of alias claims (a denormalized lookup table, like the M2M through-tables, but generic to any encyclopedia); the alias _claim_ fold itself stays in provenance (`normalize_alias_identity`), since claims go down and target tables stay up. So it lands in a single flat `engine/models.py`, with its discovery registry beside it in `engine/aliases.py`. This is the reserved case finally taken; keep it a flat module, not a package, until a second generic base actually joins it.
- **`update/` is deliberately absent.** PATCH `.../claims/` is not yet consolidated — it's hand-wired in the catalog routers (calling `claim_edit` + the domain planners). A generic update registrar is `ModelDrivenApi.md`'s work; when it lands it slots in beside `create`/`delete` inside `entity_api/`.
- **No `cud/` / `read/` sub-grouping yet — by design.** create/update/delete _do_ share a mutation envelope, but the shared primitives already live one layer down (`ChangeSetInputSchema` in provenance, claim execution in `claim_edit`); the one engine-level shared thing — a unified mutation-registrar pipeline — does not exist today. Introducing `cud/`+`read/` now would mean near-empty shared modules. Deepen only when `update` lands _and_ a shared pipeline materializes; until then the families stay flat under `entity_api/`.
- **`detail/` is an honest thin package** (`__init__.py` only) — a single registrar that delegates serialization to a caller-injected hook. Not padded with a hollow `serialize.py` for symmetry.
- **`field_constraints/` is its own thin family, not folded into `create/`.** `get_field_constraints` feeds both the create form _and_ the (not-yet-consolidated) edit form, so it isn't create-specific — it's cross-cutting read-side field metadata. It migrates here from `claim_edit` during Phase C (`ModelDrivenClaimWrite.md` Step 5 leaves it in place precisely because this is its home).
- **`schemas.py` stays at `engine/` root** because the wire bases (`EntityRef`, the detail bases) are shared across both surfaces; only family-specific schemas (`EntityCreateInputSchema`, `BlockingReferrer`) live inside a family package.

## Findings that shape the plan

**1. The real work is rebinding the registrars off `CatalogModel` — not the file move.** Every registrar is billed as domain-agnostic but is actually bound to `catalog.models.CatalogModel`: type bounds (`register_entity_*[ModelT: CatalogModel]`), ~7 signatures `model_cls: type[CatalogModel]` in `entity_create.py`, and a runtime narrowing (`_require_catalog`, `isinstance(…, CatalogModel)`) in `soft_delete.py`. `catalog.engine` may import no catalog-domain symbol — and `CatalogModel` lives in `catalog/models/` — so this rebind, not the relocation into `engine/`, is the extraction. It is **not** mechanical, and it's mostly tractable once measured: `CatalogModel = DescribedModel + SitemappedModel + LifecycleStatusModel + LinkableClaimModel`, and the registrars never touch `.description`; of the sitemap branch only `detail` reaches in, for `lastmod_expression()` on `LastUpdatedModel`. The true per-surface minimal bound:

| Surface                               | Bind to                                 | Why                                                                                                                 |
| ------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `list`                                | `Model` (already)                       | looser than `LinkableClaimModel`; leave as-is                                                                       |
| `detail`                              | `SitemappedModel`                       | reads only `entity_type`/`public_id`/`lastmod_expression()` = `LinkableModel` + `LastUpdatedModel`; no claim access |
| `create`                              | `LinkableLifecycleClaimModel`           | writes the `status` claim + column and filters `.active()` — lifecycle is a precondition, not a refinement          |
| `delete_restore` + soft-delete engine | `LinkableLifecycleClaimModel` (new ABC) | soft-delete writes the `status` claim — lifecycle is a precondition                                                 |

Done in place (Phase B), the existing suite is a behavior-preserving oracle for each step.

**2. The two surfaces have nearly disjoint heavy deps.** `entity_api` → `claim_edit`, no media. `export_api` → `media`, no `claim_edit`. They share no code — only the introspection substrate (which lives below, in core/provenance). They co-locate in `engine/`, as sibling subpackages, because they're the same architectural tier (generic HTTP surface over `LinkableClaimModel`) split by **audience/contract** — private internal API vs public API — with an anticipated future edge (the public surface reusing the generic transforms). The seam is real but intra-package, enforced by an import-linter contract.

**3. Media is a model-driven capability, with one honest seam.** Of 4 `MediaSupportedModel`s (Person, Manufacturer, MachineModel, GameplayFeature):

- **Own media** — gallery (`serialize_uploaded_media(all_media(x))`) + own thumbnail/hero — is uniform across all four and gated purely on `issubclass(model, MediaSupportedModel)`. **The engine absorbs this; declaring the marker is enough.** This is the baseball-ready promise, and it holds exactly.
- **Borrowed/derived thumbnails** — Title→its Models, Manufacturer→its Models, Person→credited Models, Series→Titles→Models, Location→Manufacturers→entities — are bespoke domain traversals. **Irreducibly domain**; the engine exposes an optional `thumbnail_source(entity)` hook and catalog wires the per-entity paths. Not a `MediaSupportedModel` concern (Manufacturer borrows a display thumbnail but its own gallery is separate).

**4. The substrate tendrils all ride into `engine/` during relocation — none is a forced cross-app move.** Each tendril must leave the catalog-domain layer before `catalog.engine ⊄ catalog-domain` can pass. But _leaving the domain layer_ is not the same as _sinking to the lowest possible app_: with the engine living **inside** catalog, the default home for a severed tendril is `catalog/engine/` itself — generic-but-catalog-flavored code the domain imports downward, including a single `engine/models.py` for any generic catalog-level model base. A tendril sinks _below_ catalog only for one **standalone reason**: it already has a consumer living below catalog. (Being an abstract Django model is _not_ such a reason — that's what `engine/models.py` is for.) Everything rides into `engine/` during the Phase C `git mv` — it is **not** separate prerequisite work. (The pure media selectors that once sat among these were a separate, cohesion-driven matter, already sunk into the `media` app in Phase A.) This is the choice that keeps the substrate legible: the generic helpers stay in one app (catalog, stratified into `engine/`) rather than scattered across apps.

| Tendril                                                            | Reached by                         | Move                                                                                                       |
| ------------------------------------------------------------------ | ---------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| pure media selectors: `media_prefetch`, `serialize_uploaded_media` | export, per-entity routers         | **DONE** (Phase A) → `media/helpers.py` + new `media/selectors.py` (new `selectors` tier)                  |
| `catalog._alias_registry` + `AliasModel` abstract base             | entity_create, entity_list, export | rides into C → `engine/models.py` (base) + `engine/aliases.py` (registry); _not_ provenance — see Phase C  |
| `catalog.naming.normalize_catalog_name` (5 importers)              | entity_create + 3 catalog routers  | rides into C → `engine/naming.py` (no below-catalog consumer; `core` only if one appears)                  |
| `_walks._catalog_app_subclasses`                                   | entity_create, entity_list, export | rides into C → generic `app_subclasses` in `engine`; catalog keeps thin scoped wrappers                    |
| `catalog.api.schemas` generic bases                                | entity_crud, soft_delete           | rides into C → `engine/schemas.py` (split out of the domain variants)                                      |
| `extra_data` extractors (`extract_image_*`)                        | export transforms                  | rides into E → `engine/export_api` (carry catalog's third-party-image convention, not media-storage logic) |
| `catalog.cache` export response-cache                              | export `_register` only            | **no move** — `_register` stays domain-side and calls the moved transforms                                 |

**5. Export splits at one clean line; cache is a non-issue.** Generic transforms (`_build_schema`, `_build_qs`, `_serialize_row`, `_serialize_relation`, `_serialize_description`, link resolution, `_scalar_py_type`, `ExportSpec`/`RelationSpec`/`DerivedField`, `EntityExportSchema`/`DescriptionExportSchema`, rate-limit spec) → `engine/export_api`. Domain (`_build_registry`, `_annotate_*`, `CreditExportSchema`, `_register` + `export_router` + cache, `EXPORT_ENTITY_TYPES`) → stays in catalog. The transforms call `extract_image_urls`/`extract_image_attribution`, which carry `extra_data` schema knowledge and therefore land in `engine/export_api` too — _not_ the low media tier (see Finding 4 and Phase E).

## Phasing

Each phase is its own commit (or small commit series). 🛑 STOP for user review before committing each. Phases A (the media-selector cohesion move), the in-place `CatalogModel` rebind (B), the relocation into `engine/` (C) and the delete-preview de-domaining (C2) are **done**; the engine owns its full private HTTP surface (create / list / detail / delete-restore / field-constraints) behind the `Engine internal layers` and `catalog.engine ⊄ catalog-domain` contracts, with no domain-named wire shapes left in it. Two phases remain. D (own-media in detail/list) is a behavior-restructuring refactor with a weaker oracle than C's pure moves. E moves the export engine last, as the most domain-entangled piece. A sub-step that stays green on the full suite is its own commit.

### ✅ DONE: Phase A — sink the pure media selectors out of catalog

Moved the two pure media-storage selectors that lived in `catalog/api/images.py` by accident of history into the `media` app, where they belong on **cohesion** grounds (zero catalog-domain knowledge):

- `media_prefetch` → `media/helpers.py` (model-tier; no contract change — it joins its existing sibling `all_media`).
- `serialize_uploaded_media` → new `media/selectors.py`, a new `selectors` tier _above_ `{storage,schemas}` in the "Media internal layers" contract (it composes both into `UploadedMediaSchema`, which the peer-isolated `helpers` tier may not). Also added the previously-omitted `helpers` and the new `selectors` to the "Media internals do not reach into the data apps" contract, and updated `docs/AppBoundaries.md` to match.

`_uploaded_image_urls` stayed in catalog with its sole caller `extract_image_urls` (which rides into `engine/export_api` in Phase E). The domain fetchers `fetch_model_media_map`, `fetch_title_media_map`, `first_thumbnail` import concrete models → stay catalog as thumbnail-hook inputs. This move was independently shippable and not a precondition for the engine.

### ✅ DONE: Phase B — decouple the registrars from `CatalogModel` (the big rock)

The actual extraction (Finding 1). Do it **in place, inside `catalog/api/`, before relocating anything into `engine/`**: behavior must not change, so the existing full suite is a behavior-preserving oracle, and each step is a ~20-line diff whose failure is unambiguous — an oracle you'd lose if a file move and import churn rode along in the same commit. Sequenced smallest-gap-first so the approach is proven on the cheap cases before the hard one:

1. **Introduce the delete base.** Add `LinkableLifecycleClaimModel(LifecycleStatusModel, LinkableClaimModel)` to `provenance/models/base.py` (provenance sits below catalog and already pairs the two ingredients in `LinkableClaimModel`). Re-parent `CatalogModel` onto it: `CatalogModel(DescribedModel, SitemappedModel, LinkableLifecycleClaimModel)`. **Base order matches `CatalogModel`'s current declaration**, so its **field layout, default manager and inherited constraints are byte-identical** — a structural no-op, confirmed by an empty migration. Precisely: the MRO is _not_ byte-identical — it gains one entry, the new combined ABC — but that entry declares no fields, no manager and no constraints, so nothing migration-visible or resolution-visible changes; the leaf order (`DescribedModel`, `SitemappedModel`, then `LifecycleStatusModel`, `LinkableClaimModel` via the combined base) is preserved. Because this re-parents a base that **every** concrete catalog model inherits, the no-op claim is verified, not assumed: `makemigrations` produces nothing, each concrete subclass's own `status_valid()` `Meta` constraint still resolves (the abstract parent's constraints are not inherited when a subclass declares `Meta`, so they must already be local — confirm), and the `check_soft_delete_policy` system check stays green. (Name order ≠ base order, deliberately; the `…ClaimModel` suffix keeps it in the family. The combined ABC linearizes safely because only `LifecycleStatusModel` declares a manager — the whole `LinkableClaimModel` chain declares none — so `.active()` survives regardless of order, and `CatalogModel` redeclares `objects` itself in any case.)
2. **`list`** — already bound to `Model`; confirm no-op.
3. **`detail_page`** — bind to `SitemappedModel` (`LinkableModel` + `LastUpdatedModel`). The body reads only `entity_type`, `public_id_field` and `model_cls.lastmod_expression()`; it never touches claims, so claim-control is not in the bound. `lastmod_expression()` lives on `LastUpdatedModel`, absent from `LinkableClaimModel`'s MRO — but present in `SitemappedModel`, which every detail-served entity already inherits via `CatalogModel`. Keep the polymorphic `model_cls.lastmod_expression()` call so `Title`'s child-Model freshness override keeps working with no per-caller wiring. (`SitemappedModel` carries a sitemap-membership connotation it doesn't strictly need; a thin `LinkableModel + LastUpdatedModel` ABC would be marginally more honest but isn't worth a new class today.)
4. **`create`** — the registrar _surface_ (`register_entity_create`, `_do_create`, `parent_model` in `entity_crud.py`) binds `LinkableLifecycleClaimModel`. Create is lifecycle-_bound_, not lifecycle-_optional_, so there is **no `has_lifecycle` branching**: beyond the two `.active()` lookups (the duplicate-name guard and `parent_model.objects.active()`), `_do_create` stamps the `status` column and writes a `status` claim on every create, and the alias scan filters `parent__status=active`. All five sites are valid under the lifecycle bound, which keeps the surface's bound truthful (it writes the status claim). The create _primitives_ in `entity_create.py`, by contrast, each take their **own** minimal bound rather than the surface's — only give each what it needs: `_resolve_alias_relation` → `Model` (reads `_meta` only); `assert_name_available` → `LifecycleStatusModel` (`.active()`); `assert_public_id_available` → `IdentifiableModel` (`public_id` + `.filter()`); `create_entity_with_claims` → generic `[M: LinkableClaimModel] → M` (claim write, no lifecycle; returns the concrete type so callers need no cast). `validate_create_input` is the one that stays at `LinkableLifecycleClaimModel`: it needs both addressing (`entity_type`) and lifecycle (it delegates to `assert_name_available`), and no leaner base conjoins the two — tightening it would mean inventing an ABC for a single caller, the one place tightening would externalize a cost. Today every creatable entity is a `CatalogModel`, so a non-lifecycle creatable entity is hypothetical; when a real one appears, split the surface's bound then, against that model rather than a throwaway. A docstring note in `register_entity_create` records this.
5. **`delete_restore` + soft-delete engine** — rebind `register_entity_delete_restore`, `plan_soft_delete`, `execute_soft_delete` from `CatalogModel → LinkableLifecycleClaimModel` (`count_entity_changesets` needs only `LinkableClaimModel` — it touches `.pk` and claims, not lifecycle). `_require_catalog` **retargets** to the new base (rename to `_require_linkable_lifecycle`) — it does **not** disappear: `soft_delete_walk` returns `LifecycleStatusModel`-typed members, and narrowing those to `LinkableLifecycleClaimModel` is a downcast (a `LifecycleStatusModel` is not statically linkable or claim-controlled), so the runtime `isinstance` boundary assert stays, just against the new base.

After Phase B, no registrar references `catalog.models.CatalogModel`; the files still live in `catalog/api/`, still mounted by the same per-entity routers, still green on the full suite. The relocation that follows is then a pure `git mv`.

### ✅ DONE: Phase C — relocate the generic registrars into `catalog/engine/entity_api/`

With Phase A done and the registrars rebound (B), move them under `engine/` — an intra-catalog `git mv` + import repoint, then flip the layered contract on. The remaining substrate tendrils are severed by this same move (they carry no below-catalog consumer, so landing in `engine/` is all it takes — see below). **C is a pure relocation**: every wire URL is byte-identical pre/post, so the full suite is an exact oracle. The own-media consolidation that once rode here is split out to Phase D precisely to keep that guarantee — it is a behavior-restructuring refactor, not a move, with a weaker oracle, and it is _not_ a precondition for the boundary (`catalog.engine ⊄ catalog-domain` passes with own-media left caller-injected in the domain routers). Source → destination follows [Package shape](#package-shape):

- Move the families: the create registrar `register_entity_create` (in `entity_crud.py`) + its helpers (`entity_create.py`) → `engine/entity_api/create/`; the delete registrar `register_entity_delete_restore` (in `entity_crud.py`) + the `soft_delete.py` engine/wire types → `engine/entity_api/delete/`; `entity_detail_page.py` → `engine/entity_api/detail/`; `entity_list.paginated_list_response` + list-query helpers → `engine/entity_api/listing/` (the generic list-query fold may instead land in `engine/query/`). Note `entity_crud.py` houses _both_ registrars, so it splits across `create/` and `delete/` rather than moving as a unit.
- **The rides-into-C substrate moves with them** (Finding 4). This is generic catalog substrate with no below-catalog consumer, so it leaves the catalog-domain layer simply by landing in `engine/` during this `git mv` — **not** separate prerequisite work:
  - **alias subsystem** → `engine/models.py` (the `AliasModel` abstract base) + `engine/aliases.py` (the registry: `AliasType`, `discover_alias_types`, `alias_type_for`). The subtlety: **provenance is already alias-aware, but on the _claim_ side, not the _table_ side** — and those are different layers. Provenance owns the alias _claim_ fold (`normalize_alias_identity` / `AliasIdentity` in `provenance/claims.py`, the `alias_value`/`alias_display`/`display_key` value-key semantics in `provenance/validation.py`), which both write paths (`catalog.edit_claims`, `claim_ingest.patches.emit`) call so an editor alias and a patch alias yield byte-identical claims. That stays in provenance — it is claim semantics. `AliasModel`, by contrast, is the **materialized projection target** of those claims (a `value` column + FK + `Lower("value")` unique, built _from_ `alias_value` claims by the alias resolver) — the same category as the M2M through-tables, which [ModelDrivenClaimResolution.md](ModelDrivenClaimResolution.md) classifies as schema that stays up ("you cannot hoist the schema"); claims go down, target tables don't. Homing the table ABC in provenance would invert the projection — provenance would define the shape of a table catalog materializes _from_ provenance's claims. So the table ABC is generic catalog substrate, exactly the "generic catalog-level base, not a provenance cross-layer base, not domain-specific" that [Package shape](#package-shape) reserves `engine/models.py` for. The generic engine binds it (`entity_create` does `issubclass(related_model, AliasModel)`; `entity_list`'s `q`-fold reads `alias_type_for`); `engine/aliases.py` imports `provenance.ClaimControlledModel` downward for parent validation. The literal `AliasModel` class is imported only by catalog today (provenance's two references are comments describing the resolver), so this is a clean descent into `engine/`, not a cross-app move. Concrete alias models (`ThemeAlias`, …) stay in `catalog/models` and subclass engine's base (domain → engine, the sanctioned direction); their `Lower("value")` constraint must keep agreeing with provenance's lowercase fold — the documented invariant that already spans those two layers, unchanged. Confirm none is named in the abstract definition, and that re-homing the base produces **no migration** (it owns no table). This is the asymmetry with `CatalogModel`, which stays domain-side: after Phase B nothing generic binds `CatalogModel`, whereas the engine genuinely binds `AliasModel`.
  - **`catalog.naming`** (`normalize_catalog_name` + `MAX_CATALOG_NAME_LENGTH`) → `engine/naming.py`. Every importer is in `catalog/api/` (which becomes engine); nothing below catalog reads it, so `core` would only push English article-stripping (`the/a/an`) into the universal foundation for no resident consumer. Promote to `core` only if one ever appears. The frontend mirror that must stay in lockstep is a codegen concern, not a backend consumer.
  - **walk introspection** — the generic `app_subclasses(app_label, base)` form of `_walks._catalog_app_subclasses` lands in `engine`; catalog keeps thin scoped wrappers that import it downward.
  - **generic schema bases** — split EntityRef, the detail bases (LinkableDetailSchema, DescribedDetailSchema, LastModifiedDetailSchema, CatalogDetailSchema→rename EntityDetailSchema) and the patch bases (EntityCreateInputSchema, ClaimPatchSchema, HierarchyClaimPatchSchema) out of `catalog.api.schemas` → `engine/schemas.py`. Domain variants (ModelClaimPatchSchema, TitleClaimPatchSchema, …) stay in catalog.
  - **`extra_data` extractors** (`extract_image_urls`, `extract_image_attribution`) ride to `engine/export_api` in Phase E, alongside the transforms that call them — _not_ the low media tier: they reach into external-source keys (`opdb.images`, `ipdb.image_urls`, `.__permissiveness_rank`, `.__license_slug`), the catalog's third-party-image provenance convention, and sinking them into media would invert the dependency and drag `core.licensing` + `provenance.schemas.AttributionSchema` down too.
- **Absorb the field-constraints read endpoint.** Move `get_field_constraints` + `FieldConstraintSchema` out of `claim_edit` (where `ModelDrivenClaimWrite.md` Step 5 parked them as the read-side outlier) into `engine/entity_api/field_constraints/`, and repoint the `GET /field-constraints/{entity_type}` route in `config/api.py`. Model-driven numeric-constraint introspection over any `LinkableClaimModel` — the read sibling of the create form, out of place in a write engine. Pure code move; the wire URL is unchanged.
- Own-media serialization stays where it is — woven into the per-entity `serialize_detail`/`serialize_row` hooks in the domain routers. The detail/list registrars are already schema-agnostic (serialization is fully caller-injected), so they relocate untouched and the boundary holds with media domain-side. Consolidating own-media _into_ the registrar is Phase D, not this move.
- catalog's per-entity routers keep mounting the registrars and passing querysets/serializers/hooks; only import paths change.
- **Contract:** this is an edit to the existing exhaustive `Catalog internal layers` contract, not just an append — `naming` and `_alias_registry` **leave** the catalog layer list (they emigrate into `engine`), `_walks` is gutted to thin scoped wrappers, and `engine` joins as the **bottom** layer (below `models | authz`: concrete alias models in `catalog/models/` subclass `engine`'s `AliasModel`, so `models → engine`). Add a forbidden contract `catalog.engine ⊄ catalog-domain`, mirroring the resolver-core rule. Add a second exhaustive contract, `Engine internal layers`, over `engine`'s own subtree (`entity_api` / `export_api` / `query` on top; `schemas | models | aliases | naming` at the base) so a new engine submodule left unplaced fails the build — the same ratchet the catalog/core contracts apply. The `entity_api ⊄ export_api` seam lands in Phase E, when `export_api` exists. Record the additions in `docs/AppBoundaries.md`. No `INSTALLED_APPS`/spine change — this is one app.

### ✅ DONE: Phase C2 — de-domain the delete registrar's preview schema

`register_entity_delete_restore` is schema-agnostic on its detail / listing / restore paths (each takes an injected serializer or `response_schema`), but its delete-preview path constructed `TaxonomyDeletePreviewSchema` inline — a domain-_named_ schema that emigrated into `engine/` in Phase C while its siblings (`ModelDeletePreviewSchema` / `PersonDeletePreviewSchema` / `TitleDeletePreviewSchema`) correctly stayed domain-side. `lint-imports` couldn't see it because the name is _defined_ in the engine, not _imported_ (the "string, not an import" gap the [Boundary](#boundary) section warns about).

**The defect was nominal, not structural — so the fix was a rename, not a caller-injection seam.** An earlier draft of this phase added a `preview_schema` + `serialize_preview` pair to the registrar and pushed the schema domain-side (mirroring restore's `response_schema`). But the registrar _already_ constructs three other generic engine schemas inline without injecting them — `DeleteResponseSchema`, `SoftDeleteBlockedSchema`, `AlreadyDeletedSchema` — and the preview's shape is exactly as generic: `name` / `slug` / `changeset_count` / `blocked_by`, plus `parent` (a generic entity ref) and `active_children_count` (a generic tree count). Nothing pinball; the only thing wrong was the word "Taxonomy" in the name (Manufacturer and CorporateEntity route through it and aren't taxonomy). The injection seam would have had exactly **one** implementation, too: the entities that need a _different_ preview (Model / Person / Title) also need _different blocking logic_, so they hand-roll their whole delete route and never touch the registrar — injecting the preview alone wouldn't pull them onto it. The seam guarded a hypothetical that can't materialize.

What landed:

- `TaxonomyDeletePreviewSchema` → `EntityDeletePreviewSchema`, kept in `engine/entity_api/delete/schemas.py`, still constructed inline by the registrar — consistent with how it already treats `DeleteResponseSchema` et al. A docstring records why the generic shape stays engine-side.
- The dead re-export in `catalog/api/schemas.py` (no domain router imported the name) was dropped rather than carried.
- The nine callers (themes, locations, systems, series, corporate_entities, franchises, gameplay_features, manufacturers, taxonomy) are untouched — no signature change reached them. After C2 the engine holds **zero** domain-named wire shapes.

The trade is the inverse of the wire-identical injection path: the rename **does** churn the OpenAPI component name and the generated frontend types (a one-time `make codegen`), but the response _body_ is byte-identical (same fields, same values) and the frontend delete-flow consumes the shape structurally (`blocked_by`, `active_children_count`), so nothing downstream broke. Verified: backend delete/restore suite green, `mypy` clean, `lint-imports` 17/17 (engine now domain-name-free), frontend vitest + `svelte-check` green. Was a sibling of D over a different registrar; independent of D and E, its own commit.

### Phase D — consolidate own-media into the detail/list registrars

The one behavior-restructuring step, split out of the C relocation so each stays cleanly oracle-able. Today own-media is woven into every per-entity `serialize_detail` (e.g. `uploaded_media=serialize_uploaded_media(all_media(x))`) and the list `thumbnail_provider` hook. This consolidates the **automatic** case into the engine: the registrar serializes own-media when `issubclass(model, MediaSupportedModel)` (calling `media.selectors`) and exposes an optional `thumbnail_source(entity)` hook for borrowed thumbnails, into which catalog's per-entity specs pass the domain traversal (`fetch_model_media_map`, `fetch_title_media_map`, `first_thumbnail`). Derived thumbnails stay domain-owned (Finding 3's honest seam).

**Pin the injection design — the registrar must not mutate the caller's schema.** The current registrars are deliberately schema-agnostic; the consistent way to absorb media is to _precompute_ it and pass it into the serializer hook, exactly as `paginated_list_response` already passes `serialize_row(row, thumbnail)`. So detail's hook gains a media argument (`serialize_detail(obj, media_ctx)`) rather than the registrar reaching into the returned `Schema` to set `uploaded_media`. This is a signature change across the ~13 detail serializers — which is exactly why it's a refactor, not a move.

The suite is a **weaker oracle** here than for the C moves (it proves the wire output unchanged, not that the wiring is reshaped correctly), so verify own-media and borrowed-thumbnail output per entity against pre-move (see [Verification](#verification)). Independent of Phase E; either can land first. (May instead fold into `ModelDrivenApi.md`, where a uniform `uploaded_media` detail field would be model-declared — noted, not required.)

### Phase E — export engine into `catalog/engine/export_api/` (last; most entangled)

Move the generic transforms (Finding 5) plus the `extra_data` extractors (`extract_image_urls`/`extract_image_attribution`, per Finding 4) into `engine/export_api/`. `_build_registry`, `_annotate_*`, `CreditExportSchema`, `_register`, `export_router` and cache wiring stay in catalog — they hand-list the concrete models, so they're domain, exactly like a per-entity router. catalog's `_register` calls the moved transforms (downward, domain → engine); the transforms import `media.{models,selectors}` for the own-image branches. Add the `entity_api ⊄ export_api` seam to the `Engine internal layers` contract now that `export_api` exists.

**Add `export_api` as a sibling of `entity_api` on the `Engine internal layers` top tier** — `"entity_api | export_api"`. A layers `|` forbids mutual import, which _is_ the `entity_api ⊄ export_api` seam (both still reach down to `engine/schemas.py`); no separate forbidden contract is needed unless an _asymmetric_ allowance ever appears.

**Relocate the export schemas without renaming them.** `EntityExportSchema` / `DescriptionExportSchema` etc. are route-response → OpenAPI components, so a rename churns frontend codegen and breaks the pure-move guarantee. Move the classes, leave the component names alone — a slightly domain-flavored name in the engine is the right trade.

Sequenced **last** because it's the most domain-entangled piece — not because it's optional. Phases A–C are shippable milestones that deliver the CRUD/list/detail/delete surface on their own; export is part of the engine's final surface.

### Deferred: app extraction

When a domain swap actually arrives, lift `catalog/engine/` to a top-level app. Because the intra-app contract already guarantees the engine imports nothing domain-specific, this is a `git mv` + an `INSTALLED_APPS`/spine entry — the decoupling this doc front-loads is exactly what makes it mechanical. The app's name (`entity_api`? `catalog_engine`?) is decided then, against a real second domain, not speculatively now.

**The extracted surface is incomplete until `ModelDrivenApi.md` lands.** This doc's engine covers create / list / detail / delete-restore / export, but **not** `update` — PATCH `.../claims/` stays hand-wired in the catalog routers (see [Package shape](#package-shape)'s "`update/` is deliberately absent"). So a second domain reusing the extracted engine would still hand-wire its edit path until the generic update registrar arrives. The two docs are independent and either can land first, but the _reuse_ payoff this doc front-loads is only fully realized once both have. State that plainly rather than implying extraction alone delivers a complete reusable HTTP surface.

## Critical files

- ✅ Phase A (done): `media_prefetch` from `apps/catalog/api/images.py` → `apps/media/helpers.py`; `serialize_uploaded_media` → new `apps/media/selectors.py`; `selectors` tier + `helpers`/`selectors` data-app guards added to `backend/pyproject.toml`; `docs/AppBoundaries.md` updated
- Rides into C, not separate work: `apps/catalog/_alias_registry.py` + `AliasModel` from `apps/catalog/models/base.py` → `apps/catalog/engine/{aliases,models}.py`; `apps/catalog/naming.py`; `apps/catalog/_walks.py` (generic `app_subclasses`); generic bases in `apps/catalog/api/schemas.py` → `apps/catalog/engine/`
- `apps/provenance/models/base.py` (new `LinkableLifecycleClaimModel`) + `apps/catalog/models/base.py` (re-parent `CatalogModel`) + in-place rebind of `apps/catalog/api/{entity_crud,entity_detail_page,entity_list,soft_delete,entity_create}.py` (Phase B)
- `apps/catalog/api/{entity_crud,entity_detail_page,entity_list,soft_delete,entity_create}.py` → `apps/catalog/engine/entity_api/` (Phase C)
- `apps/claim_edit/claim_write.py` (`get_field_constraints` + `FieldConstraintSchema`) + `config/api.py` field-constraints route → `apps/catalog/engine/entity_api/field_constraints/` (Phase C)
- `apps/catalog/api/export.py` → `apps/catalog/engine/export_api/` (transforms) + stays partial in catalog (registry) (Phase E)
- `backend/pyproject.toml` (edit `Catalog internal layers` — drop `naming`/`_alias_registry`, add `engine` as bottom layer; add the `catalog.engine ⊄ catalog-domain` forbidden contract and the `Engine internal layers` exhaustive contract — Phase C; add the `entity_api ⊄ export_api` seam — Phase E), `docs/AppBoundaries.md`

## Verification

- After each phase: `make lint` (incl. `uv run lint-imports` — the intra-app contracts green, no new baselines), `make mypy`, and a step-scoped pytest (`apps/catalog apps/core apps/provenance apps/claim_edit`).
- **Phase B specifically:** `CatalogModel`'s re-parent migration is empty (`makemigrations` produces nothing) — proof the ABC insertion is a structural no-op; the full suite stays green with the registrars _still in `catalog/api/`_; and a `grep` confirms no symbol in `entity_create/entity_crud/entity_detail_page/entity_list/soft_delete` still names `catalog.models.CatalogModel`. This is what makes the Phase C relocation a pure move.
- After Phase C (and again after D/E): **full** backend suite green (per-entity routers, signals, export, admin all reach `catalog/engine`); `make codegen` produces no consumer-facing route churn (wire URLs unchanged — the relocation is a code move, not a route change). For C the suite is an **exact** oracle (pure move); for the D media refactor it proves only that wire output is unchanged, not that the wiring is correctly reshaped — hence the per-entity own-media/borrowed-thumbnail spot-checks below.
- End-to-end on a dev DB: a create, a scalar claim PATCH, a delete-preview/delete/restore, a detail page with own-media (a `MediaSupportedModel`) and with a borrowed thumbnail (e.g. Manufacturer), and a bulk export — all behaving identically to pre-move.
- Boundary complete when `lint-imports` enforces `catalog.engine ⊄ catalog-domain` (and `entity_api ⊄ export_api`), and the substrate tendrils (naming, alias, generic schemas, image helpers) no longer resolve into the catalog domain layer. At that point the [deferred app extraction](#deferred-app-extraction) is a `git mv`.
- **During file-heavy moves, trust `mypy .` over the daemon.** The pre-commit `dmypy` daemon can cache a moved symbol's _old_ module identity and report false `incompatible type` / `has no attribute` errors a fresh non-daemon `mypy .` doesn't. If a type error names a module you just relocated, `uv run dmypy stop` (it cold-starts next run) and re-check before chasing it.

## Relationship to other docs

- **[ModelDrivenClaimWrite.md](ModelDrivenClaimWrite.md)** — sibling; extracted the write engines (`claim_edit`/`claim_ingest`) as their own apps. This builds the HTTP surface engine that consumes them, in place inside catalog, and picks up the read-side `get_field_constraints` endpoint that its Step 5 leaves parked in `claim_edit`.
- **[ModelDrivenApi.md](ModelDrivenApi.md)** — the declaration axis (model-declared `CatalogApiSpec`, generic route registry). Rides on top of this engine; independent. Once both land, a model declares its endpoints and the registry mounts them against the `engine/entity_api` registrars.
- **[ModelDrivenClaimResolution.md](ModelDrivenClaimResolution.md)** — the read-projection engine (`provenance/resolution/`); export's read path is its HTTP consumer.

## Out of scope

- Extracting `catalog/engine/` into its own top-level app — deferred to domain-swap time (see [Deferred: app extraction](#deferred-app-extraction)); the boundary work here is what makes it cheap then.
- The `CatalogApiSpec` declaration mechanism / killing per-entity route files (that's `ModelDrivenApi.md`).
- Converging the interactive relationship-claim planners onto the bulk registry (deferred per `ModelDrivenClaimWrite.md`).
- Genericizing the borrowed-thumbnail traversals — they stay domain hooks by design.
