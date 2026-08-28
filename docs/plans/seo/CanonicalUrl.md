# Canonical URL

Every indexable page emits `<link rel="canonical" href="...">` so search engines consolidate ranking signals on one authoritative URL when the same content is reachable via multiple paths (trailing-slash variants, query-string variants, scheme/host variants).

Addresses the "canonical URLs" concern in [`SearchEngines.md`](SearchEngines.md).

## Open questions

**Faceted and paginated listing URLs** (`?page=2`, `?manufacturer=stern`). Canonical strips the query string for every route, which points every filter combination at the base listing. Whether that is the right policy — versus preserving `?page=` so deep pages stay individually indexable, or `noindex` on filter combinations — is tracked as its own concern in [`SearchEngines.md`](SearchEngines.md). A per-route allowlist of canonical-bearing query params is the natural shape if the answer is "preserve some".

## Scope

**In scope:** a `<link rel="canonical">` on every indexable page, pointing at the normalized URL for the current page, always on the site's public origin.

**Handled elsewhere:**

- **Single-Model-Title duplication.** `/models/[slug]` 301-redirects to the Title route when the parent Title has exactly one Model (`frontend/src/routes/models/[slug]/+page.server.ts`). A 301 collapses the duplicate at the HTTP layer, so canonical tags are not load-bearing here. `ModelSitemapFeed` also excludes these Models per [`Sitemap.md`](Sitemap.md).
- **Slug renames.** 301 redirects in the slug-edit flow, per the "URL stability across slug changes" concern in [`SearchEngines.md`](SearchEngines.md).

## Mechanism

`MetaTags` (`frontend/src/lib/components/layout/page/head/MetaTags.svelte`) emits the tag from a `<svelte:head>` block, alongside the page's other head content. Callers pass the current `page.url`; the component pins it to the public origin and strips the query and fragment:

```svelte
let pageUrl = $derived(publicUrl(new URL(url)));
let canonicalUrl = $derived(buildCanonicalUrl(pageUrl.href));
```

`buildCanonicalUrl` (`meta-tags.ts`) drops everything from `?` or `#` onward. `og:url` uses the same value, so the two never disagree.

Because the tag renders through `<svelte:head>`, Svelte escapes the attribute value — dynamic segments (`[slug]`, `[...path]`) need no separate escaping step.

### The public origin

`publicUrl(url)` (`frontend/src/lib/public-url.ts`) rebases a URL onto `PUBLIC_SITE_ORIGIN` and is the single mechanism keeping SEO URLs off the request host. Two independent reasons the request host is the wrong source:

- **On the server,** Bunny fronts the site with Forward Host Header off (see [`../../Hosting.md`](../../Hosting.md) § Client IP trust), so the `Host` header reaching Node is the Railway origin hostname.
- **In the browser,** `page.url` follows the address bar, so a page served from any non-public host would declare that host as its identity after hydration.

It builds the result by concatenating onto the configured origin rather than passing it as a `URL` base, so a pathname beginning with `//` — a network-path reference — cannot resolve onto a foreign host. The origin holds by construction.

It returns the URL unchanged in two cases: when `PUBLIC_SITE_ORIGIN` is unset, so `make dev` works against `localhost:5173`; and during prerender, so prerendered pages depend only on `prerender.origin` — the build-time `SITE_ORIGIN` already baked into `page.url` — never on the build machine's environment.

### Origin configuration

`SITE_ORIGIN` is the one operator-facing setting. `scripts/start-production` maps it to the name each runtime requires, so the values cannot drift:

```sh
export PUBLIC_SITE_ORIGIN="${SITE_ORIGIN:?SITE_ORIGIN must be the public origin, e.g. https://flipcommons.org}"
ORIGIN="${SITE_ORIGIN}" HOST=127.0.0.1 PORT="${NODE_PORT}" node build/index.js &
```

The `:?` guard catches a set-but-empty `SITE_ORIGIN`, which `set -u` alone does not — the Dockerfile declares `ENV SITE_ORIGIN=""` as its build-arg default. An empty `ORIGIN` crashes Node at boot because adapter-node rejects it, but an empty `PUBLIC_SITE_ORIGIN` would degrade silently to the request host, so the guard sits on the export.

`ORIGIN` tells adapter-node its public URL, which is what `page.url.origin` resolves to for every server-side consumer. `PUBLIC_SITE_ORIGIN` carries the same value to the browser — `$env/dynamic/public` exposes only `PUBLIC_`-prefixed variables. `core.E303`/`E304` (`apps/core/checks.py`) block a deploy when `SITE_ORIGIN` is missing or malformed, and `svelte.config.js` refuses a Railway build without it.

### Everything that carries page identity

Canonical is one of six places the public origin has to hold. Two helpers in `public-url.ts` cover them: `publicUrl(url)` rebases a whole URL, and `pageIdentity(url)` returns the `origin + pathname` string that identity fields want — no query, no fragment.

| location                                 | emits                                                        | via              |
| ---------------------------------------- | ------------------------------------------------------------ | ---------------- |
| `MetaTags.svelte`                        | canonical, `og:url`                                          | `publicUrl()`    |
| `utils.ts` — `absoluteAssetUrl()`        | `og:image`, `twitter:image` when no CDN origin is configured | `publicUrl()`    |
| `jsonld.ts` — `absolutize()`             | breadcrumb `item` for ancestor crumbs                        | `publicUrl()`    |
| `jsonld.ts` — `breadcrumbList()`         | breadcrumb `item` for the current page                       | `pageIdentity()` |
| `jsonld.ts` — `pageNode()`               | `@id` and `url`                                              | `pageIdentity()` |
| `schema-org.ts` — `buildListingJsonLd()` | `ItemList` `@id`                                             | `pageIdentity()` |

Callers keep passing `page.url`; normalization happens at these sinks, so no route has to remember. The invariant is greppable: SEO code never reads `.origin` off a request URL — it goes through one of these two helpers.

## What gets a canonical

Every route that renders `MetaTags`, which is every indexable route. `MetaTags` lives in the shared `[slug]/+layout.svelte` for each catalog entity, so detail pages and their child routes (`edit-history`, `sources`, nested listings like `/manufacturers/[slug]/systems`) all inherit it and each emits a self-referencing canonical for its own URL.

Non-indexable routes carry `noindex` (per [`NoindexMeta.md`](NoindexMeta.md)) and no server-rendered canonical: they either omit `MetaTags` entirely (`/login`, `/search`, `/api-docs`) or set `ssr = false` so the served HTML has no head content (catalog edit and delete routes, `/users/[username]`, `/changesets`) — though on those routes the inherited `MetaTags` still adds a canonical after client rendering; the `noindex` remains authoritative.

## Gate on `ALLOW_SEARCH_ENGINE_INDEXING`?

No. Same reasoning as [`NoindexMeta.md`](NoindexMeta.md) § "Gate on `ALLOW_SEARCH_ENGINE_INDEXING`?" — on non-prod deploys robots.txt's `Disallow: /` keeps crawlers out, so the canonical tag is harmless redundancy. Unconditional emission keeps local testing trivial.

## Tests

- `frontend/src/lib/public-url.test.ts` — `publicUrl()` and `pageIdentity()` in isolation: rebasing, the `//` network-path case, identity stripping query and fragment, the unset-env and prerender fallbacks.
- `frontend/src/lib/public-origin-sinks.test.ts` — every sink in the table above resolves to the public origin when `page.url` is on another host.
- `frontend/src/lib/components/layout/page/head/MetaTags.dom.test.ts` — the rendered `<head>`: canonical and `og:url` agree and sit on the public origin.
- `backend/tests/test_public_origin_wiring.py` — pins the `scripts/start-production` contract that derives `ORIGIN` and `PUBLIC_SITE_ORIGIN` from `SITE_ORIGIN`, in the shape of `test_ssr_api_route.py`.
- `frontend/src/lib/components/layout/page/head/meta-tags.test.ts` — `buildCanonicalUrl()` query and fragment stripping.

## Alternatives considered

- **Canonical derived from the request host** (`page.url.href` unpinned, or `event.url.href` in a hook). Rejected 2026-08-28: behind a CDN that does not forward the visitor's `Host`, the request host is an internal origin hostname, so pages advertise a host that is not the public one and search engines treat the public URL as an alternate of it. The failure is silent — the page renders correctly and only the crawler notices. `publicUrl()` exists precisely to make identity independent of how the request arrived.
- **A `handle` hook that injects the tag server-side.** Rejected: a hook can inject `<link rel="canonical">` and nothing else, so the other five identity sinks — which render inside Svelte components — would still need their own mechanism. Two systems for one invariant, and both would emit a canonical unless `MetaTags` stopped. Its one structural advantage, that a server-injected string cannot be rewritten during hydration, is already provided by pinning to `PUBLIC_SITE_ORIGIN`, which does not vary with browser location.
- **Layout-load implementation** (`+layout.server.ts` returns `{ canonical }`, root `+layout.svelte` reads `data.canonical`). Rejected for the reason [`NoindexMeta.md`](NoindexMeta.md) gives: it pushes a `canonical` field into every page's `PageData` type, forcing every test that builds a literal `data` fixture to carry it.
- **A separate `ORIGIN` variable on the Railway service.** Rejected: `ORIGIN`, `PUBLIC_SITE_ORIGIN` and `SITE_ORIGIN` always hold the same value, so configuring them independently invites drift and needs a cross-check to police it. Deriving in the entrypoint keeps one operator-facing setting and puts the mapping where a test can see it.
- **Forwarding the visitor's `Host` at the CDN.** Rejected: it would make the request host correct, but the apex would have to stay a validated Railway custom domain — which can de-validate once DNS points at the CDN — and it leaves correctness resting on a dashboard setting no test can reach. See [`../../Hosting.md`](../../Hosting.md) § Networking.
