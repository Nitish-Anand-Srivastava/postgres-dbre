# Scripts: Purging Old Data (Non-Archived Deletion)

Execution order, safety classification, and expected runtime for every script
in `archival-and-data-lifecycle/purge-old-data/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_ephemeral_table_growth_check.sql` | Checks size and age distribution for a candidate ephemeral/expiring table. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_batched_purge.md` | Batched purge template for confirmed-ephemeral data with no retention requirement. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Variable -- depends on table size and chosen batch size; see runbook. |

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

- Uncertainty about whether the data actually requires retention -- escalate to compliance before purging; when in doubt, do not purge.

## Scripts That Should Not Be Run During Severe Incidents

- 02_batched_purge.md -- Varies by step -- read each step's own warning before executing it.
