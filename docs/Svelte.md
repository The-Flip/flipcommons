# Svelte

This document defines how to think about and develop SvelteKit pages in this project.

For language-level TypeScript conventions that apply across the frontend, see [Typescript.md](Typescript.md).

## Authoring Conventions

You MUST use Svelte 5 runes mode. Use modern Svelte 5 patterns, not legacy Svelte 4 syntax:

- `export let` -> `$props()`
- `$:` -> `$derived` / `$effect`
- `on:click` -> `onclick`
- `<slot>` -> `{@render children()}`

Keep component styles scoped by default. Avoid `:global` unless there is a clear reason. You MUST obtain explicit user approval to get an exception to use `:global`.

### Internal import paths

Import same-folder siblings relatively (`./Sibling.svelte`). Use the `$lib` alias for anything crossing a folder boundary (`$lib/components/effects/WearEffect.svelte`) — never `../` traversal.

## Choosing A Rendering Strategy

How to choose which rendering mode:

- **Server-Side Rendering (SSR)** for any page that needs to be indexed by search engines.
- **Prerendered static shell plus client fetch** as the default for pages that do not need to be indexed by search engines. Why? Because this is usually perceived by the user as more performant than pure CSR.
- **Pure Client-Side Rendering (CSR)** only for pages that cannot practically use a prerendered shell.

In this repo, that usually means:

- **SSR**:
  - public detail pages such as title, model, manufacturer, and similar entity detail routes. These need to be in search engines.
  - public read-only child pages when they add meaningful content that needs to be in search engines, such as `sources` or `edit-history`
  - public media/gallery pages when they have content that needs to be in search engines, not editing surfaces
- **Prerendered static shell plus client fetch**:
  - home page, search, recent activity, and large browse/index pages
  - pages where the content changes often and does not need to be indexed from the initial HTML
  - aggregate pages where fast shell delivery is more valuable than server-rendering the full dataset
  - most non-SEO pages when the route can be prerendered and the shell is generic
- **CSR-only**:
  - routes that cannot be enumerated at build time and do not need SSR
  - routes where prerendering is not practical because the shell itself depends on request-time state
  - dynamic edit, upload, review, and similar app surfaces that must support arbitrary new slugs without a rebuild

**Prerender caveat:** A prerendered shell must not read request-time state (like `window.location.search`) at module scope or during initial render — that code runs at build time when no request exists. Defer URL-dependent state initialization to `onMount` or a `browser` guard so the shell can prerender as a generic page and hydrate with the real URL on the client.

## Route Files

Use route files by responsibility:

- `+page.server.ts` for server-side page loading
- `+layout.server.ts` for shared server-side loading across a route subtree
- `+page.ts` only when the route logic truly needs universal load behavior
- `+page.svelte` and `+layout.svelte` for rendering

For public SSR pages, `+page.server.ts` or `+layout.server.ts` should be the default choice.

### Route directory naming

A `src/routes/[slug]/` directory name is the **plural** of the backend's `entity_type` string — e.g. `corporate-entities/` for `entity_type="corporate-entity"`. The rule and the generated canonical list are in [EntityNaming.md](EntityNaming.md). Parity is test-enforced, so CI catches a wrong name.

### `[slug]` vs `[...path]`

Pick the SvelteKit segment shape based on the backend model's `public_id_field`:

- **Single-segment public_id** (`public_id_field = "slug"`, the default) → use `[slug]`. The route param is the slug verbatim and gets passed as `public_id` to the typed client.
- **Multi-segment public_id** (e.g. Location's `public_id_field = "location_path"`, value `"usa/il/chicago"`) → use `[...path]` catch-all. The backend route is declared with Ninja's `{path:public_id}` converter, which matches both shapes — so the API contract is uniform regardless of segment count.

The `[slug]` directory name is kept even though the backend param is now `public_id`, because the value at every `[slug]` route still _is_ a slug. The naming dissonance is intentional — renaming directories to `[public_id]` would be churn without semantic gain.

## Implementing SSR Routes

For SSR routes, prefer:

- `+page.server.ts` or `+layout.server.ts` for route data loading
- one page-oriented backend endpoint, usually under `/api/pages/...`
- `+page.svelte` that renders the returned data directly

The page should receive a page model and render it. It should not orchestrate multiple backend calls unless there is a strong reason.

### Calling Django From Server-Side Routes

Server-side Svelte routes should call Django APIs through the typed client, not through ad hoc fetch helpers.

Use `createServerClient` from `$lib/api/server`:

```ts
import { createServerClient } from "$lib/api/server";

export const load: PageServerLoad = async ({ fetch, url, request, params }) => {
  const client = createServerClient(fetch, url, request);
  const { data, response } = await client.GET("/api/pages/title/{public_id}", {
    params: { path: { public_id: params.slug } },
  });
  // ...
};
```

`createServerClient` resolves `INTERNAL_API_BASE_URL` (direct-to-Django in production) with a fallback to the request origin (Vite proxy in dev). Every SSR load function should use this helper instead of constructing the client manually. Passing `request` is required: in production SSR crosses origins to reach Django, and SvelteKit's `event.fetch` only forwards cookies same-origin, so the helper forwards the user's `Cookie` header from the incoming request — without it, every authenticated endpoint sees an anonymous request.

This keeps:

- OpenAPI-generated types in use
- request logic consistent between routes
- backend/frontend contracts explicit
- base URL resolution in one place

The goal is not for SvelteKit SSR to reach into Django internals. The boundary stays at the HTTP API.

### SSR Inheritance In Child Routes

When a parent `+layout.server.ts` enables SSR, all child routes inherit it. This is fine for public content children (detail, sources, edit-history), but breaks interactive children that import the browser API client or read auth state at render time.

When converting a route subtree to SSR, audit every child route and add `export const ssr = false` in a `+page.ts` file for any child that:

- imports the browser `client` default export directly
- reads `auth.isAuthenticated` or other browser-only state at render time
- is an authenticated editing or upload surface

This is easy to miss because the children worked fine when the parent had `ssr = false` — the breakage only surfaces after the parent switches to SSR.

## Authorization

Frontend authorization is not authority. It covers UX — showing or hiding
affordances and routing denials to remediation surfaces — but Django remains the
source of truth. Every mutation must be enforced by the backend policy and may
still return a structured `policy_denied` 403.

Use capabilities instead of reimplementing policy logic:

- For target-less actions, use `auth.can("activity.name")` from `$lib/auth.svelte`.
- For row-specific actions, use the row's embedded `capabilities` map, such as `changeset.capabilities["changeset.undo"]`.
- Do not check raw role or user-state fields (`is_staff`, `is_superuser`, `email_verified`) to decide whether a product action is allowed.

### Show affordances the user can earn

Default to showing affordances when the denial has a self-service remediation (verify email, accumulate edits). Hiding them makes the SPA look logged-out and erases discoverability. Hide only when there is no path: staff-only actions, banned accounts.

That makes `auth.isAuthenticated` an identity/visibility signal, not a permission check:

- **Visibility**: anonymous users hide (their remediation is sign-up in `Nav`); authenticated users see the affordance regardless of verification.
- **Permission decisions belong at the click destination**, not the affordance.

### Gating destinations

- **Route loaders** for capability-gated pages (`[slug]/edit`, `*/new`): call `requireCapability(fetch, activity)`. Redirects unverified users to `/verify-email`, anonymous users to `/login`.
- **Direct-action buttons** (e.g. `EditHistory`'s Revert): submit unconditionally. `parseApiError` already turns `policy_denied` into a toast carrying the right remediation copy. Target-aware activities like `claim.revert` and `changeset.undo` are absent from `/api/auth/me/` capabilities by design — `auth.can()` would always return false and gate everyone, so don't pre-check.

### Server-side gates

For no-remediation gates that block render, use `+layout.server.ts` with `createServerClient` — see [`kiosk/edit/+layout.server.ts`](../frontend/src/routes/kiosk/edit/+layout.server.ts). Non-staff users get redirected to `/`, not `/verify-email`. Don't import the browser auth store from server files.

### Mutations are still enforced

The route-loader redirect is an optimization, not a guarantee. A stale capability map or a between-render `email_verified` flip still fires the 403, and the toast still renders. Always handle the 403 path.
