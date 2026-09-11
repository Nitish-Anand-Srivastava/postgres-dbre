# Scripts: Connection Exhaustion -- First Response Checklist

Execution order, safety classification, and expected runtime for every script
in `incident-response/connection-exhaustion/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_connection_headroom.sql` | Current connection count against max_connections and reserved slots. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_connections_by_state.sql` | Connection counts by database and state, with percent of max_connections. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_connections_by_application.sql` | Connection counts by application_name, user and state. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_long_idle_sessions.sql` | Plain idle sessions ranked by how long they have been idle. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_idle_in_transaction_sessions.sql` | Idle-in-transaction sessions, plus any of them that are blocking others. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_reclaim_connection_slots.md` | Guarded actions: reclaim idle slots, reclaim idle-in-transaction slots, apply a role connection limit. | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) | Seconds per statement. |

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

- You cannot obtain a connection at all, even through the reserved break-glass path -- escalate to AWS support immediately.
- Slots refill to the ceiling within seconds of every reclaim and the owning service cannot or will not reduce its pool -- escalate to that service's leadership; this is now an organizational decision, not a database one.
- The exhaustion is a symptom of database slowness rather than leakage, and the slowness is unresolved -- escalate on the latency track instead.
- Withdrawal or settlement processors have been unable to connect for more than a few minutes -- escalate to treasury and compliance in parallel.

## Scripts That Should Not Be Run During Severe Incidents

- 06_reclaim_connection_slots.md -- Terminating an idle session drops one pooled connection. Terminating an idle-in-transaction session additionally rolls back its open transaction. A role connection limit causes new connections above the limit to be refused by design.
