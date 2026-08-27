-- Reference data and shared helpers: facts about the deployment that no log line
-- states outright. Keep it small; prefer deriving over declaring.

-- Railway service UUIDs are stable per service but appear nowhere in the message
-- text, so this mapping has to be declared. Unknown UUIDs fall through to a
-- truncated id rather than NULL, so a new service shows up in every view instead
-- of vanishing, and `unknown_railway_service` names it.
--
-- Two spellings reach us for one service: a UUID in the legacy export's tags, and
-- Railway's display name in the puller's filenames. Both are listed so either
-- resolves to one canonical `service`.
--
-- `unstructured_confidence` is what a line from this service means when it is NOT
-- self-describing JSON. It lives here so adding a service is a row rather than an
-- edit to a CASE in shared SQL:
--
--   'stream_app'   stderr mostly does mean trouble. Directionally right, and
--                  inflated at the warn boundary by anything that bypasses
--                  `logging` (Python `warnings`, Node SSR console.warn).
--   'stream_noise' the image logs routine progress to stderr, so every line
--                  reads as an error and none of it should be counted as one.
CREATE OR REPLACE TABLE railway_services (
  service_id VARCHAR, railway_name VARCHAR, service VARCHAR,
  unstructured_confidence VARCHAR, role VARCHAR
);
INSERT INTO railway_services VALUES
  ('7e443a50-b7c2-4a0a-8357-400683eebcee', 'web', 'app', 'stream_app',
   'Caddy + SvelteKit SSR + Django/Gunicorn in one container'),
  ('2e57c910-065c-4e19-8376-3be717889bcd', 'postgres', 'postgres', 'stream_noise',
   'Postgres with pgBackRest WAL archiving; writes routine LOG:/INFO: to stderr');

COMMENT ON TABLE railway_services IS 'One row per known Railway service, carrying what its unstructured lines mean. Hand-maintained: service UUIDs appear only in log tags, never in message text.';

-- When RailwayJSONFormatter reached production, as the committer date of the
-- merge that shipped it (da20cb665). Lines before it are stream-classified and
-- their severity means little; lines after carry their own. Used to explain, not
-- to filter -- `level_confidence` is what filters.
CREATE OR REPLACE TABLE json_logging_deployed AS
  SELECT TIMESTAMP '2026-08-26 23:36:56' AS deployed_at;

COMMENT ON TABLE json_logging_deployed IS 'When RailwayJSONFormatter reached production (UTC). Before it, Railway severity is stream-derived noise.';

-- Sentry and Railway spell levels differently. Railway already emits its own
-- four-value vocabulary; this mainly folds Sentry's wider set onto it.
CREATE OR REPLACE MACRO norm_level(raw) AS
  CASE lower(raw)
    WHEN 'debug'    THEN 'debug'
    WHEN 'info'     THEN 'info'
    WHEN 'warning'  THEN 'warn'
    WHEN 'warn'     THEN 'warn'
    WHEN 'error'    THEN 'error'
    WHEN 'critical' THEN 'fatal'
    WHEN 'fatal'    THEN 'fatal'
    ELSE lower(raw)
  END;

-- Bunny pull zones. A CDN log line names its zone only by a bare number, and
-- which site that number fronts is nowhere in the file. Unknown ids fall through
-- to 'zone:<id>' rather than NULL, and `unknown_bunny_pull_zone` names them.
--
-- `origin` is what the zone pulls from, and it ties a CDN row to the tier behind
-- it: the apex origin is the Railway host that appears as `host` in
-- railway_requests. NULL where the origin is not Railway, which is the point -- a
-- media request has no downstream row to correlate with.
--
-- `zone` is the short tier label used everywhere, and what appears as a stream in
-- coverage and timeline; `bunny_name` is what Bunny calls the zone, and the slug
-- pull/bunny puts in the filename. Both are here so a file on disk can be traced
-- to a stream in a query.
CREATE OR REPLACE TABLE bunny_pull_zones (
  pull_zone BIGINT, zone VARCHAR, bunny_name VARCHAR, hostname VARCHAR,
  origin VARCHAR, role VARCHAR
);
INSERT INTO bunny_pull_zones VALUES
  (5969801, 'apex', 'flipcommons-html', 'flipcommons.org',
   'flipcommons-production.up.railway.app',
   'Anonymous SSR HTML; bypasses /api/, /djadmin/ and session or kiosk cookies'),
  (5915890, 'static', 'flipcommons-static', 'static.flipcommons.org',
   'flipcommons-production.up.railway.app',
   'Hashed /_app/immutable/* assets, fonts and version.json'),
  (5782405, 'media', 'flipcommons-media', 'media.flipcommons.org', NULL,
   'iDrive e2 media bucket. NULL origin: nothing behind it is Railway, so a media row has no downstream row to correlate with');

COMMENT ON TABLE bunny_pull_zones IS 'One row per known Bunny pull zone. Hand-maintained: a CDN log line names its zone only by numeric id.';

-- Which Railway exporter produced a file, read off its name. pull/railway writes
-- <service>.<kind>.<stamp>.<deployment>.jsonl and the hand-made exports are named
-- for their kind too, so the name is the only place this lives.
CREATE OR REPLACE MACRO railway_export_kind(path) AS
  CASE WHEN path LIKE '%http%' THEN 'http' ELSE 'deploy' END;

-- The row cap each Railway exporter returns on, for files the manifest does not
-- cover -- hand-made exports, and anything pulled before the manifest started
-- accumulating. A pulled file uses railway_manifest.truncated instead, which
-- records why a fetch stopped rather than inferring it from a row count landing
-- on a known cap.
CREATE OR REPLACE TABLE railway_export_caps (kind VARCHAR, row_cap BIGINT);
INSERT INTO railway_export_caps VALUES ('http', 500), ('deploy', 1000);

COMMENT ON TABLE railway_export_caps IS 'One row per Railway exporter: the row count at which an untracked file is assumed cut off. Pulled files use railway_manifest.truncated instead.';
