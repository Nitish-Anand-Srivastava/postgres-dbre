/*
===============================================================================
SCRIPT NAME:
04_index_state_check.sql

PURPOSE:
Checks whether an index change or an invalid index removed the access path the plan relied on.

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
Step 04 of workflow 'query-optimization/query-plan-regression'

RELATED SCRIPTS:
05_configuration_drift_check.sql, ../../tables-and-indexes/invalid-indexes/README.md

HOW TO INTERPRET RESULTS:
An invalid index is the single most common structural cause of a post-migration plan regression: the planner ignores it completely, so the plan silently reverts to a sequential scan while the application keeps paying its write cost. In the usage inventory, look for an index whose idx_scan has stopped advancing since the regression began -- that is the access path the plan abandoned, and it tells you which alternative the planner is now preferring.
===============================================================================
*/

-- Indexes left in an INVALID state, almost always because a previous
-- CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY failed partway through
-- (a killed session, statement_timeout, or deadlock). Invalid indexes are
-- not used by the planner but still consume storage and slow down writes,
-- so they should be dropped and, if needed, recreated concurrently.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    i.relname                                                   AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                      AS wasted_size,
    pg_get_indexdef(ix.indexrelid)                               AS index_definition
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE NOT ix.indisvalid
ORDER BY pg_relation_size(i.oid) DESC;

-- Index size, scan counts, and a simple size-per-row proxy for bloat.
-- PostgreSQL 16+ also reports last_idx_scan/last_idx_tup_fetch/
-- last_idx_tup_read (timestamps) on pg_stat_all_indexes, which are included
-- here to show *when* an index was last actually useful, not just whether
-- idx_scan is currently zero since the last stats reset.
\set top_n 40
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    i.relname                                                   AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                      AS index_size,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    s.last_idx_scan,
    ix.indisunique,
    ix.indisprimary,
    ix.indisvalid
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_stat_all_indexes s ON s.indexrelid = ix.indexrelid
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_relation_size(i.oid) DESC
LIMIT :top_n;
