# Observability

We use **[Sentry.io](https://sentry.io)** to learn when production has problems before a user has to tell us. Error capture and alerting — nothing else. No tracing, no profiling, no session replay, no analytics.

In Sentry, we have two projects:

- `flipcommons-backend`: Python/Django
- `flipcommons-frontend`: JavaScript/SvelteKit — both SSR and browser report here

## Sentry config

For the Sentry-side configuration (env vars, scrubbing rules, alert rules), see [Hosting.md § Sentry](Hosting.md#sentry).

## The master switch: DSN presence

A **DSN** (Data Source Name) is Sentry's name for the per-project URL to posts events to. It identifies the project and authenticates the write — it's a public write-only key by design, not a secret. Each of our two projects has its own DSN.

Each runtime's SDK init runs only when its own DSN env var is non-empty: the backend gates on `SENTRY_DSN`, the frontend (SSR + browser) gates on `PUBLIC_SENTRY_DSN`. Local, CI, and test environments leave both unset and the init blocks no-op. There is no per-environment matrix and no runtime kill switch — disabling Sentry in prod means removing the DSN and redeploying.

## What we capture

- Unhandled backend exceptions (via `DjangoIntegration`).
- Unhandled SSR and browser exceptions (via `@sentry/sveltekit`).
- Explicit `sentry_sdk.capture_*` calls for swallowed-but-noteworthy cases.

## Things we don't capture

Some of the things we explicitly don't capture:

- **Backend**: validation errors, expected permission denials, expected 404s, structured 4xx errors (rate limits, etc.).
- **Frontend**: `ResizeObserver` notifications, navigation aborts, `ChunkLoadError`, non-Error throws.

## Logs ≠ alerts

`logger.info/warning/error` flows to the container's log stream and stays there. To send to Sentry, code must call the Sentry SDK's `capture_*` API explicitly. On the backend, `LoggingIntegration(level=INFO, event_level=None)` attaches log records as breadcrumbs on real events but never promotes them to standalone Sentry events. This keeps authz denials, validation errors, and rate-limit hits out of the alert stream by construction.

## Working with production logs

[production_logs/](../production_logs/README.md) pulls these logs out of Railway and Sentry and builds a queryable database over them. Use it for incidents rather than reading the raw exports: it encodes the classification caveats below as data, so `severity` is not taken at face value, and it records what each export actually covers.

## Structured logs in Railway

Railway derives the `severity` you filter on in the log explorer from the line itself: a JSON line's `level` field wins, and a plain-text line is classified by the stream it arrived on — stdout becomes `info`, stderr becomes `error`. Python's `StreamHandler` writes to stderr, so unformatted output arrives tagged as an error whatever its real level, and `severity:error` stops meaning anything.

Both Python processes therefore emit JSON in production: Django via `settings.LOGGING`, gunicorn via `logconfig_dict` in `backend/gunicorn.conf.py`. Both use `RailwayJSONFormatter` from `backend/config/log_format.py`, which also folds tracebacks into the message so a crash is one log event rather than one per stack frame. Dev keeps the plain-text format. Caddy already emits its own structured JSON and needs nothing. Gunicorn's access log stays off — Caddy logs every request with more detail.

Anything passed as `extra=` is flattened into the same JSON object, which is what makes it filterable — `logger.info("authz.deny", extra={"user_id": ...})` becomes a `user_id` attribute you can query on, where the same value inside the message string would not be. The formatter's own fields (`level`, `message`, `logger`, `time`, `pid`) win a name collision, so an `extra` key can never rewrite the severity Railway reads.

That flattening makes `extra=` a publish. Railway's log store has none of the scrubbing described under Privacy below — no `EventScrubber`, no server-side rules — so keep personal data out of it. Internal ids, activity names and error codes are fine; emails, tokens, IPs and request bodies are not.

Four sources still classify by stream, all of them expected:

- **The Postgres service.** Its image writes every `LOG:` line to stderr, so routine checkpoints and WAL archiving read as errors. Not fixable without forking the image — scope the log explorer to the web service instead.
- **Python `warnings` and Node SSR.** Warnings bypass `logging` entirely. In Node, `console.error` genuinely is an error, but `console.warn` reads as one too.
- **Node SSR request logging.** SvelteKit's server writes a line per request (`[404] GET /wp-login.php`) straight to the console, so on a service taking real traffic these outnumber everything that went through Python logging.
- **Container start and the predeploy step.** Railway narrates its own lifecycle (`Starting Container`), and the predeploy script's `manage.py check` and `migrate` run before gunicorn and write to stdout, where `self.stdout.write` never touches `logging`.

Most app lines therefore do not carry a level of their own, and that is the healthy state rather than a symptom. Whether the formatter is running is answered by whether Python lines appear **at all** — they carry `pid`, which nothing else emits — and not by what share of lines lack it, which mostly measures how much traffic the site is taking.

## Privacy

Sentry **does not store**: emails, IPs, request bodies, cookies, session tokens. (Some never leave the app — the SDK is configured not to extract them. The rest are stripped server-side at ingest by Sentry's Advanced Data Scrubbing rules before storage.)

Sentry **does store**: route name, HTTP method, status code, exception type/message/stack trace, release SHA, environment, user id and username (authenticated requests only), `auth_state` tag (`"auth"`/`"anon"`), full User-Agent (plus `ua_family` tag for filtering).

Differnt bits of this enforcement live in different layers:

- Sentry SDK init options
- A Sentry-provided Python `EventScrubber`
- Sentry Advanced Data Scrubbing rules — see [Hosting.md § Sentry](Hosting.md#sentry) for the dashboard half.

## Release correlation

Events and uploaded sourcemaps are both tagged with `RAILWAY_GIT_COMMIT_SHA`, so production stack traces resolve to source and issues tie to a specific deploy in Sentry.
