# Blocked Queries

**Category:** Locking and Concurrency | **Workflow:** `concurrency-and-locking/blocked-queries`

## 1. Problem Description

One or more sessions are waiting on a lock held by another session, delaying query completion and, if the wait chain is long, threatening a broader slowdown or timeout cascade.

## 2. Typical Symptoms

- Application timeouts on specific operations (order update, balance write).
- Growing count of sessions in a waiting state in pg_stat_activity.
- A single write to a hot row (account balance, order row) suddenly taking seconds instead of milliseconds.

## 3. Business Impact

- Blocked writes on ledger/balance/order tables directly delay financial operations and can cause visible inconsistency windows to users.
- A blocking chain left unresolved can cascade into full connection pool exhaustion as more sessions queue up behind it.

## 4. Possible Root Causes

- A long-running transaction (application bug, forgotten COMMIT, batch job) holding a row/table lock far longer than intended.
- An idle-in-transaction session holding a lock while the client is disconnected/stuck.
- Two application code paths taking locks on the same rows in different orders (a precursor to a deadlock, not yet detected as one).
- A DDL statement (schema-changes) waiting for/holding an AccessExclusiveLock against ongoing traffic.

## 5. Investigation Strategy

1. Identify every currently blocked session and its wait duration.
2. Identify the specific session(s) directly blocking each of them.
3. Inspect what the blocking session is doing/has done and how long its transaction has been open.
4. Decide whether to wait, escalate to the owning team, or (rarely) terminate the blocking session.

## 6. Prerequisites

- pg_monitor role membership.
- Awareness of change-freeze/incident policy before terminating any backend.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_identify_blocked_sessions.sql`](scripts/01_identify_blocked_sessions.sql) -- Identifies every session currently blocked, with its blocking pid(s), using the built-in pg_blocking_pids() helper.
2. [`scripts/02_identify_blocking_sessions.sql`](scripts/02_identify_blocking_sessions.sql) -- Expands each blocking relationship to show what the blocking session is doing and for how long.
3. [`scripts/03_lock_detail.sql`](scripts/03_lock_detail.sql) -- Shows the raw lock detail (mode, object, granted state) behind the blocking relationship for precise diagnosis.
4. [`scripts/04_long_running_transactions.sql`](scripts/04_long_running_transactions.sql) -- Confirms whether the blocking session is also one of the oldest open transactions on the instance.

## 8. Interpretation Guide

- A blocking session that is `idle in transaction` with no active query is the clearest case for safe intervention (it is not doing useful work).
- A blocking session that is `active` and genuinely executing a long legitimate operation requires coordination with its owner before any termination.
- Multiple blocked sessions behind a single blocker is high leverage: fixing the one blocker unblocks everyone downstream.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If the blocker is idle-in-transaction and confirmed abandoned/orphaned, terminate it with `SELECT pg_terminate_backend(<pid>);` only after documented approval -- this rolls back its transaction.
- If the blocker is a legitimate long operation, coordinate with its owner to let it finish or cancel it gracefully.

**Short-term remediation** (hours to days):

- Add `idle_in_transaction_session_timeout` at the role/database level to prevent recurrence.
- Add `lock_timeout` to latency-sensitive application roles so a blocked session fails fast and retries instead of queuing indefinitely.

**Long-term engineering fix** (days to weeks):

- Review application transaction boundaries to ensure locks are held for the minimum necessary duration.
- Introduce row-level locking discipline documentation for hot tables (see the crypto-exchange hot-row-contention guidance in the root README).

## 10. Production Safety

- Investigation scripts are read-only.
- `pg_terminate_backend()` rolls back the target transaction -- never run it against a session performing a financial write without confirming rollback is safe and idempotent from the application's perspective.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The blocking session belongs to a system/replication process rather than application code -- escalate to database engineering before terminating anything.
- The blocking chain does not resolve after the identified blocker is handled (a second, hidden blocker exists) -- escalate for a deeper investigation.

## 12. Related Issues

- [lock-contention](../lock-contention/README.md)
- [deadlocks](../deadlocks/README.md)
- [idle-in-transaction](../idle-in-transaction/README.md)
- [lock-storm](../../incident-response/lock-storm/README.md)
