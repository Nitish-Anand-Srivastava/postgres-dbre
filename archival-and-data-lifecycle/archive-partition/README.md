# Archiving via Partition Detach

**Category:** Archiving and Data Lifecycle | **Workflow:** `archival-and-data-lifecycle/archive-partition`

## 1. Problem Description

For tables already partitioned by a time/range-compatible key, archives historical data by detaching whole partitions instead of row-by-row deletion -- dramatically faster and lower-risk than archive-large-table's batched-DELETE path.

## 2. Typical Symptoms

- A partitioned table has old partitions (e.g. entire months) that are now fully outside the retention window.

## 3. Business Impact

- Partition detach is a near-instant metadata operation regardless of the partition's row count, avoiding the hours of batched deletion an equivalent unpartitioned-table archive would require.

## 4. Possible Root Causes

- N/A -- planned operation, only applicable to already-partitioned tables.

## 5. Investigation Strategy

1. Identify partitions fully outside the retention window.
2. Detach the partition (fast, low-lock metadata operation).
3. Export the detached partition's data to cold storage (it is now a standalone ordinary table).
4. Drop the detached table once its export is validated.

## 6. Prerequisites

- The table must already be partitioned by a boundary compatible with the retention window (see partitioning/partition-existing-large-table if it is not yet partitioned).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_partitions_outside_retention.sql`](scripts/01_partitions_outside_retention.sql) -- Identifies partitions whose range is fully outside the approved retention window.
2. [`scripts/02_detach_and_archive.md`](scripts/02_detach_and_archive.md) -- Detaches the identified old partition and archives it before dropping.

## 8. Interpretation Guide

- `ALTER TABLE ... DETACH PARTITION ... CONCURRENTLY` (PostgreSQL 14+) avoids taking a blocking AccessExclusiveLock on the parent for the duration, at the cost of running as two internal transactions -- prefer it for partitions still receiving any residual read traffic.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A.

**Short-term remediation** (hours to days):

- N/A.

**Long-term engineering fix** (days to weeks):

- Automate this pattern for time-based partitioned tables via pg_partman's retention policies (see partitioning/partition-maintenance).

## 10. Production Safety

- DETACH PARTITION (especially CONCURRENTLY) is a fast, low-risk operation. DROP TABLE on the detached partition is irreversible -- always export/validate first, exactly as in archive-large-table.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The detached partition's data has not been fully exported/validated and there is pressure to drop it early -- escalate/push back; do not skip validation.

## 12. Related Issues

- [archive-large-table](../archive-large-table/README.md)
- [partition-maintenance](../../partitioning/partition-maintenance/README.md)
