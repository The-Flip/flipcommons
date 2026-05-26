# sitemap.xml

This is the plan for introducing `sitemap.xml` to the project.

## Goals

- Let search engines know what is available to be indexed.
- Give search engines accurate `<lastmod>` per catalog page so they can prioritize re-crawls.

See [`SearchEngines.md`](SearchEngines.md) for how this fits with `robots.txt` and the per-page `noindex` meta.

## Overview

The sitemap is a SvelteKit `+server.ts` endpoint that renders `/sitemap.xml` via [`super-sitemap`](https://github.com/jasongitmail/super-sitemap). Per-URL `<lastmod>` comes from two sources:

- **Dynamic catalog pages**: a single Django endpoint derives feeds from `LinkableModel` subclasses, returning per-instance `(slug, lastmod)`. The default `lastmod` is the record's own `updated_at`; the single override (`Title`) widens it to include its Models' `updated_at`.
- **Static pages** (`/`, `/about`, `/legal/*`): a build-time manifest computed from `git log -1 --format=%cI` over each route's source file. The same manifest backs "Last updated: …" footers on legal pages so the user-visible date and the sitemap `lastmod` come from the same value.

Appends a `Sitemap:` line to the existing `frontend/src/routes/robots.txt/+server.ts`.

## Invariants

The design MUST satisfy these properties:

1. **Adding a new catalog model puts its URLs in the sitemap automatically.** A new catalog model (a `LinkableModel` subclass classified as a catalog entity per [RouteWalking.md](RouteWalking.md)) produces complete `<url>` entries for its detail page, `/edit-history`, and `/sources` — each with a correct `lastmod` — without any human-authored sitemap code. When a catalog model needs to narrow which instances belong in the sitemap (today: `MachineModel`'s single-Model-Title exclusion), the override lives on the model via `sitemap_queryset()` — never in `apps/core/sitemap.py` or the SvelteKit endpoint. The invariant scopes to catalog models specifically: static routes (`/`, `/about`, `/legal/*`) and any future non-catalog dynamic indexable routes (e.g. `/users/[username]` if it flips indexable) are handled through their own mechanisms, but they are not the automation target — the catalog is.

2. **The sitemap URL set equals the indexable route set.** Every route where `isSearchEngineIndexable() === true` produces sitemap `<url>` entries; no route where it returns `false` does. Both directions flow through that single predicate — via `excludeRoutePatterns` for static routes and via `catalogRoutesByEntity()` for per-entity dynamic routes. There is no sitemap-specific allowlist or denylist for either inclusion or exclusion.

3. **Every `<lastmod>` reflects the actual freshness of the page's primary content.**
   - For catalog pages, the default `lastmod` is the record's own `updated_at`, because the primary content of nearly every catalog detail page comes from the record itself. The single override is `Title`, whose page also renders the list of its Models — its `lastmod` is `Greatest(Title.updated_at, Max(Models.updated_at))`. This naturally covers the Single-Model-Title case, where the Title page collapses to show the lone Model's content: the Model's edits flow into the Title's `lastmod` via the same aggregation.
   - For static pages, `lastmod` is the last git-commit time on the route's source file, baked into a manifest at build time.
   - There is no separate "sitemap timestamp" anywhere to keep in sync — catalog `lastmod` staleness is bounded by the 1-hour `Cache-Control`, and static `lastmod` is fixed at deploy.

The first invariant comes from the [model-driven metadata](../model_driven_metadata/ModelDrivenMetadata.md) discipline: a parallel hand-maintained per-model sitemap registry is exactly the drift surface a `LinkableModel` walk eliminates, and an entity silently absent from search is invisible to detect — it just doesn't show up in the traffic that never existed.

The second invariant is what makes the sitemap honest. A URL in `/sitemap.xml` is a "please index this" signal to crawlers; a URL absent from it asks search engines to find the page some other way (links, manual submission). Both failure modes are expensive: a non-indexable URL leaking into the sitemap wastes crawl budget on pages that then emit `noindex`, while an indexable URL missing from it slows discovery by weeks. Making both impossible-by-construction beats catching them after deploy.

The third invariant matters because `lastmod` is the signal Google uses to prioritize re-crawls — a sitemap that lies about freshness (or just stops getting refreshed) loses its main value over a flat URL list. Two failure modes are worth naming:

- A `lastmod` that doesn't move when the page's content changed → search engines re-crawl too late.
- A `lastmod` that moves when the page's content didn't change → search engines re-crawl wastefully, and eventually learn to distrust the signal.

The "record's own `updated_at`, plus one Title override" rule under-reports on transitive edits (a Manufacturer rename doesn't bump every Title listing it) and that's an accepted tradeoff — Google won't re-crawl every Title because of a Manufacturer typo anyway, and the alternative is an unbounded relationship walker that over-reports on internal non-content edits.

## 1. Backend — derive feeds from `LinkableModel`

Every catalog detail page is indexable and every listing / new / delete page is not (per [`NoindexMeta.md`](NoindexMeta.md)). That rule applies uniformly to every `LinkableModel` subclass, so the sitemap doesn't need any per-model declaration — it walks the existing `LinkableModel` registry (the same `apps.get_models()` + `issubclass` walk [`apps/core/entity_types.py`](../../../backend/apps/core/entity_types.py) already does) and reads metadata the model already carries.

This is the [`_meta` walk](../model_driven_metadata/ModelDrivenMetadata.md#pattern-_meta-walk) + [base class / mixin](../model_driven_metadata/ModelDrivenMetadata.md#pattern-base-class--mixin) shape from [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md). No `apps/catalog/sitemap_feeds.py`, no `register_sitemap_feed()` calls, no `AppConfig.ready()` hook. Adding a new `LinkableModel` catalog subclass lights up automatically.

### What the model already provides

| Feed field | Source on `LinkableModel`                                           |
| ---------- | ------------------------------------------------------------------- |
| `kind`     | `entity_type`                                                       |
| slug field | `public_id_field` (defaults to `"slug"`)                            |
| `lastmod`  | `_sitemap_lastmod` annotation from `sitemap_queryset()` classmethod |

No `route_pattern` is emitted — the frontend already maps `entity_type` → SvelteKit route IDs via `catalogRoutesByEntity()` ([`route-metadata.server.ts`](../../../frontend/src/lib/route-metadata.server.ts)), so emitting SvelteKit-shaped patterns from Python would just duplicate that map.

### Per-model override

A single `sitemap_queryset()` classmethod on `LinkableModel` covers all the catalog-page wrinkles, defaulting to the no-special-case shape. One method, not two: see [Considered alternatives](#considered-alternatives) for why `canonical_url_queryset()` was dropped.

```python
# apps/core/models/mixins.py — extending LinkableModel
@classmethod
def sitemap_queryset(cls) -> QuerySet[Self]:
    """Instances to include in the sitemap, annotated with `_sitemap_lastmod`.

    Default: every row, with `_sitemap_lastmod = updated_at`. Override to
    narrow the queryset (e.g. exclude rows whose URL isn't canonical), to
    widen the lastmod (e.g. aggregate child timestamps), or both.

    Return `cls.objects.none()` to opt a `LinkableModel` out of the sitemap
    entirely — e.g. a through-table entity with no detail page.
    """
    return (
        cls.objects
        .annotate(_sitemap_lastmod=F("updated_at"))
        .only(cls.public_id_field, "updated_at")
        .order_by(cls.public_id_field)
    )
```

The two overrides today:

```python
# apps/catalog/models/machine_model.py
class MachineModel(LinkableModel, ...):
    @classmethod
    def sitemap_queryset(cls):
        # Single-Model-Title rule: when a Title has exactly one Model, the UI
        # collapses to the Model page (per docs/SingleModelTitles.md), but the
        # Title slug is canonical. Indexing both would split signals.
        return (
            super().sitemap_queryset()
            .annotate(_sibling_count=Count("title__machine_models"))
            .filter(_sibling_count__gt=1)
        )
```

```python
# apps/catalog/models/title.py
class Title(LinkableModel, ...):
    @classmethod
    def sitemap_queryset(cls):
        # Title is the only catalog page whose primary content aggregates other
        # catalog entities (the Model list, plus — for single-Model Titles — the
        # collapsed Model's content). Bump lastmod when any of those change.
        #
        # Rebuilt from `cls.objects` (rather than `super().sitemap_queryset()`)
        # to avoid Django's re-annotation footgun: a second `.annotate()` on the
        # same alias (`_sitemap_lastmod`) doesn't reliably win across Django
        # versions. `Coalesce` defends against `Max(...) = NULL` for zero-Model
        # Titles on non-Postgres backends — Postgres' GREATEST already ignores
        # NULLs, but the explicit fallback is portable.
        return (
            cls.objects
            .annotate(
                _sitemap_lastmod=Greatest(
                    F("updated_at"),
                    Coalesce(Max("machine_models__updated_at"), F("updated_at")),
                ),
            )
            .only(cls.public_id_field, "updated_at")
            .order_by(cls.public_id_field)
        )
```

Note `machine_models` (not `models`) — that's the `related_name` on `MachineModel.title` and `MachineModel.title` is the only FK from `MachineModel` to `Title`. Read directly off `type[LinkableModel]` — no `getattr` fallback (per the [field-on-model antipattern](../model_driven_metadata/ModelDrivenMetadata.md#antipattern-field-on-model)).

### Derivation + single API endpoint

`apps/core/sitemap.py`:

```python
class SitemapEntry(NamedTuple):
    slug: str
    lastmod: datetime

class SitemapFeed(NamedTuple):
    kind: str
    entries: list[SitemapEntry]
    max_lastmod: datetime | None

def all_sitemap_feeds() -> list[SitemapFeed]:
    apps.check_apps_ready()
    feeds: list[SitemapFeed] = []
    for model in apps.get_models():
        if not issubclass(model, LinkableModel) or model._meta.abstract:
            continue
        slug_field = model.public_id_field
        entries = [
            SitemapEntry(getattr(o, slug_field), o._sitemap_lastmod)
            for o in model.sitemap_queryset().iterator()
            if o._sitemap_lastmod is not None
        ]
        if not entries:
            continue
        feeds.append(
            SitemapFeed(
                model.entity_type, entries, max(e.lastmod for e in entries)
            )
        )
    return feeds
```

The `is not None` filter and the empty-feed skip together mean `max_lastmod` is always a real datetime — neither `max([])` nor `max([None, ...])` can raise.

One endpoint returns everything in one shot — no 1+N fan-out, no partial-failure mode:

```python
# apps/core/sitemap_api.py
SITEMAP_RATE_LIMIT = RateLimitSpec(bucket="sitemap", limit=10, window_seconds=60)

@router.get("/sitemap/")
def get_sitemap(request) -> SitemapResponseSchema:
    check_and_record_ip(request, SITEMAP_RATE_LIMIT)
    return SitemapResponseSchema(feeds=all_sitemap_feeds())
```

`Cache-Control: public, max-age=3600`. Typed schemas (`SitemapEntrySchema`, `SitemapFeedSchema`, `SitemapResponseSchema`) live in `apps/core/sitemap_schemas.py`. Run `make api-gen` after.

10/min is sized for the actual workload (crawlers fetch `/sitemap.xml` ~daily, and the SvelteKit endpoint hits this once per render) and pattern-matches the project's other IP-keyed public endpoints (signup availability). It's decorative defense in depth, not a real throttle — but the limiter is the established pattern for public reads.

**Payload size note.** `all_sitemap_feeds()` materializes every entry in memory before responding. Today (~10k Titles, ~10k Models, 19 LinkableModels) that's small. At catalog scale past ~50k entries per kind, this needs pagination or streaming — same cliff that triggers super-sitemap's auto-flip to `<sitemapindex>` on the frontend side.

### Why this shape

- **One override per wrinkle, no relationship walker.** Catalog pages overwhelmingly render their own record's content. The one exception (Title) gets a one-line `sitemap_queryset()` override; everything else inherits the default. No auto-derivation from Django relationships — walking all FK/M2M relationships over-includes (provenance ChangeSets, audit rows, denormalization caches aren't page content), and walking only `LinkableModel`-targeted relationships under-includes (non-LinkableModel entities like aliases or credit lines often drive page content precisely because they don't have their own page). A "smart" walker would be wrong in both directions; the honest answer is one explicit override for the one entity that actually aggregates.
- **One method, not two.** `sitemap_queryset()` covers both "which rows" and "what `lastmod`" because that's the only consumer today. A separate `canonical_url_queryset()` was considered for hypothetical future use by canonical-link tags or schema.org `mainEntityOfPage` (see Considered alternatives) — rejected as speculative future-proofing. If a second consumer arrives, split then.
- **Sitemap inclusion is implied by being a `LinkableModel`** that has a SvelteKit route for its `entity_type`. A `LinkableModel` without a matching route (today: none; tomorrow potentially through-tables like `MachineModelTag` or `MachineModelRewardType`) emits a Django feed that the frontend silently drops via `catalogRoutesByEntity().get(kind) === undefined`. To explicitly opt out, override `sitemap_queryset()` to return `cls.objects.none()`.
- **No fan-out.** One HTTP call from SvelteKit → Django. super-sitemap fails the whole render if a `paramValues` callback throws, so eliminating the per-feed fetches eliminates that failure mode.
- **Public reads, no auth gate.** Non-mutating, contains only data already on the indexable detail pages.
- **Rate-limited** via the existing IP-keyed limiter; 10/min matches the actual crawl cadence and the project's public-endpoint pattern.
- **No lifecycle filter needed today** (no soft-delete or draft state exists). `sitemap_queryset()` is the natural home if that changes — narrow the queryset to exclude soft-deleted rows.

## 2. Static pages — build-time `lastmod` manifest

Static routes (`/`, `/about`, `/about/people`, `/legal/privacy`, `/legal/terms`, `/legal/licensing`) live as committed Svelte files. Their `lastmod` is the file's last git-commit time. A Vite build step walks the static-route source files and emits `frontend/src/lib/static-lastmod.generated.json`:

```json
{
  "/": "2026-03-04T18:22:11+00:00",
  "/about": "2026-02-19T09:14:03+00:00",
  "/legal/privacy": "2026-04-11T16:55:00+00:00"
}
```

The set of static routes comes from the same `allRoutes().filter(isSearchEngineIndexable)` walk that drives the sitemap's `excludeRoutePatterns` — minus the routes covered by catalog feeds. There's no hand-maintained list of static pages.

"The source file" for a route is its `+page.svelte` (or `+page.svx` / equivalent leaf component). Changes to shared `+layout.svelte` files don't bump every leaf's `lastmod` — a layout polish isn't a content change to `/legal/privacy`.

The manifest is consumed by **two readers**:

1. **Sitemap endpoint** uses it to emit `<lastmod>` for static URLs alongside the catalog URLs from the Django feed.
2. **Legal page components** import it to render `Last updated: {formatDate(manifest['/legal/privacy'])}` in the footer. The user-visible date and the crawler-visible timestamp come from the same value, so they cannot disagree, and a wrong date is much easier to catch when a human sees it on every visit.

Generated file is gitignored (same pattern as `schema.d.ts`).

### Soft-fail behavior

`lastmod` is a crawler hint, not data anyone makes decisions on. The build step does NOT fail when `git` is unavailable or when a listed route's source file has no usable git history. The common failure mode is the build environment, not the source tree: shallow-clone build environments like Railway/Nixpacks ship with a depth-1 clone by default, in which `git log -1 --format=%cI <file>` returns the shallow tip's commit date for every file — silently making every page's `lastmod` identical.

Per route, the build step:

- Tries `git log -1 --format=%cI <file>`.
- If the result is missing, errors, or matches the shallow-clone tip date across multiple files (heuristic for "shallow clone, not real history"), falls back to the build-time clock and logs a warning naming the route(s) that fell back.
- Emits the manifest with whatever timestamps it found.

The fallback degrades `lastmod` accuracy on static pages, which is benign: those pages change rarely, and the legal-page footer reading from the same manifest makes any obvious wrongness human-visible. Trading a benign rare drift for a sharp build failure on a crawler hint isn't worth it. If the warning ever fires on a real deploy, the fix is unshallowing the clone or pinning per-page constants — not failing the build retroactively.

## 3. Frontend — super-sitemap

The frontend uses [`super-sitemap`](https://github.com/jasongitmail/super-sitemap) for XML rendering. It handles escaping, `lastmod` formatting, and sitemap-index splitting (auto-flips to a `<sitemapindex>` if total URLs cross 50k). Pin to `super-sitemap@^1.0.12` — zero runtime dependencies, healthy maintenance (~40k downloads/month, single-maintainer with consistent cadence over 18+ months).

### Wiring

```ts
// frontend/src/routes/sitemap.xml/+server.ts
import * as sitemap from "super-sitemap";
import { SITE_ORIGIN } from "$env/static/private";
import {
  allRoutes,
  catalogRoutesByEntity,
  isSearchEngineIndexable,
} from "$lib/route-metadata.server";
import { isDeploymentSearchEngineIndexable } from "$lib/is-deployment-search-engine-indexable.server";
import staticLastmod from "$lib/static-lastmod.generated.json";

export const GET = async ({ fetch }) => {
  if (!isDeploymentSearchEngineIndexable()) {
    return new Response("Not Found", { status: 404 });
  }

  const { feeds } = await fetch("/api/sitemap/").then((r) => r.json());

  // For each entity, gather all indexable SvelteKit route IDs that share its
  // slug (detail + /edit-history + /sources today; whatever is indexable
  // tomorrow). `isSearchEngineIndexable()` is the only filter, so a new
  // indexable subroute lands here automatically — no list to maintain.
  const indexableRoutesByEntity = catalogRoutesByEntity((_cls, id) =>
    isSearchEngineIndexable(id),
  );

  const paramValues: Record<string, sitemap.ParamValues> = {};
  for (const { kind, entries } of feeds) {
    const routeIds = indexableRoutesByEntity.get(kind);
    if (!routeIds) continue;
    const values = entries.map((e) => ({
      values: [e.slug],
      lastmod: e.lastmod,
    }));
    for (const id of routeIds) paramValues[id] = values;
  }

  return sitemap.response({
    origin: SITE_ORIGIN,
    excludeRoutePatterns: allRoutes()
      .filter((id) => !isSearchEngineIndexable(id))
      .map(routeIdToRegex),
    paramValues,
    additionalPaths: Object.entries(staticLastmod).map(([path, lastmod]) => ({
      path,
      lastmod,
    })),
  });
};
```

That's the whole endpoint. Adding a new entity type requires zero changes here — `GET /api/sitemap/` reports the new feed, `catalogRoutesByEntity()` finds its route IDs, the loop wires them into `paramValues`. Adding a new static page is picked up by the manifest build step automatically.

### Rest-param routes (`Location`)

`Location.public_id_field = "location_path"` — a slash-separated path like `"manufacturer/title/region/site"` — and its SvelteKit route is `/locations/[...path]` (rest segment). The frontend passes `values: [e.slug]` to super-sitemap regardless of whether the route uses `[slug]` or `[...path]`; the library must substitute the slash-containing string into the rest param without URL-encoding the `/`. Verify behavior against super-sitemap's API and add a targeted test (fixture: a Location with two path segments → expect `/locations/foo/bar` in the output, not `/locations/foo%2Fbar`). If super-sitemap encodes the slashes, the workaround is to split the path into segments and feed `values: e.slug.split("/")` for `[...path]` routes (detected by route ID shape).

### Tolerating unclassified routes

`isSearchEngineIndexable()` throws on routes the classifier doesn't recognize — by design, to force route authors to classify intentionally at lint/build time. At request time inside `/sitemap.xml`, that discipline turns into a sharp edge: one stray unclassified route 500s the entire sitemap. Wrap classifier calls inside the endpoint in a try/catch that logs and treats the route as non-indexable (the safer default — leak nothing rather than render nothing). The classifier still throws everywhere else it's called; only the sitemap endpoint downgrades the throw to a log.

### `routeIdToRegex` helper

`excludeRoutePatterns` expects regex strings. SvelteKit route IDs include `[slug]`, `[...path]`, `[[optional]]`, and `(group)` shapes, and the helper must escape `/`, `.`, `[`, `]` literals and translate dynamic segments to wildcard patterns that match what super-sitemap is iterating. Unit-test the helper directly with each shape and against the full `allRoutes()` snapshot — accidentally over- or under-matching here silently drops correct URLs from the sitemap or leaks non-indexable ones in.

### Why super-sitemap

- **Debuggability win.** XML correctness (escaping, `lastmod` formatting, index-vs-urlset switching) is annoying to verify by hand. With the library, the debugging surface shrinks from "is our XML right?" to "does our config produce what we expect?" — and the latter is straightforward to test.
- **Boring tech in scope.** Sitemap protocol is stable; we don't need innovation here.
- **Library doesn't conflict with rate limiting.** It's just an XML-response helper at the SvelteKit layer; rate limiting lives at the Django endpoint where it belongs.

### Response caching

The SvelteKit `/sitemap.xml` response sets `Cache-Control: public, max-age=3600, s-maxage=3600` so crawler probes don't re-render XML in Node every hit. The Django `/api/sitemap/` response sets the same TTL, so the staleness budget is bounded by the longer-lived layer. The two cache lifetimes don't compose multiplicatively — both are wall-clock from the moment each layer warms — but they make repeated crawler hits cheap regardless of layer.

### Gate on `ALLOW_SEARCH_ENGINE_INDEXING`

Call `isDeploymentSearchEngineIndexable()` from `frontend/src/lib/is-deployment-search-engine-indexable.server.ts`. When it returns false, return `404 Not Found` for `/sitemap.xml` — a non-indexable deploy has nothing to advertise. The robots.txt-side `Disallow: /` already keeps crawlers out; the 404 is defense in depth.

## 4. Add `Sitemap:` line to robots.txt

The existing `robots.txt` endpoint at `frontend/src/routes/robots.txt/+server.ts` does not yet emit a `Sitemap:` line. Once `/sitemap.xml` exists, append it to the indexable-mode body:

```text
Sitemap: ${SITE_ORIGIN}/sitemap.xml
```

One-line additive change. Update the existing robots vitest to assert the line is present iff `ALLOW_SEARCH_ENGINE_INDEXING == "true"`.

## 5. What goes in the sitemap

**In:**

- `/`, `/about`, `/about/people`, `/legal/privacy`, `/legal/terms`, `/legal/licensing` — `lastmod` from the static manifest (last git-commit on the route's source file).
- All catalog detail pages with their `_sitemap_lastmod` as `lastmod`, plus per-entity `/edit-history` and `/sources` URLs (every `catalog-detail` / `catalog-edit-history` / `catalog-sources` route classifies as indexable), except:
  - **Single-Model Titles** — when a Title has exactly one Model, include the Title route and **exclude** the Model route. The UI collapses single-Model Titles into the Model page (per `docs/SingleModelTitles.md`), but the Title slug is the canonical URL; indexing both would split signals and create duplicate-content noise. Enforced via `MachineModel.sitemap_queryset()`. The collapsed Model's edits still bump the Title's `lastmod` because `Title.sitemap_queryset()` aggregates `Max(machine_models__updated_at)`.

**Out:**

- `/style-lab`, `/api-docs`, `/search`, `/kiosk`, `/_sentry_test`, `/auth/error`
- Catalog listing pages (`/titles`, `/models`, `/manufacturers`, etc.) — non-indexable today per [`RouteWalking.md`](RouteWalking.md) (low search value + CSR-only); discoverability is covered by the catalog detail entries above. Revisit when listing SSR lands.
- Catalog `/new` and `/delete` subroutes — non-indexable.
- Anything auth-gated — recognized by `requireCapability` in the layout chain; non-indexable routes are excluded by `isSearchEngineIndexable(routeId)`; never enumerated by hand
- Models whose parent Title has exactly one Model (see above)

## 6. Prerequisite — `SITE_ORIGIN` build + deploy checks (separate PR)

`SITE_ORIGIN` is consumed by the sitemap (URLs, robots.txt `Sitemap:` line) and by the prerendered meta tags that already exist. Today `frontend/svelte.config.js:40` falls back to `'http://localhost:5173'` when unset — fine for `make dev`, but a production build silently bakes `localhost` URLs into prerendered HTML.

The fix (build-phase refusal gate when `RAILWAY_GIT_COMMIT_SHA` is set but `SITE_ORIGIN` is empty/malformed, plus a deploy check in `apps/core/checks.py` with new error ids `core.E303` / `core.E304`, plus a `Dockerfile` `ARG` for `SITE_ORIGIN`) is **pre-existing env hygiene that the sitemap surfaces, not sitemap work**. Land it in its own PR ahead of this one so the sitemap PR stays focused. The sitemap depends on the build/deploy gates being in place — but bundling them couples sitemap review to deploy-check review and grows the diff surface.

## 7. Tests

- **Backend (pytest):**
  - `apps/core/tests/test_sitemap.py` — `all_sitemap_feeds()` walks every concrete `LinkableModel` subclass, builds one feed per kind, entries match `(slug, lastmod)` shape, ordering is by slug, `max_lastmod` matches the newest entry. Parameterized over every concrete `LinkableModel` so a new entity type fires the test and gets reviewed intentionally (per [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md#rules-of-thumb): "Parity tests pin derived sets"). Also asserts a model overriding `sitemap_queryset()` to return `.none()` produces no feed entry (opt-out path).
  - `apps/catalog/tests/test_title_sitemap_lastmod.py` — `Title.sitemap_queryset()` annotates `_sitemap_lastmod = max(Title.updated_at, max(its MachineModels' updated_at))` across: (a) Title-only edit, (b) MachineModel-only edit, (c) both edited, (d) single-Model Title with Model edit, (e) Title with zero MachineModels (annotation falls back to `Title.updated_at` via `Coalesce`).
  - `apps/core/tests/test_sitemap_api.py` — endpoint returns 200 with the expected shape, rate-limit returns 429 with `Retry-After` past the threshold (10/min).
  - `apps/catalog/tests/test_machine_model_sitemap_queryset.py` — the single-Model-Title exclusion: `MachineModel.sitemap_queryset()` includes Models whose parent Title has ≥2 `machine_models` and excludes the rest.
  - `apps/catalog/tests/test_location_sitemap.py` — Location's `public_id_field = "location_path"` produces multi-segment slugs (e.g. `"a/b/c"`) in the feed without further encoding.
  - **Schema validation** — fetch `/sitemap.xml` via an in-process test client and validate the response against the sitemaps.org XSD using `lxml.etree.XMLSchema` (loaded once at module import — no subprocess, no system-binary dependency in CI). XSD is bundled under `backend/tests/fixtures/sitemap.xsd` so the test is offline.
- **Frontend (vitest):**
  - `sitemap.xml/+server.ts` builds `paramValues` correctly from a mocked `/api/sitemap/` response: a single backend feed for `kind: "title"` lands under every indexable SvelteKit route ID for `title` (detail + `/edit-history` + `/sources` today) with the same slug list and `lastmod`.
  - `sitemap.xml/+server.ts` substitutes a path-shaped slug (`"a/b/c"`) into a `[...path]` rest route correctly — `/locations/a/b/c`, not `/locations/a%2Fb%2Fc`. Run the rendered XML through XSD validation in the same test so encoding regressions surface as schema errors.
  - `sitemap.xml/+server.ts` merges static-manifest entries into `additionalPaths` with their build-time `lastmod`.
  - `sitemap.xml/+server.ts` returns 404 when `ALLOW_SEARCH_ENGINE_INDEXING != "true"`.
  - `sitemap.xml/+server.ts` sets `Cache-Control: public, max-age=3600, s-maxage=3600` on 200 responses.
  - `sitemap.xml/+server.ts` does NOT throw when the route classifier would reject an unclassified route — the endpoint logs and skips, so one stray route can't 500 the whole sitemap.
  - `routeIdToRegex` helper: unit tests for `[slug]`, `[...path]`, `[[optional]]`, `(group)` shapes; snapshot test against the current `allRoutes()` set asserting the regex set excludes exactly the non-indexable routes.
  - Static-`lastmod` manifest build step: given a fixture route set, emits the expected `{route: lastmod}` shape; falls back to the build-time clock with a warning when `git log` returns nothing or all files share the shallow-tip date (does NOT fail the build).
  - Legal page components render the "Last updated" footer from the same manifest the sitemap reads.
  - Existing robots.txt test extended to assert the `Sitemap:` line is present iff `ALLOW_SEARCH_ENGINE_INDEXING == "true"`.

## 8. Implementation order

Prerequisite (separate PR, per §6): `SITE_ORIGIN` build-phase guard, deploy check, and `Dockerfile` `ARG`.

1. Add `LinkableModel.sitemap_queryset()` classmethod with its default (every row, `_sitemap_lastmod = updated_at`, `.only()`, `.order_by()`).
2. Override `MachineModel.sitemap_queryset()` for the single-Model-Title exclusion (via `Count("title__machine_models")`) and `Title.sitemap_queryset()` for the `Greatest(updated_at, Coalesce(Max("machine_models__updated_at"), updated_at))` aggregation. Tests for both, including the zero-MachineModels case.
3. `apps/core/sitemap.py` — `SitemapEntry`, `SitemapFeed`, `all_sitemap_feeds()` (filtering None lastmods and skipping empty feeds). Parameterized parity test over every concrete `LinkableModel`, including an opt-out (`sitemap_queryset()` returns `.none()`) assertion.
4. `apps/core/sitemap_api.py` — single endpoint at `/api/sitemap/`, IP rate limiting (10/min) via `apps.core.rate_limits`, `Cache-Control` headers. Tests for 200 / 429 paths.
5. `make api-gen`.
6. Build-time static-`lastmod` manifest: Vite plugin / build script that walks the static-route source files, shells `git log -1 --format=%cI`, writes `frontend/src/lib/static-lastmod.generated.json`. Add to `.gitignore`. Soft-fail to the build-time clock with a warning when git history is missing or shallow (per §2). Tests for both the happy path and the fallback path.
7. Wire legal page components to read from the manifest for their "Last updated" footers.
8. `pnpm add super-sitemap@~1.0.12`.
9. `frontend/src/routes/sitemap.xml/+server.ts` — wire super-sitemap to `/api/sitemap/` for catalog URLs and to the static manifest for static URLs, using `catalogRoutesByEntity()` + `isSearchEngineIndexable()` to expand to route IDs. Wrap classifier calls in try/catch (per §3 "Tolerating unclassified routes"). Set `Cache-Control` on responses. Gate on `ALLOW_SEARCH_ENGINE_INDEXING` via `isDeploymentSearchEngineIndexable()`.
10. Implement and unit-test the `routeIdToRegex` helper (per §3).
11. Verify rest-param handling against super-sitemap with a Location fixture (per §3); if the library URL-encodes slashes, fall back to `e.slug.split("/")` for rest-shaped routes.
12. Append the `Sitemap:` line to `frontend/src/routes/robots.txt/+server.ts` (indexable-mode only). Extend the existing robots test.
13. Add the XSD validation tests (backend pytest + frontend vitest, both using the bundled sitemap XSD).
14. Verify locally: `curl localhost:5173/sitemap.xml`; spot-check with `xmllint --noout --schema` for ad-hoc inspection (CI uses lxml / a Node XSD validator).

### Deployment routing

No Caddyfile changes needed. The current `@django` matcher in `Caddyfile` only catches `/api`, `/djadmin`, `/media`, `/static`, so `/sitemap.xml` routes to SvelteKit (Node, port 3000) by default.

## Considered alternatives

- **Per-entity `updated_at` as the only `lastmod` source.** First-draft shape. Rejected: the Title page renders its Models' content; a Model edit changes what the Title page displays but doesn't bump `Title.updated_at`. Crawlers would re-fetch late or not at all on Model edits. The one-line `Title.sitemap_queryset()` override fixes this without introducing a framework.
- **Auto-derive `lastmod` from Django relationships.** Considered. Rejected: walking all FK/M2M relationships over-includes (provenance ChangeSets, audit rows, denormalization caches aren't page content), and walking only `LinkableModel`-targeted relationships under-includes (non-LinkableModel entities like aliases or credit lines often drive page content precisely because they don't have their own page). The actual page-composition graph isn't well-described by either filter, so a "smart" walker would be wrong in both directions. Catalog pages overwhelmingly render their own record's fields; Title is the one real exception. That's a one-override situation, not a framework.
- **Touch parent `updated_at` at write time via the ChangeSet pipeline.** Considered. Rejected: pushes the dependency graph into the write path with spooky action at a distance, and the only real dependency in the catalog today is Title→Models. One read-time override is cheaper, more localized, and visible in the model file rather than as a claim-execution side effect.
- **Per-page-endpoint bulk-`lastmod` functions co-located with `/api/pages/...` endpoints.** Considered. Rejected: more general than the catalog actually needs. Page endpoints today compose mostly from a single root record; only Title meaningfully aggregates. Building a "every page endpoint declares its own lastmod query" framework is overhead for the 95% case where `lastmod = root.updated_at`. Revisit if other page endpoints start aggregating across catalog entities.
- **`<lastmod>` only on sitemap-index entries (no per-URL `<lastmod>`).** Considered. Rejected: per-URL `lastmod` is the main signal Google uses to prioritize re-crawls. Coarse-grained index-level `lastmod` wouldn't help discover which specific entities changed.
- **Frontmatter / manual "last updated" constants in static page files.** Considered for static pages. Rejected: forgettable and drifts from reality. `git log` on the source file is automatic, and the legal-page footer reading from the same manifest doubles as informal verification — if the date looks wrong, a human will notice.
- **Hand-rolled XML rendering.** Considered to avoid a third-party dependency. Rejected: the library's value isn't lines saved (it's only ~80), it's that XML correctness (escaping, `lastmod` formatting, sitemap-index splitting) becomes the library's problem to debug rather than ours.
- **New `apps/sitemap/` Django app.** Considered. Rejected per `docs/AppBoundaries.md`: a new app should own a distinct concept, and sitemap feeds are thin projections over existing catalog data with no domain of their own.
- **Hand-rolled sitemap index from day one.** Considered for "future-proofing" against the 50k-URLs-per-file cap. Rejected: super-sitemap auto-flips from `<urlset>` to `<sitemapindex>` when needed, the catalog is years from 50k.
- **Per-route hardcoded sitemap config on the frontend.** Rejected: hardcoding means adding a new entity type requires touching the frontend.
- **Separate `canonical_url_queryset()` + `sitemap_queryset()` classmethods.** First-draft shape. Rejected: the two-method split was justified by speculation that a future canonical-link tag or schema.org `mainEntityOfPage` would read the same predicate, but neither consumer exists today. Per CLAUDE.md ("don't design for hypothetical future requirements"), one method covers the one current consumer. The split also actively caused a re-annotation footgun (a `Title.sitemap_queryset()` override calling `super()` and re-annotating `_sitemap_lastmod` doesn't reliably win across Django versions). Collapsing to one method makes the override path direct: rebuild from `cls.objects`, no super-call gotcha. If a second consumer arrives, split then.
- **Failing the build when `git log` returns nothing for a static-route source file.** First-draft shape. Rejected: shallow-clone build environments (Railway/Nixpacks default to depth-1) silently make every page's `lastmod` the shallow-tip commit date — fail-the-build behavior would either never trigger (because there IS a date, just the wrong one) or trigger spuriously on environments we don't control. `lastmod` is a crawler hint, not data anyone makes decisions on; trading a benign rare drift for a sharp build failure isn't worth it. Soft-fail to the build-time clock with a warning instead (§2 "Soft-fail behavior").
- **120/min IP rate limit on `/api/sitemap/`.** First-draft shape. Rejected as over-sized: real crawlers fetch `/sitemap.xml` ~daily, and the SvelteKit endpoint is the only other consumer. 10/min still defends against abuse, stays decorative for legitimate traffic, and matches the existing pattern for public IP-keyed endpoints.
- **Per-model `SitemapFeed` classes registered from `AppConfig.ready()`.** First-draft shape. Rejected per [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md): it's a hand-maintained list that enumerates the same model set `LinkableModel.__subclasses__()` already knows, the per-model classes differ only in model import + queryset + ordering, and adding a new catalog model would require a new feed class. The `LinkableModel` walk delivers the same boundary respect (core doesn't import catalog) with zero per-model declarations.
- **Two endpoints (`GET /api/sitemap/` + `GET /api/sitemap/{kind}/`).** First-draft shape. Rejected: the split only existed so the frontend could "discover" feeds before fetching them, but it always fetches all of them anyway — 1+N HTTP calls per render with no semantic gain. super-sitemap fails the whole render if any `paramValues` callback throws, so eliminating the per-feed fetches also eliminates that partial-failure mode.
- **`route_pattern` emitted from Python.** First-draft shape. Rejected: the frontend already maps `entity_type` → SvelteKit route IDs via `catalogRoutesByEntity()`. Emitting `'/titles/[slug]'` from Python would duplicate that map and require Python to know about SvelteKit's `[...path]` rest-param shape.

## Open questions

1. **Production hostname** — confirm `SITE_ORIGIN` in production (presumably `https://flipcommons.org`?) so the `Sitemap:` line is right. Lives in the prerequisite PR (§6), but flagged here so it doesn't get lost.
2. **super-sitemap rest-param behavior** — verify against the library whether passing `values: ["a/b/c"]` to a `[...path]` route emits `/locations/a/b/c` or `/locations/a%2Fb%2Fc`. If the latter, the Location wiring needs a per-route shape branch (see §3 "Rest-param routes").

## Resolved

- **People pages** (`/people/[slug]`) — catalog persons (designers, artists, etc.). Indexable; included in the sitemap.
- **Soft-delete / draft state** — none exist today. No lifecycle-based filter needed in the sitemap feeds; revisit if/when drafts or soft-delete are introduced.
- **Single-Model Titles** — include the Title route; exclude the Model route. Title slug is canonical; indexing both would split signals. The collapsed Model's edits still bump the Title's `lastmod` via `Title.sitemap_queryset()`'s `Max(machine_models__updated_at)`.
- **`lastmod` source for catalog pages** — default to the record's own `updated_at`; widen via a `sitemap_queryset()` override only where the page renders content from other catalog entities (today: Title's Model list). No relationship walker; no write-time `updated_at` touching.
- **One method vs. two on `LinkableModel`** — one (`sitemap_queryset()`), covering both narrowing and lastmod widening. `canonical_url_queryset()` was considered for hypothetical future canonical-link / schema.org consumers and rejected as speculative future-proofing (see Considered alternatives).
- **Static-page `lastmod` from `git log` failure mode** — soft-fail with a warning, never fail the build. Trades benign rare drift on rarely-changing static pages for build-environment robustness. See §2 "Soft-fail behavior".
- **`SITE_ORIGIN` build + deploy checks** — pre-existing env hygiene the sitemap surfaces; lands in its own PR ahead of the sitemap (see §6).
- **`lastmod` source for static pages** — build-time manifest from `git log -1 --format=%cI` on the route's source `+page.svelte`. Same manifest backs legal-page "Last updated" footers so the user-visible date and the sitemap `lastmod` cannot disagree.
- **`lastmod` failure-mode tradeoff** — accept under-reporting on transitive edits (e.g., a Manufacturer rename not bumping every Title listing it). Cheaper than maintaining a relationship walker, and Google won't re-crawl every Title for a Manufacturer typo anyway.
