# Table Bloat (Tables-and-Indexes View)

**Category:** Table and Index Health | **Workflow:** `tables-and-indexes/table-bloat`

## 1. Problem Description

Table/index-health-focused entry point for table bloat investigation; see vacuum-and-autovacuum/table-bloat for the vacuum-lifecycle perspective on the same underlying issue.

## 2. Typical Symptoms

- Table on-disk size much larger than expected for its live row count.

## 3. Business Impact

- Bloat increases storage cost and the number of pages scanned per query.

## 4. Possible Root Causes

- See vacuum-and-autovacuum/table-bloat for the complete root-cause list.

## 5. Investigation Strategy

1. Estimate bloat via the catalog-only proxy.
2. Confirm with pgstattuple for top candidates.
3. Plan remediation per vacuum-and-autovacuum/table-bloat / maintenance/.

## 6. Prerequisites

- pgstattuple optional for exact confirmation.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_bloat_estimate_catalog_only.sql`](scripts/01_bloat_estimate_catalog_only.sql) -- Lightweight, lock-free bloat proxy.
2. [`scripts/02_exact_bloat_pgstattuple.sql`](scripts/02_exact_bloat_pgstattuple.sql) -- Exact physical bloat scan for one specific table.

## 8. Interpretation Guide

- See vacuum-and-autovacuum/table-bloat's interpretation guidance.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- planned action.

**Short-term remediation** (hours to days):

- Confirm autovacuum is keeping pace (autovacuum-not-keeping-up) before considering a space-reclaiming operation.

**Long-term engineering fix** (days to weeks):

- Schedule a maintenance-window VACUUM FULL/pg_repack if confirmed severe (see maintenance/).

## 10. Production Safety

- Investigation is read-only; pgstattuple's exact scan can be I/O intensive on very large tables.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Same as vacuum-and-autovacuum/table-bloat.

## 12. Related Issues

- [table-bloat](../../vacuum-and-autovacuum/table-bloat/README.md)
- [maintenance](../../maintenance/README.md)
