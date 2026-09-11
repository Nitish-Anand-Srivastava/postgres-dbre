# Scripts: Application Timeouts

Execution order, safety classification, and expected runtime for every script
in `incident-response/application-timeouts/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_effective_timeout_settings.sql` | Effective values of the timeout and concurrency settings. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_role_and_database_overrides.sql` | Role-level and database-level GUC overrides from pg_db_role_setting. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_session_outcome_counters.sql` | Abandoned, fatal and killed session counters plus rollback ratio. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_blocking_and_waits.sql` | Blocked sessions plus the current wait-event distribution. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_connection_headroom.sql` | Connection headroom plus per-application connection attribution. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_timeout_mitigation_actions.md` | Guarded actions: adjust role timeouts, add lock_timeout, cap retries, decide funds-flow semantics. | ELEVATED RISK -- MANUAL EXECUTION ONLY, CHANGES CONFIGURATION THAT AFFECTS LIVE PRODUCTION TRAFFIC (read every warning in this file first) | Seconds; behavioural change appears as pooled sessions are recycled. |

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

- Timeouts affect funds-movement flows (deposits, withdrawals, settlement) -- escalate to treasury and compliance immediately, because the failure mode determines whether funds are stranded or at risk of double-processing.
- The application cannot distinguish pool-acquisition timeouts from statement timeouts, so the investigation cannot be completed from the database side -- escalate to the owning service to add that instrumentation.
- Server-side execution times are healthy but end-to-end latency is not, which points at the network or pooler -- escalate to the platform team.
- A timeout change is requested on a role used by settlement or reconciliation -- that requires named approval, not an on-call judgement call.

## Scripts That Should Not Be Run During Severe Incidents

- 06_timeout_mitigation_actions.md -- Role-level timeout changes alter how the affected service's statements fail, for new sessions only. No data is modified by any statement in this file.
