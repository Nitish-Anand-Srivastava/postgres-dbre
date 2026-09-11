# Scripts: Query Plan Regression

Execution order, safety classification, and expected runtime for every script
in `performance/query-regression/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_pgss_regression_candidates.sql` | Ranks statements by mean execution time and call volume to identify candidate regressions and quantify their current cost. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_invalid_or_missing_indexes.sql` | Checks for invalid indexes on the affected table(s), the single most common direct cause of a sudden plan regression. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_statistics_freshness.sql` | Checks whether recent ANALYZE activity coincides with the regression's onset, and how much the table has changed since. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_table_size_growth.sql` | Checks current table and index sizes to assess whether data growth alone could explain a plan flip (e.g. nested loop no longer viable). | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_sequential_scans.sql` | Confirms whether the regressed query's table(s) are now being scanned sequentially where an index scan would be expected. | READ ONLY | Low (sub-second to a few seconds) |

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

- Regression correlates with an Aurora engine minor-version upgrade -- escalate to AWS Support with the before/after EXPLAIN plans attached.
- No root cause identified after completing this workflow and the query is on a critical path -- escalate to database engineering leadership.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
