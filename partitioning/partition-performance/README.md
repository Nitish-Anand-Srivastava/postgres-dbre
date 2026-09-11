# Partition Performance

**Category:** Partitioning | **Workflow:** `partitioning/partition-performance`

## 1. Problem Description

Investigates whether partitioning is delivering its expected performance benefits (or introducing unexpected regressions) for query, vacuum, and DML performance on the partitioned table as a whole.

## 2. Typical Symptoms

- Overall query performance against the partitioned table has not improved (or has regressed) since migration.
- Cross-partition queries (aggregates spanning many/all partitions) are slower than expected.

## 3. Business Impact

- If partitioning does not deliver the expected benefit, the operational overhead of maintaining many partitions (index management, constraint management, partition-maintenance automation) becomes pure cost with no corresponding gain.

## 4. Possible Root Causes

- Poor partition pruning for the dominant query pattern (see partition-pruning).
- Too many partitions, adding planner/executor overhead for queries that must consider all of them (common with an overly fine-grained partition scheme).
- Partition skew concentrating most activity on one partition (see partition-skew), meaning that partition alone still behaves like an unpartitioned large table.

## 5. Investigation Strategy

1. Confirm pruning is effective for the dominant query pattern.
2. Check total partition count against the table's actual size/access pattern -- too many small partitions can hurt as much as too few large ones.
3. Check whether performance-sensitive queries are cross-partition aggregates that inherently cannot benefit from pruning.

## 6. Prerequisites

- pg_stat_statements for query-level timing comparison.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_partition_count_and_size_overview.sql`](scripts/01_partition_count_and_size_overview.sql) -- Overview of total partition count and size distribution, to assess whether the granularity itself is appropriate.

## 8. Interpretation Guide

- Cross-partition aggregate queries (e.g. a dashboard summing across all history) are expected to scan multiple/all partitions regardless of partitioning -- partitioning helps write/vacuum/maintenance performance and single-partition-scoped query performance, not necessarily whole-table aggregate performance.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- this is a tuning/design investigation.

**Short-term remediation** (hours to days):

- Reduce partition count (merge overly fine-grained partitions) if planner overhead from a very large partition count is measurable.

**Long-term engineering fix** (days to weeks):

- Consider a pre-aggregated summary table/materialized view for cross-partition dashboard queries instead of expecting partitioning alone to solve that access pattern.

## 10. Production Safety

- Investigation scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The partition scheme requires a fundamental redesign -- escalate to database engineering for a re-migration planning discussion.

## 12. Related Issues

- [partition-pruning](../partition-pruning/README.md)
- [partition-skew](../partition-skew/README.md)
