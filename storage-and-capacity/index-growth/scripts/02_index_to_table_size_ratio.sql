/*
===============================================================================
SCRIPT NAME:
02_index_to_table_size_ratio.sql

PURPOSE:
Computes index bytes relative to heap bytes per table, which is the metric that actually identifies over-indexing.

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
Step 02 of workflow 'storage-and-capacity/index-growth'

RELATED SCRIPTS:
03_index_usage_and_bloat.sql

HOW TO INTERPRET RESULTS:
A ratio above 1.0 means more storage is spent on indexes than on the data itself. Treat that as normal on a narrow, read-heavy reference table and as a red flag on a wide, write-heavy table such as orders or ledger_entries, where each additional index multiplies WAL volume and vacuum cost on the hottest write path in the system. Read index_count alongside the ratio: eight or more indexes on a high-throughput table almost always contains at least one redundancy. The script filters out relations under 100 MB by default -- adjust min_total_bytes if you need a wider view.
===============================================================================
*/

-- Tables whose index footprint is large relative to their heap. A ratio
-- above roughly 1.0 (more bytes in indexes than in the table itself) is
-- normal for a narrow, heavily queried lookup table but is a strong
-- over-indexing signal on a wide, write-heavy table such as an order or
-- ledger table -- every extra index multiplies write amplification, WAL
-- volume, and vacuum cost, not just stored bytes.
\set top_n 30
\set min_total_bytes 104857600
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    count(ix.indexrelid)                                         AS index_count,
    pg_size_pretty(pg_relation_size(c.oid))                       AS heap_size,
    pg_size_pretty(pg_indexes_size(c.oid))                        AS index_size,
    round(
        pg_indexes_size(c.oid)::numeric
        / NULLIF(pg_relation_size(c.oid), 0), 2
    )                                                            AS index_to_heap_ratio,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_index ix ON ix.indrelid = c.oid
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND pg_total_relation_size(c.oid) >= :min_total_bytes
GROUP BY n.nspname, c.relname, c.oid
ORDER BY (pg_indexes_size(c.oid)::numeric / NULLIF(pg_relation_size(c.oid), 0))
         DESC NULLS LAST
LIMIT :top_n;
