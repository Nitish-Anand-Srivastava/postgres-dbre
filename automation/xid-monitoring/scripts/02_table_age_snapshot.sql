/*
===============================================================================
SCRIPT NAME:
02_table_age_snapshot.sql

PURPOSE:
Table-level XID age snapshot (top N oldest tables), intended to be captured on every scheduled run.

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
Step 02 of workflow 'automation/xid-monitoring'

RELATED SCRIPTS:
03_scheduling_runbook.md

HOW TO INTERPRET RESULTS:
Track which specific tables consistently rank highest across scheduled runs -- they are the highest-churn/least-frequently-vacuumed tables and the best candidates for proactive per-table freeze tuning, exactly as in transactions-and-xid/transaction-age.
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
