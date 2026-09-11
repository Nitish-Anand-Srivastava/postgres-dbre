# Scripts: Failed Index Build Cleanup

Execution order, safety classification, and expected runtime for every script
in `schema-changes/failed-index-build/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_invalid_indexes.sql` | INVALID indexes and the storage they waste. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_builds_currently_running.sql` | Index builds currently in progress (safety gate before any drop). | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_failure_context_and_settings.sql` | Timeout settings and lock context explaining the failure. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_cleanup_invalid_index_runbook.md` | Guarded DDL runbook: removing an INVALID index safely. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Seconds to a few minutes for the drop; the optional vacuum can take much longer on a large table. |
| 05 | `05_verify_cleanup.sql` | Post-cleanup verification and index inventory. | READ ONLY | Low (sub-second to a few seconds) |

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

- The build failed because of a duplicate key violation on a unique index -- that is a data-integrity finding and needs the owning team before any retry.
- The same build has now failed three or more times for reasons that are not understood -- stop retrying and investigate the root cause properly.
- INVALID indexes are appearing without anyone having run a build, which suggests repeated failovers or instance instability and needs an AWS support case.
- The leftover is on a table where the write overhead is measurably affecting the trading path and the owning team is not available to authorize the drop.

## Scripts That Should Not Be Run During Severe Incidents

- 04_cleanup_invalid_index_runbook.md -- Varies by step -- read each step's own warning before executing it.
