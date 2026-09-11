# Scripts: Production Triage -- Rapid Response Checklist

Execution order, safety classification, and expected runtime for every script
in `incident-response/production-triage/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_cluster_database_status.sql` | Writer/reader role and Aurora cluster-wide replica status. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_active_sessions.sql` | Session counts by database, state and wait-event type. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_wait_events.sql` | Wait-event distribution with built-in descriptions. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_blocking_locks.sql` | Blocked sessions with their blockers and what those blockers are doing. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_long_running_queries.sql` | Active queries above the runtime threshold, ranked by runtime. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_long_transactions.sql` | Open transactions ranked by age, active or idle. | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_connection_utilization.sql` | Connections by state plus headroom against max_connections. | READ ONLY | Low (sub-second to a few seconds) |
| 08 | `08_top_queries.sql` | Top statements by cumulative execution time. | READ ONLY | Low (sub-second to a few seconds) |
| 09 | `09_vacuum_autovacuum.sql` | Active vacuum workers plus tables ranked by dead tuples. | READ ONLY | Low (sub-second to a few seconds) |
| 10 | `10_storage_and_growth.sql` | Database sizes and the largest tables by total size. | READ ONLY | Low (sub-second to a few seconds) |

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

- The checklist cannot be completed because the database will not accept a connection -- escalate immediately and switch to the database-unavailable workflow and the disaster-recovery assessment in parallel.
- Script 01 shows a cluster role you did not expect (a writer that is now a reader) -- escalate on the failover track before interpreting anything else, because the topology changed underneath the incident.
- The checklist shows several independent anomaly classes at once -- treat it as a compound incident, declare a major incident, and assign a separate owner per track rather than working them sequentially.
- Order entry, deposits, withdrawals or settlement are affected -- escalate to treasury and compliance in parallel with the technical response, at the moment you know, not after resolution.
- All ten scripts are unremarkable while customer impact continues -- escalate outward to the application, platform and network teams; a clean database snapshot is strong evidence and should redirect the whole response.

## Scripts That Should Not Be Run During Severe Incidents

_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._
