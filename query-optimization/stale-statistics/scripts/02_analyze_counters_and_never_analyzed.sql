/*
===============================================================================
SCRIPT NAME:
02_analyze_counters_and_never_analyzed.sql

PURPOSE:
Surfaces tables that have never been analyzed or are analyzed far less often than their write volume warrants.

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
Step 02 of workflow 'query-optimization/stale-statistics'

RELATED SCRIPTS:
03_autoanalyze_configuration.sql

HOW TO INTERPRET RESULTS:
Tables flagged as never analyzed are the highest priority: the planner is estimating their size from whatever reltuples value the last vacuum or table creation left behind, which for a freshly migrated table is often zero, and a zero-row estimate reliably produces a nested loop over what is in fact a very large table. Note that these counters reset with pg_stat_reset() and on an Aurora failover, so a recently promoted writer can show zero analyze counts for tables that are in fact well analyzed -- cross-check last_autoanalyze, which is a timestamp rather than a counter.
===============================================================================
*/

-- Analyze history per table, ordered so that never-analyzed and
-- rarely-analyzed tables surface first. A table with substantial write
-- activity and a near-zero analyze count is either newly created, excluded
-- from autoanalyze by a per-table setting, or being starved by autovacuum
-- worker contention.
\set top_n 40
SELECT
    schemaname                                                   AS schema_name,
    relname                                                      AS table_name,
    n_live_tup,
    n_dead_tup,
    n_mod_since_analyze,
    n_tup_ins,
    n_tup_upd,
    n_tup_del,
    analyze_count                                                AS manual_analyze_count,
    autoanalyze_count,
    last_analyze,
    last_autoanalyze,
    last_vacuum,
    last_autovacuum,
    CASE
        WHEN last_analyze IS NULL AND last_autoanalyze IS NULL
            THEN 'never analyzed -- planner has no real statistics for this table'
        WHEN analyze_count + autoanalyze_count = 0
            THEN 'no analyze recorded since the last statistics reset'
        ELSE NULL
    END                                                          AS attention_flag
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY
    (last_analyze IS NULL AND last_autoanalyze IS NULL) DESC,
    (analyze_count + autoanalyze_count) ASC,
    n_live_tup DESC
LIMIT :top_n;
