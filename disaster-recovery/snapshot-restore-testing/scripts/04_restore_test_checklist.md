# 04_restore_test_checklist

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_restore_test_checklist.md` |
| Purpose | The ordered checklist for a snapshot restore test, including the business-data spot checks that a catalog-level fingerprint comparison cannot cover. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | DOCUMENTATION -- no SQL executed by this file itself |
| Expected impact | None from this file directly; the restore steps it sequences carry the impact documented in script 03. |
| Required privileges | N/A for this file itself; see scripts 01, 02, and 03 for their own required privileges. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 04 of workflow `disaster-recovery/snapshot-restore-testing` |
| Related scripts | 01_source_cluster_fingerprint.sql, 02_restored_cluster_validation.sql, 03_snapshot_restore_runbook.md, ../rto-rpo-validation/README.md |

## How to interpret / use this runbook

Follow the checklist end to end, including teardown -- the steps most often skipped are the business-data spot checks in step 7 and the deletion confirmation in step 14, and both are the ones that matter most.

---

## Before the test

1. Confirm the scratch VPC, subnet group, security group, and parameter group exist and are documented -- create them ahead of time, not during the test.
2. Confirm KMS key access for the snapshot if it is encrypted, including for a cross-account or cross-region copy.
3. Run `01_source_cluster_fingerprint.sql` on production and save the output with its capture time.
4. Record T0 for the RTO measurement (see `rto-rpo-validation`).

## Restore

5. Follow `03_snapshot_restore_runbook.md` steps 1 through 4, recording the elapsed time for the cluster restore and instance provisioning separately.

## Validate

6. Run `02_restored_cluster_validation.sql` on the restored cluster and diff every result set against the saved source fingerprint.
7. Spot-check business-critical data directly -- a catalog fingerprint confirms shape, not correctness. On a trading platform this usually means: the most recent rows in the trades and order-events tables, a sample of account balances reconciled against the ledger, the most recent deposit and withdrawal records, and the newest partition of any time-partitioned table. Confirm the newest data present is consistent with the snapshot's creation time rather than materially older.
8. Confirm sequence values are ahead of the maximum key values in their tables, so a cluster promoted from this restore would not immediately collide on insert.
9. Confirm no index is INVALID (script 02's last result set) and that the extension inventory matches the source.
10. If the application has a read-only smoke test suite that can be pointed at an arbitrary endpoint, run it against the restored cluster -- this is the strongest single piece of evidence a restore test can produce.

## Record

11. Record the measured restore duration and the observed recovery point in the register described in `../rto-rpo-validation/README.md`.
12. Record every deviation, blocker, or manual intervention -- these are the items that would have cost time during a real incident, and they are the real output of the test.

## Tear down

13. Delete the scratch instance and cluster the same day, following step 6 of `03_snapshot_restore_runbook.md`.
14. Confirm deletion actually completed rather than assuming it -- a delete call that failed on a deletion-protection flag leaves a production-data cluster running indefinitely.

## Cadence

Quarterly at minimum, and additionally before any migration or release whose rollback plan depends on restoring a snapshot. A rollback plan that depends on an untested restore is not a rollback plan.
