/*
===============================================================================
SCRIPT NAME:
02_pg_cron_recent_job_run_history.sql

PURPOSE:
Checks whether pg_cron is installed and, if so, reports the most recent run outcome for every registered job.

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
Step 02 of workflow 'automation/health-checks'

RELATED SCRIPTS:
03_quick_health_signal.sql

HOW TO INTERPRET RESULTS:
A status of failed, or a return_message describing an error, means the schedule exists but the check is not actually running successfully -- this is worse than having no schedule at all, because it creates false confidence. Review failures immediately; a job that has failed on every run since it was created has never actually protected anything.
===============================================================================
*/

-- pg_cron presence check. This script never creates or schedules
-- anything -- it only detects whether pg_cron is already installed
-- in this database.
SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') AS pg_cron_available
\gset

\if :pg_cron_available
\set lookback_hours 72
SELECT
    r.jobid,
    j.schedule,
    r.status,
    r.return_message,
    r.start_time,
    r.end_time,
    r.end_time - r.start_time AS duration
FROM cron.job_run_details r
LEFT JOIN cron.job j ON j.jobid = r.jobid
WHERE r.start_time > now() - make_interval(hours => :lookback_hours)
ORDER BY r.start_time DESC;
\else
SELECT 'pg_cron is not installed in this database, so no job run history is available. See the scheduling runbook in this workflow (script 04) for how to enable it, or how to use an external scheduler instead.' AS notice;
\endif
