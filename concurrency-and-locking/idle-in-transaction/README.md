# Idle-in-Transaction Sessions

**Category:** Locking and Concurrency | **Workflow:** `concurrency-and-locking/idle-in-transaction`

## 1. Problem Description

Sessions holding an open transaction while sitting idle (not executing any statement) -- a specific and very common form of long-running-transaction typically caused by an application/connection-pool bug rather than a legitimate long operation.

## 2. Typical Symptoms

- Sessions with `state = 'idle in transaction'` accumulating and persisting across snapshots.
- Autovacuum unable to make progress cleaning up dead tuples.
- Growing table bloat with no corresponding growth in legitimate long-running query activity.

## 3. Business Impact

- Idle-in-transaction sessions serve no business purpose while active, yet consume a connection slot and hold locks/snapshots exactly as if they were doing useful work -- pure operational risk with zero benefit.

## 4. Possible Root Causes

- Application code that opens a transaction, then makes a network call (to another service, cache, or the user) before committing, and that call hangs or is never completed.
- A connection returned to a pool without an explicit COMMIT/ROLLBACK after an exception.
- An interactive psql/GUI session left open by an engineer mid-transaction.

## 5. Investigation Strategy

1. List all idle-in-transaction sessions ranked by duration.
2. Identify the application_name/usename to attribute each to an owning service.
3. Check whether any are holding locks currently blocking other sessions.
4. Confirm whether `idle_in_transaction_session_timeout` is configured, and at what value.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_idle_in_transaction_sessions.sql`](scripts/01_idle_in_transaction_sessions.sql) -- Lists all sessions currently idle in an open transaction, ranked by duration.
2. [`scripts/02_locks_held.sql`](scripts/02_locks_held.sql) -- Checks whether any idle-in-transaction session is currently holding a lock that is blocking others.
3. [`scripts/03_idle_in_transaction_timeout_setting.sql`](scripts/03_idle_in_transaction_timeout_setting.sql) -- Confirms whether idle_in_transaction_session_timeout is configured, to assess whether this class of issue will self-resolve.

## 8. Interpretation Guide

- Any idle-in-transaction session older than a few seconds on a low-latency OLTP path is abnormal and should be investigated; this is different from long-running-transactions where an actively executing long operation may be legitimate.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Terminate confirmed-orphaned idle-in-transaction sessions per the safety guidance in blocked-queries, prioritizing any holding blocking locks.

**Short-term remediation** (hours to days):

- Set `idle_in_transaction_session_timeout` at the role or database level so these are auto-terminated by PostgreSQL itself going forward.
- Audit the owning application's transaction-boundary handling (ensure try/finally or equivalent always closes the transaction).

**Long-term engineering fix** (days to weeks):

- Add APM instrumentation/alerting on transaction duration at the application layer to catch this class of bug before it reaches the database as a symptom.

## 10. Production Safety

- Investigation scripts are read-only.
- Terminating an idle-in-transaction session always rolls back its (by definition, currently paused) transaction -- this is virtually always safe since no statement is in flight, but confirm no unusual application semantics rely on a long-held open transaction.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A specific application/service is repeatedly identified as the source -- escalate to that team with the evidence; this is an application bug fix, not an ongoing DBA task.

## 12. Related Issues

- [long-running-transactions](../long-running-transactions/README.md)
- [blocked-queries](../blocked-queries/README.md)
- [idle-in-transaction](../../connections/idle-in-transaction/README.md)
