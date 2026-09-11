"""Workflow definitions: disaster-recovery/ category (6 workflow directories).

This is an OPEN_CATALOG category (see tools/validation/catalog.py) -- there
is no fixed, exact required workflow slug list, only a requirement that the
category directory exists and has at least one workflow. One slug is
mandatory regardless: `cluster-failover-drill`, since several already-built
workflows in other categories link directly to it. The six workflows below
cover a planned failover drill, backup/restore validation, point-in-time
recovery planning, the worst-case cross-region/full-cluster-loss scenario,
measured RTO/RPO validation, and snapshot restore testing -- together
spanning Aurora's disaster-recovery surface from a routine drill to a true
regional-loss event, and turning the DR policy's stated objectives into
measured, evidenced numbers.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import ANY_INSTANCE, WRITER_ONLY, md_script, sql_script
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
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): pg_current_wal_lsn()
-- errors on Aurora clusters running with wal_level=replica (Aurora's
-- default) -- this function family depends on the same logical-WAL-cache
-- infrastructure used by logical replication, and is only reliably
-- callable once wal_level=logical is set. current_setting('wal_level') is
-- a plain GUC read that never fails, so it guards the call here: a CASE
-- expression only evaluates its matching branch (the same documented
-- mechanism used to avoid division-by-zero in a CASE), so
-- pg_current_wal_lsn() is never actually invoked unless wal_level is
-- already 'logical'.
SELECT
    current_database()                                          AS database_name,
    CASE WHEN current_setting('wal_level') = 'logical'
         THEN pg_current_wal_lsn()::text
         ELSE 'NOT AVAILABLE (wal_level=' || current_setting('wal_level') ||
              ', requires logical on Aurora)'
    END                                                          AS current_wal_lsn,
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
    sql_script("01", "01_target_restore_time_reference", "Given an operator-supplied suspected incident-start timestamp, computes a suggested restore-to target slightly earlier, alongside a safe engine-specific recovery reference.",
               """
-- Ships with an illustrative default incident_start_time -- override it with
-- the actual suspected incident-start timestamp (from application logs or
-- deployment records) via `-v incident_start_time='...'` or `\\set` before
-- running. The suggested target is intentionally a few minutes earlier than
-- the supplied time: it is safer to restore a little too early (the bad
-- data is still present in the restored copy, easy to identify and ignore)
-- than a little too late (the restore already contains the problem you are
-- trying to recover from).
--
-- IMPORTANT (verified against Aurora PostgreSQL 17.7): Aurora rejects the
-- PostgreSQL WAL/LSN functions even in a CASE branch that would not return
-- their value. Detect Aurora in psql first so no statement containing an LSN
-- function is sent to the Aurora server at all.
\\set incident_start_time '2025-01-01 00:00:00+00'
SELECT (
    current_setting('aurora_version', true) IS NOT NULL
    OR current_setting('rds.extensions', true) IS NOT NULL
    OR EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version')
)                                                                AS is_aurora
\\gset

\\if :is_aurora
SELECT
    :'incident_start_time'::timestamptz                          AS operator_supplied_incident_start,
    (:'incident_start_time'::timestamptz - interval '5 minutes')  AS suggested_restore_target_time,
    now()                                                         AS current_server_time,
    current_user                                                  AS connected_role,
    current_setting('wal_level')                                  AS wal_level,
    extract(epoch FROM :'incident_start_time'::timestamptz)        AS incident_start_epoch_seconds,
    'Aurora PostgreSQL does not expose a safe SQL WAL/LSN reference here. '
    'Use the AWS RDS LatestRestorableTime and EarliestRestorableTime values '
    'as the authoritative PITR boundaries.'                       AS guidance;
\\else
SELECT pg_is_in_recovery()                                       AS is_reader_instance
\\gset

\\if :is_reader_instance
SELECT
    :'incident_start_time'::timestamptz                          AS operator_supplied_incident_start,
    (:'incident_start_time'::timestamptz - interval '5 minutes')  AS suggested_restore_target_time,
    now()                                                         AS current_server_time,
    pg_last_wal_replay_lsn()                                      AS current_wal_lsn_for_reference,
    extract(epoch FROM :'incident_start_time'::timestamptz)        AS incident_start_epoch_seconds;
\\else
SELECT
    :'incident_start_time'::timestamptz                          AS operator_supplied_incident_start,
    (:'incident_start_time'::timestamptz - interval '5 minutes')  AS suggested_restore_target_time,
    now()                                                         AS current_server_time,
    pg_current_wal_lsn()                                          AS current_wal_lsn_for_reference,
    extract(epoch FROM :'incident_start_time'::timestamptz)        AS incident_start_epoch_seconds;
\\endif
\\endif
""".strip("\n"),
               "suggested_restore_target_time is what you pass to --restore-to-time in the runbook's AWS CLI command. On Aurora, use current_server_time only as a clock anchor and obtain the authoritative recovery window from the AWS RDS EarliestRestorableTime and LatestRestorableTime fields; Aurora does not safely expose the upstream WAL/LSN reference functions. On community PostgreSQL, the LSN column is an additional reference, not a claim about which LSN existed at the target timestamp.",
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


# ---------------------------------------------------------------------------
# rto-rpo-validation
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="rto-rpo-validation",
    title="RTO and RPO Validation",
    summary="Turns the recovery time objective and recovery point objective written in the platform's DR policy into measured, evidenced numbers rather than assumptions. It covers what the database itself can tell you about potential data loss (reader lag, logical replication slot lag, the restorable-time window), how to measure real recovery time during the drills in this category, and how to record the result against the business target so a gap is visible before an incident proves it.",
    symptoms=["The DR policy states an RTO and RPO but nobody can point to a measurement that demonstrates either is actually achievable on this cluster.", "A failover or restore drill was performed but its duration was never recorded, so the RTO figure in the policy is still an estimate.", "A logical replication consumer (a CDC pipeline feeding the data warehouse, risk engine, or compliance archive) is lagging, and nobody has quantified what that means for downstream recovery point."],
    business_impact=["For a crypto exchange, RPO is measured in trades and ledger entries, not abstract seconds: an unmeasured recovery point means an unknown number of order fills, deposits, and withdrawals could be unrecoverable, which is a customer-funds and regulatory reporting problem rather than only a technical one.", "An RTO that turns out to be several times the documented figure converts a controlled recovery into a prolonged trading outage, with market-maker and venue-reputation consequences that scale with the duration.", "Regulators and auditors of a regulated venue generally expect evidenced recovery capability, not a policy document alone -- measured drill results are that evidence."],
    root_causes=["N/A -- this is a validation and evidence workflow. Where a measurement misses its target, the cause belongs to the underlying mechanism (backup retention configuration, failover behavior, instance provisioning time, a lagging replication consumer) and is investigated in that mechanism's own workflow."],
    investigation_strategy=["Establish what the database can observe about potential data loss right now: reader lag, logical slot lag and retained WAL, and the current recovery reference point.", "Establish what the AWS control plane reports about the restorable window (earliest and latest restorable time), since that -- not anything queryable in SQL -- defines the actual PITR boundary.", "Measure real recovery time during the drills already in this category (cluster-failover-drill, backup-and-restore-validation, point-in-time-recovery-drill) rather than performing a separate artificial exercise.", "Compare each measurement against the documented business target and record the gap explicitly."],
    prerequisites=["pg_monitor role membership for the read-only scripts; IAM permission to describe DB clusters for the restorable-window figures; the organization's documented RTO/RPO targets to measure against; drills from this category scheduled so measurements come from real exercises."],
    interpretation_guide=["Aurora reader lag is typically milliseconds because readers share the same storage volume as the writer, so it is a poor proxy for RPO against a total cluster loss -- it describes read-after-write staleness for reader-endpoint traffic, which is an application-correctness concern, not a disaster recovery boundary.", "The figures that actually bound RPO are the backup retention window and the LatestRestorableTime reported by the AWS control plane (typically within minutes of now), plus, for cross-region scenarios, the Aurora Global Database replication lag or the age of the most recent cross-region snapshot copy -- which can be hours, and is usually the real RPO constraint for a regional event.", "Logical replication slot lag defines the recovery point for everything downstream of the database, not for the database itself: a lagging CDC consumer means the warehouse, risk, or compliance copy is behind, which matters for reconstructing state after an incident even when the database itself recovers cleanly.", "RTO is not the restore command's duration. It is wall-clock time from the decision to recover until the platform is serving customer traffic correctly, which includes provisioning instances, warming connection pools, validating data, and the human decision time that precedes all of it -- measure the whole chain or the number is not usable."],
    remediation_immediate=["N/A -- this is a measurement and evidence workflow. A measured gap against target is a finding to plan against, not an incident to remediate live."],
    remediation_short_term=["Record every drill's measured recovery time and observed recovery point in a single register alongside the business target, so the gap is a visible number rather than an impression.", "Where a logical slot is lagging materially, resolve it through replication-and-ha/replication-health before it becomes both a storage problem and a downstream recovery-point problem."],
    remediation_long_term=["Close a measured RTO gap with the mechanism that actually addresses it: pre-provisioned reader capacity and rehearsed failover for short RTOs, an Aurora Global Database for cross-region RTO/RPO, blue/green for upgrade-related interruption.", "Increase backup retention, or add more frequent cross-region snapshot copies, where the measured recovery point boundary is wider than the policy allows.", "Re-measure after any change to instance class, cluster topology, or data volume -- an RTO measured against a dataset a fraction of the current size is no longer evidence."],
    production_safety=["Every SQL script in this workflow is strictly read-only and safe to run against production at any time.", "This workflow triggers no recovery action of its own -- the measurements come from drills defined in the other workflows in this category, each with its own safety notes."],
    escalation_criteria=["A measured recovery time or recovery point misses the documented business target by a material margin -- escalate to the platform and compliance owners, since the organization is operating against a DR policy it cannot currently meet.", "The cross-region recovery point (Global Database lag or cross-region snapshot copy age) is materially worse than the policy assumes and no Global Database is configured -- escalate as an architectural gap rather than an operational one."],
    related_issues=["../cluster-failover-drill/README.md", "../backup-and-restore-validation/README.md", "../point-in-time-recovery-drill/README.md", "../snapshot-restore-testing/README.md", "../../replication-and-ha/replication-health/README.md"],
    aurora_notes=["Aurora separates the two objectives across different mechanisms, and they must be measured separately: in-region instance failure is handled by promoting an existing reader on the same shared storage volume (seconds of RTO, effectively no data loss), while a regional event depends either on an Aurora Global Database secondary (typically sub-second to low-second replication lag, promotion in minutes) or on cross-region snapshot copies (recovery point measured in hours). Quoting a single cluster-wide RTO/RPO pair without saying which failure scenario it describes is the most common way these numbers end up wrong."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_observable_recovery_point_signals", "Captures every recovery-point signal the database itself can report: instance role, Aurora reader lag, and replication slot lag with retained WAL.",
               sb.cluster_recovery_role() + "\n\n" + sb.aurora_replica_status() + "\n\n" + sb.replication_slots_and_wal_retention(),
               "Read each signal for what it actually bounds. Aurora reader lag bounds read-after-write staleness on the reader endpoint, not disaster-recovery data loss, because readers share the writer's storage volume -- do not quote it as an RPO figure. Replication slot lag bounds the recovery point of everything downstream (CDC into the warehouse, risk engine, compliance archive): a slot retaining a large amount of WAL means that downstream copy is materially behind the exchange's live state. The database has no visibility at all into the backup retention window or the latest restorable time -- those come from the AWS control plane in script 03, and they are the figures that actually bound PITR.",
               related_scripts="02_recovery_reference_point.sql"),
    sql_script("02", "02_recovery_reference_point", "Records a durable, engine-safe reference point (server time and commit counters, plus LSN only where supported) for comparing against a restored cluster after a drill.",
               """
-- A reference point to capture on a schedule and immediately before any
-- drill, so that "how much did we lose" can be answered by comparison
-- rather than estimation after a restore.
--
-- Aurora PostgreSQL 17.7 rejects both current and replay LSN functions.
-- Detect Aurora before psql sends any statement containing those function
-- names. The Aurora branch records a timestamp and database counters, then
-- directs the operator to the AWS control-plane recovery boundary.
SELECT (
    current_setting('aurora_version', true) IS NOT NULL
    OR current_setting('rds.extensions', true) IS NOT NULL
    OR EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version')
)                                                                AS is_aurora
\\gset

\\if :is_aurora
SELECT
    current_database()                                           AS database_name,
    current_user                                                  AS connected_role,
    pg_is_in_recovery()                                           AS is_reader_instance,
    current_setting('wal_level')                                  AS wal_level,
    clock_timestamp()                                             AS reference_timestamp,
    'Use RDS EarliestRestorableTime and LatestRestorableTime for the '
    'Aurora PITR recovery boundary, and CloudWatch AuroraReplicaLag for '
    'reader staleness. Aurora SQL WAL/LSN functions are unavailable.' AS guidance;
\\else
SELECT pg_is_in_recovery()                                       AS is_reader_instance
\\gset

\\if :is_reader_instance
SELECT
    current_database()                                           AS database_name,
    true                                                         AS is_reader_instance,
    pg_last_wal_replay_lsn()                                      AS last_replayed_lsn,
    pg_last_xact_replay_timestamp()                               AS last_replayed_commit_time,
    now() - pg_last_xact_replay_timestamp()                       AS replay_behind_by,
    clock_timestamp()                                             AS reference_timestamp;
\\else
SELECT
    current_database()                                           AS database_name,
    false                                                        AS is_reader_instance,
    pg_current_wal_lsn()                                          AS current_wal_lsn,
    clock_timestamp()                                            AS reference_timestamp;
\\endif
\\endif

-- Commit/rollback counters for the current database, valid on either
-- instance role. Captured alongside the reference point above, these give a
-- concrete before/after comparison against a restored cluster.
SELECT
    datname                                                      AS database_name,
    xact_commit,
    xact_rollback,
    stats_reset,
    now()                                                        AS captured_at
FROM pg_stat_database
WHERE datname = current_database();
""".strip("\n"),
               "On Aurora, compare reference_timestamp and the database commit counters against the restored cluster, then use the AWS control-plane EarliestRestorableTime and LatestRestorableTime values as the authoritative PITR boundary; the upstream WAL/LSN functions are unavailable. On community PostgreSQL, current_wal_lsn or replay_behind_by provides an additional engine reference. Capture this on a schedule (see automation/health-checks) as well as immediately before each drill, so a real incident has a recent anchor even when nobody had time to capture one.",
               related_scripts="03_rto_rpo_measurement_runbook.md"),
    md_script("03", "03_rto_rpo_measurement_runbook", "AWS-side guidance for the recovery-window figures the database cannot report, and the procedure for measuring real RTO during the drills in this category.",
              (
                  "This file documents AWS control-plane queries and a measurement procedure. Nothing "
                  "here is executed against the database, and none of it triggers a recovery action.\n\n"
                  "## 1. The figures that actually bound your recovery point\n\n"
                  "```\n"
                  "aws rds describe-db-clusters \\\n"
                  "  --db-cluster-identifier <cluster-identifier> \\\n"
                  "  --query 'DBClusters[0].[BackupRetentionPeriod,EarliestRestorableTime,LatestRestorableTime,PreferredBackupWindow]'\n"
                  "```\n\n"
                  "`LatestRestorableTime` is typically within a few minutes of now -- the gap between "
                  "it and the current time is the in-region recovery point for a PITR restore. "
                  "`EarliestRestorableTime` and `BackupRetentionPeriod` together define how far back "
                  "recovery is possible at all, which is the constraint that matters when an incident "
                  "is discovered days after it started (a slow-burn data corruption, for example).\n\n"
                  "## 2. Cross-region recovery point\n\n"
                  "If an Aurora Global Database secondary exists, its replication lag is the "
                  "cross-region recovery point, and it is usually sub-second to low-second:\n\n"
                  "```\n"
                  "aws rds describe-global-clusters \\\n"
                  "  --global-cluster-identifier <global-cluster-identifier>\n"
                  "```\n\n"
                  "The `AuroraGlobalDBReplicationLag` CloudWatch metric is the figure to record over "
                  "time rather than a single reading.\n\n"
                  "If there is no Global Database, the cross-region recovery point is the age of the "
                  "most recent cross-region snapshot copy, which is normally measured in hours:\n\n"
                  "```\n"
                  "aws rds describe-db-cluster-snapshots \\\n"
                  "  --region <dr-region> \\\n"
                  "  --query 'DBClusterSnapshots[].[DBClusterSnapshotIdentifier,SnapshotCreateTime,Status]'\n"
                  "```\n\n"
                  "State this clearly in the DR policy: for most clusters without a Global Database, "
                  "the regional-event recovery point is hours, not minutes, regardless of how good the "
                  "in-region figures look.\n\n"
                  "## 3. Measuring real recovery time\n\n"
                  "Measure RTO during the drills already scheduled in this category rather than as a "
                  "separate exercise. For each drill, record these timestamps:\n\n"
                  "| Marker | What it captures |\n"
                  "| --- | --- |\n"
                  "| T0 | The moment the recovery decision is made (not the moment the incident began) |\n"
                  "| T1 | The recovery action is initiated (failover triggered, restore submitted) |\n"
                  "| T2 | The database is accepting connections |\n"
                  "| T3 | Data validation has passed |\n"
                  "| T4 | The application is serving customer traffic correctly |\n\n"
                  "Measured RTO is T4 minus T0. Reporting T2 minus T1 as the RTO -- which is the "
                  "number the AWS console most readily shows -- understates real recovery time, often "
                  "by a wide margin, because it excludes decision time, instance provisioning, "
                  "validation, and connection pool warm-up.\n\n"
                  "For a restore-based recovery, instance provisioning after the cluster restore is "
                  "frequently the largest single component of T2 minus T1, and it scales with the "
                  "instance class you choose to restore onto -- so a drill performed on a small "
                  "scratch instance does not evidence the RTO of a production-sized recovery.\n\n"
                  "## 4. Measuring the observed recovery point\n\n"
                  "Run `02_recovery_reference_point.sql` on the source cluster before the drill and on "
                  "the recovered/restored cluster afterward. The difference between the two "
                  "`reference_timestamp` values, corroborated by the `xact_commit` delta, is the "
                  "observed recovery point for that specific recovery path -- an actual measurement "
                  "rather than the theoretical figure from step 1.\n\n"
                  "## 5. Scenario matrix\n\n"
                  "Record RTO and RPO separately per scenario, because a single pair of numbers for "
                  "the whole cluster is always wrong for at least one of them:\n\n"
                  "| Scenario | Mechanism | Typical RTO | Typical RPO |\n"
                  "| --- | --- | --- | --- |\n"
                  "| Writer instance failure | Automatic failover to a reader | Under a minute | Effectively none |\n"
                  "| Planned maintenance reboot | Rolling reboot or blue/green switchover | Minutes, or seconds for blue/green | None |\n"
                  "| Logical data corruption | PITR restore into a new cluster | Tens of minutes plus validation | Minutes, bounded by LatestRestorableTime |\n"
                  "| Full cluster loss in region | Snapshot or PITR restore | Tens of minutes to hours | Minutes to hours |\n"
                  "| Regional event, Global Database present | Managed planned or unplanned failover | Minutes | Sub-second to seconds |\n"
                  "| Regional event, no Global Database | Cross-region snapshot copy restore | Hours | Hours |\n\n"
                  "Replace every figure in this table with your own measured results as drills produce "
                  "them -- the table is a structure to fill in, and typical industry figures are not "
                  "evidence for this cluster.\n"
              ),
              "Measure RTO across the full chain from decision to customer-serving traffic, and measure RPO per scenario rather than once for the cluster -- a single unqualified pair of numbers is the most common way a DR policy ends up describing a capability the platform does not have.",
              safety="INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY",
              expected_impact="None. Every command shown is a read-only AWS describe call; no recovery action is triggered by this file.",
              required_privileges="IAM permission for rds:DescribeDBClusters, rds:DescribeGlobalClusters, and rds:DescribeDBClusterSnapshots; CloudWatch read access for the replication lag metric. No PostgreSQL role is used.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Minutes for the describe calls; the measurement procedure runs for the duration of whichever drill it is attached to.",
              related_scripts="01_observable_recovery_point_signals.sql, 02_recovery_reference_point.sql, 04_recovery_objectives_register.md"),
    md_script("04", "04_recovery_objectives_register", "The standing register: how to record each drill's measured results against the documented business targets so gaps stay visible between drills.",
              (
                  "## Why a register rather than a drill report\n\n"
                  "Individual drill reports get filed and forgotten. A single register, updated after "
                  "every drill, makes two things visible that no single report can: whether the "
                  "measured figures are drifting as the dataset grows, and which scenarios have never "
                  "actually been measured at all.\n\n"
                  "## What to record per entry\n\n"
                  "1. Scenario (use the scenario matrix in `03_rto_rpo_measurement_runbook.md`).\n"
                  "2. Documented business target for RTO and RPO for that scenario.\n"
                  "3. Measured RTO, broken down into the T0-T4 markers so the dominant component is "
                  "visible rather than hidden in a single total.\n"
                  "4. Measured recovery point, from the before/after comparison of "
                  "`02_recovery_reference_point.sql`.\n"
                  "5. Dataset size and instance class at the time of the drill -- without these the "
                  "measurement cannot be compared against a later one.\n"
                  "6. Gap against target, stated explicitly as a number, including when it is "
                  "comfortably within target.\n"
                  "7. Owner and due date for any remediation the gap implies.\n\n"
                  "## Cadence\n\n"
                  "- Failover scenario: measured at every `cluster-failover-drill`, quarterly at "
                  "minimum.\n"
                  "- Restore scenarios: measured at every `backup-and-restore-validation`, "
                  "`point-in-time-recovery-drill`, and `snapshot-restore-testing` exercise.\n"
                  "- Regional scenario: measured at whatever cadence the cross-region readiness "
                  "review runs, and at minimum annually, since it is the scenario most likely to be "
                  "assumed rather than tested.\n\n"
                  "## Re-measure when any of these change\n\n"
                  "- Data volume grows by an order of magnitude (restore time scales with it).\n"
                  "- Instance class or cluster topology changes.\n"
                  "- Backup retention or cross-region copy cadence changes.\n"
                  "- The application's connection handling or pool configuration changes, since that "
                  "affects the T2-to-T4 portion that drills most often ignore.\n\n"
                  "## A measurement is only evidence if it is reproducible\n\n"
                  "Record enough detail that a different engineer could repeat the drill and get a "
                  "comparable number: which endpoint was used, which instance class, what validation "
                  "was run, and who made the T0 decision. An RTO figure with no recorded method is an "
                  "assertion, and an assertion is exactly what this workflow exists to replace.\n"
              ),
              "Keep one register for the whole cluster and update it at every drill -- the value is in the trend and in the visibly-unmeasured scenarios, not in any single entry.",
              safety="DOCUMENTATION -- no SQL executed by this file itself",
              expected_impact="None from this file directly; the drills it records results from carry their own impact, documented in their own workflows.",
              required_privileges="N/A for this file itself.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Minutes per drill to record results.",
              related_scripts="03_rto_rpo_measurement_runbook.md, ../cluster-failover-drill/README.md, ../snapshot-restore-testing/README.md"),
]

# ---------------------------------------------------------------------------
# snapshot-restore-testing
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="snapshot-restore-testing",
    title="Snapshot Restore Testing",
    summary="Proves that a specific manual or automated DB cluster snapshot can actually be restored into a working, correct cluster -- the narrower, snapshot-specific counterpart to backup-and-restore-validation's broader backup-configuration review and to point-in-time-recovery-drill's continuous-backup path. It covers fingerprinting the source cluster's contents, restoring the snapshot into an isolated scratch cluster, validating the restored database against that fingerprint, and decommissioning the scratch environment afterward.",
    symptoms=["A manual snapshot is taken before every major release or migration, but no snapshot has ever actually been restored, so the rollback plan is untested.", "An encrypted snapshot or a cross-account/cross-region snapshot copy exists and nobody has confirmed the restoring account or region has the KMS key access needed to use it.", "A snapshot restore was attempted during a real incident and stalled on a missing parameter group, subnet group, or security group that nobody had prepared."],
    business_impact=["A snapshot that cannot be restored provides zero protection while creating the belief that protection exists -- for an exchange holding customer funds and ledger history, that belief is the risk, not the snapshot itself.", "Most snapshot restores are attempted for the first time under incident pressure, where a missing KMS grant or subnet group converts a bounded rollback into an extended outage.", "Testing the restore also produces the measured restore-duration evidence that the platform's RTO figure depends on (see rto-rpo-validation)."],
    root_causes=["N/A -- this is a validation workflow. Where a restore fails, the cause is typically an AWS configuration gap (KMS key policy, subnet group, parameter group, security group, instance class availability) rather than a database-level fault."],
    investigation_strategy=["Fingerprint the source cluster before the test: object inventory, per-table row estimates and sizes, extension inventory, and key settings -- so 'the restore looks fine' can be replaced by a concrete comparison.", "Restore the chosen snapshot into a new, isolated scratch cluster and provision at least one instance, since a cluster-level restore with no instance proves nothing.", "Run the same fingerprint on the restored cluster and compare, then spot-check business-critical tables for recent, known rows.", "Record the elapsed time for each phase, and decommission the scratch cluster immediately after validation."],
    prerequisites=["pg_monitor role membership on the source cluster, and CONNECT plus pg_monitor on the restored scratch cluster for validation.", "IAM permission to describe and restore DB cluster snapshots and to create DB instances; for an encrypted snapshot, access to the KMS key (and, for a cross-account copy, a key policy that grants the restoring account access).", "A non-production VPC/subnet group and security group prepared in advance for the scratch cluster, so the restore is not blocked on networking setup."],
    interpretation_guide=["Row-count estimates from the catalog (reltuples) are sufficient for comparison and far cheaper than exact counts on a large cluster -- they are maintained by vacuum and analyze, so compare them as approximate figures and only fall back to an exact count on a specific table where the estimate comparison looks wrong.", "A restored cluster is always a new cluster with its own endpoint, and it does not inherit the source's parameter group automatically unless you specify it -- an unexplained settings difference between source and restored fingerprints usually means the restore used a default parameter group, which will also make any performance comparison against the source meaningless.", "The restored cluster's statistics views (pg_stat_database, pg_stat_all_tables) start from the restore, not from the source's history, so xact_commit and scan counters will not match the source and are not a defect.", "A restore that completes but produces an instance stuck in a non-available state is usually a capacity or configuration problem in the target subnet/AZ, not a snapshot integrity problem -- read the event log before concluding the snapshot is bad.", "Restore duration scales with data volume and with the instance class chosen; a test restore onto a small instance class does not evidence the recovery time of a production-sized restore."],
    remediation_immediate=["N/A -- this is a planned validation exercise. If a restore fails during the test, that failure is the finding, and resolving it before an incident needs the snapshot is the work."],
    remediation_short_term=["Fix whatever blocked the restore (KMS key policy, subnet group, parameter group, security group, service quota) and re-run the test to confirm the fix, rather than recording the blocker and moving on.", "Decommission every scratch cluster and instance created during testing -- a forgotten scratch cluster is both an ongoing cost and, because it contains real customer and ledger data, a genuine security exposure."],
    remediation_long_term=["Make a snapshot restore test part of the standing DR cadence and part of the release process for any migration whose rollback plan depends on a snapshot.", "Pre-create and document the scratch VPC, subnet group, security group, and parameter group used for restore testing, so a real incident restore does not have to create them under pressure.", "Automate the restore test (scheduled restore into an isolated account, automated fingerprint comparison, automatic teardown) so it runs without depending on somebody remembering."],
    production_safety=["Every SQL script in this workflow is strictly read-only, on both the source and the restored cluster.", "The restore itself creates a new, separate cluster: it never modifies, replaces, or risks the production cluster, and it cannot be performed in place.", "The restored scratch cluster contains real production data -- customer balances, ledger entries, personally identifiable information -- so it must be created in an access-controlled environment, never pointed at by an application, and deleted promptly after validation.", "Never restore a snapshot into a cluster that reuses a production identifier, security group, or endpoint naming convention that an application could accidentally resolve."],
    escalation_criteria=["A snapshot fails to restore for any reason -- escalate immediately and treat the rollback plan that depended on it as invalid until a successful restore is demonstrated.", "The restored cluster's fingerprint differs from the source in ways that are not explained by the time gap between the snapshot and the fingerprint -- escalate to AWS Support and to the platform and compliance owners, since this calls actual data recoverability into question.", "The measured restore duration substantially exceeds the documented RTO for the restore scenario -- escalate through rto-rpo-validation as a policy gap."],
    related_issues=["../backup-and-restore-validation/README.md", "../point-in-time-recovery-drill/README.md", "../rto-rpo-validation/README.md", "../cluster-failover-drill/README.md", "../../database-health/comprehensive-health-check/README.md"],
    aurora_notes=["Aurora restores a DB cluster snapshot into a brand-new cluster with a new endpoint; the restore is never in place, and the restored cluster starts with no instances until you create at least one. An encrypted snapshot restores into an encrypted cluster and requires access to the KMS key it was encrypted with, which is the single most common blocker for a cross-account or cross-region restore. The restored cluster also takes whatever parameter group you specify (or the default) rather than automatically inheriting the source cluster's, which is why the settings comparison in this workflow's validation script matters."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_source_cluster_fingerprint", "Fingerprints the source cluster immediately before the snapshot restore test: object inventory, per-table row estimates and sizes, extensions, and key settings.",
               """
-- Object inventory for the current database. Compare this against the same
-- query on the restored cluster -- a missing relation or a materially
-- different count is the finding a restore test exists to surface.
SELECT
    count(*) FILTER (WHERE c.relkind IN ('r', 'p'))              AS table_count,
    count(*) FILTER (WHERE c.relkind = 'i')                      AS index_count,
    count(*) FILTER (WHERE c.relkind = 'm')                      AS matview_count,
    count(*) FILTER (WHERE c.relkind = 'S')                      AS sequence_count,
    count(DISTINCT n.nspname)                                    AS schema_count,
    pg_size_pretty(pg_database_size(current_database()))         AS database_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema');

-- Per-table row estimates and sizes, largest first. reltuples is an
-- estimate maintained by vacuum/analyze rather than an exact count, which
-- is exactly what is wanted here: it is cheap on a very large cluster and
-- precise enough for a source-versus-restored comparison.
\\set top_n 50
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    c.reltuples::bigint                                          AS estimated_rows,
    pg_size_pretty(pg_total_relation_size(c.oid))                AS total_size,
    pg_total_relation_size(c.oid)                                AS total_bytes
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;
""".strip("\n") + "\n\n" + sb.extension_inventory() + "\n\n" + sb.key_settings_snapshot(),
               "Save all four result sets verbatim as the pre-restore fingerprint, together with the exact time they were captured -- the capture time is what explains legitimate differences later, since the snapshot represents a moment that is almost never identical to the fingerprint moment. Pay particular attention to the extension inventory and key settings: these are the two areas where a restored cluster most often differs from its source through configuration rather than data, because the restore takes the parameter group you specify rather than inheriting the source's.",
               execution_location=WRITER_ONLY,
               expected_runtime="Low, though the per-table sizing portion touches every relation's size on disk -- run it off-peak on a cluster with very many relations.",
               related_scripts="02_restored_cluster_validation.sql, 03_snapshot_restore_runbook.md"),
    sql_script("02", "02_restored_cluster_validation", "Run on the restored scratch cluster: repeats the source fingerprint and adds engine identity and instance role, for a direct comparison against script 01.",
               """
-- Run this against the RESTORED scratch cluster, not production. It repeats
-- script 01's fingerprint and adds the engine identity and instance role,
-- so the comparison covers "is it the same data" and "is it the same
-- engine and configuration" together.
SELECT
    current_database()                                           AS database_name,
    current_setting('server_version')                            AS server_version,
    pg_is_in_recovery()                                          AS is_reader_instance,
    pg_postmaster_start_time()                                   AS instance_start_time,
    now() - pg_postmaster_start_time()                           AS instance_uptime,
    clock_timestamp()                                            AS validated_at;

SELECT
    count(*) FILTER (WHERE c.relkind IN ('r', 'p'))              AS table_count,
    count(*) FILTER (WHERE c.relkind = 'i')                      AS index_count,
    count(*) FILTER (WHERE c.relkind = 'm')                      AS matview_count,
    count(*) FILTER (WHERE c.relkind = 'S')                      AS sequence_count,
    count(DISTINCT n.nspname)                                    AS schema_count,
    pg_size_pretty(pg_database_size(current_database()))         AS database_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema');

\\set top_n 50
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    c.reltuples::bigint                                          AS estimated_rows,
    pg_size_pretty(pg_total_relation_size(c.oid))                AS total_size,
    pg_total_relation_size(c.oid)                                AS total_bytes
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;

-- Any index left INVALID by an interrupted build on the source cluster is
-- restored in that same invalid state -- worth catching here rather than
-- discovering it in a recovery that depended on the index existing.
SELECT
    n.nspname                                                    AS schema_name,
    t.relname                                                    AS table_name,
    i.relname                                                    AS index_name,
    ix.indisvalid                                                AS is_valid,
    ix.indisready                                                AS is_ready
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE NOT ix.indisvalid
   OR NOT ix.indisready
ORDER BY n.nspname, t.relname, i.relname;
""".strip("\n") + "\n\n" + sb.extension_inventory() + "\n\n" + sb.key_settings_snapshot(),
               "Compare each result set against script 01's saved output from the source cluster. Object counts and per-table row estimates should match within the drift explained by writes between the snapshot and the source fingerprint -- a table missing entirely, or an estimate off by an order of magnitude, is a genuine finding. A settings difference almost always means the restore used a different (often default) parameter group, which must be corrected before any performance comparison or before the restored cluster is considered a viable recovery target. A missing extension means the restored cluster cannot run the parts of this toolkit or the application that depend on it. Ignore differences in pg_stat_database counters: statistics start fresh on a restored cluster and prove nothing either way.",
               execution_location=WRITER_ONLY,
               prerequisites="Run against the restored scratch cluster, after at least one DB instance has been provisioned in it and is available. Script 01 must already have been run and saved on the source cluster.",
               expected_runtime="Low, though the per-table sizing portion touches every relation's size on disk.",
               related_scripts="01_source_cluster_fingerprint.sql, 04_restore_test_checklist.md"),
    md_script("03", "03_snapshot_restore_runbook", "AWS-side guidance for selecting a snapshot, restoring it into an isolated scratch cluster, provisioning an instance, and tearing the environment down afterward.",
              (
                  "This file documents an AWS control-plane procedure. Nothing here is a SQL statement "
                  "and nothing here modifies the production cluster -- an Aurora snapshot restore "
                  "always creates a new cluster and can never overwrite an existing one.\n\n"
                  "## 1. Choose the snapshot to test\n\n"
                  "```\n"
                  "aws rds describe-db-cluster-snapshots \\\n"
                  "  --db-cluster-identifier <cluster-identifier> \\\n"
                  "  --query 'DBClusterSnapshots[].[DBClusterSnapshotIdentifier,SnapshotType,Status,SnapshotCreateTime,StorageEncrypted,KmsKeyId]'\n"
                  "```\n\n"
                  "Prefer testing the kind of snapshot your rollback plans actually depend on -- if "
                  "releases are gated on a manual pre-release snapshot, test a manual snapshot, not an "
                  "automated one. Note `StorageEncrypted` and `KmsKeyId`: if the snapshot is encrypted, "
                  "the restoring principal needs access to that key, and for a cross-account copy the "
                  "key policy must grant the restoring account access. This is the most common reason a "
                  "first restore attempt fails.\n\n"
                  "## 2. Restore into an isolated scratch cluster\n\n"
                  "```\n"
                  "aws rds restore-db-cluster-from-snapshot \\\n"
                  "  --db-cluster-identifier <scratch-cluster-identifier> \\\n"
                  "  --snapshot-identifier <snapshot-identifier> \\\n"
                  "  --engine aurora-postgresql \\\n"
                  "  --db-subnet-group-name <non-production-subnet-group> \\\n"
                  "  --vpc-security-group-ids <restricted-security-group-id> \\\n"
                  "  --db-cluster-parameter-group-name <same-parameter-group-as-source>\n"
                  "```\n\n"
                  "Specify the source cluster's parameter group explicitly. If you omit it, the "
                  "restored cluster uses the default group, and the settings comparison in script 02 "
                  "will differ for reasons that have nothing to do with the snapshot.\n\n"
                  "Use a restricted security group that permits access only from the DBA bastion or "
                  "equivalent. The restored cluster contains real customer balances and ledger "
                  "history; it must not be reachable from anything that could treat it as a live "
                  "environment.\n\n"
                  "## 3. Provision an instance -- the restore is not usable without one\n\n"
                  "```\n"
                  "aws rds create-db-instance \\\n"
                  "  --db-instance-identifier <scratch-instance-identifier> \\\n"
                  "  --db-cluster-identifier <scratch-cluster-identifier> \\\n"
                  "  --engine aurora-postgresql \\\n"
                  "  --db-instance-class <instance-class>\n"
                  "```\n\n"
                  "For a test whose purpose includes evidencing recovery time, use the same instance "
                  "class as production -- a restore validated on a small instance class does not "
                  "evidence the RTO of a production-sized recovery (see `rto-rpo-validation`).\n\n"
                  "## 4. Wait for availability and record the elapsed time\n\n"
                  "```\n"
                  "aws rds wait db-instance-available \\\n"
                  "  --db-instance-identifier <scratch-instance-identifier>\n"
                  "```\n\n"
                  "Record the wall-clock time for the cluster restore and for instance provisioning "
                  "separately -- provisioning is frequently the larger of the two, and knowing the "
                  "split is what makes the measurement actionable.\n\n"
                  "If the instance does not reach `available`, read the events before blaming the "
                  "snapshot:\n\n"
                  "```\n"
                  "aws rds describe-events \\\n"
                  "  --source-identifier <scratch-instance-identifier> \\\n"
                  "  --source-type db-instance \\\n"
                  "  --duration 120\n"
                  "```\n\n"
                  "## 5. Validate\n\n"
                  "Connect to the restored cluster's writer endpoint and run "
                  "`02_restored_cluster_validation.sql`, then work through "
                  "`04_restore_test_checklist.md`.\n\n"
                  "## 6. Tear the scratch environment down\n\n"
                  "```\n"
                  "aws rds delete-db-instance \\\n"
                  "  --db-instance-identifier <scratch-instance-identifier> \\\n"
                  "  --skip-final-snapshot\n\n"
                  "aws rds delete-db-cluster \\\n"
                  "  --db-cluster-identifier <scratch-cluster-identifier> \\\n"
                  "  --skip-final-snapshot\n"
                  "```\n\n"
                  "Delete the instance first, then the cluster. Teardown is not optional housekeeping: "
                  "a forgotten scratch cluster holding production data is a standing security exposure "
                  "as well as an ongoing cost, and it is exactly the kind of environment that ends up "
                  "outside the normal access review.\n\n"
                  "## Do NOT\n\n"
                  "- Do NOT point any application, job, or reporting tool at the scratch cluster.\n"
                  "- Do NOT reuse a production-like identifier or DNS name for it.\n"
                  "- Do NOT call the test successful at the point the cluster reaches `available` -- "
                  "availability is not validation, and script 02 is what distinguishes them.\n"
              ),
              "Restore into an isolated, access-restricted environment, specify the source parameter group explicitly, validate with script 02 before calling the test successful, and tear the scratch environment down the same day.",
              safety="INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY",
              expected_impact="No impact on the production cluster -- a snapshot restore always creates a new cluster. Creates temporary AWS cost for the scratch cluster and instance until they are deleted.",
              required_privileges="IAM permission for rds:DescribeDBClusterSnapshots, rds:RestoreDBClusterFromSnapshot, rds:CreateDBInstance, rds:DeleteDBInstance, and rds:DeleteDBCluster; KMS key access for an encrypted snapshot. No PostgreSQL role is used for the restore itself.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Minutes for the restore call; tens of minutes to hours for the cluster restore plus instance provisioning, scaling with data volume and instance class.",
              related_scripts="01_source_cluster_fingerprint.sql, 02_restored_cluster_validation.sql, 04_restore_test_checklist.md"),
    md_script("04", "04_restore_test_checklist", "The ordered checklist for a snapshot restore test, including the business-data spot checks that a catalog-level fingerprint comparison cannot cover.",
              (
                  "## Before the test\n\n"
                  "1. Confirm the scratch VPC, subnet group, security group, and parameter group exist "
                  "and are documented -- create them ahead of time, not during the test.\n"
                  "2. Confirm KMS key access for the snapshot if it is encrypted, including for a "
                  "cross-account or cross-region copy.\n"
                  "3. Run `01_source_cluster_fingerprint.sql` on production and save the output with "
                  "its capture time.\n"
                  "4. Record T0 for the RTO measurement (see `rto-rpo-validation`).\n\n"
                  "## Restore\n\n"
                  "5. Follow `03_snapshot_restore_runbook.md` steps 1 through 4, recording the elapsed "
                  "time for the cluster restore and instance provisioning separately.\n\n"
                  "## Validate\n\n"
                  "6. Run `02_restored_cluster_validation.sql` on the restored cluster and diff every "
                  "result set against the saved source fingerprint.\n"
                  "7. Spot-check business-critical data directly -- a catalog fingerprint confirms "
                  "shape, not correctness. On a trading platform this usually means: the most recent "
                  "rows in the trades and order-events tables, a sample of account balances "
                  "reconciled against the ledger, the most recent deposit and withdrawal records, and "
                  "the newest partition of any time-partitioned table. Confirm the newest data present "
                  "is consistent with the snapshot's creation time rather than materially older.\n"
                  "8. Confirm sequence values are ahead of the maximum key values in their tables, so "
                  "a cluster promoted from this restore would not immediately collide on insert.\n"
                  "9. Confirm no index is INVALID (script 02's last result set) and that the extension "
                  "inventory matches the source.\n"
                  "10. If the application has a read-only smoke test suite that can be pointed at an "
                  "arbitrary endpoint, run it against the restored cluster -- this is the strongest "
                  "single piece of evidence a restore test can produce.\n\n"
                  "## Record\n\n"
                  "11. Record the measured restore duration and the observed recovery point in the "
                  "register described in `../rto-rpo-validation/README.md`.\n"
                  "12. Record every deviation, blocker, or manual intervention -- these are the items "
                  "that would have cost time during a real incident, and they are the real output of "
                  "the test.\n\n"
                  "## Tear down\n\n"
                  "13. Delete the scratch instance and cluster the same day, following step 6 of "
                  "`03_snapshot_restore_runbook.md`.\n"
                  "14. Confirm deletion actually completed rather than assuming it -- a delete call "
                  "that failed on a deletion-protection flag leaves a production-data cluster running "
                  "indefinitely.\n\n"
                  "## Cadence\n\n"
                  "Quarterly at minimum, and additionally before any migration or release whose "
                  "rollback plan depends on restoring a snapshot. A rollback plan that depends on an "
                  "untested restore is not a rollback plan.\n"
              ),
              "Follow the checklist end to end, including teardown -- the steps most often skipped are the business-data spot checks in step 7 and the deletion confirmation in step 14, and both are the ones that matter most.",
              safety="DOCUMENTATION -- no SQL executed by this file itself",
              expected_impact="None from this file directly; the restore steps it sequences carry the impact documented in script 03.",
              required_privileges="N/A for this file itself; see scripts 01, 02, and 03 for their own required privileges.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Variable -- dominated by the restore and instance provisioning time in script 03.",
              related_scripts="01_source_cluster_fingerprint.sql, 02_restored_cluster_validation.sql, 03_snapshot_restore_runbook.md, ../rto-rpo-validation/README.md"),
]
