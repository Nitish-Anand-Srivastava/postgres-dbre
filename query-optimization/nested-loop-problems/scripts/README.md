# Scripts: Nested Loop Join Problems

Execution order, safety classification, and expected runtime for every script
in `query-optimization/nested-loop-problems/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_high_block_access_per_row.sql` | Statements with extreme block-access-per-row ratios. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_sequential_scan_pressure.sql` | Tables under heavy sequential scan pressure. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_foreign_keys_missing_index.sql` | Foreign keys lacking a supporting index. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_statistics_freshness.sql` | Statistics freshness for the joined tables. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_join_strategy_settings.sql` | Join strategy and caching configuration. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_confirm_nested_loop_safely.md` | Guarded runbook for confirming and remediating a runaway nested loop. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Step 1: milliseconds. Steps 2 and 3: up to the configured statement_timeout. |

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

- A runaway nested loop is currently saturating the writer and the owning team cannot stop issuing the statement -- escalate as an active incident.
- The fix requires a new index on a hot exchange table -- escalate to schema-changes for a safe concurrent rollout.
- Correct statistics and correct indexes still produce the loop, meaning the query shape itself must change -- escalate to the application team with the plan evidence.

## Scripts That Should Not Be Run During Severe Incidents

- 06_confirm_nested_loop_safely.md -- Step 1: none. Step 2: a full execution of the statement under investigation, bounded by statement_timeout. Step 3: the same, plus a session-scoped planner change confined to one transaction.
