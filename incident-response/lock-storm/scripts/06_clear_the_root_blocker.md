# 06_clear_the_root_blocker

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_clear_the_root_blocker.md` |
| Purpose | Guarded runbook for clearing the root of a lock storm: cancel first, terminate only when justified, and verify the graph actually drained. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | The specific instance hosting the target backend -- `pg_cancel_backend()` / `pg_terminate_backend()` only affect backends on the instance you are currently connected to, so connect to the writer, or to the specific reader, where the session actually lives. |
| Safety | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) |
| Expected impact | A cancel aborts the blocker's current statement. A terminate rolls back its entire transaction. Both release the locks the storm is queued on. |
| Required privileges | Reading the investigation output requires only `pg_monitor`. Ending another session additionally requires membership in `pg_signal_backend` (or, on Aurora, `rds_superuser`): a plain `pg_monitor` role can see the offending backend but cannot cancel or terminate it. |
| Prerequisites | Scripts 01-05 completed, a true root identified, and the financial-write safety gate satisfied before any terminate. |
| Execution order | Step 06 of workflow `incident-response/lock-storm` |
| Related scripts | 02_blocked_sessions.sql, 03_root_blockers_by_blast_radius.sql, 05_ddl_and_old_transactions.sql |

## How to interpret / use this runbook

Clear exactly one true root, verify, and repeat only if a new true root appears. The verification step is not optional: a storm with two roots looks identical to a failed remediation if you stop measuring.

---

## One root at a time

A lock storm is cleared by resolving the true root of the wait graph, not by
signalling everything that looks suspicious. Take the single root identified in
script 03 (`blocker_is_itself_blocked_by_count = 0`, largest
`directly_blocked_sessions`), act on it, then re-measure.

## Cancel vs. terminate -- understand both before you type either

| Function | Signal | Effect | Client sees | Uncommitted work |
|---|---|---|---|---|
| `pg_cancel_backend(pid)` | SIGINT | Aborts the **currently running statement** only. The connection survives and the surrounding transaction stays open, moving to `idle in transaction (aborted)` until the client issues `COMMIT` or `ROLLBACK`. | `ERROR: canceling statement due to user request` (SQLSTATE `57014`) | Only the cancelled statement is undone. Earlier statements in the same open transaction stay pending until the client ends the transaction. |
| `pg_terminate_backend(pid)` | SIGTERM | Kills the **entire backend and its connection**. | `FATAL: terminating connection due to administrator command` (SQLSTATE `57P01`), then a dropped connection | The whole open transaction is rolled back. Everything it did since `BEGIN` and had not committed is lost. |

Both functions return `true` when the signal was *delivered* -- not when the
target actually stopped. Always re-run the investigation script afterwards to
confirm the session is really gone: a backend inside an uninterruptible
operation can ignore a cancel entirely, and a terminated backend that is still
rolling back a large transaction stays visible for as long as the rollback
takes (which, for a long bulk write, can be minutes).

**Always try `pg_cancel_backend()` first.** It is strictly less disruptive, it
resolves the large majority of incidents, and if it fails you can still escalate
to a terminate seconds later. There is no path back from a terminate.

### Financial-write safety gate (non-negotiable)

Before terminating any backend whose statement touches a financial table
(`ledger_entries`, `wallets`, `withdrawals`, `deposits`, `trades`, `orders`,
settlement or position tables), you must have all four of the following:

1. The full statement text and the owning service, from the investigation scripts
   in this workflow -- never from memory or from a screenshot in the channel.
2. Explicit confirmation from that service's on-call owner that rolling the
   transaction back is safe and that the operation is **idempotent on retry**. A
   half-applied withdrawal or a double-credited deposit is a far worse incident
   than the latency you are trying to fix.
3. A second engineer on the call who reads the pid back to you before you run it.
   Operating systems reuse pids; a stale pid from a five-minute-old snapshot can
   terminate an entirely innocent session.
4. The action, the pid, the statement text, the approver and the timestamp posted
   in the incident channel at the moment you run it -- for the post-incident
   review, and for any reconciliation of the affected accounts afterwards.

Never end a backend whose `backend_type` is not `client backend` (for example
`autovacuum worker`, `walsender`, `checkpointer`, or an Aurora-internal backend).
Terminating background machinery does not fix an application incident and can
make the cluster's state materially worse.

## Step 1 -- re-confirm the root immediately before acting

Wait graphs change second to second, and pids are reused. Re-run
`03_root_blockers_by_blast_radius.sql` and read the pid out loud to the second
engineer on the call before you type it.

## Step 2 -- special case: the root is a waiting DDL statement

*Precondition: script 05 shows a DDL statement with `granted = false`.*

Cancel the DDL, not the transaction it is waiting on. A cancelled DDL statement
rolls back cleanly, has changed no data, and its cancellation instantly drains
every query that queued behind its lock request:

```sql
SELECT pg_cancel_backend(<DDL pid from script 05>);
```

Then tell whoever issued it not to retry until the migration is converted to the
concurrent, lock-light pattern and given a `lock_timeout` -- otherwise the next
attempt recreates this incident exactly.

## Step 3 -- general case: cancel the root blocker

```sql
SELECT pg_cancel_backend(<root blocker pid from script 03>);
```

Wait about 15 seconds, then re-run `02_blocked_sessions.sql`. A draining graph
means you are done; move to verification.

Note the one case where cancel cannot work: if the root's state is `idle in
transaction`, there is no running statement to cancel. The session is idle inside
an open transaction, so only a terminate will end it -- go straight to step 4,
applying the safety gate.

## Step 4 -- terminate, only with the safety gate satisfied

```sql
SELECT pg_terminate_backend(<root blocker pid from script 03>);
```

This rolls back the blocker's entire transaction. If its statement text touches
`ledger_entries`, `wallets`, `withdrawals`, `deposits`, `trades` or `orders`, the
financial-write safety gate above applies in full and without exception. If the
owning team cannot confirm that a rollback is safe, the correct answer may be to
let the storm continue while they finish -- say so explicitly in the incident
channel so that decision is a shared, recorded one.

## Step 5 -- verify, and do not stop early

1. Re-run `02_blocked_sessions.sql`: the blocked count should fall sharply.
2. Re-run `03_root_blockers_by_blast_radius.sql`: if a NEW true root appears, the
   storm had more than one root. Repeat from step 1 rather than assuming failure.
3. Check connection headroom with `../connection-exhaustion/README.md` script 01.
   Storms leave behind a pile of connections that were waiting, and the recovery
   surge is a common second incident.
4. Confirm with the affected services that latency has actually recovered. A
   drained lock graph is necessary but not sufficient evidence.

## Never do this

Do not write a statement that signals every blocker at once. You will roll back
transactions nobody has identified, on tables nobody has checked, and on a ledger
or wallet table that turns a ten-minute lock storm into a multi-day reconciliation.
