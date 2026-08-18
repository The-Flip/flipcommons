-- The reference index — the `═══ §N` section each relation is defined under, and the
-- order `describe` lists them in.
--
-- Order is declared via a number §N in the header itself.
-- Numbers run in tens so a new section costs one line rather than a renumber.
-- A header with no §N still groups, after every numbered one.

CREATE OR REPLACE TABLE raw._relation_index AS
WITH
-- The catalog drives, so the parse can only ever LABEL something that exists. A private
-- helper, a `stg.` view or a stale name the regex picks up matches nothing here and
-- drops out.
catalog_objects AS (
  SELECT view_name AS relation_name FROM duckdb_views()
  WHERE database_name = current_database() AND schema_name = 'main'
  UNION ALL
  SELECT table_name FROM duckdb_tables()
  WHERE database_name = current_database() AND schema_name = 'main'
  UNION ALL
  SELECT DISTINCT function_name FROM duckdb_functions()
  WHERE database_name = current_database() AND schema_name = 'main' AND NOT internal
),
src AS (
  SELECT regexp_extract(filename, '[^/]+$') AS file, str_split(content, chr(10)) AS ls
  FROM read_text('scripts/analysis/sql/*.sql')
),
lines AS (SELECT file, ln, ls[ln] AS line FROM src, range(1, len(ls) + 1) t(ln)),
-- Each line is a section header, a definition, or neither. Both patterns are anchored at
-- the start of the line, which is where this layer writes both.
tagged AS (
  SELECT file, ln,
         regexp_extract(line, '^--\s*═+\s*(?:§(\d+)\s+)?(.*?)\s*═+\s*$',
                        ['num', 'label']) AS sect,
         nullif(regexp_extract(line,
           '^CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP\s+)?(?:VIEW|TABLE|MACRO)\s+([A-Za-z_][A-Za-z0-9_]*)\b',
           1), '') AS rel
  FROM lines
),
-- A header owns every definition below it in the SAME file — attribution is per file,
-- never across the manifest. Two files may share a §N and label, which lists them as
-- one section.
labelled AS (
  SELECT rel AS relation_name, file, ln,
         last(nullif(sect['label'], '') IGNORE NULLS) OVER w AS grp_label,
         TRY_CAST(last(nullif(sect['num'], '') IGNORE NULLS) OVER w AS INTEGER) AS grp_num
  FROM tagged
  WINDOW w AS (PARTITION BY file ORDER BY ln)
  QUALIFY rel IS NOT NULL
)
SELECT c.relation_name, l.grp_label,
       row_number() OVER (ORDER BY coalesce(l.grp_num, 9000), l.file, l.ln) AS ord
FROM catalog_objects c LEFT JOIN labelled l USING (relation_name);

COMMENT ON TABLE raw._relation_index IS
  'One row per relation or macro: the ═══ §N section it is defined under and its place in the reference listing. Order is the §N declared in the header, since neither load order nor a reopened catalog''s oids can supply it.';
