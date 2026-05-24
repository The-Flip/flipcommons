# Canonical URL

This is the plan for emitting `<link rel="canonical" href="...">` on every indexable page, so search engines consolidate ranking signals on one authoritative URL when the same content is reachable via multiple paths (trailing-slash variants, query-string variants, scheme/host variants).

Addresses the "canonical URLs" concern in [`SearchEngines.md`](SearchEngines.md).

## Scope — what this plan does and doesn't cover

**In scope:** a `<link rel="canonical">` tag in the root layout, pointing to the normalized URL for the current page.

**Out of scope (already handled elsewhere):**

- **Single-Model-Title duplication.** The `/models/[slug]` route already 301-redirects to the Title route when the parent Title has exactly one Model. A 301 collapses the duplicate at the HTTP layer and consolidates signals on the target; canonical tags are not load-bearing for this case. `ModelSitemapFeed` also excludes these Models per [`Sitemap.md`](Sitemap.md).
- **Slug renames.** Handled by 301 redirects in the slug-edit flow per the "URL stability across slug changes" concern in [`SearchEngines.md`](SearchEngines.md).
- **Faceted/paginated listing URLs** (`?page=2`, `?manufacturer=stern`). Tracked as a separate concern in [`SearchEngines.md`](SearchEngines.md); the canonical strategy there (canonicalize filters back to the base listing vs. `noindex` filter combinations) needs its own decision and may end up using this same `<link rel="canonical">` mechanism with route-specific rules.

What's left for this plan: mechanical canonicalization — strip the query string, normalize the trailing slash, ensure the canonical href uses the production origin (not the request host).

## Dependency

None hard. Slots in alongside [`NoindexMeta.md`](NoindexMeta.md) — both are root-layout `<svelte:head>` SEO tags driven by `page.url` / `page.route.id`. Land either order.

## Goals

- Every indexable page emits exactly one `<link rel="canonical">` pointing to the normalized URL.
- Canonical href always uses `SITE_ORIGIN`, never the request host — so a request to a preview origin or an unexpected hostname still points search engines at production.
- Query strings are stripped by default; routes that legitimately use query params for distinct content opt in.
- Non-indexable routes don't emit a canonical (they're already `noindex` per [`NoindexMeta.md`](NoindexMeta.md); a canonical would be noise).

## Mechanism

Inject in the root `+layout.svelte` next to the noindex meta. Both are driven by the same `page` state.

```svelte
<!-- frontend/src/routes/+layout.svelte -->
<script lang="ts">
  import { page } from '$app/state';
  import { isIndexable } from '$lib/route-metadata';
  import { canonicalUrl } from '$lib/seo/canonical';

  let indexable = $derived(isIndexable(page.route.id));
  let canonical = $derived(indexable ? canonicalUrl(page.url, page.route.id) : null);
</script>

<svelte:head>
  {#if canonical}
    <link rel="canonical" href={canonical} />
  {/if}
  <!-- noindex meta from NoindexMeta.md -->
</svelte:head>
```

`canonicalUrl(url, routeId)` lives in `frontend/src/lib/seo/canonical.ts`:

- Replace the origin with `SITE_ORIGIN` (read via `$env/static/public` so it's available in CSR too — the SSR-only `$env/static/private` would break client-side rerenders).
- Normalize the trailing slash to the project's convention (no trailing slash, matching SvelteKit defaults).
- Drop the query string and fragment by default.
- Per-route opt-in for preserved query params: a small `CANONICAL_QUERY_PARAMS` map keyed by route ID listing the params that contribute to canonical identity (e.g. paginated listings might keep `?page=`). Empty by default; populated only when a route needs it.

## What gets a canonical

Every route where `isIndexable(routeId) === true`. Non-indexable routes get `noindex` instead and don't need a canonical.

## Gate on `ALLOW_SEARCH_ENGINE_INDEXING`?

No. Same reasoning as [`NoindexMeta.md`](NoindexMeta.md) § "Gate on `ALLOW_SEARCH_ENGINE_INDEXING`?" — on non-prod deploys, robots.txt's `Disallow: /` already keeps crawlers out; the canonical tag is harmless redundancy. Unconditional emission keeps local testing trivial.

## Tests

`frontend/src/routes/+layout.dom.test.ts` (or a new `canonical.dom.test.ts`):

- Render an indexable route with no query string → canonical equals `${SITE_ORIGIN}${pathname}`.
- Render an indexable route with a query string → canonical strips the query.
- Render an indexable route reached via a non-prod request host → canonical still uses `SITE_ORIGIN`.
- Render a non-indexable route → no `<link rel="canonical">` is present.

Unit tests for `canonicalUrl()` cover trailing-slash normalization and the per-route query-param allowlist when one is added.

## Implementation order

1. `frontend/src/lib/seo/canonical.ts` — pure function, unit-tested.
2. Add the `<svelte:head>` block to `frontend/src/routes/+layout.svelte`.
3. DOM test per § "Tests".
4. Verify locally: `curl -s localhost:5173/titles | grep canonical` and `curl -s 'localhost:5173/titles?foo=bar' | grep canonical` both show the canonical path with no query.

## Considered alternatives

- **Use `page.url.href` directly.** Rejected: bakes in the request host and query string, so a request to a preview origin or with a tracking param would emit a wrong canonical.
- **Per-page `<svelte:head>` blocks in each indexable route.** Rejected for the same reason as in [`NoindexMeta.md`](NoindexMeta.md): centralizing in the root layout means a new route inherits correct behavior without per-page wiring.
- **Fold into `NoindexMeta.md` and rename it `HeadSeoTags.md`.** Considered — same mechanism, same test file, both driven by `isIndexable()`. Rejected to keep each plan single-purpose and matching the existing `seo/` directory pattern.

## Open questions

None.
