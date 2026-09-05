-- Railway edge HTTP access logs.
--
-- SOURCE: ../../dumps/railway/http.*.ndjson, one JSON object per request, the
-- GraphQL httpLogs row written verbatim.
--
-- One row per HTTP REQUEST as Railway's edge saw it, with status, timing and
-- client -- an outage as users met it rather than as the app narrated it. A 502 is
-- the edge failing to reach the container, so it appears here and leaves no
-- application log line at all.
--
-- The puller merges on requestId into one file per UTC day, so rows are unique
-- by construction; a request appearing in two files would be a day-bucketing
-- bug, and `http_duplicate_request_ids` fires on it. A deployment legitimately
-- spans several day files.
--
-- DURATION UNITS. totalDuration is edge-observed round trip and upstreamRqDuration
-- is time in the container; both are MILLISECONDS. A request that never reached
-- the container still has a totalDuration, so filter on status before reading
-- latency.

CREATE OR REPLACE TABLE railway_requests AS
SELECT
  ("timestamp"::TIMESTAMPTZ AT TIME ZONE 'UTC') AS ts,
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
  -- Probes aimed straight at the Railway hostname appear here and never at the CDN.
  is_synthetic_ua(clientUa) AS is_synthetic,
  edgeRegion   AS edge_region,
  rxBytes      AS rx_bytes,
  txBytes      AS tx_bytes,
  upstreamAddress AS upstream_address,
  nullif(upstreamErrors, '')   AS upstream_error,
  nullif(responseDetails, '')  AS response_details,
  requestId                     AS request_id,
  deploymentId::VARCHAR         AS deployment_id,
  deploymentInstanceId::VARCHAR AS deployment_instance_id,
  regexp_replace(filename, '^.*/', '') AS source_file
FROM read_json('../../dumps/railway/http.*.ndjson',
  format = 'newline_delimited', filename = true, columns = {
    'timestamp': 'VARCHAR', 'method': 'VARCHAR', 'path': 'VARCHAR',
    'httpStatus': 'BIGINT', 'totalDuration': 'BIGINT',
    'upstreamRqDuration': 'BIGINT', 'host': 'VARCHAR', 'srcIp': 'VARCHAR',
    'clientUa': 'VARCHAR', 'edgeRegion': 'VARCHAR', 'rxBytes': 'BIGINT',
    'txBytes': 'BIGINT', 'upstreamAddress': 'VARCHAR',
    'upstreamErrors': 'VARCHAR', 'responseDetails': 'VARCHAR',
    'requestId': 'VARCHAR', 'deploymentId': 'VARCHAR',
    'deploymentInstanceId': 'VARCHAR'});

COMMENT ON TABLE railway_requests IS 'GRAIN: one row per HTTP request seen by Railway''s edge, merged by the puller on requestId. Shows outages as users met them -- a 502 never reaches the app and so leaves no container log line. `is_synthetic` marks this project''s own probes; railway_health and timeline exclude them, this relation does not.';

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
WHERE NOT is_synthetic
GROUP BY 1 ORDER BY 1;

COMMENT ON VIEW railway_health IS 'GRAIN: one row per minute with requests present. Minutes with no traffic are absent rather than zero -- a gap is silence, which during an outage may be the point.';
