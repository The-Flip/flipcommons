-- Railway build logs: what the image builder printed while turning a commit
-- into a container.
--
-- SOURCE: ../../dumps/railway/build.*.ndjson, one JSON object per line, the
-- GraphQL buildLogs row written verbatim. Same Log shape as the deploy stream,
-- read differently because the rows mean something different:
--
--   * Severity is BUILDER-declared, not guessed from a stream: routine
--     progress arrives as `info`, and a failing step as `error`. There is no
--     level_confidence question here -- the builder is the one process
--     writing, so the level is trusted the way a JSON line's is.
--   * `tags.deploymentId` is NULL on every row -- the build precedes the
--     deployment instance -- so the build is identified by `tags.snapshotId`,
--     surfaced as `build_id`. Rows for one build share it; the puller fetched
--     them per deployment but the row does not record which.
--   * The emitter/logger/pid inference of railway_lines has no equivalent:
--     attributes carry BuildKit vertex bookkeeping (vertex, digest, cached),
--     not application fields.
--
-- Kept out of railway_lines on purpose. Folding builder output into the app
-- service's container stream would inflate its volumes and put non-runtime
-- lines inside `formatter_not_running`'s window, where enough of them could
-- trip it after a deploy.

CREATE OR REPLACE TABLE railway_build_lines AS
SELECT
  (r."timestamp"::TIMESTAMPTZ AT TIME ZONE 'UTC') AS ts,
  coalesce(svc.service, 'unknown:' || substr(r.tags ->> 'serviceId', 1, 8), 'untagged') AS service,
  norm_level(r.severity) AS level,
  r.message,
  contains(r.message, chr(10)) AS is_multiline,
  r.tags ->> 'snapshotId' AS build_id,
  r.tags ->> 'serviceId' AS service_id,
  regexp_replace(r.filename, '^.*/', '') AS source_file
FROM read_json('../../dumps/railway/build.*.ndjson',
  format = 'newline_delimited', filename = true, columns = {
    'timestamp': 'VARCHAR', 'message': 'VARCHAR', 'severity': 'VARCHAR',
    'tags': 'JSON', 'attributes': 'STRUCT(key VARCHAR, value VARCHAR)[]'}) r
LEFT JOIN railway_services svc ON svc.service_id = (r.tags ->> 'serviceId')::VARCHAR;

COMMENT ON TABLE railway_build_lines IS 'GRAIN: one row per image-builder log line, merged by the puller on (timestamp, message). One build is one build_id (the snapshot UUID); deployment ids do not appear because the build precedes the deployment instance. Severity is builder-declared and trustworthy. A build absent here either predates the dump window or genuinely emitted nothing -- Railway builds that die before the builder starts produce zero lines.';
