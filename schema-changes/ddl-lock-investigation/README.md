# DDL Lock Investigation

**Category:** Schema Changes and DDL | **Workflow:** `schema-changes/ddl-lock-investigation`

## 1. Problem Description

A schema change is stuck, or a schema change has stalled the application, and you need to know exactly what is holding what. The mechanism behind almost every incident of this shape is the same and is worth understanding before reading any output: when a DDL statement requests `AccessExclusiveLock` and cannot get it immediately, PostgreSQL queues that request -- and then queues every *subsequent* lock request on the same table behind it, including plain `SELECT`s that would not have conflicted with the current holders at all. So a single long-running read, plus one waiting `ALTER TABLE`, is enough to freeze every query against the orders table while nothing is actually doing any work. This workflow finds the head of that queue, identifies the root blocker, and provides the guarded remediation.

## 2. Typical Symptoms

- A deployment's migration step has been running far longer than expected with no visible progress.
- Queries against one specific table have all stopped returning, while the rest of the database is completely healthy.
- Application connections are piling up and timing out, all on statements against the same table.
- An `ALTER TABLE`, `CREATE INDEX`, or `DROP INDEX` appears in `pg_stat_activity` with a lock wait event.
- `pg_locks` shows a long chain of ungranted lock requests on one relation.
- A concurrent index build has been parked in a waiting phase for hours.

## 3. Business Impact

- A lock queue on the orders table stops order placement and cancellation entirely -- a complete trading outage on that instrument set, with no error the application can retry its way out of.
- Because the queue blocks reads too, customer-facing balance and order-history views fail as well, multiplying the visible impact.
- Connection pools exhaust as every connection waits on the same lock, which spreads the failure to unrelated parts of the application that merely share a pool.
- These incidents are often misdiagnosed as database performance problems, wasting critical minutes looking at CPU and I/O when nothing is actually executing.

## 4. Possible Root Causes

- A DDL statement waiting for `AccessExclusiveLock` behind a long-running read, with every later query queued behind the DDL's pending request.
- A long-running analytical or reporting query holding a `AccessShareLock` on the table for minutes, which is enough to block the DDL and start the queue.
- An idle-in-transaction session holding a lock acquired earlier in its transaction and doing nothing -- usually a connection-pool leak or a forgotten terminal.
- An orphaned prepared transaction holding locks indefinitely, which survives restarts and never resolves itself.
- Autovacuum holding a `ShareUpdateExclusiveLock` and conflicting with a DDL statement. Autovacuum yields to most conflicting lock requests, but an anti-wraparound vacuum does not.
- Two concurrent schema changes on the same table contending with each other.
- A concurrent index build waiting for transactions older than its phase boundary -- including transactions that never touch the table.
- DDL issued against a partitioned parent, which acquires locks across every partition in a single transaction.

## 5. Investigation Strategy

1. Look first at DDL-style lock waits specifically, which immediately shows whether a schema change is at the head of the problem.
2. List every blocked session to establish the scale -- how much of the application is actually stalled.
3. Expand the blocking relationships to find the root blocker, following the chain rather than stopping at the first blocker found.
4. Read the raw lock detail by mode for ground truth on who holds what, in what mode, on which object.
5. Check long-running and idle-in-transaction sessions, which are the usual root cause at the bottom of the chain.
6. Apply the remediation runbook: cancel the pending DDL first to drain the queue, then deal with the root blocker, then retry with a lock timeout.

## 6. Prerequisites

- `pg_monitor` role membership for all investigation scripts.
- Authorization to cancel or terminate backends if remediation is needed -- establish who holds that authority before the incident, not during it.
- The writer endpoint: DDL and its lock queue live on the writer.
- Knowledge of what deployment or migration is currently in flight, which usually identifies the DDL statement immediately.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_ddl_lock_waits.sql`](scripts/01_ddl_lock_waits.sql) -- Shows sessions holding or waiting on the strong lock modes taken by DDL, which immediately reveals whether a schema change is at the head of the problem.
2. [`scripts/02_blocked_sessions_overview.sql`](scripts/02_blocked_sessions_overview.sql) -- Lists every currently blocked session with its direct blockers, establishing how much of the application is actually stalled.
3. [`scripts/03_blocking_chain_detail.sql`](scripts/03_blocking_chain_detail.sql) -- Expands every blocking relationship into one row per blocker, showing what each blocker is actually doing.
4. [`scripts/04_lock_detail_by_mode.sql`](scripts/04_lock_detail_by_mode.sql) -- Provides the raw ground truth of who holds what lock, in which mode, on which object.
5. [`scripts/05_long_running_and_idle_transactions.sql`](scripts/05_long_running_and_idle_transactions.sql) -- Finds the long-running and idle-in-transaction sessions, plus prepared transactions, that sit at the root of most DDL lock incidents.
6. [`scripts/06_ddl_lock_remediation_runbook.md`](scripts/06_ddl_lock_remediation_runbook.md) -- The guarded remediation runbook for draining a DDL lock queue and safely retrying the schema change.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Lock state is entirely per instance. DDL and its lock queue live on the writer, so always investigate a DDL lock incident against the writer endpoint -- a reader shows a completely different and irrelevant lock picture.
- An Aurora failover clears all locks by restarting the database, which does resolve a lock queue -- but it is a heavy-handed remedy with its own disruption, and it does nothing about the application behavior that created the blocker in the first place.
- `log_lock_waits` and `deadlock_timeout` are set through the Aurora DB cluster parameter group. Enabling `log_lock_waits` is one of the cheapest observability improvements available for this class of incident.
- Performance Insights shows `Lock:relation` and `Lock:transactionid` wait events prominently, which is often the fastest way to spot a lock queue forming before anyone reports an application problem.

## 8. Interpretation Guide

- Read `granted = false` rows first and order by wait duration. The oldest ungranted request is usually the head of the queue and the thing to act on.
- The critical insight: a *pending* `AccessExclusiveLock` blocks every later request on that relation, even requests that would not conflict with the current holders. That is why cancelling the waiting DDL -- not the long-running query it is waiting for -- is normally the fastest way to restore service. The queue drains within seconds.
- Follow the chain to its root. `pg_blocking_pids()` gives direct blockers, but the direct blocker may itself be blocked. The root blocker is the one that is not waiting on anything, and it is the only one worth acting on.
- A blocker in state `idle in transaction` is the most common and most frustrating root cause: it is doing no work at all while holding the lock. Its `blocking_txn_age` tells you how long it has been that way, and a large value with an idle state is effectively a confirmed leak.
- `AccessExclusiveLock` is taken by most `ALTER TABLE` forms, plain `DROP INDEX`, `TRUNCATE`, `REINDEX`, and `VACUUM FULL`. `ShareUpdateExclusiveLock` is taken by the concurrent index operations, `VALIDATE CONSTRAINT`, and autovacuum. `ShareLock` is taken by a plain `CREATE INDEX`.
- Autovacuum normally yields when it conflicts with a user lock request -- but an anti-wraparound autovacuum does not, and will not. If the blocker is an anti-wraparound vacuum, do not cancel it: it is protecting the cluster from a far worse outcome, and the correct action is to wait.
- If the waiting statement is a concurrent index build parked in a waiting phase, it is not in a lock queue in the conventional sense -- it is waiting for transaction age, and cancelling the transactions it waits on is the only thing that helps.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Cancel the pending DDL statement first. This drains the queue immediately and restores service within seconds, and it is almost always the right first move because the DDL has not done any work yet.
- Then deal with the root blocker: contact the owning team to close a long-running or idle-in-transaction session through their application.
- Only if the root blocker cannot be reached, and only with explicit authorization, terminate it at the backend level. Confirm the process identifier against the investigation output first -- terminating the wrong backend on a trading platform is its own incident.
- Never cancel an anti-wraparound autovacuum to unblock DDL. It is preventing a far more serious problem and must be allowed to finish.

**Short-term remediation** (hours to days):

- Retry the schema change with `SET lock_timeout` so it fails fast instead of forming a queue.
- Resolve any orphaned prepared transaction, which will otherwise block the next attempt identically.
- Move the blocking long-running reporting query to a reader, so it cannot block writer DDL at all.

**Long-term engineering fix** (days to weeks):

- Set `idle_in_transaction_session_timeout` cluster-wide so leaked connections cannot hold locks indefinitely.
- Enforce `lock_timeout` on all production DDL in the migration framework rather than relying on individuals to remember it.
- Route analytical and reporting workloads to dedicated readers so they never contend with writer DDL.
- Enable `log_lock_waits` so future lock waits are recorded with their full context and can be investigated after the fact.
- Monitor and alert on long-running transactions and prepared transactions, which are the root cause of most of these incidents.

## 10. Production Safety

- Every script in this workflow is read-only and safe to run during an active incident -- they are designed to be run under exactly these conditions.
- The remediation runbook contains session cancellation and termination guidance and must be read before any action is taken. Confirm every process identifier against the investigation output first.
- Cancelling is always preferable to terminating: a cancel ends the statement and lets the session clean up, while a termination drops the connection entirely and may surface as an application error.
- Terminating a backend rolls back its transaction. On a long-running write transaction that rollback can itself take a while and generate its own load.
- Never cancel an anti-wraparound autovacuum to unblock a schema change.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The lock queue is blocking order placement, matching, or wallet operations -- this is a full trading incident and needs incident command, not just a DBA.
- The root blocker is a backend owned by a team that cannot be reached, and the outage is ongoing.
- The blocker is an anti-wraparound autovacuum, which must not be cancelled -- escalate to the transaction ID wraparound workflow, because that is the more serious underlying problem.
- Cancelling the DDL does not drain the queue, which indicates something beyond a simple lock queue and needs deeper investigation.
- The same DDL has caused a lock incident more than once -- stop retrying and fix the process that keeps issuing it without a lock timeout.

## 12. Related Issues

- [large-table-ddl](../large-table-ddl/README.md)
- [concurrent-index-build](../concurrent-index-build/README.md)
- [safe-index-creation](../safe-index-creation/README.md)
- [column-type-change](../column-type-change/README.md)
- [ddl-blocking](../../concurrency-and-locking/ddl-blocking/README.md)
- [blocked-queries](../../concurrency-and-locking/blocked-queries/README.md)
- [lock-contention](../../concurrency-and-locking/lock-contention/README.md)
- [long-running-transactions](../../concurrency-and-locking/long-running-transactions/README.md)
- [idle-in-transaction](../../concurrency-and-locking/idle-in-transaction/README.md)
- [prepared-transactions](../../transactions-and-xid/prepared-transactions/README.md)
