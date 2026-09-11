# Scripts: DDL on a Large Production Table

Execution order, safety classification, and expected runtime for every script
in `schema-changes/large-table-ddl/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_target_table_size_and_state.sql` | Target table size, row estimates, and maintenance state. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_dependent_objects_inventory.sql` | Indexes, constraints, foreign keys, views, and triggers depending on the table. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_current_lock_activity.sql` | Current DDL lock waits and full lock detail. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_long_running_transactions.sql` | Long-running and idle-in-transaction sessions blocking DDL. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_lock_level_and_rewrite_reference.md` | Lock level and rewrite classification for common ALTER TABLE variants. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Not applicable -- reference document. |
| 06 | `06_large_table_ddl_execution_runbook.md` | Guarded DDL runbook: safe execution patterns for large-table schema changes. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Milliseconds for pattern 1; minutes to hours for pattern 2's validation; days for a pattern 3 migration. |

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

- The change requires a full table rewrite on a table on the live trading path -- this needs a migration design, not a single statement, and should go through the partitioning or archival migration patterns.
- An `ALTER TABLE` has already caused an application stall and the cause is not fully understood -- stop and investigate through ddl-lock-investigation before retrying.
- The table has incoming foreign keys from tables owned by other teams that must be coordinated with.
- The estimated rewrite duration exceeds any window the business is willing to accept, meaning the approach itself must change.

## Scripts That Should Not Be Run During Severe Incidents

- 05_lock_level_and_rewrite_reference.md -- None by itself -- this is a reference document. The statements it classifies have the impacts described per row.
- 06_large_table_ddl_execution_runbook.md -- Varies by step -- read each step's own warning before executing it.
