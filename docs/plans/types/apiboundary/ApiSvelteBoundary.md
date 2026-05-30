# API Boundary Improvements

## Status: DONE

All scoped work in this plan is complete: PR 0-4, the `Input` ghost fix, and the OpenAPI boundary tests are all landed. Remaining ideas live in [ApiSvelteBoundaryFollowups.md](ApiSvelteBoundaryFollowups.md).

This is a plan to improve the ergonomics of working with both the backend and frontend API surface area.

## Context

The Django Ninja schema names that flow through OpenAPI into the generated
TypeScript types are inconsistent and noisy: 117 names end in `Schema` (a
Ninja base-class artifact, not domain vocabulary), the media app uses
divergent `In`/`Out` suffixes, and a handful of bare names (`Variant`,
`Source`, `Stats`, `Recognition`, `Create`) are too generic at the OpenAPI
component level.

The OpenAPI contract is the shared vocabulary between Django, the generated
types, ~86 frontend consumers, and any AI agent reading the codebase. When
the same role (input, output, list-row, detail) takes different suffixes
depending on which app a schema lives in, every contributor has to learn the
per-app convention before they can type anything correctly. The cost
compounds: every new schema either follows the local convention
(perpetuating divergence) or invents its own, and the inconsistency blocks
lint enforcement because there's no single rule a boundary test can assert.

A second friction sits one layer down: those 86 frontend consumers reach the generated types via `components['schemas']['XSchema']` indexed access — verbose, no IDE autocomplete, OpenAPI structure leaking into every call site. We want instead to write `import type { Foo } from '$lib/api/schema'`. We didn't realize that `openapi-typescript` could emit top-level type aliases via its `--root-types` flag until recently. That flag is now turned on, but the front end has not switched to using `import` statements yet.

## Direction

1. **Rename schemas.** Rename the schemas at the source — in the backend Python classes — so the OpenAPI contract, the generated `schema.d.ts`, and the frontend imports all share one vocabulary. Change the usage by the front end consumers at the same time.
2. **Add tests.** Once the contract is consistent, pin the conventions with boundary tests.

## Tasks

### Document rationalized API names - DONE

Document the convention rules and rename tables in [ApiNamingRationalization.md](ApiNamingRationalization.md). These have been reviewed and approved.

### Rename API schemas

Two-stage migration. The TS-side import style change (indexed access → named imports) is independent of the Python renames, so it ships first as one mechanical PR. After that, per-app rename PRs only need to rename existing import specifiers, never invent new import blocks.

This split was chosen over interleaving rename + import-style per app because:

- The dedupe / import-management logic (the trickiest part of the TS transform) gets exercised once on the full corpus, not over and over with shifting scopes.
- Per-app rename PRs become much simpler — each one is "rename N classes in Python, then rewrite N specifiers in TS imports."
- PR 0 is reviewable as a single concern ("switch import style") with no semantic change.
- Reviewers and `git bisect` can isolate import-style regressions from rename regressions.

The remainder of this section assumes that split. PR 0 is described first; PR 1+ follow.

#### Op-ID stability — VERIFIED

Renaming Ninja schema classes does not shift `operationId` values. Verified empirically against the current `openapi.json`: op IDs follow the `<module>_<function_name>` pattern (e.g., `config_api_stats`), derived from the view function's qualified name, not from any schema class. No endpoint declares `operation_id=` explicitly, so this is the actual mechanism in use.

The TS transform therefore never needs to touch op IDs in client call sites. If a future Ninja upgrade changes default op-ID derivation, re-verify by diffing `openapi.json` after a one-class rename.

#### Tooling

- **Python side**: libcst — preserves comments and formatting; built for codemods. Add as a dev dependency: `cd backend && uv add --dev libcst`.
- **TS side**: plain string-based scripts. ts-morph would have given us scope-aware rewriting and import-block management, but neither buys us much here: the `components['schemas']['Name']` pattern is unambiguous (no scoping concerns), no existing named-import blocks need merging into (greenfield, confirmed below), and `pnpm check` is a strong oracle — any miscompile from a botched edit surfaces immediately as a type error. Write the scripts as plain Node `.mjs` so there's no extra toolchain hop. No new frontend dev dependencies needed.

Scripts live in the language-native trees, not at repo root, so each toolchain only knows about its own:

- `backend/scripts/codemod/rename_schemas.py` — libcst transform.
- `frontend/scripts/codemod/sweep-indexed-access.mjs` — PR 0's TS transform.
- `frontend/scripts/codemod/rename-import-specifiers.mjs` — PR 1+'s TS transform.
- `frontend/scripts/codemod/rename-table.json` — shared `{"OldName": "NewName"}` map. Living in `frontend/` is mildly arbitrary (the Python script reads it too), but it co-locates with the larger of the two consumers and avoids inventing a new top-level dir. Python script reads it via a relative path.

Commit scripts and the JSON map so reviewers can re-run the transform after rebasing past other work.

#### PR 0: TS-side sweep (indexed access → named imports)

**Goal**: every `components['schemas']['XSchema']` indexed-access reference in `frontend/src/**` becomes a named import + bare-name use. No Python or OpenAPI changes; `schema.d.ts` is regenerated only to confirm `--root-types` aliases exist for every schema (already on, [frontend/package.json:20](../../../../frontend/package.json#L20)).

**Script behavior** (`sweep-indexed-access.mjs`):

1. Find every `components[<q>schemas<q>][<q>Name<q>]` reference (where `<q>` is `'` or `"`) in `frontend/src/**/*.{ts,svelte,svelte.ts}`. Skip `frontend/src/lib/api/client.ts` (the only legitimate consumer of indexed access). Empirically every real-source occurrence today uses single quotes — the double-quote form only appears in generated `schema.d.ts` — but accepting both costs nothing and prevents a silent miss. The match must be **prefix-only**: rewrite the `components['schemas']['Name']` chunk to bare `Name` and leave any trailing index/property chains (`['field']`, `[number]`, `[keyof …]`) untouched. A bare identifier is valid TypeScript in every position the original indexed access was, so further chains continue to type-check unchanged. Verified greenfield today (zero such chains in real source — every consumer stops at `['Name']`), but the prefix-only rule keeps the script correct if one ever appears.
2. For each unique `Name` referenced in a file, add it to a `import type { … } from '$lib/api/schema'` block. No existing named-import blocks today (confirmed below), so this just creates a new block; the script still needs to dedupe across multiple references to the same `Name` within one file. The script must also accept `from './schema'` — one file ([frontend/src/lib/api/media-api.ts](../../../../frontend/src/lib/api/media-api.ts)) imports relatively because it lives next to `schema.d.ts` — and preserve whichever spelling the file already uses (don't canonicalize paths; out of scope).
3. Rewrite the indexed-access reference to bare `Name`.
4. If, after the rewrites, the file no longer contains an identifier-position reference to `components` outside the import line itself, remove `components` from the import specifier list. **Specifier-level, not line-level**: one file ([frontend/src/lib/components/editors/save-claims-shared.ts](../../../../frontend/src/lib/components/editors/save-claims-shared.ts)) has `import type { components, paths } from '$lib/api/schema'` — it must become `import type { paths } from '$lib/api/schema'`, not be deleted. Drop the whole line only when `components` was the sole specifier. **Heuristic gotcha**: a naive `\bcomponents\b` test produces false positives on unrelated import paths like `'$lib/components/Foo.svelte'`, where `components` is a directory name in a string literal, not an identifier. Narrow the check to identifier-position uses — e.g. `\bcomponents\s*[\[\.,>]` — or strip import lines before testing.
5. **Insertion point** for the new `import type { … } from '$lib/api/schema'`: after the last existing import in the script block / file. Prettier reorders imports anyway, so exact placement matters less than producing a syntactically valid file for the type-checker to consume.
6. **Idempotence**: re-running the script on a fully-converted tree is a no-op (no indexed-access matches → no rewrites). This makes "rebase, re-run, commit" safe.
7. **Format after rewriting**: run `cd frontend && pnpm format` once the codemod finishes. The string-based rewrites leave noisy whitespace and the new `import type { … }` line is unsorted relative to existing imports. Without this step the diff is polluted and the pre-commit hook would rewrite the files anyway. Same rationale as the per-app PR loop ([below](#run-order)).

For `.svelte` files, transform only the contents of `<script lang="ts">…</script>` blocks (markup never references generated types). Every `.svelte` file in the repo uses `lang="ts"`. `.svelte.ts` files are plain TypeScript and are transformed as-is.

**Self-named alias collapse** — required pre-pass. Several files declare `type X = components['schemas']['X'];` (or `export type X = components['schemas']['X'];`) where the alias name on the LHS matches the schema name on the RHS. After the bare-name rewrite this becomes `type X = X;` — a self-reference that TypeScript flags as a circular type. The script must detect this pattern up front and:

- **Non-exported** (`type X = components['schemas']['X'];`) — delete the line. The bare `X` is now imported by name; the local alias was redundant.
- **Exported** (`export type X = components['schemas']['X'];`) — replace with `export type { X };`. The import block brings `X` into scope and the bare re-export preserves the module's public surface for downstream consumers.

Detect with a regex requiring the LHS identifier and the RHS schema name to be **the same captured group** (back-reference), so renaming aliases like `type Model = components['schemas']['MachineModelDetailSchema'];` are left to the regular rewrite (they become `type Model = MachineModelDetailSchema`, which is fine). Eight files in the current tree hit this pattern: `field-constraints.ts`, `location-links.ts`, one alias in `citation-types.ts`, three hierarchical-taxonomy svelte files (`Ref`), and two taxonomy-edit-types files (`RichTextSchema`).

This pre-pass also matters for **PR 1+** (see [TS transform scope below](#ts-transform-scope)): a rename like `BlockingReferrerSchema → BlockingReferrer` will turn today's non-self-aliased `export type BlockingReferrer = components['schemas']['BlockingReferrerSchema'];` (which PR 0 rewrites to `export type BlockingReferrer = BlockingReferrerSchema;`) into a fresh self-alias. The rename codemod needs the same collapse logic.

**Scope at implementation time**: 98 indexed-access call sites across 85 source files (excluding the generated `schema.d.ts`, which itself contains ~774 indexed-access references — those are the type alias bodies in the generated file, not consumer call sites). Zero files used named imports from `$lib/api/schema` before PR 0 — confirmed greenfield.

**Lock in the import style in the same PR.** Add a `no-restricted-syntax` rule to [frontend/eslint.config.js](../../../../frontend/eslint.config.js) banning `components['schemas']` indexed access, with a file-scoped override re-allowing it in `src/lib/api/client.ts`. The flat config already uses per-block `files` overrides ([frontend/eslint.config.js:19-26](../../../../frontend/eslint.config.js#L19-L26)), so this is the same shape. After the codemod runs, the rule has zero violations and permanently prevents regression — including from any branch in flight while PR 0 is in review. Folding it into PR 0 (rather than a follow-up) closes the regression window and makes the PR self-enforcing: `pnpm lint` is now a stronger oracle than the grep.

**Verification**:

- `pnpm check` passes (no type drift).
- `pnpm lint` passes (the new ESLint rule has zero violations on the converted tree).
- `pnpm test` passes.
- `pnpm format` has been run; `git diff` shows no whitespace-only churn pending.
- `grep -rE "components\[[\"']schemas" frontend/src --include="*.ts" --include="*.svelte" | grep -v "lib/api/client.ts"` returns zero matches. (Both quote styles, all three file extensions covered by the include patterns since `*.ts` matches `*.svelte.ts`.) Redundant with the ESLint rule, but cheap insurance during the PR.

**Why this is one PR, not split per area**: the codemod is mechanical and easier to review as a single sweep. Splitting by route/area would force humans to track which files were converted and which still use indexed access — extra cognitive load for no review benefit.

#### PR 1+: batched schema renames

After PR 0, every consumer uses named imports. Each batched rename PR follows this loop.

##### Run order

1. **Python rename** (`backend/scripts/codemod/rename_schemas.py`, scoped to the batch's entries from `rename-table.json` via `--names OldA,OldB,…`).
2. **`make codegen`** — regenerates `frontend/src/lib/api/schema.d.ts`.
3. **TS rename** (`frontend/scripts/codemod/rename-import-specifiers.mjs`, same `--names` scope) — rewrites import specifiers and any in-code references.
4. **Format**: `cd backend && uv run ruff format .` + `cd frontend && pnpm format`. Both libcst (Python) and the string-based TS rewrites can leave noisy whitespace; without this the diffs are polluted and the pre-commit hook would rewrite the files anyway. Whole-tree scope is intentional — both formatters are idempotent on already-formatted files, so they won't sweep unrelated content into the rename diff. (If a future contributor has uncommitted formatting drift in unrelated files, that's a pre-existing issue this step exposes, not creates.)
5. **Verify** (see _Iterate until tests pass_ below).
6. Only then commit.

##### Python transform scope

Find class definitions wherever they live — `apps/*/schemas.py` is canonical, but `apps/citation/api.py` has 15 inline schemas, `apps/accounts/api.py` has 4, `apps/core/pagination.py` holds `PaginationParams`, and the boundary tests intentionally don't yet enforce the schemas-must-live-in-`schemas.py` rule. The transform looks up class definitions **by name from the rename table** (not by `Schema`-suffix pattern — `PaginationParams`, `Ref`, `CreditInput`, etc. are entries without the suffix). It walks every matching `class <OldName>(...)` declaration regardless of file or base class, then updates every reference across `backend/**/*.py` — other apps' imports, serializers, tests, fixtures, endpoint `response=` decorators, type annotations.

The rename table contents are what's per-batch; the file scope isn't.

`rename-table.json` is a flat `{"OldName": "NewName"}` map containing the full set of renames from [ApiNamingRationalization.md](ApiNamingRationalization.md). Both scripts accept `--names OldA,OldB,…` to restrict a run to a subset; the JSON map itself never gets rewritten between batches. (Alternative: per-app grouped JSON. Rejected — PR 1's three entries don't all live in one app, so we'd need a cross-cutting filter mechanism anyway.)

##### TS transform scope

Walks `frontend/src/**/*.{ts,svelte,svelte.ts}` (excluding `client.ts`). For each `OldName → NewName` in the PR's scope:

1. In every file that imports `OldName` from `$lib/api/schema`, replace the specifier with `NewName`.
2. Replace every in-code word-boundary reference to `OldName` with `NewName`.

After PR 0, no indexed-access dedupe logic is needed — every relevant reference is already a named import. The transform is `s/\bOldName\b/NewName/g` plus rewriting specifiers in the `import type { … } from '$lib/api/schema'` block, so it's plain string-based like PR 0's script. Format step (`pnpm format`) handles import-specifier sort order; the codemod doesn't need to.

**Self-alias collapse not needed.** Verified empirically against the post-PR-0 tree: zero `export type X = XSchema;` patterns exist that the rename table would collapse into a self-reference. The only `Schema`-stripping renames are `TitleRefSchema → TitleRef`, `ModelRefSchema → ModelRef`, and `GameplayFeatureSchema → GameplayFeatureRef` — none have matching local aliases. `Ref → EntityRef` can't manufacture a self-alias because there's no `export type Ref = Ref;` (the bare `Ref` import becomes `EntityRef` along with any LHS reference). The rename codemod is therefore plain substitution, no collapse pass. PR 0's inline self-alias logic stays inline; nothing to extract or share. Re-verify with a quick `grep -rEn 'export type [A-Za-z_]+ = [A-Za-z_]+Schema;' frontend/src` if the rename table grows.

#### Iterate until tests pass

- `git reset --hard` between runs is free **once the working tree is clean**. Stash or commit unrelated in-flight work first — the iteration loop assumes nothing in the tree is worth preserving outside the codemod's output. No human-in-the-loop deciding per-batch whether things look right — just run, check, revert, fix script.
- Three-part oracle, all binary signals:
  - `make codegen` succeeds — the OpenAPI doc is internally consistent after the Python rename.
  - `pnpm check` passes — every frontend consumer compiles against the new `schema.d.ts`.
  - `make test` passes — runtime catches anything the type checks miss (string references in fixtures, admin field configs, `extra_data` JSON, etc.).

#### Batch rollout order

The "keep `Schema` everywhere" decision (see [ApiNamingRationalization.md](ApiNamingRationalization.md)) collapses the original 134-rename plan to ~40 renames concentrated in `core`, `media`, `citation`, `provenance`, and `catalog`. `accounts` has zero renames under the new rules and is skipped entirely.

After PR 0, sequence the remaining rename PRs smallest-first. The original plan split this six ways (one per app) on the theory that the codemod would grow on simple cases before encountering edge cases. In practice the codemod is a JSON map driving plain string substitution — it doesn't grow per app, and the per-PR overhead (codegen, format, three-oracle verify) dominates the actual rename work. Compress to **three batched PRs** instead, sized so the small batch still exercises both codemods end-to-end on a tiny surface before the bulk of the work:

1. **PR 1 (small batch, 3 renames)** — `config/api.py` + `apps/core/` + the already-shipped pagination touch-up. Renames: `StatsSchema → SiteStatsSchema`, `LinkTargetsResponseSchema → LinkTargetListSchema`, `PaginationParams → PaginationParamsSchema`. Debugs the codemods end-to-end on three modules and three renames.
2. **PR 2 (medium batch, ~14 renames)** — `media` (4) + `citation` (5) + `provenance` (5). Introduces the `In → Input`, `Out → ∅`, and entity-scoping patterns (`Extract*Schema → CitationExtract*Schema`, `SourceSchema → CitationSourceSchema`, etc.). The provenance `SourceSchema → CitationSourceSchema` collides with `apps.citation.models.CitationSource` already imported in `provenance/api.py`; the `Schema` suffix is what keeps them disambiguated, which is the whole point.
3. **PR 3 (large batch, ~25 renames)** — `catalog`. The bulk of the work. Includes role-suffix decisions (`PersonSchema → PersonListItemSchema`), embedded sub-shape renames (`SystemSchema → ManufacturerSystemSchema`), the `Machine → Model` purge (`MachineModelDetailSchema → ModelDetailSchema`, `TitleMachineSchema → TitleModelSchema`, etc.), and the `*Ref`-exception strip-throughs (`TitleRefSchema → TitleRef`, `ModelRefSchema → ModelRef`, `Ref → EntityRef`, `GameplayFeatureSchema → GameplayFeatureRef`). **Run `Ref → EntityRef` in dry-run first** — it's the only 3-character target and the most identifier-collision-prone rename in the table; eyeball the diff before letting it land. Known false-positive: 2 string-literal hits in [frontend/src/lib/components/form/markdown-textarea-citation.dom.test.ts](../../../../frontend/src/lib/components/form/markdown-textarea-citation.dom.test.ts) (`'Ref '` and `` `Ref [[cite:…]]` `` as user-typed search text in a test fixture) will be rewritten to `EntityRef`; revert those post-codemod.
4. **PR 4 (`Paged*Schema` ghost fix)** — non-codemod PR. Introduces `NamedPaginatedResponseSchema` (mirrors `NamedPageNumberPagination`) so the four Ninja-auto-named wrappers get stable names: `PagedTitleListSchema → TitleListSchema`, `PagedMachineModelListSchema → ModelListSchema`, `PagedPersonSchema → PersonListSchema`, `PagedManufacturerSchema → ManufacturerListSchema`. Must come **after** PR 3 since the wrapper-slot names (`TitleListSchema`, `ModelListSchema`) are only freed once the row schemas have moved to `…ListItemSchema`.

If a batch reveals a script defect, revert just that PR — three PRs still gives reasonable bisect granularity, and PR 1's tiny surface catches script-development bugs before PR 2/3 expose them at scale.

#### Caveats

- The codemod must cover `backend/**/*.py` (including `backend/config/api.py`,
  which holds `StatsSchema → SiteStatsSchema`), not just `apps/*/schemas.py` —
  tests and fixtures reference schema names too.
- `RelationshipSchema` in `apps/provenance/validation.py` is a `@dataclass`,
  not a Ninja schema, so it never reaches OpenAPI and the rename rules don't
  apply. Excluding it keeps a Python-level grep from producing a false hit.
- The Python rename codemod no longer has to think about Django-model name
  collisions, because no rename produces a bare `Claim` / `ChangeSet` /
  `CitationInstance` / `Source` / `Credit`. The `Schema` suffix is exactly
  what keeps Python files importing both `from .models import ChangeSet`
  and `from .schemas import ChangeSetSchema` unambiguous.

#### Rollback

Batched PRs are independently revertible. If a later PR reveals a script defect that retroactively breaks an earlier rename, revert the affected PRs in reverse order. The inverse transform is mechanical — swap keys/values in the rename table, re-run the codemod — but in practice `git revert` on the merged PR is faster.

PR 0 is also revertible — it's a pure import-style change with no semantic effect.

### Ghost-type fixes

Some OpenAPI components don't come from explicit Ninja schema classes — Ninja auto-generates them from internal class names inside its `@paginate` machinery. They need source-side fixes that don't fit the rename codemod. Two are tracked here: the already-shipped `Input` fix, and the `Paged*Schema` family fix that closes out the rename effort.

`JsonBody` is **not** a ghost type to fix — it's the deliberate, project-wide name for "an arbitrary JSON object" and is used pervasively in the backend (see [apps/core/types.py:19](../../../../backend/apps/core/types.py#L19)). It surfaces as a named OpenAPI component because the PEP 695 `type` alias is what Pydantic registers, and that's the desired outcome: every `extra_data`-style field `$ref`s the same `JsonBody` component, frontend consumers can `import type { JsonBody }`, and the meaning is unambiguous. Do not rename, inline, or otherwise touch `JsonBody`.

#### Status

| Step                                                               | Status |
| ------------------------------------------------------------------ | ------ |
| `Input` ghost fix (`NamedPageNumberPagination`)                    | DONE   |
| PR 0 (TS-side indexed-access → named-imports sweep)                | DONE   |
| PR 1 (small batch: config + core + pagination touch-up)            | DONE   |
| PR 2 (medium batch: media + citation + provenance)                 | DONE   |
| PR 3 (large batch: catalog)                                        | DONE   |
| PR 4 (`Paged*Schema` ghost fix via `NamedPaginatedResponseSchema`) | DONE   |
| Boundary tests (`apps/core/tests/test_openapi_boundaries.py`)      | DONE   |

When picking this up in a fresh session: read this plan top-to-bottom, then `git log refactor/api-renaming` to see what's already landed, then start at the next TODO.

#### `Input` — orphan from Ninja's pagination

`components.schemas.Input` exists with zero `$ref`s pointing at it (verified via jq). The source is Ninja's `PageNumberPagination.Input` inner class — Ninja registers it as a component side-effect of `@paginate(PageNumberPagination, ...)`, even though the path-level params are inlined and the component is never referenced.

**Spike result**: subclassing works. A `PageNumberPagination` subclass with an inner `PaginationParams` Schema and `Input = PaginationParams` produces a `PaginationParams` component in OpenAPI. After replacing all four `@paginate(PageNumberPagination, ...)` sites with the subclass, `Input` disappears entirely — only `PaginationParams` remains. All four endpoints share one component (no duplication).

**Fix**:

1. Add `apps/core/pagination.py` with a single `NamedPageNumberPagination` subclass:

   ```python
   class NamedPageNumberPagination(PageNumberPagination):
       class PaginationParams(Schema):
           page: int = Field(1, ge=1)
           page_size: int | None = Field(None, ge=1)

       Input = PaginationParams  # type: ignore[assignment]
   ```

2. Replace `@paginate(PageNumberPagination, ...)` with `@paginate(NamedPageNumberPagination, ...)` at all 4 call sites:
   - [backend/apps/catalog/api/machine_models.py:589](../../../../backend/apps/catalog/api/machine_models.py#L589)
   - [backend/apps/catalog/api/people.py:211](../../../../backend/apps/catalog/api/people.py#L211)
   - [backend/apps/catalog/api/titles.py:651](../../../../backend/apps/catalog/api/titles.py#L651)
   - [backend/apps/catalog/api/manufacturers.py:241](../../../../backend/apps/catalog/api/manufacturers.py#L241)
3. Run `make codegen`; verify `Input` is gone, `PaginationParams` is present.

Single small PR. No frontend changes (nothing references the orphan today).

### Boundary tests

After all rename PRs land, the conventions worth pinning will be clearer.
Likely candidates, to be confirmed against what actually shipped:

- Schema suffix discipline: per
  [ApiNamingRationalization.md](ApiNamingRationalization.md), every name in
  `components.schemas` ends in `Schema`, ends in `Ref`, or equals
  `JsonBody`; no name ends in `In` or `Out`; and none of the
  previously-generic names (`Variant`, `Source`, `Stats`, `Recognition`,
  `Create`, `Input`, `SearchResponse`, bare `Ref`) appear. Target
  `components.schemas`, not Python class names, so dataclasses like
  `RelationshipSchema` aren't false hits. Verified clean against the
  current OpenAPI doc (156 names, zero violations).
- Inline schemas in endpoint files don't grow: regression-style check that
  counts `class … (Schema)` definitions in `apps/*/api.py` (and
  `apps/*/api/*.py`) per app and fails if any app's count exceeds today's
  baseline. Today's baselines: `citation` 15, `accounts` 4, `media` 4,
  `provenance` 8. Not a migration-forcing test — it pins the convention
  going forward without requiring the existing inline schemas to move
  first. New schemas must go in `schemas.py`; the eventual cleanup of the
  31 existing inline classes is tracked separately.
- Every mutating endpoint (`POST`/`PATCH`/`DELETE`) declares typed 4xx
  responses in its OpenAPI definition. `ValidationErrorSchema` and
  `RateLimitErrorSchema` are wired into the doc, but no test currently
  asserts that mutating endpoints reference them — write one that iterates
  paths in the live OpenAPI doc and fails if a mutating operation has no
  `4xx`-keyed entries under `responses`.
- (The ESLint `no-restricted-syntax` rule banning `components['schemas']`
  indexed access outside `client.ts` ships **inside PR 0**, not here — see
  [PR 0](#pr-0-ts-side-sweep-indexed-access--named-imports). This section
  no longer needs to add it.)

Existing precedent at
[backend/apps/catalog/tests/test_api_schema_boundaries.py](../../../../backend/apps/catalog/tests/test_api_schema_boundaries.py)
is the model: assertions against the live OpenAPI doc and module locations,
not text-pattern checks.

The session for this task should treat the candidate list as input, not as a
spec — some items may turn out to be too noisy to enforce, others may have
been resolved during the rename in ways that change what the test should
assert.

## Acceptance checks

Per task: `make lint`, `make test`, `pnpm check` (svelte-check, distinct from `make lint`'s eslint/prettier/ruff), `make codegen`, and a spot-check of the running app via `make dev` where appropriate.

PR 0 (indexed-access sweep):

- `grep -r "components\['schemas'\]" frontend/src --include="*.ts" --include="*.svelte" | grep -v "lib/api/client.ts"` returns zero matches.
- `pnpm check`, `pnpm lint`, `pnpm test` pass. `pnpm lint` includes the new `no-restricted-syntax` rule banning `components['schemas']` outside `client.ts` — its zero violations are part of the acceptance signal.
- `pnpm format` has been run; no pending whitespace churn in `git diff`.
- No backend changes; `make codegen` is a no-op.

Per batched rename PR (PR 1–3; partial — only the schemas in that PR's scope have been renamed):

- After `make codegen`, the old names are gone from the OpenAPI doc:
  `jq -r '.components.schemas | keys[]' backend/openapi.json | grep -E '^(OldName1|OldName2|...)$'`
  returns nothing.
- `git diff` of `openapi.json` op IDs is empty (verified once on the first PR; spot-check thereafter).
- No `components['schemas']` indexed access reintroduced (the post-PR-0 ESLint rule enforces this automatically).

Ghost-type fix PRs:

- After the `Input` PR (whichever option is chosen): either `jq '.components.schemas.Input' backend/openapi.json` returns `null`, or the orphan is renamed to a non-generic name and added to the boundary-test allowlist.

After the final rename PR lands:

- Every name in `components.schemas` either ends in `Schema`, ends in `Ref`,
  or is `JsonBody`. Asserted by a boundary test against the live OpenAPI
  doc.
- No component name ends in `In` or `Out`.
- None of the previously-generic names (`Variant`, `Source`, `Stats`,
  `Recognition`, `Create`, `Input`, `SearchResponse`, bare `Ref`) appear in
  `components.schemas`.
- Every schema in `components.schemas` is exposed as a top-level type alias
  in `schema.d.ts` (the `--root-types` flag is on).
- No `components['schemas']` indexed access remains outside `client.ts`
  (enforced by the ESLint rule landed in PR 0).

## Follow-ups

See [ApiSvelteBoundaryFollowups.md](ApiSvelteBoundaryFollowups.md).
