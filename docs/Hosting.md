# Deployment & Hosting

This document is the reference for how production is hosted, configured and deployed.

For the request-routing diagram and the rest of the runtime picture, see [Architecture.md](Architecture.md#topology).

## Services

### Overview

- [Railway](#railway): web & db hosting
- Bunny.net: [CDN edge caching](#cdn) and [DNS](#dns)
- [Joker](#dns): domain registration
- [iDrive e2](#idrive-e2): media storage
- [WorkOS](#workos): authentication
- [Sentry](#sentry): error & uptime monitoring
- [PostHog](#posthog): analytics

### Railway

Railway hosts the project as two services:

- **Web** — one container running Caddy, SvelteKit Node SSR and Django/Gunicorn (see [Process model](#process-model)).
- **Postgres** — managed database; Railway injects `DATABASE_URL`. Point-in-time recovery (PITR) is attached to the Postgres service; it restores the database to any timestamp.

Both are in region US East (Virginia); see [Geography](#geography).

#### Process model

The web container runs three long-lived processes:

- **Caddy** on Railway's public `PORT`
- **Django/Gunicorn** on `127.0.0.1:8000`
- **SvelteKit Node SSR** on `127.0.0.1:3000`

SSR's own API calls go **through Caddy**, not straight to Gunicorn: `INTERNAL_API_BASE_URL` is `http://127.0.0.1:$PORT`, and Caddy's `@django` matcher forwards them on. Gunicorn's sync worker closes the connection after every response, and Node 24's bundled undici crashes the process when a large enough response body is still buffered as that FIN arrives ([#726](https://github.com/The-Flip/flipcommons/issues/726)). Caddy holds the Node-facing connection open, which removes the trigger. It does not remove the underlying defect — Node still dies if any upstream closes on it mid-body — so [`backend/tests/test_ssr_api_route.py`](../backend/tests/test_ssr_api_route.py) pins the routing, and giving each process its own restart domain (below) is what would make such a crash survivable.

The entrypoint is [`scripts/start-production`](../scripts/start-production); it starts all three and keeps the container alive while they are all healthy. Supervision is intentionally simple: there is no in-container restart policy, so when any child exits, the entrypoint kills the other two and the container exits with it. A deliberate bootstrap-phase choice — simple and fails closed, but not a full supervisor.

**Do not assume Railway restarts the container after that.** On 2026-08-17 the SSR process died on an uncatchable assertion inside Node's bundled undici — raised from a socket event handler while reading a response from Django, so no application `try`/`catch` could intercept it — the container exited, and the deployment stayed down for hours. The service was already configured `ON_FAILURE` with 10 retries at the time. Treat a single process crash as a full outage of indeterminate length until that changes.

Those restart settings are declared in [`railway.toml`](../railway.toml). The budget they describe is **cumulative across a deployment's whole life and never resets on healthy running**, so a deployment stops for good on its eleventh crash no matter how far apart those crashes are. Recovery then needs a _redeploy_ — a restart re-enters the same exhausted deployment and does nothing.

Changing it means giving each process its own restart domain. The shape that fits the platform is one process per service — Caddy holding the public domain and reverse-proxying to Django and the SSR server over private networking — since Railway restarts a single-process service natively and has no path-based routing across services on one domain, which is why the proxy has to be a service rather than a platform setting. Keeping everything in one container instead means adopting a real supervision layer such as `s6-overlay`, which also reaps the orphaned processes that a shell entrypoint running as PID 1 leaves as zombies. What does not work is hand-rolling the supervision in that shell script: the failure modes it has to handle — draining on `SIGTERM`, distinguishing a crash loop from a flaky child, reaping grandchildren that still hold a listening socket — are the ones an init system exists to solve.

#### Build & deploy lifecycle

Every push to `main` triggers a build and deploy:

1. **Docker multi-stage build**: Stage 1 installs frontend dependencies and
   builds the SvelteKit Node server. The final image contains the built
   Svelte runtime, Django, and Caddy in one container.

2. **Pre-deploy checks and migrations**: Railway's `preDeployCommand`
   runs `manage.py check --deploy && manage.py migrate` before the new
   container accepts traffic. `check --deploy` surfaces production-only
   system checks (SSL redirect, `core.W001` for missing
   `RATE_LIMIT_TRUST_PROXY_HEADERS`, `core.E301`/`core.E302` for missing or
   malformed `ALLOW_SEARCH_ENGINE_INDEXING`, etc.); Error-level findings fail the
   deploy, Warning-level findings are visible in logs but non-blocking.
   If anything in the pre-deploy command fails, the old container keeps
   serving.

   For the philosophy behind our deploy safeguards (refuse-don't-warn,
   two refusal phases), see [DeployAutomation.md](DeployAutomation.md).
   For adding new checks: [BuildChecks.md](BuildChecks.md) for the
   build phase (Dockerfile, sourcemap upload, build-time secrets),
   [DeployChecks.md](DeployChecks.md) for the preDeploy phase (Django
   system checks).

3. **Health check**: Railway probes `healthcheckPath` and holds the new container out of rotation until it answers 200, up to `healthcheckTimeout`. A container that builds and migrates but can't serve therefore never takes traffic — the old one keeps serving until the probe gives up. The path is SvelteKit's `/__health`, not Django's `/api/health`; [railway.toml](../railway.toml) records why that distinction decides whether the probe survives `ALLOWED_HOSTS`.

   This gates the release only. Railway stops probing once the deployment is live, so continuous liveness monitoring of the running site is the Sentry uptime monitor's job, hitting the same endpoint from outside.

The contributor-facing deploy workflow (branch → PR → merge → live) and rollback are in [CONTRIBUTING.md](../CONTRIBUTING.md).

#### Deploy version stamping

The SvelteKit build reads `RAILWAY_GIT_COMMIT_SHA` and writes it into `version.json`; the SPA polls that file hourly and, on a detected change, swaps the next client-side navigation for a full page reload. That's how an open browser tab picks up new JS (and drops in-memory caches) after a deploy without disrupting the user mid-task.

Railway auto-injects `RAILWAY_GIT_COMMIT_SHA` as a Docker build arg for any deploy triggered from GitHub — no service-side configuration required, just the `ARG RAILWAY_GIT_COMMIT_SHA` declaration in the [Dockerfile](../Dockerfile). Outside Railway (local `docker build`), the arg falls back to `dev` and version polling is disabled. The `version.json` in the built image (`/app/frontend_runtime/build/client/_app/version.json`) is the ground truth for which SHA was stamped.

#### Provisioning a new Railway environment

The site already runs as a single Railway service; you only need this to stand up a fresh environment (staging, disaster recovery):

1. Create a new evironment in Railway
2. Add a **Postgres** plugin; Railway sets `DATABASE_URL` automatically.
3. Set the environment variables above.
4. Connect a branch of the GitHub repo — Railway auto-detects the `Dockerfile` via `railway.toml`.
5. The environment should automatically deploy when you connect the branch.
6. Grant the first admin: sign in through WorkOS to create your user, then run `uv run python manage.py grant_admin you@example.com` in the Railway shell (or via `railway run`). `createsuperuser` can't help — the admin password form is disabled, so it only produces a row that can never sign in.

### CDN

Bunny.net pull zones:

- [`flipcommons.org`](#apex-edge-cache), origin: Railway web container.
- [`media.flipcommons.org`](#media-edge-cache), origin: [iDrive e2](#idrive-e2).

Both zones require TLS 1.2 or higher and verify the origin certificate.

Every zone setting below lives in the Bunny dashboard: unversioned, unreviewed, and invisible to the test suite, which terminates at or below Caddy. [`backend/edge_tests/`](../backend/edge_tests/) is a read-only suite that runs against the live site instead — never part of `make test`:

```bash
make test-edge                                     # against https://flipcommons.org
EDGE_BASE_URL=https://example.org make test-edge   # somewhere else
```

Run it after deploying a change to the Caddyfile, [cache-control.server.ts](../frontend/src/lib/cache-control.server.ts) or Django's middleware stack, and after editing anything in the Bunny dashboard, which no deploy accompanies. It covers liveness, conditional GET, the three bypass rules, the origin lockdown and the apex pull zone's identity. It only sees what came back to the client; the origin's side of the same request is in [production_logs/](../production_logs/README.md), where a run's rows are marked `is_synthetic`.

#### Apex edge cache

The Bunny.net apex pull zone, `flipcommons.org`, fronts the Railway web container at `flipcommons-production.up.railway.app`. Configuration:

- **API and admin bypass**: bypass `/api/` and `/djadmin/`, except `/api/public/`
- **authenticated bypass**: for any authenticated request (carrying a `sessionid` **cookie**) or a request from a museum kiosk (`mode=kiosk` **cookie**), bypass everything but static assets, such as HTML
- respect origin `Cache-Control`
- include URL query string in cache key
- serve stale content while revalidating and while the origin is offline
- cache error responses for 5 seconds
- retry an origin request once, but only when the connection never opened

The bypasses are three separate Edge Rules. "Bypass API" keys on URL alone: a **Match any** URL trigger for `*/api/*` and `*/djadmin/*` and a **Match none** URL trigger for `*/api/public/*`, with trigger matching set to **Match all**. "Bypass signed-in HTML" and "Bypass kiosk HTML" each pair their cookie trigger with a **Match none** URL trigger listing `*/_app/*`, `*/fonts/*`, `*/images/*`, `*/apple-touch-icon.png` and `*/site.webmanifest`. The two cookie triggers are different trigger types — Request Header versus Cookie Value — so they cannot share one rule. The Match none carve-out is the whole point: a single cookie-keyed bypass sends a signed-in visitor's roughly 100 asset requests to the origin on every page load. `make test-edge` asserts both directions; by hand:

```bash
curl -sSI -H 'Cookie: sessionid=x' https://flipcommons.org/_app/version.json | grep -i cdn-cache   # HIT or MISS, never BYPASS
curl -sSI -H 'Cookie: sessionid=x' https://flipcommons.org/about | grep -i cdn-cache               # BYPASS
```

The cookie bypasses match cookies, not query strings. `mode` is only ever a cookie — set by "Enter Kiosk Mode" and read server-side ([kiosk/config.ts](../frontend/src/lib/kiosk/config.ts)); nothing reads it from the URL. So `/?mode=kiosk` is an ordinary anonymous request and is cached as one, which is correct. Probe a bypass with the cookie, not the query string:

```bash
curl -sSI 'https://flipcommons.org/?mode=kiosk' | grep -i cdn-cache   # HIT — cookie-less, cached
curl -sSI -H 'Cookie: mode=kiosk' https://flipcommons.org/ | grep -i cdn-cache   # BYPASS
```

`make test-edge` asserts both. A kiosk render that gets cached is served to the public as unlicensed content, and nothing else in the system would notice.

Bunny rewrites `Cache-Control` to `public, max-age=0` on every rule-bypassed response, discarding the origin's `private, no-cache` / `private, no-store`. The `Cache-Control` bullet above applies to cached and MISS responses; bypassed ones are re-stamped by the edge.

**Stale Cache** — both While Updating and While Origin Offline are on; neither exposes a duration. While Updating serves the expired copy and refreshes behind it, so an expiry never costs a visitor a full origin round trip. While Origin Offline keeps the last good copy on screen through a Railway restart. Bunny warns that While Updating will **not** refresh an object when the origin's fresh response is non-cacheable, so a URL whose policy changes to `no-store` goes on serving its stale copy until the original TTL runs out — any deploy that changes cache policy must purge.

**Cache Error Responses** is on. Bunny holds 4xx and 5xx for a fixed 5 seconds, not configurable, which absorbs probe bursts for nonexistent asset hashes and collapses Caddy-level 502s while Node restarts. It also holds the public API's per-IP `429`, so one caller's verdict can be served to others at the same PoP for those 5 seconds.

**SafeHop** is on with one retry, no delay, and **Connection Timeout** as the only retry reason. A connection that never opened never reached the container, so re-sending is safe for every method, and a container restart is exactly the failure it covers. **Response Timeout** and **Origin 5xx** stay off: this zone passes bypassed `/api/` POSTs to Django, Bunny documents no exemption for non-idempotent methods, and a write that reached Django and then exceeded the 60-second response timeout would be submitted twice. Media upload is the one request that can plausibly run that long, and a duplicated upload is worse than a 502.

**Request Coalescing is deliberately off.** Bunny coalesces any uncached request, and bypassed signed-in `__data.json` responses are per-user, so two contributors at one PoP could be served each other's payload.

Because the zone respects origin `Cache-Control`, any response that reaches Bunny without one inherits the pull zone's 30-day default. So every response leaving the container carries an explicit header. The SvelteKit hook ([cache-control.server.ts](../frontend/src/lib/cache-control.server.ts)) stamps everything it sees, with `private, no-store` for anything that is not a successful page or a permanent redirect. Django stamps `/api/public/` ([cache_control.py](../backend/apps/core/cache_control.py)) and the sitemap; every other Django response falls through to Caddy's default. [Caddyfile](../Caddyfile) is the backstop for what neither stamps, because it is the only layer that sees every response:

| Path                                                                  | `Cache-Control`                        | Why                                                                                                       |
| --------------------------------------------------------------------- | -------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| anything still unstamped (site-level `?` default)                     | `private, no-store`                    | prerendered pages such as `/privacy` are served by Node on every request rather than frozen for 30 days   |
| `/images/*`, `/apple-touch-icon.png`, `/site.webmanifest`, `/fakes/*` | `public, max-age=3600, s-maxage=86400` | unfingerprinted files replaced in place; a day at the edge bounds staleness without a purge               |
| `/fonts/*`                                                            | `public, max-age=31536000, immutable`  | stable bytes; a changed font must be renamed                                                              |
| `/_app/env.js`                                                        | `public, max-age=0, s-maxage=60`       | carries the Sentry release tag; SvelteKit answers it before its hooks run                                 |
| `/_app/immutable/*`                                                   | `public, max-age=31536000, immutable`  | set by adapter-node's static handler on 200s, not by Caddy: content-hashed, so a wrong copy is impossible |
| `/_app/version.json`                                                  | `public, max-age=60`                   | the deploy poll                                                                                           |
| `/__health`                                                           | `no-store`                             | uptime probes must see the origin's current state                                                         |
| the 502 Caddy writes itself when it cannot dial Node or Gunicorn      | `no-store`                             | written outside the deferred header wrappers, so `handle_errors` stamps it separately                     |

Every matcher-bound `Cache-Control` line in the Caddyfile, the gate's 403 and the redirect included, uses Caddy's deferred `>` form. Two reasons: Caddy's value then replaces a header the hook also set rather than stacking beside it, and a deferred op replaces a plain one that ran earlier, so a plain `no-store` on the 403 would be overwritten by the font policy on a font URL and a PoP that pulled it during a secret rotation would cache the 403 for a year. The cost is that a 404 on one of the unfingerprinted paths is cached for the path's TTL, which only bites during a rename. [test_caddyfile_cache_backstop.py](../backend/tests/test_caddyfile_cache_backstop.py) pins the default, the form and that every file under `frontend/static/` has a policy.

**Changing a cache header is not retroactive.** Bunny consults the origin header only when it pulls, so a PoP holding an object keeps serving it for the remainder of the TTL it was cached under. After deploying a `Cache-Control` change, [purge](https://docs.bunny.net/cdn/purge-cache) the affected URL from the pull zone — otherwise the old policy survives up to its original expiry, unevenly across PoPs as eviction pressure varies. Confirm with `curl -sSI https://flipcommons.org/__health`: a `cdn-cache: HIT` still reporting the previous `Cache-Control` means the purge hasn't landed.

The origin-side cache contract is described in [Architecture.md](Architecture.md#edge-caching-of-ssr-html). The client-IP and origin-locking prerequisites for fronting the apex are under [Client IP trust](#client-ip-trust).

**www redirect**: `www.flipcommons.org` is a hostname on this zone with an Edge Rule that 301s it to the apex, carrying the path and query string. The rule is what makes the hostname safe to serve: Bunny's cache key excludes the hostname, so without it a `www` request for an already-cached path would be answered with the apex page under the `www` host.

#### Media edge cache

`media.flipcommons.org` fronts the iDrive e2 media bucket. Respects origin cache headers. POST is blocked at the edge, so every request that reaches the bucket is a GET.

Resilience settings mirror the apex, with one difference that follows from the zone being read-only:

- **Stale Cache** — While Updating and While Origin Offline both on, so an expired image is served immediately and refreshed behind the visitor, and an iDrive outage keeps already-cached images on screen instead of surfacing as broken images.
- **Cache Error Responses** on — a burst of requests for a missing object becomes one bucket request per 5 seconds instead of one per request.
- **SafeHop** on with one retry, no delay, and all three reasons ticked: Connection Timeout, Response Timeout and Origin 5xx. The apex keeps the last two off because it carries writes; this zone cannot, so retrying is always safe.

#### Rate limiting

Rate limiting is configured in the Bunny dashboard (not in code). The goal is to blunt badly behaved bots; `robots.txt` covers the polite ones.

| Zone                    | Rule Name | Scope                                        | Limit                           | Block |
| ----------------------- | --------- | -------------------------------------------- | ------------------------------- | ----- |
| `flipcommons.org`       | `Default` | everything except immutable assets and fonts | 100 requests / 10 seconds / IP  | 60 s  |
| `flipcommons.org`       | `Assets`  | `/_app/immutable/` and `/fonts/`             | 1000 requests / 10 seconds / IP | 60 s  |
| `media.flipcommons.org` | `Default` | all                                          | 300 requests / 10 seconds / IP  | 60 s  |

Counter Key = IP address and Response Action = `RateLimit` on all of them. The apex pair are `REQUEST_URI` regex rules with the `LOWERCASE` transformation, written as exact complements — `Default` matches `^/(?!_app/immutable/|fonts/)` and `Assets` matches `^/(_app/immutable/|fonts/)` — so every path is counted by exactly one rule, with no gap and no double-counting.

The split exists because a cold page load fires roughly 100 asset requests, which would trip a single 100/10s counter on real visitors rather than on bots. A cold load makes fewer than 20 immutable requests, so the page tier keeps its strength as a bot throttle, while 1000/10s still bounds asset abuse such as hash-guessing probes at about ten cold page loads per 10 seconds from one address.

**Bunny allows only two rate-limit rules per zone.** A future path tier has to fold into one of these two regexes rather than becoming a third rule.

Changing either regex is worth verifying from the edge logs rather than by a burst test, since a pattern the engine rejects fails silently — the rule stops matching anything and the zone quietly loses its limit. Both directions are visible in one query: blocks should continue on the paths a rule still covers and stop on the paths it now excludes.

```bash
production_logs/query "SELECT ts::DATE AS day, CASE WHEN path LIKE '/_app/immutable/%' THEN 'immutable' WHEN path LIKE '/fonts/%' THEN 'fonts' ELSE 'other' END AS bucket, count(*) FROM bunny_requests WHERE zone='apex' AND status=429 GROUP BY 1,2 ORDER BY 1,2"
```

Media's ceiling is higher because one gallery page legitimately fires dozens of image requests in a burst.

This is edge abuse control, separate from the application rate limits under [Client IP trust](#client-ip-trust): Shield counts on Bunny's own view of the connecting IP, so it neither depends on nor affects the `X-Client-IP`/`X-Origin-Auth` chain.

Operational caveats:

- Limiting per-IP means a shared NAT -- such as a fixed wireless operator like Verizon 5G Home that puts all their traffic behind a pool of IPs -- could trip a limit as one "client".
- Enforcement propagates across PoPs, so a burst can leak a few requests past a freshly tripped block

### DNS

[Joker](https://joker.com) holds the domain registration; Bunny hosts the DNS zone on `kiki.bunny.net` and `coco.bunny.net`.

#### Apex `PZ` record

The apex is a Bunny `PZ` (Pull Zone) record bound to the apex pull zone, not an `A`, `CNAME` or `ALIAS`. Bunny flattens it to `A`/`AAAA` inside its own network at query time, so the edge is chosen for the visitor's resolver and can never be a stale address.

- **The record names a pull zone by id.** Pointing it at a new pull zone yields valid Bunny addresses that pass every DNS check while silently dropping the origin config including **Forward Host Header**, the cache bypasses, the certificate and the `X-Client-IP` / `X-Origin-Auth` Edge Rules that rate limiting depends on (see [Client IP trust](#client-ip-trust)). Verify with `curl -sSI https://flipcommons.org/__health`: `cdn-pullzone` must match the existing apex zone, and the certificate must be the pre-existing one rather than freshly issued. `make test-edge` asserts the `cdn-pullzone` half; the certificate still needs an eye.
- **Bunny sets the TTL, not us.** The record's TTL field is not honored; Bunny serves its own short value. This costs nothing, because the flattened address is anycast — edge failover happens in BGP, not DNS.

Bunny omits `PZ`, `RDR` and `SCR` records from its zone exports, so **a Bunny export is never a complete backup of this zone.**

#### DNS Records

| Name                   |  Type | Purpose                                                        |
| ---------------------- | ----: | -------------------------------------------------------------- |
| `flipcommons.org`      |    PZ | Site — apex pull zone                                          |
| `flipcommons.org`      |    MX | Mail (`10 mx1`, `20 mx2` at `mailcast.io`)                     |
| `flipcommons.org`      |   TXT | SPF, plus two Google Search Console proofs                     |
| `_dmarc`               |   TXT | DMARC                                                          |
| `mailcast._domainkey`  | CNAME | DKIM key 1                                                     |
| `mailcast2._domainkey` | CNAME | DKIM key 2 — rotation pair with the above                      |
| `www`                  | CNAME | Apex pull zone; redirected to the apex by an Edge Rule         |
| `media`                | CNAME | Media pull zone (iDrive origin)                                |
| `auth`                 | CNAME | WorkOS custom auth domain — **login breaks if this is missed** |

No wildcard: unknown names must return `NXDOMAIN`. No DNSSEC and no CAA.

### iDrive e2

S3-compatible object store for uploaded media, in Chicago (see [Geography](#geography)). Django reads and writes it via the `MEDIA_STORAGE_*` env vars; public traffic reaches it through `media.flipcommons.org` (Bunny → iDrive). See [Media.md](Media.md).

### WorkOS

The only login surface — the Django admin password form is disabled. Configured via the `WORKOS_*` env vars. Authentication flow, session model and the authorization contract are in [Authz.md](Authz.md).

### Sentry

We use [Sentry.io](https://sentry.io) for production error monitoring. See [Observability.md](Observability.md) for the contract (what we capture, privacy posture, code wiring).

#### Projects

In Sentry, we have two projects:

- `flipcommons-backend`: Python/Django
- `flipcommons-frontend`: JavaScript/SvelteKit — both SSR and browser report here

#### Sentry env vars

Local, CI, and test environments leave these unset. The empty-DSN guard at SDK init is the master switch.

- `SENTRY_DSN` — backend runtime. Backend project DSN. Empty = Sentry off (master switch).
- `PUBLIC_SENTRY_DSN` — frontend SSR + browser runtime. Frontend project DSN. Empty = Sentry off (master switch).
- `SENTRY_AUTH_TOKEN` — frontend build (Docker `ARG` → `ENV`). Org-scoped, secret. The only Sentry value that's actually secret; DSNs are public-by-design write-only keys. Required for sourcemap upload.
- `SENTRY_ORG` — frontend build. Org slug. Required for sourcemap upload.
- `SENTRY_PROJECT` — frontend build. `flipcommons-frontend`. Required for sourcemap upload.

All three `SENTRY_*` build-time vars are declared as `ARG`s in the frontend build stage of the [Dockerfile](../Dockerfile) and `ENV`-promoted before `pnpm build` — multi-stage Docker doesn't inherit host env vars into build stages, and forgetting one silently produces a build with no sourcemaps uploaded.

#### Privacy scrubbing (dashboard)

This part of our [Privacy.md](Privacy.md) contract is manually configured on the Sentry website:

**Advanced Data Scrubbing** (Project Settings → Security & Privacy → Advanced Data Scrubbing). These are part of the privacy contract — without them, emails or IPs interpolated into log messages, or query strings carrying user input, would be stored.

- `[Mask] [@email] from [$string]`
- `[Mask] [@ip] from [$string]`
- `[Remove] [$request.query_string]`

#### Alert rules (dashboard)

Mirrored across both projects:

- **New issue** → alert all maintainers
- **Regression of a resolved issue** → alert all maintainers
  Default issue assignment: **unassigned**. Either founder may grab an issue.

#### Per-maintainer routing

Each maintainer is an org member with their own destination (email or chat). Adding or removing a maintainer is a single membership change. Production alerts go to all maintainers as co-responders.

#### Sourcemaps

`@sentry/vite-plugin` (wrapped by `sentrySvelteKit`) uploads at build time, tagged with `RAILWAY_GIT_COMMIT_SHA`. The plugin's `sourcemaps.filesToDeleteAfterUpload` is configured explicitly so maps don't ship to browsers (the plugin doesn't delete by default).

### PostHog

Product analytics — pageviews only. Enabled in prod by setting `PUBLIC_POSTHOG_KEY`; an empty key is off (same master-switch pattern as Sentry). Surface area and privacy posture are in [Analytics.md](Analytics.md).

## Geography

The Flip pinball museum and many editors and end users are in Chicago. Hosting reflects that:

- The Railway-hosted website is in Virginia. Railway does not have a Chicago presence.
- The iDrive e2 media storage is in Chicago to optimize for cold reads through the Bunny.net CDN.

## Networking

The edge proxy chain is `Browser →(HTTPS)→ Railway edge →(HTTP)→ Caddy →(HTTP loopback)→ Django`, with Bunny outermost in front of the apex. TLS terminates at the edge, so **Caddy is the trust boundary**: it strips attacker-controlled headers, reconstructs the real client IP, and emits edge-only response policy. Django sees plaintext loopback and trusts only what Caddy hands it. The two policies that follow from this:

### Client IP trust

Pre-auth rate limiters (signup flow, etc.) key off the caller's IP. Because Django sits behind two layers of proxy (Railway's edge, then Caddy), `REMOTE_ADDR` is always `127.0.0.1` — the real client IP has to come from a forwarded-header. Getting this right is security-relevant: a wrong choice silently makes IP-keyed rate limits either non-functional (every request shares one bucket) or bypassable (an attacker varies the header to spray buckets).

#### Header chain

**Railway edge** (before Caddy sees the request):

- Sets `X-Real-IP` to the real client public IP. Client-supplied values are overwritten; not spoofable.
- Sets `X-Forwarded-For` to Railway's rotating internal IP (a `100.64.0.X` CGNAT address whose last octet rotates per request across Railway's internal proxy fabric). Reading this directly would bucket each request from one client into a different bucket.
- Passes `Forwarded` (RFC 7239) through verbatim — **attacker-controlled** until Caddy strips it.

**Caddy** ([Caddyfile](../Caddyfile)):

- Strips `Forwarded` at site level (`request_header -Forwarded`) — closes the attacker-controlled channel.
- Overwrites `X-Forwarded-For` with the trusted `X-Real-IP` value via `header_up` inside each `reverse_proxy` block. `header_up` is required (not site-level `request_header`) because Caddy's `reverse_proxy` has special handling for `X-Forwarded-*` headers that overrides any site-level mutations — site-level strips of XFF were verified empirically to be ignored. If `X-Real-IP` is absent (a state Railway never produces in practice), XFF becomes empty string; the deployment contract is that `X-Real-IP` is always populated at the proxy boundary.

**Django** ([\_client_ip](../backend/apps/core/rate_limits.py)):

- Reads `X-Real-IP`. Never reads `X-Forwarded-For` — XFF parsing (left-most vs. right-most, trusted-hop counting) has no failure mode that's safe under upstream drift; `X-Real-IP` fails closed if absent.

#### Trust gate (`RATE_LIMIT_TRUST_PROXY_HEADERS`)

Django's `_client_ip` only reads proxy headers when `RATE_LIMIT_TRUST_PROXY_HEADERS=true`. The setting defaults to `false`, so dev, tests, and any container without a sanitizing proxy in front key off `REMOTE_ADDR=127.0.0.1` and degrade to "everyone shares one bucket" — observable, fixable, not a security bug.

**Production must set `RATE_LIMIT_TRUST_PROXY_HEADERS=true`.** The trust assumption (Caddy has stripped `Forwarded`, Railway has populated `X-Real-IP`) is a deployment contract.

This is the second fail-closed layer behind the X-Real-IP-only header choice. Both layers protect against the same drift: if the env var rolls back, or a future upstream stops setting `X-Real-IP`, the system degrades to one-shared-bucket rather than silently trusting attacker input.

#### Client IP behind the Bunny apex edge cache

Fronting `flipcommons.org` with the Bunny edge cache adds a **third** proxy hop and makes Bunny the outermost one. Railway's edge then sees Bunny as the immediate client and rebuilds `X-Real-IP` and `X-Forwarded-For` from _its_ view — so both standard headers carry **Bunny's** IP, and the visitor's real IP is absent from them. (Confirmed empirically: through Bunny, `X-Real-IP` is a Bunny edge IP.)

The real client IP is recovered through two Bunny **Edge Rules** that set _request_ headers — custom headers, which Railway forwards to the origin verbatim (unlike the `X-Forwarded-*` headers it rewrites):

- `X-Client-IP` = `%{User.IP}` — the true client IP.
- `X-Origin-Auth` = `<shared secret>` — proves the request came through Bunny.

Caddy ([Caddyfile](../Caddyfile)) then promotes `X-Client-IP` into `X-Real-IP` **only** when `X-Origin-Auth` matches `ORIGIN_SHARED_SECRET`. So `_client_ip` keeps reading `X-Real-IP`, unchanged — it just receives the true client IP behind Bunny. Verified end-to-end on the pull zone (including spoof attempts) before cutover.

#### Origin gate

The same comparison is a hard gate: Caddy answers **403** to any request whose `X-Origin-Auth` does not equal `ORIGIN_SHARED_SECRET`, so a caller that bypassed Bunny also bypassed its cache and rate limits and gets nothing. Two exemptions: SSR's own API calls, which arrive on the loopback interface, and Railway's health probe, matched by `Host: healthcheck.railway.app` together with the `/__health` path. The pairing matters: the Sentry uptime monitor also fetches `/__health`, but through Bunny under the public host, so it has to carry the secret like everything else, and a drifted secret turns that monitor red rather than leaving the site answering 403 behind a green health check. The redirect for the Railway hostname sits ahead of the gate so crawlers that found that host still get a 301 rather than a 403.

The gate fails closed on purpose: the Caddyfile default for an unset variable is a sentinel that matches nothing, so a missing or drifted secret rejects every request from Bunny. Two guards make that a failed deploy rather than an outage — `check --deploy` refuses an unset or malformed value (`core.E305`, `core.E306`) and [`scripts/start-production`](../scripts/start-production) refuses to boot without one — and a wrong-but-well-formed value shows up as the post-deploy 403 curl in the verification steps and, after that, as the uptime monitor. Railway's probe `Host` is documented rather than observed (the probe never appears in Railway's HTTP logs), so a deploy whose health check never passes after a Caddyfile change is the signal that the value changed; the previous container keeps serving meanwhile. [test_caddyfile_origin_gate.py](../backend/tests/test_caddyfile_origin_gate.py) pins the matcher.

#### Verifying the chain

Nothing in the chain fails loudly: if a hop stops carrying the visitor's address, every visitor shares one rate-limit bucket and no request looks wrong. `GET /api/edge/echo/` (staff-only, gated by `Activity.OBSERVABILITY_DEBUG`) returns what Django received — `x_real_ip`, `x_client_ip`, `x_forwarded_for`, whether `X-Origin-Auth` was present (never its value), `remote_addr` and `host`. Through Bunny, `x_real_ip` and `x_client_ip` must both be your own public address and `x_forwarded_for` must equal `x_real_ip`. Probe it before and after any change to the chain — a new cache tier, moving hosts, adding a CDN hop — and treat a Bunny edge address or a `100.64.0.x` address in `x_real_ip` as a regression to revert. `make test-edge` covers the gate's negative cases; the echo endpoint stays manual, since reading it needs a staff session.

Required config for this path:

- **Bunny:** the two request-header Edge Rules above.
- **Railway:** `ORIGIN_SHARED_SECRET` set (matching the `X-Origin-Auth` rule); `RATE_LIMIT_TRUST_PROXY_HEADERS=true`.

`RATE_LIMIT_TRUST_PROXY_HEADERS` stays the master switch here too: if the secret or the Edge Rules drift, Caddy stops promoting `X-Client-IP` and the system degrades to the one-shared-bucket failure above (now keyed on Bunny's IP).

#### When to revisit

- **Moving off Railway, or adding another CDN hop.** The current scheme relies on Railway's edge to populate `X-Real-IP` and strip client-supplied versions of it (and, behind the apex cache, on the Bunny `X-Client-IP`/`X-Origin-Auth` derivation above). Any further change to the proxy chain — different host, Cloudflare in front, enabling Railway's CDN — invalidates those assumptions and needs a fresh re-derivation plus a re-verification probe.
- **A new code path reads `X-Forwarded-For`.** Don't. The function in `apps/core/rate_limits.py` is the single sanctioned reader of forwarded client IP. Adding analytics, geoip, or logging that reads XFF reintroduces the parsing-bug class this design deliberately deleted.

### HSTS

The site has enabled HSTS (HTTP Strict Transport Security). It forces web browsers to communicate with the site using only HTTPS.

HSTS is sticky: once a browser sees `Strict-Transport-Security: max-age=N`, it refuses plain HTTP to that host for `N` seconds, even if the header later shortens or disappears. Shortening it therefore changes nothing for anyone already carrying the longer value, which is why [`backend/tests/test_caddyfile_hsts.py`](../backend/tests/test_caddyfile_hsts.py) pins the exact value rather than merely asserting the header is present.

Caddy emits `max-age=31536000` for the apex, from the `header { ... }` block in [`Caddyfile`](../Caddyfile). Django can't usefully: it sees plaintext loopback HTTP, so `SecurityMiddleware` adds HSTS only when `request.is_secure()` is true, and forcing that via `SECURE_SSL_REDIRECT` would loop on the internal callers — SSR, health checks — that legitimately arrive over loopback. `security.W004`, `W005` and `W021` are silenced in `config/settings.py` for that reason: the absent deploy warnings are the policy working, not a gap to close.

`includeSubDomains` is off so each subdomain owns its own HSTS, preserving room for a future one that is HTTPS-capable but can't emit the header on day 1. Preload is off for a harder reason: submission to [hstspreload.org](https://hstspreload.org/) is irreversible for months regardless of `max-age`, and requires `includeSubDomains` besides.

## Configuration

Set these in the Railway web service dashboard. `DATABASE_URL`, `PORT`, and the `RAILWAY_*` build/runtime vars are injected by Railway automatically (Caddy listens on `PORT`).

### Environment variables

#### Core

- `SECRET_KEY` — random string: `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- `DEBUG` — `false`
- `ALLOWED_HOSTS` — comma-separated hosts, e.g. `flipcommons.org,flipcommons-production.up.railway.app`. The deploy is refused if the Railway origin host is missing.
- `CSRF_TRUSTED_ORIGINS` — full origins, e.g. `https://flipcommons.org,https://www.flipcommons.org`.
- `SITE_ORIGIN` — public origin, no trailing slash, e.g. `https://flipcommons.org`. Baked into prerendered canonical URLs and OG tags; consumed by `/sitemap.xml` and `robots.txt`. [`scripts/start-production`](../scripts/start-production) also passes it to the Node SSR process as `ORIGIN` (without which adapter-node resolves `page.url` from the `Host` header, which varies by caller — Railway's health check, direct hits on the Railway origin hostname — and is absent entirely when prerendering) and mirrors it as `PUBLIC_SITE_ORIGIN` so client-side code can keep SEO URLs on the public origin after hydration. Do not set `ORIGIN` or `PUBLIC_SITE_ORIGIN` in the dashboard — they are derived, and a separately-set value could drift.
- `INTERNAL_API_BASE_URL` — base URL SvelteKit SSR uses to reach Django. Do **not** set this in the dashboard: [`scripts/start-production`](../scripts/start-production) derives it from the runtime-injected `PORT` so SSR goes through Caddy rather than Gunicorn (see [Process model](#process-model)). The entrypoint exports it unconditionally, so a dashboard value is silently ignored rather than honoured — set one and the dashboard and the running process disagree.

#### Auth

WorkOS is the only login surface.

- `WORKOS_API_KEY` — WorkOS secret API key.
- `WORKOS_CLIENT_ID` — WorkOS client ID.
- `WORKOS_REDIRECT_URI` — OAuth callback URL, e.g. `https://flipcommons.org/api/auth/callback/`.

#### Media storage

Set `MEDIA_STORAGE_BUCKET` to serve media from object storage (iDrive e2 behind the Bunny media CDN); omit it to fall back to local `/media/`. See [Media.md](Media.md).

- `MEDIA_STORAGE_BUCKET` — bucket name. Its presence switches storage from local to S3-compatible.
- `MEDIA_STORAGE_ENDPOINT` — S3-compatible endpoint URL (iDrive e2).
- `MEDIA_STORAGE_ACCESS_KEY` — access key.
- `MEDIA_STORAGE_SECRET_KEY` — secret key.
- `MEDIA_STORAGE_REGION` — optional; defaults to `auto`.
- `MEDIA_PUBLIC_BASE_URL` — public media base URL, trailing slash required, e.g. `https://media.flipcommons.org/`. Defaults to `/media/`.

#### Edge & rate limiting

- `RATE_LIMIT_TRUST_PROXY_HEADERS` — `true`, required in production. See [Client IP trust](#client-ip-trust).
- `ORIGIN_SHARED_SECRET` — secret matching the Bunny `X-Origin-Auth` Edge Rule; Caddy rejects every request that does not carry it and trusts the Bunny-forwarded `X-Client-IP` on those that do. Characters from `[A-Za-z0-9_-]` only: the value is substituted into a Caddyfile matcher as raw text, so whitespace, quotes, braces or a leading or trailing `*` would change what the gate compares. `check --deploy` refuses an empty (`core.E305`) or malformed (`core.E306`) value and `start-production` refuses to boot without one. See [Origin gate](#origin-gate).

#### SEO

- `ALLOW_SEARCH_ENGINE_INDEXING` — `true` on prod, `false` elsewhere. See [Search-engine indexing](#search-engine-indexing).

Sentry and PostHog vars live in their service sections: [Sentry](#sentry) and [PostHog](#posthog).

### Server-side cache

Per-user rate limits ([backend/apps/provenance/rate_limits.py](../backend/apps/provenance/rate_limits.py)) use `django.core.cache` as a shared store for sliding-window timestamps (bucket semantics in [Rate Limits](RecordLifecycle.md#rate-limits)). The backend is **file-based** (`FileBasedCache` under `BASE_DIR/cache`), so every Gunicorn worker and management command shares one store through the filesystem — no external cache service required. A per-process backend like `LocMemCache` would break this: each worker would keep its own window, letting a user send `N × limit` requests before any single worker decided to 429.

### Search-engine indexing

`ALLOW_SEARCH_ENGINE_INDEXING` gates SvelteKit's `robots.txt` body. Set `"true"` on prod, `"false"` on every other deployed service. Only the literal `"true"` enables indexing; anything else is off.

`check --deploy` refuses any deploy where the var is unset (`core.E301`) or not exactly `"true"`/`"false"` (`core.E302`) — so a new Railway service needs the var set before its first deploy.

#### The Railway origin hostname is not a second site

`flipcommons-production.up.railway.app` serves the same pages as the apex — the indexing gate reads an env var, not the request host — so crawlers indexed it as a duplicate. `@direct_origin` in [Caddyfile](../Caddyfile) 301s those hits to the public origin. [`test_caddyfile_direct_origin.py`](../backend/tests/test_caddyfile_direct_origin.py) pins it, because deleting the directive breaks nothing that would fail a test.

## Troubleshooting

Every item below starts with reading production logs. [production_logs/](../production_logs/README.md) pulls them from Railway and Sentry and builds a queryable database over them.

**Health check fails after deploy**:
`/__health` is served by the SvelteKit Node runtime and checks Django in turn via an internal `/api/health` call, which runs a `SELECT 1`. So a failing probe means Node is down, Django is down, or the database is unreachable — check the deploy logs for Node or Python startup errors. Common causes: missing `SECRET_KEY`, database connection issues, a bad migration or the SSR process failing to start. Railway will not promote the deployment while this fails, so the previous container stays live.

A probe that fails with **400** rather than a connection error means it reached Django with an external `Host` header and hit `ALLOWED_HOSTS`. That points at `healthcheckPath` having been changed to a Django route — put it back to `/__health`; see [railway.toml](../railway.toml).

**Every request through Bunny returns 403 with `Cache-Control: no-store`**:
The [origin gate](#origin-gate) is rejecting Bunny's traffic, which means `ORIGIN_SHARED_SECRET` on the Railway service and the value the apex zone's `X-Origin-Auth` Edge Rule sends have drifted apart. The Sentry uptime monitor on `/__health` goes red for the same reason, while Railway's own health check stays green because its probe is exempt. Fix whichever side drifted; the 403s carry `no-store`, so nothing needs purging.

**`www.flipcommons.org` fails TLS**:
Bunny terminates TLS for `www` on the apex zone, so a certificate error there is a zone problem and not a Railway one — `www` no longer reaches Railway at all. The hostname needs its own certificate on the apex zone (Bunny issues a free one, but only while DNS already points `www` at the zone) and Force SSL on, matching the other two hostnames.

**Apex returns `ERR_TOO_MANY_REDIRECTS`**:
The apex zone's `X-Origin-Auth` Edge Rule is gone. Bunny's pulls wear the Railway origin hostname, so the header's presence is the only thing keeping them out of `@direct_origin`, which sends them back to a host Bunny fronts. Restore the Edge Rule. The 301 carries `no-store`, so nothing was cached and the repair takes effect immediately.

**Every request returns Railway's `{"message":"Application not found"}`**:
Bunny is sending a hostname Railway does not route. Railway answers this for any `Host` but its own, and the apex zone should be sending exactly that — so either **Forward Host Header** was turned back on, or the zone's origin URL was edited. Compare the zone's origin against the service's `*.up.railway.app` hostname and turn the toggle back off.

**"Frontend build directory not found" error**:
The Docker build's Node stage failed to produce the SvelteKit SSR runtime.
Check the build logs for pnpm/SvelteKit errors, and confirm the final image
contains the built Node output under `/app/frontend_runtime/`.

**Frontend routes 502 or blank pages**:
Caddy may be up while the SvelteKit Node server failed to start or crashed.
Check the container logs for Node startup errors and confirm the SSR process
is listening on `127.0.0.1:3000`.

**Bad migration or failed deploy check**:
`preDeployCommand` runs `check --deploy` and migrations before swapping
containers. If either fails, the old container keeps serving and the deploy
is marked as failed. Fix and push again. Railway does not automatically
roll back the database — if a migration partially applied, you may need to
manually fix it via `railway run`.
