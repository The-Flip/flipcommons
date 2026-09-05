# Serve Static Assets from CDN

**Superseded 2026-09: assets are same-origin; see [Hosting.md](../../Hosting.md).** The body below is kept as history.

Goal: serve SvelteKit's content-hashed, immutable build output (`/_app/immutable/*`) through a CDN so first-visit asset latency drops for users far from the Railway origin (Virginia).

## Status: ✅ Implemented

This plan has been implemented.

## Scope

### The actual goal

Everything under `/_app/immutable/*`:

- hashed JS chunks, including the vendor-sentry and vendor-posthog splits configured in `frontend/vite.config.ts`
- hashed CSS
- hashed assets emitted by the build

### Served from CDN as a side-effect

By virtue of how SveltKit works, we end up CDN'ing all files referenced through SvelteKit's asset machinery, which all carry the `paths.assets` prefix automatically once the env var is set. This includes:

- `favicon.png` (via `%sveltekit.assets%` in [`app.html`](../../../frontend/src/app.html))
- `social_default.png` (via the `assets` helper from `$app/paths`)
- `/_app/version.json` (via SvelteKit's client runtime, which fetches `${assets}/_app/version.json` for deploy-version polling). This one came along with the flip rather than as a deliberate target — the unhashed file in tension with Bunny's 30-day default TTL forced a 60s `Cache-Control` and a CORS preflight handler in Caddy to keep deploy detection working.

### Reaches the CDN as a side effect of CSS being CDN-served

- `/fonts/*.woff2` — referenced from hashed CSS via relative `url()`, which resolves against the CSS file's URL. The `<link rel="preload" href="/fonts/lora-latin.woff2">` in [`app.html`](../../../frontend/src/app.html) is hand-written and stays on origin.

### Not CDN-fronted

Hand-written URLs `paths.assets` doesn't rewrite:

- `/fakes/*.avif` — referenced from the dev-only [style-lab page](../../../frontend/src/routes/style-lab/+page.svelte) as raw paths. Low traffic; convert through `assets` if it ever ships to users.

### Explicitly out of scope

- SSR'd HTML responses.
- `/static/*` (Django admin assets served by WhiteNoise) — low-volume, admin-only, not worth the additional pull-zone surface area.
- `/media/*` (user uploads) — already served by Bunny CDN in front of iDrive e2 on `media.flipcommons.org`. See [Hosting.md](../../Hosting.md).

## CDN: Bunny.net

**Bunny pull zone on `static.flipcommons.org`, wired up via SvelteKit's `kit.paths.assets`.**

### Why Bunny

- We already have the vendor relationship, billing, and DNS pattern from `media.flipcommons.org`. Adding a second pull zone is mechanical, not a new integration.
- Pull-from-origin model means no separate deploy step — assets land on the CDN the first time anyone requests them after a deploy.
- Hashed filenames make `cache-control: public, max-age=31536000, immutable` safe with zero invalidation plumbing.

### Why not Railway's edge CDN

Railway's CDN sits in front of the entire service, which would require revisiting the `X-Real-IP` / `Forwarded` trust chain and the `RATE_LIMIT_TRUST_PROXY_HEADERS` contract documented in [Hosting.md → Client IP trust](../../Hosting.md#client-ip-trust). A Bunny zone scoped to hashed asset paths doesn't sit in front of HTML/API/admin, so it leaves IP trust and rate limiting alone.

### Why `static.flipcommons.org`

`static.` is the clearest signal of intent, mirrors the issue title, and pairs naturally with the existing `media.flipcommons.org` for user uploads (the conventional static-vs-media split).

## Order of operations

Stand the CDN up first and verify it works end-to-end **before** flipping a single URL in the app. The Bunny zone is dormant until SvelteKit emits absolute asset URLs.

1. **Create Bunny pull zone**, origin = current Railway public hostname.
2. **Attach hostname** `static.flipcommons.org` — DNS CNAME + Bunny-issued SSL cert.
3. **Smoke-test by hand.** Pick a known hashed asset from origin and confirm it pulls through and caches:

   ```sh
   # Get a real hashed URL from the live site
   curl -sI https://flipcommons.org/ | grep -o '/_app/immutable/[^"]*\.js' | head -1
   # Fetch it via the new CDN host — should pull from origin first time, hit on second
   curl -sI https://static.flipcommons.org/_app/immutable/entry/start.<hash>.js
   curl -sI https://static.flipcommons.org/_app/immutable/entry/start.<hash>.js
   ```

   Verify on the second request: `cdn-cache: HIT` (or equivalent Bunny header), and the origin `cache-control: public, immutable` is preserved.

4. **Flip the app.** Set `kit.paths.assets` from a `CDN_URL` build env var in [`frontend/svelte.config.js`](../../../frontend/svelte.config.js), declare the ARG/ENV in [`Dockerfile`](../../../Dockerfile), set `CDN_URL=https://static.flipcommons.org` in Railway, and deploy. SvelteKit will emit absolute asset URLs in every SSR'd page from that point forward. The same env gate adds the CDN origin to the report-only CSP `script-/style-/font-/connect-src` directives (`connect-src` matters because the hourly `/_app/version.json` poll runs through `fetch()`).

`CDN_URL` is env-gated rather than hardcoded because SvelteKit applies `paths.assets` in dev mode too — Vite would emit CDN URLs for chunks that only exist locally and `make dev` would 404 every asset.

Railway builds fail closed if `CDN_URL` is missing (per [Reviewing.md → Deployment/runtime assumptions](../../Reviewing.md#deploymentruntime-assumptions)) so a forgotten variable can't silently ship same-origin assets. `CDN_URL` accepts any `https://<host>` origin so the deploy isn't pinned to a single hostname (alternate Bunny zone, provider swap, etc.); the production value is `https://static.flipcommons.org`. Three valid states:

- `CDN_URL=https://<host>` — CDN enabled (production: `https://static.flipcommons.org`)
- `CDN_URL=DISABLED` — CDN explicitly off (rollback path; also the right value for any Railway preview deploys that inherit `RAILWAY_GIT_COMMIT_SHA` but shouldn't route through production's pull zone)
- unset / empty — allowed locally; build error in Railway

Rollback is setting `CDN_URL=DISABLED` in Railway and redeploying — no code revert, no CDN config to unwind.

## Setup gotchas to nail before the flip

### CORS for modulepreload, fonts and the version-poll preflight

SvelteKit emits `<link rel="modulepreload" crossorigin>` for the immutable chunks. Cross-origin module preload and `@font-face` requests require `access-control-allow-origin` on the asset response, or the browser rejects them. Bunny injects `access-control-allow-origin: *` on the pull zone for `/_app/immutable/*`, `/fonts/*` and `/favicon.png` — verify with `curl -I -H "Origin: https://flipcommons.org" https://static.flipcommons.org/_app/immutable/...` before flipping.

Bunny's CORS rule does **not** cover `/_app/version.json`, and SvelteKit's version poll [sends `pragma` and `cache-control` request headers](../../../frontend/node_modules/@sveltejs/kit/src/runtime/client/utils.js) — both non-safelisted, so the browser issues an OPTIONS preflight first. Without explicit CORS on that path, the preflight fails and deploy detection silently breaks in every tab. [`Caddyfile`](../../../Caddyfile) handles this at origin: `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Headers: Cache-Control, Pragma` on the GET response, plus a `handle` block that short-circuits OPTIONS to a 204 with `Access-Control-Max-Age: 7200` so browsers don't re-preflight on every hourly poll. Bunny passes the preflight through to Caddy verbatim.

### Path-only cache key

Hashed asset URLs don't take query strings, but make sure Bunny's cache key is path-only (no query-string variance) so cache hit rate stays high. If a future caller appends a cache-buster, the CDN should ignore it.

### `paths.assets` implications

`kit.paths.assets` requires `paths.relative: false` and causes SvelteKit to emit absolute URLs for all asset references, including in SSR'd HTML. That's the desired behavior — the first byte of HTML points the browser at the CDN — but any code that does string surgery on asset URLs needs to be reviewed. (A quick grep for `_app/` in the frontend should turn up anything risky.)
