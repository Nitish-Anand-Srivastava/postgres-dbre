/*
===============================================================================
SCRIPT NAME:
05_tables_with_autovacuum_disabled.sql

PURPOSE:
Finds tables with autovacuum explicitly disabled via storage parameters, a common and easily overlooked risk factor.

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
Step 05 of workflow 'transactions-and-xid/xid-wraparound-risk'

RELATED SCRIPTS:
06_long_running_transactions.sql

HOW TO INTERPRET RESULTS:
Any table returned here combined with a high xid_age from script 02 is a strong candidate root cause -- review whether the original reason for disabling autovacuum still applies, and whether a scheduled manual VACUUM was ever put in place to compensate (it usually was not).
===============================================================================
*/

-- Tables with autovacuum explicitly disabled via a reloptions override.
-- Anti-wraparound vacuums still eventually force-run on these tables
-- regardless of this setting, but disabling routine autovacuum means the
-- table accumulates far more dead tuples and XID age between forced passes
-- than it should, making the eventual anti-wraparound vacuum larger and more
-- disruptive than necessary.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                    AS table_name,
    c.reloptions,
    age(c.relfrozenxid)                                          AS xid_age,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND c.reloptions IS NOT NULL
  AND EXISTS (
      SELECT 1 FROM unnest(c.reloptions) opt WHERE opt = 'autovacuum_enabled=false'
  )
ORDER BY xid_age DESC;
