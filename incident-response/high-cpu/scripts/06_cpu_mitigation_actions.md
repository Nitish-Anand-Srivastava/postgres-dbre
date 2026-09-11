# 06_cpu_mitigation_actions

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_cpu_mitigation_actions.md` |
| Purpose | Guarded runbook for cutting CPU load fast: cancelling the dominant sessions, stopping a retry storm, deferring maintenance, and deciding to scale. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | The specific instance hosting the target backend -- `pg_cancel_backend()` / `pg_terminate_backend()` only affect backends on the instance you are currently connected to, so connect to the writer, or to the specific reader, where the session actually lives. |
| Safety | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) |
| Expected impact | Cancelling aborts the target statement only. A role-level timeout makes that role's long statements fail fast by design. Scaling a writer requires a failover window. |
| Required privileges | Reading the investigation output requires only `pg_monitor`. Ending another session additionally requires membership in `pg_signal_backend` (or, on Aurora, `rds_superuser`): a plain `pg_monitor` role can see the offending backend but cannot cancel or terminate it. |
| Prerequisites | Scripts 01-05 completed, with script 02 confirming the load is genuinely CPU-bound rather than lock or IO wait. |
| Execution order | Step 06 of workflow `incident-response/high-cpu` |
| Related scripts | 03_top_active_queries_now.sql, 05_maintenance_competing_for_cpu.sql |

## How to interpret / use this runbook

Take one action, re-measure, then decide the next. Each action names the script output that must be true first; without that evidence the action is a guess, and guesses during CPU saturation usually cost more CPU.

---

## Order of operations

Do the cheapest reversible thing first. Cancelling a query is reversible (it can
be rerun); scaling an instance is not free; restarting is never the answer.

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

## Action A -- cancel the dominant sessions

*Precondition: script 03 shows a small number of sessions with runtimes far above
everything else, and script 02 confirmed they are not merely waiting.*

```sql
SELECT pg_cancel_backend(<pid from script 03>);
```

Re-run script 03 after each cancel. If CPU does not move, the statement you
cancelled was not the cause -- stop cancelling and go back to the evidence.

## Action B -- stop a retry storm

*Precondition: the same statement shape immediately reappears from new pids after
each cancel, and script 04 shows a very high calls count with a small mean.*

You cannot win this from the database side: the application is generating work
faster than you can cancel it. Escalate to the owning service and ask for one of:

* the feature flag or code path disabled,
* the retry policy switched to exponential backoff with jitter and a cap,
* the service scaled down temporarily to reduce its request rate.

As a database-side holding measure only, and only with that team's agreement, a
role-level timeout makes the storm fail fast instead of accumulating:

```sql
ALTER ROLE <role_name> SET statement_timeout = '2s';   -- new sessions only
ALTER ROLE <role_name> RESET statement_timeout;        -- revert step
```

## Action C -- defer competing maintenance

*Precondition: script 05 shows vacuum workers or an index build on large tables
during peak traffic.*

Cancelling an autovacuum worker is safe in the narrow sense -- autovacuum simply
reschedules the table -- but it is the wrong reflex if the table's dead-tuple
percentage is already high, and it is actively dangerous if the vacuum is running
to prevent transaction-ID wraparound (check `../../transactions-and-xid/`
before touching an anti-wraparound vacuum; those must be allowed to finish).

```sql
SELECT pg_cancel_backend(<autovacuum worker pid from script 05>);
```

A user-initiated index build or backfill is the better target: pause it at its
own scheduler so it does not immediately restart.

## Action D -- scale

*Precondition: the workload is legitimate, no single statement dominates, and the
instance is simply too small for current demand.*

Adding a reader and shifting read traffic is the lower-risk move and needs no
failover. Resizing the writer's instance class requires a failover, so it costs a
write-unavailability window and a cold cache -- it needs the approval named in
your escalation policy and is rarely the right action while an incident is live.

## What not to do

* Do not terminate backends in bulk. Every client reconnects at once, and
  connection setup is itself CPU work -- the curve gets worse before it gets
  better.
* Do not run `ANALYZE` across the whole database as a blind fix. It adds load now
  and rarely addresses the statement actually burning the CPU.
* Do not reboot. You will lose the buffer cache and the in-flight order writes,
  and the workload returns within seconds against a cold instance.
