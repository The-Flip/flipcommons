-- Railway container logs.
--
-- SOURCE: ../dumps/railway/, in two export shapes that overlap and are merged:
--
--   logs.*.json    The log-viewer export. A JSON array; severity in `severity`,
--                  service/replica/deployment in `tags`, and a JSON line's own
--                  fields nested under `attributes`. The only shape carrying the
--                  Postgres service, and the only one reaching back before the
--                  per-deployment exports begin.
--   *deploy*.jsonl The per-deployment export, one JSON object per line. Railway
--                  flattens a structured line's fields to TOP LEVEL here rather
--                  than nesting them, so `logger`, `pid`, `time` sit beside
--                  `message`.
--
-- The windows overlap, and a line present in both is identical to the nanosecond.
-- Deduped preferring the deploy shape, which carries the flattened fields; the
-- legacy rows that survive are the Postgres service and the earlier history.
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
-- ONE row with embedded newlines. Legacy stderr tracebacks are one row per frame
-- -- see is_continuation.

CREATE OR REPLACE TABLE railway_lines AS
WITH legacy AS (
  SELECT
    'legacy_export' AS origin,
    (regexp_replace(json ->> 'timestamp', '(\.\d{6})\d*Z$', '\1Z')::TIMESTAMPTZ AT TIME ZONE 'UTC') AS ts,
    json -> 'tags' ->> 'service'     AS service_id,
    json -> 'tags' ->> 'deployment'  AS deployment_id,
    json -> 'tags' ->> 'replica'     AS replica_id,
    json -> 'tags' ->> 'environment' AS environment,
    json ->> 'severity' AS level_raw,
    json ->> 'message'  AS message,
    -- An unstructured line gets exactly one attribute, `level`, mirroring the
    -- severity it was assigned. So the key count alone separates the two.
    json -> 'attributes' AS payload,
    list_filter(json_keys(json -> 'attributes'),
      lambda k: k NOT IN ('level', 'logger', 'time', 'ts', 'pid')) AS extra_keys,
    len(json_keys(json -> 'attributes')) > 1 AS is_structured,
    regexp_replace(filename, '^.*/', '') AS source_file
  FROM read_json_objects('../../dumps/railway/logs.*.json', format = 'array', filename = true)
),
deploy AS (
  SELECT
    'deploy_export',
    (regexp_replace(json ->> 'timestamp', '(\.\d{6})\d*Z$', '\1Z')::TIMESTAMPTZ AT TIME ZONE 'UTC'),
    -- The puller names the service in the filename. Older hand-made exports do
    -- not, and were all taken from the web service; `deployment_service_mismatch`
    -- tests that against the legacy tags rather than leaving it an assumption.
    (SELECT service_id FROM railway_services svc
      WHERE svc.railway_name = coalesce(
        nullif(lower(regexp_extract(filename, '([a-z0-9-]+)\.deploy\.', 1)), ''), 'web')),
    regexp_extract(filename, '([0-9a-f]{8}-[0-9a-f-]{20,})\.jsonl$', 1),
    NULL, NULL,
    json ->> 'level',
    json ->> 'message',
    json,
    list_filter(json_keys(json),
      lambda k: k NOT IN ('level', 'message', 'timestamp', 'logger', 'time', 'ts', 'pid')),
    len(list_filter(json_keys(json), lambda k: k NOT IN ('level', 'message', 'timestamp'))) > 0,
    regexp_replace(filename, '^.*/', '')
  FROM read_json_objects('../../dumps/railway/*deploy*.jsonl', filename = true)
  WHERE is_canonical_dump(filename)
),
merged AS (
  SELECT *, row_number() OVER (
    PARTITION BY ts, message
    -- deploy_export sorts first, so the flattened shape wins a tie.
    ORDER BY origin, source_file
  ) AS dup_rank
  FROM (SELECT * FROM legacy UNION ALL SELECT * FROM deploy)
)
SELECT
  m.ts,
  coalesce(svc.service, 'unknown:' || substr(m.service_id, 1, 8)) AS service,
  norm_level(m.level_raw) AS level,
  -- What an unstructured line means is a property OF the service, declared in
  -- railway_services. An unmapped service is assumed countable and flagged by
  -- `unknown_railway_service`.
  CASE WHEN m.is_structured THEN 'json'
       ELSE coalesce(svc.unstructured_confidence, 'stream_app') END AS level_confidence,
  -- Which process wrote the line, inferred from the field only that one sets.
  -- Order matters: `logger` is the weakest of the three -- every python line and
  -- half of caddy's carry one -- so both must be claimed by their own field
  -- first. `json_line_without_emitter` guards the inference.
  CASE
    WHEN json_exists(m.payload, '$.pid')    THEN 'python'
    WHEN json_exists(m.payload, '$.ts')     THEN 'caddy'
    WHEN json_exists(m.payload, '$.logger') THEN 'node'
    ELSE 'unstructured'
  END AS emitter,
  m.payload ->> 'logger' AS logger,
  (m.payload ->> 'pid')::BIGINT AS pid,
  m.message,
  contains(m.message, chr(10)) AS is_multiline,
  -- Legacy only: a stderr traceback arrives one frame per row, and the frames
  -- carry no level of their own. Always false for structured lines.
  (NOT m.is_structured AND (m.message ~ '^\s' OR m.message = '')) AS is_continuation,
  -- Whatever the caller passed as extra=, which is what the JSON flattening is
  -- for: these are the fields Railway lets you filter a query on.
  m.extra_keys,
  m.payload,
  m.origin,
  m.replica_id,
  m.deployment_id,
  m.environment,
  m.service_id,
  m.source_file
FROM merged m
LEFT JOIN railway_services svc ON svc.service_id = m.service_id
WHERE m.dup_rank = 1;

COMMENT ON TABLE railway_lines IS 'GRAIN: one row per container log line, deduped across the legacy and per-deployment exports. Structured lines are one row per EVENT (traceback folded in); legacy stderr tracebacks are one row per frame. Check level_confidence before trusting level.';
