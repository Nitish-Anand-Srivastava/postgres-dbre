"""Workflow definitions: transactions-and-xid/ category (5 issue directories).

xid-wraparound-risk is the flagship, most comprehensive workflow in this
category per the specification and receives a 12-step investigation.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import PG_MONITOR, md_script, sql_script
from .model import Workflow

CATEGORY_SLUG = "transactions-and-xid"
CATEGORY_TITLE = "Transaction ID (XID) Wraparound and Transaction Management"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

# ---------------------------------------------------------------------------
# xid-wraparound-risk (flagship, 12-step workflow)
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="xid-wraparound-risk",
    title="Transaction ID (XID) Wraparound Risk",
    summary=(
        "PostgreSQL transaction IDs are a finite 32-bit counter. If the "
        "oldest unfrozen transaction ID in any database is allowed to age "
        "past ~2.1 billion transactions without being frozen by vacuum, "
        "PostgreSQL will refuse new transactions cluster-wide to protect "
        "data integrity (a full outage that requires single-user-mode "
        "recovery to resolve). This workflow is the comprehensive, "
        "staff-level investigation and prevention runbook for that risk."
    ),
    symptoms=[
        "Warnings in the PostgreSQL log (CloudWatch Logs on Aurora): 'database is not accepting commands to avoid wraparound data loss'.",
        "age(datfrozenxid) for any database climbing steadily with no corresponding autovacuum activity.",
        "Autovacuum running continuously in 'aggressive'/anti-wraparound mode on one or more large tables.",
        "Aurora CloudWatch metric MaximumUsedTransactionIDs approaching autovacuum_freeze_max_age.",
    ],
    business_impact=[
        "Wraparound protection kicking in is a full write outage across the entire database -- every trading, ledger, and order-book write stops until an operator intervenes, typically requiring emergency single-user-mode VACUUM.",
        "This is one of the few PostgreSQL failure modes that is entirely preventable with routine monitoring, making an actual wraparound incident a severe operational failure, not an unavoidable act of nature.",
        "Recovery from an active wraparound-protection outage can take hours on very large tables, since the required VACUUM cannot be skipped or parallelized trivially in single-user mode.",
    ],
    root_causes=[
        "Autovacuum disabled or effectively starved (cost limits too conservative, autovacuum_naptime too high) for the actual write/update volume.",
        "A long-running transaction or an orphaned prepared (two-phase-commit) transaction holding back the cluster-wide minimum required XID horizon, preventing vacuum from advancing relfrozenxid even where it runs successfully elsewhere.",
        "An abandoned or forgotten replication slot retaining an old xmin, preventing cleanup.",
        "Extremely high write/update volume on one or a few huge tables outpacing autovacuum's throughput even when properly configured.",
        "autovacuum_freeze_max_age and related settings left at defaults that do not suit an extremely high-transaction-rate exchange workload.",
        "A table explicitly configured with autovacuum disabled (`autovacuum_enabled = false` in reloptions) for perceived performance reasons, inadvertently disabling its own wraparound protection too (anti-wraparound vacuums still force-run regardless of this setting, but later than they should if the table was otherwise neglected).",
    ],
    investigation_strategy=[
        "Check database-level transaction age (datfrozenxid) for every database in the cluster -- this is the single most important, highest-level signal.",
        "Check table-level transaction age (relfrozenxid) to identify which specific tables are closest to the freeze horizon.",
        "Check TOAST tables specifically, since they age independently and are commonly overlooked.",
        "Check multixact age separately, since it has its own independent wraparound horizon and its own freeze_max_age setting.",
        "Check current autovacuum activity to confirm workers are actively running and progressing on the oldest tables.",
        "Identify any tables where autovacuum is disabled via storage parameters.",
        "Check for long-running transactions holding back the cluster-wide minimum xmin horizon.",
        "Check for orphaned prepared (two-phase-commit) transactions holding back cleanup.",
        "Check replication slots for an old xmin/catalog_xmin that could be pinning the vacuum horizon.",
        "Cross-check current freeze-related configuration (autovacuum_freeze_max_age, vacuum_failsafe_age, per-table overrides) against the observed ages.",
        "Estimate time-to-wraparound at the current XID consumption rate to prioritize response urgency.",
        "Follow the documented remediation path appropriate to the specific blocker found (kill blocker, force vacuum, tune settings) -- never skip straight to VACUUM FULL or any destructive action.",
    ],
    prerequisites=[
        "pg_monitor role membership for all read-only investigation scripts.",
        "Table-owner or pg_maintain-equivalent privileges (or DBA/rds_superuser on Aurora) if a manual VACUUM must be issued as part of remediation.",
        "Familiarity with vacuum-and-autovacuum/emergency-autovacuum for the accompanying remediation runbook.",
    ],
    interpretation_guide=[
        "age() values are compared against autovacuum_freeze_max_age (default 200,000,000; many high-transaction-rate deployments lower this so autovacuum engages earlier and more gradually) and the hard failsafe at vacuum_failsafe_age (default 1,600,000,000) where PostgreSQL 14+ automatically escalates to a faster, index-skipping emergency vacuum mode.",
        "A pct_of_freeze_max_age above ~80-90% on any table warrants proactive attention even without an active incident; above 100% means autovacuum should already be running an aggressive/anti-wraparound vacuum on that table by design.",
        "If age is climbing despite autovacuum running, the workload's write rate simply exceeds autovacuum's configured throughput (cost limits) -- this is a tuning problem, not a 'vacuum is broken' problem.",
        "If age is climbing and autovacuum is NOT running on the oldest tables, look for a blocker: a long-running transaction, an orphaned prepared transaction, a disabled-autovacuum table, or a stuck replication slot.",
    ],
    remediation_immediate=[
        "If a specific long-running transaction or orphaned prepared transaction is identified as the blocker, resolve it (commit/rollback the prepared transaction, or terminate the long-running session with documented approval) so vacuum can advance.",
        "If age is critically high (approaching vacuum_failsafe_age) on a specific table, manually issue `VACUUM (VERBOSE) <table>;` (or `VACUUM (FREEZE)` for a targeted freeze) against that table immediately rather than waiting for autovacuum's next scheduled pass -- see vacuum-and-autovacuum/emergency-autovacuum for the full safe procedure.",
    ],
    remediation_short_term=[
        "Increase autovacuum cost limits (autovacuum_vacuum_cost_limit, autovacuum_vacuum_cost_delay) via the Aurora cluster parameter group for the affected tables/instance to let autovacuum work faster.",
        "Lower autovacuum_freeze_max_age (and/or set a per-table `autovacuum_freeze_max_age` storage parameter) for extremely high-write tables so freezing happens more frequently in smaller, cheaper increments instead of large, disruptive passes.",
        "Drop or fix any replication slot that is inactive/abandoned and pinning the xmin horizon, after confirming it is genuinely no longer needed.",
    ],
    remediation_long_term=[
        "Establish routine automated monitoring/alerting on transaction age (see automation/xid-monitoring) with alert thresholds well below the failsafe (e.g. alert at 50% of autovacuum_freeze_max_age).",
        "Review and, where appropriate, remove any `autovacuum_enabled = false` table-level overrides that were set for perceived performance reasons without an accompanying manual vacuum schedule.",
        "Consider partitioning extremely large, high-churn tables (see partitioning/) so freeze/vacuum work is distributed across smaller partitions rather than one monolithic table.",
    ],
    production_safety=[
        "All numbered investigation scripts (01-10) are read-only.",
        "Manual `VACUUM` (without FULL) is safe to run concurrently with production traffic -- it does not take an exclusive table lock and does not rewrite the table. Never substitute `VACUUM FULL` here: it takes AccessExclusiveLock for the duration and is a much higher-risk operation, and is not needed to resolve wraparound risk.",
        "Never disable autovacuum cluster-wide or on a specific table as a way to 'reduce load' -- this directly increases wraparound risk and is one of the root causes this workflow investigates.",
    ],
    escalation_criteria=[
        "Any table's age exceeds vacuum_failsafe_age (1,600,000,000 by default) -- this is an active, urgent risk of a wraparound-protection outage; escalate to database engineering leadership immediately regardless of time of day.",
        "The blocker is a system/replication process rather than an application session -- escalate before taking any corrective action.",
        "The cluster has already entered wraparound-protection read-only/refuse-new-transactions mode -- this is a full outage; follow your organization's major-incident process and engage AWS Support in parallel with database-side recovery.",
    ],
    related_issues=[
        "../transaction-age/README.md",
        "../multixact-risk/README.md",
        "../prepared-transactions/README.md",
        "../../vacuum-and-autovacuum/emergency-autovacuum/README.md",
        "../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md",
    ],
    aurora_notes=[
        "Aurora exposes the CloudWatch metric MaximumUsedTransactionIDs at the instance level, which mirrors the highest age() value across all databases -- use it for alerting in addition to (not instead of) the SQL-level checks here, since CloudWatch alarms fire even when nobody is actively running these scripts.",
        "Wraparound protection and its recovery mechanics (autovacuum, freeze, failsafe) are standard PostgreSQL engine behavior and work identically on Aurora -- there is no Aurora-specific bypass or storage-layer mitigation for XID exhaustion.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_database_transaction_age", "Database-level XID age against datfrozenxid -- the single highest-priority check in this entire workflow.",
               sb.database_transaction_age(),
               "Sort by xid_age descending. Any database above 50% of autovacuum_freeze_max_age deserves proactive attention; above 90% is urgent.",
               related_scripts="02_table_transaction_age.sql"),
    sql_script("02", "02_table_transaction_age", "Ranks ordinary tables, TOAST tables, and materialized views by relfrozenxid age to find the specific tables driving the database-level age found in script 01.",
               sb.table_transaction_age_top_n(),
               "The table(s) at the top of this list are where autovacuum most urgently needs to succeed; note their relkind -- TOAST tables ('t') are easy to overlook but age exactly like ordinary tables.",
               related_scripts="01_database_transaction_age.sql, 03_multixact_age.sql"),
    sql_script("03", "03_multixact_age", "Ranks tables by multixact ID age (relminmxid), a separate wraparound horizon driven by row-level locking (FOR UPDATE/SHARE, FK checks) rather than plain writes.",
               sb.multixact_age_top_n(),
               "High-multixact-age tables are typically ones with heavy concurrent row locking (order books, balances) even if their plain XID age looks fine -- both horizons must be tracked independently.",
               related_scripts="../multixact-risk/README.md"),
    sql_script("04", "04_current_autovacuum_activity", "Confirms whether autovacuum is currently running, and on which tables, via pg_stat_progress_vacuum.",
               sb.autovacuum_workers_active(),
               "Confirm the oldest tables from script 02 actually have an active worker; if the oldest table has NO active worker despite a high age, something is preventing autovacuum from starting or completing on it.",
               related_scripts="05_tables_with_autovacuum_disabled.sql"),
    sql_script("05", "05_tables_with_autovacuum_disabled", "Finds tables with autovacuum explicitly disabled via storage parameters, a common and easily overlooked risk factor.",
               """
-- Tables with autovacuum explicitly disabled via a reloptions override.
-- Anti-wraparound vacuums still eventually force-run on these tables
-- regardless of this setting, but disabling routine autovacuum means the
-- table accumulates far more dead tuples and XID age between forced passes
-- than it should, making the eventual anti-wraparound vacuum larger and more
-- disruptive than necessary.
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                    AS table_name,
    c.reloptions,
    age(c.relfrozenxid)                                          AS xid_age,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND c.reloptions IS NOT NULL
  AND EXISTS (
      SELECT 1 FROM unnest(c.reloptions) opt WHERE opt = 'autovacuum_enabled=false'
  )
ORDER BY xid_age DESC;
""".strip("\n"),
               "Any table returned here combined with a high xid_age from script 02 is a strong candidate root cause -- review whether the original reason for disabling autovacuum still applies, and whether a scheduled manual VACUUM was ever put in place to compensate (it usually was not).",
               related_scripts="06_long_running_transactions.sql"),
    sql_script("06", "06_long_running_transactions", "Checks for long-running transactions that hold back the cluster-wide minimum xmin horizon, preventing vacuum from advancing even on tables it successfully scans.",
               sb.long_running_transactions(),
               "Even a single multi-hour-old transaction on an unrelated, small table can prevent vacuum from freezing rows across the ENTIRE database, because PostgreSQL's cleanup horizon is cluster/database-wide, not per-table.",
               related_scripts="07_prepared_transactions.sql"),
    sql_script("07", "07_prepared_transactions", "Checks for orphaned two-phase-commit (PREPARE TRANSACTION) entries, which behave like an indefinitely long-running transaction until resolved.",
               sb.prepared_transactions(),
               "Any row here older than a few minutes is almost certainly a bug in a distributed transaction coordinator, not intentional application behavior -- coordinate with the owning team to COMMIT PREPARED or ROLLBACK PREPARED it.",
               related_scripts="../prepared-transactions/README.md"),
    sql_script("08", "08_replication_slots_xmin_pinning", "Checks replication slots for a retained xmin/catalog_xmin that could be pinning the vacuum cleanup horizon.",
               sb.replication_slots_status(),
               "An inactive slot (active = false) with a very old xmin is a common, easily missed cause of a database-wide vacuum horizon stall -- confirm whether the consuming service still exists before dropping the slot.",
               related_scripts="../../replication-and-ha/replication-health/README.md"),
    sql_script("09", "09_freeze_configuration_snapshot", "Snapshots the current freeze-related configuration to interpret the ages found in scripts 01-03 against the actual thresholds in effect.",
               sb.key_settings_snapshot(),
               "Confirm autovacuum_freeze_max_age and autovacuum_multixact_freeze_max_age match your organization's intended values -- Aurora parameter groups can drift from documented defaults after a parameter-group change.",
               related_scripts="10_time_to_wraparound_estimate.sql"),
    sql_script("10", "10_time_to_wraparound_estimate", "Estimates remaining headroom (in transactions and, using an assumed rate, wall-clock time) before the oldest table reaches the hard 2^31 wraparound limit.",
               """
-- Rough time-to-wraparound estimate for the table with the oldest XID age.
-- 2,146,483,648 (2^31 - 1,000,000 safety margin) is used as the effective
-- hard ceiling; PostgreSQL actually enforces failsafe/refusal behavior well
-- before the true 2^31 limit, but this gives a conservative worst-case
-- figure. Replace :assumed_xids_per_second with your own measured average
-- transaction rate (see performance/throughput-degradation script 01 for
-- how to measure it) for a realistic estimate -- there is no way to derive
-- a wall-clock estimate from catalogs alone without an assumed rate.
\\set assumed_xids_per_second 500
SELECT
    n.nspname                                                   AS schema_name,
    c.relname                                                    AS table_name,
    age(c.relfrozenxid)                                          AS current_xid_age,
    2146483648 - age(c.relfrozenxid)                              AS xids_remaining,
    round((2146483648 - age(c.relfrozenxid)) / NULLIF(:assumed_xids_per_second, 0) / 3600.0, 1) AS estimated_hours_remaining_at_assumed_rate
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'm', 't')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
ORDER BY current_xid_age DESC
LIMIT 10;
""".strip("\n"),
               "Treat estimated_hours_remaining as a rough order of magnitude, not a precise SLA -- transaction rate varies with trading volume/market volatility. Use it to prioritize response urgency, not to schedule a leisurely fix.",
               related_scripts="../../vacuum-and-autovacuum/emergency-autovacuum/README.md"),
    md_script("11", "11_remediation_decision_tree", "Manual remediation decision tree and safe commands for resolving an active or imminent wraparound risk once the blocker is identified.",
              (
                  "## Decision tree\n\n"
                  "1. **A specific long-running transaction or prepared transaction is the blocker "
                  "(scripts 06/07 found one, and the oldest table's autovacuum worker is NOT "
                  "running or is stuck):**\n"
                  "   - Contact the owning team first if the session/transaction is identifiable.\n"
                  "   - Prepared transaction: `COMMIT PREPARED 'gid';` or `ROLLBACK PREPARED 'gid';` "
                  "as appropriate -- confirm with the owning distributed-transaction coordinator "
                  "which outcome is correct; guessing wrong can leave a partial multi-database "
                  "commit inconsistent.\n"
                  "   - Ordinary session: `SELECT pg_terminate_backend(<pid>);` after documented "
                  "approval.\n\n"
                  "2. **An inactive, abandoned replication slot is pinning the horizon (script 08):**\n"
                  "   - Confirm the consuming application/service is genuinely gone, not just "
                  "temporarily disconnected.\n"
                  "   - `SELECT pg_drop_replication_slot('slot_name');`\n"
                  "   - This is irreversible for that slot's consumer -- it will need to re-sync "
                  "from scratch if it ever reconnects.\n\n"
                  "3. **No blocker found, but a specific table's age is critically high and "
                  "autovacuum has not caught up (scripts 02/04):**\n"
                  "   ```sql\n"
                  "   -- Safe to run concurrently with production traffic. Does not take an\n"
                  "   -- exclusive lock and does not rewrite the table.\n"
                  "   VACUUM (VERBOSE, ANALYZE) schema_name.table_name;\n"
                  "   ```\n"
                  "   - Monitor progress with pg_stat_progress_vacuum (script 04) while it runs.\n"
                  "   - Do NOT use `VACUUM FULL` for this purpose -- it is not required to advance "
                  "relfrozenxid and adds an unnecessary AccessExclusiveLock and full table rewrite.\n\n"
                  "4. **Cluster has already entered wraparound-protection mode (refusing new "
                  "transactions):**\n"
                  "   - This is a full outage. Follow your organization's major-incident process "
                  "immediately.\n"
                  "   - Connect as a superuser-equivalent role, identify the offending table(s) via "
                  "script 02 (single-user/limited connectivity may still be possible for "
                  "monitoring roles depending on how deep into the condition the cluster is), and "
                  "issue a manual `VACUUM (FREEZE)` against them.\n"
                  "   - Engage AWS Support in parallel -- they can advise on Aurora-specific "
                  "recovery options and should be aware of the incident regardless.\n"
              ),
              "This file documents decisions, not automatic actions -- read the matching scenario fully, confirm you are in it, and execute only the specific command it prescribes.",
              safety="GUARDED -- MANUAL EXECUTION ONLY, SEVERITY-DEPENDENT (some branches are routine, others are incident-level)",
              expected_impact="Varies by branch -- from none (read-only confirmation) to a full-outage recovery procedure.",
              required_privileges="Varies by branch; branch 4 requires a superuser-equivalent (rds_superuser on Aurora) role.",
              prerequisites="Scripts 01-10 completed and a specific blocker or critical age identified.",
              related_scripts="../../vacuum-and-autovacuum/emergency-autovacuum/README.md"),
]

WORKFLOWS.append(_wf(
    slug="transaction-age",
    title="Transaction Age Monitoring",
    summary="Routine, lower-urgency monitoring of transaction ID age across databases and tables -- the proactive counterpart to xid-wraparound-risk, intended for regular health checks rather than active-incident response.",
    symptoms=["No active symptom -- this workflow is proactive/preventative and is typically run on a schedule (see automation/xid-monitoring) rather than triggered by an incident."],
    business_impact=["Regular transaction-age monitoring is what keeps xid-wraparound-risk a theoretical scenario instead of a recurring incident."],
    root_causes=["N/A -- this is a monitoring workflow, not an incident investigation. See xid-wraparound-risk for root-cause analysis once elevated age is found."],
    investigation_strategy=["Run the database- and table-level age checks on a schedule.", "Compare against threshold percentages of autovacuum_freeze_max_age.", "Escalate to xid-wraparound-risk immediately if any threshold is breached."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["Track age trend over time (via automation/xid-monitoring's historical snapshots), not just the current value -- a slowly climbing trend is actionable long before a single snapshot looks alarming."],
    remediation_immediate=["None required at healthy age levels; if a threshold is breached, proceed directly to xid-wraparound-risk."],
    remediation_short_term=["Tune autovacuum settings proactively if age is trending toward, but not yet at, a concerning threshold."],
    remediation_long_term=["Automate this check (automation/xid-monitoring) and alert at a conservative threshold (e.g. 40-50% of autovacuum_freeze_max_age) well ahead of any urgency."],
    production_safety=["All scripts are read-only."],
    escalation_criteria=["Any database or table age exceeds 75% of autovacuum_freeze_max_age -- escalate to the full xid-wraparound-risk workflow."],
    related_issues=["../xid-wraparound-risk/README.md", "../../automation/xid-monitoring/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_database_age_snapshot", "Routine database-level XID age snapshot for scheduled monitoring.",
               sb.database_transaction_age(),
               "Record pct_of_freeze_max_age over time; alert when it crosses your organization's chosen proactive threshold (commonly 40-50%).",
               related_scripts="02_table_age_snapshot.sql"),
    sql_script("02", "02_table_age_snapshot", "Routine table-level XID age snapshot, top N oldest tables.",
               sb.table_transaction_age_top_n(),
               "Track which specific tables are consistently near the top of this list -- they are your highest-churn/least-frequently-vacuumed tables and the best candidates for proactive per-table freeze tuning.",
               related_scripts="../xid-wraparound-risk/README.md"),
]

WORKFLOWS.append(_wf(
    slug="oldest-transactions",
    title="Oldest Open Transactions",
    summary="Identifies the single oldest currently-open transaction(s) cluster-wide, since the oldest open transaction determines the effective vacuum cleanup horizon for every database, regardless of how healthy any individual table's autovacuum schedule is.",
    symptoms=["Vacuum unable to advance relfrozenxid on multiple, otherwise-unrelated tables simultaneously.", "n_dead_tup climbing across many tables at once rather than one specific hot table."],
    business_impact=["A single old transaction can silently degrade vacuum effectiveness across the entire database, making this one of the highest-leverage single checks in routine health monitoring."],
    root_causes=["See concurrency-and-locking/long-running-transactions and idle-in-transaction for the underlying causes -- this workflow is the XID-focused lens on the same underlying sessions."],
    investigation_strategy=["List the oldest open transactions cluster-wide by backend_xmin/xact_start.", "Cross-reference with locks held and idle-in-transaction state.", "Resolve per the concurrency-and-locking workflows."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["The oldest transaction's backend_xmin -- not just its xact_start wall-clock age -- is what actually pins the vacuum horizon; a transaction open for a long wall-clock time in an otherwise idle system is lower risk than a shorter-but-XID-heavy window during a traffic spike."],
    remediation_immediate=["Resolve the identified oldest transaction per concurrency-and-locking/long-running-transactions or idle-in-transaction."],
    remediation_short_term=["Set idle_in_transaction_session_timeout and statement_timeout to bound future exposure."],
    remediation_long_term=["Add oldest-transaction-age to the same automated monitoring as XID age itself (automation/xid-monitoring), since the two are directly linked."],
    production_safety=["All scripts are read-only."],
    escalation_criteria=["Oldest transaction age approaches a significant fraction of autovacuum_freeze_max_age -- escalate to xid-wraparound-risk."],
    related_issues=["../xid-wraparound-risk/README.md", "../../concurrency-and-locking/long-running-transactions/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_oldest_transactions_cluster_wide", "Lists the oldest currently open transactions across the instance, ranked by age.",
               sb.long_running_transactions(),
               "The single oldest row here is the transaction currently pinning the cleanup horizon for vacuum cluster-wide -- prioritize resolving it above any other tuning action.",
               related_scripts="02_backend_xmin_horizon.sql"),
    sql_script("02", "02_backend_xmin_horizon", "Shows each backend's reported xmin, the actual value that determines the vacuum cleanup horizon (distinct from xact_start wall-clock age).",
               """
-- Backend xmin horizon: the oldest xmin currently held by any backend
-- determines how far back vacuum can safely clean up dead tuples,
-- independent of how long (in wall-clock time) that backend's transaction
-- has been open.
SELECT
    pid,
    datname,
    usename,
    state,
    backend_xmin,
    age(backend_xmin)                                            AS xmin_age,
    now() - xact_start                                            AS xact_wall_clock_age
FROM pg_stat_activity
WHERE backend_xmin IS NOT NULL
ORDER BY age(backend_xmin) DESC;
""".strip("\n"),
               "Sort by xmin_age, not xact_wall_clock_age -- a session can have a short wall-clock lifetime but, if it started during high transaction throughput, still hold a comparatively old xmin.",
               related_scripts="../../concurrency-and-locking/long-running-transactions/README.md"),
]

WORKFLOWS.append(_wf(
    slug="prepared-transactions",
    title="Prepared (Two-Phase-Commit) Transactions",
    summary="Investigates outstanding PREPARE TRANSACTION entries left in a non-committed, non-rolled-back state, which hold locks and pin the vacuum horizon indefinitely until explicitly resolved.",
    symptoms=["Non-empty pg_prepared_xacts result set.", "Vacuum horizon stalled with no ordinary session identified as the cause."],
    business_impact=["An orphaned prepared transaction behaves like a permanently open transaction -- it does not time out on its own and will pin the vacuum horizon indefinitely, directly contributing to wraparound risk."],
    root_causes=["A distributed transaction coordinator (XA-style ORM/middleware, a manually issued PREPARE TRANSACTION) crashed or lost connectivity before issuing the matching COMMIT PREPARED/ROLLBACK PREPARED.", "max_prepared_transactions configured and in use by a framework the application team may not be fully aware of."],
    investigation_strategy=["List all currently prepared transactions and their age.", "Identify the owning application/coordinator for any found.", "Coordinate the correct resolution (commit or rollback) with that system -- do not guess."],
    prerequisites=["pg_monitor role membership for the read-only check; coordination with the owning application team before resolving any entry."],
    interpretation_guide=["Any prepared transaction older than the coordinator's expected resolution window (typically seconds) is almost certainly orphaned, not legitimately in-flight."],
    remediation_immediate=["Confirm with the owning team whether to COMMIT PREPARED or ROLLBACK PREPARED the specific `gid` -- this determines whether its changes are kept or discarded, which can matter for financial consistency across the distributed transaction."],
    remediation_short_term=["Audit why the coordinator failed to resolve it and fix the underlying reliability gap."],
    remediation_long_term=["Reassess whether two-phase commit is actually required for the use case; many distributed-consistency patterns can be achieved with an outbox/saga pattern instead, avoiding this class of risk entirely."],
    production_safety=["The listing script is read-only.", "Resolving a prepared transaction is a data-affecting decision (commit keeps its changes, rollback discards them) -- never resolve one without confirming the correct outcome with its owning system."],
    escalation_criteria=["Any prepared transaction is found and its owning system cannot be identified -- escalate to database engineering leadership before taking any action."],
    related_issues=["../xid-wraparound-risk/README.md", "../oldest-transactions/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_list_prepared_transactions", "Lists all outstanding prepared (two-phase-commit) transactions and their age.",
               sb.prepared_transactions(),
               "Any row here older than a few minutes needs investigation; note the `gid` (global transaction identifier), which typically encodes which system/coordinator created it.",
               related_scripts="../xid-wraparound-risk/scripts/07_prepared_transactions.sql"),
]

WORKFLOWS.append(_wf(
    slug="multixact-risk",
    title="Multixact ID Wraparound Risk",
    summary="Investigates the independent multixact ID wraparound horizon, driven by row-level locking (SELECT ... FOR UPDATE/SHARE, foreign key existence checks) rather than plain write volume -- easy to overlook because standard XID age can look completely healthy while multixact age is not.",
    symptoms=["mxid_age(relminmxid) climbing on tables with heavy row-level locking (order books, balance tables with FOR UPDATE reads) even while plain relfrozenxid age looks normal.", "Autovacuum log entries specifically mentioning multixact-related freezing."],
    business_impact=["An exchange's order-matching and balance-update logic frequently relies on SELECT ... FOR UPDATE, making multixact accumulation a realistic, workload-specific risk distinct from generic wraparound guidance."],
    root_causes=["High-concurrency row locking on a relatively small set of hot rows (the same root cause as concurrency-and-locking/lock-contention, viewed through the multixact lens).", "Foreign-key referential integrity checks generating multixacts on frequently-referenced parent rows.", "autovacuum_multixact_freeze_max_age left at a default not tuned for the workload's actual multixact generation rate."],
    investigation_strategy=["Check multixact age per table, ranked descending.", "Cross-reference the top tables against known hot-row/FK-heavy tables.", "Check autovacuum activity for multixact-specific freeze progress.", "Check autovacuum_multixact_freeze_max_age configuration."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["A table with high multixact age but low plain XID age is not vacuumed less often overall -- it specifically needs multixact-aware freezing, which the same VACUUM operation performs, so the standard emergency-autovacuum procedure still applies."],
    remediation_immediate=["If a table is critically close to autovacuum_multixact_freeze_max_age, manually VACUUM it per vacuum-and-autovacuum/emergency-autovacuum -- the same command freezes both XID and multixact horizons together."],
    remediation_short_term=["Lower autovacuum_multixact_freeze_max_age for very hot tables so freezing happens more frequently in smaller increments."],
    remediation_long_term=["Reduce unnecessary row-locking scope in application code (lock only the specific rows needed, avoid locking parent rows for FK checks where a lighter-weight validation pattern is possible)."],
    production_safety=["All investigation scripts are read-only.", "Remediation VACUUM guidance is identical in safety profile to standard vacuum -- non-blocking, no exclusive lock."],
    escalation_criteria=["Any table's multixact age exceeds 75% of autovacuum_multixact_freeze_max_age -- escalate to xid-wraparound-risk for the full remediation decision tree."],
    related_issues=["../xid-wraparound-risk/README.md", "../../concurrency-and-locking/lock-contention/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_multixact_age_ranked", "Ranks tables by multixact ID age, the primary signal for this workflow.",
               sb.multixact_age_top_n(),
               "Cross-reference the top tables against your known hot-row/FK-heavy tables (order books, balances, and any table frequently referenced by foreign keys). A high value here with low plain XID age is expected for exactly these tables.",
               related_scripts="02_multixact_freeze_configuration.sql"),
    sql_script("02", "02_multixact_freeze_configuration", "Checks the current multixact freeze configuration in effect.",
               sb.key_settings_snapshot(),
               "Confirm autovacuum_multixact_freeze_max_age matches intended policy; consider a lower per-table override for the tables surfaced in script 01.",
               related_scripts="../xid-wraparound-risk/scripts/09_freeze_configuration_snapshot.sql"),
]
