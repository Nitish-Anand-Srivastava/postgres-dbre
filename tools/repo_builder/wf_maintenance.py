"""Workflow definitions: maintenance/ category (4 workflow directories).

This is an OPEN_CATALOG category (see tools/validation/catalog.py) -- there
is no fixed, exact required workflow slug list, only a requirement that the
category directory exists and has at least one workflow. The four workflows
below cover the recurring maintenance checklist, reindex campaign planning,
extension upgrade planning, and Aurora parameter-group change management --
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

