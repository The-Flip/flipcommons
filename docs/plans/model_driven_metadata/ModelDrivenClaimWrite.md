# Claim Write Engines

## Context

One goal we have for Flipcommons is to make it the steel thread proving out a new, reusable category of collaborative encyclopedia wiki software. We want to be able to replace the catalog app with an entirely different domain than pinball -- like baseball or medicine -- to create an entirely different collaborative encyclopedia wiki on a different subject. Ideally we'd even have a low code / AI-driven layer that lets non-technical people do the data modeling, though that's in the future.

So we want to move everything that's not directly related to the pinball domain out of catalog, and ensure that no other app has anything about the pinball domain. This is basically the docs/plans/model_driven_metadata/ModelDrivenMetadata.md vision.

This particular plan is about rationalizing the surface area of writing claims -- both bulk (ingest) and interactive -- which is currently smeared across catalog and other apps.

## What it is

Two domain-agnostic claim-write engines, `claim_edit` and `claim_ingest`:

- **`claim_edit`** — the **interactive** authoring surface. A user edits one entity through the HTTP api; the domain endpoint resolves the entity and builds `ClaimSpec`s, then `claim_edit` writes them as an attributed `ChangeSet`, validates scalar fields, attaches citations and triggers resolution. It binds the loose `ClaimControlledModel` — its caller has already resolved the row, so it needs nothing about addressing.
- **`claim_ingest`** — the **bulk** pipeline. A YAML data patch is compiled to an `IngestPlan` IR and applied in batches. It resolves `entity_type:public_id` references out of patch text, so it binds `LinkableClaimModel` (addressable + claim-controlled).

They share **no code** — two independent implementations of "write claims" (per-edit `ChangeSet` vs. batched `bulk_create`). What they share is the **provenance substrate** both write through: the claim/`ChangeSet` model, the claim helpers (`build_relationship_claim`, `get_claim_fields`), the resolve-dispatch seam, and the `LinkableClaimModel` target contract. Neither knows pinball — no `MachineModel`, no concrete catalog class; they reach concrete behavior only through model-driven interface points (base-class ClassVars, the relationship-schema registry, the resolve seam).

```text
claim_edit:    HTTP edit  → (domain resolves entity + builds ClaimSpecs) → write ChangeSet+claims → resolve seam
claim_ingest:  YAML patch → IngestPlan IR → batched apply (bulk_create)  → resolve seam
```

That makes the write surface reusable. Pair `claim_edit` + `claim_ingest` with a different domain — baseball, medicine — and you have a different encyclopedia with the same live-edit path, bulk patch path, audit trail and patch format. The domain app owns the concrete schema, the per-relationship spec-builders and the materialization of derived fields; the engines own the writes.

## Target architecture

```text
catalog (domain)
   concrete models · concrete resolvers · HTTP endpoints
   per-relationship spec-builders (credit, theme, gameplay-feature, abbreviation, m2m, parent, alias)
        │  endpoints resolve the entity, build ClaimSpecs, call claim_edit
        ▼
claim_edit (interactive)            claim_ingest (bulk)        ← independent peers, share no code
   execute_claims,                     patches/ (compiler)
   execute_multi_entity_claims,        plan.py  (IngestPlan IR)
   ClaimSpec, scalar planning          apply/   (batched persist)
   + validation                        ingest_patches / pull_patches
   binds ClaimControlledModel          binds LinkableClaimModel
        │                                   │
        └────────────────┬──────────────────┘
                         ▼
provenance                                  core
   claim & ChangeSet model · revert            entity vocabulary (Linkable/Identifiable/
   LinkableClaimModel (target contract)        Lifecycle bases, entity registry)
   relationship-schema registry                soft-delete cascade walk
   resolve-dispatch registry · IngestRun        structured-error infra
   citation: sources, cites
```

Who owns what:

- **core** — the entity vocabulary (`LinkableModel` / `IdentifiableModel` / `LifecycleStatusModel`, the `entity_types` registry), the soft-delete cascade **walk** (`cascade_targets`, `soft_delete_walk`, `has_lifecycle`, `require_linkable`), and shared structured-error infra (`StructuredApiError`, and `StructuredValidationError` relocated here).
- **provenance** — the claim data model and the operations closed over it: claims, ChangeSets, audit, `revert`, `IngestRun`, the relationship-schema registry, the resolve-dispatch registry, and **`LinkableClaimModel`** — the addressable-claim-subject contract that `claim_ingest` binds and catalog's models inherit. Stays the substrate both engines write through.
- **citation** — sources and cites.
- **claim_edit** — the interactive write surface (`execute_claims`, `execute_multi_entity_claims`, `ClaimSpec`, the generic scalar planning + validation, field-constraints). Binds `ClaimControlledModel`; HTTP-aware (raises 422s). Consumed by the domain's endpoints.
- **claim_ingest** — the bulk pipeline (`patches/` compiler, `plan.py` IR, `apply/` persist, the `ingest_patches` / `pull_patches` commands). Binds `LinkableClaimModel`. Driven by management commands.
- **catalog** — the domain: concrete models (inherit `LinkableClaimModel`), the concrete resolvers (`Credit`, theme tables, abbreviations, …) registered into provenance's resolve seam at `ready()`, the HTTP endpoints (call `claim_edit`), and the per-relationship spec-builders that know concrete shapes (`plan_credit_claims`, `plan_gameplay_feature_claims`, `plan_m2m_claims`, `plan_abbreviation_claims`, `plan_parent_claims`, `plan_alias_claims`).

**Why `LinkableClaimModel` lives in provenance.** It's a contract two consumers share — `claim_ingest` (binds it to resolve `entity_type:public_id` references) and catalog's models (inherit it) — and provenance is the only layer that sees both bases (`LinkableModel` from core, `ClaimControlledModel` from provenance). With no shared engine app to host it, provenance is its natural home. Note `claim_edit` does **not** bind it: addressing is the caller's job, so the interactive write function needs only `ClaimControlledModel`.

**Explicit non-goal — and the seam to watch.** "Share no code" holds for the engines' _own_ code, but both ride a substantial shared provenance/core substrate (`LinkableClaimModel`, the relocated claim helpers, the resolve seam). The one place the "two independent engines" framing is genuinely aspirational is **relationship-claim construction**: the bulk path builds relationship claims model-drivenly via `build_relationship_claim` + the schema registry; the interactive path builds them with hand-written per-relationship planners. Converging the two onto the registry approach is a separate refactor, explicitly **out of scope** — for now the domain keeps its hand-written planners and feeds `ClaimSpec`s to `claim_edit`. That divergence is where the framing would first strain, so it's the seam to watch, not a thing to dissolve here. The read-side counterpart of this same per-relationship hand-coding — the resolvers — is analyzed in [ModelDrivenClaimResolution.md](ModelDrivenClaimResolution.md); the spec a converged write/resolve path would consume is designed in [ModelDrivenCatalogRelationshipMetadata.md](ModelDrivenCatalogRelationshipMetadata.md).

**Independence — three boundaries, all top-level.**

- `claim_edit` and `claim_ingest` depend on the substrate — provenance, core, **accounts** (`claim_edit` needs `User` for `ChangeSet.user`, the same dependency `provenance.revert` already has), and citation (`claim_ingest`'s `sources:`/`cites:` support) — and **never catalog, never each other**. Two independent write surfaces over a shared substrate.
- catalog imports `claim_edit` (live edits) and provenance (`LinkableClaimModel`) — but **not** `claim_ingest`. The bulk pipeline is management-command-driven, never part of the request path.

**What's actually enforced.** The retargeted forbids (Steps 3–4) enforce the **catalog↔engine** boundaries — the edges that matter and the ones the repo enforces for the ingest system today. Two more invariants are stated above and must be _enforced, not just documented_, when the apps land:

- **Engine↔engine independence.** "Never each other" is a headline property, so add the forbids `claim_edit ⊄ claim_ingest` and `claim_ingest ⊄ claim_edit` (Step 4) — two cheap lines, and the spine covers neither direction (`claim_ingest` is out of it). Not optional.
- **The media wall.** The `"Data apps do not depend on media"` forbid sources `apps.provenance` and `apps.citation` (not `catalog` — catalog legitimately uses media for its media-bearing entities). The engines import no media, so they're media-free substrate like provenance/citation: **add `apps.claim_ingest` (Step 3) and `apps.claim_edit` (Step 4) to that contract's `source_modules`.** Without it, both moves pass lint while reopening `claim_* → media`, since the moved code leaves `catalog` and lands under no media constraint.

The one boundary left genuinely soft is `engine → kiosk` (the top app) — nothing forbids it, matching the repo's existing minimal stance for the ingest system. Tighten only if it becomes a real concern.

Because both engines are their own apps, these are plain app-to-app contracts, not sub-package carve-outs. The two are enforced _asymmetrically_ (Steps 3–4): catalog may import `claim_edit`, so `claim_edit` sits in the layer spine below catalog; catalog must never import `claim_ingest`, so `claim_ingest` stays _out_ of the spine, enforced by the two mutual-independence forbids the repo already uses for the ingest system (retargeted by rename). Putting `claim_ingest` in the spine would _permit_ `catalog → claim_ingest` and then need a clawback forbid — the permit-then-revoke this codebase deliberately avoids.

**Revert stays in provenance — intentionally.** `provenance.revert` also writes claims, so a reader might expect it in an engine. It belongs in provenance because the boundary is _closed-over vs. bridge_: the engines bridge external input (HTTP edits, YAML patches) into claims; revert takes an existing `ChangeSet` and computes its inverse, never leaving provenance's vocabulary. It manipulates audit-model internals (`is_active`, `retracted_by_changeset`, predecessor reactivation) directly, shares no code with either write path (flip-flags vs. build-and-apply), and binds the loose `ClaimControlledModel`. Undo is intrinsic to the claim store, like the `ChangeSet` model itself — not a write front end.

## What stands between here and there

The write surface lives in `apps/catalog/ingestion/` (bulk) and `apps/catalog/api/edit_claims.py` (interactive core, mixed into a module with the domain spec-builders). Ties to catalog, tracked as `# BASELINE` entries on the import-linter contracts (`backend/pyproject.toml`):

- **A model type bound.** The bulk compiler (`patches/{emit,entity_registry,planning}.py`) imports `CatalogModel` purely as a parameter/return bound. → resolved by **Define `LinkableClaimModel`**.
- **Resolution.** The bulk back end (`apply/persist.py`) and the interactive core both reach catalog's resolvers — `apply/persist.py` calls `resolve_all_entities`, `patches/planning.py` imports `resolve_relationships_bulk`, and `execute_claims` calls `resolve_after_mutation`. → resolved by **Invert resolution**.
- **Co-location.** The interactive core shares one module with the domain spec-builders (which import concrete models) and raises `StructuredValidationError` (a generic error that lives in catalog by convention). import-linter is module-granular, so the core/domain seam is invisible to it until the file is split. → made apparent by **Step 0**, resolved by **Extract `claim_edit`**.

The bulk and interactive paths share no code, so they extract independently into two apps. The soft-delete walk either half needs already lives in core (`apps/core/soft_delete.py`).

The bulk boundary is **already** expressed and enforced today — the `"Ingest system does not import the catalog domain"` forbid carries the model-bound and resolution couplings above as `# BASELINE` burn-down entries, and Steps 1–2 delete them as they land. Step 0 brings the interactive boundary up to the same standard before any code moves between apps.

## Phasing discipline

Each step is its own commit. 🛑 STOP for user review before committing.

## ✅ DONE: Step 0 — Split the interactive core out of `edit_claims.py` (in place)

Made the interactive boundary apparent and enforced before any code moves between apps — an intra-catalog file split, no app, no migration. The code is the source of truth now; what the later steps depend on:

- **`catalog/api/claim_write.py`** — the generic core: `execute_claims`, `execute_multi_entity_claims`, `_write_claims_in_changeset`, `_attach_citation`, `ClaimSpec`, `EntityClaims`, `ValidationErrors`, `raise_form_error`, `plan_scalar_field_claims`, `validate_scalar_fields`, `get_field_constraints`, `FieldConstraintSchema`. Imports no concrete catalog model. (`EntityClaims` is a `NamedTuple` added here to name `execute_multi_entity_claims`'s `(entity, specs)` argument.)
- **`catalog/api/edit_claims.py`** — the domain spec-builders and the `_ParentEntity` / `_AliasEntity` aliases. Imports only `ClaimSpec, ValidationErrors, raise_form_error` from `claim_write` (the spec-builders call neither the generic planners nor `execute_*`). `StructuredValidationError` no longer appears here — it concentrates in `claim_write` via `raise_form_error` / `ValidationErrors`.
- **Enforcing contract** "Interactive claim-write core does not import the catalog domain" (`backend/pyproject.toml`): `apps.catalog.api.claim_write ⊄` the **full** catalog domain (not just `catalog.models`), carrying two `# BASELINE` edges — `claim_write -> catalog.resolve` (the `resolve_after_mutation` call, cleared by **Step 2**) and `claim_write -> catalog.exceptions` (`StructuredValidationError`, cleared by **Step 4**). Documented in `docs/AppBoundaries.md`.
- **Tests** split along the same seam: generic-core tests → `catalog/tests/test_claim_write.py`; spec-builder tests stay in `test_edit_claims.py`.

This makes Step 4 a near-trivial `git mv` of `claim_write.py` (and `test_claim_write.py`) into the new app.

## ✅ DONE: Step 1 — Define `LinkableClaimModel` in provenance

`provenance/models/base.py` declares `LinkableClaimModel(LinkableModel, ClaimControlledModel)` beside `ClaimControlledModel` — the addressable-claim-subject contract (a model is namable in a patch or by URL when it is both **linkable** and **claim-controlled**), in the one layer that sees both bases. It declares no fields, so it added no table, content-type or migration. `CatalogModel` extends it (dropping its now-redundant direct `ClaimControlledModel`, keeping its direct `LifecycleStatusModel`), and the bulk compiler's model bounds (`emit`, `entity_registry`, `planning`) bind it instead of `CatalogModel` — the gate is `issubclass(model_class, LinkableClaimModel)`. The three `apps.catalog.ingestion.patches.{emit,entity_registry,planning} -> apps.catalog.models` baselines are gone. Confirmed before commit: C3 reaches each repeated base (`LinkableModel`, `ClaimControlledModel`) once, no `_meta` field clash on a media (`MachineModel`) or non-media (`Title`) concrete, and `makemigrations --check` reports no changes.

**The capability contract is the docstring now.** The required / discovered / ignored tiers — what the write paths bind, detect by guard/introspection, and never touch — live in `LinkableClaimModel`'s docstring (`apps/provenance/models/base.py`). Read them there rather than maintaining a second copy; the design rationale that did _not_ go into code stays below.

**Lifecycle is gated symmetrically at create _and_ delete.** The original draft of this step said only that `delete:` rejects a lifecycle-less target; implementation showed create needs the same treatment. Widening the bound from `CatalogModel` (always lifecycle) to `LinkableClaimModel` dropped the static guarantee, so the create-time `status='active'` stamp is now gated behind `has_lifecycle(model_class)` in **three places that move together** — the create kwarg, its paired `PlannedClaimAssert`, and the `adapter_owned` rejection — because the apply layer's create contract requires every claim-controlled kwarg to have a matching assertion (`apps/catalog/ingestion/apply/validate.py`). Delete is gated by an `isinstance(existing, LifecycleStatusModel)` guard in `_add_delete`. Net: a lifecycle-less target is genuinely create/edit-patchable and only `delete:` rejects it — matching how the rest of the system already treats the optional lifecycle capability (`autocomplete_queryset`, the soft-delete walk's reverse-FK pass). Source of truth: `apps/catalog/ingestion/patches/{emit,planning}.py`.

### ABC structure: one marker, deliberately

`LinkableClaimModel` is the single structural marker needed; the structure stays there. Two richer groupings were considered and rejected:

- **`DeletableClaimModel(LinkableClaimModel, LifecycleStatusModel)`** as a marker for delete-able targets — rejected. It would re-tighten lifecycle onto everything inheriting it, while the `has_lifecycle` TypeGuard already makes the capability visible at the sites that branch on it. Optionality belongs at the use site, not in a base.
- **`WikiEntityModel(DescribedModel, SitemappedModel, LifecycleStatusModel, LinkableClaimModel)`** as a domain-composition base that `CatalogModel` (and a future baseball/medicine base) would extend — deferred, not adopted. It is a _domain-author_ convenience (DRY across domains), not a write-path concern: no engine binds it, and spelling out `CatalogModel`'s four bases is clearer at the leaf than hiding them behind an alias while there is only one domain. It is the natural seam to introduce the day a second domain appears; until then it adds a layer with a single consumer.

The core mixins are already cleanly factored on orthogonal axes (addressing / claims / lifecycle / content), so no mixin restructuring was needed. The clarity win is the capability contract (now the docstring) — not a deeper hierarchy.

## ✅ DONE: Step 2 — Invert resolution

The dispatch seam is split: its generic half — a model-class-keyed registry with two entry points — now lives in provenance, and both write paths plus `revert` reach catalog's resolvers through it without importing catalog. Four `* -> catalog.resolve` baselines are gone (the two bulk edges, `provenance.revert`, and the Step-0 `claim_write -> catalog.resolve`), leaving the interactive contract with only its `catalog.exceptions` baseline (cleared in Step 4). Live code is the source of truth; the durable rationale that did _not_ go into code stays here.

- **`apps/provenance/resolution/`** — the seam. `resolve_after_mutation(entity, field_names)` (per-entity) and `resolve_entities_bulk(model_class, subject_ids, field_names)` (bulk) dispatch by model class to a registered `ResolveHandlers(per_entity, bulk)` pair, raising `ImproperlyConfigured` for an unregistered model. The `PerEntityResolver` / `BulkResolver` Protocols, the registry and `register_resolve_handlers` are in `_dispatch.py`; its module docstrings carry the mechanics — the `field_names` asymmetry (per-entity takes any changed field, bulk takes relationship namespaces only), the fail-fast, and the no-catalog-import rule.
- **`apps/catalog/resolve/_dispatch.py`** — catalog's `_per_entity_handler` / `_bulk_handler` (the same pair registered under every catalog model) and `register_catalog_resolve_handlers()`, called from `CatalogConfig.ready()` over the catalog-scoped `catalog_models()` walk. The per-entity handler keeps `on_commit(invalidate_all)`; because that is a catalog symbol it cannot live in the provenance dispatch, which is why invalidation stays catalog-side. The `MachineModel` `isinstance`/`issubclass` branches survive here, not in the dispatch.
- **`apps/catalog/ingestion/plan.py` + `apply/persist.py`** — the IR change: `IngestPlan.changed_relationship_fields: dict[ContentTypeId, frozenset[str]]` replaced the closure-valued `resolve_hooks`, and the `ResolveHook` Protocol retired; `_resolve` maps each affected content type to its model and dispatches to `resolve_entities_bulk`.

**The two shapes stay distinct — not unified.** Folding per-entity and bulk into one resolver would cost the bulk path its batching or the per-entity path its whole-entity route, and they carry different invalidation contracts (per-entity schedules `on_commit(invalidate_all)`; bulk does not — `ingest_patches` invalidates once after the run). Registration is per-domain: catalog registers only its own models (the catalog-scoped walk, **not** the cross-app `all_linkable_models`), and the dispatch's fail-fast is what forces any second domain to register its own rather than silently inheriting a catalog handler.

**Landed as a package, not a flat module — deliberately.** The plan implied a `resolution.py`; it shipped as `provenance/resolution/` (`__init__` re-exporting `_dispatch`), mirroring `catalog/resolve/`'s shape. The reason is the documented destination: [ModelDrivenClaimResolution.md](ModelDrivenClaimResolution.md) hoists the generic projection engine into a `provenance/resolution/` **package** beside this very registry. Seeding the package now is free — the import path `apps.provenance.resolution` is identical either way — and lets that hoist drop `_entities` / `_helpers` / `_claim_values` in as siblings with no module→package conversion.

**Two smaller deviations, both toward pristine.** (1) `revert`'s two `resolve_after_mutation` imports hoisted from lazy-inside-the-function to a single top-level `from .resolution import …` — the lazy form existed only to dodge the old catalog cycle, which is gone (verified `provenance.models` imports neither `revert` nor `resolution`). (2) Added `provenance/tests/test_resolution.py`, pinning the registry contract directly (fail-fast on unregistered, idempotent vs. conflicting registration, empty-subject no-op, bulk routing) — the dispatch was otherwise only covered indirectly.

**Minimal pass, as planned.** One generic-with-internal-branch handler pair is registered under every model key; the type-switch is gone from the dispatch but lives on in the catalog handler. The bespoke-`MachineModel` split and the other accidental-complexity warts (`getattr`-by-name, `global … is None` lazy-init) are untouched — intra-catalog code quality that clears zero baselines, left to the resolution refactor. See [ModelDrivenClaimResolution.md § Dispatch design](ModelDrivenClaimResolution.md#dispatch-design-patterns-the-ownership-ladder-and-rejected-alternatives).

## ✅ DONE: Step 3 — Create `claim_ingest`; relocate the bulk pipeline

With both seams cut, the bulk pipeline imports only core, provenance and citation (plus `LinkableClaimModel`, now in provenance). Move it into its own app — pure code motion, no migration (the app owns no concrete models; `IngestRun` stays in provenance):

- `git mv apps/catalog/ingestion apps/claim_ingest` (its `patches/`, `plan.py`, `apply/` ride along); add an `AppConfig` and `apps.claim_ingest` to `INSTALLED_APPS`. The package has no signals or `ready()` hook, so the `AppConfig` is trivial. **Not a bare `git mv`:** the package self-imports by absolute path (`from apps.catalog.ingestion.plan import …`, ~30 of them), so the move is `git mv` _plus_ a global `apps.catalog.ingestion → apps.claim_ingest` string replace across the moved files, every external importer, the contracts, and the docstring/mock-string references below — without it the tree won't import. The `ingest_patches`, `pull_patches` and `dump_patch_entry` commands **stay in `catalog/management/commands/`** (repoint their pipeline imports to `apps.claim_ingest`). This deviates from the original draft, which moved the two ingest commands into the app — but `ingest_patches` invalidates catalog's endpoint cache (`from apps.catalog.cache import invalidate_all`) once per run, so moving it would create `claim_ingest → catalog.cache` and break the headline "never catalog" property. `apps.catalog.management` is in neither ingest contract's `source_modules` precisely so a command can be the orchestration entrypoint that composes the pipeline _and_ catalog cache invalidation; keeping the commands there is the design-consistent home (severing the cache coupling via a registered post-ingest hook is a separate refactor, out of scope for pure code motion). `dump_patch_entry` imports `catalog.models` (not the pipeline) and likewise stays. Command names are filename-derived, so `make ingest-patches` / `make pull-patches` are unaffected.
- Repoint the bulk-pipeline-importing test files (in `catalog/tests/`, plus `catalog/resolve/tests/test_source_scoped_presence.py` and `provenance/tests/test_claim_license_write.py`). The pipeline tests **stay in `catalog/tests/`** rather than move into the app: they are catalog-integration tests (they assert on `MachineModel`, `Title`, …) bound to `catalog/tests/conftest.py` fixtures (`machine_model`, `manufacturer`, `credit_roles`, `flipcommons_catalog`), and pytest `conftest` is directory-scoped, so relocating them would orphan every fixture. They are globally test-exempt and not under the `apps.claim_ingest` source, so they trip no contract where they sit — and the `apps.claim_ingest.**.tests.**` exemption the original draft anticipated is unneeded (no `claim_ingest` tests exist). Two Step-2 artifacts need **no** repoint: `test_apply.py`'s resolve-failure test mocks `apps.provenance.resolution.resolve_entities_bulk` (provenance-rooted, so the rename does not touch it), and `provenance/tests/test_resolution.py` is a provenance registry test that stays in provenance.
- Fix references import-linter can't see: the docstring mention in `citation/seeding.py`, and the string `mock.patch("apps.catalog.ingestion.patches.emit.get_relationship_schema")` target in `test_patches.py` (now `apps.claim_ingest.patches.emit.…`; fails at run time, not import — only the full suite catches it).

**Contracts — retarget by rename, keep `claim_ingest` out of the spine.** catalog must never import `claim_ingest`, so do **not** add it to the "App layer tiers" `layers` list (spine placement would permit `catalog → claim_ingest` and force a clawback forbid — the permit-then-revoke the repo avoids). Instead, **retarget the two existing forbids onto `apps.claim_ingest`** — inheriting their burn-down state, not authoring parallels (one is a literal rename; the other simplifies, see below):

- "Ingest system does not import the catalog domain" → `apps.claim_ingest ⊄ apps.catalog` (a single whole-app forbid — once `claim_ingest` is its own top-level app it is no longer a descendant of `catalog`, so the source needn't be enumerated to dodge the descendant rule; the blanket forbid also covers `catalog.api`. The reverse edge; by Step 2 its baselines are already gone).
- "Catalog domain does not import the ingest system" → catalog domain modules ⊄ `apps.claim_ingest` (a whole-app forbid).

Retarget the front-end/back-end split likewise: `apps.claim_ingest.patches ⊄ apps.claim_ingest.apply`. A **fourth** contract needs attention: the "api layer is a leaf" forbid listed `apps.catalog.ingestion` in its `source_modules` so that ingest ⊄ `catalog.api`, back when the ingest-domain forbid omitted `catalog.api` and delegated that edge here. **Remove that now-stale entry — do not rename it to `apps.claim_ingest`**: the whole-app `apps.claim_ingest ⊄ apps.catalog` forbid above already subsumes `claim_ingest → catalog.api`, so api-leaf needs no entry and returns to catalog-domain-only. No `apps.claim_ingest.**.tests.**` exemption is needed (no `claim_ingest` tests). (Engine-to-engine independence — `claim_edit ↔ claim_ingest` — isn't covered by the spine either, since `claim_ingest` is out of it; Step 4 adds the required forbids.)

**Close the media-wall hole — required.** Add `apps.claim_ingest` to the `"Data apps do not depend on media"` forbid's `source_modules` (currently `apps.provenance`, `apps.citation`). The bulk pipeline imported no media inside `catalog`; once it moves out it lands under no media constraint, so lint would pass while `claim_ingest → media` is silently permitted. Adding it keeps the wall intact.

**Acceptance.** `uv run lint-imports` green with the contracts retargeted **and `apps.claim_ingest` added to the media-wall source list**; `make mypy` clean; the **full** backend suite green (the string mock target and signals across apps reach the pipeline).

## ✅ DONE: Step 4 — Create `claim_edit`; extract the interactive write core

Step 0 already isolated the generic core into `catalog/api/claim_write.py` with an enforced `⊄ catalog domain` boundary, so this step is mostly a relocation, not a carve: `git mv apps/catalog/api/claim_write.py apps/claim_edit/claim_write.py` (**pin the destination path** — the importer repoint string depends on it), add the `AppConfig` + `INSTALLED_APPS` entry (between `apps.catalog` and `apps.citation`, mirroring Step 3), and repoint importers. The domain spec-builders stay in `catalog/api`; `edit_claims.py` imports `ClaimSpec, ValidationErrors, raise_form_error` from the module — only the path changes to `claim_edit`.

**The repoint is relative→absolute, not the absolute string-swap Step 3 was.** The 16 `catalog/api` modules import `from .claim_write import …` (relative, same-package) — invisible to an `apps.catalog.api.claim_write` grep, which is why this surface looks small until you search `\.claim_write`. Once the module leaves the package the imports must become `from apps.claim_edit.claim_write import …`: sweep `from .claim_write import` → `from apps.claim_edit.claim_write import` across the 16 (including `edit_claims.py` and `soft_delete.py`, which also imports `EntityClaims`), and the absolute importers (`config/api.py`, `test_entity_crud_registrar.py`) → `apps.claim_edit.claim_write`.

**`test_claim_write.py` stays in `catalog/tests/` — do not `git mv` it into the app.** Same conftest coupling as Step 3: it uses the `person` / `client` / `machine_model` fixtures from `catalog/tests/conftest.py` and imports concrete models (`CorporateEntity, MachineModel, Person, Title`), so it's a catalog-integration test of the generic core, not a portable engine test — relocating it orphans the fixtures. Step 0 split the _module_ cleanly (the `⊄ catalog domain` boundary holds), but the _test_ stayed catalog-coupled; the split did not make it portable. Repoint its import and leave it put, exactly as the bulk pipeline's tests stayed in Step 3. Net: like `claim_ingest`, the `claim_edit` app ships no tests of its own — all coverage runs through `catalog/tests/` until a neutral fixture source exists.

Two supporting moves:

- **`StructuredValidationError` → core (a genuine prerequisite).** `claim_edit`'s `raise_form_error` raises it, but it lives in `catalog/exceptions.py`; once `claim_edit` is its own app below catalog, importing `catalog.exceptions` is a backward edge. It subclasses core's `StructuredApiError` and imports only core, so move it next to its base. **Verify the importer set first** — the repoint rides in this commit. The module-level importers (Step-0 ground truth; re-confirm before the move): **`catalog/api/claim_write.py` — this import _is_ the backward edge once the module moves to `claim_edit`, and the `claim_write -> catalog.exceptions` baseline already tracks it**; `config/api.py` (`:13`, the global exception handler — outside `apps/`, so a missed repoint breaks the API at import); `catalog/api/{systems,locations_write,entity_create,machine_models}.py` and `catalog/services/location_paths.py` (these stay in catalog, repoint → core, fine); plus a string/docstring match in `core/schemas.py` that is **not** a live import (confirmed: comment-only). **Three test files import it too and must repoint or collection breaks**: `test_api_locations_write.py`, `test_claim_write.py`, `test_edit_claims.py`. Note `edit_claims.py` is **no longer** an importer — Step 0 moved the raising helpers into `claim_write`. `provenance.revert` is **not** an importer either — Step 2 already severed its only catalog tie (`catalog.resolve.resolve_after_mutation`), so it now imports `apps.provenance.resolution` and reaches catalog through nothing.
- **The endpoint repoint** (mechanics in the opening: 16 `catalog/api` modules, relative→absolute). `soft_delete.py`'s `execute_soft_delete` calls `execute_multi_entity_claims` too — same repoint; the soft-delete plan wrapper and wire types stay in `catalog/api`.

After this, the domain's edit flow is: endpoint → domain spec-builder (`catalog/api`) → `ClaimSpec` + `execute_*` (`claim_edit`) → claims + resolve seam.

**Contracts.** Add `apps.claim_edit` to the "App layer tiers" `layers` list **between `apps.catalog` and `apps.provenance`** (catalog imports it, so it belongs in the spine; no sibling-`|` entry — `claim_ingest` is out of the spine per Step 3). The spine enforces `claim_edit ⊄ catalog` while allowing `catalog → claim_edit`; no forbid is needed for `claim_edit` (unlike `claim_ingest`, catalog _may_ import it). The Step 0 forbid ("Interactive claim-write core does not import the catalog domain") retires — the module is gone, and the spine now carries the same guarantee one level up. Its two baselines must already be zero by here: `catalog.resolve` cleared at Step 2, `catalog.exceptions` cleared by the `StructuredValidationError → core` move in this step (so order that sub-move before deleting the contract). **Add the engine-to-engine forbids** (`claim_edit ⊄ claim_ingest`, `claim_ingest ⊄ claim_edit`) — required, not optional: the spine covers neither direction (`claim_ingest` is out of it), and "never each other" is a stated invariant. Add `apps.claim_edit` to the `"Data apps do not depend on media"` forbid's `source_modules` (Step 3 already added `apps.claim_ingest`) so the media wall doesn't develop a hole when the interactive core leaves `catalog`. Update `docs/AppBoundaries.md` — **replace** (don't append to) the Step 0 "Interactive claim-write core does not import the catalog domain" bullet, which retires with the contract: `claim_edit` and `claim_ingest` are the two claim-write surfaces below catalog and above provenance — `claim_edit` in the spine (consumed by HTTP endpoints), `claim_ingest` out of the spine behind the two ingest forbids (driven by management commands) — mutually independent and independent of catalog except that catalog calls `claim_edit`.

**Acceptance.** `uv run lint-imports` green with `claim_edit` in the spine and the `claim_ingest` forbids retargeted; `make mypy` clean; the **full** backend suite green (`uv run --directory backend pytest` — endpoints, admin, signals across apps reach `claim_edit`).

## ✅ DONE: Step 5 — Tighten `claim_edit`'s public surface

- **Add `__all__`** to `claim_write.py` listing the ten public names (`ClaimSpec`, `EntityClaims`, `ValidationErrors`, `raise_form_error`, `plan_scalar_field_claims`, `validate_scalar_fields`, `FieldConstraintSchema`, `get_field_constraints`, `execute_claims`, `execute_multi_entity_claims`). This is the one real goal of the original package idea — an explicit, enforced public surface. **Not** for mypy's no-implicit-reexport: every public name is _defined_ in this module (not imported and re-exposed), so it's already exported with or without `__all__`, and no importer can break. `__all__`'s value here is the documented surface and `import *` control. Zero importer churn.
- **Dedupe the AnonymousUser narrowing.** `execute_claims` and `execute_multi_entity_claims` carried a verbatim 12-line comment block + `assert not isinstance(user, AnonymousUser)` + `cast(User, user)`. Extracted one `_narrow_to_user(user: _RequestUser) -> User` helper; both rationales (the `AnonymousUser` tripwire and the `cast(User, …)` django-stubs workaround) moved into its docstring, since the cast now lives in the helper rather than at the `create` call. This was the only genuine code smell in the file.

  Considered and **not** done: `execute_claims` is a strict single-entity special case of `execute_multi_entity_claims` (same `try/except`, create→write→attach→resolve), so it could collapse to a one-line delegate. Skipped to keep this a surface-tightening commit — the collapse is a behavioral-equivalence claim widening the blast radius, and the two entry points carry distinct docstrings and return types (`None` vs. the `ChangeSet` Undo needs).

- **Flag the real future home of `get_field_constraints` / `FieldConstraintSchema`.** These are the read-side outlier: model-driven introspection serving `GET /field-constraints/{entity_type}` (`config/api.py`), with no `ChangeSet`, no claims, no write. They sit in a write engine only because as of this plan, the generic HTTP-surface app doesn't exist yet. Their natural home will be `entity_api` — the generic read/write HTTP surface that picks them up during its carve (see [ModelDrivenEntityApi.md](ModelDrivenEntityApi.md)). Do **not** carve a `constraints.py` island inside `claim_edit` now just to relocate it again then; leave it in `claim_write.py` until that carve.

## Verification

- After each step: `make lint && make mypy` clean, plus a **step-scoped** pytest (the engine apps don't exist until Steps 3–4, so naming them earlier fails collection):
  - Steps 0–2: `uv run --directory backend pytest apps/catalog apps/provenance apps/core -q`
  - after Step 3: add `apps/claim_ingest` (collects ~nothing — the bulk pipeline's tests stay in `catalog/tests/`; the path is for completeness, not coverage)
  - after Step 4: add `apps/claim_edit` (same — `test_claim_write.py` stays in `catalog/tests/`; both engine apps are exercised through the catalog suite)
- The decoupling is complete when `uv run lint-imports` is green with `apps.claim_edit` in the layer spine and the `apps.claim_ingest` forbids retargeted (out of the spine), no bulk-contract baselines, and the `provenance.revert -> apps.catalog.resolve` baseline deleted.
- After the moves: the **full** backend suite green.
- End-to-end on a dev DB: an interactive edit through the HTTP api and a real patch apply — confirm both write ChangeSets, the registered resolve handler fires (derived fields and through-tables materialize), a blocked `delete:` still errors with the blocker detail, and the `IngestRun` audit row writes.
