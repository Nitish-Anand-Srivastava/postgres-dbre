/*
===============================================================================
SCRIPT NAME:
05_xid_age_check.sql

PURPOSE:
Checks transaction ID age per database against the wraparound-protection thresholds.

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
Step 05 of workflow 'database-health/daily-health-check'

RELATED SCRIPTS:
06_slowest_recurring_statements.sql, ../../transactions-and-xid/xid-wraparound-risk/README.md

HOW TO INTERPRET RESULTS:
This check exists precisely because XID age moves slowly and predictably: seeing it daily converts a potential emergency into a scheduled task. Record the value each day -- the growth rate tells you how many days of headroom remain, which is the number that actually drives the escalation decision.
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
