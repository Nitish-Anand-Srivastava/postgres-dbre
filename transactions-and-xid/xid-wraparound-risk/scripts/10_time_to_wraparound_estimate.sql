/*
===============================================================================
SCRIPT NAME:
10_time_to_wraparound_estimate.sql

PURPOSE:
Estimates remaining headroom (in transactions and, using an assumed rate, wall-clock time) before the oldest table reaches the hard 2^31 wraparound limit.

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
Step 10 of workflow 'transactions-and-xid/xid-wraparound-risk'

RELATED SCRIPTS:
../../vacuum-and-autovacuum/emergency-autovacuum/README.md

HOW TO INTERPRET RESULTS:
Treat estimated_hours_remaining as a rough order of magnitude, not a precise SLA -- transaction rate varies with trading volume/market volatility. Use it to prioritize response urgency, not to schedule a leisurely fix.
===============================================================================
*/

-- Rough time-to-wraparound estimate for the table with the oldest XID age.
-- 2,146,483,648 (2^31 - 1,000,000 safety margin) is used as the effective
-- hard ceiling; PostgreSQL actually enforces failsafe/refusal behavior well
-- before the true 2^31 limit, but this gives a conservative worst-case
-- figure. Replace :assumed_xids_per_second with your own measured average
-- transaction rate (see performance/throughput-degradation script 01 for
-- how to measure it) for a realistic estimate -- there is no way to derive
-- a wall-clock estimate from catalogs alone without an assumed rate.
\set assumed_xids_per_second 500
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                    AS table_name,
    age(c.relfrozenxid)                                          AS current_xid_age,
    2146483648 - age(c.relfrozenxid)                              AS xids_remaining,
    round((2146483648 - age(c.relfrozenxid)) / NULLIF(:assumed_xids_per_second, 0) / 3600.0, 1) AS estimated_hours_remaining_at_assumed_rate
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm', 't')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY current_xid_age DESC
LIMIT 10;
