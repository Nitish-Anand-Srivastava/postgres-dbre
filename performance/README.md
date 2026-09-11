# Performance Issues

**Category:** `performance`

This is the index for the `performance/` category: every workflow
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
| [`high-cpu`](high-cpu/README.md) | Aurora instance-level CPU utilization (as reported by CloudWatch `CPUUtilization`) is sustained above a healthy threshold (commonly >80-90% for several minutes), risking query queuing, increased latency, and eventual request timeouts across every service that depends on the database. |
| [`high-database-load`](high-database-load/README.md) | The database is showing a sustained high number of active/waiting sessions (high 'load' in the Performance Insights / AAS sense) even if instance CPU itself is not yet saturated. Unlike high-cpu, this workflow starts from the load composition (what sessions are doing) rather than assuming CPU is the bottleneck. |
| [`slow-queries`](slow-queries/README.md) | One or more specific queries are executing slower than expected, either as isolated incidents reported by an engineering team or as a general pattern surfaced by APM/tracing. This is the general-purpose, query-first investigation workflow; use query-regression instead when you specifically suspect a plan change after a deploy or ANALYZE. |
| [`query-regression`](query-regression/README.md) | A previously well-performing query has recently become significantly slower, without any obvious application-level change -- typically caused by a changed execution plan (index drop, statistics change, data skew, parameter value, or a PostgreSQL/Aurora minor version upgrade) rather than a change in the query text itself. |
| [`high-iops`](high-iops/README.md) | The Aurora instance or cluster storage is showing elevated I/O operations per second (CloudWatch VolumeReadIOPS/VolumeWriteIOPS or ReadIOPS/WriteIOPS) or is approaching a provisioned/burst I/O limit, causing increased read/write latency at the storage layer. |
| [`high-latency`](high-latency/README.md) | End-to-end database call latency (as observed by the application or APM) has increased, without necessarily a CPU, IOPS, or lock signal being obviously dominant. This workflow is the general entry point for 'the database feels slow' reports and routes to the more specific workflow once the dominant cause is found. |
| [`throughput-degradation`](throughput-degradation/README.md) | The number of transactions/queries the database successfully processes per second has dropped, even if individual query latency has not obviously changed -- for example, a batch job or ETL pipeline is completing fewer rows/sec than its established baseline, or overall xact_commit rate has fallen versus incoming request rate. |
| [`sudden-performance-degradation`](sudden-performance-degradation/README.md) | Performance across the database (or a major subset of workload) degraded abruptly, within seconds to minutes, rather than gradually. This workflow is optimized for rapid correlation against a specific point in time (a deploy, a failover, a maintenance action, a traffic spike) rather than open-ended root-cause exploration. |
| [`performance-after-deployment`](performance-after-deployment/README.md) | Database performance degraded shortly after an application or schema deployment. This workflow focuses specifically on deployment-correlated causes: new/changed queries, index changes, migration side effects, and connection/config changes shipped with the release. |
| [`performance-after-failover`](performance-after-failover/README.md) | Performance degraded following an Aurora failover (planned or unplanned) -- most commonly because the newly promoted writer starts with a cold buffer cache and must re-warm it from Aurora storage under live production load. |

## Related Categories

- [`concurrency-and-locking/lock-contention`](../../concurrency-and-locking/lock-contention/README.md)
- [`concurrency-and-locking/transaction-contention`](../../concurrency-and-locking/transaction-contention/README.md)
- [`database-health/comprehensive-health-check`](../../database-health/comprehensive-health-check/README.md)
- [`database-health/post-deployment-check`](../../database-health/post-deployment-check/README.md)
- [`disaster-recovery/cluster-failover-drill`](../../disaster-recovery/cluster-failover-drill/README.md)
- [`incident-response/high-cpu`](../../incident-response/high-cpu/README.md)
- [`incident-response/production-triage`](../../incident-response/production-triage/README.md)
- [`observability/performance-insights`](../../observability/performance-insights/README.md)
- [`query-optimization/analyze-query-plan`](../../query-optimization/analyze-query-plan/README.md)
- [`query-optimization/query-plan-regression`](../../query-optimization/query-plan-regression/README.md)
- [`query-optimization/temp-file-investigation`](../../query-optimization/temp-file-investigation/README.md)
- [`replication-and-ha/failover-investigation`](../../replication-and-ha/failover-investigation/README.md)
- [`replication-and-ha/reader-lag-investigation`](../../replication-and-ha/reader-lag-investigation/README.md)
- [`schema-changes/failed-index-build`](../../schema-changes/failed-index-build/README.md)
- [`storage-and-capacity/wal-generation`](../../storage-and-capacity/wal-generation/README.md)
- [`tables-and-indexes/invalid-indexes`](../../tables-and-indexes/invalid-indexes/README.md)
- [`tables-and-indexes/missing-index-candidates`](../../tables-and-indexes/missing-index-candidates/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
