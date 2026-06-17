# Django App Boundaries

This document defines the dependency rules and responsibilities of this project's Django apps.

## Apps

- `core`: shared foundation layer used by the rest of the project
- `accounts`: authentication and account-specific behavior
- `catalog`: the pinball business/domain/data model
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
- **The api layer is a leaf** — the domain (models, services, resolve, ingestion, …) must not import back into `api/`. Catalog and core both have multi-module `api/` packages with their own leaf contracts; the remaining apps are single `api.py` modules and leaves by construction.
- **Production code does not import test factories** — `test_factories` is test-only scaffolding and must not enter the runtime path.
- **Catalog domain does not import the ingest system** — `ingestion/` is the bulk write path, a top-level consumer. The rest of catalog must not import it; only the management commands that drive ingest may, as the orchestration entrypoint.
- **Patch front end does not depend on the ingest back end** — the patch system lowers YAML to an `IngestPlan` (the IR); `catalog.ingestion.patches` must not reach into `catalog.ingestion.apply`. See [DataArchitecture.md](DataArchitecture.md).
- **Media internal layering** — `constants < models < {storage|processing|schemas|helpers} < authz < api`, a `layers` contract that also keeps `media.api` a leaf.

Several contracts carry a `# BASELINE` block listing pre-existing violations that predate enforcement: upward imports in `App layer tiers` (e.g. `provenance -> catalog` deferred imports, `core -> accounts` leaks) and domain-logic-stranded-under-`api/` in `The api layer is a leaf` (the `soft_delete` helpers consumed by catalog's ingestion layer). Each baseline is a burn-down list: fix the underlying import and delete the line. Do not add to one.
