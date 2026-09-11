# Scripts: High CPU -- First Response Checklist

Execution order, safety classification, and expected runtime for every script
in `incident-response/high-cpu/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_session_load_snapshot.sql` | Session counts by state, with the longest query and transaction runtimes. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_cpu_versus_wait_breakdown.sql` | Wait-event mix, distinguishing runnable work from waiting work. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_top_active_queries_now.sql` | Currently active queries above the runtime threshold. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_top_statements_by_total_time.sql` | Top statements by cumulative execution time. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_maintenance_competing_for_cpu.sql` | Running vacuum workers plus the tables with the most dead tuples. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_cpu_mitigation_actions.md` | Guarded actions: cancel dominant sessions, stop a retry storm, defer maintenance, scale. | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) | Seconds per statement. |

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

- CPU remains above 90% for more than 15 minutes despite mitigation, with customer-visible impact.
- The cause is a retry storm from an upstream service -- escalate to that team immediately; this cannot be fixed from inside the database.
- The workload is legitimate and the instance class is simply undersized -- a scaling decision is required beyond on-call authority.
- Both the writer and every reader are saturated simultaneously, which points at a cluster-wide or storage-layer problem worth an AWS support case.

## Scripts That Should Not Be Run During Severe Incidents

- 06_cpu_mitigation_actions.md -- Cancelling aborts the target statement only. A role-level timeout makes that role's long statements fail fast by design. Scaling a writer requires a failover window.
