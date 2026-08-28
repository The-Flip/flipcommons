-- The cross-source timeline, and the coverage table that keeps it honest.

-- READ THIS BEFORE ANY CROSS-SOURCE CLAIM.
--
-- The sources do not cover the same period, and it is not close: the Sentry pull
-- spans whatever `pull/sentry --days` asked for, while the Railway exports are
-- typically far shorter. `SELECT min(ts) FROM timeline WHERE level = 'error'`
-- therefore dates an incident to whenever the NARROWEST export opens.
--
-- Volumes are not comparable across sources either: a Sentry row is one grouped
-- event, a Railway row is one line (one stack FRAME, for legacy tracebacks), and
-- an http row is one request. Bunny and Railway are worse -- they OVERLAP, since
-- the CDN sits in front and a cache miss is one request logged twice. Group by
-- `source`, or use `edge_health`.
--
-- `tier` is declared per branch, as in `timeline` below: it is a property of the
-- branch, not derivable from the rows. It lives here as well because a stream can
-- have coverage and no problems -- the media zone and the Postgres service both
-- do -- so reading tier off a problem stream would leave those rows NULL.
CREATE OR REPLACE VIEW coverage AS
WITH railway AS (
  SELECT 'railway' AS source, service AS stream, 'container' AS tier, source_file,
         count(*) AS rows,
         count(*) FILTER (level_confidence = 'json') AS trusted_level_rows,
         min(ts) AS window_start, max(ts) AS window_end
  FROM railway_lines GROUP BY 1, 2, 3, 4
),
http AS (
  SELECT 'railway', 'http', 'origin', source_file, count(*), count(*), min(ts), max(ts)
  FROM railway_requests GROUP BY 4
),
-- Grouped by source_file like every other branch rather than naming the file as
-- a literal. sentry_uptime selects its rows on the issue CATEGORY, so a second
-- monitor joins it without an edit; a filename spelled out here would still
-- name whichever issue happened to be the only monitor when it was written.
sentry AS (
  SELECT 'sentry', 'errors', 'sentry', source_file, count(*), count(*), min(ts), max(ts)
  FROM sentry_errors GROUP BY 4
  UNION ALL
  SELECT 'sentry', 'uptime', 'sentry', source_file, count(*), count(*), min(ts), max(ts)
  FROM sentry_uptime GROUP BY 4
),
-- Streamed by pull zone rather than lumped as one 'cdn', because the zones front
-- different origins: an apex row has a Railway row behind it and a media row does
-- not. One file is one UTC day, so the row count is a day's traffic and the
-- window is the part of that day the file happens to hold.
bunny AS (
  SELECT 'bunny', zone, 'cdn', source_file, count(*), count(*), min(ts), max(ts)
  FROM bunny_requests GROUP BY 2, 4
)
SELECT c.*,
  -- One warning to a reader: this file is not the whole account of its window.
  -- `complete` is the puller's own record -- a day over at pull time, or for
  -- Sentry a count()-verified haul -- so a file still accumulating is flagged,
  -- and so is a file the manifest does not cover (a hand-dropped dump), because
  -- completeness is what cannot be read back off the file.
  NOT coalesce(man.complete, false) AS likely_truncated,
  date_diff('minute', c.window_start, c.window_end) AS window_minutes
FROM (SELECT * FROM railway UNION ALL SELECT * FROM http UNION ALL SELECT * FROM sentry
      UNION ALL SELECT * FROM bunny) c
LEFT JOIN manifests man ON man.file = c.source_file
ORDER BY c.source, c.stream, c.window_start;

COMMENT ON VIEW coverage IS 'GRAIN: one row per source file / stream. THE view to read before any cross-source claim: it states each export''s real window and flags files that are not the whole account of it -- a day still accumulating at pull time, or a file the manifest never recorded.';

-- `count(*)` over these rows is meaningless whatever the filter: a row is a log
-- line on one branch, a failed request on another and a grouped Sentry event on a
-- third, and only FAILED requests join at all. `summary` counts.
--
-- `tier` says WHERE in the request path an observation was made, which puts the
-- one arithmetic this layer cannot allow into the data: 'cdn' and 'origin' are
-- the same requests seen at two points and must never be added together.
--
-- 'container' and 'sentry' overlap more weakly, and nothing guards it: an SSR
-- exception is logged by the container AND reported to Sentry, so one fault can
-- appear under both.
CREATE OR REPLACE VIEW timeline AS
SELECT 'railway' AS source, service AS stream, 'container' AS tier, ts, level, message,
       NULL AS ref, level_confidence, is_continuation
FROM railway_lines
UNION ALL
-- Only failed requests join the timeline; a 200 is not an event worth reading
-- beside a log line. Query railway_requests directly for the full picture.
SELECT 'railway', 'http', 'origin', ts, 'error',
       method || ' ' || path || ' -> ' || status
         || coalesce(' (' || upstream_error || ')', ''),
       request_id, 'json', false
FROM railway_requests WHERE is_server_error
UNION ALL
-- The same rule one tier out. This duplicates the branch above for any request
-- that reached Railway, and earns its place because a failure the edge produced
-- itself -- or produced for a request the origin never saw -- appears nowhere
-- else. Cache disposition rides along in the message, which separates the two.
SELECT 'bunny', zone, 'cdn', ts, 'error',
       path || ' -> ' || status || ' (' || cache_status || ')',
       request_id, 'json', false
FROM bunny_requests WHERE is_server_error
UNION ALL
SELECT 'sentry', 'errors', 'sentry', ts, level, coalesce(nullif(message, ''), title), issue_short_id, 'sentry', false
FROM sentry_errors
UNION ALL
SELECT 'sentry', 'uptime', 'sentry', ts, 'error', title, issue_short_id, 'sentry', false
FROM sentry_uptime;

COMMENT ON VIEW timeline IS 'GRAIN: one row per OBSERVATION, which differs by source -- a log line, a failed request at either edge, or a whole Sentry event. Read in ts order; do NOT total it. Tier ''cdn'' and tier ''origin'' are the same requests seen at two points, so a cache miss that failed is here twice, and only FAILED requests join at all. Count summary instead. Read `coverage` first.';

-- The real problems: observations whose severity the ROW ITSELF declared.
--
-- Railway invents a severity for any line that is not JSON -- stdout becomes
-- info, stderr becomes error -- and Python's StreamHandler writes to stderr. So
-- on the app service every pre-formatter Django INFO and every gunicorn boot
-- line arrived tagged `error`, and on Postgres the image's routine LOG:/INFO:
-- chatter still does. Counting those is how "how many errors" comes back orders
-- of magnitude high, and they outnumber the lines that declared a severity by
-- so much that the real ones are invisible among them.
--
-- The excluded set is READ FROM railway_services. Every value in
-- `unstructured_confidence` is by definition a severity Railway guessed from a
-- stream, so a service added there is excluded without an edit here. A list
-- repeated in this file would fail silently in the dangerous direction: the new
-- value matches nothing, and that service's invented severities count as errors.
--
-- Nothing is lost by narrowing: `timeline` keeps every row and carries
-- level_confidence, so the stream-classified lines around an onset are
-- `FROM timeline WHERE level_confidence = 'stream_app'`.
CREATE OR REPLACE VIEW problems AS
SELECT * FROM timeline
WHERE level IN ('error', 'fatal')
  -- IS NOT NULL guards the NOT IN three-valued-logic trap: one NULL in the
  -- subquery would make this NULL for every row and empty the whole view.
  AND level_confidence NOT IN (
    SELECT unstructured_confidence FROM railway_services
    WHERE unstructured_confidence IS NOT NULL
  )
  AND NOT is_continuation;  -- a stack frame is not an observation

COMMENT ON VIEW problems IS 'GRAIN: one row per non-continuation observation at error or worse whose severity the row itself declared. Excludes every Railway line whose level was guessed from stdout/stderr rather than carried in the line. The stream to READ during an incident; count summary instead, because tier ''cdn'' and tier ''origin'' hold the same failed request twice. To read the EXCLUDED lines, query timeline and filter on level_confidence.';

-- One row per stream: what was pulled, what was wrong with it and over what
-- window. The counting surface, and what `build` prints.
--
-- THE PROBLEM COUNT SITS BESIDE THE VOLUME because alone it is the wrong answer
-- to "how many errors". A problem is a failed REQUEST on an http stream, a log
-- LINE on a container stream and a grouped EVENT on a Sentry one -- three
-- measurements in one column, which undenominated invite the reading that the
-- container was quiet while the edge failed. Against `rows` they cannot.
--
-- `tier` carries the arithmetic this layer cannot allow: 'cdn' and 'origin' are
-- the same requests seen at two points and must never be added to each other.
-- edge_health can make that query unwriteable by pivoting the tiers into columns;
-- here there is no join key to pivot on, since a Bunny request id is 32 hex
-- characters and a Railway one is base64. Visible is what is achievable.
--
-- Volumes come from `coverage`, not `timeline`, which carries only FAILED http
-- requests -- counting it would report the failures as the traffic. Problems are
-- joined on rather than filtered in so a stream with none still appears, at zero.
--
-- first_problem/last_problem are when trouble was OBSERVED; window_start/
-- window_end are what the export covers. Both are here because the gap between
-- them is the first thing worth seeing.
CREATE OR REPLACE VIEW summary AS
WITH vol AS (
  -- Grouped by tier rather than picking one per pair: if the dependency ever
  -- broke, the stream splits into two visible rows instead of one row silently
  -- claiming whichever tier came first.
  SELECT source, stream, tier, sum(rows) AS rows,
         sum(trusted_level_rows) AS trusted,
         min(window_start) AS window_start, max(window_end) AS window_end
  FROM coverage GROUP BY 1, 2, 3
),
probs AS (
  SELECT source, stream, count(*) AS problems,
         min(ts) AS first_problem, max(ts) AS last_problem
  FROM problems GROUP BY 1, 2
)
SELECT v.tier, v.source, v.stream, v.rows, v.trusted,
       coalesce(p.problems, 0) AS problems,
       v.window_start, v.window_end,
       p.first_problem, p.last_problem
FROM vol v LEFT JOIN probs p USING (source, stream)
ORDER BY v.tier, v.source, v.stream;

COMMENT ON VIEW summary IS 'GRAIN: one row per source/stream, which is also one row per tier -- tier is functionally determined by the pair. The view to read when asked "how many errors", and the reason the answer sits beside `rows`: a problem is a failed request in one stream and a log line in another, so the counts are only interpretable against their volumes. Rows within one tier are safe to add; ''cdn'' and ''origin'' are the same requests seen at two points and must not be added to each other.';
