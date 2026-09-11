# Long-Running Transactions

**Category:** Locking and Concurrency | **Workflow:** `concurrency-and-locking/long-running-transactions`

## 1. Problem Description

A transaction has been open significantly longer than the workload's normal transaction duration, risking lock retention, vacuum horizon stalls, and increased rollback cost if it eventually fails.

## 2. Typical Symptoms

- A session's xact_start age far exceeds typical OLTP transaction duration (seconds, not minutes/hours).
- Autovacuum unable to advance relfrozenxid/clean up dead tuples on tables touched by the long transaction.
- Growing table bloat correlated with the transaction's start time.

## 3. Business Impact

- Long transactions on ledger/order tables hold locks and prevent vacuum cleanup, degrading performance for every other session touching the same tables for as long as the transaction remains open.

## 4. Possible Root Causes

- A batch/reporting job wrapped in a single large transaction instead of batched smaller ones.
- An application bug: a transaction opened and never committed/rolled back (often paired with idle-in-transaction).
- A long-running analytical query executed directly against the OLTP database inside an explicit transaction.
- A stuck two-phase-commit (prepared transaction) left unresolved.

## 5. Investigation Strategy

1. List all transactions currently open beyond a reasonable threshold, ranked by age.
2. For each, determine if it is actively executing a query or idle.
3. Check for any associated locks the transaction is holding that could be impacting others.
4. Check whether the transaction's age is materially affecting database-wide XID age / vacuum progress.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_open_transactions_by_age.sql`](scripts/01_open_transactions_by_age.sql) -- Lists all currently open transactions ranked by age, regardless of whether they are actively running a query.
2. [`scripts/02_locks_held_by_long_transactions.sql`](scripts/02_locks_held_by_long_transactions.sql) -- Shows what locks the oldest open transactions are currently holding.
3. [`scripts/03_xid_age_impact.sql`](scripts/03_xid_age_impact.sql) -- Checks database-level transaction age to assess whether the long-running transaction is meaningfully delaying vacuum's ability to advance the freeze horizon.

## 8. Interpretation Guide

- Age alone does not make a transaction a problem -- a multi-minute batch job may be legitimate. The key questions are: (1) is it holding locks that block others, and (2) is its age approaching a meaningful fraction of autovacuum_freeze_max_age for the busiest tables it touches.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If confirmed abandoned/orphaned and holding blocking locks, terminate per the safety guidance in blocked-queries.
- If it is a legitimate long batch job, ensure it is not scheduled to overlap with peak trading hours going forward.

**Short-term remediation** (hours to days):

- Break large batch operations into smaller, committed-in-chunks transactions.
- Set `idle_in_transaction_session_timeout` and a reasonable `statement_timeout` for application roles.

**Long-term engineering fix** (days to weeks):

- Route long-running analytical/reporting queries to a reader endpoint or a dedicated analytical replica instead of the writer.
- Add monitoring/alerting on transaction age directly (not just query duration) so this is caught proactively.

## 10. Production Safety

- Investigation scripts are read-only.
- Terminating a long-running transaction rolls back all of its uncommitted work -- confirm this is safe before doing so.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Transaction age approaches a meaningful percentage of autovacuum_freeze_max_age on any table it touches -- escalate immediately per transactions-and-xid/xid-wraparound-risk.

## 12. Related Issues

- [idle-in-transaction](../idle-in-transaction/README.md)
- [blocked-queries](../blocked-queries/README.md)
- [xid-wraparound-risk](../../transactions-and-xid/xid-wraparound-risk/README.md)
