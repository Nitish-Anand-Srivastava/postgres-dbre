/*
===============================================================================
SCRIPT NAME:
09_transaction_id_age.sql

PURPOSE:
Measures transaction ID age per database against the wraparound-protection thresholds.

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
Step 09 of workflow 'database-health/comprehensive-health-check'

RELATED SCRIPTS:
10_top_queries_by_total_time.sql, ../../transactions-and-xid/xid-wraparound-risk/README.md

HOW TO INTERPRET RESULTS:
pct_of_freeze_max_age under 50% is comfortable; above 50% and rising between runs means freezing is not keeping pace and needs attention this week, not this quarter. Above 100% means anti-wraparound autovacuum is already mandatory for some relations. The failure mode at the far end is not slowness: PostgreSQL refuses new write transactions to protect data integrity, which on an exchange means trading, deposits, and withdrawals all stop at once.
===============================================================================
*/

-- Transaction ID (XID) age per database, measured against datfrozenxid.
-- autovacuum_freeze_max_age (default 200,000,000) is the point at which
-- autovacuum is forced to run in every table regardless of cost limits;
-- autovacuum_vacuum_freeze_min_age / vacuum_failsafe_age (default
-- 1,600,000,000) is the emergency threshold before wraparound-protection
-- kicks in and PostgreSQL refuses new writes to protect data integrity.
SELECT
    datname,
    age(datfrozenxid)                                           AS xid_age,
    datfrozenxid,
    round(
        100.0 * age(datfrozenxid) /
        (SELECT setting::numeric FROM pg_settings WHERE name = 'autovacuum_freeze_max_age'),
        2
    )                                                            AS pct_of_freeze_max_age,
    2147483647 - age(datfrozenxid)                                AS xids_remaining_to_wraparound
FROM pg_database
WHERE datallowconn
ORDER BY xid_age DESC;
