# Autovacuum Not Keeping Up

**Category:** Vacuum and Autovacuum | **Workflow:** `vacuum-and-autovacuum/autovacuum-not-keeping-up`

## 1. Problem Description

Autovacuum is running but dead tuples / table bloat are growing faster than autovacuum can clean them up, degrading query performance and increasing storage over time.

## 2. Typical Symptoms

- n_dead_tup growing steadily across snapshots on one or more hot tables.
- last_autovacuum timestamp falling further and further behind for a specific table.
- Increasing bloat-driven query latency on tables that were previously fast.

## 3. Business Impact

- Unchecked bloat on hot OLTP tables (orders, balances) increases I/O per query and, left long enough, risks an emergency VACUUM disruption and XID wraparound exposure.

## 4. Possible Root Causes

- autovacuum_vacuum_cost_limit / autovacuum_vacuum_cost_delay set too conservatively for the actual write volume.
- Too few autovacuum_max_workers for the number of tables needing attention simultaneously.
- A long-running transaction repeatedly preventing autovacuum from removing dead tuples it has already identified.
- autovacuum_naptime too long relative to the table's churn rate.

## 5. Investigation Strategy

1. Rank tables by dead tuple count/ratio to find the worst offenders.
2. Check current and historical autovacuum activity/frequency for those tables.
3. Check for competing long-running transactions blocking cleanup.
4. Review current autovacuum cost/worker configuration.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_dead_tuples_ranked.sql`](scripts/01_dead_tuples_ranked.sql) -- Ranks tables by dead tuple count and ratio to find the worst autovacuum-lag offenders.
2. [`scripts/02_current_autovacuum_workers.sql`](scripts/02_current_autovacuum_workers.sql) -- Shows currently running autovacuum workers and their progress.
3. [`scripts/03_blocking_transactions.sql`](scripts/03_blocking_transactions.sql) -- Checks for long-running transactions that could be preventing autovacuum from reclaiming space it has already identified as dead.
4. [`scripts/04_autovacuum_configuration.sql`](scripts/04_autovacuum_configuration.sql) -- Snapshots current autovacuum cost/worker configuration to assess whether tuning is the root cause.

## 8. Interpretation Guide

- A high dead_tuple_pct with a recent last_autovacuum timestamp means autovacuum is running but not keeping pace -- a tuning problem. A high dead_tuple_pct with a stale/NULL last_autovacuum means autovacuum is not running at all on that table -- an investigation-for-blocker problem.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a specific table is critically bloated, issue a manual `VACUUM (VERBOSE, ANALYZE) <table>;` to catch it up immediately.

**Short-term remediation** (hours to days):

- Set a more aggressive per-table autovacuum_vacuum_cost_limit/scale_factor for the specific hot tables identified (via `ALTER TABLE ... SET (autovacuum_vacuum_scale_factor = 0.01)` for very large tables where the default 20% dead-tuple threshold is too high in absolute terms).
- Increase autovacuum_max_workers via the cluster parameter group if many tables need attention concurrently.

**Long-term engineering fix** (days to weeks):

- Consider partitioning extremely large, high-churn tables so each partition is vacuumed independently and more frequently in smaller units (see partitioning/).

## 10. Production Safety

- Investigation scripts are read-only.
- Manual VACUUM (without FULL) is non-blocking and safe to run concurrently with production traffic.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Bloat continues to grow despite tuning changes and manual vacuum -- escalate to database engineering for a schema/partitioning-level fix.

## 12. Related Issues

- [dead-tuples](../dead-tuples/README.md)
- [table-bloat](../table-bloat/README.md)
- [emergency-autovacuum](../emergency-autovacuum/README.md)
