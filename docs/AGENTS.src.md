# Development Guide

START_IGNORE

This is the source file for generating [`CLAUDE.md`](../CLAUDE.md) and [`AGENTS.md`](../AGENTS.md).
Do not edit those files directly - edit this file instead.

Regenerate with: make agent-docs

Markers:

- START_CLAUDE / END_CLAUDE - content appears only in [`CLAUDE.md`](../CLAUDE.md)
- START_AGENTS / END_AGENTS - content appears only in [`AGENTS.md`](../AGENTS.md)
- START_IGNORE / END_IGNORE - content stripped from both (like this block)

END_IGNORE

This file provides guidance to AI programming agents when working with the Flipcommons project, an interactive, collaborative database of pinball knowledge.

## Project Overview

Flipcommons is a Django + SvelteKit monorepo. Django owns the data model, APIs (Django Ninja), and admin UI. SvelteKit handles the user-facing frontend with Node SSR for public pages and CSR for authenticated app pages.

## Requirements

- Python 3.14+
- Node 24+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [pnpm](https://pnpm.io/) (Node package manager, or enable via `corepack enable`)

## Getting Started

```bash
cp .env.example .env
make bootstrap
make dev
```

Then open http://localhost:5173

To create a Django admin superuser:

```bash
cd backend && uv run python manage.py createsuperuser
```

## Development Commands

```bash
make bootstrap    # Install all deps, run migrations, generate API types
make dev          # Start Django + SvelteKit dev servers
make test         # Run pytest (backend) + vitest (frontend)
make lint         # Run ruff (backend) + eslint/prettier (frontend)
make mypy         # Run backend type checks
make quality      # Lint + regenerate API types + svelte-check
make api-gen      # Regenerate frontend API types from the backend schema
make pull-ingest  # Download catalog data from R2
make ingest       # Run full ingestion pipeline
make agent-docs   # Regenerate CLAUDE.md and AGENTS.md
```

## Project Structure

```text
backend/          Django project (uv, pyproject.toml)
  config/         Django settings, urls, wsgi, asgi
  apps/           Django apps
frontend/         SvelteKit project (pnpm)
  src/lib/api/    Generated types (schema.d.ts) + hand-written client (client.ts)
  src/routes/     SvelteKit routes
scripts/          POSIX shell scripts
docs/             Documentation source files
```

## Key Conventions

- Backend dependencies managed with `uv`, frontend with `pnpm`
- Session cookies for auth (no JWT, no CORS); SPA auth gates are UX-only — the backend is the source of truth for access control
- CSRF: Django sets `csrftoken` cookie; the frontend `client.ts` reads it and sends `X-CSRFToken` on mutating requests
- Vite dev server proxies `/api/`, `/djadmin/`, `/media/`, and `/static/` to Django at `127.0.0.1:8000`
- For SSR route conventions, see [Svelte.md](Svelte.md). For API design — both endpoint shape (page-oriented vs resource) and schema design heuristics (when to consolidate, when to keep separate, inheritance smells) — see [ApiDesign.md](ApiDesign.md)

### Generated API Types

The system generates frontend Typescript types from the backend Python API types.

#### `schema.d.ts` is gitignored

`frontend/src/lib/api/schema.d.ts` is generated and **not committed**. Do not stage or commit it.

#### Run `make api-gen` to regenerate API types

After adding or changing any API endpoint, run `make api-gen` to regenerate it — the typed client will not see new endpoints until you do.

#### ALWAYS use named imports

When importing a generated schema type, you MUST use the named export. NEVER use indexed access into `components`:

```ts
// Right
import type { ValidationErrorBodySchema } from "$lib/api/schema";

// Wrong — NEVER traverse the nested path
import type { components } from "$lib/api/schema";
type X = components["schemas"]["ValidationErrorBodySchema"];
```

`schema.d.ts` re-exports every component as a named alias precisely so consumers don't have to walk `components['schemas'][...]`. If a needed type isn't exported by name, that's a codegen-config bug to fix — not a license to use the indexed form.

#### Derive wire-shape unions from the schema; don't redeclare them

When you need a subset of a generated type's field — most commonly a Literal union like an error `reason` or `kind` — derive it from the schema with indexed access on the _imported_ name (not the `components` traversal above):

```ts
// Right — derives from the generated source of truth
import type { SignupCheckResponseSchema } from "$lib/api/schema";
type CheckReason = NonNullable<SignupCheckResponseSchema["reason"]>;

// Wrong — silently drifts from the backend after the next api-gen
type CheckReason =
  | "too_short"
  | "too_long"
  | "bad_charset"
  | "reserved"
  | "taken";
```

A locally-redeclared Literal stays right until the backend adds a value, at which point it silently narrows the wire shape and the frontend stops handling the new case. The derived form catches it at type-check time.

### Frontend URLs and `resolve()`

Use SvelteKit's `resolve()` from `$app/paths` for internal routes by default. `resolve()` is strongly typed against the project's route tree and accepts dynamic params, so prefer it even when the URL has runtime values — it catches typos and route renames at compile time:

```svelte
<script lang="ts">
  import { resolve } from '$app/paths';
</script>

<a href={resolve('/users/[username]', { username })}>{username}</a>
<a href={resolve('/models/[slug]', { slug: model.slug })}>{model.name}</a>
```

Only fall back to `$lib/utils/resolveHref()` when the route **pattern** itself isn't known at the call site — for example, an href returned from the API, or a base path passed as a prop:

```svelte
<a href={resolveHref(model.href)}>{model.name}</a>
<a href={resolveHref(`${basePath}/${slug}`)}>{label}</a>
```

`resolveHref` casts through `as any` to bypass the route-pattern type, so each caller is silently opting out of type safety. Keep its surface area small.

The `svelte/no-navigation-without-resolve` ESLint rule is disabled project-wide because it doesn't recognize the wrapper.

## Critical Rules — Non-Negotiable

These rules exist because agents have repeatedly gotten them wrong. Read them before writing code.

### Python: `except A, B:` is correct

`except ExcType1, ExcType2:` is **valid Python 3** and is ruff-format's preferred style.
Do NOT add parentheses. `except (ExcType1, ExcType2):` will be reverted by ruff-format every time. Stop trying to fix it.

### Svelte 5 runes mode only

The frontend uses **Svelte 5 runes mode** (`runes: true` in compiler options). Do NOT use legacy Svelte 4 patterns:

- `export let` → use `let { } = $props()`
- `$:` reactive declarations → use `$derived` / `$derived.by()` / `$effect()`
- `on:click` directive syntax → use `onclick` attribute
- `createEventDispatcher` → use callback props
- `<slot>` → use `{@render children()}` snippets
- `$$props` / `$$restProps` → use `$props()` with rest syntax

### No `:global` in Svelte styles

NEVER use `:global` in Svelte component styles without explicit approval from the user. Scoped styles are the default and preferred approach. We rearchitect components rather than use `:global`.

### Don't restyle basic form elements

`frontend/src/app.css` owns global styles for `input[type='text']` (and the other text-like input types listed there), `textarea`, and `select` — width, padding, border, background, border-radius, font. Components consuming these elements should NOT re-declare those properties. Override only when you need a state-specific tweak (e.g. `input[aria-invalid='true'] { border-color: ... }`).

The same applies to layout primitives served by `Page.svelte`, `Button.svelte`, `FieldGroup.svelte`, etc. — check the component first, only roll your own when no existing primitive fits.

### Authorization goes through activities

Backend authorization gates product actions through `Activity` rules in `apps/core/authz/`; frontend auth checks are UX hints only. For mutating backend routes, use `@requires(Activity.X)`, `@gated_inline(Activity.X)`, or `@public_mutation("reason")` so the route inventory stays complete.

Do NOT add new raw `is_staff`, `is_superuser`, or `email_verified` checks to decide whether a user may perform a product action. Add or use an `Activity` instead. Do NOT mirror policy logic in Svelte — use `auth.can("activity.name")` for target-less affordances and row `capabilities[...]` for target-aware affordances.

For predicate design (purity, target Protocols, denial messages), see [docs/Authz.md](Authz.md).

### All user-inputted catalog fields MUST be claims-based

**Every user-inputted catalog field MUST be claims-based**: scalars, FKs, M2M, slugs, parents, aliases. This includes ingested data that goes into fields that users can input.

**System-generated fields aren't claims-based**: `id`/`uuid`, timestamps, derived fields like `Location.location_path = f"{parent.location_path}/{slug}"`.

The test is "could a user input this field?" If yes, claim it. If no, it's system-generated. There is no third category. See [docs/Provenance.md](Provenance.md) for the architecture.

#### Writing ChangeSets — `action` is required on user ChangeSets

Every `ChangeSet` attributed to a user must carry an `action` value (`create`, `edit`, `delete`, or `revert`). Ingest ChangeSets never do — they're identified by the `ingest_run` FK. The DB enforces this via the `provenance_changeset_action_iff_user` check constraint, so forgetting means an `IntegrityError`, not a code-review catch. For catalog record lifecycle semantics, see [docs/RecordLifecycle.md](RecordLifecycle.md#record-lifecycle).

Prefer the factories over `ChangeSet.objects.create` in new code:

- Application code: call `execute_claims(entity, specs, user=..., action=ChangeSetAction.EDIT)` — the action kwarg is required at the type level for readability, even though `EDIT` is the default. Revert writes use `ChangeSetAction.REVERT`. Create flows use `ChangeSetAction.CREATE`.
- Test fixtures: use `from apps.provenance.test_factories import user_changeset, ingest_changeset` instead of constructing `ChangeSet` rows directly. The factories encode the constraint invariants so mistakes fail at call time, not at DB time.

### General rules

- Don't silence linter warnings — fix the underlying issue
- Never hardcode secrets — use environment variables via `.env`
- Describe your approach before implementing non-trivial changes

START_CLAUDE

## Tool Usage

Use Context7 (`mcp__context7__resolve-library-id` and `mcp__context7__query-docs`) to look up current documentation when:

- Implementing Django features (models, views, forms, admin, etc.)
- Working with SvelteKit routing, adapters, or configuration
- Configuring Railway hosting and deployment
- Answering questions about library APIs or best practices

GitHub access:

- Use the GitHub MCP server for read-only operations (listing/viewing issues, PRs, commits, files)
- Use the `gh` CLI for writes or auth-required actions (creating/updating/commenting/merging)

END_CLAUDE

START_AGENTS

## Environment Setup (Codex Cloud)

The Makefile works without a venv — it detects the environment automatically.

**Setup command**: `bash scripts/bootstrap`

After setup, use the standard commands:

```bash
make test         # Run tests
make lint         # Lint and format check
```

**Notes:**

- Internet is disabled during task execution — all dependencies must be installed during setup
- Tests use SQLite in-memory by default
- Use the `gh` CLI for GitHub operations
- For multi-session Codex worktree setup only, see [docs/CodexWorktrees.md](docs/CodexWorktrees.md)

END_AGENTS

## Data Ingestion

The catalog app has management commands for importing from external data sources (IPDB, OPDB, Fandom wiki, etc.). Run `make pull-ingest` to download data from R2, then `make ingest` to run the pipeline. See [docs/Ingest.md](Ingest.md) for sources, file formats, and production ingestion steps.

## Pre-commit Hooks

Pre-commit hooks auto-regenerate `CLAUDE.md` and `AGENTS.md` when `docs/AGENTS.src.md` changes, and block direct edits to those generated files. Hooks also run ruff, ESLint, type checks, and the full test suite. Do not edit `CLAUDE.md` or `AGENTS.md` directly — edit `docs/AGENTS.src.md` instead.

## Deployment

Single Railway service: Caddy fronts SvelteKit Node SSR and Django/Gunicorn inside one container. Multi-stage Dockerfile builds the frontend with Node/pnpm, then copies the SSR runtime into the Python image. WhiteNoise still serves Django static assets, while Caddy routes frontend requests to SvelteKit and `/api/`/`/djadmin/` to Django. See [docs/Hosting.md](Hosting.md) for setup and troubleshooting.

## Testing

- For any change, identify and run the smallest meaningful test set.

### Bug Fixes Require TDD — Non-Negotiable

When fixing a bug, you **MUST** follow this exact order:

1. **Write a failing test first** that reproduces the bug.
2. **Run the test** and confirm it fails for the expected reason.
3. **Then fix the code** to make the test pass.
4. **Run the test again** and confirm it passes.

Do NOT skip step 1. Do NOT write the fix first "to understand the problem" and backfill tests after. The failing test _is_ how you understand the problem.

### New Features

For new behavior, include tests. Consider writing the test first, though sometimes that's more trouble than it's worth.

## Strong Typing (backend)

Code MUST be as strongly typed as possible.

The following smells are _sometimes_ legitimate, but are usually a sign the type can be tightened:

- Use of `Any`, `object`, `cast`, `isinstance`, `setattr`, `getattr`, `TYPE_CHECKING`, `# type: ignore`, `# noqa`
- Compound types in signatures whose meaning isn't obvious from the types alone — `tuple[...]`, nested dicts (`dict[X, dict[Y, Z]]`), `Callable[[A, B, C], R]`. **Heuristic**: if a reader would need a comment to know what each position/key means, name it. Applies to 2-tuples that cross a module boundary or appear in a public signature; locally unpacked pairs (`found, value = _lookup(key)`) are fine as plain tuples.

Prefer NamedTuple, dataclass, or TypedDict. For worked examples (including the no-op decorator pattern that pins `Callable` implementations to a typed contract) and the full catalogue of exceptions, see [docs/Python.md](Python.md).

## Data Modeling

See [DomainModel.md](DomainModel.md) for the catalog entity hierarchy (Title → Model, variants, remakes, manufacturers, taxonomy, etc.).

See [SingleModelTitles.md](SingleModelTitles.md) for how the catalog handles Titles with exactly one Model — the UI collapse rule, the asymmetric Title/Model info split, and the description forward-compat rule.

See [docs/DataModeling.md](DataModeling.md) for modeling principles, Django pitfalls, and constraint testing patterns. Key rules:

- **Validate strictly** — start with the tightest constraint you can defend. Relaxing is a one-line migration; tightening requires auditing every row.
- **Validate in the database** — `full_clean()` is optional; CHECK constraints are not. Use `field_not_blank()`, CHECK constraints for enums/ranges, and UNIQUE constraints for identity rules.
- **Default to `PROTECT`** on foreign keys. Use `CASCADE` only for wholly owned children.

## Code Review

When reviewing code or a PR, read [docs/Reviewing.md](Reviewing.md) first and follow its checklist.

## Related Repos

This project has two sister projects:

### Catalog seed records

**[pindata](https://github.com/deanmoses/pindata)**: pre-launch seed canonical catalog records (markdown files + JSON schemas). It publishes the catalog as JSON to Cloudflare R2 and this project pulls it down from R2 via `make pull-ingest`.

### Analytics DB over pinball data

**[pinexplore](https://github.com/deanmoses/pinexplore)**: DuckDB exploration/validation database for exploring the Pindata data as well as other sources of pinball knowledge.
