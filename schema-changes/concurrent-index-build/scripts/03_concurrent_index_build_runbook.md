# 03_concurrent_index_build_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_concurrent_index_build_runbook.md` |
| Purpose | The guarded DDL runbook for running a concurrent index build, with lock level, blocking risk, transaction behavior, rollback, and production considerations. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | The read-only investigation scripts for this workflow have been completed and reviewed; a change ticket exists; a second engineer is present; and the rollback path has been agreed before the first statement is executed. |
| Execution order | Step 03 of workflow `schema-changes/concurrent-index-build` |
| Related scripts | 04_monitor_build_progress.sql, 06_post_build_validity_check.sql |

## How to interpret / use this runbook

Work through the steps strictly in order and do not skip step 1 -- the transaction-block check catches the most common failure before it wastes hours. Substitute your real schema, table, index name, and column list into the template in step 3. The two things that most often go wrong are entirely preventable from this runbook: a framework-implicit transaction (step 1) and a statement_timeout firing mid-build (step 2). Budget for the possibility of abandonment and cleanup before you start, so that decision is not being made under pressure.

---

## Operation profile

| Property | Value |
|---|---|
| Lock level | `ShareUpdateExclusiveLock` on the target table |
| Blocks reads | No |
| Blocks writes | No |
| Blocks autovacuum on this table | **Yes, for the entire build** |
| Blocks other DDL on this table | Yes |
| Runs inside a transaction block | **No -- PostgreSQL rejects it** |
| Rollback | None. A failure leaves an INVALID index that must be dropped. |
| Restartable | No. A failed build starts again from the beginning. |

---

## Step 1 -- confirm you are not inside a transaction

```sql
-- In psql, this returns 'idle' when no transaction is open. Anything else
-- means you are inside a transaction block and the build will be rejected.
SELECT state, xact_start
FROM pg_stat_activity
WHERE pid = pg_backend_pid();
```

If you are driving this from a migration framework, disable its implicit
per-migration transaction for this step. The error you get otherwise is:

```
ERROR:  CREATE INDEX CONCURRENTLY cannot run inside a transaction block
```

This is the single most common reason concurrent builds fail in deployment
pipelines, and it is entirely preventable.

## Step 2 -- set session parameters

```sql
SET lock_timeout = '5s';
SET statement_timeout = 0;          -- the build must not be killed part-way
SET maintenance_work_mem = '2GB';   -- keep the sort in memory if possible
```

`statement_timeout = 0` for this session only. A timeout firing mid-build is the
most avoidable failure mode there is, and the cleanup it forces is more
disruptive than the build itself.

## Step 3 -- run the build

```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ledger_entries_account_id_posted_at
    ON public.ledger_entries (account_id, posted_at DESC);
```

- **Lock level:** `ShareUpdateExclusiveLock`. Application reads and writes are unaffected throughout.
- **Blocking risk:** the build blocks nothing in the application, but it does block autovacuum on this table for its entire duration. On a high-write table, a multi-hour build means multi-hour dead tuple accumulation -- check dead tuples after it completes.
- **Transaction behavior:** cannot run in a transaction block. Internally it runs several transactions and waits for older ones between phases, which is why it is slower and why it can stall on transactions that never touch this table.
- **Rollback:** none. Cancellation, timeout, session death, or an Aurora failover leaves an INVALID index behind that must be dropped before retrying.
- **Production considerations:** monitor Aurora reader lag throughout. Do not start a build immediately before a known market event, a deployment, or a scheduled failover test.

## Step 4 -- monitor while it runs

From a **second session** (the build session is busy), run
`04_monitor_build_progress.sql` repeatedly. Watch the `phase` column rather than
the percentages. If the phase does not change for a long period, run
`05_blocking_sessions_during_build.sql` to find the backend it is waiting on.

## Step 5 -- abandoning a build, if you must

```sql
-- Preferred: press Ctrl-C in the psql session running the build. That sends a
-- cancel request to that backend only and is the least disruptive option.
-- If the build session is unreachable, an authorized operator can cancel it by
-- pid using the standard cancellation function, but confirm the pid against
-- pg_stat_progress_create_index first and get a second pair of eyes on it --
-- cancelling the wrong backend on a trading platform is its own incident.
```

After any abandonment, **the cleanup is mandatory, not optional**: an INVALID
index is maintained by every write while being ignored by the planner, so leaving
it in place is strictly worse than never having started. Go to the
failed-index-build workflow.

## Step 6 -- validate

Run `06_post_build_validity_check.sql`. The index must report `indisvalid = true`
before the change can be recorded as successful.
