# Scripts: Daily Health Check

Execution order, safety classification, and expected runtime for every script
in `database-health/daily-health-check/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_current_activity_snapshot.sql` | Current backends grouped by state and wait event. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_connection_headroom.sql` | Connection utilization and per-application connection counts. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_transaction_and_idle_check.sql` | Oldest open transactions and idle-in-transaction sessions. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_vacuum_debt_check.sql` | Vacuum debt by table. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_xid_age_check.sql` | Per-database XID age vs wraparound thresholds. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_slowest_recurring_statements.sql` | Slowest frequently-executed statements (pg_stat_statements). | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_reader_lag_check.sql` | Aurora reader status and lag. | READ ONLY | Low (sub-second to a few seconds) |

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

- Connection utilization above 85%, or a jump of more than 20 percentage points versus yesterday.
- XID age above 50% of autovacuum_freeze_max_age, or any increase that would reach 100% before the next scheduled maintenance window.
- A transaction open longer than one hour, or any prepared transaction at all.
- Reader lag sustained above the application's read-your-own-write tolerance, since stale balance or order reads on an exchange generate support tickets and regulatory questions.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
