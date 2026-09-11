# Scripts: High Query/Transaction Latency

Execution order, safety classification, and expected runtime for every script
in `performance/high-latency/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_session_and_wait_overview.sql` | Broad session/state and wait-event snapshot to orient the investigation. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_statement_latency_trends.sql` | Statements with the highest mean execution time, called frequently enough to be a real trend rather than noise. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_lock_wait_check.sql` | Checks for blocked sessions as a latency amplifier that would not show up in a query's own plan. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_connection_headroom.sql` | Checks connection utilization, since pool exhaustion manifests to the application as latency (waiting for a connection) rather than a slow query. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_replication_lag_if_reader.sql` | If the affected traffic is reader-routed, checks Aurora replica lag via the cluster-native function. | READ ONLY | Low (sub-second to a few seconds) |

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

- No database-side signal found after completing this workflow -- hand off to application/network/SRE with the gathered evidence rather than continuing to search inside the database.
- Latency increase correlates with a specific reader instance -- escalate for potential instance-level AWS issue investigation.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
