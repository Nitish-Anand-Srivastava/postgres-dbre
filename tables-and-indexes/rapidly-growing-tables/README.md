# Rapidly Growing Tables

**Category:** Table and Index Health | **Workflow:** `tables-and-indexes/rapidly-growing-tables`

## 1. Problem Description

Identifies which tables are growing fastest (not just which are currently largest), the more actionable signal for proactive capacity planning, partitioning, and archiving prioritization.

## 2. Typical Symptoms

- Overall database storage growth trend exceeds expectations.
- A specific table's size has doubled within an unexpectedly short window.

## 3. Business Impact

- A rapidly growing table will become tomorrow's largest-table problem; catching growth rate early gives more lead time for a partitioning/archiving decision than waiting until it is already enormous.

## 4. Possible Root Causes

- Organic business growth (more users, more trades).
- A new feature writing at a much higher rate than anticipated.
- A missing archiving/retention mechanism allowing indefinite accumulation.

## 5. Investigation Strategy

1. Requires historical snapshots (see automation/growth-monitoring) to compute a genuine growth rate, not just a single point-in-time size.
2. Compare growth rate against the largest-tables inventory to prioritize.

## 6. Prerequisites

- A historical size-tracking table populated by automation/growth-monitoring; without it, this workflow can only establish current state, not a rate.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_growth_rate_from_history.sql`](scripts/01_growth_rate_from_history.sql) -- Computes growth over a lookback window using a historical size-tracking table populated by automation/growth-monitoring.

## 8. Interpretation Guide

- A small table growing 10x/month is a more urgent long-term concern than a huge table growing 1%/month, even though the huge table is 'larger' today.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A.

**Short-term remediation** (hours to days):

- Flag rapidly growing tables for investigate-partitioning-candidate / investigate-archiving-candidate assessment.

**Long-term engineering fix** (days to weeks):

- Ensure automation/growth-monitoring is actively populating historical snapshots so this workflow remains usable over time.

## 10. Production Safety

- Read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A core financial table's growth rate significantly exceeds the capacity plan's assumptions -- escalate to capacity planning/database engineering leadership.

## 12. Related Issues

- [large-tables](../large-tables/README.md)
- [growth-monitoring](../../automation/growth-monitoring/README.md)
