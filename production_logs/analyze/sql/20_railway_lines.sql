-- Railway container logs.
--
-- SOURCE: ../../dumps/railway/deploy.*.ndjson, one JSON object per line, the
-- GraphQL environmentLogs row written verbatim: severity in `severity`,
-- service/deployment/replica UUIDs in `tags`, and a structured line's own
-- fields as a key/value list under `attributes`, each value JSON-encoded.
--
-- HOW SEVERITY WORKS, because it decides what every other view can claim.
--
-- Railway reads a line's severity from the line itself when the line is JSON --
-- its `level` field wins -- and otherwise from the stream it arrived on, where
-- stdout becomes `info` and stderr becomes `error`. Python's StreamHandler writes
-- to stderr, so before structured logging every Django INFO and every gunicorn
-- boot line arrived tagged `error`.
--
-- RailwayJSONFormatter (backend/config/log_format.py) fixed that for both Python
-- processes and $lib/log (frontend/src/lib/log.ts) for Node SSR, while Caddy
-- already emitted JSON. `level_confidence` records whether a given row benefits:
--
--   'json'         The line carried its own level. Trust it.
--   'stream_app'   Unstructured on the web service. Python `warnings` bypass
--                  logging entirely, and SSR lines from before $lib/log landed
--                  are here too: console.error genuinely is an error but
--                  console.warn read as one as well. Directionally right,
--                  inflated at the warn boundary.
--   'stream_noise' Unstructured on the Postgres service, whose image writes every
--                  routine `LOG:` and pgBackRest `INFO:` line to stderr. All of it
--                  reads as `error`. Do not count it as one.
--
-- Both fixes are forward-only: a dump reaching back past a deploy holds rows the
-- formatter never touched, which is why `level_confidence` stays a per-row column
-- rather than a fact about the service.
--
-- The formatter also folds tracebacks into the message, so a structured crash is
-- ONE row with embedded newlines. Unstructured stderr tracebacks are one row per
-- frame -- see is_continuation.

-- The value of one named attribute, unwrapped from its JSON encoding
-- ('"gunicorn"' -> gunicorn). NULL when the line does not carry it.
CREATE OR REPLACE MACRO attr(attrs, name) AS
  list_extract(list_filter(attrs, lambda a: a.key = name), 1).value::JSON ->> '$';

CREATE OR REPLACE TABLE railway_lines AS
SELECT
  (r."timestamp"::TIMESTAMPTZ AT TIME ZONE 'UTC') AS ts,
  coalesce(svc.service, 'unknown:' || substr(r.tags ->> 'serviceId', 1, 8), 'untagged') AS service,
  norm_level(r.severity) AS level,
  -- An unstructured line gets exactly one attribute, `level`, mirroring the
  -- severity Railway assigned it. So the attribute count alone separates the
  -- two. What an unstructured line means is a property OF the service, declared
  -- in railway_services; an unmapped service is assumed countable and flagged
  -- by `unknown_railway_service`.
  CASE WHEN len(r.attributes) > 1 THEN 'json'
       ELSE coalesce(svc.unstructured_confidence, 'stream_app') END AS level_confidence,
  -- Which process wrote the line, inferred from the field only that one sets.
  -- Order matters: `logger` is the weakest of the three -- every python line and
  -- half of caddy's carry one -- so both must be claimed by their own field
  -- first. `json_line_without_emitter` guards the inference.
  CASE
    WHEN attr(r.attributes, 'pid') IS NOT NULL    THEN 'python'
    WHEN attr(r.attributes, 'ts') IS NOT NULL     THEN 'caddy'
    WHEN attr(r.attributes, 'logger') IS NOT NULL THEN 'node'
    ELSE 'unstructured'
  END AS emitter,
  attr(r.attributes, 'logger') AS logger,
  attr(r.attributes, 'pid')::BIGINT AS pid,
  r.message,
  contains(r.message, chr(10)) AS is_multiline,
  -- Unstructured only: a stderr traceback arrives one frame per row, and the
  -- frames carry no level of their own. Always false for structured lines.
  (len(r.attributes) <= 1 AND (r.message ~ '^\s' OR r.message = '')) AS is_continuation,
  -- Whatever the caller passed as extra=, which is what the JSON flattening is
  -- for: these are the fields Railway lets you filter a query on.
  list_filter(list_transform(r.attributes, lambda a: a.key),
    lambda k: k NOT IN ('level', 'logger', 'time', 'ts', 'pid')) AS extra_keys,
  r.attributes,
  r.tags ->> 'deploymentInstanceId' AS replica_id,
  r.tags ->> 'deploymentId' AS deployment_id,
  r.tags ->> 'environmentId' AS environment,
  r.tags ->> 'serviceId' AS service_id,
  regexp_replace(r.filename, '^.*/', '') AS source_file
FROM read_json('../../dumps/railway/deploy.*.ndjson',
  format = 'newline_delimited', filename = true, columns = {
    'timestamp': 'VARCHAR', 'message': 'VARCHAR', 'severity': 'VARCHAR',
    'tags': 'JSON', 'attributes': 'STRUCT(key VARCHAR, value VARCHAR)[]'}) r
LEFT JOIN railway_services svc ON svc.service_id = (r.tags ->> 'serviceId')::VARCHAR;

COMMENT ON TABLE railway_lines IS 'GRAIN: one row per container log line, every service, merged by the puller on (timestamp, message). Structured lines are one row per EVENT (traceback folded in); unstructured stderr tracebacks are one row per frame. Check level_confidence before trusting level.';
