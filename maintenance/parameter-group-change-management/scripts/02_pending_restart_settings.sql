/*
===============================================================================
SCRIPT NAME:
02_pending_restart_settings.sql

PURPOSE:
Lists every setting currently flagged as changed-in-the-parameter-group-but-not-yet-applied, the direct signal that a reboot (or failover) is needed to finish a previously started change.

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
Step 02 of workflow 'maintenance/parameter-group-change-management'

RELATED SCRIPTS:
03_parameter_group_change_runbook.md

HOW TO INTERPRET RESULTS:
Any row here means that setting's parameter-group value has already been changed but this specific instance has not yet rebooted to pick it up -- schedule the reboot deliberately (see the runbook) rather than leaving the cluster in a half-applied state indefinitely.
===============================================================================
*/

-- Settings where pending_restart = true: the parameter group's stored value
-- differs from the value this running instance is actually using. This is
-- the definitive way to confirm a parameter-group change is only half
-- applied, rather than inferring it from the AWS Console alone.
SELECT
    name,
    setting                                                     AS currently_running_value,
    unit,
    context,
    pending_restart
FROM pg_settings
WHERE pending_restart = true
ORDER BY name;
