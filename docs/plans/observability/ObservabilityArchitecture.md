# Observability Architecture

Also see:

- [Observability.md](Observability.md) — purpose, audiences, goals
- [ObservabilityVendors.md](ObservabilityVendors.md) — vendor evaluation
- [ObservabilityPlan.md](ObservabilityPlan.md) — detailed plan

## Architecture relies on Sentry

We use **Sentry.io** for error capture, alerting, and uptime. See [ObservabilityVendors.md](ObservabilityVendors.md) for the choice rationale. This doc heavily relies on Sentry-specific features (`EventScrubber`, Advanced Data Scrubbing, `ignore_errors`, …).

## System shape

Three in-process Sentry SDKs (Django, SvelteKit SSR, browser) feed events to Sentry through layered privacy enforcement; alerts fan out to per-maintainer destinations.

```text
exception (Django | SSR | browser)
   │
   ▼
In-process Sentry SDKs
   │   ├── Sentry `ignore_errors` / `ignoreErrors` drops the "don't capture" list
   │   ├── Python: EventScrubber redacts known-bad keys (default denylist)
   │   └── JS: `sendDefaultPii: false` + request-body suppression + omitted integrations
   ▼
Ingest to hosted Sentry service
   │   └── Sentry Advanced Data Scrubbing rules drop pattern-shaped PII and query strings
   ▼
Sentry storage (separate backend + frontend projects)
   │
   ▼
alert rules ──▶ per-maintainer destination (email/chat)
```

## Trust boundaries

- User id and username cross to Sentry (usernames are public per [Privacy.md](../../Privacy.md)); email and IP do not. The keep-list at each `set_user` / `setUser` call site is the chokepoint.
- Sourcemaps are upload-only build artifacts and never ship to browsers.
- Backend and frontend events live in separate Sentry projects so Sentry's per-platform issue-grouping works cleanly and the JS sourcemap pipeline isn't asked to resolve Python frames.

## Design decisions

### Logs and error events are decoupled

Application logging (`logger.info/warning/error`) flows to stdout, collected by Railway. It never becomes an alert-emitting event. To page someone, code must call the SDK's explicit capture API — the contract is "if you want it in Sentry, say so." This keeps the [non-alert list](Observability.md#alerting) (authz denials, validation errors, rate-limit hits) out of the alert stream by construction, not by allowlist.

### Privacy is delegated to Sentry's built-in layers

Sentry layers do the work. SDK init options refuse extraction at the source in both runtimes; on Python the built-in `EventScrubber` adds key-based denylist redaction on top; server-side Advanced Data Scrubbing rules catch pattern-shaped PII at ingest for both. The JS SDK has no separate scrubber class — its in-process privacy posture comes entirely from init options and integration choices (see [§ Privacy enforcement](#privacy-enforcement)). A custom `before_send` / `beforeSend` hook would reimplement what those layers already do, in two languages, with no runtime test that the JS and Python versions stay in sync. Sentry tutorials reach for that hook first; we don't.

The trade-off: privacy is configured in two places (SDK init in code, dashboard rules in the Sentry UI) instead of one. The dashboard rules become a deploy prerequisite ([ObservabilityPlan.md § Prerequisites](ObservabilityPlan.md#prerequisites)) and are verified per-project at first-event time. We accept the split because reimplementing email/IP regex matching and request-body redaction ourselves costs more to maintain and is more likely to drift than two dashboard rules per project.

### DSN presence is the master environment switch

SDK init runs only when the ingestion-endpoint env var (DSN) is non-empty. Local, CI, and test runs leave it unset and the init block is a no-op. No per-environment config matrix, no runtime kill switch, no "disabled in dev" branch — one variable, same guard in both runtimes.

### Sentry defaults we don't want are disabled at init

Session replay, profiling, full-request performance tracing, and the user-feedback widget appear in our [non-goals](Observability.md#non-goals). They are explicitly disabled (or never integrated) at SDK init, so privacy and noise discipline show up in code review rather than being assumed from Sentry.

## Capture scope

What we capture:

- unhandled exceptions on the backend (framework integration)
- unhandled exceptions in SSR and the browser
- explicit capture calls for swallowed-but-noteworthy cases

What we don't capture:

- validation errors (`ValidationError`, Ninja schema rejects)
- expected 401/403 from authz enforcement (see [Authz.md](../../Authz.md))
- expected 404s, including bot/scanner traffic
- rate-limit denials
- WorkOS callback states that resolve to a user-facing error page
- `IntegrityError`s used as control flow (e.g. unique-constraint races)
- unambiguous browser noise: `ResizeObserver` loop notifications, `AbortError`, `ChunkLoadError`, "Non-Error promise rejection captured"

The "don't capture" list is enforced at the SDK boundary via `ignore_errors` (Python) and `ignoreErrors` (JS). `DjangoIntegration` hooks `got_request_exception`, which fires for `ValidationError`, `Http404`, `PermissionDenied`, etc. _before_ Django maps them to a 4xx response. The concrete lists live in dedicated modules per runtime so tests import the same list rather than redeclare it.

Generic network-failure strings (`Failed to fetch`, `Load failed`) are deliberately **not** in the browser list — they can mask real production breakage. Add them only if they dominate the noise floor in production.

`IntegrityError`s used as control flow are not on the list — we can't blanket-ignore them without also dropping real DB errors; those sites are expected to swallow the exception locally.

## Privacy enforcement

Sentry layers, innermost to outermost. Layer 2 is Python-only; layers 1 and 3 apply to both runtimes.

1. **SDK options at init.** `send_default_pii=False` in both runtimes. Request bodies suppressed: `max_request_body_size="never"` (Python), `httpIntegration({ maxIncomingRequestBodySize: 'none' })` (JS server). The JS browser SDK does not extract request bodies at all. The JS SDKs further omit `replayIntegration` and `feedbackIntegration` so those capture surfaces never load. Net effect across both runtimes: the SDK never extracts request bodies, cookies, the user's IP, or the user's email.
2. **`EventScrubber(recursive=True)` — Python only.** Sentry's built-in key-based scrubber, passed explicitly to `sentry_sdk.init()`. Redacts ~30 default-denylist names (`password`, `secret`, `token`, `csrf*`, `cookie`, `authorization`, session keys, …) across headers, body keys, extras, contexts, breadcrumb `data`, and span data. Recurses into nested dicts and lists. The JS SDK has no equivalent class; on the JS side, key-name protection reduces to "don't put secrets in the few keys the SDK extracts," which combined with `sendDefaultPii: false` (no cookies, no extra headers) and the request-body suppression in layer 1 leaves a much smaller surface to begin with.
3. **Sentry Advanced Data Scrubbing rules.** Server-side rules applied at ingest, before storage. Cover what the in-process layers can't reach: pattern-shaped PII inside free-form string values, and unconditionally-extracted fields like `request.query_string`. Apply to both projects identically.

The posture prefers strictness: when in doubt, drop. Anything not on the kept-fields list below should not reach Sentry (layers 1–2) or its storage (layer 3).

### Advanced Data Scrubbing rules (configured per Sentry project)

Configured at Project Settings → Security & Privacy → Advanced Data Scrubbing on each project. Required rules:

- `[Mask] [@email] from [$string]` — masks every RFC-shaped email in any string field.
- `[Mask] [@ip] from [$string]` — masks every IPv4/IPv6 address in any string field.
- `[Remove] [$request.query_string]` — drops the query string entirely. `DjangoIntegration` extracts it unconditionally and no SDK option suppresses it; this rule is the only way.

The placeholder for `[Mask]` is `[Filtered]`, matching the SDK's `EventScrubber` token. Without these rules, an email or IP interpolated into a log message, or a query string carrying user input, would be stored.

### Kept fields

Per [Observability.md § Privacy](Observability.md#privacy):

- route or endpoint name, HTTP method, status code
- exception type, message, stack trace
- release SHA, environment, deploy timestamp
- user id and username, for authenticated requests
- anonymous/authenticated state (also surfaced as the `auth_state` tag — `"auth"` / `"anon"`)
- User-Agent header (full value, plus a coarse `ua_family` tag — `chrome`/`firefox`/`safari`/`edge`/`bot`/`other`/`unknown` — for filtering). The full UA ships unredacted; the tag is a filter aid, not a privacy measure. The contract is "no email, no IP," not "no UA."

### User attribution

Backend: `SentryScopeMiddleware` runs after `AuthenticationMiddleware` and attaches `{id, username}` for authenticated requests (no user for anonymous), plus the `auth_state` and `ua_family` tags on every request.

Frontend: `Sentry.setUser(...)` is called from the auth store's `set()` function — every login, refresh, and logout flows through it. The keep-list at that call site is the **privacy chokepoint** for the user dict; a refactor that adds `email` would ship it. A regression test and a call-site docstring pin this. SSR-side user attribution is deferred for v1 (the browser store doesn't run server-side); the gap is narrow because backend events still carry full attribution.

## Environment separation

SDK init runs **only when the DSN is set**. The init block is the master switch:

- production → DSN set in Railway → init runs → events flow
- local dev / CI / pytest → no DSN → init no-ops → no events
- a maintainer testing SDK changes locally → opts in by setting the DSN themselves; if they do, use a separate Sentry project or a `development` environment tag to avoid mixing with real prod

`environment="production"` is hardcoded today. If staging or preview environments are ever introduced, this becomes env-var-driven per Railway environment.

Disabling observability in production requires removing the DSN and redeploying — there is no runtime kill switch. If Sentry is itself down or rate-limiting us, the SDK queues and drops events internally without crashing the app; we accept the temporary blindness.

## Alerting

Per-recipient routing is configured in Sentry. Each founder is a member of the org with their own destination (email or chat). Adding or removing a maintainer is a single membership change — see [ObservabilityVendors.md § Access & offboarding](ObservabilityVendors.md#access--offboarding).

Alert rules, mirrored across both projects:

- **new issue** → alert all maintainers
- **regression of a resolved issue** → alert all maintainers
- **uptime check failure** → alert all maintainers
- **spike in an existing issue** → alert all maintainers, threshold tuned from production data after launch

Non-alerting activity (assignment changes, comments, resolution events) stays in-product.

Default issue assignment: **unassigned**. Either founder may grab an issue. Diffusion-of-responsibility hasn't been a real failure mode at this team size, and double-paging both founders for every event creates noise. Revisit if anything falls through the cracks.

## Uptime

Single monitor against `/__health` on a 5-minute interval. The endpoint already exists ([frontend/src/routes/\_\_health/+server.ts](../../../frontend/src/routes/__health/+server.ts)) and proxies to the Django `/api/health` ([backend/config/api.py:56-60](../../../backend/config/api.py#L56-L60)), which performs a `SELECT 1`. A successful response proves Caddy + SvelteKit SSR + Django + DB are all alive in one ping.

Keep `/__health` shallow. `SELECT 1` is the right depth: deep enough to catch a dead app server or DB, shallow enough not to false-positive on transient external blips. Do **not** grow it into a per-subsystem dependency check (R2, Redis, external APIs) — those failures should surface as errors when product code hits them, not as uptime flapping.

The monitor is hosted in Sentry for operational simplicity — one org, one login, one offboarding step, shared alert routing. See [§ Sentry wiring](#sentry-wiring) for the fallback if the free uptime quota is exceeded.

## Sentry wiring

The concrete bindings — projects, packages, init sites, file paths. Everything above describes _what_ we do; this section describes _where it lives_.

### Projects

Two projects on Sentry.io:

- `flipcommons-backend` — Python/Django
- `flipcommons-frontend` — JavaScript/SvelteKit

### Backend

- Package: `sentry-sdk[django]`.
- Init: `config/settings.py`, gated on `SENTRY_DSN`. See the file for the literal options.
- "Don't capture" list: [`backend/config/sentry_options.py`](../../../backend/config/sentry_options.py).
- Per-request scope (user, `auth_state`, `ua_family`): `SentryScopeMiddleware`, after `AuthenticationMiddleware`.
- Logging integration: `LoggingIntegration(level=INFO, event_level=None)` — log records at INFO+ attach as **breadcrumbs** on real events, and **never become standalone Sentry events**. This is the implementation of [Logs and error events are decoupled](#logs-and-error-events-are-decoupled).

Three non-obvious init options worth knowing about when reading the file:

- `auto_session_tracking=True` — emits release-health sessions so the dashboard surfaces crash-free request rate per release. Works without tracing enabled.
- `shutdown_timeout=5` — Railway sends SIGTERM and waits ~10s for exit. The default 2s flush window risks losing the exception that _caused_ a crash.
- `traces_sample_rate=0.0`, `profiles_sample_rate=0.0` — tracing and profiling are non-goals; off explicitly so they show up in review.

### Frontend

- Package: `@sentry/sveltekit` (10.8.0+). Use the adapter, not raw `@sentry/browser`, so the framework integration stays on the doc-blessed path.
- Init sites:
  - `frontend/src/instrumentation.server.ts` — `Sentry.init({...})` for SSR. Loaded by SvelteKit before any other server import when `experimental.instrumentation.server: true` is set in `svelte.config.js`. Required since `@sentry/sveltekit` 10.8.0 — initializing in `hooks.server.ts` is no longer load-order-safe with the OpenTelemetry-powered server SDK.
  - `frontend/src/hooks.server.ts` — exports `handleError = Sentry.handleErrorWithSentry(...)`. No `Sentry.init` here.
  - `frontend/src/hooks.client.ts` — `Sentry.init({...})` plus `handleError = Sentry.handleErrorWithSentry(...)` for browser errors.
  - `frontend/vite.config.ts` — the `sentrySvelteKit` plugin for sourcemap upload.
- "Don't capture" list: `frontend/src/lib/sentry/ignore-errors.ts`, imported by both inits.
- User attribution and `auth_state` tag: the auth store's `set()` function (see [§ User attribution](#user-attribution)).
- Replay and feedback integrations are never added — not merely disabled.

### Releases & sourcemaps

`@sentry/vite-plugin` (wrapped by `sentrySvelteKit`) handles sourcemap upload at build time, tagged with the release name from `RAILWAY_GIT_COMMIT_SHA`. The plugin's `sourcemaps.filesToDeleteAfterUpload` is configured explicitly so the maps don't ship to browsers (the plugin doesn't delete by default). Sentry resolves browser stack traces against the uploaded maps at issue time. The same SHA tags backend events at runtime, so events from both projects share a release name.

Required build-time env: `SENTRY_AUTH_TOKEN` (org-scoped Railway secret — the only Sentry value that is actually secret; the DSN is a public write-only key by design), `SENTRY_ORG`, `SENTRY_PROJECT`, and `RAILWAY_GIT_COMMIT_SHA`. All four are declared as `ARG`s in the frontend build stage of `Dockerfile` and `ENV`-promoted before `pnpm build` runs — multi-stage Docker doesn't inherit host env vars into build stages, so Railway's service vars only reach `vite build` for `ARG`s the Dockerfile explicitly declares. Forgetting one of those declarations silently produces a build with no sourcemaps uploaded.

**Three consumers, one source of truth.** `RAILWAY_GIT_COMMIT_SHA` (set by Railway) is the only release-name input the operator manages. Three places consume it and they must all agree, or events tag with a release that doesn't match what sourcemaps were uploaded under, and stack traces show as minified:

1. **Sourcemap upload** — `frontend/vite.config.ts` reads `process.env.RAILWAY_GIT_COMMIT_SHA` directly during `vite build`.
2. **SSR runtime** — `frontend/src/instrumentation.server.ts` reads `RAILWAY_GIT_COMMIT_SHA` from `process.env` directly at SSR-process startup. NOT via `$env/dynamic/private` — SvelteKit loads this file before its `$env/*` shim is initialized, so the shim resolves to undefined and `Sentry.init` silently skips. The Sentry SDK is unusable from here without that workaround.
3. **Browser** — `frontend/src/hooks.client.ts` reads `PUBLIC_RAILWAY_GIT_COMMIT_SHA` via `$env/dynamic/public`. Since Railway only injects the un-PUBLIC variant, this is derived by mirroring in two places: `frontend/vite.config.ts` at build time (for any `$env/static/public` consumers), and `scripts/start-production` at SSR-runtime (for the actual `$env/dynamic/public` lookup the browser bundle uses).

If you find yourself "simplifying" one of those mirrors, the failure mode is silent — events still ship, sourcemap matching just stops working, and you only notice when a real prod stack trace lands in Sentry minified. The `core.E207` preflight check (`backend/apps/core/checks.py`) backs this by refusing to promote a deploy where `RAILWAY_GIT_COMMIT_SHA` is unset.

### Uptime monitor

Sentry Uptime hosts the `/__health` check from [§ Uptime](#uptime). Uptime failures land in the same issue stream as exceptions. If the free uptime quota is ever exceeded, slot in a free [UptimeRobot](ObservabilityVendors.md#uptimerobot) check next to it — nothing else depends on which service answers the ping.

### First-event verification

Runbook for verifying a working install (initial setup, SDK upgrade, sourcemap config change, env-var change) lives in [ObservabilityPlan.md](ObservabilityPlan.md). The staff-gated trigger routes (`/api/sentry_test` and `/_sentry_test`) are gated on `Activity.OBSERVABILITY_DEBUG`.
