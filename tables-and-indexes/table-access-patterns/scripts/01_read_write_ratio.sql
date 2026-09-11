/*
===============================================================================
SCRIPT NAME:
01_read_write_ratio.sql

PURPOSE:
Compares read activity (scans) against write activity (inserts/updates/deletes) per table.

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
Step 01 of workflow 'tables-and-indexes/table-access-patterns'

RELATED SCRIPTS:
../missing-index-candidates/README.md

HOW TO INTERPRET RESULTS:
A read_write_ratio well above 1 indicates a read-dominated table (a good indexing candidate); well below 1 indicates a write-dominated table (prioritize vacuum tuning and be cautious about adding write-amplifying indexes).
===============================================================================
*/

-- Read vs. write activity ratio per table, to characterize its access
-- pattern for indexing/partitioning/caching decisions.
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    seq_scan + idx_scan                                          AS total_reads,
    n_tup_ins + n_tup_upd + n_tup_del                             AS total_writes,
    round(
        (seq_scan + idx_scan)::numeric /
        NULLIF(n_tup_ins + n_tup_upd + n_tup_del, 0),
        2
    )                                                            AS read_write_ratio
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY (seq_scan + idx_scan) + (n_tup_ins + n_tup_upd + n_tup_del) DESC
LIMIT 30;
