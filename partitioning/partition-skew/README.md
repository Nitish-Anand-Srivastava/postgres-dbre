# Partition Skew

**Category:** Partitioning | **Workflow:** `partitioning/partition-skew`

## 1. Problem Description

Investigates uneven data distribution across partitions -- some partitions much larger or more heavily accessed than others -- which undermines the maintenance and performance benefits partitioning is meant to provide.

## 2. Typical Symptoms

- One or a few partitions dramatically larger than the rest.
- Query latency uneven across similar queries scoped to different partitions.

## 3. Business Impact

- A severely skewed partition effectively recreates the original 'one giant table' problem within a single partition, while adding the operational overhead of managing many partitions for no corresponding benefit.

## 4. Possible Root Causes

- A range/list partition key with a naturally uneven distribution (e.g. one dominant trading pair or region generating far more volume than others under list partitioning).
- A hash partition count too low for the actual data volume/cardinality.

## 5. Investigation Strategy

1. Compare partition sizes across the table.
2. Cross-reference size skew against known business skew (a dominant trading pair, a large tenant) to determine if it is expected or a key-choice mistake.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_partition_size_distribution.sql`](scripts/01_partition_size_distribution.sql) -- Compares partition sizes across a partitioned table to identify skew.

## 8. Interpretation Guide

- Some skew is expected and acceptable if it reflects genuine business skew (a dominant asset pair will always have more orders) -- the actionable question is whether the largest partition alone is still too large to manage/vacuum/query efficiently, which may call for a compound partition key (e.g. sub-partitioning the largest list value by range).

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- skew is a design consideration, not typically an emergency.

**Short-term remediation** (hours to days):

- Consider sub-partitioning (partition of a partition) the specific oversized partition by an additional key (e.g. range by date within a dominant list value).

**Long-term engineering fix** (days to weeks):

- Revisit partition key/strategy choice if skew consistently undermines partitioning's benefit; this may require a re-migration following partition-existing-large-table's runbook again with a revised key.

## 10. Production Safety

- Investigation scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- The most skewed partition alone has grown large enough to reproduce the original pre-partitioning performance/maintenance problems -- escalate for a redesign decision.

## 12. Related Issues

- [partition-existing-large-table](../partition-existing-large-table/README.md)
- [partition-performance](../partition-performance/README.md)
