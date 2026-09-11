# Scripts: Sort Spills to Disk

Execution order, safety classification, and expected runtime for every script
in `query-optimization/sort-spills/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_statements_spilling_to_disk.sql` | Statements writing the most temporary blocks. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_temp_file_volume_trend.sql` | Cluster-wide temp file volume trend. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_sort_memory_settings.sql` | Sort memory and temp file logging configuration. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_ordering_index_coverage.sql` | Index coverage for the required ordering. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_size_sort_memory_safely.md` | Guarded runbook for confirming a sort spill and sizing the fix. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Step 1: milliseconds. Steps 2 and 3: up to the configured statement_timeout. |

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

- Local instance storage is close to exhaustion from concurrent temporary files -- this fails queries outright and must be escalated immediately.
- A settlement, reconciliation, or regulatory export cannot complete within its window even with a reasonable memory allocation.
- The sort is inherent to the query shape (deep pagination, an unbounded export) and needs an application-side change rather than database tuning.

## Scripts That Should Not Be Run During Severe Incidents

- 05_size_sort_memory_safely.md -- Step 1: none. Steps 2 and 3: a full execution of the statement, including its temporary file I/O. A large work_mem test on a busy instance contributes real memory pressure for the duration.
