# Scripts: Sudden Latency Spike

Execution order, safety classification, and expected runtime for every script
in `incident-response/sudden-latency-spike/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_activity_overview.sql` | Session counts by database, state and wait-event type. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_wait_event_mix.sql` | Wait-event distribution with the PG17 pg_wait_events descriptions. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_longest_active_queries.sql` | Active queries above the runtime threshold, ranked by runtime. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_blocking_snapshot.sql` | Sessions currently blocked, with their blocking pids. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_checkpoint_io_and_temp_pressure.sql` | Checkpoint, IO and temp-file pressure indicators in one snapshot. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_statement_timing_shift.sql` | Slowest statements by mean execution time from pg_stat_statements. | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_latency_mitigation_actions.md` | Guarded actions: clear blocking, cancel the dominant statement, shed load, time-box work. | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) | Seconds per statement. |

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

- Latency stays elevated for more than 15 minutes with customer-visible impact on the order or withdrawal path.
- The spike coincides with a deployment that cannot be rolled back without a data migration -- involve the deploying team and database engineering jointly, immediately.
- The dominant wait events are Aurora-internal (IO or IPC waits with no application-side explanation) -- open an AWS support case in parallel with continuing the investigation.
- Latency degradation is accompanied by rising replica lag on every reader, which suggests a writer-side saturation problem with cluster-wide reach.

## Scripts That Should Not Be Run During Severe Incidents

- 07_latency_mitigation_actions.md -- Cancelling a statement aborts that statement only; a role-level timeout change causes the affected service's long statements to fail fast by design.
