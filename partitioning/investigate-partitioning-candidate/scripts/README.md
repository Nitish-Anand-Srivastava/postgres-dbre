# Scripts: Investigating a Partitioning Candidate

Execution order, safety classification, and expected runtime for every script
in `partitioning/investigate-partitioning-candidate/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_table_size_and_growth.sql` | Checks current size and row count for the candidate table as the baseline feasibility input. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_query_pattern_review.sql` | Surfaces the top statements touching the candidate table to assess whether a dominant filter column (candidate partition key) exists. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_constraint_and_fk_complexity.sql` | Inventories existing constraints and foreign keys referencing/referenced-by the candidate table, since these materially affect migration difficulty. | READ ONLY | Low (sub-second to a few seconds) |

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

- A confirmed candidate is business-critical (financial ledger) -- involve database engineering leadership before committing to the migration plan.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
