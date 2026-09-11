# 04_cleanup_invalid_index_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_cleanup_invalid_index_runbook.md` |
| Purpose | The guarded DDL runbook for removing an INVALID index left by a failed build, with lock level, blocking risk, transaction behavior, and rollback documented. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). |
| Prerequisites | Scripts 01-03 completed, and `02_builds_currently_running.sql` has confirmed no index build is in progress for the target index. The read-only investigation scripts for this workflow have been completed and reviewed; a change ticket exists; a second engineer is present; and the rollback path has been agreed before the first statement is executed. |
| Execution order | Step 04 of workflow `schema-changes/failed-index-build` |
| Related scripts | 02_builds_currently_running.sql, 05_verify_cleanup.sql |

## How to interpret / use this runbook

Step 1 and the mandatory gate above it are the parts that matter; the drop itself is the easy bit. Confirm no build is running, confirm the exact index name, then drop it concurrently. Everything downstream of the drop -- the duplicate-key investigation in step 4 and the vacuum in step 5 -- is about making sure the retry succeeds where the original attempt did not, so do not skip straight back to rebuilding. Substitute your real schema and index names into every statement before running it.

---

## Before you run anything

**Mandatory gate:** `02_builds_currently_running.sql` must show no build in
progress for the index you are about to drop. An in-flight build's index is
legitimately invalid until it completes; dropping it destroys hours of work and
forces a restart from scratch. This is the only genuinely destructive mistake
available in this workflow, and it is entirely avoidable by running that script
first.

## Operation profile

| Property | `DROP INDEX CONCURRENTLY` | `DROP INDEX` (plain) |
|---|---|---|
| Lock level | `ShareUpdateExclusiveLock` | `AccessExclusiveLock` |
| Blocks reads | No | **Yes** |
| Blocks writes | No | **Yes** |
| Runs inside a transaction block | **No -- rejected** | Yes |
| Rollback | None once it proceeds | Clean -- `ROLLBACK` undoes it |
| Use on production | **Default choice** | Only inside a rehearsal transaction |

---

## Step 1 -- identify the exact index

```sql
-- Read the full name and definition from 01_invalid_indexes.sql output and
-- confirm it is the one you mean. Index names are easy to confuse when a build
-- has been retried several times and left several near-identical leftovers.
SELECT n.nspname, i.relname, ix.indisvalid, ix.indisready,
       pg_get_indexdef(ix.indexrelid)
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE NOT ix.indisvalid;
```

## Step 2 -- drop it concurrently

```sql
-- Must NOT be inside BEGIN/COMMIT. PostgreSQL rejects it with:
--   ERROR:  DROP INDEX CONCURRENTLY cannot run inside a transaction block
-- The same restriction, and the same framework pitfall, as the concurrent
-- create. Only one index per statement is allowed in the concurrent form.
SET lock_timeout = '5s';
DROP INDEX CONCURRENTLY IF EXISTS public.idx_ledger_entries_account_id_posted_at;
```

- **Lock level:** `ShareUpdateExclusiveLock` on the parent table. Application reads and writes proceed normally.
- **Blocking risk:** minimal. Like the concurrent create, it waits for transactions older than its phase boundaries, so a long-running transaction can delay it -- but it blocks nothing itself.
- **Transaction behavior:** cannot run inside a transaction block, and cannot name more than one index.
- **Rollback:** none once it proceeds. This is acceptable here precisely because the object being removed is INVALID and therefore provides no query benefit -- there is nothing to regress.
- **Production considerations:** safe at any time of day. This is one of the few changes in this category that does not need a window.

## Step 3 -- handle a `REINDEX CONCURRENTLY` leftover

An index named `..._ccnew`, `..._ccnew1` and so on is the transient index from an
interrupted `REINDEX CONCURRENTLY`. The original index is still present and
valid, so the leftover is always safe to drop once no reindex is running:

```sql
DROP INDEX CONCURRENTLY IF EXISTS public.idx_trades_account_id_ccnew;
```

## Step 4 -- if the failure was a duplicate key

If the original build was a unique index that failed on a duplicate key, **do not
simply retry**. The duplicate rows are a real data-integrity finding. Identify
them, involve the owning team, and resolve the data before rebuilding:

```sql
-- Read-only: find the offending duplicate values first. Adapt the column list
-- to the proposed unique index definition.
SELECT account_id, external_reference, count(*)
FROM public.deposits
GROUP BY account_id, external_reference
HAVING count(*) > 1
ORDER BY count(*) DESC
LIMIT 50;
```

On an exchange, duplicates in a deposits, withdrawals, or ledger table are a
financial-correctness issue, not a schema inconvenience. Escalate rather than
deleting rows to make an index build succeed.

## Step 5 -- vacuum if the build ran long

A concurrent build holds a lock that blocks autovacuum on the table for its whole
duration. After a long failed build, dead tuples have usually accumulated:

```sql
-- Plain VACUUM only. Never VACUUM FULL on a production exchange table: it takes
-- an AccessExclusiveLock for its entire duration and, on Aurora, returns nothing
-- to the cluster volume anyway.
VACUUM (VERBOSE, ANALYZE) public.ledger_entries;
```

## Step 6 -- retry only after the cause is fixed

Return to the concurrent-index-build workflow. Do not retry with the same session
settings and the same blocking transactions still present -- that simply produces
another leftover and another cleanup.
