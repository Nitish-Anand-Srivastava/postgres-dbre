# Scripts: Performance Degradation After Failover

Execution order, safety classification, and expected runtime for every script
in `performance/performance-after-failover/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_confirm_recovery_role_and_uptime.sql` | Confirms this instance's current writer/reader role and how recently it started, to verify a failover occurred. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_cache_warmup_progress.sql` | Tracks buffer cache hit ratio to quantify and monitor cold-cache recovery progress. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_reconnect_storm_check.sql` | Checks current connection count/composition for a reconnect storm compounding the cache warm-up effect. | READ ONLY | Low (sub-second to a few seconds) |

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

- Cache hit ratio and latency do not show any recovery trend after 15-20 minutes -- escalate as a distinct incident rather than continuing to assume normal warm-up.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
