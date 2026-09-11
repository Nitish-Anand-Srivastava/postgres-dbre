"""Workflow definitions: vacuum-and-autovacuum/ category (8 issue directories)."""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import PG_MONITOR, md_script, sql_script
from .model import Workflow

CATEGORY_SLUG = "vacuum-and-autovacuum"
CATEGORY_TITLE = "Vacuum and Autovacuum"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

WORKFLOWS.append(_wf(
    slug="autovacuum-not-keeping-up",
    title="Autovacuum Not Keeping Up",
    summary="Autovacuum is running but dead tuples / table bloat are growing faster than autovacuum can clean them up, degrading query performance and increasing storage over time.",
    symptoms=["n_dead_tup growing steadily across snapshots on one or more hot tables.", "last_autovacuum timestamp falling further and further behind for a specific table.", "Increasing bloat-driven query latency on tables that were previously fast."],
    business_impact=["Unchecked bloat on hot OLTP tables (orders, balances) increases I/O per query and, left long enough, risks an emergency VACUUM disruption and XID wraparound exposure."],
    root_causes=["autovacuum_vacuum_cost_limit / autovacuum_vacuum_cost_delay set too conservatively for the actual write volume.", "Too few autovacuum_max_workers for the number of tables needing attention simultaneously.", "A long-running transaction repeatedly preventing autovacuum from removing dead tuples it has already identified.", "autovacuum_naptime too long relative to the table's churn rate."],
    investigation_strategy=["Rank tables by dead tuple count/ratio to find the worst offenders.", "Check current and historical autovacuum activity/frequency for those tables.", "Check for competing long-running transactions blocking cleanup.", "Review current autovacuum cost/worker configuration."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["A high dead_tuple_pct with a recent last_autovacuum timestamp means autovacuum is running but not keeping pace -- a tuning problem. A high dead_tuple_pct with a stale/NULL last_autovacuum means autovacuum is not running at all on that table -- an investigation-for-blocker problem."],
    remediation_immediate=["If a specific table is critically bloated, issue a manual `VACUUM (VERBOSE, ANALYZE) <table>;` to catch it up immediately."],
    remediation_short_term=["Set a more aggressive per-table autovacuum_vacuum_cost_limit/scale_factor for the specific hot tables identified (via `ALTER TABLE ... SET (autovacuum_vacuum_scale_factor = 0.01)` for very large tables where the default 20% dead-tuple threshold is too high in absolute terms).", "Increase autovacuum_max_workers via the cluster parameter group if many tables need attention concurrently."],
    remediation_long_term=["Consider partitioning extremely large, high-churn tables so each partition is vacuumed independently and more frequently in smaller units (see partitioning/)."],
    production_safety=["Investigation scripts are read-only.", "Manual VACUUM (without FULL) is non-blocking and safe to run concurrently with production traffic."],
    escalation_criteria=["Bloat continues to grow despite tuning changes and manual vacuum -- escalate to database engineering for a schema/partitioning-level fix."],
    related_issues=["../dead-tuples/README.md", "../table-bloat/README.md", "../emergency-autovacuum/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_dead_tuples_ranked", "Ranks tables by dead tuple count and ratio to find the worst autovacuum-lag offenders.",
               sb.dead_tuples_ranked(),
               "A high dead_tuple_pct combined with a recent autovacuum_count increase means autovacuum is active but losing ground; combined with a stale last_autovacuum means it is not running at all.",
               related_scripts="02_current_autovacuum_workers.sql"),
    sql_script("02", "02_current_autovacuum_workers", "Shows currently running autovacuum workers and their progress.",
               sb.autovacuum_workers_active(),
               "Confirm the tables from script 01 have an active worker; if not, check for a blocking transaction (script 03) preventing autovacuum from starting/completing.",
               related_scripts="03_blocking_transactions.sql"),
    sql_script("03", "03_blocking_transactions", "Checks for long-running transactions that could be preventing autovacuum from reclaiming space it has already identified as dead.",
               sb.long_running_transactions(),
               "Any old transaction here can prevent autovacuum from making real progress even while it appears to run continuously -- resolve it per concurrency-and-locking/long-running-transactions.",
               related_scripts="04_autovacuum_configuration.sql"),
    sql_script("04", "04_autovacuum_configuration", "Snapshots current autovacuum cost/worker configuration to assess whether tuning is the root cause.",
               sb.key_settings_snapshot(),
               "Low autovacuum_vacuum_cost_limit combined with high autovacuum_vacuum_cost_delay throttles autovacuum heavily -- appropriate for shared/small instances, often too conservative for a high-throughput exchange workload.",
               related_scripts="../../vacuum-and-autovacuum/vacuum-progress/README.md"),
]

WORKFLOWS.append(_wf(
    slug="vacuum-progress",
    title="Vacuum Progress Monitoring",
    summary="Tracks the real-time progress of an in-flight VACUUM (manual or autovacuum) operation, to answer 'how much longer will this take' and 'is it stuck'.",
    symptoms=["A known VACUUM is running and its completion time/impact needs to be estimated.", "Uncertainty about whether a long-running vacuum is stuck or genuinely making progress."],
    business_impact=["Understanding vacuum progress lets the DBA make an informed decision about whether to let it continue, especially when the vacuum itself is competing for I/O with production traffic."],
    root_causes=["N/A -- this is a monitoring workflow for an already-running vacuum, not a root-cause investigation."],
    investigation_strategy=["Query pg_stat_progress_vacuum for the specific relation.", "Interpret phase and the PG17 byte-based dead-tuple counters to estimate remaining work.", "Re-run periodically to confirm heap_blks_scanned is advancing (not stalled)."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["heap_blks_scanned advancing between two snapshots confirms the vacuum is making progress, even if slowly. A phase stuck at 'vacuuming indexes' for a long time on a table with many/large indexes is expected, not necessarily stuck."],
    remediation_immediate=["None required if progressing normally; if genuinely stalled (heap_blks_scanned not advancing across several checks and no visible wait_event explaining why), investigate for an internal lock conflict."],
    remediation_short_term=["Consider `VACUUM (PARALLEL n)` behavior is automatic for index vacuuming when the table has multiple indexes and maintenance_work_mem permits -- no manual action normally needed."],
    remediation_long_term=["If vacuum on this table routinely takes an inconvenient amount of time, investigate whether it is a partitioning candidate."],
    production_safety=["All scripts are read-only. VACUUM itself (non-FULL) does not block reads/writes to the table it targets, aside from momentary lock acquisition for truncation at the very end (which can itself be skipped with `VACUUM (TRUNCATE false)` if that final step is a concern)."],
    escalation_criteria=["A vacuum has been running for an unusually long time with no progress and no clear cause -- escalate to database engineering."],
    related_issues=["../autovacuum-not-keeping-up/README.md", "../emergency-autovacuum/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_vacuum_progress_detail", "Shows detailed progress for every currently running VACUUM (manual or autovacuum), using PostgreSQL 17's byte-based progress columns.",
               sb.autovacuum_workers_active(),
               "Re-run this every 30-60 seconds; heap_blks_scanned and indexes_processed should both be advancing over time. dead_tuple_bytes approaching max_dead_tuple_bytes signals an index vacuum cycle is about to be triggered (normal).",
               related_scripts="02_relation_scan_rate.sql"),
    sql_script("02", "02_relation_scan_rate", "Computes the target table's total size against the vacuum's current scanned-block progress to estimate percent complete.",
               """
-- Percent-complete estimate for a specific in-flight vacuum, combining
-- pg_stat_progress_vacuum with the table's total block count.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                    AS table_name,
    v.phase,
    v.heap_blks_scanned,
    v.heap_blks_total,
    round(100.0 * v.heap_blks_scanned / NULLIF(v.heap_blks_total, 0), 1) AS pct_heap_scanned,
    v.indexes_processed,
    v.indexes_total
FROM pg_stat_progress_vacuum v
JOIN pg_class c ON c.oid = v.relid
JOIN pg_namespace n ON n.oid = c.relnamespace
ORDER BY pct_heap_scanned ASC NULLS LAST;
""".strip("\n"),
               "pct_heap_scanned is only for the 'scanning heap' phase; once in 'vacuuming indexes' or 'cleaning up indexes' phases, watch indexes_processed/indexes_total instead.",
               related_scripts="../autovacuum-not-keeping-up/README.md"),
]

WORKFLOWS.append(_wf(
    slug="dead-tuples",
    title="Dead Tuple Accumulation",
    summary="Investigates elevated dead tuple counts/ratios across tables -- the direct precursor to bloat, degraded index efficiency, and increased I/O, and the primary metric autovacuum acts on.",
    symptoms=["Rising n_dead_tup on one or more tables.", "Growing gap between n_live_tup + n_dead_tup and the table's expected logical row count."],
    business_impact=["Dead tuples directly inflate table and index size, increasing I/O for every scan and reducing effective cache hit ratio for hot tables."],
    root_causes=["High UPDATE/DELETE churn on a table (common for order status transitions, balance updates) outpacing vacuum's cleanup rate.", "A long-running transaction preventing cleanup of tuples that are otherwise eligible.", "autovacuum thresholds (scale_factor) too high in absolute terms for a very large table."],
    investigation_strategy=["Rank tables by dead tuple count/ratio.", "Cross-reference with UPDATE/DELETE volume (n_tup_upd, n_tup_del) to confirm churn is the driver.", "Check for a blocking transaction preventing cleanup."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["A table with high n_tup_upd/n_tup_del and correspondingly high n_dead_tup is behaving as expected for a busy OLTP table -- the question is whether autovacuum's scale_factor threshold is appropriate for its absolute size, not whether dead tuples exist at all (some level is normal and expected between vacuum cycles)."],
    remediation_immediate=["Manually VACUUM tables with a critically high dead_tuple_pct if autovacuum has not yet caught up."],
    remediation_short_term=["Lower autovacuum_vacuum_scale_factor for large, high-churn tables (default 20% of table size is very large in absolute terms for a multi-million-row table)."],
    remediation_long_term=["See vacuum-and-autovacuum/autovacuum-not-keeping-up for systemic tuning; see partitioning/ for tables where per-partition vacuum would help."],
    production_safety=["Investigation scripts are read-only; manual VACUUM guidance is non-blocking."],
    escalation_criteria=["Dead tuple ratio remains high and growing despite tuning -- escalate to autovacuum-not-keeping-up for a deeper investigation."],
    related_issues=["../autovacuum-not-keeping-up/README.md", "../table-bloat/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_dead_tuples_ranked", "Ranks tables by dead tuple count and ratio.",
               sb.dead_tuples_ranked(),
               "Cross-reference dead_tuple_pct against the table's write pattern -- a high ratio on a rarely-updated table is more concerning than the same ratio on a known-hot table between vacuum cycles.",
               related_scripts="../table-bloat/README.md"),
]

WORKFLOWS.append(_wf(
    slug="table-bloat",
    title="Table Bloat",
    summary="Investigates physical table bloat -- disk space consumed by dead/reusable tuple space that has not been returned to the OS or reused efficiently, distinct from the logical dead-tuple count itself.",
    symptoms=["Table on-disk size much larger than expected for its live row count.", "Growing total_relation_size with flat or declining n_live_tup."],
    business_impact=["Bloat increases storage costs and, more importantly, increases the number of pages that must be read for a sequential or even index scan, directly degrading query performance."],
    root_causes=["Sustained dead-tuple accumulation (see dead-tuples) without full space reclamation, since ordinary VACUUM marks space reusable but does not necessarily shrink the file on disk.", "A historical spike in deletes/updates (e.g. a large one-time cleanup) leaving behind free space that is reused slowly."],
    investigation_strategy=["Estimate bloat using the catalog-only proxy (safe, no lock, approximate).", "Confirm with pgstattuple's exact physical scan for the top candidates (heavier, but precise).", "Decide between routine VACUUM (reclaims space for reuse, does not shrink file) and a maintenance-window VACUUM FULL/pg_repack (shrinks file, but locks/rewrites)."],
    prerequisites=["pgstattuple extension for the exact-bloat script (optional but recommended for confirmation)."],
    interpretation_guide=["Regular (non-FULL) VACUUM makes dead space available for reuse by future inserts/updates on the same table -- it does NOT shrink the file on disk. Only VACUUM FULL, CLUSTER, or pg_repack physically shrink the table, and all require careful scheduling due to locking."],
    remediation_immediate=["None -- bloat remediation is inherently a planned, scheduled action, not an emergency one, unless bloat is actively causing a severe performance incident."],
    remediation_short_term=["Ensure routine VACUUM is keeping bloat from growing further (see autovacuum-not-keeping-up) before considering a space-reclaiming operation."],
    remediation_long_term=["Schedule a VACUUM FULL (small tables, brief maintenance window) or pg_repack (installed via Aurora's supported extension list, minimal-lock alternative for large tables) during a planned maintenance window -- see maintenance/ for the runbook and locking implications."],
    production_safety=["Bloat estimation scripts are read-only and safe at any time.", "pgstattuple's exact scan takes a light read lock and can be I/O-intensive on very large tables -- prefer pgstattuple_approx() for tables over a few GB, or schedule the exact scan off-peak."],
    escalation_criteria=["Bloat is confirmed severe (free_pct from pgstattuple well above 30-40%) on a business-critical table -- escalate to schedule a maintenance-window remediation with stakeholder sign-off."],
    related_issues=["../dead-tuples/README.md", "../index-bloat/README.md", "../../maintenance/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_bloat_estimate_catalog_only", "Lightweight, lock-free bloat proxy using only pg_class/pg_stat_all_tables -- always safe to run.",
               sb.table_bloat_estimate(),
               "Use this to triage which tables merit a closer, exact look; it is a proxy, not an exact bloat percentage.",
               related_scripts="02_exact_bloat_pgstattuple.sql"),
    sql_script("02", "02_exact_bloat_pgstattuple", "Exact physical bloat scan for one specific table using the pgstattuple extension.",
               sb.pgstattuple_exact_bloat(),
               "free_pct and dead_tuple_pct together give the true reclaimable-space percentage; a combined figure above 30-40% on a large table is a strong candidate for a scheduled space-reclaiming operation.",
               safety="READ ONLY (may be resource intensive on very large tables -- see EXPECTED IMPACT)",
               expected_impact="Performs a full table scan (or sampled scan for pgstattuple_approx) and takes a light read lock; can be I/O-intensive on very large tables.",
               prerequisites="pgstattuple extension must be created in the current database.",
               related_scripts="../../maintenance/README.md"),
]

WORKFLOWS.append(_wf(
    slug="index-bloat",
    title="Index Bloat",
    summary="Investigates physical bloat specifically within indexes, which accumulates independently of table bloat and directly slows down index scans and increases index-storage footprint.",
    symptoms=["Index size disproportionately large relative to the table's row count.", "Index scan performance degrading over time without a corresponding table-size change."],
    business_impact=["Bloated indexes on hot lookup columns (order id, account id) directly increase the latency of the most frequent, latency-sensitive queries."],
    root_causes=["High UPDATE churn on indexed columns (each update typically creates a new index entry) without corresponding cleanup.", "A historical bulk delete/update leaving substantial reusable-but-unreclaimed space in the index structure."],
    investigation_strategy=["Rank indexes by size and scan activity.", "Cross-reference with the parent table's bloat status, since index bloat commonly correlates with table bloat.", "Consider REINDEX CONCURRENTLY for confirmed bloated indexes."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["Unlike tables, indexes generally benefit more directly from a REINDEX to reclaim space efficiently, and PostgreSQL supports `REINDEX INDEX CONCURRENTLY` (non-blocking) as the safe production path -- prefer it over `REINDEX INDEX` (which takes a blocking lock)."],
    remediation_immediate=["None -- index bloat remediation is a planned action."],
    remediation_short_term=["`REINDEX INDEX CONCURRENTLY schema.index_name;` during a lower-traffic window, monitoring for the same failure modes as CREATE INDEX CONCURRENTLY (can leave an INVALID index if interrupted)."],
    remediation_long_term=["Investigate whether the underlying UPDATE pattern can be reduced (e.g. avoid updating indexed columns unnecessarily) to slow future bloat accumulation."],
    production_safety=["Investigation scripts are read-only.", "REINDEX CONCURRENTLY requires roughly double the index's disk space temporarily and cannot run inside an explicit transaction block; see schema-changes/concurrent-index-build for the full safety runbook."],
    escalation_criteria=["A hot-path index shows severe bloat and cannot tolerate a REINDEX CONCURRENTLY window without app-visible impact -- escalate to schedule an off-peak maintenance action."],
    related_issues=["../table-bloat/README.md", "../../tables-and-indexes/index-bloat/README.md", "../../schema-changes/concurrent-index-build/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_index_bloat_and_usage", "Index size and usage statistics to identify large, potentially bloated indexes.",
               sb.index_bloat_and_usage(),
               "A large index_size relative to the table's row count and low idx_tup_fetch efficiency suggests bloat; confirm with pgstattuple if a precise figure is needed before scheduling a REINDEX.",
               related_scripts="../../schema-changes/concurrent-index-build/README.md"),
]

WORKFLOWS.append(_wf(
    slug="vacuum-blocked",
    title="Vacuum Blocked or Unable to Proceed",
    summary="Autovacuum or a manual VACUUM is unable to start or make progress on a specific table due to a lock conflict or a long-running transaction holding back its required snapshot horizon.",
    symptoms=["A table shows a stale last_autovacuum/last_vacuum timestamp despite clearly needing attention (high dead_tup).", "No active pg_stat_progress_vacuum entry for a table that should be receiving attention."],
    business_impact=["A table vacuum cannot proceed indefinitely blocks bloat and (if sustained) XID-age cleanup for that table, compounding into the more severe autovacuum-not-keeping-up and xid-wraparound-risk scenarios."],
    root_causes=["A conflicting lock (e.g. an explicit LOCK TABLE, or a long-running transaction holding a conflicting lock mode) preventing vacuum from acquiring the ShareUpdateExclusiveLock it needs.", "A long-running transaction whose snapshot predates the dead tuples, meaning vacuum can scan the table but cannot yet remove those specific tuples."],
    investigation_strategy=["Confirm no autovacuum worker is currently assigned to the table despite it needing attention.", "Check for locks on the table that would conflict with vacuum's required lock mode.", "Check for a long-running transaction whose xmin predates the table's dead tuples."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["VACUUM only requires ShareUpdateExclusiveLock, which does not block ordinary reads/writes -- but it does conflict with other ShareUpdateExclusiveLock or stronger requests (another VACUUM, a CREATE INDEX CONCURRENTLY, most ALTER TABLE forms) already in progress on the same table."],
    remediation_immediate=["Resolve the conflicting lock holder or long-running transaction identified, using the concurrency-and-locking workflows."],
    remediation_short_term=["Avoid scheduling concurrent CONCURRENTLY-mode DDL and manual VACUUM against the same large table in the same window."],
    remediation_long_term=["Add monitoring that alerts when a known-hot table has gone unusually long without a successful vacuum."],
    production_safety=["Investigation scripts are read-only."],
    escalation_criteria=["The table's XID age is simultaneously climbing toward a concerning threshold while vacuum remains blocked -- escalate immediately per xid-wraparound-risk."],
    related_issues=["../../transactions-and-xid/xid-wraparound-risk/README.md", "../../concurrency-and-locking/long-running-transactions/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_locks_conflicting_with_vacuum", "Checks for locks on candidate tables that would conflict with vacuum's required ShareUpdateExclusiveLock.",
               sb.ddl_lock_waits(),
               "Any granted lock at ShareUpdateExclusiveLock or stronger on a table that needs vacuuming will prevent a new vacuum from starting until it is released.",
               related_scripts="02_transactions_predating_dead_tuples.sql"),
    sql_script("02", "02_transactions_predating_dead_tuples", "Checks for long-running transactions whose snapshot predates recent dead tuples, preventing vacuum from reclaiming them even if it can run.",
               sb.long_running_transactions(),
               "A transaction open since before the dead tuples were created means vacuum can scan the table but cannot yet remove those specific rows -- resolving the transaction is the direct fix.",
               related_scripts="../autovacuum-not-keeping-up/README.md"),
]

WORKFLOWS.append(_wf(
    slug="emergency-autovacuum",
    title="Emergency / Anti-Wraparound Autovacuum",
    summary="A table has crossed autovacuum_freeze_max_age and is now being vacuumed in mandatory 'anti-wraparound' mode (or has crossed vacuum_failsafe_age and is in accelerated failsafe mode), which cannot be cancelled without directly increasing wraparound risk.",
    symptoms=["Autovacuum log entries explicitly marked '(to prevent wraparound)'.", "A vacuum that appears to ignore normal cost-based throttling and run at maximum speed (failsafe mode, PostgreSQL 14+).", "pg_stat_progress_vacuum showing a worker on a table whose age already exceeds autovacuum_freeze_max_age."],
    business_impact=["This is the last automatic safety net before a full wraparound-protection outage -- it is expected, necessary behavior, and interfering with it (e.g. cancelling it) directly increases outage risk."],
    root_causes=["See transactions-and-xid/xid-wraparound-risk for the full root-cause list; this workflow is specifically about safely handling the emergency vacuum once it has already started."],
    investigation_strategy=["Confirm the vacuum is genuinely in anti-wraparound/failsafe mode (not just a normal, but slow, routine vacuum).", "Monitor its progress rather than attempting to stop it.", "Ensure no long-running transaction is preventing it from completing."],
    prerequisites=["pg_monitor role membership; rds_superuser-equivalent only if manual intervention beyond monitoring becomes necessary."],
    interpretation_guide=["In failsafe mode, PostgreSQL suspends cost-based delay entirely and may skip index cleanup to freeze rows as fast as possible -- this is intentional and appropriate given the alternative (a full outage), even though it consumes more I/O/CPU than a routine vacuum."],
    remediation_immediate=["Do NOT cancel or terminate an anti-wraparound/failsafe vacuum. Instead, ensure it can complete: resolve any long-running transaction that could still be blocking its progress."],
    remediation_short_term=["Once complete, immediately address the underlying root cause (see xid-wraparound-risk) so this does not recur within days."],
    remediation_long_term=["Tune autovacuum settings proactively so freeze work happens in smaller, routine increments well before failsafe mode is ever triggered again."],
    production_safety=["This vacuum itself is the safety mechanism -- the primary safety guidance here is 'do not interfere with it', not 'here is a destructive action to avoid'."],
    escalation_criteria=["The database has already begun refusing new transactions (full wraparound outage) -- this is beyond routine emergency-autovacuum monitoring; escalate as a major incident immediately."],
    related_issues=["../../transactions-and-xid/xid-wraparound-risk/README.md", "../autovacuum-not-keeping-up/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_confirm_emergency_vacuum", "Confirms whether a currently running vacuum is in anti-wraparound/failsafe mode by cross-referencing its target table's age against the configured thresholds.",
               sb.autovacuum_workers_active() + "\n\n-- Cross-reference each relid above against transactions-and-xid/xid-wraparound-risk/scripts/01_database_transaction_age.sql and 02_table_transaction_age.sql output: a worker on a table already past autovacuum_freeze_max_age is running in mandatory anti-wraparound mode.",
               "A worker present here for a table whose age already exceeds autovacuum_freeze_max_age (from the xid-wraparound-risk scripts) is running in anti-wraparound mode -- let it complete.",
               related_scripts="../../transactions-and-xid/xid-wraparound-risk/scripts/04_current_autovacuum_activity.sql"),
    md_script("02", "02_safe_handling_during_emergency_vacuum", "Manual guidance for what to do (and not do) while an anti-wraparound/failsafe vacuum is in progress.",
              (
                  "## Do\n\n"
                  "- Monitor progress via `pg_stat_progress_vacuum` (see script 01) every few minutes.\n"
                  "- Resolve any long-running transaction or lock conflict that could be preventing the "
                  "vacuum from completing (see concurrency-and-locking/long-running-transactions and "
                  "vacuum-and-autovacuum/vacuum-blocked).\n"
                  "- Communicate expected duration to stakeholders based on heap_blks_scanned progress "
                  "rate, since this vacuum may consume more visible I/O/CPU than routine background "
                  "vacuuming.\n\n"
                  "## Do NOT\n\n"
                  "- Do NOT run `SELECT pg_cancel_backend(<autovacuum_worker_pid>);` against this "
                  "worker -- cancelling it does not remove the underlying wraparound risk, it only "
                  "delays the inevitable next attempt while the risk continues to grow.\n"
                  "- Do NOT disable autovacuum (globally or per-table) to 'stop the noise' -- this is "
                  "the single worst possible action during an active wraparound-risk event.\n"
                  "- Do NOT attempt a `VACUUM FULL` instead, hoping it will be faster -- it takes an "
                  "AccessExclusiveLock for a full table rewrite and is not needed; the running "
                  "anti-wraparound vacuum is already the correct, safe operation.\n"
              ),
              "Read this in full before taking any action while an emergency vacuum is in progress -- the single most important guidance is to let it run.",
              safety="DOCUMENTATION -- no SQL executed by this file itself",
              expected_impact="None from this file directly.",
              required_privileges="N/A",
              prerequisites="An anti-wraparound/failsafe vacuum confirmed via script 01.",
              related_scripts="../../transactions-and-xid/xid-wraparound-risk/README.md"),
]

WORKFLOWS.append(_wf(
    slug="analyze-statistics",
    title="ANALYZE and Planner Statistics",
    summary="Investigates whether planner statistics are fresh and representative, distinct from vacuum's tuple-cleanup role -- ANALYZE (whether run manually, via autoanalyze, or as part of autovacuum) is what keeps the query planner's row/selectivity estimates accurate.",
    symptoms=["Query plans that do not match expected row-count estimates.", "n_mod_since_analyze high relative to table size.", "last_analyze/last_autoanalyze significantly stale relative to the table's write rate."],
    business_impact=["Stale statistics are one of the most common root causes of sudden query-plan regressions on an otherwise-unchanged query."],
    root_causes=["autovacuum_analyze_scale_factor too high in absolute terms for a very large table.", "A large bulk load/backfill completed without a follow-up manual ANALYZE.", "autoanalyze disabled or starved similarly to autovacuum (shares the same worker pool and cost settings)."],
    investigation_strategy=["Check statistics freshness (modifications since last analyze) across tables.", "For any table suspected of a plan regression, manually ANALYZE it and compare plans before/after.", "Consider a higher statistics target for specific skewed columns."],
    prerequisites=["pg_monitor role membership; table-owner privilege to run ANALYZE manually."],
    interpretation_guide=["Distinguish ANALYZE (statistics only, all data types, fast, no data rewrite) from VACUUM ANALYZE (does both). Running ANALYZE alone is comparatively cheap and safe to run more frequently than a full VACUUM pass if statistics freshness -- not bloat -- is the specific concern."],
    remediation_immediate=["`ANALYZE schema.table_name;` (targeted, not database-wide) for any table with clearly stale statistics implicated in a current performance issue."],
    remediation_short_term=["Lower autovacuum_analyze_scale_factor for large tables so autoanalyze triggers more frequently in absolute row-count terms.", "Increase the statistics target (`ALTER TABLE ... ALTER COLUMN ... SET STATISTICS n;`) for specific columns with skewed distributions that the planner is misjudging."],
    remediation_long_term=["Adopt a habit of running a manual, targeted ANALYZE immediately after any large bulk load/backfill/migration as a standard runbook step."],
    production_safety=["ANALYZE takes only a brief, low-impact lock (does not block reads/writes) and never rewrites table data -- safe to run on production at any time.", "Never run a blind, database-wide `ANALYZE;` as a routine fix -- target the specific tables that need it."],
    escalation_criteria=["A specific query's plan regression is not resolved by a fresh ANALYZE -- escalate to query-optimization/analyze-query-plan for a deeper investigation."],
    related_issues=["../../query-optimization/stale-statistics/README.md", "../../performance/query-regression/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_statistics_freshness", "Checks statistics freshness (modifications since last analyze) across all tables.",
               sb.statistics_freshness(),
               "A high pct_modified_since_analyze combined with a stale last_analyze/last_autoanalyze is the clearest sign the planner is working from outdated assumptions for that table.",
               related_scripts="../../query-optimization/stale-statistics/README.md"),
]
