# Scripts: Lock Storm

Execution order, safety classification, and expected runtime for every script
in `incident-response/lock-storm/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_lock_wait_scale.sql` | Scale of lock waiting across the instance, by wait event and state. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_blocked_sessions.sql` | Every blocked session with its blocking pids and wait duration. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_root_blockers_by_blast_radius.sql` | Blockers ranked by how many sessions they block, flagging true roots. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_lock_detail_at_the_root.sql` | Raw lock detail by relation and mode, granted and waiting. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_ddl_and_old_transactions.sql` | DDL-strength lock waits plus the oldest open transactions. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_clear_the_root_blocker.md` | Guarded actions: cancel a waiting DDL, cancel or terminate the root blocker, verify the graph drained. | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) | Seconds to act; a terminated long transaction may take minutes to roll back. |

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

- The root blocker is a system or replication process rather than an application backend -- escalate to database engineering and do not signal it.
- The chain does not clear after the identified root is resolved, which means a second root exists and the graph needs re-reading rather than more terminations.
- The blocker is a settlement, withdrawal or reconciliation transaction whose rollback has financial consequences -- escalate to treasury and compliance before acting, even if that means the storm runs longer.
- Storms on the same relation recur more than once in a week -- escalate as a structural data-model issue rather than continuing to treat each occurrence as an incident.

## Scripts That Should Not Be Run During Severe Incidents

- 06_clear_the_root_blocker.md -- A cancel aborts the blocker's current statement. A terminate rolls back its entire transaction. Both release the locks the storm is queued on.
