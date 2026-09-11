# Archive Validation

**Category:** Archiving and Data Lifecycle | **Workflow:** `archival-and-data-lifecycle/archive-validation`

## 1. Problem Description

Standalone, repeatable validation procedures to confirm an existing archive (already exported, whether recently or long ago) remains complete, queryable, and restorable -- distinct from the one-time validation performed during an active archive-large-table migration.

## 2. Typical Symptoms

- An archive has not been test-restored/validated since it was created.
- Uncertainty about whether an archive destination (S3, a separate database) is still accessible and intact.

## 3. Business Impact

- An archive that cannot actually be restored/queried when needed (for an audit, a legal request, or a data-recovery need) provides none of the assurance it was created for.

## 4. Possible Root Causes

- Archive validation was a one-time step at creation and was never repeated.
- Underlying storage (S3 bucket policy, a decommissioned archive database) changed in a way that broke access without anyone noticing.

## 5. Investigation Strategy

1. Periodically re-run row-count reconciliation between the source table's retained metadata (if any) and the archive.
2. Periodically test an actual restore/query against the archive destination.
3. Confirm access credentials/permissions to the archive destination are still valid.

## 6. Prerequisites

- Access to both the (if still present) source-side archival record and the archive destination.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_periodic_archive_reconciliation.sql`](scripts/01_periodic_archive_reconciliation.sql) -- Re-runs the row-count/checksum reconciliation used during the original archive to confirm the archive remains intact over time.

## 8. Interpretation Guide

- A successful validation is not just 'the S3 object exists' -- it means the data was actually queried/restored and matched expectations.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If validation fails, treat it as a data-loss risk and escalate immediately -- do not wait for a real audit/legal request to discover the problem.

**Short-term remediation** (hours to days):

- Fix access/permission issues found during validation.

**Long-term engineering fix** (days to weeks):

- Schedule recurring archive-validation checks (see automation/) rather than relying on a single point-in-time validation from the original archive-large-table run.

## 10. Production Safety

- Validation queries against the archive destination are read-only; validation against the source table (if any residual metadata is compared) is also read-only.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- An archive fails validation and no other copy of the data exists -- escalate immediately as a potential data-loss/compliance incident.

## 12. Related Issues

- [archive-large-table](../archive-large-table/README.md)
- [retention-policy](../retention-policy/README.md)
