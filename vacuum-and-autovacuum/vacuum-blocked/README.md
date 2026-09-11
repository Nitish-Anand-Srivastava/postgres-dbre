# Vacuum Blocked or Unable to Proceed

**Category:** Vacuum and Autovacuum | **Workflow:** `vacuum-and-autovacuum/vacuum-blocked`

## 1. Problem Description

Autovacuum or a manual VACUUM is unable to start or make progress on a specific table due to a lock conflict or a long-running transaction holding back its required snapshot horizon.

## 2. Typical Symptoms

- A table shows a stale last_autovacuum/last_vacuum timestamp despite clearly needing attention (high dead_tup).
- No active pg_stat_progress_vacuum entry for a table that should be receiving attention.

## 3. Business Impact

- A table vacuum cannot proceed indefinitely blocks bloat and (if sustained) XID-age cleanup for that table, compounding into the more severe autovacuum-not-keeping-up and xid-wraparound-risk scenarios.

## 4. Possible Root Causes

- A conflicting lock (e.g. an explicit LOCK TABLE, or a long-running transaction holding a conflicting lock mode) preventing vacuum from acquiring the ShareUpdateExclusiveLock it needs.
- A long-running transaction whose snapshot predates the dead tuples, meaning vacuum can scan the table but cannot yet remove those specific tuples.

## 5. Investigation Strategy

1. Confirm no autovacuum worker is currently assigned to the table despite it needing attention.
2. Check for locks on the table that would conflict with vacuum's required lock mode.
3. Check for a long-running transaction whose xmin predates the table's dead tuples.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_locks_conflicting_with_vacuum.sql`](scripts/01_locks_conflicting_with_vacuum.sql) -- Checks for locks on candidate tables that would conflict with vacuum's required ShareUpdateExclusiveLock.
2. [`scripts/02_transactions_predating_dead_tuples.sql`](scripts/02_transactions_predating_dead_tuples.sql) -- Checks for long-running transactions whose snapshot predates recent dead tuples, preventing vacuum from reclaiming them even if it can run.

## 8. Interpretation Guide

- VACUUM only requires ShareUpdateExclusiveLock, which does not block ordinary reads/writes -- but it does conflict with other ShareUpdateExclusiveLock or stronger requests (another VACUUM, a CREATE INDEX CONCURRENTLY, most ALTER TABLE forms) already in progress on the same table.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Resolve the conflicting lock holder or long-running transaction identified, using the concurrency-and-locking workflows.

**Short-term remediation** (hours to days):

- Avoid scheduling concurrent CONCURRENTLY-mode DDL and manual VACUUM against the same large table in the same window.

**Long-term engineering fix** (days to weeks):

- Add monitoring that alerts when a known-hot table has gone unusually long without a successful vacuum.

## 10. Production Safety

- Investigation scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The table's XID age is simultaneously climbing toward a concerning threshold while vacuum remains blocked -- escalate immediately per xid-wraparound-risk.

## 12. Related Issues

- [xid-wraparound-risk](../../transactions-and-xid/xid-wraparound-risk/README.md)
- [long-running-transactions](../../concurrency-and-locking/long-running-transactions/README.md)
