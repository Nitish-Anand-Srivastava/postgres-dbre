# Scripts: Adding a Column to a Large Table

Execution order, safety classification, and expected runtime for every script
in `schema-changes/add-column-large-table/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_target_table_size_and_state.sql` | Target table size and maintenance state. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_existing_column_inventory.sql` | Existing column definitions and fast-default usage. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_current_lock_activity.sql` | Lock waits and long-running transactions before execution. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_add_column_semantics_reference.md` | Rewrite classification for every ADD COLUMN form. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Not applicable -- reference document. |
| 05 | `05_add_column_execution_runbook.md` | Guarded DDL runbook: adding a column without a rewrite. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Milliseconds for the DDL steps; hours to days for an online backfill on a very large table. |
| 06 | `06_post_change_verification.sql` | Post-change column definition and fast-default verification. | READ ONLY | Low (sub-second to a few seconds) |

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

- The proposed statement requires a rewrite on a table on the live trading path and the owning team is pushing to run it as-is.
- The column is a financial field whose default value affects settlement or reconciliation logic -- that needs compliance review, not just a DBA.
- The table is partitioned with a large number of partitions, making even the fast form a wide lock footprint.
- An earlier `ADD COLUMN` on this table caused an incident whose cause was never established -- resolve that before adding another.

## Scripts That Should Not Be Run During Severe Incidents

- 04_add_column_semantics_reference.md -- None by itself -- this is a reference document. The statements it classifies have the impacts described per row.
- 05_add_column_execution_runbook.md -- Varies by step -- read each step's own warning before executing it.
