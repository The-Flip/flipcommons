# robots.txt

This is the plan for introducing `robots.txt` to the project. SvelteKit owns public pages, so the file lives there as a `+server.ts` endpoint. Two jobs: gate non-prod deploys from crawlers entirely (via the `ALLOW_SEARCH_ENGINE_INDEXING` env var), and tell crawlers not to fetch the `/api/` JSON surface.

Addresses the "gating non-prod deploys" and "crawler traffic for non-page paths" concerns in [`SearchEngines.md`](SearchEngines.md); per-page index exclusion lives in [`NoindexMeta.md`](NoindexMeta.md), and the affirmative "what to index" signal lives in [`Sitemap.md`](Sitemap.md).

## Status: ✅ Implemented

This plan has been implemented.

## What robots.txt is and isn't for

Per [Google's current guidance](https://developers.google.com/search/docs/crawling-indexing/robots/intro) (Bing and others behave similarly): **robots.txt is for managing crawl traffic, not for keeping pages out of the index.** A URL `Disallow`-ed in robots.txt can still appear in search results (URL + anchor text, no snippet) if anything links to it. The recommended mechanism for "do not index this page" is per-page `<meta name="robots" content="noindex">`, covered in [`NoindexMeta.md`](NoindexMeta.md).

Concretely:

- **In scope for robots.txt:**
  - Non-prod deploys → `Disallow: /` to keep crawlers off the deploy entirely (preview/staging have no external inbound links, so crawl-block is sufficient).
  - The `/api/` JSON surface → `Disallow:` as a hygiene signal that this isn't a user-facing page tree.
- **Out of scope (handled in `NoindexMeta.md`):** user-facing pages we want kept out of the index (`/login`, `/signup`, `/search`, `/kiosk/*`, `/*/edit`, …). These are real pages with potential inbound links; we want crawlers to fetch them (so they see the `noindex` meta) but not index them. Putting them in robots.txt `Disallow` would actively prevent the noindex from working.
- **Deliberately omitted:** `/djadmin/` and `/_sentry_test`. Listing them here publishes their existence to anyone reading `robots.txt` — `/djadmin/` was renamed from Django's default `/admin/` partly for obscurity, and a public `Disallow:` undoes that. Nothing public links to either path, so well-behaved crawlers won't hit them; non-compliant scrapers ignore `robots.txt` anyway. Not advertising them is the better default.

## Goals

- Don't accidentally index preview/staging deploys — a missing or wrong flag must fail safe (un-indexed), not leak.
- Steer crawlers away from the `/api/` JSON surface.
- Keep robots.txt small and static — and don't use it to advertise endpoints that nothing public links to.

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
- Read via a tiny `lib/is-deployment-search-engine-indexable.server.ts` helper exporting `isDeploymentSearchEngineIndexable(): boolean`, so the rule is single-sourced (and reusable by the sitemap endpoint in [`Sitemap.md`](Sitemap.md)). Named to contrast with the existing per-route `isSearchEngineIndexable(routeId)` in `lib/route-metadata.server.ts` — that one answers "should this URL be indexed"; this one answers "should this whole deploy be indexed at all". The `search-engine` qualifier in the name leaves room for future indexability axes (internal search, sitemap-only inclusion, etc.) without ambiguity. The helper reads from `$env/dynamic/private` — **not** `$env/static/private`, which would bake the value in at build time and silently misclassify any environment that shares a build artifact. Parse strictly: only the literal string `"true"` enables indexing; anything else (including `""`, `"1"`, `"yes"`, `"True"`) is treated as off.
- Document in the repo-root `.env.example` (there is no `frontend/.env.example`) as commented-out, with a note that local dev defaults to off and only needs setting for testing.
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
```

The production list is intentionally minimal. `/djadmin/` and `/_sentry_test` are deliberately omitted — `robots.txt` is world-readable, so listing them advertises their existence (and undoes the obscurity of renaming `/admin/` → `/djadmin/`). Nothing public links to either path, so compliant crawlers won't find them; non-compliant scrapers ignore `robots.txt`, so a `Disallow:` wouldn't stop them anyway.

User-facing non-indexable pages — `/login`, `/signup`, `/search`, `/kiosk/*`, `/*/edit`, etc. — are kept out of the index via per-page `<meta name="robots" content="noindex">` per [`NoindexMeta.md`](NoindexMeta.md), not via robots.txt `Disallow`. Putting them here would block crawlers from ever seeing the `noindex` meta, leaving them visible in search results via inbound links.

The `Sitemap:` line is intentionally absent in this PR; [`Sitemap.md`](Sitemap.md) adds it once `/sitemap.xml` exists.

### Response headers

The `+server.ts` returns the body with:

- `Content-Type: text/plain; charset=utf-8` — the spec-mandated type for `robots.txt`; without it, some crawlers will refuse to parse the response.
- `Cache-Control: public, max-age=300` — crawlers refetch `robots.txt` frequently; a short cache prevents pointless regeneration. Five minutes is short enough that flipping `ALLOW_SEARCH_ENGINE_INDEXING` and redeploying takes effect promptly.

### Deployment routing

No Caddyfile changes needed. The current `@django` matcher in `Caddyfile` only catches `/api`, `/djadmin`, `/media`, `/static`, so `/robots.txt` routes to SvelteKit (Node, port 3000) by default.

## 3. Deploy validation — `ALLOW_SEARCH_ENGINE_INDEXING`

Validated at the earliest point it's consumed (deploy/runtime). Pattern and conventions per `docs/DeployChecks.md`.

Frontend env vars are validated in Python because backend and frontend share the Railway env (per `docs/DeployChecks.md` § "Frontend checks belong in Python"). Add to `backend/apps/core/checks.py` (alongside `check_observability_env`):

- **`ALLOW_SEARCH_ENGINE_INDEXING`** — `@register(Tags.security, deploy=True)` check that errors when `ALLOW_SEARCH_ENGINE_INDEXING` is empty, and errors when set to anything other than the literal `"true"` or `"false"`. Local dev is unaffected: the check is `deploy=True`, so it only runs under `manage.py check --deploy`. New error ids `core.E301` (missing) and `core.E302` (malformed). This starts a new `core.E3xx` group for security-tag checks, mirroring how `E1xx` clusters observability and `E2xx` clusters build/version.

**Why require it on every deployed env, not just prod.** The read-time default is safe (off), so an unset preview won't leak. But the deploy check can't distinguish prod from preview — there's no `IS_PROD` flag to key off — so the only way to force the _production_ operator to explicitly declare intent is to force _every_ operator to. Without that, prod can ship with the var unset, default off, and silently drop out of search indexes for weeks before anyone notices traffic crater. That's exactly the invisible-silent-failure mode [`DeployAutomation.md`](../../DeployAutomation.md) tells us to refuse: the false-positive cost (set one env var on a new preview service) is negligible; the false-negative cost (prod de-indexed, nobody notices) is catastrophic. Per `DeployChecks.md` § "Assert env-var shape, don't probe services", this check stays in-process and only reads `os.environ` — it does **not** fetch its own `/robots.txt` or otherwise probe the running service.

Tests in `backend/apps/core/tests/test_checks.py` (matching the existing pattern): one test per error id — flip the env state, assert the message id appears (or doesn't).

The check is deploy-gated (`deploy=True`), so it only runs under `manage.py check --deploy` — i.e., Railway's `preDeployCommand`. Reproduce locally per `docs/DeployChecks.md` § "Running deploy checks locally".

## 4. Tests

- **Backend (pytest):** one test per `core.E301` / `core.E302` error id in `apps/core/tests/test_checks.py`.
- **Frontend (vitest):** `robots.txt` returns the `Disallow: /` body when `ALLOW_SEARCH_ENGINE_INDEXING != "true"`, and the production body (with `Disallow: /api/`) when `== "true"`. Snapshot test of both bodies.

## 5. Implementation order

1. Add `ALLOW_SEARCH_ENGINE_INDEXING` to the repo-root `.env.example` (commented-out, with a note that it's only needed for local testing) and write `lib/is-deployment-search-engine-indexable.server.ts`.
2. Add the `ALLOW_SEARCH_ENGINE_INDEXING` deploy check in `apps/core/checks.py`, with tests. Verify locally per `docs/DeployChecks.md` § "Running deploy checks locally".
3. `frontend/src/routes/robots.txt/+server.ts` — gate on `isDeploymentSearchEngineIndexable()`, emit the appropriate static body with the headers per § 2. Frontend test per § 4.
4. Verify locally: `curl -i localhost:5173/robots.txt` with and without `ALLOW_SEARCH_ENGINE_INDEXING=true` in `.env`; check body **and** `Content-Type` / `Cache-Control` headers.
5. **Set Railway env vars _before_ merging the PR** — `ALLOW_SEARCH_ENGINE_INDEXING=true` on the production service, `=false` on every other deployed service (staging _and_ every existing per-PR preview service, not just the canonical ones). The new deploy check refuses any deploy where the value is unset or malformed, so the first post-merge deploy will fail on any service that hasn't been updated — including in-flight preview deploys for unrelated open PRs. Doing this step before merge keeps the deploy pipeline green; doing it after means a window where every service refuses to promote until an operator catches up.

## Considered alternatives

- **Constance config instead of env var.** Rejected: robots.txt is served by SvelteKit (Node), so a Django/constance value would need an API hop per request. Constance also has no per-environment visibility concept, loses the deploy-refusal gate (every env gets the default), and a single admin click on a security-adjacent toggle leaves no audit trail. Env var changes show up in Railway's deploy history.
- **Sniff `SITE_ORIGIN` hostname or key off `NODE_ENV`/`DEBUG`.** Rejected: preview/staging services run with `DEBUG=false` and an `https://` origin, so any heuristic silently misclassifies them. An explicit flag stays correct as we add environments.
- **Required env var everywhere (including local dev).** Considered. Rejected: forces every developer to set a var they don't care about for local work. Defaulting to off at read time keeps local ergonomic; the deploy-time check still forces every real env to declare intent.
- **Derive the production `Disallow:` list from the route tree.** Considered. Rejected after switching to the noindex-meta strategy for user-facing pages: the remaining production disallow is the `/api/` JSON surface, which doesn't live in the SvelteKit route tree anyway. A one-line static list is more honest than a derivation.
- **Also `Disallow: /djadmin/` and `/_sentry_test`.** Rejected: `robots.txt` is world-readable, so listing these advertises endpoints that nothing public links to (and undoes the obscurity of renaming `/admin/` → `/djadmin/`). Compliant crawlers won't find them without a link; non-compliant scrapers ignore `robots.txt`. Silence is the better default.

## Open questions

None.
