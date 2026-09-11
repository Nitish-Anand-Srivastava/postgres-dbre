# Scripts: Scheduling Routine Health Checks

Execution order, safety classification, and expected runtime for every script
in `automation/health-checks/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_pg_cron_extension_and_jobs.sql` | Registered pg_cron jobs, if the extension is installed. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_pg_cron_recent_job_run_history.sql` | Recent pg_cron job run outcomes, if the extension is installed. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_scheduling_runbook.md` | Scheduling runbook for database-health workflows (pg_cron or external scheduler). | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |

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

- A scheduled health check has been silently failing (per script 02) for long enough that its findings could not have been acted on -- treat any finding from the next successful run with extra scrutiny and review why the failures went unnoticed.

## Scripts That Should Not Be Run During Severe Incidents

- 03_scheduling_runbook.md -- Varies by step -- read each step's own warning before executing it.
