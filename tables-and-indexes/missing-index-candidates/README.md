# Missing Index Candidates

**Category:** Table and Index Health | **Workflow:** `tables-and-indexes/missing-index-candidates`

## 1. Problem Description

Identifies tables/query patterns that would likely benefit from a new index -- unindexed foreign keys, and tables with heavy sequential scans relative to their size.

## 2. Typical Symptoms

- Queries filtering/joining on a column with no supporting index, visible as high seq_scan/seq_tup_read in pg_stat_all_tables.
- UPDATE/DELETE on a parent row taking noticeably long due to an unindexed FK on the child table.

## 3. Business Impact

- A missing index on a hot query path is one of the most common and highest-leverage fixes for both high-cpu and slow-queries incidents.

## 4. Possible Root Causes

- A new query pattern shipped without an accompanying index.
- A foreign key added without a supporting index on the referencing column(s).
- Data growth crossed the threshold where a sequential scan is no longer efficient for a previously-fine query.

## 5. Investigation Strategy

1. Check for unindexed foreign keys.
2. Check for sequential-scan-heavy tables.
3. Confirm against actual query patterns (pg_stat_statements) before adding an index speculatively.

## 6. Prerequisites

- pg_stat_statements recommended for confirming the query pattern.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_unindexed_foreign_keys.sql`](scripts/01_unindexed_foreign_keys.sql) -- Finds foreign key constraints with no supporting index on the referencing (child) columns.
2. [`scripts/02_sequential_scan_heavy_tables.sql`](scripts/02_sequential_scan_heavy_tables.sql) -- Finds large tables with a high sequential-scan-to-row-read ratio, a proxy for a missing index on a filter/join column.

## 8. Interpretation Guide

- Add indexes based on confirmed query patterns, not just theoretical schema analysis -- an unindexed FK that is never used in a JOIN/lookup direction may not need an index despite appearing in this report.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- always add indexes deliberately, never as an emergency same-incident action unless directly resolving an active severe incident with full understanding of the tradeoffs.

**Short-term remediation** (hours to days):

- Add the identified index using `CREATE INDEX CONCURRENTLY` (see schema-changes/concurrent-index-build).

**Long-term engineering fix** (days to weeks):

- Add FK-index-coverage and query-pattern review to the standard schema/migration review checklist.

## 10. Production Safety

- Investigation scripts are read-only; index creation must always use CONCURRENTLY per schema-changes guidance.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A confirmed missing index is on an extremely large, hot table where even a CONCURRENTLY build carries meaningful resource-consumption risk -- coordinate a build window with the owning team.

## 12. Related Issues

- [sequential-scan-investigation](../sequential-scan-investigation/README.md)
- [concurrent-index-build](../../schema-changes/concurrent-index-build/README.md)
