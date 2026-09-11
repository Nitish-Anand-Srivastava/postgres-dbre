# Multixact ID Wraparound Risk

**Category:** Transaction ID (XID) Wraparound and Transaction Management | **Workflow:** `transactions-and-xid/multixact-risk`

## 1. Problem Description

Investigates the independent multixact ID wraparound horizon, driven by row-level locking (SELECT ... FOR UPDATE/SHARE, foreign key existence checks) rather than plain write volume -- easy to overlook because standard XID age can look completely healthy while multixact age is not.

## 2. Typical Symptoms

- mxid_age(relminmxid) climbing on tables with heavy row-level locking (order books, balance tables with FOR UPDATE reads) even while plain relfrozenxid age looks normal.
- Autovacuum log entries specifically mentioning multixact-related freezing.

## 3. Business Impact

- An exchange's order-matching and balance-update logic frequently relies on SELECT ... FOR UPDATE, making multixact accumulation a realistic, workload-specific risk distinct from generic wraparound guidance.

## 4. Possible Root Causes

- High-concurrency row locking on a relatively small set of hot rows (the same root cause as concurrency-and-locking/lock-contention, viewed through the multixact lens).
- Foreign-key referential integrity checks generating multixacts on frequently-referenced parent rows.
- autovacuum_multixact_freeze_max_age left at a default not tuned for the workload's actual multixact generation rate.

## 5. Investigation Strategy

1. Check multixact age per table, ranked descending.
2. Cross-reference the top tables against known hot-row/FK-heavy tables.
3. Check autovacuum activity for multixact-specific freeze progress.
4. Check autovacuum_multixact_freeze_max_age configuration.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_multixact_age_ranked.sql`](scripts/01_multixact_age_ranked.sql) -- Ranks tables by multixact ID age, the primary signal for this workflow.
2. [`scripts/02_multixact_freeze_configuration.sql`](scripts/02_multixact_freeze_configuration.sql) -- Checks the current multixact freeze configuration in effect.

## 8. Interpretation Guide

- A table with high multixact age but low plain XID age is not vacuumed less often overall -- it specifically needs multixact-aware freezing, which the same VACUUM operation performs, so the standard emergency-autovacuum procedure still applies.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a table is critically close to autovacuum_multixact_freeze_max_age, manually VACUUM it per vacuum-and-autovacuum/emergency-autovacuum -- the same command freezes both XID and multixact horizons together.

**Short-term remediation** (hours to days):

- Lower autovacuum_multixact_freeze_max_age for very hot tables so freezing happens more frequently in smaller increments.

**Long-term engineering fix** (days to weeks):

- Reduce unnecessary row-locking scope in application code (lock only the specific rows needed, avoid locking parent rows for FK checks where a lighter-weight validation pattern is possible).

## 10. Production Safety

- All investigation scripts are read-only.
- Remediation VACUUM guidance is identical in safety profile to standard vacuum -- non-blocking, no exclusive lock.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any table's multixact age exceeds 75% of autovacuum_multixact_freeze_max_age -- escalate to xid-wraparound-risk for the full remediation decision tree.

## 12. Related Issues

- [xid-wraparound-risk](../xid-wraparound-risk/README.md)
- [lock-contention](../../concurrency-and-locking/lock-contention/README.md)
