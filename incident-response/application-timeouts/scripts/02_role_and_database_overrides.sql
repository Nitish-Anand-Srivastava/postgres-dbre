/*
===============================================================================
SCRIPT NAME:
02_role_and_database_overrides.sql

PURPOSE:
Shows the per-role and per-database setting overrides that explain why one service times out while another does not.

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
Step 02 of workflow 'incident-response/application-timeouts'

RELATED SCRIPTS:
03_session_outcome_counters.sql

HOW TO INTERPRET RESULTS:
This is where surprising timeout behaviour almost always hides. A role with statement_timeout set aggressively, or set to 0, explains an entire class of incident instantly -- and an override nobody remembers applying is a very common root cause after a role or credential change.
===============================================================================
*/

-- Role-level and database-level GUC overrides (pg_db_role_setting). This is
-- the settings layer pg_settings does NOT show you: pg_settings reports what
-- YOUR session resolved to, while this shows the per-role / per-database
-- ALTER ROLE ... SET and ALTER DATABASE ... SET overrides that apply to other
-- roles -- for example statement_timeout = 0 (no timeout) applied to a
-- reporting role, or statement_timeout = 2s applied to the trading API role.
--
-- During a timeout incident this answers "which timeout is the application
-- actually hitting" far faster than reading application configuration
-- repositories, and it frequently explains why one service times out while
-- another, running the same query, does not.
SELECT
    coalesce(r.rolname, '(all roles)')                           AS role_name,
    coalesce(d.datname, '(all databases)')                       AS database_name,
    s.setconfig                                                  AS applied_settings
FROM pg_db_role_setting s
LEFT JOIN pg_roles r ON r.oid = s.setrole
LEFT JOIN pg_database d ON d.oid = s.setdatabase
ORDER BY database_name, role_name;
