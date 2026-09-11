# Scripts: Post-Deployment Incident

Execution order, safety classification, and expected runtime for every script
in `incident-response/post-deployment-incident/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_workload_by_application_and_session_age.sql` | Workload by application and user, including session establishment times. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_migration_lock_waits.sql` | DDL-strength lock waits plus the sessions queued behind them. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_index_build_state.sql` | Index build progress plus invalid indexes from failed builds. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_new_query_shapes.sql` | Top statements by call count, to spot newly introduced query shapes. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_statistics_and_scan_regression.sql` | Statistics staleness plus sequential-scan-heavy tables. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_rollback_decision_runbook.md` | Rollback decision criteria plus guarded actions: cancel a migration, roll back, fix forward, clean up. | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) | Seconds to cancel; a concurrent index drop takes proportionally longer on a large table. |

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

- A migration is half-applied on a financial table -- escalate to database engineering leadership and treasury immediately; do not attempt to complete or reverse it unilaterally.
- Rollback is blocked by an applied non-reversible migration while customer impact continues -- this requires a joint decision between database engineering and the deploying team, with a named decision owner.
- The incident affects deposits, withdrawals or settlement -- involve compliance from the start, not after resolution.
- The deployment cannot be correlated with any database-side change yet impact continues -- broaden the investigation rather than continuing to focus on the release.

## Scripts That Should Not Be Run During Severe Incidents

- 06_rollback_decision_runbook.md -- Cancelling a waiting migration rolls that DDL back cleanly with no data change. Rollback and index cleanup are change-managed operations with their own, separately documented impact.
