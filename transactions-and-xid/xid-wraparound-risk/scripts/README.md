# Scripts: Transaction ID (XID) Wraparound Risk

Execution order, safety classification, and expected runtime for every script
in `transactions-and-xid/xid-wraparound-risk/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_database_transaction_age.sql` | Database-level XID age against datfrozenxid -- the single highest-priority check in this entire workflow. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_table_transaction_age.sql` | Ranks ordinary tables, TOAST tables, and materialized views by relfrozenxid age to find the specific tables driving the database-level age found in script 01. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_multixact_age.sql` | Ranks tables by multixact ID age (relminmxid), a separate wraparound horizon driven by row-level locking (FOR UPDATE/SHARE, FK checks) rather than plain writes. | READ ONLY | Low (sub-second to a few seconds) |
| 04 | `04_current_autovacuum_activity.sql` | Confirms whether autovacuum is currently running, and on which tables, via pg_stat_progress_vacuum. | READ ONLY | Low (sub-second to a few seconds) |
| 05 | `05_tables_with_autovacuum_disabled.sql` | Finds tables with autovacuum explicitly disabled via storage parameters, a common and easily overlooked risk factor. | READ ONLY | Low (sub-second to a few seconds) |
| 06 | `06_long_running_transactions.sql` | Checks for long-running transactions that hold back the cluster-wide minimum xmin horizon, preventing vacuum from advancing even on tables it successfully scans. | READ ONLY | Low (sub-second to a few seconds) |
| 07 | `07_prepared_transactions.sql` | Checks for orphaned two-phase-commit (PREPARE TRANSACTION) entries, which behave like an indefinitely long-running transaction until resolved. | READ ONLY | Low (sub-second to a few seconds) |
| 08 | `08_replication_slots_xmin_pinning.sql` | Checks replication slots for a retained xmin/catalog_xmin that could be pinning the vacuum cleanup horizon. | READ ONLY | Low (sub-second to a few seconds) |
| 09 | `09_freeze_configuration_snapshot.sql` | Snapshots the current freeze-related configuration to interpret the ages found in scripts 01-03 against the actual thresholds in effect. | READ ONLY | Low (sub-second to a few seconds) |
| 10 | `10_time_to_wraparound_estimate.sql` | Estimates remaining headroom (in transactions and, using an assumed rate, wall-clock time) before the oldest table reaches the hard 2^31 wraparound limit. | READ ONLY | Low (sub-second to a few seconds) |
| 11 | `11_remediation_decision_tree.md` | Manual remediation decision tree and safe commands for resolving an active or imminent wraparound risk once the blocker is identified. | GUARDED -- MANUAL EXECUTION ONLY, SEVERITY-DEPENDENT (some branches are routine, others are incident-level) | Variable -- depends on table size and chosen batch size; see runbook. |

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

- Any table's age exceeds vacuum_failsafe_age (1,600,000,000 by default) -- this is an active, urgent risk of a wraparound-protection outage; escalate to database engineering leadership immediately regardless of time of day.
- The blocker is a system/replication process rather than an application session -- escalate before taking any corrective action.
- The cluster has already entered wraparound-protection read-only/refuse-new-transactions mode -- this is a full outage; follow your organization's major-incident process and engage AWS Support in parallel with database-side recovery.

## Scripts That Should Not Be Run During Severe Incidents

- 11_remediation_decision_tree.md -- Varies by branch -- from none (read-only confirmation) to a full-outage recovery procedure.
