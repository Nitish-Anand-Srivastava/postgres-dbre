/*
===============================================================================
SCRIPT NAME:
01_pg_cron_extension_and_jobs.sql

PURPOSE:
Checks whether pg_cron is installed in this database and, if so, lists every job currently registered.

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
`pg_cron` must already be installed in this database. It must first be added to `shared_preload_libraries` on the Aurora DB cluster parameter group (requires a reboot to take effect), and then `CREATE EXTENSION pg_cron;` must be run once by an administrator in a change-managed session. This script never creates or schedules anything -- it only detects whether pg_cron is already installed, and prints an instructional notice instead of failing if it is not.

EXECUTION ORDER:
Step 01 of workflow 'automation/health-checks'

RELATED SCRIPTS:
02_pg_cron_recent_job_run_history.sql

HOW TO INTERPRET RESULTS:
An empty result set with pg_cron installed means the extension is available but nothing has been scheduled yet. Each row's schedule is a standard five-field cron expression evaluated in the database server's time zone; cross-reference command against the runbooks this workflow and growth-monitoring/xid-monitoring/index-monitoring/capacity-monitoring document to confirm a job actually matches what you expect it to run.
===============================================================================
*/

-- pg_cron presence check. This script never creates or schedules
-- anything -- it only detects whether pg_cron is already installed
-- in this database.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') AS pg_cron_available
\gset

\if :pg_cron_available
SELECT
    jobid,
    schedule,
    command,
    nodename,
    nodeport,
    database,
    username,
    active
FROM cron.job
ORDER BY jobid;
\else
SELECT 'pg_cron is not installed in this database, so no scheduled jobs are registered here. See the scheduling runbook in this workflow (script 04) for how to enable it via the Aurora cluster parameter group, or how to use an external scheduler instead if pg_cron is not appropriate for this cluster.' AS notice;
\endif
