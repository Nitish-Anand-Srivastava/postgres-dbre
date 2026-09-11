# Duplicate Indexes

**Category:** Table and Index Health | **Workflow:** `tables-and-indexes/duplicate-indexes`

## 1. Problem Description

Identifies structurally identical or fully redundant indexes on the same table -- pure waste with no tradeoff, unlike unused-indexes which requires judgment about rare query patterns.

## 2. Typical Symptoms

- Two or more indexes on the same table with the same columns/expressions/predicate.

## 3. Business Impact

- Duplicate indexes are unambiguous waste: every one adds write overhead and storage without any additional query benefit over its twin.

## 4. Possible Root Causes

- An ORM or migration tool creating an index that already existed manually.
- A renamed/recreated index left alongside its original instead of replacing it.
- Independent teams adding the same index unaware of each other's prior work.

## 5. Investigation Strategy

1. Find indexes with matching normalized definitions on the same table.
2. Confirm neither is required for a differently-named constraint before dropping either.

## 6. Prerequisites

- pg_monitor role membership.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_duplicate_indexes.sql`](scripts/01_duplicate_indexes.sql) -- Finds indexes with identical normalized definitions on the same table.

## 8. Interpretation Guide

- Unlike unused-indexes, true structural duplicates provide no scenario where keeping both is beneficial -- the only decision is which one to keep (usually the one with the more descriptive name, or the one backing a constraint).

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- None -- always a planned, reviewed action.

**Short-term remediation** (hours to days):

- Drop the redundant duplicate using `DROP INDEX CONCURRENTLY` (see schema-changes/drop-index-safely), keeping only one copy.

**Long-term engineering fix** (days to weeks):

- Add a duplicate-index check to CI/migration review to prevent recurrence.

## 10. Production Safety

- Investigation script is read-only; drop guidance follows schema-changes/drop-index-safely's safety practices.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- None typical -- this is usually a low-risk, straightforward cleanup once confirmed.

## 12. Related Issues

- [unused-indexes](../unused-indexes/README.md)
- [drop-index-safely](../../schema-changes/drop-index-safely/README.md)
