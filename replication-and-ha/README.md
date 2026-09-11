# Replication and High Availability

**Category:** `replication-and-ha`

This is the index for the `replication-and-ha/` category: every workflow
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
| [`replication-lag`](replication-lag/README.md) | Investigates elevated replication lag -- either Aurora's native storage-layer reader lag, or standard PostgreSQL streaming/logical replication lag to an external consumer -- and helps distinguish the two, since they are measured and caused differently. |
| [`reader-performance`](reader-performance/README.md) | Investigates performance issues specific to an Aurora reader instance -- distinct from writer performance workflows, since readers have their own independent buffer cache, connection pool, and query load. |
| [`reader-lag-investigation`](reader-lag-investigation/README.md) | A deeper, more structured investigation than replication-lag for cases where initial checks did not resolve the cause, walking through writer write-rate, storage I/O, and reader-side factors systematically. |
| [`failover-investigation`](failover-investigation/README.md) | Post-hoc investigation of an Aurora failover event -- confirming it occurred, understanding its cause and timing, and assessing its impact, distinct from performance/performance-after-failover which focuses specifically on the post-failover cache-warmup performance dip. |
| [`failover-readiness`](failover-readiness/README.md) | Proactive assessment of whether the cluster and application are well-prepared for a failover, before one occurs -- covering reader fleet adequacy, application retry/backoff behavior, and connection endpoint usage. |
| [`writer-reader-imbalance`](writer-reader-imbalance/README.md) | Investigates whether read traffic is effectively distributed across the reader fleet, or whether load is concentrated on the writer (under-utilizing readers) or unevenly distributed across readers. |
| [`replication-health`](replication-health/README.md) | A routine, holistic health check spanning Aurora reader lag, any external logical replication slots/subscribers, and replication-related configuration -- intended for regular health monitoring rather than active-incident response. |

## Related Categories

- [`database-health/daily-health-check`](../../database-health/daily-health-check/README.md)
- [`disaster-recovery/cluster-failover-drill`](../../disaster-recovery/cluster-failover-drill/README.md)
- [`performance/high-database-load`](../../performance/high-database-load/README.md)
- [`performance/high-iops`](../../performance/high-iops/README.md)
- [`performance/performance-after-failover`](../../performance/performance-after-failover/README.md)
- [`transactions-and-xid/xid-wraparound-risk`](../../transactions-and-xid/xid-wraparound-risk/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
