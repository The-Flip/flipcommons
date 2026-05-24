# Search Engine Strategy

This is a hub document about how the project interacts with search engines -- such as which deploys are crawlable, which pages on a crawlable deploy belong in the index, how we tell crawlers about them, how the data on each page is presented in results.

## The concerns

## Per-route metadata

Several consumers — sitemap, noindex meta, and any future per-route enforcement (canonical declaration, title/description presence) — read from the same per-route classification:

```ts
isIndexable(routeId): boolean
```

defined in [`RouteWalking.md`](RouteWalking.md). The predicate composes the per-route `searchEngineInclusion` export with the auth-gating layout-chain check. Each consumer applies it differently — sitemap filters _in_, noindex injects _out_, robots.txt mostly ignores it (its scope is server endpoints, not pages) — but they can't drift, because there's only one source.

### Server-side rendering

Public routes must render meaningful HTML server-side, not depend on client-side hydration to become visible to crawlers. A public route that flips to CSR-only is effectively non-indexable.

#### SSR routes done

Detail pages (`/titles/[slug]`, `/models/[slug]`, and the rest of the catalog detail routes) declare `ssr = true` on their `+layout.ts`. Edit subroutes correctly declare `ssr = false` — non-indexable, so it doesn't matter.

#### SSR routes not yet done

##### Catalog listing pages are CSR-only

[`/titles/+page.ts:2`](frontend/src/routes/titles/+page.ts#L2),[`/manufacturers/+page.ts:2`](frontend/src/routes/manufacturers/+page.ts#L2), [`/corporate-entities/+page.ts:2`](frontend/src/routes/corporate-entities/+page.ts#L2), and the rest of the listings export `ssr = false`.

This was a deliberate performance choice; the listings hydrate a large client-side slug (e.g. all titles) so filtering/sorting is instant — but the cost is that they currently don't render meaningful HTML for crawlers. Fixing isn't just flipping the flag: the page's data-loading and rendering model is built around having the full dataset client-side.

Fixing this isn't urgent; the listing pages are not super important for driving search traffic, unlike detail pages.

Either the SSR path needs a different (lighter) data shape, or the page architecture changes, or we accept the tradeoff and mark listings `searchEngineInclusion = 'excluded'`, relying on the sitemap of detail pages for discovery. Decision still open.

##### `/users/[username]` is CSR-only

([`+page.ts:6`](frontend/src/routes/users/[username]/+page.ts#L6)). Smaller scope than listings; likely just needs an SSR path.

##### No enforcement test

There's nothing today that catches a regression where someone adds `ssr = false` to a new indexable route. The check is exactly the kind of route-tree property `RouteWalking.md` is built for: walk the layout chain, assert every indexable route has SSR enabled. Belongs there as a follow-up.

### ✅ DONE: 404 status integrity

A "not found" page must return HTTP 404, not 200 with apologetic copy ("soft-404"). Soft-404s confuse search indexing — it sees the 200 and may index the apology page. Entity loaders throw `error(404, …)` (e.g. `frontend/src/routes/models/[slug]/+layout.server.ts`) and `frontend/src/routes/+error.svelte` renders the response; the constraint is to keep using these rather than rolling custom not-found rendering in `+page.svelte`.

### Gating staging deploys

Staging environments should never appear in Google, regardless of what links to them. See [`Robots.md`](Robots.md).

### Excluding pages from crawling

Server endpoints like `/api/`, `/djadmin/`, and `/_sentry_test` aren't user-facing pages and shouldn't be crawled at all — fetches against them waste crawl budget and load the backend with no SEO benefit.

See [`Robots.md`](Robots.md).

### Excluding pages from search indexes

Routes like `/login`, `/search`, `/style-lab`, `/kiosk/*`, and `/*/edit` are real pages that crawlers can reach via inbound links — but they shouldn't appear in search results. Per [Google's guidance](https://developers.google.com/search/docs/crawling-indexing/block-indexing), robots.txt is the wrong tool for this (see § "Why the split between robots.txt and noindex" below).

See [`NoindexMeta.md`](NoindexMeta.md).

### Per-page title and description

Every indexable route needs a unique, meaningful `<title>` and `<meta name="description">`. The title drives the clickable SERP heading; the description drives the snippet underneath. Generic or duplicated values across pages dilute ranking and click-through. The route-walking primitive could enforce that every indexable route declares both.

### Canonical URLs

Multiple URLs can serve the same or near-identical content: trailing-slash variants, query-string variants, scheme/host variants. Without `<link rel="canonical">`, Google picks one to index and may pick wrong, splitting ranking signals across duplicates. (The Single-Model-Title case where Title and Model pages show the same content is already collapsed by a 301 redirect on `/models/[slug]`, so canonical tags aren't load-bearing there.)

See [`CanonicalUrl.md`](CanonicalUrl.md).

### Aiding search engine discovery

A sitemap enumerates every indexable URL with its `lastmod` timestamp. This helps crawlers find pages they might otherwise miss (especially ones with few inbound links) and prioritize re-crawls when content changes. It doesn't make a page indexable on its own — indexing is default-on for any crawled, non-noindex page — but it accelerates discovery and signals freshness.

See [`Sitemap.md`](Sitemap.md).

### URL stability across slug changes

The catalog supports slug edits. Without `301` redirects from the old slug to the new one, every rename silently discards accumulated SEO equity (inbound links, ranking history) and creates broken bookmarks. The mechanism belongs in the slug-edit flow itself, not in a separate SEO mechanism.

### Structured data

JSON-LD or microdata using schema.org types — `Product`-like schemas for Models, `Person` for designers and artists, `Organization` for manufacturers, `BreadcrumbList` for navigation. Google uses these for rich results: knowledge panels, carousels, breadcrumb display in SERPs. High-leverage for a domain catalog like this, but only valuable if maintained accurately per entity type.

### Faceted and paginated listing URLs

Listing pages like `/titles?manufacturer=stern&era=ss&page=2` can multiply into thousands of low-value URL combinations, wasting crawl budget and creating thin/duplicate content problems. Strategies include: canonicalizing filtered/paginated views back to the base listing, applying `noindex` to filter combinations, or restricting which combinations are linkable.

### Search Console operations

Verifying the production property, submitting the sitemap URL, monitoring index-coverage reports, and watching for manual actions or security warnings. Operational rather than architectural — belongs in an ops runbook rather than a code-design doc.
