-- Railway edge HTTP access logs.
--
-- SOURCE: ../dumps/railway/*http*.jsonl, one JSON object per request.
--
-- One row per HTTP REQUEST as Railway's edge saw it, with status, timing and
-- client -- an outage as users met it rather than as the app narrated it. A 502 is
-- the edge failing to reach the container, so it appears here and leaves no
-- application log line at all.
--
-- TRUNCATION. Railway caps a response at 5000 rows and HTTP logs cannot be paged
-- past it, so a deployment busier than that holds only its most recent 5000
-- requests. Files pulled before the puller asked for that maximum sit at the CLI
-- default of 500, which is why the older ones are short. `is_truncated` carries it
-- per row. Rates survive truncation; absolute counts do not.
--
-- These rows are NOT deduped, because a repeated request is a real repeated
-- request -- so reading two overlapping exports of one deployment would
-- double-count outright, and the manifest picks one canonical file per deployment
-- to prevent it.
--
-- DURATION UNITS. totalDuration is edge-observed round trip and upstreamRqDuration
-- is time in the container; both are MILLISECONDS. A request that never reached
-- the container still has a totalDuration, so filter on status before reading
-- latency.

CREATE OR REPLACE TABLE railway_requests AS
SELECT
  (regexp_replace("timestamp", '(\.\d{6})\d*Z$', '\1Z')::TIMESTAMPTZ AT TIME ZONE 'UTC') AS ts,
  method,
  path,
  httpStatus AS status,
  -- 502 is the edge failing to reach the container; 499 is the client giving up
  -- first, which during an outage is usually a symptom of the same stall.
  (httpStatus = 502) AS is_bad_gateway,
  (httpStatus = 499) AS is_client_abort,
  (httpStatus >= 500) AS is_server_error,
  totalDuration      AS total_ms,
  upstreamRqDuration AS upstream_ms,
  host,
  srcIp        AS src_ip,
  clientUa     AS client_ua,
  edgeRegion   AS edge_region,
  rxBytes      AS rx_bytes,
  txBytes      AS tx_bytes,
  upstreamAddress AS upstream_address,
  nullif(upstreamErrors, '')   AS upstream_error,
  nullif(responseDetails, '')  AS response_details,
  requestId                     AS request_id,
  deploymentId::VARCHAR         AS deployment_id,
  deploymentInstanceId::VARCHAR AS deployment_instance_id,
  coalesce(man.truncated, false) AS is_truncated,
  regexp_replace(filename, '^.*/', '') AS source_file
FROM read_json_auto('../../dumps/railway/*http*.jsonl', union_by_name = true, filename = true) raw
LEFT JOIN railway_manifest man ON man.file = regexp_replace(raw.filename, '^.*/', '')
WHERE is_canonical_dump(raw.filename);

COMMENT ON TABLE railway_requests IS 'GRAIN: one row per HTTP request seen by Railway''s edge. Shows outages as users met them -- a 502 never reaches the app and so leaves no container log line. A busy deployment can exceed the exporter''s per-fetch maximum and lose its oldest end, so prefer rates over counts and check is_truncated.';

-- Per-minute health, the shape an outage actually has.
CREATE OR REPLACE VIEW railway_health AS
SELECT
  date_trunc('minute', ts) AS minute,
  count(*) AS requests,
  count(*) FILTER (is_bad_gateway)  AS bad_gateways,
  count(*) FILTER (is_client_abort) AS client_aborts,
  round(100.0 * count(*) FILTER (is_server_error) / count(*), 1) AS pct_5xx,
  round(median(total_ms) FILTER (status = 200), 1) AS median_ok_ms
FROM railway_requests
GROUP BY 1 ORDER BY 1;

COMMENT ON VIEW railway_health IS 'GRAIN: one row per minute with requests present. Minutes with no traffic are absent rather than zero -- a gap is silence, which during an outage may be the point.';
