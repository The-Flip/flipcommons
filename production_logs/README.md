# Production logs

Production log acquisition and analysis.

```text
production_logs/
  dumps/bunny, railway, sentry    Raw log dumps. Gitignored.
  analyze/production_logs.duckdb  The log db. Derived, gitignored.
  analyze/sql/*.sql               SQL that creates the log db.
```

```bash
# Analyze
production_logs/query "FROM coverage;"   # one-shot
production_logs/query                    # interactive session
production_logs/query --stale "..."      # query without rebuilding; says how old
production_logs/analyze/sql/build        # rebuild, gating on the checks
production_logs/analyze/test             # build against fixtures and assert

# Acquire
production_logs/pull/all --start 2026-08-26      # every source, that day through today
production_logs/pull/bunny --start 2026-08-26 --end 2026-08-26
production_logs/pull/railway --start 2026-08-26  # deploy + http + build logs, all services
production_logs/pull/sentry --start 2026-08-01   # issues, events, releases
```

## Analyze

`query` rebuilds if the SQL or a dump is newer than the db, so the query is always current. Drop new dumps into `dumps/` and `query`; the readers glob.

Start from these:

| relation      | what it answers                                                       |
| ------------- | --------------------------------------------------------------------- |
| `coverage`    | what each export actually covers. Read before any cross-source claim. |
| `summary`     | volume and problems per stream. The answer to "how many errors".      |
| `edge_health` | CDN and Railway per minute, side by side. The shape of an outage.     |
| `timeline`    | every observation, all sources, in `ts` order. The stream to read.    |
| `problems`    | `timeline` at error or worse, with the invented severities removed.   |

Every relation states its own grain and the wrong answer it prevents:

```sql
SELECT table_name AS rel, comment FROM duckdb_tables() WHERE internal = false
UNION ALL SELECT view_name, comment FROM duckdb_views() WHERE internal = false;
```

**This project's own probes are in these logs.** `make test-edge` sends real requests to the real site. `is_synthetic` marks those rows in `bunny_requests` and `railway_requests`, and `bunny_health`, `edge_health`, `railway_health`, `timeline` and `problems` leave them out. The base relations, `coverage` and `summary` keep every row, so filter yourself when reading one directly:

```sql
SELECT ... FROM bunny_requests WHERE NOT is_synthetic
```

A probe of your own is excluded the same way if its user-agent starts with `flipcommons-`.

## Acquire

Every puller takes the same window: `--start <YYYY-MM-DD>` (required) through `--end <YYYY-MM-DD>` (default today), inclusive UTC days. Rows are written verbatim as the vendor hands them down, merged on row identity into one file per UTC day — so a re-pull only ever adds rows, and re-pulling mid-incident is always safe. Each dump directory carries a `manifest.json` recording per-file coverage and whether the file's day was over at pull time; a missing credential aborts before anything is fetched. `pull/all` preflights all three keys and runs the pullers in order of perishability.

- `pull/bunny` needs `BUNNY_API_KEY` — the account API key from [the Bunny dashboard](https://dash.bunny.net/account/settings), not a storage-zone password. It reads the Logging API v2, which answers a day outside retention with a clean error: reported, skipped, exit 0.
- `pull/railway` needs `RAILWAY_TOKEN` — a project token (project Settings > Tokens). It talks to Railway's GraphQL API directly: deploy logs environment-wide, and HTTP and image-build logs per deployment (enumerated for the window, removed and failed deployments included), all paged until the window is exhausted. A build that dies before the builder starts emits zero build lines — an absence the dump can faithfully hold but never explain; the deployment's `deploymentEvents` in the dashboard or API are the only record of such a failure.
- `pull/sentry` needs `SENTRY_API_TOKEN`, and fails if its haul disagrees with Sentry's own `count()` — a silently short pull looks exactly like a quiet week. Events merge on their id, so the dump can hold events past Sentry's retention that no later pull could recover; `issues.json` — mutable state, so nothing to append along — merges on the issue id with each row stamped `_observed_at`. Surfaced as `sentry_issues.observed_at`, and worth checking before quoting a status or a lifetime count, because a row can be older than the window you asked for.

**Bunny logs expire after a rolling three days.** Sentry keeps 90 and Railway keeps what the plan allows (7 days on Hobby, 30 on Pro), so those tolerate being pulled after the fact; Bunny does not, and the edge is the only source that sees a request the origin never received. Pull it within two days of anything worth keeping.

### Work in this order

Diagnosis is reconstructing a sequence, and sequence is the one axis you cannot filter away. Slicing by service and severity first is how these logs are browsed and how the vendor UIs are laid out, but it is the wrong way in: during a real outage here, 402 requests failed at Railway's edge while the application logged 36 lines, 10 of them at `error`, and Sentry recorded nothing.

1. **`FROM coverage`** — what can you see? Every later claim is bounded by it.
2. **`FROM edge_health`** — the shape, before reading any line. Onset and recovery timestamps come from here, and the CDN column is the only one reflecting what users actually got. Read across a row, never down two. It is the apex zone against Railway.
3. **Correlate the onset** against `sentry_releases` and deployments. Most incidents are a change.
4. **Read the edge unfiltered** — `FROM timeline` over minutes, not hours, around onset, all sources and severities, ordered by `ts`. Causes routinely log at `info`, or are the last line before silence.
5. **Then slice** by service, status, path, text — to quantify a hypothesis, not to find one.
6. **Try to break it.** An explanation that covers the spike but not the silences is usually wrong.

Habits to keep. Prefer **rates to counts**, because a window rarely covers every source equally — read `coverage` before quoting one. Treat **severity as a ranking, not a filter**: Railway invents a level for every line that is not JSON, so count `summary` and rank `timeline` on `level_confidence` rather than filtering on `level`.

A trap in any window whose `static` rows are misses rather than 301s: the zone pulled through the `apex` zone rather than from Railway, so a static miss is also an apex request and only apex misses reach Railway. Compare `apex` alone against a Railway relation; adding `static` counts each of its misses twice at the CDN. The origin can still legitimately exceed the apex by around a tenth, because Railway also logs requests that never passed Bunny. `host` no longer tells them apart, and neither does status, since `@direct_origin` and the site's own canonical redirects both answer 301. `upstream_ms` does: it is time inside the container, so a direct hit Caddy answers itself lands near 1ms while a redirect the app rendered was proxied to Node and lands above 60ms.

## Editing the analytics

See [analyze/sql/README.md](analyze/sql/README.md).
