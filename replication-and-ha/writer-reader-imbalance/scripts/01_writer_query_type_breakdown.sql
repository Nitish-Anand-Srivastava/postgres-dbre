/*
===============================================================================
SCRIPT NAME:
01_writer_query_type_breakdown.sql

PURPOSE:
Breaks down query activity on the writer by application to identify read-heavy traffic that could potentially be offloaded to readers.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Writer instance only (the query reads/writes state that only exists or is meaningful on the writer)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 01 of workflow 'replication-and-ha/writer-reader-imbalance'

RELATED SCRIPTS:
../reader-performance/README.md

HOW TO INTERPRET RESULTS:
Run this on the writer specifically; applications showing high active_count here that are known to be read-only candidates are your offloading opportunities -- confirm with the owning team whether their consistency requirements actually need the writer.
===============================================================================
*/

-- Connection counts broken down by application_name and usename. Useful to
-- identify which service, connection pool, or batch job is responsible for
-- a spike or leak in connection count.
SELECT
    coalesce(NULLIF(application_name, ''), '(unset)')           AS application_name,
    usename,
    datname,
    count(*)                                                    AS session_count,
    count(*) FILTER (WHERE state = 'active')                    AS active_count,
    count(*) FILTER (WHERE state = 'idle')                      AS idle_count,
    count(*) FILTER (WHERE state = 'idle in transaction')       AS idle_in_txn_count
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
GROUP BY application_name, usename, datname
ORDER BY session_count DESC;
