# Scripts: Inefficient Index Usage

Execution order, safety classification, and expected runtime for every script
in `query-optimization/inefficient-index-usage/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_index_inventory_and_usage.sql` | Index size and usage inventory. | READ ONLY | Low to moderate (seconds; scales with the number of indexes). |
| 02 | `02_unused_index_candidates.sql` | Candidate unused indexes. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_duplicate_indexes.sql` | Structurally duplicate indexes. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_index_scan_efficiency.sql` | Index scan efficiency (entries read versus rows fetched). | READ ONLY | Low to moderate (seconds). |
| 05 | `05_sequential_scan_cross_check.sql` | Sequential scan pressure and invalid indexes. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_validate_index_change_safely.md` | Guarded runbook for validating an index addition or removal. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Minutes to hours for a concurrent build on a large exchange table. |

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

- A proposed index change affects orders, trades, wallets, or ledger_entries -- escalate for review, because the write-path impact is felt by every trade.
- An index appears unused on the writer but the reporting team cannot confirm it is unused on the readers.
- Index storage growth is a material component of the cluster's storage trend -- escalate into the capacity conversation rather than handling it as a local tuning task.

## Scripts That Should Not Be Run During Severe Incidents

- 06_validate_index_change_safely.md -- CREATE INDEX CONCURRENTLY and DROP INDEX CONCURRENTLY take SHARE UPDATE EXCLUSIVE rather than ACCESS EXCLUSIVE, so reads and writes continue, but the build is I/O intensive, takes roughly twice as long as a plain build, and conflicts with vacuum and other DDL on the same table.
