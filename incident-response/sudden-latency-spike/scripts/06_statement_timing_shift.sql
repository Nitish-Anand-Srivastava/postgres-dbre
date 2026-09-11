/*
===============================================================================
SCRIPT NAME:
06_statement_timing_shift.sql

PURPOSE:
Compares current statement timings against pg_stat_statements history to find the specific statements whose cost has moved.

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
pg_stat_statements installed in the current database; the script prints a notice and exits cleanly if it is not.

EXECUTION ORDER:
Step 06 of workflow 'incident-response/sudden-latency-spike'

RELATED SCRIPTS:
../../performance/high-cpu/README.md

HOW TO INTERPRET RESULTS:
A statement whose mean_exec_time is far above its historical norm, with a large stddev_exec_time, is either contended or parameter-sensitive; a uniformly elevated mean with a small stddev is a plan regression. Capture the queryid before you remediate -- it is the handle every follow-up workflow needs.
===============================================================================
*/

-- pg_stat_statements presence check. This script never creates the
-- extension itself -- it only detects whether it is already available,
-- so the script is safe to run blind during an incident.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available
\gset

\if :pgss_available
-- Top statements by mean execution time, restricted to statements called at
-- least :min_calls times so a single slow one-off migration query does not
-- crowd out genuinely slow, frequently-run application queries.
\set top_n 20
\set min_calls 20
SELECT
    queryid,
    calls,
    round(mean_exec_time::numeric, 2)                             AS mean_exec_time_ms,
    round(stddev_exec_time::numeric, 2)                           AS stddev_exec_time_ms,
    round(max_exec_time::numeric, 2)                              AS max_exec_time_ms,
    rows,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND calls >= :min_calls
ORDER BY mean_exec_time DESC
LIMIT :top_n;
\else
SELECT 'pg_stat_statements is not installed in this database, so statement-level '
       'history is unavailable for this triage step. Ask an administrator to add '
       'pg_stat_statements to shared_preload_libraries in the Aurora DB cluster '
       'parameter group (a reboot is required for that change) and then install '
       'the extension in a change-managed session -- an investigation script must '
       'never do that for you mid-incident. Continue the checklist with the '
       'remaining scripts; none of them depend on this extension.' AS notice;
\endif
