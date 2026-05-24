# sitemap.xml

This is the plan for introducing `sitemap.xml` to the project. SvelteKit owns public pages, so the file lives there as a `+server.ts` endpoint. The frontend uses [`super-sitemap`](https://github.com/jasongitmail/super-sitemap) for XML rendering, and discovers dynamic-route slugs from a Django-side registry of per-entity sitemap feeds.

Addresses the "aiding search engine discovery" concern in [`SearchEngines.md`](SearchEngines.md); see that doc for how this fits with robots.txt and the per-page noindex meta.

This PR builds on [`Robots.md`](Robots.md), which already shipped the `ALLOW_SEARCH_ENGINE_INDEXING` env var, the `lib/server/search-engine-indexable.ts` helper, and the deploy-time validation. It also adds the `Sitemap: ${SITE_ORIGIN}/sitemap.xml` line to the existing `robots.txt`.

## Dependencies

- [`RouteWalking.md`](RouteWalking.md) — provides `allRoutes()`, `isSearchEngineIndexable(routeId)`, and the `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS` constant in `frontend/src/lib/route-metadata.server.ts`.
- [`Robots.md`](Robots.md) — provides the `ALLOW_SEARCH_ENGINE_INDEXING` env var, `lib/server/search-engine-indexable.ts`, and the deploy-time validation that prevents preview/staging from leaking. The sitemap endpoint reuses the same helper rather than re-reading the env var.

Throughout this doc, `isSearchEngineIndexable(routeId)` refers to the predicate defined in `RouteWalking.md` — true when the route is a `catalog-detail` / `catalog-edit-history` / `catalog-sources` route or appears in `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS`; false otherwise.

## Goals

- Tell crawlers what to index (the public catalog).
- Give search engines accurate `<lastmod>` per catalog page so they can prioritize re-crawls.
- Adding a new indexable entity type should be a one-file backend change with no frontend touch.

## 1. Backend — sitemap feed registry

Catalog (and any future indexable-content app) shouldn't have to know about a "sitemap" concept beyond "here are my feeds." We use the registration pattern AppBoundaries.md prescribes for cross-app composition:

> _"registration hooks, where a generic subsystem lets another app register behavior without becoming coupled to it"_

### Layout

**`apps/core/sitemap/`** — generic subsystem. No imports from other apps.

```python
# apps/core/sitemap/registry.py
from collections.abc import Iterable
from datetime import datetime
from typing import NamedTuple, Protocol

class SitemapEntry(NamedTuple):
    slug: str
    updated_at: datetime

class SitemapFeed(Protocol):
    kind: str             # 'titles', 'models', 'taxonomy_themes', ...
    route_pattern: str    # SvelteKit route ID, e.g. '/titles/[slug]'
    def entries(self) -> Iterable[SitemapEntry]: ...
    def max_updated_at(self) -> datetime | None: ...

_REGISTRY: dict[str, SitemapFeed] = {}

def register_sitemap_feed(feed: SitemapFeed) -> None:
    """Called from each app's AppConfig.ready(). Raises on duplicate kind."""

def get_sitemap_feed(kind: str) -> SitemapFeed | None: ...
def all_registered_feeds() -> list[SitemapFeed]: ...
```

```python
# apps/core/sitemap/api.py
from apps.core.rate_limits import RateLimitSpec, check_and_record_ip

SITEMAP_FEED_RATE_LIMIT = RateLimitSpec(
    bucket="sitemap_feed",
    limit=120,
    window_seconds=60,
)

@router.get("/sitemap/")
def list_feeds(request) -> list[SitemapFeedSummarySchema]:
    """Discovery endpoint — frontend reads this to know what feeds exist."""
    check_and_record_ip(request, SITEMAP_FEED_RATE_LIMIT)
    return [
        SitemapFeedSummarySchema(
            kind=f.kind,
            route_pattern=f.route_pattern,
            max_updated_at=f.max_updated_at(),
        )
        for f in all_registered_feeds()
    ]

@router.get("/sitemap/{kind}/")
def get_feed(request, kind: str) -> list[SitemapEntrySchema]:
    check_and_record_ip(request, SITEMAP_FEED_RATE_LIMIT)
    feed = get_sitemap_feed(kind)
    if feed is None:
        raise Http404
    return list(feed.entries())
```

**`apps/catalog/sitemap_feeds.py`** — catalog's plug-ins.

```python
from apps.core.sitemap import SitemapEntry, register_sitemap_feed
from apps.catalog.models import Title, MachineModel, Manufacturer, ...

class TitleSitemapFeed:
    kind = "titles"
    route_pattern = "/titles/[slug]"
    def entries(self):
        return (Title.objects
            .only("slug", "updated_at")
            .order_by("slug")
            .iterator())
    def max_updated_at(self):
        return Title.objects.aggregate(Max("updated_at"))["updated_at__max"]

class ModelSitemapFeed:
    kind = "models"
    route_pattern = "/models/[slug]"
    def entries(self):
        # Single-Model-Title rule: exclude Models whose parent Title has exactly one Model.
        # The UI collapses single-Model Titles into the Model page (per docs/SingleModelTitles.md),
        # so the Title slug is canonical and indexing both routes would split signals.
        return (MachineModel.objects
            .annotate(_sibling_count=Count("title__models"))
            .filter(_sibling_count__gt=1)
            .only("slug", "updated_at")
            .order_by("slug")
            .iterator())
    def max_updated_at(self): ...

# ...one class per indexable entity type (Manufacturer, Person, System, Series,
# Franchise, Location — path-variant — plus each taxonomy type)

register_sitemap_feed(TitleSitemapFeed())
register_sitemap_feed(ModelSitemapFeed())
# ...
```

```python
# apps/catalog/apps.py
class CatalogConfig(AppConfig):
    def ready(self):
        from apps.catalog import sitemap_feeds  # noqa: F401 — registers on import
```

### Why this shape

- **Boundary respect.** Core defines the Protocol and dispatch; doesn't import catalog. Catalog imports core (already legal) and registers itself. Future non-catalog apps (kiosk, hypothetical blog) plug in without touching core or catalog.
- **Dynamic discovery.** Frontend reads `GET /api/sitemap/` once per render to learn what feeds exist. Adding a new entity type is a one-file backend change.
- **Rate limiting.** Each feed query is a DB hit; without protection, a fanout abuser could drive real load. Reuses `apps/core/rate_limits.py`'s existing IP-keyed limiter. 120/min is comfortable for the ~15-call fanout per `/sitemap.xml` render (real crawlers fetch maybe daily), tight enough to deflect abuse.
- **Public reads — no auth gate.** No `Activity` needed; these are public, non-mutating, and contain only data already on the indexable detail pages.
- **No lifecycle filter needed today** (no soft-delete or draft state exists). Add one if/when `RecordLifecycle.md` introduces non-live states.

Typed schemas (`SitemapEntrySchema`, `SitemapFeedSummarySchema`) live in `apps/core/sitemap/schemas.py`. Set `Cache-Control: public, max-age=3600` on both endpoints. Run `make api-gen` after.

## 2. Frontend — super-sitemap

The frontend uses [`super-sitemap`](https://github.com/jasongitmail/super-sitemap) for XML rendering. It handles escaping, `lastmod` formatting, and sitemap-index splitting (auto-flips to a `<sitemapindex>` if total URLs cross 50k). Pin to `super-sitemap@^1.0.12` — zero runtime dependencies, healthy maintenance (~40k downloads/month, single-maintainer with consistent cadence over 18+ months).

### Wiring

```ts
// frontend/src/routes/sitemap.xml/+server.ts
import * as sitemap from "super-sitemap";
import { SITE_ORIGIN } from "$env/static/private";
import { allRoutes, isSearchEngineIndexable } from "$lib/route-metadata.server";

// Every entity's detail page has two indexable sibling subroutes —
// /edit-history and /sources — that share the same slug. One loader serves
// all three pattern keys; super-sitemap renders one URL per (pattern, slug)
// combination. Keep this list aligned with the indexable catalog-* kinds
// in route-metadata.server.ts; if a new indexable subroute lands (or one
// flips to non-indexable), update both places.
const INDEXABLE_CATALOG_SUBROUTE_SUFFIXES = [
  "",
  "/edit-history",
  "/sources",
] as const;

export const GET = async ({ fetch }) => {
  const feeds = await fetch("/api/sitemap/").then((r) => r.json());

  const paramValues: Record<string, () => Promise<sitemap.ParamValues>> = {};
  for (const { kind, route_pattern } of feeds) {
    const loader = async () => {
      const entries = await fetch(`/api/sitemap/${kind}/`).then((r) =>
        r.json(),
      );
      return entries.map((e) => ({ values: [e.slug], lastmod: e.updated_at }));
    };
    for (const suffix of INDEXABLE_CATALOG_SUBROUTE_SUFFIXES) {
      paramValues[`${route_pattern}${suffix}`] = loader;
    }
  }

  return sitemap.response({
    origin: SITE_ORIGIN,
    excludeRoutePatterns: allRoutes()
      .filter((id) => !isSearchEngineIndexable(id))
      .map(routeIdToRegex),
    paramValues,
  });
};
```

That's the whole endpoint. Adding a new entity type requires zero changes here — `GET /api/sitemap/` reports the new feed, the loop wires it into `paramValues` for detail + edit-history + sources automatically.

### Why super-sitemap

- **Debuggability win.** XML correctness (escaping, `lastmod` formatting, index-vs-urlset switching) is annoying to verify by hand. With the library, the debugging surface shrinks from "is our XML right?" to "does our config produce what we expect?" — and the latter is straightforward to test.
- **Boring tech in scope.** Sitemap protocol is stable; we don't need innovation here.
- **Library doesn't conflict with rate limiting.** It's just an XML-response helper at the SvelteKit layer; rate limiting lives at the Django endpoint where it belongs.

### One subtlety to handle

`super-sitemap`'s `paramValues` callbacks fail the whole sitemap render if any throws. If a backend feed returns 429 during a fetch, the entire `/sitemap.xml` returns 5xx to the crawler. Mitigations:

- The 120/min rate limit + 1-hour `Cache-Control` make this vanishingly rare in practice.
- If we see it in production, wrap each callback in try/catch returning `[]` (better: last-known-good cached entries) so the sitemap degrades gracefully rather than failing whole.

Start with the simple version; harden only if observed.

### Gate on `ALLOW_SEARCH_ENGINE_INDEXING`

Reuse the `lib/server/search-engine-indexable.ts` helper from `Robots.md`. When `ALLOW_SEARCH_ENGINE_INDEXING != "true"`, return `404 Not Found` for `/sitemap.xml` — a non-indexable deploy has nothing to advertise. The robots.txt-side `Disallow: /` already keeps crawlers out; the 404 is defense in depth.

## 3. Add `Sitemap:` line to robots.txt

The `robots.txt` endpoint shipped in [`Robots.md`](Robots.md) does not yet emit a `Sitemap:` line. Once `/sitemap.xml` exists, append it to the indexable-mode body:

```text
Sitemap: ${SITE_ORIGIN}/sitemap.xml
```

One-line additive change. Update the existing robots vitest to assert the line is present iff `ALLOW_SEARCH_ENGINE_INDEXING == "true"`.

## 4. What goes in the sitemap

**In:**

- `/`
- `/about`, `/about/people`
- `/legal/privacy`, `/legal/terms`, `/legal/licensing`
- All catalog detail pages with their `updated_at` as `lastmod`, plus per-entity `/edit-history` and `/sources` URLs (every `catalog-detail` / `catalog-edit-history` / `catalog-sources` route classifies as indexable), except:
  - **Single-Model Titles** — when a Title has exactly one Model, include the Title route and **exclude** the Model route. The UI collapses single-Model Titles into the Model page (per `docs/SingleModelTitles.md`), but the Title slug is the canonical URL; indexing both would split signals and create duplicate-content noise. Enforced in `ModelSitemapFeed.entries()`.

**Out:**

- `/style-lab`, `/api-docs`, `/search`, `/kiosk`, `/_sentry_test`, `/auth/error`
- Catalog listing pages (`/titles`, `/models`, `/manufacturers`, etc.) — non-indexable today per [`RouteWalking.md`](RouteWalking.md) (low search value + CSR-only); discoverability is covered by the catalog detail entries above. Revisit when listing SSR lands.
- Catalog `/new` and `/delete` subroutes — non-indexable.
- Anything auth-gated — recognized by `requireCapability` in the layout chain; non-indexable routes are excluded by `isSearchEngineIndexable(routeId)`; never enumerated by hand
- Models whose parent Title has exactly one Model (see above)

## 5. Startup validation — `SITE_ORIGIN`

`SITE_ORIGIN` is consumed at _both_ build time (baked into prerendered meta tags) and deploy/runtime (sitemap URLs and the `Sitemap:` line in robots.txt), so it needs gates at both phases. Pattern and conventions per `docs/BuildChecks.md` and `docs/DeployChecks.md`.

### Build-phase check

Today `frontend/svelte.config.js:40` falls back to `'http://localhost:5173'` when `SITE_ORIGIN` is unset. That fallback is the right behavior for `make dev`, but in a production build it silently bakes `localhost` URLs into prerendered HTML — exactly the failure mode we want a refusal gate for.

Approach: keep the dev fallback, but fail the build when a production indicator is present (e.g. `RAILWAY_GIT_COMMIT_SHA` is set, which the project already treats as the "real build" signal — see the same file at line 34 / 37). If `RAILWAY_GIT_COMMIT_SHA` is set and `SITE_ORIGIN` is empty or doesn't shape-match an `https://` origin, throw with a clear message. Non-zero exit at this stage fails `pnpm build` and Railway refuses the image (per `docs/BuildChecks.md` § "What fails the build for free").

Add `SITE_ORIGIN` to `Dockerfile` `ARG` declarations alongside the existing build-time vars (the file already lists `RAILWAY_GIT_COMMIT_SHA`, `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT`), and set it on the Railway service. Per `docs/BuildChecks.md` § "What requires explicit wiring", a missing `ARG` silently turns the consumer into a no-op — so this is a two-step change.

### Deploy-phase check

Frontend env vars are validated in Python because backend and frontend share the Railway env (per `docs/DeployChecks.md` § "Frontend checks belong in Python"). Add to `backend/apps/core/checks.py` (alongside `check_observability_env` and the `ALLOW_SEARCH_ENGINE_INDEXING` check from `Robots.md`):

- **`SITE_ORIGIN`** — `@register(Tags.security, deploy=True)` check that errors when `SITE_ORIGIN` is empty in non-DEBUG. Shape-validate it as an `https://` origin with a netloc and no path/trailing slash (reuse the `urlparse` pattern from `_is_valid_dsn`). New error ids `core.E301` (missing) and `core.E302` (malformed). Catches the case where the build had a value but the running container does not.

Tests in `backend/apps/core/tests/test_checks.py`: one test per error id — flip the env state, assert the message id appears (or doesn't).

The check is deploy-gated (`deploy=True`), so it only runs under `manage.py check --deploy` — i.e., Railway's `preDeployCommand`. Reproduce locally per `docs/DeployChecks.md` § "Running deploy checks locally".

## 6. Tests

- **Backend (pytest):**
  - `apps/core/tests/test_sitemap_registry.py` — registry mechanics: register, lookup, list, duplicate-kind raises. Uses a fake feed; doesn't import catalog.
  - `apps/core/tests/test_sitemap_api.py` — dispatch endpoint: 200 with expected shape for a registered kind, 404 for an unknown kind, listing endpoint returns the registered feeds, rate-limit returns 429 with `Retry-After` past the threshold.
  - `apps/catalog/tests/test_sitemap_feeds.py` — each catalog feed's queryset shape, ordering, `max_updated_at` matches newest row. Includes the single-Model-Title exclusion test for `ModelSitemapFeed`.
  - One test per `core.E301` / `core.E302` error id in `apps/core/tests/test_checks.py`.
  - **XSD validation** — fetch `/sitemap.xml` via an in-process test client and validate the response against the sitemaps.org XSD using `xmllint --noout --schema`. Catches schema drift on every CI run.
- **Frontend (vitest):**
  - `sitemap.xml/+server.ts` builds super-sitemap's `paramValues` correctly from a mocked `/api/sitemap/` response, including the fan-out: a single backend feed produces param entries under three pattern keys (detail + `/edit-history` + `/sources`) with the same slug list.
  - `sitemap.xml/+server.ts` returns 404 when `ALLOW_SEARCH_ENGINE_INDEXING != "true"`.
  - Existing robots.txt test extended to assert the `Sitemap:` line is present iff `ALLOW_SEARCH_ENGINE_INDEXING == "true"`.

## 7. Implementation order

1. Add the `SITE_ORIGIN` build-phase guard in `frontend/svelte.config.js` (throw when `RAILWAY_GIT_COMMIT_SHA` is set and `SITE_ORIGIN` is empty/malformed). Declare `SITE_ORIGIN` as an `ARG` in `Dockerfile`.
2. Add the `SITE_ORIGIN` deploy check in `apps/core/checks.py`, with tests. Verify locally per `docs/DeployChecks.md` § "Running deploy checks locally".
3. `apps/core/sitemap/registry.py` — `SitemapEntry`, `SitemapFeed` Protocol, `register_sitemap_feed` / `get_sitemap_feed` / `all_registered_feeds`. Tests with a fake feed.
4. `apps/core/sitemap/api.py` — dispatch endpoint at `/api/sitemap/{kind}/`, listing endpoint at `/api/sitemap/`, IP rate limiting via `apps.core.rate_limits`. Tests for 200 / 404 / 429 paths.
5. `apps/catalog/sitemap_feeds.py` — `TitleSitemapFeed`, `ModelSitemapFeed` (with single-Model-Title filter), and the rest of the catalog feeds. Tests per feed.
6. `apps/catalog/apps.py` — trigger registration in `AppConfig.ready()`.
7. `make api-gen`.
8. `pnpm add super-sitemap@~1.0.12`.
9. `frontend/src/routes/sitemap.xml/+server.ts` — wire super-sitemap to `/api/sitemap/` + `/api/sitemap/{kind}/`, with `excludeRoutePatterns` derived from the manifest. Gate on `ALLOW_SEARCH_ENGINE_INDEXING` via the helper from `Robots.md`.
10. Append the `Sitemap:` line to `frontend/src/routes/robots.txt/+server.ts` (indexable-mode only). Extend the existing robots test.
11. Add the XSD validation test (backend pytest, fetches its own endpoint and pipes through `xmllint`).
12. Verify locally: `curl localhost:5173/sitemap.xml`, validate with `xmllint --noout --schema`.

### Deployment routing

No Caddyfile changes needed. The current `@django` matcher in `Caddyfile` only catches `/api`, `/djadmin`, `/media`, `/static`, so `/sitemap.xml` routes to SvelteKit (Node, port 3000) by default.

## Considered alternatives

- **Hand-rolled XML rendering.** Considered to avoid a third-party dependency. Rejected: the library's value isn't lines saved (it's only ~80), it's that XML correctness (escaping, `lastmod` formatting, sitemap-index splitting) becomes the library's problem to debug rather than ours.
- **New `apps/sitemap/` Django app.** Considered. Rejected per `docs/AppBoundaries.md`: a new app should own a distinct concept, and sitemap feeds are thin projections over existing catalog data with no domain of their own.
- **Hand-rolled sitemap index from day one.** Considered for "future-proofing" against the 50k-URLs-per-file cap. Rejected: super-sitemap auto-flips from `<urlset>` to `<sitemapindex>` when needed, the catalog is years from 50k.
- **Per-route hardcoded sitemap config on the frontend.** Rejected: hardcoding means adding a new entity type requires touching the frontend, defeating the registration pattern's main benefit.

## Open questions

1. **Production hostname** — confirm `SITE_ORIGIN` in production (presumably `https://flipcommons.org`?) so the `Sitemap:` line is right.

## Resolved

- **People pages** (`/people/[slug]`) — catalog persons (designers, artists, etc.). Indexable; included in the sitemap.
- **Soft-delete / draft state** — none exist today. No lifecycle-based filter needed in the sitemap feeds; revisit if/when drafts or soft-delete are introduced.
- **Single-Model Titles** — include the Title route; exclude the Model route. Title slug is canonical; indexing both would split signals.
