# Cross-Region Failover and Full Cluster Loss Recovery

**Category:** Disaster Recovery | **Workflow:** `disaster-recovery/cross-region-and-full-cluster-loss`

## 1. Problem Description

Covers the worst-case disaster scenarios beyond a single-cluster failover: a regional-scale event handled via Aurora Global Database's cross-region failover, or the total, unrecoverable loss of the primary cluster requiring restore from a cross-region-copied snapshot into an entirely new region -- fundamentally an AWS infrastructure recovery process, not a SQL-level investigation.

## 2. Typical Symptoms

- An entire AWS region hosting the primary cluster becomes unavailable (a regional service event, not just an instance/AZ issue).
- The primary cluster (and its automated backups/PITR window) is confirmed lost or inaccessible in its home region, requiring recovery from a separately-stored, cross-region copy.

## 3. Business Impact

- This is the tail-risk scenario every other disaster-recovery workflow in this category exists to make unnecessary in the common case -- for a trading platform, a true regional loss without a tested cross-region recovery path is an existential business continuity risk, not merely an extended outage.

## 4. Possible Root Causes

- An AWS regional service disruption affecting the home region's control plane and/or data plane for an extended period.
- An account-level or cluster-level event (misconfiguration, deletion, corruption) severe enough that in-region recovery options (failover, same-region PITR/snapshot restore) are not viable and only a cross-region copy remains.

## 5. Investigation Strategy

1. If an Aurora Global Database is in place: confirm the secondary region's cluster is healthy and initiate a managed or unplanned regional failover via the AWS control plane.
2. If no Global Database is in place (or it is also affected) and only cross-region-copied snapshots exist: identify the most recent valid cross-region snapshot copy and restore it into a new cluster in a healthy region.
3. In either path, validate data currency and completeness in the recovered cluster before directing production traffic to it, and understand the accepted data-loss window (RPO) for the specific path taken.

## 6. Prerequisites

- An Aurora Global Database already configured with a secondary region (for the managed-failover path), or a standing cross-region snapshot-copy schedule already in place (for the snapshot-restore path) -- this workflow assumes one of these was set up in advance; neither can be created for the first time during the event itself.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_pre_incident_baseline_reference.sql`](scripts/01_pre_incident_baseline_reference.sql) -- Captures a lightweight baseline (engine version, current database, and connection role) intended to be kept on file for comparison after a cross-region recovery, run periodically as part of standing DR preparedness rather than during the event itself.
2. [`scripts/02_cross_region_and_full_loss_runbook.md`](scripts/02_cross_region_and_full_loss_runbook.md) -- Guarded runbook covering both recovery paths for a true regional-scale event: Aurora Global Database managed failover, and cross-region snapshot-copy restore when no Global Database is in place.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora Global Database is a distinct, separately-provisioned feature (a primary cluster in one region plus one or more secondary, read-only clusters in other regions, linked by Aurora's own low-latency storage-based replication) from the single-region Multi-AZ cluster this repository otherwise assumes -- confirm which topology is actually in place for this cluster well before an event, since the two require entirely different recovery procedures.

## 8. Interpretation Guide

- Aurora Global Database replication to the secondary region is asynchronous and typically sub-second, but it is NOT synchronous -- an unplanned regional failover of the primary can lose the last fraction of a second to low-single-digit seconds of committed writes that had not yet replicated; this is an accepted, documented RPO characteristic of the mechanism, not a malfunction, and must be understood by the business ahead of time, not discovered during the event.
- A cross-region snapshot-copy-based restore's RPO is bounded by how recently the last snapshot was copied to the target region, which is typically far coarser (hours, depending on the copy schedule) than Global Database's near-real-time replication -- confirm which of the two mechanisms is actually in place for this cluster before assuming a sub-second RPO is available.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- For a Global Database setup: initiate failover of the secondary region to become the new primary via the AWS control plane, then redirect application traffic to the new regional endpoint once promoted.
- For a snapshot-copy-only setup: restore the most recent valid cross-region snapshot copy into a new cluster in a healthy region, provision instances, validate data currency, then redirect application traffic.

**Short-term remediation** (hours to days):

- Once traffic is restored in the new region, assess and communicate the accepted data loss window (if any) to stakeholders, and begin reconciling any transactions known to have been in flight at the time of the event.

**Long-term engineering fix** (days to weeks):

- If this event occurred without a Global Database in place, evaluate establishing one going forward given its materially better RPO/RTO characteristics versus snapshot-copy-only recovery.
- Incorporate a cross-region recovery exercise (at whatever cadence is operationally feasible, given its cost and complexity) alongside the more frequent in-region cluster-failover-drill and backup-and-restore-validation drills, so this path is not entirely untested until an actual regional event.

## 10. Production Safety

- This is fundamentally an AWS infrastructure recovery process, not a SQL-level operation -- there is no PostgreSQL-side script that performs or substitutes for either recovery path; the guidance here is entirely a change-managed, AWS-control-plane runbook.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Any true regional-loss event triggers this workflow -- by definition, escalate to the highest level of incident command your organization has immediately; this is not a DBA-only response.

## 12. Related Issues

- [cluster-failover-drill](../cluster-failover-drill/README.md)
- [backup-and-restore-validation](../backup-and-restore-validation/README.md)
- [point-in-time-recovery-drill](../point-in-time-recovery-drill/README.md)
