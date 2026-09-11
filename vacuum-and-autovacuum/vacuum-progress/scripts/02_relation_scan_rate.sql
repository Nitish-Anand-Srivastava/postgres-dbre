/*
===============================================================================
SCRIPT NAME:
02_relation_scan_rate.sql

PURPOSE:
Computes the target table's total size against the vacuum's current scanned-block progress to estimate percent complete.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 02 of workflow 'vacuum-and-autovacuum/vacuum-progress'

RELATED SCRIPTS:
../autovacuum-not-keeping-up/README.md

HOW TO INTERPRET RESULTS:
pct_heap_scanned is only for the 'scanning heap' phase; once in 'vacuuming indexes' or 'cleaning up indexes' phases, watch indexes_processed/indexes_total instead.
===============================================================================
*/

-- Percent-complete estimate for a specific in-flight vacuum, combining
-- pg_stat_progress_vacuum with the table's total block count.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                    AS table_name,
    v.phase,
    v.heap_blks_scanned,
    v.heap_blks_total,
    round(100.0 * v.heap_blks_scanned / NULLIF(v.heap_blks_total, 0), 1) AS pct_heap_scanned,
    v.indexes_processed,
    v.indexes_total
FROM pg_stat_progress_vacuum v
JOIN pg_class c ON c.oid = v.relid
JOIN pg_namespace n ON n.oid = c.relnamespace
ORDER BY pct_heap_scanned ASC NULLS LAST;
