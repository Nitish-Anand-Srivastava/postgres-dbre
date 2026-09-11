/*
===============================================================================
SCRIPT NAME:
05_temp_files_on_disk.sql

PURPOSE:
Lists the temporary files physically present on this instance right now to size the immediate local-storage exposure.

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
Step 05 of workflow 'storage-and-capacity/temp-file-growth'

RELATED SCRIPTS:
06_statistics_freshness.sql

HOW TO INTERPRET RESULTS:
Zero rows is the healthy steady state and simply means nothing is spilling at this instant. A small number of very large files usually belongs to one still-running query -- match it against script 04 by timing. Many files with an age of hours and no matching active session suggests files left behind by backends that died; PostgreSQL cleans these up on the next instance restart, so note them but do not attempt manual cleanup. Sum size_bytes and compare against CloudWatch FreeLocalStorage for this specific instance to judge how close to the edge you are.
===============================================================================
*/

-- Temporary files currently on disk for THIS instance. Temp files live on
-- per-instance local storage (CloudWatch FreeLocalStorage), which is
-- entirely separate from the shared Aurora cluster volume -- so always run
-- this on the instance that is actually reporting low local storage, not
-- on whichever instance you happen to be connected to.
--
-- pg_ls_tmpdir() execution is granted to pg_monitor by default. Check role
-- membership first rather than letting the call fail with a permission
-- error, so this script degrades to guidance instead of an error for an
-- under-privileged role.
\set top_n 50
SELECT pg_has_role(current_user, 'pg_monitor', 'MEMBER')          AS can_list_tmpdir
\gset

\if :can_list_tmpdir
SELECT
    name                                                         AS temp_file_name,
    pg_size_pretty(size)                                          AS file_size,
    size                                                          AS size_bytes,
    modification                                                  AS last_modified,
    now() - modification                                          AS age
FROM pg_ls_tmpdir()
ORDER BY size DESC
LIMIT :top_n;
\else
SELECT
    'The current role is not a member of pg_monitor, so pg_ls_tmpdir() '
    'cannot be executed and on-disk temp files cannot be listed. Ask an '
    'administrator to GRANT pg_monitor TO your role, or use the CloudWatch '
    'FreeLocalStorage metric for this instance instead -- it measures the '
    'same exposure from outside the database and needs no database '
    'privileges at all.'                                          AS notice;
\endif
