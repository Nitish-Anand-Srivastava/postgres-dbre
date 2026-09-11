"""Workflow definitions: database-health/ category (7 issue directories)."""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import (
    ANY_INSTANCE,
    PG_MONITOR,
    PG_MONITOR_PLUS_PGSS,
    WRITER_PREFERRED,
    md_script,
    sql_script,
)
from .model import Workflow

CATEGORY_SLUG = "database-health"
CATEGORY_TITLE = "Database Health Checks"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


PGSS_PREREQ = (
    "pg_stat_statements must be present in shared_preload_libraries (Aurora DB "
    "cluster parameter group, requires a reboot to apply) and created in the "
    "current database. This script detects its absence and prints a notice "
    "instead of failing, so it is safe to run either way."
)


def _pgss_guarded(body: str) -> str:
    """Wrap a pg_stat_statements query in an extension-presence guard.

    The guard uses psql's ``\\gset`` / ``\\if`` so the script executes
    unmodified on a database where the extension has never been created --
    it prints an instructional notice rather than raising
    "relation pg_stat_statements does not exist". This file never runs DDL
    itself: creating an extension is a change-managed administrative action,
    not something an investigation script may do implicitly.
    """
    return (
        "-- pg_stat_statements presence check. This script never creates the\n"
        "-- extension itself -- it only detects whether it is already available.\n"
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available\n"
        "\\gset\n"
        "\n"
        "\\if :pgss_available\n"
        f"{body}\n"
        "\\else\n"
        "SELECT 'pg_stat_statements is not installed in this database, so query-level '\n"
        "       'statistics are unavailable for this health check. Ask an administrator '\n"
        "       'to add pg_stat_statements to shared_preload_libraries in the Aurora DB '\n"
        "       'cluster parameter group (reboot required) and then run '\n"
        "       'CREATE EXTENSION pg_stat_statements; in a change-managed session. '\n"
        "       'Until then, continue this health check with the remaining scripts -- '\n"
        "       'they do not depend on this extension.'                  AS notice;\n"
        "\\endif"
    )


WORKFLOWS: List[Workflow] = []

# ---------------------------------------------------------------------------
# comprehensive-health-check
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="comprehensive-health-check",
    title="Comprehensive Database Health Check",
    summary=(
        "A single, end-to-end read-only sweep of every dimension of Aurora PostgreSQL health "
        "that can silently degrade a crypto-exchange platform: sizing and growth, connection "
        "headroom, open transaction horizon, locking, dead tuples and vacuum progress, "
        "transaction ID age, query hot spots, temporary file spills, index usage, and reader "
        "replication health. This is the deep quarterly/ad-hoc assessment, the first thing to "
        "run when taking over an unfamiliar cluster, and the evidence pack to attach to an "
        "incident review -- not the lightweight daily loop (see daily-health-check for that)."
    ),
    symptoms=[
        "No specific active symptom is required -- this workflow is run proactively, on cluster handover, before a major trading event (token listing, scheduled derivatives expiry, marketing campaign), or as the evidence-gathering pass after an incident.",
        "A vague, hard-to-localize report such as 'the exchange feels slower this week' with no single obvious failing subsystem.",
        "An audit or compliance review requires a documented, point-in-time statement of database health for the order, ledger, and settlement stores.",
    ],
    business_impact=[
        "Health problems on an exchange cluster are rarely visible until they are urgent: XID age climbing toward wraparound, a replication slot silently retaining WAL, or a bloating ledger table will each eventually convert into a trading halt rather than a gradual slowdown.",
        "Catching connection-headroom exhaustion before it happens prevents the failure mode where matching-engine and withdrawal-processing services cannot open a connection at exactly the moment volatility spikes and volume is highest.",
        "A documented baseline of 'what healthy looks like' shortens every future incident: without it, the on-call DBA cannot distinguish an abnormal reading from this cluster's normal operating profile.",
    ],
    root_causes=[
        "Capacity drift: steady organic growth of trades, ledger_entries, and order_book_snapshots gradually consuming the headroom that was sized for last year's volume.",
        "Configuration drift: parameter-group changes, per-table autovacuum overrides, or work_mem tuning applied during an incident and never reviewed afterwards.",
        "Workload drift: a new API endpoint, market-data consumer, or reconciliation job introducing query shapes that were never capacity-planned.",
        "Maintenance debt: autovacuum falling behind on the highest-churn tables, stale planner statistics after a backfill, or invalid indexes left behind by a failed concurrent build.",
        "Operational debt: an abandoned logical replication slot from a decommissioned CDC pipeline, or a forgotten prepared transaction holding back the vacuum horizon indefinitely.",
    ],
    investigation_strategy=[
        "Establish context first: which instance am I on (writer or reader), what engine version, and how long has it been up since the last failover or reboot?",
        "Size the system: database and table footprint, so every later finding can be judged in proportion.",
        "Check the cheap, high-signal cluster-wide counters (cache hit ratio, rollback ratio, deadlocks, temp files) before drilling into anything specific.",
        "Check connection headroom, because exhausting it makes every other remediation harder to apply.",
        "Check the open transaction horizon (long transactions and prepared transactions), since one old snapshot invalidates conclusions drawn from vacuum and bloat data.",
        "Check locking, vacuum/dead tuples, and transaction ID age -- the three maintenance-health pillars.",
        "Check query-level hot spots and temp file spills to connect database state back to application behavior.",
        "Check index usage and, finally, reader/replication health so the whole cluster (not just the writer) is covered.",
        "Record the output of every step with a timestamp; the value of this workflow compounds only if successive runs can be compared.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats) on the target database.",
        "pg_stat_statements installed for the query-level step (the script degrades gracefully with a notice if it is absent).",
        "A place to store the output (ticket, runbook log, or object storage) so this run becomes a comparable baseline rather than a throwaway.",
        "Knowledge of when statistics were last reset -- every cumulative counter in this workflow is 'since stats_reset', and an Aurora failover or a manual pg_stat_reset() silently restarts that window.",
    ],
    interpretation_guide=[
        "Nothing in this workflow is judged against a universal 'good' number: interpret every value against this cluster's own previous run and against the business cycle (a Monday-morning reading is not comparable to a weekend reading on an exchange).",
        "Cumulative counters (xact_commit, blks_hit, temp_files, deadlocks, idx_scan) are meaningless as absolutes -- always divide by the time since stats_reset, or diff two runs, to get a rate.",
        "A cache hit ratio below roughly 99% on an OLTP exchange workload usually means the working set no longer fits in shared_buffers; on Aurora this matters more than on community PostgreSQL because a buffer miss becomes a network round trip to the distributed storage layer rather than a local page read.",
        "One old transaction explains a surprising number of simultaneous 'problems' (rising dead tuples, unremovable bloat, growing XID age, lock waits). Always resolve the oldest-transaction finding before concluding anything about vacuum health.",
        "Findings that look alarming in isolation are often expected for an exchange: a high seq_scan count on a small markets/instruments reference table, or a high dead tuple count on an orders table between vacuum cycles, are both normal.",
        "If the instance restarted or failed over recently (script 01), most cumulative counters have been reset and this run is a fresh baseline, not a comparison point.",
    ],
    remediation_immediate=[
        "Triage only what this sweep shows as actively dangerous right now: connection utilization above ~85%, XID age above ~50% of autovacuum_freeze_max_age, a blocking chain on ledger/wallet tables, or a prepared transaction older than a few minutes.",
        "For each such finding, hand off to the dedicated workflow rather than improvising here -- this workflow deliberately stops at detection.",
    ],
    remediation_short_term=[
        "Open a ticket per finding with the captured output attached, ranked by proximity to a hard limit (connections, XID age, storage) rather than by how unusual the number looks.",
        "Re-run the specific sub-check after each remediation so the ticket carries before/after evidence.",
        "Schedule targeted vacuum/analyze for the specific tables this sweep flagged, instead of a blanket database-wide maintenance pass.",
    ],
    remediation_long_term=[
        "Automate this sweep on a schedule and persist the results, so growth and drift become a trend line rather than a series of disconnected snapshots.",
        "Promote the checks that repeatedly find real problems on this cluster into the daily-health-check loop, and the ones that never fire into a quarterly cadence.",
        "Feed the capacity findings (storage growth, connection headroom) into the platform capacity plan ahead of known volume events such as a new listing or a derivatives launch.",
    ],
    production_safety=[
        "Every script in this workflow is strictly read-only: catalog and statistics views only, no DDL, no DML, no session termination, and no ANALYZE/VACUUM of any table.",
        "All scripts execute unmodified on a connection with default_transaction_read_only = on, which makes them safe to run against the writer during an active incident.",
        "Safe to run on a reader instance, with one caveat: pg_stat_activity, pg_locks, and the statistics counters are per-instance, so a reader shows only that reader's own sessions and activity -- run the connection, lock, and query steps on the writer when investigating writer-side behavior.",
        "The heaviest step is the index/size inventory, which reads pg_class and relation-size functions for every relation; on a schema with tens of thousands of partitions this can take several seconds. It still takes no locks beyond brief catalog access.",
    ],
    escalation_criteria=[
        "XID age above 1,000,000,000 in any database, or above 50% of autovacuum_freeze_max_age and still rising between two runs -- escalate immediately to transactions-and-xid/xid-wraparound-risk.",
        "Connection utilization above 90% of max_connections on the writer -- escalate to connections/connection-exhaustion before it becomes a full outage.",
        "A prepared transaction older than a few minutes, or a replication slot retaining tens of gigabytes of WAL -- both silently block cleanup cluster-wide and need an owner identified immediately.",
        "Any finding that implicates the ledger, wallet, or settlement tables' correctness (not just their performance) -- escalate to database engineering and the finance/treasury on-call together.",
    ],
    related_issues=[
        "../daily-health-check/README.md",
        "../capacity-health-check/README.md",
        "../pre-deployment-check/README.md",
        "../../performance/high-database-load/README.md",
        "../../transactions-and-xid/xid-wraparound-risk/README.md",
        "../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md",
        "../../connections/connection-exhaustion/README.md",
        "../../replication-and-ha/replication-health/README.md",
    ],
    aurora_notes=[
        "Aurora readers are not standard streaming replicas: they replay redo from the shared storage volume, so pg_stat_replication is empty on an Aurora writer even when readers exist and are healthy. Reader lag must be read from aurora_replica_status() or the CloudWatch AuroraReplicaLag metric.",
        "An Aurora failover resets in-memory statistics on the promoted instance: pg_stat_database, pg_stat_statements, pg_stat_wal, and pg_stat_checkpointer all restart their accumulation window. Check instance uptime (script 01) before comparing counters against a previous run.",
        "Logical database size as reported by pg_database_size() is not the billed Aurora storage figure -- the cluster volume grows in increments and does not shrink when rows are deleted. Use CloudWatch VolumeBytesUsed for the storage-cost view and these queries for the logical view.",
        "Aurora does not support ALTER SYSTEM for most parameters: every configuration finding from this sweep is remediated through the DB cluster or DB instance parameter group, and some changes require a reboot to take effect.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_instance_identity_and_uptime",
        "Establishes which instance, engine version, and role this session is connected to, and how long the instance has been up.",
        """
-- Context for everything that follows. Two facts matter most before
-- reading any other health metric:
--   1. Writer or reader? pg_stat_activity, pg_locks and most statistics
--      counters are per-instance, so a reader shows only its own sessions.
--   2. How long has this instance been up? Every cumulative counter in
--      this workflow accumulates since the instance started or since the
--      last pg_stat_reset(); a recent Aurora failover silently resets them
--      and makes comparison against a previous health check invalid.
--
-- aurora_version() only exists on Aurora PostgreSQL. Its presence is
-- detected through pg_proc first so this script also runs unmodified on
-- community PostgreSQL 17 (for example, in a local staging environment)
-- instead of failing with "function does not exist".
SELECT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version') AS is_aurora_engine
\\gset

SELECT
    current_database()                                          AS database_name,
    current_user                                                AS connected_as,
    inet_server_addr()                                          AS server_address,
    inet_server_port()                                          AS server_port,
    version()                                                   AS postgresql_version,
    pg_is_in_recovery()                                         AS is_reader_instance,
    pg_postmaster_start_time()                                  AS instance_started_at,
    now() - pg_postmaster_start_time()                          AS instance_uptime,
    current_setting('timezone')                                 AS server_timezone,
    now()                                                       AS health_check_captured_at;

\\if :is_aurora_engine
SELECT aurora_version()                                         AS aurora_engine_version;
\\else
SELECT 'aurora_version() is not available on this server, so this is community '
       'PostgreSQL (or a non-Aurora managed service) rather than Aurora '
       'PostgreSQL. Every script in this workflow still runs, but the '
       'Aurora-specific reader-lag step will report that aurora_replica_status() '
       'is unavailable.'                                        AS notice;
\\endif
""".strip("\n"),
        "An instance_uptime of less than a few hours means a reboot or failover occurred recently: treat this run as a new baseline, because all cumulative counters restarted then. If is_reader_instance is true, do not draw writer-wide conclusions from the connection, lock, or transaction steps -- reconnect to the cluster writer endpoint for those.",
        related_scripts="02_database_and_table_sizes.sql",
        table_purpose="Instance identity, engine version, writer/reader role, and uptime.",
    ),
    sql_script(
        "02", "02_database_and_table_sizes",
        "Captures the logical footprint of every database and the largest tables in the current database.",
        sb.database_sizes() + "\n\n" + sb.largest_tables(),
        "Compare both result sets against the previous health check to derive a growth rate. On an exchange, the expected shape is trades, ledger_entries, order_book_snapshots, and audit/event tables dominating, with reference tables (markets, instruments, fee_tiers) staying small. A reference or configuration table appearing in the largest-tables list is a strong signal of unintended row accumulation or severe bloat.",
        expected_runtime="Low to moderate (seconds; longer on schemas with many thousands of partitions).",
        related_scripts="03_database_activity_counters.sql, ../../database-health/capacity-health-check/README.md",
        table_purpose="Database sizes plus the largest tables by total size.",
    ),
    sql_script(
        "03", "03_database_activity_counters",
        "Cluster-wide throughput, cache efficiency, rollback ratio, deadlock, and temp file counters per database.",
        """
-- High-signal, low-cost cumulative counters for every database. Each value
-- accumulates since stats_reset, so the *rate* (value divided by the time
-- since stats_reset, or the difference between two health-check runs) is
-- what matters -- never the absolute number.
SELECT
    datname                                                      AS database_name,
    numbackends                                                  AS current_backends,
    xact_commit,
    xact_rollback,
    round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 2) AS rollback_pct,
    blks_hit,
    blks_read,
    round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2)  AS cache_hit_pct,
    tup_returned,
    tup_fetched,
    tup_inserted,
    tup_updated,
    tup_deleted,
    conflicts,
    deadlocks,
    temp_files,
    pg_size_pretty(temp_bytes)                                    AS temp_bytes_total,
    checksum_failures,
    stats_reset,
    now() - stats_reset                                           AS counting_window
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY xact_commit + xact_rollback DESC;
""".strip("\n"),
        "cache_hit_pct below ~99% on an OLTP exchange database means the hot working set (open orders, account balances, recent trades) no longer fits in shared_buffers -- on Aurora every miss is a read from the distributed storage layer, so this shows up as latency before it shows up as CPU. A rollback_pct that jumps after a deployment usually means a new code path is failing and retrying rather than a database fault. Any non-zero checksum_failures is a hardware/storage integrity signal and must be escalated to AWS support immediately.",
        related_scripts="04_connection_headroom_and_state.sql",
        table_purpose="Per-database throughput, cache hit ratio, rollbacks, deadlocks, and temp file counters.",
    ),
    sql_script(
        "04", "04_connection_headroom_and_state",
        "Measures connection utilization against max_connections and breaks current sessions down by database and state.",
        sb.max_connections_headroom() + "\n\n" + sb.connections_by_state(),
        "pct_utilized above 85% is the point at which a volatility-driven traffic burst can exhaust connections and lock out the matching engine and withdrawal workers. A large idle count relative to active is normal for a pooled application; a large 'idle in transaction' count is never normal and is investigated in script 05. Remember that max_connections on Aurora is derived from the instance class via the parameter-group formula, so headroom is fixed by instance sizing, not freely tunable.",
        execution_location=WRITER_PREFERRED,
        related_scripts="05_open_transaction_horizon.sql, ../../connections/connection-exhaustion/README.md",
        table_purpose="Connection utilization vs max_connections, and sessions by state.",
    ),
    sql_script(
        "05", "05_open_transaction_horizon",
        "Identifies the oldest open transactions and any outstanding prepared (two-phase commit) transactions.",
        sb.long_running_transactions() + "\n\n" + sb.prepared_transactions(),
        "This is the single most important step to read before scripts 06-09: one old transaction holds back the global vacuum horizon and simultaneously produces rising dead tuples, unreclaimable bloat, growing XID age, and lock waits. An 'idle in transaction' entry is an application bug (a connection checked out of the pool with an open transaction and never committed). Any row at all in the prepared-transactions result on an exchange stack is almost always an abandoned distributed-transaction coordinator entry and must be resolved by its owner -- it blocks cleanup indefinitely and survives reconnects.",
        execution_location=WRITER_PREFERRED,
        related_scripts="06_blocking_and_lock_waits.sql, ../../concurrency-and-locking/long-running-transactions/README.md",
        table_purpose="Oldest open transactions plus outstanding prepared transactions.",
    ),
    sql_script(
        "06", "06_blocking_and_lock_waits",
        "Checks for sessions currently blocked on locks and identifies which sessions are blocking them.",
        sb.blocked_sessions(),
        "An empty result is the expected healthy state and takes one second to confirm. Any blocked session on wallets, ledger_entries, or withdrawals is immediately actionable: those paths are latency-sensitive and user-visible, and a blocking chain there tends to cascade into pool exhaustion as retries queue up behind the original blocker.",
        execution_location=WRITER_PREFERRED,
        related_scripts="07_dead_tuples_and_vacuum_status.sql, ../../concurrency-and-locking/blocked-queries/README.md",
        table_purpose="Currently blocked sessions and their blockers.",
    ),
    sql_script(
        "07", "07_dead_tuples_and_vacuum_status",
        "Ranks tables by dead tuple volume and shows when each was last vacuumed or analyzed.",
        sb.dead_tuples_ranked(),
        "Read dead_tuple_pct together with last_autovacuum. A high percentage with a recent autovacuum means autovacuum is running but losing ground against write volume (a tuning problem). A high percentage with a stale or NULL last_autovacuum means autovacuum is not reaching the table at all (a blocked-vacuum or worker-starvation problem). High churn on order status transitions and balance updates makes orders, wallets, and open_positions the usual occupants of the top of this list.",
        related_scripts="08_autovacuum_activity.sql, ../../vacuum-and-autovacuum/dead-tuples/README.md",
        table_purpose="Tables ranked by dead tuples, with last vacuum/analyze timestamps.",
    ),
    sql_script(
        "08", "08_autovacuum_activity",
        "Shows autovacuum and manual VACUUM workers running right now, with their progress phase.",
        sb.autovacuum_workers_active(),
        "An empty result during a period of heavy write traffic, combined with high dead tuple counts from script 07, suggests autovacuum is starved of workers or is being blocked. Long-running workers on the tables flagged in script 07 are the healthy, expected picture. On PostgreSQL 17 the dead-tuple progress counters are reported in bytes rather than tuple counts, reflecting the TID-store vacuum implementation.",
        execution_location=WRITER_PREFERRED,
        related_scripts="09_transaction_id_age.sql, ../../vacuum-and-autovacuum/vacuum-progress/README.md",
        table_purpose="Currently running vacuum workers and their progress.",
    ),
    sql_script(
        "09", "09_transaction_id_age",
        "Measures transaction ID age per database against the wraparound-protection thresholds.",
        sb.database_transaction_age(),
        "pct_of_freeze_max_age under 50% is comfortable; above 50% and rising between runs means freezing is not keeping pace and needs attention this week, not this quarter. Above 100% means anti-wraparound autovacuum is already mandatory for some relations. The failure mode at the far end is not slowness: PostgreSQL refuses new write transactions to protect data integrity, which on an exchange means trading, deposits, and withdrawals all stop at once.",
        related_scripts="10_top_queries_by_total_time.sql, ../../transactions-and-xid/xid-wraparound-risk/README.md",
        table_purpose="Per-database XID age vs the wraparound thresholds.",
    ),
    sql_script(
        "10", "10_top_queries_by_total_time",
        "Ranks normalized statements by cumulative execution time to show where the database actually spends its time.",
        _pgss_guarded(sb.pgss_top_by_total_time()),
        "Total time, not mean time, is the correct ranking for a health check: a 2ms query executed 50 million times a day costs far more capacity than a 5-second report run twice. Expect the order-placement, order-cancellation, and balance-lookup statements to dominate on an exchange. Anything unexpected in the top five -- an admin query, a reconciliation job, an ORM-generated count(*) -- is a capacity finding worth a ticket even when latency currently looks acceptable.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="11_temp_file_usage.sql, ../../query-optimization/analyze-query-plan/README.md",
        table_purpose="Top statements by cumulative execution time (pg_stat_statements).",
    ),
    sql_script(
        "11", "11_temp_file_usage",
        "Reports cumulative temporary file creation per database, indicating sorts and hashes spilling to disk.",
        sb.temp_file_usage_by_database(),
        "Divide temp_bytes by the counting window to get a rate and compare it with the previous run. A steadily climbing rate means work_mem is undersized for the query shapes now running, or that stale statistics are causing the planner to under-estimate rows and pick a memory-starved plan. Temp file I/O on Aurora is served by local instance storage, which is finite and shared with other operations -- large sustained spills can degrade unrelated queries on the same instance.",
        related_scripts="12_index_usage_overview.sql, ../../query-optimization/temp-file-investigation/README.md",
        table_purpose="Cumulative temp file usage per database.",
    ),
    sql_script(
        "12", "12_index_usage_overview",
        "Inventories index size and scan activity to reveal both unused indexes and heavily relied-upon ones.",
        sb.index_bloat_and_usage(),
        "Large indexes with idx_scan at or near zero are storage and write-amplification overhead on every INSERT and UPDATE -- important on an exchange where the order and ledger write paths are latency-critical. Do not act on a single reading: idx_scan resets on restart and failover, and month-end reconciliation or compliance-reporting indexes may legitimately be unused for weeks. Confirm across at least one full business cycle via tables-and-indexes/unused-indexes before proposing any removal.",
        expected_runtime="Low to moderate (seconds; scales with the number of indexes in the database).",
        related_scripts="13_replication_and_reader_health.sql, ../../tables-and-indexes/unused-indexes/README.md",
        table_purpose="Index size and scan-activity inventory.",
    ),
    sql_script(
        "13", "13_replication_and_reader_health",
        "Reports Aurora cluster replica status and lag from the Aurora-native status function.",
        sb.aurora_replica_status(),
        "Reader lag directly determines how stale a balance or order-history read served from a reader can be. Sub-second lag is the normal Aurora profile; sustained lag above a few seconds means read-your-own-write assumptions in the application are being violated, which on an exchange surfaces as users seeing a deposit credited and then apparently disappearing. If this function is unavailable you are not on Aurora -- use replication-and-ha/replication-health for the standard streaming-replication equivalent.",
        execution_location=ANY_INSTANCE,
        related_scripts="../../replication-and-ha/replication-health/README.md",
        table_purpose="Aurora cluster replica status and lag.",
    ),
]

# ---------------------------------------------------------------------------
# daily-health-check
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="daily-health-check",
    title="Daily Health Check",
    summary=(
        "The lightweight morning sweep an on-call DBA runs every day before the busiest "
        "trading session: current load, connection headroom, the oldest open transaction, "
        "vacuum debt, transaction ID age, the slowest recurring statements, and reader lag. "
        "It is deliberately short enough to complete in a few minutes across every cluster in "
        "the fleet, and deliberately biased toward the small set of conditions that reliably "
        "turn into an exchange-wide incident if left unnoticed for another day."
    ),
    symptoms=[
        "No active symptom -- this is the scheduled daily routine, run at the start of the operational day and again before a known high-volume window (a token listing, a funding-rate settlement, a scheduled derivatives expiry).",
        "Used as the first response to a vague overnight alert that has since cleared and left no obvious trace.",
        "Used as the standing handover artifact between on-call shifts across regions.",
    ],
    business_impact=[
        "Most exchange database outages are slow-moving conditions that were observable for days before they became urgent: vacuum debt, XID age, connection creep, and reader lag all announce themselves well in advance if someone looks daily.",
        "A five-minute daily check that catches a single connection-headroom trend before a volatility spike prevents an outage during exactly the window where trading volume, and therefore revenue and reputational exposure, are highest.",
        "Daily readings build the trend data that make capacity planning an evidence-based conversation instead of a guess.",
    ],
    root_causes=[
        "This workflow detects rather than root-causes: each finding hands off to the dedicated workflow that owns that failure mode.",
        "The recurring day-to-day causes it surfaces are gradual write growth outpacing autovacuum, connection-pool misconfiguration after a deployment, a forgotten batch job holding a transaction open overnight, and reader lag creeping up as writer WAL volume grows.",
    ],
    investigation_strategy=[
        "Take a one-shot snapshot of current activity to see whether anything is abnormal right now.",
        "Check connection headroom, the limit that turns a degradation into a hard outage fastest.",
        "Check the oldest open transaction and any idle-in-transaction sessions, since they silently poison vacuum and locking.",
        "Check vacuum debt on the highest-churn tables.",
        "Check transaction ID age against the wraparound thresholds.",
        "Check the slowest recurring statements for a day-over-day change.",
        "Check reader lag, because read-path staleness is user-visible on an exchange even when the writer looks perfectly healthy.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "pg_stat_statements for the query step (the script prints a notice and continues if it is absent).",
        "Yesterday's output available for comparison -- the value of this workflow is almost entirely in the day-over-day delta, not the absolute readings.",
    ],
    interpretation_guide=[
        "Compare against yesterday first and against absolute thresholds second: a value that has been stable for months is far less interesting than one that moved 20% overnight.",
        "Expect a diurnal and weekly pattern on an exchange (Asian-hours volume, weekend derivatives activity, month-end reconciliation) and take today's reading at the same time of day as yesterday's, or the comparison is meaningless.",
        "If any check crosses its escalation threshold, stop the daily sweep and switch to the dedicated workflow for that condition -- do not finish the checklist first.",
        "A clean daily check is a legitimate, valuable result: record it, because the absence of change is itself the trend data that makes tomorrow's anomaly obvious.",
    ],
    remediation_immediate=[
        "Terminate nothing and change nothing from within this workflow -- it exists to detect and hand off.",
        "For an idle-in-transaction session older than the application's documented maximum transaction duration, notify the owning service team immediately; that is the single most common actionable daily finding.",
    ],
    remediation_short_term=[
        "Raise a ticket for each threshold crossing with the captured output, and re-run the affected step after the fix to confirm the reading has returned to baseline.",
        "Schedule a targeted vacuum/analyze for any table whose vacuum debt has grown for several consecutive days.",
    ],
    remediation_long_term=[
        "Convert each daily check into an automated alert with the threshold this cluster has empirically proven appropriate, so the human daily pass becomes a verification rather than the primary detector.",
        "Track the daily readings in a time series so capacity and vacuum-tuning decisions are driven by trend lines rather than by the most recent incident.",
    ],
    production_safety=[
        "All scripts are strictly read-only and execute unmodified under default_transaction_read_only = on.",
        "Total runtime is a few seconds; this sweep is safe to run during peak trading hours and during an active incident.",
        "Run the connection, transaction, and lock steps against the cluster writer endpoint: on a reader they only describe that reader's own local sessions.",
    ],
    escalation_criteria=[
        "Connection utilization above 85%, or a jump of more than 20 percentage points versus yesterday.",
        "XID age above 50% of autovacuum_freeze_max_age, or any increase that would reach 100% before the next scheduled maintenance window.",
        "A transaction open longer than one hour, or any prepared transaction at all.",
        "Reader lag sustained above the application's read-your-own-write tolerance, since stale balance or order reads on an exchange generate support tickets and regulatory questions.",
    ],
    related_issues=[
        "../comprehensive-health-check/README.md",
        "../capacity-health-check/README.md",
        "../../connections/connection-exhaustion/README.md",
        "../../transactions-and-xid/transaction-age/README.md",
        "../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md",
        "../../replication-and-ha/replication-lag/README.md",
    ],
    aurora_notes=[
        "Run the daily check against the cluster writer endpoint, not an instance endpoint: after a failover the instance endpoint may point at what is now a reader, and the connection/transaction/lock readings would silently describe the wrong instance.",
        "Cumulative counters reset on the promoted instance after an Aurora failover, so a day-over-day comparison across a failover will show apparent drops in every counter -- verify instance uptime before concluding a workload actually decreased.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_current_activity_snapshot",
        "One-shot snapshot of all backends grouped by state and wait event, to see whether anything is abnormal right now.",
        sb.activity_overview(),
        "Read this as a shape, not a number: a healthy exchange writer shows mostly short active queries plus pooled idle connections. A large Lock wait_event_type group, or a longest_txn_runtime measured in minutes, means stop the daily sweep and investigate that first.",
        execution_location=WRITER_PREFERRED,
        required_privileges=PG_MONITOR,
        related_scripts="02_connection_headroom.sql",
        table_purpose="Current backends grouped by state and wait event.",
    ),
    sql_script(
        "02", "02_connection_headroom",
        "Connection utilization against max_connections, plus a breakdown by application and user.",
        sb.max_connections_headroom() + "\n\n" + sb.connections_by_application_and_user(),
        "The per-application breakdown localizes a rising trend to a specific service (matching engine, wallet service, market-data API, reporting) instead of leaving it as an unattributed cluster-level number. A service whose count grew overnight without a deployment is usually leaking connections or has had its pool size changed by an autoscaling event.",
        execution_location=WRITER_PREFERRED,
        related_scripts="03_transaction_and_idle_check.sql, ../../connections/application-connection-analysis/README.md",
        table_purpose="Connection utilization and per-application connection counts.",
    ),
    sql_script(
        "03", "03_transaction_and_idle_check",
        "Finds the oldest open transactions and any sessions sitting idle inside a transaction.",
        sb.long_running_transactions() + "\n\n" + sb.idle_in_transaction_sessions(),
        "An overnight batch job (reconciliation, settlement export, compliance extract) that left a transaction open is the classic daily finding here: it blocks vacuum cluster-wide and inflates XID age for as long as it lives. Note the application_name and client_addr so the owning team can be contacted directly rather than through a broadcast.",
        execution_location=WRITER_PREFERRED,
        related_scripts="04_vacuum_debt_check.sql, ../../connections/idle-in-transaction/README.md",
        table_purpose="Oldest open transactions and idle-in-transaction sessions.",
    ),
    sql_script(
        "04", "04_vacuum_debt_check",
        "Ranks tables by dead tuples and shows when autovacuum last reached each one.",
        sb.dead_tuples_ranked(),
        "Track the same handful of hot tables (orders, wallets, ledger_entries, open_positions) day over day. A table whose dead_tuple_pct rises for three consecutive days is losing the race against its write rate and needs per-table autovacuum tuning before it turns into a bloat and latency problem.",
        related_scripts="05_xid_age_check.sql, ../../vacuum-and-autovacuum/dead-tuples/README.md",
        table_purpose="Vacuum debt by table.",
    ),
    sql_script(
        "05", "05_xid_age_check",
        "Checks transaction ID age per database against the wraparound-protection thresholds.",
        sb.database_transaction_age(),
        "This check exists precisely because XID age moves slowly and predictably: seeing it daily converts a potential emergency into a scheduled task. Record the value each day -- the growth rate tells you how many days of headroom remain, which is the number that actually drives the escalation decision.",
        related_scripts="06_slowest_recurring_statements.sql, ../../transactions-and-xid/xid-wraparound-risk/README.md",
        table_purpose="Per-database XID age vs wraparound thresholds.",
    ),
    sql_script(
        "06", "06_slowest_recurring_statements",
        "Lists the slowest frequently-executed statements by mean execution time.",
        _pgss_guarded(sb.pgss_top_by_mean_time()),
        "The minimum-calls filter keeps one-off migrations and ad-hoc analyst queries out of the list so it reflects the production request path. Compare the top entries and their mean_exec_time with yesterday: a statement that doubled in mean time overnight without a deployment usually means statistics went stale or data volume crossed a plan-choice boundary.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="07_reader_lag_check.sql, ../../query-optimization/query-plan-regression/README.md",
        table_purpose="Slowest frequently-executed statements (pg_stat_statements).",
    ),
    sql_script(
        "07", "07_reader_lag_check",
        "Checks Aurora reader replication status and lag from any instance in the cluster.",
        sb.aurora_replica_status(),
        "Reader lag is the daily check most directly visible to end users: order history, balance, and trade-history reads are usually served from readers on an exchange. Sustained lag above the application's tolerance means either the writer's WAL generation rate has risen or a reader is under-provisioned relative to its read load.",
        related_scripts="../../replication-and-ha/reader-lag-investigation/README.md",
        table_purpose="Aurora reader status and lag.",
    ),
]

# ---------------------------------------------------------------------------
# pre-deployment-check
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="pre-deployment-check",
    title="Pre-Deployment Health Check",
    summary=(
        "The go/no-go gate run in the minutes immediately before a release, schema migration, "
        "or parameter change reaches production. It answers one question: is the database in a "
        "state where this deployment can proceed safely right now? A migration that would take "
        "a millisecond on a quiet cluster can take an AccessExclusiveLock queue hostage and halt "
        "order matching for minutes if it lands while a long transaction, a lock wait, or a "
        "vacuum is already in flight -- this check catches exactly that."
    ),
    symptoms=[
        "No active symptom -- this is a scheduled gate immediately before a deployment window opens.",
        "Run again after an aborted or rolled-back deployment attempt, before retrying.",
        "Run before any change-managed parameter-group change that requires a reboot or failover.",
    ],
    business_impact=[
        "A DDL statement that queues behind a long-running transaction takes an AccessExclusiveLock request that then blocks every subsequent query on that table -- on an orders or wallets table this halts trading and withdrawals within seconds, even though the DDL itself never actually started.",
        "Deploying into an already-degraded database makes root-causing the resulting incident far harder: the team cannot tell whether the deployment caused the problem or merely arrived during it.",
        "A pre-deployment baseline of query performance is what makes the post-deployment comparison meaningful; without it, 'is this slower than before?' is unanswerable.",
    ],
    root_causes=[
        "Not a failure workflow -- these are the pre-existing conditions that make a deployment unsafe at this moment.",
        "A long-running transaction or idle-in-transaction session that a migration's lock request would queue behind, blocking all subsequent traffic to the table.",
        "An in-flight autovacuum on the target table, which holds a ShareUpdateExclusiveLock that conflicts with most ALTER TABLE forms.",
        "Insufficient connection headroom to absorb the connection churn of a rolling application restart.",
        "Elevated reader lag, which a deployment's extra WAL generation will make worse and which breaks read-your-own-write behavior for users mid-deploy.",
    ],
    investigation_strategy=[
        "Confirm no session is currently blocked and no lock wait chain exists.",
        "Check specifically for strong lock modes (ShareUpdateExclusive and above) that a migration would have to queue behind.",
        "Check for long-running and idle-in-transaction sessions that would make a DDL lock request block the world.",
        "Confirm connection headroom is sufficient to absorb a rolling restart of the application fleet.",
        "Confirm reader lag is at its normal baseline before adding deployment write volume.",
        "Confirm no autovacuum or maintenance operation is in flight on the tables the migration will touch.",
        "Capture a query-performance baseline so post-deployment-check has something to compare against.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "The list of tables the deployment's migrations will touch, so the lock and vacuum checks can be read with the right focus.",
        "An agreed abort threshold for each check, decided before the window opens rather than negotiated under time pressure at execution time.",
        "pg_stat_statements for the baseline capture step (optional; the script degrades gracefully).",
    ],
    interpretation_guide=[
        "Treat this as a checklist with pre-agreed veto conditions, not as data to be interpreted creatively while the release train waits.",
        "The most dangerous finding is a long-running transaction combined with a migration that takes a strong lock: PostgreSQL queues the DDL's lock request ahead of all later requests, so the DDL blocks the entire table even while it is still waiting and has done nothing.",
        "An autovacuum worker on the migration's target table is not a reason to abort permanently -- it is a reason to wait for it to finish, or to accept that the migration's lock request will wait for it.",
        "Baseline capture is not a pass/fail check: its only purpose is to make post-deployment-check meaningful, so record it even when everything else is green.",
    ],
    remediation_immediate=[
        "Abort or postpone the deployment if any veto condition is present; the cost of a 30-minute delay is orders of magnitude lower than a lock-storm-induced trading halt.",
        "If a long-running transaction is the only blocker, have the owning team end it and re-run the check rather than proceeding hopefully.",
        "Set an explicit lock_timeout in the migration session (for example `SET lock_timeout = '3s';`) so a migration that cannot acquire its lock quickly fails fast instead of queueing behind traffic and blocking the table.",
    ],
    remediation_short_term=[
        "Reschedule the deployment to a window with lower volume if the check repeatedly finds contention at the usual time.",
        "Split a migration that requires a strong lock into a sequence of individually safe steps (see schema-changes patterns such as concurrent index builds and nullable-column-then-backfill).",
    ],
    remediation_long_term=[
        "Automate this check as a required, blocking stage in the deployment pipeline so an unsafe deployment cannot be started manually at all.",
        "Adopt migration patterns that avoid strong locks entirely on the exchange's hot tables, and make lock_timeout mandatory in every migration tool configuration.",
    ],
    production_safety=[
        "Every script here is read-only and safe to run at any time, including during peak trading.",
        "This check never changes anything: it produces a go/no-go decision and a baseline, nothing more.",
        "Run it against the writer -- a deployment's migrations run on the writer, and lock and transaction state on a reader says nothing about the writer's state.",
    ],
    escalation_criteria=[
        "Any blocked session already exists before the deployment starts -- do not add a migration on top of an existing lock chain.",
        "A transaction has been open longer than the migration's lock_timeout budget and its owner cannot be reached.",
        "Connection utilization above 80%, leaving no room for the connection churn of a rolling restart.",
        "Reader lag above its normal baseline, or a failover in the last few minutes -- let the cluster stabilize first.",
    ],
    related_issues=[
        "../post-deployment-check/README.md",
        "../pre-maintenance-check/README.md",
        "../comprehensive-health-check/README.md",
        "../../concurrency-and-locking/ddl-blocking/README.md",
        "../../concurrency-and-locking/long-running-transactions/README.md",
        "../../performance/performance-after-deployment/README.md",
    ],
    aurora_notes=[
        "Aurora applies most parameter-group changes only after a reboot, and a reboot of the writer triggers a failover in a multi-instance cluster -- treat any parameter change in the deployment as a failover event and run failover-readiness checks as well.",
        "Aurora's fast DDL (in-place ALTER TABLE ... ADD COLUMN for some cases) does not remove the need for the lock: the statement still requires an AccessExclusiveLock briefly, so it must still acquire it ahead of production traffic.",
        "Because Aurora readers replay redo from shared storage, a heavy migration on the writer raises reader lag for the duration -- check the lag baseline before starting so the increase can be attributed correctly.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_blocking_and_lock_waits",
        "Confirms no session is currently blocked on a lock before the deployment starts.",
        sb.blocked_sessions(),
        "An empty result is the required pass condition. Any existing blocking chain is an automatic no-go: adding a migration's lock request to an already-congested queue is how a routine deployment becomes a trading halt.",
        execution_location=WRITER_PREFERRED,
        related_scripts="02_strong_lock_modes_held.sql",
        table_purpose="Currently blocked sessions and their blockers.",
    ),
    sql_script(
        "02", "02_strong_lock_modes_held",
        "Checks for ShareUpdateExclusive and stronger locks that a migration would have to queue behind.",
        sb.ddl_lock_waits(),
        "These are exactly the lock modes that conflict with DDL. A granted ShareUpdateExclusiveLock is usually an autovacuum worker or an in-flight concurrent index build; a granted AccessExclusiveLock means another DDL statement is already running and this deployment must wait. Match the relation names against the migration's target tables before deciding.",
        execution_location=WRITER_PREFERRED,
        related_scripts="03_long_running_transactions.sql, ../../concurrency-and-locking/ddl-blocking/README.md",
        table_purpose="Strong lock modes currently held or waiting.",
    ),
    sql_script(
        "03", "03_long_running_transactions",
        "Identifies open transactions that a DDL lock request would queue behind.",
        sb.long_running_transactions() + "\n\n" + sb.idle_in_transaction_sessions(),
        "This is the single highest-value pre-deployment check. A migration needing an AccessExclusiveLock cannot acquire it until every existing transaction touching that table commits -- and while it waits, all newly arriving queries on that table queue behind it. One forgotten reconciliation transaction can therefore convert a millisecond ALTER into a multi-minute outage on the orders table.",
        execution_location=WRITER_PREFERRED,
        related_scripts="04_connection_headroom.sql, ../../concurrency-and-locking/long-running-transactions/README.md",
        table_purpose="Open and idle-in-transaction sessions that would block DDL.",
    ),
    sql_script(
        "04", "04_connection_headroom",
        "Verifies there is enough connection headroom for a rolling restart of the application fleet.",
        sb.max_connections_headroom() + "\n\n" + sb.connections_by_application_and_user(),
        "A rolling restart briefly doubles a service's connection count as new pods warm their pools before old ones drain. Headroom below roughly 20% means the deployment can exhaust connections mid-roll, at which point neither the old nor the new version can serve traffic and the rollback path itself needs connections it cannot get.",
        execution_location=WRITER_PREFERRED,
        related_scripts="05_replication_lag_baseline.sql, ../../connections/connection-pooling/README.md",
        table_purpose="Connection headroom and per-application connection counts.",
    ),
    sql_script(
        "05", "05_replication_lag_baseline",
        "Records the current Aurora reader lag as the pre-deployment baseline.",
        sb.aurora_replica_status(),
        "Record these values verbatim: post-deployment-check compares against them. Starting a deployment while lag is already elevated means the migration's additional WAL will push reader staleness past the point where balance and order-history reads served from readers become visibly wrong to users.",
        related_scripts="06_maintenance_in_flight.sql, ../../replication-and-ha/replication-lag/README.md",
        table_purpose="Reader lag baseline before deployment.",
    ),
    sql_script(
        "06", "06_maintenance_in_flight",
        "Checks whether autovacuum or a manual maintenance operation is currently running on any table.",
        sb.autovacuum_workers_active(),
        "An autovacuum worker holds a ShareUpdateExclusiveLock on its table for the duration, which conflicts with most ALTER TABLE forms and with CREATE INDEX. If a worker is running on a table this deployment migrates, either wait for it to finish or accept that the migration will block until it does -- and remember that anti-wraparound autovacuum must never be cancelled to make room for a deployment.",
        execution_location=WRITER_PREFERRED,
        related_scripts="07_query_performance_baseline.sql, ../../vacuum-and-autovacuum/vacuum-progress/README.md",
        table_purpose="In-flight vacuum/maintenance operations.",
    ),
    sql_script(
        "07", "07_query_performance_baseline",
        "Captures the pre-deployment query performance baseline for later comparison.",
        _pgss_guarded(sb.pgss_top_by_total_time()),
        "Save this output with the deployment ticket. After the release, post-deployment-check re-runs the same query and the comparison answers 'did this deployment make anything slower?' objectively. Note the exact capture time and whether pg_stat_statements was reset recently, since the counters are cumulative and a reset between the two captures invalidates the comparison.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="../post-deployment-check/README.md",
        table_purpose="Pre-deployment top-query baseline (pg_stat_statements).",
    ),
]

# ---------------------------------------------------------------------------
# post-deployment-check
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="post-deployment-check",
    title="Post-Deployment Health Check",
    summary=(
        "The verification sweep run in the first minutes and hours after a release reaches "
        "production, designed to catch the specific damage a deployment can do to a database: "
        "query plan regressions from new or changed statements, a rising rollback rate from "
        "failing code paths, newly dominant sequential scans, invalid indexes left by a failed "
        "concurrent build, stale statistics after a data migration, connection-pool behavior "
        "changes, and new lock contention. Its purpose is to detect a bad release while rolling "
        "back is still cheap."
    ),
    symptoms=[
        "A deployment has just completed and its database-side impact has not yet been verified.",
        "Latency, error rate, or CPU has risen since a release, but the application team reports no code path as obviously broken.",
        "A migration reported success, but it is not confirmed that every index it created is actually valid and being used.",
    ],
    business_impact=[
        "A query plan regression introduced by a release degrades the order or balance path continuously until it is found -- with an exchange's request volume, that is thousands of affected user actions per minute.",
        "An invalid index left behind by an interrupted CREATE INDEX CONCURRENTLY silently removes the plan the application depends on, converting an indexed lookup into a sequential scan on a table with hundreds of millions of rows.",
        "Detecting a regression inside the rollback window turns a potential multi-hour incident into a five-minute revert; detecting it the next day usually means fixing forward under pressure.",
    ],
    root_causes=[
        "A new or modified query whose plan is fine on a small staging dataset and catastrophic on production data volumes.",
        "A schema migration that invalidated planner assumptions (new column, changed type, dropped or added index) without a follow-up ANALYZE.",
        "A failed or interrupted CREATE INDEX CONCURRENTLY leaving an INVALID index that the planner ignores.",
        "A connection-pool configuration change shipped alongside the application change, altering connection count or transaction lifetime.",
        "A bulk backfill run as part of the release, leaving both stale statistics and a large volume of dead tuples behind.",
        "New transaction boundaries in the application code producing lock contention patterns the previous version never created.",
    ],
    investigation_strategy=[
        "Check the error and rollback rate first -- it is the fastest signal that a code path is failing rather than merely slow.",
        "Compare top statements by mean and total time against the pre-deployment baseline captured by pre-deployment-check.",
        "Look for newly high-frequency statements, which reveal N+1 patterns or retry storms introduced by the release.",
        "Look for tables that have suddenly become sequential-scan dominated, the classic signature of a lost or unused index.",
        "Check for invalid indexes produced by the migration.",
        "Check statistics freshness on any table the migration modified in bulk.",
        "Check connection behavior and lock contention for changes attributable to the new version.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "The pre-deployment baseline output from pre-deployment-check script 07, without which the query comparison is guesswork.",
        "The migration's change list (tables, indexes, backfills) so the checks can be focused rather than exploratory.",
        "pg_stat_statements, ideally not reset between the baseline capture and this run.",
    ],
    interpretation_guide=[
        "pg_stat_statements counters are cumulative since stats_reset, so a newly deployed statement's mean_exec_time is trustworthy immediately, while a pre-existing statement's mean is diluted by all its executions before the release -- watch for a rising max_exec_time and stddev_exec_time on pre-existing statements rather than expecting the mean to move quickly.",
        "A brand-new queryid appearing at the top of the total-time list is expected after a release; the question is whether its cost is proportionate to what the feature does.",
        "A rollback_pct increase that starts exactly at the deployment timestamp is almost always application errors, not database faults -- route it to the deploying team with the evidence rather than investigating database internals.",
        "A table that has just started accumulating sequential scans is a stronger and faster signal than any latency metric, because it points directly at the lost access path.",
        "Give autoanalyze time: immediately after a bulk backfill, statistics are stale by definition. Stale statistics found five minutes after a migration are a reason to run a targeted ANALYZE, not evidence of a systemic problem.",
    ],
    remediation_immediate=[
        "If a regression is confirmed and the rollback window is still open, roll back the deployment first and investigate afterwards.",
        "If an invalid index is found, the application is currently running without that access path -- treat it as an active incident and plan an immediate concurrent rebuild.",
        "Run a targeted ANALYZE on the specific tables a bulk migration touched (a guarded, change-managed action -- see vacuum-and-autovacuum/analyze-statistics for the runbook), never a blind database-wide ANALYZE.",
    ],
    remediation_short_term=[
        "File the specific regressed statement with its queryid, its baseline numbers, and its current numbers to the owning team.",
        "Rebuild any invalid index with CREATE INDEX CONCURRENTLY / REINDEX CONCURRENTLY during a low-traffic window, following the schema-changes runbook.",
        "Add the newly discovered regression shape to the pre-deployment review checklist so the next release catches it before shipping.",
    ],
    remediation_long_term=[
        "Automate the baseline-versus-post comparison in the deployment pipeline and fail the release automatically on a defined regression threshold.",
        "Require a representative production-scale dataset for query plan validation in the pre-production environment, because plan differences between a small staging dataset and a production-scale exchange table are the root cause of most of these regressions.",
        "Make a post-migration ANALYZE a mandatory, automated step of every migration that backfills or bulk-updates data.",
    ],
    production_safety=[
        "Every script here is read-only; none of them runs ANALYZE, DDL, or any write.",
        "Safe during peak trading; the heaviest step is the index and sequential-scan inventory, which only reads catalogs and statistics views.",
        "Remediating a finding (ANALYZE, index rebuild) is explicitly out of scope for these scripts and is handled by the referenced guarded runbooks so that a human decides when it happens.",
    ],
    escalation_criteria=[
        "Any statement on the order-placement, balance-check, withdrawal, or settlement path is measurably slower than its pre-deployment baseline -- escalate to the deploying team immediately and evaluate rollback.",
        "An invalid index exists on a hot table -- the application is running without an expected access path right now.",
        "The rollback rate rose sharply at the deployment timestamp, indicating failing transactions rather than slow ones.",
        "New lock contention appears on ledger or wallet tables, which risks financial-operation delays and not merely latency.",
    ],
    related_issues=[
        "../pre-deployment-check/README.md",
        "../comprehensive-health-check/README.md",
        "../../performance/performance-after-deployment/README.md",
        "../../performance/query-regression/README.md",
        "../../query-optimization/query-plan-regression/README.md",
        "../../query-optimization/stale-statistics/README.md",
        "../../tables-and-indexes/invalid-indexes/README.md",
    ],
    aurora_notes=[
        "If the deployment included a parameter-group change requiring a reboot, the resulting failover reset pg_stat_statements and pg_stat_database on the promoted instance -- the pre-deployment baseline is then no longer comparable and must be rebuilt from application-side metrics instead.",
        "Aurora readers serve much of an exchange's read traffic; after a deployment, verify reader-side query behavior too, since a plan regression on a read-only reporting query only manifests on the readers.",
        "Aurora's shared storage means an index rebuild consumes cluster volume that is never returned when the old index is dropped -- factor that into the storage impact of any post-deployment index remediation.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_error_and_rollback_rates",
        "Compares commit and rollback counters plus deadlock and conflict counts to detect failing code paths.",
        """
-- Transaction outcome counters per database. A release that introduces a
-- failing code path shows up here as a rollback_pct increase long before
-- it shows up in latency metrics, because failing transactions are usually
-- fast transactions.
--
-- These counters are cumulative since stats_reset, so the absolute values
-- are not meaningful on their own: capture this immediately before and
-- after the deployment, or divide by the counting window to get a rate.
SELECT
    datname                                                      AS database_name,
    xact_commit,
    xact_rollback,
    round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 3) AS rollback_pct,
    deadlocks,
    conflicts,
    temp_files,
    pg_size_pretty(temp_bytes)                                    AS temp_bytes_total,
    round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2)  AS cache_hit_pct,
    stats_reset,
    now() - stats_reset                                           AS counting_window,
    round(
        (xact_commit + xact_rollback)::numeric /
        NULLIF(EXTRACT(epoch FROM (now() - stats_reset)), 0),
        2
    )                                                             AS avg_txn_per_second
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY xact_commit + xact_rollback DESC;
""".strip("\n"),
        "A rollback_pct that steps up at the deployment timestamp means transactions are failing, which is an application-code finding to route to the deploying team, not a database tuning problem. A rising deadlocks count after a release means the new version changed lock acquisition order -- on ledger and wallet tables this risks silently dropped financial writes if the application's retry logic is not correct.",
        related_scripts="02_query_performance_vs_baseline.sql",
        table_purpose="Commit/rollback ratio, deadlocks, and throughput per database.",
    ),
    sql_script(
        "02", "02_query_performance_vs_baseline",
        "Re-captures top statements by total time for direct comparison against the pre-deployment baseline.",
        _pgss_guarded(sb.pgss_top_by_total_time()),
        "Compare row by row against pre-deployment-check script 07. A pre-existing queryid whose total_exec_time share grew disproportionately, or a new queryid that immediately dominates, is the regression. Confirm stats_reset has not changed between the two captures -- if it has (for example because the deployment triggered a failover), this comparison is invalid and must be replaced with application-side latency metrics.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ + " The pre-deployment baseline from pre-deployment-check script 07 is required for the comparison.",
        related_scripts="03_new_and_high_frequency_statements.sql, ../pre-deployment-check/README.md",
        table_purpose="Post-deployment top statements, for baseline comparison.",
    ),
    sql_script(
        "03", "03_new_and_high_frequency_statements",
        "Ranks statements by call count to expose N+1 patterns and retry storms introduced by the release.",
        _pgss_guarded(sb.pgss_top_by_calls()),
        "A statement whose call count exploded after the release is usually an N+1 access pattern (one query per row of a result set) or a client-side retry loop reacting to an error. Both are cheap individually and devastating in aggregate: at exchange request volumes, a per-row lookup added to the order-book read path can add tens of thousands of statements per second.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="04_sequential_scan_regression.sql",
        table_purpose="Highest-frequency statements after the deployment.",
    ),
    sql_script(
        "04", "04_sequential_scan_regression",
        "Finds tables where sequential scans now dominate, the signature of a lost or unusable index.",
        sb.sequential_scan_heavy_tables(),
        "A large table with a high and newly growing seq_tup_read is the clearest post-deployment red flag: the access path the application relied on is gone or is no longer chosen. Compare seq_scan against idx_scan for the tables the migration touched. Small reference tables such as markets or fee_tiers appearing here is normal and not a finding.",
        related_scripts="05_invalid_indexes.sql, ../../tables-and-indexes/sequential-scan-investigation/README.md",
        table_purpose="Tables newly dominated by sequential scans.",
    ),
    sql_script(
        "05", "05_invalid_indexes",
        "Detects indexes left in an INVALID state by a failed or interrupted concurrent build.",
        sb.invalid_indexes(),
        "Any row here means the planner is ignoring that index while it still costs write overhead and storage on every insert and update. On an exchange hot table this is an active incident, not a cleanup task: the queries that depended on it are running without it right now. An invalid index must be dropped and rebuilt concurrently -- it cannot be validated in place.",
        related_scripts="06_statistics_freshness.sql, ../../tables-and-indexes/invalid-indexes/README.md",
        table_purpose="Invalid indexes left behind by failed concurrent builds.",
    ),
    sql_script(
        "06", "06_statistics_freshness",
        "Checks how stale planner statistics are on tables the migration modified in bulk.",
        sb.statistics_freshness(),
        "A migration that backfilled or bulk-updated rows leaves n_mod_since_analyze high and last_analyze stale, so the planner is choosing plans from a picture of the data that no longer exists. This is the most common cause of a plan regression that appears minutes after a successful migration. The fix is a targeted ANALYZE on those tables, executed as a change-managed action.",
        related_scripts="07_connection_and_lock_behavior.sql, ../../query-optimization/stale-statistics/README.md",
        table_purpose="Statistics staleness after the migration.",
    ),
    sql_script(
        "07", "07_connection_and_lock_behavior",
        "Compares per-application connection counts and checks for new lock contention after the release.",
        sb.connections_by_application_and_user() + "\n\n" + sb.blocked_sessions(),
        "A changed connection count for the deployed service usually means its pool configuration changed with the release -- verify that was intentional. New blocking chains that did not exist before the deployment indicate the new version changed transaction boundaries or lock ordering; on wallets and ledger_entries that is a financial-operation risk and warrants immediate escalation rather than monitoring.",
        execution_location=WRITER_PREFERRED,
        related_scripts="../../concurrency-and-locking/blocked-queries/README.md",
        table_purpose="Connection mix and new lock contention after deployment.",
    ),
]

# ---------------------------------------------------------------------------
# pre-maintenance-check
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="pre-maintenance-check",
    title="Pre-Maintenance Health Check",
    summary=(
        "The go/no-go baseline captured immediately before a planned infrastructure "
        "operation -- a failover test, an instance class resize, a major engine version "
        "upgrade, or an extension version upgrade -- rather than an application deployment. "
        "It answers 'is it safe to start this operation now, and what does healthy look like "
        "so we can tell whether the operation itself introduced a regression?' A resize or "
        "major-version upgrade forces a writer restart (and therefore a failover in a "
        "multi-instance cluster); starting one while a transaction is open, a vacuum is "
        "mid-flight, or a reader is already lagging turns a planned few minutes of downtime "
        "into an extended incident."
    ),
    symptoms=[
        "No active symptom -- this is a scheduled gate run in the minutes before a maintenance window opens (failover drill, instance resize, major version upgrade, extension upgrade, parameter-group change requiring a reboot).",
        "Run again after an aborted maintenance attempt, before retrying.",
        "Used as the evidence baseline attached to the maintenance ticket so post-maintenance-check has something concrete to compare against.",
    ],
    business_impact=[
        "A major version upgrade or instance resize forces the writer to restart; if that restart lands while a long transaction or an anti-wraparound autovacuum is in flight, recovery after the restart takes measurably longer and the trading halt extends well past the announced window.",
        "Starting maintenance while a reader is already lagging compounds the outage: readers briefly fall further behind during the writer restart, and an already-elevated baseline means the recovery tail is longer and read-your-own-write violations last longer for users.",
        "Without a captured pre-maintenance baseline, the team cannot distinguish 'this is a known side effect of the maintenance operation' from 'this is a new regression the operation introduced', which turns every maintenance window into a debugging exercise.",
    ],
    root_causes=[
        "Not a failure workflow -- these are the pre-existing conditions that make starting maintenance right now unsafe, or that need to be recorded before it starts.",
        "A long-running transaction or prepared transaction that the restart will forcibly abort, leaving its owning service to handle an unexpected disconnection instead of a clean commit/rollback.",
        "An in-flight autovacuum (especially an anti-wraparound vacuum) that a restart interrupts, forcing it to restart its scan from the beginning afterward.",
        "Reader lag or connection headroom already outside normal bounds before the operation even begins, which the maintenance operation itself will make temporarily worse.",
    ],
    investigation_strategy=[
        "Confirm cluster topology and instance uptime, so it is clear which instance is the current writer and how long it has been running.",
        "Check connection headroom and the per-application connection mix, since the operation will force a reconnect storm.",
        "Check for long-running transactions and prepared transactions that the restart would forcibly abort.",
        "Record the current Aurora reader lag as the pre-maintenance baseline.",
        "Check whether autovacuum (especially anti-wraparound autovacuum) is currently running on any table.",
        "Snapshot key configuration settings and the installed extension inventory, so post-maintenance-check can confirm nothing drifted unexpectedly.",
        "Capture a query-performance baseline for the post-maintenance comparison.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "The maintenance change record (what operation, on which instance(s), and the announced window) so findings can be read in that context.",
        "An agreed abort/reschedule threshold for each check, decided before the window opens.",
        "pg_stat_statements for the baseline capture step (optional; the script degrades gracefully with a notice if absent).",
    ],
    interpretation_guide=[
        "Treat this as a pre-agreed checklist with veto conditions, the same discipline as pre-deployment-check, but the trigger here is an infrastructure operation rather than an application release.",
        "A long transaction or an in-flight anti-wraparound autovacuum is not merely inconvenient here -- the restart will abort or interrupt it outright, so the finding is 'this work will be lost/interrupted', not just 'this might block something'.",
        "Reader lag already above baseline before the operation starts is a strong signal to delay: the operation will add to it, not just coexist with it.",
        "The settings/extension snapshot and query-performance baseline are not pass/fail checks -- their only purpose is to make post-maintenance-check's comparison meaningful, so capture them even when every other check is green.",
    ],
    remediation_immediate=[
        "Postpone the maintenance window if any veto condition is present -- an extra day's delay is far cheaper than an extended trading halt caused by starting mid-transaction.",
        "If a long transaction or prepared transaction is the only blocker, have its owning team resolve it and re-run this check before proceeding.",
        "If reader lag is already elevated, wait for it to return to baseline before starting an operation that will add to it.",
    ],
    remediation_short_term=[
        "Reschedule recurring maintenance windows away from the times this check repeatedly finds contention (e.g. batch/reconciliation job overlap).",
        "Coordinate with the owning teams of any long-lived transaction or job in advance of the next maintenance window rather than discovering it at execution time.",
    ],
    remediation_long_term=[
        "Automate this check as a required, blocking pre-check in the maintenance runbook/automation tooling so an unsafe window cannot be started manually.",
        "Track pre-maintenance baselines over time to see whether reader lag, connection headroom, or vacuum debt are trending toward being a recurring blocker.",
    ],
    production_safety=[
        "Every script in this workflow is strictly read-only and safe to run at any time, including immediately before an active maintenance window.",
        "This check never changes anything: it produces a go/no-go decision and a baseline, nothing more.",
        "Run it against the writer for transaction/connection/vacuum state; run the replication check from any instance since aurora_replica_status() is cluster-wide.",
    ],
    escalation_criteria=[
        "Any transaction open longer than a few minutes, or any prepared transaction at all, with no owner reachable before the window opens.",
        "An anti-wraparound autovacuum currently running on a large table -- interrupting it via restart means it restarts its scan from the beginning afterward.",
        "Reader lag already above the application's normal tolerance, or a failover in the last few minutes -- let the cluster stabilize first.",
        "Connection utilization above 80%, leaving no headroom for the reconnect storm the operation will cause.",
    ],
    related_issues=[
        "../post-maintenance-check/README.md",
        "../pre-deployment-check/README.md",
        "../comprehensive-health-check/README.md",
        "../../replication-and-ha/failover-readiness/README.md",
        "../../disaster-recovery/cluster-failover-drill/README.md",
        "../../vacuum-and-autovacuum/vacuum-progress/README.md",
        "../../concurrency-and-locking/long-running-transactions/README.md",
    ],
    aurora_notes=[
        "Aurora applies most parameter-group changes, and every engine major-version upgrade, only via a reboot -- a reboot of the writer is a failover in a multi-instance cluster, so treat any such maintenance as a failover event and run replication-and-ha/failover-readiness alongside this check.",
        "An in-progress anti-wraparound autovacuum does not block a requested reboot/failover from proceeding, but the restart discards its progress; the vacuum restarts from scratch afterward, so a table that was close to finishing will still show high XID age immediately post-maintenance.",
        "Aurora minor version upgrades can sometimes apply without a reboot depending on the specific version jump; confirm the specific upgrade path's restart behavior in the AWS documentation for the target engine version before assuming zero downtime.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_instance_topology_and_uptime",
        "Confirms current writer/reader topology and instance uptime before starting the maintenance operation.",
        sb.cluster_recovery_role() + "\n\n" + sb.aurora_replica_status(),
        "Confirm which instance the maintenance operation targets, and that the cluster topology matches what the maintenance plan expects (correct number of readers, none already in an unexpected state). A short instance_uptime on any member going into a planned maintenance window usually means an unplanned event already happened recently and should be understood before adding a second one.",
        related_scripts="02_connection_headroom_and_mix.sql",
        table_purpose="Writer/reader role and Aurora cluster topology/lag.",
    ),
    sql_script(
        "02", "02_connection_headroom_and_mix",
        "Checks connection headroom and per-application connection mix before the reconnect storm a restart causes.",
        sb.max_connections_headroom() + "\n\n" + sb.connections_by_application_and_user(),
        "A restart drops every existing connection at once; every application pool then reconnects within roughly the same short window. Headroom below about 20% before the operation starts means that reconnect storm alone can exhaust connections, independent of anything else the maintenance changes.",
        execution_location=WRITER_PREFERRED,
        related_scripts="03_open_transactions_and_prepared.sql, ../../connections/connection-pooling/README.md",
        table_purpose="Connection headroom and per-application connection counts.",
    ),
    sql_script(
        "03", "03_open_transactions_and_prepared",
        "Identifies long-running transactions and prepared transactions the restart would forcibly abort.",
        sb.long_running_transactions() + "\n\n" + sb.prepared_transactions(),
        "A restart does not wait for open transactions to finish -- it terminates every backend. A long transaction found here will be aborted mid-flight rather than given the chance to commit or roll back cleanly, which its owning service needs to handle. A prepared transaction is worse: it is a two-phase-commit entry expected to survive a restart, and its coordinator may not correctly resume it after the instance comes back.",
        execution_location=WRITER_PREFERRED,
        related_scripts="04_replication_lag_baseline.sql, ../../concurrency-and-locking/long-running-transactions/README.md",
        table_purpose="Open and prepared transactions that a restart would interrupt.",
    ),
    sql_script(
        "04", "04_replication_lag_baseline",
        "Records the current Aurora reader lag as the pre-maintenance baseline.",
        sb.aurora_replica_status(),
        "Save this output verbatim -- post-maintenance-check compares against it. Starting an operation while lag is already elevated means the brief additional replication disruption the operation causes stacks on top of an already-degraded baseline, extending the time before reads served from readers are trustworthy again.",
        related_scripts="05_vacuum_and_xid_status.sql, ../../replication-and-ha/replication-lag/README.md",
        table_purpose="Reader lag baseline before maintenance.",
    ),
    sql_script(
        "05", "05_vacuum_and_xid_status",
        "Checks for in-flight autovacuum (including anti-wraparound autovacuum) and current transaction ID age.",
        sb.autovacuum_workers_active() + "\n\n" + sb.database_transaction_age(),
        "An anti-wraparound autovacuum currently running on a large table is the strongest reason to delay a restart: interrupting it discards its progress, and it restarts its scan from the beginning afterward. If XID age is already elevated (above roughly 50% of autovacuum_freeze_max_age) going into the window, factor the lost vacuum progress into how soon the next maintenance window needs to happen.",
        execution_location=WRITER_PREFERRED,
        related_scripts="06_settings_and_extension_baseline.sql, ../../vacuum-and-autovacuum/vacuum-progress/README.md",
        table_purpose="In-flight vacuum workers and per-database XID age.",
    ),
    sql_script(
        "06", "06_settings_and_extension_baseline",
        "Captures the current configuration settings and installed extension inventory as a pre-maintenance baseline.",
        sb.key_settings_snapshot() + "\n\n" + sb.extension_inventory(),
        "Save this output with the maintenance ticket. It is the reference point post-maintenance-check uses to confirm a parameter-group change took effect as intended, or that a major-version/extension upgrade did not silently change a setting's effective value or an extension's version.",
        related_scripts="07_query_performance_baseline.sql",
        table_purpose="Configuration settings and extension inventory baseline.",
    ),
    sql_script(
        "07", "07_query_performance_baseline",
        "Captures the pre-maintenance query performance baseline for later comparison.",
        _pgss_guarded(sb.pgss_top_by_total_time()),
        "Save this output with the maintenance ticket. After the operation, post-maintenance-check re-runs the same query and the comparison shows whether the maintenance (for example, a major version upgrade changing the planner's behavior) changed query performance, independent of any application change.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="../post-maintenance-check/README.md",
        table_purpose="Pre-maintenance top-query baseline (pg_stat_statements).",
    ),
]

# ---------------------------------------------------------------------------
# post-maintenance-check
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="post-maintenance-check",
    title="Post-Maintenance Health Check",
    summary=(
        "The verification sweep run immediately after a planned infrastructure operation -- a "
        "failover test, an instance class resize, a major engine version upgrade, or an "
        "extension version upgrade -- completes. Its purpose is to confirm the cluster came "
        "back in the expected topology and configuration, that replication and connections "
        "recovered fully, that no vacuum/XID regression was introduced by an interrupted "
        "autovacuum, and that query performance did not silently change, before declaring the "
        "maintenance window closed."
    ),
    symptoms=[
        "A planned maintenance operation has just completed and its impact has not yet been verified.",
        "The maintenance operation reported success, but application-side latency or error rate looks different than before the window.",
        "A major version upgrade or extension upgrade just finished and configuration/extension versions need to be confirmed against expectations.",
    ],
    business_impact=[
        "A restart that interrupted an anti-wraparound autovacuum leaves that table's XID age exactly where it was, or worse, immediately after maintenance -- undetected, this compounds with the next maintenance window's own disruption.",
        "A major version upgrade can silently change planner defaults or a parameter's effective value; undetected, this produces a query plan regression on the ledger or order-book path that looks like a random performance incident days later, disconnected from the maintenance event that actually caused it.",
        "Declaring a maintenance window closed while reader lag has not fully recovered leaves users seeing stale balances or order history for longer than necessary, with no one aware it is still an open issue.",
    ],
    root_causes=[
        "This workflow verifies rather than root-causes: each finding hands off to the dedicated workflow that owns that failure mode.",
        "A restart interrupting an in-flight anti-wraparound autovacuum, leaving XID age unimproved or elevated.",
        "A major version upgrade or parameter-group change altering a planner setting, default, or extension version from what was expected.",
        "A reconnect storm after the restart leaving the connection pool in an unexpected state (some pools not recovering cleanly).",
        "Slower-than-normal reader catch-up after the writer restart, especially on a cluster with high WAL generation.",
    ],
    investigation_strategy=[
        "Confirm instance topology and uptime reflect the maintenance event as expected (correct instance now the writer, uptime consistent with the restart time).",
        "Check Aurora reader lag against the pre-maintenance baseline to confirm full recovery.",
        "Check connection headroom and mix to confirm the application fleet reconnected cleanly.",
        "Check for any blocked sessions or lock contention immediately after the restart.",
        "Check vacuum and transaction ID age to confirm no regression from an interrupted autovacuum.",
        "Verify configuration settings and extension versions against the pre-maintenance baseline.",
        "Compare query performance against the pre-maintenance baseline.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "The pre-maintenance baseline output from pre-maintenance-check, without which several of these comparisons are guesswork.",
        "The maintenance change record describing exactly what was expected to change (settings, extension versions, instance class).",
        "pg_stat_statements, ideally not reset between the baseline capture and this run (note that a major version upgrade or extension upgrade may reset it regardless).",
    ],
    interpretation_guide=[
        "Compare every finding against the specific pre-maintenance baseline captured for this window, not against a generic 'healthy' number -- the question is whether this operation changed anything, not whether the cluster looks healthy in the abstract.",
        "Some cumulative counters (pg_stat_statements, pg_stat_database) reset on a restart by design -- a 'regression' that is actually just a fresh counting window since the restart is not a finding, it is expected. Check stats_reset before concluding anything from a counter comparison.",
        "A settings or extension-version difference from the baseline that was not part of the planned change is the most actionable finding this workflow can produce -- it usually means the operation had a side effect nobody planned for.",
        "Give reader lag a few minutes to catch up after a restart before treating elevated lag as a finding; the concerning case is lag that is not converging back toward baseline after a reasonable interval, not a brief spike immediately after recovery.",
    ],
    remediation_immediate=[
        "If a settings or extension-version drift is found that was not part of the planned change, correct it in the parameter group and document why it happened before closing the maintenance ticket.",
        "If reader lag is not converging after a reasonable interval, escalate to replication-and-ha/reader-lag-investigation rather than waiting indefinitely.",
        "If XID age did not improve as expected because an anti-wraparound autovacuum was interrupted, confirm autovacuum has resumed on the affected table and is progressing.",
    ],
    remediation_short_term=[
        "File the specific regressed statement (if any) with its baseline and post-maintenance numbers to the team that requested the maintenance.",
        "Update the maintenance runbook with any unexpected side effect found, so the next occurrence of this operation anticipates it.",
    ],
    remediation_long_term=[
        "Automate the baseline-versus-post comparison for recurring maintenance operations (e.g. scheduled failover drills) so it runs and reports automatically rather than depending on someone remembering to check.",
        "Feed configuration and extension-version drift findings back into infrastructure-as-code so the parameter group definition matches what is actually running.",
    ],
    production_safety=[
        "Every script here is read-only; none of them runs DDL, VACUUM, or any write.",
        "Safe to run immediately after maintenance completes, including during the tail end of an announced maintenance window.",
        "Remediating a finding (parameter-group correction, index rebuild, vacuum) is out of scope for these scripts and is handled by the referenced dedicated runbooks.",
    ],
    escalation_criteria=[
        "Reader lag has not started converging back toward the pre-maintenance baseline within the expected recovery interval.",
        "A configuration setting or extension version differs from the baseline in a way that was not part of the planned change.",
        "Any statement on the order-placement, balance-check, withdrawal, or settlement path is measurably slower than its pre-maintenance baseline.",
        "XID age on any table did not improve as expected after maintenance that was supposed to include a vacuum pass, or is now closer to the wraparound threshold than before the window opened.",
    ],
    related_issues=[
        "../pre-maintenance-check/README.md",
        "../comprehensive-health-check/README.md",
        "../../replication-and-ha/failover-investigation/README.md",
        "../../replication-and-ha/reader-lag-investigation/README.md",
        "../../disaster-recovery/cluster-failover-drill/README.md",
        "../../transactions-and-xid/xid-wraparound-risk/README.md",
    ],
    aurora_notes=[
        "A restart (whether from a resize, major version upgrade, or parameter-group reboot) resets pg_stat_statements, pg_stat_database, and pg_stat_checkpointer on the affected instance -- a 'change' in these counters immediately after maintenance is expected, not a finding, unless it persists well past a fresh accumulation window.",
        "After a major version upgrade, run ANALYZE-freshness verification (statistics_freshness in post-deployment-check) as well: some upgrade paths recommend or require a statistics refresh, and stale statistics immediately post-upgrade are a common source of an apparent plan regression that is actually just an unrefreshed planner.",
        "Aurora reader instances resume redo application from the shared storage layer after a restart; expect a brief lag spike immediately after recovery even when nothing is wrong, and judge convergence over a few minutes rather than expecting instant zero lag.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_instance_topology_and_uptime",
        "Confirms writer/reader topology and instance uptime reflect the completed maintenance operation.",
        sb.cluster_recovery_role() + "\n\n" + sb.aurora_replica_status(),
        "instance_uptime should be consistent with when the maintenance restart actually completed. Confirm the writer/reader roles match what the maintenance plan intended -- after a failover test in particular, confirm the promoted instance is the one expected to be the writer going forward, not merely 'a' writer.",
        related_scripts="02_replication_lag_after_maintenance.sql",
        table_purpose="Writer/reader role and Aurora cluster topology/lag after maintenance.",
    ),
    sql_script(
        "02", "02_replication_lag_after_maintenance",
        "Re-checks Aurora reader lag for direct comparison against the pre-maintenance baseline.",
        sb.aurora_replica_status(),
        "Compare directly against pre-maintenance-check script 04. A brief lag spike immediately after the restart is expected as the reader catches up on redo; the finding is lag that has not converged back toward baseline within a few minutes, which points to a reader under-provisioned for the current WAL generation rate.",
        related_scripts="03_connection_recovery_check.sql, ../pre-maintenance-check/README.md",
        table_purpose="Post-maintenance reader lag, for baseline comparison.",
    ),
    sql_script(
        "03", "03_connection_recovery_check",
        "Confirms the application fleet reconnected cleanly after the restart.",
        sb.max_connections_headroom() + "\n\n" + sb.connections_by_application_and_user(),
        "Compare the per-application connection counts against the pre-maintenance baseline. A service showing zero or a much lower connection count than before means its pool did not reconnect cleanly and needs a manual restart; a much higher count than before suggests a reconnect storm that has not yet settled into steady state.",
        execution_location=WRITER_PREFERRED,
        related_scripts="04_blocking_and_lock_check.sql, ../../connections/connection-pooling/README.md",
        table_purpose="Connection headroom and per-application connection counts after maintenance.",
    ),
    sql_script(
        "04", "04_blocking_and_lock_check",
        "Checks for blocked sessions immediately after the restart.",
        sb.blocked_sessions(),
        "An empty result is the expected healthy state. New blocking chains immediately after maintenance often trace back to the reconnect storm itself (many sessions competing for the same rows/objects on first reconnect) rather than to the maintenance operation's content -- if the chain persists past the initial reconnect burst, treat it as a genuine finding.",
        execution_location=WRITER_PREFERRED,
        related_scripts="05_vacuum_and_xid_status.sql, ../../concurrency-and-locking/blocked-queries/README.md",
        table_purpose="Currently blocked sessions and their blockers, after maintenance.",
    ),
    sql_script(
        "05", "05_vacuum_and_xid_status",
        "Checks autovacuum activity and transaction ID age for a regression caused by an interrupted vacuum.",
        sb.autovacuum_workers_active() + "\n\n" + sb.database_transaction_age(),
        "Compare pct_of_freeze_max_age against the pre-maintenance-check reading. If it did not improve, or is now higher, despite this maintenance including a restart that could have interrupted an in-flight anti-wraparound autovacuum (see pre-maintenance-check script 05), confirm autovacuum has resumed and is actively progressing on the affected table.",
        execution_location=WRITER_PREFERRED,
        related_scripts="06_settings_and_extension_verification.sql, ../../vacuum-and-autovacuum/vacuum-progress/README.md",
        table_purpose="In-flight vacuum workers and per-database XID age after maintenance.",
    ),
    sql_script(
        "06", "06_settings_and_extension_verification",
        "Re-captures configuration settings and extension inventory for comparison against the pre-maintenance baseline.",
        sb.key_settings_snapshot() + "\n\n" + sb.extension_inventory(),
        "Compare row by row against pre-maintenance-check script 06. Any difference not explained by the planned change (an intended parameter-group update or an intended extension version bump) is an unplanned side effect of the maintenance and should be understood and documented before the ticket is closed.",
        related_scripts="07_query_performance_vs_baseline.sql",
        table_purpose="Post-maintenance configuration and extension inventory, for baseline comparison.",
    ),
    sql_script(
        "07", "07_query_performance_vs_baseline",
        "Re-captures top statements by total time for direct comparison against the pre-maintenance baseline.",
        _pgss_guarded(sb.pgss_top_by_total_time()),
        "Compare against pre-maintenance-check script 07. Confirm stats_reset has not changed between the two captures (a major version upgrade or a reboot typically does reset it) -- if it has, this specific comparison is invalid and application-side latency metrics are the more reliable signal for a query-performance regression.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ + " The pre-maintenance baseline from pre-maintenance-check script 07 is required for the comparison.",
        related_scripts="../pre-maintenance-check/README.md",
        table_purpose="Post-maintenance top-query comparison (pg_stat_statements).",
    ),
]

# ---------------------------------------------------------------------------
# capacity-health-check
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="capacity-health-check",
    title="Capacity Health Check",
    summary=(
        "A focused sweep of storage, connection, and I/O capacity headroom -- distinct from "
        "the general checks in comprehensive-health-check and daily-health-check, which touch "
        "capacity only in passing. This workflow answers one question specifically: does this "
        "cluster have room to keep growing at its current rate before storage, connections, or "
        "I/O become the limiting factor? It is the read-only, SQL-level companion to "
        "storage-and-capacity/capacity-forecasting, which builds the longer-range trend and "
        "projection on top of the same underlying signals."
    ),
    symptoms=[
        "No active symptom -- this is a scheduled capacity review (monthly, or ahead of a known volume event such as a new listing or a derivatives launch).",
        "Storage cost or CloudWatch VolumeBytesUsed has been trending upward and the team wants a database-level explanation of what is driving it.",
        "A capacity planning conversation needs current, concrete numbers rather than estimates.",
    ],
    business_impact=[
        "Aurora storage grows in increments and never shrinks automatically when rows are deleted; an exchange platform's steadily accumulating trades, ledger_entries, and audit tables mean storage capacity questions compound rather than resolve themselves.",
        "Connection headroom exhausted during a volatility spike is a binary, all-or-nothing failure: every unserved connection request means matching-engine and withdrawal-processing requests simply fail, at exactly the moment volume and revenue are highest.",
        "I/O capacity that has quietly become the bottleneck (rather than CPU) is easy to miss because CPU utilization can look comfortable while checkpoint and buffer I/O pressure is already high -- catching this before it becomes latency-visible avoids a harder-to-diagnose incident later.",
    ],
    root_causes=[
        "Organic data growth outpacing the storage/retention plan that was sized for a smaller historical volume.",
        "Retained WAL from an inactive or lagging replication slot silently consuming storage that is not visible in a simple table-size inventory.",
        "Connection pool sizing across an expanding number of application instances or services approaching the instance class's effective max_connections ceiling.",
        "Write-heavy workload growth increasing checkpoint frequency and buffer I/O pressure faster than table row counts alone would suggest.",
        "Temp file spillage growing as query volume grows, consuming local instance storage that is shared with other operations.",
    ],
    investigation_strategy=[
        "Size the database and its largest tables first, to establish which objects are actually driving storage consumption.",
        "Check the growth trend if historical snapshots are available, or note that they are not yet being collected.",
        "Check connection capacity headroom and its per-application breakdown.",
        "Check I/O and checkpoint pressure, since this is the capacity dimension least visible from a simple size inventory.",
        "Check replication slots for WAL retention that silently consumes storage outside any table.",
        "Check temp file usage and index footprint as secondary storage consumers.",
        "Review the key settings that define the current capacity ceiling (max_connections, work_mem, checkpoint tuning).",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "The optional table-size history tracking table from automation/growth-monitoring (if deployed) for a real growth-rate calculation; without it, this workflow still produces a single-point-in-time capacity snapshot.",
        "The cluster's current instance class and provisioned storage configuration, to interpret headroom percentages against actual limits rather than in the abstract.",
    ],
    interpretation_guide=[
        "This is a capacity check, not a performance check: a finding here is 'we are approaching a ceiling', not 'a query is slow right now' -- route performance-shaped findings to the performance/ category instead.",
        "A single snapshot shows the current state; it cannot show the growth rate. Whenever the growth-trend script has no tracking table available, treat this run as the first of a series and schedule the next one rather than trying to conclude a trend from one data point.",
        "Connection headroom should be read against the instance class's effective max_connections, not against an assumption of what the value should be -- Aurora derives it from instance memory via the parameter-group formula, so the only way to raise the ceiling is a larger instance class or fewer per-service connections via pooling.",
        "A replication slot retaining a large amount of WAL is a capacity finding even though it shows up nowhere in a table-size inventory -- it is easy to miss unless checked explicitly.",
        "Checkpoint and buffer I/O pressure trending upward while CPU utilization looks comfortable is the classic 'we still have headroom' false signal on Aurora, where I/O to the distributed storage layer is a genuinely separate capacity dimension from compute.",
    ],
    remediation_immediate=[
        "This workflow does not remediate capacity -- it is entirely diagnostic. Any capacity action (retention/archival, instance resize, connection pooling change) is planned and executed through its owning workflow.",
        "The one exception worth acting on immediately: a replication slot retaining an unexpectedly large amount of WAL from a decommissioned or broken consumer should be investigated and, if genuinely abandoned, removed under change control -- it is pure waste that a table-size inventory would never surface.",
    ],
    remediation_short_term=[
        "Open a capacity ticket per finding, ranked by proximity to a hard limit (connections, provisioned IOPS, storage cost trend) rather than by which number looks largest in isolation.",
        "Hand off storage-growth findings to archival-and-data-lifecycle/investigate-archiving-candidate and connection-headroom findings to connections/max-connections-planning for the detailed remediation path.",
    ],
    remediation_long_term=[
        "Deploy the growth-monitoring collector (automation/growth-monitoring) if it is not already running, so future capacity-health-check runs have real trend data instead of single-point snapshots.",
        "Feed this workflow's findings into storage-and-capacity/capacity-forecasting on a recurring cadence so capacity planning becomes a standing process rather than a reactive one-off review.",
        "Establish per-instance-class connection and storage headroom thresholds with the platform team ahead of known high-volume events, rather than discovering the ceiling during one.",
    ],
    production_safety=[
        "Every script in this workflow is strictly read-only: catalog and statistics views only, no DDL, no DML, and no VACUUM/ANALYZE.",
        "Safe to run at any time, including during peak trading; the heaviest step is the table/index size inventory, which scales with the number of relations in the schema but takes no locks beyond brief catalog access.",
        "Safe to run on a reader instance for the sizing and settings steps; run the connection and I/O steps against the writer, since those statistics are per-instance.",
    ],
    escalation_criteria=[
        "Connection utilization above 85% with no clear path to reduce per-service pool sizes -- escalate to connections/max-connections-planning before the next high-volume event.",
        "A replication slot retaining tens of gigabytes or more of WAL with no active consumer -- escalate immediately, this is unattributed storage growth with a clear owner question attached.",
        "Storage growth on a table not explained by expected business volume (a reference or configuration table appearing among the largest tables) -- escalate to investigate a bug or unintended accumulation.",
        "Checkpoint or buffer I/O pressure rising for several consecutive reviews while row counts alone do not explain the increase -- escalate to storage-and-capacity/wal-generation.",
    ],
    related_issues=[
        "../comprehensive-health-check/README.md",
        "../daily-health-check/README.md",
        "../../storage-and-capacity/capacity-forecasting/README.md",
        "../../storage-and-capacity/database-growth/README.md",
        "../../connections/max-connections-planning/README.md",
        "../../archival-and-data-lifecycle/investigate-archiving-candidate/README.md",
    ],
    aurora_notes=[
        "Aurora storage grows in 10GiB increments on the shared cluster volume and is never returned to the pool when rows are deleted or a table is dropped -- pg_database_size()/pg_total_relation_size() show the logical footprint, not the billed volume; use CloudWatch VolumeBytesUsed for the actual billed figure.",
        "max_connections on Aurora is derived from the instance class via the parameter-group formula rather than freely set -- raising the ceiling requires a larger instance class (or reducing per-service connection counts via pooling), not a simple parameter change.",
        "Aurora's I/O to the distributed storage layer is billed and capacity-planned separately from compute (see CloudWatch VolumeReadIOPs/VolumeWriteIOPs); a checkpoint/buffer-I/O finding here is a signal to review that CloudWatch data alongside this SQL-level view, not a substitute for it.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_database_and_table_footprint",
        "Sizes every database and the largest tables in the current database.",
        sb.database_sizes() + "\n\n" + sb.largest_tables(),
        "This is the starting inventory for every other capacity question: which objects actually account for the storage footprint right now. On an exchange, expect trades, ledger_entries, order_book_snapshots, and audit/event tables to dominate; a small reference table appearing near the top is itself a finding worth investigating.",
        expected_runtime="Low to moderate (seconds; longer on schemas with many thousands of partitions).",
        related_scripts="02_table_growth_trend.sql",
        table_purpose="Database sizes and largest tables by total size.",
    ),
    sql_script(
        "02", "02_table_growth_trend",
        "Computes table growth over time from an optional periodic size-history tracking table, if one has been deployed.",
        sb.table_growth_rate_from_snapshot(),
        "If the tracking table does not exist yet, this prints an instructional notice rather than failing -- deploy the collector in automation/growth-monitoring and treat today's script 01 output as the first snapshot. If it does exist, the growth-over-window figures for the largest tables are the actual number that drives 'how many months until this table is a problem', not the single-point-in-time size alone.",
        related_scripts="03_connection_capacity_headroom.sql, ../../storage-and-capacity/table-growth/README.md",
        table_purpose="Table growth over the tracked window, where a growth-history table exists.",
    ),
    sql_script(
        "03", "03_connection_capacity_headroom",
        "Measures connection utilization against max_connections and breaks it down by application.",
        sb.max_connections_headroom() + "\n\n" + sb.connections_by_application_and_user(),
        "pct_utilized is the ceiling that matters most during a volatility-driven traffic burst -- unlike storage, there is no graceful degradation once connections are exhausted. The per-application breakdown shows which service's pool sizing needs review first if utilization is trending upward.",
        execution_location=WRITER_PREFERRED,
        related_scripts="04_io_and_checkpoint_pressure.sql, ../../connections/max-connections-planning/README.md",
        table_purpose="Connection utilization and per-application connection counts.",
    ),
    sql_script(
        "04", "04_io_and_checkpoint_pressure",
        "Reports per-backend-type I/O statistics and checkpoint/background-writer activity.",
        sb.pg_stat_io_summary() + "\n\n" + sb.checkpoint_activity() + "\n\n" + sb.bgwriter_activity(),
        "A rising pct_forced_checkpoints (checkpoints triggered by hitting max_wal_size rather than the scheduled timeout) means the write rate has outgrown the current checkpoint tuning -- a capacity finding distinct from storage size. On PG17, pg_stat_io reports operation counts and a fixed op_bytes rather than direct byte columns; the derived byte totals in this query's output already account for that.",
        execution_location=WRITER_PREFERRED,
        related_scripts="05_replication_slot_wal_retention.sql, ../../storage-and-capacity/wal-generation/README.md",
        table_purpose="I/O statistics by backend type, plus checkpoint and background-writer activity.",
    ),
    sql_script(
        "05", "05_replication_slot_wal_retention",
        "Flags replication slots retaining an unusually large amount of WAL relative to a documented threshold.",
        sb.replication_slots_and_wal_retention(),
        "Any slot with exceeds_warning_threshold = true is consuming cluster storage right now with no offsetting benefit if its consumer is gone or broken -- this is storage growth that a table-size inventory never shows. Confirm each slot has an active, healthy consumer (a CDC pipeline, a logical replica) before concluding it is safe to leave in place.",
        related_scripts="06_temp_file_and_index_footprint.sql, ../../replication-and-ha/replication-lag/README.md",
        table_purpose="Replication slots and their retained WAL, against a documented threshold.",
    ),
    sql_script(
        "06", "06_temp_file_and_index_footprint",
        "Reports cumulative temp file usage per database and the largest indexes in the current database.",
        sb.temp_file_usage_by_database() + "\n\n" + sb.largest_indexes(),
        "Temp file usage consumes local instance storage that is shared with other operations and grows with query volume even when table data itself is not growing. Large indexes are often a comparable or larger storage consumer than their base table; a duplicate or unused large index found here is capacity that can be reclaimed without any data risk (see tables-and-indexes/unused-indexes and tables-and-indexes/duplicate-indexes for the confirmation workflow before removing one).",
        related_scripts="07_key_capacity_settings.sql",
        table_purpose="Temp file usage per database and largest indexes.",
    ),
    sql_script(
        "07", "07_key_capacity_settings",
        "Snapshots the settings that define the current capacity ceiling.",
        sb.key_settings_snapshot(),
        "max_connections, work_mem, and maintenance_work_mem together define how much of the instance's memory each connection and maintenance operation can consume before spilling to disk or exhausting available memory -- read these values together with the instance class rather than in isolation, since Aurora derives several of them from the parameter-group formula tied to instance memory.",
        table_purpose="Key configuration settings relevant to capacity planning.",
    ),
]
