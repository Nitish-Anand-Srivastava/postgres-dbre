"""Workflow definitions: maintenance/ category (7 workflow directories).

This is an OPEN_CATALOG category (see tools/validation/catalog.py) -- there
is no fixed, exact required workflow slug list, only a requirement that the
category directory exists and has at least one workflow. The seven workflows
below cover the recurring maintenance checklist, reindex campaign planning,
extension upgrade planning, Aurora parameter-group change management, minor
engine version upgrade readiness, planner statistics maintenance, and the
planned maintenance window checklist that wraps every disruptive change --
the standing, planned (non-incident) operational work a DBA is responsible
for on an Aurora PostgreSQL cluster.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import ANY_INSTANCE, TABLE_OWNER_OR_DDL, WRITER_ONLY, md_script, sql_script
from .model import Workflow

CATEGORY_SLUG = "maintenance"
CATEGORY_TITLE = "Maintenance"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

# ---------------------------------------------------------------------------
# routine-maintenance-checklist
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="routine-maintenance-checklist",
    title="Routine Maintenance Checklist",
    summary="A recurring, standing checklist covering vacuum/autovacuum health, index bloat, planner statistics freshness, extension/settings drift, and a pointer to backup verification -- the standard set of checks a DBA runs on a regular cadence (weekly/monthly) rather than only reactively during an incident.",
    symptoms=["No active symptom -- this is a scheduled, proactive workflow, not an incident-response one.", "Run ahead of a compliance/operational review to produce evidence the cluster is being actively maintained."],
    business_impact=["Most of the incidents covered elsewhere in this repository (autovacuum falling behind, bloat accumulating unnoticed, stale statistics causing plan regressions) are cheaper to prevent via a regular checklist than to diagnose after they have already caused a customer-visible incident."],
    root_causes=["N/A -- this is a preventive/monitoring workflow, not a root-cause investigation for a single symptom."],
    investigation_strategy=["Check dead-tuple accumulation and autovacuum activity across the cluster's tables.", "Check index bloat/usage for obviously bloated or unused indexes.", "Check planner statistics freshness.", "Check installed extension versions and key settings for unexpected drift from the documented baseline.", "Confirm backup/restore verification (disaster-recovery/backup-and-restore-validation) has run within its own cadence."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["Treat this checklist as a trend-line exercise, not a single-snapshot pass/fail -- a slowly worsening dead-tuple count or a statistics-freshness gap that widens run over run is the actual signal, even when any single run looks unremarkable in isolation.", "A finding here that matches an existing dedicated workflow (e.g. dead tuples piling up) should be handed off to that workflow (vacuum-and-autovacuum/dead-tuples) for the full investigation rather than remediated ad hoc from this checklist."],
    remediation_immediate=["N/A -- pivot to the specific matching workflow (vacuum-and-autovacuum/*, tables-and-indexes/index-bloat, query-optimization/stale-statistics) for any finding that needs immediate action."],
    remediation_short_term=["Schedule follow-up on any finding that is trending worse run over run, even if not yet at an actionable threshold."],
    remediation_long_term=["Automate this checklist's read-only steps into a scheduled job (see automation/health-checks) so the checklist itself does not depend on someone remembering to run it manually."],
    production_safety=["Every SQL script in this checklist is read-only."],
    escalation_criteria=["A trend line across multiple checklist runs shows a metric worsening toward a known danger threshold (e.g. dead-tuple ratio, transaction ID age) with no corrective action yet taken -- escalate before it becomes an active incident."],
    related_issues=["../../vacuum-and-autovacuum/dead-tuples/README.md", "../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md", "../../database-health/daily-health-check/README.md", "../../disaster-recovery/backup-and-restore-validation/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_dead_tuples_and_autovacuum_activity", "Ranks tables by dead-tuple volume and shows currently active autovacuum workers, the first stop for the vacuum-health portion of the checklist.",
               sb.dead_tuples_ranked(),
               "A table with a high dead-tuple ratio that keeps recurring run over run despite autovacuum activity elsewhere is worth a dedicated look via vacuum-and-autovacuum/autovacuum-not-keeping-up rather than being noted and deferred again.",
               related_scripts="02_index_bloat_and_usage.sql"),
    sql_script("02", "02_index_bloat_and_usage", "Surfaces index size, scan counts, and last-used timestamps to catch both bloated and simply-unused indexes as part of the routine review.",
               sb.index_bloat_and_usage(),
               "An index with idx_scan = 0 (or a last_idx_scan far in the past) across several checklist runs is a candidate for tables-and-indexes/unused-indexes; an index that is large relative to its table without an obvious reason is a candidate for reindex-strategy.",
               related_scripts="03_statistics_freshness.sql"),
    sql_script("03", "03_statistics_freshness", "Checks how stale planner statistics are across tables, since this checklist is often the first place staleness is noticed before it causes a plan regression.",
               sb.statistics_freshness(),
               "A table with a large n_mod_since_analyze relative to its row count, and a last_analyze/last_autoanalyze far in the past, is a candidate for a manual ANALYZE (see vacuum-and-autovacuum/analyze-statistics) before it causes a query-optimization/stale-statistics incident.",
               related_scripts="04_extension_and_key_settings_inventory.sql"),
    sql_script("04", "04_extension_and_key_settings_inventory", "Snapshots installed extension versions and the settings most likely to drift or matter operationally, to catch unexpected configuration/version drift between checklist runs.",
               sb.extension_inventory() + "\n\n" + sb.key_settings_snapshot(),
               "Compare this run's extension versions against the previous run and against extension-upgrade-planning's findings; compare key settings against the documented baseline for this cluster -- any unexplained difference (e.g. a setting reverted after a parameter-group rollback) is the finding.",
               related_scripts="05_routine_maintenance_checklist.md"),
    md_script("05", "05_routine_maintenance_checklist", "The checklist itself: the ordered list of checks to run each cycle, what to do with each finding, and the cadence this workflow is intended to run on.",
              (
                  "## Cadence\n\n"
                  "Run this checklist on a fixed cadence (weekly is a reasonable starting point for a "
                  "high-throughput exchange platform; monthly at minimum) regardless of whether any "
                  "incident has occurred -- its value is in catching a slow trend before it becomes "
                  "one.\n\n"
                  "## Checklist\n\n"
                  "1. Run `01_dead_tuples_and_autovacuum_activity.sql`. Hand off any table with a "
                  "worsening trend to `vacuum-and-autovacuum/dead-tuples` or "
                  "`vacuum-and-autovacuum/autovacuum-not-keeping-up`.\n"
                  "2. Run `02_index_bloat_and_usage.sql`. Hand off unused indexes to "
                  "`tables-and-indexes/unused-indexes`; hand off bloated-but-used indexes to "
                  "`reindex-strategy` in this category.\n"
                  "3. Run `03_statistics_freshness.sql`. Hand off stale tables to "
                  "`vacuum-and-autovacuum/analyze-statistics`.\n"
                  "4. Run `04_extension_and_key_settings_inventory.sql`. Compare against the previous "
                  "run's saved output and the documented baseline; hand off any extension needing an "
                  "upgrade to `extension-upgrade-planning` in this category.\n"
                  "5. Confirm `disaster-recovery/backup-and-restore-validation` has been run within its "
                  "own required cadence -- this checklist does not re-run that workflow's steps "
                  "itself, it only confirms the standing evidence exists.\n"
                  "6. File or update a single tracking ticket per cycle recording the date, findings, "
                  "and any hand-offs created, so trends across cycles are reviewable later.\n\n"
                  "## What this checklist is not\n\n"
                  "This is a review-and-triage checklist, not a remediation workflow -- every finding "
                  "here should be handed off to the specific dedicated workflow named above (which has "
                  "its own full investigation, interpretation, and remediation guidance) rather than "
                  "acted on directly from this checklist.\n"
              ),
              "Follow the checklist in order once per scheduled cycle; the value of this workflow comes from consistent cadence and consistent hand-off, not from any single run in isolation.",
              safety="DOCUMENTATION -- no SQL executed by this file itself",
              expected_impact="None from this file directly; hand-off workflows carry their own impact.",
              required_privileges="N/A for this file itself; see the hand-off workflow for its own required privileges.",
              related_scripts="01_dead_tuples_and_autovacuum_activity.sql, 02_index_bloat_and_usage.sql, 03_statistics_freshness.sql, 04_extension_and_key_settings_inventory.sql"),
]

# ---------------------------------------------------------------------------
# reindex-strategy
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="reindex-strategy",
    title="REINDEX CONCURRENTLY Campaign Planning",
    summary="Plans a batched, off-peak REINDEX CONCURRENTLY campaign across multiple bloated indexes in a cluster -- distinct from schema-changes/concurrent-index-build's single-index build guidance, this workflow is about sequencing and monitoring a multi-index campaign safely.",
    symptoms=["index-bloat/routine-maintenance-checklist findings identify multiple bloated indexes across several tables that need rebuilding.", "A large batch of indexes has not been rebuilt since initial creation and bloat has accumulated over months of write traffic."],
    business_impact=["Rebuilding many indexes without a plan (all at once, during peak hours, without monitoring) risks compounding I/O/CPU load across the cluster at the worst possible time; a planned, batched, off-peak campaign gets the same space/performance benefit without that risk."],
    root_causes=["Indexes accumulate bloat over time from update/delete churn the same way tables do, but unlike table bloat (addressed continuously by autovacuum), PostgreSQL has no automatic index-bloat reclamation -- REINDEX (or an equivalent extension-based tool) is the only way to reclaim it.", "A cluster that has never had a standing reindex cadence accumulates a large backlog that then requires a deliberate campaign rather than one-off maintenance."],
    investigation_strategy=["Identify and rank candidate indexes by size/bloat and usage, to sequence the campaign by highest-value target first.", "Check for any REINDEX (or CREATE INDEX CONCURRENTLY) already in progress before starting another, since concurrent index-maintenance operations compete for maintenance_work_mem and I/O.", "Plan batch size and off-peak scheduling before starting, rather than reacting index-by-index."],
    prerequisites=["Table-owner privilege (or pg_maintain membership) on every index's parent table; an off-peak maintenance window agreed with stakeholders for a multi-index campaign on a high-traffic cluster."],
    interpretation_guide=["REINDEX CONCURRENTLY (available since PostgreSQL 12) avoids the exclusive lock a plain REINDEX takes, at the cost of roughly double the disk space during the rebuild (old and new index coexist briefly) and a longer overall duration than the blocking form -- sequencing indexes one at a time, or a few at a time bounded by available disk headroom, avoids running out of space mid-campaign.", "pg_stat_progress_create_index reports REINDEX CONCURRENTLY's progress under the same view as CREATE INDEX CONCURRENTLY (the `command` column distinguishes them) -- a build parked in a 'waiting for ...' phase is blocked on another transaction finishing, not on I/O, and no amount of extra maintenance_work_mem will speed that up."],
    remediation_immediate=["N/A -- this is a planned maintenance workflow, not an incident response."],
    remediation_short_term=["Execute the campaign in the planned batches, monitoring each batch's progress before starting the next."],
    remediation_long_term=["Establish a standing reindex cadence (e.g. as part of routine-maintenance-checklist) so bloat is addressed incrementally going forward instead of requiring another large one-off campaign."],
    production_safety=["The investigation/monitoring scripts here are read-only. The REINDEX CONCURRENTLY campaign itself is a guarded, manual runbook -- it takes a SHARE UPDATE EXCLUSIVE lock (blocks other DDL and VACUUM on the table, but not ordinary reads/writes) and requires roughly double the index's disk space during the rebuild."],
    escalation_criteria=["Available disk headroom on the cluster is not comfortably larger than the single largest candidate index's current size -- escalate for a capacity check (storage-and-capacity/capacity-forecasting) before starting the campaign, since REINDEX CONCURRENTLY needs to build the full new index before dropping the old one."],
    related_issues=["../../tables-and-indexes/index-bloat/README.md", "../../schema-changes/concurrent-index-build/README.md", "../routine-maintenance-checklist/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_reindex_candidate_ranking", "Ranks indexes by size and usage to sequence the campaign, reusing the same bloat/usage view as the routine checklist.",
               sb.index_bloat_and_usage(),
               "Sequence the campaign starting with the largest indexes that are still actively used (idx_scan > 0) -- these carry the most bloat-reclamation benefit; deprioritize or drop-instead-of-reindex any candidate that also shows idx_scan = 0 (see tables-and-indexes/unused-indexes first, since rebuilding an unused index wastes the maintenance window).",
               related_scripts="02_reindex_progress_monitor.sql"),
    sql_script("02", "02_reindex_progress_monitor", "Monitors live progress of any REINDEX CONCURRENTLY (or CREATE INDEX CONCURRENTLY) currently running, to confirm each batch is progressing before starting the next.",
               sb.create_index_progress(),
               "A `command` value of 'REINDEX CONCURRENTLY' confirms this is the campaign's own operation; a phase parked on 'waiting for old snapshots' or similar is waiting on another transaction to end, not on I/O -- check concurrency-and-locking/long-running-transactions for what might be holding it up before assuming the rebuild itself is slow.",
               related_scripts="03_reindex_concurrently_runbook.md"),
    md_script("03", "03_reindex_concurrently_runbook", "Guarded runbook for executing a batched REINDEX CONCURRENTLY campaign across the candidates identified in script 01.",
              (
                  "## Plan the batches first\n\n"
                  "Using `01_reindex_candidate_ranking.sql`'s output, group candidates into batches "
                  "sized so that the cumulative disk space needed (roughly the sum of each batch's "
                  "candidate index sizes, since the old and new index coexist briefly) stays "
                  "comfortably within available headroom -- do not plan a batch that could exhaust "
                  "disk space mid-rebuild.\n\n"
                  "## Run one index at a time within a batch\n\n"
                  "```sql\n"
                  "REINDEX INDEX CONCURRENTLY public.idx_orders_customer_id;\n"
                  "```\n\n"
                  "Replace the index name with the actual next candidate from script 01's ranked "
                  "output for this batch. `REINDEX INDEX CONCURRENTLY` (unlike plain `REINDEX INDEX`) "
                  "does not take an ACCESS EXCLUSIVE lock, so ordinary reads/writes against the table "
                  "continue throughout -- but it does take a SHARE UPDATE EXCLUSIVE lock, which blocks "
                  "other DDL and a concurrent VACUUM on the same table, so do not start the next index "
                  "on the same table until this one completes.\n\n"
                  "## Monitor before starting the next\n\n"
                  "Re-run `02_reindex_progress_monitor.sql` and confirm no row remains for this index "
                  "before starting the next one in the batch.\n\n"
                  "## If a REINDEX CONCURRENTLY fails partway\n\n"
                  "PostgreSQL 14+ automatically cleans up an INVALID index left behind by a failed "
                  "`REINDEX CONCURRENTLY` on its next attempt; on any version, check for an INVALID "
                  "index afterward (`tables-and-indexes/invalid-indexes`) and drop it with `DROP INDEX "
                  "CONCURRENTLY` before retrying, since a leftover invalid index otherwise just "
                  "consumes space without serving any query.\n\n"
                  "## Between batches\n\n"
                  "Confirm disk headroom is back to a comfortable level (the temporary extra space "
                  "from the completed batch's old indexes has been released) before starting the next "
                  "batch, and prefer scheduling batches during the cluster's lowest-traffic window "
                  "even though `CONCURRENTLY` does not block ordinary queries -- the rebuild still "
                  "consumes real I/O and CPU shared with production traffic.\n"
              ),
              "Work through one index at a time within a batch, confirming completion via the progress monitor before moving to the next -- do not launch an entire batch's REINDEX statements concurrently against the same table.",
              safety="LOW RISK WRITE (REINDEX CONCURRENTLY takes SHARE UPDATE EXCLUSIVE, not ACCESS EXCLUSIVE; ordinary reads/writes continue -- see runbook for lock/disk-space details)",
              expected_impact="Real I/O/CPU load for the duration of each index rebuild, plus roughly double that index's disk space temporarily; blocks other DDL and VACUUM on the same table until each REINDEX CONCURRENTLY completes.",
              required_privileges=TABLE_OWNER_OR_DDL,
              execution_location=WRITER_ONLY,
              expected_runtime="Minutes to hours per index depending on size; plan the full campaign across multiple maintenance windows for a large backlog.",
              related_scripts="01_reindex_candidate_ranking.sql, 02_reindex_progress_monitor.sql, ../../tables-and-indexes/invalid-indexes/README.md"),
]

# ---------------------------------------------------------------------------
# extension-upgrade-planning
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="extension-upgrade-planning",
    title="Extension Upgrade Planning",
    summary="Plans ALTER EXTENSION ... UPDATE for installed extensions that have a newer version available on this Aurora engine version -- distinguishing routine, low-risk extension updates from ones with a documented behavior change worth testing before applying in production.",
    symptoms=["routine-maintenance-checklist's extension inventory shows an installed extension version older than what is available.", "A newly required feature (e.g. a pg_stat_statements column added in a later extension version) is missing even though the extension itself is installed."],
    business_impact=["An extension left on an old version can be missing bug fixes or new observability columns other workflows in this repository depend on (e.g. pg_stat_statements' per-query WAL/I/O columns), and, on the security side, an outdated extension version can itself be the subject of a CVE."],
    root_causes=["An extension was installed once (at whatever version was current then) and never revisited as the Aurora engine itself was upgraded across versions that bundled newer extension releases.", "ALTER EXTENSION ... UPDATE is not automatic -- installing a newer extension binary via an engine upgrade does not itself update an already-created extension's active SQL-level version in a given database."],
    investigation_strategy=["Inventory currently installed extensions and their active versions.", "Compare each installed extension's version against the newest version available on this Aurora engine release.", "For any extension with an available upgrade, check whether the specific version jump has a documented behavior change (new/renamed columns, changed function signatures) before just running the upgrade."],
    prerequisites=["Table/database-owner-equivalent privilege to run ALTER EXTENSION; access to the extension's own release notes for the specific version jump identified."],
    interpretation_guide=["upgrade_available = true only tells you a newer version exists on this engine, not that it is risk-free to apply -- a patch-level version bump (e.g. 1.9 to 1.10) is usually safe to apply directly, while a major version bump (e.g. 1.x to 2.x) is more likely to include a schema or function-signature change worth testing against a non-production copy first.", "The naive text-based max() comparison used here can misorder multi-digit version segments (e.g. '1.9' vs '1.10') -- always visually confirm the actual available version list from pg_available_extension_versions rather than trusting the boolean flag alone for anything but a quick first pass."],
    remediation_immediate=["N/A -- this is a planning workflow; an extension version being behind current is essentially never itself an active incident."],
    remediation_short_term=["Apply a confirmed low-risk (patch-level) extension upgrade via the guarded runbook during a routine maintenance window."],
    remediation_long_term=["Add extension-version review to the standing routine-maintenance-checklist cadence so upgrades happen incrementally rather than accumulating into a large, higher-risk jump."],
    production_safety=["The investigation scripts are read-only. ALTER EXTENSION ... UPDATE itself is a guarded, change-managed DDL step -- it can briefly hold locks on objects the extension owns and, for some extensions, can change function behavior/output that dependent application code relies on, so it must be tested against a non-production copy first for anything beyond a routine patch bump."],
    escalation_criteria=["An installed extension is multiple major versions behind what is available, with no documented upgrade path tested -- escalate for a dedicated upgrade project rather than attempting it as routine maintenance."],
    related_issues=["../routine-maintenance-checklist/README.md", "../../schema-changes/README.md"],
    aurora_notes=["Aurora PostgreSQL supports a curated, engine-version-specific set of extensions and extension versions -- an extension version shown as available in pg_available_extension_versions is guaranteed compatible with this specific Aurora engine release; do not attempt to install a version from upstream PostgreSQL documentation that is not listed there."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_installed_extension_inventory", "Baseline inventory of every extension currently installed and its active version, the starting point for upgrade planning.",
               sb.extension_inventory(),
               "This is the same inventory used by routine-maintenance-checklist -- use it here specifically as the baseline for the version-skew comparison in the next script.",
               related_scripts="02_extension_version_skew_check.sql"),
    sql_script("02", "02_extension_version_skew_check", "Compares each installed extension's active version against the newest version available on this Aurora engine release.",
               """
-- Flags any installed extension with a newer version available on this
-- specific Aurora engine release. The comparison itself is a plain text
-- max() over pg_available_extension_versions.version, which is a reasonable
-- first pass but can misorder multi-digit version segments (e.g. '1.9' vs
-- '1.10') -- always look at the actual version list for anything but a
-- quick triage.
SELECT
    e.extname,
    e.extversion                                                AS installed_version,
    (SELECT max(v.version)
       FROM pg_available_extension_versions v
      WHERE v.name = e.extname)                                 AS latest_available_version,
    e.extversion <> (SELECT max(v.version)
                        FROM pg_available_extension_versions v
                       WHERE v.name = e.extname)                 AS upgrade_available
FROM pg_extension e
ORDER BY upgrade_available DESC, e.extname;
""".strip("\n"),
               "upgrade_available = true identifies a candidate; before applying, look up the specific version jump's release notes (or the extension's CHANGELOG) to classify it as a routine patch bump vs. a larger jump worth testing first -- see 03_extension_upgrade_runbook.md.",
               related_scripts="03_extension_upgrade_runbook.md"),
    md_script("03", "03_extension_upgrade_runbook", "Guarded runbook for applying ALTER EXTENSION ... UPDATE for an extension identified as needing an upgrade by script 02.",
              (
                  "## Classify the version jump first\n\n"
                  "Using `02_extension_version_skew_check.sql`'s output, look up the specific "
                  "installed_version -> latest_available_version jump in the extension's own release "
                  "notes. A patch-level bump within the same major version is usually safe to apply "
                  "directly; any major-version change should be tested against a non-production copy "
                  "of this database first, since it may add/rename columns or change a function's "
                  "signature that application code or another workflow in this repository (e.g. "
                  "observability/slow-query-observability's pg_stat_statements queries) depends on.\n\n"
                  "## Applying the upgrade\n\n"
                  "```sql\n"
                  "ALTER EXTENSION pg_stat_statements UPDATE;\n"
                  "```\n\n"
                  "Replace `pg_stat_statements` with the actual extension identified in script 02. "
                  "`ALTER EXTENSION ... UPDATE` (with no `TO` clause) upgrades to the default (latest "
                  "available) version; add `TO 'x.y'` to target a specific intermediate version "
                  "instead if you are deliberately not jumping straight to the latest.\n\n"
                  "## After applying\n\n"
                  "1. Re-run `01_installed_extension_inventory.sql` to confirm the new extversion.\n"
                  "2. Re-run any workflow in this repository that specifically depends on that "
                  "extension (for example, re-run observability/slow-query-observability's "
                  "pg_stat_statements queries) to confirm nothing broke.\n"
                  "3. Note the upgrade and version in the next routine-maintenance-checklist cycle's "
                  "tracking ticket.\n\n"
                  "## Do NOT\n\n"
                  "- Do NOT run `CREATE EXTENSION` here -- this runbook only covers upgrading an "
                  "already-installed extension; installing a new extension for the first time is its "
                  "own separate, deliberate decision (see docs/prerequisites/README.md).\n"
                  "- Do NOT apply a major-version jump directly to production without first testing "
                  "against a non-production copy, even if the extension's own documentation describes "
                  "the upgrade as backward compatible.\n"
              ),
              "Classify the version jump before applying anything -- the runbook itself takes seconds to run, so the actual risk being managed here is an unreviewed behavior change, not the DDL statement's own duration.",
              safety="LOW RISK WRITE (ALTER EXTENSION ... UPDATE; briefly locks the extension's owned objects, does not rewrite table data)",
              expected_impact="Brief lock on objects owned by the extension during the upgrade; a major-version jump can change function signatures/output relied on by application code or other workflows.",
              required_privileges=TABLE_OWNER_OR_DDL,
              expected_runtime="Seconds for the ALTER EXTENSION statement itself; allow additional time for pre-upgrade testing against a non-production copy for any major-version jump.",
              related_scripts="01_installed_extension_inventory.sql, 02_extension_version_skew_check.sql"),
]

# ---------------------------------------------------------------------------
# parameter-group-change-management
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="parameter-group-change-management",
    title="Aurora Parameter Group Change Management",
    summary="Explains how Aurora's cluster vs. instance parameter groups work, how to tell whether a specific parameter change needs a reboot, and how to roll a change out safely -- the foundational mechanism every other workflow in this repository refers to whenever it says a setting must be changed via the parameter group rather than SQL.",
    symptoms=["A setting change made via the AWS Console/CLI does not appear to have taken effect.", "A previous parameter-group change is shown as 'pending-reboot' and nobody is sure whether/when it applied."],
    business_impact=["A parameter-group change applied incorrectly (wrong scope, unexpected reboot, or a value that regresses performance) affects every database in the cluster/instance at once -- getting the mechanism itself right is a prerequisite for every other workflow in this repository that recommends a configuration change."],
    root_causes=["The change was made to the DB instance parameter group when it needed to be cluster-wide (or vice versa), so it did not apply where expected.", "The specific parameter is static (requires a reboot) and no reboot was performed after the change, so the running value has not changed even though the parameter group itself now shows the new value.", "The change was applied directly to the default parameter group rather than a custom one, which AWS does not allow to be modified -- the change silently failed to be created at all."],
    investigation_strategy=["Confirm which settings are cluster-scoped vs. instance-scoped by reviewing their context/source in pg_settings.", "Check for any setting currently in a pending-restart state, meaning a parameter-group change has been made but not yet applied because the instance has not rebooted.", "Confirm you are targeting a custom (non-default) parameter group, since AWS does not allow direct modification of the default one."],
    prerequisites=["IAM permission to describe/modify DB cluster and instance parameter groups; a non-production cluster/parameter group to validate a new change against before applying to production."],
    interpretation_guide=["pending_restart = true for a setting means its parameter-group value has already changed but the running instance has not yet picked it up -- the instance needs a reboot (or, for some parameters, a failover) before the new value is actually in effect; do not assume a parameter-group change is live just because the AWS Console shows the parameter group itself updated.", "context in pg_settings ('postmaster', 'sighup', 'superuser', 'user', etc.) indicates how a setting can be changed at the PostgreSQL level, which combined with the parameter's ApplyType in describe-db-cluster-parameters tells you whether a reboot is required."],
    remediation_immediate=["N/A -- this is a foundational/reference workflow, not an incident-response one, though it is frequently consulted *during* an incident when another workflow's remediation calls for a configuration change."],
    remediation_short_term=["Apply any pending, already-approved parameter-group change during the next scheduled maintenance window rather than leaving it in pending-reboot indefinitely, since a change that is 'half-applied' (parameter group updated, instance not yet rebooted) is a common source of confusion during a later, unrelated investigation."],
    remediation_long_term=["Maintain the cluster's parameter groups as infrastructure-as-code (not manual Console edits) so every change is reviewable, and always validate a new parameter-group value against a non-production cluster/parameter group before applying it to production."],
    production_safety=["The SQL investigation here is entirely read-only. Applying a parameter-group change is an AWS control-plane action, not a SQL statement; for any parameter whose ApplyType requires a reboot, treat the reboot itself as the disruptive step and schedule it as a maintenance-window activity."],
    escalation_criteria=["A parameter-group change is found in a pending-reboot state for longer than a routine maintenance window would explain -- escalate to confirm whether it was intentionally deferred or simply forgotten."],
    related_issues=["../../security-and-access/ssl-and-connection-security/README.md", "../../security-and-access/audit-logging-and-iam-auth/README.md", "../reindex-strategy/README.md"],
    aurora_notes=["Aurora PostgreSQL uses two levels of parameter group: the DB cluster parameter group (values shared by every instance in the cluster -- most PostgreSQL settings live here) and the DB instance parameter group (writer/reader-specific overrides, used less often). Neither is edited via ALTER SYSTEM -- Aurora does not support ALTER SYSTEM for the great majority of parameters that matter operationally, and any attempt should be treated as a sign the wrong mechanism is being used, not as a workaround."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_key_settings_and_scope", "Snapshots the settings most commonly changed operationally, including each one's context, which indicates whether it can be changed dynamically, via SIGHUP, or only at instance start.",
               sb.key_settings_snapshot(),
               "context = 'postmaster' means the setting can only change by restarting the instance process (a reboot); context = 'sighup' means the running instance picks up a parameter-group change without a full reboot once AWS applies it; context = 'user'/'superuser' means it can be changed at the session/role level independent of the parameter group entirely.",
               related_scripts="02_pending_restart_settings.sql"),
    sql_script("02", "02_pending_restart_settings", "Lists every setting currently flagged as changed-in-the-parameter-group-but-not-yet-applied, the direct signal that a reboot (or failover) is needed to finish a previously started change.",
               """
-- Settings where pending_restart = true: the parameter group's stored value
-- differs from the value this running instance is actually using. This is
-- the definitive way to confirm a parameter-group change is only half
-- applied, rather than inferring it from the AWS Console alone.
SELECT
    name,
    setting                                                     AS currently_running_value,
    unit,
    context,
    pending_restart
FROM pg_settings
WHERE pending_restart = true
ORDER BY name;
""".strip("\n"),
               "Any row here means that setting's parameter-group value has already been changed but this specific instance has not yet rebooted to pick it up -- schedule the reboot deliberately (see the runbook) rather than leaving the cluster in a half-applied state indefinitely.",
               related_scripts="03_parameter_group_change_runbook.md"),
    md_script("03", "03_parameter_group_change_runbook", "Guarded runbook for making an Aurora parameter-group change safely: validating on non-prod first, understanding ApplyType, and scheduling any required reboot.",
              (
                  "## Choose the right parameter group\n\n"
                  "Cluster-wide settings (the majority of what matters operationally -- memory, "
                  "autovacuum, logging, statement/lock timeouts) belong on the DB **cluster** "
                  "parameter group, applied to every instance in the cluster. A small number of "
                  "instance-specific overrides belong on the DB **instance** parameter group instead. "
                  "Confirm you are editing a **custom** parameter group, not the AWS-managed default "
                  "one, which cannot be modified.\n\n"
                  "## Validate on non-production first\n\n"
                  "Apply the intended change to a non-production cluster's parameter group and "
                  "confirm the resulting behavior (via `01_key_settings_and_scope.sql`) before "
                  "touching production, especially for any setting affecting memory sizing or "
                  "autovacuum aggressiveness, where an overly aggressive value can itself cause a "
                  "performance regression.\n\n"
                  "## Applying the change\n\n"
                  "```\n"
                  "aws rds modify-db-cluster-parameter-group \\\n"
                  "  --db-cluster-parameter-group-name <cluster-parameter-group-name> \\\n"
                  "  --parameters \"ParameterName=<parameter-name>,ParameterValue=<new-value>,ApplyMethod=pending-reboot\"\n"
                  "```\n\n"
                  "Check the parameter's `ApplyType` first via:\n\n"
                  "```\n"
                  "aws rds describe-db-cluster-parameters \\\n"
                  "  --db-cluster-parameter-group-name <cluster-parameter-group-name> \\\n"
                  "  --query \"Parameters[?ParameterName=='<parameter-name>'].ApplyType\"\n"
                  "```\n\n"
                  "An `ApplyType` of `dynamic` can use `ApplyMethod=immediate` and takes effect without "
                  "a reboot; `static` requires `ApplyMethod=pending-reboot` and will not take effect "
                  "until each instance is rebooted.\n\n"
                  "## Scheduling the reboot (static parameters only)\n\n"
                  "Reboot readers first, then the writer, during an agreed maintenance window -- "
                  "rebooting the writer causes a brief failover-like interruption (see "
                  "disaster-recovery/cluster-failover-drill for what that interruption looks like from "
                  "the application's perspective). Re-run `02_pending_restart_settings.sql` "
                  "immediately after each reboot to confirm the setting cleared from the pending list.\n\n"
                  "## Do NOT\n\n"
                  "- Do NOT attempt `ALTER SYSTEM SET ...` as a substitute -- Aurora does not support it "
                  "for parameter-group-managed settings, and it will either fail outright or (for the "
                  "handful of settings where it is accepted) create a confusing split between the "
                  "session/instance-level value and the parameter group's own value.\n"
                  "- Do NOT apply a `static` parameter change with `ApplyMethod=immediate` expecting it "
                  "to take effect without a reboot -- AWS will accept the parameter-group update but "
                  "the running instance will not reflect it until rebooted regardless of the "
                  "ApplyMethod requested.\n"
              ),
              "Confirm ApplyType before choosing ApplyMethod, and always validate on non-production first -- the mechanism itself (cluster vs. instance parameter group, dynamic vs. static) is what most parameter-group-change mistakes get wrong, not the chosen value.",
              safety="LOW RISK WRITE (Aurora DB cluster/instance parameter group change; static parameters require a per-instance reboot to take effect -- see runbook)",
              expected_impact="None until applied; a static parameter's eventual reboot causes a brief per-instance availability interruption, worse on the writer than on a reader.",
              required_privileges="IAM permission to describe/modify DB cluster and instance parameter groups; no PostgreSQL role required for the parameter-group step itself.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Minutes to apply the parameter-group change itself; a full maintenance-window reboot cycle for any static parameter to take effect.",
              related_scripts="01_key_settings_and_scope.sql, 02_pending_restart_settings.sql"),
]


# ---------------------------------------------------------------------------
# minor-version-upgrade-readiness
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="minor-version-upgrade-readiness",
    title="Minor Version Upgrade Readiness",
    summary="Establishes, from inside the database, whether this Aurora PostgreSQL cluster is actually ready for a minor engine version upgrade -- current engine version, the in-database conditions that block or complicate an upgrade (prepared transactions, inactive logical replication slots, very long-running transactions), and the extension/statistics work that must follow the upgrade. The upgrade itself is an AWS control-plane action; everything a DBA can verify beforehand and afterward from SQL lives here.",
    symptoms=["An Aurora minor version has been released (or AWS has scheduled an automatic minor version upgrade during the next maintenance window) and nobody has verified the cluster is in a state where it can be upgraded cleanly.", "A previous minor version upgrade took far longer than the expected downtime window, or rolled back, and nobody established why beforehand.", "Query plans regressed immediately after a previous engine upgrade because planner statistics were never refreshed afterward."],
    business_impact=["A minor version upgrade reboots every instance in the cluster: for a trading platform that means order placement, deposits, and withdrawals are interrupted for the duration -- an upgrade started without checking for blockers can extend that interruption from a predictable minute or two into an unbounded incident.", "Minor versions carry security fixes; staying on an unpatched minor version indefinitely is itself a compliance and security exposure for a regulated exchange, so 'never upgrade' is not a safe default.", "Post-upgrade plan regressions on the order-matching and ledger hot paths look identical to a performance incident, but are entirely preventable by a planned post-upgrade statistics refresh."],
    root_causes=["An open prepared (two-phase) transaction pins resources and is a well-known upgrade and vacuum blocker -- an abandoned prepared transaction from a settlement or ledger job that crashed mid-commit is the usual culprit.", "An inactive logical replication slot (a stopped AWS DMS task, a decommissioned CDC consumer) retains WAL and complicates both the upgrade and the cluster's storage footprint.", "Long-running analytical or reporting transactions spanning the intended upgrade window turn a short reboot into a long recovery.", "Planner statistics are not automatically re-collected by an engine upgrade, so a planner change in the new minor version meets stale statistics on the first post-upgrade query."],
    investigation_strategy=["Record exactly what engine version is running now, from inside the database, so the upgrade's before/after state is documented rather than assumed from the AWS Console alone.", "Check for in-database upgrade blockers: prepared transactions, replication slots (especially inactive ones), and long-running transactions.", "Inventory installed extensions, since some require an ALTER EXTENSION ... UPDATE after the engine moves to a new minor version before their newest behavior is available.", "Plan the post-upgrade statistics refresh and validation before starting, not after a regression appears."],
    prerequisites=["pg_monitor role membership for the read-only scripts; IAM permission to modify the DB cluster for the upgrade itself; an agreed maintenance window; a recent, verified backup (see disaster-recovery/backup-and-restore-validation) before any engine change."],
    interpretation_guide=["Any row from the prepared-transactions check is a hard blocker to resolve before the upgrade, not a warning to note and proceed past -- a prepared transaction that has been open for days is almost certainly abandoned, but it must still be explicitly committed or rolled back by its owner rather than silently discarded.", "An inactive replication slot (active = false) with a large retained WAL figure is both an upgrade complication and an ongoing storage cost; decide deliberately whether its consumer is coming back before the window, since dropping a slot a live consumer still needs forces that consumer to re-seed from scratch.", "A long-running transaction that will still be open when the window starts does not prevent the upgrade -- the reboot will terminate it -- but it does mean whatever business process owns it (an end-of-day reconciliation, a large archival batch) will fail mid-flight, so coordinate rather than surprise it.", "The absence of blockers is not the same as readiness: a verified recent backup and a rehearsed rollback position (see disaster-recovery/point-in-time-recovery-drill) are part of readiness too."],
    remediation_immediate=["N/A -- this is planned maintenance. If a blocker is found, resolving the blocker is the work; the upgrade waits."],
    remediation_short_term=["Clear each blocker found (have the owning service commit or roll back its prepared transaction, retire or restart the consumer behind an inactive slot, reschedule the long-running batch outside the window), then re-run the readiness scripts immediately before the window opens rather than relying on a check from days earlier."],
    remediation_long_term=["Adopt a standing minor-version cadence (upgrade within a defined number of weeks of release) so the cluster never accumulates a large version gap, and wire the readiness scripts into the pre-maintenance pipeline (see automation/health-checks) so the check is automatic rather than remembered."],
    production_safety=["Every SQL script in this workflow is strictly read-only and safe to run at any time, including immediately before the window.", "The upgrade itself is an AWS control-plane action, not a SQL statement: it reboots every instance in the cluster and interrupts every connection. The post-upgrade statistics refresh is a real database operation documented as a guarded runbook.", "Never start an engine upgrade without a verified, restorable backup and a documented decision about how far back a point-in-time restore would have to go if the upgrade goes badly."],
    escalation_criteria=["A prepared transaction exists whose owning application/team cannot be identified before the window -- escalate rather than guessing, since rolling back a settlement or ledger two-phase transaction blindly can leave the exchange's books inconsistent with an external counterparty.", "The cluster is several minor versions behind and the accumulated change set can no longer be reviewed as a routine patch bump -- escalate for a scheduled, separately-tested upgrade rather than treating it as routine maintenance."],
    related_issues=["../parameter-group-change-management/README.md", "../extension-upgrade-planning/README.md", "../planned-maintenance-window-checklist/README.md", "../../disaster-recovery/backup-and-restore-validation/README.md", "../../transactions-and-xid/xid-wraparound-risk/README.md"],
    aurora_notes=["Aurora PostgreSQL minor version upgrades are applied to the whole cluster and reboot every instance; because all instances share the same distributed storage volume, there is no per-instance data copy, but there is still a real, connection-terminating interruption. AWS can also apply minor versions automatically during the maintenance window when auto minor version upgrade is enabled -- which means an 'unplanned' upgrade can arrive on AWS's schedule rather than yours, so readiness should be a standing state, not a one-off pre-window exercise.", "Aurora exposes its own engine build via the aurora_version() function in addition to the community version() string; both should be recorded before and after an upgrade, since the community major.minor can stay the same across an Aurora-specific patch level."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_current_engine_version_inventory", "Records the exact community and Aurora engine version this cluster is running, as the documented before-state for the upgrade.",
               """
-- Community PostgreSQL version identity. server_version_num is the reliable
-- machine-comparable form (e.g. 170007 for 17.7); the version() string also
-- records the build/platform details.
SELECT
    current_setting('server_version')                            AS server_version,
    current_setting('server_version_num')                        AS server_version_num,
    version()                                                    AS full_version_string;

-- Aurora exposes an additional, Aurora-specific engine build identifier via
-- aurora_version(). It does not exist on community PostgreSQL, so detect it
-- from the catalog first rather than calling it unconditionally (a bare call
-- would fail with "function aurora_version() does not exist" on any
-- non-Aurora instance, including a local test database).
SELECT EXISTS (
    SELECT 1 FROM pg_proc WHERE proname = 'aurora_version'
)                                                                AS is_aurora
\\gset

\\if :is_aurora
SELECT aurora_version()                                          AS aurora_engine_version;
\\else
SELECT 'aurora_version() is not present on this server, so this is community PostgreSQL rather than Aurora PostgreSQL. The community version reported above is the only engine identity available here.' AS notice;
\\endif
""".strip("\n"),
               "Save this output verbatim in the change ticket before the window opens, and re-run it immediately afterward: the pair of before/after results is the only in-database proof the upgrade actually applied. Note that an Aurora patch-level upgrade can change aurora_engine_version while leaving server_version unchanged -- comparing only the community version can make a real upgrade look like a no-op.",
               related_scripts="02_upgrade_blockers_precheck.sql"),
    sql_script("02", "02_upgrade_blockers_precheck", "Checks the three in-database conditions that most often block or complicate an engine upgrade: prepared transactions, replication slots, and long-running transactions.",
               sb.prepared_transactions() + "\n\n" + sb.replication_slots_status() + "\n\n" + sb.long_running_transactions(),
               "Treat any prepared transaction as a hard blocker: it must be committed or rolled back by its owning service before the window (see transactions-and-xid/prepared-transactions). An inactive replication slot is a decision to make deliberately before the window rather than during it -- a stopped DMS task or retired CDC consumer should be retired properly, and a slot whose consumer is genuinely returning should be left alone and its WAL retention accounted for. A long-running transaction still open when the window starts will simply be terminated by the reboot, so the question is which business process loses its work, not whether the upgrade can proceed.",
               execution_location=WRITER_ONLY,
               related_scripts="03_extension_and_settings_upgrade_surface.sql"),
    sql_script("03", "03_extension_and_settings_upgrade_surface", "Inventories installed extensions and the operationally significant settings, so post-upgrade drift and extension updates can be identified against a recorded baseline.",
               sb.extension_inventory() + "\n\n" + sb.available_extensions_check() + "\n\n" + sb.key_settings_snapshot(),
               "An engine upgrade moves the available default_version of bundled extensions forward but does not update an already-installed extension in place -- after the upgrade, an extension can remain on its old version until ALTER EXTENSION ... UPDATE is run (see maintenance/extension-upgrade-planning). Record the installed versions here so that post-upgrade comparison is a lookup rather than a guess. The key-settings snapshot serves the same purpose for configuration: an upgrade that also moves the cluster to a new default parameter group family can silently change a default, and this baseline is what makes that visible.",
               related_scripts="04_minor_version_upgrade_runbook.md"),
    md_script("04", "04_minor_version_upgrade_runbook", "AWS-side guidance for executing the minor version upgrade itself, including the blue/green alternative for minimizing the interruption.",
              (
                  "This file documents an AWS control-plane procedure. Nothing here is executed against "
                  "the database by this repository, and none of it is a SQL statement -- an Aurora "
                  "engine upgrade cannot be triggered from inside PostgreSQL.\n\n"
                  "## Before the window\n\n"
                  "1. Run `01_current_engine_version_inventory.sql`, `02_upgrade_blockers_precheck.sql`, "
                  "and `03_extension_and_settings_upgrade_surface.sql`, and attach their output to the "
                  "change ticket.\n"
                  "2. Confirm a recent backup is genuinely restorable -- not merely that a snapshot "
                  "exists (see `disaster-recovery/backup-and-restore-validation`).\n"
                  "3. Confirm the target version is available for this cluster:\n\n"
                  "```\n"
                  "aws rds describe-db-engine-versions \\\n"
                  "  --engine aurora-postgresql \\\n"
                  "  --engine-version <current-engine-version> \\\n"
                  "  --query \"DBEngineVersions[].ValidUpgradeTarget[].[EngineVersion,IsMajorVersionUpgrade]\"\n"
                  "```\n\n"
                  "4. Read the AWS release notes for every version between the current one and the "
                  "target, not just the target's own notes.\n\n"
                  "## Option A: in-place upgrade (simplest, reboots the cluster)\n\n"
                  "```\n"
                  "aws rds modify-db-cluster \\\n"
                  "  --db-cluster-identifier <cluster-identifier> \\\n"
                  "  --engine-version <target-engine-version> \\\n"
                  "  --apply-immediately\n"
                  "```\n\n"
                  "Omit `--apply-immediately` to defer the change to the cluster's next scheduled "
                  "maintenance window. Every instance is rebooted and every connection is terminated; "
                  "applications must reconnect exactly as they would during a failover, which is why "
                  "`disaster-recovery/cluster-failover-drill` is the best rehearsal for this "
                  "interruption.\n\n"
                  "## Option B: blue/green deployment (shorter interruption, more setup)\n\n"
                  "An RDS blue/green deployment creates a synchronized green environment already "
                  "running the target engine version, letting you validate it before a switchover that "
                  "is typically far shorter than an in-place upgrade's reboot:\n\n"
                  "```\n"
                  "aws rds create-blue-green-deployment \\\n"
                  "  --blue-green-deployment-name <deployment-name> \\\n"
                  "  --source <source-cluster-arn> \\\n"
                  "  --target-engine-version <target-engine-version>\n"
                  "```\n\n"
                  "Validate the green environment (run this workflow's scripts 01 and 03 against it, "
                  "plus the relevant application smoke tests) and only then switch over:\n\n"
                  "```\n"
                  "aws rds switchover-blue-green-deployment \\\n"
                  "  --blue-green-deployment-identifier <deployment-identifier> \\\n"
                  "  --switchover-timeout 300\n"
                  "```\n\n"
                  "For an exchange where order entry and withdrawal processing cannot absorb a "
                  "multi-minute reboot during active trading hours, the extra setup cost of blue/green "
                  "usually pays for itself in interruption length alone.\n\n"
                  "## Disable surprise upgrades while you are planning\n\n"
                  "If auto minor version upgrade is enabled, AWS may apply a minor version during the "
                  "maintenance window on its own schedule. Decide deliberately which behavior you "
                  "want; check it with:\n\n"
                  "```\n"
                  "aws rds describe-db-instances \\\n"
                  "  --db-instance-identifier <instance-identifier> \\\n"
                  "  --query \"DBInstances[].AutoMinorVersionUpgrade\"\n"
                  "```\n\n"
                  "## Immediately after the switchover or reboot\n\n"
                  "Re-run script 01 to confirm the new version, then follow "
                  "`05_post_upgrade_validation_runbook.md` for the statistics refresh and extension "
                  "updates -- an upgrade is not finished at the moment the cluster accepts connections "
                  "again.\n"
              ),
              "Choose between in-place and blue/green on the basis of how long the platform can actually be down, not on setup convenience -- and treat the AWS release notes for every intermediate version as required reading, since the minor version gap is where behavior changes accumulate.",
              safety="INFORMATIONAL -- NO SQL EXECUTED, AWS CONSOLE/API GUIDANCE ONLY",
              expected_impact="None from this file itself. The described in-place upgrade reboots every instance and terminates every connection; the blue/green switchover interrupts connections for a much shorter, bounded period.",
              required_privileges="IAM permission for rds:ModifyDBCluster, rds:DescribeDBEngineVersions, and (for blue/green) rds:CreateBlueGreenDeployment and rds:SwitchoverBlueGreenDeployment. No PostgreSQL role is used to trigger the upgrade.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Typically several minutes for an in-place cluster reboot; blue/green setup takes longer overall but shortens the actual interruption.",
              related_scripts="01_current_engine_version_inventory.sql, 05_post_upgrade_validation_runbook.md, ../../disaster-recovery/cluster-failover-drill/README.md"),
    md_script("05", "05_post_upgrade_validation_runbook", "Guarded runbook for the database-side work an engine upgrade does not do for you: extension updates, planner statistics refresh, and post-upgrade validation.",
              (
                  "An engine upgrade does not refresh planner statistics and does not update installed "
                  "extensions. Both are real database operations and belong here rather than in an "
                  "auto-running script.\n\n"
                  "## 1. Confirm the upgrade actually applied\n\n"
                  "Re-run `01_current_engine_version_inventory.sql` and compare against the "
                  "pre-upgrade output in the change ticket. Re-run "
                  "`03_extension_and_settings_upgrade_surface.sql` and diff the key settings against "
                  "the pre-upgrade baseline -- an unexplained default change is a finding to chase "
                  "now, not after it causes a regression.\n\n"
                  "## 2. Refresh planner statistics\n\n"
                  "Statistics survive a minor version upgrade, but a planner change meeting stale "
                  "statistics is the single most common cause of a post-upgrade plan regression. "
                  "Refresh the busiest tables first, one at a time, watching load between each:\n\n"
                  "```sql\n"
                  "ANALYZE VERBOSE public.orders;\n"
                  "ANALYZE VERBOSE public.trades;\n"
                  "ANALYZE VERBOSE public.ledger_entries;\n"
                  "```\n\n"
                  "Replace these with the actual hot tables on this cluster (rank them with "
                  "`maintenance/statistics-maintenance` script 01). `ANALYZE` takes only a "
                  "SHARE UPDATE EXCLUSIVE lock, so ordinary reads and writes continue -- but it is "
                  "real I/O, so sequence it rather than launching it across every table at once on a "
                  "cluster still absorbing reconnect traffic.\n\n"
                  "A whole-database `ANALYZE;` is acceptable on a small cluster and a poor idea on a "
                  "large one during a reconnect storm; prefer the ranked, table-at-a-time form here.\n\n"
                  "## 3. Update extensions that moved forward\n\n"
                  "Compare script 03's post-upgrade output against the pre-upgrade baseline. Where an "
                  "extension has a newer default_version available, follow "
                  "`maintenance/extension-upgrade-planning` -- its runbook covers classifying the "
                  "version jump before applying:\n\n"
                  "```sql\n"
                  "ALTER EXTENSION pg_stat_statements UPDATE;\n"
                  "```\n\n"
                  "## 4. Reset query statistics for a clean post-upgrade baseline\n\n"
                  "Where `pg_stat_statements` is installed, the pre-upgrade accumulated statistics "
                  "mix old-planner and new-planner executions, which makes a post-upgrade regression "
                  "hunt harder, not easier. Resetting gives a clean comparison baseline -- but it "
                  "also discards history that other investigations may still need, so agree the "
                  "trade-off before running it:\n\n"
                  "```sql\n"
                  "SELECT pg_stat_statements_reset();\n"
                  "```\n\n"
                  "## 5. Validate before declaring the window closed\n\n"
                  "1. Run `database-health/post-maintenance-check`.\n"
                  "2. Run `maintenance/planned-maintenance-window-checklist` script 05 for the "
                  "post-window verification queries.\n"
                  "3. Watch the top queries by mean time for the first full trading session after the "
                  "upgrade (`query-optimization/query-regression`) -- a regression that only appears "
                  "under real order-book load will not show up in a smoke test.\n\n"
                  "## Rollback position\n\n"
                  "There is no in-place downgrade for an engine version. The rollback path is a "
                  "restore (snapshot or point-in-time) to just before the upgrade, which loses "
                  "everything committed since -- which is exactly why the backup verification step in "
                  "script 04's pre-window checklist is not optional. For a blue/green upgrade, the "
                  "blue environment remains available until you delete it, which is a materially "
                  "better rollback position and another argument for that option.\n"
              ),
              "Work through the numbered steps in order after the cluster is accepting connections again; the statistics refresh in step 2 is the step most often skipped and the one most often responsible for a post-upgrade performance incident.",
              safety="LOW RISK WRITE (ANALYZE and ALTER EXTENSION ... UPDATE; SHARE UPDATE EXCLUSIVE locks only, no table rewrite -- see runbook before running any step)",
              expected_impact="Real I/O and CPU for the duration of each ANALYZE; a brief lock on extension-owned objects during ALTER EXTENSION ... UPDATE; pg_stat_statements_reset() permanently discards accumulated query statistics.",
              required_privileges=TABLE_OWNER_OR_DDL,
              execution_location=WRITER_ONLY,
              expected_runtime="Minutes, dominated by the ANALYZE of the largest hot tables.",
              related_scripts="01_current_engine_version_inventory.sql, 03_extension_and_settings_upgrade_surface.sql, ../statistics-maintenance/README.md"),
]

# ---------------------------------------------------------------------------
# statistics-maintenance
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="statistics-maintenance",
    title="Planner Statistics Maintenance",
    summary="The standing maintenance workflow for planner statistics: which tables are drifting away from their last ANALYZE, whether per-table autovacuum/analyze settings are tuned for the tables that actually need it, and whether columns on the hot trading paths need a raised statistics target or an extended (multi-column) statistics object. This is the preventive counterpart to the reactive stale-statistics investigation in query-optimization.",
    symptoms=["Plans flip between good and bad for the same query shape with no code change, typically after a large batch load into an orders, trades, or ledger table.", "The routine maintenance checklist keeps flagging the same tables as having a large n_mod_since_analyze relative to their row count.", "The planner's row estimates are wildly wrong for queries filtering on two correlated columns (for example, market symbol and side, or currency and account type)."],
    business_impact=["Stale statistics on the order-matching and balance-lookup paths produce plans that are orders of magnitude slower than the correct plan -- the same query that normally serves an order book in milliseconds can start sequentially scanning a multi-hundred-million-row trades table during peak volatility.", "Statistics problems are the cheapest class of performance problem to prevent and one of the most expensive to diagnose during a live incident, because the query text and the schema both look unchanged.", "Correlated-column misestimates on compliance and reporting queries cause them to overrun their windows, delaying regulatory reporting."],
    root_causes=["Default autovacuum_analyze_scale_factor (0.1) means a very large table must accumulate 10% modified rows before autoanalyze triggers -- on a 500 million row trades table that is 50 million rows of drift, which is far too much for time-series-skewed data.", "Bulk loads and large archival deletes change a table's distribution far faster than autoanalyze reacts, leaving a window where plans are chosen from a distribution that no longer exists.", "The default statistics target (100) is too coarse for highly skewed columns -- a handful of dominant trading pairs plus a long tail of thin markets is exactly the distribution that a small histogram represents badly.", "PostgreSQL assumes column independence without an extended statistics object, so correlated predicates multiply selectivities and produce estimates far below reality.", "Per-table storage parameters set years ago for a table that has since grown by two orders of magnitude are no longer appropriate but nobody revisits them."],
    investigation_strategy=["Rank tables by how far they have drifted since their last analyze, weighted by how large and how hot they are.", "Check which tables already carry per-table autovacuum/analyze storage parameter overrides, and whether those overrides still match the table's current size and churn.", "Check for non-default per-column statistics targets and for existing extended statistics objects, so tuning builds on what is there rather than duplicating it.", "Tie each finding to a specific query or plan problem where possible -- raising a statistics target everywhere costs planning time on every query, so it should be targeted."],
    prerequisites=["pg_monitor role membership for the read-only scripts; table ownership (or pg_maintain membership) to apply any ANALYZE, statistics target change, or extended statistics object."],
    interpretation_guide=["n_mod_since_analyze compared against the table's live row count is the real drift signal; a raw modification count is meaningless without that ratio. A 2% drift on a 500 million row table can matter more than a 50% drift on a 10,000 row lookup table, because the absolute number of rows the planner is now wrong about is far larger.", "last_autoanalyze being NULL on a large, actively written table is a strong signal that autoanalyze has never successfully completed there -- check autovacuum worker saturation (vacuum-and-autovacuum/autovacuum-not-keeping-up) rather than assuming the thresholds are the problem.", "A per-table override that sets autovacuum_analyze_scale_factor to a small value (0.01 or lower) on a huge table is usually correct and deliberate; the same override on a small table just burns autovacuum worker cycles for no benefit.", "An existing extended statistics object only helps if it has actually been analyzed -- creating it is not enough, the next ANALYZE on the table is what populates it.", "Raising a column's statistics target increases both ANALYZE cost and per-query planning time. Target it at the specific skewed columns real plans are getting wrong, not at every column on the table."],
    remediation_immediate=["If a plan regression is live right now, a targeted ANALYZE of the affected table is the fastest safe corrective action -- see query-optimization/stale-statistics for the incident path; this workflow is about not getting there again."],
    remediation_short_term=["Run a targeted ANALYZE on the drifted tables identified by script 01, and set per-table autovacuum_analyze_scale_factor overrides on the largest, highest-churn tables so autoanalyze triggers on a sensible absolute row count rather than a percentage of an enormous table."],
    remediation_long_term=["Make a post-bulk-load ANALYZE a mandatory step in every batch/ETL and archival job rather than leaving the refresh to autoanalyze's schedule.", "Add extended statistics objects for the correlated column pairs that recur in the platform's hot query shapes, and review them whenever those query shapes change.", "Re-review per-table statistics settings whenever a table crosses an order-of-magnitude growth boundary, as part of the routine maintenance checklist."],
    production_safety=["Every SQL script in this workflow is strictly read-only.", "ANALYZE takes a SHARE UPDATE EXCLUSIVE lock: ordinary reads and writes continue, but it conflicts with other maintenance operations (VACUUM, another ANALYZE, DDL) on the same table, and it is real I/O on a large table.", "Setting a statistics target or creating an extended statistics object is DDL requiring a brief ACCESS EXCLUSIVE (SHARE UPDATE EXCLUSIVE for CREATE STATISTICS) lock, and neither takes effect until the next ANALYZE of the table."],
    escalation_criteria=["A table shows extreme drift and its last_autoanalyze is NULL or very old despite autovacuum being enabled -- this is an autovacuum capacity problem, not a statistics problem, and belongs with vacuum-and-autovacuum/autovacuum-not-keeping-up.", "A plan regression persists on the hot trading path immediately after a successful targeted ANALYZE -- statistics are not the cause; escalate to query-optimization/query-regression."],
    related_issues=["../routine-maintenance-checklist/README.md", "../minor-version-upgrade-readiness/README.md", "../../vacuum-and-autovacuum/table-bloat/README.md", "../../tables-and-indexes/large-tables/README.md", "../../database-health/comprehensive-health-check/README.md"],
    aurora_notes=["Autovacuum and autoanalyze thresholds on Aurora are controlled through the DB cluster parameter group rather than postgresql.conf (see maintenance/parameter-group-change-management), but per-table storage parameter overrides are ordinary PostgreSQL DDL and work exactly as they do in community PostgreSQL -- which makes per-table overrides the more precise tool for a handful of very large tables, since they need no parameter-group change or reboot."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_statistics_drift_ranking", "Ranks tables by how far their contents have drifted since the last ANALYZE, which is the primary input to every other decision in this workflow.",
               sb.statistics_freshness(),
               "Work top-down, but read the ratio rather than the raw count: the tables worth acting on are the large, actively written ones (orders, trades, ledger entries, deposit/withdrawal events) whose modified-row count is large in absolute terms, not the small lookup tables that can show an alarming percentage from a handful of rows. A NULL last_autoanalyze on a large, busy table means autoanalyze has never completed there -- that is an autovacuum capacity finding, not a threshold-tuning one.",
               related_scripts="02_per_table_autovacuum_and_analyze_settings.sql"),
    sql_script("02", "02_per_table_autovacuum_and_analyze_settings", "Shows which tables already carry per-table autovacuum/analyze storage parameter overrides, alongside their current size and churn, so tuning decisions build on what is already configured.",
               """
-- Per-table storage parameter overrides (reloptions) alongside size and
-- churn. A table with no reloptions simply inherits the cluster-wide
-- autovacuum/autoanalyze settings from the DB cluster parameter group.
-- reloptions is a text[] of 'key=value' entries; it is displayed as-is
-- rather than parsed, so an unexpected or obsolete override is visible
-- exactly as it was set.
\\set top_n 50
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    pg_size_pretty(pg_total_relation_size(c.oid))                AS total_size,
    c.reltuples::bigint                                          AS estimated_rows,
    c.reloptions                                                 AS per_table_overrides,
    s.n_live_tup,
    s.n_mod_since_analyze,
    round(
        100.0 * s.n_mod_since_analyze / NULLIF(s.n_live_tup, 0), 2
    )                                                            AS pct_modified_since_analyze,
    s.last_analyze,
    s.last_autoanalyze
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_all_tables s ON s.relid = c.oid
WHERE c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT :top_n;
""".strip("\n"),
               "Read this as size-ranked rather than problem-ranked: the question for each of the largest tables is whether per_table_overrides is NULL when it should not be. A 500 million row trades table inheriting the default analyze scale factor of 0.1 needs 50 million modified rows before autoanalyze fires, which is almost never the behavior you want on a time-series-skewed table. Conversely, an override present on a now-small table (a partition that has aged out, a table that was archived down) is stale configuration worth removing so autovacuum workers are not woken up for no reason.",
               related_scripts="03_column_targets_and_extended_statistics.sql"),
    sql_script("03", "03_column_targets_and_extended_statistics", "Lists non-default per-column statistics targets and every extended (multi-column) statistics object, so correlated-column tuning is visible and not duplicated.",
               """
-- Columns with a non-default statistics target. In PostgreSQL 17
-- attstattarget is NULL when the column simply inherits the
-- default_statistics_target GUC (older releases stored -1 for the same
-- meaning), so filtering on attstattarget >= 0 returns only deliberate
-- (or long-forgotten) per-column overrides under either convention.
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    a.attname                                                    AS column_name,
    a.attstattarget                                              AS column_statistics_target,
    (SELECT setting::int FROM pg_settings WHERE name = 'default_statistics_target')
                                                                 AS cluster_default_target
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE a.attnum > 0
  AND NOT a.attisdropped
  AND a.attstattarget >= 0
  AND c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY a.attstattarget DESC, n.nspname, c.relname, a.attname;

-- Extended statistics objects: these are how the planner learns that two
-- columns are correlated (ndistinct / dependencies) or how often specific
-- value combinations occur (mcv). Use the permission-filtered pg_stats_ext
-- view for populated data rather than pg_statistic_ext_data, which is
-- restricted to elevated roles on Aurora PostgreSQL. A NULL data column can
-- therefore mean either that ANALYZE has not populated the object yet or that
-- the current role cannot inspect the underlying table.
SELECT
    sn.nspname                                                   AS statistics_schema,
    s.stxname                                                    AS statistics_name,
    tn.nspname                                                   AS table_schema,
    t.relname                                                    AS table_name,
    s.stxkind                                                    AS kinds,
    (e.n_distinct IS NOT NULL)                                   AS ndistinct_visible,
    (e.dependencies IS NOT NULL)                                 AS dependencies_visible,
    (e.most_common_vals IS NOT NULL)                             AS mcv_visible,
    CASE
        WHEN e.statistics_name IS NULL THEN
            'statistics data not populated or not visible to current role'
        ELSE 'statistics data visible'
    END                                                          AS visibility_status
FROM pg_statistic_ext s
JOIN pg_class t ON t.oid = s.stxrelid
JOIN pg_namespace tn ON tn.oid = t.relnamespace
JOIN pg_namespace sn ON sn.oid = s.stxnamespace
LEFT JOIN pg_stats_ext e
       ON e.statistics_schemaname = sn.nspname
      AND e.statistics_name = s.stxname
ORDER BY tn.nspname, t.relname, s.stxname;
""".strip("\n"),
               "An empty first result means every column is using the cluster default target, which is the normal starting state -- it is a finding only for tables whose plans are known to be wrong on a skewed column (a symbol or market column where a few pairs carry most of the volume). An empty second result means the planner is assuming every column is statistically independent everywhere, which is where correlated-predicate underestimates come from. A visibility_status warning means either ANALYZE has not populated the object or the current role lacks SELECT privilege on the underlying table; verify privileges before concluding the object is stale. Do not create extended statistics speculatively across every column pair -- each one adds ANALYZE cost, so add them for the specific correlated predicates that appear in real slow plans.",
               related_scripts="04_statistics_maintenance_runbook.md"),
    md_script("04", "04_statistics_maintenance_runbook", "Guarded runbook for applying the statistics maintenance actions this workflow identifies: targeted ANALYZE, per-table thresholds, statistics targets, and extended statistics.",
              (
                  "Every statement in this runbook is a real database operation. Read the lock and cost "
                  "notes for each step before running it, and apply one change at a time so the effect "
                  "of each is measurable.\n\n"
                  "## 1. Targeted ANALYZE (start here)\n\n"
                  "```sql\n"
                  "ANALYZE VERBOSE public.trades;\n"
                  "```\n\n"
                  "Replace with the actual drifted table from script 01. `ANALYZE` takes a "
                  "SHARE UPDATE EXCLUSIVE lock -- ordinary reads and writes continue, but it conflicts "
                  "with VACUUM, another ANALYZE, and DDL on the same table. On a very large table this "
                  "is real, sustained I/O, so run it off-peak and one table at a time.\n\n"
                  "Rollback: none needed, and none possible -- an ANALYZE only replaces statistics with "
                  "more current statistics. The 'risk' of running it is the I/O it consumes, not the "
                  "result.\n\n"
                  "## 2. Per-table autoanalyze thresholds for very large tables\n\n"
                  "```sql\n"
                  "ALTER TABLE public.trades SET (\n"
                  "    autovacuum_analyze_scale_factor = 0.01,\n"
                  "    autovacuum_analyze_threshold    = 50000\n"
                  ");\n"
                  "```\n\n"
                  "This makes autoanalyze fire after roughly 1% of the table plus 50,000 rows have "
                  "changed, instead of the default 10%. `ALTER TABLE ... SET (...)` for storage "
                  "parameters takes a brief SHARE UPDATE EXCLUSIVE lock -- it does not rewrite the "
                  "table and completes in milliseconds -- but it will queue behind a long-running "
                  "transaction holding a conflicting lock, so use a `lock_timeout` to avoid parking a "
                  "lock request in front of production traffic:\n\n"
                  "```sql\n"
                  "SET lock_timeout = '5s';\n"
                  "```\n\n"
                  "Rollback: `ALTER TABLE public.trades RESET (autovacuum_analyze_scale_factor, "
                  "autovacuum_analyze_threshold);` returns the table to the cluster-wide defaults.\n\n"
                  "## 3. Raise the statistics target on a specific skewed column\n\n"
                  "```sql\n"
                  "ALTER TABLE public.trades ALTER COLUMN market_symbol SET STATISTICS 500;\n"
                  "ANALYZE public.trades;\n"
                  "```\n\n"
                  "The new target does nothing until the following ANALYZE runs. Higher targets cost "
                  "more ANALYZE time and more planning time on every query touching that column, so "
                  "raise it for columns whose skew is actually producing bad estimates -- typically a "
                  "market/symbol, currency, or status column where a few values dominate and a long "
                  "tail is thin. This is DDL on the table and takes an ACCESS EXCLUSIVE lock briefly; "
                  "keep `lock_timeout` set.\n\n"
                  "Rollback: `ALTER TABLE public.trades ALTER COLUMN market_symbol SET STATISTICS "
                  "DEFAULT;` restores the cluster-wide default_statistics_target (PostgreSQL 17 "
                  "accepts the older `SET STATISTICS -1` spelling for the same effect).\n\n"
                  "## 4. Extended statistics for correlated columns\n\n"
                  "```sql\n"
                  "CREATE STATISTICS trades_symbol_side_stats (ndistinct, dependencies, mcv)\n"
                  "    ON market_symbol, side\n"
                  "    FROM public.trades;\n"
                  "ANALYZE public.trades;\n"
                  "```\n\n"
                  "Use this where the planner underestimates a predicate on two columns that are not "
                  "independent in practice (symbol and side, currency and account type, status and "
                  "created-date range). `CREATE STATISTICS` takes a SHARE UPDATE EXCLUSIVE lock and "
                  "the object stays empty until the next ANALYZE populates it -- verify with script 03 "
                  "that the populated flags flipped to true.\n\n"
                  "Rollback: `DROP STATISTICS trades_symbol_side_stats;`\n\n"
                  "## 5. Make post-load ANALYZE part of the job, not an afterthought\n\n"
                  "Any batch load, backfill, or large archival delete should end with an ANALYZE of "
                  "the affected table inside the same job. This is the single highest-value change in "
                  "this runbook, because it removes the window in which plans are chosen from a "
                  "distribution that no longer exists.\n\n"
                  "## Verify\n\n"
                  "Re-run scripts 01 and 03 after each change, and confirm the specific query whose "
                  "plan motivated the change now estimates rows sensibly (compare the estimate against "
                  "actual rows using `query-optimization`'s plan-analysis workflows). A statistics "
                  "change that does not move a real plan estimate was not worth its ongoing ANALYZE "
                  "cost.\n"
              ),
              "Apply one change at a time and verify its effect on a real plan before the next -- statistics tuning applied in bulk is impossible to attribute, and every raised target and extended statistics object carries an ongoing ANALYZE and planning cost.",
              safety="LOW RISK WRITE (ANALYZE and statistics DDL; SHARE UPDATE EXCLUSIVE locks with a brief ACCESS EXCLUSIVE for column-level DDL, no table rewrite -- see per-step notes)",
              expected_impact="Real I/O for the duration of each ANALYZE on a large table; brief lock acquisition for the DDL steps, which can queue behind a long-running transaction if lock_timeout is not set.",
              required_privileges=TABLE_OWNER_OR_DDL,
              execution_location=WRITER_ONLY,
              expected_runtime="Seconds for the DDL steps; minutes to tens of minutes for an ANALYZE of a very large table.",
              related_scripts="01_statistics_drift_ranking.sql, 03_column_targets_and_extended_statistics.sql, ../routine-maintenance-checklist/README.md"),
]

# ---------------------------------------------------------------------------
# planned-maintenance-window-checklist
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="planned-maintenance-window-checklist",
    title="Planned Maintenance Window Checklist",
    summary="The wrapper procedure around any planned, disruptive maintenance on this cluster -- an engine upgrade, a reboot for a static parameter change, a failover drill, an instance class change, or a large schema migration. It defines what to verify before the window opens, what to hold as the go/no-go decision, and what to verify afterward before declaring the window closed and handing the platform back to trading.",
    symptoms=["A disruptive maintenance action is scheduled and the team wants a consistent, repeatable procedure rather than an ad hoc checklist assembled from memory each time.", "A previous window overran or left a change half-applied because a pre-check (a long-running transaction, an in-flight index build, a lagging reader) was not performed beforehand.", "Post-window, nobody could say definitively whether the platform was fully healthy or merely accepting connections again."],
    business_impact=["For an exchange, a maintenance window is a deliberate, scheduled outage of order entry, deposits, and withdrawals -- overrunning it converts planned, communicated downtime into an incident with customer, market-maker, and regulatory consequences.", "A window closed prematurely, before the cluster is genuinely healthy, pushes the real failure into live trading hours where it is far more expensive.", "Consistent pre/post evidence for each window is also the operational audit trail a regulated venue is expected to produce on request."],
    root_causes=["N/A -- this is a procedural workflow. Each specific maintenance action has its own workflow (minor-version-upgrade-readiness, parameter-group-change-management, disaster-recovery/cluster-failover-drill, schema-changes/*); this one wraps whichever of them is being executed."],
    investigation_strategy=["Before the window: confirm the cluster's current activity level, that no long-running transaction or in-flight maintenance operation will be destroyed mid-flight, and that no blocking chain is already in progress.", "Before the window: confirm the topology is what you think it is (which instance is writer), that every reader is healthy and low-lag, and that no replication slot is silently retaining WAL.", "Hold an explicit go/no-go on that evidence rather than proceeding by default.", "After the window: confirm settings, connectivity, topology, and workload health against the pre-window baseline before declaring completion."],
    prerequisites=["pg_monitor role membership for the read-only scripts; an agreed, communicated window; a verified recent backup (disaster-recovery/backup-and-restore-validation); the specific maintenance action's own workflow read in advance."],
    interpretation_guide=["The pre-window scripts are a go/no-go input, not a formality: a transaction that has been open for hours, an index build in progress, or a reader already lagging are each individually sufficient reason to delay a window rather than proceed and discover the consequence mid-change.", "An existing blocking chain before the window means the cluster is already unhealthy; performing disruptive maintenance on top of it makes attribution of whatever happens next nearly impossible.", "Post-window, 'the cluster accepts connections' is not the completion criterion. The criterion is: the expected instance is the writer, settings match intent, connection counts have recovered to a normal shape rather than a reconnect storm, and no new blocking or error pattern has appeared.", "Comparing post-window key settings against the pre-window snapshot is what catches a change that was half-applied (parameter group updated, reboot performed on only some instances) -- see maintenance/parameter-group-change-management."],
    remediation_immediate=["If a pre-window check fails, delay the window. If a post-window check fails, do not hand the platform back -- treat it as an active incident and use the matching incident workflow."],
    remediation_short_term=["Record the pre-window and post-window script output in the change ticket for every window, so the next window starts from evidence rather than memory."],
    remediation_long_term=["Automate the pre- and post-window script runs into the deployment/maintenance pipeline (see automation/health-checks) so the evidence is collected identically every time, and review overrun windows as a trend to find which class of maintenance consistently takes longer than planned."],
    production_safety=["Every SQL script in this workflow is strictly read-only and safe to run during live trading, including immediately before the window opens.", "This workflow performs no maintenance action itself -- the disruptive step always belongs to the specific workflow being wrapped, and its own safety notes govern."],
    escalation_criteria=["Any pre-window check fails and there is pressure to proceed anyway -- escalate the go/no-go decision rather than absorbing it.", "The window's planned duration has elapsed and the change is not complete -- escalate and start the rollback path defined by the specific maintenance action's own workflow rather than extending the window indefinitely."],
    related_issues=["../minor-version-upgrade-readiness/README.md", "../parameter-group-change-management/README.md", "../routine-maintenance-checklist/README.md", "../../disaster-recovery/cluster-failover-drill/README.md", "../../database-health/comprehensive-health-check/README.md"],
    aurora_notes=["On Aurora, most disruptive maintenance ultimately manifests as a reboot or a failover of the writer, and the application-visible behavior is the same in both cases: every connection is reset and the cluster endpoint re-resolves. That means disaster-recovery/cluster-failover-drill is the most useful rehearsal for almost any window in this category, regardless of what is actually being changed."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_pre_window_activity_and_transactions", "Pre-window snapshot of overall activity and of any transaction long-running enough to be destroyed mid-flight by the maintenance action.",
               sb.activity_overview() + "\n\n" + sb.long_running_transactions(),
               "Run this immediately before the window, not hours earlier. Any transaction open longer than the planned window duration will be terminated by a reboot or failover -- identify what owns it (an end-of-day reconciliation, an archival batch, a reporting job) and either let it finish or coordinate its cancellation deliberately. An activity profile far above the expected off-peak baseline is itself a reason to reconsider the timing: maintenance during unexpectedly heavy order flow amplifies every consequence of the interruption.",
               execution_location=WRITER_ONLY,
               related_scripts="02_pre_window_lock_and_blocking_check.sql"),
    sql_script("02", "02_pre_window_lock_and_blocking_check", "Pre-window check for an existing blocking chain or a DDL lock wait already in progress, either of which means the cluster is unhealthy before the maintenance even starts.",
               sb.blocked_sessions() + "\n\n" + sb.ddl_lock_waits(),
               "Both results should be empty before a window opens. A blocking chain already in progress means whatever happens during the window cannot be cleanly attributed to the maintenance action, and a DDL lock wait usually means an earlier migration is still trying to acquire its lock -- proceeding on top of either is how a planned window turns into an incident. If rows appear, resolve them via concurrency-and-locking/blocked-queries first and re-run this script before making the go/no-go call.",
               execution_location=WRITER_ONLY,
               related_scripts="03_pre_window_topology_and_replication_check.sql"),
    sql_script("03", "03_pre_window_topology_and_replication_check", "Pre-window confirmation of which instance is the writer, that every reader is healthy and low-lag, and that no replication slot is silently retaining WAL.",
               sb.cluster_recovery_role() + "\n\n" + sb.aurora_replica_status() + "\n\n" + sb.replication_slots_and_wal_retention(),
               "Confirm the connection you are about to perform maintenance through is actually reaching the instance you believe it is -- is_reader_instance = true when you expect the writer means an earlier, unnoticed failover has already occurred and the window's assumptions are wrong. Every reader should show low, stable lag: performing a reboot or failover while a reader is already behind removes the very redundancy the maintenance depends on. A slot retaining a large amount of WAL, especially an inactive one, should be resolved before the window rather than discovered as a storage problem during it.",
               related_scripts="04_maintenance_window_checklist.md"),
    md_script("04", "04_maintenance_window_checklist", "The checklist itself: the ordered pre-window, go/no-go, in-window, and post-window steps that wrap whichever specific maintenance action is being performed.",
              (
                  "## Before the window (T-minus one day)\n\n"
                  "1. Confirm the specific maintenance action's own workflow has been read and its "
                  "steps are written into the change ticket -- this checklist wraps that workflow, it "
                  "does not replace it.\n"
                  "2. Confirm a recent backup is genuinely restorable, not merely present "
                  "(`disaster-recovery/backup-and-restore-validation`).\n"
                  "3. Confirm the rollback path is written down and someone has read it. For an engine "
                  "upgrade the rollback is a restore, which has a real data-loss cost -- that needs to "
                  "be understood before the window, not discovered during it.\n"
                  "4. Confirm the window is communicated to trading operations, market makers if "
                  "relevant, and customer support, with a stated expected duration.\n\n"
                  "## Immediately before the window opens\n\n"
                  "5. Run `01_pre_window_activity_and_transactions.sql`. Resolve or accept every "
                  "long-running transaction listed.\n"
                  "6. Run `02_pre_window_lock_and_blocking_check.sql`. Both results must be empty.\n"
                  "7. Run `03_pre_window_topology_and_replication_check.sql`. Confirm the writer is "
                  "where you expect, readers are low-lag, and no slot is retaining unexpected WAL.\n"
                  "8. Save all three outputs into the change ticket as the pre-window baseline.\n\n"
                  "## Go / no-go\n\n"
                  "State the decision explicitly, with a named decision-maker. Any of the following is "
                  "a no-go by default, overridable only by an explicit, recorded decision:\n\n"
                  "- A transaction open longer than the planned window duration that nobody owns.\n"
                  "- A blocking chain or DDL lock wait already in progress.\n"
                  "- A reader with elevated lag, or fewer healthy readers than the HA design assumes.\n"
                  "- No verified restorable backup.\n"
                  "- Activity materially above the expected off-peak baseline.\n\n"
                  "## During the window\n\n"
                  "9. Execute the specific maintenance action following its own workflow.\n"
                  "10. Keep a running time log. If the planned duration elapses and the change is not "
                  "complete, escalate and begin the rollback path rather than extending silently.\n\n"
                  "## After the change, before declaring the window closed\n\n"
                  "11. Run `05_post_window_verification.sql` and compare against the pre-window "
                  "baseline: settings should match intent, the writer should be the instance you "
                  "expect, and connection counts should be recovering toward their normal shape.\n"
                  "12. Run `database-health/post-maintenance-check` for the broader health pass.\n"
                  "13. Confirm the application's own smoke tests pass -- order placement, balance "
                  "lookup, deposit and withdrawal paths -- not just that the database accepts "
                  "connections.\n"
                  "14. Watch the first full trading session afterward for plan or latency regressions "
                  "(`query-optimization/query-regression`).\n\n"
                  "## Closing out\n\n"
                  "15. Record in the ticket: actual versus planned duration, anything that deviated "
                  "from the runbook, and any check that should be added to this checklist next time. "
                  "The overrun trend across windows is more valuable than any single window's "
                  "record.\n"
              ),
              "Work the checklist in order and make the go/no-go decision explicit and attributable -- most maintenance windows that become incidents do so because a pre-window signal was visible and proceeded past, not because the maintenance action itself was wrong.",
              safety="DOCUMENTATION -- no SQL executed by this file itself",
              expected_impact="None from this file directly; the wrapped maintenance action carries its own impact, documented in its own workflow.",
              required_privileges="N/A for this file itself; see the specific maintenance action's workflow for its own required privileges.",
              execution_location=ANY_INSTANCE,
              expected_runtime="Minutes for the checklist steps themselves, excluding the wrapped maintenance action.",
              related_scripts="01_pre_window_activity_and_transactions.sql, 02_pre_window_lock_and_blocking_check.sql, 03_pre_window_topology_and_replication_check.sql, 05_post_window_verification.sql"),
    sql_script("05", "05_post_window_verification", "Post-window verification: settings versus intent, writer identity, connection recovery shape, and transaction age -- run before declaring the window closed.",
               sb.key_settings_snapshot() + "\n\n" + sb.cluster_recovery_role() + "\n\n" + sb.connections_by_state() + "\n\n" + sb.database_transaction_age(),
               "Compare the settings block line by line against the pre-window baseline from script 03 of minor-version-upgrade-readiness or script 01 of parameter-group-change-management: any difference that was not the intended change is the finding, and any intended change that is missing means the change is only half-applied (check pending_restart). is_reader_instance must be false on the writer endpoint. A connection profile dominated by idle-in-transaction sessions, or a total count far above baseline, is a reconnect storm or a pool that has not settled -- wait and re-run before closing the window. XID age should be continuous with the pre-window value; a jump is not caused by maintenance and points at a separate problem.",
               execution_location=WRITER_ONLY,
               related_scripts="04_maintenance_window_checklist.md, ../../database-health/comprehensive-health-check/README.md"),
]
