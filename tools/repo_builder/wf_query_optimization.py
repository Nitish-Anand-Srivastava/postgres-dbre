"""Workflow definitions: query-optimization/ category (10 issue directories)."""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import (
    ANY_INSTANCE,
    GUARDED_DDL,
    PG_MONITOR,
    PG_MONITOR_PLUS_PGSS,
    WRITER_PREFERRED,
    md_script,
    sql_script,
)
from .model import Workflow

CATEGORY_SLUG = "query-optimization"
CATEGORY_TITLE = "Query Optimization"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


PGSS_PREREQ = (
    "pg_stat_statements must be listed in shared_preload_libraries (an Aurora DB "
    "cluster parameter-group change that requires a reboot) and created in the "
    "current database. This script detects its absence and prints an "
    "instructional notice instead of failing, so it is safe to run either way."
)

EXPLAIN_ANALYZE_WARNING = (
    "Deciding to actually execute a candidate production query is an operator "
    "judgement call, not something an investigation script may do on the "
    "operator's behalf. That is why every EXPLAIN ANALYZE step in this toolkit "
    "is a markdown runbook rather than a .sql file."
)


def _pgss_guarded(body: str) -> str:
    """Wrap a pg_stat_statements query in an extension-presence guard.

    The guard uses psql's ``\\gset`` / ``\\if`` so the script runs unmodified
    against a database where pg_stat_statements has never been created: it
    prints an instructional notice instead of raising "relation
    pg_stat_statements does not exist". Creating an extension is a
    change-managed administrative action and is never performed implicitly by
    an investigation script.
    """
    return (
        "-- pg_stat_statements presence check. This script only detects whether the\n"
        "-- extension is already available; it never creates it.\n"
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS pgss_available\n"
        "\\gset\n"
        "\n"
        "\\if :pgss_available\n"
        f"{body}\n"
        "\\else\n"
        "SELECT 'pg_stat_statements is not installed in this database, so statement-level '\n"
        "       'statistics are unavailable. Ask an administrator to add '\n"
        "       'pg_stat_statements to shared_preload_libraries in the Aurora DB cluster '\n"
        "       'parameter group (a reboot is required for that change to take effect) '\n"
        "       'and then run CREATE EXTENSION pg_stat_statements; in a change-managed '\n"
        "       'session. Without it, query-level investigation must fall back to '\n"
        "       'application-side latency metrics plus the catalog and table-level '\n"
        "       'statistics used by the other scripts in this workflow.'  AS notice;\n"
        "\\endif"
    )


def _planner_settings() -> str:
    return """
-- Planner and executor configuration: the inputs that decide which plan
-- shape PostgreSQL chooses for a given query. Differences here between a
-- staging environment and production explain a surprising share of
-- "the same query has a different plan in production" reports.
--
-- reset_val is the value a new session would get; setting is the value in
-- THIS session (an application that issues SET at connection time can be
-- running with something entirely different from the parameter group).
-- source shows where the value came from, and pending_restart flags a
-- parameter-group change that has been applied but not yet activated by
-- the required reboot.
SELECT
    name,
    setting,
    unit,
    boot_val                                                     AS engine_default,
    reset_val                                                    AS new_session_value,
    source,
    context,
    pending_restart,
    short_desc
FROM pg_settings
WHERE name IN (
    'work_mem', 'hash_mem_multiplier', 'maintenance_work_mem', 'temp_buffers',
    'shared_buffers', 'effective_cache_size', 'effective_io_concurrency',
    'random_page_cost', 'seq_page_cost', 'cpu_tuple_cost',
    'cpu_index_tuple_cost', 'cpu_operator_cost',
    'default_statistics_target', 'from_collapse_limit', 'join_collapse_limit',
    'geqo', 'geqo_threshold', 'plan_cache_mode', 'jit', 'jit_above_cost',
    'enable_seqscan', 'enable_indexscan', 'enable_indexonlyscan',
    'enable_bitmapscan', 'enable_nestloop', 'enable_hashjoin',
    'enable_mergejoin', 'enable_memoize', 'enable_sort',
    'enable_incremental_sort', 'enable_partitionwise_join',
    'enable_partitionwise_aggregate',
    'max_parallel_workers_per_gather', 'parallel_setup_cost',
    'parallel_tuple_cost', 'track_io_timing', 'log_temp_files',
    'temp_file_limit'
)
ORDER BY name;
""".strip("\n")


def _memory_and_spill_settings() -> str:
    return """
-- The memory settings that decide whether a sort, hash, or materialize
-- step stays in RAM or spills to a temporary file on local instance
-- storage, shown both as the value this session would get and as the value
-- currently in effect for this session.
--
-- work_mem is per sort/hash NODE, not per query and not per connection: a
-- single query with several sorts and hash joins, running in parallel
-- across workers, can consume a multiple of work_mem simultaneously. That
-- is why raising it globally on a high-connection exchange writer is
-- dangerous, and why the safe experiment is a session-scoped SET LOCAL.
SELECT
    name,
    setting,
    unit,
    boot_val                                                     AS engine_default,
    reset_val                                                    AS new_session_value,
    source,
    context,
    short_desc
FROM pg_settings
WHERE name IN (
    'work_mem', 'hash_mem_multiplier', 'maintenance_work_mem',
    'temp_buffers', 'temp_file_limit', 'log_temp_files',
    'max_parallel_workers_per_gather', 'max_parallel_workers',
    'shared_buffers', 'effective_cache_size',
    'enable_sort', 'enable_incremental_sort', 'enable_hashagg'
)
ORDER BY name;

SELECT
    current_setting('work_mem')                                  AS session_work_mem,
    current_setting('hash_mem_multiplier')                        AS session_hash_mem_multiplier,
    current_setting('temp_buffers')                               AS session_temp_buffers,
    current_setting('log_temp_files')                             AS session_log_temp_files,
    current_setting('max_parallel_workers_per_gather')            AS session_parallel_workers;
""".strip("\n")


def _index_inventory_for_table() -> str:
    return """
-- Every index on one specific table, with its definition and its real
-- usage counters. Edit the two \\set lines to name the table you are
-- investigating.
--
-- The relation name is only ever compared inside a catalog WHERE clause
-- here (never used as a FROM target and never cast with ::regclass), so a
-- name that does not exist simply returns zero rows instead of raising
-- "relation does not exist".
\\set schema_name 'public'
\\set table_name 'orders'
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    i.relname                                                    AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                       AS index_size,
    ix.indisunique,
    ix.indisprimary,
    ix.indisvalid,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    s.last_idx_scan,
    pg_get_indexdef(ix.indexrelid)                                AS index_definition
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_index ix ON ix.indrelid = c.oid
JOIN pg_class i ON i.oid = ix.indexrelid
LEFT JOIN pg_stat_all_indexes s ON s.indexrelid = ix.indexrelid
WHERE n.nspname = :'schema_name'
  AND c.relname = :'table_name'
ORDER BY pg_relation_size(i.oid) DESC;
""".strip("\n")


def _column_statistics_for_table() -> str:
    return """
-- The planner's actual picture of one table's data distribution, as stored
-- by the last ANALYZE. This is the ground truth for "why did it estimate
-- 3 rows when there are 4 million". Edit the two \\set lines first.
--
-- Reading pg_stats requires SELECT on the table or membership in
-- pg_read_all_stats (which pg_monitor includes). The relation name is only
-- compared in a WHERE clause, so a non-existent name yields zero rows
-- rather than an error.
--
-- NOTE: most_common_vals and histogram_bounds are declared as the
-- pseudo-type anyarray, which cannot be cast to text or passed to
-- array-processing functions. most_common_freqs is a concrete real[] with
-- exactly one entry per most-common value, so its length is used below to
-- report how many MCV entries were stored, and a simple NULL test reports
-- whether a histogram exists at all.
\\set schema_name 'public'
\\set table_name 'orders'
SELECT
    schemaname                                                   AS schema_name,
    tablename                                                    AS table_name,
    attname                                                      AS column_name,
    inherited,
    null_frac,
    avg_width,
    n_distinct,
    array_length(most_common_freqs, 1)                            AS mcv_entries,
    most_common_freqs[1]                                          AS most_common_value_frequency,
    (histogram_bounds IS NOT NULL)                                AS has_histogram,
    correlation
FROM pg_stats
WHERE schemaname = :'schema_name'
  AND tablename = :'table_name'
ORDER BY attname;
""".strip("\n")


WORKFLOWS: List[Workflow] = []

# ---------------------------------------------------------------------------
# analyze-query-plan
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="analyze-query-plan",
    title="Analyze a Query Plan",
    summary=(
        "The structured method for taking a specific slow statement on an Aurora PostgreSQL 17 "
        "exchange database and understanding why the planner chose the plan it did. It starts "
        "from evidence that costs nothing (pg_stat_statements aggregates, table and index "
        "statistics, planner configuration), and only then decides whether capturing a real "
        "execution profile is justified -- because EXPLAIN is free and EXPLAIN ANALYZE actually "
        "runs the statement, with every consequence that implies on a production order book."
    ),
    symptoms=[
        "A specific statement has been identified as slow by pg_stat_statements, by application tracing, or by a user-visible latency complaint on order placement, balance lookup, or trade history.",
        "A query performs acceptably in staging against a small dataset and unacceptably in production against hundreds of millions of rows.",
        "Latency for one statement is bimodal: usually fast, occasionally many times slower, suggesting more than one plan or a parameter-dependent plan choice.",
    ],
    business_impact=[
        "A single badly planned statement on the order-placement or balance-check path multiplies across the exchange's request rate: at thousands of requests per second, an extra 50ms per call is a queue that never drains during a volatility spike.",
        "Plan problems tend to be non-linear: a nested loop that is fine at 10,000 rows becomes catastrophic at 10 million, so a query that has been healthy for a year can fail abruptly as a table crosses a threshold.",
        "Reading plans correctly is what separates a targeted 20-minute fix (one index, one ANALYZE, one rewritten predicate) from a speculative multi-day optimization effort.",
    ],
    root_causes=[
        "Estimation error: the planner's row estimate for a node is far from reality, so it chooses a join strategy that would have been correct for the estimated size.",
        "Stale or insufficient statistics: last ANALYZE predates a bulk load, or default_statistics_target is too low for a skewed column such as market symbol or order status.",
        "Missing or unusable index: no index supports the predicate, or an index exists but the predicate is not sargable (a function or type cast wrapped around the indexed column).",
        "Correlated predicates the planner treats as independent, producing an estimate that is the product of two selectivities when the real selectivity is far higher -- the classic case for extended statistics.",
        "Configuration that misrepresents the hardware: random_page_cost and effective_cache_size left at defaults that do not describe Aurora's distributed storage and the instance's real cache size.",
        "Parameter-sensitive plans: a generic plan cached for a prepared statement that is good for typical parameters and terrible for outliers (one enormous account, one extremely liquid trading pair).",
    ],
    investigation_strategy=[
        "Identify the statement objectively from pg_stat_statements, ranked by total time, so effort goes where the database actually spends it.",
        "Check mean and maximum execution time for that statement to distinguish 'always slow' from 'occasionally catastrophic'.",
        "If planning time is being tracked, check whether time is going into planning rather than execution.",
        "Review the planner configuration that shaped the decision.",
        "Inspect the tables and indexes the statement touches: sizes, index definitions, usage counters, and statistics freshness.",
        "Only then decide how to capture a plan: EXPLAIN first (free, no execution), and EXPLAIN ANALYZE only under the guardrails in the runbook.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "pg_stat_statements installed, ideally with pg_stat_statements.track_planning enabled if planning time is in question (it is off by default because it adds overhead).",
        "The statement text or queryid under investigation, plus realistic parameter values for it -- a plan captured with unrepresentative parameters answers the wrong question.",
        "Awareness of which tables the statement touches, so the table-level steps can be pointed at them.",
    ],
    interpretation_guide=[
        "EXPLAIN shows the plan the planner would choose and its cost estimates. It does not execute the statement, takes no row locks, is safe against SELECT and against INSERT/UPDATE/DELETE alike, and should always be the first capture.",
        "EXPLAIN ANALYZE executes the statement for real. For a SELECT that means consuming the same I/O, CPU, memory, and time as the original slow query; for a data-modifying statement it means actually performing the writes unless it is wrapped in a transaction that is rolled back.",
        "Cost units are not milliseconds. Compare costs between alternative plans for the same query, never across different queries, and never treat a cost number as a time prediction.",
        "The single most informative signal in an EXPLAIN ANALYZE plan is the ratio of estimated rows to actual rows at each node. Find the deepest node where they diverge by an order of magnitude: that is where the planner was misled, and everything above it is a consequence rather than a cause.",
        "For nodes inside a loop, actual rows is reported per loop: multiply by the loops value to get the true total, which is exactly where a nested loop's real cost hides.",
        "PostgreSQL 17 adds EXPLAIN (ANALYZE, SERIALIZE), which measures the time spent converting result rows into wire format. Use it when a query returns a very large result set and the plan itself looks reasonable -- the cost may be in serialization and transfer rather than in the plan.",
        "On Aurora, a buffer miss is a read from the distributed storage layer rather than a local disk read, so the BUFFERS output (shared read versus shared hit) maps more directly to latency than it does on a self-managed server with a local page cache.",
    ],
    remediation_immediate=[
        "If a single statement is actively harming the platform, apply the narrowest safe mitigation first: cancel or rate-limit the offending workload, or have the application stop issuing it, while the real fix is prepared.",
        "If the cause is clearly stale statistics, run a targeted ANALYZE on the implicated table as a change-managed action (see stale-statistics for the guarded runbook).",
    ],
    remediation_short_term=[
        "Add the specific missing index identified by the plan, built with CREATE INDEX CONCURRENTLY so the exchange's write path is not blocked.",
        "Rewrite a non-sargable predicate (a function or cast applied to the indexed column) so an existing index can be used, or add a matching expression index.",
        "Raise the statistics target on a badly estimated skewed column, or create extended statistics for correlated predicate pairs, then re-analyze.",
    ],
    remediation_long_term=[
        "Capture and store plan baselines for the exchange's critical statements so a future regression is detected by comparison rather than by a user complaint.",
        "Tune random_page_cost and effective_cache_size to describe the actual Aurora instance rather than the 1990s-era defaults, cluster-wide, under change management.",
        "Partition the very large tables whose scan sizes drive these plan problems, so partition pruning reduces the planner's work rather than requiring ever more index tuning.",
    ],
    production_safety=[
        "Every .sql script in this workflow is read-only: statistics views, catalogs, and configuration only. None of them executes the statement under investigation.",
        "The EXPLAIN and EXPLAIN ANALYZE guidance is deliberately a markdown runbook, not an executable script, because running the candidate statement is a decision that requires an operator to weigh production impact. " + EXPLAIN_ANALYZE_WARNING,
        "Never run EXPLAIN ANALYZE on a data-modifying statement outside an explicit transaction you intend to roll back, and never run it at all against a statement whose full execution you are not prepared to complete.",
        "Prefer capturing an execution profile on a reader instance when the statement is a read, so the writer's order-matching path is unaffected.",
    ],
    escalation_criteria=[
        "The plan is understood but the fix requires a schema change to a hot exchange table (a new index on orders, ledger_entries, or wallets) -- escalate to schema-changes for a safe rollout plan.",
        "The statement cannot be made acceptably fast without an application-side change to its shape, pagination, or caching strategy.",
        "The plan is correct and the statement is simply doing too much work for the data volume -- escalate to a partitioning or archival conversation rather than continuing to tune.",
        "A plan regression is suspected rather than a persistently bad plan -- switch to the query-plan-regression workflow, which is built around before/after comparison.",
    ],
    related_issues=[
        "../cardinality-estimation/README.md",
        "../stale-statistics/README.md",
        "../nested-loop-problems/README.md",
        "../query-plan-regression/README.md",
        "../inefficient-index-usage/README.md",
        "../../performance/slow-queries/README.md",
        "../../tables-and-indexes/missing-index-candidates/README.md",
    ],
    aurora_notes=[
        "Aurora's storage layer is network-attached and shared, so a shared buffer miss costs a network round trip. random_page_cost left at the community default of 4.0 often overstates the penalty for random access relative to Aurora's actual behavior, and effective_cache_size left low understates how much data is effectively cached -- both push the planner toward sequential scans it should not choose.",
        "Aurora does not support ALTER SYSTEM for planner parameters. Persistent changes go through the DB cluster or DB instance parameter group; per-session experiments use SET or SET LOCAL and affect only that session.",
        "Readers are the right place to capture an execution profile for a read-only statement: they carry a copy of the same data, and a heavy EXPLAIN ANALYZE there does not compete with order matching on the writer. Be aware their cache contents differ from the writer's, so buffer hit ratios in the plan will not match exactly.",
        "pg_stat_statements counters live in instance memory and are reset by an Aurora failover, so a statement's history disappears when the writer changes. Persist the output if it is needed as a baseline.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_identify_statement_by_total_time",
        "Ranks statements by cumulative execution time so plan analysis effort is spent where the database actually spends its time.",
        _pgss_guarded(sb.pgss_top_by_total_time()),
        "Rank by total time, not mean time: on an exchange the statement worth analyzing is usually a fast one executed enormously often (an order-book read, a balance check), not a slow report run twice a day. Note the queryid of the statement you are investigating -- every later step in this workflow refers back to it. A low cache_hit_pct on a top statement points at an I/O-bound plan, which is the strongest early hint that the access path, not the machine, is the problem.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="02_statement_latency_profile.sql",
        table_purpose="Top statements by cumulative execution time.",
    ),
    sql_script(
        "02", "02_statement_latency_profile",
        "Shows mean, standard deviation, and maximum execution time per statement to separate consistently slow from occasionally catastrophic.",
        _pgss_guarded(sb.pgss_top_by_mean_time()),
        "A high mean with a low standard deviation means one stable, consistently bad plan -- analyze it directly. A modest mean with a very large max and standard deviation means the statement is parameter-sensitive: it is fast for typical values and pathological for outliers such as the single most active trading pair or the largest institutional account. That distinction determines whether you capture a plan with typical parameters or specifically with the outlier values.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="03_planning_vs_execution_time.sql",
        table_purpose="Mean, stddev, and max execution time per statement.",
    ),
    sql_script(
        "03", "03_planning_vs_execution_time",
        "Separates time spent planning from time spent executing, to detect planning-bound statements.",
        _pgss_guarded("""
-- Planning time versus execution time per statement.
--
-- IMPORTANT: the plan-time columns are only populated when
-- pg_stat_statements.track_planning is on. It is OFF by default (it adds
-- measurable overhead on high-frequency workloads), so all-zero plan times
-- here mean "not being tracked", not "planning is free". Enable it
-- deliberately, for a bounded period, via the Aurora DB cluster parameter
-- group if planning cost is genuinely in question.
\\set top_n 20
SELECT
    queryid,
    calls,
    round(total_plan_time::numeric, 2)                            AS total_plan_time_ms,
    round(mean_plan_time::numeric, 4)                             AS mean_plan_time_ms,
    round(total_exec_time::numeric, 2)                            AS total_exec_time_ms,
    round(mean_exec_time::numeric, 4)                             AS mean_exec_time_ms,
    round(
        (100.0 * total_plan_time / NULLIF(total_plan_time + total_exec_time, 0))::numeric, 2
    )                                                             AS pct_time_spent_planning,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC
LIMIT :top_n;

-- Is planning time actually being tracked in this cluster?
SELECT
    name,
    setting,
    source,
    short_desc
FROM pg_settings
WHERE name IN ('pg_stat_statements.track_planning', 'pg_stat_statements.track', 'plan_cache_mode')
ORDER BY name;
""".strip("\n")),
        "If the second result set shows track_planning is off, the plan-time columns are structurally zero and prove nothing. When it is on, a pct_time_spent_planning above roughly 10% on a very high-frequency statement is significant: it usually means a query with many joins (planning cost grows steeply with join count and join_collapse_limit) or heavy use of unprepared statements where the application could use prepared statements instead. Most exchange OLTP statements should be overwhelmingly execution-bound.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="04_planner_configuration.sql",
        table_purpose="Planning time vs execution time per statement.",
    ),
    sql_script(
        "04", "04_planner_configuration",
        "Snapshots the planner and executor configuration that shaped the plan choice.",
        _planner_settings(),
        "Check three things in order. First, any enable_* parameter set to off: these are debugging tools and must never be off in production, but they do occasionally survive an incident. Second, random_page_cost and effective_cache_size: community defaults describe a small machine with local spinning disks, not an Aurora instance with a large buffer cache and network-attached storage, and leaving them unadjusted biases the planner toward sequential scans. Third, the source column -- a value that came from a session-level SET rather than the parameter group means the application is overriding cluster configuration at connection time.",
        required_privileges=PG_MONITOR,
        related_scripts="05_target_table_indexes_and_statistics.sql",
        table_purpose="Planner and executor configuration snapshot.",
    ),
    sql_script(
        "05", "05_target_table_indexes_and_statistics",
        "Inventories the indexes and statistics freshness of the table the statement touches.",
        _index_inventory_for_table() + "\n\n" + sb.statistics_freshness(),
        "Read the index list against the statement's WHERE, JOIN, and ORDER BY clauses: the question is not 'are there indexes' but 'is there an index whose leading columns match this predicate'. An index with idx_scan at zero while the statement runs constantly means the planner is rejecting it -- usually because of a type mismatch, a function wrapped around the column, or statistics that make a sequential scan look cheaper. Then check statistics freshness for the same table: a high n_mod_since_analyze means every estimate in the plan is built on an outdated picture.",
        expected_runtime="Low (sub-second to a few seconds).",
        related_scripts="06_capture_plan_safely.md, ../stale-statistics/README.md",
        table_purpose="Index inventory and statistics freshness for the target table.",
    ),
    md_script(
        "06", "06_capture_plan_safely",
        "Guarded runbook for capturing a query plan: EXPLAIN first, EXPLAIN ANALYZE only under explicit production guardrails.",
        (
            "## Why this step is a runbook and not a script\n\n"
            "Capturing a plan means running something against production. `EXPLAIN` is harmless;\n"
            "`EXPLAIN ANALYZE` is not, because it **actually executes the statement**. A toolkit\n"
            "script cannot know whether the statement under investigation is a read of the trade\n"
            "history or an `UPDATE` on the wallet ledger, so the decision stays with the\n"
            "operator. Read this whole file before running anything.\n\n"
            "## The three capture modes, in increasing order of risk\n\n"
            "### 1. Plan only -- always safe\n\n"
            "```sql\n"
            "EXPLAIN (FORMAT TEXT)\n"
            "SELECT ... ;                      -- the statement under investigation\n"
            "```\n\n"
            "- Does **not** execute the statement. Safe against `SELECT`, `INSERT`, `UPDATE`,\n"
            "  `DELETE` alike, on the writer, at peak trading hours.\n"
            "- Shows the chosen plan shape, the estimated row counts, and the cost estimates.\n"
            "- This is enough to answer most questions: which join strategy, which index, in\n"
            "  what order. Start here, always.\n"
            "- Add `VERBOSE` for output column lists and `COSTS OFF` if you want a stable plan\n"
            "  shape to store as a baseline for later comparison.\n\n"
            "### 2. Plan plus real measurements -- executes the statement\n\n"
            "```sql\n"
            "SET LOCAL statement_timeout = '10s';   -- bound the blast radius first\n"
            "EXPLAIN (ANALYZE, BUFFERS, TIMING, FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "- **This runs the query for real.** It will take at least as long as the original\n"
            "  slow execution, and slightly longer because of instrumentation overhead.\n"
            "- Set `statement_timeout` first, in the same session, so a pathological plan cannot\n"
            "  itself become the next incident.\n"
            "- Prefer a reader instance for read-only statements: the data is the same and the\n"
            "  writer's order-matching path stays untouched. Expect buffer hit counts to differ\n"
            "  from the writer's, because each instance has its own cache.\n"
            "- `BUFFERS` is the highest-value option on Aurora: shared read counts are storage\n"
            "  round trips, which is where the latency actually comes from.\n"
            "- On PostgreSQL 17 you can add `SERIALIZE` to measure the cost of converting rows\n"
            "  to wire format, which matters for statements returning very large result sets\n"
            "  (a full order-book snapshot, a bulk trade export).\n\n"
            "### 3. Plan plus real measurements for a write statement -- highest risk\n\n"
            "```sql\n"
            "BEGIN;\n"
            "SET LOCAL statement_timeout = '10s';\n"
            "EXPLAIN (ANALYZE, BUFFERS)\n"
            "UPDATE ... ;                      -- the write statement under investigation\n"
            "ROLLBACK;                          -- MANDATORY: without this, the write is permanent\n"
            "```\n\n"
            "- The statement is genuinely executed inside the transaction. It takes every row\n"
            "  lock the real statement would take, generates the same WAL, fires the same\n"
            "  triggers, and blocks concurrent writers on those rows for its whole duration.\n"
            "- `ROLLBACK` undoes the data change. It does **not** undo the lock contention, the\n"
            "  WAL generated, the dead tuples created, or the replica lag caused while it ran.\n"
            "- Do not do this against `orders`, `wallets`, `ledger_entries`, or any settlement\n"
            "  table during trading hours. Use a restored snapshot or a pre-production clone\n"
            "  with representative data volume instead.\n\n"
            "## Choosing parameters for the capture\n\n"
            "pg_stat_statements normalizes literals to `$1`, `$2`, so the statement text it\n"
            "stores is not directly runnable. Substitute **representative** values, and note\n"
            "that for a parameter-sensitive statement there are two interesting captures:\n\n"
            "- typical parameters (an average account, a mid-liquidity trading pair), and\n"
            "- the outlier parameters that produced the `max_exec_time` seen in script 02 (the\n"
            "  largest institutional account, the single most active pair, the widest date\n"
            "  range).\n\n"
            "A plan captured only with typical values will often look perfectly reasonable while\n"
            "the real production pain comes entirely from the outliers.\n\n"
            "## Reading what you captured\n\n"
            "1. Find the deepest node where `rows=` (estimate) and `actual rows=` differ by an\n"
            "   order of magnitude or more. That node is the cause; everything above it is a\n"
            "   consequence of the planner believing that number.\n"
            "2. Multiply `actual rows` by `loops` for any node on the inner side of a nested\n"
            "   loop -- the per-loop figure hides the real total work.\n"
            "3. Look for `Sort Method: external merge  Disk: NkB` (a sort spill) and for\n"
            "   `Batches: N  Memory Usage: MkB` with N greater than 1 on a Hash node (a hash\n"
            "   spill). Both mean `work_mem` was insufficient for that node.\n"
            "4. Look for `Seq Scan` on a large table where an index scan was expected, and for\n"
            "   `Rows Removed by Filter` far exceeding the rows returned -- both point at a\n"
            "   missing or unusable index.\n"
            "5. Compare `shared hit` against `shared read`: a high read count on Aurora is\n"
            "   storage traffic and translates directly into latency.\n\n"
            "## Record the result\n\n"
            "Save the plan text, the exact parameter values used, the instance it was captured\n"
            "on, and the timestamp, alongside the queryid from script 01. That record is what\n"
            "makes the `query-plan-regression` workflow possible later; without it, a future\n"
            "'this got slower' report has nothing to compare against.\n"
        ),
        "Work down the three capture modes and stop at the least risky one that answers your question -- most plan problems are fully diagnosable from the plan-only capture plus the statistics evidence from script 05. Only escalate to EXPLAIN ANALYZE when you specifically need estimated-versus-actual row counts or real buffer numbers, and only ever wrap a write statement in an explicit transaction that ends in ROLLBACK.",
        safety=GUARDED_DDL,
        expected_impact="Mode 1 has no impact. Mode 2 consumes the same resources as one full execution of the statement. Mode 3 additionally takes row locks, generates WAL, and creates dead tuples even though the change is rolled back.",
        required_privileges="The same privileges the statement under investigation requires. No elevated privileges beyond that.",
        prerequisites="Scripts 01-05 completed, the target statement and representative parameter values identified, and a decision made about which instance to capture on.",
        execution_location="Reader instance preferred for read-only statements; writer only when the statement itself must run on the writer.",
        expected_runtime="Mode 1: milliseconds. Mode 2: at least the statement's normal execution time. Mode 3: the same, plus lock hold time.",
        related_scripts="../query-plan-regression/README.md, ../cardinality-estimation/README.md",
        table_purpose="Guarded EXPLAIN / EXPLAIN ANALYZE capture runbook.",
    ),
]

# ---------------------------------------------------------------------------
# nested-loop-problems
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="nested-loop-problems",
    title="Nested Loop Join Problems",
    summary=(
        "A nested loop join re-executes the inner side once per outer row. That is the fastest "
        "possible strategy when the outer side really does produce a handful of rows and the "
        "inner side has a supporting index -- and it is the single most destructive plan shape "
        "in PostgreSQL when the planner underestimates the outer row count. This workflow finds "
        "statements whose block-access-per-row profile is characteristic of a runaway nested "
        "loop, identifies the estimation error or missing index behind it, and guards the "
        "decision to confirm it with a real execution profile."
    ),
    symptoms=[
        "A statement's execution time scales super-linearly with data growth: fine last quarter, unusable now, with no code change in between.",
        "Very high shared block reads per row returned -- the query touches far more of the database than the size of its result justifies.",
        "A join between a filtered table and a large table (trades, ledger_entries, order_fills) that is fast for narrow filters and pathological for wide ones.",
        "An EXPLAIN ANALYZE plan showing a Nested Loop whose inner node has a large loops count, where actual rows multiplied by loops is orders of magnitude above the estimate.",
    ],
    business_impact=[
        "A runaway nested loop consumes CPU and storage I/O out of all proportion to the work it accomplishes, so a single such statement can saturate an instance and degrade every unrelated query on the exchange at the same time.",
        "The failure is abrupt rather than gradual: the plan stays reasonable until the outer row count crosses a threshold, then collapses, which makes it a common cause of 'nothing changed but everything is slow' incidents.",
        "Because it commonly appears on reporting, reconciliation, and compliance-export queries joining trades to accounts to ledger entries, it tends to fire at month end -- exactly when those reports are time-critical.",
    ],
    root_causes=[
        "Cardinality underestimation on the outer side: the planner expects a few rows, chooses a nested loop, and then executes the inner side millions of times.",
        "Stale statistics after a bulk load or backfill, so the planner's row estimates describe a table that no longer exists.",
        "A missing index on the inner side's join key, turning each of the millions of inner executions into a sequential scan.",
        "Correlated predicates treated as independent (for example market symbol and order status, which are strongly correlated on an exchange), multiplying selectivities and producing an estimate far below reality.",
        "A join key whose type differs between the two tables, preventing index use on the inner side even though an index exists.",
        "A LIMIT clause that makes a nested loop look cheap to the planner because it expects to stop early, when in practice the filter matches nothing until very late in the scan.",
    ],
    investigation_strategy=[
        "Find statements with an extreme ratio of blocks accessed to rows returned -- the fingerprint of repeated inner-side execution.",
        "Check which tables are being scanned sequentially in bulk, since an unindexed inner side turns into a scan per outer row.",
        "Check for foreign keys without a supporting index, the most common structural cause of an unindexed inner side in a normalized exchange schema.",
        "Check statistics freshness on the tables involved, because underestimation is usually a statistics problem rather than a planner defect.",
        "Review the planner settings that influence the nested loop choice, including enable_memoize, which materially changes how expensive repeated inner lookups are.",
        "Only then capture a plan, following the guarded runbook, to confirm the nested loop and measure the true loop count.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "pg_stat_statements for the statement-level steps (the scripts degrade gracefully to a notice without it).",
        "The identity of the statement or report under investigation, and the tables it joins.",
    ],
    interpretation_guide=[
        "Blocks accessed per row returned is the key derived metric: a statement returning 50 rows while touching two million blocks is re-scanning something, and a nested loop is the most likely reason.",
        "A nested loop is not intrinsically wrong. With a small outer side and an indexed inner side it is the optimal join for most OLTP lookups on an exchange -- the goal is to find the ones where the outer estimate was wrong, not to eliminate the plan shape.",
        "PostgreSQL 14 and later can place a Memoize node above the inner side, caching results for repeated parameter values. It softens the damage when inner keys repeat, and does nothing when they are distinct -- so a plan with Memoize can still be a runaway loop.",
        "If the estimate is right and the loop count is genuinely large, the fix is a different join strategy (usually a hash join), which is normally achieved by fixing statistics or adding an index rather than by disabling the plan type.",
        "Never fix this by turning off enable_nestloop in production. It is a diagnostic tool: setting it off for a single session proves the alternative plan is better, but leaving it off distorts every other query on the connection.",
    ],
    remediation_immediate=[
        "Stop the bleeding first if a runaway statement is currently saturating the instance: have the application stop issuing it, or cancel the specific backend under the concurrency-and-locking runbook.",
        "If statistics are clearly stale on a joined table, a targeted ANALYZE frequently restores a sane plan within seconds (run it as a change-managed action -- see stale-statistics).",
    ],
    remediation_short_term=[
        "Add the missing index on the inner side's join key, built with CREATE INDEX CONCURRENTLY.",
        "Add extended statistics for correlated predicate pairs so the outer-side estimate stops being the product of two independent selectivities.",
        "Raise the statistics target on the skewed column driving the underestimate, then re-analyze that table.",
        "Fix join-key type mismatches in the schema or the query so the inner index becomes usable at all.",
    ],
    remediation_long_term=[
        "Rewrite or decompose the reporting and reconciliation queries that repeatedly produce this shape, for example by materializing an intermediate aggregate rather than joining raw trades to raw ledger entries.",
        "Partition the large inner-side tables so that even a badly chosen loop touches only the relevant partitions.",
        "Add plan-shape regression testing against production-scale data for the exchange's critical reports, so an estimation-driven collapse is caught before release.",
    ],
    production_safety=[
        "All .sql scripts here are read-only aggregate and catalog queries; none executes the statement under investigation.",
        "Confirming a nested loop with EXPLAIN ANALYZE means executing the runaway statement in full, which is exactly the thing causing the incident -- that is why it is a guarded runbook with an explicit statement_timeout requirement. " + EXPLAIN_ANALYZE_WARNING,
        "Never disable enable_nestloop cluster-wide as a remediation; if it is used at all, it is used with SET LOCAL inside a single diagnostic session.",
    ],
    escalation_criteria=[
        "A runaway nested loop is currently saturating the writer and the owning team cannot stop issuing the statement -- escalate as an active incident.",
        "The fix requires a new index on a hot exchange table -- escalate to schema-changes for a safe concurrent rollout.",
        "Correct statistics and correct indexes still produce the loop, meaning the query shape itself must change -- escalate to the application team with the plan evidence.",
    ],
    related_issues=[
        "../analyze-query-plan/README.md",
        "../cardinality-estimation/README.md",
        "../stale-statistics/README.md",
        "../hash-join-analysis/README.md",
        "../inefficient-index-usage/README.md",
        "../../tables-and-indexes/missing-index-candidates/README.md",
        "../../performance/slow-queries/README.md",
    ],
    aurora_notes=[
        "Each inner-side lookup that misses shared buffers becomes a read from Aurora's distributed storage, so the cost of a runaway loop is amplified relative to a server with local disks: millions of small random reads is the worst possible access pattern for network-attached storage.",
        "Aurora readers can be used to reproduce and confirm the plan for a read-only statement without adding load to the writer, but their buffer cache contents differ, so absolute buffer numbers will not match the writer's.",
        "effective_cache_size on Aurora should reflect the instance's real memory rather than the community default; when it is too low the planner underestimates how much of the inner side is cached and its nested-loop costing is distorted.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_high_block_access_per_row",
        "Finds statements that touch a disproportionate number of blocks for the number of rows they return.",
        _pgss_guarded("""
-- The fingerprint of a runaway nested loop: enormous block access relative
-- to rows returned, because the inner side is being re-executed once per
-- outer row. This does not prove a nested loop by itself (a missing index
-- on a single-table filter produces a similar ratio), but it reliably
-- ranks the statements worth capturing a plan for.
\\set top_n 20
\\set min_calls 5
SELECT
    queryid,
    calls,
    rows                                                          AS total_rows_returned,
    round(rows::numeric / NULLIF(calls, 0), 1)                     AS avg_rows_per_call,
    shared_blks_hit,
    shared_blks_read,
    round(
        (shared_blks_hit + shared_blks_read)::numeric / NULLIF(calls, 0), 1
    )                                                              AS avg_blocks_per_call,
    round(
        (shared_blks_hit + shared_blks_read)::numeric / NULLIF(rows, 0), 1
    )                                                              AS blocks_per_row_returned,
    round(mean_exec_time::numeric, 2)                              AS mean_exec_time_ms,
    round(max_exec_time::numeric, 2)                               AS max_exec_time_ms,
    round(stddev_exec_time::numeric, 2)                            AS stddev_exec_time_ms,
    left(query, 200)                                               AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND calls >= :min_calls
  AND rows > 0
ORDER BY (shared_blks_hit + shared_blks_read)::numeric / NULLIF(rows, 0) DESC
LIMIT :top_n;
""".strip("\n")),
        "blocks_per_row_returned in the thousands means the statement is reading a substantial fraction of a table for every row it emits. Combined with a large stddev and max relative to mean, that is the classic parameter-sensitive nested loop: cheap for selective parameters, catastrophic for a wide date range or a high-volume trading pair. Aggregate statements (a count or sum returning one row) will naturally rank high here and are false positives -- read the query snippet before acting.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="02_sequential_scan_pressure.sql",
        table_purpose="Statements with extreme block-access-per-row ratios.",
    ),
    sql_script(
        "02", "02_sequential_scan_pressure",
        "Identifies tables being read sequentially in bulk, the signature of an unindexed inner side.",
        sb.sequential_scan_heavy_tables(),
        "An inner side without a usable index turns every loop iteration into a sequential scan, which shows up here as an enormous seq_tup_read on a large table. Compare seq_scan against idx_scan for each candidate: a large table with millions of sequential tuple reads and few index scans is almost certainly the inner side of the problem join. Small reference tables (markets, instruments, fee_tiers) legitimately live at the top of this list and are not findings.",
        related_scripts="03_foreign_keys_missing_index.sql, ../../tables-and-indexes/sequential-scan-investigation/README.md",
        table_purpose="Tables under heavy sequential scan pressure.",
    ),
    sql_script(
        "03", "03_foreign_keys_missing_index",
        "Finds foreign key constraints with no supporting index on the referencing side.",
        sb.foreign_keys_missing_index(),
        "In a normalized exchange schema the join keys are the foreign keys: order_fills to orders, ledger_entries to accounts, withdrawals to wallets. An unindexed foreign key is therefore both a lock-escalation hazard on parent updates and the most common structural reason the inner side of a nested loop has no index to use. Each row here is a concrete, well-understood index candidate rather than a speculative one.",
        related_scripts="04_statistics_freshness.sql, ../../tables-and-indexes/missing-index-candidates/README.md",
        table_purpose="Foreign keys lacking a supporting index.",
    ),
    sql_script(
        "04", "04_statistics_freshness",
        "Checks whether the planner's row estimates for the joined tables are based on current data.",
        sb.statistics_freshness(),
        "Underestimation on the outer side is what makes the planner choose a nested loop in the first place, and stale statistics are the most common source of underestimation. A table with a high pct_modified_since_analyze that participates in the problem join is the prime suspect: the planner may believe it holds the row count it had before the last backfill. A targeted ANALYZE is the cheapest possible fix and should be tried before any index work.",
        related_scripts="05_join_strategy_settings.sql, ../stale-statistics/README.md",
        table_purpose="Statistics freshness for the joined tables.",
    ),
    sql_script(
        "05", "05_join_strategy_settings",
        "Reviews the planner settings that govern join strategy selection and repeated-lookup caching.",
        _planner_settings(),
        "Confirm enable_nestloop, enable_hashjoin, and enable_mergejoin are all on -- any of them left off from a previous diagnostic session forces the planner into a corner. Check enable_memoize (on by default since PostgreSQL 14): it caches inner-side results for repeated keys and substantially reduces the damage of a loop with low key cardinality. Finally, effective_cache_size and random_page_cost directly determine how cheap the planner believes each repeated index lookup to be; defaults that describe a small local-disk server systematically distort that judgement on Aurora.",
        required_privileges=PG_MONITOR,
        related_scripts="06_confirm_nested_loop_safely.md",
        table_purpose="Join strategy and caching configuration.",
    ),
    md_script(
        "06", "06_confirm_nested_loop_safely",
        "Guarded runbook for confirming a runaway nested loop with a real plan, and for testing the alternative plan safely.",
        (
            "## Before you run anything\n\n"
            "The statement you are about to analyze is, by hypothesis, the one saturating the\n"
            "instance. `EXPLAIN ANALYZE` executes it in full, so running it carelessly repeats\n"
            "the incident on purpose. Every command below is deliberate.\n\n"
            "## Step 1 -- Confirm the plan shape for free\n\n"
            "```sql\n"
            "EXPLAIN (FORMAT TEXT)\n"
            "SELECT ... ;                     -- with representative parameter values\n"
            "```\n\n"
            "This executes nothing. Look for `Nested Loop` with a large table on the inner side,\n"
            "and read the estimated `rows=` on the outer side. If the outer estimate is small\n"
            "(single or double digits) while you know the real filter matches millions of rows,\n"
            "you have already found the problem and may not need to execute anything at all.\n\n"
            "## Step 2 -- Measure the real loop count, with a hard time bound\n\n"
            "```sql\n"
            "SET LOCAL statement_timeout = '15s';\n"
            "EXPLAIN (ANALYZE, BUFFERS, TIMING, FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "- Run this on a **reader instance** if the statement is read-only. The data is the\n"
            "  same and the writer's order-matching path is untouched.\n"
            "- The `statement_timeout` is not optional. A runaway loop that ran for 40 minutes\n"
            "  in production will run for 40 minutes here too, and the timeout is what stops\n"
            "  the diagnosis from becoming the next incident.\n"
            "- If the statement times out, that is itself a result: the loop is confirmed\n"
            "  expensive. Re-run with more selective parameters to get a completable plan.\n\n"
            "In the output, on the inner node of the `Nested Loop`, read:\n\n"
            "```\n"
            "->  Index Scan using ... (cost=... rows=1 width=...)\n"
            "      (actual time=0.004..0.006 rows=1 loops=2841193)\n"
            "```\n\n"
            "`rows` is **per loop**. The real work is `rows x loops`. A `loops` value in the\n"
            "millions confirms the runaway loop immediately.\n\n"
            "## Step 3 -- Prove the alternative plan is better (diagnostic only)\n\n"
            "```sql\n"
            "BEGIN;\n"
            "SET LOCAL enable_nestloop = off;      -- SESSION-SCOPED, diagnostic only\n"
            "SET LOCAL statement_timeout = '15s';\n"
            "EXPLAIN (ANALYZE, BUFFERS)\n"
            "SELECT ... ;\n"
            "ROLLBACK;\n"
            "```\n\n"
            "- `SET LOCAL` confines the change to this transaction, and the `ROLLBACK` ends it.\n"
            "  Nothing leaks into other sessions.\n"
            "- If the hash-join plan is dramatically faster, you have evidence -- **not a fix**.\n"
            "  Disabling a join method is never the production remediation: it distorts every\n"
            "  other query on the connection and will eventually produce a worse plan\n"
            "  elsewhere.\n"
            "- The real fix is to make the planner choose that plan on its own, by correcting\n"
            "  the estimate (ANALYZE, higher statistics target, extended statistics) or by\n"
            "  adding the index that makes the loop genuinely cheap.\n\n"
            "## Step 4 -- Decide the remediation\n\n"
            "| Finding in the plan | Correct remediation |\n"
            "|---|---|\n"
            "| Outer estimate far below actual, statistics stale | Targeted `ANALYZE` on that table |\n"
            "| Outer estimate far below actual, statistics fresh, correlated predicates | Extended statistics (`CREATE STATISTICS`) on the correlated columns |\n"
            "| Inner side doing a sequential scan per loop | Index on the inner join key, built `CONCURRENTLY` |\n"
            "| Inner index exists but is unused | Check for a type mismatch or a function wrapped around the join column |\n"
            "| Estimates correct, loop count genuinely huge | Query shape must change -- application-side fix or a materialized intermediate result |\n\n"
            "## Never do this\n\n"
            "- Do not set `enable_nestloop = off` in the Aurora parameter group. It is a\n"
            "  diagnostic switch, not a configuration setting, and a cluster-wide change would\n"
            "  degrade the high-frequency OLTP lookups that legitimately depend on nested loops.\n"
            "- Do not run step 2 or 3 against a data-modifying statement without wrapping it in\n"
            "  `BEGIN ... ROLLBACK`, and do not do it at all against `wallets`, `ledger_entries`,\n"
            "  or settlement tables during trading hours.\n"
        ),
        "Use step 1 alone whenever it is sufficient -- an obviously wrong outer estimate is diagnostic on its own and costs nothing to obtain. Escalate to step 2 only when you need the real loop count, and treat step 3 strictly as evidence-gathering: the deliverable from this runbook is a statistics or index change, never a disabled join method.",
        safety=GUARDED_DDL,
        expected_impact="Step 1: none. Step 2: a full execution of the statement under investigation, bounded by statement_timeout. Step 3: the same, plus a session-scoped planner change confined to one transaction.",
        required_privileges="The same privileges the statement under investigation requires.",
        prerequisites="Scripts 01-05 completed and a candidate statement with representative parameters identified.",
        execution_location="Reader instance preferred for read-only statements; writer only when unavoidable.",
        expected_runtime="Step 1: milliseconds. Steps 2 and 3: up to the configured statement_timeout.",
        related_scripts="../cardinality-estimation/README.md, ../hash-join-analysis/README.md",
        table_purpose="Guarded runbook for confirming and remediating a runaway nested loop.",
    ),
]

# ---------------------------------------------------------------------------
# hash-join-analysis
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="hash-join-analysis",
    title="Hash Join Analysis",
    summary=(
        "A hash join builds an in-memory hash table from one input and probes it with the other. "
        "It is the right strategy for joining large row sets and is what an exchange's "
        "reconciliation, settlement, and reporting queries should normally use -- provided the "
        "hash table fits in memory. When it does not, PostgreSQL partitions the join into "
        "batches spilled to temporary files, and the same query silently becomes several times "
        "slower. This workflow finds hash joins that are spilling, determines whether the cause "
        "is memory sizing or a bad row estimate, and guards the memory experiment."
    ),
    symptoms=[
        "Temporary file volume rising on the instance without any obvious change in the workload.",
        "A reporting, reconciliation, or settlement query whose runtime has grown disproportionately as trade and ledger volumes grew.",
        "An EXPLAIN ANALYZE plan showing a Hash node with Batches greater than 1, or with a Memory Usage figure close to the work_mem limit.",
        "Query latency that improves markedly in a session where work_mem was raised, confirming a memory-bound rather than plan-bound problem.",
    ],
    business_impact=[
        "A spilling hash join writes and re-reads its entire build input through temporary files on local instance storage, turning a memory-speed operation into an I/O-bound one and multiplying runtime several times over.",
        "Month-end reconciliation and regulatory reporting queries are the usual victims on an exchange, and they run against deadlines where a multiplied runtime becomes a compliance risk rather than a performance annoyance.",
        "Temporary files consume finite local instance storage; several large concurrent spills can exhaust it and cause unrelated queries to fail outright.",
    ],
    root_causes=[
        "work_mem too small for the size of the build input -- the most common and most directly fixable cause.",
        "A row underestimate on the build side, so the planner sized the hash table for a fraction of the rows that actually arrive.",
        "The planner choosing the larger relation as the build input because its estimate said it was smaller.",
        "Parallel query multiplying memory demand: each worker gets its own work_mem allocation for its own hash table.",
        "hash_mem_multiplier left at its default when the workload is dominated by a few large hash joins that could safely be given more memory than sorts get.",
        "A genuinely enormous join that no reasonable work_mem can hold, where the correct answer is to reduce the input (better predicates, pre-aggregation, partition pruning) rather than to add memory.",
    ],
    investigation_strategy=[
        "Identify statements writing the most temporary blocks -- hash spills and sort spills both surface here, and the plan later tells you which.",
        "Quantify the cluster-wide temporary file trend to judge whether this is a growing systemic issue or one bad query.",
        "Review work_mem, hash_mem_multiplier, and the parallel worker settings that jointly determine how much memory a hash join can actually use.",
        "Check statistics freshness on the joined tables, since an underestimated build side is a statistics problem wearing a memory problem's clothing.",
        "Capture the plan under the guarded runbook to read the actual Batches and Memory Usage figures, and to test a higher work_mem safely in a single session.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "pg_stat_statements for the statement-level temp file attribution.",
        "log_temp_files enabled (a value of 0 logs every temp file) is extremely helpful for attributing spills to statements over time; on Aurora the log is exported to CloudWatch Logs.",
    ],
    interpretation_guide=[
        "Batches greater than 1 on a Hash node in an EXPLAIN ANALYZE plan is the definitive confirmation of a spill. Batches reported as 'N (originally M)' means the planner expected M and had to grow to N at run time, which is simultaneously a spill and proof of an underestimate.",
        "work_mem is a per-node, per-worker limit rather than a per-query or per-connection one: one query with two hash joins running across four parallel workers can use many multiples of it at once. That is why raising it globally on a high-connection exchange writer is risky.",
        "hash_mem_multiplier scales the memory available to hash operations specifically. Raising it preferentially helps hash joins and hash aggregates without giving every sort the same increase, which is usually what a reporting-heavy workload actually wants.",
        "If the build side estimate is accurate and the input is genuinely huge, more memory is the wrong answer: reduce the input instead through better predicates, partition pruning, or pre-aggregation.",
        "temp_blks_written in pg_stat_statements is cumulative per statement and does not distinguish a hash spill from a sort spill or a large materialize -- it identifies candidates, and only the plan identifies the node.",
    ],
    remediation_immediate=[
        "For a one-off report that must complete now, raise work_mem for that session alone with SET before running it, rather than changing cluster configuration under time pressure.",
        "If the instance is close to exhausting local storage because of concurrent spills, stop or defer the non-critical spilling workloads first.",
    ],
    remediation_short_term=[
        "Run a targeted ANALYZE on the build-side table if its statistics are stale, which often removes the spill entirely by letting the planner size the hash table correctly or pick the smaller input to build from.",
        "Raise work_mem or hash_mem_multiplier for the specific role that runs the reporting workload, rather than for every connection on the cluster.",
        "Add the predicate or index that reduces the build side to the rows the report actually needs.",
    ],
    remediation_long_term=[
        "Separate the analytical workload onto dedicated Aurora readers with their own parameter group, so reporting-sized work_mem does not have to be granted to the order-path writer.",
        "Pre-aggregate the recurring reconciliation and settlement joins into summary tables refreshed on a schedule, so the large hash join happens once rather than on every report execution.",
        "Partition the large fact tables (trades, ledger_entries) by time so reports naturally touch a bounded subset.",
    ],
    production_safety=[
        "All .sql scripts here are read-only and safe during trading hours.",
        "Testing a larger work_mem is a guarded runbook step, not a script: work_mem multiplies across nodes, workers, and connections, so an unconsidered increase is one of the fastest ways to drive an instance into memory exhaustion. " + EXPLAIN_ANALYZE_WARNING,
        "Never raise work_mem cluster-wide as a first response. Session-scoped and role-scoped changes deliver the same benefit to the affected workload with a fraction of the risk.",
    ],
    escalation_criteria=[
        "Local instance storage is close to exhaustion because of concurrent temporary file usage -- escalate immediately, as this fails queries outright rather than merely slowing them.",
        "A reporting query with a compliance or settlement deadline cannot be made to complete within its window even with a reasonable memory allocation.",
        "The join is genuinely too large for any sane work_mem, meaning the data model or the report definition has to change -- escalate to engineering rather than continuing to tune.",
    ],
    related_issues=[
        "../sort-spills/README.md",
        "../temp-file-investigation/README.md",
        "../analyze-query-plan/README.md",
        "../merge-join-analysis/README.md",
        "../cardinality-estimation/README.md",
        "../../performance/high-iops/README.md",
    ],
    aurora_notes=[
        "Temporary files are written to the instance's local storage, not to the shared Aurora cluster volume. Their capacity is therefore a property of the instance class, and exhausting it produces query failures rather than cluster-level storage growth.",
        "work_mem is set through the Aurora DB cluster or DB instance parameter group; ALTER SYSTEM is not available. A per-role default (ALTER ROLE ... SET work_mem) is the usual way to give a reporting role more memory than the order-path role, and it requires no reboot.",
        "Running the analytical workload on a dedicated reader with its own DB instance parameter group is the cleanest Aurora-native separation: the reader can carry a large work_mem without exposing the writer to the same risk.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_statements_writing_temp_files",
        "Ranks statements by temporary block volume, the statement-level signature of a spilling hash join.",
        _pgss_guarded(sb.pgss_temp_and_io_heavy()),
        "Every statement listed here is spilling something to disk. This view cannot tell you whether the spill is a hash join, a sort, or a materialize -- that requires the plan -- but it gives you the ranked candidate list and the queryid to investigate. Divide temp_blks_written by calls: a statement that spills a little on every one of a million calls is a very different problem from a monthly report that spills enormously once.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="02_cluster_temp_file_trend.sql",
        table_purpose="Statements writing the most temporary blocks.",
    ),
    sql_script(
        "02", "02_cluster_temp_file_trend",
        "Measures cluster-wide temporary file volume to judge whether spilling is systemic or isolated.",
        sb.temp_file_usage_by_database(),
        "Divide temp_bytes by the counting window to get a rate, and compare it across health checks. A steadily rising rate with an unchanged workload means data volumes have crossed the threshold where previously in-memory operations now spill -- a capacity signal about memory sizing, not a query defect. A sudden step change points at a specific deployment or a new report.",
        related_scripts="03_memory_and_spill_settings.sql, ../temp-file-investigation/README.md",
        table_purpose="Cluster-wide temp file volume per database.",
    ),
    sql_script(
        "03", "03_memory_and_spill_settings",
        "Reviews the memory settings that determine whether a hash join stays in memory or spills.",
        _memory_and_spill_settings(),
        "Effective hash memory is roughly work_mem multiplied by hash_mem_multiplier, per node and per parallel worker. Multiply that by max_parallel_workers_per_gather and by the number of hash nodes in the plan to see the true worst-case footprint of a single statement, then by the number of concurrent connections running it to see the instance-level exposure. If log_temp_files is -1, temporary file creation is not being logged at all and spills can only be seen after the fact through these counters.",
        required_privileges=PG_MONITOR,
        related_scripts="04_statistics_freshness_on_join_inputs.sql",
        table_purpose="Memory and spill-related configuration.",
    ),
    sql_script(
        "04", "04_statistics_freshness_on_join_inputs",
        "Checks whether the planner's size estimates for the joined tables are current.",
        sb.statistics_freshness(),
        "A spill caused by an underestimated build side is a statistics problem, and adding memory only masks it. If the tables in the problem join show a high pct_modified_since_analyze, run a targeted ANALYZE and re-capture the plan before touching work_mem at all -- a correct estimate frequently causes the planner to build the hash from the smaller input instead, which removes the spill without any memory change.",
        related_scripts="05_test_memory_hypothesis_safely.md, ../stale-statistics/README.md",
        table_purpose="Statistics freshness on the join inputs.",
    ),
    md_script(
        "05", "05_test_memory_hypothesis_safely",
        "Guarded runbook for confirming a hash spill in the plan and testing a larger work_mem without endangering the instance.",
        (
            "## What this runbook decides\n\n"
            "Whether the statement is spilling because memory is too small, or because the\n"
            "planner's estimate was wrong. Those look identical from the outside and have\n"
            "completely different fixes.\n\n"
            "## Step 1 -- Look at the plan without executing anything\n\n"
            "```sql\n"
            "EXPLAIN (FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "This shows the join strategy and the estimated row counts on each side. It does not\n"
            "show batches or memory usage -- those only exist at run time -- but it tells you\n"
            "which input the planner intends to build the hash from and how large it thinks that\n"
            "input is. If that estimate is obviously wrong, go fix statistics first and come\n"
            "back; you may never need step 2.\n\n"
            "## Step 2 -- Measure the actual spill\n\n"
            "```sql\n"
            "SET LOCAL statement_timeout = '30s';\n"
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "This executes the statement. Prefer a reader instance. In the output, find the\n"
            "`Hash` node:\n\n"
            "```\n"
            "->  Hash  (cost=... rows=1200000 width=48)\n"
            "      Buckets: 65536  Batches: 16  Memory Usage: 4096kB\n"
            "```\n\n"
            "- `Batches: 1` means no spill.\n"
            "- `Batches: 16` means the build input was partitioned into 16 pieces and 15 of them\n"
            "  were written to temporary files and read back.\n"
            "- `Batches: 16 (originally 4)` means the planner expected 4 and discovered at run\n"
            "  time that it needed 16 -- a spill **and** proof of an underestimate.\n"
            "- Compare the `Hash` node's estimated `rows=` against `actual rows` on its input.\n"
            "  A large gap means the fix is statistics, not memory.\n\n"
            "## Step 3 -- Test more memory, for one statement only\n\n"
            "```sql\n"
            "BEGIN;\n"
            "SET LOCAL work_mem = '256MB';         -- this transaction only\n"
            "SET LOCAL statement_timeout = '30s';\n"
            "EXPLAIN (ANALYZE, BUFFERS)\n"
            "SELECT ... ;\n"
            "ROLLBACK;\n"
            "```\n\n"
            "- `SET LOCAL` inside an explicit transaction is the safest possible scope: the\n"
            "  setting dies with the transaction and cannot leak to the connection pool.\n"
            "- Increase in steps (64MB, 128MB, 256MB) and stop at the smallest value that gets\n"
            "  `Batches: 1`. The goal is the minimum sufficient allocation, not the largest one\n"
            "  that fits.\n"
            "- **Before you run this, do the arithmetic.** Worst-case memory for one statement\n"
            "  is roughly:\n\n"
            "  ```\n"
            "  work_mem x hash_mem_multiplier x (hash/sort nodes in the plan)\n"
            "            x (1 + max_parallel_workers_per_gather)\n"
            "  ```\n\n"
            "  Multiply again by how many sessions would run it concurrently in production. On\n"
            "  a writer serving hundreds of exchange connections, a 256MB work_mem applied\n"
            "  broadly is an out-of-memory incident waiting to happen.\n\n"
            "## Step 4 -- Apply the right fix at the right scope\n\n"
            "| Evidence | Fix | Scope |\n"
            "|---|---|---|\n"
            "| Estimate wrong, statistics stale | Targeted `ANALYZE` | The affected table |\n"
            "| Estimate wrong, statistics fresh, correlated columns | `CREATE STATISTICS` on the correlated columns | The affected table |\n"
            "| Estimate right, input genuinely large, report is analytical | `ALTER ROLE reporting_role SET work_mem = '256MB';` | One role |\n"
            "| Estimate right, spill on a hot OLTP path | Reduce the input (predicate, index, partition pruning) | The query |\n"
            "| Spilling reports competing with trading traffic | Move the workload to a dedicated reader with its own parameter group | The cluster topology |\n\n"
            "## Never do this\n\n"
            "- Do not raise `work_mem` in the Aurora cluster parameter group as a first response.\n"
            "  Every connection inherits it, and the exposure is multiplied by nodes, workers,\n"
            "  and concurrency.\n"
            "- Do not run step 2 or 3 against a data-modifying statement outside\n"
            "  `BEGIN ... ROLLBACK`.\n"
            "- Do not tune memory before checking statistics. Fixing an estimate is free and\n"
            "  permanent; adding memory is neither.\n"
        ),
        "The deliverable is a decision between 'fix the estimate' and 'grant more memory at the narrowest workable scope'. Read the Batches figure and the estimated-versus-actual gap on the Hash node together: they tell you which of those two it is, and step 4 maps that answer onto the correct remediation and the correct scope.",
        safety=GUARDED_DDL,
        expected_impact="Step 1: none. Steps 2 and 3: a full execution of the statement, plus the temporary file and memory footprint it implies. A mis-sized work_mem test on a busy writer can itself cause memory pressure.",
        required_privileges="The same privileges the statement under investigation requires. Changing a role's default work_mem additionally requires ALTER ROLE privileges and change-management approval.",
        prerequisites="Scripts 01-04 completed; a candidate statement with representative parameters identified; the memory arithmetic in step 3 done before running it.",
        execution_location="Reader instance preferred; writer only when the statement must run there.",
        expected_runtime="Step 1: milliseconds. Steps 2 and 3: up to the configured statement_timeout.",
        related_scripts="../sort-spills/README.md, ../temp-file-investigation/README.md",
        table_purpose="Guarded runbook for confirming a hash spill and sizing work_mem.",
    ),
]

# ---------------------------------------------------------------------------
# merge-join-analysis
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="merge-join-analysis",
    title="Merge Join Analysis",
    summary=(
        "A merge join walks two inputs in sorted order simultaneously. When both inputs already "
        "arrive sorted -- typically from an index scan on the join key -- it is extremely "
        "efficient and memory-light, which makes it the ideal strategy for large "
        "time-ordered joins such as trades to fills or ledger entries to settlement batches. "
        "When the inputs are not already sorted, PostgreSQL must sort them first, and those "
        "sorts can spill to disk and dominate the query's cost. This workflow determines which "
        "situation you are in and what to do about it."
    ),
    symptoms=[
        "A large join whose cost is dominated by explicit Sort nodes rather than by the join itself.",
        "Temporary file usage attributable to sorts feeding a join rather than to a user-visible ORDER BY.",
        "A time-range join over trades or ledger entries that performs far worse than its row counts suggest it should.",
        "A plan that alternates between merge join and hash join across executions or environments, with markedly different performance.",
    ],
    business_impact=[
        "Reconciliation and settlement jobs joining large time-ordered datasets are exactly the workload where a merge join should excel; when it degenerates into sort-then-merge with spills, those jobs miss their processing windows.",
        "Sorts feeding a merge join consume work_mem per node and spill to local instance storage, so several concurrent such jobs can exhaust temporary space and cause unrelated failures.",
        "The fix is often a single well-chosen index that makes both sides arrive pre-sorted, converting a multi-minute batch job into a streaming one -- high leverage, low risk.",
    ],
    root_causes=[
        "No index providing sorted input on the join key, so both sides must be explicitly sorted first.",
        "An index exists but its sort order (ASC/DESC, NULLS FIRST/LAST) or its leading column order does not match what the join requires, so it cannot supply the ordering.",
        "work_mem too small for the sorts feeding the join, causing external merge sorts on disk.",
        "A row underestimate that made the planner believe the sorts would be small and cheap.",
        "Low physical correlation between the index order and the heap order, making an index scan expensive enough that the planner prefers a sequential scan plus sort.",
        "A join key with a collation or type difference between the two sides, preventing merge join from using existing index ordering.",
    ],
    investigation_strategy=[
        "Identify statements writing temporary blocks, since sorts feeding a merge join are a common source.",
        "Inspect the indexes on the join tables and check whether any of them can supply the required ordering on the join key.",
        "Inspect the column statistics, especially correlation, which determines how attractive an ordered index scan looks to the planner.",
        "Review the settings governing merge join, sorting, and incremental sort.",
        "Capture the plan under the guarded runbook to see whether Sort nodes dominate and whether they spill.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "pg_stat_statements for statement-level temporary block attribution.",
        "The identity of the join under investigation and the tables and columns it joins on.",
    ],
    interpretation_guide=[
        "A merge join fed by two Index Scans with no Sort nodes is the good case and generally needs no intervention, even on very large inputs, because it streams rather than materializing.",
        "A merge join fed by Sort nodes is only worthwhile if the sorts are cheap. Read Sort Method in the plan: 'quicksort  Memory: NkB' is in-memory and fine, while 'external merge  Disk: NkB' means the sort spilled and the join is now I/O-bound.",
        "PostgreSQL 13 and later can use an Incremental Sort when an index provides a prefix of the required ordering, sorting only within groups. Seeing Incremental Sort in the plan means a partially useful index exists and extending it to cover the full ordering may remove the sort entirely.",
        "The correlation statistic per column indicates how closely physical row order matches logical order: values near 1 or -1 make an ordered index scan cheap, values near 0 make it look expensive and push the planner toward sequential scan plus sort.",
        "Index sort direction matters: an index defined ASC NULLS LAST cannot supply DESC NULLS FIRST ordering directly. Read pg_get_indexdef output carefully rather than assuming any index on the column will do.",
    ],
    remediation_immediate=[
        "For a batch job that must complete now, raise work_mem for that session alone so the feeding sorts stay in memory.",
    ],
    remediation_short_term=[
        "Create the index that supplies sorted input on the join key, with matching column order and sort direction, built CONCURRENTLY.",
        "Run a targeted ANALYZE if statistics are stale, so the planner's estimate of the sort size and of the index scan cost is correct.",
        "Raise work_mem for the reporting or batch role specifically, rather than globally.",
    ],
    remediation_long_term=[
        "Align the physical clustering of the large time-ordered tables with their natural join and scan order (for example by partitioning by time), so correlation stays high and ordered index scans stay cheap as the tables grow.",
        "Standardize join key types and collations across the schema so index ordering is always usable for merge joins.",
        "Move large analytical joins onto dedicated readers where a generous work_mem is safe.",
    ],
    production_safety=[
        "All .sql scripts here are read-only and safe at any time.",
        "Plan capture that executes the statement is a guarded runbook step. " + EXPLAIN_ANALYZE_WARNING,
        "Creating an index to supply sorted input is a schema change: build it CONCURRENTLY and follow the schema-changes safety guidance, because a non-concurrent build takes a lock that blocks writes to the table for its entire duration.",
    ],
    escalation_criteria=[
        "The required index would be large enough to materially affect write latency on a hot exchange table -- escalate for a cost/benefit decision rather than adding it unilaterally.",
        "The join cannot avoid sorting and the sorts cannot fit in a reasonable work_mem, meaning the data model or the job design must change.",
        "A settlement or reconciliation job is missing its processing window as a direct result -- escalate with the operational deadline made explicit.",
    ],
    related_issues=[
        "../sort-spills/README.md",
        "../hash-join-analysis/README.md",
        "../analyze-query-plan/README.md",
        "../inefficient-index-usage/README.md",
        "../../tables-and-indexes/missing-index-candidates/README.md",
    ],
    aurora_notes=[
        "Ordered index scans issue many small random reads, which on Aurora's network-attached storage are more expensive relative to sequential reads than on local NVMe. effective_io_concurrency and random_page_cost therefore materially influence whether the planner chooses the ordered index scan that makes merge join worthwhile.",
        "The sorts feeding a merge join spill to local instance storage, whose capacity is a property of the instance class rather than of the shared cluster volume.",
        "A dedicated Aurora reader with its own parameter group is the natural home for large merge-join batch jobs: it can carry a work_mem sized for sorting without exposing the writer's order path to the same risk.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_sort_and_temp_heavy_statements",
        "Identifies statements writing temporary blocks, including sorts that feed a merge join.",
        _pgss_guarded(sb.pgss_temp_and_io_heavy()),
        "Sorts that feed a join are invisible at the application level -- there is no ORDER BY in the statement text -- so a statement appearing here without a user-visible sort is a strong hint that the planner is sorting to enable a join. Note the queryid and carry it into the plan capture in script 05.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="02_join_key_index_coverage.sql",
        table_purpose="Statements with heavy temporary block usage.",
    ),
    sql_script(
        "02", "02_join_key_index_coverage",
        "Lists the indexes on the join table and their exact definitions, to determine whether any can supply sorted input.",
        _index_inventory_for_table(),
        "Read each index_definition literally, not approximately. A merge join can use an index for ordering only when the index's leading columns match the join key in the same order and with a compatible sort direction. An index on (account_id, created_at) supplies ordering for a join on account_id and for one on (account_id, created_at), but not for a join on created_at alone. Note also which indexes have a non-zero idx_scan: an index that exists and is never used often indicates a type or collation mismatch preventing its use.",
        related_scripts="03_join_column_correlation.sql",
        table_purpose="Index inventory and definitions for the join table.",
    ),
    sql_script(
        "03", "03_join_column_correlation",
        "Shows per-column statistics, especially physical correlation, for the join columns.",
        _column_statistics_for_table(),
        "correlation near 1 or -1 means the table's physical row order closely follows that column's logical order, so an ordered index scan is sequential-like and cheap -- exactly the condition that makes merge join attractive. correlation near 0 means an ordered scan would jump randomly across the heap, and the planner will usually prefer a sequential scan plus an explicit sort. On an exchange, an append-only trades table is naturally near-perfectly correlated on its timestamp and primary key, while a heavily updated orders table often is not.",
        related_scripts="04_sort_and_join_settings.sql, ../cardinality-estimation/README.md",
        table_purpose="Column statistics and physical correlation for the join columns.",
    ),
    sql_script(
        "04", "04_sort_and_join_settings",
        "Reviews the settings that govern merge join selection, sorting, and incremental sort.",
        _planner_settings(),
        "Confirm enable_mergejoin and enable_sort are on, and note whether enable_incremental_sort is on (it is by default from PostgreSQL 13): incremental sort is what lets a partially matching index still avoid a full sort. work_mem determines whether the feeding sorts stay in memory. random_page_cost and effective_io_concurrency determine how expensive the planner believes the ordered index scan to be, and defaults tuned for local spinning disks systematically discourage the ordered scan that would make merge join the better plan on Aurora.",
        required_privileges=PG_MONITOR,
        related_scripts="05_inspect_merge_join_plan.md",
        table_purpose="Merge join, sort, and I/O cost configuration.",
    ),
    md_script(
        "05", "05_inspect_merge_join_plan",
        "Guarded runbook for reading a merge join plan and deciding between adding an index and adding memory.",
        (
            "## The question this runbook answers\n\n"
            "Is this merge join streaming two already-sorted inputs (good, leave it alone), or\n"
            "is it sorting them first (fixable, usually with one index)?\n\n"
            "## Step 1 -- Plan only, no execution\n\n"
            "```sql\n"
            "EXPLAIN (FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "Nothing is executed. Look at what feeds the `Merge Join`:\n\n"
            "```\n"
            "Merge Join\n"
            "  Merge Cond: (t.order_id = f.order_id)\n"
            "  ->  Index Scan using trades_order_id_idx on trades t        <- good: pre-sorted\n"
            "  ->  Sort                                                    <- costly: must sort\n"
            "        Sort Key: f.order_id\n"
            "        ->  Seq Scan on order_fills f\n"
            "```\n\n"
            "Two `Index Scan` inputs and no `Sort` nodes is the efficient case and needs no\n"
            "further work. Any `Sort` node feeding the join is the target of this\n"
            "investigation.\n\n"
            "## Step 2 -- Measure the sorts (executes the statement)\n\n"
            "```sql\n"
            "SET LOCAL statement_timeout = '30s';\n"
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "Read `Sort Method` on each Sort node:\n\n"
            "- `quicksort  Memory: 8192kB` -- fully in memory. If the sort is small, the merge\n"
            "  join may still be the best available plan and there is nothing to fix.\n"
            "- `external merge  Disk: 412MB` -- spilled to a temporary file on local instance\n"
            "  storage. This sort now dominates the query cost.\n"
            "- `Incremental Sort` with `Pre-sorted Groups:` -- an index already supplies part of\n"
            "  the ordering. Extending that index to cover the full sort key usually removes\n"
            "  the sort entirely, and is the cheapest fix available.\n\n"
            "Prefer a reader instance for this capture when the statement is read-only.\n\n"
            "## Step 3 -- Choose between an index and memory\n\n"
            "| Observation | Fix |\n"
            "|---|---|\n"
            "| Sort feeding one side, and a matching index could exist | Create the index on the join key, `CONCURRENTLY`; this removes the sort permanently |\n"
            "| `Incremental Sort` present | Extend the existing index to cover the remaining sort columns |\n"
            "| Sort is small and in memory | Leave it; the merge join is fine |\n"
            "| Sort is unavoidable and spilling | Raise `work_mem` for the batch role only, and reduce the input with better predicates |\n"
            "| Index exists but is not used for ordering | Check sort direction, `NULLS FIRST/LAST`, leading column order, and join key type/collation mismatches |\n\n"
            "An index is almost always the better answer than memory here: it fixes the problem\n"
            "for every future execution, on every instance, at every data volume, whereas more\n"
            "memory only postpones the spill until the table grows again.\n\n"
            "## Step 4 -- Diagnostic comparison, if you need it\n\n"
            "```sql\n"
            "BEGIN;\n"
            "SET LOCAL enable_mergejoin = off;    -- diagnostic only, this transaction only\n"
            "SET LOCAL statement_timeout = '30s';\n"
            "EXPLAIN (ANALYZE, BUFFERS)\n"
            "SELECT ... ;\n"
            "ROLLBACK;\n"
            "```\n\n"
            "This shows what the planner would do instead (usually a hash join) and whether it\n"
            "is actually faster. It is evidence for the ticket, never a production setting.\n\n"
            "## Never do this\n\n"
            "- Do not disable `enable_mergejoin` or `enable_sort` outside a single diagnostic\n"
            "  transaction, and never in the Aurora parameter group.\n"
            "- Do not build the new index without `CONCURRENTLY` on a hot exchange table: a\n"
            "  plain `CREATE INDEX` holds a lock that blocks every write to that table for the\n"
            "  whole build.\n"
            "- Do not run step 2 or 4 against a data-modifying statement outside\n"
            "  `BEGIN ... ROLLBACK`.\n"
        ),
        "Start with step 1: the presence or absence of Sort nodes above the join inputs answers most of the question at zero cost. Execute the statement only when you need the Sort Method line to distinguish an in-memory sort from a spilling one, and prefer the index fix over the memory fix whenever an index can supply the ordering.",
        safety=GUARDED_DDL,
        expected_impact="Step 1: none. Steps 2 and 4: a full execution of the statement, including any temporary file usage its sorts require.",
        required_privileges="The same privileges the statement under investigation requires; creating the remediation index additionally requires table ownership.",
        prerequisites="Scripts 01-04 completed and the join's tables, columns, and representative parameters identified.",
        execution_location="Reader instance preferred for read-only statements.",
        expected_runtime="Step 1: milliseconds. Steps 2 and 4: up to the configured statement_timeout.",
        related_scripts="../sort-spills/README.md, ../../schema-changes/concurrent-index-build/README.md",
        table_purpose="Guarded runbook for reading and remediating a merge join plan.",
    ),
]

# ---------------------------------------------------------------------------
# cardinality-estimation
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="cardinality-estimation",
    title="Cardinality Estimation Errors",
    summary=(
        "Almost every bad plan in PostgreSQL is a bad estimate wearing a costume. The planner "
        "chooses join strategies, join order, and access paths from its prediction of how many "
        "rows each node will produce; when that prediction is wrong by an order of magnitude, "
        "the resulting plan is wrong no matter how well the engine executes it. This workflow "
        "examines what the planner actually believes about an exchange's data -- distinct "
        "values, skew, null fractions, correlation, and the multi-column dependencies it cannot "
        "see by default -- and shows how to correct it."
    ),
    symptoms=[
        "An EXPLAIN ANALYZE plan where estimated rows and actual rows differ by one or more orders of magnitude at a specific node.",
        "A plan that flips between a nested loop and a hash join depending on the parameter values supplied.",
        "Query performance that is excellent for one market symbol or account and terrible for another, with identical query text.",
        "A query on a status or state column (order status, withdrawal state) whose plan assumes an even distribution that does not exist.",
    ],
    business_impact=[
        "An exchange's data is intensely skewed by nature: a handful of trading pairs carry most volume, most orders end in a small number of terminal states, and a few institutional accounts dwarf the rest. A planner that assumes uniformity is systematically wrong about exactly the queries that matter most.",
        "Estimation errors produce non-linear failures: the plan is fine until the data crosses a threshold, then collapses, which is why these incidents appear without any deployment to blame.",
        "Correcting an estimate is usually free and permanent (one ANALYZE, one statistics target change, one extended statistics object), making this among the highest-return investigations available.",
    ],
    root_causes=[
        "Stale statistics: the last ANALYZE predates a bulk load, backfill, or a change in data distribution.",
        "Insufficient statistics resolution: default_statistics_target of 100 cannot describe a column with heavy skew and many distinct values, such as market symbol or account identifier.",
        "Correlated columns treated as independent: the planner multiplies the selectivity of market_symbol and order_status as if they were unrelated, when in reality certain statuses only occur for certain markets.",
        "Expressions and function calls in predicates, for which no statistics exist unless an expression index or extended statistics object provides them.",
        "A poor n_distinct estimate, which is sampled rather than exact and is frequently wrong for high-cardinality columns in very large tables.",
        "Join-key estimates across several joins compounding: a small error at the bottom of a deep join tree becomes an enormous one at the top.",
        "Partitioned tables where per-partition statistics exist but the query predicates prevent effective pruning, so estimates are drawn from the wrong scope.",
    ],
    investigation_strategy=[
        "Start with statistics freshness -- a stale ANALYZE explains most estimation errors and is the cheapest thing to rule out.",
        "Inspect what the planner actually stores for the suspect table's columns: distinct values, most common value frequencies, null fraction, and correlation.",
        "Check the per-column statistics targets against the column's real distribution, since a skewed column may need far more than the default resolution.",
        "Check whether extended statistics exist for the correlated column groups the queries filter on together.",
        "Confirm the error empirically by comparing estimated and actual rows in a plan, under the guarded runbook.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats), which grants the access needed to read pg_stats.",
        "The identity of the table and columns involved in the suspect predicate, set in the psql variables at the top of scripts 02 and 03.",
        "An understanding of the business meaning of the columns: knowing that order status and market symbol are correlated on an exchange is what turns a statistics reading into a diagnosis.",
    ],
    interpretation_guide=[
        "n_distinct is a sampled estimate, not a count. A positive value is an absolute number of distinct values; a negative value between -1 and 0 is a ratio of distinct values to total rows (-1 means every row is unique). A value that badly misdescribes reality on a large table is a strong candidate for an explicit override.",
        "most_common_value_frequency shows how dominant the single most frequent value is. On an exchange this is where skew becomes visible: if one market symbol is 40% of the rows, the planner knows that only if that value is captured in the most common value list.",
        "mcv_entries is bounded by the column's statistics target. A column with 5,000 distinct values and a target of 100 keeps only the top 100, so the frequencies of everything else are approximated from the remaining histogram -- which is exactly where estimates for mid-frequency values go wrong.",
        "null_frac matters more than it appears: a column that is 95% NULL (for example settled_at on open orders) makes IS NULL and IS NOT NULL predicates wildly different in selectivity, and a planner without that information will misjudge both.",
        "correlation near zero makes ordered index scans look expensive; near 1 or -1 makes them look cheap. It is a physical-layout statistic and changes after a table rewrite or repack.",
        "Extended statistics (CREATE STATISTICS) are the only mechanism that teaches the planner about dependencies between columns. Without them, the estimate for a two-column predicate is the product of two independent selectivities, which for correlated exchange columns is wrong by orders of magnitude in the safe direction (too small) -- which is precisely what produces runaway nested loops.",
    ],
    remediation_immediate=[
        "Run a targeted ANALYZE on the implicated table if its statistics are stale; this frequently corrects the estimate and the plan within seconds (see stale-statistics for the guarded runbook).",
    ],
    remediation_short_term=[
        "Raise the statistics target for the specific skewed column and re-analyze, rather than raising default_statistics_target cluster-wide.",
        "Create extended statistics for the correlated column groups the application filters on together, then ANALYZE the table so they are populated.",
        "Add an expression index where a predicate wraps a column in a function, which both enables index use and provides statistics for the expression.",
    ],
    remediation_long_term=[
        "Add statistics-target and extended-statistics decisions to the schema definition for hot exchange tables, so they survive table rebuilds and environment recreation instead of being re-discovered during incidents.",
        "Include representative production-scale data in pre-production so plan differences driven by skew are caught before release.",
        "Review the autoanalyze scale factor for very large tables, where the default 10% threshold means an enormous absolute number of modifications before statistics are refreshed.",
    ],
    production_safety=[
        "All .sql scripts here are read-only catalog and statistics reads.",
        "Comparing estimates against actuals requires executing the query, which is why it is a guarded runbook. " + EXPLAIN_ANALYZE_WARNING,
        "ANALYZE and CREATE STATISTICS are not run by any script in this workflow: they are change-managed actions documented in the runbook, because ANALYZE on a very large table consumes I/O and CREATE STATISTICS is a schema change.",
    ],
    escalation_criteria=[
        "Statistics are fresh, targets are adequate, extended statistics exist, and the estimate is still wrong by orders of magnitude -- this is a genuinely hard estimation case that needs engineering input on query shape.",
        "The estimation error affects a settlement, reconciliation, or compliance query with a deadline.",
        "Correcting the estimate requires an ANALYZE on a table large enough that its I/O cost needs a maintenance window.",
    ],
    related_issues=[
        "../stale-statistics/README.md",
        "../analyze-query-plan/README.md",
        "../nested-loop-problems/README.md",
        "../query-plan-regression/README.md",
        "../../vacuum-and-autovacuum/analyze-statistics/README.md",
    ],
    aurora_notes=[
        "Statistics live in the shared cluster storage as ordinary catalog data, so an ANALYZE run on the writer immediately benefits every reader in the cluster -- there is no need to analyze per instance.",
        "default_statistics_target is set through the Aurora DB cluster parameter group; per-column targets are set with ALTER TABLE and are usually the better-targeted choice.",
        "An Aurora failover does not lose planner statistics (they are catalog data, not in-memory counters), unlike pg_stat_statements, which does not survive it.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_statistics_freshness",
        "Ranks tables by how much they have changed since their last ANALYZE.",
        sb.statistics_freshness(),
        "Rule this out before anything else: a high pct_modified_since_analyze combined with a stale last_analyze means the planner is estimating from a picture of the table that no longer exists, and no amount of statistics-target tuning will help until that is corrected. On a very large exchange table the default autoanalyze threshold of 10% of rows can represent tens of millions of modifications, so a table can be badly stale while still technically within policy.",
        related_scripts="02_column_distribution_statistics.sql",
        table_purpose="Statistics freshness across tables.",
    ),
    sql_script(
        "02", "02_column_distribution_statistics",
        "Shows the planner's stored distribution statistics for every column of one table.",
        _column_statistics_for_table(),
        "This is exactly what the planner knows. Compare each column against your knowledge of the business data: if you know one market symbol carries 40% of trades, most_common_value_frequency should show roughly that, and if it does not, the statistics are either stale or too coarse. A negative n_distinct close to -1 means nearly every value is unique; a positive value far below the true distinct count on a large table is a sampling failure and is a candidate for an explicit override. Note any column with a high null_frac, since predicates on it will be estimated very differently from what a naive reading suggests.",
        related_scripts="03_statistics_targets.sql",
        table_purpose="Per-column distribution statistics for one table.",
    ),
    sql_script(
        "03", "03_statistics_targets",
        "Shows the per-column statistics target for one table alongside the cluster default.",
        """
-- How much resolution the planner is allowed to keep for each column.
-- The statistics target controls both the number of most-common-value
-- entries and the number of histogram buckets stored by ANALYZE.
--
-- PostgreSQL 17 note: pg_attribute.attstattarget is nullable, and NULL
-- means "use default_statistics_target" (earlier versions stored -1 for
-- the same meaning). It is coalesced to -1 below so the two conventions
-- read identically.
--
-- The relation name is only compared inside a WHERE clause, so a name that
-- does not exist yields zero rows rather than an error.
\\set schema_name 'public'
\\set table_name 'orders'
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    a.attname                                                    AS column_name,
    a.attnum                                                     AS column_position,
    format_type(a.atttypid, a.atttypmod)                          AS column_type,
    coalesce(a.attstattarget, -1)                                 AS column_statistics_target,
    (SELECT setting::int FROM pg_settings WHERE name = 'default_statistics_target')
                                                                  AS default_statistics_target,
    CASE
        WHEN coalesce(a.attstattarget, -1) < 0
            THEN 'inherits default_statistics_target'
        ELSE 'explicit per-column override'
    END                                                           AS target_source,
    a.attnotnull                                                  AS is_not_null
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :'schema_name'
  AND c.relname = :'table_name'
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum;
""".strip("\n"),
        "The default target of 100 stores at most 100 most-common values and 100 histogram buckets per column. That is ample for a boolean or a small enumeration and wholly inadequate for a heavily skewed, high-cardinality column such as market symbol on an exchange with hundreds of listed pairs. Where script 02 showed mcv_entries pinned at the target and a long tail of values below it, raising that column's target (commonly to 500 or 1000) and re-analyzing is the direct fix. Raise it per column, not cluster-wide: a higher default makes every ANALYZE slower and every planning cycle more expensive.",
        related_scripts="04_extended_statistics_inventory.sql",
        table_purpose="Per-column statistics targets vs the cluster default.",
    ),
    sql_script(
        "04", "04_extended_statistics_inventory",
        "Lists the extended statistics objects defined in this database and the columns they cover.",
        """
-- Extended statistics objects teach the planner about relationships
-- BETWEEN columns. Without them, the planner assumes independence and
-- multiplies selectivities, which for correlated columns produces an
-- estimate that is far too small -- the classic trigger for a runaway
-- nested loop.
--
-- stxkind codes: 'd' = n-distinct, 'f' = functional dependencies,
-- 'm' = most-common-values list, 'e' = expression statistics.
--
-- stxkeys is an int2vector and is cast to smallint[] so it can be used
-- with ANY(); this is the same catalog-safe pattern used elsewhere in this
-- toolkit for pg_index.indkey.
SELECT
    sn.nspname                                                   AS statistics_schema,
    s.stxname                                                    AS statistics_name,
    tn.nspname                                                   AS table_schema,
    c.relname                                                    AS table_name,
    (
        SELECT array_agg(a.attname ORDER BY a.attnum)
        FROM pg_attribute a
        WHERE a.attrelid = s.stxrelid
          AND a.attnum = ANY (s.stxkeys::int2[])
    )                                                            AS covered_columns,
    s.stxkind                                                    AS statistic_kinds
FROM pg_statistic_ext s
JOIN pg_class c ON c.oid = s.stxrelid
JOIN pg_namespace tn ON tn.oid = c.relnamespace
JOIN pg_namespace sn ON sn.oid = s.stxnamespace
ORDER BY table_schema, table_name, statistics_name;

-- Candidate tables where extended statistics may be worth creating:
-- large tables carrying multiple low-cardinality columns that application
-- predicates commonly combine (for example market symbol plus order
-- status, or asset plus transaction type).
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size,
    c.reltuples::bigint                                          AS estimated_rows,
    count(*) FILTER (WHERE st.n_distinct BETWEEN 1 AND 1000)       AS low_cardinality_columns,
    EXISTS (
        SELECT 1 FROM pg_statistic_ext s WHERE s.stxrelid = c.oid
    )                                                            AS already_has_extended_statistics
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stats st
       ON st.schemaname = n.nspname
      AND st.tablename = c.relname
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
GROUP BY n.nspname, c.relname, c.oid, c.reltuples
HAVING count(*) FILTER (WHERE st.n_distinct BETWEEN 1 AND 1000) >= 2
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT 25;
""".strip("\n"),
        "An empty first result set is common and is itself a finding: most databases have no extended statistics at all, so every multi-column predicate is being estimated on an independence assumption that exchange data routinely violates. The second result set ranks large tables that carry several low-cardinality columns -- these are where a CREATE STATISTICS object is most likely to pay off, typically on pairs such as (market_symbol, order_status) or (asset, entry_type). Note that an extended statistics object listed here is inert until the table is analyzed: creating it does nothing on its own, and the populated data itself lives in a catalog that ordinary monitoring roles cannot read, so verify its effect through the plan rather than through the catalog.",
        expected_runtime="Low to moderate (the candidate query aggregates pg_stats across the database).",
        related_scripts="05_confirm_estimate_error.md",
        table_purpose="Extended statistics inventory and candidate tables.",
    ),
    md_script(
        "05", "05_confirm_estimate_error",
        "Guarded runbook for measuring estimated versus actual rows and applying the correct statistics remediation.",
        (
            "## What you are trying to establish\n\n"
            "Which node in the plan is being mis-estimated, by how much, and in which direction.\n"
            "Everything else -- the join strategy, the join order, the index choice -- follows\n"
            "from that number.\n\n"
            "## Step 1 -- Read the estimates for free\n\n"
            "```sql\n"
            "EXPLAIN (FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "Executes nothing. Note the estimated `rows=` at each node, especially at the\n"
            "filter or index scan that feeds the join. If you already know from the application\n"
            "that the filter matches millions of rows and the planner says 12, you have your\n"
            "answer without running anything.\n\n"
            "## Step 2 -- Get the actual counts (executes the statement)\n\n"
            "```sql\n"
            "SET LOCAL statement_timeout = '20s';\n"
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "Compare `rows=` with `actual rows=` at every node and find the **deepest** node\n"
            "where they diverge by an order of magnitude. That node is the cause; every bad\n"
            "decision above it is a consequence. Remember that on the inner side of a nested\n"
            "loop, `actual rows` is per loop -- multiply by `loops`.\n\n"
            "Prefer a reader instance for read-only statements. For a write statement, wrap in\n"
            "`BEGIN ... ROLLBACK` and do not do it on wallet, ledger, or settlement tables\n"
            "during trading hours.\n\n"
            "A cheaper alternative for a single predicate, which does not run the full query:\n\n"
            "```sql\n"
            "-- What the planner thinks:\n"
            "EXPLAIN SELECT 1 FROM orders WHERE market_symbol = 'BTC-USD' AND status = 'open';\n"
            "-- What is actually true (a plain count, no EXPLAIN ANALYZE of the full query):\n"
            "SELECT count(*) FROM orders WHERE market_symbol = 'BTC-USD' AND status = 'open';\n"
            "```\n\n"
            "The count still scans, so bound it with `statement_timeout` too, but it isolates\n"
            "the predicate without executing the rest of the query.\n\n"
            "## Step 3 -- Map the error to the right remediation\n\n"
            "| What the statistics show | Remediation |\n"
            "|---|---|\n"
            "| `last_analyze` stale, high `n_mod_since_analyze` | `ANALYZE schema.table;` -- targeted, change-managed |\n"
            "| Skewed column, `mcv_entries` pinned at the target | `ALTER TABLE t ALTER COLUMN c SET STATISTICS 1000;` then `ANALYZE t;` |\n"
            "| Two columns filtered together, estimate = product of selectivities | `CREATE STATISTICS ... (dependencies, mcv) ON a, b FROM t;` then `ANALYZE t;` |\n"
            "| Predicate wraps a column in a function or cast | Expression index, or `CREATE STATISTICS ... ON (expr) FROM t;` |\n"
            "| `n_distinct` badly wrong on a huge table | `ALTER TABLE t ALTER COLUMN c SET (n_distinct = -0.3);` then `ANALYZE t;` |\n\n"
            "### The statements themselves, with their real costs\n\n"
            "```sql\n"
            "-- Targeted statistics refresh. Takes a SHARE UPDATE EXCLUSIVE lock: does not\n"
            "-- block reads or writes, but does conflict with another ANALYZE/VACUUM and with\n"
            "-- most ALTER TABLE forms on the same table. Reads a sample of the table, so on a\n"
            "-- very large table it is real I/O -- prefer off-peak for multi-hundred-GB tables.\n"
            "ANALYZE public.orders;\n\n"
            "-- Higher resolution for one skewed column. The ALTER is instant (catalog only),\n"
            "-- but it takes ACCESS EXCLUSIVE briefly, and it has NO effect until the\n"
            "-- following ANALYZE actually collects the extra detail.\n"
            "ALTER TABLE public.orders ALTER COLUMN market_symbol SET STATISTICS 1000;\n"
            "ANALYZE public.orders;\n\n"
            "-- Teach the planner that two columns are related. Creating the object is cheap;\n"
            "-- it is inert until ANALYZE populates it.\n"
            "CREATE STATISTICS orders_market_status_stx (dependencies, mcv)\n"
            "    ON market_symbol, status\n"
            "    FROM public.orders;\n"
            "ANALYZE public.orders;\n"
            "```\n\n"
            "Every one of these is a change-managed action on a production exchange database:\n"
            "raise a change record, run it with a second engineer, and re-capture the plan\n"
            "afterwards to prove the estimate improved.\n\n"
            "## Step 4 -- Verify\n\n"
            "Re-run step 1. The estimate at the previously wrong node should now be within the\n"
            "same order of magnitude as reality, and the plan shape should have changed if the\n"
            "error was what drove the bad choice. If the estimate improved but the plan did not\n"
            "change, the estimate was not the binding constraint -- go back to\n"
            "`analyze-query-plan` and look elsewhere.\n\n"
            "## Never do this\n\n"
            "- Do not raise `default_statistics_target` cluster-wide to fix one column. Every\n"
            "  ANALYZE across the database gets slower and every planning cycle gets more\n"
            "  expensive.\n"
            "- Do not run a bare database-wide `ANALYZE;` on a production exchange cluster as a\n"
            "  routine fix. Target the specific tables.\n"
            "- Do not create extended statistics on every column pair speculatively: each object\n"
            "  adds work to every ANALYZE of that table.\n"
        ),
        "Use step 1 to form the hypothesis and step 2 only when you need the actual counts to confirm it. The output of this runbook should be one specific, minimal statistics change -- a targeted ANALYZE, one column's statistics target, or one extended statistics object -- followed by a re-capture proving the estimate moved.",
        safety=GUARDED_DDL,
        expected_impact="Step 1: none. Step 2: a full execution of the statement. Step 3: ANALYZE reads a sample of the table and takes a SHARE UPDATE EXCLUSIVE lock; ALTER TABLE ... SET STATISTICS takes a brief ACCESS EXCLUSIVE lock; CREATE STATISTICS is catalog-only but makes every subsequent ANALYZE of that table do more work.",
        required_privileges="pg_monitor for the read-only steps. ANALYZE requires table ownership or MAINTAIN; ALTER TABLE and CREATE STATISTICS require table ownership.",
        prerequisites="Scripts 01-04 completed, with the mis-estimated predicate and its columns identified.",
        execution_location=WRITER_PREFERRED,
        expected_runtime="Steps 1 and 3 (ALTER/CREATE): seconds. Step 2 and ANALYZE: minutes on a large table.",
        related_scripts="../stale-statistics/README.md, ../nested-loop-problems/README.md",
        table_purpose="Guarded runbook for measuring and correcting estimation errors.",
    ),
]

# ---------------------------------------------------------------------------
# stale-statistics
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="stale-statistics",
    title="Stale Planner Statistics",
    summary=(
        "Planner statistics are a snapshot of the data taken by the last ANALYZE. When a table "
        "changes substantially after that snapshot -- a backfill, a migration, a surge of new "
        "trades during a volatility event, a bulk purge -- the planner keeps making decisions "
        "from a picture of the data that no longer exists. This workflow finds tables whose "
        "statistics have drifted, explains why autoanalyze did not catch them, and provides the "
        "guarded runbook for refreshing them safely."
    ),
    symptoms=[
        "A query plan changed for the worse shortly after a data migration, backfill, or bulk load, with no code deployment involved.",
        "A newly created or recently truncated-and-reloaded table performs terribly on its first queries.",
        "n_mod_since_analyze is very large relative to the table's row count, while last_analyze and last_autoanalyze are old or NULL.",
        "Estimates in EXPLAIN output that match the table's size from some point in the past rather than its size now.",
    ],
    business_impact=[
        "Stale statistics are the most common cause of a sudden plan regression on an exchange, and they strike hardest immediately after a migration -- the moment when the team is least able to distinguish a database problem from a release problem.",
        "During a volatility event, table contents can change faster in an hour than they normally do in a week, so statistics can go stale precisely when query performance matters most.",
        "The remedy is usually a single targeted ANALYZE taking seconds to minutes, which makes an unfixed stale-statistics problem an expensive incident to leave running.",
    ],
    root_causes=[
        "A bulk load, backfill, or migration completed without a follow-up ANALYZE.",
        "autovacuum_analyze_scale_factor (default 0.1) being a percentage: on a 500 million row trades table, 10% means 50 million modifications before autoanalyze triggers.",
        "Autoanalyze starved because autovacuum workers are all busy, or because the table is repeatedly skipped in favour of more urgent anti-wraparound work.",
        "A per-table storage option disabling autovacuum or autoanalyze for the table, often set during a past incident and never reverted.",
        "A newly created table with no statistics at all until the first ANALYZE runs.",
        "A table restored from a dump or created by a migration tool, where statistics are never carried over and must be built fresh.",
    ],
    investigation_strategy=[
        "Rank tables by modifications since their last ANALYZE, relative to their size.",
        "Look specifically for tables that have never been analyzed, or that have very low analyze counters despite heavy write volume.",
        "Check the autovacuum and autoanalyze configuration, including per-table storage options that may have disabled it.",
        "Inspect the actual stored statistics for a suspect table to see how far they have drifted from reality.",
        "Refresh statistics for the specific tables identified, following the guarded runbook.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats) for the investigation.",
        "Table ownership, MAINTAIN privilege, or pg_maintain membership to execute the ANALYZE described in the runbook.",
        "The list of tables recently affected by a migration or bulk operation, if this investigation follows a deployment.",
    ],
    interpretation_guide=[
        "n_mod_since_analyze counts inserts, updates, and deletes since the last ANALYZE. Judge it as a percentage of n_live_tup rather than in absolute terms: 5 million modifications is nothing on a 500 million row table and catastrophic on a 2 million row one.",
        "last_analyze being NULL while last_autoanalyze is populated is normal -- it just means no human has ever run ANALYZE manually. Both being NULL on a table with rows means the planner has never had real statistics for it.",
        "A high analyze_count with still-stale statistics means autoanalyze is running but the scale factor is too coarse for the table's size; lower the per-table scale factor rather than analyzing manually on a schedule.",
        "A reloptions value containing autovacuum_enabled=false disables autoanalyze for that table as well. This is occasionally correct for a transient staging table and is almost always wrong on a permanent exchange table.",
        "ANALYZE is much cheaper than VACUUM: it reads a sample of pages rather than the whole table, takes a lock that does not block reads or writes, and never rewrites data. Running it on a specific table during trading hours is a normal, low-risk operation.",
        "Statistics do not exist for a table's TOAST storage or for expressions unless an expression index or extended statistics object provides them -- a table can look fully analyzed and still leave the planner blind to a predicate's selectivity.",
    ],
    remediation_immediate=[
        "Run a targeted ANALYZE on the specific tables implicated in the current performance problem, following the runbook in this workflow.",
    ],
    remediation_short_term=[
        "Lower autovacuum_analyze_scale_factor for the largest, highest-churn tables so autoanalyze triggers on a sensible absolute number of modifications rather than on a percentage of an enormous table.",
        "Remove any per-table option that disabled autovacuum or autoanalyze, unless there is a current, documented reason for it.",
        "Add an explicit ANALYZE step to the end of every migration that loads or bulk-modifies data.",
    ],
    remediation_long_term=[
        "Make post-migration ANALYZE an automated, non-optional step of the deployment pipeline rather than a runbook instruction someone must remember.",
        "Monitor statistics staleness as a first-class metric alongside vacuum debt, with per-table thresholds for the exchange's critical tables.",
        "Partition the very large tables so that autoanalyze operates on partition-sized units and triggers at a useful frequency without any scale-factor tuning.",
    ],
    production_safety=[
        "Every .sql script in this workflow is read-only; none of them runs ANALYZE.",
        "ANALYZE is deliberately provided only as a guarded markdown runbook. It is a maintenance operation against a specific table, and choosing when to run it against a production exchange table is an operator decision requiring change management -- an investigation script must never issue it implicitly.",
        "ANALYZE takes a SHARE UPDATE EXCLUSIVE lock: it does not block reads or writes, but it does conflict with concurrent VACUUM, another ANALYZE, and most ALTER TABLE forms on the same table.",
        "Never run a bare database-wide ANALYZE on a production exchange cluster as a routine remedy: it analyzes every table including the largest, generating substantial unnecessary I/O.",
    ],
    escalation_criteria=[
        "A table is so large that a full ANALYZE has a material I/O cost and needs a scheduled window.",
        "Statistics go stale again within hours of every refresh, meaning the write rate has outgrown the current autoanalyze configuration entirely.",
        "A plan regression persists after fresh, correctly-sized statistics -- escalate to cardinality-estimation and then to analyze-query-plan.",
    ],
    related_issues=[
        "../cardinality-estimation/README.md",
        "../query-plan-regression/README.md",
        "../analyze-query-plan/README.md",
        "../../vacuum-and-autovacuum/analyze-statistics/README.md",
        "../../database-health/post-deployment-check/README.md",
    ],
    aurora_notes=[
        "Statistics are catalog data on the shared cluster volume, so an ANALYZE on the writer is immediately visible to every reader. They also survive a failover, unlike pg_stat_statements counters.",
        "ANALYZE must run on the writer: readers are in continuous recovery and cannot write catalog rows.",
        "autovacuum_analyze_scale_factor and default_statistics_target are DB cluster parameter group settings on Aurora; per-table overrides via ALTER TABLE ... SET are the targeted alternative and require no parameter-group change or reboot.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_statistics_freshness_ranked",
        "Ranks tables by how far their statistics have drifted since the last ANALYZE.",
        sb.statistics_freshness(),
        "Read pct_modified_since_analyze together with n_live_tup and the analyze timestamps. Anything above roughly 20% on a table that participates in latency-sensitive queries is worth refreshing; anything above 50% means the planner is working from a substantially different table than the one that exists. A NULL in both last_analyze and last_autoanalyze on a populated table is the most severe case: the planner has never had real statistics for it at all.",
        related_scripts="02_analyze_counters_and_never_analyzed.sql",
        table_purpose="Tables ranked by statistics drift.",
    ),
    sql_script(
        "02", "02_analyze_counters_and_never_analyzed",
        "Surfaces tables that have never been analyzed or are analyzed far less often than their write volume warrants.",
        """
-- Analyze history per table, ordered so that never-analyzed and
-- rarely-analyzed tables surface first. A table with substantial write
-- activity and a near-zero analyze count is either newly created, excluded
-- from autoanalyze by a per-table setting, or being starved by autovacuum
-- worker contention.
\\set top_n 40
SELECT
    schemaname                                                   AS schema_name,
    relname                                                      AS table_name,
    n_live_tup,
    n_dead_tup,
    n_mod_since_analyze,
    n_tup_ins,
    n_tup_upd,
    n_tup_del,
    analyze_count                                                AS manual_analyze_count,
    autoanalyze_count,
    last_analyze,
    last_autoanalyze,
    last_vacuum,
    last_autovacuum,
    CASE
        WHEN last_analyze IS NULL AND last_autoanalyze IS NULL
            THEN 'never analyzed -- planner has no real statistics for this table'
        WHEN analyze_count + autoanalyze_count = 0
            THEN 'no analyze recorded since the last statistics reset'
        ELSE NULL
    END                                                          AS attention_flag
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY
    (last_analyze IS NULL AND last_autoanalyze IS NULL) DESC,
    (analyze_count + autoanalyze_count) ASC,
    n_live_tup DESC
LIMIT :top_n;
""".strip("\n"),
        "Tables flagged as never analyzed are the highest priority: the planner is estimating their size from whatever reltuples value the last vacuum or table creation left behind, which for a freshly migrated table is often zero, and a zero-row estimate reliably produces a nested loop over what is in fact a very large table. Note that these counters reset with pg_stat_reset() and on an Aurora failover, so a recently promoted writer can show zero analyze counts for tables that are in fact well analyzed -- cross-check last_autoanalyze, which is a timestamp rather than a counter.",
        related_scripts="03_autoanalyze_configuration.sql",
        table_purpose="Analyze history and never-analyzed tables.",
    ),
    sql_script(
        "03", "03_autoanalyze_configuration",
        "Shows the global autoanalyze settings and any per-table overrides that change or disable them.",
        """
-- Global autovacuum/autoanalyze configuration. On Aurora these come from
-- the DB cluster parameter group rather than postgresql.conf.
SELECT
    name,
    setting,
    unit,
    boot_val                                                     AS engine_default,
    reset_val                                                    AS new_session_value,
    source,
    short_desc
FROM pg_settings
WHERE name IN (
    'autovacuum',
    'autovacuum_analyze_threshold',
    'autovacuum_analyze_scale_factor',
    'autovacuum_vacuum_threshold',
    'autovacuum_vacuum_scale_factor',
    'autovacuum_vacuum_insert_threshold',
    'autovacuum_vacuum_insert_scale_factor',
    'autovacuum_max_workers',
    'autovacuum_naptime',
    'default_statistics_target'
)
ORDER BY name;

-- Per-table storage options. A reloptions entry containing
-- autovacuum_enabled=false disables autoANALYZE for that table as well as
-- autovacuum, which is a very common reason a single table's statistics
-- are indefinitely stale while every other table is fine.
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    c.relkind,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size,
    c.reloptions                                                  AS per_table_options
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'm')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND c.reloptions IS NOT NULL
ORDER BY pg_total_relation_size(c.oid) DESC;
""".strip("\n"),
        "autovacuum_analyze_scale_factor is a fraction of the table, so the absolute trigger point is threshold plus scale_factor multiplied by row count. At the default 0.1, a 500 million row trades table needs 50 million modifications before autoanalyze fires -- far too coarse for a table whose distribution shifts during every volatility event. The fix is a per-table override such as autovacuum_analyze_scale_factor = 0.01 on the largest tables. In the second result set, any table carrying autovacuum_enabled=false should be justified in writing or reverted.",
        required_privileges=PG_MONITOR,
        related_scripts="04_stored_statistics_for_table.sql",
        table_purpose="Autoanalyze configuration and per-table overrides.",
    ),
    sql_script(
        "04", "04_stored_statistics_for_table",
        "Inspects the actual stored distribution statistics for one suspect table.",
        _column_statistics_for_table(),
        "This is the direct evidence of drift. Compare what the planner stores against what you know is true now: if the exchange listed twenty new markets last month and the most common values list still contains only the old ones, the statistics predate that change and every predicate on that column is being estimated from history. An empty result set for a table you know has rows means no statistics exist at all for it, which is the most severe form of staleness.",
        related_scripts="05_refresh_statistics_safely.md",
        table_purpose="Stored distribution statistics for a suspect table.",
    ),
    md_script(
        "05", "05_refresh_statistics_safely",
        "Guarded runbook for refreshing planner statistics on specific tables with ANALYZE.",
        (
            "## Why ANALYZE is not a .sql script in this toolkit\n\n"
            "`ANALYZE` is a maintenance command that writes catalog data and takes a lock on the\n"
            "target table. Which tables to analyze, and when, is an operational decision that\n"
            "depends on table size, current load, and what else is running. An investigation\n"
            "script must never make that decision on the operator's behalf, and it must never\n"
            "execute a statement that a read-only session could not run. Hence: a runbook.\n\n"
            "## What ANALYZE actually costs\n\n"
            "- **Lock:** `SHARE UPDATE EXCLUSIVE`. It does **not** block `SELECT`, `INSERT`,\n"
            "  `UPDATE`, or `DELETE`. It **does** conflict with a concurrent `VACUUM`, another\n"
            "  `ANALYZE`, and most `ALTER TABLE` forms on the same table.\n"
            "- **I/O:** reads a random sample of pages, sized from the statistics target\n"
            "  (roughly 300 x target pages per column). Seconds on a small table; minutes and\n"
            "  real storage I/O on a multi-hundred-gigabyte table.\n"
            "- **Data:** never rewrites table data. There is nothing to roll back and no\n"
            "  possibility of data loss.\n"
            "- **Effect:** immediate. New plans are chosen from the new statistics as soon as it\n"
            "  commits, on the writer and on every Aurora reader.\n\n"
            "## Step 1 -- Analyze the specific tables, one at a time\n\n"
            "```sql\n"
            "-- Run on the WRITER. Readers are in recovery and cannot update catalogs.\n"
            "SET statement_timeout = 0;        -- only if a role default would cut it short\n"
            "\n"
            "ANALYZE VERBOSE public.orders;\n"
            "ANALYZE VERBOSE public.trades;\n"
            "```\n\n"
            "- Name the tables explicitly. Never issue a bare `ANALYZE;` on a production\n"
            "  exchange cluster -- it analyzes everything, including tables that do not need it.\n"
            "- `VERBOSE` reports the sample size and row count per table, which is useful\n"
            "  evidence for the change record.\n"
            "- Run them sequentially rather than in parallel sessions, so several large samples\n"
            "  do not compete for storage I/O at once.\n"
            "- For a single very large table during trading hours, consider analyzing specific\n"
            "  columns only:\n\n"
            "  ```sql\n"
            "  ANALYZE public.trades (market_symbol, executed_at);\n"
            "  ```\n\n"
            "## Step 2 -- Verify it took effect\n\n"
            "Re-run script 01 of this workflow. `last_analyze` must now be current and\n"
            "`n_mod_since_analyze` must have reset to approximately zero. Then re-run script 04\n"
            "and confirm the stored distribution now matches reality.\n\n"
            "Finally, re-capture the plan for the affected query with plain `EXPLAIN` (no\n"
            "`ANALYZE` needed) and confirm the estimates and the plan shape changed as expected.\n\n"
            "## Step 3 -- Stop it recurring\n\n"
            "```sql\n"
            "-- Make autoanalyze trigger on a sane absolute number of modifications for a very\n"
            "-- large table, instead of on 10% of an enormous row count.\n"
            "-- Catalog-only change, but it takes a brief ACCESS EXCLUSIVE lock: schedule it\n"
            "-- like any other DDL on a hot table.\n"
            "ALTER TABLE public.trades SET (autovacuum_analyze_scale_factor = 0.01);\n"
            "\n"
            "-- Re-enable autovacuum/autoanalyze on a table where it was disabled during a past\n"
            "-- incident and never restored.\n"
            "ALTER TABLE public.order_book_snapshots SET (autovacuum_enabled = true);\n"
            "```\n\n"
            "And make the migration pipeline do it automatically: every migration that backfills\n"
            "or bulk-modifies a table should end with a targeted `ANALYZE` of that table, so the\n"
            "planner never spends time working from a pre-migration picture of the data.\n\n"
            "## Do not\n\n"
            "- Do not run a bare database-wide `ANALYZE;` as a routine remedy.\n"
            "- Do not run `VACUUM ANALYZE` when only statistics are stale: `VACUUM` is far more\n"
            "  expensive and is not what the problem calls for.\n"
            "- Do not run `ANALYZE` concurrently on many large tables during peak trading -- the\n"
            "  sampling I/O competes with the order path.\n"
            "- Do not raise `default_statistics_target` cluster-wide as a substitute for\n"
            "  analyzing the specific table that is stale.\n"
        ),
        "Use this immediately after any migration or bulk data change, and whenever script 01 shows a latency-sensitive table above roughly 20% drift. The verification in step 2 is not optional: an ANALYZE that ran against the wrong database or was cut short by an inherited statement_timeout looks exactly like one that succeeded until you check last_analyze.",
        safety=GUARDED_DDL,
        expected_impact="ANALYZE takes a SHARE UPDATE EXCLUSIVE lock (does not block reads or writes) and reads a sample of the table, which is real storage I/O on a very large table. ALTER TABLE ... SET takes a brief ACCESS EXCLUSIVE lock.",
        required_privileges="Table ownership, the MAINTAIN privilege (PostgreSQL 16+), or pg_maintain membership to run ANALYZE. Table ownership to change per-table storage options.",
        prerequisites="Scripts 01-04 completed and the specific stale tables identified. Change record raised for a production exchange cluster.",
        execution_location="Writer instance only -- readers are in continuous recovery and cannot update catalog statistics.",
        expected_runtime="Seconds on a small table; minutes on a multi-hundred-gigabyte table.",
        related_scripts="../cardinality-estimation/README.md, ../../vacuum-and-autovacuum/analyze-statistics/README.md",
        table_purpose="Guarded ANALYZE runbook for refreshing stale statistics.",
    ),
]

# ---------------------------------------------------------------------------
# sort-spills
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="sort-spills",
    title="Sort Spills to Disk",
    summary=(
        "When a sort does not fit in work_mem, PostgreSQL switches from an in-memory quicksort "
        "to an external merge sort that writes runs to temporary files and merges them back. "
        "The query still returns correct results, silently, several times slower. On an exchange "
        "this hits ORDER BY on trade and order history, window functions over ledger entries, "
        "DISTINCT and GROUP BY on large result sets, and the sorts that feed merge joins. This "
        "workflow finds the spilling statements, decides whether the answer is memory, an index, "
        "or a smaller input, and guards the memory experiment."
    ),
    symptoms=[
        "Rising temp_bytes on the instance with no corresponding change in query volume.",
        "A paginated history endpoint (order history, trade history, ledger export) that is fast for recent pages and slow for deep ones.",
        "An EXPLAIN ANALYZE plan showing 'Sort Method: external merge  Disk: NkB'.",
        "Reporting queries whose runtime grew sharply once a table crossed a size threshold, with no plan change.",
    ],
    business_impact=[
        "A spilled sort converts a memory-speed operation into local-disk I/O, typically multiplying the statement's runtime several-fold and consuming I/O capacity shared with the trading workload.",
        "Deep pagination over trade history is a common exchange pattern and a common spill source: the database sorts a very large result set to return the fiftieth page of it.",
        "Concurrent spills compete for finite local instance storage, so several large sorts at once can fail outright rather than merely slow down.",
    ],
    root_causes=[
        "work_mem too small for the sort's input size -- the direct cause of every spill.",
        "A row underestimate making the planner believe the sort would be small, so it chose a plan requiring a sort at all.",
        "No index providing the required ordering, forcing an explicit sort where an ordered index scan would have needed none.",
        "OFFSET-based deep pagination, which sorts the entire result set to discard most of it.",
        "Parallel query multiplying memory demand: each worker performs its own sort with its own work_mem allocation.",
        "Wide rows being sorted: selecting many columns, or large text and JSON payloads, inflates the sort's memory footprint far beyond what the row count suggests.",
    ],
    investigation_strategy=[
        "Identify the statements writing the most temporary blocks.",
        "Quantify the cluster-wide temp file trend to distinguish a systemic memory-sizing problem from one bad query.",
        "Review the memory settings that determine the spill threshold, including the parallel worker multiplier.",
        "Check whether an index could supply the ordering and remove the sort altogether.",
        "Capture the plan under the guarded runbook to read Sort Method and size the minimum sufficient work_mem.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "pg_stat_statements for statement-level temporary block attribution.",
        "log_temp_files set to 0 is strongly recommended so every spill is logged with its size and statement; on Aurora those log lines are exported to CloudWatch Logs.",
    ],
    interpretation_guide=[
        "'Sort Method: quicksort  Memory: NkB' means the sort fit in memory and there is nothing to fix. 'external merge  Disk: NkB' means it spilled, and the Disk figure tells you roughly how much memory would have been needed to avoid it.",
        "The Disk figure is not the required work_mem directly -- the on-disk representation differs from the in-memory one -- but it is the right order of magnitude for choosing the next value to test.",
        "An index that provides the required ordering removes the sort entirely and permanently, at every data volume. That is almost always a better answer than granting more memory, which only postpones the spill until the table grows.",
        "Deep OFFSET pagination cannot be fixed with memory: sorting a million rows to return rows 900,000 to 900,050 is inherent to the query shape. Keyset pagination (WHERE (created_at, id) < (:last_seen_at, :last_seen_id) ORDER BY created_at DESC, id DESC LIMIT 50) removes both the sort and the offset scan.",
        "work_mem applies per sort node and per parallel worker. A statement with two sorts across four workers can allocate eight times work_mem at once, which is why a global increase is far riskier than it appears.",
        "A sort that spills only occasionally is parameter-sensitive: it is fine for a narrow date range and spills for a wide one. Size the fix for the realistic worst case, not the average.",
    ],
    remediation_immediate=[
        "For a report that must complete now, raise work_mem in that session alone before running it.",
    ],
    remediation_short_term=[
        "Add the index that supplies the required ordering so no sort is needed, built CONCURRENTLY.",
        "Raise work_mem for the specific reporting or batch role rather than cluster-wide.",
        "Run a targeted ANALYZE if a row underestimate caused the planner to choose a sort-based plan it should not have chosen.",
        "Reduce the sorted row width by selecting only the needed columns, which can pull a borderline sort back into memory at no cost.",
    ],
    remediation_long_term=[
        "Replace OFFSET pagination with keyset pagination on the exchange's history endpoints -- it removes the sort and the discarded scan work simultaneously.",
        "Move analytical and export workloads onto dedicated Aurora readers with a parameter group sized for sorting.",
        "Partition the large history tables by time so ordered scans and sorts naturally operate on bounded partitions.",
    ],
    production_safety=[
        "All .sql scripts here are read-only.",
        "Testing a larger work_mem is a guarded runbook step because the setting multiplies across sort nodes, parallel workers, and concurrent connections; an unconsidered global increase is a direct route to instance memory exhaustion. " + EXPLAIN_ANALYZE_WARNING,
        "Prefer reproducing a spilling read-only statement on a reader instance, where the temporary file I/O does not compete with the order path on the writer.",
    ],
    escalation_criteria=[
        "Local instance storage is close to exhaustion from concurrent temporary files -- this fails queries outright and must be escalated immediately.",
        "A settlement, reconciliation, or regulatory export cannot complete within its window even with a reasonable memory allocation.",
        "The sort is inherent to the query shape (deep pagination, an unbounded export) and needs an application-side change rather than database tuning.",
    ],
    related_issues=[
        "../temp-file-investigation/README.md",
        "../hash-join-analysis/README.md",
        "../merge-join-analysis/README.md",
        "../analyze-query-plan/README.md",
        "../../performance/high-iops/README.md",
    ],
    aurora_notes=[
        "Temporary files are written to local instance storage, not to the shared Aurora cluster volume, so their capacity is bounded by the instance class and exhausting it produces query errors rather than cluster storage growth.",
        "work_mem is changed through the Aurora DB cluster or DB instance parameter group; ALTER SYSTEM is unavailable. A per-role default set with ALTER ROLE is the targeted alternative and takes effect without a reboot.",
        "A dedicated reader with its own DB instance parameter group can carry a large work_mem for reporting without exposing the writer to the same memory risk -- the cleanest Aurora-native separation for spill-heavy analytical work.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_statements_spilling_to_disk",
        "Ranks statements by temporary block volume to find those whose sorts are spilling.",
        _pgss_guarded(sb.pgss_temp_and_io_heavy()),
        "Divide temp_blks_written by calls to distinguish two very different problems: a report that spills gigabytes once a month, and an API query that spills a few megabytes on every one of a million calls. The second is usually the more damaging on an exchange, because it consumes local storage I/O continuously in the request path. Note that this view cannot distinguish a sort spill from a hash spill -- the plan capture in script 05 does that.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="02_temp_file_volume_trend.sql",
        table_purpose="Statements writing the most temporary blocks.",
    ),
    sql_script(
        "02", "02_temp_file_volume_trend",
        "Measures cluster-wide temporary file volume to judge whether spilling is systemic.",
        sb.temp_file_usage_by_database(),
        "Convert temp_bytes into a rate using the counting window and compare it against previous health checks. A steadily rising rate with an unchanged workload is a capacity signal: data volumes have crossed the point where previously in-memory sorts no longer fit, and the memory configuration needs to grow with the data. A sudden step change points at a specific new query or deployment instead.",
        related_scripts="03_sort_memory_settings.sql, ../temp-file-investigation/README.md",
        table_purpose="Cluster-wide temp file volume trend.",
    ),
    sql_script(
        "03", "03_sort_memory_settings",
        "Reviews the memory and logging settings that determine when a sort spills and whether it is recorded.",
        _memory_and_spill_settings(),
        "Compute the realistic worst case before changing anything: work_mem multiplied by the number of sort and hash nodes in the plan, multiplied by one plus max_parallel_workers_per_gather, multiplied by the number of concurrent sessions running that statement. If log_temp_files is -1, spills are not being logged at all and you are working blind between health checks -- setting it to 0 in the Aurora parameter group logs every temporary file with its size and owning statement, at negligible cost.",
        required_privileges=PG_MONITOR,
        related_scripts="04_ordering_index_coverage.sql",
        table_purpose="Sort memory and temp file logging configuration.",
    ),
    sql_script(
        "04", "04_ordering_index_coverage",
        "Checks whether an index could supply the required ordering and remove the sort entirely.",
        _index_inventory_for_table(),
        "Read each index definition against the statement's ORDER BY, GROUP BY, and DISTINCT clauses, including sort direction and NULLS ordering. An index on (account_id, created_at DESC) can serve ORDER BY created_at DESC for a single account without any sort at all; an index on (created_at) alone cannot serve ORDER BY account_id, created_at. Where a partial prefix matches, PostgreSQL 13+ can use an Incremental Sort, which is already a large improvement and hints that extending the index would remove the sort completely.",
        related_scripts="05_size_sort_memory_safely.md, ../merge-join-analysis/README.md",
        table_purpose="Index coverage for the required ordering.",
    ),
    md_script(
        "05", "05_size_sort_memory_safely",
        "Guarded runbook for confirming a sort spill and choosing between an index, a smaller input, and more memory.",
        (
            "## What this runbook produces\n\n"
            "A decision between three remediations, in descending order of preference: remove the\n"
            "sort with an index, shrink the sort's input, or grant more memory at the narrowest\n"
            "scope that works.\n\n"
            "## Step 1 -- See whether a sort is planned at all (free)\n\n"
            "```sql\n"
            "EXPLAIN (FORMAT TEXT)\n"
            "SELECT ... ORDER BY ... ;\n"
            "```\n\n"
            "Executes nothing. A `Sort` node means an explicit sort is planned. An `Index Scan`\n"
            "satisfying the `ORDER BY` with no `Sort` node above it means the ordering is already\n"
            "free and there is nothing to fix here.\n\n"
            "## Step 2 -- Confirm the spill and its size (executes the statement)\n\n"
            "```sql\n"
            "SET LOCAL statement_timeout = '30s';\n"
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n"
            "SELECT ... ORDER BY ... ;\n"
            "```\n\n"
            "Read the `Sort Method` line:\n\n"
            "```\n"
            "->  Sort  (cost=... rows=2400000 width=96)\n"
            "      Sort Key: t.executed_at DESC\n"
            "      Sort Method: external merge  Disk: 412320kB\n"
            "```\n\n"
            "- `quicksort  Memory: NkB` -- fits in memory, nothing to fix.\n"
            "- `external merge  Disk: NkB` -- spilled. The `Disk` figure is the right order of\n"
            "  magnitude for the memory the sort needed.\n"
            "- `top-N heapsort  Memory: NkB` -- a `LIMIT` let PostgreSQL keep only the top N\n"
            "  rows. This is the cheap case and is what keyset pagination produces.\n\n"
            "Also compare the Sort node's estimated `rows=` against `actual rows`: a large gap\n"
            "means the planner never expected this sort to be big, and the real fix is\n"
            "statistics, not memory.\n\n"
            "Run this on a reader for read-only statements.\n\n"
            "## Step 3 -- Find the minimum sufficient work_mem (if memory is the answer)\n\n"
            "```sql\n"
            "BEGIN;\n"
            "SET LOCAL work_mem = '128MB';        -- this transaction only\n"
            "SET LOCAL statement_timeout = '30s';\n"
            "EXPLAIN (ANALYZE, BUFFERS)\n"
            "SELECT ... ORDER BY ... ;\n"
            "ROLLBACK;\n"
            "```\n\n"
            "Step the value up (32MB, 64MB, 128MB, 256MB) until `Sort Method` becomes\n"
            "`quicksort`. Use the **smallest** value that achieves it -- the goal is the minimum\n"
            "sufficient allocation, not the largest one that fits.\n\n"
            "Before applying that value anywhere beyond a single transaction, do the arithmetic:\n\n"
            "```\n"
            "worst case per statement = work_mem x (sort + hash nodes)\n"
            "                                    x (1 + max_parallel_workers_per_gather)\n"
            "worst case on the instance = that x concurrent sessions running it\n"
            "```\n\n"
            "## Step 4 -- Apply the fix at the right scope\n\n"
            "| Evidence | Fix | Scope |\n"
            "|---|---|---|\n"
            "| An index could supply the ordering | `CREATE INDEX CONCURRENTLY` on the sort key | Permanent, all volumes |\n"
            "| Sort estimate far below actual | Targeted `ANALYZE`, then re-plan | The table |\n"
            "| Deep `OFFSET` pagination | Keyset pagination in the application | The query |\n"
            "| Wide rows being sorted | Select fewer columns; sort keys and identifiers only | The query |\n"
            "| Genuinely large analytical sort | `ALTER ROLE reporting_role SET work_mem = '256MB';` | One role |\n"
            "| Analytical sorts competing with trading | Dedicated reader with its own parameter group | Cluster topology |\n\n"
            "### Keyset pagination, the highest-leverage fix for exchange history endpoints\n\n"
            "```sql\n"
            "-- Instead of: ORDER BY executed_at DESC OFFSET 900000 LIMIT 50\n"
            "-- (which sorts everything and throws away 900,000 rows)\n"
            "SELECT ...\n"
            "FROM trades\n"
            "WHERE account_id = :account_id\n"
            "  AND (executed_at, id) < (:last_seen_at, :last_seen_id)\n"
            "ORDER BY executed_at DESC, id DESC\n"
            "LIMIT 50;\n"
            "```\n\n"
            "With an index on `(account_id, executed_at DESC, id DESC)` this becomes a bounded\n"
            "index scan with no sort and no discarded rows, at any page depth.\n\n"
            "## Never do this\n\n"
            "- Do not raise `work_mem` in the cluster parameter group to fix one report.\n"
            "- Do not run step 2 or 3 against a data-modifying statement outside\n"
            "  `BEGIN ... ROLLBACK`.\n"
            "- Do not treat more memory as a permanent answer to a sort that grows with the\n"
            "  table: it postpones the problem to the next volume threshold.\n"
        ),
        "Run step 1 first -- if there is no Sort node, this workflow does not apply. Use step 2 to get the Sort Method and the Disk size, and only use step 3 when the index and query-shape options in step 4 are genuinely unavailable. The deliverable is the narrowest fix that removes the spill, with an index preferred over memory wherever one can supply the ordering.",
        safety=GUARDED_DDL,
        expected_impact="Step 1: none. Steps 2 and 3: a full execution of the statement, including its temporary file I/O. A large work_mem test on a busy instance contributes real memory pressure for the duration.",
        required_privileges="The same privileges the statement under investigation requires. Changing a role default additionally requires ALTER ROLE privileges.",
        prerequisites="Scripts 01-04 completed and the spilling statement plus representative parameters identified.",
        execution_location="Reader instance preferred for read-only statements.",
        expected_runtime="Step 1: milliseconds. Steps 2 and 3: up to the configured statement_timeout.",
        related_scripts="../temp-file-investigation/README.md, ../hash-join-analysis/README.md",
        table_purpose="Guarded runbook for confirming a sort spill and sizing the fix.",
    ),
]

# ---------------------------------------------------------------------------
# temp-file-investigation
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="temp-file-investigation",
    title="Temporary File Investigation",
    summary=(
        "Temporary files are PostgreSQL's overflow mechanism: any operation that exceeds its "
        "memory budget -- a sort, a hash join, a hash aggregate, a materialized CTE, a large "
        "cursor -- writes the excess to local instance storage. This workflow is the "
        "instance-level view: how much temporary file volume exists, which statements produce "
        "it, which sessions are producing it right now, and whether the configuration makes it "
        "visible at all. It is where an unexplained I/O or storage symptom is traced back to a "
        "specific statement."
    ),
    symptoms=[
        "Rising temp_bytes on pg_stat_database with no obvious workload change.",
        "Elevated local storage I/O or an unexplained latency increase that does not correlate with query volume.",
        "Sessions waiting on IO wait events such as BufFileRead and BufFileWrite.",
        "Log entries reporting temporary file creation, or a local storage capacity alert on the instance.",
    ],
    business_impact=[
        "Temporary file I/O competes directly with the trading workload for the instance's I/O capacity, so heavy spilling by a background report degrades order placement and balance lookups that are nowhere near it in the code.",
        "Local instance storage is finite and not shared with the Aurora cluster volume: exhausting it causes queries to fail outright with an out-of-space condition rather than merely slowing down.",
        "Because the excess is invisible in table sizes and in the cluster volume, unexplained temporary file growth is frequently misdiagnosed as a hardware or Aurora platform problem when it is in fact one query with an undersized memory budget.",
    ],
    root_causes=[
        "work_mem too small for the workload's sorts, hashes, and aggregates -- the dominant cause.",
        "Row underestimates leading the planner to choose memory-hungry plans it believed would be small.",
        "Large analytical or export queries running against the writer instead of a dedicated reader.",
        "Deep OFFSET pagination and unbounded exports sorting far more rows than they return.",
        "Materialized CTEs and large cursors holding intermediate result sets on disk.",
        "Parallel query multiplying per-worker memory demand beyond what a single work_mem value suggests.",
        "log_temp_files left disabled, so spills accumulate unobserved until they become a capacity problem.",
    ],
    investigation_strategy=[
        "Quantify the cluster-wide temporary file volume and rate per database.",
        "Attribute the volume to specific statements through pg_stat_statements.",
        "Catch sessions that are spilling right now, using the temporary-file I/O wait events.",
        "Check the memory and logging configuration, including whether spills are being logged at all.",
        "Correlate the findings with the logs and reproduce safely under the guarded runbook.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "pg_stat_statements for statement-level attribution.",
        "log_temp_files set to 0 for complete visibility, with Aurora log export to CloudWatch Logs enabled so the entries are searchable.",
    ],
    interpretation_guide=[
        "pg_stat_database.temp_bytes is cumulative since stats_reset and counts every temporary file written by every backend. Convert it to a rate before comparing anything.",
        "pg_stat_statements attributes temporary blocks to normalized statements, which is what turns 'the instance is spilling' into 'this specific query is spilling'. Without the extension, the log is the only attribution path.",
        "The BufFileRead and BufFileWrite wait events indicate a backend actively reading or writing temporary files at this instant. Catching them requires sampling pg_stat_activity repeatedly during the problem window, since each spill may be brief.",
        "Temporary file volume is a symptom, never a root cause. The actual cause is always either insufficient memory for a legitimate operation, or a plan that should not have needed that much memory in the first place -- and only the plan distinguishes them.",
        "A steady low-level spill rate from a very high-frequency statement is usually more damaging to an exchange than a large occasional spill from a monthly report, because it consumes I/O continuously in the request path.",
        "On Aurora, temporary file space is local instance storage. It does not appear in VolumeBytesUsed, it is not shared between instances, and running out of it is an instance-level failure rather than a cluster-level one.",
    ],
    remediation_immediate=[
        "If local storage is close to exhaustion, stop or defer the largest spilling workloads first -- typically a report or export, not the trading path.",
        "Move a large one-off analytical query to a reader instance rather than letting it continue on the writer.",
    ],
    remediation_short_term=[
        "Raise work_mem for the specific role running the spilling workload, after sizing it with the sort-spills or hash-join-analysis runbook.",
        "Enable log_temp_files (value 0) so every future spill is attributed automatically instead of being reconstructed from counters.",
        "Run targeted ANALYZE where a row underestimate caused a memory-hungry plan.",
    ],
    remediation_long_term=[
        "Route analytical, export, and reconciliation workloads to dedicated Aurora readers with their own parameter group sized for spilling work.",
        "Set temp_file_limit for analytical roles so a runaway query fails fast instead of consuming the instance's entire local storage.",
        "Replace OFFSET pagination and unbounded exports with keyset pagination and chunked exports across the exchange's history and reporting endpoints.",
    ],
    production_safety=[
        "All .sql scripts here are read-only and safe during trading hours.",
        "Reproducing a spilling statement executes it and produces the same temporary file I/O again, which is why reproduction is a guarded runbook step and should happen on a reader. " + EXPLAIN_ANALYZE_WARNING,
        "Setting temp_file_limit is a safety control, not a tuning knob: it causes offending queries to fail rather than to exhaust storage, and that trade-off must be agreed with the workload owner before it is applied.",
    ],
    escalation_criteria=[
        "Local instance storage is close to exhaustion -- escalate immediately, because the failure mode is query errors rather than slow queries.",
        "Temporary file volume rose sharply with no identifiable statement and no deployment to explain it.",
        "The spilling workload cannot be moved off the writer and cannot be given more memory safely -- escalate for a topology or instance-class decision.",
    ],
    related_issues=[
        "../sort-spills/README.md",
        "../hash-join-analysis/README.md",
        "../analyze-query-plan/README.md",
        "../../performance/high-iops/README.md",
        "../../database-health/capacity-health-check/README.md",
    ],
    aurora_notes=[
        "Temporary files live on local instance storage, separate from the shared Aurora cluster volume. They do not appear in VolumeBytesUsed and their capacity is a property of the instance class, so the relevant CloudWatch metric is FreeLocalStorage rather than any cluster storage metric.",
        "log_temp_files is set through the Aurora DB cluster parameter group and takes effect without a reboot; the resulting log lines are exported to CloudWatch Logs, where they can be searched and aggregated across the fleet.",
        "Because each instance has its own local storage, moving analytical work to a reader moves its temporary file footprint there too -- which is precisely the point, as it removes that I/O from the writer's order path.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_temp_file_volume_by_database",
        "Quantifies cumulative temporary file volume and rate per database.",
        sb.temp_file_usage_by_database(),
        "Divide temp_bytes by the counting window for a bytes-per-second rate, and temp_files by the same window for a files-per-second rate. Together they distinguish many small spills (typical of a high-frequency statement with a slightly undersized work_mem) from a few enormous ones (typical of a report or export). Both need fixing, but the first one is the one silently taxing the trading path.",
        execution_location=ANY_INSTANCE,
        related_scripts="02_statements_producing_temp_files.sql",
        table_purpose="Temp file volume and rate per database.",
    ),
    sql_script(
        "02", "02_statements_producing_temp_files",
        "Attributes temporary file volume to specific normalized statements.",
        _pgss_guarded(sb.pgss_temp_and_io_heavy()),
        "This is the step that turns an instance-level symptom into an actionable statement. Note both the total temp_blks_written and the per-call figure: a statement with a small per-call spill and an enormous call count is a continuous drain on I/O capacity, while a large per-call spill on a rare statement is a scheduling and memory-sizing question. Carry the queryid into the plan capture to learn whether the spill is a sort, a hash, or a materialize.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="03_sessions_spilling_now.sql",
        table_purpose="Statements attributed with temporary file usage.",
    ),
    sql_script(
        "03", "03_sessions_spilling_now",
        "Catches sessions currently performing temporary file I/O, using the BufFile wait events.",
        """
-- Backends that are, at this instant, reading or writing temporary files
-- (the BufFile* wait events) or otherwise waiting on I/O. Spills are often
-- brief, so run this repeatedly during the problem window rather than once
-- -- each execution is a sample, not a continuous trace.
--
-- pg_wait_events (PostgreSQL 17) is joined so every wait_event value
-- carries its canonical description without needing the manual.
SELECT
    a.pid,
    a.datname,
    a.usename,
    coalesce(NULLIF(a.application_name, ''), '(unset)')           AS application_name,
    a.client_addr,
    a.state,
    a.backend_type,
    a.wait_event_type,
    a.wait_event,
    we.description                                                AS wait_event_description,
    now() - a.query_start                                         AS query_runtime,
    now() - a.xact_start                                          AS txn_runtime,
    left(a.query, 200)                                            AS query_snippet
FROM pg_stat_activity a
LEFT JOIN pg_wait_events we
       ON we.type = a.wait_event_type
      AND we.name = a.wait_event
WHERE a.pid <> pg_backend_pid()
  AND (
        a.wait_event LIKE 'BufFile%'
     OR a.wait_event_type = 'IO'
      )
ORDER BY query_runtime DESC NULLS LAST;

-- Broader context: what every backend is waiting on right now, so the
-- temporary-file I/O above can be weighed against everything else
-- happening on this instance.
SELECT
    a.wait_event_type,
    a.wait_event,
    count(*)                                                      AS backend_count
FROM pg_stat_activity a
WHERE a.pid <> pg_backend_pid()
  AND a.wait_event IS NOT NULL
GROUP BY a.wait_event_type, a.wait_event
ORDER BY backend_count DESC;
""".strip("\n"),
        "A backend on BufFileRead or BufFileWrite is actively spilling right now, and its query snippet identifies the statement directly -- this is the fastest attribution path when a spill is happening while you watch. Sample it several times over a minute: a single empty result does not mean nothing is spilling, only that nothing was spilling at that instant. If many backends appear here simultaneously, the instance's local storage I/O is saturated by temporary files and unrelated queries are being slowed by it.",
        execution_location=WRITER_PREFERRED,
        required_privileges=PG_MONITOR,
        related_scripts="04_memory_and_logging_settings.sql",
        table_purpose="Sessions currently performing temporary file I/O.",
    ),
    sql_script(
        "04", "04_memory_and_logging_settings",
        "Reviews the memory budget, the temp file limit, and whether spills are being logged.",
        _memory_and_spill_settings(),
        "Three findings matter here. log_temp_files at -1 means no spill is ever logged, so attribution depends entirely on cumulative counters -- set it to 0 in the Aurora cluster parameter group for full visibility at negligible cost. temp_file_limit at -1 means a single runaway query can consume all local storage; a bounded value makes it fail instead, which is usually the better outcome for an analytical role. And work_mem must be read as a per-node, per-worker budget, so the instance-level exposure is much larger than the configured value suggests.",
        required_privileges=PG_MONITOR,
        related_scripts="05_correlate_and_reproduce_safely.md",
        table_purpose="Memory budget, temp file limit, and logging configuration.",
    ),
    md_script(
        "05", "05_correlate_and_reproduce_safely",
        "Guarded runbook for correlating temporary files with statements via the logs and reproducing a spill safely.",
        (
            "## Where the definitive evidence lives\n\n"
            "The catalog views tell you that spilling happened and, with pg_stat_statements,\n"
            "which normalized statement did it. They cannot tell you **when**, with which\n"
            "parameters, or how large each individual spill was. That information is in the\n"
            "PostgreSQL log, which on Aurora is exported to CloudWatch Logs.\n\n"
            "## Step 1 -- Turn on temp file logging (if it is off)\n\n"
            "`log_temp_files` is a DB cluster parameter group setting on Aurora. Setting it to\n"
            "`0` logs every temporary file with its size and the statement that created it, and\n"
            "takes effect without a reboot.\n\n"
            "```\n"
            "log_temp_files = 0        -- log every temporary file, any size\n"
            "```\n\n"
            "The cost is one log line per temporary file. On a cluster spilling heavily that is\n"
            "a lot of lines -- which is itself the signal you are looking for.\n\n"
            "## Step 2 -- Find the spills in CloudWatch Logs\n\n"
            "The log group is `/aws/rds/cluster/<cluster-id>/postgresql`. A CloudWatch Logs\n"
            "Insights query such as:\n\n"
            "```\n"
            "fields @timestamp, @message\n"
            "| filter @message like /temporary file/\n"
            "| sort @timestamp desc\n"
            "| limit 200\n"
            "```\n\n"
            "returns lines of the form:\n\n"
            "```\n"
            "LOG:  temporary file: path \"base/pgsql_tmp/pgsql_tmp12345.0\", size 412319744\n"
            "STATEMENT:  SELECT ... ORDER BY executed_at DESC OFFSET 900000 LIMIT 50\n"
            "```\n\n"
            "The `STATEMENT` line carries the **real parameter values**, which pg_stat_statements\n"
            "normalizes away. That is what makes the log the definitive source: it tells you\n"
            "which account, which market, or which date range actually caused the spill.\n\n"
            "## Step 3 -- Reproduce safely, on a reader\n\n"
            "```sql\n"
            "-- On a READER instance, using the real parameters taken from the log.\n"
            "SET LOCAL statement_timeout = '30s';\n"
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "This executes the statement and produces the same spill again -- on the reader,\n"
            "where the local storage I/O does not compete with order matching. Read the plan to\n"
            "classify the spill:\n\n"
            "| Plan evidence | Spill type | Workflow to follow |\n"
            "|---|---|---|\n"
            "| `Sort Method: external merge  Disk:` | Sort spill | `sort-spills` |\n"
            "| `Hash ... Batches: N` where N > 1 | Hash join spill | `hash-join-analysis` |\n"
            "| `HashAggregate ... Disk Usage:` | Hash aggregate spill | `hash-join-analysis` (same memory rules) |\n"
            "| `CTE Scan` over a large materialized CTE | Materialization | Rewrite the CTE or add `NOT MATERIALIZED` |\n\n"
            "Do not reproduce a data-modifying statement without `BEGIN ... ROLLBACK`, and do not\n"
            "reproduce anything against wallet, ledger, or settlement tables during trading\n"
            "hours.\n\n"
            "## Step 4 -- Bound the damage while the real fix is built\n\n"
            "```sql\n"
            "-- Make a runaway analytical query fail instead of consuming all local storage.\n"
            "-- Applies to new sessions for that role; agree it with the workload owner first,\n"
            "-- because the query will now error rather than merely run slowly.\n"
            "ALTER ROLE reporting_role SET temp_file_limit = '8GB';\n"
            "\n"
            "-- Give the analytical role the memory it actually needs, sized with the\n"
            "-- sort-spills or hash-join-analysis runbook -- not guessed.\n"
            "ALTER ROLE reporting_role SET work_mem = '256MB';\n"
            "```\n\n"
            "Both are role-scoped: the exchange's order-path role keeps its original, safe\n"
            "settings.\n\n"
            "## Never do this\n\n"
            "- Do not raise `work_mem` globally to make temp file volume disappear. It converts\n"
            "  a disk problem into a memory-exhaustion risk across every connection.\n"
            "- Do not set `temp_file_limit` on the order-path role without agreement: a trading\n"
            "  query that fails is worse than a trading query that spills.\n"
            "- Do not reproduce a large spilling statement on the writer during trading hours\n"
            "  when a reader is available.\n"
        ),
        "Use the log to get the real parameter values, the reader to reproduce safely, and the plan to classify the spill as a sort, a hash, an aggregate, or a materialization -- then continue in the workflow named in the classification table. The role-scoped settings in step 4 are containment while the real fix is built, not the fix itself.",
        safety=GUARDED_DDL,
        expected_impact="Steps 1 and 2: no database impact (a parameter change and log reading). Step 3: a full execution of the statement including its temporary file I/O. Step 4: changes the default settings for new sessions of the named role.",
        required_privileges="pg_monitor for investigation; CloudWatch Logs read access for step 2; ALTER ROLE privileges for step 4; parameter-group change permissions for step 1.",
        prerequisites="Scripts 01-04 completed and a candidate statement identified.",
        execution_location="Reader instance preferred for reproduction; the parameter and role changes apply cluster-wide.",
        expected_runtime="Step 3: up to the configured statement_timeout. The other steps are immediate.",
        related_scripts="../sort-spills/README.md, ../hash-join-analysis/README.md",
        table_purpose="Guarded runbook for log correlation and safe spill reproduction.",
    ),
]

# ---------------------------------------------------------------------------
# inefficient-index-usage
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="inefficient-index-usage",
    title="Inefficient Index Usage",
    summary=(
        "An index can be present, valid, and still be the wrong answer: the planner may ignore "
        "it, it may be scanned but discard most of what it reads, it may duplicate another "
        "index, or it may never have been used at all while still taxing every insert on the "
        "order path. This workflow separates those cases using the catalog and the index "
        "statistics, so index changes on an exchange's hot tables are made from evidence rather "
        "than from intuition."
    ),
    symptoms=[
        "A query performs a sequential scan on a large table that visibly has a relevant index.",
        "Index scans return far more tuples than the query ultimately uses, indicating a poorly matched index.",
        "Write latency on orders, trades, or ledger_entries has grown as indexes accumulated over time.",
        "Index storage is a large fraction of total table storage on the biggest tables.",
    ],
    business_impact=[
        "Every index is write amplification: each insert into trades or ledger_entries must update every index on that table, so unused indexes tax the exchange's most latency-critical path continuously and invisibly.",
        "An index the planner refuses to use gives the worst of both outcomes -- full write and storage cost, zero read benefit.",
        "Index bloat and duplication inflate storage on the Aurora cluster volume, which never shrinks once grown.",
    ],
    root_causes=[
        "Predicate not sargable: a function or cast wrapped around the indexed column, so the index cannot be matched.",
        "Type or collation mismatch between the column and the comparison value, preventing index use.",
        "Wrong leading column: an index on (created_at, account_id) cannot serve a lookup on account_id alone.",
        "Low selectivity: the planner correctly judges that a sequential scan is cheaper than an index scan returning a large fraction of the table.",
        "Stale statistics making the index look less selective than it is.",
        "Duplicate or redundant indexes accumulated over years of incremental change, where one is a prefix of another.",
        "Indexes created for a feature or report that no longer exists, never removed.",
        "random_page_cost and effective_cache_size describing hardware that is not this Aurora instance, systematically biasing the planner against index scans.",
    ],
    investigation_strategy=[
        "Inventory index size and scan activity across the database to see where index effort and index cost actually are.",
        "Identify indexes with no recorded scans, being careful about the reset semantics of those counters.",
        "Identify structurally duplicate indexes, which are pure overhead by definition.",
        "Measure index scan efficiency: how many tuples each scan reads versus how many it returns.",
        "Cross-check tables where sequential scans dominate despite indexes existing.",
        "Validate any proposed index change safely before applying it to a hot table.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "Knowledge of when statistics were last reset -- idx_scan restarts at zero on instance restart, on failover, and on pg_stat_reset(), and acting on a reset counter is how correct indexes get dropped.",
        "The business cycle context: month-end reconciliation, quarterly regulatory reporting, and audit queries can leave an index unused for weeks and then make it essential.",
    ],
    interpretation_guide=[
        "idx_scan of zero means 'not used since the counters were reset', never 'not needed'. On an Aurora cluster that has failed over recently, every counter may be hours old. Check instance uptime and stats_reset before drawing any conclusion.",
        "PostgreSQL 16 and later also record last_idx_scan, a timestamp. It is far more trustworthy than the counter, because it survives as a statement about when the index was genuinely last useful.",
        "A large gap between idx_tup_read and idx_tup_fetch means the index scan reads many entries and the executor discards most of them -- typically a poorly ordered composite index, or one missing a column needed by the filter.",
        "Index counters on a reader reflect only that reader's own workload. An index unused on the writer may be heavily used by reporting on a reader, so check every instance before concluding anything.",
        "Indexes backing primary keys, unique constraints, and exclusion constraints exist for correctness, not performance. They must never be dropped on usage evidence.",
        "An index that is a strict leading-column prefix of another (a on (a) versus (a, b)) is usually redundant, but not always: a narrower index is smaller, fits in cache better, and can be meaningfully faster for a very hot lookup. Judge each case rather than applying the rule mechanically.",
    ],
    remediation_immediate=[
        "None. Index changes on exchange tables are planned changes, not incident responses -- the only exception is rebuilding an index that is actually invalid.",
    ],
    remediation_short_term=[
        "Rewrite non-sargable predicates, or add the matching expression index, so an existing index becomes usable.",
        "Add the correctly ordered composite index the workload actually needs, built CONCURRENTLY.",
        "Run a targeted ANALYZE where stale statistics are making the planner misjudge index selectivity.",
    ],
    remediation_long_term=[
        "Establish a periodic index review covering a full business cycle, so unused and duplicate indexes are removed deliberately rather than discovered during a storage incident.",
        "Treat index additions as schema changes with a stated query they serve, so indexes cannot accumulate anonymously.",
        "Tune random_page_cost and effective_cache_size to describe the actual Aurora instance, so the planner stops systematically preferring sequential scans.",
    ],
    production_safety=[
        "All .sql scripts here are read-only catalog and statistics reads; none of them creates or drops anything.",
        "Any index change is a schema change: build with CREATE INDEX CONCURRENTLY and drop with DROP INDEX CONCURRENTLY, because the non-concurrent forms take locks that block all traffic to the table for the duration.",
        "Never drop an index on the evidence of a single reading. Confirm across at least one full business cycle and across every instance in the cluster, and keep the exact index definition so it can be recreated quickly if the decision proves wrong.",
    ],
    escalation_criteria=[
        "A proposed index change affects orders, trades, wallets, or ledger_entries -- escalate for review, because the write-path impact is felt by every trade.",
        "An index appears unused on the writer but the reporting team cannot confirm it is unused on the readers.",
        "Index storage growth is a material component of the cluster's storage trend -- escalate into the capacity conversation rather than handling it as a local tuning task.",
    ],
    related_issues=[
        "../analyze-query-plan/README.md",
        "../cardinality-estimation/README.md",
        "../merge-join-analysis/README.md",
        "../../tables-and-indexes/unused-indexes/README.md",
        "../../tables-and-indexes/duplicate-indexes/README.md",
        "../../tables-and-indexes/missing-index-candidates/README.md",
        "../../tables-and-indexes/sequential-scan-investigation/README.md",
    ],
    aurora_notes=[
        "Index statistics are per-instance in-memory counters. The writer and each reader maintain their own, and all of them reset on restart or failover -- so a complete picture requires querying every instance in the cluster, not just the writer.",
        "Building an index consumes cluster volume that is not returned when another index is dropped: Aurora storage keeps its high-water mark, so removing an unused index frees space for reuse inside the database but does not reduce the storage bill.",
        "Aurora's network-attached storage changes the relative cost of random versus sequential access, so leaving random_page_cost at the community default of 4.0 biases the planner toward sequential scans more than the hardware justifies.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_index_inventory_and_usage",
        "Inventories every index with its size and scan activity, including the last-used timestamp.",
        sb.index_bloat_and_usage(),
        "Read size and idx_scan together. A large index with substantial scans is earning its cost. A large index with no scans is pure overhead on every write to that table -- but check last_idx_scan before believing the counter, because it survives the reasoning errors that a reset idx_scan causes. On an exchange, indexes on trades and ledger_entries deserve the most scrutiny: they are the largest, and they are on the tables whose insert latency matters most.",
        expected_runtime="Low to moderate (seconds; scales with the number of indexes).",
        related_scripts="02_unused_index_candidates.sql",
        table_purpose="Index size and usage inventory.",
    ),
    sql_script(
        "02", "02_unused_index_candidates",
        "Lists indexes with no recorded scans, excluding those backing constraints.",
        sb.unused_indexes(),
        "This is a candidate list, not a drop list. The query already excludes primary key and constraint-backing indexes, which exist for correctness. Before acting on any remaining entry, confirm three things: the counters have not been reset recently, the index is also unused on every reader in the cluster, and a full business cycle including month-end and quarter-end reporting has elapsed. Then keep the index definition on record so it can be recreated immediately if the decision turns out to be wrong.",
        related_scripts="03_duplicate_indexes.sql, ../../tables-and-indexes/unused-indexes/README.md",
        table_purpose="Candidate unused indexes.",
    ),
    sql_script(
        "03", "03_duplicate_indexes",
        "Finds structurally duplicate indexes on the same table.",
        sb.duplicate_indexes(),
        "True duplicates -- identical column lists, access method, and predicate -- are unambiguous overhead: identical storage, identical write cost, no additional query benefit. They usually arise from a migration that created an index the schema already had under a different name. Removing them is among the safest index changes available, though it is still a schema change and still uses DROP INDEX CONCURRENTLY.",
        related_scripts="04_index_scan_efficiency.sql, ../../tables-and-indexes/duplicate-indexes/README.md",
        table_purpose="Structurally duplicate indexes.",
    ),
    sql_script(
        "04", "04_index_scan_efficiency",
        "Measures how many tuples each index scan reads versus how many the executor actually keeps.",
        """
-- Index scan efficiency. idx_tup_read counts index entries read;
-- idx_tup_fetch counts live table rows actually fetched through those
-- entries. A large gap means the index is being scanned broadly and most
-- of what it returns is discarded -- the signature of an index whose
-- column order or column set does not match how the workload queries it.
--
-- (Index-only scans satisfy the query from the index alone and do not
-- increment idx_tup_fetch, so a high read/low fetch ratio can also be a
-- healthy index-only scan. Read this alongside the plan before concluding
-- the index is badly matched.)
\\set top_n 30
SELECT
    s.schemaname                                                 AS schema_name,
    s.relname                                                    AS table_name,
    s.indexrelname                                               AS index_name,
    pg_size_pretty(pg_relation_size(s.indexrelid))                AS index_size,
    s.idx_scan,
    s.idx_tup_read,
    s.idx_tup_fetch,
    round(s.idx_tup_read::numeric / NULLIF(s.idx_scan, 0), 1)      AS avg_entries_read_per_scan,
    round(
        100.0 * s.idx_tup_fetch / NULLIF(s.idx_tup_read, 0), 2
    )                                                             AS pct_read_entries_fetched,
    s.last_idx_scan,
    ix.indisunique,
    ix.indisprimary,
    pg_get_indexdef(s.indexrelid)                                 AS index_definition
FROM pg_stat_all_indexes s
JOIN pg_index ix ON ix.indexrelid = s.indexrelid
WHERE s.schemaname NOT IN ('pg_catalog', 'information_schema')
  AND s.idx_scan > 0
ORDER BY (s.idx_tup_read - s.idx_tup_fetch) DESC
LIMIT :top_n;
""".strip("\n"),
        "A high avg_entries_read_per_scan on an index meant to serve point lookups means it is being used for range scans it is not shaped for -- typically the leading column is not selective enough, so the scan walks a large portion of the index and the filter discards the rest. Adding the filtering column to the index, in the right position, usually converts that into a tight scan. Read pct_read_entries_fetched cautiously: a low value can equally mean an efficient index-only scan, so confirm against the plan before changing anything.",
        expected_runtime="Low to moderate (seconds).",
        related_scripts="05_sequential_scan_cross_check.sql",
        table_purpose="Index scan efficiency (entries read versus rows fetched).",
    ),
    sql_script(
        "05", "05_sequential_scan_cross_check",
        "Cross-checks tables where sequential scans dominate despite indexes being present.",
        sb.sequential_scan_heavy_tables() + "\n\n" + sb.invalid_indexes(),
        "A large table with heavy sequential scanning and a healthy set of indexes means the planner is declining to use them. The usual reasons, in order of frequency, are: a non-sargable predicate (a function or cast around the column), a type or collation mismatch, the wrong leading column, stale statistics making the index look unselective, and a cost configuration that overstates random I/O. The second result set catches the remaining case -- an index that is present but INVALID, which the planner ignores entirely while the application still pays for it on every write.",
        related_scripts="06_validate_index_change_safely.md, ../../tables-and-indexes/sequential-scan-investigation/README.md",
        table_purpose="Sequential scan pressure and invalid indexes.",
    ),
    md_script(
        "06", "06_validate_index_change_safely",
        "Guarded runbook for validating an index addition or removal before applying it to a hot exchange table.",
        (
            "## Principle\n\n"
            "An index change on `orders`, `trades`, `wallets`, or `ledger_entries` affects every\n"
            "write on the exchange's critical path. Validate first, change once, and always use\n"
            "the `CONCURRENTLY` forms.\n\n"
            "## Part A -- Validating a proposed NEW index\n\n"
            "### A1. Confirm the planner is not already using an equivalent index (free)\n\n"
            "```sql\n"
            "EXPLAIN (FORMAT TEXT)\n"
            "SELECT ... WHERE ... ;\n"
            "```\n\n"
            "Executes nothing. If it already shows an `Index Scan` on a suitable index, the\n"
            "problem is elsewhere and a new index is not the answer.\n\n"
            "### A2. Check whether the predicate is sargable at all\n\n"
            "A predicate that wraps the column in a function or a cast cannot use an ordinary\n"
            "index on that column:\n\n"
            "```sql\n"
            "-- Cannot use an index on created_at:\n"
            "WHERE date(created_at) = '2026-09-11'\n"
            "-- Can:\n"
            "WHERE created_at >= '2026-09-11' AND created_at < '2026-09-12'\n"
            "\n"
            "-- Cannot use an index on account_id if the types differ:\n"
            "WHERE account_id::text = :param\n"
            "-- Can, when the parameter is passed with the column's own type:\n"
            "WHERE account_id = :param\n"
            "```\n\n"
            "Rewriting the predicate is free and permanent; adding an index to work around an\n"
            "unnecessary cast is not.\n\n"
            "### A3. Build it CONCURRENTLY\n\n"
            "```sql\n"
            "-- Takes SHARE UPDATE EXCLUSIVE, not ACCESS EXCLUSIVE: reads and writes continue.\n"
            "-- Cannot run inside a transaction block. Takes roughly twice as long as a plain\n"
            "-- build and needs space for the finished index on the cluster volume.\n"
            "CREATE INDEX CONCURRENTLY idx_trades_account_executed\n"
            "    ON public.trades (account_id, executed_at DESC);\n"
            "```\n\n"
            "If the build is interrupted -- a cancelled session, a `statement_timeout`, a\n"
            "deadlock -- it leaves an **INVALID** index behind. Check for one afterwards with\n"
            "script 05 of this workflow, and drop it before retrying; an invalid index cannot be\n"
            "validated in place.\n\n"
            "### A4. Prove it is being used\n\n"
            "```sql\n"
            "EXPLAIN (FORMAT TEXT) SELECT ... ;    -- should now show the new index\n"
            "```\n\n"
            "Then re-run script 01 after a period of production traffic and confirm `idx_scan`\n"
            "is climbing. An index that is still unused after a day of traffic is a failed\n"
            "hypothesis: drop it rather than leaving it to tax every write.\n\n"
            "## Part B -- Validating a proposed index REMOVAL\n\n"
            "### B1. Confirm it is genuinely unused, everywhere\n\n"
            "- `idx_scan = 0` **and** `last_idx_scan IS NULL` (or very old) in script 01.\n"
            "- Verified on the writer **and on every reader** -- reporting queries run there and\n"
            "  their index usage is counted separately.\n"
            "- Instance uptime and `stats_reset` confirm the counters cover a meaningful period.\n"
            "- At least one full business cycle has elapsed, including month-end and\n"
            "  quarter-end reconciliation and any annual audit extract.\n"
            "- It backs no primary key, unique, exclusion, or foreign key constraint.\n\n"
            "### B2. Record the definition before you drop it\n\n"
            "```sql\n"
            "SELECT pg_get_indexdef(i.oid)\n"
            "FROM pg_class i\n"
            "JOIN pg_namespace n ON n.oid = i.relnamespace\n"
            "WHERE n.nspname = 'public' AND i.relname = 'idx_candidate_for_removal';\n"
            "```\n\n"
            "Paste the result into the change record. That one line is the entire rollback plan.\n\n"
            "### B3. Drop it CONCURRENTLY\n\n"
            "```sql\n"
            "-- Avoids the ACCESS EXCLUSIVE lock that a plain DROP INDEX takes.\n"
            "-- Cannot run inside a transaction block.\n"
            "DROP INDEX CONCURRENTLY public.idx_candidate_for_removal;\n"
            "```\n\n"
            "### B4. Watch for the regression\n\n"
            "For the next full business cycle, watch the sequential scan counters on that table\n"
            "(script 05) and the latency of the queries that touched those columns. If something\n"
            "regresses, recreate the index from the definition recorded in B2 using\n"
            "`CREATE INDEX CONCURRENTLY`.\n\n"
            "## Never do this\n\n"
            "- Never `CREATE INDEX` or `DROP INDEX` without `CONCURRENTLY` on a hot exchange\n"
            "  table: both take `ACCESS EXCLUSIVE` and block every read and write for the\n"
            "  duration.\n"
            "- Never drop an index because `idx_scan = 0` on one instance at one point in time.\n"
            "- Never drop a constraint-backing index to save space; drop the constraint if the\n"
            "  constraint is genuinely not needed, which is a different and larger decision.\n"
            "- Never add an index to compensate for a predicate that could simply be rewritten\n"
            "  to be sargable.\n"
        ),
        "Use part A when the evidence points at a missing or badly shaped index, and part B when it points at an index that costs more than it returns. Both parts end with a verification step, and part B's B2 is the non-negotiable one: the recorded definition is the whole rollback plan for an index removal.",
        safety=GUARDED_DDL,
        expected_impact="CREATE INDEX CONCURRENTLY and DROP INDEX CONCURRENTLY take SHARE UPDATE EXCLUSIVE rather than ACCESS EXCLUSIVE, so reads and writes continue, but the build is I/O intensive, takes roughly twice as long as a plain build, and conflicts with vacuum and other DDL on the same table.",
        required_privileges="Table ownership to create or drop an index. pg_monitor is sufficient for the validation steps.",
        prerequisites="Scripts 01-05 completed, the candidate index identified, and for a removal, confirmation across every instance and a full business cycle.",
        execution_location="Writer instance only -- index DDL cannot run on a reader.",
        expected_runtime="Minutes to hours for a concurrent build on a large exchange table.",
        related_scripts="../../tables-and-indexes/unused-indexes/README.md, ../../tables-and-indexes/missing-index-candidates/README.md",
        table_purpose="Guarded runbook for validating an index addition or removal.",
    ),
]

# ---------------------------------------------------------------------------
# query-plan-regression
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="query-plan-regression",
    title="Query Plan Regression",
    summary=(
        "A statement that was fast yesterday is slow today, and its text has not changed. The "
        "plan did. This workflow is built around comparison: it finds statements whose latency "
        "distribution has shifted, enumerates the things that can change a plan without "
        "changing a query (statistics, data volume, index state, configuration, parameter "
        "values, cached generic plans), and provides the runbook for capturing plan baselines "
        "so the next regression is diagnosed by comparison rather than by reconstruction."
    ),
    symptoms=[
        "A specific statement's latency stepped up at an identifiable moment, with no deployment of that code path.",
        "Latency is bimodal: most executions are fast, a minority are dramatically slower.",
        "A statement's mean execution time is stable while its maximum and standard deviation have grown sharply.",
        "Performance degraded immediately after a migration, a bulk load, an index change, a parameter change, or an Aurora failover.",
    ],
    business_impact=[
        "Plan regressions are abrupt rather than gradual: the plan flips and latency changes by an order of magnitude in a single moment, so an exchange can go from healthy to failing order placement without any warning trend.",
        "Because the query text did not change, the deploying team's first instinct is that the database broke, which costs time at exactly the wrong moment unless the evidence is ready.",
        "Regressions on the order-placement, balance-check, and withdrawal paths are immediately user-visible and, during volatility, revenue-affecting.",
    ],
    root_causes=[
        "Statistics changed: an ANALYZE (manual or automatic) updated the planner's picture and it chose differently, for better or worse.",
        "Data volume or distribution crossed a threshold where the planner's cost comparison flipped between two plans.",
        "An index was added, dropped, or left invalid by a failed concurrent build, changing the available access paths.",
        "A configuration change: work_mem, random_page_cost, effective_cache_size, or an enable_* parameter altered in a parameter group.",
        "Parameter-value sensitivity: the same prepared statement is fast for typical values and slow for outliers such as the most liquid trading pair or the largest institutional account.",
        "A cached generic plan being used for a prepared statement where a custom plan would be far better (plan_cache_mode and the five-execution heuristic).",
        "An Aurora failover: the new writer has a cold cache and reset statistics counters, so both plan choice inputs and measured performance change at once.",
        "Table bloat or a physical reorganization altering correlation and therefore the attractiveness of ordered index scans.",
    ],
    investigation_strategy=[
        "Find statements whose latency distribution is widest -- high standard deviation and a maximum far above the mean is the statistical signature of more than one plan.",
        "Check whether planning time itself changed, which points at a different cause than execution-time regression.",
        "Check statistics freshness and recency: an ANALYZE at the regression moment is a prime suspect, in either direction.",
        "Check index state, including indexes left invalid by a failed build, which silently removes an access path.",
        "Check configuration for drift, including parameters that were changed during a previous incident and never reverted.",
        "Compare the current plan against the stored baseline, or establish that baseline now if none exists.",
    ],
    prerequisites=[
        "Role membership in pg_monitor (or pg_read_all_stats).",
        "pg_stat_statements, ideally not reset since before the regression -- an Aurora failover resets it and destroys the comparison.",
        "A stored plan baseline for the affected statement if one exists (from database-health/pre-deployment-check, or from the runbook in this workflow).",
        "The approximate time the regression began, correlated against the deployment, migration, parameter change, and failover timelines.",
    ],
    interpretation_guide=[
        "pg_stat_statements aggregates every execution of a normalized statement since the counters were reset, so a regression halfway through that window shows up as a raised maximum and standard deviation long before the mean moves noticeably. Do not wait for the mean.",
        "A high standard deviation relative to the mean means executions are not homogeneous: either two different plans are in use, or one plan performs very differently for different parameter values.",
        "Correlate the regression's start time with the four change timelines that can move a plan without touching code: deployments and migrations, ANALYZE and autoanalyze activity, index changes, and parameter-group changes. Aurora failovers are the fifth.",
        "A regression immediately after a failover may be a cold cache rather than a plan change at all: the new writer's buffer cache starts empty and warms over minutes to hours. Confirm instance uptime before concluding the plan changed.",
        "If the statement is a prepared statement executed more than five times, PostgreSQL may have switched from custom plans to a cached generic plan. That switch is invisible in pg_stat_statements and is a classic cause of a regression with no external change whatsoever.",
        "An invalid index removes an access path silently: the planner ignores it, the application keeps paying its write cost, and the plan reverts to a sequential scan. Always check for one after any migration.",
    ],
    remediation_immediate=[
        "If the regression started with a deployment and the rollback window is open, roll back first and diagnose afterwards.",
        "If an invalid index is the cause, the access path is currently missing -- plan an immediate concurrent rebuild.",
        "If stale statistics are the cause, a targeted ANALYZE frequently restores the previous plan within seconds.",
    ],
    remediation_short_term=[
        "Rebuild any index left invalid by a failed concurrent build.",
        "Revert an unintended parameter change, or correct statistics for the mis-estimated table.",
        "For a parameter-sensitivity regression, consider forcing custom plans for that statement (plan_cache_mode = force_custom_plan, set at the narrowest possible scope) after confirming with a plan capture that a custom plan is genuinely better.",
    ],
    remediation_long_term=[
        "Capture and store plan baselines for the exchange's critical statements as part of the deployment pipeline, so a regression is a two-minute comparison rather than a multi-hour reconstruction.",
        "Alert on latency distribution (maximum and standard deviation) rather than on mean latency alone, so a bimodal regression is detected while only a minority of executions are affected.",
        "Include production-scale data in pre-production plan validation so volume-threshold flips are found before release.",
    ],
    production_safety=[
        "All .sql scripts here are read-only.",
        "Capturing the current plan for comparison uses plain EXPLAIN, which executes nothing and is safe at any time; EXPLAIN ANALYZE is only needed when estimated-versus-actual row counts are required, and is guarded accordingly. " + EXPLAIN_ANALYZE_WARNING,
        "Never disable a plan type (enable_nestloop, enable_hashjoin) as a production remedy for a regression: it is a diagnostic tool, and a cluster-wide setting distorts every other statement.",
    ],
    escalation_criteria=[
        "A regression affects order placement, balance checks, withdrawals, or settlement -- escalate immediately and evaluate rollback in parallel with diagnosis.",
        "pg_stat_statements was reset (typically by a failover) and no stored baseline exists, so the regression cannot be confirmed from database evidence -- escalate to reconstruct it from application-side latency metrics.",
        "The plan reverts to the bad shape after every remediation, indicating a deeper estimation problem -- escalate to cardinality-estimation.",
    ],
    related_issues=[
        "../analyze-query-plan/README.md",
        "../stale-statistics/README.md",
        "../cardinality-estimation/README.md",
        "../inefficient-index-usage/README.md",
        "../../performance/query-regression/README.md",
        "../../performance/performance-after-deployment/README.md",
        "../../database-health/post-deployment-check/README.md",
    ],
    aurora_notes=[
        "An Aurora failover resets pg_stat_statements, pg_stat_database, and every other in-memory statistics view on the promoted instance. A regression investigation that starts after a failover has no history to compare against unless a baseline was persisted beforehand.",
        "The promoted writer also starts with a cold buffer cache, so the first minutes after a failover show elevated latency that is not a plan regression at all. Check instance uptime before diagnosing anything else.",
        "Planner statistics are catalog data on the shared cluster volume and do survive a failover, so the plan itself should not change across one -- which is a useful discriminator between a genuine plan regression and a cache-warming effect.",
        "Parameter-group changes are applied cluster-wide and some require a reboot; a parameter that was changed days ago may only have taken effect at the reboot, making the regression's start time correlate with the reboot rather than with the change.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_latency_distribution_by_statement",
        "Finds statements whose execution time distribution is widest, the statistical signature of a plan change.",
        _pgss_guarded("""
-- Latency distribution per statement. A regression that began partway
-- through the statistics window barely moves the mean, but it moves the
-- maximum and the standard deviation immediately -- which is why those,
-- not the mean, are the right regression detectors.
--
-- coefficient_of_variation (stddev / mean) normalizes the spread so
-- statements of very different absolute speeds can be compared directly.
-- A value well above 1 means executions are not homogeneous: either two
-- plans are in use, or one plan behaves very differently across parameter
-- values.
\\set top_n 25
\\set min_calls 50
SELECT
    queryid,
    calls,
    round(min_exec_time::numeric, 3)                              AS min_exec_time_ms,
    round(mean_exec_time::numeric, 3)                             AS mean_exec_time_ms,
    round(max_exec_time::numeric, 3)                              AS max_exec_time_ms,
    round(stddev_exec_time::numeric, 3)                           AS stddev_exec_time_ms,
    round(
        stddev_exec_time::numeric / NULLIF(mean_exec_time::numeric, 0), 2
    )                                                             AS coefficient_of_variation,
    round(
        max_exec_time::numeric / NULLIF(mean_exec_time::numeric, 0), 1
    )                                                             AS max_to_mean_ratio,
    rows,
    shared_blks_read,
    temp_blks_written,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND calls >= :min_calls
ORDER BY stddev_exec_time DESC
LIMIT :top_n;
""".strip("\n")),
        "A coefficient_of_variation above 1 combined with a max_to_mean_ratio in the tens is the clearest available evidence of more than one plan for the same statement. On an exchange, check the order-placement and balance-lookup statements here first regardless of their ranking. Remember these are aggregates over the whole window since stats_reset: a regression that started an hour ago inside a week-long window will look mild here and severe in the application's own latency metrics, and the application metrics are the more accurate view of now.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="02_planning_time_check.sql",
        table_purpose="Latency distribution and variance per statement.",
    ),
    sql_script(
        "02", "02_planning_time_check",
        "Checks whether the regression is in planning time rather than execution time.",
        _pgss_guarded("""
-- Planning versus execution time. A regression in PLANNING time has
-- entirely different causes from one in execution time: more partitions to
-- consider, a higher join_collapse_limit, many more indexes to evaluate,
-- or a switch away from generic plans for a prepared statement.
--
-- These columns are only populated when pg_stat_statements.track_planning
-- is on, which is off by default. All-zero plan times mean "not tracked",
-- not "planning is free".
\\set top_n 25
SELECT
    queryid,
    calls,
    round(total_plan_time::numeric, 2)                            AS total_plan_time_ms,
    round(mean_plan_time::numeric, 4)                             AS mean_plan_time_ms,
    round(mean_exec_time::numeric, 4)                             AS mean_exec_time_ms,
    round(
        (100.0 * total_plan_time / NULLIF(total_plan_time + total_exec_time, 0))::numeric, 2
    )                                                             AS pct_time_spent_planning,
    left(query, 200)                                              AS query_snippet
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_plan_time DESC NULLS LAST
LIMIT :top_n;

-- Settings that govern planning cost and generic-plan behaviour.
SELECT
    name,
    setting,
    source,
    short_desc
FROM pg_settings
WHERE name IN (
    'pg_stat_statements.track_planning',
    'pg_stat_statements.track',
    'plan_cache_mode',
    'join_collapse_limit',
    'from_collapse_limit',
    'geqo_threshold'
)
ORDER BY name;
""".strip("\n")),
        "If planning time is being tracked and has grown, look for structural causes rather than data causes: a partitioned table that has accumulated many partitions, an index count that has grown on a heavily queried table, or a join_collapse_limit change. Note plan_cache_mode: on the default auto setting, PostgreSQL switches a prepared statement to a cached generic plan after five executions when it looks safe, and that switch is one of the few regressions that leaves no trace anywhere except in the latency itself.",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=PGSS_PREREQ,
        related_scripts="03_statistics_change_check.sql",
        table_purpose="Planning time and generic-plan configuration.",
    ),
    sql_script(
        "03", "03_statistics_change_check",
        "Checks when statistics were last refreshed on the tables involved, in both directions.",
        sb.statistics_freshness(),
        "Correlate last_analyze and last_autoanalyze against the moment the regression began. An ANALYZE at that moment is a prime suspect in both directions: statistics that went stale and produced a bad plan, or statistics that were refreshed and caused the planner to switch away from a plan that happened to be working well. The second case is uncomfortable but real -- the fix is then to make the estimate good enough that the planner chooses well with accurate statistics, never to leave statistics deliberately stale.",
        related_scripts="04_index_state_check.sql, ../stale-statistics/README.md",
        table_purpose="Statistics refresh timing on the involved tables.",
    ),
    sql_script(
        "04", "04_index_state_check",
        "Checks whether an index change or an invalid index removed the access path the plan relied on.",
        sb.invalid_indexes() + "\n\n" + sb.index_bloat_and_usage(),
        "An invalid index is the single most common structural cause of a post-migration plan regression: the planner ignores it completely, so the plan silently reverts to a sequential scan while the application keeps paying its write cost. In the usage inventory, look for an index whose idx_scan has stopped advancing since the regression began -- that is the access path the plan abandoned, and it tells you which alternative the planner is now preferring.",
        expected_runtime="Low to moderate (seconds; scales with the number of indexes).",
        related_scripts="05_configuration_drift_check.sql, ../../tables-and-indexes/invalid-indexes/README.md",
        table_purpose="Invalid indexes and index usage state.",
    ),
    sql_script(
        "05", "05_configuration_drift_check",
        "Checks planner and memory configuration for drift that could have changed the plan.",
        _planner_settings() + "\n\n" + sb.key_settings_snapshot(),
        "Focus on three things. Any enable_* parameter set to off -- these are diagnostic switches and a forgotten one from a past incident will distort plans indefinitely. The source column: a value that came from a session-level SET means the application is overriding the parameter group at connection time, so the plan depends on which application connects. And pending_restart being true means a parameter-group change has been made but is not yet active, so the regression may correlate with a later reboot or failover rather than with the change itself.",
        required_privileges=PG_MONITOR,
        related_scripts="06_plan_baseline_comparison.md",
        table_purpose="Planner and memory configuration drift check.",
    ),
    md_script(
        "06", "06_plan_baseline_comparison",
        "Guarded runbook for comparing the current plan against a stored baseline, and for creating baselines when none exist.",
        (
            "## If you have a baseline\n\n"
            "### Step 1 -- Capture the current plan, for free\n\n"
            "```sql\n"
            "EXPLAIN (COSTS OFF, FORMAT TEXT)\n"
            "SELECT ... ;                      -- the regressed statement, real parameters\n"
            "```\n\n"
            "`COSTS OFF` strips the cost numbers and leaves the plan **shape**, which is what you\n"
            "want for a diff: shapes are stable across data growth, costs are not. Nothing is\n"
            "executed.\n\n"
            "Diff it against the stored baseline. The differences to look for, in order of how\n"
            "often they explain a regression:\n\n"
            "1. A join strategy changed (`Hash Join` became `Nested Loop`, or the reverse).\n"
            "2. An access path changed (`Index Scan` became `Seq Scan`).\n"
            "3. The join order changed.\n"
            "4. A `Sort` or `Materialize` node appeared where there was none.\n"
            "5. Parallelism appeared or disappeared (`Gather` nodes).\n\n"
            "### Step 2 -- Only if the shape diff is not conclusive\n\n"
            "```sql\n"
            "SET LOCAL statement_timeout = '20s';\n"
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "This executes the statement. Use it when you need estimated-versus-actual row\n"
            "counts to explain *why* the shape changed, not merely to observe *that* it changed.\n"
            "Prefer a reader; wrap any write statement in `BEGIN ... ROLLBACK`.\n\n"
            "## If you do not have a baseline\n\n"
            "You cannot prove a regression from the database alone -- pg_stat_statements gives\n"
            "you aggregates, not history, and an Aurora failover may have reset even those. Do\n"
            "two things:\n\n"
            "1. Use the application's own latency metrics as the before picture, and this\n"
            "   workflow's scripts 03, 04, and 05 to identify what changed around that moment.\n"
            "2. **Create the baseline now**, so the next occurrence is a two-minute comparison.\n\n"
            "## Creating plan baselines\n\n"
            "For each of the exchange's critical statements -- order placement, order\n"
            "cancellation, balance lookup, trade history, withdrawal processing, settlement\n"
            "batch -- capture and store:\n\n"
            "```sql\n"
            "EXPLAIN (COSTS OFF, FORMAT TEXT)\n"
            "SELECT ... ;\n"
            "```\n\n"
            "Store alongside it: the `queryid` from pg_stat_statements, the exact parameter\n"
            "values used, the instance and cluster the capture came from, the timestamp, the\n"
            "engine version, and the current `mean_exec_time` and `calls`. Keep it in version\n"
            "control next to the application code that issues the statement, so the baseline is\n"
            "reviewed whenever the query is changed.\n\n"
            "Capture baselines at three moments: as part of\n"
            "`database-health/pre-deployment-check`, after any significant data growth\n"
            "milestone, and after any deliberate planner parameter change.\n\n"
            "## Applying the remediation\n\n"
            "| Diff finding | Likely cause | Remediation |\n"
            "|---|---|---|\n"
            "| `Index Scan` became `Seq Scan` | Index invalid or dropped, or statistics changed | Rebuild the index `CONCURRENTLY`, or targeted `ANALYZE` |\n"
            "| `Hash Join` became `Nested Loop` | Outer-side estimate collapsed | Targeted `ANALYZE`, then extended statistics if it persists |\n"
            "| New `Sort` node appeared | Ordering index dropped or no longer chosen | Restore or extend the index |\n"
            "| Shape identical, timings worse | Not a plan regression | Cold cache after failover, bloat, or resource contention -- see `performance/` |\n"
            "| Fast for some parameters, slow for others | Generic plan for a prepared statement | Confirm with a capture, then consider `plan_cache_mode = force_custom_plan` at the narrowest scope |\n\n"
            "## Never do this\n\n"
            "- Do not set `enable_nestloop = off` (or any other plan-type switch) in the Aurora\n"
            "  parameter group to force the old plan back. It is diagnostic only.\n"
            "- Do not leave statistics deliberately stale because the old plan was better with\n"
            "  stale statistics. Fix the estimate instead.\n"
            "- Do not conclude a plan regression from timings alone after a failover: check\n"
            "  instance uptime first, because a cold cache looks identical from the outside.\n"
        ),
        "The plan-shape diff from step 1 is the deliverable and costs nothing to obtain; execute the statement only when you need actual row counts to explain the shape change. If no baseline exists, treat creating one for the exchange's critical statements as the primary output of this investigation -- it is what converts the next regression from an archaeology exercise into a comparison.",
        safety=GUARDED_DDL,
        expected_impact="Step 1 and baseline capture: none, EXPLAIN does not execute the statement. Step 2: a full execution of the statement, bounded by statement_timeout.",
        required_privileges="The same privileges the statement under investigation requires.",
        prerequisites="Scripts 01-05 completed, the regressed statement identified with representative parameters, and the stored baseline retrieved if one exists.",
        execution_location="Reader instance preferred for read-only statements.",
        expected_runtime="Step 1: milliseconds. Step 2: up to the configured statement_timeout.",
        related_scripts="../analyze-query-plan/README.md, ../../database-health/pre-deployment-check/README.md",
        table_purpose="Guarded runbook for plan baseline comparison and creation.",
    ),
]

