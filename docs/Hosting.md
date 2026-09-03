# Deployment & Hosting

This document is the reference for how production is hosted, configured and deployed.

For the request-routing diagram and the rest of the runtime picture, see [Architecture.md](Architecture.md#topology).

## Services

### Overview

- [Railway](#railway): web & db hosting
- [Bunny.net](#bunny-cdn): CDN edge caching and [DNS](#dns)
- [Joker](#dns): domain registration
- [iDrive e2](#idrive-e2): media storage
- [WorkOS](#workos): authentication
- [Sentry](#sentry): error & uptime monitoring
- [PostHog](#posthog): analytics

### Railway

Railway hosts the project as two services:

- **Web** — one container running Caddy, SvelteKit Node SSR and Django/Gunicorn (see [Process model](#process-model)). Region: US East (Virginia); see [Geography](#geography).
- **Postgres** — managed database; Railway injects `DATABASE_URL`. Point-in-time recovery (PITR) is attached to the Postgres service; it restores the database to any timestamp.

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

### Bunny CDN

Bunny runs the following pull zones:

- [`flipcommons.org`](#apex-edge-cache): anonymous SSR HTML
- [`static.flipcommons.org`](#static-edge-cache): static app assets like `/_app/immutable/*`, pulled through the apex zone
- [`media.flipcommons.org`](#media-edge-cache): uploaded images

All three zones require TLS 1.2 or higher and verify the origin certificate.

#### Apex edge cache

Bunny fronts `flipcommons.org` for anonymous SSR HTML caching. Configured to:

- respect origin `Cache-Control`
- include the URL query string in the cache key
- bypass `/api/` and `/djadmin/`
- bypass any request carrying a `sessionid` **cookie**
- bypass any request carrying a `mode=kiosk` **cookie**

The last two bypasses match cookies, not query strings. `mode` is only ever a cookie — set by "Enter Kiosk Mode" and read server-side ([kiosk/config.ts](../frontend/src/lib/kiosk/config.ts)); nothing reads it from the URL. So `/?mode=kiosk` is an ordinary anonymous request and is cached as one, which is correct. Probe a bypass with the cookie, not the query string:

```bash
curl -sSI 'https://flipcommons.org/?mode=kiosk' | grep -i cdn-cache   # HIT — cookie-less, cached
curl -sSI -H 'Cookie: mode=kiosk' https://flipcommons.org/ | grep -i cdn-cache   # BYPASS
```

Bunny rewrites `Cache-Control` to `public, max-age=0` on every rule-bypassed response, discarding the origin's `private, no-cache` / `private, no-store`. The `Cache-Control` bullet above applies to cached and MISS responses; bypassed ones are re-stamped by the edge.

Because the zone respects origin `Cache-Control`, any response that reaches Bunny without one inherits the pull zone's 30-day default. SvelteKit leaves `+server.ts` endpoints unstamped, so [Caddyfile](../Caddyfile) sets `Cache-Control: no-store` on `/__health` — otherwise an edge PoP serves uptime probes a cached `ok` for weeks after the origin stops responding.

**Changing a cache header is not retroactive.** Bunny consults the origin header only when it pulls, so a PoP holding an object keeps serving it for the remainder of the TTL it was cached under. After deploying a `Cache-Control` change, [purge](https://docs.bunny.net/cdn/purge-cache) the affected URL from the pull zone — otherwise the old policy survives up to its original expiry, unevenly across PoPs as eviction pressure varies. Confirm with `curl -sSI https://flipcommons.org/__health`: a `cdn-cache: HIT` still reporting the previous `Cache-Control` means the purge hasn't landed.

The origin-side cache contract is described in [Architecture.md](Architecture.md#edge-caching-of-ssr-html). The client-IP and origin-locking prerequisites for fronting the apex are under [Client IP trust](#client-ip-trust).

The apex resolves to this pull zone through a Bunny [`PZ` record](#dns) rather than to Railway, but the domain stays registered on the Railway service so it still routes by `Host`.

#### Static edge cache

`static.flipcommons.org` serves everything the build and [app.html](../frontend/src/app.html) reference through SvelteKit's assets path: the hashed `/_app/immutable/*` assets, `version.json`, the fonts, the favicons under `/images/favicon/` and `/apple-touch-icon.png`. Respects origin cache headers. Does not include the query string in the cache key.

Its origin is `https://flipcommons.org`, the apex pull zone, not Railway (Forward Host Header off, Follow Redirects off, no Edge Rules). A static miss is fetched through the apex zone and reaches Railway as an apex request with `Host: flipcommons.org`. Consequences:

- **Caddy cannot see the static hostname.** Static-origin traffic is indistinguishable from apex traffic at the origin, so anything static-specific has to be an Edge Rule on the static zone in the Bunny dashboard. A `host static.flipcommons.org` matcher in the [Caddyfile](../Caddyfile) would silently never match.
- **Do not repoint static at Railway without first adding the `X-Origin-Auth` Edge Rule to it.** `@direct_origin` redirects every Railway-host request lacking that header, and with Follow Redirects off the static zone would cache the 301 for every asset, site-wide, until purged. The chain is what keeps static's traffic out of that matcher today.
- **A purge of an asset path has to hit both zones, apex first.** The apex zone holds a copy of everything static has pulled, so purging static alone re-pulls the same bytes from apex. The hashed `/_app/immutable/*` assets and the fonts never need one, and `version.json` ages out of both zones within two minutes because its 60-second TTL applies at each hop. In practice this means the favicons and `apple-touch-icon.png`: unfingerprinted, they reach Bunny without `Cache-Control` and sit in two 30-day caches, so replacing one without purging both zones can take 60 days to fully age out.

Log analytics count a static miss once, at the apex; see [production_logs/README.md](../production_logs/README.md).

#### Media edge cache

`media.flipcommons.org` fronts the iDrive e2 media bucket. Respects origin cache headers.

#### Rate limiting

Rate limiting is configured in the Bunny dashboard (not in code). The goal is to blunt badly behaved bots; `robots.txt` covers the polite ones.

| Zone                    | Limit                          | Block |
| ----------------------- | ------------------------------ | ----- |
| `flipcommons.org`       | 100 requests / 10 seconds / IP | 60 s  |
| `media.flipcommons.org` | 300 requests / 10 seconds / IP | 60 s  |

Rule shape on both: condition `Request URI` contains `/` (match-all), Counter Key = IP address, Response Action = `RateLimit`. Media's ceiling is higher because one gallery page legitimately fires dozens of image requests in a burst.

This is edge abuse control, separate from the application rate limits under [Client IP trust](#client-ip-trust): Shield counts on Bunny's own view of the connecting IP, so it neither depends on nor affects the `X-Client-IP`/`X-Origin-Auth` chain.

Operational caveats:

- Limiting per-IP means a shared NAT -- such as a fixed wireless operator like Verizon 5G Home that puts all their traffic behind a pool of IPs -- could trip a limit as one "client".
- Enforcement propagates across PoPs, so a burst can leak a few requests past a freshly tripped block

### DNS

[Joker](https://joker.com) holds the domain registration; Bunny hosts the DNS zone on `kiki.bunny.net` and `coco.bunny.net`.

#### Apex `PZ` record

The apex is a Bunny **`PZ` (Pull Zone)** record bound to the apex pull zone, not an `A`, `CNAME` or `ALIAS`. Bunny flattens it to `A`/`AAAA` inside its own network at query time, so the edge is chosen for the visitor's resolver and can never be a stale address.

Two consequences worth knowing before touching it:

- **The record names a pull zone by id.** Pointing it at a new pull zone yields valid Bunny addresses that pass every DNS check while silently dropping the origin config including **Forward Host Header**, the cache bypasses, the certificate and the `X-Client-IP` / `X-Origin-Auth` Edge Rules that rate limiting depends on (see [Client IP trust](#client-ip-trust)). Verify with `curl -sSI https://flipcommons.org/__health`: `cdn-pullzone` must match the existing apex zone, and the certificate must be the pre-existing one rather than freshly issued.
- **Bunny sets the TTL, not us.** The record's TTL field is not honored; Bunny serves its own short value. This costs nothing, because the flattened address is anycast — edge failover happens in BGP, not DNS.

Bunny omits `PZ`, `RDR` and `SCR` records from its zone exports, so **a Bunny export is never a complete backup of this zone.** Record the apex pull-zone binding separately.

#### DNS Records

| Name                   |  Type | Purpose                                                          |
| ---------------------- | ----: | ---------------------------------------------------------------- |
| `flipcommons.org`      |    PZ | Site — apex pull zone                                            |
| `flipcommons.org`      |    MX | Mail (`10 mx1`, `20 mx2` at `mailcast.io`)                       |
| `flipcommons.org`      |   TXT | SPF, plus two Google Search Console proofs                       |
| `_dmarc`               |   TXT | DMARC                                                            |
| `mailcast._domainkey`  | CNAME | DKIM key 1                                                       |
| `mailcast2._domainkey` | CNAME | DKIM key 2 — rotation pair with the above                        |
| `www`                  | CNAME | Railway (`<token>.up.railway.app`); serves Caddy's apex redirect |
| `static`               | CNAME | Static asset pull zone                                           |
| `media`                | CNAME | Media pull zone (iDrive origin)                                  |
| `auth`                 | CNAME | WorkOS custom auth domain — **login breaks if this is missed**   |

No wildcard: unknown names must return `NXDOMAIN`. No DNSSEC and no CAA.

The apex also depends on `flipcommons.org` staying a registered custom domain on the Railway service, because Railway routes by `Host` and answers anything unrecognized with its own `Application not found`.

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

Caddy ([Caddyfile](../Caddyfile)) then promotes `X-Client-IP` into `X-Real-IP` **only** when `X-Origin-Auth` matches `ORIGIN_SHARED_SECRET`. So `_client_ip` keeps reading `X-Real-IP`, unchanged — it just receives the true client IP behind Bunny. A direct `*.railway.app` hit carries no valid secret, so its forged `X-Client-IP` is ignored and it's rate-limited on its own (direct) IP — no spoof, no bypass. Verified end-to-end on the pull zone (including spoof attempts) before cutover.

Required config for this path:

- **Bunny:** the two request-header Edge Rules above; **Forward Host Header ON**, so Bunny forwards the visitor's `Host` and requests reach Railway as `flipcommons.org`. It requires `flipcommons.org` to stay a registered Railway custom domain; see [DNS Records](#dns-records).
- **Railway:** `ORIGIN_SHARED_SECRET` set (matching the `X-Origin-Auth` rule); `flipcommons.org` in `ALLOWED_HOSTS`; `RATE_LIMIT_TRUST_PROXY_HEADERS=true`.

`RATE_LIMIT_TRUST_PROXY_HEADERS` stays the master switch here too: if the secret or the Edge Rules drift, Caddy stops promoting `X-Client-IP` and the system degrades to the one-shared-bucket failure above (now keyed on Bunny's IP).

#### When to revisit

- **Moving off Railway, or adding another CDN hop.** The current scheme relies on Railway's edge to populate `X-Real-IP` and strip client-supplied versions of it (and, behind the apex cache, on the Bunny `X-Client-IP`/`X-Origin-Auth` derivation above). Any further change to the proxy chain — different host, Cloudflare in front, enabling Railway's CDN — invalidates those assumptions and needs a fresh re-derivation plus a re-verification probe.
- **A new code path reads `X-Forwarded-For`.** Don't. The function in `apps/core/rate_limits.py` is the single sanctioned reader of forwarded client IP. Adding analytics, geoip, or logging that reads XFF reintroduces the parsing-bug class this design deliberately deleted.

### HSTS

HTTP Strict Transport Security is sticky: once a browser sees `Strict-Transport-Security: max-age=N`, it refuses plain HTTP to that host for `N` seconds — even if the header later disappears or shortens. A wrong `max-age` locks users out for the duration, so we ratchet it up deliberately.

#### Emitted by Caddy, not Django

The header lives in the `header { ... }` block in [`Caddyfile`](../Caddyfile), not in Django settings.

Django can't emit it usefully in this topology: it sees plaintext loopback HTTP, so `SecurityMiddleware` only adds HSTS when `request.is_secure()` returns `True`, which it doesn't here. Bridging that gap would require setting `SECURE_PROXY_SSL_HEADER` — but enabling that without `SECURE_SSL_REDIRECT` is a footgun, and turning on `SECURE_SSL_REDIRECT` would loop on internal callers (SSR, health checks) that legitimately reach Django over plain loopback HTTP. Caddy fronts the HTTPS edge and has no such gate, so it's the right place.

The Django deploy warnings `security.W004`, `W005` and `W021` are silenced via `SILENCED_SYSTEM_CHECKS` in `config/settings.py` because Caddy owns this policy. A pytest test (`backend/tests/test_caddyfile_hsts.py`) guards against accidental deletion or weakening of the directive.

#### Apex policy only — subdomains opt in individually

`includeSubDomains` is intentionally **not** set. The apex policy covers `flipcommons.org` itself; each subdomain owns its own HSTS via its own server. This preserves the option of adding a future subdomain (a SaaS-hosted status page, a LAN-local device, anything we can't foresee) that's HTTPS-capable but for whatever reason can't or shouldn't emit HSTS on day 1.

In practice, modern providers cover their own subdomains: `media.flipcommons.org` already gets `Strict-Transport-Security: max-age=31536000; includeSubDomains` from iDrive (through Bunny), and any future SaaS-hosted subdomain will do the same. So the cost of omitting `includeSubDomains` is narrow — it only matters for an HTTPS-capable subdomain that emits no HSTS of its own.

#### Rollout sequence

Three steps, not four — the conventional 1-week intermediate buys ceremony, not signal:

1. **`max-age=60`** — header-emission check. Too short to be a soak; just confirms the header is emitted (`curl -sI https://flipcommons.org | grep -i strict-transport`, and the same for `www`).
2. **`max-age=86400`** (1 day) — current. The real soak: a day of sticky HSTS under real traffic. Anything that breaks (an HTTP-only apex resource, a redirect loop) surfaces here, with lockout bounded at 24h.
3. **`max-age=31536000`** (1 year) — destination. Edit the `Strict-Transport-Security` line in `Caddyfile`, commit, deploy.

Verify after each step: response includes `Strict-Transport-Security: max-age=N` (no `includeSubDomains`, by design).

#### Preload list — intentionally never enabled

Submission to [hstspreload.org](https://hstspreload.org/) is irreversible regardless of `max-age` (browsers ship the domain hardcoded; removal takes months) and requires `includeSubDomains`, which we've ruled out for the same flexibility reason above. The two are inseparable: if we're not committing to "every subdomain HTTPS-only forever," preload is unreachable.

## Configuration

Set these in the Railway web service dashboard. `DATABASE_URL`, `PORT`, and the `RAILWAY_*` build/runtime vars are injected by Railway automatically (Caddy listens on `PORT`).

### Environment variables

#### Core

- `SECRET_KEY` — random string: `python -c "import secrets; print(secrets.token_urlsafe(50))"`
- `DEBUG` — `false`
- `ALLOWED_HOSTS` — comma-separated public hosts, e.g. `flipcommons.org,www.flipcommons.org`. The Railway origin host does not belong here: `settings.py` appends `RAILWAY_PUBLIC_DOMAIN` on its own, which covers the residual paths that still reach Django wearing it.
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
- `ORIGIN_SHARED_SECRET` — secret matching the Bunny `X-Origin-Auth` Edge Rule; lets Caddy trust the Bunny-forwarded `X-Client-IP`. See [Client IP trust](#client-ip-trust).

#### SEO

- `ALLOW_SEARCH_ENGINE_INDEXING` — `true` on prod, `false` elsewhere. See [Search-engine indexing](#search-engine-indexing).

Sentry and PostHog vars live in their service sections: [Sentry](#sentry) and [PostHog](#posthog).

### Server-side cache

Per-user rate limits ([backend/apps/provenance/rate_limits.py](../backend/apps/provenance/rate_limits.py)) use `django.core.cache` as a shared store for sliding-window timestamps (bucket semantics in [Rate Limits](RecordLifecycle.md#rate-limits)). The backend is **file-based** (`FileBasedCache` under `BASE_DIR/cache`), so every Gunicorn worker and management command shares one store through the filesystem — no external cache service required. A per-process backend like `LocMemCache` would break this: each worker would keep its own window, letting a user send `N × limit` requests before any single worker decided to 429.

### Search-engine indexing

`ALLOW_SEARCH_ENGINE_INDEXING` gates SvelteKit's `robots.txt` body. Set `"true"` on prod, `"false"` on every other deployed service. Only the literal `"true"` enables indexing; anything else is off.

`check --deploy` refuses any deploy where the var is unset (`core.E301`) or not exactly `"true"`/`"false"` (`core.E302`) — so a new Railway service needs the var set before its first deploy.

#### The Railway origin hostname is not a second site

That gate is deployment-level — it reads an env var, never the request host — so `flipcommons-production.up.railway.app` would otherwise serve the same indexable pages and the same permissive `robots.txt` as the apex, and be indexed as a duplicate of it. The `@direct_origin` matcher in [Caddyfile](../Caddyfile) 301s direct hits to the public origin instead. It is not a security boundary: a direct caller can still reach the origin by sending `Host: flipcommons.org`. [`test_caddyfile_direct_origin.py`](../backend/tests/test_caddyfile_direct_origin.py) pins the directive, whose absence is otherwise invisible.

## Troubleshooting

Every item below starts with reading production logs. [production_logs/](../production_logs/README.md) pulls them from Railway and Sentry and builds a queryable database over them.

**Health check fails after deploy**:
`/__health` is served by the SvelteKit Node runtime and checks Django in turn via an internal `/api/health` call, which runs a `SELECT 1`. So a failing probe means Node is down, Django is down, or the database is unreachable — check the deploy logs for Node or Python startup errors. Common causes: missing `SECRET_KEY`, database connection issues, a bad migration or the SSR process failing to start. Railway will not promote the deployment while this fails, so the previous container stays live.

A probe that fails with **400** rather than a connection error means it reached Django with an external `Host` header and hit `ALLOWED_HOSTS`. That points at `healthcheckPath` having been changed to a Django route — put it back to `/__health`; see [railway.toml](../railway.toml).

**Apex returns `ERR_TOO_MANY_REDIRECTS`**:
Bunny is forwarding the Railway origin hostname again and its requests are matching `@direct_origin`, which sends them back to a host Bunny fronts. Check **Forward Host Header** on the apex pull zone (must be ON) and the `X-Origin-Auth` Edge Rule (whose presence is what excludes Bunny's traffic when the toggle is wrong). Fix whichever drifted, then [purge](https://docs.bunny.net/cdn/purge-cache) the affected URLs — the zone has Follow Redirects disabled, so cached 301s survive the repair.

**Every request returns Railway's `{"message":"Application not found"}`**:
The `flipcommons.org` Railway custom domain has been removed or de-validated. Bunny forwards `Host: flipcommons.org` and Railway routes by that header, so the domain must stay registered — check `railway domain` for an `ACTIVE` row. Re-adding it means completing the ownership challenge Railway issues, a temporary TXT record that can be removed once validation completes; see [DNS Records](#dns-records).

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
