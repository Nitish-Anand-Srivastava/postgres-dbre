# 07_latency_mitigation_actions

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `07_latency_mitigation_actions.md` |
| Purpose | Guarded runbook for the actions that actually cut a latency spike short: cancelling the dominant work, shedding non-critical load, and time-boxing statements. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | The specific instance hosting the target backend -- `pg_cancel_backend()` / `pg_terminate_backend()` only affect backends on the instance you are currently connected to, so connect to the writer, or to the specific reader, where the session actually lives. |
| Safety | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) |
| Expected impact | Cancelling a statement aborts that statement only; a role-level timeout change causes the affected service's long statements to fail fast by design. |
| Required privileges | Reading the investigation output requires only `pg_monitor`. Ending another session additionally requires membership in `pg_signal_backend` (or, on Aurora, `rds_superuser`): a plain `pg_monitor` role can see the offending backend but cannot cancel or terminate it. |
| Prerequisites | Scripts 01-06 completed and a dominant cause identified; owning-team agreement for any configuration change. |
| Execution order | Step 07 of workflow `incident-response/sudden-latency-spike` |
| Related scripts | 03_longest_active_queries.sql, 04_blocking_snapshot.sql |

## How to interpret / use this runbook

Match the action to the evidence, take one action at a time, and re-run scripts 01-04 after each one. Acting on two hypotheses simultaneously makes it impossible to know which change helped.

---

## Pick the action that matches what scripts 01-06 showed

A latency spike has exactly four realistic immediate responses. Choosing the
wrong one costs minutes you do not have, so match the evidence first.

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

## Action A -- blocking dominates (script 04 returned rows)

Do not tune anything. Go to `../lock-storm/README.md`, find the root blocker,
and clear it. Latency across every affected service normally returns within
seconds of the wait graph draining.

## Action B -- one statement dominates (script 03 or 06)

Confirm the owning service from `application_name`, then cancel the worst
offender -- one pid at a time:

```sql
SELECT pg_cancel_backend(<pid from script 03>);
```

If the same statement shape immediately reappears from many sessions, cancelling
individual backends is pointless: the application is generating it in a loop.
Ask the owning team to disable that code path or feature flag, which is the only
action that actually stops it.

## Action C -- shed non-critical load

*Precondition: scripts 01 and 02 show high, broadly distributed activity with no
single dominant statement and no blocking.*

Shed in this order, never the reverse: reporting and analytics, then backfills
and reconciliation jobs, then non-trading product features, and only then
anything on the order, wallet or settlement path. Pause the job at its own
scheduler where possible -- that is cleaner than cancelling its database
sessions, which most schedulers will simply retry.

If an index build or bulk maintenance operation is running, pausing it is almost
always correct: it can rerun tonight, the trading day cannot.

## Action D -- time-box new work so the spike cannot deepen

*Precondition: latency is caused by a small number of statements that the
application keeps re-issuing, and the owning team needs time to ship a fix.*

A role-level statement timeout makes those statements fail fast instead of
queueing, which frees connections and stabilizes everything else. This is a real
configuration change affecting live traffic, so it needs the owning team's
agreement first -- their service will start receiving errors by design:

```sql
-- Applies to NEW sessions of that role only; existing sessions are unaffected.
ALTER ROLE <role_name> SET statement_timeout = '5s';
```

Record it as an incident-scoped change with an explicit owner and a revert step:

```sql
ALTER ROLE <role_name> RESET statement_timeout;
```

Never apply a blanket statement timeout to every role mid-incident. Settlement
and reconciliation jobs legitimately run long, and killing them halfway creates a
financial-integrity problem that is far more expensive than the latency.

## After the spike clears

Capture the evidence while it still exists: the queryids from script 06, the
wait-event mix from script 02, and the exact minute the step change started.
pg_stat_activity keeps nothing once sessions end, and without that evidence the
follow-up investigation restarts from zero.
