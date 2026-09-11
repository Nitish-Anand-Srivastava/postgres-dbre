/*
===============================================================================
SCRIPT NAME:
01_high_block_access_per_row.sql

PURPOSE:
Finds statements that touch a disproportionate number of blocks for the number of rows they return.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor`, plus SELECT on `pg_stat_statements` (granted automatically to `pg_read_all_stats` once the extension is created; otherwise `GRANT SELECT ON pg_stat_statements TO <role>;`).

PREREQUISITES:
pg_stat_statements must be listed in shared_preload_libraries (an Aurora DB cluster parameter-group change that requires a reboot) and created in the current database. This script detects its absence and prints an instructional notice instead of failing, so it is safe to run either way.

EXECUTION ORDER:
Step 01 of workflow 'query-optimization/nested-loop-problems'

RELATED SCRIPTS:
02_sequential_scan_pressure.sql

HOW TO INTERPRET RESULTS:
blocks_per_row_returned in the thousands means the statement is reading a substantial fraction of a table for every row it emits. Combined with a large stddev and max relative to mean, that is the classic parameter-sensitive nested loop: cheap for selective parameters, catastrophic for a wide date range or a high-volume trading pair. Aggregate statements (a count or sum returning one row) will naturally rank high here and are false positives -- read the query snippet before acting.
===============================================================================
*/

-- pg_stat_statements presence check. This script only detects whether the
-- extension is already available; it never creates it.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available
\gset

\if :pgss_available
-- The fingerprint of a runaway nested loop: enormous block access relative
-- to rows returned, because the inner side is being re-executed once per
-- outer row. This does not prove a nested loop by itself (a missing index
-- on a single-table filter produces a similar ratio), but it reliably
-- ranks the statements worth capturing a plan for.
\set top_n 20
\set min_calls 5
SELECT
    queryid,
    calls,
    rows                                                          AS total_rows_returned,
    round(rows::numeric / NULLIF(calls, 0), 1)                     AS avg_rows_per_call,
    shared_blks_hit,
    shared_blks_read,
    round(
        (shared_blks_hit + shared_blks_read)::numeric / NULLIF(calls, 0), 1
    )                                                              AS avg_blocks_per_call,
    round(
        (shared_blks_hit + shared_blks_read)::numeric / NULLIF(rows, 0), 1
    )                                                              AS blocks_per_row_returned,
    round(mean_exec_time::numeric, 2)                              AS mean_exec_time_ms,
    round(max_exec_time::numeric, 2)                               AS max_exec_time_ms,
    round(stddev_exec_time::numeric, 2)                            AS stddev_exec_time_ms,
    left(query, 200)                                               AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND calls >= :min_calls
  AND rows > 0
ORDER BY (shared_blks_hit + shared_blks_read)::numeric / NULLIF(rows, 0) DESC
LIMIT :top_n;
\else
SELECT 'pg_stat_statements is not installed in this database, so statement-level '
       'statistics are unavailable. Ask an administrator to add '
       'pg_stat_statements to shared_preload_libraries in the Aurora DB cluster '
       'parameter group (a reboot is required for that change to take effect) '
       'and then run CREATE EXTENSION pg_stat_statements; in a change-managed '
       'session. Without it, query-level investigation must fall back to '
       'application-side latency metrics plus the catalog and table-level '
       'statistics used by the other scripts in this workflow.'  AS notice;
\endif
