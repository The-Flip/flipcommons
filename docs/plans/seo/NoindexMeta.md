# Noindex Signals

This is the plan for emitting noindex on every non-indexable route, so user-facing pages we don't want in search results (`/login`, `/search`, `/style-lab`, `*/edit`, etc.) stay out of search engine indexes even when crawlers reach them via inbound links.

## Status: ✅ Implemented

This plan has been implemented.

## Key design decision

We emit two signals together:

- `<meta name="robots" content="noindex" />` in the page `<head>`.
- `X-Robots-Tag: noindex` HTTP response header.

Both come from a single `handle` hook (`noindexHandle` in `hooks.server.ts`) that reads the `isSearchEngineIndexable()` predicate, so they can't disagree. They cover each other's blind spots:

- The header reaches crawlers on non-HTML responses where a meta tag isn't possible (e.g. `__data.json` fetches that SvelteKit issues for `ssr=false` routes).
- The meta tag survives infrastructure that strips response headers (CDN edge rules, proxies, archive snapshots).

Addresses the "keeping non-indexable user-facing pages out of the index" concern in [`SearchEngines.md`](SearchEngines.md); see that doc for how this fits with robots.txt and sitemap.

## Why noindex signals, not robots.txt `Disallow`

Per [Google's current guidance](https://developers.google.com/search/docs/crawling-indexing/block-indexing): robots.txt is for crawl-traffic management, not index exclusion. A page `Disallow`-ed in robots.txt can still appear in search results (URL + anchor text, no snippet) if anything links to it. The recommended mechanism for "do not index this page" is a per-page noindex signal — meta tag or `X-Robots-Tag` header.

The two are also mutually exclusive: if a URL is `Disallow`-ed in robots.txt, Googlebot can't crawl it and so never sees the `noindex` signal. So for user-facing pages we explicitly want crawled (so the signal is seen) but not indexed.

See [`SearchEngines.md`](SearchEngines.md) § "Why the split between robots.txt and noindex" for the full mapping.

## Goals

- Every non-indexable user-facing page emits noindex via **both** the meta tag in its `<head>` and the `X-Robots-Tag` response header.
- The decision is driven by the same `isSearchEngineIndexable(routeId)` predicate the sitemap uses — no parallel list, no drift.
- Adding a new non-indexable route requires only adding it to `SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS` (or letting the catalog convention classify it); both signals follow automatically.

## Mechanism

`route-metadata.server.ts` is server-only (its `?raw` glob would balloon the client bundle), so the predicate has to run server-side. We put it in a `handle` hook added to the existing `sequence()` in `frontend/src/hooks.server.ts`:

```ts
export const noindexHandle: Handle = async ({ event, resolve }) => {
  if (!shouldIndex(event.route.id)) {
    const response = await resolve(event, {
      transformPageChunk: ({ html }) =>
        html.replace(
          "</head>",
          '<meta name="robots" content="noindex" />\n</head>',
        ),
    });
    response.headers.set("X-Robots-Tag", "noindex");
    return response;
  }
  return resolve(event);
};

function shouldIndex(id: RouteId | null): boolean {
  if (id === null) return false; // unmatched URLs (404).
  try {
    return isSearchEngineIndexable(id);
  } catch {
    // Unclassified routes are +server.ts endpoints (e.g. /__health) —
    // see notes below for why we swallow rather than crash.
    return false;
  }
}

export const handle = sequence(Sentry.sentryHandle(), noindexHandle);
```

Notes:

- **Why `handle`, not a layout `load`.** A root `+layout.server.ts` would put `noindex` into `PageData`, forcing every page test that constructs a literal `data` fixture to add the field. The hook stays out of `PageData` entirely. It also covers responses the layout load wouldn't reach (see next bullet).
- **`ssr=false` routes are covered on the initial response.** The hook fires for every request including the static-shell page response, so both the X-Robots-Tag header and the injected meta tag land on the first response — not deferred to the post-hydration `__data.json` fetch the way a layout-load implementation would be.
- **`transformPageChunk` string-replaces `</head>`.** SvelteKit renders the document head before any body streaming, so `</head>` reliably appears in the first chunk. This is the same pattern used in the wild for CSP nonce injection, analytics shim insertion, etc.
- **Why the `try/catch` on the predicate.** `isSearchEngineIndexable()` throws on unclassified routes — a deliberate guardrail that makes new `+page.svelte` routes fail loudly in `route-metadata.test.ts` until they're classified. But `allRoutes()` only enumerates `+page.svelte` files, so `+server.ts` endpoints (today just `/__health`) are _outside_ that test's coverage and would be unclassified at runtime. Without the catch, the hook would crash the liveness probe on every deploy. Defaulting unclassified routes to noindex is safe: they're not HTML pages, so accidentally signaling noindex doesn't hurt anything.
- **Auth-gated routes get noindex too.** They're already invisible to crawlers (the layout redirects unauthenticated requests), but defense in depth is cheap: if anything ever serves an auth-gated page's bytes to a logged-out crawler, the signals still say noindex.
- Use `<meta name="robots">` (not `<meta name="googlebot">`) and `X-Robots-Tag: noindex` (not `X-Robots-Tag: googlebot: noindex`) — the generic forms cover Google, Bing, and other compliant crawlers in one signal.

## What gets the noindex signals

Every route where `isSearchEngineIndexable(routeId) === false`. With current routes:

- Auth-gated (anything under a `requireCapability` layout): `/admin/*`, `/kiosk/edit/*`, and all catalog `*/edit` subroutes.
- Listed non-indexable (entries in `SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS`): `/login`, `/signup`, `/verify-email`, `/auth/error`, `/search`, `/kiosk`, `/style-lab`, `/api-docs`, `/_sentry_test`, `/changesets`, `/review`, `/users/[username]`.
- Catalog non-indexable kinds (`catalog-new`, `catalog-delete`) for every entity, plus edit subroutes through their auth-gated layouts. Catalog listings are indexable now that they are SSR.

The list isn't enumerated in this doc — it's whatever `isSearchEngineIndexable()` returns false for, and the route-walking test (per [`RouteWalking.md`](RouteWalking.md)) already enforces that every route classifies.

## Gate on `ALLOW_SEARCH_ENGINE_INDEXING`?

No. Both signals are emitted on every deploy regardless of whether indexing is allowed at the deploy level. Reasoning:

- On non-prod deploys (`ALLOW_SEARCH_ENGINE_INDEXING != "true"`), robots.txt already says `Disallow: /` and crawlers shouldn't be looking at any page. The noindex signals are redundant but harmless.
- Tying them to the env var adds a branch to the hook for no behavioral benefit and one more failure mode.
- Keeping them unconditional makes local testing trivial: visit any non-indexable route and view source / check headers.

## Tests

`frontend/src/hooks-noindex.server.test.ts` imports `noindexHandle` and parameterizes over anchor routes from each bucket. For each routeId it calls the handle with a stubbed `event` and a `resolve` that captures the `transformPageChunk` invocation and returns a fake HTML response, then asserts:

- Indexable (`/`, `/about`, `/titles`, `/titles/[slug]`) → `resolve` called without options, response has no `X-Robots-Tag`, response body has no `name="robots"` meta tag.
- Listed non-indexable (`/login`, `/search`, `/users/[username]`), auth-gated (`/admin/dashboard`, `/kiosk/edit`), catalog non-indexable kinds (`/titles/new`, `/titles/[slug]/edit`, `/titles/[slug]/delete`), and `route.id === null` → header set, body contains the meta tag, `resolve` called with a `transformPageChunk` function.
- Unclassified routes (`/__health`, the only `+server.ts` endpoint today) → header set, no crash. Pins the `try/catch` behavior so a future refactor that "cleans up" the catch surfaces here instead of crashing the liveness probe in production.

## Implementation order

1. Add `noindexHandle` to `frontend/src/hooks.server.ts`, add it to the `sequence()`, and export it for testing.
2. Add `frontend/src/hooks-noindex.server.test.ts` per § "Tests".
3. Verify locally:
   - `curl -sI localhost:5173/login | grep -i x-robots-tag` shows the header.
   - `curl -s localhost:5173/login | grep robots` shows the meta.
   - Both checks against an SSR'd indexable route (e.g. `/titles/medieval-madness`) show nothing.
   - Catalog listings (e.g. `/titles`) are SSR and indexable, so they should show neither the header nor the meta tag.

That's the whole PR. Tiny.

## Considered alternatives

- **Layout-load implementation (`+layout.server.ts` that returns `{ noindex }`, root `+layout.svelte` with `<svelte:head>{#if data.noindex}…</svelte:head>`).** Rejected: pushes a `noindex` field into every page's `PageData` type, forcing every test that constructs a literal `data` fixture to add `noindex: boolean` — ~13 unrelated test files in this codebase. Also fails to set headers on the initial page response for `ssr=false` routes (SvelteKit serves the static shell without running layout loads; the header lands only on the deferred `__data.json` fetch).
- **Meta tag only, no `X-Robots-Tag` header.** Rejected: the meta tag can't appear in non-HTML responses (e.g. `__data.json`), and the header is what survives proxies that translate or rewrite HTML.
- **Header only, no meta tag.** Rejected: header-stripping infrastructure (CDNs, archive snapshots) would silently disable the only signal. The meta tag survives that.
- **Per-route `<svelte:head>` blocks in each excluded page.** Rejected: would silently miss any new non-indexable route until a reviewer noticed. Centralizing the decision in the hook means "well-classified" automatically implies "correctly signaled."
- **Computing `noindex` client-side.** Rejected — would require importing `route-metadata.server.ts` into a client-bundle file, which SvelteKit blocks (rightly: the module's `?raw` glob would ship server source as strings to the browser).
- **Folding into `Robots.md`.** Rejected: different mechanism (per-page signal vs. static text file), different consumer (per-request render vs. crawler bootstrap), different testing surface. Sharing the `isSearchEngineIndexable()` predicate is enough integration.
