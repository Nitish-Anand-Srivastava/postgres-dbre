# DDL Blocking Application Traffic

**Category:** Locking and Concurrency | **Workflow:** `concurrency-and-locking/ddl-blocking`

## 1. Problem Description

A DDL statement (ALTER TABLE, CREATE INDEX without CONCURRENTLY, VACUUM FULL, TRUNCATE) is holding or waiting for a strong lock (e.g. AccessExclusiveLock) that blocks a wide swath of normal application queries -- the classic 'one migration takes down the app' incident.

## 2. Typical Symptoms

- A sudden, near-total stall of queries against one specific table.
- A migration/deployment step correlates with the stall's onset.
- Many sessions blocked simultaneously on the same relation.

## 3. Business Impact

- DDL-driven stalls typically block ALL access (reads and writes) to the affected table, unlike a typical row-level contention issue -- this is often the most severe form of concurrency incident.

## 4. Possible Root Causes

- A non-concurrent index build/rebuild on a live production table.
- An ALTER TABLE that requires a full table rewrite (adding a column with a volatile default pre-PG11 semantics, changing a column type) taking AccessExclusiveLock for the duration.
- The DDL statement itself is queued behind a long-running transaction, and every subsequent query queues up behind the DDL's own lock request (DDL doesn't need to be running long to cause this -- it just needs to be waiting).

## 5. Investigation Strategy

1. Identify the DDL statement itself: is it running, or is it waiting for a lock?
2. If waiting, identify what it is waiting on (typically an old long-running transaction).
3. Quantify how many sessions are now queued behind the DDL.
4. Decide: wait for the blocker to finish, cancel the DDL, or (in the worst case) terminate the underlying blocker.

## 6. Prerequisites

- pg_monitor role membership.
- Direct communication channel with whoever initiated the DDL/deployment.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_ddl_style_lock_waits.sql`](scripts/01_ddl_style_lock_waits.sql) -- Identifies sessions holding or waiting for strong (DDL-style) lock modes and whether the DDL itself is granted or queued.
2. [`scripts/02_who_is_queued_behind_ddl.sql`](scripts/02_who_is_queued_behind_ddl.sql) -- Shows every other session now queued behind the DDL statement's own lock request.
3. [`scripts/03_root_blocker_of_ddl.sql`](scripts/03_root_blocker_of_ddl.sql) -- Identifies the original long-running transaction that the DDL statement itself is waiting on.

## 8. Interpretation Guide

- Because lock requests queue strictly in arrival order, a DDL statement waiting for a lock will itself block all subsequent queries against that table, even queries that would not conflict with each other -- this is why a single blocked ALTER TABLE can look like a full table outage.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Cancel the DDL statement itself (`SELECT pg_cancel_backend(<ddl_pid>);`) to immediately drain the queue if the DDL cannot be allowed to keep waiting -- this is generally safer than terminating the underlying long-running blocker.
- If cancelling the DDL is not acceptable, resolve the underlying blocking transaction per blocked-queries.

**Short-term remediation** (hours to days):

- Always use `CREATE INDEX CONCURRENTLY` / `DROP INDEX CONCURRENTLY` / `ALTER TABLE ... ADD CONSTRAINT ... NOT VALID` + `VALIDATE CONSTRAINT` patterns for production DDL (see schema-changes/).
- Set a conservative `lock_timeout` for the session running planned DDL so it fails fast instead of queuing indefinitely and blocking others.

**Long-term engineering fix** (days to weeks):

- Adopt a mandatory pre-deployment DDL lock-risk review (see schema-changes/ddl-lock-investigation) for every migration touching a hot table.

## 10. Production Safety

- Cancelling a DDL statement is safe (it rolls back cleanly, no data change was committed); always prefer cancelling the DDL over terminating an unrelated long-running application transaction unless the DDL is time-critical.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The DDL is part of an in-progress deployment and cannot be simply cancelled without breaking application compatibility -- escalate to the deploying team immediately to decide between waiting, cancelling, or rolling back the deployment.

## 12. Related Issues

- [blocked-queries](../blocked-queries/README.md)
- [ddl-lock-investigation](../../schema-changes/ddl-lock-investigation/README.md)
- [safe-index-creation](../../schema-changes/safe-index-creation/README.md)
