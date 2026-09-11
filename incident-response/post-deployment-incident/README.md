# Post-Deployment Incident

**Category:** Incident Response | **Workflow:** `incident-response/post-deployment-incident`

## 1. Problem Description

Something broke immediately after a release, and the question is whether the deployment caused it and whether to roll back now. Time pressure here is extreme and the bias should be toward rollback -- but a schema migration may have made rollback unsafe, so this workflow establishes what the deployment actually did to the database before that decision is made.

## 2. Typical Symptoms

- Errors, latency or lock waits that begin within minutes of a rollout, with a clear before-and-after in the graphs.
- A new application_name, or a sharp change in session count, appearing at the deployment timestamp.
- A migration statement visible in pg_stat_activity, running or waiting on a lock.
- New invalid indexes left behind by a concurrent index build that failed during the release.
- A query shape that has never been seen before suddenly appearing in the top statements by call count.

## 3. Business Impact

- Deployment-induced incidents hit the newest, least-proven code path on the most business-critical system, often during business hours when trading volume is highest.
- A migration that is half-applied is far more dangerous than one that never ran: the schema and the application disagree, and financial writes can fail or, worse, succeed against the wrong shape.
- Rollback decisions made without knowing what the migration did to the database are how a ten-minute incident becomes a data-integrity investigation.

## 4. Possible Root Causes

- A schema migration taking or waiting for a strong lock on a hot table, blocking the application behind it.
- A new or changed query with no supporting index, turning a fast lookup into a sequential scan on a large table.
- A concurrent index build that failed partway, leaving an invalid index that consumes storage and slows writes without ever being used.
- A connection-pool configuration change that multiplied the fleet's connection count.
- An ORM upgrade changing generated SQL, isolation level, or transaction boundaries in ways nobody reviewed.
- A new code path issuing many small queries where one set-based query was intended -- the classic N+1 pattern arriving in production.
- Statistics invalidated by a large data backfill run as part of the release, so the planner's estimates are suddenly wrong.

## 5. Investigation Strategy

1. Attribute current workload by application and session age, so the newly deployed fleet is visible as a distinct group with a distinct arrival time.
2. Check immediately for migration DDL holding or waiting for locks -- this is both the most common and the most damaging deployment failure mode.
3. Check for in-progress or failed index builds, including invalid indexes left behind.
4. Look for new or newly frequent query shapes in pg_stat_statements.
5. Check statistics freshness and scan patterns on the tables the release touched, since a backfill can invalidate the planner's assumptions instantly.
6. Make the rollback decision explicitly, using the schema-compatibility criteria in the runbook rather than instinct.

## 6. Prerequisites

- The exact deployment timestamp and the list of services included in it -- without this, correlation is guesswork.
- The migration list from the release, including whether each migration is reversible.
- `pg_monitor` role membership, plus `pg_stat_statements` for the query-shape check.
- A direct line to the deploying team, who must be part of the rollback decision rather than informed after it.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_workload_by_application_and_session_age.sql`](scripts/01_workload_by_application_and_session_age.sql) -- Attributes the current workload to each service and shows when its sessions were established, making the newly deployed fleet visible.
2. [`scripts/02_migration_lock_waits.sql`](scripts/02_migration_lock_waits.sql) -- Checks for migration DDL holding or waiting for strong locks -- the most common and most damaging deployment failure mode.
3. [`scripts/03_index_build_state.sql`](scripts/03_index_build_state.sql) -- Checks in-progress index builds and any invalid indexes left behind by a build that failed during the release.
4. [`scripts/04_new_query_shapes.sql`](scripts/04_new_query_shapes.sql) -- Looks for new or newly frequent statements, which is how a changed code path announces itself at the database.
5. [`scripts/05_statistics_and_scan_regression.sql`](scripts/05_statistics_and_scan_regression.sql) -- Checks whether a release backfill invalidated planner statistics, or whether a new access pattern is driving sequential scans on large tables.
6. [`scripts/06_rollback_decision_runbook.md`](scripts/06_rollback_decision_runbook.md) -- The rollback decision itself: the schema-compatibility criteria that determine whether rolling back is recovery or a second incident, plus the guarded actions for each branch.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora does not make DDL any cheaper than community PostgreSQL: an ALTER TABLE that needs an AccessExclusiveLock still blocks all access to the table for its duration, and the fast-storage architecture does not change lock semantics at all.
- A failed CREATE INDEX CONCURRENTLY leaves an invalid index on Aurora exactly as it does on community PostgreSQL, and that index still consumes cluster-volume storage while being useless to the planner.
- Aurora's cluster-volume storage does not shrink when an index is dropped -- space is reused, not returned -- so cleaning up after a failed release recovers usable capacity, not billed storage.

## 8. Interpretation Guide

- Session groups whose newest_session_started clusters at the deployment time identify the new fleet. Comparing its blocked_count and longest_active_query against unchanged services isolates the effect of the release in one query.
- A migration statement with granted = false is the highest-priority finding in this workflow: the DDL is waiting, and every query that arrived after it is queued behind its lock request, so a single waiting ALTER TABLE presents as a total outage on that table.
- Invalid indexes dated to the release mean a concurrent build failed. They are never used by the planner but still slow every write to the table, so they must be cleaned up deliberately.
- A query shape with a high call count that did not exist before the release is the new code path; if its mean time is small but its call count is enormous, you are looking at an N+1 pattern.
- A table with a very high pct_modified_since_analyze right after a release means a backfill ran and statistics have not caught up, which can flip plans on statements that were fine an hour ago.
- If nothing in the database correlates with the deployment, say so clearly -- a release can coincide with an unrelated incident, and anchoring on the deployment wastes the response.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a migration is blocking traffic, cancel the migration statement rather than the application transactions it is waiting on -- a cancelled DDL rolls back cleanly with no data change.
- If the application code is the problem and the migration is reversible or was never applied, roll back the deployment now. Rollback is almost always the fastest route to recovery.
- If the migration is applied and not reversible, do not roll back blindly: a rollback to code that does not understand the new schema is a data-integrity risk, not a recovery.
- If a missing index is the cause and rollback is unavailable, build it concurrently per the schema-changes workflow rather than with a blocking build during an incident.

**Short-term remediation** (hours to days):

- Clean up any invalid indexes left behind by failed concurrent builds, in a change-managed window.
- Analyse the specific tables affected by a release backfill so the planner's estimates catch up with the new data.
- Add the missing index the new query shape needs, built concurrently.
- Re-run the failed migration with `lock_timeout` set and using the concurrent, lock-light patterns.

**Long-term engineering fix** (days to weeks):

- Make every migration follow the expand/contract pattern so that application and schema are always compatible in both directions and rollback is never gated on a migration.
- Require a lock-risk review for every migration touching a hot table, stating the expected lock mode and duration before it ships.
- Add a post-deploy database canary: compare top query shapes, lock waits and error rates for a fixed window after each release, and fail the rollout automatically on a regression.

## 10. Production Safety

- Scripts 01-05 are read-only and safe to run at any point during the incident.
- Script 06 is a decision runbook containing guarded actions; read it fully, and note that its most important content is the decision criteria rather than the statements.
- Never roll back application code past an applied, non-reversible migration without an explicit schema-compatibility check. That single mistake causes more data-integrity incidents than the deployments themselves.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A migration is half-applied on a financial table -- escalate to database engineering leadership and treasury immediately; do not attempt to complete or reverse it unilaterally.
- Rollback is blocked by an applied non-reversible migration while customer impact continues -- this requires a joint decision between database engineering and the deploying team, with a named decision owner.
- The incident affects deposits, withdrawals or settlement -- involve compliance from the start, not after resolution.
- The deployment cannot be correlated with any database-side change yet impact continues -- broaden the investigation rather than continuing to focus on the release.

## 12. Related Issues

- [production-triage](../production-triage/README.md)
- [lock-storm](../lock-storm/README.md)
- [sudden-latency-spike](../sudden-latency-spike/README.md)
- [application-timeouts](../application-timeouts/README.md)
- [failed-index-build](../../schema-changes/failed-index-build/README.md)
- [comprehensive-health-check](../../database-health/comprehensive-health-check/README.md)
