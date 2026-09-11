# Scripts: Concurrent Index Build

Execution order, safety classification, and expected runtime for every script
in `schema-changes/concurrent-index-build/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_preflight_blocking_transactions.sql` | Transactions that would stall a concurrent build. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_target_table_and_settings.sql` | Target table size plus timeout and memory settings. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_concurrent_index_build_runbook.md` | Guarded DDL runbook: running a concurrent index build. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Typically 2-3x a plain index build; hours on a multi-hundred-GB exchange table. |
| 04 | `04_monitor_build_progress.sql` | Live index build progress and phase. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_blocking_sessions_during_build.sql` | Blockers stalling the build, and the lock queue behind it. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_post_build_validity_check.sql` | Post-build validity and full index inventory. | READ ONLY | Low (sub-second to a few seconds) |

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

- The build is stalled on a backend owned by a team that cannot be reached, and the stall is now blocking autovacuum on a high-write table.
- Reader lag caused by the build is affecting customer-facing reads -- treat as an incident and cancel the build.
- The build has failed more than once for reasons that are not understood -- stop retrying and investigate properly through failed-index-build.
- An Aurora failover occurred mid-build; confirm the state of the index on the new writer before any retry.

## Scripts That Should Not Be Run During Severe Incidents

- 03_concurrent_index_build_runbook.md -- Varies by step -- read each step's own warning before executing it.
