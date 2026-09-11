/*
===============================================================================
SCRIPT NAME:
04_wal_heavy_statements.sql

PURPOSE:
Attributes WAL generation to individual statements using pg_stat_statements, with the Aurora reporting caveat applied.

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
Step 04 of workflow 'storage-and-capacity/wal-generation'

RELATED SCRIPTS:
05_write_volume_by_table.sql

HOW TO INTERPRET RESULTS:
Rank by total WAL first to find the statements that dominate cluster-wide volume, then look at avg_wal_per_call to find individually expensive statements that may simply not run often yet. Critically: a reported wal_bytes of 0 for a statement you know performs writes means this engine version did not record it, NOT that the statement is WAL-cheap -- the script flags this explicitly in wal_reporting_caveat. Corroborate every conclusion here against the per-table write counters in script 05 before acting, and prefer the table-level evidence when the two disagree.
===============================================================================
*/

-- pg_stat_statements presence check. This script never creates the
-- extension itself -- it only detects whether it is already available.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available
\gset

\if :pgss_available
-- Statements generating the most WAL, ranked by total WAL bytes. High
-- WAL-generating statements are the primary driver of replica lag (Aurora
-- readers must apply the same redo the writer generates) and of storage
-- growth; this is the first place to look when replication lag or storage
-- growth correlates with a specific workload rather than overall volume.
--
-- CAVEAT (observed on Aurora PostgreSQL 17.7): pg_stat_statements'
-- wal_records/wal_fpi/wal_bytes columns have been observed reporting 0 for
-- some write-heavy INSERT/UPDATE statements, even though those statements
-- are demonstrably generating WAL (visible via pg_stat_wal / rising storage
-- growth). Treat a 0 here as "not observed via this instrumentation path
-- for this statement on this engine version" -- NOT as proof the statement
-- generates no WAL. Corroborate with storage-and-capacity/wal-generation
-- (cluster-wide pg_stat_wal totals) before concluding a specific statement
-- is WAL-cheap.
\set top_n 20
SELECT
    queryid,
    calls,
    wal_records,
    wal_fpi,
    pg_size_pretty(wal_bytes)                                     AS total_wal,
    pg_size_pretty((wal_bytes / NULLIF(calls, 0))::bigint)         AS avg_wal_per_call,
    CASE WHEN wal_bytes = 0
         THEN 'zero reported -- not observed/unavailable on this engine version, not proof of no WAL (see script header)'
         ELSE NULL
    END                                                            AS wal_reporting_caveat,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY wal_bytes DESC
LIMIT :top_n;
\else
SELECT 'pg_stat_statements is not installed in this database, so query-level '
       'statistics are unavailable for this capacity check. Ask an administrator '
       'to add pg_stat_statements to shared_preload_libraries in the Aurora DB '
       'cluster parameter group (a reboot is required) and then install the '
       'extension in a change-managed session; the exact statement is documented '
       'in the repository prerequisites guide and is deliberately never executed '
       'by an investigation script. The remaining scripts in this workflow do not '
       'depend on this extension.'
                                                                 AS notice;
\endif
