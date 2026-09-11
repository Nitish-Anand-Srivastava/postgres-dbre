# 06_rollback_decision_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_rollback_decision_runbook.md` |
| Purpose | The rollback decision itself: the schema-compatibility criteria that determine whether rolling back is recovery or a second incident, plus the guarded actions for each branch. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | The specific instance hosting the target backend -- `pg_cancel_backend()` / `pg_terminate_backend()` only affect backends on the instance you are currently connected to, so connect to the writer, or to the specific reader, where the session actually lives. |
| Safety | ELEVATED RISK -- MANUAL EXECUTION ONLY, CANCELS A STATEMENT OR ROLLS BACK THE TARGET TRANSACTION (read every warning in this file first) |
| Expected impact | Cancelling a waiting migration rolls that DDL back cleanly with no data change. Rollback and index cleanup are change-managed operations with their own, separately documented impact. |
| Required privileges | Reading the investigation output requires only `pg_monitor`. Ending another session additionally requires membership in `pg_signal_backend` (or, on Aurora, `rds_superuser`): a plain `pg_monitor` role can see the offending backend but cannot cancel or terminate it. Dropping an index additionally requires ownership of the index or its table. |
| Prerequisites | Scripts 01-05 completed, the migration list and its reversibility confirmed with the deploying team, and a named decision owner for the rollback call. |
| Execution order | Step 06 of workflow `incident-response/post-deployment-incident` |
| Related scripts | 02_migration_lock_waits.sql, 03_index_build_state.sql, 05_statistics_and_scan_regression.sql |

## How to interpret / use this runbook

The decision table at the top is the point of this file. Answer the schema-compatibility question before considering any action -- rolling back past an applied destructive migration causes a data-integrity incident that is far more expensive than the outage you are trying to end.

---

## The decision this file exists for

Rollback is usually the fastest path to recovery, and the default bias should be
toward it. The one thing that can make rollback *worse* than the incident is a
schema migration that has already been applied. Answer this question before
anything else:

> **Can the previous application version run correctly against the schema as it
> exists right now?**

| Migration state | Rollback safe? | Action |
|---|---|---|
| No migration in this release | Yes | Roll back now. |
| Migration is additive only (new nullable column, new table, new index) | Yes | Roll back now; the old code simply ignores the additions. |
| Migration never started, or is still waiting on a lock | Yes | Cancel the DDL (Action A), then roll back. |
| Migration applied, and is reversible with a tested down-migration | Usually | Roll back code first, then reverse the migration deliberately -- never both at once. |
| Migration applied and destructive (column or table dropped, type narrowed, constraint tightened) | **No** | Do NOT roll back. Fix forward, and escalate now. |
| Migration half-applied on a financial table | **No** | Stop. Escalate to database engineering leadership and treasury immediately. |

Get the answer from the deploying team's migration list, not from memory. If
nobody can say confidently which row applies, that uncertainty is itself an
escalation trigger.

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

## Action A -- cancel a migration that is blocking traffic

*Precondition: script 02 shows a DDL statement with `granted = false` and other
sessions queued behind it.*

Cancel the DDL, not the application transaction it is waiting on. A DDL statement
that has not obtained its lock has changed no data, so cancelling it is clean and
instantly drains the queue behind it:

```sql
SELECT pg_cancel_backend(<migration pid from script 02>);
```

Then tell the deploying team not to retry until the migration has a `lock_timeout`
and uses the concurrent, lock-light pattern -- an immediate retry recreates this
incident exactly, usually within a minute.

## Action B -- roll back the application

*Precondition: the table above says rollback is safe.*

Roll back through your normal deployment mechanism. From the database side, watch
`01_workload_by_application_and_session_age.sql` as the old fleet reconnects: the
new session group should drain and the previous one reappear. Confirm blocked_count
returns to zero for the affected services before declaring recovery.

## Action C -- fix forward when rollback is unsafe

*Precondition: the table above says rollback is not safe.*

Options, in order of preference:

1. Disable the offending code path with a feature flag. Fastest, and fully
   reversible.
2. Add the missing index the new query needs -- built concurrently, never with a
   blocking build during an incident. Follow
   `../../schema-changes/failed-index-build/README.md`.
3. Analyse the specific tables a backfill touched, so the planner's estimates
   catch up. Target the named tables from script 05; do not analyse the whole
   database during an incident.

## Action D -- clean up after a failed index build

*Precondition: script 03 listed invalid indexes created during this release.*

An invalid index is never used by the planner but still consumes storage and slows
every write to its table, so it must be removed -- deliberately, and normally in a
change-managed window rather than mid-incident. The concurrent form avoids taking
a blocking lock on the table:

```sql
-- Verify the index is genuinely invalid and genuinely from this release first,
-- using script 03. Dropping the wrong index during an incident is its own outage.
DROP INDEX CONCURRENTLY <schema>.<index_name>;
```

On Aurora, the space is returned to the cluster volume for reuse but the volume
itself does not shrink, so this recovers usable capacity rather than billed
storage.

## Record the decision

Write down which row of the table applied, who confirmed the migration state, and
what was decided. Post-deployment incidents are re-litigated in review more than
any other kind, and the migration-state evidence is what makes that review useful
instead of speculative.
