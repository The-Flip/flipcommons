# Reviewing

This document is for AI reviewers. It's a checklist of project-specific rules.

## Review Priorities

When reviewing a change, check in roughly this order:

1. behavioral regressions
2. architectural rule violations
3. missing tests or weak verification
4. documentation or generated-artifact drift
5. style and cleanup issues

Do not lead with style feedback when there are more important correctness or architecture problems.

## Repo-Specific Checks

### App boundaries

When a change adds modules, imports, or new backend entrypoints, check [AppBoundaries.md](AppBoundaries.md).

In particular:

- `core` should not depend on `catalog`, `citation`, `provenance`, or `media`
- `catalog`, `provenance`, and `media` must not depend on each other (peer isolation)
- `provenance` depends on `citation` but `citation` does not depend on `provenance`
- new APIs for catalog entities usually belong in `apps.catalog`
- cross-app coupling should be treated as an architecture issue, not a convenience refactor

### Claims and provenance

When a change touches catalog models, fields, or relationships, check [Provenance.md](Provenance.md) and [DataModeling.md](DataModeling.md).

In particular:

- new catalog fields must be claim-controlled (exceptions require explicit user approval)
- "only one source today" is not a valid reason to bypass provenance
- model constraints should be enforced in the database, not only in Python

### Svelte SSR / CSR boundaries

When a change touches routes, layouts, or data loading, check [Svelte.md](Svelte.md).

In particular:

- public content pages should usually use SSR
- authenticated or highly interactive app surfaces may need `ssr = false`
- changing a parent layout's SSR mode can silently change all child routes — audit child routes and add explicit `ssr = false` where needed
- SSR routes must use `createServerClient` from `$lib/api/server`, not the browser client or ad hoc fetch

### Authorization

When a change touches mutating API routes, user-state gates, role checks,
frontend affordances, or structured 403s, check [Authz.md](Authz.md).

In particular:

- every mutating route should be classified with `@requires`, `@gated_inline`, or `@public_mutation`
- new product gates should use `Activity` and policy rules, not raw `is_staff`, `is_superuser`, or `email_verified` checks
- frontend code should consume capabilities, not reimplement policy logic
- target-aware predicates should use narrow Protocols and have zero-query tests
- denial responses should use closed `DenialCode` values and backend-owned messages

### Page-oriented APIs

When a change introduces or changes web-facing endpoints for pages, check [ApiDesign.md](ApiDesign.md).

In particular:

- important SSR pages should usually fetch one page-oriented endpoint
- page-shaped endpoints should usually live under `/api/pages/...`
- those endpoints should usually be tagged `tags=["private"]`
- avoid frontend fanout when the backend can return the page model directly

### Type strength (backend)

When a change touches Python signatures, return types, or data structures, check [Python.md](Python.md) for the smell catalogue and legitimate exception shapes.

Treat each of these as a closer-look trigger, not an automatic finding:

- `Any` or `object` in parameter or return annotations
- `cast(Any, ...)` — no legitimate use
- `dict[str, Any]` in non-test signatures where callers pass dict literals with consistent keys
- `tuple[...]` with three or more positional fields, or the same tuple shape repeated across modules
- `isinstance` checks on values whose upstream signature could be narrower
- `TYPE_CHECKING`-only imports paired with `cast` or stringified annotations
- bare or unexplained `# type: ignore` (should be `# type: ignore[<code>]` with a reason)
- bare or unexplained `# noqa` (should be `# noqa: <code>` with a reason; ANN401 noqas matching [Python.md](Python.md)'s exception shapes are correct, not findings)

The fix is usually a NamedTuple, dataclass, or TypedDict — not a type alias, which leaves callers indexing by position. Don't flag a hit that [Python.md](Python.md) lists as a legitimate exception (Django management `**kwargs`, signal receivers, Ninja dispatch, JSON parse results, framework-owned callback surfaces).

### Deployment/runtime assumptions

When a change affects routing, SSR, startup, or runtime ports, check [Hosting.md](Hosting.md) and [Architecture.md](Architecture.md).

In particular:

- same-origin assumptions must remain coherent
- Caddy, Django, and SvelteKit routing must agree
- health checks should reflect real readiness, not only partial readiness
- features that introduce new production env vars or configuration should be gated by a refusal check per [DeployAutomation.md](DeployAutomation.md) — typically a [BuildChecks.md](BuildChecks.md) ARG declaration for build-time secrets, a [DeployChecks.md](DeployChecks.md) preflight for runtime vars, or both — so a missing or malformed value fails the deploy instead of degrading silently

## Generated And Derived Artifacts

Review whether the change also needed to update derived artifacts.

Common examples:

- OpenAPI-derived frontend types after API changes
- `AGENTS.md` / `CLAUDE.md` after editing `docs/AGENTS.src.md`
- docs that describe route behavior, hosting, or API shape after architecture changes

Missing regeneration is a valid finding when it will leave the repo inconsistent.

## What Counts As A Finding

Call something a finding when it is likely to cause one of these:

- broken behavior
- architectural drift that will make later work harder or unsafe
- misleading tests that no longer prove what they claim
- documentation or generated files that leave the repo internally inconsistent

Prefer concrete, repo-specific reasoning over abstract best practices.

## What Usually Does Not Count

These are usually not findings by themselves:

- a different but coherent style choice
- a simplification you would not personally choose
- a hypothetical cleanup that is unrelated to the change
- a test shape you would prefer, if the current test still proves the intended behavior

Do not invent blockers just because a different design would also work.

## Review Discipline

Before flagging an issue:

- check the relevant doc for the area
- verify that the code actually violates that doc or contract
- distinguish a stale reference from a runtime bug
- prefer one precise finding over three speculative ones

The goal is not to maximize comments. The goal is to catch real problems and keep the repo aligned with its own rules.
