# Observability

We use:

- [Sentry.io](#sentry): error reporting
- [Log analytics](#log-analytics): production log analysis
- [Discord](#product-events): product notifications like user signups

## Sentry

We use [Sentry](https://sentry.io) for error capture and alerting and nothing else: no tracing, no profiling, no session replay, no analytics.

### Sentry config

For the Sentry-side configuration (env vars, scrubbing rules, alert rules), see [Hosting.md § Sentry](Hosting.md#sentry).

### Sentry projects

In Sentry, we have two projects:

- `flipcommons-backend`: Python/Django
- `flipcommons-frontend`: JavaScript/SvelteKit — both SSR and browser report here

### The master switch: DSN presence

A **DSN** (Data Source Name) is Sentry's name for the per-project URL to posts events to. It identifies the project and authenticates the write — it's a public write-only key by design, not a secret. Each of our two projects has its own DSN.

Each runtime's SDK init runs only when its own DSN env var is non-empty: the backend gates on `SENTRY_DSN`, the frontend (SSR + browser) gates on `PUBLIC_SENTRY_DSN`. Local, CI, and test environments leave both unset and the init blocks no-op. There is no per-environment matrix and no runtime kill switch — disabling Sentry in prod means removing the DSN and redeploying.

### What we capture

- Unhandled backend exceptions (via `DjangoIntegration`).
- Unhandled SSR and browser exceptions (via `@sentry/sveltekit`).
- Explicit `sentry_sdk.capture_*` calls for swallowed-but-noteworthy cases.

### What we don't capture

Some of the things we explicitly don't capture:

- **Backend**: validation errors, expected permission denials, expected 404s, structured 4xx errors (rate limits, etc.).
- **Frontend**: `ResizeObserver` notifications, navigation aborts, `ChunkLoadError`, non-Error throws.

### Logs don't go to Sentry

`logger.info/warning/error` flows to the container's log stream and stays there. To send to Sentry, code must call the Sentry SDK's `capture_*` API explicitly. On the backend, `LoggingIntegration(level=INFO, event_level=None)` attaches log records as breadcrumbs on real events but never promotes them to standalone Sentry events. This keeps authz denials, validation errors, and rate-limit hits out of the alert stream by construction.

So a fault reaches Sentry only by propagating uncaught or through an explicit `capture_*` call. Propagating is the default and the cheapest: Django logs the traceback at ERROR and fires `got_request_exception` in the same step, so the log line and the event pair for free. Converting a fault into a status-coded response breaks that pairing in both frameworks:

- Backend: never `raise HttpError(5xx, ...)` for a fault; let it propagate. `test_no_5xx_http_error.py` enforces this and explains the mechanism.
- Frontend: a loader that hits an upstream fault throws a plain `Error` or lets the fetch rejection propagate. SvelteKit's `error()` is for expected 4xx outcomes only; `handle-error.ts` explains why.

Where a swallow is deliberate — an `on_commit` callback, a login path that must land on a styled error page — the code that swallows it must also call `sentry_sdk.capture_exception()`.

## Logs

### Log analytics

[production_logs/](../production_logs/README.md) pulls logs from our production systems -- Railway, Bunny.net and Sentry -- and builds a DuckDB over them. Use the DuckDB rather than reading the raw exports: it encodes the classification caveats below as data, so `severity` is not taken at face value, and it records what each export actually covers.

### Structured logs in Railway

Railway derives the `severity` you filter on in the log explorer from the line itself: a JSON line's `level` field wins, and a plain-text line is classified by the stream it arrived on — stdout becomes `info`, stderr becomes `error`. Python's `StreamHandler` writes to stderr, so unformatted output arrives tagged as an error whatever its real level, and `severity:error` stops meaning anything.

Everything the app logs on purpose therefore emits JSON in production. Both Python processes use `RailwayJSONFormatter` from `backend/config/log_format.py` — Django via `settings.LOGGING`, gunicorn via `logconfig_dict` in `backend/gunicorn.conf.py` — and Node SSR uses `getLogger()` from `frontend/src/lib/log.ts`. The two emit the same field names so one query spans both, and each folds a traceback or stack into the message, so a crash is one log event rather than one per frame. Dev keeps the plain-text format on both sides. Caddy already emits its own structured JSON and needs nothing. Gunicorn's access log stays off — Caddy logs every request with more detail.

On the frontend the fix matters most for warnings: Node writes `console.warn` to stderr alongside `console.error`, so before `$lib/log` every SSR warning was indistinguishable from a fault. An ESLint rule (`no-restricted-syntax` on `console.*`, in `frontend/eslint.config.js`) keeps new code from reintroducing one; repo scripts under `frontend/scripts/` are exempt, being CLI tools that never touch the request path. Off the server the logger falls through to `console.*` — devtools' object inspector and source-mapped stacks beat a JSON string there, and no aggregator reads browser console output. Both branches are selected by `import.meta.env` flags, so each bundle keeps only its own.

Scalars passed as `extra=` are flattened into the same JSON object, which is what makes them filterable — `logger.info("authz.deny", extra={"user_id": ...})` becomes a `user_id` attribute you can query on, where the same value inside the message string would not be. The formatter's own fields (`level`, `message`, `logger`, `time`, `pid`) win a name collision, so an `extra` key can never rewrite the severity Railway reads.

That flattening makes `extra=` a publish. Railway's log store has none of the scrubbing described under Privacy below — no `EventScrubber`, no server-side rules — so keep personal data out of it. Internal ids, activity names and error codes are fine; emails, tokens, IPs and request bodies are not.

**Only strings, numbers, booleans and `None` are emitted; every other value is dropped.** That rule exists because `extra=` is not a channel we control end to end. `django.utils.log.log_response` attaches the live `HttpRequest` to every record it emits, and `HttpRequest.__repr__` carries the full path _including the query string_ — on `/api/auth/callback/` that is a live OAuth code. A formatter willing to stringify objects would publish it on any unhandled 500. Django's own `status_code` still comes through, and the path is already in the message, so nothing useful is lost. Non-finite floats are dropped for a different reason: `NaN` and `Infinity` are Python spellings that no JSON parser accepts, and one of them makes the whole line unparseable, sending Railway back to classifying it by its stream.

The filter narrows the blast radius of a misconfiguration rather than removing it. At DEBUG, `django.db.backends` logs every query with `extra={"sql": ..., "params": ...}`; the bound params are a sequence and get dropped, but the query text is a string and would be published. That logger is pinned to `WARNING` in `settings.LOGGING` — keep it there.

Four sources still classify by stream, all of them expected:

- **The Postgres service.** Its image writes every `LOG:` line to stderr, so routine checkpoints and WAL archiving read as errors. Not fixable without forking the image — scope the log explorer to the web service instead.
- **Python `warnings`.** They bypass `logging` entirely, so they reach stderr unformatted and read as errors.
- **Runtime output that isn't ours.** adapter-node announces its own boot (`Listening on http://0.0.0.0:3000`), and a dependency writing straight to the console bypasses `$lib/log` — the ESLint rule reaches our source, not `node_modules`. Both land on stdout and read as `info`, which is harmless.
- **Container start and the predeploy step.** Railway narrates its own lifecycle (`Starting Container`), and the predeploy script's `manage.py check` and `migrate` run before gunicorn and write to stdout, where `self.stdout.write` never touches `logging`.

Whether the Python formatter is running is answered by whether Python lines appear **at all**. They carry `pid`, which nothing else emits — the SSR logger deliberately omits it, since SSR is one process and the field would carry no information there. That absence is also what tells the two structured emitters apart: an SSR line carries `logger` without `pid`, which is how `railway_lines.emitter` classifies it.

## Product events

We have a private Discord channel to which we send product events an Admin wants to hear about — a new account today, first edits and destructive editorial actions later.

These go through `notify_admins()` in `backend/apps/core/admin_notifications.py`. For enablement see [Hosting.md § Discord](Hosting.md#discord).

The payload lands in a channel with no scrubbing and no retention policy, so it carries only data that is already public on the site: usernames, entity names, links. Never emails, IPs or tokens — the same line drawn for `extra=` under [Structured logs in Railway](#structured-logs-in-railway).

Delivery is best-effort, not guaranteed.

Sentry would be the wrong home for these: it groups `capture_message` events by message and its alert rules fire on _new_ issues and regressions, so a recurring product event would alert once and then stay silent forever.

## Privacy

Sentry **does not store**: emails, IPs, request bodies, cookies, session tokens, local variable values in tracebacks. (Some never leave the app — the SDK is configured not to extract them. The rest are stripped server-side at ingest by Sentry's Advanced Data Scrubbing rules before storage.)

Sentry **does store**: route name, HTTP method, status code, exception type/message/stack trace, release SHA, environment, user id and username (authenticated requests only), `auth_state` tag (`"auth"`/`"anon"`), full User-Agent (plus `ua_family` tag for filtering).

Differnt bits of this enforcement live in different layers:

- Sentry SDK init options
- A Sentry-provided Python `EventScrubber`
- Sentry Advanced Data Scrubbing rules — see [Hosting.md § Sentry](Hosting.md#sentry) for the dashboard half.

## Release correlation

Events and uploaded sourcemaps are both tagged with `RAILWAY_GIT_COMMIT_SHA`, so production stack traces resolve to source and issues tie to a specific deploy in Sentry.
