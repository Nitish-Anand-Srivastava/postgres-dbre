# Pre-Deployment Health Check

**Category:** Database Health Checks | **Workflow:** `database-health/pre-deployment-check`

## 1. Problem Description

The go/no-go gate run in the minutes immediately before a release, schema migration, or parameter change reaches production. It answers one question: is the database in a state where this deployment can proceed safely right now? A migration that would take a millisecond on a quiet cluster can take an AccessExclusiveLock queue hostage and halt order matching for minutes if it lands while a long transaction, a lock wait, or a vacuum is already in flight -- this check catches exactly that.

## 2. Typical Symptoms

- No active symptom -- this is a scheduled gate immediately before a deployment window opens.
- Run again after an aborted or rolled-back deployment attempt, before retrying.
- Run before any change-managed parameter-group change that requires a reboot or failover.

## 3. Business Impact

- A DDL statement that queues behind a long-running transaction takes an AccessExclusiveLock request that then blocks every subsequent query on that table -- on an orders or wallets table this halts trading and withdrawals within seconds, even though the DDL itself never actually started.
- Deploying into an already-degraded database makes root-causing the resulting incident far harder: the team cannot tell whether the deployment caused the problem or merely arrived during it.
- A pre-deployment baseline of query performance is what makes the post-deployment comparison meaningful; without it, 'is this slower than before?' is unanswerable.

## 4. Possible Root Causes

- Not a failure workflow -- these are the pre-existing conditions that make a deployment unsafe at this moment.
- A long-running transaction or idle-in-transaction session that a migration's lock request would queue behind, blocking all subsequent traffic to the table.
- An in-flight autovacuum on the target table, which holds a ShareUpdateExclusiveLock that conflicts with most ALTER TABLE forms.
- Insufficient connection headroom to absorb the connection churn of a rolling application restart.
- Elevated reader lag, which a deployment's extra WAL generation will make worse and which breaks read-your-own-write behavior for users mid-deploy.

## 5. Investigation Strategy

1. Confirm no session is currently blocked and no lock wait chain exists.
2. Check specifically for strong lock modes (ShareUpdateExclusive and above) that a migration would have to queue behind.
3. Check for long-running and idle-in-transaction sessions that would make a DDL lock request block the world.
4. Confirm connection headroom is sufficient to absorb a rolling restart of the application fleet.
5. Confirm reader lag is at its normal baseline before adding deployment write volume.
6. Confirm no autovacuum or maintenance operation is in flight on the tables the migration will touch.
7. Capture a query-performance baseline so post-deployment-check has something to compare against.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- The list of tables the deployment's migrations will touch, so the lock and vacuum checks can be read with the right focus.
- An agreed abort threshold for each check, decided before the window opens rather than negotiated under time pressure at execution time.
- pg_stat_statements for the baseline capture step (optional; the script degrades gracefully).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_blocking_and_lock_waits.sql`](scripts/01_blocking_and_lock_waits.sql) -- Confirms no session is currently blocked on a lock before the deployment starts.
2. [`scripts/02_strong_lock_modes_held.sql`](scripts/02_strong_lock_modes_held.sql) -- Checks for ShareUpdateExclusive and stronger locks that a migration would have to queue behind.
3. [`scripts/03_long_running_transactions.sql`](scripts/03_long_running_transactions.sql) -- Identifies open transactions that a DDL lock request would queue behind.
4. [`scripts/04_connection_headroom.sql`](scripts/04_connection_headroom.sql) -- Verifies there is enough connection headroom for a rolling restart of the application fleet.
5. [`scripts/05_replication_lag_baseline.sql`](scripts/05_replication_lag_baseline.sql) -- Records the current Aurora reader lag as the pre-deployment baseline.
6. [`scripts/06_maintenance_in_flight.sql`](scripts/06_maintenance_in_flight.sql) -- Checks whether autovacuum or a manual maintenance operation is currently running on any table.
7. [`scripts/07_query_performance_baseline.sql`](scripts/07_query_performance_baseline.sql) -- Captures the pre-deployment query performance baseline for later comparison.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora applies most parameter-group changes only after a reboot, and a reboot of the writer triggers a failover in a multi-instance cluster -- treat any parameter change in the deployment as a failover event and run failover-readiness checks as well.
- Aurora's fast DDL (in-place ALTER TABLE ... ADD COLUMN for some cases) does not remove the need for the lock: the statement still requires an AccessExclusiveLock briefly, so it must still acquire it ahead of production traffic.
- Because Aurora readers replay redo from shared storage, a heavy migration on the writer raises reader lag for the duration -- check the lag baseline before starting so the increase can be attributed correctly.

## 8. Interpretation Guide

- Treat this as a checklist with pre-agreed veto conditions, not as data to be interpreted creatively while the release train waits.
- The most dangerous finding is a long-running transaction combined with a migration that takes a strong lock: PostgreSQL queues the DDL's lock request ahead of all later requests, so the DDL blocks the entire table even while it is still waiting and has done nothing.
- An autovacuum worker on the migration's target table is not a reason to abort permanently -- it is a reason to wait for it to finish, or to accept that the migration's lock request will wait for it.
- Baseline capture is not a pass/fail check: its only purpose is to make post-deployment-check meaningful, so record it even when everything else is green.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Abort or postpone the deployment if any veto condition is present; the cost of a 30-minute delay is orders of magnitude lower than a lock-storm-induced trading halt.
- If a long-running transaction is the only blocker, have the owning team end it and re-run the check rather than proceeding hopefully.
- Set an explicit lock_timeout in the migration session (for example `SET lock_timeout = '3s';`) so a migration that cannot acquire its lock quickly fails fast instead of queueing behind traffic and blocking the table.

**Short-term remediation** (hours to days):

- Reschedule the deployment to a window with lower volume if the check repeatedly finds contention at the usual time.
- Split a migration that requires a strong lock into a sequence of individually safe steps (see schema-changes patterns such as concurrent index builds and nullable-column-then-backfill).

**Long-term engineering fix** (days to weeks):

- Automate this check as a required, blocking stage in the deployment pipeline so an unsafe deployment cannot be started manually at all.
- Adopt migration patterns that avoid strong locks entirely on the exchange's hot tables, and make lock_timeout mandatory in every migration tool configuration.

## 10. Production Safety

- Every script here is read-only and safe to run at any time, including during peak trading.
- This check never changes anything: it produces a go/no-go decision and a baseline, nothing more.
- Run it against the writer -- a deployment's migrations run on the writer, and lock and transaction state on a reader says nothing about the writer's state.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any blocked session already exists before the deployment starts -- do not add a migration on top of an existing lock chain.
- A transaction has been open longer than the migration's lock_timeout budget and its owner cannot be reached.
- Connection utilization above 80%, leaving no room for the connection churn of a rolling restart.
- Reader lag above its normal baseline, or a failover in the last few minutes -- let the cluster stabilize first.

## 12. Related Issues

- [post-deployment-check](../post-deployment-check/README.md)
- [pre-maintenance-check](../pre-maintenance-check/README.md)
- [comprehensive-health-check](../comprehensive-health-check/README.md)
- [ddl-blocking](../../concurrency-and-locking/ddl-blocking/README.md)
- [long-running-transactions](../../concurrency-and-locking/long-running-transactions/README.md)
- [performance-after-deployment](../../performance/performance-after-deployment/README.md)
