/*
===============================================================================
SCRIPT NAME:
02_table_transaction_age.sql

PURPOSE:
Ranks ordinary tables, TOAST tables, and materialized views by relfrozenxid age to find the specific tables driving the database-level age found in script 01.

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
Step 02 of workflow 'transactions-and-xid/xid-wraparound-risk'

RELATED SCRIPTS:
01_database_transaction_age.sql, 03_multixact_age.sql

HOW TO INTERPRET RESULTS:
The table(s) at the top of this list are where autovacuum most urgently needs to succeed; note their relkind -- TOAST tables ('t') are easy to overlook but age exactly like ordinary tables.
===============================================================================
*/

-- Per-table XID age ranked descending, restricted to ordinary tables and
-- materialized views (relkind 'r'/'m'/'t' -- includes TOAST tables, which
-- can independently accumulate age and are frequently overlooked).
\set top_n 25
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS relation_name,
    c.relkind,
    age(c.relfrozenxid)                                         AS xid_age,
    c.relfrozenxid,
    pg_size_pretty(pg_total_relation_size(c.oid))                AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm', 't')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY xid_age DESC
LIMIT :top_n;
