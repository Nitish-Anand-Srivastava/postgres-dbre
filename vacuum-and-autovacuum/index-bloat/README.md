# Index Bloat

**Category:** Vacuum and Autovacuum | **Workflow:** `vacuum-and-autovacuum/index-bloat`

## 1. Problem Description

Investigates physical bloat specifically within indexes, which accumulates independently of table bloat and directly slows down index scans and increases index-storage footprint.

## 2. Typical Symptoms

- Index size disproportionately large relative to the table's row count.
- Index scan performance degrading over time without a corresponding table-size change.

## 3. Business Impact

- Bloated indexes on hot lookup columns (order id, account id) directly increase the latency of the most frequent, latency-sensitive queries.

## 4. Possible Root Causes

- High UPDATE churn on indexed columns (each update typically creates a new index entry) without corresponding cleanup.
- A historical bulk delete/update leaving substantial reusable-but-unreclaimed space in the index structure.

## 5. Investigation Strategy

1. Rank indexes by size and scan activity.
2. Cross-reference with the parent table's bloat status, since index bloat commonly correlates with table bloat.
3. Consider REINDEX CONCURRENTLY for confirmed bloated indexes.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_index_bloat_and_usage.sql`](scripts/01_index_bloat_and_usage.sql) -- Index size and usage statistics to identify large, potentially bloated indexes.

## 8. Interpretation Guide

- Unlike tables, indexes generally benefit more directly from a REINDEX to reclaim space efficiently, and PostgreSQL supports `REINDEX INDEX CONCURRENTLY` (non-blocking) as the safe production path -- prefer it over `REINDEX INDEX` (which takes a blocking lock).

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- index bloat remediation is a planned action.

**Short-term remediation** (hours to days):

- `REINDEX INDEX CONCURRENTLY schema.index_name;` during a lower-traffic window, monitoring for the same failure modes as CREATE INDEX CONCURRENTLY (can leave an INVALID index if interrupted).

**Long-term engineering fix** (days to weeks):

- Investigate whether the underlying UPDATE pattern can be reduced (e.g. avoid updating indexed columns unnecessarily) to slow future bloat accumulation.

## 10. Production Safety

- Investigation scripts are read-only.
- REINDEX CONCURRENTLY requires roughly double the index's disk space temporarily and cannot run inside an explicit transaction block; see schema-changes/concurrent-index-build for the full safety runbook.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A hot-path index shows severe bloat and cannot tolerate a REINDEX CONCURRENTLY window without app-visible impact -- escalate to schedule an off-peak maintenance action.

## 12. Related Issues

- [table-bloat](../table-bloat/README.md)
- [index-bloat](../../tables-and-indexes/index-bloat/README.md)
- [concurrent-index-build](../../schema-changes/concurrent-index-build/README.md)
