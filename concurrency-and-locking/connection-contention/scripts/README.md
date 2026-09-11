# Scripts: Connection-Level Contention

Execution order, safety classification, and expected runtime for every script
in `concurrency-and-locking/connection-contention/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_client_and_ipc_wait_breakdown.sql` | Breaks down current wait events specifically for Client and IPC types to isolate connection-level (as opposed to lock/IO) contention. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_connection_headroom.sql` | Checks whether the database's own max_connections is the limiting factor, or whether it has headroom (pointing at an application/pooler-side limit instead). | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_connections_by_pool_identity.sql` | Breaks connections down by application_name/usename to identify which pool/service is consuming the most connection slots. | READ ONLY | Low (sub-second to a few seconds) |

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

- Root cause is clearly network/application-side -- hand off to SRE/application teams with the gathered evidence rather than continuing database-side tuning.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
