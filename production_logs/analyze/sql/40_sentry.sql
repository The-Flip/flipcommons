-- Sentry issues, error events and uptime checks.
--
-- SOURCE: ../../dumps/sentry/, pulled from the Sentry Web API for the `the-flip` org.
--
-- TWO THINGS THAT MISLEAD:
--
--   Uptime events are NOT in the errors dataset. Sentry stores uptime-monitor
--   results separately, so they are absent from discover_errors.ndjson and so
--   from `sentry_errors`. Read `sentry_uptime` for downtime. Where the error
--   stream goes quiet while downtime continues, that is a dataset boundary and
--   not a recovery.
--
--   `count` on an issue is LIFETIME, not windowed, and routinely totals several
--   times what the pull window holds. `lifetime_events` is named to make the
--   mistake hard to make by accident; use sentry_errors for anything
--   time-bounded.
--
-- The org's structured-log dataset (ourlogs) is empty, so Sentry contributes
-- errors and uptime checks only -- no application log lines.
--
-- EVERY READER HERE DECLARES ITS COLUMNS, and that is not a style choice.
-- read_json_auto infers the schema from the file's contents, so an EMPTY export
-- has no columns to infer and every SELECT against it fails to bind, taking the
-- whole database build down. An empty export is not an error condition: it is a
-- quiet window, which `pull/sentry --days 1` produces on any calm day.
--
-- Declaring also pins the interface. The nested payloads infer as STRUCT types
-- tens of kilobytes wide that change shape whenever Sentry adds a field, so
-- `entries` and `contexts` are declared JSON and read with -> and ->>. A field
-- Sentry adds is then ignored until it is declared here, which is the direction of
-- failure to prefer.
--
-- An empty export is therefore readable, and sentry_manifest (10_manifests.sql)
-- records whether the pull's count() verification passed, which is what
-- separates a quiet window from a failed pull.

CREATE OR REPLACE TABLE sentry_errors AS
SELECT
  "timestamp" AS ts,
  "project.name"  AS project,
  title,
  message,
  norm_level(level) AS level,
  issue           AS issue_short_id,
  id              AS event_id,
  release,
  environment,
  transaction,
  culprit,
  url,
  "user.id"       AS user_id,
  "user.email"    AS user_email,
  "browser.name"  AS browser,
  "os.name"       AS os,
  "sdk.name"      AS sdk,
  server_name,
  regexp_replace(filename, '^.*/', '') AS source_file
FROM read_json('../../dumps/sentry/discover_errors.ndjson',
  format = 'newline_delimited', filename = true, columns = {
    'id': 'VARCHAR', 'timestamp': 'TIMESTAMP', 'message': 'VARCHAR',
    'title': 'VARCHAR', 'level': 'VARCHAR', 'project.name': 'VARCHAR',
    'release': 'VARCHAR', 'environment': 'VARCHAR', 'transaction': 'VARCHAR',
    'culprit': 'VARCHAR', 'url': 'VARCHAR', 'user.id': 'VARCHAR',
    'user.email': 'VARCHAR', 'browser.name': 'VARCHAR', 'os.name': 'VARCHAR',
    'sdk.name': 'VARCHAR', 'issue': 'VARCHAR', 'server_name': 'VARCHAR'});

COMMENT ON TABLE sentry_errors IS 'GRAIN: one row per error event in the pulled window. Verified complete against Sentry''s own count() aggregate. Excludes uptime events -- see sentry_uptime.';

-- Selected on the issue's own category rather than a title match or a specific
-- issue's filename: Sentry classifies uptime monitors as `outage`, so a second
-- monitor or a renamed check lands here without anyone editing this file.
CREATE OR REPLACE TABLE sentry_uptime AS
SELECT
  dateCreated AS ts,
  _project AS project,
  _short_id AS issue_short_id,
  id AS event_id,
  _issue_title AS title,
  _issue_type AS issue_type,
  list_extract(list_filter(tags, lambda t: t.key = 'environment'), 1).value AS environment,
  regexp_replace(filename, '^.*/', '') AS source_file
FROM read_json('../../dumps/sentry/events.ndjson',
  format = 'newline_delimited', filename = true, columns = {
    'id': 'VARCHAR', 'dateCreated': 'TIMESTAMP', '_project': 'VARCHAR',
    '_short_id': 'VARCHAR', '_issue_title': 'VARCHAR', '_issue_type': 'VARCHAR',
    '_issue_category': 'VARCHAR', 'tags': 'STRUCT(key VARCHAR, value VARCHAR)[]'})
WHERE _issue_category = 'outage';

COMMENT ON TABLE sentry_uptime IS 'GRAIN: one row per uptime-monitor downtime detection against https://flipcommons.org/__health. Lives only in the per-issue export; absent from sentry_errors by construction.';

CREATE OR REPLACE TABLE sentry_issues AS
SELECT
  shortId    AS issue_short_id,
  _project   AS project,
  title,
  culprit,
  norm_level(level) AS level,
  issueCategory AS issue_category,
  issueType AS issue_type,
  status,
  count::BIGINT     AS lifetime_events,
  userCount::BIGINT AS lifetime_users,
  firstSeen AS first_seen,
  lastSeen AS last_seen,
  permalink,
  _observed_at AS observed_at
FROM read_json('../../dumps/sentry/issues.json', format = 'array', columns = {
    'shortId': 'VARCHAR', '_project': 'VARCHAR', 'title': 'VARCHAR',
    'culprit': 'VARCHAR', 'level': 'VARCHAR', 'issueCategory': 'VARCHAR',
    'issueType': 'VARCHAR', 'status': 'VARCHAR', 'count': 'VARCHAR',
    'userCount': 'VARCHAR', 'firstSeen': 'TIMESTAMP', 'lastSeen': 'TIMESTAMP',
    'permalink': 'VARCHAR', '_observed_at': 'TIMESTAMP'});

COMMENT ON TABLE sentry_issues IS 'GRAIN: one row per issue ever pulled, state as of observed_at -- NOT one row per issue active in a window, since a narrow pull merges into the rows a wider one left. status and the lifetime counts are only as fresh as observed_at. lifetime_events/lifetime_users are ALL-TIME counts and do not match any window -- join to sentry_errors to count in-window.';

-- Full event payloads: stacktraces, breadcrumbs, request, contexts, tags. 23MB of
-- deeply nested JSON, so heavy to SELECT * from -- filter first.
CREATE OR REPLACE TABLE sentry_event_details AS
SELECT
  dateCreated AS ts,
  _short_id AS issue_short_id,
  _project  AS project,
  id AS event_id,
  title,
  culprit,
  platform,
  entries,
  contexts,
  tags AS tag_pairs
FROM read_json('../../dumps/sentry/events.ndjson',
  format = 'newline_delimited', columns = {
    'id': 'VARCHAR', 'dateCreated': 'TIMESTAMP', '_short_id': 'VARCHAR',
    '_project': 'VARCHAR', 'title': 'VARCHAR', 'culprit': 'VARCHAR',
    'platform': 'VARCHAR', 'entries': 'JSON', 'contexts': 'JSON',
    'tags': 'STRUCT(key VARCHAR, value VARCHAR)[]'});

COMMENT ON TABLE sentry_event_details IS 'GRAIN: one row per event, with the full nested payload (entries holds stacktrace and breadcrumbs). Heavy -- filter by issue_short_id or ts first.';

CREATE OR REPLACE TABLE sentry_releases AS
SELECT
  version,
  shortVersion AS short_version,
  dateCreated AS created,
  dateReleased AS released,
  commitCount AS commit_count,
  authors
FROM read_json('../../dumps/sentry/releases.json', format = 'array', columns = {
    'version': 'VARCHAR', 'shortVersion': 'VARCHAR', 'dateCreated': 'TIMESTAMP',
    'dateReleased': 'TIMESTAMP', 'commitCount': 'BIGINT', 'authors': 'JSON'});

COMMENT ON TABLE sentry_releases IS 'GRAIN: one row per org release. Org-wide and not window-filtered -- use for correlating error onsets against deploys.';
