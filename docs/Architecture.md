# Architecture

This document describes how the system is put together at runtime: how browser requests flow through the stack, how Django and SvelteKit split responsibility, how same-origin is preserved, and how SSR and CSR are split between routes.

## Layers

The pieces the system is built from. See [Hosting.md](Hosting.md#services) for the production service inventory and how each is configured and deployed.

| Layer            | Production | Local dev        |
| ---------------- | ---------- | ---------------- |
| CDN & DNS        | Bunny.net  | —                |
| Authentication   | WorkOS     | WorkOS           |
| Frontend         | SvelteKit  | SvelteKit        |
| API              | Ninja      | Ninja            |
| Backend          | Django     | Django           |
| Database         | Postgres   | SQLite           |
| Media storage    | iDrive e2  | Local filesystem |
| Error monitoring | Sentry     | —                |
| Analytics        | PostHog    | —                |

There is **no async layer**: no task queue, worker pool or scheduler. Work that elsewhere would be backgrounded — applying data patches, in particular — runs as synchronous management commands invoked by hand.

The shared rate-limit store is a file-based Django cache, not an external service.

## Topology

### Production Topology

The production origin is one Railway service running Caddy, Django/Gunicorn,
and SvelteKit Node SSR in a single container.

Bunny CDN fronts every request.

```text
Browser
   ├─ flipcommons.org        → Bunny CDN (apex)   → Railway /*
   ├─ static.flipcommons.org → Bunny CDN (static) → Bunny CDN (apex) → Railway /_app/*, /fonts/*, favicons
   └─ media.flipcommons.org  → Bunny CDN (media)  → iDrive e2 private bucket

Railway (single Caddy service)
   ├─ /api/*                 → Django Ninja API
   ├─ /djadmin/*             → Django Admin
   ├─ /static/*              → Django staticfiles / WhiteNoise
   ├─ /media/*               → Django media fallback when CDN not used
   ├─ /__health              → Node → SvelteKit readiness endpoint
   ├─ /_app/*                → Node → SvelteKit static app assets
   └─ /*                     → Node → SvelteKit routes
```

### Development Topology

In localhost development, the browser talks to the SvelteKit dev server. Vite handles frontend routes and proxies backend paths to Django.

```text
Browser
   └─ SvelteKit dev server
        ├─ /api/*, /djadmin/*, /media/*, /static/* proxied to Django
        └─ frontend routes handled by SvelteKit
```

## Frontend vs backend responsibilities

### Django

Django is the source of truth for:

- the catalog and supporting models
- provenance, claim assertion, and claim resolution
- data-patch ingest of catalog data
- authentication and authorization
- admin and operational tooling
- the API exported to the frontend

See [Authz.md](Authz.md) for the backend authorization policy and frontend capability contract.

### SvelteKit

SvelteKit is responsible for:

- the public-facing browsing experience
- authenticated user-facing application flows
- rendering server-side HTML for public pages
- rendering CSR-only application pages where interactivity or auth-gated UX is the priority

The frontend does not own business truth. It renders and edits data through Django — including during SSR, where the Node server calls the same `/api/` over an internal loopback request rather than touching the database directly.

## API

The frontend talks to the backend through a [Django Ninja](https://django-ninja.dev/) API mounted at `/api/`.

### API routers

Ninja API Routers are defined per Django app (`apps.catalog.api`, `apps.accounts.api`, etc.) and assembled in `config/api.py`.

### Typed client

The OpenAPI schema is generated from the Ninja routers and compiled into TypeScript types in `frontend/src/lib/api/schema.d.ts` (gitignored, regenerated via `make codegen`). A hand-written client in `frontend/src/lib/api/client.ts` wraps `fetch` with the schema's typed paths, bodies, and responses.

### Authentication and authorization

All routes use Django session cookies. No JWT, no API key, no CORS. Mutating routes carry an `Activity`-based authorization marker (`@requires`, `@gated_inline`, or `@public_mutation`); a route-inventory test ensures every mutating route is classified. See [Authz.md](Authz.md).

### Endpoint design

See [ApiDesign.md](ApiDesign.md) for endpoint shape (page-oriented vs. resource-oriented), schema consolidation heuristics, and inheritance smells.

## Caching

The layers of caching:

### Backend data cache

([`catalog/cache.py`](../../../backend/apps/catalog/cache.py)) — pre-serialized JSON + ETag for `/all/` and the no-filter facets payloads, audience-scoped, invalidated on commit.

### Edge HTML cache

Bunny.net CDN pull zone for anonymous public SSR HTML.

### Static asset CDN

Bunny.net CDN pull zone for the build's assets. It pulls through the apex zone rather than from Railway; [Hosting.md](Hosting.md#static-edge-cache) has the inventory and what the chain constrains.

## Provenance

One of the most distinctive things about this system is its provenance system. One the system's core jobs is to ensure that the provenance of each piece of catalog data -- pinball models, manufacturers etc -- is maintained in full detail.

Because of this, Catalog writes do not mutate entity rows directly. Every user-inputted catalog field — scalars, FKs, M2M, slugs, parents, aliases — is **claims-based**, including ingested data that lands in fields a user could edit. Only system-generated fields (`id`/`uuid`, timestamps, derived values like `Location.location_path`) bypass claims.

Two layers sit behind every materialized field:

- **Claims** — a stream of source-attributed assertions. Each claim says "Source X (an external database, a book or the editorial team) — or User U — says entity Y's field Z is V." Multiple sources can assert different values for the same field; a newer claim from the same source supersedes the old one.
- **Resolution** — the materialized model fields are _derived_ from claims by deterministic, priority-based conflict resolution: order by source priority then date, highest wins, coerce onto the model field (or into the M2M and related rows for relationship claims).

So the entity row a request reads is a resolved projection, not the system of record — the claim stream is. That is what lets the system always answer "who said this, and where did it come from?", accept a second source for any field with no migration and keep a full audit trail even where nothing is disputed.

User claim-writes are attributed through a `ChangeSet` carrying an `action` (`create`/`edit`/`delete`/`revert`); ingest writes are attributed to an `ingest_run` instead. See [Provenance.md](Provenance.md) for the model and resolution detail, and [RecordLifecycle.md](RecordLifecycle.md) for record lifecycle semantics.

## Django apps

Within Django, responsibilities are split across explicit apps:

- `core` shared foundation layer
- `accounts` auth/account-specific behavior
- `catalog` the pinball business/domain model
- `citation` citation-source metadata and evidence records
- `provenance` the claims and audit machinery
- `media` photo and video upload and hosting infrastructure

See [AppBoundaries.md](AppBoundaries.md) for dependency rules and boundary guidance.

## Same-origin model

This project uses a same-origin model in both development and production.

### Why

This keeps authentication and CSRF simple:

- Django session auth works naturally
- the browser does not need cross-origin API calls
- no JWT or CORS architecture is required
- Django admin and the user-facing app share the same auth authority

### CSRF enforcement

Django Ninja marks every view as `csrf_exempt`, so Django's stock `CsrfViewMiddleware` short-circuits for `/api/` routes. This project re-enforces CSRF with a dedicated `NinjaCsrfMiddleware` (in `apps.core.middleware`).

The contract:

- The frontend's `client.ts` reads the `csrftoken` cookie set by Django and sends its value as the `X-CSRFToken` header on every mutating request.
- The backend's `NinjaCsrfMiddleware` validates the header against the cookie on every `POST`/`PATCH`/`DELETE` request to `/api/`. `GET` is unaffected.

How the middleware reinstates the check (and why it sits where it does in `MIDDLEWARE`) is documented in the docstrings of `apps/core/middleware/csrf.py`.

## SSR vs CSR

This project uses both SSR and CSR.

- Unauthenticated routes should usually render meaningful HTML on the server.
- Authenticated routes may deliberately opt out with `ssr = false`.

See [Svelte.md](Svelte.md) for route-level guidance and [ApiDesign.md](ApiDesign.md) for page-oriented API design.

## Edge caching of SSR HTML

Public SSR HTML is **per-user-invariant**: the server renders identical markup for every visitor because auth state loads **client-side only** (the nav and auth store hydrate in the browser, never during SSR). The HTML carries no per-user content, so it is safe to share across users — the property a shared cache depends on.

To make that shareable HTML edge-cacheable without ever serving a contributor a stale copy of their own edit, a SvelteKit server hook ([`cache-control.server.ts`](../frontend/src/lib/cache-control.server.ts), in the `handle` sequence) stamps `Cache-Control` on SSR HTML responses and permanent (301) redirects, driven by the request's cookies:

| Request                         | `Cache-Control`                 |
| ------------------------------- | ------------------------------- |
| anonymous                       | `public, s-maxage=…, max-age=0` |
| `sessionid` (a signed-in user)  | `private, no-cache`             |
| `mode=kiosk` (checked first)    | `private, no-store`             |
| any response that sets a cookie | `private, no-store`             |
| anything else                   | `private, no-store`             |

Every response that set no `Cache-Control` of its own gets one, because the edge gives an unstamped response a 30-day default. What SvelteKit answers before its hooks run (prerendered pages, files under `static/`, `/_app/env.js`) is stamped by Caddy instead; see [Hosting.md](Hosting.md#apex-edge-cache) for that table.

The directive is **cookie-driven, not route-driven** — the markup is the same for everyone, so only the directive differs. Anonymous caching is **CDN-only** (`s-maxage` for the shared edge, `max-age=0` so browsers always revalidate): once a request carries `sessionid` it reaches the edge bypass rather than a stale local copy. `private` keeps authenticated and kiosk responses out of every cache, and the `Set-Cookie` fallback keeps any cookie-bearing response from being shared-cached. The hook never sets `Vary: Cookie` — the audience split rides on `public` vs `private` plus the edge's cookie bypass, not on keying the cache by cookie (which would fragment it per `csrftoken`).

**`__data.json` data requests are not edge-cached.** SvelteKit stamps `private, no-store` on every data response itself, and the hook does not clobber a header a response already carries, so every anonymous client-side navigation reaches the origin. Deliberate: across nine days of edge logs only 8 of 625 data requests would have become cache hits at a 60-second TTL, the rest already bypassing on the signed-in or kiosk cookie. Overriding SvelteKit would also mean shared-caching auth-gate bounces, which arrive as a 200 carrying a redirect payload rather than as a 3xx.

The CDN that consumes this contract — its bypass rules and pull-zone config — is operator territory; see [Hosting.md](Hosting.md#apex-edge-cache).
