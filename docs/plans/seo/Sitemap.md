# sitemap.xml

This is the plan for introducing `sitemap.xml` to the project.

## Goals

- Let search engines know what is available to be indexed.
- Give search engines accurate `<lastmod>` per catalog page so they can prioritize re-crawls.

See [`SearchEngines.md`](SearchEngines.md) for how this fits with `robots.txt` and the per-page `noindex` meta.

## Overview

> **Update (2026-09):** `/edit-history` and `/sources` are no longer indexable and no longer appear in the sitemap. §1's premise that "every catalog detail page, listing page, edit-history page and sources page is indexable" now holds for detail and listing pages only. **Why:** index hygiene. The two subroutes carried 33,842 of the sitemap's 45,810 URLs (74%) while contributing no content of their own — each re-renders the parent entity's description in raw claim form with wikilinks unrendered in the visible text (`[[person:raymond-t-moloney]]`), under a `<meta name="description">` byte-identical to the parent's and a self-referencing canonical, so all three URLs offer Google the same prose and nothing consolidates them. They are provenance appendices to the detail page, not pages anyone searches for. Wikipedia is the precedent: articles are indexed, `action=history` is not. `noindex` states the intent directly — these pages should never appear in search results. A cross-URL `rel="canonical"` would claim the subroute is a duplicate of the detail page, which an edit-history diff is not, and Google treats the tag as an overridable hint rather than a directive, so none is added. Shrinking the sitemap also shifts Googlebot's crawl mix (two days of 2026-09 logs showed 201 requests to these pages against 144 to content pages), but that is a side effect — noindexed pages are still crawled, and the largest bucket in those logs was JS chunks, which this change doesn't touch. **Consequence for this plan:** `non_canonical_detail_slugs()` and the wire's `detail_excluded_slugs` are removed. Their sole purpose was to drop a single-Model-Title member's detail URL while keeping its `/edit-history` and `/sources`; with those no longer indexable the row contributes no sitemap URLs at all, so `MachineModel.sitemap_queryset()` excludes it outright and the two-method split below collapses back to one. Note the collapsed Model's `/edit-history` and `/sources` URLs still render (only the detail route 301s to the Title); they go from canonical sitemap entries to noindexed pages. The note in "Considered alternatives" that a future `<link rel="canonical">` would also read `non_canonical_detail_slugs()` is obsolete — `/models/[slug]` already 301s to the Title, and [`CanonicalUrl.md`](CanonicalUrl.md) records that canonical tags are not load-bearing there.

> **Update (2026-08):** the shipped endpoint no longer uses super-sitemap — it emits the XML directly (see §3 note). The rest of this plan (the Django feed, `SitemappedModel`, `STATIC_LASTMOD`, `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE`) still describes the shipped design.

The sitemap is a SvelteKit `+server.ts` endpoint that renders `/sitemap.xml` via [`super-sitemap`](https://github.com/jasongitmail/super-sitemap). Per-URL `<lastmod>` comes from two sources:

- **Dynamic catalog pages**: a single Django endpoint derives feeds from `SitemappedModel` subclasses, returning per-instance `(slug, lastmod)` plus an optional per-kind set of slugs whose `catalog-detail` URL is non-canonical. The default `lastmod` is the record's own `updated_at` filtered to `.active()`; one override (`Title`) widens lastmod to include its Models' `updated_at`. One canonical-URL override (`MachineModel`) marks single-Model-Title members as non-canonical at the detail route.
- **Static pages** (`/`, `/about`, `/legal/*`): a small hand-maintained map of route ID → date-only `YYYY-MM-DD` (sitemaps.org accepts plain dates for `<lastmod>` — no need to type a fake time). The legal pages already render a "Last updated: …" line under the `<h1>` via the existing `<LastUpdated />` component; the sitemap reads the same constant so the user-visible date and the crawler-visible `<lastmod>` cannot disagree. When a static page's content changes, the author bumps the date in the same diff — same edit, same reviewer.
- **Non-catalog dynamic routes** (today only `/manufacturers/[slug]/systems`): a tiny `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE` map names the parent entity whose slugs feed each such route. One entry today, growable.

Appends a `Sitemap:` line to the existing `frontend/src/routes/robots.txt/+server.ts`.

## 1. Backend — derive feeds from `SitemappedModel`

Every catalog detail page and listing page is indexable; edit-history, sources, new, delete and edit pages are not (per [`NoindexMeta.md`](NoindexMeta.md)). That rule applies uniformly to every sitemapped entity, so the sitemap doesn't need any per-model declaration — it walks the `SitemappedModel` registry (the same `apps.get_models()` + `issubclass` walk [`apps/core/entity_types.py`](../../../backend/apps/core/entity_types.py) already does) and reads metadata the model already carries.

`SitemappedModel(LinkableModel, LastUpdatedModel)` is the abstract base for "appears in the sitemap": it composes the two prerequisites — a canonical URL (`LinkableModel`) and a freshness value (`LastUpdatedModel`). A `LinkableModel` that is _not_ a `SitemappedModel` (a future linkable-but-virtual entity) is simply absent from the walk rather than crashing on a missing `sitemap_queryset()`.

This is the [`_meta` walk](../model_driven_metadata/ModelDrivenMetadata.md#pattern-_meta-walk) + [base class / mixin](../model_driven_metadata/ModelDrivenMetadata.md#pattern-base-class--mixin) shape from [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md). No `apps/catalog/sitemap_feeds.py`, no `register_sitemap_feed()` calls, no `AppConfig.ready()` hook. Adding a new `SitemappedModel` catalog subclass lights up automatically.

### What the model already provides

| Feed field              | Source                                                      |
| ----------------------- | ----------------------------------------------------------- |
| `kind`                  | `entity_type` (`LinkableModel`)                             |
| slug field              | `public_id_field` (defaults to `"slug"`)                    |
| `lastmod`               | `_last_modified` annotation from `sitemap_queryset()`       |
| `detail_excluded_slugs` | `non_canonical_detail_slugs()` classmethod (default: empty) |

The `_last_modified` annotation is sourced from `LastUpdatedModel.lastmod_expression()` (default `F("updated_at")`) — the one freshness definition shared with JSON-LD's `dateModified` (see [JsonLdAndFriends.md](JsonLdAndFriends.md)).

No `route_pattern` is emitted — the frontend already maps `entity_type` → SvelteKit route IDs via `catalogRoutesByEntity()` ([`route-metadata.server.ts`](../../../frontend/src/lib/route-metadata.server.ts)), so emitting SvelteKit-shaped patterns from Python would just duplicate that map.

### Per-model overrides — two methods, by category

Two classmethods on `SitemappedModel`, each covering a distinct concern:

- `sitemap_queryset()` — which **active** rows belong in the sitemap, with their `_last_modified` (annotated from `lastmod_expression()`). Used uniformly across `catalog-detail`, `catalog-edit-history`, and `catalog-sources` routes.
- `non_canonical_detail_slugs()` — within those rows, the subset whose `catalog-detail` URL is non-canonical (the canonical URL lives on a different entity). Applies only to the detail route; `/edit-history` and `/sources` still emit.

Freshness itself is a third, orthogonal concern that lives on `LastUpdatedModel`: `lastmod_expression()` (the queryset expression the sitemap annotates, default `F("updated_at")`) and `last_modified` (the per-instance value). A `lastmod`-widening entity overrides `lastmod_expression()` only — not the whole `sitemap_queryset()`.

The split exists because single-Model-Title MachineModels have a non-canonical detail page (the Title is canonical) but their `/edit-history` and `/sources` are independently canonical per [`SingleModelTitles.md`](../../SingleModelTitles.md). One method that excludes the row entirely would drop those ancillary URLs too. See [Considered alternatives](#considered-alternatives) for the history of this split.

Today every concrete `SitemappedModel` subclass also inherits `LifecycleStatusModel` (via [`CatalogModel`](../../../backend/apps/catalog/models/base.py), which combines both) and `TimeStampedModel` (giving it `updated_at`). The defaults below rely on both — `.active()` and `lastmod_expression()`'s `F("updated_at")`. A parity test (see §7) pins the inheritance so a future non-lifecycle `SitemappedModel` fails CI rather than crashing at sitemap render.

```python
# apps/core/models/mixins.py

class LastUpdatedModel(models.Model):
    """Freshness concept — the one definition shared by sitemap + dateModified."""

    @classmethod
    def lastmod_expression(cls) -> Combinable:
        return F("updated_at")  # Title overrides to aggregate child Models

    @property
    def last_modified(self) -> datetime:
        # Reads the `_last_modified` annotation when present, else updated_at.
        ...

    class Meta:
        abstract = True


class SitemappedModel(LinkableModel, LastUpdatedModel):
    @classmethod
    def sitemap_queryset(cls) -> QuerySet[Self]:
        """Active rows to include in the sitemap, annotated with `_last_modified`.

        Default: `.active()` rows with `_last_modified` from
        `lastmod_expression()` (`updated_at` unless a subclass widens it).
        Override `lastmod_expression()` to widen `lastmod`; override this
        method only to narrow membership, or return `cls.objects.none()` to
        opt out (e.g. a future through-table entity with no detail page). A
        subclass that doesn't also inherit `LifecycleStatusModel` +
        `TimeStampedModel` MUST override this method; the parity test in
        `apps/core/tests/test_sitemapped_model_lifecycle_parity.py` catches that
        contract at CI time.
        """
        return (
            cls.objects.active()
            .annotate(_last_modified=cls.lastmod_expression())
            .only(cls.public_id_field, "updated_at")
            .order_by(cls.public_id_field)
        )

    @classmethod
    def non_canonical_detail_slugs(cls) -> Iterable[str]:
        """Slugs whose `catalog-detail` URL is non-canonical.

        Default: empty. Override when the detail page collapses to a different
        entity's page in the UI (canonical URL lives elsewhere) — the row stays
        in `sitemap_queryset()` so `/edit-history` and `/sources` still emit,
        but its detail URL is omitted from the sitemap.

        Returned slugs must already be members of `sitemap_queryset()`; slugs
        outside that set are ignored (defensive — they wouldn't appear anyway).
        """
        return ()
```

The overrides today:

```python
# apps/catalog/models/machine_model.py
class MachineModel(CatalogModel, ...):
    @classmethod
    def non_canonical_detail_slugs(cls):
        # Single-Model-Title rule: when a Title has exactly one active Model,
        # the UI collapses to the Model page (per docs/SingleModelTitles.md),
        # but the Title slug is the canonical URL for the detail page. The
        # Model's /edit-history and /sources are independently canonical
        # (each lists that Model's history / sources, not the Title's), so
        # they stay in the sitemap via the default `sitemap_queryset()`.
        return (
            cls.objects.active()
            .annotate(_sibling_count=Count(
                "title__machine_models",
                filter=active_status_q("title__machine_models"),
            ))
            .filter(_sibling_count=1)
            .values_list(cls.public_id_field, flat=True)
        )
```

```python
# apps/catalog/models/title.py
class Title(CatalogModel, ...):
    @classmethod
    def lastmod_expression(cls):
        # Title is the only catalog page whose primary content aggregates other
        # catalog entities (the Model list, plus — for single-Model Titles — the
        # collapsed Model's content). Bump lastmod when any Model changes. This
        # one expression feeds both the sitemap `<lastmod>` and the detail
        # response's `last_modified` (both annotate via it), so they can't
        # diverge. `Coalesce` defends against `Max(...) = NULL` for Titles with
        # no Models on non-Postgres backends — Postgres' GREATEST already
        # ignores NULLs, but the explicit fallback is portable.
        return Greatest(
            F("updated_at"),
            Coalesce(
                Max("machine_models__updated_at"),
                F("updated_at"),
            ),
        )
```

```python
# apps/catalog/models/location.py
class Location(CatalogModel, ...):
    @classmethod
    def sitemap_queryset(cls):
        # Membership-narrowing override (the documented "narrow membership"
        # case): only locations with ≥1 manufacturer at or below them. A
        # location page's primary content is its aggregated manufacturer grid
        # (manufacturers propagate up the ancestor chain), so a
        # zero-manufacturer location renders an empty page that search
        # engines cluster as duplicate content ("Duplicate without
        # user-selected canonical" in Search Console). Excluded rows drop ALL
        # their URLs (detail, /edit-history, /sources) — unlike
        # `non_canonical_detail_slugs()`, which is for canonical-URL reasons
        # and keeps the ancillary pages. Implemented as an `Exists` over
        # CorporateEntityLocation with a `location_path` prefix match; see
        # the model for the shipped queryset.
        ...
```

Note `machine_models` (not `models`) — that's the `related_name` on `MachineModel.title` and `MachineModel.title` is the only FK from `MachineModel` to `Title`. `active_status_q("relation")` (from `apps/core/models/mixins.py`) builds the active-or-null `Q` filter for child rows reached through a relation, mirroring `LifecycleQuerySet.active()`'s null-inclusive shape for ingest compatibility. Read directly off `type[LinkableModel]` — no `getattr` fallback (per the [field-on-model antipattern](../model_driven_metadata/ModelDrivenMetadata.md#antipattern-field-on-model)).

### Derivation + single API endpoint

`apps/core/sitemap.py`:

```python
class SitemapEntry(NamedTuple):
    slug: str
    lastmod: datetime

class SitemapFeed(NamedTuple):
    kind: str
    entries: list[SitemapEntry]
    detail_excluded_slugs: frozenset[str]
    max_lastmod: datetime | None

def all_sitemap_feeds() -> list[SitemapFeed]:
    apps.check_apps_ready()
    feeds: list[SitemapFeed] = []
    for model in apps.get_models():
        if not issubclass(model, SitemappedModel) or model._meta.abstract:
            continue
        slug_field = model.public_id_field
        entries = [
            SitemapEntry(getattr(o, slug_field), o._last_modified)
            for o in model.sitemap_queryset().iterator()
            if o._last_modified is not None
        ]
        if not entries:
            continue
        feeds.append(
            SitemapFeed(
                kind=model.entity_type,
                entries=entries,
                detail_excluded_slugs=frozenset(model.non_canonical_detail_slugs()),
                max_lastmod=max(e.lastmod for e in entries),
            )
        )
    return feeds
```

The `is not None` filter and the empty-feed skip together mean `max_lastmod` is always a real datetime — neither `max([])` nor `max([None, ...])` can raise. `detail_excluded_slugs` is a `frozenset` to make the wire shape order-independent and to give the frontend O(1) lookups.

One endpoint returns everything in one shot — no 1+N fan-out, no partial-failure mode:

```python
# apps/core/api/sitemap.py
SITEMAP_CACHE_KEY = "core:sitemap:feeds"
SITEMAP_CACHE_TTL = 3600  # seconds

router = Router()

@router.get("/sitemap/", response=SitemapResponseSchema)
def get_sitemap(request) -> SitemapResponseSchema:
    feeds = cache.get(SITEMAP_CACHE_KEY)
    if feeds is None:
        feeds = all_sitemap_feeds()
        cache.set(SITEMAP_CACHE_KEY, feeds, SITEMAP_CACHE_TTL)
    return SitemapResponseSchema(feeds=feeds)
```

Wired the same way every other Ninja router in the repo is wired: the router lives in `apps/core/api/sitemap.py` and is exposed by `apps/core/api/__init__.py` as `routers = [("", router)]` (create the `api/` package if it doesn't exist yet). `config/api.py` auto-discovers via `apps.get_app_configs()` looking for `<app>.api.routers` — no extra registration. Typed schemas (`SitemapEntrySchema`, `SitemapFeedSchema`, `SitemapResponseSchema`) live in `apps/core/api/sitemap_schemas.py`. Response sets `Cache-Control: public, max-age=3600`. Run `make codegen` after.

No rate limiter. The SvelteKit `/sitemap[[page=integer]].xml` endpoint calls this server-side via `createServerClient(...)` (per [`Svelte.md`](../../Svelte.md)), so from Django's perspective every public hit on the sitemap arrives from the Node container's single IP. An IP-keyed limiter would bucket all crawler traffic — including post-deploy bursts where multiple bots simultaneously cache-miss — under one key and 429 the whole sitemap render. The shared Django cache (`django.core.cache`, configured as `FileBasedCache` at `BASE_DIR/cache` in [`config/settings.py`](../../../backend/config/settings.py); same pattern as [`apps/catalog/cache.py`](../../../backend/apps/catalog/cache.py)) collapses the workload to one full materialization per hour across all worker processes, which is the actual cost ceiling we care about.

**Wire-shape note.** `SitemapEntrySchema.lastmod` is typed `datetime` in Python; Django Ninja serializes it as an ISO 8601 string in JSON, and the generated TypeScript type is `string`. The SvelteKit consumer passes the string straight through to super-sitemap (which expects ISO strings) — no parsing on either side.

**Payload size note.** `all_sitemap_feeds()` materializes every entry in memory before responding. Today (~10k Titles, ~10k Models, 20 LinkableModels) that's small. At catalog scale past ~50k entries per kind, this needs pagination or streaming — same cliff that triggers super-sitemap's `<sitemapindex>` splitting on the frontend side (which is why the SvelteKit route is named `sitemap[[page=integer]].xml` from day one; see §3).

### Why this shape

- **One override per wrinkle, no relationship walker.** Catalog pages overwhelmingly render their own record's content. The one lastmod-aggregation exception (Title) gets a one-line `lastmod_expression()` override; the one canonical-URL exception (MachineModel) gets a `non_canonical_detail_slugs()` override; everything else inherits the defaults. No auto-derivation from Django relationships — walking all FK/M2M relationships over-includes (provenance ChangeSets, audit rows, denormalization caches aren't page content), and walking only `LinkableModel`-targeted relationships under-includes (non-LinkableModel entities like aliases or credit lines often drive page content precisely because they don't have their own page). A "smart" walker would be wrong in both directions; the honest answer is explicit overrides for the entities that actually aggregate or collapse.
- **Two methods, split by category.** Membership-and-lastmod (`sitemap_queryset()`) and canonical-URL-at-detail (`non_canonical_detail_slugs()`) are different questions because `/edit-history` and `/sources` are independently canonical even when the detail page collapses. A single-method shape was the first draft and was reopened (see Considered alternatives) once the sitemap surfaced as the canonical-URL consumer. A future `<link rel="canonical">` tag on the rendered HTML would read `non_canonical_detail_slugs()` too.
- **Sitemap inclusion is implied by being a `SitemappedModel`** that has a SvelteKit route for its `entity_type`. A `SitemappedModel` without a matching route (today: none; tomorrow potentially through-tables like `MachineModelTag` or `MachineModelRewardType`) emits a Django feed that the frontend silently drops via `catalogRoutesByEntity().get(kind) === undefined`. To explicitly opt out, override `sitemap_queryset()` to return `cls.objects.none()`; a `LinkableModel` that should never appear simply isn't a `SitemappedModel` at all.
- **Soft-deleted rows excluded by default.** `sitemap_queryset()` calls `.active()` directly. Every concrete `LinkableModel` today inherits `LifecycleStatusModel` via `CatalogModel`, so `status='deleted'` rows never appear in the sitemap. `MachineModel.non_canonical_detail_slugs()` filters its sibling count with `active_status_q("title__machine_models")` so single-Model detection counts only active siblings. If `status='draft'` or other lifecycle states are added later, narrow `.active()` at the `LifecycleQuerySet` level — the sitemap inherits the change automatically.
- **No fan-out.** One HTTP call from SvelteKit → Django. super-sitemap fails the whole render if a `paramValues` callback throws, so eliminating the per-feed fetches eliminates that failure mode.
- **Public reads, no auth gate.** Non-mutating, contains only data already on the indexable detail pages.
- **Cached for 1 hour in the shared file-based cache**, not rate-limited. The endpoint's only public caller is the SvelteKit `/sitemap[[page=integer]].xml` server-side fetch, which arrives from the Node container's single IP — an IP-keyed limiter would 429 the entire sitemap render on post-deploy / post-restart cache-miss bursts. The file-based cache (configured globally in [`config/settings.py`](../../../backend/config/settings.py)) collapses the cost ceiling to one materialization per hour across all Gunicorn workers; that's the actual workload to bound.

## 2. Static pages — hand-maintained `lastmod` constants

Static routes (`/`, `/about`, `/about/people`, `/legal/privacy`, `/legal/terms`, `/legal/licensing`) live as committed Svelte files. There are six of them today, they change roughly 1–2× per year, and the legal pages already display a "Last updated" line under their `<h1>` via the existing [`<LastUpdated />`](../../../frontend/src/lib/components/LastUpdated.svelte) component. The same date is what the sitemap should emit as `<lastmod>`.

One hand-maintained map, two readers:

```ts
// frontend/src/lib/static-lastmod.ts
import type { RouteId } from "$app/types";

/**
 * Hand-maintained `YYYY-MM-DD` dates for static pages. Date-only is a valid
 * `<lastmod>` per sitemaps.org — no fake time component. When the content of
 * one of these pages changes substantively, bump the date in the same diff.
 * The legal pages display the corresponding date under their `<h1>` via
 * `<LastUpdated />`, so a forgotten bump is visible in human review.
 *
 * The `satisfies` clause forces every entry to be a known route ID and every
 * indexable static route to have an entry — `make quality` / `svelte-check`
 * catches typos and missing routes at build time.
 */
export const STATIC_LASTMOD = {
  "/": "2026-03-04",
  "/about": "2026-02-19",
  "/about/people": "2026-02-19",
  "/(legal)/privacy": "2026-04-11",
  "/(legal)/terms": "2026-03-22",
  "/(legal)/licensing": "2026-01-30",
} as const satisfies Record<StaticIndexableRouteId, string>;
```

`StaticIndexableRouteId` is derived from the route classifier: indexable route IDs that are not `catalog-*`, contain no `[param]` / `[...path]` / `[[optional]]` segments, and are not keys of `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE`. All three exclusions matter — `/manufacturers/[slug]/systems` is indexable and non-catalog, but it's a parameterized listed route handled via `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE`, not a static page. Adding a new static indexable route fails the typecheck until `STATIC_LASTMOD` gets an entry; removing or renaming a route fails the typecheck on the old key. No drift surface, no Vite plugin, no `git` calls, no shallow-clone heuristic.

The legal pages keep their current shape:

```svelte
<h1>Privacy Policy</h1>
<LastUpdated>Last updated: {formatLastUpdated(STATIC_LASTMOD["/(legal)/privacy"])}</LastUpdated>
```

`formatLastUpdated` (new, small) renders `"2026-04-11"` → `"April 11, 2026"` so the user-visible date and the `<lastmod>` value come from the same constant at the same precision — no day-level drift between what readers see and what crawlers receive. Each page references its own key directly — no `page.route.id` runtime lookup, which means the typechecker catches a typo at the call site instead of throwing at render time.

The sitemap endpoint reads `STATIC_LASTMOD` directly (see §3) and emits one `<url>` per entry. If a new static indexable route is added without a `STATIC_LASTMOD` entry, the typecheck fails before the sitemap can render an incomplete set.

### Why hand-maintained beats `git log`

- **Better signal.** `git log -1` over a source file moves on prettier reflows, whitespace fixes, and layout-component refactors that touch the file without changing meaning. A hand-bumped date moves only on substantive content changes — exactly the signal `<lastmod>` is supposed to be.
- **No deploy-environment fragility.** Railway/Nixpacks ship depth-1 clones by default, in which `git log` returns the shallow tip date for every file. Detecting that needs a heuristic; the heuristic itself is a smell.
- **No build step to maintain.** Skips the Vite plugin, the generated JSON, the gitignore entry, the soft-fail logic, and the tests for all of that.
- **The forgotten-bump failure mode is visible.** Legal pages display the date under the `<h1>`. A reviewer who reads the policy diff also reads the date next to it.
- **Scales fine.** Six pages today. If the static-page count ever grows past ~30 and editors start forgetting bumps, revisit — but the trigger for revisiting is "we observed the failure mode," not "we imagined it."

## 3. Frontend — super-sitemap

> **Update (2026-08):** super-sitemap was removed. Profiling against production-shaped data showed the library dominated cold-serve compute (~50ms of a ~70ms render on a dev laptop, 5–10× that on Railway): its subtractive model materializes every path object several times over (generate → strip → `processPaths` → dedupe) before rendering, and fighting its auto-discovery accounted for most of the handler's complexity (`routeIdToRegex`, `excludeRoutePatterns`, `emptyRouteExclusions`, `processPaths` lastmod re-attachment). The shipped `+server.ts` instead emits URLs additively — static indexable routes plus one URL per (route, slug) pair from the feed — and renders the XML directly via `$lib/sitemap-helpers` (~4ms), preserving the 50k `<sitemapindex>` split, the `[[page=integer]]` route shape, XSD validity and the `Cache-Control` policy, with a wiring-completeness test replacing the library's fail-loud-on-unwired-route behavior. The sections below record the original library-based design.

The frontend uses [`super-sitemap`](https://github.com/jasongitmail/super-sitemap) for XML rendering. It handles escaping, `lastmod` formatting, and sitemap-index splitting (when total URLs cross 50k, an index document points at `/sitemap1.xml`, `/sitemap2.xml`, etc. — which only works if the route file is named `sitemap[[page=integer]].xml` and passes `page: params.page`, per the super-sitemap README). Pin to `super-sitemap@^2.0.4`, imported through its SvelteKit adapter subpath (`super-sitemap/sveltekit`) — v2 dropped the bare package entry point in favor of per-framework adapters. Still zero runtime dependencies, healthy maintenance (~40k downloads/month, single-maintainer with consistent cadence over 18+ months).

### Route file: `sitemap[[page=integer]].xml`

The route lives at `frontend/src/routes/sitemap[[page=integer]].xml/+server.ts` from day one, even though today's URL count is well under 50k. The optional `[[page=integer]]` rest-param lets the same endpoint serve `/sitemap.xml` (the index or single urlset) and `/sitemap1.xml`, `/sitemap2.xml`, etc. (per-page urlsets) without a second file. Renaming later when we cross 50k would mean either breaking the canonical `/sitemap.xml` URL or adding a redirect — both avoidable by getting the route shape right upfront. The `=integer` matcher (in `src/params/integer.ts`, pattern `^[1-9]\d*$` to match super-sitemap's own page validation, `/^[1-9]\d*$/` in `core/internal/pagination.js`) keeps `/sitemapfoo.xml`, `/sitemap0.xml`, and `/sitemap007.xml` 404ing at the router instead of routing through and getting 400 from super-sitemap.

### Listed-indexable routes that consume a catalog entity's slug

Some indexable routes are dynamic but not classified as `catalog-*` because they aren't the catalog entity's own detail/history/sources page — `/manufacturers/[slug]/systems` is the only one today (per `route-metadata.server.ts`'s `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS`). They consume a parent entity's slugs, so the sitemap needs to know which feed feeds which route. A tiny hand-maintained map names the parent:

```ts
// frontend/src/lib/route-metadata.server.ts (additive)
export const LISTED_INDEXABLE_ENTITY_SLUG_SOURCE = {
  "/manufacturers/[slug]/systems": "manufacturer",
} as const satisfies Partial<Record<RouteId, CatalogEntityKey>>;
```

The `satisfies` clause forces every key to be a real route ID and every value to be a known `CatalogEntityKey`. One entry today; a parity test (see §7) asserts every key is also in `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS` (so a typo can't silently drop the entry) and that every value has a backend feed. This is the "non-catalog dynamic indexable routes handled through their own mechanism" footnote from invariant #1 — outside the catalog-model automation guarantee, deliberately.

`lastmod` for these routes comes from the parent entity's `_last_modified`. That under-reports when the listing's content changes without bumping the parent (e.g. a new System linked to a Manufacturer doesn't bump `Manufacturer.updated_at`) — same accepted tradeoff as the rest of the design. Revisit per-route lastmod widening if/when traffic data shows we're losing re-crawls because of it.

### Wiring

```ts
// frontend/src/routes/sitemap[[page=integer]].xml/+server.ts
import * as sitemap from "super-sitemap/sveltekit";
import { SITE_ORIGIN } from "$env/static/private";
import {
  allRoutes,
  catalogRoutesByEntity,
  classifyRoute,
  isSearchEngineIndexable,
  LISTED_INDEXABLE_ENTITY_SLUG_SOURCE,
} from "$lib/route-metadata.server";
import { isDeploymentSearchEngineIndexable } from "$lib/is-deployment-search-engine-indexable.server";
import { STATIC_LASTMOD } from "$lib/static-lastmod";
import { createServerClient } from "$lib/api/server";
import type { RouteId } from "$app/types";

// STATIC_LASTMOD keys are route IDs (may contain `(group)` segments); the
// `processPaths` callback below receives super-sitemap's already-resolved URLs,
// so look up by URL form. Built once at module load.
const STATIC_LASTMOD_BY_URL: ReadonlyMap<string, string> = new Map(
  Object.entries(STATIC_LASTMOD).map(([routeId, lastmod]) => [
    stripRouteGroups(routeId),
    lastmod,
  ]),
);

export const GET = async ({ fetch, url, request, params }) => {
  if (!isDeploymentSearchEngineIndexable()) {
    return new Response("Not Found", { status: 404 });
  }

  const client = createServerClient(fetch, url, request);
  const { data, error } = await client.GET("/api/sitemap/");
  if (error || !data) {
    return new Response("Sitemap unavailable", { status: 502 });
  }
  const { feeds } = data;

  // For each entity, gather all indexable SvelteKit route IDs that share its
  // slug (detail + /edit-history + /sources today; whatever is indexable
  // tomorrow). `safeIsIndexable` swallows classifier throws (see below).
  const directRoutesByEntity = catalogRoutesByEntity((_cls, id) =>
    safeIsIndexable(id),
  );

  // Per-entity listed-indexable routes (e.g. `/manufacturers/[slug]/systems`
  // under `manufacturer`). Inverted at module-edit time, not request time.
  const listedRoutesByEntity = new Map<string, RouteId[]>();
  for (const [routeId, kind] of Object.entries(
    LISTED_INDEXABLE_ENTITY_SLUG_SOURCE,
  )) {
    const arr = listedRoutesByEntity.get(kind) ?? [];
    arr.push(routeId as RouteId);
    listedRoutesByEntity.set(kind, arr);
  }

  const paramValues: sitemap.ParamValues = {};
  for (const { kind, entries, detail_excluded_slugs } of feeds) {
    const direct = directRoutesByEntity.get(kind) ?? [];
    const listed = listedRoutesByEntity.get(kind) ?? [];
    const excluded = new Set(detail_excluded_slugs);
    for (const id of [...direct, ...listed]) {
      const cls = classifyRoute(id);
      const isDetail = cls.kind === "catalog-detail";
      const filteredEntries =
        isDetail && excluded.size
          ? entries.filter((e) => !excluded.has(e.slug))
          : entries;
      paramValues[id] = filteredEntries.map((e) => ({
        values: [e.slug],
        lastmod: e.lastmod,
      }));
    }
  }

  return sitemap.response({
    origin: SITE_ORIGIN,
    page: params.page,
    excludeRoutePatterns: allRoutes()
      .filter((id) => !safeIsIndexable(id))
      .map(routeIdToRegex),
    paramValues,
    // Static routes are auto-discovered by super-sitemap walking the routes
    // tree; we don't enumerate them. `processPaths` attaches `lastmod` to
    // each one from `STATIC_LASTMOD_BY_URL`. Dynamic-route paths already
    // carry `lastmod` from `paramValues`, so they pass through unchanged.
    processPaths: (paths) =>
      paths.map((p) => {
        const lastmod = STATIC_LASTMOD_BY_URL.get(p.path);
        return lastmod ? { ...p, lastmod } : p;
      }),
    // Override super-sitemap's default `max-age=0, s-maxage=3600`. We don't
    // have a shared cache today and we want browsers/crawlers to actually
    // cache the response for the TTL. Revisit `s-maxage` when a CDN lands.
    headers: { "Cache-Control": "public, max-age=3600" },
  });
};
```

That's the whole endpoint. Adding a new entity type requires zero changes here — `GET /api/sitemap/` reports the new feed, `catalogRoutesByEntity()` finds its route IDs, the loop wires them into `paramValues`. Adding a new static page requires one line: an entry in `STATIC_LASTMOD`. Adding a new listed-indexable route that consumes a catalog entity's slug requires one line in `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE`.

**super-sitemap v2 deltas (the shipped `+server.ts` is authoritative; this sketch is a simplified skeleton).** The v2 upgrade tightened several rules the sketch above glosses over, all handled in the real endpoint: (a) import from `super-sitemap/sveltekit`, not the bare package; (b) `excludeRoutePatterns` takes `RegExp` objects, not strings (see `routeIdToRegex` below); (c) v2 rejects a `paramValues` key on a param-less route, so the `directRoutesByEntity` predicate also drops `catalog-listing` routes (`/titles`, `/cabinets`, … stay static-discovered, with `<lastmod>` attached via a `listingLastmodByUrl` map keyed off each feed's `max_lastmod`); (d) v2 rejects both a missing key AND an empty array for a discovered dynamic route, so the loop sets `paramValues` only for routes that have entries and adds every zero-entry indexable dynamic route to `excludeRoutePatterns` for that request instead of seeding an empty array.

### Rest-param routes (`Location`)

`Location.public_id_field = "location_path"` — a slash-separated path like `"manufacturer/title/region/site"` — and its SvelteKit route is `/locations/[...path]` (rest segment). The frontend passes `values: [e.slug]` to super-sitemap regardless of whether the route uses `[slug]` or `[...path]`. Verified against super-sitemap@2.0.4: the library substitutes without URL-encoding, so `values: ["a/b/c"]` produces `/locations/a/b/c` (literal slashes). No per-route shape branch is needed. A targeted regression test (Location with multi-segment path → expect `/locations/foo/bar`, not `/locations/foo%2Fbar`) belongs in §7 to catch a future library change.

### Tolerating unclassified routes

`isSearchEngineIndexable()` throws on routes the classifier doesn't recognize — by design, to force route authors to classify intentionally at lint/build time. At request time inside `/sitemap.xml`, that discipline turns into a sharp edge: one stray unclassified route 500s the entire sitemap. The endpoint calls the classifier at **two** sites — once in the `allRoutes().filter(...)` that builds `excludeRoutePatterns`, and once in the `catalogRoutesByEntity((_cls, id) => ...)` predicate — so introduce a local helper:

```ts
function safeIsIndexable(id: RouteId): boolean {
  try {
    return isSearchEngineIndexable(id);
  } catch (e) {
    console.warn(
      `[sitemap] route ${id} unclassified; treating as non-indexable`,
      e,
    );
    return false;
  }
}
```

and call `safeIsIndexable` at both sites. Returning `false` is the safer default — leak nothing rather than render nothing. The classifier still throws everywhere else it's called; only the sitemap endpoint downgrades the throw to a log.

### `routeIdToRegex` helper

`excludeRoutePatterns` expects an array of `RegExp` objects — super-sitemap@2 throws on plain strings. SvelteKit route IDs include `[slug]`, `[...path]`, `[[optional]]`, and `(group)` shapes. Crucially, v2 matches `excludeRoutePatterns` against the route **key** — after `(group)` segments are stripped but _before_ dynamic params are interpolated — not against resolved URLs (this changed from v1). So the helper (a) **strips `(group)` segments** (the same `stripRouteGroups` transform used to build `STATIC_LASTMOD_BY_URL`), then (b) escapes regex metacharacters and (c) anchors both ends, leaving `[slug]`/`[...path]` literal — no wildcard translation, because super-sitemap feeds the un-interpolated key. Both consumers must agree on group handling, or a static route's exclusion pattern won't line up with the key super-sitemap emits for it from auto-discovery. Unit-test the helper directly with each shape and against the full `allRoutes()` snapshot (matching against `stripRouteGroups(id)`, as super-sitemap does) — accidentally over- or under-matching here silently drops correct URLs from the sitemap or leaks non-indexable ones in. (One gap: optional-param `[[x]]` routes are expanded into variants by super-sitemap before filtering, which `routeIdToRegex` does not mirror; harmless today because the only `[[…]]` route is this `+server` endpoint, which super-sitemap never discovers.)

### Why super-sitemap

- **Debuggability win.** XML correctness (escaping, `lastmod` formatting, index-vs-urlset switching) is annoying to verify by hand. With the library, the debugging surface shrinks from "is our XML right?" to "does our config produce what we expect?" — and the latter is straightforward to test.
- **Boring tech in scope.** Sitemap protocol is stable; we don't need innovation here.
- **Library doesn't conflict with rate limiting.** It's just an XML-response helper at the SvelteKit layer; rate limiting lives at the Django endpoint where it belongs.

### Response caching

The SvelteKit `/sitemap.xml` response sets `Cache-Control: public, max-age=3600` by passing explicit `headers` to `sitemap.response()` — super-sitemap's default is `max-age=0, s-maxage=3600` (`getHeaders` in `core/internal/sitemap.js`), which we override because (a) we want clients/crawlers to actually cache, not re-validate every hit, and (b) `s-maxage` is a no-op today (Caddy isn't a caching reverse proxy and there's no CDN in front of it). The Django `/api/sitemap/` response sets the same TTL and is also cached in-process for an hour, so the staleness budget is bounded by the longer-lived layer. The two cache lifetimes don't compose multiplicatively — both are wall-clock from the moment each layer warms — but they make repeated crawler hits cheap regardless of layer.

Add `s-maxage` back the same diff that introduces a shared cache layer.

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

- `/`, `/about`, `/about/people`, `/legal/privacy`, `/legal/terms`, `/legal/licensing` — `lastmod` from the per-route `STATIC_LASTMOD` constant (hand-bumped when the page's content changes; visible to humans on the legal pages via `<LastUpdated />`).
- All catalog detail pages for active rows, with their `_last_modified` as `lastmod`, plus per-entity `/edit-history` and `/sources` URLs (every `catalog-detail` / `catalog-edit-history` / `catalog-sources` route classifies as indexable), except:
  - **Single-Model Title member Models** — `/models/[slug]` (the catalog-detail route) is **excluded** because the canonical URL is the Title's detail page (the UI collapses to the Model page but the Title slug is canonical per `docs/SingleModelTitles.md`). `/models/[slug]/edit-history` and `/models/[slug]/sources` are **still included** with the Model's own `updated_at` — those pages show the Model's history and sources independently, not the Title's. Implemented via `MachineModel.non_canonical_detail_slugs()`. The Title's own `lastmod` aggregates `Max(machine_models.updated_at)` so the collapsed Model's edits bump the Title's detail-page freshness signal.
- `/manufacturers/[slug]/systems` — the only listed-indexable dynamic route today. Receives manufacturer slugs via `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE` and the manufacturer's own `_last_modified`.

**Out:**

- `/style-lab`, `/api-docs`, `/search`, `/kiosk`, `/_sentry_test`, `/auth/error`
- Catalog `/new` and `/delete` subroutes — non-indexable.
- Anything auth-gated — recognized by `requireCapability` in the layout chain; non-indexable routes are excluded by `isSearchEngineIndexable(routeId)`; never enumerated by hand.
- Soft-deleted catalog rows (`status='deleted'`) — excluded by `.active()` at every queryset entry point.
- The `catalog-detail` URL for Models whose parent Title has exactly one active Model (see above); their `/edit-history` and `/sources` URLs are still in.
- Locations with zero manufacturers at or below them — excluded entirely (detail, `/edit-history`, and `/sources`) via `Location.sitemap_queryset()`, since their pages render an empty manufacturer grid that search engines cluster as duplicate content.

## 6. `SITE_ORIGIN` build + deploy checks

`SITE_ORIGIN` is `https://flipcommons.org` in production (apex, no `www`). Consumed by the sitemap (URLs, robots.txt `Sitemap:` line) and by the prerendered meta tags that already exist. Today `frontend/svelte.config.js:40` falls back to `'http://localhost:5173'` when unset — fine for `make dev`, but a production build silently bakes `localhost` URLs into prerendered HTML.

The fix: build-phase refusal gate when `RAILWAY_GIT_COMMIT_SHA` is set but `SITE_ORIGIN` is empty/malformed, plus a deploy check in `apps/core/checks.py` with new error ids `core.E303` / `core.E304`, plus a `Dockerfile` `ARG` for `SITE_ORIGIN`. Pre-existing env hygiene the sitemap surfaces — but the sitemap can't ship without it, so it lands as the first commit of this PR.

## 7. Tests

- **Backend (pytest):**
  - `apps/core/tests/test_sitemap.py` — `all_sitemap_feeds()` walks every concrete `SitemappedModel` subclass, builds one feed per kind, entries match `(slug, lastmod)` shape, ordering is by slug, `max_lastmod` matches the newest entry, `detail_excluded_slugs` is a `frozenset` (default empty). Parameterized over every concrete `SitemappedModel` so a new entity type fires the test and gets reviewed intentionally (per [ModelDrivenMetadata.md](../model_driven_metadata/ModelDrivenMetadata.md#rules-of-thumb): "Parity tests pin derived sets"). Also asserts a model overriding `sitemap_queryset()` to return `.none()` produces no feed entry (opt-out path), and — same parameterized class — that the default `sitemap_queryset()` excludes `status='deleted'` rows.
  - `apps/core/tests/test_sitemapped_model_lifecycle_parity.py` — every concrete `SitemappedModel` subclass inherits `LifecycleStatusModel` and `TimeStampedModel`. The default `sitemap_queryset()` calls `.active()` and annotates `lastmod_expression()` (which reads `updated_at`); a future subclass that doesn't satisfy this must override `sitemap_queryset()`, and this test makes that contract explicit instead of letting the omission crash at sitemap render.
  - `apps/catalog/tests/test_title_last_modified.py` — `Title.sitemap_queryset()` annotates `_last_modified = max(Title.updated_at, max(machine_models.updated_at))` across: (a) Title-only edit, (b) MachineModel-only edit, (c) both edited, (d) single-Model Title with Model edit, (e) Title with zero MachineModels (annotation falls back to `Title.updated_at` via `Coalesce`).
  - `apps/core/tests/test_sitemap_api.py` — endpoint returns 200 with the expected shape (including `detail_excluded_slugs` per feed); second call within the TTL is served from cache (assert `all_sitemap_feeds` is invoked once across two requests via a spy / mock).
  - `apps/catalog/tests/test_machine_model_non_canonical.py` — `MachineModel.non_canonical_detail_slugs()` returns exactly the slugs of active Models whose parent Title has exactly one active Model. Cases: (a) Title with two active Models → both slugs absent from the result; (b) Title with one active + one deleted Model → the active Model's slug IS present (the deleted sibling shouldn't keep it canonical); (c) Title with one active Model → that slug IS present; (d) the same Model still appears in `sitemap_queryset()` so its `/edit-history` and `/sources` are not dropped from the feed entries.
  - `apps/catalog/tests/test_location_sitemap.py` — Location's `public_id_field = "location_path"` produces multi-segment slugs (e.g. `"a/b/c"`) in the feed without further encoding.
  - `apps/core/tests/test_entity_type_parity.py` — every concrete `LinkableModel.entity_type` is a member of the frontend's `CatalogEntityKey` set. The sitemap relies on `directRoutesByEntity.get(kind)` matching Python `entity_type` strings against `CatalogEntityKey` exactly; this test pins the cross-language coupling so renaming on either side fails CI rather than silently dropping a kind from the sitemap. Source the frontend set from a checked-in generated file (or a small JSON exported alongside `make codegen`) — do not duplicate the literal by hand.
- **Frontend (vitest):**
  - `sitemap[[page=integer]].xml/+server.ts` builds `paramValues` correctly from a mocked `/api/sitemap/` response: a single backend feed for `kind: "title"` lands under every indexable SvelteKit route ID for `title` (detail + `/edit-history` + `/sources` today) with the same slug list and `lastmod`.
  - **Canonical-URL split** — given a `machine-model` feed where `detail_excluded_slugs = {"sm1"}` and entries are `[{slug:"sm1",lastmod:T1}, {slug:"mm2",lastmod:T2}]`: `paramValues["/models/[slug]"]` includes only `mm2`, but `paramValues["/models/[slug]/edit-history"]` and `paramValues["/models/[slug]/sources"]` include BOTH `sm1` and `mm2` with their own `lastmod`s. This is the load-bearing test for invariant #2.
  - **Listed-indexable bridge** — given a `manufacturer` feed, `paramValues["/manufacturers/[slug]/systems"]` is populated with the manufacturer slugs and their `lastmod`s, sourced via `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE`. Removing the map entry drops the route from `paramValues`.
  - `sitemap[[page=integer]].xml/+server.ts` substitutes a path-shaped slug (`"a/b/c"`) into a `[...path]` rest route correctly — `/locations/a/b/c`, not `/locations/a%2Fb%2Fc`. Run the rendered XML through XSD validation in the same test so encoding regressions surface as schema errors.
  - `processPaths` attaches the right `lastmod` to each auto-discovered static URL from `STATIC_LASTMOD_BY_URL` (one assertion per static route), and leaves dynamic-route paths (which already carry their own `lastmod` from `paramValues`) unchanged.
  - **Sitemap-index page param plumbing** — when `params.page === undefined`, the endpoint renders a single urlset (or a `<sitemapindex>` if URLs cross 50k); when `params.page === "1"`, it renders page 1 of the urlset. Mock super-sitemap or assert on the `page` argument the wrapper passes through.
  - `sitemap[[page=integer]].xml/+server.ts` returns 404 when `ALLOW_SEARCH_ENGINE_INDEXING != "true"`.
  - `sitemap[[page=integer]].xml/+server.ts` returns 502 when the Django client returns an error (resilience: one stray Django outage shouldn't 500 the route).
  - `sitemap[[page=integer]].xml/+server.ts` sets `Cache-Control: public, max-age=3600` on 200 responses.
  - `sitemap[[page=integer]].xml/+server.ts` does NOT throw when the route classifier would reject an unclassified route — `safeIsIndexable` logs and treats it as non-indexable, so one stray route can't 500 the whole sitemap.
  - `routeIdToRegex` helper: unit tests for `[slug]`, `[...path]`, `[[optional]]`, `(group)` shapes; snapshot test against the current `allRoutes()` set asserting the regex set excludes exactly the non-indexable routes.
  - `STATIC_LASTMOD` parity (`static-lastmod.test.ts`): every static indexable route ID has an entry, every entry corresponds to a real static indexable route, every value matches `YYYY-MM-DD` and parses as a real calendar date. The `satisfies` clause covers the first two at typecheck time; the test pins them at runtime too so the failure has a clear name when it breaks.
  - `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE` parity: every key is also in `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS` (otherwise the entry is dead); every value is a known `CatalogEntityKey` (the `satisfies` clause covers this at typecheck, the test pins it at runtime). Importantly, no key is a `catalog-*` route ID — those are already handled by `catalogRoutesByEntity()`, so a duplicate here would double-emit URLs.
  - Existing robots.txt test extended to assert the `Sitemap:` line is present iff `ALLOW_SEARCH_ENGINE_INDEXING == "true"`.

## 8. Implementation order

### Commits

The work below ships as **multiple commits in one PR**, each done by a fresh AI session. **🛑 Do NOT commit until the user explicitly directs the commit.** When a commit's code is ready, stop and wait — the user reviews, then says to commit. No commit happens without explicit go-ahead.

#### ✅ DONE - Commit A: prereqs

`SITE_ORIGIN` prerequisites (per §6). Build-phase refusal gate, deploy check (`core.E303` / `core.E304`), `Dockerfile` `ARG`. No sitemap code yet — just the env hygiene the sitemap depends on. Reviewable as deploy-check work.

#### ✅ DONE - Commit B: backend

Backend feeds + backend sitemap API endpoint (Commit B steps). `SitemappedModel.sitemap_queryset()` + `non_canonical_detail_slugs()`, the per-model overrides, `all_sitemap_feeds()`, cached `/api/sitemap/` endpoint, `make codegen`. Reviewable on its own: tests prove the feeds are right, the endpoint returns the right shape; nothing user-visible yet.

#### ✅ DONE - Commit C: static page timestamps

`STATIC_LASTMOD` + legal page wiring (Commit C step). Hand-maintained map with typed `satisfies`, parity test, and `formatLastUpdated` helper. Wire the legal pages to read from the constant (replacing the current inline "Last updated: March 2026" strings). User-visible: legal-page dates now show the day and come from the same source the sitemap will read.

#### ✅ DONE - Commit D: sitemap

Sitemap frontend endpoint + robots line (Commit D steps). `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE`, super-sitemap wiring (via `createServerClient`, `processPaths`, `page: params.page`, `safeIsIndexable`), `routeIdToRegex`, rest-param handling, robots `Sitemap:` line, XSD validation test. Lights up `/sitemap.xml` (the user-facing URL; the route file is `sitemap[[page=integer]].xml`).

### Steps

#### Commit B — backend feeds + API endpoint

1. Add the `LastUpdatedModel` freshness mixin (`lastmod_expression()` → `F("updated_at")`, `last_modified` property) and `SitemappedModel(LinkableModel, LastUpdatedModel)` carrying `sitemap_queryset()` (`.active()`, `.annotate(_last_modified=cls.lastmod_expression())`, `.only()`, `.order_by()`) and `non_canonical_detail_slugs()` (default empty). `CatalogModel` inherits `SitemappedModel`. Add a parity test asserting every concrete `SitemappedModel` subclass also inherits `LifecycleStatusModel` and `TimeStampedModel` — the default's contract.
2. Override `MachineModel.non_canonical_detail_slugs()` for the single-Model-Title rule (active sibling count == 1, via `Count("title__machine_models", filter=active_status_q("title__machine_models"))`) and `Title.lastmod_expression()` for the `Greatest(updated_at, Coalesce(Max("machine_models__updated_at"), updated_at))` aggregation. Tests per §7, including the zero-Models case.
3. `apps/core/sitemap.py` — `SitemapEntry`, `SitemapFeed` (with `detail_excluded_slugs: frozenset[str]`), `all_sitemap_feeds()` (filtering None lastmods and skipping empty feeds). Parameterized parity test over every concrete `SitemappedModel`, including an opt-out (`sitemap_queryset()` returns `.none()`) assertion and a default-active-filter assertion.
4. `apps/core/api/sitemap.py` + `apps/core/api/__init__.py` (`routers = [("", router)]`) — single endpoint at `/api/sitemap/`, shared `django.core.cache` (file-based per project settings, 1h TTL), `Cache-Control: public, max-age=3600` response header. Typed schemas in `apps/core/api/sitemap_schemas.py` carry `detail_excluded_slugs` as `frozenset[str]` → JSON array. Tests for the 200 path and the cache-hit path (one materialization across two requests).
5. `make codegen`.

> 🛑 **Stop — do NOT commit until the user explicitly says to.**

#### Commit C — static page timestamps

1. `frontend/src/lib/static-lastmod.ts` — `STATIC_LASTMOD` map (`YYYY-MM-DD` values) + `StaticIndexableRouteId` type + `formatLastUpdated` helper. Parity test (every static indexable route has an entry; every value matches `YYYY-MM-DD` and parses as a real date). Update each legal page's `<LastUpdated>` to read from the constant via `formatLastUpdated(STATIC_LASTMOD["..."])`.

> 🛑 **Stop — do NOT commit until the user explicitly says to.**

#### Commit D — sitemap endpoint + robots line

1. `frontend/src/lib/route-metadata.server.ts` — add `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE` with `/manufacturers/[slug]/systems → manufacturer`. Add parity test (key ∈ `SEARCH_ENGINE_INDEXABLE_ROUTE_IDS`; value ∈ `CatalogEntityKey`; key NOT a `catalog-*` route).
2. `pnpm add super-sitemap@~2.0.4` (import via the `super-sitemap/sveltekit` adapter subpath).
3. `frontend/src/routes/sitemap[[page=integer]].xml/+server.ts` — note the optional-param route shape (sitemap-index support from day one). Wire super-sitemap to `/api/sitemap/` via `createServerClient` for catalog URLs, expand to route IDs via `catalogRoutesByEntity()` + `LISTED_INDEXABLE_ENTITY_SLUG_SOURCE`, apply `detail_excluded_slugs` only to `catalog-detail` classifications, attach static `lastmod` via `processPaths` reading `STATIC_LASTMOD_BY_URL`. Pass `page: params.page` to `sitemap.response()`. Use `safeIsIndexable` (per §3 "Tolerating unclassified routes"). Set `Cache-Control` on responses. Gate on `ALLOW_SEARCH_ENGINE_INDEXING` via `isDeploymentSearchEngineIndexable()`. Return 502 if the Django client returns an error.
4. Implement and unit-test the `routeIdToRegex` helper plus `stripRouteGroups` (per §3).
5. Append the `Sitemap:` line to `frontend/src/routes/robots.txt/+server.ts` (indexable-mode only, pointing to `${SITE_ORIGIN}/sitemap.xml` — the canonical entry point even with the `[[page]]` route shape). Extend the existing robots test.
6. Add the frontend XSD validation test (vitest, using a bundled sitemap XSD validated by a Node XSD validator), including the Location rest-param regression case (per §3 "Rest-param routes"). XML correctness is the frontend's concern — the backend response is JSON and its shape is already pinned by `SitemapResponseSchema`.
7. Verify locally: `curl localhost:5173/sitemap.xml`; spot-check with `xmllint --noout --schema` for ad-hoc inspection.

> 🛑 **Stop — do NOT commit until the user explicitly says to.**

### Deployment routing

No Caddyfile changes needed. The current `@django` matcher in `Caddyfile` only catches `/api`, `/djadmin`, `/media`, `/static`, so `/sitemap.xml`, `/sitemap1.xml`, `/sitemap2.xml`, etc. all route to SvelteKit (Node, port 3000) by default.

## Follow-ups

### Write-time sitemap cache invalidation

When a user edits or creates a catalog row, the sitemap doesn't reflect that for up to 1h (the `SITEMAP_CACHE_TTL`). By design — keeps the cost ceiling at one materialization per hour per process — but worth revisiting if/when SEO data shows we're losing re-crawls because crawlers see stale `<lastmod>` values.

When we want it: hook a `post_save` / `post_delete` signal on `CatalogModel` that calls `cache.delete(SITEMAP_CACHE_KEY)`. Cheap; the next request re-materializes. The narrower variant (invalidate only on lifecycle / structural edits, not every claim write) is the right level of granularity but adds bookkeeping — start with the broad invalidation and tighten only if materializations become hot.
