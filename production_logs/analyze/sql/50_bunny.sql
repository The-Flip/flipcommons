-- Bunny CDN edge access logs.
--
-- SOURCE: ../../dumps/bunny/*.ndjson, one JSON object per request, the Logging
-- API v2 row written verbatim. One file is one UTC day of one zone, merged by
-- the puller on requestId, though nothing here reads the filename: the zone
-- comes from the rows and the window is measured from them.
--
-- Bunny sits in front of Railway, so these rows and railway_requests are the same
-- requests seen at two points. A cache miss appears in both; a cache HIT never
-- reaches Railway at all. The two edges log different things -- Bunny has cache
-- disposition, PoP, country and bytes, and no method or latency whatsoever.
--
-- A 502 here may be Bunny's own, when it cannot reach the origin, or an origin
-- 502 passed through unchanged. The log records only the status.

CREATE OR REPLACE TABLE bunny_requests AS
SELECT
  ("timestamp"::TIMESTAMPTZ AT TIME ZONE 'UTC') AS ts,
  coalesce(z.zone, 'zone:' || r.pullZoneId) AS zone,
  r.cacheStatus AS cache_status,
  -- HIT, MISS, EXPIRED, BYPASS or `-`. Only HIT was answered by the edge:
  -- EXPIRED revalidated against the origin and BYPASS was ruled out of the cache,
  -- so both went to Railway like a MISS. `-` never reached a cache lookup -- the
  -- http->https redirect the edge answers itself, and client aborts. It does not
  -- mean the origin was spared: Railway logs 499s in the same window, so some
  -- aborted requests were forwarded before the client gave up.
  (r.cacheStatus = 'HIT') AS is_cache_hit,
  r.statusCode AS status,
  -- Named to match railway_requests, so the same predicate reads the same at both
  -- tiers. 499 is the client giving up first.
  (r.statusCode = 502) AS is_bad_gateway,
  (r.statusCode = 499) AS is_client_abort,
  (r.statusCode >= 500) AS is_server_error,
  r.scheme,
  r.host,
  -- Path and query separated so `path` means what it means in railway_requests
  -- and the two tiers can be joined on it.
  coalesce(nullif(r.path, ''), '/') AS path,
  nullif(regexp_extract(r.url, '\?([^#]*)', 1), '') AS query,
  r.url,
  -- `-` is Bunny's empty marker in every text column.
  nullif(r.referer, '-') AS referer,
  r.bytesSent AS bytes_sent,
  -- The real client, anonymised on these zones to a /24 or /64: a network, not a
  -- caller. railway_requests.src_ip is the Bunny PoP that forwarded the request,
  -- so the two columns are not the same thing.
  nullif(r.remoteIp, '-') AS client_ip,
  nullif(r.userAgent, '-') AS client_ua,
  nullif(r.countryCode, '-') AS country,
  -- Bunny's PoP code (TX, UK, DE...): where the request was served. `country`
  -- is where the client was.
  nullif(r.edgeLocation, '-') AS edge_location,
  r.requestId AS request_id,
  r.pullZoneId AS pull_zone,
  regexp_replace(r.filename, '^.*/', '') AS source_file
FROM read_json('../../dumps/bunny/*.ndjson',
  format = 'newline_delimited', filename = true, columns = {
    'timestamp': 'VARCHAR', 'pullZoneId': 'BIGINT', 'requestId': 'VARCHAR',
    'cacheStatus': 'VARCHAR', 'statusCode': 'BIGINT', 'bytesSent': 'BIGINT',
    'remoteIp': 'VARCHAR', 'countryCode': 'VARCHAR', 'edgeLocation': 'VARCHAR',
    'scheme': 'VARCHAR', 'host': 'VARCHAR', 'path': 'VARCHAR',
    'url': 'VARCHAR', 'userAgent': 'VARCHAR', 'referer': 'VARCHAR'}) r
LEFT JOIN bunny_pull_zones z ON z.pull_zone = r.pullZoneId;

COMMENT ON TABLE bunny_requests IS 'GRAIN: one row per HTTP request at the Bunny CDN edge, merged by the puller on Bunny''s request id. The OUTERMOST tier -- the only relation that sees cache hits, which never reach Railway. Do NOT union with railway_requests: a cache miss appears in both. No method and no latency; Bunny logs neither.';

-- Per-minute health at the CDN edge: what users got, including what the edge
-- answered itself.
CREATE OR REPLACE VIEW bunny_health AS
SELECT
  date_trunc('minute', ts) AS minute,
  zone,
  count(*) AS requests,
  count(*) FILTER (is_bad_gateway)  AS bad_gateways,
  count(*) FILTER (is_client_abort) AS client_aborts,
  round(100.0 * count(*) FILTER (is_server_error) / count(*), 1) AS pct_5xx,
  round(100.0 * count(*) FILTER (is_cache_hit) / count(*), 1) AS pct_cache_hit
FROM bunny_requests
GROUP BY 1, 2 ORDER BY 1, 2;

COMMENT ON VIEW bunny_health IS 'GRAIN: one row per minute per pull zone with requests present. What users actually got, including the requests the edge answered itself. Minutes with no traffic are absent rather than zero.';

-- The two tiers side by side, per minute. One column per tier rather than a
-- `tier` column, because a union invites the sum that double-counts a cache miss.
-- A minute where the CDN reports failures the origin does not is one where the
-- fault was at or before the edge.
--
-- Don't read cdn_requests minus origin_requests as what the cache absorbed: the
-- exports can have different coverage, so some of that difference is missing
-- export. `pct_cache_hit` is the measurement. A NULL means that tier has no
-- export for the minute, not that it saw no traffic, and both sides are FULL
-- joined so neither window clips the other.
--
-- Every zone whose origin is Railway contributes, derived from
-- bunny_pull_zones.origin: railway_requests holds their traffic mixed together
-- with nothing saying which zone forwarded a request, so naming one zone compares
-- a subset of the CDN against the whole origin and makes the origin look larger
-- than the tier in front of it. `edge_tier_inverted` catches that. `media` stays
-- out because its origin is not Railway.
--
-- Aggregated from bunny_requests, not rolled up from bunny_health, whose grain is
-- per zone: summing its rows would duplicate the origin across the join, and its
-- percentages cannot be averaged across zones without weighting.
CREATE OR REPLACE VIEW edge_health AS
WITH cdn AS (
  SELECT
    date_trunc('minute', ts) AS minute,
    count(*) AS requests,
    count(*) FILTER (is_bad_gateway) AS bad_gateways,
    round(100.0 * count(*) FILTER (is_server_error) / count(*), 1) AS pct_5xx,
    round(100.0 * count(*) FILTER (is_cache_hit) / count(*), 1) AS pct_cache_hit
  FROM bunny_requests
  WHERE zone IN (SELECT zone FROM bunny_pull_zones WHERE origin IS NOT NULL)
  GROUP BY 1
)
SELECT
  coalesce(b.minute, h.minute) AS minute,
  b.requests     AS cdn_requests,
  h.requests     AS origin_requests,
  b.bad_gateways AS cdn_502s,
  h.bad_gateways AS origin_502s,
  b.pct_5xx      AS cdn_pct_5xx,
  h.pct_5xx      AS origin_pct_5xx,
  -- Blended across the contributing zones. The per-zone rates, which differ by a
  -- lot, are in bunny_health.
  b.pct_cache_hit AS cdn_pct_cache_hit,
  h.median_ok_ms AS origin_median_ok_ms
FROM cdn b
FULL JOIN railway_health h ON h.minute = b.minute
ORDER BY 1;

COMMENT ON VIEW edge_health IS 'GRAIN: one row per minute, the Railway-fronted CDN zones and the Railway edge side by side. Read ACROSS a row; never sum or subtract the two request columns -- they describe the same requests twice, with different coverage. A NULL means that tier has no export covering the minute.';
