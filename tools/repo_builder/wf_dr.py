"""Workflow definitions: disaster-recovery/ category (4 workflow directories).

This is an OPEN_CATALOG category (see tools/validation/catalog.py) -- there
is no fixed, exact required workflow slug list, only a requirement that the
category directory exists and has at least one workflow. One slug is
mandatory regardless: `cluster-failover-drill`, since several already-built
workflows in other categories link directly to it. The four workflows below
cover a planned failover drill, backup/restore validation, point-in-time
recovery planning, and the worst-case cross-region/full-cluster-loss
scenario -- together spanning Aurora's disaster-recovery surface from a
routine drill to a true regional-loss event.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import ANY_INSTANCE, md_script, sql_script
from .model import Workflow

CATEGORY_SLUG = "disaster-recovery"
CATEGORY_TITLE = "Disaster Recovery"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

# ---------------------------------------------------------------------------
# cluster-failover-drill  (MANDATORY exact slug -- linked from several
# already-built workflows in performance/ and replication-and-ha/)
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="cluster-failover-drill",
    title="Aurora Cluster Failover Drill",
    summary="A planned, deliberately triggered failover of the Aurora cluster to validate that the reader fleet, application connection handling, and operational runbooks all behave as expected -- run proactively, on a schedule, rather than waiting to learn the answer during an unplanned failover.",
    symptoms=["No active symptom -- this is a proactive, scheduled drill, typically run quarterly or ahead of a major application change that depends on HA behavior.", "Also run after replication-and-ha/failover-readiness identifies a gap, to empirically confirm the fix actually works, not just that the configuration looks correct."],
    business_impact=["An untested failover path is a false sense of security -- Aurora's HA mechanism is only as good as the application's actual behavior during the brief cutover, and the only way to know that behavior for certain is to trigger a real failover deliberately, on your own schedule, rather than for the first time during an unplanned production incident."],
    root_causes=["N/A -- this is a proactive validation workflow, not a root-cause investigation for a symptom."],
    investigation_strategy=["Confirm current writer/reader topology and pick a healthy, low-lag reader as the failover target.", "Confirm every reader's replication lag is low immediately before triggering the drill, so the drill measures the failover mechanism itself, not a pre-existing lag problem.", "Trigger the failover via the AWS control plane (never via SQL) and observe application-visible impact during the cutover.", "Verify the new writer's identity and health immediately afterward."],
    prerequisites=["AWS IAM permission to call rds:FailoverDBCluster; a maintenance window or otherwise-acceptable time to intentionally disrupt connections for the drill's duration; stakeholder awareness that a deliberate, brief disruption is about to occur."],
    interpretation_guide=["A healthy drill looks like: the promoted reader becomes the new writer, the cluster endpoint DNS re-points to it, and connected applications experience a brief (typically tens of seconds) burst of connection errors/retries before resuming normally -- this is expected and is exactly what the drill is meant to confirm, not a failure of the drill.", "If the application does not recover on its own within a couple of minutes without manual intervention, that is the actual finding: something in the application's connection handling (a hardcoded instance endpoint, no retry/backoff, an over-eager circuit breaker that does not reset) needs to be fixed before the next drill, not something to work around during this one."],
    remediation_immediate=["N/A -- if the drill reveals the application does not recover on its own, that is a finding to fix before the next drill, not something to remediate live during this one (this is a planned exercise, not an incident)."],
    remediation_short_term=["Fix any application-side issue the drill surfaced (hardcoded instance endpoint, missing retry/backoff, connection pool not detecting the topology change) and re-run a subset of the drill to confirm the fix."],
    remediation_long_term=["Establish a standing quarterly (or more frequent) cadence for this drill so HA readiness is continuously validated rather than assumed, and track drill results (time-to-recovery, any manual intervention needed) over time as a trend."],
    production_safety=["This workflow's SQL scripts are entirely read-only. The failover itself is an AWS control-plane action (not a SQL statement) that deliberately and briefly disrupts every existing connection to the cluster -- this is the whole point of the drill, but it must be scheduled and communicated, never triggered casually."],
    escalation_criteria=["The application does not recover within a reasonable window (several minutes) without manual intervention -- treat this as the drill's primary finding and open a tracking issue with the owning application team immediately, since the next failover may not be a scheduled drill."],
    related_issues=["../../replication-and-ha/failover-investigation/README.md", "../../replication-and-ha/failover-readiness/README.md", "../../performance/performance-after-failover/README.md", "../../database-health/post-maintenance-check/README.md"],
    aurora_notes=["Aurora failover is fundamentally different from a traditional PostgreSQL physical-standby promotion: it promotes an existing reader (already attached to the same shared distributed storage volume as the writer, so no data needs to be copied) and re-points the cluster endpoint's DNS to it, typically completing the client-visible cutover in well under a minute -- there is no lengthy WAL-replay-then-promote sequence, and the operation is triggered exclusively through the AWS control plane (Console, CLI, or API), never through any SQL statement."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_confirm_writer_reader_topology", "Confirms current writer/reader role, run against each endpoint the application actually uses (cluster/writer endpoint and reader endpoint), as the pre-drill topology baseline.",
               sb.cluster_recovery_role(),
               "Run this against every endpoint your applications are configured to use, immediately before the drill. Any endpoint that does not resolve to the role you expect (e.g. an application hardcoded to a specific instance rather than the cluster endpoint) is a readiness gap to fix before running the drill, not during it -- see replication-and-ha/failover-readiness.",
               execution_location=ANY_INSTANCE,
               related_scripts="02_reader_health_and_lag_precheck.sql"),
    sql_script("02", "02_reader_health_and_lag_precheck", "Confirms every reader's replication lag is low immediately before triggering the drill, so the drill measures the failover mechanism itself rather than a pre-existing lag problem.",
               sb.aurora_replica_status(),
               "Every reader should show low, stable lag before proceeding. If the reader you intend to promote (or any reader) shows elevated lag, either wait for it to stabilize or explicitly target a healthy reader via --target-db-instance-identifier in the drill runbook -- do not proceed against a reader you have not confirmed healthy.",
               related_scripts="03_failover_drill_runbook.md"),
    md_script("03", "03_failover_drill_runbook", "Guarded runbook for triggering the actual Aurora failover via the AWS control plane and observing application-visible impact during the cutover.",
              (
                  "## Before triggering\n\n"
                  "1. Confirm `01_confirm_writer_reader_topology.sql` and "
                  "`02_reader_health_and_lag_precheck.sql` both look healthy.\n"
                  "2. Confirm stakeholders are aware a brief, deliberate connection disruption is "
                  "about to occur, and that this is happening inside an agreed window.\n"
                  "3. Have application-side dashboards/logs open so the cutover's application-visible "
                  "impact can be observed in real time, not just inferred afterward.\n\n"
                  "## Triggering the failover\n\n"
                  "Aurora failover is an AWS control-plane operation -- it is never triggered via a SQL "
                  "statement or function call from inside PostgreSQL:\n\n"
                  "```\n"
                  "aws rds failover-db-cluster \\\n"
                  "  --db-cluster-identifier <cluster-identifier> \\\n"
                  "  --target-db-instance-identifier <target-reader-instance-identifier>\n"
                  "```\n\n"
                  "Omit `--target-db-instance-identifier` to let Aurora choose the best-positioned "
                  "reader automatically; specify it explicitly when the drill is deliberately "
                  "validating a specific reader (for example, the newest or largest instance class in "
                  "the fleet).\n\n"
                  "## What happens during the cutover\n\n"
                  "The targeted reader is promoted to writer and the cluster endpoint's DNS re-points "
                  "to it -- because the new writer already shares the same underlying storage volume, "
                  "no data copy is needed, and the client-visible interruption is typically on the "
                  "order of tens of seconds, not minutes. Every existing connection (to the old writer "
                  "and to every reader, since the reader endpoint's membership also changes) is reset; "
                  "applications must reconnect and DNS caches must expire and re-resolve, which is why "
                  "connection pool/retry configuration matters as much as the Aurora-side mechanism "
                  "itself.\n\n"
                  "## Immediately after\n\n"
                  "Run `04_post_failover_verification.sql` against the cluster/writer endpoint to "
                  "confirm the new writer's identity and recent start time, then follow "
                  "`database-health/post-maintenance-check` for the fuller post-event health check.\n\n"
                  "## Recording the drill\n\n"
                  "Track, per drill: time-to-first-successful-reconnect for each application, whether "
                  "any manual intervention was needed, and any configuration gap discovered -- compare "
                  "this against previous drills' results as a standing HA-readiness trend line.\n"
              ),
              "Follow the sequence in order -- the value of this drill is entirely in observing real application behavior during the cutover, so do not skip the 'before triggering' stakeholder/observability steps to save time.",
              safety="ELEVATED RISK (deliberately disrupts every existing connection to the cluster for the duration of the cutover -- an AWS control-plane action, not a SQL statement)",
              expected_impact="A brief (typically tens of seconds) period where the cluster/reader endpoints are unavailable or reset for existing connections while the promoted reader becomes the new writer and DNS re-points.",
              required_privileges="AWS IAM permission for rds:FailoverDBCluster (or console equivalent); no PostgreSQL role is used to trigger the failover itself.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Typically under a minute for the cutover itself; allow additional time afterward for full application-side recovery observation.",
              related_scripts="01_confirm_writer_reader_topology.sql, 02_reader_health_and_lag_precheck.sql, 04_post_failover_verification.sql"),
    sql_script("04", "04_post_failover_verification", "Confirms the new writer's identity and how recently it started, run against the cluster/writer endpoint immediately after the drill to verify the promotion completed as expected.",
               """
-- Run against the cluster (writer) endpoint immediately after the drill.
-- A very recent instance_start_time here, combined with pg_is_in_recovery()
-- = false, confirms this connection is now reaching the newly promoted
-- writer.
SELECT
    pg_is_in_recovery()                                          AS is_reader_instance,
    pg_postmaster_start_time()                                   AS instance_start_time,
    now() - pg_postmaster_start_time()                           AS instance_uptime;
""".strip("\n"),
               "is_reader_instance should read false (this is now the writer) and instance_start_time should be very recent, consistent with the drill's promotion having just completed. Follow up with database-health/post-maintenance-check for the fuller post-event verification, and performance/performance-after-failover if buffer-cache warm-up impact is observed.",
               execution_location=ANY_INSTANCE,
               related_scripts="../../database-health/post-maintenance-check/README.md"),
]

# ---------------------------------------------------------------------------
# backup-and-restore-validation
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="backup-and-restore-validation",
    title="Backup and Restore Validation",
    summary="Verifies that Aurora's automated backups/snapshots actually exist within the expected retention window, and periodically proves they are restorable by test-restoring into a scratch cluster -- since an untested backup is only a assumption, not a verified recovery capability.",
    symptoms=["No active symptom -- a scheduled validation practice, typically run monthly or quarterly and ahead of any compliance review that requires evidence of tested backup/restore capability.", "Run reactively after any change to backup retention configuration to confirm the new setting took effect as intended."],
    business_impact=["For a financial trading platform, 'we have automated backups' is not the same claim as 'we have confirmed we can actually restore from them' -- a backup that has never been test-restored can fail silently (a corrupted snapshot, an unexpectedly short retention window, a permissions issue on the target account) and that failure is only ever discovered during a real disaster, which is the worst possible time."],
    root_causes=["Backup retention period was reduced (intentionally or accidentally) below what the organization's recovery point objective actually requires.", "A backup/snapshot exists but has never been test-restored, so an unknown issue (permissions, corruption, cross-account/cross-region copy configuration) would only surface during an actual disaster.", "Continuous backup (which Aurora uses for PITR) is a distinct mechanism from manual/automated snapshots -- confirming one does not confirm the other."],
    investigation_strategy=["Confirm current backup retention configuration and snapshot existence via the AWS control plane (not SQL -- this information lives entirely outside PostgreSQL).", "Capture a SQL-side reference snapshot (current WAL position and database-level statistics) immediately before a scheduled test-restore, to have a concrete before/after comparison point.", "Perform the test-restore into a scratch cluster and validate the restored data against the reference snapshot."],
    prerequisites=["AWS IAM permission to describe cluster snapshots/backup configuration and to restore into a new (scratch) cluster; a scratch-cluster budget/approval for periodic test restores, since this creates real (temporary) infrastructure."],
    interpretation_guide=["Automated backups and manual snapshots being present and within retention is necessary but not sufficient evidence of recoverability -- treat a clean test-restore, performed at least once per validation cycle, as the actual proof; existence of a snapshot alone is only evidence that the mechanism ran, not that the data is usable.", "The SQL-side reference snapshot (script 01) is a sanity/comparison aid, not the recovery point itself -- the actual recovery point for Aurora backups is managed and tracked entirely by the AWS control plane (backup window, retention period), which this workflow's runbook checks separately."],
    remediation_immediate=["N/A -- this is a proactive validation workflow, not an incident response; if validation reveals backups are NOT actually restorable, treat that finding itself as an urgent gap to close, even though nothing is actively broken yet."],
    remediation_short_term=["If backup retention is shorter than the organization's recovery point objective requires, increase it via the cluster's backup configuration.", "If a test-restore fails or reveals unexpected data loss/corruption, open an AWS Support case immediately -- this is exactly the failure mode this workflow exists to catch before a real disaster."],
    remediation_long_term=["Establish a standing test-restore cadence (e.g. quarterly) with the scratch cluster's cost budgeted for in advance, and track each cycle's result (success/failure, time taken) as a compliance/audit artifact."],
    production_safety=["The SQL scripts here are read-only. The test-restore itself creates a new, separate scratch cluster -- it does not modify or risk the production cluster in any way, and the scratch cluster should be decommissioned after validation to avoid ongoing cost."],
    escalation_criteria=["A scheduled test-restore fails, or the restored data does not match the pre-restore reference snapshot -- escalate to AWS Support and to the platform/compliance team immediately, since this means the organization's actual recovery capability does not match its assumed one."],
    related_issues=["../cluster-failover-drill/README.md", "../point-in-time-recovery-drill/README.md", "../../maintenance/routine-maintenance-checklist/README.md"],
    aurora_notes=["Aurora automatically and continuously backs up cluster storage to S3 in a way that supports point-in-time restore across the configured backup retention window (1-35 days), independent of any manual snapshot -- automated backups and manual DB cluster snapshots are complementary, not interchangeable: retention-window PITR capability should not be assumed to also mean a specific manual snapshot exists, and vice versa."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_restore_point_reference_snapshot", "Captures a SQL-side reference point (current WAL position and database-level statistics) immediately before a scheduled test-restore, for concrete before/after comparison.",
               """
-- A lightweight, point-in-time reference snapshot to compare against after
-- a test-restore completes. This is a sanity/comparison aid only -- the
-- authoritative recovery-point mechanism for Aurora backups (the backup
-- window and retention period) is tracked entirely by the AWS control
-- plane, not by anything queryable here.
SELECT
    current_database()                                          AS database_name,
    pg_current_wal_lsn()                                        AS current_wal_lsn,
    clock_timestamp()                                           AS reference_timestamp,
    d.xact_commit,
    d.xact_rollback,
    d.stats_reset
FROM pg_stat_database d
WHERE d.datname = current_database();
""".strip("\n"),
               "Save this output alongside the test-restore's own start time. After the restore completes into the scratch cluster, re-run this same query there and compare xact_commit/reference_timestamp to confirm the restored data reflects activity from at or before your intended recovery point, not unexpectedly older or newer data.",
               related_scripts="02_backup_and_restore_test_runbook.md"),
    md_script("02", "02_backup_and_restore_test_runbook", "Guarded runbook for confirming backup/snapshot configuration via the AWS control plane and performing a periodic test-restore into a scratch cluster.",
              (
                  "## Confirm backup configuration exists and meets your retention requirement\n\n"
                  "```\n"
                  "aws rds describe-db-clusters \\\n"
                  "  --db-cluster-identifier <cluster-identifier> \\\n"
                  "  --query 'DBClusters[0].[BackupRetentionPeriod,PreferredBackupWindow,EarliestRestorableTime,LatestRestorableTime]'\n"
                  "```\n\n"
                  "Confirm `BackupRetentionPeriod` (in days) meets your organization's recovery point "
                  "objective, and that `EarliestRestorableTime`/`LatestRestorableTime` span the window "
                  "you expect.\n\n"
                  "## Confirm manual/automated snapshots exist\n\n"
                  "```\n"
                  "aws rds describe-db-cluster-snapshots \\\n"
                  "  --db-cluster-identifier <cluster-identifier> \\\n"
                  "  --query 'DBClusterSnapshots[].[DBClusterSnapshotIdentifier,SnapshotType,Status,SnapshotCreateTime]'\n"
                  "```\n\n"
                  "## Test-restoring into a scratch cluster\n\n"
                  "Restore into a **new**, separate cluster -- this never touches the production "
                  "cluster:\n\n"
                  "```\n"
                  "aws rds restore-db-cluster-to-point-in-time \\\n"
                  "  --source-db-cluster-identifier <cluster-identifier> \\\n"
                  "  --db-cluster-identifier <scratch-cluster-identifier> \\\n"
                  "  --use-latest-restorable-time\n"
                  "```\n\n"
                  "(Substitute `--restore-to-time <timestamp>` for `--use-latest-restorable-time` to "
                  "validate an earlier point instead.) Then create at least one DB instance in the new "
                  "scratch cluster so it is actually queryable -- a cluster restore alone does not "
                  "provision a compute instance.\n\n"
                  "## Validating the restore\n\n"
                  "1. Connect to the scratch cluster's instance and re-run "
                  "`01_restore_point_reference_snapshot.sql` there; compare against the reference "
                  "captured on the source cluster.\n"
                  "2. Spot-check a handful of known recent rows/tables for presence and correctness.\n"
                  "3. Record the total restore time (snapshot/PITR restore plus instance provisioning) "
                  "as part of your recovery-time-objective evidence.\n\n"
                  "## Cleaning up\n\n"
                  "Decommission the scratch cluster and its instance(s) after validation completes, to "
                  "avoid ongoing cost -- this is a test-restore, not a standing environment.\n\n"
                  "## Do NOT\n\n"
                  "- Do NOT point any application at the scratch cluster -- it exists solely for "
                  "validation and must never become a de facto second production environment.\n"
                  "- Do NOT skip provisioning at least one instance in the restored cluster and call "
                  "the restore 'validated' -- a cluster-level restore with no instance to query proves "
                  "nothing about actual data recoverability.\n"
              ),
              "Work through configuration confirmation first, then the actual test-restore, then validation against the reference snapshot -- treat a restore with no subsequent data validation as an incomplete drill.",
              safety="LOW RISK WRITE (creates a new, separate scratch cluster; does not modify or risk the production cluster)",
              expected_impact="No impact to the production cluster; creates temporary AWS infrastructure cost for the scratch cluster until it is decommissioned.",
              required_privileges="AWS IAM permission to describe cluster/snapshot configuration and to restore/create a new DB cluster and instance; no elevated PostgreSQL privilege needed beyond CONNECT on the restored scratch cluster for validation.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Minutes to describe configuration; tens of minutes for the restore and instance provisioning, depending on data volume.",
              related_scripts="01_restore_point_reference_snapshot.sql"),
]

# ---------------------------------------------------------------------------
# point-in-time-recovery-drill
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="point-in-time-recovery-drill",
    title="Point-in-Time Recovery (PITR) Drill",
    summary="Plans and practices restoring the cluster to a specific point in time within Aurora's continuous backup retention window -- always into a new cluster, never in-place -- for the scenario where a specific past moment (just before a bad deployment or an erroneous bulk write) needs to be recovered to, rather than only the latest restorable time.",
    symptoms=["A bad deployment or an erroneous bulk UPDATE/DELETE corrupted data starting at a known point in time, and the fix requires recovering data as it existed just before that point.", "No active symptom -- run as a periodic drill (often alongside backup-and-restore-validation) to confirm the team can execute a PITR restore under time pressure before ever needing to."],
    business_impact=["A real incident requiring PITR is, by definition, already a data-integrity emergency -- practicing the exact restore-to-time mechanics (identifying the right target time, running the restore, validating the result) in a drill removes the risk of fumbling the mechanism itself while under the added pressure of a live incident."],
    root_causes=["N/A for the drill itself; the scenario it prepares for is typically an application-level bug (a bad deployment or an erroneous bulk write) rather than a database-level fault."],
    investigation_strategy=["Identify the target restore-to time based on when the incident actually started (from application logs, deployment timestamps, or the first bad row's own timestamp column -- not solely from database-side signals, since the database itself usually has no record of *why* a write was wrong, only that it happened).", "Restore to a point slightly before the identified incident start, into a new cluster, never in-place.", "Validate the restored data represents the pre-incident state before using it for any recovery action (e.g. re-inserting lost-but-good rows into production)."],
    prerequisites=["AWS IAM permission to restore a new cluster from point-in-time; a reasonably precise incident-start timestamp (from application logs/deployment records) to restore against."],
    interpretation_guide=["Aurora's PITR restore always creates a brand-new cluster as of the requested time -- it is never an in-place rollback of the existing cluster, which means the existing (post-incident) cluster keeps running throughout, and the restored cluster is a separate point of reference to compare against and selectively recover from, not a direct replacement.", "Restoring to a time slightly earlier than your best estimate of the incident start is safer than restoring to the exact estimated moment -- if the estimate is a little late, you still have the bad data in the restored copy; if it is well early, you can identify the correct cutover using the data itself once you have the restored cluster to inspect."],
    remediation_immediate=["Restore into a new cluster at the identified target time, then use the restored cluster's data to identify and manually reconcile what needs to be corrected in production -- never restore in-place and never treat the restored cluster as an automatic drop-in replacement for the live cluster."],
    remediation_short_term=["Once the specific bad rows/tables are identified by comparing the restored cluster against production, perform a targeted, reviewed data-correction (not a blanket restore-and-replace) against production."],
    remediation_long_term=["Feed the incident's actual timeline (how precisely the start time was identified, how long the restore took) back into this drill's practiced procedure, and add any missing tooling/logging that made identifying the target time harder than it should have been."],
    production_safety=["The SQL companion script here is read-only and only assists in reasoning about a target time; it does not perform any restore itself. The restore itself creates a new, separate cluster and does not modify the existing cluster."],
    escalation_criteria=["The incident-start time cannot be identified with reasonable confidence from available logs/timestamps -- escalate to restore multiple candidate points in parallel (as separate scratch clusters) rather than guessing a single target time for a data-integrity-critical restore."],
    related_issues=["../backup-and-restore-validation/README.md", "../cluster-failover-drill/README.md"],
    aurora_notes=["Aurora's continuous backup mechanism supports restoring to any second within the configured backup retention window (1-35 days) via restore-db-cluster-to-point-in-time, distinct from restoring from a specific named manual snapshot -- both restore into a new cluster, never in-place, which is a deliberate safety property of the mechanism, not a limitation to work around."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_target_restore_time_reference", "Given an operator-supplied suspected incident-start timestamp, computes a suggested restore-to target slightly earlier, alongside the current server time and WAL position for reference.",
               """
-- Ships with an illustrative default incident_start_time -- override it with
-- the actual suspected incident-start timestamp (from application logs or
-- deployment records) via `-v incident_start_time='...'` or `\\set` before
-- running. The suggested target is intentionally a few minutes earlier than
-- the supplied time: it is safer to restore a little too early (the bad
-- data is still present in the restored copy, easy to identify and ignore)
-- than a little too late (the restore already contains the problem you are
-- trying to recover from).
\\set incident_start_time '2025-01-01 00:00:00+00'
SELECT
    :'incident_start_time'::timestamptz                          AS operator_supplied_incident_start,
    (:'incident_start_time'::timestamptz - interval '5 minutes')  AS suggested_restore_target_time,
    now()                                                         AS current_server_time,
    pg_current_wal_lsn()                                          AS current_wal_lsn_for_reference,
    extract(epoch FROM :'incident_start_time'::timestamptz)        AS incident_start_epoch_seconds;
""".strip("\n"),
               "suggested_restore_target_time is what you pass to --restore-to-time in the runbook's AWS CLI command; current_wal_lsn_for_reference and current_server_time are only a sanity-check anchor for how far 'now' is from the target, not a claim about what LSN existed at the target time itself, since Aurora's PITR mechanism resolves the target time internally rather than from this query.",
               related_scripts="02_point_in_time_recovery_runbook.md"),
    md_script("02", "02_point_in_time_recovery_runbook", "Guarded runbook for restoring the cluster to a specific point in time into a new cluster, using the target time identified by script 01.",
              (
                  "## Confirm the target time is within the retention window\n\n"
                  "```\n"
                  "aws rds describe-db-clusters \\\n"
                  "  --db-cluster-identifier <cluster-identifier> \\\n"
                  "  --query 'DBClusters[0].[EarliestRestorableTime,LatestRestorableTime]'\n"
                  "```\n\n"
                  "The `suggested_restore_target_time` from script 01 must fall between these two "
                  "timestamps -- if it does not, the required recovery point has already aged out of "
                  "the configured backup retention period and cannot be restored via PITR.\n\n"
                  "## Restoring to the target time\n\n"
                  "This always creates a **new** cluster; it never modifies the existing one in "
                  "place:\n\n"
                  "```\n"
                  "aws rds restore-db-cluster-to-point-in-time \\\n"
                  "  --source-db-cluster-identifier <cluster-identifier> \\\n"
                  "  --db-cluster-identifier <recovery-cluster-identifier> \\\n"
                  "  --restore-to-time <suggested_restore_target_time-from-script-01> \\\n"
                  "  --restore-type full-copy\n"
                  "```\n\n"
                  "Then provision at least one DB instance in the new cluster -- the cluster-level "
                  "restore alone is not queryable until an instance exists in it.\n\n"
                  "## Validating and recovering the data\n\n"
                  "1. Connect to the recovery cluster's instance and confirm the restored data reflects "
                  "the pre-incident state (spot-check the specific rows/tables known to be affected).\n"
                  "2. Identify exactly what needs to be corrected in production by comparing the "
                  "recovery cluster against production -- do not treat the recovery cluster as an "
                  "automatic drop-in replacement.\n"
                  "3. Perform a targeted, reviewed correction against production (e.g. re-inserting "
                  "specific rows, or exporting a table's pre-incident state for reconciliation), with a "
                  "second engineer reviewing the exact statements before they run against production.\n\n"
                  "## After the drill/incident\n\n"
                  "Decommission the recovery cluster once the correction is complete and confirmed, to "
                  "avoid ongoing cost, and record the actual end-to-end time taken (time to identify the "
                  "target time, restore duration, validation, and correction) for the next drill cycle.\n\n"
                  "## Do NOT\n\n"
                  "- Do NOT restore in-place or attempt to point the production application at the "
                  "recovery cluster -- it exists solely to recover specific data, not to replace the "
                  "running cluster.\n"
                  "- Do NOT skip the retention-window confirmation step -- requesting a restore-to-time "
                  "outside `EarliestRestorableTime`/`LatestRestorableTime` will simply fail, and it is "
                  "faster to confirm the window first than to discover the failure mid-incident.\n"
              ),
              "Confirm the retention window before restoring, and treat the recovery cluster strictly as a reference/source for reconciliation, never as a replacement for the live cluster.",
              safety="LOW RISK WRITE (creates a new, separate cluster; does not modify the existing cluster in place)",
              expected_impact="No impact to the existing production cluster; creates temporary AWS infrastructure cost for the recovery cluster until it is decommissioned.",
              required_privileges="AWS IAM permission to restore/create a new DB cluster and instance from a point in time; no elevated PostgreSQL privilege needed beyond CONNECT on the recovery cluster for validation.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Tens of minutes for the restore and instance provisioning, depending on data volume; validation and correction time varies with incident scope.",
              related_scripts="01_target_restore_time_reference.sql"),
]

# ---------------------------------------------------------------------------
# cross-region-and-full-cluster-loss
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="cross-region-and-full-cluster-loss",
    title="Cross-Region Failover and Full Cluster Loss Recovery",
    summary="Covers the worst-case disaster scenarios beyond a single-cluster failover: a regional-scale event handled via Aurora Global Database's cross-region failover, or the total, unrecoverable loss of the primary cluster requiring restore from a cross-region-copied snapshot into an entirely new region -- fundamentally an AWS infrastructure recovery process, not a SQL-level investigation.",
    symptoms=["An entire AWS region hosting the primary cluster becomes unavailable (a regional service event, not just an instance/AZ issue).", "The primary cluster (and its automated backups/PITR window) is confirmed lost or inaccessible in its home region, requiring recovery from a separately-stored, cross-region copy."],
    business_impact=["This is the tail-risk scenario every other disaster-recovery workflow in this category exists to make unnecessary in the common case -- for a trading platform, a true regional loss without a tested cross-region recovery path is an existential business continuity risk, not merely an extended outage."],
    root_causes=["An AWS regional service disruption affecting the home region's control plane and/or data plane for an extended period.", "An account-level or cluster-level event (misconfiguration, deletion, corruption) severe enough that in-region recovery options (failover, same-region PITR/snapshot restore) are not viable and only a cross-region copy remains."],
    investigation_strategy=["If an Aurora Global Database is in place: confirm the secondary region's cluster is healthy and initiate a managed or unplanned regional failover via the AWS control plane.", "If no Global Database is in place (or it is also affected) and only cross-region-copied snapshots exist: identify the most recent valid cross-region snapshot copy and restore it into a new cluster in a healthy region.", "In either path, validate data currency and completeness in the recovered cluster before directing production traffic to it, and understand the accepted data-loss window (RPO) for the specific path taken."],
    prerequisites=["An Aurora Global Database already configured with a secondary region (for the managed-failover path), or a standing cross-region snapshot-copy schedule already in place (for the snapshot-restore path) -- this workflow assumes one of these was set up in advance; neither can be created for the first time during the event itself."],
    interpretation_guide=["Aurora Global Database replication to the secondary region is asynchronous and typically sub-second, but it is NOT synchronous -- an unplanned regional failover of the primary can lose the last fraction of a second to low-single-digit seconds of committed writes that had not yet replicated; this is an accepted, documented RPO characteristic of the mechanism, not a malfunction, and must be understood by the business ahead of time, not discovered during the event.", "A cross-region snapshot-copy-based restore's RPO is bounded by how recently the last snapshot was copied to the target region, which is typically far coarser (hours, depending on the copy schedule) than Global Database's near-real-time replication -- confirm which of the two mechanisms is actually in place for this cluster before assuming a sub-second RPO is available."],
    remediation_immediate=["For a Global Database setup: initiate failover of the secondary region to become the new primary via the AWS control plane, then redirect application traffic to the new regional endpoint once promoted.", "For a snapshot-copy-only setup: restore the most recent valid cross-region snapshot copy into a new cluster in a healthy region, provision instances, validate data currency, then redirect application traffic."],
    remediation_short_term=["Once traffic is restored in the new region, assess and communicate the accepted data loss window (if any) to stakeholders, and begin reconciling any transactions known to have been in flight at the time of the event."],
    remediation_long_term=["If this event occurred without a Global Database in place, evaluate establishing one going forward given its materially better RPO/RTO characteristics versus snapshot-copy-only recovery.", "Incorporate a cross-region recovery exercise (at whatever cadence is operationally feasible, given its cost and complexity) alongside the more frequent in-region cluster-failover-drill and backup-and-restore-validation drills, so this path is not entirely untested until an actual regional event."],
    production_safety=["This is fundamentally an AWS infrastructure recovery process, not a SQL-level operation -- there is no PostgreSQL-side script that performs or substitutes for either recovery path; the guidance here is entirely a change-managed, AWS-control-plane runbook."],
    escalation_criteria=["Any true regional-loss event triggers this workflow -- by definition, escalate to the highest level of incident command your organization has immediately; this is not a DBA-only response."],
    related_issues=["../cluster-failover-drill/README.md", "../backup-and-restore-validation/README.md", "../point-in-time-recovery-drill/README.md"],
    aurora_notes=["Aurora Global Database is a distinct, separately-provisioned feature (a primary cluster in one region plus one or more secondary, read-only clusters in other regions, linked by Aurora's own low-latency storage-based replication) from the single-region Multi-AZ cluster this repository otherwise assumes -- confirm which topology is actually in place for this cluster well before an event, since the two require entirely different recovery procedures."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_pre_incident_baseline_reference", "Captures a lightweight baseline (engine version, current database, and connection role) intended to be kept on file for comparison after a cross-region recovery, run periodically as part of standing DR preparedness rather than during the event itself.",
               sb.cluster_recovery_role() + "\n\n" + """
-- Engine-version and database-inventory baseline, kept alongside the
-- cluster_recovery_role() output above as a pre-incident reference point --
-- useful for confirming a cross-region-recovered cluster (which may have
-- been restored from an older snapshot copy) matches the expected engine
-- version and database set before cutting application traffic over to it.
SELECT
    current_setting('server_version')                            AS server_version,
    current_setting('server_version_num')                        AS server_version_num,
    (SELECT array_agg(datname ORDER BY datname)
       FROM pg_database
      WHERE datistemplate = false)                                AS user_databases;
""".strip("\n"),
               "Keep this output on file (alongside your DR runbook, not only in the database itself, since the whole point is to have it available even if the source cluster/region is unavailable). After a cross-region recovery, re-run this same query against the recovered cluster and confirm the engine version and database inventory match what you expect before directing production traffic to it.",
               related_scripts="02_cross_region_and_full_loss_runbook.md"),
    md_script("02", "02_cross_region_and_full_loss_runbook", "Guarded runbook covering both recovery paths for a true regional-scale event: Aurora Global Database managed failover, and cross-region snapshot-copy restore when no Global Database is in place.",
              (
                  "## First, determine which recovery path applies\n\n"
                  "Confirm in advance (this cannot be determined mid-event from inside a lost/"
                  "unreachable region) whether this cluster is part of an Aurora Global Database "
                  "(managed cross-region replication already in place) or relies solely on "
                  "cross-region-copied snapshots. The two paths below are not interchangeable.\n\n"
                  "## Path A -- Aurora Global Database failover\n\n"
                  "```\n"
                  "aws rds failover-global-cluster \\\n"
                  "  --global-cluster-identifier <global-cluster-identifier> \\\n"
                  "  --target-db-cluster-identifier <secondary-region-cluster-arn>\n"
                  "```\n\n"
                  "This promotes the named secondary-region cluster to become the new primary of the "
                  "global cluster. Because Global Database replication is asynchronous, the most "
                  "recent sub-second-to-low-single-digit-seconds of committed writes on the original "
                  "primary may not have replicated and will not be present after failover -- this is "
                  "an accepted characteristic of the mechanism (see this workflow's Aurora Notes), not "
                  "a failure of the failover itself.\n\n"
                  "## Path B -- restore from a cross-region snapshot copy\n\n"
                  "If no Global Database exists (or it is also affected), identify the most recent "
                  "valid snapshot copy already present in a healthy target region:\n\n"
                  "```\n"
                  "aws rds describe-db-cluster-snapshots \\\n"
                  "  --region <target-region> \\\n"
                  "  --snapshot-type manual \\\n"
                  "  --query 'DBClusterSnapshots[].[DBClusterSnapshotIdentifier,SnapshotCreateTime,Status]'\n"
                  "```\n\n"
                  "Then restore it into a new cluster in that region:\n\n"
                  "```\n"
                  "aws rds restore-db-cluster-from-snapshot \\\n"
                  "  --region <target-region> \\\n"
                  "  --db-cluster-identifier <recovery-cluster-identifier> \\\n"
                  "  --snapshot-identifier <most-recent-valid-snapshot-identifier> \\\n"
                  "  --engine aurora-postgresql\n"
                  "```\n\n"
                  "Then provision at least one DB instance in the new cluster. This path's RPO is "
                  "bounded by the snapshot-copy schedule's frequency, typically far coarser than "
                  "Global Database's near-real-time replication -- communicate the actual data-loss "
                  "window implied by the restored snapshot's timestamp to stakeholders explicitly.\n\n"
                  "## After either path\n\n"
                  "1. Re-run `01_pre_incident_baseline_reference.sql` against the new primary/recovered "
                  "cluster and compare against the reference captured beforehand.\n"
                  "2. Update application configuration/DNS to point at the new region's endpoint.\n"
                  "3. Communicate the accepted data-loss window to stakeholders and begin reconciling "
                  "any transactions known to have been in flight at the time of the event.\n"
                  "4. Once stable, evaluate re-establishing cross-region replication/backup-copy "
                  "coverage from the new primary region, since the original topology's protection is "
                  "gone until it is rebuilt.\n\n"
                  "## Do NOT\n\n"
                  "- Do NOT assume Path A (Global Database failover) is available without having "
                  "confirmed in advance that this specific cluster is part of a Global Database -- "
                  "attempting it against a cluster that is not will simply fail and cost time you do "
                  "not have during a true regional event.\n"
                  "- Do NOT skip communicating the RPO/data-loss window to stakeholders once the "
                  "recovery path is chosen -- the business, not the DBA alone, must decide how to "
                  "handle the transactions that fall within that window.\n"
              ),
              "Escalate to full incident command immediately for any true regional event -- this runbook exists to make the mechanical recovery steps fast and correct once that escalation has happened, not to substitute for it.",
              safety="ELEVATED RISK (regional-scale recovery action -- either promotes a secondary region as the new production primary, or restores a new cluster from a potentially-hours-old cross-region snapshot copy)",
              expected_impact="A managed Global Database failover accepts a small (sub-second to low-single-digit-second) data-loss window; a snapshot-copy restore accepts a data-loss window bounded by the copy schedule's frequency, typically much larger.",
              required_privileges="AWS IAM permission for rds:FailoverGlobalCluster (Path A) or rds:RestoreDBClusterFromSnapshot in the target region (Path B); no PostgreSQL role is used to trigger either recovery path.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Minutes for a Global Database failover; tens of minutes to hours for a cross-region snapshot restore plus instance provisioning, depending on data volume and cross-region transfer.",
              related_scripts="01_pre_incident_baseline_reference.sql"),
]

