/*
===============================================================================
SCRIPT NAME:
04_sessions_spilling_now.sql

PURPOSE:
Shows currently active sessions and flags those waiting on temporary file I/O right now.

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
Step 04 of workflow 'storage-and-capacity/temp-file-growth'

RELATED SCRIPTS:
05_temp_files_on_disk.sql

HOW TO INTERPRET RESULTS:
Any row with spilling_to_temp_now = true is actively writing or reading a temp file, and its query_snippet plus application_name tells you exactly which workload and which team to contact. During a local-storage incident this is the script that names the offender. Long query_runtime combined with a BufFile wait event is the worst case -- a query that has been spilling for minutes may have already written many gigabytes. Cross-check the statement against script 03 to see whether this is a recurring pattern or a one-off, because that determines whether the fix is a code change or a parameter change.
===============================================================================
*/

-- Live view of active backends with an explicit flag for the ones that are
-- reading or writing temporary files at this instant. BufFileRead,
-- BufFileWrite and BufFileTruncate are the IO wait events PostgreSQL
-- reports while a sort, hash, or materialize node is spilling to local
-- storage -- if a session is parked on one of these, its query text is your
-- immediate culprit.
--
-- Absence of rows flagged here does NOT prove nothing is spilling: this is
-- an instantaneous sample, and a query can write a large temp file between
-- two samples. Use script 01 and script 03 for cumulative evidence and this
-- script for live incident attribution.
SELECT
    pid,
    datname,
    usename,
    application_name,
    client_addr,
    wait_event_type,
    wait_event,
    (wait_event_type = 'IO' AND wait_event LIKE 'BufFile%')       AS spilling_to_temp_now,
    now() - query_start                                          AS query_runtime,
    now() - xact_start                                           AS transaction_runtime,
    left(query, 250)                                             AS query_snippet
FROM pg_stat_activity
WHERE state = 'active'
  AND pid <> pg_backend_pid()
  AND backend_type = 'client backend'
ORDER BY spilling_to_temp_now DESC, query_runtime DESC NULLS LAST;
