/*
===============================================================================
SCRIPT NAME:
07_key_monitoring_settings.sql

PURPOSE:
Reports the runtime value of a curated set of parameters that most
investigation workflows in this repository implicitly depend on (e.g.
whether pg_stat_statements is preloaded, statement/idle-in-transaction
timeouts, autovacuum concurrency), so gaps are visible before they cause a
confusing "empty result set" during an actual incident.

AURORA POSTGRESQL VERSION:
17+

EXECUTION LOCATION:
Any instance (writer or reader) -- some of these parameters (notably
shared_preload_libraries) are cluster-parameter-group-controlled and will
be identical across instances; others (e.g. statement_timeout) can be
overridden per instance parameter group or per session/role.

SAFETY:
READ ONLY

EXPECTED IMPACT:
None -- reads pg_settings only.

REQUIRED PRIVILEGES:
None beyond CONNECT for most rows returned. Membership in pg_monitor / 
pg_read_all_settings ensures parameters that are otherwise hidden from
non-privileged roles are visible rather than returning NULL.

PREREQUISITES:
None.

EXECUTION ORDER:
Step 07 of common/scripts

RELATED SCRIPTS:
03_installed_extensions.sql

HOW TO INTERPRET RESULTS:
If `shared_preload_libraries` does not include `pg_stat_statements`,
scripts depending on it will fail with "relation pg_stat_statements does
not exist" even after `CREATE EXTENSION` -- the library must be preloaded
via the cluster parameter group (requires a reboot) before the extension
can function. `context = 'postmaster'` means a change requires a full
instance restart; `context = 'sighup'` means a reload is sufficient;
`context = 'user'` means it can be changed per-session. Compare
`statement_timeout` and `idle_in_transaction_session_timeout` against
your application's expectations -- `0` means "no timeout," which is a
common contributor to long-running/idle-in-transaction incidents on
latency-sensitive OLTP workloads.
===============================================================================
*/

SELECT
    name                                          AS setting_name,
    setting                                       AS current_value,
    unit                                           AS unit,
    context                                        AS change_requires,
    source                                         AS value_source
FROM pg_settings
WHERE name IN (
    'shared_preload_libraries',
    'track_activity_query_size',
    'track_io_timing',
    'log_min_duration_statement',
    'log_lock_waits',
    'deadlock_timeout',
    'statement_timeout',
    'idle_in_transaction_session_timeout',
    'max_connections',
    'autovacuum',
    'autovacuum_max_workers',
    'autovacuum_naptime'
)
ORDER BY name;
