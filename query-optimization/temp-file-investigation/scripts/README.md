# Scripts: Temporary File Investigation

Execution order, safety classification, and expected runtime for every script
in `query-optimization/temp-file-investigation/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_temp_file_volume_by_database.sql` | Temp file volume and rate per database. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_statements_producing_temp_files.sql` | Statements attributed with temporary file usage. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_sessions_spilling_now.sql` | Sessions currently performing temporary file I/O. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_memory_and_logging_settings.sql` | Memory budget, temp file limit, and logging configuration. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_correlate_and_reproduce_safely.md` | Guarded runbook for log correlation and safe spill reproduction. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Step 3: up to the configured statement_timeout. The other steps are immediate. |

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

- Local instance storage is close to exhaustion -- escalate immediately, because the failure mode is query errors rather than slow queries.
- Temporary file volume rose sharply with no identifiable statement and no deployment to explain it.
- The spilling workload cannot be moved off the writer and cannot be given more memory safely -- escalate for a topology or instance-class decision.

## Scripts That Should Not Be Run During Severe Incidents

- 05_correlate_and_reproduce_safely.md -- Steps 1 and 2: no database impact (a parameter change and log reading). Step 3: a full execution of the statement including its temporary file I/O. Step 4: changes the default settings for new sessions of the named role.
