# robots.txt

This is the plan for introducing `robots.txt` to the project. SvelteKit owns public pages, so the file lives there as a `+server.ts` endpoint. Two jobs: gate non-prod deploys from crawlers entirely (via the `ALLOW_SEARCH_ENGINE_INDEXING` env var), and tell crawlers not to fetch non-page server endpoints (`/api/`, `/djadmin/`, `/_sentry_test`).

Addresses the "gating non-prod deploys" and "crawler traffic for non-page paths" concerns in [`SearchEngines.md`](SearchEngines.md); per-page index exclusion lives in [`NoindexMeta.md`](NoindexMeta.md), and the affirmative "what to index" signal lives in [`Sitemap.md`](Sitemap.md).

## What robots.txt is and isn't for

Per [Google's current guidance](https://developers.google.com/search/docs/crawling-indexing/robots/intro) (Bing and others behave similarly): **robots.txt is for managing crawl traffic, not for keeping pages out of the index.** A URL `Disallow`-ed in robots.txt can still appear in search results (URL + anchor text, no snippet) if anything links to it. The recommended mechanism for "do not index this page" is per-page `<meta name="robots" content="noindex">`, covered in [`NoindexMeta.md`](NoindexMeta.md).

Concretely:

- **In scope for robots.txt:**
  - Non-prod deploys → `Disallow: /` to keep crawlers off the deploy entirely (preview/staging have no external inbound links, so crawl-block is sufficient).
  - Non-page server endpoints (`/api/`, `/djadmin/`, `/_sentry_test`) → `Disallow:` to prevent crawl traffic against them.
- **Out of scope (handled in `NoindexMeta.md`):** user-facing pages we want kept out of the index (`/login`, `/signup`, `/search`, `/kiosk/*`, `/*/edit`, …). These are real pages with potential inbound links; we want crawlers to fetch them (so they see the `noindex` meta) but not index them. Putting them in robots.txt `Disallow` would actively prevent the noindex from working.

## Goals

- Don't accidentally index preview/staging deploys — a missing or wrong flag must fail safe (un-indexed), not leak.
- Keep crawlers off non-page server endpoints.
- Keep robots.txt small and static — the production body is a fixed list of server-endpoint paths, not a derived projection of the route tree.

## 1. Per-deployment indexability signal

Whether a given deploy should be crawled is a deploy-identity question, and the answer needs to stay correct as we add environments (preview, staging, future prod-like services). The constraints we're designing against:

- **Preview/staging must not leak into any search engine index.** A preview deploy with an `https://` origin and `DEBUG=false` looks production-shaped to any heuristic — sniffing `SITE_ORIGIN` for a hostname or keying off `NODE_ENV` will silently misclassify it.
- **Read-time default must be off.** If the flag is ever read without being set — local dev, a misconfigured env, an emergency rollback that drops env vars — the safe outcome is "not indexable." Production is the one place that opts in.
- **Deploys must declare intent.** A new preview service that ships without the flag set is exactly the leak we're trying to prevent. The read-time default protects against accidents at runtime; a deploy-time check forces the operator to make the call before the service goes live.
- **Typos must fail safe.** `"True"` or `"1"` quietly disabling indexing on prod is a much better failure than the reverse.
- **The signal has to be readable from SvelteKit (Node).** `robots.txt` is a SvelteKit endpoint, so the source of truth needs to be available without a Django round-trip per request.

A single opt-in env var satisfies all four — production explicitly turns it on, every other environment (local dev, preview, staging, future services) inherits the safe default with no config.

### Mechanism

- `ALLOW_SEARCH_ENGINE_INDEXING` — an env var, set by a human operator in each environment's config (Railway's service settings for deployed envs, a developer's local `.env` for local dev). Nothing auto-detects or auto-populates the value. Read-time default when unset is off. Operators set it to `true` on the production Railway service, `false` on every other deployed environment (preview, staging), and either value (or unset) locally — only set locally when a developer wants to test the corresponding `robots.txt` output.
- Read via a tiny `lib/server/search-engine-indexable.ts` helper so the rule is single-sourced (and reusable by the sitemap endpoint in [`Sitemap.md`](Sitemap.md)). Parse strictly: only the literal string `"true"` enables indexing; anything else (including `""`, `"1"`, `"yes"`, `"True"`) is treated as off.
- Document in `.env.example` as commented-out, with a note that local dev defaults to off and only needs setting for testing.
- A deploy check (see § 3) enforces the stronger rule under `manage.py check --deploy`: the value MUST be present and MUST be the literal `"true"` or `"false"`. Local `make dev` never trips this — the requirement applies only to real deploys, where forgetting to declare intent on a new preview service is the failure mode we care about.

## 2. robots.txt contents

> **Do not add user-facing routes (`/login`, `/search`, `/*/edit`, etc.) to this list** — they're handled by per-page `noindex` meta per [`NoindexMeta.md`](NoindexMeta.md). Adding a `Disallow:` for them blocks crawling, which means crawlers never see the `noindex` and the URL can still appear in results via inbound links.

When `ALLOW_SEARCH_ENGINE_INDEXING != "true"`:

```text
User-agent: *
Disallow: /
```

When `ALLOW_SEARCH_ENGINE_INDEXING == "true"`:

```text
User-agent: *
Disallow: /api/
Disallow: /djadmin/
Disallow: /_sentry_test
```

The production list is intentionally short: only paths that are server endpoints (not user-facing pages). User-facing non-indexable pages — `/login`, `/signup`, `/search`, `/kiosk/*`, `/*/edit`, etc. — are kept out of the index via per-page `<meta name="robots" content="noindex">` per [`NoindexMeta.md`](NoindexMeta.md), not via robots.txt `Disallow`. Putting them here would block crawlers from ever seeing the `noindex` meta, leaving them visible in search results via inbound links.

The `Sitemap:` line is intentionally absent in this PR; [`Sitemap.md`](Sitemap.md) adds it once `/sitemap.xml` exists.

### Deployment routing

No Caddyfile changes needed. The current `@django` matcher in `Caddyfile` only catches `/api`, `/djadmin`, `/media`, `/static`, so `/robots.txt` routes to SvelteKit (Node, port 3000) by default.

## 3. Deploy validation — `ALLOW_SEARCH_ENGINE_INDEXING`

Validated at the earliest point it's consumed (deploy/runtime). Pattern and conventions per `docs/DeployChecks.md`.

Frontend env vars are validated in Python because backend and frontend share the Railway env (per `docs/DeployChecks.md` § "Frontend checks belong in Python"). Add to `backend/apps/core/checks.py` (alongside `check_observability_env`):

- **`ALLOW_SEARCH_ENGINE_INDEXING`** — `@register(Tags.security, deploy=True)` check that errors when `ALLOW_SEARCH_ENGINE_INDEXING` is empty, and errors when set to anything other than the literal `"true"` or `"false"`. Every deployed environment must declare its intent (catches the new-preview-service-leaks-into-search-indexes failure mode) and the strict-shape rule catches typos like `"True"` or `"1"` that would silently leave production un-indexed. Local dev is unaffected: the check is `deploy=True`, so it only runs under `manage.py check --deploy`. New error ids `core.E303` (missing) and `core.E304` (malformed).

Tests in `backend/apps/core/tests/test_checks.py` (matching the existing pattern): one test per error id — flip the env state, assert the message id appears (or doesn't).

The check is deploy-gated (`deploy=True`), so it only runs under `manage.py check --deploy` — i.e., Railway's `preDeployCommand`. Reproduce locally per `docs/DeployChecks.md` § "Running deploy checks locally".

## 4. Tests

- **Backend (pytest):** one test per `core.E303` / `core.E304` error id in `apps/core/tests/test_checks.py`.
- **Frontend (vitest):** `robots.txt` returns the `Disallow: /` body when `ALLOW_SEARCH_ENGINE_INDEXING != "true"`, and the production body (with the three non-page disallows) when `== "true"`. Snapshot test of both bodies.

## 5. Implementation order

1. Add `ALLOW_SEARCH_ENGINE_INDEXING` to `.env.example` (commented-out, with a note that it's only needed for local testing) and write `lib/server/search-engine-indexable.ts`.
2. Add the `ALLOW_SEARCH_ENGINE_INDEXING` deploy check in `apps/core/checks.py`, with tests. Verify locally per `docs/DeployChecks.md` § "Running deploy checks locally".
3. `frontend/src/routes/robots.txt/+server.ts` — gate on `ALLOW_SEARCH_ENGINE_INDEXING`, emit the appropriate static body. Frontend test per § 4.
4. Verify locally: `curl localhost:5173/robots.txt` with and without `ALLOW_SEARCH_ENGINE_INDEXING=true` in `.env`.
5. Set `ALLOW_SEARCH_ENGINE_INDEXING=true` on the production Railway service and `ALLOW_SEARCH_ENGINE_INDEXING=false` on every preview/staging service (separate manual step — not part of the PR). The deploy check refuses promotion if any deployed env leaves the value unset or sets it to anything other than `"true"` or `"false"`.

## Considered alternatives

- **Constance config instead of env var.** Rejected: robots.txt is served by SvelteKit (Node), so a Django/constance value would need an API hop per request. Constance also has no per-environment visibility concept, loses the deploy-refusal gate (every env gets the default), and a single admin click on a security-adjacent toggle leaves no audit trail. Env var changes show up in Railway's deploy history.
- **Sniff `SITE_ORIGIN` hostname or key off `NODE_ENV`/`DEBUG`.** Rejected: preview/staging services run with `DEBUG=false` and an `https://` origin, so any heuristic silently misclassifies them. An explicit flag stays correct as we add environments.
- **Required env var everywhere (including local dev).** Considered. Rejected: forces every developer to set a var they don't care about for local work. Defaulting to off at read time keeps local ergonomic; the deploy-time check still forces every real env to declare intent.
- **Derive the production `Disallow:` list from the route tree.** Considered. Rejected after switching to the noindex-meta strategy for user-facing pages: the remaining production disallows are non-page server endpoints (`/api/`, `/djadmin/`, `/_sentry_test`), which don't live in the SvelteKit route tree anyway. A small static list is more honest than a derivation that walks a tree to find three paths.

## Open questions

None.
