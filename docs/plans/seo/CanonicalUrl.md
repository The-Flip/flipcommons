# Canonical URL

This is the plan for emitting `<link rel="canonical" href="...">` on every indexable page, so search engines consolidate ranking signals on one authoritative URL when the same content is reachable via multiple paths (trailing-slash variants, query-string variants, scheme/host variants).

Addresses the "canonical URLs" concern in [`SearchEngines.md`](SearchEngines.md).

## Scope — what this plan does and doesn't cover

**In scope:** a `<link rel="canonical">` tag injected into every indexable page's `<head>`, pointing to the normalized URL for the current page.

**Out of scope (already handled elsewhere):**

- **Single-Model-Title duplication.** The `/models/[slug]` route already 301-redirects to the Title route when the parent Title has exactly one Model. A 301 collapses the duplicate at the HTTP layer and consolidates signals on the target; canonical tags are not load-bearing for this case. `ModelSitemapFeed` also excludes these Models per [`Sitemap.md`](Sitemap.md).
- **Slug renames.** Handled by 301 redirects in the slug-edit flow per the "URL stability across slug changes" concern in [`SearchEngines.md`](SearchEngines.md).
- **Faceted/paginated listing URLs** (`?page=2`, `?manufacturer=stern`). Tracked as a separate concern in [`SearchEngines.md`](SearchEngines.md); the canonical strategy there (canonicalize filters back to the base listing vs. `noindex` filter combinations) needs its own decision and may end up using this same `<link rel="canonical">` mechanism with route-specific rules.

What's left for this plan: mechanical canonicalization — strip the query string, normalize the trailing slash, ensure the canonical href uses the production origin (not the request host).

## Goals

- Every indexable page emits exactly one `<link rel="canonical">` pointing to the normalized URL.
- Canonical href always uses `SITE_ORIGIN`, never the request host — so a request to a preview origin or an unexpected hostname still points search engines at production.
- Query strings are stripped by default; routes that legitimately use query params for distinct content opt in.
- Non-indexable routes don't emit a canonical (they're already `noindex` per [`NoindexMeta.md`](NoindexMeta.md); a canonical would be noise).

## Mechanism

A `handle` hook (`canonicalHandle` in `frontend/src/hooks.server.ts`) added to the existing `sequence()` alongside `noindexHandle`. It computes the canonical URL from `event.url` + `event.route.id` and string-inserts the tag into the rendered HTML's `<head>` via `transformPageChunk` — exactly mirroring how `noindexHandle` injects the noindex meta tag (see [`NoindexMeta.md`](NoindexMeta.md) § "Mechanism" for the architectural rationale; the same reasoning applies here):

```ts
export const canonicalHandle: Handle = async ({ event, resolve }) => {
  if (!shouldIndex(event.route.id)) return resolve(event);

  const canonical = canonicalUrl(event.url, event.route.id);
  const tag = `<link rel="canonical" href="${escapeHtmlAttribute(canonical)}" />`;
  return resolve(event, {
    transformPageChunk: ({ html }) =>
      html.replace("</head>", `${tag}\n</head>`),
  });
};

export const handle = sequence(
  Sentry.sentryHandle(),
  noindexHandle,
  canonicalHandle,
);
```

`shouldIndex(id)` is already defined in `hooks.server.ts` for the noindex case — same predicate, opposite direction. Reuse it directly: a route is canonical-eligible iff it's indexable. Null and unclassified routes (`+server.ts` endpoints) get neither signal.

`canonicalUrl(url, routeId)` lives in `frontend/src/lib/seo/canonical.ts`:

- Replace the origin with `SITE_ORIGIN` (read via `$env/static/public`; the value is also referenced by the canonical itself, so co-locating with public env keeps it grep-able).
- Normalize the trailing slash to the project's convention (no trailing slash, matching SvelteKit defaults).
- Drop the query string and fragment by default.
- Per-route opt-in for preserved query params: a small `CANONICAL_QUERY_PARAMS` map keyed by route ID listing the params that contribute to canonical identity (e.g. paginated listings might keep `?page=`). Empty by default; populated only when a route needs it.

`escapeHtmlAttribute(s)` is a small utility (likely co-located with `canonicalUrl`) that escapes `&`, `<`, `>`, `"`, `'` for safe insertion into an HTML attribute value. The canonical URL is built from `event.url.pathname`, which can contain user-controlled dynamic-segment values (`[slug]`, `[...path]`); even though SvelteKit's routing constrains what can match, escaping at the insertion site is the right defensive layer — same reason we URL-encode at every boundary even when we "know" the input.

Notes:

- **Separate hook, not folded into `noindexHandle`.** Noindex fires on non-indexable; canonical fires on indexable; they never both fire for the same route. Keeping them as independent hooks in the `sequence()` keeps each one's responsibility scannable and lets the tests be split cleanly. The extra `transformPageChunk` pass is negligible.
- **`transformPageChunk` string-replaces `</head>`.** Same pattern noindex uses; the head reliably appears in the first chunk so the replace is single-pass and unambiguous.
- **`ssr=false` routes get the canonical on the initial response.** The hook fires for every request including the static-shell response, so the canonical tag lands on the first response (not deferred to a later `__data.json` fetch the way a layout-load implementation would be). Mirror of the same property `noindexHandle` provides.

## What gets a canonical

Every route where `isSearchEngineIndexable(routeId) === true`. Non-indexable routes get `noindex` instead and don't need a canonical. Unclassified routes (`+server.ts` endpoints like `/__health`) also get neither — they're not pages and would never be indexed regardless.

## Gate on `ALLOW_SEARCH_ENGINE_INDEXING`?

No. Same reasoning as [`NoindexMeta.md`](NoindexMeta.md) § "Gate on `ALLOW_SEARCH_ENGINE_INDEXING`?" — on non-prod deploys, robots.txt's `Disallow: /` already keeps crawlers out; the canonical tag is harmless redundancy. Unconditional emission keeps local testing trivial.

## Tests

`frontend/src/hooks-canonical.server.test.ts` mirrors the structure of `hooks-noindex.server.test.ts`: import `canonicalHandle`, run it against a stubbed `event`/`resolve`, capture the `transformPageChunk` invocation, assert on the rendered HTML and headers.

Cases:

- Indexable route (`/`, `/about`, `/titles/[slug]`) with no query string → response body contains `<link rel="canonical" href="${SITE_ORIGIN}${pathname}" />`.
- Indexable route with a query string → canonical strips the query.
- Indexable route reached via a non-prod request host (e.g. `preview.example.com`) → canonical still uses `SITE_ORIGIN`.
- Non-indexable route (`/login`, `/admin/dashboard`, `/titles/[slug]/edit`) → no `<link rel="canonical">` in the body, `resolve` called without options.
- `route.id === null` (404) → no canonical.
- Unclassified route (`/__health`) → no canonical, no crash.
- Per-route query-param allowlist: when `CANONICAL_QUERY_PARAMS` lists `page` for a route, the canonical preserves `?page=2` but still strips other params.

Unit tests for `canonicalUrl()` cover trailing-slash normalization, query-param allowlist application, and the `SITE_ORIGIN` override in isolation from the hook plumbing.

## Implementation order

1. `frontend/src/lib/seo/canonical.ts` — pure `canonicalUrl()` + `escapeHtmlAttribute()` functions, unit-tested.
2. Add `canonicalHandle` to `frontend/src/hooks.server.ts` and append it to the `sequence()` after `noindexHandle`.
3. Add `frontend/src/hooks-canonical.server.test.ts` per § "Tests".
4. Verify locally:
   - `curl -s localhost:5173/titles/medieval-madness | grep canonical` shows `<link rel="canonical" href="${SITE_ORIGIN}/titles/medieval-madness" />`.
   - `curl -s 'localhost:5173/titles/medieval-madness?foo=bar' | grep canonical` shows the same canonical (no query).
   - `curl -s localhost:5173/login | grep canonical` shows nothing.
   - `curl -s localhost:5173/__health | grep canonical` shows nothing.

## Considered alternatives

- **Layout-load implementation (`+layout.server.ts` returns `{ indexable, canonical }`, root `+layout.svelte` reads `data.canonical` in a `<svelte:head>` block).** Rejected for the same reason `NoindexMeta.md` rejected it: pushes `indexable`/`canonical` fields into every page's `PageData` type, forcing every test that constructs a literal `data` fixture to add them. Also fails to emit the canonical on the initial response for `ssr=false` routes (SvelteKit serves the static shell without running layout loads; the data lands only on the deferred `__data.json` fetch). The hook approach has neither problem.
- **Fold into `noindexHandle`.** Considered — both hooks read `shouldIndex(event.route.id)` and both inject into `</head>` via `transformPageChunk`. Rejected to keep each hook single-responsibility: noindex and canonical are complementary signals (exactly one fires per route), and splitting them keeps each one's intent obvious in the `sequence()` and lets the test files name what they cover. The cost (one extra `transformPageChunk` pass on indexable routes) is invisible.
- **Use `event.url.href` directly.** Rejected: bakes in the request host and query string, so a request to a preview origin or with a tracking param would emit a wrong canonical. The `canonicalUrl()` helper exists precisely to strip these.
- **Per-page `<svelte:head>` blocks in each indexable route.** Rejected: would silently miss any new indexable route until a reviewer noticed. Centralizing in a hook means a new route inherits correct behavior automatically.
- **Fold into `NoindexMeta.md` and rename it `HeadSeoTags.md`.** Considered — same mechanism, both driven by `isSearchEngineIndexable()`. Rejected to keep each plan single-purpose and matching the existing `seo/` directory pattern. The implementation files (`hooks.server.ts`, the two hook tests) share a directory and a helper; the plans don't need to.

## Open questions

None.
