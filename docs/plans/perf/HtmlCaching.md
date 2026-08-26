# Cache SSR HTML

Goal: a shared cache to absorb anonymous traffic to the public SSR pages (listings, detail pages), so the Railway origin renders each page once per invalidation window instead of once per visitor — without ever showing contributors a stale copy of their own edits.

## Status: ✅ Implemented

This plan has been implemented.

## The caching layers

### Layer 1: Backend data cache

([`catalog/cache.py`](../../../backend/apps/catalog/cache.py)) — pre-serialized JSON + ETag for `/all/` and the no-filter facets payloads, audience-scoped, invalidated on commit. Lives inside Django.

### Layer 2: Edge HTML cache (this doc)

Shared cache of anonymous public SSR HTML, in front of Node.

### Layer 2: Static asset CDN

([StaticAssetCDN.md](StaticAssetCDN.md)) — Bunny pull zone for hashed `/_app/immutable/*`, fonts and `version.json`.

### How the caching layers compose

Caching layers 1 and 2 compose: layer 1 keeps the origin correct, layer 2 keeps anonymous load off the origin. `/api/*` and `/djadmin/*` belong to neither this cache nor the asset CDN — the API has only its own internal data cache (layer 1).

## Invariants

The design rests on the following load-bearing properties of the current system.

### SSR HTML is per-user-invariant

The server renders the same HTML for every visitor — anonymous and authenticated alike. Auth state is loaded **client-side only**: [`Nav.svelte`](../../../frontend/src/lib/components/layout/site/Nav.svelte) calls `auth.load()` from a `$effect` (browser-only, never SSR), and every auth-dependent branch is gated behind `{#if auth.loaded}`, which is false on the server. [`auth.svelte.ts`](../../../frontend/src/lib/auth.svelte.ts)'s `set()` is browser-guarded. So the server emits the anonymous shell and the client personalizes after hydration.

The HTML therefore carries no per-user content and is safe to mark `public` and share. **This must keep holding**: if a public page ever renders user-specific content server-side, shared caching would leak it across users, so auth-dependent UI must stay client-only behind `{#if auth.loaded}`.

### Anonymous traffic is cookie-less

An anonymous reader sends no cookie. Anonymous requests never create a `django_session` row (the session is empty, so `SessionMiddleware` never persists it even under `SESSION_SAVE_EVERY_REQUEST`), and `csrftoken` is not force-set on anonymous browsing (no `ensure_csrf_cookie`/`get_token` on the public path; the SPA only _reads_ the cookie in [`csrf.ts`](../../../frontend/src/lib/api/csrf.ts)).

So the vast majority of launch traffic arrives cookie-less and collapses to **one cache entry per URL** — an unusually cache-friendly profile.

### Kiosk is the only audience split

The only content-audience split is kiosk vs default, toggled by a single `mode=kiosk` cookie ([`kiosk_audience.py`](../../../backend/apps/core/middleware/kiosk_audience.py) reads `request.COOKIES.get("mode") == "kiosk"`; [`licensing.py`](../../../backend/apps/core/licensing.py) `current_audience()` returns `"kiosk"` or `"default"`). The kiosk audience sees licensing-gated content the public must not, so it **must not** share cache entries with public content.

Kiosk mode runs on display terminals at The Flip museum — _very_ low traffic — and need not be cached itself. The cookie is set only by the SvelteKit kiosk routes on those terminals (and by admins testing kiosk mode), never on a normal response.

**This must keep holding**: a second licensing-gated audience input beyond `mode=kiosk` would break the rule and require extending the bypass. Today facet counts gate on status only (active/deleted), carrying no licensing input, so default-audience HTML is audience-invariant.

### The server-side data cache invalidates on commit

Catalog edits go through the claims pipeline, which busts the backend's `/all/` and facets data cache via `transaction.on_commit(invalidate_all)` ([`resolve/_dispatch.py`](../../../backend/apps/catalog/resolve/_dispatch.py)) plus model `post_save`/`post_delete` signals ([`catalog/signals.py`](../../../backend/apps/catalog/signals.py)). Invalidation runs **after** the edit commits, so a rebuild can't re-cache pre-edit rows.

So once an edit commits, an origin render reflects it immediately — the origin is always authoritative. (This is a separate layer from the edge HTML cache; see [Relationship to other caches](#relationship-to-other-caches).)

## The cache rule

A request is cacheable iff it carries **neither** a `sessionid` cookie **nor** `mode=kiosk`:

| Request                                     | Edge behavior                    | Origin `Cache-Control`          |
| ------------------------------------------- | -------------------------------- | ------------------------------- |
| Anonymous (no `sessionid`, no `mode=kiosk`) | cache / serve from cache         | `public, s-maxage=…, max-age=0` |
| Authenticated (`sessionid` present)         | **bypass** (no lookup, no store) | `private, no-cache`             |
| Kiosk (`mode=kiosk` present)                | **bypass**                       | `private, no-store`             |

Three points make the rule correct:

- **Anonymous caching is CDN-only** (`s-maxage` for the shared edge, `max-age=0` for the browser), not browser-cacheable. This closes a contributor-freshness hole: a user who viewed a record while anonymous holds a `public` browser-cache entry, and with no `Vary: Cookie` the browser would reuse it _after_ signing in — serving a stale copy of their own just-made edit without the request reaching the edge bypass. `max-age=0` forces every browser to revalidate on each navigation, so the post-auth request always leaves the browser, carries `sessionid`, and bypasses to a fresh render. (No browser-facing `stale-while-revalidate`, for the same reason; edge stale-serving, if wanted, is a Bunny zone setting.)
- **`csrftoken` is ignored** in the cache key — it does not vary the HTML, and keying on it (or on "any cookie") would needlessly drop hits for anonymous users who picked one up.
- **It applies to both HTML documents and `__data.json`**, because authenticated SPA navigation fetches the latter, not the former (see the [guarantee](#the-contributor-freshness-guarantee)).
- **Kiosk bypass closes both leak directions**: a kiosk request can neither read a public entry nor write a kiosk-audience entry under a public key. (Public responses never carry `Set-Cookie: mode=…`, so the public cache can't pick it up either.)

## The contributor-freshness guarantee

Requirement: a contributor who edits a record **must** see their own change on next view. Other users seeing the old value until the staleness window expires is acceptable.

Contributors are authenticated, so they carry `sessionid` on every request — Django's default cookie (host-only, path `/`, only `SAMESITE=Lax` customized), sent to the whole site origin since Caddy fronts both Node and Django under one domain. The bypass rule turns "authenticated" into "always origin", which reaches the contributor on **every** return path:

- **Hard reload** → HTML document request carries `sessionid` → edge bypass → fresh SSR render.
- **SPA navigation** (the default post-save path: [`save-claims-shared.ts`](../../../frontend/src/lib/components/pages/record/edit/editors/save-claims-shared.ts) calls `invalidateAll()` then `goto()`) → `__data.json` request carries `sessionid` → edge bypass → fresh load data.

End to end: `PATCH` commits → server data cache busted on commit → `invalidateAll()` → `__data.json` to origin _with `sessionid`_ → edge bypass → Node SSR → Django (fresh) → contributor sees their edit.

Two header rules form the second half of the guarantee, both about the contributor's **own browser cache**:

- The `private` header on authenticated responses stops the browser caching a stale local copy of an edit after the edge is bypassed.
- Anonymous responses are `max-age=0` (CDN-only; see [the cache rule](#the-cache-rule)). `max-age=0` forces a revalidation that carries `sessionid` and reaches the edge. A browser-cacheable `public, max-age>0` (or browser-facing `stale-while-revalidate`) would reintroduce exactly the staleness this design exists to prevent, via this sequence:
  1. You land on `/titles/foo` **while signed out** → the browser caches the HTML `public, max-age=60`.
  2. You notice an error, sign in, edit it, save.
  3. You navigate back to `/titles/foo` (back button or a link — **not** a hard reload).
  4. With no `Vary: Cookie`, the browser sees a still-fresh cached entry and serves its own anonymous copy without hitting the network. You see your edit missing.

  The bypass can't help here because the request never leaves the browser. `max-age=0` is what guarantees it does. (A contributor who signs in _first_ is never exposed — all their requests carry `sessionid`, so nothing is ever cached locally as `public`. The hole is specific to the anonymous→authenticated transition on a page cached during the anonymous phase.)

**No per-edit purge needed.** Because contributors never read the shared cache, there is nothing to invalidate for them — the hard "purge the CDN on every edit" problem does not arise. Stale shared entries simply age out via `s-maxage`.

## Other requirements

### Simplicity

We are a [small volunteer team](../../SmallTeam.md) with no devops engineers; we want a system we can quickly understand, as few moving parts as possible.

## Options

We chose Bunny:

- Railway has a 🛑 showstopper: it can't cache our system correctly because it can't express the cookie bypass the [cache rule](#the-cache-rule).
- Caddy would be the simplest, but it only offloads render CPU, doesn't edge cache.
- Bunny is the correct long term solution because it edge caches. We nearly didn't do it because of complexity. Now that we've implemented it, I did indeed find the complexity suck hard, but the localhost AI dev assistants were there to keep deploying updates to the system until we got it right. I'm not happy with how complex it is to configure in the Bunny console, but at least AIs are good at inspecting network traffic and debugging.

| Option  | Correct? | Edge | IP-trust | `/api/`                                  |
| ------- | -------- | ---- | -------- | ---------------------------------------- |
| Caddy   | ✅       | ❌   | ✅       | ✅ (`/api/` already a separate `handle`) |
| Bunny   | ✅       | ✅   | ❌       | ✅ pass-through rules                    |
| Railway | 🛑       | ⚠️   | ✅       | ⚠️ `private`/`no-store`                  |

### Caddy

An HTTP cache module ([Souin / `cache-handler`](https://github.com/caddyserver/cache-handler)) compiled into the Caddy that already fronts the container, caching responses in-process behind Railway's edge.

Pros:

- It leaves the IP-trust chain untouched because it sits _behind_ Railway's edge.
- There is no service-wide `/api/` exposure to audit, since the cache directive wraps only the Node `handle` (with `/api/` and `/djadmin/` already separate `handle`s in the [Caddyfile](../../../Caddyfile)).
- It expresses the [cache rule](#the-cache-rule) exactly, with the strong contributor guarantee and full kiosk bypass. The bypass is a native Caddy request matcher, not a cache-module feature: match `Cookie` against `sessionid|mode=kiosk`, route those straight to Node, and run the cache only for cookie-less requests.
- It's Infrastructure as Code (IaC): the correctness rules are in the repo; we can version it; we can have AIs reason about it and guide us.

Cons:

- It offloads origin **CPU only, not the edge**: a HIT skips re-rendering Node/Django, but every request still travels to and terminates at the single Virginia container — no latency win for distant users, no spike absorption.
- We have to build a custom Caddy. The stock Caddy binary cannot be used. This adds an `xcaddy` build step.
- The cache is container-local: cold after each deploy and not shared if the service ever scales to multiple replicas.

When to choose:

The conservative pick when the launch risk is render cost, not a connection spike.

### Bunny

A Bunny CDN pull zone on the site origin (apex), pulling from Railway — caching HTML at Bunny's geo-distributed edge.

Pros:

- We have an existing relationship with Bunny. Bunny already serves `static.flipcommons.org` and `media.flipcommons.org`.
- It absorbs load at the edge: geo-distributed, so cached HTML is served near the user and spikes are soaked up before it reaches the single container.
- Bunny has a POP in Chicago, where the museum is and many users are. It was chosen for static assets partly because of that.
- Bunny has 100+ POPs whereas Railway CDN has 4.
- It expresses the [cache rule](#the-cache-rule) exactly via Edge Rules that bypass on a cookie condition, so the strong contributor guarantee and full kiosk bypass both hold. Bunny's `CookieValue` Edge Rule trigger matches a named cookie within the `Cookie` header, so the `sessionid` and `mode=kiosk` bypasses are directly expressible.

Cons:

- A new outermost hop forces IP-trust re-derivation
  - Bunny sits _in front of_ Railway's edge, so the client IP arrives via Bunny and the `X-Real-IP`/`Forwarded`/`RATE_LIMIT_TRUST_PROXY_HEADERS` chain ([ClientIpTrust.md](../devops/ClientIpTrust.md)) must be re-derived so rate limits and IP logging see the true client — the prerequisite [StaticAssetCDN.md](StaticAssetCDN.md) deliberately avoided by scoping Bunny to a static subdomain.
- It exposes the origin
  - Edge absorption and the IP-trust fix both depend on the Railway origin being unreachable except through Bunny, but Railway keeps a public `*.railway.app` hostname that is awkward to lock down — so an attacker can hit the origin directly, bypassing rate limiting and, because the origin now trusts Bunny's forwarded client IP, spoofing that IP. Caddy adds no new front door to lock.
- `/api/` and `/djadmin/` now flow through Bunny
  - This means they need explicit pass-through Bunny Edge Rules
- Correctness logic lives off-repo
  - The cookie bypass protects both the contributor guarantee and the kiosk licensing-leak, but as Edge Rules configured by hand in the Bunny console (consistent with how the other pull zones are managed) it is unversioned, outside PR review and untested in CI, where a silent misconfiguration could leak licensing-gated content or serve contributors stale. Whereas Caddy's matchers live in the [Caddyfile](../../../Caddyfile), reviewed and testable.
  - Bunny's first-party Terraform provider, `BunnyWay/bunnynet`, _could_ bring these rules in-repo if that risk ever bites, but was judged not worth the added moving parts because we'realready configuring the other pull zones by hand.
- Bunny becomes a whole-site single point of failure
  - Fronting the apex puts Bunny in the critical path of the dynamic site, not just assets, so a Bunny incident takes the whole site down with DNS-propagation-delayed failback. Caddy lives in the container you already depend on.
- It dilutes the cache across PoPs
  - Geo-distribution helps hot pages but hurts the long tail, since each PoP caches independently — a rarely-viewed record fetched from two regions is two origin misses where a single Caddy cache would serve the second as a HIT. Mitigable with Bunny's tiered/origin-shield caching, at the cost of more config and some of the latency win.
- It is bandwidth-priced
  - Caddy and Railway's CDN are free; Bunny bills per byte/request — small for HTML, but nonzero.

When to choose:

When the launch risk is a real traffic or connection spike, or global latency matters — and the IP-trust and origin-locking work is acceptable.

### Railway

Railway's [built-in CDN](https://docs.railway.com/networking/cdn) — a per-service toggle, free, off by default, caching at Railway's own edge. HTML caching is opt-in (mode **Auto** caches HTML only when the origin sends `max-age`/`s-maxage`; **Force**; **Never**).

Pros:

- It is free on all plans, one toggle, no new vendor — fully integrated.
- It adds no new hop and no IP-trust work: it _is_ Railway's own edge, already the outermost hop and trust anchor.
- It absorbs load at the edge, like Bunny: Railway routes through a multi-region Anycast edge — though that edge is coarse (see con below).
- It respects origin `Cache-Control` (`max-age`, `s-maxage`, `stale-while-revalidate`, `stale-if-error`) and excludes any response carrying `no-store`, `private`, `Set-Cookie` or `Vary: Cookie`.

Cons:

- Its cache key is **cookie-blind** ("Cookies aren't part of the cache key"), and the only request-side bypass is the `Authorization` header, which this app does not use (session-cookie auth, no JWT). So a contributor's request to a URL with a cached anonymous entry is served that entry, and the exact [contributor guarantee](#the-contributor-freshness-guarantee) cannot be expressed. The best achievable is fresh on the post-save SPA navigation (if `__data.json` is marked `private`/`no-store`) but **stale up to `max-age` on a hard reload**, with no per-edit fix — purging is manual or auto-on-deploy only, no per-URL API, ~10s propagation.
- It fronts `/api/` too (service-wide toggle), so every non-public response must be audited to set `private`, `no-store` or `Set-Cookie`. `Cache-Control: no-cache` is **not** sufficient (it is not on Railway's block list), so the catalog reads' current `no_cache=True` would not keep them out of the shared cache. The filtered-facets live path already sets `Vary: Cookie` and is safe; other endpoints are not audited.
- Its edge is only **four anycast locations** — US West (California), US East (Virginia), Europe West (Amsterdam) and Asia Southeast (Singapore) — with **no Chicago or US Midwest PoP**. Bunny has 100+ PoPs (including Chicago), so the edge-absorption and global-latency advantage is far smaller than Bunny's. And since the origin is already the Virginia container, Midwest/East users hit Virginia either way and get **no geo-latency win** — Railway's edge here buys spike/connection offload at Virginia, not proximity. ([edge-networking docs](https://docs.railway.com/networking/edge-networking))
- Kiosk is only half-protected: with no cookie bypass, emitting `private`/`no-store` on kiosk-audience responses stops the public from being served licensed content (mandatory), but nothing stops the kiosk terminal from being served a cached public copy on a HIT (the request never reaches the origin), so it would intermittently show the de-licensed public view. Fixing that needs a key-changing kludge — a kiosk-only query param/path (only if Railway keys on the query string; unverified) or an `Authorization` header on kiosk requests.

When to choose:

Only if the weaker freshness bound (stale on hard reload) is acceptable and the `/api/` audit is done — when zero cost and zero new infra outweigh the exact contributor guarantee.
