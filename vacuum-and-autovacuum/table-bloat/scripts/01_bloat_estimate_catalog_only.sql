/*
===============================================================================
SCRIPT NAME:
01_bloat_estimate_catalog_only.sql

PURPOSE:
Lightweight, lock-free bloat proxy using only pg_class/pg_stat_all_tables -- always safe to run.

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
Step 01 of workflow 'vacuum-and-autovacuum/table-bloat'

RELATED SCRIPTS:
02_exact_bloat_pgstattuple.sql

HOW TO INTERPRET RESULTS:
Use this to triage which tables merit a closer, exact look; it is a proxy, not an exact bloat percentage.
===============================================================================
*/

-- Lightweight, catalog-only bloat proxy: live/dead tuple ratio plus actual
-- on-disk size vs. a rough expectation from reltuples. This is NOT as
-- accurate as the pgstattuple extension's exact physical scan, but it
-- requires no extension and no table lock, so it is safe to run against any
-- table at any time -- use it for triage, and use pgstattuple (see
-- 05_pgstattuple_exact_bloat.sql in this same directory, if present) for
-- confirmation before scheduling a maintenance window.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    pg_size_pretty(pg_relation_size(c.oid))                      AS heap_size,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size,
    s.n_live_tup,
    s.n_dead_tup,
    round(100.0 * s.n_dead_tup / NULLIF(s.n_live_tup + s.n_dead_tup, 0), 2) AS dead_tuple_pct,
    c.reltuples::bigint                                          AS planner_row_estimate,
    c.relpages                                                   AS heap_pages
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_stat_all_tables s ON s.relid = c.oid
WHERE c.relkind = 'r'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT 30;
