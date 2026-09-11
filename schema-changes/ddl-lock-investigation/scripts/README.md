# Scripts: DDL Lock Investigation

Execution order, safety classification, and expected runtime for every script
in `schema-changes/ddl-lock-investigation/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_ddl_lock_waits.sql` | DDL-mode lock holders and waiters. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_blocked_sessions_overview.sql` | All blocked sessions and their direct blockers. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_blocking_chain_detail.sql` | Expanded blocker detail per blocked session. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_lock_detail_by_mode.sql` | Raw lock detail by mode, ungranted requests first. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_long_running_and_idle_transactions.sql` | Long-running, idle-in-transaction, and prepared transactions. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_ddl_lock_remediation_runbook.md` | Guarded runbook: draining a DDL lock queue and retrying safely. | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) | Seconds for the cancellation; the retry depends on the underlying DDL. |

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

- The lock queue is blocking order placement, matching, or wallet operations -- this is a full trading incident and needs incident command, not just a DBA.
- The root blocker is a backend owned by a team that cannot be reached, and the outage is ongoing.
- The blocker is an anti-wraparound autovacuum, which must not be cancelled -- escalate to the transaction ID wraparound workflow, because that is the more serious underlying problem.
- Cancelling the DDL does not drain the queue, which indicates something beyond a simple lock queue and needs deeper investigation.
- The same DDL has caused a lock incident more than once -- stop retrying and fix the process that keeps issuing it without a lock timeout.

## Scripts That Should Not Be Run During Severe Incidents

- 06_ddl_lock_remediation_runbook.md -- Varies by step -- cancelling a waiting DDL is near-instant and low risk; terminating an application backend rolls back its transaction and may surface as an application error.
