# Large Tables Inventory

**Category:** Table and Index Health | **Workflow:** `tables-and-indexes/large-tables`

## 1. Problem Description

Routine inventory of the largest tables/indexes in the database, used as a starting point for capacity planning, partitioning, and archiving decisions.

## 2. Typical Symptoms

- No specific symptom -- routine inventory/health-check workflow.

## 3. Business Impact

- Knowing which tables are largest (and growing fastest) focuses capacity, partitioning, and archiving effort where it matters most.

## 4. Possible Root Causes

- N/A.

## 5. Investigation Strategy

1. List largest tables and indexes by total size.
2. Cross-reference against partitioning-and-archival candidacy workflows for the biggest entries.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_largest_tables.sql`](scripts/01_largest_tables.sql) -- Lists the largest tables by total size.
2. [`scripts/02_largest_indexes.sql`](scripts/02_largest_indexes.sql) -- Lists the largest indexes by size.

## 8. Interpretation Guide

- Rank by total_size (heap + indexes + TOAST), not just heap size, for an accurate capacity picture.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A.

**Short-term remediation** (hours to days):

- N/A.

**Long-term engineering fix** (days to weeks):

- Feed this inventory into storage-and-capacity/capacity-forecasting on a recurring basis.

## 10. Production Safety

- Read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- N/A.

## 12. Related Issues

- [rapidly-growing-tables](../rapidly-growing-tables/README.md)
- [capacity-forecasting](../../storage-and-capacity/capacity-forecasting/README.md)
