/*
===============================================================================
SCRIPT NAME:
05_post_drop_regression_check.sql

PURPOSE:
Watches for a query regression after the drop, over a window long enough to include periodic jobs.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor`, plus SELECT on `pg_stat_statements` (granted automatically to `pg_read_all_stats` once the extension is created; otherwise `GRANT SELECT ON pg_stat_statements TO <role>;`).

PREREQUISITES:
`pg_stat_statements` must already be installed in this database (`shared_preload_libraries` includes it on the Aurora cluster parameter group and `CREATE EXTENSION pg_stat_statements;` has been run by an administrator in a change-managed session). This script never creates it.

EXECUTION ORDER:
Step 05 of workflow 'schema-changes/drop-index-safely'

RELATED SCRIPTS:
../../query-optimization/query-plan-regression/README.md

HOW TO INTERPRET RESULTS:
Run this immediately after the drop and again daily for at least a full cycle of periodic jobs, because a regression from a wrong drop usually appears when a weekly or month-end reconciliation job runs rather than in the first hour. Compare mean_exec_time_ms for statements touching the affected table against the values recorded before the drop -- a statement whose mean execution time has jumped by an order of magnitude is the signature of a lost index, and the fix is to recreate it concurrently from the definition you recorded in step 1 of the runbook. If pg_stat_statements is not installed, the script prints guidance instead of failing, and you should fall back to application-level latency monitoring and the sequential-scan counters on the affected table.
===============================================================================
*/

-- pg_stat_statements presence check. This script never creates the
-- extension itself -- it only detects whether it is already available.
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
       'statistics are unavailable for this check. Ask an administrator to add '
       'pg_stat_statements to shared_preload_libraries in the Aurora DB cluster '
       'parameter group (a reboot is required) and then install the extension in '
       'a change-managed session; the exact statement is documented in the '
       'repository prerequisites guide and is deliberately never executed by an '
       'investigation script. The other scripts in this workflow do not depend on '
       'this extension.'
                                                                 AS notice;
\endif
