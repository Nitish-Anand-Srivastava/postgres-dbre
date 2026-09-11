# Partition Maintenance

**Category:** Partitioning | **Workflow:** `partitioning/partition-maintenance`

## 1. Problem Description

Ongoing operational maintenance for an already-partitioned table: creating future partitions ahead of need, detaching/archiving old ones, and keeping indexes/constraints consistent across all partitions.

## 2. Typical Symptoms

- A time-based partitioned table is approaching the end of its currently-created partitions (writes for a future period would have no matching partition).
- Inconsistent indexes across partitions (some partitions missing an index that others have).

## 3. Business Impact

- Running out of future partitions on an append-only time-series table causes inserts for the missing period to fail outright (no default partition) or silently land in an unintended default partition (a data-integrity risk) if one exists.

## 4. Possible Root Causes

- No automated process creating future partitions ahead of need.
- An index added to the partitioned parent after some partitions were already detached/archived, or added directly to one partition instead of the parent.

## 5. Investigation Strategy

1. Check how many future partitions currently exist and how much runway remains.
2. Check index/constraint consistency across all partitions.
3. Automate partition creation going forward (pg_partman or a scheduled job).

## 6. Prerequisites

- pg_monitor role membership for investigation; DDL privileges for maintenance actions.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_future_partition_runway.sql`](scripts/01_future_partition_runway.sql) -- Checks how many future partitions exist for a time-based partitioned table and how much runway remains.
2. [`scripts/02_index_consistency_across_partitions.sql`](scripts/02_index_consistency_across_partitions.sql) -- Checks whether every partition has the same set of indexes as the partitioned parent, to catch drift from manual per-partition changes.

## 8. Interpretation Guide

- A partitioned table with a DEFAULT partition catching unexpected values is safer against insert failures but risks silently accumulating data that should have been rejected/routed elsewhere -- monitor its size specifically.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Create the next required partition(s) immediately if runway is critically low.

**Short-term remediation** (hours to days):

- Adopt pg_partman (supported on Aurora PostgreSQL) to automate future-partition creation and retention-based partition maintenance.

**Long-term engineering fix** (days to weeks):

- Establish a partition-maintenance automation job (see automation/) with alerting well ahead of any runway exhaustion.

## 10. Production Safety

- Creating a new empty partition is a fast, low-risk metadata operation.
- Detaching a partition (`ALTER TABLE ... DETACH PARTITION`) is fast in PostgreSQL 14+ (CONCURRENTLY option available) but dropping a detached partition is an irreversible data-deleting operation -- always DETACH first and CONFIRM before DROP.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- No automated partition-maintenance process exists for a business-critical partitioned table -- treat this as a standing operational risk and escalate for prioritization.

## 12. Related Issues

- [partition-existing-large-table](../partition-existing-large-table/README.md)
- [automation](../../automation/README.md)
