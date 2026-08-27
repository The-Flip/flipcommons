-- What pull/railway recorded about its own output.
--
-- The puller knows things the files cannot show: which deployment a file came
-- from, which service, and -- the one that matters -- whether a file hit Railway's
-- row cap and is therefore only the most RECENT N rows of its window. Inferring
-- that from row counts goes wrong the moment a window genuinely holds exactly the
-- cap.
--
-- Supersession is NOT read from here. A pull run is usually scoped to one service
-- or a handful of deployments, so the manifest describes that run's files and not
-- necessarily every file on disk. Which export wins is derived from the filenames,
-- which are always all there.

CREATE OR REPLACE TABLE railway_manifest AS
SELECT
  f.file::VARCHAR AS file,
  f.service AS railway_name,
  f.deployment::VARCHAR AS deployment_id,
  f.rows,
  (regexp_replace(f.first_ts, '(\.\d{6})\d*Z$', '\1Z')::TIMESTAMPTZ AT TIME ZONE 'UTC') AS first_ts,
  (regexp_replace(f.last_ts,  '(\.\d{6})\d*Z$', '\1Z')::TIMESTAMPTZ AT TIME ZONE 'UTC') AS last_ts,
  f.row_cap,
  f.truncated,
  railway_export_kind(f.file) AS kind
-- first_ts/last_ts are declared VARCHAR because they are stamped to nanoseconds,
-- one digit more than a duckdb TIMESTAMP holds, and the regexp above is what
-- trims them. Inference would bind them as TIMESTAMP the moment a puller stamped
-- microseconds instead, and the trim would then fail to bind -- taking the whole
-- build down over a change that made the input tidier.
FROM read_json('../../dumps/railway/manifest.json', columns = {
       'files': 'STRUCT(file VARCHAR, service VARCHAR, deployment VARCHAR,
                        rows BIGINT, first_ts VARCHAR, last_ts VARCHAR,
                        row_cap BIGINT, truncated BOOLEAN)[]'}),
     unnest(files) AS u(f);

COMMENT ON TABLE railway_manifest IS 'GRAIN: one row per file pull/railway wrote. The authority on truncation and on which of several overlapping exports is canonical.';

-- pull/railway names its output <service>.<kind>.<stamp>.<deployment>.jsonl. The
-- hand-made exports have no service prefix, so the prefix alone says which
-- generation a file belongs to -- read off disk, so it stays right no matter what
-- any one pull run covered.
CREATE OR REPLACE TABLE railway_pulled_deployments AS
SELECT DISTINCT regexp_extract(file, '([0-9a-f]{8}-[0-9a-f-]{20,})\.jsonl$', 1) AS deployment_id
FROM glob('../../dumps/railway/*.jsonl')
WHERE regexp_matches(regexp_replace(file, '^.*/', ''), '^[a-z0-9-]+\.(deploy|http)\.');

COMMENT ON TABLE railway_pulled_deployments IS 'Deployments pull/railway has written a file for, derived from filenames on disk. A hand-made export naming one of these is skipped in favour of the pulled file.';

-- Applied by both jsonl readers, so the rule lives in one place.
CREATE OR REPLACE MACRO is_canonical_dump(path) AS
  regexp_matches(regexp_replace(path, '^.*/', ''), '^[a-z0-9-]+\.(deploy|http)\.')
  OR regexp_extract(path, '([0-9a-f]{8}-[0-9a-f-]{20,})\.jsonl$', 1)
     NOT IN (SELECT deployment_id FROM railway_pulled_deployments);
