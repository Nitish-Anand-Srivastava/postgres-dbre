# 06_reclaim_connection_slots

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_reclaim_connection_slots.md` |
| Purpose | Guarded runbook for reclaiming connection slots safely and for applying a per-role connection limit so they do not immediately refill. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | The specific instance hosting the target backend -- `pg_cancel_backend()` / `pg_terminate_backend()` only affect backends on the instance you are currently connected to, so connect to the writer, or to the specific reader, where the session actually lives. |
| Safety | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) |
| Expected impact | Terminating an idle session drops one pooled connection. Terminating an idle-in-transaction session additionally rolls back its open transaction. A role connection limit causes new connections above the limit to be refused by design. |
| Required privileges | Reading the investigation output requires only `pg_monitor`. Ending another session additionally requires membership in `pg_signal_backend` (or, on Aurora, `rds_superuser`): a plain `pg_monitor` role can see the offending backend but cannot cancel or terminate it. |
| Prerequisites | Scripts 01-05 completed, the owning service identified from script 03, and agreement from that team before any role-level limit is applied. |
| Execution order | Step 06 of workflow `incident-response/connection-exhaustion` |
| Related scripts | 01_connection_headroom.sql, 04_long_idle_sessions.sql, 05_idle_in_transaction_sessions.sql |

## How to interpret / use this runbook

Reclaim in the documented order, one pid at a time, re-measuring headroom as you go. If headroom does not improve after a reclaim round, stop terminating and fix demand instead -- more terminations will not help.

---

## Reclaim in order of increasing risk

1. Plain `idle` sessions, oldest first (script 04).
2. `idle in transaction` sessions that are also blocking others (script 05).
3. `idle in transaction` sessions that are not blocking anyone.
4. Nothing else. Active sessions are doing work for customers; if they are the
   problem, the answer is the latency workflow, not a termination.

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

## Action A -- reclaim idle slots

Re-list the candidates immediately before acting -- a list from two minutes ago
is already stale, and pids get reused:

```sql
SELECT pid, usename, application_name, client_addr,
       now() - state_change AS idle_duration
FROM pg_stat_activity
WHERE state = 'idle'
  AND backend_type = 'client backend'
  AND pid <> pg_backend_pid()
  AND application_name = '<application_name from script 03>'
ORDER BY idle_duration DESC;
```

Then, one pid at a time:

```sql
SELECT pg_terminate_backend(<pid>);
```

Re-run script 01 after every few reclaims. If pct_utilized does not fall, the
slots are refilling as fast as you free them and the fix is Action C, not more
terminations.

**Do not** write a statement that terminates all matching sessions at once. Mass
simultaneous reconnection is a second incident, and connection setup is itself
expensive -- you will spike CPU on an instance that is already in trouble.

## Action B -- reclaim idle-in-transaction slots

*Precondition: script 05 listed them, and you have checked whether each one is
blocking other sessions.*

Terminating these rolls back whatever the transaction had already done. For a
session whose last statement touched a financial table, the financial-write
safety gate above applies in full -- get the owning team's confirmation first.

```sql
SELECT pg_terminate_backend(<pid from script 05>);
```

(A cancel does not help here: there is no statement running to cancel. The
session is idle *inside* a transaction, so only a terminate ends it.)

## Action C -- stop the slots refilling

Reclaiming without reducing demand is a treatment, not a cure. Do both:

* Ask the owning service to reduce its pool size or scale in replicas now.
* Apply a per-role connection limit as an incident-scoped guardrail. This affects
  only NEW connections for that role; existing sessions are untouched. Agree it
  with the owning team first -- their service will start seeing connection
  errors by design, which is the point:

```sql
-- Choose a limit that leaves the rest of the fleet room to breathe.
ALTER ROLE <role_name> CONNECTION LIMIT 50;

-- Revert step, to be run once the service's own pool configuration is fixed:
ALTER ROLE <role_name> CONNECTION LIMIT -1;
```

Never apply a connection limit to a role used by settlement, withdrawal or
reconciliation processing without explicit treasury-side agreement: blocking
those connections trades a connection incident for a funds-movement incident.

## Verify

Re-run `01_connection_headroom.sql`. You are done when pct_utilized is back
below roughly 80% and stays there across two consecutive checks a minute apart.
A number that falls and immediately climbs again means demand, not leakage, and
the durable fix lives in `../../connections/connection-exhaustion/README.md`.
