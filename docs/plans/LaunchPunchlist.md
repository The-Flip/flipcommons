# Flipcommons Public Launch Hardening Checklist

## Blockers — do before announcing

- [ ] **HSTS header** — One step remaining: `max-age=31536000` (#463).
- [ ] **Content Security Policy (CSP)** — report-only block shipped in #465 (`fcc3bb6`); SvelteKit emits via `kit.csp`, violations stream to Sentry. Enforce mode pending a week of clean reports; known gap: prerendered routes can't carry report-only headers, so they'll need a smoke-test before flipping.
- [ ] **Media backups** — Setup backups of user-uploaded media. iDrive e2's internal replication doesn't cover accidental/malicious deletes, nor ransomware.
- [ ] **Test DB restore** — Restore the most recent backup into a scratch Postgres, run smoke tests.

## Auth & abuse prevention

- [x] Rate limiting — pre-auth session+IP buckets (`apps/core/rate_limits.py`); per-user CREATE/EDIT/DELETE buckets applied via `@rate_limited(spec)` decorator (`apps/provenance/rate_limits.py`). Invariant test in `test_route_inventory.py` (#453) fails if a mutating route is missing or mismatched, plus OpenAPI boundary check requires `429: RateLimitErrorSchema` on every rate-limited route.
- [x] CSRF, session cookies, secure cookie flags conditional on `not DEBUG` (`backend/config/settings.py`).
- [x] WorkOS OAuth flow for login/signup.
- [x] **Email verification** — WorkOS guarantees verified emails on signup; no additional verification gate needed.
- [x] **Password reset / WorkOS dependency** — WorkOS is the only auth path by design; if WorkOS is down, the site is down. Accepted dependency, no fallback planned.
- [x] **Admin URL hardening** — Django admin moved to `/djadmin/` in #454 (`e860667`); `/admin/` reclaimed for the SvelteKit admin area. Default-path scanners no longer find Django.
- [x] **Django admin password login disabled** — #461 (`6979f5b`) routes admin auth through WorkOS only; login/password_change surfaces return 404 or redirect. Bootstrap flow is now `manage.py grant_admin <email>` after the user has signed up via WorkOS. Removes the only brute-forceable login path.
- [ ] **Confirm WorkOS bot detection is enabled** — Signup lives on WorkOS, so this is a dashboard check, not a code change. AuthKit has built-in bot detection / brute-force protection; verify it's switched on for the production tenant.
- [ ] **Abuse / report flow** — no way for users to flag content. At minimum link a "report" mailto on entity pages.

## Security hardening

- [x] `SECRET_KEY` required in prod, `DEBUG` defaults safely, `ALLOWED_HOSTS` env-driven.
- [x] Sentry PII scrubbing (`send_default_pii=False`, request bodies stripped).
- [x] PostHog privacy posture locked down (`autocapture: false`, no session recording, IP off); confirmed live in production for launch.
- [x] Baseline Caddy security headers (#449): `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options: DENY`.
- [x] Django `SECURE_*` headers intentionally off — Caddy→Django is loopback HTTP, so a redirect would break SSR. HTTPS terminates at the Railway edge.
- [ ] **Triage open Dependabot alerts** — GitHub currently reports 9 open vulnerabilities on `main` (2 high, 2 moderate, 5 low). Resolve each or document why it's acceptable to ship with before announcement.
- [x] **Review uploaded-media safety** — Audit done. Safe: 20MB API cap (`constants.py:53`), UUID-based S3 keys (non-enumerable, `storage.py:25`), default-private bucket, Pillow full-decode validation (`api.py:191`), per-user 60/hr rate limit, `@requires(Activity.MEDIA_EDIT)` + session-auth gated. SVGs rejected (not in allowed extensions). Two minor hardening gaps split out below.
- [ ] **Tighten image decompression-bomb defense** — `Image.MAX_IMAGE_PIXELS` is not set; the 20000×20000 dimension cap (`constants.py:49`) allows up to ~400M pixels (~1.6 GB RGBA decode). Set `MAX_IMAGE_PIXELS` explicitly in `apps/media/processing.py` (e.g. 64M).
- [ ] **Reject animated GIFs explicitly** — `process_original()` silently strips to the first frame. Add an `is_animated` check in `validate_image()` so the rejection is loud and intentional.
- [ ] **Review what's exposed in Sentry events** — confirm no auth tokens, raw bodies, or full URLs with sensitive query strings leak.

## Observability & operations

- [x] Sentry backend + frontend wired with release tagging from `RAILWAY_GIT_COMMIT_SHA`; confirmed live, both reporting errors.
- [x] Health route at `__health`.
- [x] Postgres `conn_max_age=600`, `conn_health_checks=True`.
- [x] **Production DB backups** — Daily snapshots confirmed in Railway (automated, retained).
- [x] **Production DB PITR** - Railway Postgres DB Point-In-Time-Recovery
- [x] **Alerting** — configure Sentry alert rules (5xx spike, new issue, performance regression).
- [ ] **Uptime monitoring** — external pinger hitting `__health` (UptimeRobot, Better Stack, etc.).
- [ ] **Forward-fix playbook** — We don't do traditional rollback. Document the decision tree: (a) bad code/config → roll forward with a new commit; (b) bad ingest → bulk-revert ChangeSets where `ingest_run = X` via `ChangeSetAction.REVERT`; (c) unrecoverable data loss → restore from backup. Plus: who runs each, and what the smoke-test signal is.
- [ ] **Bulk-revert path for a bad ingest run** — `ChangeSetAction.REVERT` exists per record; verify (or build) a one-shot path that reverts every ChangeSet from a given `ingest_run` in one transaction. Test on staging with a deliberately-bad fixture.
- [ ] **Migration failure rehearsal** — `railway.toml` pre-deploy runs `migrate --noinput`. Dry-run a deliberately-failing migration on staging to confirm the deploy aborts cleanly and the previous container keeps serving. Forward-fix the migration, redeploy.
- [ ] **Enable object-lock / delete-lock on iDrive e2 media bucket** — Defense-in-depth against accidental or malicious deletion (an errant `delete_unused_assets()` pass, leaked credentials). Requires a bucket migration since the existing bucket isn't versioned. Not a launch blocker once an external media backup (above) is in place — that's the primary recovery path.
- [ ] **Cache backend** — file-based cache is fine for one container, but rate-limit state is per-container. If/when you scale, move to Redis (Railway has a plugin).

## SEO & discoverability

- [x] `MetaTags.svelte` for OG/Twitter/canonical.
- [x] Default OG image (`og-default.png`).
- [x] **`robots.txt`** — SvelteKit `/robots.txt` endpoint landed in #460, gated on `ALLOW_SEARCH_ENGINE_INDEXING` (default deny; deploy check refuses any unset/non-literal value).
- [x] **Noindex signals on non-indexable routes** — `noindexHandle` in `hooks.server.ts` (#459) emits both `X-Robots-Tag: noindex` header and `<meta name="robots" content="noindex">` (via `transformPageChunk`) for any route where `isSearchEngineIndexable()` is false. Both signals are needed: the header reaches crawlers on non-HTML responses (e.g. `__data.json`), the meta survives header-stripping infrastructure.
- [x] **`sitemap.xml`** — Backend cached `/api/sitemap/` + per-page lastmod (#473); SvelteKit `/sitemap[[page=integer]].xml` route + `Sitemap:` line in `/robots.txt` (#474).
- [x] **SSR + SEO coverage of public pages** — All catalog listing pages converted CSR→SSR (#488 and predecessors); `catalog-listing` flipped to indexable in #488 (`f9ce53d`), which cascades to sitemap, noindex hook, and SSR test.
- [x] **Per-entity OG images** — MetaTags wired into listing wrappers in `f9ce53d`; `55451d7` added a branded 1200×630 default for imageless pages, the full `twitter:*` tag set, and fixed a wikilink-token leak in meta descriptions across 6 detail layouts.
- [x] **JSON-LD structured data** — schema.org `Product` / `CreativeWork` markup on pinball entity pages helps Google rich results.
- [x] Favicon (`favicon.png`) and theme-color (light + dark variants) in `app.html`.
- [x] **iOS home-screen + PWA-install affordances** — Full icon set landed in #476 (`30c61ad`): SVG favicon, 32px PNG fallback, `apple-touch-icon.png`, and `site.webmanifest` with 192/512/maskable app icons; `<link>` tags wired in `app.html`.
- [x] **Canonical domain** — Apex `flipcommons.org` is canonical. Caddy 301s `www.flipcommons.org` → apex (`Caddyfile:3-5`). `SITE_ORIGIN` for SvelteKit prerender/meta tags is `https://flipcommons.org`. No hardcoded `www.flipcommons.org` anywhere in code; the only `www` reference is the Caddy redirect rule itself.

## Content & legal

- [x] LICENSE (Apache 2.0).
- [x] ToS, Privacy Policy (includes PostHog and Sentry disclosure), Licensing pages exist.
- [x] About page.
- [x] **Contact / feedback channel** — `howdy@flipcommons.org` (About, Terms), `privacy@flipcommons.org` (Privacy Policy), `licensing@flipcommons.org` (Licensing).
- [x] **Account deletion** — Privacy Policy directs users to email `privacy@flipcommons.org` (deletions handled manually for now).
- [x] **Cookie consent** — only essential cookies are set (session + CSRF). PostHog is configured with `persistence: 'memory'` and does not set cookies, so EU consent requirements don't apply. Revisit if any tracker that sets cookies is added later.
- [ ] **Code of Conduct** — public collaborative knowledge site needs one. Add `frontend/src/routes/(legal)/conduct/` and link from footer and signup.
- [ ] **Contributor expectations** — short page or section describing what edits are welcome, what gets reverted, how disputes are handled (you have ChangeSet revert capability — surface the policy).
- [ ] **DMCA / takedown process** — A pinball catalog attracts copyright complaints (manufacturer images, manuals, ROM references). Publish a designated agent / email + a documented response process; link from the footer.

## User-facing polish

- [x] **Custom 404 / 500 pages** — SvelteKit covered by #450; Django admin is staff-only so default templates are fine.
- [ ] **Empty states** — search results, "no edits yet", new user dashboard. Walk through the app cold and note where copy is missing.
- [ ] **First-run experience** — what does a brand-new visitor see on the homepage? Is there a "what is this?" hook?
- [ ] **Loading states** — make sure SSR pages don't flash unstyled content and CSR transitions show feedback.
- [ ] **Mobile pass** — open the major pages on a phone-sized viewport.
- [ ] **Accessibility sweep** — keyboard nav, focus rings, alt text on entity images, `lang="en"` on `<html>`.

## Performance

- [ ] **Database index audit** — no custom indexes spotted in models. Check slow queries with `django-debug-toolbar` locally on representative pages, add indexes on filter/sort fields (slug already unique-indexed via constraints; check `status`, `type`, FK chains used in list queries).
- [ ] **N+1 audit on list pages** — Title/Model browse pages are the obvious risk. `select_related` / `prefetch_related` review.
- [x] **Immutable static assets via CDN** — #470 (`4558492`) flips `kit.paths.assets` to the Bunny pull zone at `static.flipcommons.org` when `CDN_URL` is set; hashed chunks, CSS, fonts, and the version.json poll all load from CDN. Caddy serves `/fonts/*` with `Cache-Control: public, max-age=1y, immutable`.
- [ ] **HTML response Cache-Control** — SvelteKit SSR pages still need explicit `Cache-Control` (private for authed pages, short public TTL for public pages). Static assets covered above.
- [ ] **Image sizing** — large source images served as-is hurt LCP. If Bunny isn't already doing on-the-fly resizing, configure it or pre-generate responsive variants.
- [ ] **Load test** — run a quick `k6`/`oha` against a few public pages to know your ceiling before announcement.
