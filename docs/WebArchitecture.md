# Web Architecture

This document describes how this project's web application behaves at runtime: how browser requests flow through the stack, how same-origin is preserved, and how SSR and CSR are split between routes.

For the top-level system map, see [Architecture.md](Architecture.md). For deployment and operator details, see [Hosting.md](Hosting.md).

## Web Split

### Django backend

Django is the source of truth for:

- the catalog and supporting models
- provenance, claim assertion, and claim resolution
- ingest from external and editorial sources
- authentication and authorization
- admin and operational tooling
- the API exported to the frontend

See [Authz.md](Authz.md) for the backend authorization policy and frontend capability contract.

### SvelteKit frontend

SvelteKit is responsible for:

- the public-facing browsing experience
- authenticated user-facing application flows
- consuming the Django API
- rendering server-side HTML for public pages
- rendering CSR-only application pages where interactivity or auth-gated UX is the priority

The frontend does not own business truth. It renders and edits data through Django.

## Same-Origin Model

This project uses a same-origin model in both development and production.

### Why

This keeps authentication and CSRF simple:

- Django session auth works naturally
- the browser does not need cross-origin API calls
- no JWT or CORS architecture is required
- Django admin and the user-facing app share the same auth authority

## API Layer

The frontend talks to the backend through a single typed API mounted at `/api/`, built on [Django Ninja](https://django-ninja.dev/).

### API routers

Ninja API Routers are defined per Django app (`apps.catalog.api`, `apps.accounts.api`, etc.) and assembled in `config/api.py`.

### Typed client

The OpenAPI schema is generated from the Ninja routers and compiled into TypeScript types in `frontend/src/lib/api/schema.d.ts` (gitignored, regenerated via `make api-gen`). A hand-written client in `frontend/src/lib/api/client.ts` wraps `fetch` with the schema's typed paths, bodies, and responses.

### Authentication and authorization

All routes use Django session cookies. No JWT, no API key, no CORS. Mutating routes carry an `Activity`-based authorization marker (`@requires`, `@gated_inline`, or `@public_mutation`); a route-inventory test ensures every mutating route is classified. See [Authz.md](Authz.md).

### CSRF enforcement

Django Ninja marks every view as `csrf_exempt`, so Django's stock `CsrfViewMiddleware` short-circuits for `/api/` routes. This project re-enforces CSRF with a dedicated `NinjaCsrfMiddleware` (in `apps.core.middleware`) that runs Django's CSRF check against unsafe-method `/api/` requests via a non-exempt placeholder callable.

The contract:

- The frontend's `client.ts` reads the `csrftoken` cookie set by Django and sends its value as the `X-CSRFToken` header on every mutating request.
- The backend's `NinjaCsrfMiddleware` validates the header against the cookie on every `POST`/`PATCH`/`DELETE` request to `/api/`. `GET` is unaffected.

`NinjaCsrfMiddleware` is positioned immediately after Django's `CsrfViewMiddleware` in `MIDDLEWARE`; the stock middleware's `process_request` populates `request.META['CSRF_COOKIE']`, which the Ninja-specific middleware then compares against the submitted header. A route-inventory test (`apps/core/tests/test_csrf_inventory.py`) asserts every mutating `/api/` route is rejected without a valid token, and end-to-end integration tests against `/api/auth/logout/` cover the full middleware chain.

### Endpoint design

See [ApiDesign.md](ApiDesign.md) for endpoint shape (page-oriented vs. resource-oriented), schema consolidation heuristics, and inheritance smells.

## Development

In local development, the browser talks to the SvelteKit dev server. Vite handles frontend routes and proxies backend paths to Django.

```text
Browser
  -> SvelteKit dev server
     -> /api/*, /djadmin/*, /media/*, /static/* proxied to Django
     -> frontend routes handled by SvelteKit
```

Public routes can still be server-rendered in development because SvelteKit's dev server supports SSR directly. This preserves the same-origin mental model even though two processes are running.

## Production

In production, one Railway service handles:

- `/api/` via Django Ninja
- `/djadmin/` via Django admin
- `/static/` via Django/WhiteNoise
- frontend routes via SvelteKit Node SSR

Uploaded media is served outside the Railway request path: API payloads return
URLs on `media.flipcommons.org`, where Bunny CDN pulls from the private iDrive
e2 bucket.

At a high level:

```text
Browser
  -> Caddy
     -> /api/* handled by Django/Gunicorn
     -> /djadmin/* handled by Django admin
     -> /static/* handled by Django/WhiteNoise
     -> frontend routes handled by SvelteKit Node SSR

Browser
  -> media.flipcommons.org
     -> Bunny CDN
        -> iDrive e2 private bucket
```

See [Hosting.md](Hosting.md) for the production serving details.

## Rendering Model

This project uses both SSR and CSR, but not for the same kinds of routes.

- Public content-heavy routes should usually render meaningful HTML on the server.
- Internal or highly interactive application routes may deliberately opt out with `ssr = false`.
- The decision is per route, not all-or-nothing for the whole frontend.

See [Svelte.md](Svelte.md) for route-level guidance and [ApiDesign.md](ApiDesign.md) for page-oriented API design.

## Read Next

- [Architecture.md](Architecture.md)
- [Svelte.md](Svelte.md)
- [ApiDesign.md](ApiDesign.md)
- [Authz.md](Authz.md)
- [Hosting.md](Hosting.md)
