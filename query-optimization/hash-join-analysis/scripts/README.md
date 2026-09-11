# Scripts: Hash Join Analysis

Execution order, safety classification, and expected runtime for every script
in `query-optimization/hash-join-analysis/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_statements_writing_temp_files.sql` | Statements writing the most temporary blocks. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_cluster_temp_file_trend.sql` | Cluster-wide temp file volume per database. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_memory_and_spill_settings.sql` | Memory and spill-related configuration. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_statistics_freshness_on_join_inputs.sql` | Statistics freshness on the join inputs. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_test_memory_hypothesis_safely.md` | Guarded runbook for confirming a hash spill and sizing work_mem. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Step 1: milliseconds. Steps 2 and 3: up to the configured statement_timeout. |

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

- Local instance storage is close to exhaustion because of concurrent temporary file usage -- escalate immediately, as this fails queries outright rather than merely slowing them.
- A reporting query with a compliance or settlement deadline cannot be made to complete within its window even with a reasonable memory allocation.
- The join is genuinely too large for any sane work_mem, meaning the data model or the report definition has to change -- escalate to engineering rather than continuing to tune.

## Scripts That Should Not Be Run During Severe Incidents

- 05_test_memory_hypothesis_safely.md -- Step 1: none. Steps 2 and 3: a full execution of the statement, plus the temporary file and memory footprint it implies. A mis-sized work_mem test on a busy writer can itself cause memory pressure.
