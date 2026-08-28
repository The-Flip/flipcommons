-- What the pullers recorded about their own output.
--
-- Every pull script writes the same manifest shape into its dump directory:
-- one record per file, carrying the facts a file cannot show about itself --
-- above all `complete`, whether the file's UTC day was over when it was last
-- pulled. A file for today is still accumulating; a partial day and a quiet
-- day are identical on disk. For Sentry's event files, `complete` instead
-- records whether the pull's count() verification passed.
--
-- Readers tolerate a missing record (a hand-dropped file is absent from the
-- manifest), and `coverage` flags such files rather than vouching for them.

CREATE OR REPLACE TABLE railway_manifest AS
SELECT
  f.file::VARCHAR AS file,
  f.kind::VARCHAR AS kind,
  f.rows::BIGINT AS rows,
  (f.first_ts::TIMESTAMPTZ AT TIME ZONE 'UTC') AS first_ts,
  (f.last_ts::TIMESTAMPTZ AT TIME ZONE 'UTC') AS last_ts,
  f.complete,
  (f.pulled_at::TIMESTAMPTZ AT TIME ZONE 'UTC') AS pulled_at
FROM read_json('../../dumps/railway/manifest.json', columns = {
       'files': 'STRUCT(file VARCHAR, kind VARCHAR, rows BIGINT,
                        first_ts VARCHAR, last_ts VARCHAR,
                        complete BOOLEAN, pulled_at VARCHAR)[]'}),
     unnest(files) AS u(f);

COMMENT ON TABLE railway_manifest IS 'GRAIN: one row per file pull/railway wrote. The authority on whether a day file is complete, which is not recoverable from the file.';

-- Bunny's extras: whether a zone had logging on at all (an empty file for that
-- reason is not a quiet day), and whether client_ip is a network or a whole
-- address.
CREATE OR REPLACE TABLE bunny_manifest AS
SELECT
  f.file::VARCHAR AS file,
  f.kind::VARCHAR AS kind,
  f.zone_id::BIGINT AS pull_zone,
  f.zone_name::VARCHAR AS bunny_name,
  f.rows::BIGINT AS rows,
  (f.first_ts::TIMESTAMPTZ AT TIME ZONE 'UTC') AS first_ts,
  (f.last_ts::TIMESTAMPTZ AT TIME ZONE 'UTC') AS last_ts,
  f.complete,
  f.logging_enabled,
  f.ip_anonymization,
  (f.pulled_at::TIMESTAMPTZ AT TIME ZONE 'UTC') AS pulled_at
FROM read_json('../../dumps/bunny/manifest.json', columns = {
       'files': 'STRUCT(file VARCHAR, kind VARCHAR, zone_id BIGINT,
                        zone_name VARCHAR, rows BIGINT, first_ts VARCHAR,
                        last_ts VARCHAR, complete BOOLEAN,
                        logging_enabled BOOLEAN, ip_anonymization VARCHAR,
                        pulled_at VARCHAR)[]'}),
     unnest(files) AS u(f);

COMMENT ON TABLE bunny_manifest IS 'GRAIN: one row per file pull/bunny wrote. The authority on whether a day is complete and on whether a zone had logging on at all -- neither is recoverable from the file. Hand-downloaded dumps are absent.';

CREATE OR REPLACE TABLE sentry_manifest AS
SELECT
  f.file::VARCHAR AS file,
  f.kind::VARCHAR AS kind,
  f.rows::BIGINT AS rows,
  (f.first_ts::TIMESTAMPTZ AT TIME ZONE 'UTC') AS first_ts,
  (f.last_ts::TIMESTAMPTZ AT TIME ZONE 'UTC') AS last_ts,
  f.complete,
  (f.pulled_at::TIMESTAMPTZ AT TIME ZONE 'UTC') AS pulled_at
FROM read_json('../../dumps/sentry/manifest.json', columns = {
       'files': 'STRUCT(file VARCHAR, kind VARCHAR, rows BIGINT,
                        first_ts VARCHAR, last_ts VARCHAR,
                        complete BOOLEAN, pulled_at VARCHAR)[]'}),
     unnest(files) AS u(f);

COMMENT ON TABLE sentry_manifest IS 'GRAIN: one row per file pull/sentry wrote. `complete` on the event files records whether the pull''s count() verification passed.';

-- The uniform columns of all three, for anything (coverage, above all) that
-- wants one join whatever the source.
CREATE OR REPLACE TABLE manifests AS
SELECT 'railway' AS source, file, kind, rows, first_ts, last_ts, complete, pulled_at
FROM railway_manifest
UNION ALL
SELECT 'bunny', file, kind, rows, first_ts, last_ts, complete, pulled_at
FROM bunny_manifest
UNION ALL
SELECT 'sentry', file, kind, rows, first_ts, last_ts, complete, pulled_at
FROM sentry_manifest;

COMMENT ON TABLE manifests IS 'GRAIN: one row per dump file any puller wrote -- the three per-source manifests on their shared columns. Join on file for completeness facts.';
