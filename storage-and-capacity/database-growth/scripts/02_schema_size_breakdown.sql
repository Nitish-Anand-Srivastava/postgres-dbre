/*
===============================================================================
SCRIPT NAME:
02_schema_size_breakdown.sql

PURPOSE:
Attributes the current database's footprint to individual user schemas so growth can be assigned to a business domain and an owning team.

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
Step 02 of workflow 'storage-and-capacity/database-growth'

RELATED SCRIPTS:
01_database_sizes.sql, 03_largest_tables.sql

HOW TO INTERPRET RESULTS:
Look at pct_of_user_data rather than raw bytes. A single schema holding more than roughly 60-70% of user data owns the capacity conversation, and the rest of this investigation should stay inside it. On an exchange schema layout, a dominant trading schema (orders/trades/order_book_snapshots) usually means a retention problem, whereas a dominant ledger/settlement schema means a compliance-constrained archival problem with far fewer options.
===============================================================================
*/

-- On-disk footprint of every user schema in the current database (heap +
-- indexes + TOAST for every relation the schema owns). On a crypto-exchange
-- schema layout this is the fastest way to attribute growth to a business
-- domain: the trading path (orders, trades, order_book_snapshots), the
-- money path (wallets, ledger_entries, deposits, withdrawals), or an
-- audit/compliance schema nobody has ever pruned.
--
-- Partitioned parents (relkind 'p') have no storage of their own; their
-- partitions are separate 'r' relations and are counted individually, so
-- there is no double counting here.
SELECT
    n.nspname                                                    AS schema_name,
    count(*)                                                     AS relation_count,
    pg_size_pretty(sum(pg_total_relation_size(c.oid)))            AS total_size,
    sum(pg_total_relation_size(c.oid))                            AS total_size_bytes,
    round(
        100.0 * sum(pg_total_relation_size(c.oid)) / NULLIF((
            SELECT sum(pg_total_relation_size(c2.oid))
            FROM pg_class c2
            JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
            WHERE c2.relkind IN ('r', 'p', 'm')
              AND n2.nspname NOT IN ('pg_catalog', 'information_schema')
        ), 0), 2
    )                                                            AS pct_of_user_data
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
GROUP BY n.nspname
ORDER BY sum(pg_total_relation_size(c.oid)) DESC;
