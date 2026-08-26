# API Design

This document defines how backend APIs should be designed for the web application, and how the frontend should consume them.

It covers three concerns:

- **Endpoint design** — how to shape endpoints (page-oriented vs resource), where data should come from, and how SvelteKit pages should obtain it from Django.
- **Schema design** — how to structure individual Django Ninja schemas: when to consolidate, when to keep separate, and what inheritance patterns smell.
- **Error response declarations** — which 4xx/429 shapes to declare in `response={…}` and which to leave silent.

## Endpoint design

### Two API types

The backend serves two distinct kinds of endpoints for different purposes:

| API type     | Path             | Purpose                                   |
| ------------ | ---------------- | ----------------------------------------- |
| Resource API | `/api/...`       | Reusable domain data and write operations |
| Page API     | `/api/pages/...` | One route's rendering payload             |

- **Resource APIs** under `/api/...` expose reusable domain data: CRUD operations, autocomplete, lookups, edit forms, and bulk exports.
- **Page APIs** under `/api/pages/...` expose route-shaped payloads optimized for one page. A page endpoint returns a **page model**: exactly the data one specific page needs to render.

### Core rule

Prefer **page-oriented endpoints** over client-or-server fanout.

For an important page, especially an SSR page, the default should be:

- one route-specific backend endpoint
- one fetch in the page load path
- one response shaped for that page

Do not default to building a page by calling several generic endpoints and stitching them together in Svelte.

### Why

This rule exists for performance, reliability, and code clarity.

#### Lower latency

Every extra API call is on the critical path to HTML.

For SSR pages, a route that calls four endpoints is usually slower than a route that calls one page-oriented endpoint that already contains the data the page needs.

#### Less orchestration in the frontend

The page should render data, not assemble it.

Hierarchy expansion, related-object selection, sorting rules, fallback logic, and other page composition policy usually belong in Django, not repeated in Svelte route code.

#### Better failure behavior

One page endpoint can fail coherently.

Fanout produces partial-failure cases where one call succeeds, another fails, and the frontend has to guess how to degrade.

#### Better caching

A page-model response is easier to cache than several smaller calls with page-specific merge logic in the frontend.

### What a good page endpoint looks like

A good page-oriented endpoint:

- returns exactly the fields the page needs
- includes already-expanded related data the page needs to render
- applies the page's canonical sort and selection rules
- avoids forcing the route to issue follow-up fetches for obvious related data
- has a stable response shape that maps cleanly to the page UI
- is tagged `tags=["private"]` in Django Ninja so it does not appear in the public API docs (page endpoints are internal website endpoints, not part of the public reusable API surface)

The response is a **page model**, not a raw dump of the underlying database model.

### Namespace convention

Page-oriented endpoints should usually live under a distinct namespace:

- reusable resource endpoints stay under `/api/...`
- page-shaped view-model endpoints should usually live under `/api/pages/...`

Examples:

- `/api/titles/{slug}` for the canonical title resource
- `/api/pages/title/{slug}` for the title detail page model
- `/api/pages/home` for the homepage payload

This is not about following a universal industry standard. It is about keeping two different API types clearly separated:

- resource APIs expose reusable domain data
- page APIs expose route-shaped payloads optimized for one page

Avoid mixing page-specific view models into the general resource namespace unless there is a strong reason.

### What to avoid

For a public SSR page like a title detail page, avoid:

1. fetch the title
2. fetch related models
3. fetch related taxonomy or auxiliary lookup data
4. merge and normalize in Svelte
5. render

Prefer:

1. fetch one `title page` endpoint from `+page.server.ts` or `+layout.server.ts`
2. place that endpoint under `/api/pages/...`, for example `/api/pages/title/{slug}`
3. return a response that already contains the title, the related models the page needs, and any display-ready related data
4. render that page model directly

The backend should own the page composition rules. Svelte should render the resulting page model.

### When generic endpoints are still appropriate

Generic endpoints are still appropriate when:

- the UI is highly interactive and CSR-only
- the same resource is reused across many unrelated pages
- the route is an internal tool where SSR and crawlability do not matter
- the response is naturally resource-oriented and does not require page-specific composition

Examples:

- autocomplete
- small lookup collections
- edit forms that load one entity for mutation
- reusable internal admin-style tools

### SSR guidance

For SSR pages, assume the load path is latency-sensitive.

Default to one page endpoint for:

- public detail pages
- public index pages that need SEO
- any route where the initial HTML should contain the meaningful content

Be skeptical of SSR routes that call multiple backend endpoints from `load()`. That should be a deliberate exception, not the default design.

### How server-side routes should call Django

Server-side Svelte routes should call Django through `createServerClient` from `$lib/api/server`, not through ad hoc fetch wrappers or direct backend internals.

`createServerClient(fetch, url, request)` resolves `INTERNAL_API_BASE_URL` (Caddy's loopback listener in production, which proxies on to Django) with a fallback to the request origin (Vite proxy in dev). The `request` argument is required so the user's Cookie header is forwarded across origins. See `docs/Svelte.md` for the full pattern.

This keeps the boundary clean:

- Django remains the source of truth for data shape
- OpenAPI remains the contract
- generated TypeScript types remain in use
- SvelteKit renders data returned by Django instead of reconstructing it

Do not treat SSR routes as a place to bypass the backend contract. The page may render on the server, but it should still consume Django through the API boundary.

### Frontend / backend contract

The backend API remains the source of truth for the contract.

- Django Ninja defines the schema
- OpenAPI is generated from Django
- TypeScript types are generated from OpenAPI

After changing Django Ninja endpoint response types or schema fields, run `make codegen` so the frontend contract reflects the backend change.

The goal is not "thin backend, smart page assembly." The goal is a clean contract where the backend exports the data shape the page actually needs.

### Page-endpoint heuristic

When building a page, ask:

"If I removed all frontend data-merging code, what single backend response would I wish I already had?"

That response shape is usually the endpoint you should build.

## Schema design

These rules apply to Django Ninja schemas in `apps/*/api/schemas.py` and per-router schema modules. They are about how to structure schemas themselves, not about endpoint shape.

The rules below pull in two directions: rule 1 is the gate for any consolidation (semantics must actually match), and rules 3 and 4 are tiebreakers for when semantics _do_ match but other factors still argue for keeping schemas separate. Read them together, not à la carte.

### Verify semantic equivalence before consolidating schemas

Same field signature can hide different domain meanings. Two schemas with identical shape are not necessarily the same schema.

Before merging two schemas, ask: "do the call sites mean the same thing, or just look the same?" If the answer is "they happen to share a shape today," keep them separate.

Worked example — `gameplay_features` appears in three places with three different meanings:

| Call site                     | Type                                            | Semantics                               |
| ----------------------------- | ----------------------------------------------- | --------------------------------------- |
| Cross-model facet aggregation | `list[Ref]`                                     | which features exist, no counts         |
| Per-model listing             | `list[GameplayFeatureSchema]` with `count`      | how many of each feature this model has |
| Taxonomy hierarchy            | `list[GameplayFeatureSchema]` with `count=None` | parent/child relationships only         |

Only the third was a real consolidation candidate; it was narrowed to `list[Ref]` because the count field was load-bearing nowhere. The other two look similar but mean different things and stay separate.

### When consolidation _is_ the right call

Consolidate when one schema is provably a strict subset of another with identical semantics for the shared fields, and the call sites would benefit from a shared base for OpenAPI clarity or to enforce a shared invariant. The `DeletePreviewBase` hierarchy in [`backend/apps/catalog/api/schemas.py`](../backend/apps/catalog/api/schemas.py) is the pattern: a real shared base (entity ref + blocker info) with per-entity subclasses adding their own fields, not a shape-only parent that subclasses have to fight against. For the lifecycle meaning of delete blockers and cascade impact, see [Cascade Rules](RecordLifecycle.md#cascade-rules).

### A subclass that re-narrows a parent's field type is usually a smell

If `Child(Parent)` has to override `field: X | None` to `field: X`, the parent often isn't actually shared — it's a shape-only base class. Flatten it: let each schema declare what it needs, inheriting from the real common base (or from `Schema` directly).

Count the actually-shared fields before deciding. If the parent shares five fields and only one is re-narrowed, the inheritance may still be earning its keep. If the parent shares one field and it's the re-narrowed one, the inheritance is pure overhead.

The legitimate case for a shape-only base is when several endpoints need to reuse the same generated OpenAPI component for client ergonomics. That's a deliberate choice, not an accident — document it.

### Keep entity-specific scalars separate even when their type matches

The same `int` shape can mean very different things to the consuming UI. `active_children_count`, `active_credit_count`, and `active_model_count` on the various delete-preview schemas are all `int`, but they mean different things — blocker count from one relationship, cascade-impact count, blocker count from a different relationship. Don't collapse them under a generic `count` field. Those distinctions come from the lifecycle policy in [Cascade Rules](RecordLifecycle.md#cascade-rules).

This is the inverse of the consolidation rule: don't merge separate scalars into a generic name just because their type matches.

### Naming an entity preserves a future expansion point

A schema that is shape-equivalent to `Ref` (just `name + slug`) may still be worth keeping under its own name if the entity is plausibly going to grow display fields. Collapsing it to `Ref` is a one-line save now, but reintroducing the named schema later means touching every call site.

The cost isn't free, though: every named schema is another OpenAPI component, another import, and another thing for new contributors to keep straight when browsing `schemas.py`. When the entity has a plausible growth path, keep the named schema. When it's a stable terminal value (e.g., a tag, a status), collapsing to `Ref` is fine.

### Use schemas as the API boundary type

When helper code builds an API response shape, return the Ninja/Pydantic `Schema` instance, not a `dict` that the endpoint later revalidates into the same schema. If no schema exists for that response shape, add one rather than maintaining a parallel `TypedDict`.

Use dicts only when the dict is the real runtime contract, such as cached JSON-byte responses. In that case, leave a short comment naming the cache/wire contract.

### Don't mutate response schemas as accumulators

Collect intermediate state in a private mutable structure, then construct the response schema once.

### Document Pydantic union-dispatch dependencies

When two response schemas participate in a union and Pydantic discriminates between them by shape (presence/absence of fields, `extra="forbid"` to reject sibling fields), document it in the schema's docstring. These constraints look like noise without context and are easy to break in an unrelated refactor.

See `AlreadyDeletedSchema` and `SoftDeleteBlockedSchema` in [`backend/apps/catalog/api/schemas.py`](../backend/apps/catalog/api/schemas.py) for the pattern: required fields and `extra="forbid"` together force union dispatch to route the right body to the right arm.

## Error response declarations

Mutating endpoints should declare their 4xx/429 failure shapes in `response={…}` so the OpenAPI doc reflects what callers can actually receive. Stock 400/401/403/404 from `HttpError(...)` don't need declaration — they always produce `{"detail": str}` and every contract reader knows that. Read paths (authenticated or not) stay silent on 4xx.

### Error schemas

Shared shapes live in [`backend/apps/core/schemas.py`](../backend/apps/core/schemas.py) and [`backend/apps/core/authz/schemas.py`](../backend/apps/core/authz/schemas.py):

| Schema                  | Wire shape                                         | Produced by                                                         |
| ----------------------- | -------------------------------------------------- | ------------------------------------------------------------------- |
| `ErrorDetailSchema`     | `{"detail": str}`                                  | Plain `HttpError(…)`, throttle middleware                           |
| `ValidationErrorSchema` | `{"detail": {message, field_errors, form_errors}}` | `StructuredValidationError`, Ninja's malformed-body 422 (see below) |
| `RateLimitErrorSchema`  | `{"detail": {message, bucket, retry_after}}`       | `check_and_record(…)` (`RateLimitExceededError`)                    |
| `PolicyDeniedSchema`    | `{"detail": {message, code, context}}`             | Authz policy denials (`PolicyDeniedError`)                          |

A global handler in [`backend/config/api.py`](../backend/config/api.py) reshapes Ninja's stock malformed-body 422 (`{"detail": [{loc, msg}, …]}`) into the `ValidationErrorSchema` envelope so the frontend has one fewer wire shape to parse.

### When to declare each

Apply the rule that fits what your view body (and one level of helpers) can produce. Don't over-declare — `response={200: Foo, 422: ValidationErrorSchema}` on an endpoint that can't produce 422 lies to contract readers.

- **422 structured** (`ValidationErrorSchema`): endpoint calls `execute_claims`, or any helper that can raise `StructuredValidationError` (`validate_name`, `validate_slug_format`, `assert_name_available`, `create_entity_with_claims`).
- **422 plain** (`ErrorDetailSchema`): endpoint raises `HttpError(422, "msg")` directly, or returns `(422, ErrorDetailSchema(...))` explicitly.
- **422 union** (`ErrorDetailSchema | ValidationErrorSchema`): endpoint can produce both shapes.
- **429 structured** (`RateLimitErrorSchema`): endpoint calls `check_and_record`.
- **429 plain** (`ErrorDetailSchema`): endpoint raises `HttpError(429, "msg")` directly, or is decorated with `throttle=[…]` (Ninja's `Throttled` subclasses `HttpError`).
- **403 structured** (`PolicyDeniedSchema`): endpoint declares policy denial as a response shape. Routes using `@requires` do not need to declare 403 solely for policy denial — the global structured-error handler returns the body at runtime. Declare it when policy denial is the natural documented 4xx for the route, or when a route already needs to distinguish 403 shapes.

### Known gap: body-validation 422s

Ninja's body validation runs _before_ the view and produces `ValidationErrorSchema` on any body-accepting endpoint, regardless of whether the view explicitly raises 422. The rules above enumerate by what views raise, not by whether they accept a body, so endpoints whose only 422 path is body-validation are currently silent in the OpenAPI doc. When this gap is closed, every body-accepting endpoint's declared 422 shape should include `ValidationErrorSchema`.
