# Unused Indexes

**Category:** Table and Index Health | **Workflow:** `tables-and-indexes/unused-indexes`

## 1. Problem Description

Identifies indexes that appear to receive zero or negligible scans, representing pure write-amplification and storage cost with no measured query benefit -- while explicitly guarding against premature removal.

## 2. Typical Symptoms

- Elevated write latency/WAL volume on tables with many indexes.
- Storage growth attributable to index size rather than table size.

## 3. Business Impact

- Every index adds overhead to every INSERT/UPDATE/DELETE on its table; an unused index is pure cost on the hottest part of the workload (writes) for zero benefit.

## 4. Possible Root Causes

- An index created for a query pattern that was later removed/changed in application code.
- A speculative index added 'just in case' that never proved necessary.
- An index that only supports a rare (e.g. quarterly reporting) query and looks unused within a short observation window.

## 5. Investigation Strategy

1. List candidate unused indexes (idx_scan = 0), excluding those backing a constraint.
2. Cross-check stats_reset / instance uptime to ensure the observation window is long enough to be meaningful (must span at least one full business cycle).
3. Confirm with the owning application team before dropping anything.

## 6. Prerequisites

- pg_monitor role membership.
- Confidence that no failover/restart has reset statistics recently (which would make idx_scan = 0 look artificially alarming).

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_unused_index_candidates.sql`](scripts/01_unused_index_candidates.sql) -- Lists candidate unused indexes, excluding those backing a constraint.

## 8. Interpretation Guide

- idx_scan = 0 since the last stats reset is necessary but NOT sufficient evidence to drop an index -- always check stats_reset age and confirm the query pattern that would use this index truly no longer exists (including rare batch/reporting jobs).

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- index removal is always a planned, reviewed action.

**Short-term remediation** (hours to days):

- For a confirmed-unused, non-constraint-backing index, drop it with `DROP INDEX CONCURRENTLY` (see schema-changes/drop-index-safely) during a low-traffic window, keeping the index definition saved in case it needs to be recreated.

**Long-term engineering fix** (days to weeks):

- Add a periodic (e.g. quarterly) unused-index review to standing operational practice (see automation/index-monitoring) rather than a one-off cleanup.

## 10. Production Safety

- The investigation script is read-only.
- Never drop an index the same day it is found 'unused' without confirming the observation window is long enough and the owning team has been consulted.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- An index appears unused but is suspected to back a rare, business-critical batch/compliance job -- escalate to the owning team before any action.

## 12. Related Issues

- [duplicate-indexes](../duplicate-indexes/README.md)
- [drop-index-safely](../../schema-changes/drop-index-safely/README.md)
