# Scripts: Table Bloat

Execution order, safety classification, and expected runtime for every script
in `vacuum-and-autovacuum/table-bloat/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_bloat_estimate_catalog_only.sql` | Lightweight, lock-free bloat proxy using only pg_class/pg_stat_all_tables -- always safe to run. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_exact_bloat_pgstattuple.sql` | Exact physical bloat scan for one specific table using the pgstattuple extension. | READ ONLY (may be resource intensive on very large tables -- see EXPECTED IMPACT) | Low (sub-second to a few seconds) |

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

- Bloat is confirmed severe (free_pct from pgstattuple well above 30-40%) on a business-critical table -- escalate to schedule a maintenance-window remediation with stakeholder sign-off.

## Scripts That Should Not Be Run During Severe Incidents

- 02_exact_bloat_pgstattuple.sql -- Performs a full table scan (or sampled scan for pgstattuple_approx) and takes a light read lock; can be I/O-intensive on very large tables.
