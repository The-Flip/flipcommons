-- Bunny CDN edge access logs.
--
-- SOURCE: ../../dumps/bunny/*.log, pipe-delimited, no header, one line per request:
--
--   CacheStatus|StatusCode|Timestamp|BytesSent|PullZoneId|RemoteIP
--   |RefererUrl|Url|EdgeLocation|UserAgent|UniqueRequestId|CountryCode
--
-- Timestamp is epoch MILLISECONDS. Lines within a file are in no particular
-- order. One file is one UTC day of one zone, though nothing here reads the
-- filename: the zone comes from the rows and the window is measured from them.
--
-- Bunny sits in front of Railway, so these rows and railway_requests are the same
-- requests seen at two points. A cache miss appears in both; a cache HIT never
-- reaches Railway at all. The two edges log different things -- Bunny has cache
-- disposition, PoP, country and bytes, and no method or latency whatsoever.
--
-- A 502 here may be Bunny's own, when it cannot reach the origin, or an origin
-- 502 passed through unchanged. The log records only the status.

-- What pull/bunny recorded about its own output. Three facts cannot be recovered
-- by reading a file:
--
--   `complete`          false for the day still in progress at pull time. A
--                       partial day and a quiet day are identical on disk.
--   `logging_enabled`   false for a zone with logging switched off, whose file
--                       is empty for that reason and not for want of traffic.
--   `ip_anonymization`  whether client_ip is a network or a whole address.
--
-- A hand-downloaded file is absent from the manifest, so every consumer LEFT
-- JOINs and tolerates the miss.
CREATE OR REPLACE TABLE bunny_manifest AS
SELECT
  f.file::VARCHAR AS file,
  f.zone_id::BIGINT AS pull_zone,
  f.zone_name::VARCHAR AS bunny_name,
  f.date::DATE AS log_date,
  f.http::INTEGER AS http_status,
  f.rows::BIGINT AS rows,
  (f.first_ts::TIMESTAMPTZ AT TIME ZONE 'UTC') AS first_ts,
  (f.last_ts::TIMESTAMPTZ AT TIME ZONE 'UTC') AS last_ts,
  f.complete,
  f.logging_enabled,
  f.ip_anonymization,
  (f.pulled_at::TIMESTAMPTZ AT TIME ZONE 'UTC') AS pulled_at
FROM read_json('../../dumps/bunny/manifest.json', columns = {
       'files': 'STRUCT(file VARCHAR, zone_id BIGINT, zone_name VARCHAR, date DATE,
                        http INTEGER, rows BIGINT, first_ts VARCHAR, last_ts VARCHAR,
                        complete BOOLEAN, logging_enabled BOOLEAN,
                        ip_anonymization VARCHAR, pulled_at VARCHAR)[]'}),
     unnest(files) AS u(f);

COMMENT ON TABLE bunny_manifest IS 'GRAIN: one row per file pull/bunny wrote. The authority on whether a day is complete and on whether a zone had logging on at all -- neither is recoverable from the file. Hand-downloaded dumps are absent.';

-- Every line, still whole, with only its field count computed. The CSV reader is
-- handed a delimiter that cannot occur (\x01) so the splitting happens below, in
-- SQL, for two reasons:
--
--   BUNNY DOES NOT ESCAPE THE DELIMITER. A `|` inside a url, referer or user
--   agent yields a 13-field line, which a fixed 12-column reader rejects
--   outright -- so one request to `/search?q=a|b` would abort the whole database
--   build. Reading the line whole turns the width into data.
--
--   AN EMPTY FILE has no dialect to sniff, and empty files are routine: a day
--   older than Bunny's four-day retention, or a zone with logging switched off.
--   `auto_detect = false` is what makes them readable.
--
-- quote and escape stay disabled because the format has no quoting rules, so a
-- lone `"` in a user agent would otherwise swallow the rest of the line.
--
-- TEMP: the tables below partition it completely, so persisting the split lines
-- as well would store the same data twice.
CREATE OR REPLACE TEMP TABLE bunny_lines AS
SELECT str_split(line, '|') AS f,
       len(str_split(line, '|')) AS fields,
       regexp_replace(filename, '^.*/', '') AS source_file
FROM read_csv('../../dumps/bunny/*.log',
  delim = e'\x01', header = false, quote = '', escape = '',
  auto_detect = false, filename = true, columns = {'line': 'VARCHAR'});

-- Normally empty. A row here is either a request carrying a raw `|` or the export
-- format changing shape, and `checks` fires on any of them.
CREATE OR REPLACE TABLE bunny_malformed_lines AS
SELECT source_file, fields, array_to_string(f, '|') AS line
FROM bunny_lines WHERE fields <> 12;

COMMENT ON TABLE bunny_malformed_lines IS 'GRAIN: one row per log line whose field count is not 12. Empty when the export matches the documented format.';

CREATE OR REPLACE TABLE bunny_requests AS
WITH raw AS (
  SELECT
    -- Built from microseconds rather than to_timestamp() so the result cannot
    -- shift with whatever timezone the building session happens to be in.
    make_timestamp(f[3]::BIGINT * 1000) AS ts,
    f[1] AS cache_status,
    f[2]::INTEGER AS status,
    f[4]::BIGINT AS bytes_sent,
    f[5]::BIGINT AS pull_zone,
    -- `-` is Bunny's empty marker in every text column.
    nullif(f[6], '-') AS client_ip,
    nullif(f[7], '-') AS referer,
    -- Positions counted from BOTH ends, which is exact at 12 fields and the best
    -- available reading beyond it. The first six fields cannot contain a `|` --
    -- a status word, three numbers and an IP -- and neither can the last two, a
    -- hex request id and a country code. Any surplus lies in the middle, and the
    -- url absorbs it: a query string is the likeliest place for a raw delimiter.
    array_to_string(f[8:fields - 4], '|') AS url,
    nullif(f[fields - 3], '-') AS edge_location,
    nullif(f[fields - 2], '-') AS client_ua,
    f[fields - 1] AS request_id,
    nullif(f[fields], '-') AS country,
    source_file
  -- Short lines have no reading at all, and bunny_malformed_lines already holds
  -- them.
  FROM bunny_lines WHERE fields >= 12
),
-- Bunny's request id is unique per request, so overlapping files are safe --
-- re-pulling today, whose file is still being written, is a no-op rather than a
-- doubling. The opposite of the Railway HTTP rule, where a repeated request is a
-- real repeat and a canonical file is picked instead.
deduped AS (
  SELECT *, row_number() OVER (PARTITION BY request_id ORDER BY source_file) AS dup_rank
  FROM raw
)
SELECT
  d.ts,
  coalesce(z.zone, 'zone:' || d.pull_zone) AS zone,
  d.cache_status,
  -- HIT, MISS, EXPIRED, BYPASS or `-`. Only HIT was answered by the edge:
  -- EXPIRED revalidated against the origin and BYPASS was ruled out of the cache,
  -- so both went to Railway like a MISS. `-` never reached a cache lookup -- the
  -- http->https redirect the edge answers itself, and client aborts. It does not
  -- mean the origin was spared: Railway logs 499s in the same window, so some
  -- aborted requests were forwarded before the client gave up.
  (d.cache_status = 'HIT') AS is_cache_hit,
  d.status,
  -- Named to match railway_requests, so the same predicate reads the same at both
  -- tiers. 499 is the client giving up first.
  (d.status = 502) AS is_bad_gateway,
  (d.status = 499) AS is_client_abort,
  (d.status >= 500) AS is_server_error,
  -- Split out of the url so `path` means what it means in railway_requests --
  -- path without query -- and the two tiers can be joined on it.
  regexp_extract(d.url, '^(https?)://', 1) AS scheme,
  regexp_extract(d.url, '^https?://([^/?#]+)', 1) AS host,
  coalesce(nullif(regexp_extract(d.url, '^https?://[^/?#]*([^?#]*)', 1), ''), '/') AS path,
  nullif(regexp_extract(d.url, '\?([^#]*)', 1), '') AS query,
  d.url,
  d.referer,
  d.bytes_sent,
  -- The real client, anonymised on these zones to a /24 or /64: a network, not a
  -- caller. railway_requests.src_ip is the Bunny PoP that forwarded the request,
  -- so the two columns are not the same thing.
  d.client_ip,
  d.client_ua,
  d.country,
  -- Bunny's PoP code (ASB, UK, DEN...): where the request was served. `country`
  -- is where the client was.
  d.edge_location,
  d.request_id,
  d.pull_zone,
  d.source_file
FROM deduped d
LEFT JOIN bunny_pull_zones z ON z.pull_zone = d.pull_zone
WHERE d.dup_rank = 1;

COMMENT ON TABLE bunny_requests IS 'GRAIN: one row per HTTP request at the Bunny CDN edge, deduped on Bunny''s request id. The OUTERMOST tier -- the only relation that sees cache hits, which never reach Railway. Do NOT union with railway_requests: a cache miss appears in both. No method and no latency; Bunny logs neither.';

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
-- exports have different coverage and the Railway one is capped per deployment,
-- so most of that difference is missing export. `pct_cache_hit` is the
-- measurement. A NULL means that tier has no export for the minute, not that it
-- saw no traffic, and both sides are FULL joined so neither window clips the
-- other.
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
