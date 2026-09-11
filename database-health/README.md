# Database Health Checks

**Category:** `database-health`

This is the index for the `database-health/` category: every workflow
(issue directory) below addresses a distinct, real operational problem or
DBA use case for this Aurora PostgreSQL toolkit, per the repository's
one-parent-directory-per-problem design. Each workflow directory is
self-contained -- its own `README.md` (problem description, symptoms,
business impact, root causes, investigation strategy, prerequisites,
interpretation guide, remediation options, production safety, and
escalation criteria) and a `scripts/` directory of numbered, read-only-by
-default investigation scripts (see each workflow's `scripts/README.md`
for the full script-by-script execution table).

## Workflows

| Workflow | Summary |
| --- | --- |
| [`comprehensive-health-check`](comprehensive-health-check/README.md) | A single, end-to-end read-only sweep of every dimension of Aurora PostgreSQL health that can silently degrade a crypto-exchange platform: sizing and growth, connection headroom, open transaction horizon, locking, dead tuples and vacuum progress, transaction ID age, query hot spots, temporary file spills, index usage, and reader replication health. This is the deep quarterly/ad-hoc assessment, the first thing to run when taking over an unfamiliar cluster, and the evidence pack to attach to an incident review -- not the lightweight daily loop (see daily-health-check for that). |
| [`daily-health-check`](daily-health-check/README.md) | The lightweight morning sweep an on-call DBA runs every day before the busiest trading session: current load, connection headroom, the oldest open transaction, vacuum debt, transaction ID age, the slowest recurring statements, and reader lag. It is deliberately short enough to complete in a few minutes across every cluster in the fleet, and deliberately biased toward the small set of conditions that reliably turn into an exchange-wide incident if left unnoticed for another day. |
| [`pre-deployment-check`](pre-deployment-check/README.md) | The go/no-go gate run in the minutes immediately before a release, schema migration, or parameter change reaches production. It answers one question: is the database in a state where this deployment can proceed safely right now? A migration that would take a millisecond on a quiet cluster can take an AccessExclusiveLock queue hostage and halt order matching for minutes if it lands while a long transaction, a lock wait, or a vacuum is already in flight -- this check catches exactly that. |
| [`post-deployment-check`](post-deployment-check/README.md) | The verification sweep run in the first minutes and hours after a release reaches production, designed to catch the specific damage a deployment can do to a database: query plan regressions from new or changed statements, a rising rollback rate from failing code paths, newly dominant sequential scans, invalid indexes left by a failed concurrent build, stale statistics after a data migration, connection-pool behavior changes, and new lock contention. Its purpose is to detect a bad release while rolling back is still cheap. |
| [`pre-maintenance-check`](pre-maintenance-check/README.md) | The go/no-go baseline captured immediately before a planned infrastructure operation -- a failover test, an instance class resize, a major engine version upgrade, or an extension version upgrade -- rather than an application deployment. It answers 'is it safe to start this operation now, and what does healthy look like so we can tell whether the operation itself introduced a regression?' A resize or major-version upgrade forces a writer restart (and therefore a failover in a multi-instance cluster); starting one while a transaction is open, a vacuum is mid-flight, or a reader is already lagging turns a planned few minutes of downtime into an extended incident. |
| [`post-maintenance-check`](post-maintenance-check/README.md) | The verification sweep run immediately after a planned infrastructure operation -- a failover test, an instance class resize, a major engine version upgrade, or an extension version upgrade -- completes. Its purpose is to confirm the cluster came back in the expected topology and configuration, that replication and connections recovered fully, that no vacuum/XID regression was introduced by an interrupted autovacuum, and that query performance did not silently change, before declaring the maintenance window closed. |
| [`capacity-health-check`](capacity-health-check/README.md) | A focused sweep of storage, connection, and I/O capacity headroom -- distinct from the general checks in comprehensive-health-check and daily-health-check, which touch capacity only in passing. This workflow answers one question specifically: does this cluster have room to keep growing at its current rate before storage, connections, or I/O become the limiting factor? It is the read-only, SQL-level companion to storage-and-capacity/capacity-forecasting, which builds the longer-range trend and projection on top of the same underlying signals. |

## Related Categories

- [`archival-and-data-lifecycle/investigate-archiving-candidate`](../../archival-and-data-lifecycle/investigate-archiving-candidate/README.md)
- [`concurrency-and-locking/ddl-blocking`](../../concurrency-and-locking/ddl-blocking/README.md)
- [`concurrency-and-locking/long-running-transactions`](../../concurrency-and-locking/long-running-transactions/README.md)
- [`connections/connection-exhaustion`](../../connections/connection-exhaustion/README.md)
- [`connections/max-connections-planning`](../../connections/max-connections-planning/README.md)
- [`disaster-recovery/cluster-failover-drill`](../../disaster-recovery/cluster-failover-drill/README.md)
- [`performance/high-database-load`](../../performance/high-database-load/README.md)
- [`performance/performance-after-deployment`](../../performance/performance-after-deployment/README.md)
- [`performance/query-regression`](../../performance/query-regression/README.md)
- [`query-optimization/query-plan-regression`](../../query-optimization/query-plan-regression/README.md)
- [`query-optimization/stale-statistics`](../../query-optimization/stale-statistics/README.md)
- [`replication-and-ha/failover-investigation`](../../replication-and-ha/failover-investigation/README.md)
- [`replication-and-ha/failover-readiness`](../../replication-and-ha/failover-readiness/README.md)
- [`replication-and-ha/reader-lag-investigation`](../../replication-and-ha/reader-lag-investigation/README.md)
- [`replication-and-ha/replication-health`](../../replication-and-ha/replication-health/README.md)
- [`replication-and-ha/replication-lag`](../../replication-and-ha/replication-lag/README.md)
- [`storage-and-capacity/capacity-forecasting`](../../storage-and-capacity/capacity-forecasting/README.md)
- [`storage-and-capacity/database-growth`](../../storage-and-capacity/database-growth/README.md)
- [`tables-and-indexes/invalid-indexes`](../../tables-and-indexes/invalid-indexes/README.md)
- [`transactions-and-xid/transaction-age`](../../transactions-and-xid/transaction-age/README.md)
- [`transactions-and-xid/xid-wraparound-risk`](../../transactions-and-xid/xid-wraparound-risk/README.md)
- [`vacuum-and-autovacuum/autovacuum-not-keeping-up`](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
- [`vacuum-and-autovacuum/vacuum-progress`](../../vacuum-and-autovacuum/vacuum-progress/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
