/*
===============================================================================
SCRIPT NAME:
04_table_size_components.sql

PURPOSE:
Splits each large relation into heap, TOAST, and index bytes, because the component mix determines which remediation is actually available.

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
Step 04 of workflow 'storage-and-capacity/database-growth'

RELATED SCRIPTS:
03_largest_tables.sql, 05_largest_indexes.sql

HOW TO INTERPRET RESULTS:
This is the script that chooses your remediation path. High pct_indexes (over 50%) means the cheapest win is index cleanup -- reversible, no data migration, and it also cuts write amplification and WAL. High pct_toast means wide varlena payloads (JSON order snapshots, raw blockchain transaction bodies) and the question becomes whether that payload belongs in the OLTP database at all. A dominant heap with a proportionate estimated_row_count is genuine data volume, which means partitioning and archival. A dominant heap with a modest row count means wide rows or bloat -- check dead tuples before treating it as real data.
===============================================================================
*/

-- Splits each large relation's footprint into its three physical
-- components -- main heap fork, TOAST (out-of-line storage for wide values
-- such as JSON order payloads, raw blockchain transaction bodies, or
-- serialized order-book snapshots), and indexes -- so growth can be
-- attributed to the right cause before any remediation is chosen.
--
-- pg_relation_size(oid) returns the main fork only; pg_indexes_size(oid)
-- sums every index on the relation; the TOAST branch is guarded with a
-- reltoastrelid <> 0 test because relations with no varlena columns have
-- no TOAST relation at all.
\set top_n 30
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    pg_size_pretty(pg_relation_size(c.oid))                       AS heap_main_fork,
    pg_size_pretty(
        CASE WHEN c.reltoastrelid <> 0
             THEN pg_total_relation_size(c.reltoastrelid)
             ELSE 0 END
    )                                                            AS toast_total,
    pg_size_pretty(pg_indexes_size(c.oid))                        AS index_total,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS grand_total,
    round(
        100.0 * pg_indexes_size(c.oid)
        / NULLIF(pg_total_relation_size(c.oid), 0), 1
    )                                                            AS pct_indexes,
    round(
        100.0 * (CASE WHEN c.reltoastrelid <> 0
                      THEN pg_total_relation_size(c.reltoastrelid)
                      ELSE 0 END)
        / NULLIF(pg_total_relation_size(c.oid), 0), 1
    )                                                            AS pct_toast,
    c.reltuples::bigint                                          AS estimated_row_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;
