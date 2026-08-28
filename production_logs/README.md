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
production_logs/pull/sentry              # last 30 days; --days 90 is the ceiling
production_logs/pull/railway             # 10 deployments per service; --limit, --service, --since
production_logs/pull/bunny               # last 4 UTC days, every pull zone; --days, --zone
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

## Acquire

- `pull/sentry` needs `SENTRY_API_TOKEN`, and fails if its haul disagrees with Sentry's own `count()` — a silently short pull looks exactly like a quiet week. Every window is safe to run: events merge on their id, and `issues.json` — mutable state, so nothing to append along — merges on the issue id with each row stamped `_observed_at`. Surfaced as `sentry_issues.observed_at`, and worth checking before quoting a status or a lifetime count, because a row can be older than the window you asked for.
- `pull/railway` needs the `railway` CLI, logged in and linked. It addresses logs per deployment, so a time window — `--since 12h`, or an ISO 8601 instant — selects deployments by the window instead of by `--limit` (every one created inside it, plus the one already serving when it opened) and then clamps each to the floor, since the deployment serving most of a window usually predates it. A clamped fetch is narrower than its deployment, so it never clears a `truncated` flag it did not repair. Its HTTP export cannot be paged, so a deployment serving more than the API's 5000-row maximum keeps only its newest 5000, and each fetch merges into the dump already on disk rather than replacing it — which is what makes re-pulling mid-incident safe. Truncation goes in `manifest.json`, because it cannot be recovered from the files afterwards.
- `pull/bunny` needs `BUNNY_API_KEY` — the account API key from [the Bunny dashboard](https://dash.bunny.net/account/settings), not a storage-zone password. A day fetches whole, so re-pulling today supersedes an earlier partial — but a day at the retention edge comes back _trimmed_, an ordinary 200 carrying a fraction of the rows it held, and an empty answer means aged out, logging off or no traffic with nothing to separate them. So it refuses to write any haul shorter than the dump already on disk, finishes the remaining zone-days anyway, and exits non-zero naming what it skipped. Re-pulling can never cost you a day.

**Bunny logs expire after four days.** Sentry keeps 90 and Railway keeps whatever a deployment keeps, so those tolerate being pulled after the fact; Bunny does not, and the edge is the only source that sees a request the origin never received.

### Work in this order

Diagnosis is reconstructing a sequence, and sequence is the one axis you cannot filter away. Slicing by service and severity first is how these logs are browsed and how the vendor UIs are laid out, but it is the wrong way in: during a real outage here, 402 requests failed at Railway's edge while the application logged 36 lines, 10 of them at `error`, and Sentry recorded nothing.

1. **`FROM coverage`** — what can you see? Every later claim is bounded by it.
2. **`FROM edge_health`** — the shape, before reading any line. Onset and recovery timestamps come from here, and the CDN column is the only one reflecting what users actually got. Read across a row, never down two.
3. **Correlate the onset** against `sentry_releases` and deployments. Most incidents are a change.
4. **Read the edge unfiltered** — `FROM timeline` over minutes, not hours, around onset, all sources and severities, ordered by `ts`. Causes routinely log at `info`, or are the last line before silence.
5. **Then slice** by service, status, path, text — to quantify a hypothesis, not to find one.
6. **Try to break it.** An explanation that covers the spike but not the silences is usually wrong.

Habits to keep. Prefer **rates to counts**, because the exporters truncate. Treat **severity as a ranking, not a filter**: Railway invents a level for every line that is not JSON, so count `summary` and rank `timeline` on `level_confidence` rather than filtering on `level`.

A trap: `apex` and `static` pull from the same Railway host and their traffic arrives mixed in `railway_requests`, with nothing recording which zone forwarded a request. Filter `bunny_requests` by `zone` before comparing it against a Railway relation, and include **both** zones when you do — comparing one against the whole origin makes the origin look bigger than the tier in front of it.

## Editing the analytics

See [analyze/sql/README.md](analyze/sql/README.md).
