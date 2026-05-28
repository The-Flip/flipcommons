# Admin Dashboard

## Status: ✅ Implemented

Resolves [#415](https://github.com/The-Flip/flipcommons/issues/415).

## Overview

A mobile-first page for admins showing how the system is doing at a glance: signups, edits, uploads.

**Route**: `/admin/dashboard` (SvelteKit), with `/admin` redirecting to it. `/admin` is the SPA admin area, which will host other admin-only pages over time.

**Scope**: production-database stats only. PostHog (pageviews) and Sentry (errors) are deferred.

The DB-stats subset implemented here is the easy slice of [analytics/AnalyticsDbStatsPlan.md](analytics/AnalyticsDbStatsPlan.md). Retention cohorts and the 80/20 curve live there, not here.

## URL structure

```text
/admin          → redirects to /admin/dashboard (v1 has only one admin page;
                  when a second lands, /admin is promoted to a real index)
/admin/dashboard → the at-a-glance dashboard
```

Routing layout:

```text
src/routes/admin/
  +layout.server.ts       ← auth gate (Activity.VIEW_ADMIN_AREA)
  +page.server.ts         ← throw redirect(303, '/admin/dashboard')
  dashboard/
    +page.server.ts       ← fetches /api/pages/admin/dashboard
    +page.svelte          ← renders the cards
```

The auth gate runs in `+layout.server.ts` before the redirect, so unauthenticated/non-admin users get bounced to login (or 403'd) rather than redirected to a page they can't reach. Future admin-only SPA pages drop into `src/routes/admin/<thing>/` and inherit the gate for free.

## Auth gate

One predicate, enforced once at the `/admin/*` layout boundary.

- New `Activity.VIEW_ADMIN_AREA = "admin_area.view"` in [`apps/core/authz/types.py`](../../backend/apps/core/authz/types.py). Verb-led `VIEW_` makes the read-only scope explicit; any future mutating admin action gets its own activity rather than silently riding on this one.
- Registered in [`apps/core/authz/rules.py`](../../backend/apps/core/authz/rules.py) with predicates `is_authenticated, email_verified, is_staff` — same shape as `OBSERVABILITY_DEBUG`.
- The Ninja endpoint that serves the stats is decorated `@requires(Activity.VIEW_ADMIN_AREA)`.
- SvelteKit `src/routes/admin/+layout.server.ts` calls `requireCapability({ fetch, url, request, activity: 'admin_area.view' })` from [`$lib/require-capability.server`](../../frontend/src/lib/require-capability.server.ts) — same helper used by [`_sentry_test/+page.server.ts`](../../frontend/src/routes/_sentry_test/+page.server.ts). Per the project rule in [CLAUDE.md](../../CLAUDE.md) "Authorization goes through activities" — no raw `is_staff` checks in SSR locals.
- Every page that later lands under `/admin/*` inherits the gate automatically. No second predicate, no copy-pasted check.

## Backend

New page-API endpoint (per [ApiDesign.md § Endpoint design](../ApiDesign.md#endpoint-design)):

```text
GET /api/pages/admin/dashboard  →  AdminDashboardPageSchema
```

Tagged `private`, `auth=django_auth`, gated `@requires(Activity.VIEW_ADMIN_AREA)`. Lives at `backend/apps/core/api/admin_dashboard_page.py` — no single app owns the payload (spans `accounts.User`, `provenance.ChangeSet`, `media.Media`), so it goes under `core`.

### Schema

```python
class AdminMetricSchema(Schema):
    last_24h: int
    last_7d: int
    total: int
    last_at: datetime | None  # most recent event of this kind, or None

class AdminDashboardPageSchema(Schema):
    signups: AdminMetricSchema
    edits: AdminMetricSchema
    uploads: AdminMetricSchema
    generated_at: datetime
```

Three uniform metric cards. An "active editors" distinct-count was considered and dropped from v1 — it's the seed of the 80/20 curve already deferred to [analytics/AnalyticsDbStatsPlan.md](analytics/AnalyticsDbStatsPlan.md), and an isolated number without trend is weak signal next to the windowed metrics.

### Definitions

- **Signups**: `User` rows. Time field: `date_joined`.
- **Edits**: `ChangeSet` rows where `user_id IS NOT NULL` (any `action`). Ingest ChangeSets are excluded by virtue of having a null user. Time field: `created_at`.
- **Uploads**: `Media` rows. Time field: `created_at` (only completed uploads persist).

### Time windows

Rolling from the moment the endpoint is called:

- `last_24h`: `created_at >= now() - interval '24 hours'`
- `last_7d`: `created_at >= now() - interval '7 days'`
- `total`: all rows.

No timezone gymnastics. The numbers reflect "the last 24 hours" in the literal wall-clock sense, which is what an admin means when they glance at the page.

### Query shape

One query per metric — three aggregates and a `MAX(created_at)` in a single `SELECT` per table. The three queries are independent and could run in parallel via `asyncio.gather`, but the synchronous version is fine for v1 (each query is sub-ms on tables of this size).

## Frontend

Routing layout repeated from [URL structure](#url-structure):

```text
src/routes/admin/
  +layout.server.ts       ← auth gate (Activity.VIEW_ADMIN_AREA)
  +page.server.ts         ← throw redirect(303, '/admin/dashboard')
  dashboard/
    +page.server.ts       ← fetches /api/pages/admin/dashboard via the typed client
    +page.svelte          ← renders the three cards
```

`dashboard/+page.server.ts` returns `{ stats }`. The page renders three cards stacked vertically; each card shows three time-windowed counts in a row plus a "last X" timestamp formatted with `smartDate(iso)` from [`$lib/dates`](../../frontend/src/lib/dates.ts) — adaptive output: "8:34pm" today, "Yesterday 6:30pm", "Monday 3pm", "Mar 14". When `last_at` is `null` (fresh DB, no rows of that kind yet), render `∅` in place.

### Auto-refresh every hour

`dashboard/+page.svelte` runs a `setInterval(() => invalidate(...), 60 * 60 * 1000)` on mount. SvelteKit re-runs `dashboard/+page.server.ts`, the typed client refetches, the cards update. Interval cleared on `onDestroy`. No reactive flicker beyond what `invalidate()` already does.

### Layout

Mobile-first. Vertical stack of cards on phones; same stack on desktop (this is a phone page first, the desktop view doesn't need columns). Uses existing `Page.svelte` and `FieldGroup.svelte` primitives where they fit — no new layout primitives.

Phone sketch:

```text
┌────────────────────┐
│ Flipcommons / Admin│
├────────────────────┤
│ Signups            │
│   24h   7d   total │
│    3    12   847   │
│ last: 6:30pm       │
├────────────────────┤
│ Edits              │
│   24h   7d   total │
│   18    94   5,213 │
│ last: 8:21pm       │
├────────────────────┤
│ Uploads            │
│   24h   7d   total │
│    7    41   2,108 │
│ last: Yesterday 9pm│
└────────────────────┘
(updated 12:04 PM · auto-refresh every hour)
```

## Testing

Backend (`apps/<location>/tests/`):

- Auth: anonymous → 401/403; non-staff → 403; staff w/o `email_verified` → 403; staff w/ `email_verified` → 200.
- Stats correctness: factory-built `User`, `ChangeSet`, `Media` rows across the time windows; assert each metric returns the expected counts.
- Ingest ChangeSets excluded: a ChangeSet with `user_id=NULL` does not contribute to edits.
- `last_at` semantics: empty table → `None`; populated → matches the latest `created_at`.

Frontend:

- `admin/+layout.server.ts` gate: unauthorized hits redirect / 403.
- `admin/+page.server.ts` redirect: authorized hit to `/admin` lands on `/admin/dashboard`.
- `admin/dashboard/+page.svelte`: renders the three metric cards from a fixture payload.
- `∅` empty-state: when `last_at` is `null`, the card renders `∅` instead of the formatted timestamp.
- `smartDate` already has its own tests in [`$lib/dates.test.ts`](../../frontend/src/lib/dates.test.ts); no new helper to test.

## Out of scope

- **PostHog inline** — pageviews, top URLs, referrer breakdown.
- **Sentry inline** — error/warning counts, latest incidents.
- **Retention cohorts** — see [analytics/AnalyticsDbStatsPlan.md](analytics/AnalyticsDbStatsPlan.md).
- **80/20 editor curve** — same plan doc.
- **Deploy SHA / deploy time** — Sentry already correlates events to releases per [observability/ObservabilityBackendPlan.md](observability/ObservabilityBackendPlan.md) "Release Correlation".
- **Per-user drill-downs**, **time-series sparklines**, **week-vs-week deltas** — wait for the v1 to be in use before designing v2.
- **Last 24h error count** (Sentry API) — single number, high signal, justifies the integration cost.
- **Last 24h pageviews** (PostHog API) — same shape.
- **First-edit conversion** (of last-7d signups, how many edited) — onboarding pulse.
- **Top-5 editors this week** — light 80/20 peek; a candidate for a `/staff/contributors` sub-page rather than the glance card.

## Implementation order

A suggested sequence. Each step is independently testable; don't move on until the previous step's tests are green.

1. **Activity.** Add `VIEW_ADMIN_AREA = "admin_area.view"` to [`apps/core/authz/types.py`](../../backend/apps/core/authz/types.py); register predicates `(is_authenticated, email_verified, is_staff)` in [`apps/core/authz/rules.py`](../../backend/apps/core/authz/rules.py). Unit test: predicates match `OBSERVABILITY_DEBUG`'s set.
2. **Backend page endpoint.** New module `apps/core/api/admin_dashboard_page.py` with `AdminMetricSchema`, `AdminDashboardPageSchema`, and the route handler. Register the router under `/api/pages/admin/`. Tag `private`, decorate `@requires(Activity.VIEW_ADMIN_AREA)`.
3. **Backend tests.** Auth matrix (anon / non-staff / staff w/o verified / staff w/ verified), per-metric counts across the time windows, ingest-ChangeSet exclusion, `last_at` empty-table → `None`. Use the existing `user_changeset` factory from [`apps/provenance/test_factories.py`](../../backend/apps/provenance/test_factories.py).
4. **API codegen.** Run `make codegen` to regenerate `frontend/src/lib/api/schema.d.ts`. Verify the new schema names appear as named exports, and that `Activity` now includes `'admin_area.view'`.
5. **Frontend route gate.** Create `frontend/src/routes/admin/+layout.server.ts` calling `requireCapability({ fetch, url, request, activity: 'admin_area.view' })` from [`$lib/require-capability.server`](../../frontend/src/lib/require-capability.server.ts) — copy the pattern from [`_sentry_test/+page.server.ts`](../../frontend/src/routes/_sentry_test/+page.server.ts). Test: anonymous → redirect to login; non-admin → redirect to verify-email; admin → passes through.
6. **Frontend `/admin` redirect.** `frontend/src/routes/admin/+page.server.ts` issues `throw redirect(303, '/admin/dashboard')`. Test: authorized hit lands on `/admin/dashboard`.
7. **Frontend dashboard page.** `frontend/src/routes/admin/dashboard/+page.server.ts` calls the typed client; `+page.svelte` renders. Extract a `MetricCard.svelte` (the three cards are near-identical). Format `last_at` via `smartDate` from [`$lib/dates`](../../frontend/src/lib/dates.ts); render `∅` when null.
8. **Auto-refresh.** Define `ADMIN_DASHBOARD_DEPEND_KEY = 'app:admin-dashboard'` in a sibling `_dependencies.ts` module (importable by both `+page.server.ts` and `+page.svelte` — non-`.server.ts` so the client can read it). `+page.server.ts` calls `depends(ADMIN_DASHBOARD_DEPEND_KEY)`; `+page.svelte` uses `setInterval(() => invalidate(ADMIN_DASHBOARD_DEPEND_KEY), 60 * 60 * 1000)` on mount and `clearInterval` on destroy. Also wire a `visibilitychange` listener that calls `invalidate(...)` when the tab returns to foreground — `setInterval` is throttled while backgrounded, and a phone-bookmark reopen should refresh immediately rather than waiting up to an hour. Prefer the dep-key indirection over passing the endpoint URL directly so the typed client stays the only place that knows the URL.
9. **Mobile UX check.** Load the route on a phone (or DevTools mobile viewport). Verify the cards stack cleanly, the title bar is readable, the `smartDate` strings don't overflow on the longest output ("Yesterday 11:30pm").
10. **Manual smoke.** Bookmark `/admin` on a phone; reopen; confirm the redirect lands on `/admin/dashboard` and the numbers look plausible against production-shape seed data.
