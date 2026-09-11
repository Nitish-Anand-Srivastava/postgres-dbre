/*
===============================================================================
SCRIPT NAME:
03_multixact_age.sql

PURPOSE:
Ranks tables by multixact ID age (relminmxid), a separate wraparound horizon driven by row-level locking (FOR UPDATE/SHARE, FK checks) rather than plain writes.

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
Step 03 of workflow 'transactions-and-xid/xid-wraparound-risk'

RELATED SCRIPTS:
../multixact-risk/README.md

HOW TO INTERPRET RESULTS:
High-multixact-age tables are typically ones with heavy concurrent row locking (order books, balances) even if their plain XID age looks fine -- both horizons must be tracked independently.
===============================================================================
*/

-- Per-table multixact ID age (relminmxid), which tracks a separate
-- wraparound horizon from relfrozenxid. Row-level locking (SELECT ... FOR
-- UPDATE/SHARE, foreign key checks) generates multixacts, so tables with
-- heavy row locking (order books, balances, ledgers) can accumulate
-- multixact age even when regular XID age looks healthy.
\set top_n 25
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                   AS relation_name,
    mxid_age(c.relminmxid)                                      AS multixact_age,
    c.relminmxid,
    round(
        100.0 * mxid_age(c.relminmxid) /
        (SELECT setting::numeric FROM pg_settings WHERE name = 'autovacuum_multixact_freeze_max_age'),
        2
    )                                                            AS pct_of_multixact_freeze_max_age
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm', 't')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY multixact_age DESC
LIMIT :top_n;
