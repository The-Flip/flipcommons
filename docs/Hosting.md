# Deployment on Railway

This site runs as a **single [Railway](https://railway.com/) service**: one Docker container running Caddy, SvelteKit Node SSR, and Django/Gunicorn.

This document is the operator-facing reference for production deployment, runtime processes, ports, and troubleshooting.

For browser request flow and the SSR/CSR split, see [WebArchitecture.md](WebArchitecture.md).

## Runtime Topology

```text
Browser ──→ Railway (single Caddy service)
              │
              ├─ frontend routes        → SvelteKit Node SSR
              ├─ /_app/*                → SvelteKit Node SSR
              ├─ /api/*                 → Django Ninja API
              ├─ /djadmin/*             → Django Admin
              └─ /static/*              → Django staticfiles / WhiteNoise

Browser ──→ media.flipcommons.org       → Bunny CDN → iDrive e2 private bucket
```

### Runtime flow

1. **Docker multi-stage build**: Stage 1 installs frontend dependencies and
   builds the SvelteKit Node server. The final image contains the built
   Svelte runtime, Django, and Caddy in one container.

2. **Caddy reverse proxy**: Caddy listens on Railway's public `PORT` and
   routes `/api/`, `/djadmin/`, and `/static/` to Django on `127.0.0.1:8000`.
   All other requests are forwarded to SvelteKit SSR on `127.0.0.1:3000`.

3. **WhiteNoise static files**: Django still serves collected static files
   for admin assets through `/static/`.

4. **Uploaded media serving**: Django writes uploaded media to the configured
   S3-compatible storage backend. In production, public media URLs point at
   Bunny CDN on `media.flipcommons.org`, which pulls from the private iDrive e2
   bucket. Django is not in the production media-serving path.

5. **Pre-deploy checks and migrations**: Railway's `preDeployCommand`
   runs `manage.py check --deploy && manage.py migrate` before the new
   container accepts traffic. `check --deploy` surfaces production-only
   system checks (HSTS, SSL redirect, `core.W001` for missing
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

## Geography

The Flip pinball museum and many editors and end users are in Chicago. Hosting reflects that:

- The Railway-hosted website in Virginia. Railway does not have a Chicago presence.
- The iDrive e2 media storage is in Chicago to optimize for cold reads through the Bunny.net CDN.

## Process Model

The production container runs three long-lived processes:

- **Caddy** on Railway's public `PORT`
- **Django/Gunicorn** on `127.0.0.1:8000`
- **SvelteKit Node SSR** on `127.0.0.1:3000`

The entrypoint is [`scripts/start-production`](../scripts/start-production).
It starts all three processes and keeps the container alive while they are all healthy.

### Current supervision behavior

The supervision model is intentionally simple for now:

- there is no in-container restart policy for Node or Gunicorn
- if one of the child processes exits, the container exits shortly after
- Railway is responsible for restarting the container

This is acceptable for the current bootstrap phase because it is simple and fails closed, but it is not a full process supervisor. If the container needs stronger production hardening later, a dedicated supervision layer such as `s6-overlay` would be the next step.

### Route handling examples

| Request                        | Handled by                           |
| ------------------------------ | ------------------------------------ |
| `GET /api/models/`             | Django Ninja                         |
| `GET /djadmin/`                | Django Admin                         |
| `GET /__health`                | Caddy → SvelteKit readiness endpoint |
| `GET /titles/medieval-madness` | Caddy → SvelteKit SSR                |
| `GET /_app/immutable/app.js`   | Caddy → SvelteKit SSR                |
| `GET /manufacturers/williams`  | Caddy → SvelteKit SSR                |
| `GET /`                        | Caddy → SvelteKit SSR                |

## Client IP trust

Pre-auth rate limiters (signup flow, etc.) key off the caller's IP. Because Django sits behind two layers of proxy (Railway's edge, then Caddy), `REMOTE_ADDR` is always `127.0.0.1` — the real client IP has to come from a forwarded-header. Getting this right is security-relevant: a wrong choice silently makes IP-keyed rate limits either non-functional (every request shares one bucket) or bypassable (an attacker varies the header to spray buckets).

### Header chain

**Railway edge** (before Caddy sees the request):

- Sets `X-Real-IP` to the real client public IP. Client-supplied values are overwritten; not spoofable. Verified empirically by the Client-IP-Trust probe.
- Sets `X-Forwarded-For` to Railway's rotating internal IP (a `100.64.0.X` CGNAT address whose last octet rotates per request across Railway's internal proxy fabric). Reading this directly would bucket each request from one client into a different bucket.
- Passes `Forwarded` (RFC 7239) through verbatim — **attacker-controlled** until Caddy strips it.

**Caddy** ([Caddyfile](../Caddyfile)):

- Strips `Forwarded` at site level (`request_header -Forwarded`) — closes the attacker-controlled channel.
- Overwrites `X-Forwarded-For` with the trusted `X-Real-IP` value via `header_up` inside each `reverse_proxy` block. `header_up` is required (not site-level `request_header`) because Caddy's `reverse_proxy` has special handling for `X-Forwarded-*` headers that overrides any site-level mutations — site-level strips of XFF were verified empirically to be ignored. If `X-Real-IP` is absent (a state Railway never produces in practice), XFF becomes empty string; the deployment contract is that `X-Real-IP` is always populated at the proxy boundary.

**Django** ([\_client_ip](../backend/apps/core/rate_limits.py)):

- Reads `X-Real-IP`. Never reads `X-Forwarded-For` — XFF parsing (left-most vs. right-most, trusted-hop counting) has no failure mode that's safe under upstream drift; `X-Real-IP` fails closed if absent.

### Trust gate (`RATE_LIMIT_TRUST_PROXY_HEADERS`)

Django's `_client_ip` only reads proxy headers when `RATE_LIMIT_TRUST_PROXY_HEADERS=true`. The setting defaults to `false`, so dev, tests, and any container without a sanitizing proxy in front key off `REMOTE_ADDR=127.0.0.1` and degrade to "everyone shares one bucket" — observable, fixable, not a security bug.

**Production must set `RATE_LIMIT_TRUST_PROXY_HEADERS=true`.** The trust assumption (Caddy has stripped `Forwarded`, Railway has populated `X-Real-IP`) is a deployment contract.

This is the second fail-closed layer behind the X-Real-IP-only header choice. Both layers protect against the same drift: if the env var rolls back, or a future upstream stops setting `X-Real-IP`, the system degrades to one-shared-bucket rather than silently trusting attacker input.

### When to revisit

- **Moving off Railway, or adding a CDN.** The current scheme relies on Railway's edge to populate `X-Real-IP` and strip client-supplied versions of it. Any infra change to the proxy chain — different host, Cloudflare/Bunny in front, enabling Railway's CDN — invalidates that assumption and likely needs a Caddy `trusted_proxies` block plus a re-verification probe.
- **A new code path reads `X-Forwarded-For`.** Don't. The function in `apps/core/rate_limits.py` is the single sanctioned reader of forwarded client IP. Adding analytics, geoip, or logging that reads XFF reintroduces the parsing-bug class this design deliberately deleted.

## Search-engine indexing

`ALLOW_SEARCH_ENGINE_INDEXING` gates SvelteKit's `robots.txt` body. Set `"true"` on prod, `"false"` on every other deployed service. Only the literal `"true"` enables indexing; anything else is off.

`check --deploy` refuses any deploy where the var is unset (`core.E301`) or not exactly `"true"`/`"false"` (`core.E302`) — so a new Railway service needs the var set before its first deploy.

## Setup

### 1. Create Railway project

In your Railway workspace, create a new project and connect the GitHub repo.
Railway auto-detects the `Dockerfile` via `railway.toml`.

Add a **Postgres** plugin to the project. Railway sets `DATABASE_URL`
automatically via a reference variable.

### 2. Set environment variables

In the Railway service dashboard:

| Variable                         | Value                                                                                     |
| -------------------------------- | ----------------------------------------------------------------------------------------- |
| `SECRET_KEY`                     | Random string: `python -c "import secrets; print(secrets.token_urlsafe(50))"`             |
| `DEBUG`                          | `false`                                                                                   |
| `ALLOWED_HOSTS`                  | Comma-separated hosts, e.g. `flipcommons.org,www.flipcommons.org`                         |
| `CSRF_TRUSTED_ORIGINS`           | Full origins, e.g. `https://flipcommons.org,https://www.flipcommons.org`                  |
| `INTERNAL_API_BASE_URL`          | `http://127.0.0.1:8000`                                                                   |
| `RATE_LIMIT_TRUST_PROXY_HEADERS` | `true` — required in production. See [Client IP trust](#client-ip-trust).                 |
| `ALLOW_SEARCH_ENGINE_INDEXING`   | `true` on prod, `false` elsewhere. See [Search-engine indexing](#search-engine-indexing). |

`DATABASE_URL` and `PORT` are set automatically by Railway.

### Runtime environment notes

- `PORT` is the public port Railway assigns to the container. Caddy listens on this port.
- `INTERNAL_API_BASE_URL` is the base URL SvelteKit SSR uses to call Django from server-side routes. In the current production topology it should point directly at Gunicorn on `http://127.0.0.1:8000` so SSR does not bounce back through the public Caddy origin.
- The Docker image sets `INTERNAL_API_BASE_URL=http://127.0.0.1:8000` by default. You should keep that value unless the internal Django address changes.

### Cache backend — required for shared state across workers

Per-user rate limits ([backend/apps/provenance/rate_limits.py](../backend/apps/provenance/rate_limits.py)) use `django.core.cache` as the shared store for sliding-window timestamps. Lifecycle buckets and action semantics are described in [Rate Limits](RecordLifecycle.md#rate-limits). In a multi-worker deployment (Gunicorn with more than one worker), the default `LocMemCache` backend is **per-process** — each worker keeps its own window, and a user can effectively send `N × limit` requests before any one worker decides to 429. Any other feature that starts using the cache for cross-request state has the same failure mode.

Use a shared backend in production. On Railway, the simplest options are:

- Redis (`django-redis`), added as a Railway plugin and wired up via `CACHES` in `config/settings.py`.
- Postgres-backed cache (`django.core.cache.backends.db.DatabaseCache`) — slower but requires no new infra since we already have Postgres.

Dev + tests run fine with `LocMemCache` because there's only one process. Document the limit-per-worker behavior if you ever ship multi-worker without a shared backend.

### Stamping the deploy version

The SvelteKit build reads `RAILWAY_GIT_COMMIT_SHA` and writes it into `version.json`; the SPA polls that file hourly and, on a detected change, swaps the next client-side navigation for a full page reload. That's how an open browser tab picks up new JS (and drops in-memory caches) after a deploy without disrupting the user mid-task.

Railway auto-injects `RAILWAY_GIT_COMMIT_SHA` as a Docker build arg for any deploy triggered from GitHub — no service-side configuration required, just the `ARG RAILWAY_GIT_COMMIT_SHA` declaration in the [Dockerfile](../Dockerfile). Outside Railway (local `docker build`), the arg falls back to `dev` and version polling is disabled. The `version.json` in the built image (`/app/frontend_runtime/build/client/_app/version.json`) is the ground truth for which SHA was stamped.

### 3. Deploy

Push to `main`. Railway builds the Docker image and deploys. The
`preDeployCommand` in `railway.toml` runs `manage.py check --deploy`
followed by `manage.py migrate` before the new container starts
accepting traffic.

### 4. Grant admin access (one-time)

The Django admin password form is disabled — WorkOS is the only login surface — so `createsuperuser` produces a row that can never sign in. Instead, open the deployed site and sign in via WorkOS to create your user, then promote it in the Railway service shell (or via `railway run`):

```bash
uv run python manage.py grant_admin you@example.com
```

## Custom domain

1. Add a custom domain in Railway project settings
2. Update `ALLOWED_HOSTS` to include the domain
3. Update `CSRF_TRUSTED_ORIGINS` to include `https://yourdomain.com`

## Sentry

We use [Sentry.io](https://sentry.io) for production error monitoring. See [Observability.md](Observability.md) for the contract (what we capture, privacy posture, code wiring).

### Sentry Projects

In Sentry, we have two projects:

- `flipcommons-backend`: Python/Django
- `flipcommons-frontend`: JavaScript/SvelteKit — both SSR and browser report here

### Sentry env vars on Railway

Local, CI, and test environments leave these unset. The empty-DSN guard at SDK init is the master switch.

- `SENTRY_DSN` — backend runtime. Backend project DSN. Empty = Sentry off (master switch).
- `PUBLIC_SENTRY_DSN` — frontend SSR + browser runtime. Frontend project DSN. Empty = Sentry off (master switch).
- `SENTRY_AUTH_TOKEN` — frontend build (Docker `ARG` → `ENV`). Org-scoped, secret. The only Sentry value that's actually secret; DSNs are public-by-design write-only keys. Required for sourcemap upload.
- `SENTRY_ORG` — frontend build. Org slug. Required for sourcemap upload.
- `SENTRY_PROJECT` — frontend build. `flipcommons-frontend`. Required for sourcemap upload.

All three `SENTRY_*` build-time vars are declared as `ARG`s in the frontend build stage of the [Dockerfile](../Dockerfile) and `ENV`-promoted before `pnpm build` — multi-stage Docker doesn't inherit host env vars into build stages, and forgetting one silently produces a build with no sourcemaps uploaded.

### Sentry dashboard config

#### Privacy config

This part of our [Privacy.md](Privacy.md) contract is manually configured on the Sentry website:

**Advanced Data Scrubbing** (Project Settings → Security & Privacy → Advanced Data Scrubbing). These are part of the privacy contract — without them, emails or IPs interpolated into log messages, or query strings carrying user input, would be stored.

- `[Mask] [@email] from [$string]`
- `[Mask] [@ip] from [$string]`
- `[Remove] [$request.query_string]`

#### Alert rules\*\*

Mirrored across both projects:

- **New issue** → alert all maintainers
- **Regression of a resolved issue** → alert all maintainers
  Default issue assignment: **unassigned**. Either founder may grab an issue.

### Per-maintainer routing

Each maintainer is an org member with their own destination (email or chat). Adding or removing a maintainer is a single membership change. Production alerts go to all maintainers as co-responders.

### Sourcemaps

`@sentry/vite-plugin` (wrapped by `sentrySvelteKit`) uploads at build time, tagged with `RAILWAY_GIT_COMMIT_SHA`. The plugin's `sourcemaps.filesToDeleteAfterUpload` is configured explicitly so maps don't ship to browsers (the plugin doesn't delete by default).

## Troubleshooting

**Health check fails after deploy**:
The health check should hit `/__health`. That endpoint is served by the
SvelteKit Node runtime and, in turn, checks Django via its internal
`/api/health/` call. If it fails, check the deploy logs for Node or Python
startup errors. Common causes: missing `SECRET_KEY`, database connection
issues, a bad migration, or the SSR process failing to start.

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
