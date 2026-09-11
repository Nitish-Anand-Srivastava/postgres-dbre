# Scripts: Snapshot Restore Testing

Execution order, safety classification, and expected runtime for every script
in `disaster-recovery/snapshot-restore-testing/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_source_cluster_fingerprint.sql` | Fingerprints the source cluster immediately before the snapshot restore test: object inventory, per-table row estimates and sizes, extensions, and key settings. | READ ONLY | Low, though the per-table sizing portion touches every relation's size on disk -- run it off-peak on a cluster with very many relations. |
| 02 | `02_restored_cluster_validation.sql` | Run on the restored scratch cluster: repeats the source fingerprint and adds engine identity and instance role, for a direct comparison against script 01. | READ ONLY | Low, though the per-table sizing portion touches every relation's size on disk. |
| 03 | `03_snapshot_restore_runbook.md` | AWS-side guidance for selecting a snapshot, restoring it into an isolated scratch cluster, provisioning an instance, and tearing the environment down afterward. | INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY | Minutes for the restore call; tens of minutes to hours for the cluster restore plus instance provisioning, scaling with data volume and instance class. |
| 04 | `04_restore_test_checklist.md` | The ordered checklist for a snapshot restore test, including the business-data spot checks that a catalog-level fingerprint comparison cannot cover. | DOCUMENTATION -- no SQL executed by this file itself | Variable -- dominated by the restore and instance provisioning time in script 03. |

## Execution Order

Run scripts strictly in the numeric order shown above. Each script assumes the
operator has reviewed the output of the prior step. Do not skip ahead to a
remediation template (`.md` files, if present) without completing the
read-only investigation steps first.

## Required Permissions

Unless a script states otherwise in its `REQUIRED PRIVILEGES` header field, a
role with the built-in `pg_monitor` (or `pg_read_all_stats` /
`pg_read_all_settings`) attribute, `CONNECT` on the target database, and
`USAGE` on `public` is sufficient. Scripts that read `pg_stat_statements`
require that extension to be installed in the current database. Scripts that
touch DDL, `pg_terminate_backend()`, or write operations state elevated
requirements explicitly in their own header.

## Expected Output

Every script returns a result set intended to be read directly in `psql` (or
any SQL client). Columns are named for direct interpretation; each script's
header contains a `HOW TO INTERPRET RESULTS` section, and the parent
`README.md` section 8 ("Interpretation Guide") gives workflow-level guidance.

## When to Stop and Escalate

- A snapshot fails to restore for any reason -- escalate immediately and treat the rollback plan that depended on it as invalid until a successful restore is demonstrated.
- The restored cluster's fingerprint differs from the source in ways that are not explained by the time gap between the snapshot and the fingerprint -- escalate to AWS Support and to the platform and compliance owners, since this calls actual data recoverability into question.
- The measured restore duration substantially exceeds the documented RTO for the restore scenario -- escalate through rto-rpo-validation as a policy gap.

## Scripts That Should Not Be Run During Severe Incidents

- 03_snapshot_restore_runbook.md -- No impact on the production cluster -- a snapshot restore always creates a new cluster. Creates temporary AWS cost for the scratch cluster and instance until they are deleted.
- 04_restore_test_checklist.md -- None from this file directly; the restore steps it sequences carry the impact documented in script 03.
