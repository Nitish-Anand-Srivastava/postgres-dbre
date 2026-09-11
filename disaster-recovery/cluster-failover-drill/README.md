# Aurora Cluster Failover Drill

**Category:** Disaster Recovery | **Workflow:** `disaster-recovery/cluster-failover-drill`

## 1. Problem Description

A planned, deliberately triggered failover of the Aurora cluster to validate that the reader fleet, application connection handling, and operational runbooks all behave as expected -- run proactively, on a schedule, rather than waiting to learn the answer during an unplanned failover.

## 2. Typical Symptoms

- No active symptom -- this is a proactive, scheduled drill, typically run quarterly or ahead of a major application change that depends on HA behavior.
- Also run after replication-and-ha/failover-readiness identifies a gap, to empirically confirm the fix actually works, not just that the configuration looks correct.

## 3. Business Impact

- An untested failover path is a false sense of security -- Aurora's HA mechanism is only as good as the application's actual behavior during the brief cutover, and the only way to know that behavior for certain is to trigger a real failover deliberately, on your own schedule, rather than for the first time during an unplanned production incident.

## 4. Possible Root Causes

- N/A -- this is a proactive validation workflow, not a root-cause investigation for a symptom.

## 5. Investigation Strategy

1. Confirm current writer/reader topology and pick a healthy, low-lag reader as the failover target.
2. Confirm every reader's replication lag is low immediately before triggering the drill, so the drill measures the failover mechanism itself, not a pre-existing lag problem.
3. Trigger the failover via the AWS control plane (never via SQL) and observe application-visible impact during the cutover.
4. Verify the new writer's identity and health immediately afterward.

## 6. Prerequisites

- AWS IAM permission to call rds:FailoverDBCluster; a maintenance window or otherwise-acceptable time to intentionally disrupt connections for the drill's duration; stakeholder awareness that a deliberate, brief disruption is about to occur.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_confirm_writer_reader_topology.sql`](scripts/01_confirm_writer_reader_topology.sql) -- Confirms current writer/reader role, run against each endpoint the application actually uses (cluster/writer endpoint and reader endpoint), as the pre-drill topology baseline.
2. [`scripts/02_reader_health_and_lag_precheck.sql`](scripts/02_reader_health_and_lag_precheck.sql) -- Confirms every reader's replication lag is low immediately before triggering the drill, so the drill measures the failover mechanism itself rather than a pre-existing lag problem.
3. [`scripts/03_failover_drill_runbook.md`](scripts/03_failover_drill_runbook.md) -- Guarded runbook for triggering the actual Aurora failover via the AWS control plane and observing application-visible impact during the cutover.
4. [`scripts/04_post_failover_verification.sql`](scripts/04_post_failover_verification.sql) -- Confirms the new writer's identity and how recently it started, run against the cluster/writer endpoint immediately after the drill to verify the promotion completed as expected.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora failover is fundamentally different from a traditional PostgreSQL physical-standby promotion: it promotes an existing reader (already attached to the same shared distributed storage volume as the writer, so no data needs to be copied) and re-points the cluster endpoint's DNS to it, typically completing the client-visible cutover in well under a minute -- there is no lengthy WAL-replay-then-promote sequence, and the operation is triggered exclusively through the AWS control plane (Console, CLI, or API), never through any SQL statement.

## 8. Interpretation Guide

- A healthy drill looks like: the promoted reader becomes the new writer, the cluster endpoint DNS re-points to it, and connected applications experience a brief (typically tens of seconds) burst of connection errors/retries before resuming normally -- this is expected and is exactly what the drill is meant to confirm, not a failure of the drill.
- If the application does not recover on its own within a couple of minutes without manual intervention, that is the actual finding: something in the application's connection handling (a hardcoded instance endpoint, no retry/backoff, an over-eager circuit breaker that does not reset) needs to be fixed before the next drill, not something to work around during this one.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- if the drill reveals the application does not recover on its own, that is a finding to fix before the next drill, not something to remediate live during this one (this is a planned exercise, not an incident).

**Short-term remediation** (hours to days):

- Fix any application-side issue the drill surfaced (hardcoded instance endpoint, missing retry/backoff, connection pool not detecting the topology change) and re-run a subset of the drill to confirm the fix.

**Long-term engineering fix** (days to weeks):

- Establish a standing quarterly (or more frequent) cadence for this drill so HA readiness is continuously validated rather than assumed, and track drill results (time-to-recovery, any manual intervention needed) over time as a trend.

## 10. Production Safety

- This workflow's SQL scripts are entirely read-only. The failover itself is an AWS control-plane action (not a SQL statement) that deliberately and briefly disrupts every existing connection to the cluster -- this is the whole point of the drill, but it must be scheduled and communicated, never triggered casually.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The application does not recover within a reasonable window (several minutes) without manual intervention -- treat this as the drill's primary finding and open a tracking issue with the owning application team immediately, since the next failover may not be a scheduled drill.

## 12. Related Issues

- [failover-investigation](../../replication-and-ha/failover-investigation/README.md)
- [failover-readiness](../../replication-and-ha/failover-readiness/README.md)
- [performance-after-failover](../../performance/performance-after-failover/README.md)
- [post-maintenance-check](../../database-health/post-maintenance-check/README.md)
