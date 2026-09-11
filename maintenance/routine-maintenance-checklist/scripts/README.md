# Scripts: Routine Maintenance Checklist

Execution order, safety classification, and expected runtime for every script
in `maintenance/routine-maintenance-checklist/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_dead_tuples_and_autovacuum_activity.sql` | Ranks tables by dead-tuple volume and shows currently active autovacuum workers, the first stop for the vacuum-health portion of the checklist. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_index_bloat_and_usage.sql` | Surfaces index size, scan counts, and last-used timestamps to catch both bloated and simply-unused indexes as part of the routine review. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_statistics_freshness.sql` | Checks how stale planner statistics are across tables, since this checklist is often the first place staleness is noticed before it causes a plan regression. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_extension_and_key_settings_inventory.sql` | Snapshots installed extension versions and the settings most likely to drift or matter operationally, to catch unexpected configuration/version drift between checklist runs. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_routine_maintenance_checklist.md` | The checklist itself: the ordered list of checks to run each cycle, what to do with each finding, and the cadence this workflow is intended to run on. | DOCUMENTATION -- no SQL executed by this file itself | Variable -- depends on table size and chosen batch size; see runbook. |

## Execution Order

Run scripts strictly in the numeric order shown above. Each script assumes the
operator has reviewed the output of the prior step. Do not skip ahead to a
remediation template (`.md` files, if present) without completing the
read-only investigation steps first.

## Required Permissions

Unless a script states otherwise in its `REQUIRED PRIVILEGES` header field, a
role with the built-in `pg_monitor` (or `pg_read_all_stats` /
`pg_read_all_settings`) attribute, `CONNECT` on the target database, and
`USAGE` on `public` is sufficient. Scripts that read `pg_stat_statements`
require that extension to be installed in the current database. Scripts that
touch DDL, `pg_terminate_backend()`, or write operations state elevated
requirements explicitly in their own header.

## Expected Output

Every script returns a result set intended to be read directly in `psql` (or
any SQL client). Columns are named for direct interpretation; each script's
header contains a `HOW TO INTERPRET RESULTS` section, and the parent
`README.md` section 8 ("Interpretation Guide") gives workflow-level guidance.

## When to Stop and Escalate

- A trend line across multiple checklist runs shows a metric worsening toward a known danger threshold (e.g. dead-tuple ratio, transaction ID age) with no corrective action yet taken -- escalate before it becomes an active incident.

## Scripts That Should Not Be Run During Severe Incidents

- 05_routine_maintenance_checklist.md -- None from this file directly; hand-off workflows carry their own impact.
