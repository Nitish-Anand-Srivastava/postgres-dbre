# Post-Deployment Health Check

**Category:** Database Health Checks | **Workflow:** `database-health/post-deployment-check`

## 1. Problem Description

The verification sweep run in the first minutes and hours after a release reaches production, designed to catch the specific damage a deployment can do to a database: query plan regressions from new or changed statements, a rising rollback rate from failing code paths, newly dominant sequential scans, invalid indexes left by a failed concurrent build, stale statistics after a data migration, connection-pool behavior changes, and new lock contention. Its purpose is to detect a bad release while rolling back is still cheap.

## 2. Typical Symptoms

- A deployment has just completed and its database-side impact has not yet been verified.
- Latency, error rate, or CPU has risen since a release, but the application team reports no code path as obviously broken.
- A migration reported success, but it is not confirmed that every index it created is actually valid and being used.

## 3. Business Impact

- A query plan regression introduced by a release degrades the order or balance path continuously until it is found -- with an exchange's request volume, that is thousands of affected user actions per minute.
- An invalid index left behind by an interrupted CREATE INDEX CONCURRENTLY silently removes the plan the application depends on, converting an indexed lookup into a sequential scan on a table with hundreds of millions of rows.
- Detecting a regression inside the rollback window turns a potential multi-hour incident into a five-minute revert; detecting it the next day usually means fixing forward under pressure.

## 4. Possible Root Causes

- A new or modified query whose plan is fine on a small staging dataset and catastrophic on production data volumes.
- A schema migration that invalidated planner assumptions (new column, changed type, dropped or added index) without a follow-up ANALYZE.
- A failed or interrupted CREATE INDEX CONCURRENTLY leaving an INVALID index that the planner ignores.
- A connection-pool configuration change shipped alongside the application change, altering connection count or transaction lifetime.
- A bulk backfill run as part of the release, leaving both stale statistics and a large volume of dead tuples behind.
- New transaction boundaries in the application code producing lock contention patterns the previous version never created.

## 5. Investigation Strategy

1. Check the error and rollback rate first -- it is the fastest signal that a code path is failing rather than merely slow.
2. Compare top statements by mean and total time against the pre-deployment baseline captured by pre-deployment-check.
3. Look for newly high-frequency statements, which reveal N+1 patterns or retry storms introduced by the release.
4. Look for tables that have suddenly become sequential-scan dominated, the classic signature of a lost or unused index.
5. Check for invalid indexes produced by the migration.
6. Check statistics freshness on any table the migration modified in bulk.
7. Check connection behavior and lock contention for changes attributable to the new version.

## 6. Prerequisites

- Role membership in pg_monitor (or pg_read_all_stats).
- The pre-deployment baseline output from pre-deployment-check script 07, without which the query comparison is guesswork.
- The migration's change list (tables, indexes, backfills) so the checks can be focused rather than exploratory.
- pg_stat_statements, ideally not reset between the baseline capture and this run.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_error_and_rollback_rates.sql`](scripts/01_error_and_rollback_rates.sql) -- Compares commit and rollback counters plus deadlock and conflict counts to detect failing code paths.
2. [`scripts/02_query_performance_vs_baseline.sql`](scripts/02_query_performance_vs_baseline.sql) -- Re-captures top statements by total time for direct comparison against the pre-deployment baseline.
3. [`scripts/03_new_and_high_frequency_statements.sql`](scripts/03_new_and_high_frequency_statements.sql) -- Ranks statements by call count to expose N+1 patterns and retry storms introduced by the release.
4. [`scripts/04_sequential_scan_regression.sql`](scripts/04_sequential_scan_regression.sql) -- Finds tables where sequential scans now dominate, the signature of a lost or unusable index.
5. [`scripts/05_invalid_indexes.sql`](scripts/05_invalid_indexes.sql) -- Detects indexes left in an INVALID state by a failed or interrupted concurrent build.
6. [`scripts/06_statistics_freshness.sql`](scripts/06_statistics_freshness.sql) -- Checks how stale planner statistics are on tables the migration modified in bulk.
7. [`scripts/07_connection_and_lock_behavior.sql`](scripts/07_connection_and_lock_behavior.sql) -- Compares per-application connection counts and checks for new lock contention after the release.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- If the deployment included a parameter-group change requiring a reboot, the resulting failover reset pg_stat_statements and pg_stat_database on the promoted instance -- the pre-deployment baseline is then no longer comparable and must be rebuilt from application-side metrics instead.
- Aurora readers serve much of an exchange's read traffic; after a deployment, verify reader-side query behavior too, since a plan regression on a read-only reporting query only manifests on the readers.
- Aurora's shared storage means an index rebuild consumes cluster volume that is never returned when the old index is dropped -- factor that into the storage impact of any post-deployment index remediation.

## 8. Interpretation Guide

- pg_stat_statements counters are cumulative since stats_reset, so a newly deployed statement's mean_exec_time is trustworthy immediately, while a pre-existing statement's mean is diluted by all its executions before the release -- watch for a rising max_exec_time and stddev_exec_time on pre-existing statements rather than expecting the mean to move quickly.
- A brand-new queryid appearing at the top of the total-time list is expected after a release; the question is whether its cost is proportionate to what the feature does.
- A rollback_pct increase that starts exactly at the deployment timestamp is almost always application errors, not database faults -- route it to the deploying team with the evidence rather than investigating database internals.
- A table that has just started accumulating sequential scans is a stronger and faster signal than any latency metric, because it points directly at the lost access path.
- Give autoanalyze time: immediately after a bulk backfill, statistics are stale by definition. Stale statistics found five minutes after a migration are a reason to run a targeted ANALYZE, not evidence of a systemic problem.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If a regression is confirmed and the rollback window is still open, roll back the deployment first and investigate afterwards.
- If an invalid index is found, the application is currently running without that access path -- treat it as an active incident and plan an immediate concurrent rebuild.
- Run a targeted ANALYZE on the specific tables a bulk migration touched (a guarded, change-managed action -- see vacuum-and-autovacuum/analyze-statistics for the runbook), never a blind database-wide ANALYZE.

**Short-term remediation** (hours to days):

- File the specific regressed statement with its queryid, its baseline numbers, and its current numbers to the owning team.
- Rebuild any invalid index with CREATE INDEX CONCURRENTLY / REINDEX CONCURRENTLY during a low-traffic window, following the schema-changes runbook.
- Add the newly discovered regression shape to the pre-deployment review checklist so the next release catches it before shipping.

**Long-term engineering fix** (days to weeks):

- Automate the baseline-versus-post comparison in the deployment pipeline and fail the release automatically on a defined regression threshold.
- Require a representative production-scale dataset for query plan validation in the pre-production environment, because plan differences between a small staging dataset and a production-scale exchange table are the root cause of most of these regressions.
- Make a post-migration ANALYZE a mandatory, automated step of every migration that backfills or bulk-updates data.

## 10. Production Safety

- Every script here is read-only; none of them runs ANALYZE, DDL, or any write.
- Safe during peak trading; the heaviest step is the index and sequential-scan inventory, which only reads catalogs and statistics views.
- Remediating a finding (ANALYZE, index rebuild) is explicitly out of scope for these scripts and is handled by the referenced guarded runbooks so that a human decides when it happens.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any statement on the order-placement, balance-check, withdrawal, or settlement path is measurably slower than its pre-deployment baseline -- escalate to the deploying team immediately and evaluate rollback.
- An invalid index exists on a hot table -- the application is running without an expected access path right now.
- The rollback rate rose sharply at the deployment timestamp, indicating failing transactions rather than slow ones.
- New lock contention appears on ledger or wallet tables, which risks financial-operation delays and not merely latency.

## 12. Related Issues

- [pre-deployment-check](../pre-deployment-check/README.md)
- [comprehensive-health-check](../comprehensive-health-check/README.md)
- [performance-after-deployment](../../performance/performance-after-deployment/README.md)
- [query-regression](../../performance/query-regression/README.md)
- [query-plan-regression](../../query-optimization/query-plan-regression/README.md)
- [stale-statistics](../../query-optimization/stale-statistics/README.md)
- [invalid-indexes](../../tables-and-indexes/invalid-indexes/README.md)
