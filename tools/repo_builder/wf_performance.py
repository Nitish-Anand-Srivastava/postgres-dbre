"""Workflow definitions: performance/ category (10 issue directories)."""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import (
    ANY_INSTANCE, PG_MONITOR, PG_MONITOR_PLUS_PGSS, READ_ONLY, READ_ONLY_HEAVY,
    WRITER_PREFERRED, md_script, sql_script,
)
from .model import Script, Workflow

CATEGORY_SLUG = "performance"
CATEGORY_TITLE = "Performance Issues"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

# ---------------------------------------------------------------------------
# 1. high-cpu
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="high-cpu",
    title="High CPU Utilization",
    summary=(
        "Aurora instance-level CPU utilization (as reported by CloudWatch "
        "`CPUUtilization`) is sustained above a healthy threshold (commonly "
        ">80-90% for several minutes), risking query queuing, increased "
        "latency, and eventual request timeouts across every service that "
        "depends on the database."
    ),
    symptoms=[
        "CloudWatch CPUUtilization alarm on the writer or a reader instance.",
        "API latency (p95/p99) increasing across multiple services simultaneously.",
        "Order placement / trade matching latency increasing.",
        "Increasing number of active sessions in pg_stat_activity without a proportional increase in throughput.",
        "Performance Insights showing high Average Active Sessions (AAS) with CPU as the dominant wait.",
    ],
    business_impact=[
        "Trading and order execution latency directly affects fill quality and user trust in a low-latency exchange.",
        "Sustained high CPU risks cascading timeouts in upstream services (API gateways, matching engine, risk checks).",
        "If CPU saturation persists, Aurora may throttle or the instance may become unresponsive, risking a full outage.",
    ],
    root_causes=[
        "Query-level: a new or regressed query plan (missing index, stale statistics, changed data distribution) causing CPU-heavy operations (sorts, hashes, nested loops over large sets).",
        "Volume-level: legitimate traffic growth or a burst (market volatility event) exceeding provisioned instance capacity.",
        "Concurrency-level: lock contention causing spin/retry behavior, or an excessive number of parallel workers per query.",
        "Maintenance-level: autovacuum/ANALYZE running heavily on large tables concurrently with peak traffic.",
        "Connection-level: connection storm causing excessive context switching and parsing/planning overhead (especially without a pooler / prepared statements).",
        "Extension/function-level: expensive user-defined functions, JSON/JSONB processing, or regex-heavy WHERE clauses.",
        "Infrastructure-level: undersized instance class for current workload; needs vertical scaling or read offloading.",
    ],
    investigation_strategy=[
        "Confirm the scope: is this one instance (writer only, one reader, or all readers) or cluster-wide?",
        "Identify overall session load and how much of it is 'active' vs. waiting on locks/IO (broad view).",
        "Identify the specific queries currently consuming CPU (active queries with runtime and query text).",
        "Cross-reference with pg_stat_statements to find historically expensive queries, not just this instant's snapshot.",
        "Check wait events to distinguish true CPU-bound work from lock/IO waits that only look like load.",
        "Check for lock contention that could be causing retries or serialization overhead.",
        "Check table/index health (sequential scans, missing indexes, stale statistics, bloat) as a root cause of expensive plans.",
        "Correlate with recent deployments, schema changes, or known traffic events (see performance-after-deployment, sudden-performance-degradation).",
    ],
    prerequisites=[
        "`pg_stat_statements` extension created in the target database for script 03 (falls back to pg_stat_activity-only analysis if unavailable).",
        "`pg_monitor` (or `pg_read_all_stats`) role membership for the connecting user.",
        "AWS Console/CloudWatch access to confirm instance-level CPUUtilization and Performance Insights Top SQL/Top Waits (see docs/aurora-postgresql/performance-insights-and-cloudwatch.md).",
    ],
    interpretation_guide=[
        "A large number of 'active' sessions with no wait_event (NULL) genuinely running CPU-bound work is the clearest DB-side CPU signal.",
        "A large number of sessions with a non-null wait_event (especially Lock or IO) is NOT primarily a CPU problem even though CloudWatch CPU may still be elevated from context switching -- follow the concurrency-and-locking workflows instead.",
        "A handful of queries dominating pg_stat_statements total_exec_time with a high mean_exec_time and high calls is the most actionable finding -- prioritize plan/index fixes for those first.",
        "High seq_scan counts on large tables combined with the above is strong evidence of a missing index or a regressed plan.",
    ],
    remediation_immediate=[
        "If one or a few runaway queries dominate: consider cancelling (`pg_cancel_backend`) -- not terminating -- the specific backend(s) after confirming with the owning team, per incident-response/runaway-query.",
        "If traffic is legitimately elevated (e.g. market volatility): add read replicas / route eligible read traffic to reader endpoint to offload the writer.",
        "If an Aurora instance class is undersized for a sustained new baseline: scale the writer/reader instance class (requires brief failover for writer resize on some paths -- confirm with AWS documentation for zero-downtime options).",
    ],
    remediation_short_term=[
        "Add or adjust indexes for the specific expensive queries identified in pg_stat_statements/EXPLAIN.",
        "Tune connection pooling (PgBouncer) to reduce planning/parsing overhead from very high connection churn.",
        "Schedule autovacuum/ANALYZE more aggressively on high-churn tables to keep plans efficient (see vacuum-and-autovacuum).",
    ],
    remediation_long_term=[
        "Introduce query result caching or read-replica routing for read-heavy, latency-tolerant endpoints.",
        "Revisit schema/partitioning strategy for tables driving the most CPU-heavy scans (see partitioning/).",
        "Establish CPU/AAS-based autoscaling or a documented vertical-scaling runbook tied to capacity forecasts (see storage-and-capacity/capacity-forecasting).",
    ],
    production_safety=[
        "All investigation scripts in this workflow are read-only.",
        "Do not run ANALYZE across every table as a blind remediation step; target specific tables identified in the investigation.",
        "Do not terminate backends without following incident-response/runaway-query safety guidance.",
    ],
    escalation_criteria=[
        "CPU remains >90% for more than 15 minutes despite mitigations, with visible customer-facing latency impact.",
        "Root cause appears to be outside the database (application bug, retry storm) -- loop in application/SRE teams immediately rather than continuing DB-only investigation.",
        "Suspected undersized instance class requiring a scaling decision beyond on-call authority.",
    ],
    related_issues=[
        "../high-database-load/README.md",
        "../slow-queries/README.md",
        "../../concurrency-and-locking/lock-contention/README.md",
        "../../incident-response/high-cpu/README.md",
    ],
    aurora_notes=[
        "CPUUtilization is an instance-level CloudWatch metric, not a PostgreSQL catalog value -- there is no SQL query that returns 'CPU percent used'; the closest SQL-visible proxy is active session count and query-level exec-time from pg_stat_statements.",
        "Aurora Performance Insights' 'Average Active Sessions' (AAS) view decomposed by wait type is generally a faster way to distinguish CPU-bound from lock/IO-bound load than reconstructing it from pg_stat_activity snapshots alone.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_identify_database_load", "Cluster-wide session/state overview to establish overall load before drilling in.",
               sb.activity_overview(),
               "A high 'active' session_count with NULL wait_event is the strongest indicator of genuine CPU-bound load. Compare against normal baseline session counts for this time of day.",
               related_scripts="02_identify_active_queries.sql"),
    sql_script("02", "02_identify_active_queries", "Lists currently active queries running longer than a threshold, to identify what is actively consuming CPU right now.",
               sb.active_long_running_queries(),
               "Queries appearing repeatedly here across multiple snapshots (run this script every 5-10 seconds during the incident) are the best candidates for the actual CPU driver.",
               related_scripts="01_identify_database_load.sql, 03_identify_expensive_queries.sql"),
    sql_script("03", "03_identify_expensive_queries", "Top statements by total execution time from pg_stat_statements, to find the historically dominant CPU consumers, not just this instant's snapshot.",
               sb.pgss_top_by_total_time(),
               "Statements with both high total_exec_time and high calls are the highest-leverage fix targets. A single new statement with a large share of total time since a recent deploy suggests a plan regression.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements extension must be created in the current database.",
               related_scripts="02_identify_active_queries.sql, 04_check_wait_events.sql"),
    sql_script("04", "04_check_wait_events", "Aggregates current wait events to confirm whether load is genuinely CPU-bound vs. lock/IO-bound.",
               sb.wait_events_summary(),
               "A high proportion of NULL wait_event on active sessions confirms CPU-bound work. A high proportion of Lock/IO wait events means the real bottleneck is elsewhere -- pivot to concurrency-and-locking or storage-and-capacity workflows.",
               related_scripts="05_check_lock_contention.sql"),
    sql_script("05", "05_check_lock_contention", "Confirms or rules out lock contention as a secondary/contributing factor to elevated CPU (e.g. spin-heavy retry logic).",
               sb.blocked_sessions(),
               "A non-trivial number of blocked sessions during a high-CPU incident suggests contention is compounding the load; resolve the blocking chain (see concurrency-and-locking/blocked-queries) before judging whether CPU pressure remains.",
               related_scripts="../../concurrency-and-locking/blocked-queries/scripts/01_identify_blocked_sessions.sql"),
    sql_script("06", "06_check_table_index_health", "Checks for sequential-scan-heavy tables and stale statistics that commonly cause CPU-expensive plans.",
               sb.sequential_scan_heavy_tables(),
               "Large tables with a high seq_tup_read/seq_scan ratio and low idx_scan are strong candidates for a missing index; cross-reference with the specific queries found in scripts 02/03 before adding an index.",
               related_scripts="../../tables-and-indexes/missing-index-candidates/README.md"),
]

# ---------------------------------------------------------------------------
# 2. high-database-load
# ---------------------------------------------------------------------------
WORKFLOWS.append(_wf(
    slug="high-database-load",
    title="High Database Load (Average Active Sessions)",
    summary=(
        "The database is showing a sustained high number of active/waiting "
        "sessions (high 'load' in the Performance Insights / AAS sense) "
        "even if instance CPU itself is not yet saturated. Unlike "
        "high-cpu, this workflow starts from the load composition (what "
        "sessions are doing) rather than assuming CPU is the bottleneck."
    ),
    symptoms=[
        "Performance Insights Database Load graph exceeding the instance's vCPU count for a sustained period.",
        "Growing number of sessions in pg_stat_activity across all states (active, idle in transaction, waiting on locks).",
        "Increasing p95/p99 latency without a single obviously dominant query.",
    ],
    business_impact=[
        "High load is a leading indicator that precedes CPU/IO saturation and outright timeouts -- catching it early prevents a full incident.",
        "In a high-throughput exchange, load spikes often correlate with market volatility events where correctness and availability both matter most.",
    ],
    root_causes=[
        "Application-level: retry storms, connection leaks, or a new feature generating far more queries per request than expected.",
        "Query-level: a mix of moderately expensive queries whose combined effect saturates capacity (no single 'smoking gun').",
        "Concurrency-level: growing lock wait queues amplifying apparent load (waiting sessions still count toward AAS).",
        "Vacuum-level: multiple autovacuum workers running concurrently against large hot tables during peak hours.",
        "Capacity-level: genuine organic growth outpacing the current instance class / reader fleet size.",
    ],
    investigation_strategy=[
        "Break down current load by wait_event_type/wait_event to see the composition (CPU vs Lock vs IO vs IPC vs Client).",
        "Break down load by database and application_name to see which service/tenant is driving it.",
        "Check pg_stat_statements for the queries contributing the most total execution time in the current window.",
        "Check autovacuum activity, since concurrent vacuum workers count toward load and compete for the same resources as application queries.",
        "Compare current connection counts against max_connections headroom, since a growing backlog can itself be both a symptom and an amplifier.",
    ],
    prerequisites=[
        "pg_stat_statements recommended (script 03) but not mandatory to begin the investigation.",
        "AWS Performance Insights enabled is strongly recommended for this workflow specifically, since it provides a ready decomposition of AAS by wait type and top SQL without needing to poll pg_stat_activity manually.",
    ],
    interpretation_guide=[
        "AAS (Average Active Sessions) > number of vCPUs sustained for minutes, not seconds, is the actionable threshold -- brief spikes are normal.",
        "If load composition is dominated by one wait_event, pivot directly to the matching specialized workflow (Lock -> concurrency-and-locking, IO -> storage-and-capacity, CPU/NULL -> high-cpu).",
        "Autovacuum contributing a large share of load on its own is not inherently bad -- it means autovacuum is doing necessary work; the question is whether its cost limits should be tuned to spread the work over a longer window instead of running at full throttle during peak hours.",
    ],
    remediation_immediate=[
        "Route eligible read-only traffic to reader endpoint(s) to redistribute load away from the writer.",
        "If a specific application/tenant is identified as the driver, engage that team to pause/rate-limit the offending traffic.",
    ],
    remediation_short_term=[
        "Tune autovacuum cost-based delay settings so background maintenance does not compete with peak-hour traffic (see vacuum-and-autovacuum/autovacuum-not-keeping-up).",
        "Add missing indexes / fix moderately expensive queries identified in pg_stat_statements even if none is individually dominant.",
    ],
    remediation_long_term=[
        "Capacity plan for observed growth trend (see storage-and-capacity/capacity-forecasting) and pre-provision reader capacity ahead of anticipated volatility events.",
        "Introduce application-level rate limiting / backpressure so a downstream retry storm cannot translate directly into database load.",
    ],
    production_safety=[
        "All scripts are read-only.",
        "Do not disable autovacuum to 'reduce load' -- this defers cost and risks a much worse emergency-autovacuum situation later (see vacuum-and-autovacuum/emergency-autovacuum).",
    ],
    escalation_criteria=[
        "Load composition points to an application-level retry storm or leak -- escalate to the owning application team immediately, in parallel with continued DB-side investigation.",
        "Sustained load approaching 2x the instance's vCPU count with no single fixable root cause -- this is a capacity decision, escalate to database engineering leadership.",
    ],
    related_issues=[
        "../high-cpu/README.md",
        "../../database-health/comprehensive-health-check/README.md",
        "../../observability/performance-insights/README.md",
    ],
    aurora_notes=[
        "Average Active Sessions (AAS) as displayed in Performance Insights is an AWS-computed metric; there is no single PostgreSQL catalog column that reproduces it exactly, though the scripts here approximate it via point-in-time pg_stat_activity snapshots.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_load_composition_by_wait_event", "Breaks current session load down by wait_event_type/wait_event to identify the dominant contributor.",
               sb.wait_events_summary(),
               "Rank the wait_event_type groups by backend_count. Whichever dominates tells you which specialized workflow to pivot into next.",
               related_scripts="02_load_by_application_and_database.sql"),
    sql_script("02", "02_load_by_application_and_database", "Breaks load down by application_name/usename/datname to identify which service or tenant is driving it.",
               sb.connections_by_application_and_user(),
               "A single application_name with a disproportionate active_count relative to its normal baseline is the fastest way to identify a runaway service or tenant.",
               related_scripts="01_load_composition_by_wait_event.sql"),
    sql_script("03", "03_top_queries_by_total_time", "Identifies the queries contributing the most cumulative execution time in the current window.",
               sb.pgss_top_by_total_time(),
               "Look for several moderately expensive queries collectively dominating, not necessarily one single smoking gun -- this is the key difference from a classic single-query high-cpu incident.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements extension must be created in the current database.",
               related_scripts="04_autovacuum_contribution.sql"),
    sql_script("04", "04_autovacuum_contribution", "Checks whether concurrent autovacuum workers are a meaningful contributor to current load.",
               sb.autovacuum_workers_active(),
               "Multiple simultaneous autovacuum workers on large tables during peak hours can materially add to load; this is not a bug, but may need cost-limit tuning to spread the work off-peak.",
               related_scripts="../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md"),
    sql_script("05", "05_connection_headroom", "Checks connection count against max_connections headroom, since a growing backlog itself compounds load.",
               sb.max_connections_headroom(),
               "Utilization approaching 80-90% of max_connections combined with high load suggests connection pooling or pool-size tuning is needed in addition to any query-level fix.",
               related_scripts="../../connections/connection-exhaustion/README.md"),
]

WORKFLOWS.append(_wf(
    slug="slow-queries",
    title="Slow Queries",
    summary=(
        "One or more specific queries are executing slower than expected, "
        "either as isolated incidents reported by an engineering team or as "
        "a general pattern surfaced by APM/tracing. This is the general-"
        "purpose, query-first investigation workflow; use query-regression "
        "instead when you specifically suspect a plan change after a "
        "deploy or ANALYZE."
    ),
    symptoms=[
        "A specific API endpoint or batch job reports elevated latency or timeouts.",
        "APM/tracing shows increased time spent in a database call.",
        "Customer/internal reports of a specific operation (e.g. order history lookup, balance query) being slow.",
    ],
    business_impact=[
        "Slow queries on hot paths (order placement, balance checks, withdrawal processing) directly degrade user experience and can breach internal SLAs.",
        "Slow queries holding connections/transactions open longer than necessary reduce effective connection pool capacity for all other traffic.",
    ],
    root_causes=[
        "Missing or unused index for the query's predicate/join/order-by.",
        "Stale statistics causing the planner to choose a poor join order or scan method.",
        "Data growth: a previously fine plan (e.g. nested loop over a small table) no longer suits the current table size.",
        "Lock contention delaying the query's execution rather than the query itself being computationally expensive.",
        "Parameter sniffing / generic plan issues with prepared statements and highly skewed data distributions.",
        "Excessive temp file usage from undersized work_mem for the query's sort/hash/aggregate operations.",
    ],
    investigation_strategy=[
        "Confirm current activity: is the slow query still running, or has it already completed?",
        "Identify any currently long-running instances of the query and their exact runtime.",
        "Look up the query in pg_stat_statements for historical calls/mean/total time trends.",
        "Check wait events for the specific backend(s) running the query.",
        "Check for lock contention affecting the query's table(s).",
        "Check table-level statistics (dead tuples, last analyze, row counts) for the query's target tables.",
        "Check index usage/existence for the query's predicates.",
        "Obtain and review the query's execution plan (EXPLAIN, and EXPLAIN ANALYZE only under the safety conditions documented in script 08).",
    ],
    prerequisites=[
        "pg_stat_statements extension created in the target database (scripts 03).",
        "Query text or queryid from the reporting team/APM tool to narrow scripts 03/07/08 to the specific statement.",
    ],
    interpretation_guide=[
        "If the query does not appear as currently active and has a low mean_exec_time in pg_stat_statements, the slowness was likely transient (lock wait, connection pool exhaustion, or network) rather than the query plan itself.",
        "A high stddev_exec_time relative to mean_exec_time in pg_stat_statements indicates inconsistent performance -- often parameter-sensitive plans or lock contention -- rather than a uniformly bad plan.",
        "Confirm via EXPLAIN whether the planner's row estimates are close to reality; large estimate-vs-actual gaps point to a statistics problem, not an index problem.",
    ],
    remediation_immediate=[
        "If the query is currently running and confirmed safe to cancel (not a financial write in flight), cancel via `pg_cancel_backend` (never `pg_terminate_backend` for a routine slow query) -- see incident-response/runaway-query.",
        "If lock contention is the cause, resolve the blocking session per concurrency-and-locking/blocked-queries instead of touching the slow query itself.",
    ],
    remediation_short_term=[
        "Add a targeted index using CREATE INDEX CONCURRENTLY (see schema-changes/concurrent-index-build).",
        "Run a targeted ANALYZE on the specific table(s) if statistics are stale (do not ANALYZE the whole database as a blind fix).",
        "Rewrite the query (e.g. replace an OR-based predicate with a UNION, or restructure a subquery as a join) if the plan is fundamentally suboptimal for the current data shape.",
    ],
    remediation_long_term=[
        "Revisit schema/partitioning for tables that are structurally too large for the current query pattern (see partitioning/investigate-partitioning-candidate).",
        "Add query-shape regression testing/plan monitoring to CI or synthetic canaries so regressions are caught before reaching production.",
    ],
    production_safety=[
        "Scripts 01-07 are read-only and safe to run at any time.",
        "Script 08 is documentation-only guidance and explicitly warns against running EXPLAIN ANALYZE on write statements or unbounded queries in production without safeguards.",
    ],
    escalation_criteria=[
        "The slow query is on a financial write path (order matching, balance update, ledger write) and cannot be safely cancelled -- escalate to database engineering leadership and the owning application team immediately.",
        "Root cause is a plan regression correlated with a recent deployment -- cross-link to performance-after-deployment and involve the deploying team.",
    ],
    related_issues=[
        "../query-regression/README.md",
        "../../query-optimization/analyze-query-plan/README.md",
        "../../tables-and-indexes/missing-index-candidates/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_current_activity", "Snapshot of current session/state activity to confirm whether the reported slow query is still running.",
               sb.activity_overview(),
               "If the reported query's session no longer appears here, gather forensic evidence from pg_stat_statements (script 03) instead of chasing a live session.",
               related_scripts="02_long_running_queries.sql"),
    sql_script("02", "02_long_running_queries", "Lists currently active queries beyond a runtime threshold, to catch the slow query if it is still executing.",
               sb.active_long_running_queries(),
               "Match on query text/application_name to confirm this is the reported query, then note its pid for the wait-event and lock checks in scripts 04-05.",
               related_scripts="01_current_activity.sql, 03_pg_stat_statements_top_queries.sql"),
    sql_script("03", "03_pg_stat_statements_top_queries", "Looks up historical call/timing statistics for the query pattern from pg_stat_statements.",
               sb.pgss_top_by_mean_time(),
               "Compare mean_exec_time against stddev_exec_time and max_exec_time: a wide spread suggests contention or parameter-sensitivity rather than a uniformly bad plan.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements extension must be created in the current database.",
               related_scripts="02_long_running_queries.sql, 08_execution_plan_guidance.md"),
    sql_script("04", "04_wait_events", "Checks the specific wait event(s) for the backend(s) running the slow query.",
               sb.wait_events_summary(),
               "A non-null wait_event on the specific backend means the query itself is not the bottleneck -- pivot to the resource indicated (Lock, IO, IPC).",
               related_scripts="05_lock_contention.sql"),
    sql_script("05", "05_lock_contention", "Checks whether the slow query is blocked by another session.",
               sb.blocked_sessions(),
               "If the query's pid appears here, the fix is to resolve the blocking session (concurrency-and-locking/blocked-queries), not to tune the slow query's plan.",
               related_scripts="../../concurrency-and-locking/blocked-queries/README.md"),
    sql_script("06", "06_table_statistics", "Checks table-level statistics (row counts, dead tuples, last analyze) for the query's target table(s).",
               sb.statistics_freshness(),
               "A high pct_modified_since_analyze combined with a stale last_analyze/last_autoanalyze strongly suggests the planner is working from outdated row estimates.",
               related_scripts="07_index_usage.sql"),
    sql_script("07", "07_index_usage", "Checks existing index definitions and usage for the query's target table(s).",
               sb.index_bloat_and_usage(),
               "Confirm an index actually exists for the query's WHERE/JOIN/ORDER BY columns and that idx_scan is non-zero and growing; absence of a suitable index is the most common root cause of a slow query.",
               related_scripts="../../tables-and-indexes/missing-index-candidates/README.md"),
    md_script("08", "08_execution_plan_guidance", "Guidance for safely obtaining and reading an execution plan for the slow query.",
              (
                  "## EXPLAIN vs. EXPLAIN ANALYZE\n\n"
                  "* `EXPLAIN (FORMAT TEXT) <query>;` shows the planner's *estimated* plan and cost "
                  "without executing the query. Always safe to run in production, including "
                  "against write statements, because it never executes anything.\n"
                  "* `EXPLAIN ANALYZE <query>;` **actually executes the query** (including any "
                  "writes it contains) and measures real timing per plan node. Never run "
                  "`EXPLAIN ANALYZE` against an UPDATE/DELETE/INSERT statement in production "
                  "unless it is wrapped in a transaction you intend to `ROLLBACK`, and never run "
                  "it against a query you are not prepared to have actually complete (it will "
                  "take at least as long as the original slow query, possibly longer due to "
                  "instrumentation overhead).\n"
                  "* For a read query you want to time-box, prefer:\n"
                  "  ```sql\n"
                  "  SET LOCAL statement_timeout = '5s';\n"
                  "  EXPLAIN (ANALYZE, BUFFERS, TIMING, FORMAT TEXT) <query>;\n"
                  "  ```\n"
                  "  so a misbehaving plan cannot itself become a new incident.\n"
                  "* PostgreSQL 17 adds `EXPLAIN (ANALYZE, SERIALIZE)` to additionally measure "
                  "the time spent converting result rows to wire format -- useful when a query "
                  "returns a very large result set and you suspect client-side serialization, not "
                  "the plan itself, dominates latency.\n"
                  "* For an UPDATE/DELETE/INSERT you must analyze safely, run inside an explicit "
                  "transaction and roll back:\n"
                  "  ```sql\n"
                  "  BEGIN;\n"
                  "  EXPLAIN (ANALYZE, BUFFERS) UPDATE ...;\n"
                  "  ROLLBACK;\n"
                  "  ```\n"
                  "  Be aware this still takes locks for the duration of the statement and "
                  "generates the same row-level work as a real execution -- do not do this "
                  "against a hot production table without a maintenance window or a replica.\n\n"
                  "## Reading the plan\n\n"
                  "* Compare `rows=` (estimated) against `actual rows=` (from EXPLAIN ANALYZE) at "
                  "each node -- large gaps indicate stale/insufficient statistics.\n"
                  "* Look for `Seq Scan` on large tables where an `Index Scan`/`Index Only Scan` "
                  "would be expected.\n"
                  "* Look for `Sort Method: external merge Disk` or `Batches: N (originally M)` in "
                  "hash operations -- both indicate spilling to disk due to insufficient "
                  "`work_mem` for that operation.\n"
                  "* `Nested Loop` joining two large row sets without a supporting index on the "
                  "inner side is the classic pattern behind the query-optimization/"
                  "nested-loop-problems workflow.\n"
              ),
              "Use this guidance to safely capture a plan for the slow query identified in scripts 02/03, then follow query-optimization/analyze-query-plan for a deeper structured plan-reading workflow.",
              safety="DOCUMENTATION -- no SQL is executed by this file itself",
              expected_impact="None from this file; impact depends entirely on which guidance the operator chooses to execute.",
              required_privileges="Same as the query being analyzed.",
              prerequisites="Query text/queryid identified from scripts 02 or 03.",
              related_scripts="../../query-optimization/analyze-query-plan/README.md"),
]

WORKFLOWS.append(_wf(
    slug="query-regression",
    title="Query Plan Regression",
    summary=(
        "A previously well-performing query has recently become "
        "significantly slower, without any obvious application-level "
        "change -- typically caused by a changed execution plan (index "
        "drop, statistics change, data skew, parameter value, or a "
        "PostgreSQL/Aurora minor version upgrade) rather than a change in "
        "the query text itself."
    ),
    symptoms=[
        "A specific queryid's mean_exec_time in pg_stat_statements has increased sharply compared to prior weeks.",
        "APM shows a step-change (not gradual) increase in latency for a specific database call, correlated with a deploy, ANALYZE, index change, or maintenance window.",
    ],
    business_impact=[
        "Plan regressions on hot paths can silently double or 10x latency for a specific operation while overall system metrics look fine, hiding in aggregate dashboards.",
        "Left unresolved, a regressed plan can eventually saturate CPU/IO as call volume grows, escalating into a broader high-cpu/high-database-load incident.",
    ],
    root_causes=[
        "An index was dropped or became invalid (failed CONCURRENTLY build) removing the planner's best access path.",
        "A recent ANALYZE picked up a data distribution change (e.g. a new highly skewed status value) that flips the planner's chosen join order or scan method.",
        "Data growth crossed a threshold where a previously-efficient nested loop plan is no longer efficient.",
        "A minor engine version upgrade changed planner defaults or cost model behavior (rare, but documented in Aurora PostgreSQL release notes).",
        "A parameterized/prepared statement is using a generic plan unsuited to the actual parameter value distribution (parameter sniffing).",
    ],
    investigation_strategy=[
        "Confirm the regression is real and quantify it: compare current mean_exec_time against pg_stat_statements' longer-window history if available, or against APM history.",
        "Check whether any index the query likely depends on is missing, invalid, or was recently dropped.",
        "Check statistics freshness/last_analyze timing against the regression's onset time.",
        "Check current table size/row counts against what the query's original plan assumed.",
        "Obtain a current EXPLAIN and compare its shape (scan types, join order) against a known-good historical plan if one was saved.",
        "Check for a correlated deployment, migration, or maintenance event around the regression's onset.",
    ],
    prerequisites=[
        "pg_stat_statements extension created in the target database.",
        "Ideally, a previously captured 'known good' EXPLAIN plan or pg_stat_statements queryid history to compare against (see query-optimization/query-plan-regression for a template to store these going forward).",
    ],
    interpretation_guide=[
        "A sudden step-change correlated with a deploy timestamp points to schema/index changes in that deploy; a gradual drift over days/weeks points to data growth or bloat.",
        "If the invalid-indexes check (script 02) shows an invalid index on this query's table, that is very likely the direct cause -- a previous CREATE INDEX CONCURRENTLY failed and was never retried.",
    ],
    remediation_immediate=[
        "If an index was dropped or is invalid, restore it via CREATE INDEX CONCURRENTLY (see schema-changes/concurrent-index-build).",
        "If a specific bad parameter value is triggering a generic/bad plan for a prepared statement, consider `SET plan_cache_mode = force_custom_plan` for that session/role as a stopgap (session-level, not cluster-wide).",
    ],
    remediation_short_term=[
        "Run a targeted ANALYZE on the affected table(s) with an increased statistics target for the specific skewed column if data skew is the cause.",
        "Add an index or rewrite the query if data growth has fundamentally changed the optimal plan.",
    ],
    remediation_long_term=[
        "Adopt a plan-regression detection process: periodically snapshot pg_stat_statements per queryid and alert on sustained mean_exec_time increases (see automation/health-checks).",
        "Add invalid-index detection to routine health checks (database-health/daily-health-check) so a failed CONCURRENTLY build is caught within a day, not discovered via a regression.",
    ],
    production_safety=[
        "Investigation scripts are read-only.",
        "Do not rebuild indexes with plain CREATE INDEX / DROP INDEX on a live production table -- always use the CONCURRENTLY variants per schema-changes/concurrent-index-build.",
    ],
    escalation_criteria=[
        "Regression correlates with an Aurora engine minor-version upgrade -- escalate to AWS Support with the before/after EXPLAIN plans attached.",
        "No root cause identified after completing this workflow and the query is on a critical path -- escalate to database engineering leadership.",
    ],
    related_issues=[
        "../slow-queries/README.md",
        "../performance-after-deployment/README.md",
        "../../query-optimization/query-plan-regression/README.md",
        "../../tables-and-indexes/invalid-indexes/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_pgss_regression_candidates", "Ranks statements by mean execution time and call volume to identify candidate regressions and quantify their current cost.",
               sb.pgss_top_by_mean_time(),
               "Cross-reference the queryid against APM/dashboards for a 'known good' historical mean_exec_time; a large relative increase is the regression signal.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements extension must be created in the current database.",
               related_scripts="02_invalid_or_missing_indexes.sql"),
    sql_script("02", "02_invalid_or_missing_indexes", "Checks for invalid indexes on the affected table(s), the single most common direct cause of a sudden plan regression.",
               sb.invalid_indexes(),
               "Any row returned here on a table used by the regressed query is a near-certain root cause -- a previous CONCURRENTLY build failed and left the index unusable by the planner.",
               related_scripts="03_statistics_freshness.sql"),
    sql_script("03", "03_statistics_freshness", "Checks whether recent ANALYZE activity coincides with the regression's onset, and how much the table has changed since.",
               sb.statistics_freshness(),
               "A last_analyze/last_autoanalyze timestamp shortly before the regression started suggests newly gathered statistics changed the planner's chosen plan -- verify with a fresh EXPLAIN.",
               related_scripts="04_table_size_growth.sql"),
    sql_script("04", "04_table_size_growth", "Checks current table and index sizes to assess whether data growth alone could explain a plan flip (e.g. nested loop no longer viable).",
               sb.largest_tables(),
               "Compare current sizes against the last time the query was known to perform well; crossing common planner thresholds (e.g. table no longer fits comfortably in effective_cache_size) is a frequent cause of gradual regressions.",
               related_scripts="05_sequential_scans.sql"),
    sql_script("05", "05_sequential_scans", "Confirms whether the regressed query's table(s) are now being scanned sequentially where an index scan would be expected.",
               sb.sequential_scan_heavy_tables(),
               "A recent jump in seq_scan count on the affected table, together with a missing or invalid index found in script 02, is strong confirmatory evidence.",
               related_scripts="../../query-optimization/query-plan-regression/README.md"),
]

WORKFLOWS.append(_wf(
    slug="high-iops",
    title="High IOPS / Storage I/O Saturation",
    summary=(
        "The Aurora instance or cluster storage is showing elevated I/O "
        "operations per second (CloudWatch VolumeReadIOPS/VolumeWriteIOPS "
        "or ReadIOPS/WriteIOPS) or is approaching a provisioned/burst I/O "
        "limit, causing increased read/write latency at the storage layer."
    ),
    symptoms=[
        "CloudWatch VolumeReadIOPS/VolumeWriteIOPS or ReadIOPS/WriteIOPS elevated versus baseline.",
        "Increased ReadLatency/WriteLatency CloudWatch metrics.",
        "Queries that were previously fast now show elevated planning-independent latency (same plan, slower execution).",
        "Increased buffer cache miss rate (shared_blks_read growing much faster than shared_blks_hit in pg_stat_statements).",
    ],
    business_impact=[
        "Storage I/O saturation increases the latency of every operation touching disk, not just one query -- broad, hard-to-isolate degradation.",
        "On Aurora, sustained IOPS also directly affects the AWS bill (I/O-Optimized vs. standard billing) and can be an early indicator of a capacity/pricing-tier decision.",
    ],
    root_causes=[
        "Working set no longer fits in shared_buffers / OS cache: queries that used to hit the buffer cache now read from Aurora storage.",
        "A specific query or batch job scanning far more data than necessary (missing index, missing partition pruning).",
        "Autovacuum or manual VACUUM/ANALYZE reading large tables concurrently with peak traffic.",
        "Checkpoint activity writing a large volume of dirty buffers (see checkpoint_timeout/max_wal_size tuning).",
        "Excessive temp file spill activity from undersized work_mem.",
        "A logical replication slot or CDC consumer falling behind, forcing WAL retention and re-reads.",
    ],
    investigation_strategy=[
        "Check the cache hit ratio at the database level to see how much read traffic is actually reaching storage.",
        "Identify statements generating the most shared buffer reads (proxy for I/O) via pg_stat_statements.",
        "Check per-backend-type I/O breakdown (pg_stat_io) to see whether autovacuum/checkpointer/backends are the dominant I/O source.",
        "Check checkpoint frequency/duration, since checkpoint writes are a major, tunable source of write I/O.",
        "Check temp file usage, since spilling sorts/hashes to disk directly consumes IOPS.",
        "Check replication slot WAL retention, since a stuck consumer can force additional storage I/O.",
    ],
    prerequisites=[
        "pg_stat_statements for script 02.",
        "track_io_timing enabled (check via key settings snapshot) for I/O timing columns to be populated rather than zero.",
    ],
    interpretation_guide=[
        "A falling cache hit ratio over time at constant traffic volume indicates the working set has outgrown shared_buffers/instance memory -- consider a larger instance class or reducing the scanned data volume (indexes, partitioning, archiving).",
        "If pg_stat_io shows checkpointer/autovacuum as the dominant writer, the fix is scheduling/timeout tuning, not query optimization.",
        "If a small number of queries dominate shared_blks_read, that is the highest-leverage fix (index/partition pruning) before considering instance-class changes.",
    ],
    remediation_immediate=[
        "Route read traffic to reader endpoint(s) if the writer specifically is I/O saturated and readers have headroom.",
        "If a specific batch/reporting query is the driver, pause or reschedule it off-peak.",
    ],
    remediation_short_term=[
        "Add missing indexes / partition pruning support to reduce scanned data volume for the top offending queries.",
        "Tune checkpoint_timeout/max_wal_size (via the Aurora cluster parameter group) to smooth write I/O instead of bursty checkpoints.",
    ],
    remediation_long_term=[
        "Evaluate Aurora I/O-Optimized configuration if IOPS cost/volume is consistently high (an AWS Console/billing decision, not a SQL change).",
        "Archive/partition large historical tables that are the primary source of scanned data volume (see archival-and-data-lifecycle, partitioning).",
    ],
    production_safety=[
        "All investigation scripts are read-only.",
        "Do not change checkpoint_timeout/max_wal_size without testing recovery-time implications -- larger values reduce write I/O but increase crash-recovery replay time.",
    ],
    escalation_criteria=[
        "IOPS sustained near the storage subsystem's practical ceiling for the instance class with no single fixable query -- this is a capacity/billing decision, escalate to database engineering leadership.",
        "Suspected Aurora storage-layer issue (not explained by any workload change) -- open an AWS Support case.",
    ],
    related_issues=[
        "../high-latency/README.md",
        "../../storage-and-capacity/wal-generation/README.md",
        "../../query-optimization/temp-file-investigation/README.md",
    ],
    aurora_notes=[
        "Aurora storage IOPS and throughput are metrics reported by CloudWatch at the cluster/instance level; PostgreSQL catalogs only expose logical proxies (cache hit ratio, buffer reads, WAL bytes), never the actual physical storage IOPS number itself.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_database_cache_hit_ratio", "Computes the buffer cache hit ratio per database as a proxy for how much read traffic is reaching storage.",
               """
-- Buffer cache hit ratio per database. A ratio consistently below ~99% for
-- an OLTP workload is a meaningful signal that the working set no longer
-- fits comfortably in memory.
SELECT
    datname,
    blks_hit,
    blks_read,
    round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 3) AS cache_hit_ratio_pct,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY cache_hit_ratio_pct ASC NULLS LAST;
""".strip("\n"),
               "A low or declining cache hit ratio, especially trending downward over weeks, indicates the working set has outgrown available memory -- correlate with table growth before assuming an instance-class change is required.",
               related_scripts="02_top_io_generating_queries.sql"),
    sql_script("02", "02_top_io_generating_queries", "Identifies statements generating the most shared buffer reads, the strongest query-level proxy for storage I/O.",
               sb.pgss_top_by_total_time().replace("ORDER BY total_exec_time DESC", "ORDER BY shared_blks_read DESC"),
               "Statements at the top of this list are consuming the most I/O; check whether they have a supporting index or are scanning far more data than the business logic requires.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements extension must be created in the current database.",
               related_scripts="03_io_by_backend_type.sql"),
    sql_script("03", "03_io_by_backend_type", "Breaks down I/O by backend type (client backend, autovacuum, checkpointer, etc.) using pg_stat_io.",
               sb.pg_stat_io_summary(),
               "If autovacuum or checkpointer backend types dominate reads/writes, the fix is scheduling/tuning (vacuum cost limits, checkpoint_timeout), not application query optimization.",
               prerequisites="pg_stat_io view (PostgreSQL 16+) available; track_io_timing recommended for populated timing columns.",
               related_scripts="04_checkpoint_frequency.sql"),
    sql_script("04", "04_checkpoint_frequency", "Checks checkpoint frequency and the ratio of forced vs. scheduled checkpoints, a major source of write I/O.",
               sb.checkpoint_activity(),
               "A high pct_forced_checkpoints means max_wal_size is too small for the current write rate, forcing frequent, bursty checkpoint writes instead of smooth, timed ones.",
               related_scripts="05_temp_file_io.sql"),
    sql_script("05", "05_temp_file_io", "Checks temp file generation, which directly consumes read/write IOPS for spilled sorts/hashes.",
               sb.temp_file_usage_by_database(),
               "A high or rapidly growing temp_bytes total indicates work_mem is undersized for current query shapes; see query-optimization/temp-file-investigation for the query-level drill-down.",
               related_scripts="../../query-optimization/temp-file-investigation/README.md"),
]

WORKFLOWS.append(_wf(
    slug="high-latency",
    title="High Query/Transaction Latency",
    summary=(
        "End-to-end database call latency (as observed by the application "
        "or APM) has increased, without necessarily a CPU, IOPS, or lock "
        "signal being obviously dominant. This workflow is the general "
        "entry point for 'the database feels slow' reports and routes to "
        "the more specific workflow once the dominant cause is found."
    ),
    symptoms=[
        "Application/APM-reported p95/p99 database call latency increase.",
        "Increase in average query duration in pg_stat_statements without a single obvious cause.",
        "Trading/order API latency creeping upward gradually rather than spiking suddenly.",
    ],
    business_impact=[
        "Latency directly affects competitiveness in a low-latency trading environment -- even modest increases can push an exchange out of acceptable execution-speed tolerances.",
        "Gradual latency creep is easy to normalize/ignore until it crosses an SLA threshold; catching it early avoids a harder future incident.",
    ],
    root_causes=[
        "Any of: CPU saturation, lock contention, IOPS saturation, connection pool exhaustion, network/client-side factors, or a genuine plan regression.",
        "Increased network round trips per logical operation (N+1 query patterns from an application-level change).",
        "Connection setup/teardown overhead if connections are not being pooled/reused efficiently.",
    ],
    investigation_strategy=[
        "Start broad: session/state overview and wait event composition.",
        "Check pg_stat_statements for statements whose mean_exec_time has increased.",
        "Check lock contention and connection headroom as common latency amplifiers that are not visible in a single query's plan.",
        "Check replication lag if the latency is specifically reported against reader-routed traffic.",
        "If none of the above show a clear signal, treat this as network/application-side and hand off to the owning team with the evidence gathered.",
    ],
    prerequisites=[
        "pg_stat_statements for the statement-level breakdown.",
        "Knowledge of whether the affected traffic is writer-routed or reader-routed, to scope scripts 01-04 to the correct instance.",
    ],
    interpretation_guide=[
        "Wait event composition dominated by Lock -> concurrency-and-locking; dominated by IO -> high-iops/storage-and-capacity; dominated by nothing in particular but connection count is near max_connections -> connections/connection-exhaustion.",
        "If reader-routed traffic is affected and replication lag is elevated, the reported 'latency' may actually be read-after-write staleness/retry behavior at the application layer, not raw query latency -- see replication-and-ha/reader-lag-investigation.",
    ],
    remediation_immediate=[
        "Route affected traffic away from a specifically degraded instance (reader) if the issue is isolated to one node.",
        "Apply the specific remediation from whichever pivot workflow (locking/IOPS/connections/replication) the investigation points to.",
    ],
    remediation_short_term=[
        "Fix the specific statements identified with elevated mean_exec_time via indexing or rewriting.",
        "Increase reader fleet size or tune pooler settings if connection-level overhead is contributing materially.",
    ],
    remediation_long_term=[
        "Establish latency SLOs per critical query/endpoint and alert on drift before it becomes customer-visible.",
        "Review architecture for opportunities to reduce round trips (batching, caching) for latency-critical paths.",
    ],
    production_safety=[
        "All scripts are read-only.",
    ],
    escalation_criteria=[
        "No database-side signal found after completing this workflow -- hand off to application/network/SRE with the gathered evidence rather than continuing to search inside the database.",
        "Latency increase correlates with a specific reader instance -- escalate for potential instance-level AWS issue investigation.",
    ],
    related_issues=[
        "../high-iops/README.md",
        "../../concurrency-and-locking/lock-contention/README.md",
        "../../replication-and-ha/reader-lag-investigation/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_session_and_wait_overview", "Broad session/state and wait-event snapshot to orient the investigation.",
               sb.activity_overview(),
               "Use this purely as an orientation step; the goal is to decide which of scripts 02-05 to prioritize, not to draw conclusions from this alone.",
               related_scripts="02_statement_latency_trends.sql"),
    sql_script("02", "02_statement_latency_trends", "Statements with the highest mean execution time, called frequently enough to be a real trend rather than noise.",
               sb.pgss_top_by_mean_time(),
               "Compare against historical baselines if available (APM or a saved snapshot); a broad-based increase across many statements suggests a systemic cause (I/O, cache), while one or two standouts suggest a localized plan/index issue.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements extension must be created in the current database.",
               related_scripts="03_lock_wait_check.sql"),
    sql_script("03", "03_lock_wait_check", "Checks for blocked sessions as a latency amplifier that would not show up in a query's own plan.",
               sb.blocked_sessions(),
               "Any sustained blocked_duration here means part of the reported latency is lock-wait time, not execution time -- pivot to concurrency-and-locking.",
               related_scripts="04_connection_headroom.sql"),
    sql_script("04", "04_connection_headroom", "Checks connection utilization, since pool exhaustion manifests to the application as latency (waiting for a connection) rather than a slow query.",
               sb.max_connections_headroom(),
               "High utilization here means part of the reported 'query latency' may actually be connection-acquisition wait time at the pooler/application layer.",
               related_scripts="05_replication_lag_if_reader.sql"),
    sql_script("05", "05_replication_lag_if_reader", "If the affected traffic is reader-routed, checks Aurora replica lag via the cluster-native function.",
               sb.aurora_replica_status(),
               "Elevated replica_lag on the specific reader serving the affected traffic can explain apparent 'latency' that is really data-visibility staleness or client-side retry-on-stale-read behavior.",
               execution_location=ANY_INSTANCE,
               related_scripts="../../replication-and-ha/reader-lag-investigation/README.md"),
]

WORKFLOWS.append(_wf(
    slug="throughput-degradation",
    title="Throughput Degradation",
    summary=(
        "The number of transactions/queries the database successfully "
        "processes per second has dropped, even if individual query "
        "latency has not obviously changed -- for example, a batch job or "
        "ETL pipeline is completing fewer rows/sec than its established "
        "baseline, or overall xact_commit rate has fallen versus incoming "
        "request rate."
    ),
    symptoms=[
        "A batch/ETL job that normally completes in X minutes now takes significantly longer at the same input size.",
        "xact_commit rate (transactions/sec) has dropped while application-reported request volume has not.",
        "Growing backlog/queue depth in an upstream system feeding the database (e.g. a Kafka consumer lag growing against a DB sink).",
    ],
    business_impact=[
        "Throughput degradation on settlement/batch reconciliation jobs risks missed SLAs for downstream regulatory or partner reporting.",
        "If sustained, throughput degradation on the primary write path will eventually manifest as growing queue depth and, ultimately, dropped/rejected requests upstream.",
    ],
    root_causes=[
        "Serialization: increased lock contention forcing transactions to run one-at-a-time instead of concurrently.",
        "Batch size regression: an ORM/batch job now issuing many small transactions instead of fewer larger ones (or vice versa, causing lock hold time to increase).",
        "Autovacuum/checkpoint contention consuming I/O and CPU that would otherwise serve application throughput.",
        "A downstream consumer (replica, CDC) falling behind and backpressuring writes if synchronous replication or a replication-slot-based consumer is involved.",
        "Connection pool exhaustion capping concurrent in-flight transactions below the workload's needs.",
    ],
    investigation_strategy=[
        "Establish the current transaction commit rate and compare against the known baseline for this time of day/week.",
        "Check for lock contention/serialization forcing effective single-threading of what should be concurrent transactions.",
        "Check autovacuum and checkpoint activity as competing consumers of the same I/O/CPU budget.",
        "Check connection headroom, since a capped pool directly caps achievable throughput regardless of per-transaction latency.",
        "Check replication slot/WAL retention if a downstream consumer is suspected of backpressuring the writer.",
    ],
    prerequisites=[
        "A known throughput baseline (transactions/sec or job completion time) to compare against -- without one, this workflow can only establish current state, not confirm degradation.",
    ],
    interpretation_guide=[
        "A falling xact_commit rate with stable or falling active session count suggests serialization (each transaction is individually fine, but fewer run concurrently) -- check locks.",
        "A falling xact_commit rate with a growing active session count suggests a resource bottleneck (CPU/IO) is now the limiting factor -- pivot to high-cpu/high-iops.",
    ],
    remediation_immediate=[
        "If a specific blocking session is identified, resolve it per concurrency-and-locking/blocked-queries.",
        "If connection pool exhaustion is capping throughput, temporarily raise pool size within max_connections headroom.",
    ],
    remediation_short_term=[
        "Batch small transactions together (fewer, larger transactions) if per-transaction overhead is dominating.",
        "Reschedule or throttle competing maintenance (manual VACUUM/REINDEX) away from the batch window.",
    ],
    remediation_long_term=[
        "Redesign the batch/ETL job for partitioned, parallelizable processing (see partitioning/partition-performance).",
        "Establish throughput SLOs and alert on drift rather than relying on manual comparison against memory of past runs.",
    ],
    production_safety=[
        "All scripts are read-only.",
    ],
    escalation_criteria=[
        "Throughput degradation affects a regulatory/settlement deadline -- escalate immediately to database engineering leadership and compliance stakeholders.",
    ],
    related_issues=[
        "../high-database-load/README.md",
        "../../concurrency-and-locking/transaction-contention/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_transaction_commit_rate", "Reports cumulative commit/rollback counters per database to compute a commit rate across two snapshots.",
               """
-- Run this script, wait N seconds (or minutes for a batch job), then run it
-- again: the delta in xact_commit divided by the elapsed time is the
-- current transaction commit rate (transactions/sec) for that database.
SELECT
    datname,
    xact_commit,
    xact_rollback,
    round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 3) AS rollback_pct,
    numbackends,
    stats_reset
FROM pg_stat_database
WHERE datname IS NOT NULL
ORDER BY xact_commit DESC;
""".strip("\n"),
               "Compute (xact_commit_now - xact_commit_before) / elapsed_seconds and compare against the known baseline rate. A rising rollback_pct alongside falling throughput suggests contention causing serialization failures/retries, not just raw slowness.",
               related_scripts="02_lock_serialization_check.sql"),
    sql_script("02", "02_lock_serialization_check", "Checks for lock waits that would force otherwise-concurrent transactions to serialize.",
               sb.lock_detail_by_mode(),
               "A queue of sessions waiting on the same relation/row lock, especially with a long-held granted lock at the head of the queue, is the classic serialization signature behind throughput degradation.",
               related_scripts="03_autovacuum_and_checkpoint_competition.sql"),
    sql_script("03", "03_autovacuum_and_checkpoint_competition", "Checks whether autovacuum or checkpoint activity is competing for the same resources as the throughput-sensitive workload.",
               sb.autovacuum_workers_active(),
               "Vacuum workers actively processing the same hot tables the batch job writes to can materially reduce achievable throughput during the overlap window.",
               related_scripts="04_connection_pool_headroom.sql"),
    sql_script("04", "04_connection_pool_headroom", "Checks whether the connection pool itself is capping achievable concurrency/throughput.",
               sb.max_connections_headroom(),
               "If utilization is near 100% and the workload is designed to run many concurrent transactions, the pool ceiling -- not the database engine -- may be the throughput limiter.",
               related_scripts="05_replication_slot_backpressure.sql"),
    sql_script("05", "05_replication_slot_backpressure", "Checks replication slot WAL retention, since a stalled logical replication consumer can backpressure the writer.",
               sb.replication_slots_and_wal_retention(),
               "A slot with active=false and a large/growing retained WAL size means a consumer has stopped reading; this can eventually force storage growth and, in extreme cases, operational intervention to drop the slot.",
               related_scripts="../../replication-and-ha/replication-health/README.md"),
]

WORKFLOWS.append(_wf(
    slug="sudden-performance-degradation",
    title="Sudden Performance Degradation",
    summary=(
        "Performance across the database (or a major subset of workload) "
        "degraded abruptly, within seconds to minutes, rather than "
        "gradually. This workflow is optimized for rapid correlation "
        "against a specific point in time (a deploy, a failover, a "
        "maintenance action, a traffic spike) rather than open-ended "
        "root-cause exploration."
    ),
    symptoms=[
        "A step-change in latency/error rate visible on dashboards at a specific timestamp.",
        "Alerting fired within seconds/minutes of a change window, deployment, or known external event (e.g. a market volatility spike).",
    ],
    business_impact=[
        "Sudden degradation is the highest-urgency performance scenario -- it typically indicates an active incident in progress rather than a slow-building trend, and requires immediate triage.",
    ],
    root_causes=[
        "A deployment introduced a new query pattern, removed/changed an index, or changed connection pool configuration.",
        "A failover occurred, and the new writer/reader has a cold buffer cache (see performance-after-failover).",
        "A sudden traffic spike (market volatility) exceeded provisioned capacity.",
        "A long-running transaction or lock was acquired and is now blocking a wide swath of subsequent queries.",
        "An autovacuum-related emergency (anti-wraparound vacuum) began consuming significant resources.",
        "An external dependency (AWS infrastructure event, network partition) degraded connectivity/latency.",
    ],
    investigation_strategy=[
        "Immediately capture current session/lock/wait state before it changes further -- this is the most valuable forensic evidence for a transient issue.",
        "Check for a single dominant blocking session or runaway query that could explain a sudden, sharp change.",
        "Check whether a deployment or maintenance action occurred in the minutes immediately preceding the degradation.",
        "Check whether a failover occurred (compare current writer identity against expected).",
        "Check whether an anti-wraparound/emergency autovacuum has started.",
        "If nothing above explains it, capture a full production-triage snapshot for handoff/escalation.",
    ],
    prerequisites=[
        "Access to deployment/change logs to correlate timestamps.",
        "AWS Console access to check recent Aurora events (failovers, parameter group changes, maintenance).",
    ],
    interpretation_guide=[
        "A single session at the head of a long blocking chain is the highest-priority, fastest-to-fix finding -- resolve it before investigating anything else.",
        "If a failover timestamp aligns with the degradation onset, treat this as performance-after-failover (cold cache) rather than continuing generic investigation.",
    ],
    remediation_immediate=[
        "Resolve the identified blocking session per concurrency-and-locking/blocked-queries if one is found.",
        "If correlated with a deploy, coordinate an immediate rollback with the deploying team rather than attempting a forward-fix under incident pressure.",
    ],
    remediation_short_term=[
        "Apply the specific remediation from whichever specialized workflow (locking, vacuum, replication, deployment) the correlation points to.",
    ],
    remediation_long_term=[
        "Add automated pre/post-deployment health checks (database-health/pre-deployment-check, post-deployment-check) to catch regressions before they reach this severity.",
    ],
    production_safety=[
        "All investigation scripts are read-only and safe to run under incident pressure.",
        "Do not attempt speculative DDL/config changes mid-incident; gather evidence first per this workflow, then act on a specific, confirmed root cause.",
    ],
    escalation_criteria=[
        "No root cause identified within 10-15 minutes of investigation -- escalate to database engineering leadership and open the full incident-response/production-triage checklist in parallel.",
    ],
    related_issues=[
        "../performance-after-deployment/README.md",
        "../performance-after-failover/README.md",
        "../../incident-response/production-triage/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_snapshot_current_state", "Captures a broad current-state snapshot (sessions, states, wait events) as the first forensic step.",
               sb.activity_overview(),
               "Save this output with a timestamp -- it is your best evidence of what the system looked like at the moment of the incident, since pg_stat_activity is transient and will change as the incident evolves or resolves.",
               related_scripts="02_dominant_blocking_chain.sql"),
    sql_script("02", "02_dominant_blocking_chain", "Identifies the single most impactful blocking session, if one exists, to prioritize the fastest possible fix.",
               sb.blocking_sessions_detail(),
               "Sort mentally by how many blocked sessions each blocking_pid is responsible for (re-run 01_identify_blocked_sessions.sql style aggregation in concurrency-and-locking if needed) -- one session blocking dozens of others is the highest-leverage finding possible.",
               related_scripts="03_recovery_role_check.sql"),
    sql_script("03", "03_recovery_role_check", "Confirms whether this instance is currently the writer or a reader, to detect an unnoticed failover.",
               sb.cluster_recovery_role(),
               "If this instance's role has changed unexpectedly (a reader is now answering writer-routed traffic, or vice versa), the degradation is very likely failover-related -- pivot to performance-after-failover immediately.",
               related_scripts="04_autovacuum_emergency_check.sql"),
    sql_script("04", "04_autovacuum_emergency_check", "Checks for an anti-wraparound or failsafe autovacuum currently running, which can consume significant resources and cannot be safely cancelled.",
               sb.autovacuum_workers_active(),
               "If a vacuum worker's phase and the surrounding transaction-age context (see transactions-and-xid/xid-wraparound-risk) indicate an anti-wraparound vacuum, this is expected, necessary behavior -- do not cancel it; see vacuum-and-autovacuum/emergency-autovacuum for safe handling.",
               related_scripts="../../vacuum-and-autovacuum/emergency-autovacuum/README.md"),
    sql_script("05", "05_recent_wal_and_checkpoint_spike", "Checks for a recent spike in WAL generation or forced checkpoints that could correlate with the incident window.",
               sb.checkpoint_activity(),
               "A high pct_forced_checkpoints combined with the incident's onset time suggests a burst of write activity (possibly from the same deploy/traffic spike) saturated the WAL/checkpoint subsystem.",
               related_scripts="../../incident-response/production-triage/README.md"),
]

WORKFLOWS.append(_wf(
    slug="performance-after-deployment",
    title="Performance Degradation After Deployment",
    summary=(
        "Database performance degraded shortly after an application or "
        "schema deployment. This workflow focuses specifically on "
        "deployment-correlated causes: new/changed queries, index changes, "
        "migration side effects, and connection/config changes shipped "
        "with the release."
    ),
    symptoms=[
        "Degradation onset closely follows a known deployment timestamp.",
        "A specific new feature/endpoint correlates with the new load pattern.",
        "A schema migration ran as part of the deployment (new column, new index, backfill).",
    ],
    business_impact=[
        "Deployment-correlated regressions are often the most preventable class of incident, and require both an immediate fix and a process improvement to avoid recurrence.",
    ],
    root_causes=[
        "A new query pattern shipped without a supporting index.",
        "A migration that ran CREATE INDEX (non-concurrent) or ALTER TABLE, holding a stronger-than-expected lock during deployment.",
        "A CONCURRENTLY index build that failed partway through the deployment, leaving an invalid index.",
        "A connection pool/config change (new service instance count, changed pool size) increasing total connections beyond prior baseline.",
        "A backfill/data-migration job left running concurrently with production traffic.",
    ],
    investigation_strategy=[
        "Confirm what changed: review the deployment's migration/DDL history.",
        "Check for invalid indexes left behind by a failed CONCURRENTLY build during the deployment.",
        "Check pg_stat_statements for new queryids with high total time that did not exist before the deployment.",
        "Check current connection counts/pool composition against the pre-deployment baseline.",
        "Check for any lingering backfill/migration session still running.",
    ],
    prerequisites=[
        "Deployment/migration change log with timestamps.",
        "pg_stat_statements extension created in the target database.",
    ],
    interpretation_guide=[
        "An invalid index discovered here that maps to a table touched by the deployment's migration is close to a confirmed root cause.",
        "A new queryid dominating pg_stat_statements immediately after the deployment window is the direct application-level regression to hand back to the deploying team with evidence.",
    ],
    remediation_immediate=[
        "If a failed CONCURRENTLY build left an invalid index, rebuild it per schema-changes/concurrent-index-build.",
        "If a lingering backfill session is found and confirmed non-critical to complete immediately, coordinate pausing/throttling it with the owning team.",
    ],
    remediation_short_term=[
        "Ship a follow-up fix (index, query rewrite) for the new regressed query pattern.",
    ],
    remediation_long_term=[
        "Adopt pre-deployment and post-deployment checks (database-health/pre-deployment-check, post-deployment-check) as a standing part of the release process.",
        "Require CONCURRENTLY + post-build validation for all production index changes (see schema-changes/concurrent-index-build).",
    ],
    production_safety=[
        "Investigation scripts are read-only.",
        "Any corrective DDL must follow schema-changes guidance, never a same-day non-concurrent rebuild on a hot table.",
    ],
    escalation_criteria=[
        "The deployment cannot be safely forward-fixed within the incident window -- escalate to the deploying team's leadership to authorize a rollback.",
    ],
    related_issues=[
        "../sudden-performance-degradation/README.md",
        "../query-regression/README.md",
        "../../database-health/post-deployment-check/README.md",
        "../../schema-changes/failed-index-build/README.md",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_invalid_indexes_since_deployment", "Checks for invalid indexes, the most common direct side effect of a deployment's failed CONCURRENTLY build.",
               sb.invalid_indexes(),
               "Any result here maps directly to a migration step in the deployment; cross-reference the table name against the deployment's migration list.",
               related_scripts="02_new_expensive_queries.sql"),
    sql_script("02", "02_new_expensive_queries", "Surfaces the current top statements by total execution time, to identify any new queryid dominating since the deployment.",
               sb.pgss_top_by_total_time(),
               "A queryid you do not recognize from before the deployment, now near the top of this list, is very likely the new/changed code path introduced by the release.",
               required_privileges=PG_MONITOR_PLUS_PGSS,
               prerequisites="pg_stat_statements extension must be created in the current database.",
               related_scripts="03_connection_profile_change.sql"),
    sql_script("03", "03_connection_profile_change", "Checks current connection composition by application_name, to detect a pool-size or service-count change shipped with the deployment.",
               sb.connections_by_application_and_user(),
               "Compare total connections per application_name against the pre-deployment baseline; an increase proportional to a new service replica count is expected, but an unexpected spike suggests a pool misconfiguration.",
               related_scripts="04_lingering_migration_sessions.sql"),
    sql_script("04", "04_lingering_migration_sessions", "Checks for any long-running session that could be a still-active backfill/migration job from the deployment.",
               sb.long_running_transactions(),
               "A transaction whose query text matches a known migration/backfill script and has been running since the deployment window should be confirmed with the deploying team before any action is taken.",
               related_scripts="../../schema-changes/large-table-ddl/README.md"),
]

WORKFLOWS.append(_wf(
    slug="performance-after-failover",
    title="Performance Degradation After Failover",
    summary=(
        "Performance degraded following an Aurora failover (planned or "
        "unplanned) -- most commonly because the newly promoted writer "
        "starts with a cold buffer cache and must re-warm it from Aurora "
        "storage under live production load."
    ),
    symptoms=[
        "Elevated latency/IOPS immediately following a failover event, gradually improving over minutes.",
        "Application connection errors/retries at the moment of failover (expected, brief) followed by a slower-than-normal recovery period.",
        "CloudWatch showing a new writer instance identity at the failover timestamp.",
    ],
    business_impact=[
        "Failover is a designed-for HA mechanism, but the post-failover performance dip is real and, if not anticipated, can be mistaken for a new unrelated incident -- wasting response time.",
        "For a trading platform, even a brief post-failover degradation window can affect order execution during exactly the period when resilience matters most.",
    ],
    root_causes=[
        "Cold buffer cache on the newly promoted writer: shared_buffers starts empty and must be repopulated from Aurora shared storage.",
        "Connection storm as application connection pools reconnect simultaneously after the failover-induced disconnect.",
        "Query plans that were cached (prepared statement generic plans) are invalidated by the new connections' fresh sessions, temporarily increasing planning overhead.",
        "Any lock/vacuum state from the previous writer does not carry over -- this is not usually a cause, but should be confirmed, not assumed.",
    ],
    investigation_strategy=[
        "Confirm the failover occurred and identify the exact timestamp and new writer instance identity.",
        "Check current buffer cache hit ratio to confirm and quantify the cold-cache effect.",
        "Check current connection counts/rate to assess whether a reconnect storm is compounding the cold-cache effect.",
        "Check whether performance is recovering over time (re-run the cache hit ratio check every few minutes) to distinguish an expected, resolving warm-up from a separate, non-failover-related problem.",
    ],
    prerequisites=[
        "AWS Console/CloudWatch or RDS Events access to confirm failover timestamp and new writer identity.",
    ],
    interpretation_guide=[
        "A cache hit ratio that starts low immediately after failover and steadily climbs back toward baseline over minutes is the expected, self-resolving pattern -- communicate this clearly to stakeholders rather than treating it as a new open-ended incident.",
        "If the cache hit ratio does NOT recover within a reasonable window (worse than pre-failover baseline warm-up times), or another symptom (locks, specific query errors) persists, treat it as a separate incident and pivot to sudden-performance-degradation.",
    ],
    remediation_immediate=[
        "None required if this is expected post-failover cache warm-up -- monitor and communicate expected recovery time to stakeholders.",
        "If a reconnect storm is overwhelming the new writer, ensure application-side connection retry logic includes jitter/backoff (an application-side fix, not a database one).",
    ],
    remediation_short_term=[
        "Consider a brief post-failover warm-up routine (running a set of representative read queries) for critical hot tables if warm-up time is a recurring pain point.",
    ],
    remediation_long_term=[
        "Evaluate Aurora's fast failover characteristics and, if warm-up time is a recurring business risk, discuss a maintained warm standby / connection draining strategy with the platform team.",
        "Add failover drills (see disaster-recovery/cluster-failover-drill) to regularly measure and track actual warm-up duration.",
    ],
    production_safety=[
        "All scripts are read-only.",
        "Do not attempt to force a second failover or restart the instance while it is still warming up -- this resets progress and extends the degraded period.",
    ],
    escalation_criteria=[
        "Cache hit ratio and latency do not show any recovery trend after 15-20 minutes -- escalate as a distinct incident rather than continuing to assume normal warm-up.",
    ],
    related_issues=[
        "../sudden-performance-degradation/README.md",
        "../../replication-and-ha/failover-investigation/README.md",
        "../../disaster-recovery/cluster-failover-drill/README.md",
    ],
    aurora_notes=[
        "Aurora failover typically completes (DNS/endpoint cutover) within seconds to tens of seconds, which is fast relative to traditional PostgreSQL replica promotion, but the buffer cache warm-up period afterward is a separate, workload-dependent duration that Aurora's fast failover does not eliminate.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_confirm_recovery_role_and_uptime", "Confirms this instance's current writer/reader role and how recently it started, to verify a failover occurred.",
               sb.cluster_recovery_role() + "\n\nSELECT pg_postmaster_start_time() AS instance_start_time,\n       now() - pg_postmaster_start_time() AS instance_uptime;",
               "A very recent pg_postmaster_start_time combined with this instance now reporting as the writer strongly confirms a recent promotion/failover.",
               related_scripts="02_cache_warmup_progress.sql"),
    sql_script("02", "02_cache_warmup_progress", "Tracks buffer cache hit ratio to quantify and monitor cold-cache recovery progress.",
               """
-- Buffer cache hit ratio for the current database. Re-run this every few
-- minutes after a failover: a steadily improving ratio confirms normal,
-- self-resolving cache warm-up rather than a separate ongoing problem.
SELECT
    datname,
    blks_hit,
    blks_read,
    round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 3) AS cache_hit_ratio_pct
FROM pg_stat_database
WHERE datname = current_database();
""".strip("\n"),
               "An improving trend across repeated runs is expected and healthy; a flat, persistently low ratio well past a typical warm-up window (minutes, not tens of minutes, for most working sets) warrants pivoting to sudden-performance-degradation.",
               related_scripts="03_reconnect_storm_check.sql"),
    sql_script("03", "03_reconnect_storm_check", "Checks current connection count/composition for a reconnect storm compounding the cache warm-up effect.",
               sb.connections_by_state(),
               "A connection count far above the pre-failover baseline, especially many sessions in 'active' state simultaneously attempting reconnection, indicates client-side retry logic is compounding the recovery -- an application-side backoff/jitter fix may be needed in addition to waiting out the cache warm-up.",
               related_scripts="../../replication-and-ha/failover-investigation/README.md"),
]
