"""Workflow definitions: tables-and-indexes/ category (10 issue directories)."""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import PG_MONITOR, md_script, sql_script
from .model import Workflow

CATEGORY_SLUG = "tables-and-indexes"
CATEGORY_TITLE = "Table and Index Health"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

WORKFLOWS.append(_wf(
    slug="unused-indexes",
    title="Unused Indexes",
    summary="Identifies indexes that appear to receive zero or negligible scans, representing pure write-amplification and storage cost with no measured query benefit -- while explicitly guarding against premature removal.",
    symptoms=["Elevated write latency/WAL volume on tables with many indexes.", "Storage growth attributable to index size rather than table size."],
    business_impact=["Every index adds overhead to every INSERT/UPDATE/DELETE on its table; an unused index is pure cost on the hottest part of the workload (writes) for zero benefit."],
    root_causes=["An index created for a query pattern that was later removed/changed in application code.", "A speculative index added 'just in case' that never proved necessary.", "An index that only supports a rare (e.g. quarterly reporting) query and looks unused within a short observation window."],
    investigation_strategy=["List candidate unused indexes (idx_scan = 0), excluding those backing a constraint.", "Cross-check stats_reset / instance uptime to ensure the observation window is long enough to be meaningful (must span at least one full business cycle).", "Confirm with the owning application team before dropping anything."],
    prerequisites=["pg_monitor role membership.", "Confidence that no failover/restart has reset statistics recently (which would make idx_scan = 0 look artificially alarming)."],
    interpretation_guide=["idx_scan = 0 since the last stats reset is necessary but NOT sufficient evidence to drop an index -- always check stats_reset age and confirm the query pattern that would use this index truly no longer exists (including rare batch/reporting jobs)."],
    remediation_immediate=["None -- index removal is always a planned, reviewed action."],
    remediation_short_term=["For a confirmed-unused, non-constraint-backing index, drop it with `DROP INDEX CONCURRENTLY` (see schema-changes/drop-index-safely) during a low-traffic window, keeping the index definition saved in case it needs to be recreated."],
    remediation_long_term=["Add a periodic (e.g. quarterly) unused-index review to standing operational practice (see automation/index-monitoring) rather than a one-off cleanup."],
    production_safety=["The investigation script is read-only.", "Never drop an index the same day it is found 'unused' without confirming the observation window is long enough and the owning team has been consulted."],
    escalation_criteria=["An index appears unused but is suspected to back a rare, business-critical batch/compliance job -- escalate to the owning team before any action."],
    related_issues=["../duplicate-indexes/README.md", "../../schema-changes/drop-index-safely/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_unused_index_candidates", "Lists candidate unused indexes, excluding those backing a constraint.",
               sb.unused_indexes(),
               "Cross-check the instance's stats_reset/uptime before treating any result as conclusive; a recently restarted/failed-over instance will show idx_scan = 0 for everything.",
               related_scripts="../../schema-changes/drop-index-safely/README.md"),
]

WORKFLOWS.append(_wf(
    slug="duplicate-indexes",
    title="Duplicate Indexes",
    summary="Identifies structurally identical or fully redundant indexes on the same table -- pure waste with no tradeoff, unlike unused-indexes which requires judgment about rare query patterns.",
    symptoms=["Two or more indexes on the same table with the same columns/expressions/predicate."],
    business_impact=["Duplicate indexes are unambiguous waste: every one adds write overhead and storage without any additional query benefit over its twin."],
    root_causes=["An ORM or migration tool creating an index that already existed manually.", "A renamed/recreated index left alongside its original instead of replacing it.", "Independent teams adding the same index unaware of each other's prior work."],
    investigation_strategy=["Find indexes with matching normalized definitions on the same table.", "Confirm neither is required for a differently-named constraint before dropping either."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["Unlike unused-indexes, true structural duplicates provide no scenario where keeping both is beneficial -- the only decision is which one to keep (usually the one with the more descriptive name, or the one backing a constraint)."],
    remediation_immediate=["None -- always a planned, reviewed action."],
    remediation_short_term=["Drop the redundant duplicate using `DROP INDEX CONCURRENTLY` (see schema-changes/drop-index-safely), keeping only one copy."],
    remediation_long_term=["Add a duplicate-index check to CI/migration review to prevent recurrence."],
    production_safety=["Investigation script is read-only; drop guidance follows schema-changes/drop-index-safely's safety practices."],
    escalation_criteria=["None typical -- this is usually a low-risk, straightforward cleanup once confirmed."],
    related_issues=["../unused-indexes/README.md", "../../schema-changes/drop-index-safely/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_duplicate_indexes", "Finds indexes with identical normalized definitions on the same table.",
               sb.duplicate_indexes(),
               "Prefer keeping the index backing a constraint (if any) or the one with the clearer name; drop the other via DROP INDEX CONCURRENTLY.",
               related_scripts="../../schema-changes/drop-index-safely/README.md"),
]

WORKFLOWS.append(_wf(
    slug="missing-index-candidates",
    title="Missing Index Candidates",
    summary="Identifies tables/query patterns that would likely benefit from a new index -- unindexed foreign keys, and tables with heavy sequential scans relative to their size.",
    symptoms=["Queries filtering/joining on a column with no supporting index, visible as high seq_scan/seq_tup_read in pg_stat_all_tables.", "UPDATE/DELETE on a parent row taking noticeably long due to an unindexed FK on the child table."],
    business_impact=["A missing index on a hot query path is one of the most common and highest-leverage fixes for both high-cpu and slow-queries incidents."],
    root_causes=["A new query pattern shipped without an accompanying index.", "A foreign key added without a supporting index on the referencing column(s).", "Data growth crossed the threshold where a sequential scan is no longer efficient for a previously-fine query."],
    investigation_strategy=["Check for unindexed foreign keys.", "Check for sequential-scan-heavy tables.", "Confirm against actual query patterns (pg_stat_statements) before adding an index speculatively."],
    prerequisites=["pg_stat_statements recommended for confirming the query pattern."],
    interpretation_guide=["Add indexes based on confirmed query patterns, not just theoretical schema analysis -- an unindexed FK that is never used in a JOIN/lookup direction may not need an index despite appearing in this report."],
    remediation_immediate=["None -- always add indexes deliberately, never as an emergency same-incident action unless directly resolving an active severe incident with full understanding of the tradeoffs."],
    remediation_short_term=["Add the identified index using `CREATE INDEX CONCURRENTLY` (see schema-changes/concurrent-index-build)."],
    remediation_long_term=["Add FK-index-coverage and query-pattern review to the standard schema/migration review checklist."],
    production_safety=["Investigation scripts are read-only; index creation must always use CONCURRENTLY per schema-changes guidance."],
    escalation_criteria=["A confirmed missing index is on an extremely large, hot table where even a CONCURRENTLY build carries meaningful resource-consumption risk -- coordinate a build window with the owning team."],
    related_issues=["../sequential-scan-investigation/README.md", "../../schema-changes/concurrent-index-build/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_unindexed_foreign_keys", "Finds foreign key constraints with no supporting index on the referencing (child) columns.",
               sb.foreign_keys_missing_index(),
               "Every result here is a near-certain candidate for a supporting index, since unindexed FKs cause sequential scans on the child table for every parent-row UPDATE/DELETE.",
               related_scripts="02_sequential_scan_heavy_tables.sql"),
    sql_script("02", "02_sequential_scan_heavy_tables", "Finds large tables with a high sequential-scan-to-row-read ratio, a proxy for a missing index on a filter/join column.",
               sb.sequential_scan_heavy_tables(),
               "Cross-reference against pg_stat_statements query text for these tables to identify the specific column(s) driving the scans before adding an index.",
               related_scripts="../../schema-changes/concurrent-index-build/README.md"),
]

WORKFLOWS.append(_wf(
    slug="sequential-scan-investigation",
    title="Sequential Scan Investigation",
    summary="Deep-dive investigation into why a specific table or query is using a sequential scan instead of an expected index scan.",
    symptoms=["A specific query's EXPLAIN plan shows Seq Scan on a large table where an Index Scan was expected."],
    business_impact=["An unexpected sequential scan on a large hot table is a direct, often severe, latency and CPU/IO cost."],
    root_causes=["No index exists for the query's predicate.", "An index exists but the planner chose not to use it (poor selectivity estimate from stale statistics, or the predicate uses a function/cast the index cannot support).", "The table is small enough that the planner correctly judges a sequential scan cheaper (not actually a problem)."],
    investigation_strategy=["Confirm table size -- a seq scan on a genuinely small table is expected and fine.", "Check for an existing, usable index matching the query's predicate.", "Check statistics freshness, since stale stats can cause the planner to misjudge selectivity and skip a usable index.", "Obtain EXPLAIN to see the planner's actual reasoning/estimates."],
    prerequisites=["Query text/plan for the specific case under investigation."],
    interpretation_guide=["A sequential scan on a table under a few thousand rows (or a few MB) is frequently the CORRECT and fastest plan -- do not chase 'seq_scan > 0' as inherently bad; focus on large tables where the ratio of rows read to rows returned is poor."],
    remediation_immediate=["None -- diagnose before acting."],
    remediation_short_term=["Add a targeted index if none exists and the table/row-selectivity justifies one; refresh statistics if staleness is the cause."],
    remediation_long_term=["See missing-index-candidates for the broader, table-wide review."],
    production_safety=["Investigation is read-only; EXPLAIN (without ANALYZE) never executes the query."],
    escalation_criteria=["The planner ignores an existing, seemingly-appropriate index even with fresh statistics -- escalate to query-optimization/analyze-query-plan for a deeper plan-level investigation."],
    related_issues=["../missing-index-candidates/README.md", "../../query-optimization/analyze-query-plan/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_sequential_scan_heavy_tables", "Confirms which tables are experiencing the most sequential-scan read volume.",
               sb.sequential_scan_heavy_tables(),
               "Focus only on tables large enough (check table_size) that a seq scan is genuinely costly -- small tables in this list are not a concern.",
               related_scripts="02_statistics_freshness.sql"),
    sql_script("02", "02_statistics_freshness", "Checks whether stale statistics could be causing the planner to misjudge selectivity and avoid an existing index.",
               sb.statistics_freshness(),
               "If statistics are stale, run a targeted ANALYZE and re-check the query's plan before concluding an index is actually missing.",
               related_scripts="../../vacuum-and-autovacuum/analyze-statistics/README.md"),
]

WORKFLOWS.append(_wf(
    slug="index-bloat",
    title="Index Bloat (Tables-and-Indexes View)",
    summary="Table/index-health-focused entry point for index bloat investigation; see vacuum-and-autovacuum/index-bloat for the vacuum-lifecycle perspective on the same underlying issue.",
    symptoms=["Index size disproportionate to table row count.", "Index scan latency degrading over time."],
    business_impact=["Bloated indexes on hot lookup paths directly increase the latency of the most frequent queries."],
    root_causes=["High UPDATE churn on indexed columns without full space reclamation.", "See vacuum-and-autovacuum/index-bloat for the complete root-cause list."],
    investigation_strategy=["Rank indexes by size and usage.", "Confirm bloat with pgstattuple if a precise figure is needed.", "Plan a REINDEX CONCURRENTLY if confirmed."],
    prerequisites=["pg_monitor role membership; pgstattuple optional for exact confirmation."],
    interpretation_guide=["See vacuum-and-autovacuum/index-bloat's interpretation guidance -- this workflow exists as the tables-and-indexes-category entry point to the same investigation for discoverability."],
    remediation_immediate=["None -- planned action."],
    remediation_short_term=["REINDEX INDEX CONCURRENTLY during a lower-traffic window."],
    remediation_long_term=["See vacuum-and-autovacuum/autovacuum-not-keeping-up for the systemic prevention angle."],
    production_safety=["Investigation is read-only; REINDEX CONCURRENTLY guidance is in schema-changes/concurrent-index-build."],
    escalation_criteria=["Same as vacuum-and-autovacuum/index-bloat."],
    related_issues=["../../vacuum-and-autovacuum/index-bloat/README.md", "../../schema-changes/concurrent-index-build/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_index_bloat_and_usage", "Index size and usage statistics to identify large, potentially bloated indexes.",
               sb.index_bloat_and_usage(),
               "Cross-reference with vacuum-and-autovacuum/index-bloat for the exact pgstattuple confirmation script and REINDEX CONCURRENTLY guidance.",
               related_scripts="../../vacuum-and-autovacuum/index-bloat/scripts/01_index_bloat_and_usage.sql"),
]

WORKFLOWS.append(_wf(
    slug="table-bloat",
    title="Table Bloat (Tables-and-Indexes View)",
    summary="Table/index-health-focused entry point for table bloat investigation; see vacuum-and-autovacuum/table-bloat for the vacuum-lifecycle perspective on the same underlying issue.",
    symptoms=["Table on-disk size much larger than expected for its live row count."],
    business_impact=["Bloat increases storage cost and the number of pages scanned per query."],
    root_causes=["See vacuum-and-autovacuum/table-bloat for the complete root-cause list."],
    investigation_strategy=["Estimate bloat via the catalog-only proxy.", "Confirm with pgstattuple for top candidates.", "Plan remediation per vacuum-and-autovacuum/table-bloat / maintenance/."],
    prerequisites=["pgstattuple optional for exact confirmation."],
    interpretation_guide=["See vacuum-and-autovacuum/table-bloat's interpretation guidance."],
    remediation_immediate=["None -- planned action."],
    remediation_short_term=["Confirm autovacuum is keeping pace (autovacuum-not-keeping-up) before considering a space-reclaiming operation."],
    remediation_long_term=["Schedule a maintenance-window VACUUM FULL/pg_repack if confirmed severe (see maintenance/)."],
    production_safety=["Investigation is read-only; pgstattuple's exact scan can be I/O intensive on very large tables."],
    escalation_criteria=["Same as vacuum-and-autovacuum/table-bloat."],
    related_issues=["../../vacuum-and-autovacuum/table-bloat/README.md", "../../maintenance/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_bloat_estimate_catalog_only", "Lightweight, lock-free bloat proxy.",
               sb.table_bloat_estimate(),
               "Use to triage which tables merit the exact pgstattuple confirmation in script 02.",
               related_scripts="02_exact_bloat_pgstattuple.sql"),
    sql_script("02", "02_exact_bloat_pgstattuple", "Exact physical bloat scan for one specific table.",
               sb.pgstattuple_exact_bloat(),
               "free_pct + dead_tuple_pct above 30-40% on a large table is a strong candidate for a scheduled space-reclaiming operation.",
               safety="READ ONLY (may be resource intensive on very large tables -- see EXPECTED IMPACT)",
               expected_impact="Full or sampled table scan; can be I/O-intensive on very large tables.",
               prerequisites="pgstattuple extension must be created in the current database.",
               related_scripts="../../maintenance/README.md"),
]

WORKFLOWS.append(_wf(
    slug="invalid-indexes",
    title="Invalid Indexes",
    summary="Finds indexes left in an INVALID state after a failed CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY -- unused by the planner, but still consuming storage and write overhead until removed and, if needed, rebuilt.",
    symptoms=["A recent plan regression on a table where a CONCURRENTLY index build was recently attempted.", "Unexplained storage growth from an index providing no query benefit."],
    business_impact=["An invalid index provides zero planner benefit while still paying its full write-overhead and storage cost -- and its presence often directly explains a co-occurring plan regression (see performance/query-regression)."],
    root_causes=["A CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY was interrupted (killed session, statement_timeout, deadlock) partway through."],
    investigation_strategy=["List all invalid indexes.", "Drop each (a normal, fast DROP INDEX is safe since an invalid index is never in use) and rebuild with CONCURRENTLY if the index is still needed."],
    prerequisites=["DDL privileges to drop/rebuild."],
    interpretation_guide=["Any result here is unambiguous -- an invalid index has zero query benefit and should either be dropped (if no longer needed) or rebuilt (if still needed), not left in place."],
    remediation_immediate=["Drop the invalid index if identified as the cause of an active plan regression, then immediately rebuild with CONCURRENTLY if it is still needed."],
    remediation_short_term=["Audit recent CONCURRENTLY build failures to understand why they were interrupted (a too-aggressive statement_timeout on the migration role is a common cause)."],
    remediation_long_term=["Add a post-migration automated check for invalid indexes to deployment pipelines (see database-health/post-deployment-check)."],
    production_safety=["Dropping an invalid index is safe and low-risk (it is never used by the planner). Rebuilding uses CREATE INDEX CONCURRENTLY per schema-changes guidance."],
    escalation_criteria=["None typical -- straightforward once found, though the underlying cause of the failed build should still be investigated."],
    related_issues=["../../performance/query-regression/README.md", "../../schema-changes/failed-index-build/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_invalid_indexes", "Lists all indexes currently in an INVALID state.",
               sb.invalid_indexes(),
               "Any result is actionable: drop it, and rebuild with CREATE INDEX CONCURRENTLY if still needed.",
               related_scripts="../../schema-changes/failed-index-build/README.md"),
]

WORKFLOWS.append(_wf(
    slug="large-tables",
    title="Large Tables Inventory",
    summary="Routine inventory of the largest tables/indexes in the database, used as a starting point for capacity planning, partitioning, and archiving decisions.",
    symptoms=["No specific symptom -- routine inventory/health-check workflow."],
    business_impact=["Knowing which tables are largest (and growing fastest) focuses capacity, partitioning, and archiving effort where it matters most."],
    root_causes=["N/A."],
    investigation_strategy=["List largest tables and indexes by total size.", "Cross-reference against partitioning-and-archival candidacy workflows for the biggest entries."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["Rank by total_size (heap + indexes + TOAST), not just heap size, for an accurate capacity picture."],
    remediation_immediate=["N/A."],
    remediation_short_term=["N/A."],
    remediation_long_term=["Feed this inventory into storage-and-capacity/capacity-forecasting on a recurring basis."],
    production_safety=["Read-only."],
    escalation_criteria=["N/A."],
    related_issues=["../rapidly-growing-tables/README.md", "../../storage-and-capacity/capacity-forecasting/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_largest_tables", "Lists the largest tables by total size.",
               sb.largest_tables(),
               "The top entries here are your primary candidates for partitioning/archiving investigation.",
               related_scripts="02_largest_indexes.sql"),
    sql_script("02", "02_largest_indexes", "Lists the largest indexes by size.",
               sb.largest_indexes(),
               "A very large index relative to its table's size may indicate bloat (see index-bloat) rather than genuinely large data volume.",
               related_scripts="../rapidly-growing-tables/README.md"),
]

WORKFLOWS.append(_wf(
    slug="rapidly-growing-tables",
    title="Rapidly Growing Tables",
    summary="Identifies which tables are growing fastest (not just which are currently largest), the more actionable signal for proactive capacity planning, partitioning, and archiving prioritization.",
    symptoms=["Overall database storage growth trend exceeds expectations.", "A specific table's size has doubled within an unexpectedly short window."],
    business_impact=["A rapidly growing table will become tomorrow's largest-table problem; catching growth rate early gives more lead time for a partitioning/archiving decision than waiting until it is already enormous."],
    root_causes=["Organic business growth (more users, more trades).", "A new feature writing at a much higher rate than anticipated.", "A missing archiving/retention mechanism allowing indefinite accumulation."],
    investigation_strategy=["Requires historical snapshots (see automation/growth-monitoring) to compute a genuine growth rate, not just a single point-in-time size.", "Compare growth rate against the largest-tables inventory to prioritize."],
    prerequisites=["A historical size-tracking table populated by automation/growth-monitoring; without it, this workflow can only establish current state, not a rate."],
    interpretation_guide=["A small table growing 10x/month is a more urgent long-term concern than a huge table growing 1%/month, even though the huge table is 'larger' today."],
    remediation_immediate=["N/A."],
    remediation_short_term=["Flag rapidly growing tables for investigate-partitioning-candidate / investigate-archiving-candidate assessment."],
    remediation_long_term=["Ensure automation/growth-monitoring is actively populating historical snapshots so this workflow remains usable over time."],
    production_safety=["Read-only."],
    escalation_criteria=["A core financial table's growth rate significantly exceeds the capacity plan's assumptions -- escalate to capacity planning/database engineering leadership."],
    related_issues=["../large-tables/README.md", "../../automation/growth-monitoring/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_growth_rate_from_history", "Computes growth over a lookback window using a historical size-tracking table populated by automation/growth-monitoring.",
               sb.table_growth_rate_from_snapshot(),
               "Requires automation/growth-monitoring's collector to already be populating dba_toolkit.table_size_history; without history, fall back to large-tables for a current-state-only view.",
               related_scripts="../../automation/growth-monitoring/README.md"),
]

WORKFLOWS.append(_wf(
    slug="table-access-patterns",
    title="Table Access Pattern Analysis",
    summary="Characterizes how a table is actually accessed (read-heavy vs write-heavy, sequential vs index-driven, hot vs cold) to inform indexing, partitioning, and caching decisions.",
    symptoms=["Uncertainty about whether a table is a good candidate for a specific optimization (index, partition, cache) without first understanding its actual access pattern."],
    business_impact=["Optimizing a table without understanding its real access pattern risks solving the wrong problem (e.g. adding an index to a write-heavy table with few reads, adding write overhead for no benefit)."],
    root_causes=["N/A -- diagnostic/characterization workflow."],
    investigation_strategy=["Compare read (seq_scan + idx_scan) vs write (n_tup_ins/upd/del) volume.", "Compare index scan vs sequential scan ratio.", "Cross-reference with pg_stat_statements for the specific query shapes touching the table."],
    prerequisites=["pg_stat_statements recommended."],
    interpretation_guide=["A table with n_tup_upd/n_tup_ins far exceeding idx_scan+seq_scan is write-dominated -- index additions should be weighed carefully against their write-amplification cost. A table with the reverse ratio is read-dominated and a better candidate for additional indexing."],
    remediation_immediate=["N/A."],
    remediation_short_term=["Route the finding into the appropriate specific workflow (missing-index-candidates for read-heavy tables needing better index coverage, vacuum-and-autovacuum for write-heavy tables needing more aggressive vacuum tuning)."],
    remediation_long_term=["Document known access patterns for the platform's core tables (orders, balances, ledger) as living architecture documentation."],
    production_safety=["Read-only."],
    escalation_criteria=["N/A."],
    related_issues=["../missing-index-candidates/README.md", "../../vacuum-and-autovacuum/autovacuum-not-keeping-up/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_read_write_ratio", "Compares read activity (scans) against write activity (inserts/updates/deletes) per table.",
               """
-- Read vs. write activity ratio per table, to characterize its access
-- pattern for indexing/partitioning/caching decisions.
SELECT
    schemaname                                                  AS schema_name,
    relname                                                     AS table_name,
    seq_scan + idx_scan                                          AS total_reads,
    n_tup_ins + n_tup_upd + n_tup_del                             AS total_writes,
    round(
        (seq_scan + idx_scan)::numeric /
        NULLIF(n_tup_ins + n_tup_upd + n_tup_del, 0),
        2
    )                                                            AS read_write_ratio
FROM pg_stat_all_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY (seq_scan + idx_scan) + (n_tup_ins + n_tup_upd + n_tup_del) DESC
LIMIT 30;
""".strip("\n"),
               "A read_write_ratio well above 1 indicates a read-dominated table (a good indexing candidate); well below 1 indicates a write-dominated table (prioritize vacuum tuning and be cautious about adding write-amplifying indexes).",
               related_scripts="../missing-index-candidates/README.md"),
]
