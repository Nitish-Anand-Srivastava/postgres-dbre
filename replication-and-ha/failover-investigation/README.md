# Failover Investigation

**Category:** Replication and High Availability | **Workflow:** `replication-and-ha/failover-investigation`

## 1. Problem Description

Post-hoc investigation of an Aurora failover event -- confirming it occurred, understanding its cause and timing, and assessing its impact, distinct from performance/performance-after-failover which focuses specifically on the post-failover cache-warmup performance dip.

## 2. Typical Symptoms

- Application experienced a brief connectivity disruption.
- AWS RDS/Aurora Events show a failover event.
- The writer instance identity has changed.

## 3. Business Impact

- Understanding why a failover occurred (planned maintenance vs. an unplanned instance failure) determines whether follow-up action is needed and informs confidence in the platform's HA posture.

## 4. Possible Root Causes

- A planned failover (e.g. an AWS-initiated instance patch/maintenance, or a manually-triggered failover for testing/maintenance).
- An unplanned failover due to a writer instance failure/health-check failure detected by Aurora.
- A manually-triggered application-side failover test (see disaster-recovery/cluster-failover-drill).

## 5. Investigation Strategy

1. Confirm current writer/reader roles and recent instance start times.
2. Check AWS RDS Events (via AWS Console/CLI, not SQL) for the specific failover cause and timestamp.
3. Assess connection/application impact during the failover window.

## 6. Prerequisites

- AWS Console/CLI access to RDS/Aurora Events -- the failover cause itself is not visible via SQL.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_confirm_role_and_recent_restart.sql`](scripts/01_confirm_role_and_recent_restart.sql) -- Confirms current writer/reader role and how recently this instance started, as SQL-side evidence of a recent failover.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- The failover mechanism itself, its trigger conditions, and its detailed cause are managed and recorded by the Aurora control plane and are visible via AWS RDS Events / CloudTrail / the Console, not via any PostgreSQL catalog -- SQL can only confirm the current role and instance start time from inside the database.

## 8. Interpretation Guide

- A recent pg_postmaster_start_time on the current writer combined with a corresponding AWS RDS Event is the clearest confirmation of a recent failover and its type (planned vs. unplanned).

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If ongoing post-failover performance impact is present, see performance/performance-after-failover.

**Short-term remediation** (hours to days):

- If the failover was unplanned (instance failure), review CloudWatch/RDS Events for the underlying health-check failure reason and consider an AWS Support case if the cause is unclear.

**Long-term engineering fix** (days to weeks):

- Use findings to inform disaster-recovery/cluster-failover-drill planning and application-side resiliency (connection retry/backoff) improvements.

## 10. Production Safety

- SQL-side investigation is read-only; failover itself is an AWS-managed operation, not something triggered via SQL.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- An unplanned failover's root cause is not clear from RDS Events -- open an AWS Support case.

## 12. Related Issues

- [failover-readiness](../failover-readiness/README.md)
- [performance-after-failover](../../performance/performance-after-failover/README.md)
- [cluster-failover-drill](../../disaster-recovery/cluster-failover-drill/README.md)
