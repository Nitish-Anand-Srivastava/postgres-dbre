# 06_ddl_lock_remediation_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `06_ddl_lock_remediation_runbook.md` |
| Purpose | The guarded remediation runbook for draining a DDL lock queue and safely retrying the schema change. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- cancelling a waiting DDL is near-instant and low risk; terminating an application backend rolls back its transaction and may surface as an application error. |
| Required privileges | `pg_monitor` for the investigation. Cancelling or terminating another role's backend additionally requires membership in `pg_signal_backend`, or ownership of the target role. Resolving a prepared transaction requires the original transaction owner or superuser-equivalent privileges. |
| Prerequisites | Scripts 01-05 completed so the lock queue, the root blocker, and the affected relation are all identified, and authorization to cancel or terminate backends has been confirmed. |
| Execution order | Step 06 of workflow `schema-changes/ddl-lock-investigation` |
| Related scripts | 01_ddl_lock_waits.sql, 02_blocked_sessions_overview.sql |

## How to interpret / use this runbook

The ordering here is the whole point: cancel the waiting DDL first to restore service, then deal with the root blocker, then retry with a lock timeout. Reversing the first two steps means the application stays down while you negotiate with whoever owns the blocking session. Confirm every process identifier against the script output before acting on it, prefer cancelling over terminating, and never cancel an anti-wraparound autovacuum to unblock a schema change -- it is protecting the cluster from something considerably worse than a delayed migration. Substitute your real schema, table, and statement text into the step 3 template before retrying.

---

## Understand the mechanism before acting

```
  Session A: long-running SELECT on public.orders   -> holds AccessShareLock
  Session B: ALTER TABLE public.orders ...          -> WAITING for AccessExclusiveLock
  Session C: SELECT ... FROM public.orders          -> WAITING behind B
  Session D..Z: every later query on public.orders  -> WAITING behind B
```

Session C would not have conflicted with session A at all. It is blocked purely because PostgreSQL queues lock requests in order and B's pending exclusive request sits in front of it. **This is why the fastest fix is almost always to cancel B, not A.** B has done no work, so cancelling it costs nothing, and the queue drains within seconds.

---

## Step 1 -- cancel the pending DDL

```sql
-- Preferred: press Ctrl-C in the session running the DDL, or have the
-- deployment pipeline abort the migration step.
--
-- If that session is unreachable, an authorized operator can cancel it by
-- process id. Confirm the pid against 01_ddl_lock_waits.sql output first --
-- cancelling the wrong backend on a trading platform is its own incident.
-- Cancel (graceful, ends the statement, session survives):
--     SELECT pg_cancel_backend(<pid>);
-- Terminate (drops the connection entirely -- only if cancel does not work):
--     SELECT pg_terminate_backend(<pid>);
```

Always try cancel before terminate. A cancel ends the statement and lets the session clean up normally; a terminate drops the connection and usually surfaces as an application error.

Re-run `02_blocked_sessions_overview.sql` immediately afterwards. The queue should drain within seconds. If it does not, the pending DDL was not the head of the queue and you should re-read `04_lock_detail_by_mode.sql`.

## Step 2 -- deal with the root blocker

Now that service is restored, address the thing that made the DDL wait.

**If it is an application session (long-running or idle in transaction):** contact the owning team and have them close it through their application. This is always preferable to terminating it from the database side, because they know what work it was doing.

**If it is unreachable and the incident is ongoing:** terminate it with explicit authorization, having confirmed the pid. Note that terminating a long-running *write* transaction triggers a rollback that can itself take time and generate load.

**If it is an orphaned prepared transaction:**

```sql
-- Read-only first -- confirm it is genuinely orphaned, not a live two-phase
-- commit mid-flight. Anything older than a few minutes with no coordinator is
-- orphaned; it holds its locks indefinitely and survives restarts.
SELECT gid, prepared, owner, database FROM pg_prepared_xacts ORDER BY prepared;

-- Then, with the owning team's confirmation, resolve it:
--     ROLLBACK PREPARED '<gid>';
-- (or COMMIT PREPARED if the transaction is confirmed to have been intended to
-- commit -- on a financial table this decision is never the DBA's alone).
```

**If it is an anti-wraparound autovacuum: do not cancel it.** It does not yield the way ordinary autovacuum does, and it is preventing transaction ID wraparound, which is a far more serious outcome than a delayed schema change. Wait for it, and treat the underlying transaction age as the real problem.

## Step 3 -- retry the schema change safely

```sql
BEGIN;
  -- Never retry production DDL without this. With a short timeout the statement
  -- either gets its lock immediately or fails harmlessly, and can never form the
  -- queue that caused this incident.
  SET LOCAL lock_timeout = '3s';

  ALTER TABLE public.orders ADD COLUMN settlement_batch_id bigint;
COMMIT;
```

If it fails with `canceling statement due to lock timeout`, that is the system working exactly as intended. Wait a few seconds and retry in a loop -- on a busy table a clean window usually appears within a handful of attempts. Do **not** respond by raising the timeout; that reintroduces the original failure mode.

## Step 4 -- prevent the recurrence

- Set `idle_in_transaction_session_timeout` in the Aurora cluster parameter group so a leaked connection cannot hold locks indefinitely.
- Enforce `lock_timeout` for all DDL in the migration framework, not by convention.
- Enable `log_lock_waits` so the next occurrence is fully recorded and can be investigated after the fact rather than only live.
- Route long-running analytical and reporting queries to a reader so they cannot block writer DDL at all.
- Alert on long-running transactions and on any prepared transaction older than a few minutes.
