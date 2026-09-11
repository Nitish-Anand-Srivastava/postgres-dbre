# Scripts: Cardinality Estimation Errors

Execution order, safety classification, and expected runtime for every script
in `query-optimization/cardinality-estimation/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_statistics_freshness.sql` | Statistics freshness across tables. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_column_distribution_statistics.sql` | Per-column distribution statistics for one table. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_statistics_targets.sql` | Per-column statistics targets vs the cluster default. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_extended_statistics_inventory.sql` | Extended statistics inventory and candidate tables. | READ ONLY | Low to moderate (the candidate query aggregates pg_stats across the database). |
| 05 | `05_confirm_estimate_error.md` | Guarded runbook for measuring and correcting estimation errors. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Steps 1 and 3 (ALTER/CREATE): seconds. Step 2 and ANALYZE: minutes on a large table. |

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

- Statistics are fresh, targets are adequate, extended statistics exist, and the estimate is still wrong by orders of magnitude -- this is a genuinely hard estimation case that needs engineering input on query shape.
- The estimation error affects a settlement, reconciliation, or compliance query with a deadline.
- Correcting the estimate requires an ANALYZE on a table large enough that its I/O cost needs a maintenance window.

## Scripts That Should Not Be Run During Severe Incidents

- 05_confirm_estimate_error.md -- Step 1: none. Step 2: a full execution of the statement. Step 3: ANALYZE reads a sample of the table and takes a SHARE UPDATE EXCLUSIVE lock; ALTER TABLE ... SET STATISTICS takes a brief ACCESS EXCLUSIVE lock; CREATE STATISTICS is catalog-only but makes every subsequent ANALYZE of that table do more work.
