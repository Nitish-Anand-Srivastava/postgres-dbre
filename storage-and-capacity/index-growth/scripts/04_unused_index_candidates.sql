/*
===============================================================================
SCRIPT NAME:
04_unused_index_candidates.sql

PURPOSE:
Lists never-scanned, non-constraint-backing indexes as drop candidates for review by the owning team.

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
Step 04 of workflow 'storage-and-capacity/index-growth'

RELATED SCRIPTS:
../../schema-changes/drop-index-safely/README.md

HOW TO INTERPRET RESULTS:
This is a candidate list, never a decision. Before proposing any drop, confirm three things: statistics have been accumulating across at least one full business cycle including month-end and regulatory reporting runs, the index shows zero scans on the readers as well as the writer (reporting traffic is often pinned to a reader), and the owning application team recognizes the access pattern it was built for. Constraint-backing and primary-key indexes are deliberately excluded here because they exist for correctness rather than performance.
===============================================================================
*/

-- Candidate unused indexes: idx_scan = 0 (or very low relative to table
-- write volume) since the last stats reset, excluding indexes that back a
-- primary key, unique, exclusion, or foreign-key-supporting constraint,
-- since those often exist for correctness/latching reasons rather than
-- query performance and must not be dropped purely on scan-count evidence.
--
-- IMPORTANT: idx_scan resets to zero on instance restart/failover and after
-- pg_stat_reset(). Cross-check stats_reset on pg_stat_database and confirm
-- the index has genuinely been unused across at least one full business
-- cycle (including month-end/quarter-end batch jobs and reporting queries)
-- before considering removal. Never drop an index based on this report
-- alone.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS table_name,
    i.relname                                                   AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                      AS index_size,
    s.idx_scan,
    ix.indisunique,
    ix.indisprimary,
    EXISTS (
        SELECT 1 FROM pg_constraint con
        WHERE con.conindid = ix.indexrelid
    )                                                            AS backs_constraint
FROM pg_index ix
JOIN pg_class c ON c.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_stat_all_indexes s ON s.indexrelid = ix.indexrelid
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND s.idx_scan = 0
  AND NOT ix.indisprimary
  AND NOT EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = ix.indexrelid)
ORDER BY pg_relation_size(i.oid) DESC;
