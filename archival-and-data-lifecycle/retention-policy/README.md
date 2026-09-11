# Retention Policy Documentation and Enforcement

**Category:** Archiving and Data Lifecycle | **Workflow:** `archival-and-data-lifecycle/retention-policy`

## 1. Problem Description

Establishes and documents durable retention policy per table/data category, distinguishing compliance-mandated retention (must archive, never purge) from purely operational ephemeral data (safe to purge), and tracks which tables have an active, working enforcement mechanism.

## 2. Typical Symptoms

- No single source of truth exists for how long each table's data must be retained.
- A table has grown for years with no active archiving/purging mechanism despite an intended policy.

## 3. Business Impact

- Inconsistent or undocumented retention creates both a compliance risk (data deleted too early) and an operational/cost risk (data kept indefinitely with no plan).

## 4. Possible Root Causes

- Retention policy was decided informally at table-creation time and never documented centrally.
- A previously working archive/purge job was silently disabled or broken and never noticed.

## 5. Investigation Strategy

1. Inventory large/growing tables and their current retention behavior (archived, purged, or neither).
2. Cross-reference against documented compliance requirements.
3. Confirm any claimed automated retention job is actually running and succeeding.

## 6. Prerequisites

- Access to compliance/legal retention requirements documentation.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_growing_tables_without_retention_evidence.sql`](scripts/01_growing_tables_without_retention_evidence.sql) -- Surfaces large, continuously growing tables as candidates to audit against the retention-policy document.

## 8. Interpretation Guide

- A table with continuous growth and no corresponding archive-large-table or purge-old-data mechanism in place is retention policy debt -- flag it even if no incident has occurred yet.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this is a documentation/audit workflow.

**Short-term remediation** (hours to days):

- For any table found lacking an enforcement mechanism, initiate archive-large-table or purge-old-data as appropriate.

**Long-term engineering fix** (days to weeks):

- Maintain a durable, reviewed retention-policy document (docs/) mapping every large/growing table to its retention period, archive/purge mechanism, and last-verified-working date.

## 10. Production Safety

- This workflow itself is investigative/documentation-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A table handling regulated financial data has no confirmed retention mechanism -- escalate to compliance/legal and database engineering leadership immediately.

## 12. Related Issues

- [investigate-archiving-candidate](../investigate-archiving-candidate/README.md)
- [purge-old-data](../purge-old-data/README.md)
- [archive-validation](../archive-validation/README.md)
