# 03_failover_drill_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_failover_drill_runbook.md` |
| Purpose | Guarded runbook for triggering the actual Aurora failover via the AWS control plane and observing application-visible impact during the cutover. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | ELEVATED RISK (deliberately disrupts every existing connection to the cluster for the duration of the cutover -- an AWS control-plane action, not a SQL statement) |
| Expected impact | A brief (typically tens of seconds) period where the cluster/reader endpoints are unavailable or reset for existing connections while the promoted reader becomes the new writer and DNS re-points. |
| Required privileges | AWS IAM permission for rds:FailoverDBCluster (or console equivalent); no PostgreSQL role is used to trigger the failover itself. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 03 of workflow `disaster-recovery/cluster-failover-drill` |
| Related scripts | 01_confirm_writer_reader_topology.sql, 02_reader_health_and_lag_precheck.sql, 04_post_failover_verification.sql |

## How to interpret / use this runbook

Follow the sequence in order -- the value of this drill is entirely in observing real application behavior during the cutover, so do not skip the 'before triggering' stakeholder/observability steps to save time.

---

## Before triggering

1. Confirm `01_confirm_writer_reader_topology.sql` and `02_reader_health_and_lag_precheck.sql` both look healthy.
2. Confirm stakeholders are aware a brief, deliberate connection disruption is about to occur, and that this is happening inside an agreed window.
3. Have application-side dashboards/logs open so the cutover's application-visible impact can be observed in real time, not just inferred afterward.

## Triggering the failover

Aurora failover is an AWS control-plane operation -- it is never triggered via a SQL statement or function call from inside PostgreSQL:

```
aws rds failover-db-cluster \
  --db-cluster-identifier <cluster-identifier> \
  --target-db-instance-identifier <target-reader-instance-identifier>
```

Omit `--target-db-instance-identifier` to let Aurora choose the best-positioned reader automatically; specify it explicitly when the drill is deliberately validating a specific reader (for example, the newest or largest instance class in the fleet).

## What happens during the cutover

The targeted reader is promoted to writer and the cluster endpoint's DNS re-points to it -- because the new writer already shares the same underlying storage volume, no data copy is needed, and the client-visible interruption is typically on the order of tens of seconds, not minutes. Every existing connection (to the old writer and to every reader, since the reader endpoint's membership also changes) is reset; applications must reconnect and DNS caches must expire and re-resolve, which is why connection pool/retry configuration matters as much as the Aurora-side mechanism itself.

## Immediately after

Run `04_post_failover_verification.sql` against the cluster/writer endpoint to confirm the new writer's identity and recent start time, then follow `database-health/post-maintenance-check` for the fuller post-event health check.

## Recording the drill

Track, per drill: time-to-first-successful-reconnect for each application, whether any manual intervention was needed, and any configuration gap discovered -- compare this against previous drills' results as a standing HA-readiness trend line.
