# Purging Old Data (Non-Archived Deletion)

**Category:** Archiving and Data Lifecycle | **Workflow:** `archival-and-data-lifecycle/purge-old-data`

## 1. Problem Description

Investigates and safely executes deletion of old data that does NOT need to be retained/archived at all (e.g. expired sessions, ephemeral cache-like rows, expired idempotency keys) -- distinct from archive-large-table, where the data must be preserved in cold storage first.

## 2. Typical Symptoms

- A table of inherently ephemeral/expiring data (sessions, tokens, idempotency keys, rate-limit counters) growing without bound.
- No compliance requirement to retain this specific data at all.

## 3. Business Impact

- Ephemeral tables left unpurged grow indefinitely, consuming storage and slowing down any query/index touching them for no business benefit.

## 4. Possible Root Causes

- No scheduled purge job ever implemented for a table designed to hold only transient data.
- A purge job exists but has silently stopped running or is filtering incorrectly.

## 5. Investigation Strategy

1. Confirm the data genuinely requires no retention (distinct from archive-large-table's compliance-sensitive data).
2. Check current row count/growth and the age distribution of rows.
3. Implement or fix a scheduled batched purge.

## 6. Prerequisites

- Explicit confirmation that this data has zero compliance/audit retention requirement -- if there is any doubt, treat it as an archive-large-table candidate instead, not a purge candidate.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_ephemeral_table_growth_check.sql`](scripts/01_ephemeral_table_growth_check.sql) -- Checks size and age distribution for a candidate ephemeral/expiring table.
2. [`scripts/02_batched_purge.md`](scripts/02_batched_purge.md) -- Batched purge template for confirmed-ephemeral data with no retention requirement.

## 8. Interpretation Guide

- Unlike archive-large-table, purge-old-data does not require an export step, since the data is deliberately being discarded -- but the batched-deletion safety practices (small batches, monitoring WAL/replica lag) still fully apply.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Run a batched purge for the current backlog if one has never been run or has stalled.

**Short-term remediation** (hours to days):

- Schedule a recurring automated purge job (see automation/) sized to keep the table consistently small going forward rather than requiring periodic large manual catch-up purges.

**Long-term engineering fix** (days to weeks):

- Add a TTL-style design pattern (e.g. an expires_at column with an index, or partitioning by creation time with routine detach+drop) for any new ephemeral table from the outset.

## 10. Production Safety

- Batched DELETE guidance mirrors archive-large-table's script 05 -- small batches, monitored, never a single unbounded statement.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Uncertainty about whether the data actually requires retention -- escalate to compliance before purging; when in doubt, do not purge.

## 12. Related Issues

- [archive-large-table](../archive-large-table/README.md)
- [retention-policy](../retention-policy/README.md)
