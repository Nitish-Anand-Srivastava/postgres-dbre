# Failover Readiness Assessment

**Category:** Replication and High Availability | **Workflow:** `replication-and-ha/failover-readiness`

## 1. Problem Description

Proactive assessment of whether the cluster and application are well-prepared for a failover, before one occurs -- covering reader fleet adequacy, application retry/backoff behavior, and connection endpoint usage.

## 2. Typical Symptoms

- No active symptom -- proactive readiness review, typically ahead of a planned maintenance window or as a standing operational practice.

## 3. Business Impact

- Failover readiness directly determines how disruptive an inevitable future failover (planned or unplanned) will be to the business -- assessed and improved proactively, not discovered reactively during an actual incident.

## 4. Possible Root Causes

- N/A -- proactive assessment workflow.

## 5. Investigation Strategy

1. Confirm the application uses the cluster/reader endpoints correctly (not a hardcoded specific instance IP/hostname).
2. Confirm at least one healthy reader exists to serve as failover target.
3. Confirm application-side connection retry/backoff behavior is documented and tested.

## 6. Prerequisites

- Access to application connection-string/endpoint configuration for review.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_current_cluster_topology.sql`](scripts/01_current_cluster_topology.sql) -- Confirms current writer/reader role for the connection being tested, to be run against each endpoint your applications actually use.

## 8. Interpretation Guide

- An application connecting via a specific instance's endpoint/IP rather than the cluster (writer) endpoint will NOT automatically follow a failover and will experience an extended outage until manually reconfigured -- this is the single most critical readiness check.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A.

**Short-term remediation** (hours to days):

- Fix any application connecting via a hardcoded instance endpoint instead of the cluster/reader endpoint immediately -- this is a readiness gap, not just an optimization.

**Long-term engineering fix** (days to weeks):

- Schedule regular failover drills (see disaster-recovery/cluster-failover-drill) to validate readiness empirically, not just via configuration review.

## 10. Production Safety

- This is a review/assessment workflow; the SQL scripts here are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A business-critical service is found connecting via a hardcoded instance endpoint -- escalate to that service's owning team immediately as a standing availability risk.

## 12. Related Issues

- [failover-investigation](../failover-investigation/README.md)
- [cluster-failover-drill](../../disaster-recovery/cluster-failover-drill/README.md)
