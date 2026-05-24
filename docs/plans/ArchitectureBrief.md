# Project Brief

After building Flipfix (a Django system for maintaining a pinball museum), I'm very much sold on Django as a way of modeling schema, with its great migrations feature. I'm not so sold on Django's UI system. I come from the Svelte and React worlds, and find 3,000 line CSS files unacceptable. Though I _do_ love Django's auto-scaffolded admin UI for infrequent superuser tasks.

I'm dreaming of a system that combines the best of these worlds: Django on the back end, that owns the data model and the APIs and hopefully infrequent admin UIs, with a Sveltekit front end for everything facing end users. The Sveltekit would use a SPA for the authenticated pages and pre-rendered static HTML for public pages. This setup feels like it would be super fast for end users and very ergonomic for developers.

I'm also a TypeScript nut. Whatever APIs are exposed to Sveltekit _must_ have TypeScript bindings.

I'm also a bit of a performance nut... I suspect Node.js equivalents to Django as an API and data layer won't be as performant? Also, I'd be interested in systems that are _more_ performant than Django.

Also, I want a system that I'm going to remember how to work with when I come back to it in a year, or hand it off to a maybe not-so-skilled volunteer developer later on. The developer experience, operational simplicity and devops must be dead simple. For one thing, to me that means a monorepo with both the Sveltekit front end _AND_ the back end.

Also, I plan to use a menagerie of AIs to build everything: Claude Code, Claude Code for Web, Codex, Codex in the Cloud, and more. So it needs to be easy for those systems not only to reason about the overall thing, but not get lost in how to replicate the environment. I know each of these has a different way of spinning up environments, and I want to support them all. I'm not planning on using Docker myself on localhost, if that means connecting remotely into the IDE, I tried that once and it was a pain.

Also, I love Github Actions as a CI system. Require PRs to submit to main.

## The Architecture

## Single Domain Makes Auth Easier

Single origin and seamless Django admin. In production, route by path on the same domain:

- /djadmin/ → Django
- /api/ → Django Ninja
- / and everything else → static Svelte build (served by the same reverse proxy)
  Because Django is the auth authority, users can authenticate once and switch to /djadmin/ without a separate login.

On localhost, dev proxy:

- Run both dev servers, but have the browser only talk to SvelteKit, proxying to Django:
- Browser hits http://localhost:5173
- `/api/_` and `/djadmin/_` are proxied to http://127.0.0.1:8000

Because the browser always talks to a single origin — localhost:5173 in dev, yourdomain.com in prod — Django's standard session cookie auth just works with zero special handling. No CORS headers needed, no JWT complexity, no "secure cookie on different subdomain" headaches. The cookie Django sets for /djadmin/ or a /api/auth/login/ endpoint is a same-origin cookie from the browser's perspective. SvelteKit's fetch calls to /api/ automatically include it.

CSRF works the same way. Django sees requests coming from the same origin, so its CSRF middleware is satisfied. You'll want to make sure SvelteKit reads the csrftoken cookie and sends it as X-CSRFToken on mutating requests, which is about 10 lines of a shared fetch wrapper.

Vite proxy in dev to kill CORS. Proxy /api and /djadmin to Django, to test authenticated flows without CORS thrash.

This is meaningfully simpler than any JWT or OAuth flow, and it's the same mental model in dev and prod — the proxy is just an implementation detail of how same-origin is achieved.

I'd rather not introduce Node into Prod, it's an expense and another thing to go wrong. But I've had enough headaches around authentication on localhost dev to be super wary, I want to nail this decision. Django will handle the auth.

### Authenicated vs Public

Authenticated app: Client-Side Rendering (CSR)

- Fast navigations after login
- Simplest deployment (static assets)
- No second runtime server (no Node process)

Public pages: prerender

- Great SEO and link previews (because they’re real HTML files)
- Still no Node server needed at runtime
- SvelteKit can do this per-route

## Database

- SQLite for dev and Postgres for prod

## Monorepo structure

```text
repo/
    backend/ # python project
        manage.py
        pyproject.toml  (or requirements.txt)
    frontend/ # sveltekit project
        package.json
    scripts/
        bootstrap # creates .venv, installs backend deps, npm ci
        dev # starts both Django and Svelte servers)
        test # runs backend tests; optionally frontend tests too)
        lint #
    Makefile
    README.md
    .env.example
```

## Devops Scripting

I'm thinking of POSIX shell scripts in ./scripts/ (lowest common denominator) with a Makefile as a thin convenience wrapper:

- scripts/bootstrap (creates .venv, installs backend deps, npm ci)
- scripts/dev (starts both Django and Svelte servers)
- scripts/test (runs backend tests; optionally frontend tests too)
- scripts/lint

Let me know if there's a better way.

## Django Ninja

To get first-class TypeScript bindings, make OpenAPI the contract and generate a typed client from it. Django Ninja is a good fit because it emits OpenAPI cleanly. Workflow:

1. Django publishes an OpenAPI spec (JSON) for your API
2. Frontend runs a generator that outputs:
   • TypeScript types
   • optionally an API client (fetch wrapper)
   In your monorepo:

- backend/ exposes OpenAPI at e.g. /api/openapi.json
- frontend/ has npm run api:gen, which: • downloads http://localhost:8000/api/openapi.json • generates frontend/src/lib/api/ (or similar) • formats it
