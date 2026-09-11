# Index Bloat (Tables-and-Indexes View)

**Category:** Table and Index Health | **Workflow:** `tables-and-indexes/index-bloat`

## 1. Problem Description

Table/index-health-focused entry point for index bloat investigation; see vacuum-and-autovacuum/index-bloat for the vacuum-lifecycle perspective on the same underlying issue.

## 2. Typical Symptoms

- Index size disproportionate to table row count.
- Index scan latency degrading over time.

## 3. Business Impact

- Bloated indexes on hot lookup paths directly increase the latency of the most frequent queries.

## 4. Possible Root Causes

- High UPDATE churn on indexed columns without full space reclamation.
- See vacuum-and-autovacuum/index-bloat for the complete root-cause list.

## 5. Investigation Strategy

1. Rank indexes by size and usage.
2. Confirm bloat with pgstattuple if a precise figure is needed.
3. Plan a REINDEX CONCURRENTLY if confirmed.

## 6. Prerequisites

- pg_monitor role membership; pgstattuple optional for exact confirmation.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_index_bloat_and_usage.sql`](scripts/01_index_bloat_and_usage.sql) -- Index size and usage statistics to identify large, potentially bloated indexes.

## 8. Interpretation Guide

- See vacuum-and-autovacuum/index-bloat's interpretation guidance -- this workflow exists as the tables-and-indexes-category entry point to the same investigation for discoverability.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- planned action.

**Short-term remediation** (hours to days):

- REINDEX INDEX CONCURRENTLY during a lower-traffic window.

**Long-term engineering fix** (days to weeks):

- See vacuum-and-autovacuum/autovacuum-not-keeping-up for the systemic prevention angle.

## 10. Production Safety

- Investigation is read-only; REINDEX CONCURRENTLY guidance is in schema-changes/concurrent-index-build.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Same as vacuum-and-autovacuum/index-bloat.

## 12. Related Issues

- [index-bloat](../../vacuum-and-autovacuum/index-bloat/README.md)
- [concurrent-index-build](../../schema-changes/concurrent-index-build/README.md)
