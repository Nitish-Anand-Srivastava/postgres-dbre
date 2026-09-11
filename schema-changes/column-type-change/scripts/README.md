# Scripts: Changing a Column Type on a Production Table

Execution order, safety classification, and expected runtime for every script
in `schema-changes/column-type-change/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_column_definition_inventory.sql` | Exact column definitions for the target table. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_dependent_objects_inventory.sql` | Objects depending on the target table. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_target_table_size.sql` | Target table size for rewrite duration estimation. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_type_change_rewrite_reference.md` | Rewrite classification for type changes, plus the metadata-only runbook. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Milliseconds for a metadata-only change. |
| 05 | `05_online_column_type_change_runbook.md` | Guarded DDL runbook: online column type change via add-and-swap. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Days for the online backfill on a very large table; milliseconds for the final swap. |
| 06 | `06_post_change_verification.sql` | Post-change column type and index validity verification. | READ ONLY | Low (sub-second to a few seconds) |

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

- An integer column is within weeks of its ceiling on a table on the trading path -- this is a pending outage and needs immediate prioritization above normal work.
- The change is to a financial amount or price column where precision or scale is affected -- compliance and settlement must sign off before execution.
- Incoming foreign keys from tables owned by other teams must change type in lockstep -- that coordination is the critical path and needs engineering leadership.
- The online pattern's validation step shows any row count or checksum mismatch -- halt immediately and do not cut over with unvalidated financial data.

## Scripts That Should Not Be Run During Severe Incidents

- 04_type_change_rewrite_reference.md -- Varies by step -- read each step's own warning before executing it.
- 05_online_column_type_change_runbook.md -- Varies by step -- read each step's own warning before executing it.
