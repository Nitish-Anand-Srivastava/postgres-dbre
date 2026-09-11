# Observability

**Category:** `observability`

This is the index for the `observability/` category: every workflow
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
| [`postgres-metrics`](postgres-metrics/README.md) | The core set of native PostgreSQL statistics views and catalogs that a continuously-running monitoring pipeline (a scheduled collector, an exporter feeding Prometheus/Grafana, or a periodic health-check job) should read from, and why each one matters for an exchange-scale Aurora PostgreSQL 17+ deployment. This workflow is the SQL-level foundation everything else in this category builds on: performance-insights and cloudwatch add AWS-managed context on top of these same underlying signals, and dashboard-recommendations proposes how to lay them out for a team to watch continuously. |
| [`comprehensive-html-report`](comprehensive-html-report/README.md) | A production-validated, self-contained psql report that captures a broad Aurora PostgreSQL observability snapshot and writes structurally valid HTML for offline review. It combines configuration, sessions, waits, query statistics, vacuum, storage, replication, capacity, and extension readiness in one operator-friendly artifact while dynamically handling optional or unavailable Aurora features. |
| [`performance-insights`](performance-insights/README.md) | AWS Performance Insights (PI) samples pg_stat_activity roughly once per second and aggregates it into Average Active Sessions (AAS) broken down by wait event, SQL statement, user, and host -- the same underlying source data this repository's SQL-level scripts read on demand, but continuously recorded, retained, and rendered as a stacked timeline. This workflow explains how to read PI's DB load view correctly, when to reach for it before a SQL session, and how to cross-reference its findings back against the live catalog queries in this repository to confirm and drill into what it shows. |
| [`cloudwatch`](cloudwatch/README.md) | The Aurora-published CloudWatch metrics an on-call DBA and platform team should already have alarms on, and -- for each one -- the SQL-level query in this repository that explains *why* the metric moved. CloudWatch metrics come from the instance/hypervisor and Aurora storage layer, not from inside PostgreSQL, so they answer 'something changed' reliably but rarely 'what changed inside the database'; this workflow is the bridge between the two. |
| [`slow-query-observability`](slow-query-observability/README.md) | How to build standing, always-on visibility into slow and expensive queries -- centered on pg_stat_statements as the primary continuous instrumentation, plus guidance on configuring statement-level logging (log_min_duration_statement, auto_explain) through Aurora's DB parameter group model. This is durable observability infrastructure, not a one-off diagnostic pass: the goal is that the next slow-query incident starts with existing data to query, not with turning on instrumentation after the fact. |
| [`wait-event-analysis`](wait-event-analysis/README.md) | A deep dive on pg_stat_activity's wait_event_type / wait_event columns -- what each wait event category actually means, how to read the aggregated and per-session views, and how this same taxonomy is what Performance Insights uses to color its DB load chart. Wait events are the most direct answer PostgreSQL can give to 'what is this session waiting for right now', and reading them correctly is usually faster than guessing from symptoms alone. |
| [`dashboard-recommendations`](dashboard-recommendations/README.md) | A proposed baseline layout for a team building its own always-on Grafana/CloudWatch dashboard for an Aurora PostgreSQL fleet, grouping the signals from postgres-metrics, performance-insights, cloudwatch, slow-query-observability, and wait-event-analysis into a coherent set of panels. This workflow is primarily documentation: the goal is a concrete starting layout a platform team can implement immediately, plus a single-row query that can back a simple 'cluster at a glance' panel without any other tooling. |

## Related Categories

- [`concurrency-and-locking/blocked-queries`](../../concurrency-and-locking/blocked-queries/README.md)
- [`concurrency-and-locking/lock-contention`](../../concurrency-and-locking/lock-contention/README.md)
- [`connections/connection-exhaustion`](../../connections/connection-exhaustion/README.md)
- [`connections/max-connections-planning`](../../connections/max-connections-planning/README.md)
- [`database-health/comprehensive-health-check`](../../database-health/comprehensive-health-check/README.md)
- [`database-health/daily-health-check`](../../database-health/daily-health-check/README.md)
- [`performance/high-database-load`](../../performance/high-database-load/README.md)
- [`performance/high-iops`](../../performance/high-iops/README.md)
- [`performance/slow-queries`](../../performance/slow-queries/README.md)
- [`query-optimization/analyze-query-plan`](../../query-optimization/analyze-query-plan/README.md)
- [`query-optimization/query-plan-regression`](../../query-optimization/query-plan-regression/README.md)
- [`replication-and-ha/replication-health`](../../replication-and-ha/replication-health/README.md)
- [`replication-and-ha/replication-lag`](../../replication-and-ha/replication-lag/README.md)
- [`storage-and-capacity/capacity-forecasting`](../../storage-and-capacity/capacity-forecasting/README.md)
- [`storage-and-capacity/database-growth`](../../storage-and-capacity/database-growth/README.md)
- [`tables-and-indexes/sequential-scan-investigation`](../../tables-and-indexes/sequential-scan-investigation/README.md)
- [`vacuum-and-autovacuum/autovacuum-not-keeping-up`](../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md)
- [`vacuum-and-autovacuum/dead-tuples`](../../vacuum-and-autovacuum/dead-tuples/README.md)

Start with the workflow whose title most closely matches the symptom you are
investigating; if uncertain, `database-health/comprehensive-health-check`
and `incident-response/production-triage` both provide a broad first pass
that surfaces which specific workflow to open next.
