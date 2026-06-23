# Django App Boundaries

This document is the conceptual map of the project's app dependency rules. The executable rules — every contract, its exact module lists, baselines and mechanical rationale — live in [`backend/pyproject.toml`](../backend/pyproject.toml) under `[tool.importlinter]`; this doc explains the architecture they enforce, not their line-by-line detail.

## Apps

- `core`: shared foundation layer used by the rest of the project
- `accounts`: authentication and account-specific behavior
- `catalog`: the pinball business/domain/data model
- `claim_edit`: interactive catalog writes — validates scalar fields, writes claims, attaches citations, triggers resolution
- `claim_ingest`: bulk catalog writes — ingests YAML data patches and applies them in batches
- `citation`: citation-source metadata and evidence objects that can be cited
- `provenance`: claims, source and audit system
- `media`: media upload and hosting infrastructure
- `kiosk`: museum kiosk display configuration

## The dependency spine

Most apps form a single linear stack — higher tiers may import lower, never the reverse (the `App layer tiers` contract):

```text
kiosk         museum kiosk config
  │
catalog       the domain
  │
claim_edit    interactive writes
  │
provenance    claims / audit
  │
citation      citable sources
  │
accounts      auth
  │
core          foundation — depends on nothing
```

The edges that carry meaning beyond "higher imports lower":

- `core` depends on nothing; `accounts` depends only on `core` (so `core` must not import `accounts`).
- `provenance` imports `citation`, not the reverse — they are adjacent tiers, not peers.
- `catalog` uses the full middle tier and sits one above `claim_edit`, whose interactive write path catalog's HTTP edit endpoints call into.

Two apps sit **outside** the linear spine:

- **`media`** has its own internal stack (`Media internal layers`): `constants → models → {storage|processing|schemas|helpers} → selectors → authz → api`. `selectors` sits above the peer group because it composes `storage` + `schemas` into wire schemas — something the peer-isolated `helpers` tier (which only reads prefetched rows off `models`) may not do. Its `api` tier consumes `catalog` and `provenance` (upload handlers write `media_attachment` claims), so it is effectively a top-level consumer like `kiosk`. Its lower tiers are peer-isolated from `provenance`/`citation` — they must not import them — with one sanctioned edge, `media.models → provenance.models`: `media_attachment` is a claim field, so any `MediaSupportedModel` is structurally a `ClaimControlledModel`, and the inheritance encodes that as a compile-time guarantee. The reverse direction — data apps importing `media` — is forbidden outright.
- **`claim_ingest`** is the bulk write path: a management-command-driven consumer kept deliberately out of the spine so `catalog → claim_ingest` stays forbidden (sealed in both directions). It and `claim_edit` are mutually independent — the two claim-write surfaces share no code, only the provenance/core substrate they both write through.

`kiosk` references `catalog` (FK to `Title`); its audit FKs use `AUTH_USER_MODEL` via Django core, not `accounts.UserProfile`. Kiosk configs are operational settings, not claims, so the app stays out of `provenance`.

## Intra-app invariants

Within an app, a few internal boundaries are enforced (named contracts in `pyproject.toml` carry the module lists):

- **The api/schema layer is a leaf.** Domain code (models, services, …) must not import back up into `api/`. Both catalog and core express this as an _exhaustive_ layered contract over the app's whole acyclic internal stack (`Catalog internal layers`, `Core internal layers`) — a new submodule left unplaced fails the build. The remaining apps are single `api.py` modules, leaves by construction.
- **Domain models do not import the api/schema layer** — a model reaching up into HTTP serialization is a dependency inversion.
- **The generic resolver core stays catalog-agnostic.** `catalog/resolve/{_entities,_helpers,_claim_values}` drive entirely off claim-field introspection and name no concrete model; the contract forbids them from importing the catalog domain so that property can't silently regress.
- **The domain-neutral engine stays catalog-agnostic.** `catalog/engine/` — the generic HTTP-surface registrars (`entity_api/{create,detail,listing,delete}`), the query fold (`query/`) and the generic bases the domain mounts and subclasses (`AliasModel`, the wire schema bases, `naming`, the model-registry walk) — sits at the bottom of the `Catalog internal layers` stack (concrete alias models in `models/` subclass `engine.models.AliasModel`, so `models → engine`). `Engine does not import the catalog domain` forbids the reverse edge, so the engine names no concrete model and stays liftable to its own app by a `git mv`. Its own internals are exhaustively layered by `Engine internal layers` (registrars on top, the generic substrate at the base).
- **The patch system and the apply engine meet only at the `IngestPlan` IR — sealed both ways.** `claim_ingest.patches` is a compiler front end that lowers YAML to an `IngestPlan`; `claim_ingest.apply` executes it. The front end must not fork the back end (new patch behavior belongs against the IR), and the apply engine must not import the patch adapter — it is **source-agnostic**, consuming the IR blind to which front end produced it. So the engine raises plain `ValidationError` and lets the patch command map it to `PatchError`, never importing `PatchError` itself.
- **Production code does not import test factories** — `test_factories` is test-only scaffolding and must not enter the runtime path.

## Preferred patterns over widening imports

When strict boundaries make integration awkward, prefer these over widening imports:

- generic foreign keys and content types for cross-domain references
- registration hooks, where a generic subsystem lets another app register behavior without coupling to it
- serialized or value-level contracts rather than direct model imports
- orchestration in higher-level entrypoints (API composition, management commands) rather than deep lateral imports

The rule: solve integration by designing a boundary, not by punching through one.

## Exception: Page API endpoints

Page API endpoints (see [ApiDesign.md § Two API types](ApiDesign.md#two-api-types)) are expected to cross app layers: a page endpoint returns one route's full rendering payload, which routinely reads from several apps. It lives in the app that owns the _page concept_, not the app that owns the most data it reads — `/api/pages/title/{slug}` lives in catalog though it reads claims from provenance and attachments from media; `/api/pages/user/{username}/` lives in accounts though it reads from provenance. These are an intentional carve-out (`ignore_imports` entries) and should not be refactored to obey peer isolation at the cost of the page-composition pattern; the peer-isolation rules apply to the non-page surface (models, services, helpers).

## Enforcement

The rules above are enforced statically by [import-linter](https://import-linter.readthedocs.io/). The contracts — with their exact module lists and per-rule rationale — live in [`backend/pyproject.toml`](../backend/pyproject.toml) under `[tool.importlinter]`. They run via `make lint` (through `scripts/lint`) and as a pre-commit hook; run them directly with `cd backend && uv run lint-imports`.

Tests are exempt from the boundary rules (an `ignore_imports` pattern), the same way the frontend ESLint config gives test files vendor-boundary-only treatment.

Some contracts carry a `# BASELINE` block: pre-existing violations that predate enforcement (currently a few upward imports in `App layer tiers`). Each is a burn-down list — fix the underlying import and delete the line; never add to one. import-linter errors on an unmatched non-wildcard `ignore_imports` entry, so a baseline left stale after its import is gone fails the build until deleted — that error is the burn-down's forcing function.
