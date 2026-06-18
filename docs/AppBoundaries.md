# Django App Boundaries

This document defines the dependency rules and responsibilities of this project's Django apps.

## Apps

- `core`: shared foundation layer used by the rest of the project
- `accounts`: authentication and account-specific behavior
- `catalog`: the pinball business/domain/data model
- `claim_ingest`: the bulk catalog write path — compiles YAML data patches to an `IngestPlan` IR and applies them in batches. A top-level consumer driven by management commands, not part of the request path
- `citation`: citation-source metadata and evidence objects that can be cited
- `provenance`: claims, source, and audit system
- `media`: media upload and hosting infrastructure
- `kiosk`: kiosk display configuration (operational settings, not catalog claims)

## Dependencies

```text
        kiosk | media.api
____________________________
           catalog
____________________________
provenance | media.{models,storage,processing,schemas} | citation
____________________________
            accounts
____________________________
             core
```

- `core` is the foundation layer and depends on nothing
- `accounts` depends only on `core`; `core` must not depend on `accounts`
- `citation`, `provenance`, and `media.{storage,processing,schemas}` are peer-isolated (must not depend on each other). `media.models` is permitted one targeted dependency on `provenance.models` for `ClaimControlledModel` only — `media_attachment` is a claim field, so any `MediaSupportedModel` entity is by construction a `ClaimControlledModel`; the inheritance encodes that structural commitment as a compile-time guarantee. The rest of `media.models` (concrete `MediaAsset` / `MediaRendition` / `EntityMedia`) does not reach into provenance.
- `provenance` depends on `citation` but `citation` does not depend on `provenance`
- `catalog` uses the full middle tier
- `media.api` depends on `catalog` and `provenance`: upload handlers write `media_attachment` claims through catalog's relationship-claim registry and persist `Claim` rows directly. This is a structural consequence of `media_attachment` being a catalog-registered relationship type whose target happens to live in media; splitting it out would require extracting the whole relationship-claim machinery into a neutral app
- `kiosk` depends on `catalog` (FK to `Title`); audit FKs reference `AUTH_USER_MODEL` via Django core, not `accounts.UserProfile`. Kiosk configs are operational settings, not claims-controlled — the app deliberately stays out of `provenance`

## Preferred patterns over widening imports

When strict app boundaries make integration awkward, prefer these patterns over widening imports:

- generic foreign keys and content types for cross-domain references where appropriate
- registration hooks, where a generic subsystem lets another app register behavior without becoming coupled to it
- serialized or value-level contracts rather than direct model imports
- orchestration in higher-level entrypoints, such as API composition or management commands, rather than deep lateral imports

The important rule is: solve integration by designing a boundary, not by punching through one.

## Exception: Page API endpoints

Page API endpoints (see [ApiDesign.md § Two API types](ApiDesign.md#two-api-types)) are expected to cross app layers. A page endpoint's job is to return one route's full rendering payload, which routinely means reading from several apps and returning a composed page model.

A page endpoint lives in the app that owns the _page concept_, not the app that owns the most data it reads. The title detail page is about a title, so `/api/pages/title/{slug}` lives in catalog even though it reads claims from provenance and attachments from media. The user profile page is about a user, so `/api/pages/user/{username}/` lives in accounts even though it reads ChangeSets and Claims from provenance.

The rules above apply to the non-page surface (models, services, helpers). Page endpoints are an intentional carve-out and should not be refactored to obey peer isolation at the cost of the page-composition pattern.

## Enforcement

These rules are enforced statically by [import-linter](https://import-linter.readthedocs.io/). The contracts live in [`backend/pyproject.toml`](../backend/pyproject.toml) under `[tool.importlinter]` and run as part of `make lint` (via `scripts/lint`) and as a pre-commit hook. Run them directly with `cd backend && uv run lint-imports`.

The tiers above map to a `layers` contract; the media peer-isolation rules map to two `forbidden` contracts (one per direction). The `media.models -> provenance.models` exception and the page-API carve-out are expressed as `ignore_imports` entries, as is the test surface — tests are exempt from boundary rules, the same way the frontend ESLint config gives test files vendor-boundary-only treatment.

Beyond the cross-app tiers, several intra-app invariants are enforced:

- **Domain models do not import the api/schema layer** — a model reaching up into HTTP serialization is a dependency inversion.
- **The api layer is a leaf** — the domain (models, services, resolve, …) must not import back into `api/`. Catalog and core both have multi-module `api/` packages with their own leaf contracts; the remaining apps are single `api.py` modules and leaves by construction.
- **Production code does not import test factories** — `test_factories` is test-only scaffolding and must not enter the runtime path.
- **Catalog domain does not import the ingest system** — `claim_ingest` is the bulk write path, a top-level consumer. The rest of catalog must not import it; only the `ingest_patches` / `pull_patches` management commands (which stay in `catalog/management/commands/`) may, as the orchestration entrypoint — they compose the pipeline with catalog cache invalidation, the one coupling that keeps `claim_ingest` itself free of catalog.
- **Ingest system does not import the catalog domain** — the forward mirror of the rule above: `claim_ingest` depends only on core, provenance and citation. A single whole-app `forbidden_modules = ["apps.catalog"]` catches a new coupling to **any** catalog package — `catalog.api` included — not only the burn-down baselines. The blanket forbid is possible because `claim_ingest` is a separate top-level app, not a descendant of `catalog`, so the source needn't be enumerated to dodge import-linter's descendant rule (the reverse rule above must still enumerate its source, to exclude `catalog.management`). The catalog imports were a `# BASELINE` list severed step by step (the model-type bound and the resolution dispatch were the last two); having reached **zero**, the boundary was sealed and the ingest system moved to its own app, `apps.claim_ingest`.
- **Interactive claim-write core does not import the catalog domain** — the interactive analog of the ingest rule. `catalog/api/claim_write.py` is the generic interactive write engine (validate fields, write claims in a ChangeSet, attach citations, resolve), split out of the per-relationship spec-builders that stay in `edit_claims.py`. It must not import the catalog domain, so it stays a reusable write surface and can later extract into its own app; `forbidden_modules` enumerates the full domain, with one `# BASELINE` edge remaining — `claim_write -> catalog.exceptions` (`StructuredValidationError`), cleared when that error relocates to core. (The former `claim_write -> catalog.resolve` edge — the `resolve_after_mutation` call — cleared when resolution dispatch moved to the provenance-local seam `apps.provenance.resolution`.)
- **Generic resolver core does not import the catalog domain** — the read-side analog of the claim-write rule, and the first enforced step of [ModelDrivenClaimResolution.md](plans/model_driven_metadata/ModelDrivenClaimResolution.md). Resolution materializes claims into denormalized fields and through-tables, and its Tier-1 core — `catalog/resolve/_entities.py` (scalar/bulk projection), `_helpers.py` (coercion, FK, constraints) and `_claim_values.py` (read-side payload TypedDicts) — is already fully model-driven: it names no concrete model, driving entirely off `get_claim_fields`/`_meta` introspection. The contract forbids these three modules from importing the catalog domain so that property can't silently regress and the eventual hoist to the substrate stays a near-trivial move. It is green with no baselines — a ratchet on what is already true, not the model-driven resolver engine (which awaits the deferred relationship-declaration vocabulary). The relationship/dispatch resolvers (`_relationships`, `_dispatch`, `__init__`) still bind `MachineModel` and are deliberately out of scope; the dispatch seam is restructured by [ModelDrivenClaimWrite.md](plans/model_driven_metadata/ModelDrivenClaimWrite.md)'s "Invert resolution" step.
- **Patch front end does not depend on the ingest back end** — the patch system lowers YAML to an `IngestPlan` (the IR); `claim_ingest.patches` must not reach into `claim_ingest.apply`. See [DataArchitecture.md](DataArchitecture.md).
- **Media internal layering** — `constants < models < {storage|processing|schemas|helpers} < authz < api`, a `layers` contract that also keeps `media.api` a leaf.

Several contracts carry a `# BASELINE` block listing pre-existing violations that predate enforcement: upward imports in `App layer tiers` (e.g. `provenance -> catalog` deferred imports, `core -> accounts` leaks) and domain-logic-stranded-under-`api/` in `The api layer is a leaf` (the `soft_delete` helpers consumed by catalog's ingestion layer). The `claim_write -> catalog.exceptions` edge in `Interactive claim-write core does not import the catalog domain` uses the same `# BASELINE` mechanism but is a deliberately staged decoupling introduced with the contract, not drift that predates it. Each baseline is a burn-down list: fix the underlying import and delete the line. Do not add to one. import-linter errors on an unmatched `ignore_imports` entry, so a baseline left stale after its import is gone fails the build until deleted — that error is the burn-down's forcing function.
