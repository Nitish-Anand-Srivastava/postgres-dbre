# Lock Storm

**Category:** Incident Response | **Workflow:** `incident-response/lock-storm`

## 1. Problem Description

A large number of sessions are simultaneously waiting on locks, so the database is up and has plenty of CPU but is effectively frozen for the affected tables. Order writes, balance updates and ledger inserts queue behind a wait graph that is usually rooted in one or two sessions. This workflow finds that root within minutes and clears it safely.

## 2. Typical Symptoms

- A sudden cliff in throughput with CPU falling rather than rising -- the instance is idle because everything is waiting.
- Many sessions with `wait_event_type = 'Lock'` in pg_stat_activity, all stacked on a small number of relations.
- Application timeouts concentrated on one table or one feature (order placement, balance update) while unrelated features work normally.
- A queue of sessions that grows monotonically and does not drain on its own.
- The incident started at a discrete moment, often correlated with a migration, a batch job, or a long-running transaction opening.

## 3. Business Impact

- Writes to the order book and ledger stop entirely for the affected tables, so customers cannot place, amend or cancel orders on those markets.
- Because the queue grows rather than drains, a lock storm reliably escalates into connection exhaustion within minutes -- one incident becomes two.
- Settlement and reconciliation jobs blocked mid-run leave partially applied batches that need manual verification even after the storm clears.

## 4. Possible Root Causes

- One long-running or idle-in-transaction session holding a lock that a hot code path needs on every request.
- A DDL statement (ALTER TABLE, non-concurrent CREATE INDEX, TRUNCATE) taking or waiting for an AccessExclusiveLock on a hot table, so every subsequent query queues behind its lock request.
- Hot-row contention that crossed a tipping point: the same row (a market's summary row, a shared counter, an omnibus wallet balance) updated by more concurrent transactions than it can serialize.
- A batch job taking row locks across a wide range in a single transaction rather than in small committed chunks.
- An unindexed foreign key or filter column causing an UPDATE or DELETE to lock far more rows than the business logic intended.
- A deploy that changed lock-acquisition order between two code paths, converting occasional contention into a persistent pile-up.

## 5. Investigation Strategy

1. Size the storm first: how many sessions are waiting, and on what wait-event types. This distinguishes a genuine lock storm from general slowness.
2. List the blocked sessions and their blocking pids.
3. Rank the blockers by blast radius and, critically, identify which of them are true roots -- blockers that are not themselves blocked.
4. Inspect the lock detail so you know exactly which relation and lock mode is at the centre of the storm.
5. Check specifically for DDL-strength locks and for very old transactions, which are the two most common roots.
6. Clear the root: cancel first, terminate only if cancel fails and the safety gate is satisfied.

## 6. Prerequisites

- `pg_monitor` role membership, plus `pg_signal_backend` (or `rds_superuser`) to clear a blocker.
- A connection that is not itself blocked -- connect and confirm you can run a trivial query before starting.
- Knowledge of which tables are on the trading and funds-movement hot path, so you can judge the blast radius correctly.
- `log_lock_waits` enabled in the parameter group is strongly recommended, so the storm is also reconstructable from CloudWatch Logs afterwards.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_lock_wait_scale.sql`](scripts/01_lock_wait_scale.sql) -- Sizes the storm: how many backends are waiting, on what, and for how long.
2. [`scripts/02_blocked_sessions.sql`](scripts/02_blocked_sessions.sql) -- Lists every session currently blocked and the pids blocking it, using the queue-order-aware pg_blocking_pids() helper.
3. [`scripts/03_root_blockers_by_blast_radius.sql`](scripts/03_root_blockers_by_blast_radius.sql) -- Collapses the wait graph to the handful of blockers that matter, and identifies which of them are true roots.
4. [`scripts/04_lock_detail_at_the_root.sql`](scripts/04_lock_detail_at_the_root.sql) -- Shows the exact relations and lock modes at the centre of the storm.
5. [`scripts/05_ddl_and_old_transactions.sql`](scripts/05_ddl_and_old_transactions.sql) -- Checks the two most common storm roots: a DDL statement queued on a strong lock, and a very old open transaction.
6. [`scripts/06_clear_the_root_blocker.md`](scripts/06_clear_the_root_blocker.md) -- Guarded runbook for clearing the root of a lock storm: cancel first, terminate only when justified, and verify the graph actually drained.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Lock waits are instance-local: a storm on the writer is invisible on the readers, so always confirm which instance you are connected to before concluding that a cluster is or is not affected.
- Aurora exports lock-wait log lines (when log_lock_waits is enabled) to CloudWatch Logs rather than to a local file, which makes CloudWatch Logs Insights the place to reconstruct the storm's timeline after the fact -- pg_locks retains nothing once the waits clear.
- Aurora Performance Insights attributes waiting time to the Lock wait-event class in its Average Active Sessions chart, which is usually the fastest way to establish the exact minute the storm started and whether it has genuinely ended.

## 8. Interpretation Guide

- The key column in the blast-radius ranking is blocker_is_itself_blocked_by_count. Zero means a true root: clearing it releases the chain. Non-zero means a middle link, and clearing it accomplishes nothing.
- A blocker whose state is `idle in transaction` is the safest and most satisfying target: it is doing no work at all while holding everyone up.
- A blocker that is `active` and legitimately executing needs owner coordination -- it may be a settlement run whose rollback is more expensive than the storm.
- A DDL statement with granted = false is a special and very common case: the DDL is itself waiting, and every query that arrived after it is queued behind its lock request. Cancelling the DDL is usually the cheapest possible fix and is entirely safe.
- Many waiters on the same relation with the same lock mode means the storm is structural (hot row or hot table), so expect it to recur until the data model or access pattern changes.
- If the blocked count is large but the blocker set is empty, the sessions are waiting on something other than a heavyweight lock -- re-read the wait-event types before acting.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Cancel the true root blocker. For a waiting DDL statement this is both the fastest and the safest action, because a cancelled DDL rolls back cleanly with no data change.
- If cancel does not clear it within about 15 seconds and the financial-write safety gate is satisfied, terminate the root blocker.
- If the root is a batch job, stop the job at its scheduler as well, or it will simply reopen the same transaction and restart the storm.
- After the chain drains, immediately re-check connection headroom: a lock storm usually leaves connection pressure behind it.

**Short-term remediation** (hours to days):

- Set `lock_timeout` for the roles that run DDL and batch work, so a statement that cannot get its lock fails fast instead of blocking everything behind it.
- Set `idle_in_transaction_session_timeout` for application roles so an abandoned transaction cannot become a storm root.
- Convert the offending DDL to the concurrent, lock-light pattern documented in the schema-changes category before it is retried.
- Break wide-range batch updates into small committed chunks ordered by primary key.

**Long-term engineering fix** (days to weeks):

- Redesign the hot-row patterns behind repeat storms -- shard a global counter, or move to an append-only ledger with periodic aggregation instead of in-place updates on one row.
- Make a lock-risk review mandatory for every migration touching a hot table, with the expected lock mode and duration stated in the change request.
- Add monitoring on blocked-session count with alerting well below the level at which customers notice, so a storm is caught while it is still a chain of three.

## 10. Production Safety

- Scripts 01-05 are read-only and safe to run during the storm; they add negligible load, and pg_blocking_pids() is the correct, queue-order-aware way to read the wait graph.
- Script 06 ends sessions and must be read fully first.
- Never terminate blockers in bulk to 'clear the graph'. You will roll back legitimate transactions you have not identified, and on a ledger or wallet table that creates a reconciliation problem far worse than the storm.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The root blocker is a system or replication process rather than an application backend -- escalate to database engineering and do not signal it.
- The chain does not clear after the identified root is resolved, which means a second root exists and the graph needs re-reading rather than more terminations.
- The blocker is a settlement, withdrawal or reconciliation transaction whose rollback has financial consequences -- escalate to treasury and compliance before acting, even if that means the storm runs longer.
- Storms on the same relation recur more than once in a week -- escalate as a structural data-model issue rather than continuing to treat each occurrence as an incident.

## 12. Related Issues

- [production-triage](../production-triage/README.md)
- [database-unavailable](../database-unavailable/README.md)
- [application-timeouts](../application-timeouts/README.md)
- [post-deployment-incident](../post-deployment-incident/README.md)
- [blocked-queries](../../concurrency-and-locking/blocked-queries/README.md)
- [failed-index-build](../../schema-changes/failed-index-build/README.md)
