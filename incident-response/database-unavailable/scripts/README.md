# Scripts: Database Unavailable

Execution order, safety classification, and expected runtime for every script
in `incident-response/database-unavailable/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_instance_identity_and_uptime.sql` | Proves reachability and identifies the answering instance, its role and uptime. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_cluster_role_and_replica_status.sql` | Writer/reader role plus Aurora cluster-wide replica status and lag. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_connection_slot_saturation.sql` | Connection headroom against max_connections, broken down by state. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_session_outcome_counters.sql` | Abandoned / fatal / killed session counters per database. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_blocked_and_stuck_sessions.sql` | Blocked-session pileup plus the oldest open transactions. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_availability_mitigation_actions.md` | Guarded actions: reclaim slots, end a paralysing session, pooler restart, failover decision. | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) | Seconds per statement, though a terminated transaction can take minutes to finish rolling back. |

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

- You cannot connect at all from a known-good direct path -- escalate immediately to AWS support and database engineering leadership, and start the disaster-recovery assessment in parallel.
- The instance restarted with no explanation in the cluster events -- escalate to database engineering, because an unexplained restart tends to recur.
- Deposits or withdrawals have been failing for more than a few minutes -- escalate to the treasury and compliance on-call in parallel with the technical fix, because customer-funds visibility carries its own reporting obligations.
- Restoring access requires a failover or an instance-class change beyond on-call authority.

## Scripts That Should Not Be Run During Severe Incidents

- 06_availability_mitigation_actions.md -- Varies by action: ending an idle session drops one pooled connection; terminating an active session rolls its transaction back; a pooler restart or a failover causes a short, deliberate outage window.
