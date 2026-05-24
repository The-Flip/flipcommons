# Noindex Meta Tag

This is the plan for injecting `<meta name="robots" content="noindex">` on every non-indexable route, so user-facing pages we don't want in search results (`/login`, `/search`, `/style-lab`, `*/edit`, etc.) stay out of Google's index even when crawlers reach them via inbound links.

Addresses the "keeping non-indexable user-facing pages out of the index" concern in [`SearchEngines.md`](SearchEngines.md); see that doc for how this fits with robots.txt and sitemap.

## Dependency

This plan consumes [`RouteWalking.md`](RouteWalking.md) — the per-route `searchEngineInclusion` export, the walker primitives in `frontend/src/lib/route-metadata.ts`, and the `isIndexable(routeId)` predicate. Land that first.

## Why per-page noindex, not robots.txt `Disallow`

Per [Google's current guidance](https://developers.google.com/search/docs/crawling-indexing/block-indexing): robots.txt is for crawl-traffic management, not index exclusion. A page `Disallow`-ed in robots.txt can still appear in search results (URL + anchor text, no snippet) if anything links to it. The recommended mechanism for "do not index this page" is per-page `<meta name="robots" content="noindex">`.

The two are also mutually exclusive: if a URL is `Disallow`-ed in robots.txt, Googlebot can't crawl it and so never sees the `noindex` meta. So for user-facing pages we explicitly want crawled (so the meta is seen) but not indexed.

See [`SearchEngines.md`](SearchEngines.md) § "Why the split between robots.txt and noindex" for the full mapping.

## Goals

- Every non-indexable user-facing page emits `<meta name="robots" content="noindex">` in its `<head>`.
- The decision is driven by the same `isIndexable(routeId)` predicate the sitemap uses — no parallel list, no drift.
- Adding a new non-indexable route requires only the existing `searchEngineInclusion = 'excluded'` export; the meta tag follows automatically.

## Mechanism

Inject in the root `+layout.svelte` so it covers every route:

```svelte
<!-- frontend/src/routes/+layout.svelte -->
<script lang="ts">
  import { page } from '$app/state';
  import { isIndexable } from '$lib/route-metadata';

  let noindex = $derived(!isIndexable(page.route.id));
</script>

<svelte:head>
  {#if noindex}
    <meta name="robots" content="noindex" />
  {/if}
</svelte:head>

<!-- ...existing layout body... -->
```

Notes:

- `page.route.id` is the SvelteKit route ID (e.g. `/titles/[slug]`), which is the same shape `isIndexable()` already operates on — no translation needed.
- Auth-gated routes get the meta tag too. They're already invisible to crawlers (the layout redirects unauthenticated requests), but defense in depth is cheap: if anything ever serves an auth-gated page bytes to a logged-out crawler, the meta still says noindex.
- Use `<meta name="robots">`, not `<meta name="googlebot">` — the generic form covers Google, Bing, and other compliant crawlers in one tag.

## What gets the meta tag

Every route where `isIndexable(routeId) === false`. With current routes:

- Auth-gated (anything under a `requireCapability` layout): `/a/*`, plus catalog edit subroutes once they have such a layout.
- Declared `searchEngineInclusion = 'excluded'`: `/login`, `/signup`, `/verify-email`, `/auth/*`, `/search`, `/kiosk/*`, `/style-lab`, `/api-docs`, `/_sentry_test`, `/changesets/*`, `/review/*`, and the catalog edit subroutes (`/*/edit`, `/*/edit-history`, `/*/sources`, `/*/new`) until/unless they get a `requireCapability` layout.

The list isn't enumerated in this doc — it's whatever `isIndexable()` returns false for, and the route-walking test (per [`RouteWalking.md`](RouteWalking.md)) already enforces that every route declares its classification.

## Gate on `ALLOW_SEARCH_ENGINE_INDEXING`?

No. The meta tag should be emitted on every deploy regardless of whether indexing is allowed at the deploy level. Reasoning:

- On non-prod deploys (`ALLOW_SEARCH_ENGINE_INDEXING != "true"`), robots.txt already says `Disallow: /` and crawlers shouldn't be looking at any page. The meta is redundant but harmless.
- Tying the meta to the env var adds a branch to the layout for no behavioral benefit and one more failure mode (e.g. forgetting to thread the var into SSR context).
- Keeping the meta unconditional makes local testing trivial: visit any non-indexable route and view source.

## Tests

`frontend/src/routes/+layout.dom.test.ts` (or a new `noindex-meta.dom.test.ts` alongside):

- Render the layout for an indexable route (`/titles`) and assert no `<meta name="robots">` is present.
- Render for a non-indexable declared route (`/login`) and assert `<meta name="robots" content="noindex">` is present.
- Render for an auth-gated route (`/a/dashboard`) and assert the meta is present.

The test parameterizes over the same anchor routes used in `RouteWalking.md`'s sanity check — keeps both tests honest if the route classifications drift.

## Implementation order

1. Add the `<svelte:head>` block to `frontend/src/routes/+layout.svelte`. Roughly five lines.
2. Add the dom test per § "Tests".
3. Verify locally: `curl -s localhost:5173/login | grep robots` shows the meta; same for `/titles` shows nothing.

That's the whole PR. Tiny.

## Considered alternatives

- **`X-Robots-Tag: noindex` HTTP response header instead of a meta tag.** Equivalent in effect; required for non-HTML responses (PDFs, images). For HTML pages we control, the meta tag is simpler — no SvelteKit `setHeaders` plumbing, just markup. Revisit if we ever serve non-HTML responses that need excluding.
- **Per-route `<svelte:head>` blocks in each excluded page.** Rejected: would silently miss any new non-indexable route until a reviewer noticed. Centralizing the decision in the root layout means "well-classified" automatically implies "correctly headed."
- **Folding into `Robots.md`.** Rejected: different mechanism (HTML markup vs. text file), different consumer (per-request render vs. static file), different testing surface. Sharing the `isIndexable()` predicate is enough integration.
