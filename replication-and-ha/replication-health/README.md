# Overall Replication Health Check

**Category:** Replication and High Availability | **Workflow:** `replication-and-ha/replication-health`

## 1. Problem Description

A routine, holistic health check spanning Aurora reader lag, any external logical replication slots/subscribers, and replication-related configuration -- intended for regular health monitoring rather than active-incident response.

## 2. Typical Symptoms

- No active symptom -- routine health check, suitable for inclusion in database-health/daily-health-check.

## 3. Business Impact

- Regular replication health checks catch a slowly degrading reader or a silently stalled logical replication slot before it becomes a customer-visible incident.

## 4. Possible Root Causes

- N/A -- monitoring workflow.

## 5. Investigation Strategy

1. Check Aurora reader lag across the fleet.
2. Check all replication slots (physical and logical) for active status and retained WAL.
3. Check standard streaming replication for any external consumers.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_aurora_reader_lag_fleet_check.sql`](scripts/01_aurora_reader_lag_fleet_check.sql) -- Fleet-wide Aurora reader lag check.
2. [`scripts/02_replication_slots_health.sql`](scripts/02_replication_slots_health.sql) -- Checks all replication slots for active status and retained WAL as part of the routine health check.

## 8. Interpretation Guide

- A healthy state is: all readers reporting low, stable lag via aurora_replica_status(); every replication slot either active=true or explicitly and knowingly retained for a documented reason; no unexpectedly large retained WAL.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- pivot to the specific workflow (replication-lag, xid-wraparound-risk if a slot is pinning vacuum) matching any finding.

**Short-term remediation** (hours to days):

- N/A.

**Long-term engineering fix** (days to weeks):

- Include this check in the standing automation/health-checks schedule.

## 10. Production Safety

- Read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- An inactive replication slot with significant retained WAL and no known owner -- escalate before dropping it (see transactions-and-xid/xid-wraparound-risk's slot-handling guidance).

## 12. Related Issues

- [replication-lag](../replication-lag/README.md)
- [daily-health-check](../../database-health/daily-health-check/README.md)
- [xid-wraparound-risk](../../transactions-and-xid/xid-wraparound-risk/README.md)
