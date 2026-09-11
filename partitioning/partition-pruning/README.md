# Partition Pruning Investigation

**Category:** Partitioning | **Workflow:** `partitioning/partition-pruning`

## 1. Problem Description

Investigates whether queries against a partitioned table are actually benefiting from partition pruning (scanning only relevant partitions) or are unexpectedly scanning all partitions.

## 2. Typical Symptoms

- A partitioned table's query performance is no better than before partitioning.
- EXPLAIN output shows scans against partitions that should have been excluded by the WHERE clause.

## 3. Business Impact

- Partitioning without effective pruning provides none of its intended query-performance benefit while still incurring the operational overhead of managing many partitions.

## 4. Possible Root Causes

- The query's WHERE clause does not directly reference the partition key (e.g. filtering on a derived/cast expression the planner cannot use for pruning).
- The partition key column's data type or the filter's parameter type causes an implicit cast the planner cannot prune across.
- `enable_partition_pruning` is disabled (non-default) at the session/database level.

## 5. Investigation Strategy

1. Run EXPLAIN on the affected query and check which partitions are listed as scanned.
2. Confirm the WHERE clause directly and simply references the partition key column with a compatible type.
3. Confirm enable_partition_pruning is on.

## 6. Prerequisites

- Access to the exact query text being investigated.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_pruning_configuration_check.sql`](scripts/01_pruning_configuration_check.sql) -- Confirms partition pruning is enabled at the session/database level.
2. [`scripts/02_explain_guidance.md`](scripts/02_explain_guidance.md) -- Guidance for using EXPLAIN to confirm whether a specific query against a partitioned table is pruning effectively.

## 8. Interpretation Guide

- EXPLAIN (not EXPLAIN ANALYZE) is sufficient to see which partitions the planner intends to scan (look for 'Subplans Removed' or the explicit list of scanned partition relations) -- no need to execute the query for this specific check.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Rewrite the query's filter to directly reference the partition key column without a wrapping function/cast if that is the cause.

**Short-term remediation** (hours to days):

- Confirm enable_partition_pruning = on at the database/session level.

**Long-term engineering fix** (days to weeks):

- Revisit the partition key choice (partition-existing-large-table) if the application's actual dominant query pattern does not align with the current key.

## 10. Production Safety

- EXPLAIN (without ANALYZE) is always safe -- it does not execute the query.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Pruning cannot be achieved for the dominant query pattern without an application-level query rewrite that the owning team must implement -- escalate to that team with the EXPLAIN evidence.

## 12. Related Issues

- [partition-existing-large-table](../partition-existing-large-table/README.md)
- [analyze-query-plan](../../query-optimization/analyze-query-plan/README.md)
