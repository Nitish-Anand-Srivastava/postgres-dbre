# 05_stop_the_runaway_query

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `05_stop_the_runaway_query.md` |
| Purpose | Guarded runbook for stopping a runaway query with the smallest intervention that actually works, and for handling the open-transaction case correctly. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | The specific instance hosting the target backend -- `pg_cancel_backend()` / `pg_terminate_backend()` only affect backends on the instance you are currently connected to, so connect to the writer, or to the specific reader, where the session actually lives. |
| Safety | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) |
| Expected impact | A cancel aborts the running statement and leaves the connection and any open transaction alive. A terminate ends the connection and rolls the whole transaction back. |
| Required privileges | Reading the investigation output requires only `pg_monitor`. Ending another session additionally requires membership in `pg_signal_backend` (or, on Aurora, `rds_superuser`): a plain `pg_monitor` role can see the offending backend but cannot cancel or terminate it. |
| Prerequisites | Scripts 01-04 completed, the full query text captured, the owner identified, and backend_type confirmed as client backend. |
| Execution order | Step 05 of workflow `incident-response/runaway-query` |
| Related scripts | 02_target_backend_detail.sql, 03_collateral_damage.sql |

## How to interpret / use this runbook

Capture the query text first, cancel before terminating, and check the open-transaction trap in step 2 -- a successful cancel that leaves the transaction open is the most common false 'fixed' in this workflow.

---

## Before you stop anything

Three things must be true, and all three come from script 02:

1. You have captured `full_query_text` and posted it in the incident channel.
2. You know the owning service or human from `application_name` / `usename` /
   `client_addr`, and you have told them.
3. `backend_type` is `client backend`. If it is anything else, stop -- this is not
   an application query and signalling it is not your call.

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

## Step 1 -- cancel

```sql
SELECT pg_cancel_backend(<pid from script 02>);
```

Re-run `02_target_backend_detail.sql`. Three possible outcomes:

* **No rows.** The session is gone entirely (its client disconnected on error).
  Done -- go to verification.
* **State is `idle` or `idle in transaction (aborted)`.** The statement was
  cancelled and the connection survived, which is the intended result.
* **Still `active` with the same query_start.** The cancel has not taken effect.
  A backend inside certain long internal operations cannot be interrupted
  immediately; give it another 15 seconds before escalating.

## Step 2 -- the open-transaction trap

*Precondition: script 02 showed `txn_runtime` much larger than `query_runtime`.*

The statement was only part of a longer transaction. Cancelling it leaves that
transaction OPEN, still holding its snapshot and every lock it had already
acquired -- so the blocking and the vacuum-horizon damage continue even though
the expensive statement has stopped. This surprises people constantly.

Resolve it one of two ways:

* Have the owning client issue `ROLLBACK` (preferred -- the application controls
  its own outcome), or
* Terminate the backend, per step 3, which rolls the transaction back for it.

## Step 3 -- terminate, only if justified

```sql
SELECT pg_terminate_backend(<pid from script 02>);
```

Justified when: the cancel demonstrably failed, or the transaction must be rolled
back and its client cannot be reached. The financial-write safety gate above
applies in full if the statement touched `ledger_entries`, `wallets`,
`withdrawals`, `deposits`, `trades` or `orders`.

Expect the rollback itself to take time for a statement that had already written
a lot -- the backend stays visible in `pg_stat_activity` while it unwinds, and
signalling it again does not speed that up.

## Step 4 -- stop it coming straight back

An unmodified retry reproduces this incident within minutes, so close the loop
before you close the incident:

* Tell the owner explicitly not to retry as-is.
* If it was ad-hoc analytical work, point it at the reader endpoint.
* If it was application code, agree a role-level `statement_timeout` as a
  guardrail with that team (new sessions only; existing sessions unaffected):

```sql
ALTER ROLE <role_name> SET statement_timeout = '30s';
ALTER ROLE <role_name> RESET statement_timeout;   -- revert step
```

## Step 5 -- verify

Re-run `03_collateral_damage.sql`. Sessions that were blocked behind the runaway
should now be draining. If they are not, a second blocker exists and the incident
continues in `../lock-storm/README.md`.
