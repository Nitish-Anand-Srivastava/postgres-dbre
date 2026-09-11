# Transaction ID (XID) Wraparound Risk

**Category:** Transaction ID (XID) Wraparound and Transaction Management | **Workflow:** `transactions-and-xid/xid-wraparound-risk`

## 1. Problem Description

PostgreSQL transaction IDs are a finite 32-bit counter. If the oldest unfrozen transaction ID in any database is allowed to age past ~2.1 billion transactions without being frozen by vacuum, PostgreSQL will refuse new transactions cluster-wide to protect data integrity (a full outage that requires single-user-mode recovery to resolve). This workflow is the comprehensive, staff-level investigation and prevention runbook for that risk.

## 2. Typical Symptoms

- Warnings in the PostgreSQL log (CloudWatch Logs on Aurora): 'database is not accepting commands to avoid wraparound data loss'.
- age(datfrozenxid) for any database climbing steadily with no corresponding autovacuum activity.
- Autovacuum running continuously in 'aggressive'/anti-wraparound mode on one or more large tables.
- Aurora CloudWatch metric MaximumUsedTransactionIDs approaching autovacuum_freeze_max_age.

## 3. Business Impact

- Wraparound protection kicking in is a full write outage across the entire database -- every trading, ledger, and order-book write stops until an operator intervenes, typically requiring emergency single-user-mode VACUUM.
- This is one of the few PostgreSQL failure modes that is entirely preventable with routine monitoring, making an actual wraparound incident a severe operational failure, not an unavoidable act of nature.
- Recovery from an active wraparound-protection outage can take hours on very large tables, since the required VACUUM cannot be skipped or parallelized trivially in single-user mode.

## 4. Possible Root Causes

- Autovacuum disabled or effectively starved (cost limits too conservative, autovacuum_naptime too high) for the actual write/update volume.
- A long-running transaction or an orphaned prepared (two-phase-commit) transaction holding back the cluster-wide minimum required XID horizon, preventing vacuum from advancing relfrozenxid even where it runs successfully elsewhere.
- An abandoned or forgotten replication slot retaining an old xmin, preventing cleanup.
- Extremely high write/update volume on one or a few huge tables outpacing autovacuum's throughput even when properly configured.
- autovacuum_freeze_max_age and related settings left at defaults that do not suit an extremely high-transaction-rate exchange workload.
- A table explicitly configured with autovacuum disabled (`autovacuum_enabled = false` in reloptions) for perceived performance reasons, inadvertently disabling its own wraparound protection too (anti-wraparound vacuums still force-run regardless of this setting, but later than they should if the table was otherwise neglected).

## 5. Investigation Strategy

1. Check database-level transaction age (datfrozenxid) for every database in the cluster -- this is the single most important, highest-level signal.
2. Check table-level transaction age (relfrozenxid) to identify which specific tables are closest to the freeze horizon.
3. Check TOAST tables specifically, since they age independently and are commonly overlooked.
4. Check multixact age separately, since it has its own independent wraparound horizon and its own freeze_max_age setting.
5. Check current autovacuum activity to confirm workers are actively running and progressing on the oldest tables.
6. Identify any tables where autovacuum is disabled via storage parameters.
7. Check for long-running transactions holding back the cluster-wide minimum xmin horizon.
8. Check for orphaned prepared (two-phase-commit) transactions holding back cleanup.
9. Check replication slots for an old xmin/catalog_xmin that could be pinning the vacuum horizon.
10. Cross-check current freeze-related configuration (autovacuum_freeze_max_age, vacuum_failsafe_age, per-table overrides) against the observed ages.
11. Estimate time-to-wraparound at the current XID consumption rate to prioritize response urgency.
12. Follow the documented remediation path appropriate to the specific blocker found (kill blocker, force vacuum, tune settings) -- never skip straight to VACUUM FULL or any destructive action.

## 6. Prerequisites

- pg_monitor role membership for all read-only investigation scripts.
- Table-owner or pg_maintain-equivalent privileges (or DBA/rds_superuser on Aurora) if a manual VACUUM must be issued as part of remediation.
- Familiarity with vacuum-and-autovacuum/emergency-autovacuum for the accompanying remediation runbook.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_database_transaction_age.sql`](scripts/01_database_transaction_age.sql) -- Database-level XID age against datfrozenxid -- the single highest-priority check in this entire workflow.
2. [`scripts/02_table_transaction_age.sql`](scripts/02_table_transaction_age.sql) -- Ranks ordinary tables, TOAST tables, and materialized views by relfrozenxid age to find the specific tables driving the database-level age found in script 01.
3. [`scripts/03_multixact_age.sql`](scripts/03_multixact_age.sql) -- Ranks tables by multixact ID age (relminmxid), a separate wraparound horizon driven by row-level locking (FOR UPDATE/SHARE, FK checks) rather than plain writes.
4. [`scripts/04_current_autovacuum_activity.sql`](scripts/04_current_autovacuum_activity.sql) -- Confirms whether autovacuum is currently running, and on which tables, via pg_stat_progress_vacuum.
5. [`scripts/05_tables_with_autovacuum_disabled.sql`](scripts/05_tables_with_autovacuum_disabled.sql) -- Finds tables with autovacuum explicitly disabled via storage parameters, a common and easily overlooked risk factor.
6. [`scripts/06_long_running_transactions.sql`](scripts/06_long_running_transactions.sql) -- Checks for long-running transactions that hold back the cluster-wide minimum xmin horizon, preventing vacuum from advancing even on tables it successfully scans.
7. [`scripts/07_prepared_transactions.sql`](scripts/07_prepared_transactions.sql) -- Checks for orphaned two-phase-commit (PREPARE TRANSACTION) entries, which behave like an indefinitely long-running transaction until resolved.
8. [`scripts/08_replication_slots_xmin_pinning.sql`](scripts/08_replication_slots_xmin_pinning.sql) -- Checks replication slots for a retained xmin/catalog_xmin that could be pinning the vacuum cleanup horizon.
9. [`scripts/09_freeze_configuration_snapshot.sql`](scripts/09_freeze_configuration_snapshot.sql) -- Snapshots the current freeze-related configuration to interpret the ages found in scripts 01-03 against the actual thresholds in effect.
10. [`scripts/10_time_to_wraparound_estimate.sql`](scripts/10_time_to_wraparound_estimate.sql) -- Estimates remaining headroom (in transactions and, using an assumed rate, wall-clock time) before the oldest table reaches the hard 2^31 wraparound limit.
11. [`scripts/11_remediation_decision_tree.md`](scripts/11_remediation_decision_tree.md) -- Manual remediation decision tree and safe commands for resolving an active or imminent wraparound risk once the blocker is identified.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora exposes the CloudWatch metric MaximumUsedTransactionIDs at the instance level, which mirrors the highest age() value across all databases -- use it for alerting in addition to (not instead of) the SQL-level checks here, since CloudWatch alarms fire even when nobody is actively running these scripts.
- Wraparound protection and its recovery mechanics (autovacuum, freeze, failsafe) are standard PostgreSQL engine behavior and work identically on Aurora -- there is no Aurora-specific bypass or storage-layer mitigation for XID exhaustion.

## 8. Interpretation Guide

- age() values are compared against autovacuum_freeze_max_age (default 200,000,000; many high-transaction-rate deployments lower this so autovacuum engages earlier and more gradually) and the hard failsafe at vacuum_failsafe_age (default 1,600,000,000) where PostgreSQL 14+ automatically escalates to a faster, index-skipping emergency vacuum mode.
- A pct_of_freeze_max_age above ~80-90% on any table warrants proactive attention even without an active incident; above 100% means autovacuum should already be running an aggressive/anti-wraparound vacuum on that table by design.
- If age is climbing despite autovacuum running, the workload's write rate simply exceeds autovacuum's configured throughput (cost limits) -- this is a tuning problem, not a 'vacuum is broken' problem.
- If age is climbing and autovacuum is NOT running on the oldest tables, look for a blocker: a long-running transaction, an orphaned prepared transaction, a disabled-autovacuum table, or a stuck replication slot.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a specific long-running transaction or orphaned prepared transaction is identified as the blocker, resolve it (commit/rollback the prepared transaction, or terminate the long-running session with documented approval) so vacuum can advance.
- If age is critically high (approaching vacuum_failsafe_age) on a specific table, manually issue `VACUUM (VERBOSE) <table>;` (or `VACUUM (FREEZE)` for a targeted freeze) against that table immediately rather than waiting for autovacuum's next scheduled pass -- see vacuum-and-autovacuum/emergency-autovacuum for the full safe procedure.

**Short-term remediation** (hours to days):

- Increase autovacuum cost limits (autovacuum_vacuum_cost_limit, autovacuum_vacuum_cost_delay) via the Aurora cluster parameter group for the affected tables/instance to let autovacuum work faster.
- Lower autovacuum_freeze_max_age (and/or set a per-table `autovacuum_freeze_max_age` storage parameter) for extremely high-write tables so freezing happens more frequently in smaller, cheaper increments instead of large, disruptive passes.
- Drop or fix any replication slot that is inactive/abandoned and pinning the xmin horizon, after confirming it is genuinely no longer needed.

**Long-term engineering fix** (days to weeks):

- Establish routine automated monitoring/alerting on transaction age (see automation/xid-monitoring) with alert thresholds well below the failsafe (e.g. alert at 50% of autovacuum_freeze_max_age).
- Review and, where appropriate, remove any `autovacuum_enabled = false` table-level overrides that were set for perceived performance reasons without an accompanying manual vacuum schedule.
- Consider partitioning extremely large, high-churn tables (see partitioning/) so freeze/vacuum work is distributed across smaller partitions rather than one monolithic table.

## 10. Production Safety

- All numbered investigation scripts (01-10) are read-only.
- Manual `VACUUM` (without FULL) is safe to run concurrently with production traffic -- it does not take an exclusive table lock and does not rewrite the table. Never substitute `VACUUM FULL` here: it takes AccessExclusiveLock for the duration and is a much higher-risk operation, and is not needed to resolve wraparound risk.
- Never disable autovacuum cluster-wide or on a specific table as a way to 'reduce load' -- this directly increases wraparound risk and is one of the root causes this workflow investigates.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any table's age exceeds vacuum_failsafe_age (1,600,000,000 by default) -- this is an active, urgent risk of a wraparound-protection outage; escalate to database engineering leadership immediately regardless of time of day.
- The blocker is a system/replication process rather than an application session -- escalate before taking any corrective action.
- The cluster has already entered wraparound-protection read-only/refuse-new-transactions mode -- this is a full outage; follow your organization's major-incident process and engage AWS Support in parallel with database-side recovery.

## 12. Related Issues

- [transaction-age](../transaction-age/README.md)
- [multixact-risk](../multixact-risk/README.md)
- [prepared-transactions](../prepared-transactions/README.md)
- [emergency-autovacuum](../../vacuum-and-autovacuum/emergency-autovacuum/README.md)
- [autovacuum-not-keeping-up](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
