# Scripts: Safe Index Creation

Execution order, safety classification, and expected runtime for every script
in `schema-changes/safe-index-creation/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_existing_index_and_constraint_inventory.sql` | Existing indexes and constraints on the target table. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_target_table_size_and_state.sql` | Target table size, row estimates, and maintenance state. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_duplicate_index_check.sql` | Structurally duplicate indexes across the database. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_ddl_safety_settings.sql` | Timeout, memory, and parallelism settings for the build. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_safe_index_creation_runbook.md` | Guarded DDL runbook: index creation methods and their lock behavior. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Minutes to many hours, depending on table size and method -- the concurrent form typically takes 2-3x the plain form. |
| 06 | `06_post_build_validation.sql` | Post-build validity and in-progress build check. | READ ONLY | Low (sub-second to a few seconds) |

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

- The target table is on the live order-matching or wallet-balance path and a blocking build is being proposed -- this needs explicit sign-off, not a DBA decision.
- The estimated build duration exceeds the agreed window, or the table is large enough that the concurrent build will run for many hours across a market event.
- The table is partitioned with a large number of partitions, which turns one index build into hundreds and needs a coordinated plan.
- A previous build attempt failed and its cause is not understood -- resolve that through the failed-index-build workflow before retrying.

## Scripts That Should Not Be Run During Severe Incidents

- 05_safe_index_creation_runbook.md -- Varies by step -- read each step's own warning before executing it.
