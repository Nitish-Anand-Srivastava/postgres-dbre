# Deadlocks

**Category:** Locking and Concurrency | **Workflow:** `concurrency-and-locking/deadlocks`

## 1. Problem Description

Two or more transactions are (or recently were) mutually waiting on locks held by each other, causing PostgreSQL's deadlock detector to abort one of them automatically.

## 2. Typical Symptoms

- Application-level errors: 'deadlock detected' (SQLSTATE 40P01).
- A rising `deadlocks` counter in pg_stat_database.
- Intermittent transaction failures under concurrent load that succeed on retry.

## 3. Business Impact

- Deadlocked transactions are aborted automatically by PostgreSQL -- if the application does not retry correctly, this can silently drop a user-facing write (an order update, a balance change) that appeared to fail from the user's perspective.

## 4. Possible Root Causes

- Two code paths acquiring locks on the same set of rows/tables in a different order under concurrent execution.
- A single statement that internally touches multiple tables/rows in a non-deterministic order (e.g. a multi-row UPDATE without an explicit ORDER BY where deadlock risk exists across concurrent callers).
- Foreign-key-driven locking: an UPDATE/DELETE on a parent row taking a lock that conflicts with a concurrent child-table write's FK check.

## 5. Investigation Strategy

1. Confirm deadlocks are occurring and quantify frequency via pg_stat_database counters.
2. Retrieve the actual deadlock details from the PostgreSQL log (CloudWatch Logs on Aurora) since pg_locks/pg_stat_activity do not retain historical deadlock detail once resolved.
3. Identify the specific transactions/queries involved from the log entries.
4. Determine the lock-acquisition order difference between the two code paths.

## 6. Prerequisites

- `log_lock_waits` and default deadlock logging enabled (on by default) with logs exported to CloudWatch Logs for the Aurora instance -- this workflow's most important evidence lives in the log, not in live catalogs.
- pg_monitor role membership for the counter check.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_deadlock_counters.sql`](scripts/01_deadlock_counters.sql) -- Confirms deadlocks are occurring and quantifies frequency per database since the last stats reset.
2. [`scripts/02_current_lock_graph.sql`](scripts/02_current_lock_graph.sql) -- Captures the current lock graph, in case a near-deadlock (a long circular wait about to be detected) is actively forming.
3. [`scripts/03_transaction_age_of_contended_sessions.sql`](scripts/03_transaction_age_of_contended_sessions.sql) -- Checks transaction age for currently active/blocked sessions, to identify which transactions have been open long enough to plausibly be involved in repeated deadlock cycles.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- PostgreSQL's deadlock log messages are written to the standard PostgreSQL log, which on Aurora is exported to CloudWatch Logs (log group `/aws/rds/cluster/<cluster-id>/postgresql`) rather than a local filesystem -- use CloudWatch Logs Insights to search for 'deadlock detected' across the fleet.

## 8. Interpretation Guide

- The PostgreSQL deadlock log entry lists both processes, the queries they were running, and the exact lock types/objects involved -- this is the ground truth for root-causing which two code paths are in conflict, not a live SQL query (the deadlock is already resolved by the time you look).
- A steadily rising deadlocks counter with no corresponding application error-rate increase suggests the application is already retrying transparently -- lower urgency, but still worth fixing at the root.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Confirm the application is retrying deadlock-aborted transactions (SQLSTATE 40P01) correctly; if not, this is an urgent application-level bug fix, not a database fix.

**Short-term remediation** (hours to days):

- Standardize lock-acquisition order across all code paths touching the same tables (e.g. always lock accounts in ascending id order).
- Add explicit `ORDER BY` to multi-row UPDATE/DELETE statements that touch more than one row to make acquisition order deterministic.

**Long-term engineering fix** (days to weeks):

- Introduce application-level architectural patterns (single-writer-per-aggregate, optimistic concurrency with version columns) that eliminate the possibility of circular waits for hot financial entities.

## 10. Production Safety

- All investigation scripts here are read-only.
- PostgreSQL's deadlock detector already resolves deadlocks automatically by aborting one transaction -- no manual DBA intervention is possible or necessary at the moment a deadlock occurs.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Deadlock rate increases sharply after a deployment -- escalate to the deploying team with the log evidence immediately.
- Deadlocks involve core ledger/balance tables -- escalate to database engineering leadership given the financial-integrity sensitivity even if the application retry logic is confirmed correct.

## 12. Related Issues

- [lock-contention](../lock-contention/README.md)
- [transaction-contention](../transaction-contention/README.md)
