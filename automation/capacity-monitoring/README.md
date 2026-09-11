# Scheduled Capacity Threshold Monitoring

**Category:** Automation | **Workflow:** `automation/capacity-monitoring`

## 1. Problem Description

The automated, scheduled counterpart to storage-and-capacity/capacity-forecasting and database-health/capacity-health-check -- both of which are, by design, point-in-time or manually-triggered reviews. This workflow documents capturing the same storage, connection, and I/O capacity signals on a recurring schedule with threshold-based alerting, so a capacity ceiling (storage cost trajectory, connection headroom, I/O pressure) is flagged automatically as it is approached, rather than only discovered at the next manually-triggered review.

## 2. Typical Symptoms

- storage-and-capacity/capacity-forecasting or database-health/capacity-health-check has been run manually more than once, and the team wants continuous threshold alerting instead of periodic manual review.
- A capacity ceiling (connection exhaustion, a storage cost jump) was reached without any advance warning because the last manual review was weeks earlier.

## 3. Business Impact

- Connection-capacity exhaustion during a volatility spike is an all-or-nothing failure with no graceful degradation -- scheduled threshold alerting is what catches a climbing utilization trend days or weeks before a spike turns it into an outage.
- Storage cost trajectory is a compounding, permanent-on-Aurora cost; catching it via scheduled monitoring rather than at the next manual review shortens the window during which cost accumulates unnoticed.

## 4. Possible Root Causes

- N/A -- this is a scheduling/automation workflow. See storage-and-capacity/capacity-forecasting and database-health/capacity-health-check for the underlying investigation once a scheduled check crosses a threshold.

## 5. Investigation Strategy

1. Capture the same storage-size, connection-headroom, and I/O/checkpoint signals that capacity-forecasting and capacity-health-check already use, on a recurring schedule.
2. Define concrete alert thresholds for each signal (a connection-utilization percentage, an I/O pressure indicator, a storage growth-rate figure) rather than relying on someone noticing a number looks high during a manual review.
3. Route threshold breaches to the same alerting/ticketing system used for other operational alerts.

## 6. Prerequisites

- `pg_monitor` role membership (or `pg_read_all_stats`) for the read-only scripts in this workflow.
- `pg_cron` must already be installed in this database. It must first be added to `shared_preload_libraries` on the Aurora DB cluster parameter group (requires a reboot to take effect), and then `CREATE EXTENSION pg_cron;` must be run once by an administrator in a change-managed session. This script never creates or schedules anything -- it only detects whether pg_cron is already installed, and prints an instructional notice instead of failing if it is not. Only required if scheduling via pg_cron; the external-scheduler alternative (recommended for this workflow specifically, since it can alert directly) has no such dependency.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_storage_and_connection_snapshot.sql`](scripts/01_storage_and_connection_snapshot.sql) -- Storage-size and connection-utilization snapshot, intended to be captured on every scheduled run and compared against documented thresholds.
2. [`scripts/02_io_and_checkpoint_snapshot.sql`](scripts/02_io_and_checkpoint_snapshot.sql) -- Per-backend-type I/O and checkpoint-pressure snapshot, intended to be captured on every scheduled run since I/O-tier capacity is a separate dimension from raw storage bytes.
3. [`scripts/03_scheduling_runbook.md`](scripts/03_scheduling_runbook.md) -- Documents how to schedule the capacity snapshot scripts with threshold-based alerting, via an external scheduler (preferred, since it can alert directly) or pg_cron plus a separate poller.

## 8. Interpretation Guide

- Prefer the external-scheduler pattern for this workflow specifically over a pure pg_cron/table-logging approach: capacity thresholds usually need to page someone directly (a CloudWatch alarm, a PagerDuty integration), and pg_cron alone cannot reach those systems -- it can only write back into the database.
- A single scheduled run crossing a threshold once, briefly, during an expected volume event (a known listing, a scheduled batch job) is a different finding from a sustained breach across many consecutive runs -- tune alert sensitivity (e.g. require N consecutive breaches before paging) accordingly.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this workflow is scheduling/automation. A specific threshold breach is remediated through storage-and-capacity/capacity-forecasting, connections/max-connections-planning, or the relevant owning workflow.

**Short-term remediation** (hours to days):

- Deploy the scheduled capacity checks and thresholds in this workflow's runbook if they are not already running.

**Long-term engineering fix** (days to weeks):

- Review and adjust alert thresholds periodically as the cluster's baseline instance class, connection pool sizing, and storage footprint change, so thresholds do not become stale relative to a since-changed baseline.

## 10. Production Safety

- Every `.sql` script in this workflow is strictly read-only, identical in safety profile to the storage-and-capacity and database-health scripts it schedules.
- The scheduling runbook documents an external scheduler (preferred) or pg_cron invocation -- markdown, never auto-executed by this repository. No configuration or instance-class change is made by anything in this workflow.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A scheduled check reports sustained (not a single transient) breach of a connection-headroom or storage-growth threshold -- escalate to connections/max-connections-planning or storage-and-capacity/capacity-forecasting respectively for the detailed remediation path.

## 12. Related Issues

- [health-checks](../health-checks/README.md)
- [capacity-forecasting](../../storage-and-capacity/capacity-forecasting/README.md)
- [capacity-health-check](../../database-health/capacity-health-check/README.md)
- [max-connections-planning](../../connections/max-connections-planning/README.md)
