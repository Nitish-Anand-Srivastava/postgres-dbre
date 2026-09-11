/*
===============================================================================
SCRIPT NAME:
03_contended_rows.sql

PURPOSE:
Identifies the specific rows/relations currently experiencing the most lock waiting.

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
Step 03 of workflow 'concurrency-and-locking/transaction-contention'

RELATED SCRIPTS:
../../database-health/comprehensive-health-check/README.md

HOW TO INTERPRET RESULTS:
Repeated appearances of the same relation across multiple snapshots over time confirms a genuine hot-row pattern rather than a one-off spike.
===============================================================================
*/

-- Raw pg_locks detail joined to pg_stat_activity, restricted to relation and
-- transactionid locks that are either not yet granted or held by a session
-- that is also blocking someone else. This is the ground truth for "who
-- holds what lock, in what mode, on what object".
SELECT
    l.pid,
    a.usename,
    l.locktype,
    n.nspname                                                   AS schema_name,
    c.relname                                                    AS relation_name,
    l.mode,
    l.granted,
    a.state,
    now() - a.query_start                                        AS held_or_waiting_duration,
    left(a.query, 160)                                           AS query_snippet
FROM pg_locks l
LEFT JOIN pg_class c ON c.oid = l.relation
LEFT JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.pid <> pg_backend_pid()
  AND l.locktype IN ('relation', 'tuple', 'transactionid')
ORDER BY l.granted ASC, held_or_waiting_duration DESC NULLS LAST;
