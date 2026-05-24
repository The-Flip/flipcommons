# Noindex Meta Tag

This is the plan for injecting `<meta name="robots" content="noindex">` on every non-indexable route, so user-facing pages we don't want in search results (`/login`, `/search`, `/style-lab`, `*/edit`, etc.) stay out of Google's index even when crawlers reach them via inbound links.

Addresses the "keeping non-indexable user-facing pages out of the index" concern in [`SearchEngines.md`](SearchEngines.md); see that doc for how this fits with robots.txt and sitemap.

## Dependency

This plan consumes [`RouteWalking.md`](RouteWalking.md) — the walker primitives in `frontend/src/lib/route-metadata.server.ts` and the `isSearchEngineIndexable(routeId)` predicate. Land that first.

## Why per-page noindex, not robots.txt `Disallow`

Per [Google's current guidance](https://developers.google.com/search/docs/crawling-indexing/block-indexing): robots.txt is for crawl-traffic management, not index exclusion. A page `Disallow`-ed in robots.txt can still appear in search results (URL + anchor text, no snippet) if anything links to it. The recommended mechanism for "do not index this page" is per-page `<meta name="robots" content="noindex">`.

The two are also mutually exclusive: if a URL is `Disallow`-ed in robots.txt, Googlebot can't crawl it and so never sees the `noindex` meta. So for user-facing pages we explicitly want crawled (so the meta is seen) but not indexed.

See [`SearchEngines.md`](SearchEngines.md) § "Why the split between robots.txt and noindex" for the full mapping.

## Goals

- Every non-indexable user-facing page emits `<meta name="robots" content="noindex">` in its `<head>`.
- The decision is driven by the same `isSearchEngineIndexable(routeId)` predicate the sitemap uses — no parallel list, no drift.
- Adding a new non-indexable route requires only adding it to `SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS` (or letting the catalog convention classify it); the meta tag follows automatically.

## Mechanism

`route-metadata.server.ts` is a server-only module — its `?raw` glob would balloon the client bundle if imported into a `.svelte` file. So the predicate runs in the root `+layout.server.ts` and the result rides down as load data:

```ts
// frontend/src/routes/+layout.server.ts (new file)
import { isSearchEngineIndexable } from "$lib/route-metadata.server";
import type { LayoutServerLoad } from "./$types";

export const load: LayoutServerLoad = ({ route }) => {
  return { noindex: !isSearchEngineIndexable(route.id) };
};
```

```svelte
<!-- frontend/src/routes/+layout.svelte -->
<script lang="ts">
  let { data, children } = $props();
</script>

<svelte:head>
  {#if data.noindex}
    <meta name="robots" content="noindex" />
  {/if}
</svelte:head>

{@render children?.()}
<!-- ...rest of existing layout body... -->
```

Notes:

- `route.id` on the server load event is the SvelteKit route ID (e.g. `/titles/[slug]`), which is the same shape `isSearchEngineIndexable()` already operates on — no translation needed.
- Adding a root `+layout.server.ts` must NOT import `$lib/require-capability.server` — the auth-gate scan in `route-metadata.server.ts` throws at module load if a root gate is detected (it would silently make every non-catalog route non-indexable).
- Auth-gated routes get the meta tag too. They're already invisible to crawlers (the layout redirects unauthenticated requests), but defense in depth is cheap: if anything ever serves an auth-gated page bytes to a logged-out crawler, the meta still says noindex.
- Use `<meta name="robots">`, not `<meta name="googlebot">` — the generic form covers Google, Bing, and other compliant crawlers in one tag.

## What gets the meta tag

Every route where `isSearchEngineIndexable(routeId) === false`. With current routes:

- Auth-gated (anything under a `requireCapability` layout): `/admin/*`, `/kiosk/edit/*`, and all catalog `*/edit` subroutes.
- Listed non-indexable (entries in `SEARCH_ENGINE_NON_INDEXABLE_ROUTE_IDS`): `/login`, `/signup`, `/verify-email`, `/auth/error`, `/search`, `/kiosk`, `/style-lab`, `/api-docs`, `/_sentry_test`, `/changesets`, `/review`, `/users/[username]`.
- Catalog non-indexable kinds (`catalog-listing`, `catalog-new`, `catalog-delete`) for every entity.

The list isn't enumerated in this doc — it's whatever `isSearchEngineIndexable()` returns false for, and the route-walking test (per [`RouteWalking.md`](RouteWalking.md)) already enforces that every route classifies.

## Gate on `ALLOW_SEARCH_ENGINE_INDEXING`?

No. The meta tag should be emitted on every deploy regardless of whether indexing is allowed at the deploy level. Reasoning:

- On non-prod deploys (`ALLOW_SEARCH_ENGINE_INDEXING != "true"`), robots.txt already says `Disallow: /` and crawlers shouldn't be looking at any page. The meta is redundant but harmless.
- Tying the meta to the env var adds a branch to the layout for no behavioral benefit and one more failure mode (e.g. forgetting to thread the var into SSR context).
- Keeping the meta unconditional makes local testing trivial: visit any non-indexable route and view source.

## Tests

`frontend/src/routes/+layout.dom.test.ts` (or a new `noindex-meta.dom.test.ts` alongside):

- Render the layout for an indexable route (`/titles/[slug]`) and assert no `<meta name="robots">` is present.
- Render for a listed non-indexable route (`/login`) and assert `<meta name="robots" content="noindex">` is present.
- Render for an auth-gated route (`/admin/dashboard`) and assert the meta is present.

The test parameterizes over the same anchor routes used in `RouteWalking.md`'s sanity check — keeps both tests honest if the route classifications drift.

## Implementation order

1. Create `frontend/src/routes/+layout.server.ts` with the noindex load. Verify the auth-gate scan still passes (the new file imports `route-metadata.server`, not `require-capability.server`, so it's fine).
2. Add the `<svelte:head>` block to `frontend/src/routes/+layout.svelte` reading `data.noindex`.
3. Add the dom test per § "Tests".
4. Verify locally: `curl -s localhost:5173/login | grep robots` shows the meta; same for `/titles/medieval-madness` shows nothing.

That's the whole PR. Tiny.

## Considered alternatives

- **`X-Robots-Tag: noindex` HTTP response header instead of a meta tag.** Equivalent in effect; required for non-HTML responses (PDFs, images). For HTML pages we control, the meta tag is simpler — no SvelteKit `setHeaders` plumbing, just markup. Revisit if we ever serve non-HTML responses that need excluding.
- **Per-route `<svelte:head>` blocks in each excluded page.** Rejected: would silently miss any new non-indexable route until a reviewer noticed. Centralizing the decision in the root layout means "well-classified" automatically implies "correctly headed."
- **Computing `noindex` in `+layout.svelte` directly.** Rejected — would require importing `route-metadata.server.ts` into a client-bundle file, which SvelteKit blocks (rightly: the module's `?raw` glob would ship server source as strings to the browser).
- **Folding into `Robots.md`.** Rejected: different mechanism (HTML markup vs. text file), different consumer (per-request render vs. static file), different testing surface. Sharing the `isSearchEngineIndexable()` predicate is enough integration.
