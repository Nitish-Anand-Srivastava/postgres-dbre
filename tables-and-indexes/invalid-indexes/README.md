# Invalid Indexes

**Category:** Table and Index Health | **Workflow:** `tables-and-indexes/invalid-indexes`

## 1. Problem Description

Finds indexes left in an INVALID state after a failed CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY -- unused by the planner, but still consuming storage and write overhead until removed and, if needed, rebuilt.

## 2. Typical Symptoms

- A recent plan regression on a table where a CONCURRENTLY index build was recently attempted.
- Unexplained storage growth from an index providing no query benefit.

## 3. Business Impact

- An invalid index provides zero planner benefit while still paying its full write-overhead and storage cost -- and its presence often directly explains a co-occurring plan regression (see performance/query-regression).

## 4. Possible Root Causes

- A CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY was interrupted (killed session, statement_timeout, deadlock) partway through.

## 5. Investigation Strategy

1. List all invalid indexes.
2. Drop each (a normal, fast DROP INDEX is safe since an invalid index is never in use) and rebuild with CONCURRENTLY if the index is still needed.

## 6. Prerequisites

- DDL privileges to drop/rebuild.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_invalid_indexes.sql`](scripts/01_invalid_indexes.sql) -- Lists all indexes currently in an INVALID state.

## 8. Interpretation Guide

- Any result here is unambiguous -- an invalid index has zero query benefit and should either be dropped (if no longer needed) or rebuilt (if still needed), not left in place.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- Drop the invalid index if identified as the cause of an active plan regression, then immediately rebuild with CONCURRENTLY if it is still needed.

**Short-term remediation** (hours to days):

- Audit recent CONCURRENTLY build failures to understand why they were interrupted (a too-aggressive statement_timeout on the migration role is a common cause).

**Long-term engineering fix** (days to weeks):

- Add a post-migration automated check for invalid indexes to deployment pipelines (see database-health/post-deployment-check).

## 10. Production Safety

- Dropping an invalid index is safe and low-risk (it is never used by the planner). Rebuilding uses CREATE INDEX CONCURRENTLY per schema-changes guidance.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- None typical -- straightforward once found, though the underlying cause of the failed build should still be investigated.

## 12. Related Issues

- [query-regression](../../performance/query-regression/README.md)
- [failed-index-build](../../schema-changes/failed-index-build/README.md)
