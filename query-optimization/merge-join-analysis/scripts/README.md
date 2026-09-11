# Scripts: Merge Join Analysis

Execution order, safety classification, and expected runtime for every script
in `query-optimization/merge-join-analysis/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_sort_and_temp_heavy_statements.sql` | Statements with heavy temporary block usage. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_join_key_index_coverage.sql` | Index inventory and definitions for the join table. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_join_column_correlation.sql` | Column statistics and physical correlation for the join columns. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_sort_and_join_settings.sql` | Merge join, sort, and I/O cost configuration. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_inspect_merge_join_plan.md` | Guarded runbook for reading and remediating a merge join plan. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Step 1: milliseconds. Steps 2 and 4: up to the configured statement_timeout. |

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

- The required index would be large enough to materially affect write latency on a hot exchange table -- escalate for a cost/benefit decision rather than adding it unilaterally.
- The join cannot avoid sorting and the sorts cannot fit in a reasonable work_mem, meaning the data model or the job design must change.
- A settlement or reconciliation job is missing its processing window as a direct result -- escalate with the operational deadline made explicit.

## Scripts That Should Not Be Run During Severe Incidents

- 05_inspect_merge_join_plan.md -- Step 1: none. Steps 2 and 4: a full execution of the statement, including any temporary file usage its sorts require.
