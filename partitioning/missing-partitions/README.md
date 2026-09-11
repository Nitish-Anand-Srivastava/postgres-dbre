# Missing Partitions

**Category:** Partitioning | **Workflow:** `partitioning/missing-partitions`

## 1. Problem Description

A partitioned table has received (or is about to receive) data for a period/value that has no matching partition, either failing the insert or silently routing to an unintended DEFAULT partition.

## 2. Typical Symptoms

- Application errors: 'no partition of relation found for row'.
- A DEFAULT partition growing unexpectedly large.

## 3. Business Impact

- A missing partition causes hard insert failures for exactly the data the application is trying to write in real time -- for a trading/order platform this can mean rejected writes during live operation.

## 4. Possible Root Causes

- Partition-maintenance automation not keeping ahead of actual data arrival (see partition-maintenance).
- An unexpected list-partition value (e.g. a new market/region code) with no corresponding partition and no DEFAULT partition configured.

## 5. Investigation Strategy

1. Confirm whether a DEFAULT partition exists and, if so, its current size/contents.
2. Identify the specific missing range/value from the application error.
3. Create the missing partition(s) immediately.

## 6. Prerequisites

- DDL privileges to create the missing partition.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_default_partition_check.sql`](scripts/01_default_partition_check.sql) -- Checks whether a DEFAULT partition exists and how much data it currently holds.

## 8. Interpretation Guide

- A populated DEFAULT partition after this incident should be reviewed and, where appropriate, its rows migrated into a properly created specific partition to restore the intended pruning/maintenance benefits.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Create the missing partition immediately using the same DDL pattern as partition-existing-large-table script 06.

**Short-term remediation** (hours to days):

- Audit and migrate any rows that landed in a DEFAULT partition during the gap.

**Long-term engineering fix** (days to weeks):

- See partition-maintenance for the long-term automation fix that prevents recurrence.

## 10. Production Safety

- Creating a new partition is a fast, low-risk metadata operation and safe to perform immediately in production.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The application experienced write failures/rejections due to this gap -- escalate to the application team to assess whether any writes were lost (not just delayed/retried).

## 12. Related Issues

- [partition-maintenance](../partition-maintenance/README.md)
