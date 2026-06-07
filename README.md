# Flipcommons

This is the source code for [Flipcommons](https://flipcommons.org/), an interactive, collaborative database of pinball knowledge.

It's sponsored and hosted by [The Flip](https://www.theflip.museum/), Chicago's playable pinball museum.

## Architecture

This is a Django + SvelteKit monorepo. SvelteKit handles the user-facing frontend. Django owns the backend: the database data model, APIs, and it also serves Django's admin UI.

- **Backend**: Django + Django Ninja API at `/api/`, admin at `/djadmin/`
- **Frontend**: SvelteKit with Node SSR for public routes and CSR-only authenticated app routes
- **Auth**: Session-based, same-origin (no JWT, no CORS)
- **Dev proxy**: Vite proxies `/api/`, `/djadmin/`, `/media/`, and `/static/` to Django
- **Production routing**: Caddy fronts SvelteKit SSR and Django inside one Railway service

## Getting started

**Requirements**: Python 3.14+, Node 24+, [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io/) (or enable via `corepack enable`)

```bash
cp .env.example .env
make bootstrap
make dev
```

Then open http://localhost:5173

To grant yourself Django admin access, sign in to the local site at http://localhost:5173 (which routes through WorkOS), then promote your account:

```bash
cd backend && uv run python manage.py grant_admin you@example.com
```

The admin password form is disabled — WorkOS is the only login surface — so `createsuperuser` produces a row that can never sign in.

## Commands

| Command               | What it does                                               |
| --------------------- | ---------------------------------------------------------- |
| `make bootstrap`      | Install all deps, run migrations, generate API types       |
| `make dev`            | Start Django + SvelteKit dev servers                       |
| `make test`           | Run pytest (backend) + vitest (frontend)                   |
| `make lint`           | Run ruff (backend) + eslint/prettier (frontend)            |
| `make mypy`           | Run backend type checks                                    |
| `make quality`        | Lint + regenerate API types + svelte-check                 |
| `make codegen`        | Regenerate frontend API types from the backend schema      |
| `make pull-ingest`    | Download catalog data from R2                              |
| `make ingest-all`     | Fresh-DB bootstrap: full seed ingest, then all patches     |
| `make ingest-patches` | Apply pending data patches (the post-seed correction path) |
| `make agent-docs`     | Regenerate CLAUDE.md and AGENTS.md from docs/AGENTS.src.md |

## Project Structure

```text
backend/          Django project (uv, pyproject.toml)
frontend/         SvelteKit project (pnpm, package.json)
scripts/          POSIX shell scripts for bootstrap, dev, test, lint
docs/             Product, architecture, development, and operations docs
Makefile          Thin wrappers around scripts/
```

## Full Documentation

See [docs/README.md](docs/README.md) for the full documentation index

## Pull Requests

See [CONTRIBUTING.md](CONTRIBUTING.md) for the PR workflow.
