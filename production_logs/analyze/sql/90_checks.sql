-- Invariants. Each returns ZERO rows when healthy; any row is a finding.
--
-- These guard the assumptions the layer makes about log SHAPE. The severity model
-- rests on Railway indexing a JSON line's keys as attributes, so if an export
-- format changes, or a service starts emitting something unparsed, these surface
-- it instead of the layer quietly mis-classifying.

CREATE OR REPLACE VIEW checks AS
-- A NULL ts means the export changed its timestamp format.
SELECT 'railway_null_ts' AS check_name,
       count(*) || ' Railway lines have an unparseable timestamp' AS detail
FROM railway_lines WHERE ts IS NULL
HAVING count(*) > 0

UNION ALL
SELECT 'unknown_railway_service',
       'Unmapped service ' || service || ' (' || count(*) || ' lines); add it to railway_services'
FROM railway_lines WHERE service LIKE 'unknown:%' GROUP BY service

UNION ALL
-- RailwayJSONFormatter always sets logger and pid. A python-emitted line lacking
-- them means its field names changed and the columns here are silently NULL.
-- Scoped to python because Caddy legitimately omits logger on lifecycle lines.
SELECT 'python_json_missing_fields',
       count(*) || ' python JSON lines lack logger or pid; RailwayJSONFormatter''s keys may have changed'
FROM railway_lines WHERE emitter = 'python' AND (logger IS NULL OR pid IS NULL)
HAVING count(*) > 0

UNION ALL
-- Tested by the PRESENCE of formatter output, not by the share of lines lacking
-- it. RailwayJSONFormatter is the only thing on this service emitting `pid`, and
-- `pid` is what resolves `emitter` to 'python', so if it stops, python lines stop
-- appearing at all -- a binary signal that cannot be diluted.
--
-- A ratio cannot do this job. Most app lines never passed through Python logging:
-- Node SSR logs a line per request, Railway narrates container lifecycle, and the
-- predeploy step writes management-command output to stdout. Their share rises
-- with traffic, so any threshold on it eventually fires on a healthy deployment.
--
-- The row guard keeps this quiet in the minutes after a deploy, when a window can
-- hold a handful of lines and none of them Python's yet.
SELECT 'formatter_not_running',
       'No python JSON lines on the app service since '
         || (SELECT deployed_at FROM json_logging_deployed) || ', across '
         || count(*) || ' app lines; RailwayJSONFormatter may not be running'
FROM railway_lines
WHERE service = 'app' AND ts > (SELECT deployed_at FROM json_logging_deployed)
HAVING count(*) > 20 AND count(*) FILTER (emitter = 'python') = 0

UNION ALL
-- A line of any other width is either a request carrying a raw `|` -- recoverable,
-- and read from both ends -- or the export having changed shape, which is not.
SELECT 'bunny_malformed_lines',
       count(*) || ' Bunny log lines are not 12 fields (widths: '
         || string_agg(DISTINCT fields::VARCHAR, ', ') || '); see bunny_malformed_lines'
FROM bunny_malformed_lines
HAVING count(*) > 0

UNION ALL
-- A level outside the shared vocabulary means norm_level needs a new case.
SELECT 'unnormalised_level',
       'Level ' || coalesce(level, 'NULL') || ' is not one of debug/info/warn/error/fatal ('
         || count(*) || ' rows)'
FROM timeline
-- `level IS NULL` is not redundant with the NOT IN: under three-valued logic
-- `NULL NOT IN (...)` evaluates to NULL, which WHERE discards, so a level field
-- vanishing from an export would slip past the guard that exists to catch it.
WHERE level IS NULL OR level NOT IN ('debug', 'info', 'warn', 'error', 'fatal')
GROUP BY level

UNION ALL
-- `problems` splits on level_confidence: counted when the line declared its own
-- severity, excluded when railway_services says the value is a stream-derived
-- guess. A value in neither set is a source added without anyone deciding which
-- side it falls on. It is COUNTED, so this turns that default into a decision.
SELECT 'unknown_level_confidence',
       'level_confidence ' || level_confidence || ' (' || count(*) || ' rows) is neither '
         || 'self-declared nor a railway_services.unstructured_confidence; '
         || 'problems is counting it -- confirm that is right'
FROM timeline
WHERE level_confidence NOT IN ('json', 'sentry')
  AND level_confidence NOT IN (
    SELECT unstructured_confidence FROM railway_services
    WHERE unstructured_confidence IS NOT NULL
  )
GROUP BY level_confidence

UNION ALL
-- The per-deployment export carries no service tag, so its service is read off the
-- filename prefix and falls back to the web service when there is none. Where a
-- deployment id also appears in a legacy dump, whose rows are tagged, the two can
-- be compared instead of the derivation being trusted.
SELECT 'deployment_service_mismatch',
       'Deployment ' || d.deployment_id || ' reads as ' || any_value(d.service)
         || ' from ' || any_value(d.source_file) || ', but is tagged '
         || any_value(l.service) || ' in the legacy dumps'
FROM railway_lines d
JOIN railway_lines l ON l.deployment_id = d.deployment_id AND l.origin = 'legacy_export'
WHERE d.origin = 'deploy_export' AND d.service <> l.service
GROUP BY d.deployment_id

UNION ALL
-- HTTP rows are not deduped, so reading two overlapping exports of one deployment
-- silently doubles its traffic. The manifest is supposed to make that impossible;
-- this proves it did.
SELECT 'http_deployment_double_read',
       'Deployment ' || deployment_id || ' read from ' || count(DISTINCT source_file)
         || ' files; its request counts are inflated'
FROM railway_requests GROUP BY deployment_id HAVING count(DISTINCT source_file) > 1

UNION ALL
-- The same failure with a sharper signal, for two files that disagree about their
-- filenames but describe the same requests.
SELECT 'http_duplicate_request_ids',
       count(*) || ' request ids appear more than once across the HTTP dumps'
FROM (SELECT request_id FROM railway_requests GROUP BY 1 HAVING count(*) > 1)
HAVING count(*) > 0

UNION ALL
-- Every manifest entry should resolve to a file the readers took. A miss means the
-- naming convention moved and the glob no longer matches.
SELECT 'manifest_file_not_read',
       'Manifest lists ' || file || ' but no rows were read from it'
FROM railway_manifest m
WHERE NOT EXISTS (SELECT 1 FROM railway_requests h WHERE h.source_file = m.file)
  AND NOT EXISTS (SELECT 1 FROM railway_lines l WHERE l.source_file = m.file)

UNION ALL
SELECT 'http_missing_status', count(*) || ' HTTP rows have no status'
FROM railway_requests WHERE status IS NULL
HAVING count(*) > 0

UNION ALL
-- Bunny's format is positional and unlabelled, so a column inserted upstream
-- shifts every field after it without anything failing to parse. The url is the
-- canary: it is the one field whose shape is unmistakable, so a row whose url is
-- not a url means every column here is off by one.
SELECT 'bunny_column_order_shifted',
       count(*) || ' CDN rows have a url that is not a url; the pipe field order may have changed'
FROM bunny_requests WHERE url NOT LIKE 'http://%' AND url NOT LIKE 'https://%'
HAVING count(*) > 0

UNION ALL
-- The other half of that failure: a shift landing a plausible number in the
-- timestamp column parses fine and silently dates the traffic to 1970 or the far
-- future. Bounded against now() rather than a hardcoded date so it ages well.
SELECT 'bunny_ts_out_of_range',
       count(*) || ' CDN rows fall outside 2020..now; epoch-millisecond parsing may be wrong'
FROM bunny_requests WHERE ts < TIMESTAMP '2020-01-01' OR ts > now() + INTERVAL 1 DAY
HAVING count(*) > 0

UNION ALL
-- How the next pull zone announces itself, rather than arriving as an unreadable
-- number.
SELECT 'unknown_bunny_pull_zone',
       'Unmapped pull zone ' || zone || ' (' || count(*) || ' requests); add it to bunny_pull_zones'
FROM bunny_requests WHERE zone LIKE 'zone:%' GROUP BY zone

UNION ALL
-- Bunny's request id is what the reader dedupes on, so a NULL or empty one would
-- collapse every affected row into a single survivor and quietly delete traffic.
SELECT 'bunny_missing_request_id',
       count(*) || ' CDN rows have no request id; overlapping dumps would be deduped wrongly'
FROM bunny_requests WHERE request_id IS NULL OR request_id = ''
HAVING count(*) > 0

UNION ALL
-- The only check here guarding topology rather than format. Bunny is in front of
-- Railway, so over minutes both tiers cover, the CDN cannot have seen fewer
-- requests than the origin behind it. When it appears to, the layer is misreading:
-- a Railway-fronted pull zone missing from edge_health's zone set is how this
-- breaks, and it is invisible to every shape check because each file parses.
--
-- Thresholded and aggregated rather than tested per minute. A request Bunny stamps
-- at 11:59:59.9 and Railway at 12:00:00.1 inverts both minutes, so a per-minute
-- test fires constantly; across a window the skew cancels. The 5% allowance covers
-- what does not, chiefly anything reaching the Railway host without passing the
-- edge. Restricted to shared minutes because comparing raw totals would measure
-- the Railway export's per-deployment cap rather than the cache.
SELECT 'edge_tier_inverted',
       'Origin logged ' || sum(origin_requests) || ' requests against the CDN''s '
         || sum(cdn_requests) || ' over ' || count(*) || ' shared minutes; the CDN is '
         || 'in front and cannot see fewer. A Railway-fronted pull zone is probably '
         || 'missing from edge_health -- check bunny_pull_zones.origin'
FROM edge_health
WHERE cdn_requests IS NOT NULL AND origin_requests IS NOT NULL
HAVING sum(origin_requests) > 1.05 * sum(cdn_requests)

UNION ALL
-- Uptime events must not also appear in the errors dataset, or every downtime
-- detection would be counted twice.
SELECT 'uptime_leaked_into_errors',
       count(*) || ' error events look like uptime detections; timeline would double-count'
FROM sentry_errors WHERE title ILIKE 'Downtime detected%'
HAVING count(*) > 0

UNION ALL
-- The Bunny half of manifest_file_not_read. Exempts what the manifest reports as
-- legitimately empty -- logging switched off, or a day recorded as holding no rows
-- -- so what remains is a file that HAS content and is not being read.
SELECT 'manifest_file_not_read',
       'Manifest lists ' || file || ' (' || rows || ' rows) but no rows were read from it'
FROM bunny_manifest m
WHERE m.rows > 0 AND m.logging_enabled
  AND NOT EXISTS (SELECT 1 FROM bunny_requests b WHERE b.source_file = m.file)

UNION ALL
-- No VIEW may read the filesystem. A view over a file reader re-reads its files on
-- every query, resolved against the CALLER's working directory -- and `query` does
-- not cd. read_csv raises there, which is loud; glob returns an empty result, so a
-- view built on one reports nothing found, with no error, from every directory but
-- this one.
--
-- Matched on the shape of a CALL rather than a list of reader names, which would
-- have to track DuckDB and would miss read_csv_auto for spelling. Requiring the
-- open paren also keeps this branch from matching its own text, which
-- duckdb_views() hands back like any other view.
SELECT 'view_reads_filesystem',
       'View ' || view_name || ' reads the filesystem, so it resolves only from '
         || 'analyze/sql/ and is empty or failing everywhere else; make it a TABLE'
FROM duckdb_views()
WHERE internal = false
  AND regexp_matches(sql, '"?\bread_[a-z_]*"?\s*\(|"?\bglob"?\s*\(');

COMMENT ON VIEW checks IS 'Zero rows means healthy. Any row is a finding -- most often that a log format changed and the severity model has quietly stopped applying.';
