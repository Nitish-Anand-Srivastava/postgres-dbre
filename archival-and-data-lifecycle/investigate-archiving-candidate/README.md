# Investigating an Archiving Candidate

**Category:** Archiving and Data Lifecycle | **Workflow:** `archival-and-data-lifecycle/investigate-archiving-candidate`

## 1. Problem Description

Determines whether a table is a good candidate for archiving/retention-based purging, and establishes the data required (growth rate, access pattern, regulatory retention requirements) to plan a safe archive-large-table migration.

## 2. Typical Symptoms

- A table's growth is a recurring topic in capacity planning.
- Old data in the table is rarely or never queried by the live application.

## 3. Business Impact

- Archiving reduces storage cost, improves vacuum/backup efficiency, and reduces the working set for queries and cache -- but for a financial platform, retention must also satisfy regulatory/compliance requirements, which take priority over any performance motivation.

## 4. Possible Root Causes

- N/A -- feasibility assessment workflow.

## 5. Investigation Strategy

1. Check table growth trend and current size.
2. Check the access-age profile: what fraction of queries touch recent vs. old data.
3. Confirm regulatory/compliance retention requirements with legal/compliance stakeholders before setting any retention boundary.

## 6. Prerequisites

- Legal/compliance sign-off on minimum retention period before any purge boundary is finalized -- this is a compliance decision, not a purely technical one, especially for ledger/transaction history.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_table_growth_and_age_profile.sql`](scripts/01_table_growth_and_age_profile.sql) -- Checks table size and estimates the age distribution of its data via a candidate timestamp column.
2. [`scripts/02_recent_vs_historical_query_pattern.sql`](scripts/02_recent_vs_historical_query_pattern.sql) -- Reviews top queries against the table to assess whether the live application query pattern is scoped to recent data only.

## 8. Interpretation Guide

- A table where the vast majority of queries filter on a recent time window (e.g. 'last 90 days') while the table itself spans years of history is a strong archiving candidate -- the old data is costing storage/vacuum/backup overhead without serving the live query pattern.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A.

**Short-term remediation** (hours to days):

- If confirmed a good candidate with a compliance-approved retention boundary, proceed to archive-large-table.

**Long-term engineering fix** (days to weeks):

- Establish a standing retention-policy document (see retention-policy) so future tables are designed with archiving in mind from the start.

## 10. Production Safety

- All scripts are read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Retention requirements are unclear or contested -- escalate to legal/compliance before proceeding with any technical planning.

## 12. Related Issues

- [archive-large-table](../archive-large-table/README.md)
- [retention-policy](../retention-policy/README.md)
