"""Workflow definitions: partitioning/ category (7 issue directories).

partition-existing-large-table is the flagship, most comprehensive workflow
in this category per the specification: a realistic, multi-step migration
runbook for partitioning an existing large production table, not a naive
single ALTER TABLE ... PARTITION BY.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import PG_MONITOR, md_script, sql_script
from .model import Workflow

CATEGORY_SLUG = "partitioning"
CATEGORY_TITLE = "Partitioning"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

WORKFLOWS.append(_wf(
    slug="investigate-partitioning-candidate",
    title="Investigating a Partitioning Candidate",
    summary="Determines whether a given table is actually a good candidate for partitioning before committing to the significant engineering effort of partition-existing-large-table.",
    symptoms=["A table has grown large enough that vacuum, backup, or query performance concerns are being raised.", "A table has an obvious time-based or range-based access pattern (append-mostly, queries scoped to recent data)."],
    business_impact=["Partitioning is a significant, higher-risk migration -- investing the effort without confirming a genuine access-pattern fit wastes engineering time and introduces unnecessary risk."],
    root_causes=["N/A -- this is a feasibility assessment workflow, not an incident investigation."],
    investigation_strategy=["Check table size and growth trend.", "Check whether queries are naturally scoped by a candidate partition key (date range, tenant id, status) via pg_stat_statements query text review.", "Check current constraint/index/FK complexity, since that determines migration difficulty.", "Check whether the access pattern favors range, list, or hash partitioning."],
    prerequisites=["pg_stat_statements for query-pattern review.", "pg_monitor role membership."],
    interpretation_guide=["The best partitioning candidates are large (multi-GB+), append-heavy or time-series-like, and queried predominantly with a predicate on the candidate partition key (enabling partition pruning). A table queried broadly across its entire range with no dominant filter column is a poor hash/range candidate and may not benefit."],
    remediation_immediate=["N/A."],
    remediation_short_term=["If a good candidate is confirmed, proceed to partition-existing-large-table for the full migration runbook."],
    remediation_long_term=["Build partition-key awareness into new large-table schema design from the outset (see the root README's crypto-exchange ledger-table-growth guidance) to avoid this retrofit exercise in the future."],
    production_safety=["All scripts here are read-only."],
    escalation_criteria=["A confirmed candidate is business-critical (financial ledger) -- involve database engineering leadership before committing to the migration plan."],
    related_issues=["../partition-existing-large-table/README.md", "../../storage-and-capacity/table-growth/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_table_size_and_growth", "Checks current size and row count for the candidate table as the baseline feasibility input.",
               sb.largest_tables(),
               "Tables in the tens-of-GB+ range with continued growth are the strongest partitioning candidates; small or stable tables rarely justify the migration effort.",
               related_scripts="02_query_pattern_review.sql"),
    sql_script("02", "02_query_pattern_review", "Surfaces the top statements touching the candidate table to assess whether a dominant filter column (candidate partition key) exists.",
               sb.pgss_top_by_calls(),
               "Manually review query_snippet for a WHERE clause consistently filtering on one column (created_at, tenant_id, status) -- this is your partition key candidate. If queries scan broadly with no consistent filter, partition pruning will provide little benefit.",
               related_scripts="03_constraint_and_fk_complexity.sql"),
    sql_script("03", "03_constraint_and_fk_complexity", "Inventories existing constraints and foreign keys referencing/referenced-by the candidate table, since these materially affect migration difficulty.",
               """
-- All constraints on the candidate table, plus any foreign keys FROM other
-- tables pointing AT it (which is the more complex direction to migrate,
-- since referenced unique/PK constraints on a partitioned table have extra
-- requirements in PostgreSQL: the referenced columns must be part of the
-- partition key for a FK to reference a partitioned table in PG12+). Ships
-- with an illustrative default (public.orders); edit the \\set lines below
-- for your real candidate table.
\\set schema_name 'public'
\\set table_name 'orders'
SELECT
    con.conname,
    con.contype,
    pg_get_constraintdef(con.oid) AS definition,
    'on candidate table' AS direction
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = :'schema_name' AND c.relname = :'table_name'
UNION ALL
SELECT
    con.conname,
    con.contype,
    pg_get_constraintdef(con.oid),
    'referencing candidate table from elsewhere'
FROM pg_constraint con
WHERE con.contype = 'f'
  -- to_regclass() is used here rather than a bare ::regclass cast: a cast
  -- raises "relation does not exist" and aborts the whole statement the
  -- moment the default table_name doesn't exist in this database;
  -- to_regclass() instead returns NULL, so this branch simply contributes
  -- zero rows (the UNION ALL still runs safely) when the candidate table
  -- is absent.
  AND con.confrelid = to_regclass(:'schema_name' || '.' || :'table_name')
ORDER BY direction, contype;
""".strip("\n"),
               "Every foreign key pointing INTO the candidate table needs the referenced unique/PK constraint to include the partition key columns after migration -- this is frequently the single biggest source of migration complexity and must be planned for explicitly in partition-existing-large-table.",
               related_scripts="../partition-existing-large-table/README.md"),
]

WORKFLOWS.append(_wf(
    slug="partition-existing-large-table",
    title="Partitioning an Existing Large Production Table",
    summary=(
        "A comprehensive, realistic Staff DBA runbook for migrating an "
        "existing, already-large, in-production table to a native "
        "PostgreSQL declarative-partitioned structure with minimal downtime "
        "and controlled risk. This is deliberately NOT a single "
        "`ALTER TABLE ... PARTITION BY` -- PostgreSQL does not support "
        "converting an existing table in place; a new partitioned table "
        "must be built alongside it, backfilled, kept in sync, validated, "
        "and cut over."
    ),
    symptoms=["The table has been confirmed a strong partitioning candidate (see investigate-partitioning-candidate) and a migration has been approved."],
    business_impact=["A well-executed partitioned migration materially improves vacuum efficiency, query pruning, and archive/retention operations for a large, continuously growing table -- but a poorly executed one risks extended downtime, data loss, or referential-integrity breaks on a business-critical table."],
    root_causes=["N/A -- this is a planned migration runbook."],
    investigation_strategy=[
        "Confirm partition key selection and strategy (range/list/hash) against the query-pattern review from investigate-partitioning-candidate.",
        "Inventory every constraint, index, and foreign key relationship that must be recreated on the new structure.",
        "Estimate partition count/sizing.",
        "Build the new partitioned table and its partitions/indexes alongside the existing table.",
        "Backfill historical data in controlled batches.",
        "Establish a delta-sync mechanism (trigger-based dual-write or logical replication) to keep the new table current with ongoing writes during backfill.",
        "Validate row counts and checksums between old and new tables.",
        "Perform a brief, controlled cutover (rename swap) inside a short transaction.",
        "Validate the application against the new structure post-cutover.",
        "Retain the old table (renamed, not dropped) for a rollback window before final cleanup.",
    ],
    prerequisites=[
        "A confirmed partition key and strategy from investigate-partitioning-candidate.",
        "A maintenance window or low-traffic period for the final cutover step specifically (the backfill/sync steps themselves are designed to run online).",
        "Table-owner/DDL privileges and explicit change-management approval given the business criticality implied by 'large production table'.",
    ],
    interpretation_guide=[
        "The backfill and delta-sync phases can run for hours/days on a very large table without any application downtime -- only the final cutover step needs a brief exclusive lock (typically milliseconds to low seconds using an atomic rename swap), which is why this runbook separates 'safe to run online, take your time' steps from the single 'brief locking window' step.",
    ],
    remediation_immediate=["N/A -- see the rollback runbook (script 11) if a specific step must be aborted mid-migration."],
    remediation_short_term=["N/A."],
    remediation_long_term=["After a successful cutover and a confirmed rollback-safe period, drop the old (renamed) table and any now-redundant dual-write triggers."],
    production_safety=[
        "Every DDL/DML step in this workflow is provided as a guarded `.md` runbook template, not a ready-to-run `.sql` script, and requires the operator to substitute real schema/table/column names and review locking behavior before execution.",
        "The backfill step must run in small, committed batches -- never as one large transaction -- to avoid long-held locks, excessive WAL generation, and replica lag.",
        "The cutover step is the only step that takes a brief strong lock; every other step is designed to be safely run against a live, fully-online production table.",
    ],
    escalation_criteria=[
        "The table has foreign keys referencing it from tables you do not control/cannot coordinate a migration with -- escalate to database engineering and the owning teams before proceeding; this is the most common source of partitioning migrations stalling mid-way.",
        "Any validation step (row count/checksum mismatch) fails -- halt the migration and escalate immediately; do not proceed to cutover with unvalidated data.",
    ],
    related_issues=["../investigate-partitioning-candidate/README.md", "../partition-maintenance/README.md", "../../schema-changes/large-table-ddl/README.md"],
    aurora_notes=["Aurora PostgreSQL supports the pg_partman extension for ongoing partition maintenance (creating future partitions, dropping/archiving old ones automatically) -- consider adopting it (see partition-maintenance) once the initial migration in this runbook is complete, rather than only for the migration itself."],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_partition_key_distribution", "Analyzes the data distribution of the chosen candidate partition key to validate range/list boundary choices and detect skew.",
               """
-- Distribution of the candidate partition key column, to validate proposed
-- range boundaries (or list values) and detect skew that would create an
-- unevenly sized set of partitions. Ships with an illustrative default
-- (public.orders / created_at); edit the \\set lines below for your real
-- candidate table and key. The to_regclass guard means running this
-- unmodified against a database without that default table prints an
-- instructional notice instead of failing.
\\set schema_name 'public'
\\set table_name 'orders'
\\set partition_key_column 'created_at'
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\\gset

\\if :target_table_exists
SELECT
    date_trunc('month', :"partition_key_column")                  AS bucket,
    count(*)                                                  AS row_count
FROM :"schema_name".:"table_name"
GROUP BY 1
ORDER BY 1;
-- NOTE: date_trunc('month', ...) assumes a timestamp partition key
-- (range partitioning). For a non-time key (list/hash partitioning, e.g.
-- tenant_id), replace the bucket expression and GROUP BY with the raw
-- partition_key_column value instead -- the bucketing strategy is
-- inherently table- and key-specific.
\\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name/partition_key_column '
    '\\set lines above to point at your real partitioning candidate table.' AS notice;
\\endif
""".strip("\n"),
               "Roughly even row_count across buckets supports range partitioning by that time unit; heavy skew in a small number of buckets suggests either a different bucket granularity or a different partition key/strategy (e.g. hash) is more appropriate.",
               related_scripts="02_partition_sizing_estimate.sql"),
    sql_script("02", "02_partition_sizing_estimate", "Estimates resulting partition sizes given a proposed bucketing granularity, to avoid creating either too many tiny partitions or too few oversized ones.",
               """
-- Estimates average partition size in bytes given the current table's total
-- size and the row-distribution bucket counts gathered in script 01.
-- A commonly cited practical guideline is to keep individual partitions in
-- the low tens-of-GB range and avoid exceeding a few thousand total
-- partitions per table (planner and catalog overhead both grow with
-- partition count) -- treat this as a starting heuristic, not a hard rule,
-- and validate against your own query latency requirements.
\\set schema_name 'public'
\\set table_name 'orders'
\\set proposed_partition_count 24
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\\gset

\\if :target_table_exists
SELECT
    pg_size_pretty(pg_total_relation_size(to_regclass(:'schema_name' || '.' || :'table_name'))) AS current_total_size,
    pg_total_relation_size(to_regclass(:'schema_name' || '.' || :'table_name')) / NULLIF(:proposed_partition_count, 0) AS avg_bytes_per_partition_estimate,
    pg_size_pretty((pg_total_relation_size(to_regclass(:'schema_name' || '.' || :'table_name')) / NULLIF(:proposed_partition_count, 0))::bigint) AS avg_size_per_partition_pretty;
\\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name \\set lines above to '
    'point at your real partitioning candidate table.'              AS notice;
\\endif
""".strip("\n"),
               "If avg_size_per_partition_pretty is far outside the tens-of-GB heuristic range, revisit the bucketing granularity from script 01 before finalizing the partition scheme.",
               related_scripts="03_dependent_objects_inventory.sql"),
    sql_script("03", "03_dependent_objects_inventory", "Inventories every index, constraint, trigger, view, and foreign key touching the candidate table that must be recreated or adapted on the new partitioned structure.",
               """
-- Full dependency inventory for the migration plan: indexes, constraints,
-- triggers, and dependent views. Foreign keys are covered separately by
-- investigate-partitioning-candidate/scripts/03_constraint_and_fk_complexity.sql.
-- Ships with an illustrative default (public.orders); edit the \\set lines
-- below for your real candidate table. to_regclass() (never a bare
-- ::regclass cast) is used throughout so a missing default table returns
-- zero rows for the trigger/view branches instead of aborting the query.
\\set schema_name 'public'
\\set table_name 'orders'
SELECT 'index' AS object_type, indexname AS object_name, indexdef AS definition
FROM pg_indexes
WHERE schemaname = :'schema_name' AND tablename = :'table_name'
UNION ALL
SELECT 'trigger', tgname, pg_get_triggerdef(oid)
FROM pg_trigger
WHERE tgrelid = to_regclass(:'schema_name' || '.' || :'table_name')
  AND NOT tgisinternal
UNION ALL
SELECT 'dependent view', v.relname, pg_get_viewdef(v.oid)
FROM pg_depend d
JOIN pg_rewrite r ON r.oid = d.objid
JOIN pg_class v ON v.oid = r.ev_class
WHERE d.refobjid = to_regclass(:'schema_name' || '.' || :'table_name')
  AND v.relkind = 'v'
ORDER BY object_type, object_name;
""".strip("\n"),
               "Every object returned here needs an explicit plan: indexes must be recreated per-partition (PostgreSQL 11+ propagates a CREATE INDEX on the parent to all partitions automatically), triggers may need to be re-evaluated for partition-local vs. parent-level behavior, and dependent views must be tested against the new partitioned table before cutover.",
               related_scripts="04_row_count_baseline.sql"),
    sql_script("04", "04_row_count_baseline", "Captures the authoritative pre-migration row count and a lightweight checksum baseline for later validation.",
               """
-- Baseline row count and a lightweight aggregate checksum (sum of hashtext
-- over primary key values) for the source table, to be compared against the
-- new partitioned table after backfill in script 09. Ships with an
-- illustrative default (public.orders / id); edit the \\set lines below for
-- your real candidate table and primary key column.
\\set schema_name 'public'
\\set table_name 'orders'
\\set primary_key_column 'id'
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\\gset

\\if :target_table_exists
SELECT
    count(*)                                                    AS row_count,
    sum(hashtext(:"primary_key_column"::text))                    AS pk_checksum
FROM :"schema_name".:"table_name";
\\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name/primary_key_column '
    '\\set lines above to point at your real candidate table before '
    'recording a baseline.'                                       AS notice;
\\endif
""".strip("\n"),
               "Record row_count and pk_checksum somewhere durable (a runbook ticket, not just your terminal scrollback) -- this is your ground truth for validation in script 09, taken before any backfill activity begins.",
               related_scripts="05_create_partitioned_replacement_table.md"),
    md_script("05", "05_create_partitioned_replacement_table", "Creates the new partitioned replacement table structure (empty), matching the source table's columns and defaults.",
              (
                  "## Step 1: Create the new partitioned parent table\n\n"
                  "Choose ONE partitioning strategy based on the distribution analysis in "
                  "script 01:\n\n"
                  "**Range partitioning (time-series, e.g. order/ledger history by month):**\n"
                  "```sql\n"
                  "CREATE TABLE public.orders_partitioned (\n"
                  "    LIKE public.orders INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING IDENTITY\n"
                  ") PARTITION BY RANGE (created_at);\n"
                  "```\n\n"
                  "**List partitioning (discrete categories, e.g. by tenant/exchange region):**\n"
                  "```sql\n"
                  "CREATE TABLE public.orders_partitioned (\n"
                  "    LIKE public.orders INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING IDENTITY\n"
                  ") PARTITION BY LIST (region_code);\n"
                  "```\n\n"
                  "**Hash partitioning (even distribution with no natural range/list key, e.g. by "
                  "account_id for pure write-scaling rather than pruning):**\n"
                  "```sql\n"
                  "CREATE TABLE public.orders_partitioned (\n"
                  "    LIKE public.orders INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING IDENTITY\n"
                  ") PARTITION BY HASH (account_id);\n"
                  "```\n\n"
                  "Notes:\n"
                  "- `LIKE ... INCLUDING CONSTRAINTS` copies CHECK constraints but NOT foreign keys "
                  "or the primary key as a partitioned-table-compatible constraint automatically -- "
                  "add the primary key explicitly and ensure it includes the partition key column(s) "
                  "(a hard PostgreSQL requirement for partitioned tables).\n"
                  "- This CREATE TABLE is a metadata-only operation on an empty table and is fast "
                  "and low-risk; it does not touch the original table at all.\n"
              ),
              "This step is fully additive and does not touch the existing production table -- safe to run at any time.",
              related_scripts="06_create_partitions_and_indexes.md"),
    md_script("06", "06_create_partitions_and_indexes", "Creates the individual partitions and recreates indexes/constraints on the new partitioned table.",
              (
                  "## Step 2: Create partitions\n\n"
                  "```sql\n"
                  "CREATE TABLE public.orders_y2024m01 PARTITION OF public.orders_partitioned\n"
                  "    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');\n"
                  "-- Repeat for each bucket identified in script 01/02, including a few\n"
                  "-- future partitions ahead of the current date.\n"
                  "```\n\n"
                  "## Step 3: Recreate indexes\n\n"
                  "```sql\n"
                  "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_partitioned_account_id\n"
                  "    ON ONLY public.orders_partitioned (account_id);\n"
                  "-- On PostgreSQL, CREATE INDEX ... ON ONLY against the partitioned parent\n"
                  "-- registers the index definition; you must still create/attach a matching\n"
                  "-- index CONCURRENTLY on each existing partition individually, then\n"
                  "-- ALTER INDEX ... ATTACH PARTITION to link it, so no partition index build\n"
                  "-- ever takes a blocking lock on the whole partitioned table.\n"
                  "```\n\n"
                  "## Step 4: Recreate constraints\n\n"
                  "- Add the primary key on the partitioned parent (must include the partition "
                  "key column(s)).\n"
                  "- For foreign keys FROM other tables INTO this table: PostgreSQL requires the "
                  "referenced unique/PK constraint to include the partition key -- coordinate with "
                  "owners of any referencing tables before finalizing the key.\n"
                  "- Add any CHECK constraints not already copied via `LIKE ... INCLUDING "
                  "CONSTRAINTS` in script 05.\n\n"
                  "All of the above operate on the new, empty `orders_partitioned` structure and "
                  "do not lock or affect the original production table.\n"
              ),
              "Each partition and each CONCURRENTLY index build is independent -- validate one partition's index build completes (not INVALID) before scripting the rest in bulk.",
              related_scripts="07_backfill_historical_data_batches.md"),
    md_script("07", "07_backfill_historical_data_batches", "Backfills historical data from the original table into the new partitioned table in small, committed batches.",
              (
                  "## Batched backfill template\n\n"
                  "Never copy the whole table in one transaction -- it will hold a long-running "
                  "transaction (delaying vacuum cleanup and risking XID-age impact per "
                  "transactions-and-xid/xid-wraparound-risk) and generate a single enormous burst "
                  "of WAL that can spike replica lag.\n\n"
                  "```sql\n"
                  "-- Repeat this loop (via a script/psql \\watch, or an application-side batch job)\n"
                  "-- advancing :batch_start_id / :batch_end_id each iteration until the source\n"
                  "-- table is fully copied. Keep batches small enough to complete in well under a\n"
                  "-- second each on your hardware -- a few thousand to a low tens-of-thousands of\n"
                  "-- rows is a typical starting point; tune based on observed replica lag and\n"
                  "-- lock-wait impact during a test run.\n"
                  "\\set batch_start_id 0\n"
                  "\\set batch_size 5000\n"
                  "INSERT INTO public.orders_partitioned\n"
                  "SELECT * FROM public.orders\n"
                  "WHERE id > :batch_start_id\n"
                  "ORDER BY id\n"
                  "LIMIT :batch_size\n"
                  "ON CONFLICT DO NOTHING;\n"
                  "-- COMMIT after each batch (autocommit in psql commits each statement by\n"
                  "-- default; if wrapped in an explicit transaction elsewhere, COMMIT here).\n"
                  "```\n\n"
                  "Monitor WAL generation (storage-and-capacity/wal-generation) and Aurora replica "
                  "lag (replication-and-ha/reader-lag-investigation) while backfilling and slow "
                  "down/pause the batch loop if either climbs beyond your accepted tolerance.\n"
              ),
              "This step can safely take hours to days for a very large table -- there is no rush, and slower is safer. It runs fully online against a live production table.",
              related_scripts="08_dual_write_or_cdc_sync_delta.md"),
    md_script("08", "08_dual_write_or_cdc_sync_delta", "Keeps the new partitioned table current with ongoing writes made to the original table while the batched backfill (script 07) is in progress.",
              (
                  "## Option A: Trigger-based dual write (simplest, most portable)\n\n"
                  "```sql\n"
                  "CREATE OR REPLACE FUNCTION public.sync_orders_to_partitioned() RETURNS trigger AS $$\n"
                  "BEGIN\n"
                  "    IF TG_OP = 'INSERT' THEN\n"
                  "        INSERT INTO public.orders_partitioned VALUES (NEW.*) ON CONFLICT DO NOTHING;\n"
                  "    ELSIF TG_OP = 'UPDATE' THEN\n"
                  "        UPDATE public.orders_partitioned SET (col1, col2, ...) = (NEW.col1, NEW.col2, ...)\n"
                  "            WHERE id = NEW.id;\n"
                  "    ELSIF TG_OP = 'DELETE' THEN\n"
                  "        DELETE FROM public.orders_partitioned WHERE id = OLD.id;\n"
                  "    END IF;\n"
                  "    RETURN NULL;\n"
                  "END;\n"
                  "$$ LANGUAGE plpgsql;\n\n"
                  "CREATE TRIGGER trg_sync_orders_partitioned\n"
                  "    AFTER INSERT OR UPDATE OR DELETE ON public.orders\n"
                  "    FOR EACH ROW EXECUTE FUNCTION public.sync_orders_to_partitioned();\n"
                  "```\n"
                  "`CREATE TRIGGER` takes a brief `ShareRowExclusiveLock` -- schedule this specific "
                  "statement for a lower-traffic moment even though the rest of this runbook is "
                  "online, and confirm it completes quickly (it should, since it only adds metadata, "
                  "not data).\n\n"
                  "## Option B: Logical replication (larger tables, lower per-write overhead)\n\n"
                  "Create a publication on the source table and subscribe from the new table's "
                  "database/schema via `CREATE PUBLICATION` / `CREATE SUBSCRIPTION`, or use AWS DMS "
                  "for a managed CDC pipeline. This avoids adding a synchronous trigger to the hot "
                  "write path at the cost of additional operational complexity (monitoring "
                  "replication slot lag per replication-and-ha/replication-health) and is generally "
                  "preferable for the very highest-throughput tables.\n\n"
                  "Whichever option is chosen, it must remain active from before the backfill starts "
                  "until after the cutover (script 10) completes.\n"
              ),
              "Choose Option A for simplicity on moderate-throughput tables; choose Option B for the very highest-throughput ledger/order tables where trigger overhead on every write is unacceptable.",
              related_scripts="09_validation_row_counts_checksums.sql"),
    sql_script("09", "09_validation_row_counts_checksums", "Compares row counts and checksums between the original and new partitioned table before cutover.",
               """
-- Post-backfill validation: compare row counts and the same lightweight
-- checksum computed in script 04 against the new partitioned table. Run
-- this AFTER the dual-write/CDC sync (script 08) has been active for at
-- least one full validation pass with no application writes in flight
-- (e.g. during a brief write-quiesce window), so both sides are compared at
-- a consistent point in time. Ships with illustrative defaults (public.
-- orders / public.orders_partitioned); edit the \\set lines below for your
-- real source and target tables.
\\set schema_name 'public'
\\set source_table 'orders'
\\set target_table 'orders_partitioned'
SELECT
    to_regclass(:'schema_name' || '.' || :'source_table') IS NOT NULL
    AND to_regclass(:'schema_name' || '.' || :'target_table') IS NOT NULL AS both_tables_exist
\\gset

\\if :both_tables_exist
SELECT
    (SELECT count(*) FROM :"schema_name".:"source_table")               AS source_row_count,
    (SELECT count(*) FROM :"schema_name".:"target_table")                AS target_row_count,
    (SELECT count(*) FROM :"schema_name".:"source_table") - (SELECT count(*) FROM :"schema_name".:"target_table") AS row_count_difference;
\\else
SELECT
    'One or both of ' || :'schema_name' || '.' || :'source_table' || ' and '
    || :'schema_name' || '.' || :'target_table' || ' do not exist in this '
    'database yet. Edit the schema_name/source_table/target_table \\set '
    'lines above once the replacement table from script 05 has been '
    'created and backfilled.'                                      AS notice;
\\endif
""".strip("\n"),
               "row_count_difference must be exactly zero (during a brief write-quiesce window) before proceeding to cutover. Any non-zero difference means the dual-write/CDC mechanism has a gap that must be found and fixed before continuing -- do not proceed to cutover with an unexplained mismatch.",
               related_scripts="10_cutover_procedure.md"),
    md_script("10", "10_cutover_procedure", "Performs the brief, controlled cutover from the original table to the new partitioned table using an atomic rename swap.",
              (
                  "## Cutover procedure (the only step requiring a brief exclusive lock)\n\n"
                  "Perform during your lowest-traffic window despite the swap itself being fast, "
                  "since a short connection-draining/retry blip is still expected for in-flight "
                  "transactions.\n\n"
                  "```sql\n"
                  "BEGIN;\n"
                  "  -- Optional: set a short lock_timeout so this transaction fails fast rather\n"
                  "  -- than queuing indefinitely if an unexpected long-running transaction is\n"
                  "  -- holding a conflicting lock on the table at this moment.\n"
                  "  SET LOCAL lock_timeout = '5s';\n"
                  "\n"
                  "  ALTER TABLE public.orders RENAME TO orders_pre_partition_backup;\n"
                  "  ALTER TABLE public.orders_partitioned RENAME TO orders;\n"
                  "\n"
                  "  -- If using Option A (trigger-based sync) from script 08, drop the now-obsolete\n"
                  "  -- trigger inside this same transaction so no further dual-writes occur once\n"
                  "  -- the rename takes effect:\n"
                  "  DROP TRIGGER IF EXISTS trg_sync_orders_partitioned ON public.orders_pre_partition_backup;\n"
                  "COMMIT;\n"
                  "```\n\n"
                  "Both `ALTER TABLE ... RENAME` statements take `AccessExclusiveLock`, but on "
                  "already-open, already-indexed tables this is typically a millisecond-scale "
                  "metadata operation -- the actual data was already fully backfilled and "
                  "validated in prior steps. Application connections attempting to use the table "
                  "during this brief window will wait (or fail-fast if a client-side statement "
                  "timeout is set) and succeed immediately after COMMIT.\n\n"
                  "Immediately after cutover: run script 09's validation query again against the "
                  "new `public.orders` (now the renamed partitioned table) and a fresh application "
                  "smoke test before declaring the migration complete.\n"
              ),
              "This is the highest-risk single step in the entire runbook -- have the rollback runbook (script 11) open and ready before starting, and execute during your lowest-traffic window.",
              related_scripts="11_rollback_plan.md"),
    md_script("11", "11_rollback_plan", "Rollback procedure if validation fails post-cutover, or if the cutover itself must be aborted.",
              (
                  "## If validation fails BEFORE cutover (script 09 shows a mismatch)\n\n"
                  "- Do not proceed to script 10. Investigate and fix the dual-write/CDC mechanism "
                  "gap (script 08), then re-run validation.\n\n"
                  "## If an issue is discovered AFTER cutover (script 10 already committed)\n\n"
                  "```sql\n"
                  "BEGIN;\n"
                  "  ALTER TABLE public.orders RENAME TO orders_partitioned_rollback;\n"
                  "  ALTER TABLE public.orders_pre_partition_backup RENAME TO orders;\n"
                  "COMMIT;\n"
                  "```\n"
                  "This reverses the rename swap, restoring the original (pre-partition) table as "
                  "`public.orders` immediately. Any writes that occurred against the partitioned "
                  "table between cutover and rollback will need to be reconciled manually -- for "
                  "this reason, keep the post-cutover validation-and-smoke-test window (immediately "
                  "after script 10) as short as practically possible, and treat a rollback beyond "
                  "that immediate window as a data-reconciliation exercise, not a simple rename.\n\n"
                  "## Final cleanup (only after a confirmed, stable rollback-safe period)\n\n"
                  "```sql\n"
                  "DROP TABLE public.orders_pre_partition_backup; -- only after full confidence\n"
                  "```\n"
                  "Do not drop the renamed backup table until you have observed the new "
                  "partitioned table under full production load for a duration your organization's "
                  "change-management policy considers safe (commonly one full business cycle).\n"
              ),
              "Keep this runbook open and reviewed by a second engineer during the cutover window (script 10) -- do not read it for the first time after something has already gone wrong.",
              related_scripts="../partition-maintenance/README.md"),
]

WORKFLOWS.append(_wf(
    slug="partition-maintenance",
    title="Partition Maintenance",
    summary="Ongoing operational maintenance for an already-partitioned table: creating future partitions ahead of need, detaching/archiving old ones, and keeping indexes/constraints consistent across all partitions.",
    symptoms=["A time-based partitioned table is approaching the end of its currently-created partitions (writes for a future period would have no matching partition).", "Inconsistent indexes across partitions (some partitions missing an index that others have)."],
    business_impact=["Running out of future partitions on an append-only time-series table causes inserts for the missing period to fail outright (no default partition) or silently land in an unintended default partition (a data-integrity risk) if one exists."],
    root_causes=["No automated process creating future partitions ahead of need.", "An index added to the partitioned parent after some partitions were already detached/archived, or added directly to one partition instead of the parent."],
    investigation_strategy=["Check how many future partitions currently exist and how much runway remains.", "Check index/constraint consistency across all partitions.", "Automate partition creation going forward (pg_partman or a scheduled job)."],
    prerequisites=["pg_monitor role membership for investigation; DDL privileges for maintenance actions."],
    interpretation_guide=["A partitioned table with a DEFAULT partition catching unexpected values is safer against insert failures but risks silently accumulating data that should have been rejected/routed elsewhere -- monitor its size specifically."],
    remediation_immediate=["Create the next required partition(s) immediately if runway is critically low."],
    remediation_short_term=["Adopt pg_partman (supported on Aurora PostgreSQL) to automate future-partition creation and retention-based partition maintenance."],
    remediation_long_term=["Establish a partition-maintenance automation job (see automation/) with alerting well ahead of any runway exhaustion."],
    production_safety=["Creating a new empty partition is a fast, low-risk metadata operation.", "Detaching a partition (`ALTER TABLE ... DETACH PARTITION`) is fast in PostgreSQL 14+ (CONCURRENTLY option available) but dropping a detached partition is an irreversible data-deleting operation -- always DETACH first and CONFIRM before DROP."],
    escalation_criteria=["No automated partition-maintenance process exists for a business-critical partitioned table -- treat this as a standing operational risk and escalate for prioritization."],
    related_issues=["../partition-existing-large-table/README.md", "../../automation/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_future_partition_runway", "Checks how many future partitions exist for a time-based partitioned table and how much runway remains.",
               """
-- Lists all partitions of a given partitioned parent table with their
-- range bounds, to assess remaining runway for future data.
\\set schema_name 'public'
\\set parent_table 'orders'
SELECT
    child.relname                                               AS partition_name,
    pg_get_expr(child.relpartbound, child.oid)                   AS partition_bound,
    pg_size_pretty(pg_total_relation_size(child.oid))             AS partition_size
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table'
ORDER BY child.relname;
""".strip("\n"),
               "Confirm at least 1-2 future periods' worth of partitions already exist beyond the current date; if the highest partition_bound is approaching now(), create additional future partitions immediately.",
               related_scripts="02_index_consistency_across_partitions.sql"),
    sql_script("02", "02_index_consistency_across_partitions", "Checks whether every partition has the same set of indexes as the partitioned parent, to catch drift from manual per-partition changes.",
               """
-- Compares each partition's index count against the parent's expected index
-- count, to catch a partition that is missing an index the others have
-- (commonly from a partition created before an index was added to the
-- parent, or an index build that failed on one specific partition).
\\set schema_name 'public'
\\set parent_table 'orders'
SELECT
    child.relname                                               AS partition_name,
    count(idx.indexrelid)                                        AS index_count
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
LEFT JOIN pg_index idx ON idx.indrelid = child.oid
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table'
GROUP BY child.relname
ORDER BY index_count ASC, child.relname;
""".strip("\n"),
               "Partitions with a lower index_count than their siblings are missing an index -- cross-reference against the parent's index list and add the missing index CONCURRENTLY on that specific partition.",
               related_scripts="../partition-existing-large-table/scripts/06_create_partitions_and_indexes.md"),
]

WORKFLOWS.append(_wf(
    slug="partition-pruning",
    title="Partition Pruning Investigation",
    summary="Investigates whether queries against a partitioned table are actually benefiting from partition pruning (scanning only relevant partitions) or are unexpectedly scanning all partitions.",
    symptoms=["A partitioned table's query performance is no better than before partitioning.", "EXPLAIN output shows scans against partitions that should have been excluded by the WHERE clause."],
    business_impact=["Partitioning without effective pruning provides none of its intended query-performance benefit while still incurring the operational overhead of managing many partitions."],
    root_causes=["The query's WHERE clause does not directly reference the partition key (e.g. filtering on a derived/cast expression the planner cannot use for pruning).", "The partition key column's data type or the filter's parameter type causes an implicit cast the planner cannot prune across.", "`enable_partition_pruning` is disabled (non-default) at the session/database level."],
    investigation_strategy=["Run EXPLAIN on the affected query and check which partitions are listed as scanned.", "Confirm the WHERE clause directly and simply references the partition key column with a compatible type.", "Confirm enable_partition_pruning is on."],
    prerequisites=["Access to the exact query text being investigated."],
    interpretation_guide=["EXPLAIN (not EXPLAIN ANALYZE) is sufficient to see which partitions the planner intends to scan (look for 'Subplans Removed' or the explicit list of scanned partition relations) -- no need to execute the query for this specific check."],
    remediation_immediate=["Rewrite the query's filter to directly reference the partition key column without a wrapping function/cast if that is the cause."],
    remediation_short_term=["Confirm enable_partition_pruning = on at the database/session level."],
    remediation_long_term=["Revisit the partition key choice (partition-existing-large-table) if the application's actual dominant query pattern does not align with the current key."],
    production_safety=["EXPLAIN (without ANALYZE) is always safe -- it does not execute the query."],
    escalation_criteria=["Pruning cannot be achieved for the dominant query pattern without an application-level query rewrite that the owning team must implement -- escalate to that team with the EXPLAIN evidence."],
    related_issues=["../partition-existing-large-table/README.md", "../../query-optimization/analyze-query-plan/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_pruning_configuration_check", "Confirms partition pruning is enabled at the session/database level.",
               sb.key_settings_snapshot(),
               "enable_partition_pruning should be 'on' (the default); if disabled, no query will ever prune regardless of how well-written its WHERE clause is.",
               related_scripts="02_explain_guidance.md"),
    md_script("02", "02_explain_guidance", "Guidance for using EXPLAIN to confirm whether a specific query against a partitioned table is pruning effectively.",
              (
                  "Run `EXPLAIN <query>;` (no ANALYZE needed -- pruning is a planning-time decision) "
                  "against the query in question. In the plan:\n\n"
                  "- Look for an `Append` or `MergeAppend` node listing only the specific partition "
                  "subplans expected to contain matching data -- this confirms pruning worked.\n"
                  "- A count of `Subplans Removed: N` confirms the planner successfully excluded N "
                  "partitions.\n"
                  "- If EVERY partition appears as a subplan despite a WHERE clause that should "
                  "only match one, the filter expression is likely not directly comparable to the "
                  "partition key (e.g. `WHERE created_at::date = ...` wrapping the column in a cast "
                  "the planner cannot reason about generically -- rewrite as a plain range "
                  "comparison: `WHERE created_at >= '...' AND created_at < '...'`).\n"
              ),
              "Confirm the rewritten query's plan shows the expected Subplans Removed count before considering the investigation complete.",
              safety="DOCUMENTATION -- no SQL executed by this file itself",
              expected_impact="None from this file; running EXPLAIN itself never executes the query.",
              related_scripts="../../query-optimization/analyze-query-plan/README.md"),
]

WORKFLOWS.append(_wf(
    slug="missing-partitions",
    title="Missing Partitions",
    summary="A partitioned table has received (or is about to receive) data for a period/value that has no matching partition, either failing the insert or silently routing to an unintended DEFAULT partition.",
    symptoms=["Application errors: 'no partition of relation found for row'.", "A DEFAULT partition growing unexpectedly large."],
    business_impact=["A missing partition causes hard insert failures for exactly the data the application is trying to write in real time -- for a trading/order platform this can mean rejected writes during live operation."],
    root_causes=["Partition-maintenance automation not keeping ahead of actual data arrival (see partition-maintenance).", "An unexpected list-partition value (e.g. a new market/region code) with no corresponding partition and no DEFAULT partition configured."],
    investigation_strategy=["Confirm whether a DEFAULT partition exists and, if so, its current size/contents.", "Identify the specific missing range/value from the application error.", "Create the missing partition(s) immediately."],
    prerequisites=["DDL privileges to create the missing partition."],
    interpretation_guide=["A populated DEFAULT partition after this incident should be reviewed and, where appropriate, its rows migrated into a properly created specific partition to restore the intended pruning/maintenance benefits."],
    remediation_immediate=["Create the missing partition immediately using the same DDL pattern as partition-existing-large-table script 06."],
    remediation_short_term=["Audit and migrate any rows that landed in a DEFAULT partition during the gap."],
    remediation_long_term=["See partition-maintenance for the long-term automation fix that prevents recurrence."],
    production_safety=["Creating a new partition is a fast, low-risk metadata operation and safe to perform immediately in production."],
    escalation_criteria=["The application experienced write failures/rejections due to this gap -- escalate to the application team to assess whether any writes were lost (not just delayed/retried)."],
    related_issues=["../partition-maintenance/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_default_partition_check", "Checks whether a DEFAULT partition exists and how much data it currently holds.",
               """
-- Identifies the DEFAULT partition (if any) of a given partitioned table
-- and its current size -- a growing default partition is a leading
-- indicator that specific partitions are missing for arriving data.
\\set schema_name 'public'
\\set parent_table 'orders'
SELECT
    child.relname                                               AS default_partition_name,
    pg_size_pretty(pg_total_relation_size(child.oid))             AS size,
    (SELECT count(*) FROM pg_class WHERE oid = child.oid)          AS exists_check
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table'
  AND pg_get_expr(child.relpartbound, child.oid) = 'DEFAULT';
""".strip("\n"),
               "A non-trivial or growing size here confirms rows are landing in the default partition instead of a specific one -- identify their actual partition-key values and create the missing specific partition(s).",
               related_scripts="../partition-maintenance/README.md"),
]

WORKFLOWS.append(_wf(
    slug="partition-skew",
    title="Partition Skew",
    summary="Investigates uneven data distribution across partitions -- some partitions much larger or more heavily accessed than others -- which undermines the maintenance and performance benefits partitioning is meant to provide.",
    symptoms=["One or a few partitions dramatically larger than the rest.", "Query latency uneven across similar queries scoped to different partitions."],
    business_impact=["A severely skewed partition effectively recreates the original 'one giant table' problem within a single partition, while adding the operational overhead of managing many partitions for no corresponding benefit."],
    root_causes=["A range/list partition key with a naturally uneven distribution (e.g. one dominant trading pair or region generating far more volume than others under list partitioning).", "A hash partition count too low for the actual data volume/cardinality."],
    investigation_strategy=["Compare partition sizes across the table.", "Cross-reference size skew against known business skew (a dominant trading pair, a large tenant) to determine if it is expected or a key-choice mistake."],
    prerequisites=["pg_monitor role membership."],
    interpretation_guide=["Some skew is expected and acceptable if it reflects genuine business skew (a dominant asset pair will always have more orders) -- the actionable question is whether the largest partition alone is still too large to manage/vacuum/query efficiently, which may call for a compound partition key (e.g. sub-partitioning the largest list value by range)."],
    remediation_immediate=["None -- skew is a design consideration, not typically an emergency."],
    remediation_short_term=["Consider sub-partitioning (partition of a partition) the specific oversized partition by an additional key (e.g. range by date within a dominant list value)."],
    remediation_long_term=["Revisit partition key/strategy choice if skew consistently undermines partitioning's benefit; this may require a re-migration following partition-existing-large-table's runbook again with a revised key."],
    production_safety=["Investigation scripts are read-only."],
    escalation_criteria=["The most skewed partition alone has grown large enough to reproduce the original pre-partitioning performance/maintenance problems -- escalate for a redesign decision."],
    related_issues=["../partition-existing-large-table/README.md", "../partition-performance/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_partition_size_distribution", "Compares partition sizes across a partitioned table to identify skew.",
               """
-- Size distribution across all partitions of a given parent table, sorted
-- largest first, to quantify skew.
\\set schema_name 'public'
\\set parent_table 'orders'
SELECT
    child.relname                                               AS partition_name,
    pg_size_pretty(pg_total_relation_size(child.oid))             AS partition_size,
    round(
        100.0 * pg_total_relation_size(child.oid) /
        NULLIF(sum(pg_total_relation_size(child.oid)) OVER (), 0),
        2
    )                                                            AS pct_of_total
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table'
ORDER BY pg_total_relation_size(child.oid) DESC;
""".strip("\n"),
               "A single partition holding a dramatically disproportionate pct_of_total (well beyond what an even N-way split would predict) is skewed -- confirm whether this matches expected business skew or indicates a key-choice problem.",
               related_scripts="../partition-performance/README.md"),
]

WORKFLOWS.append(_wf(
    slug="partition-performance",
    title="Partition Performance",
    summary="Investigates whether partitioning is delivering its expected performance benefits (or introducing unexpected regressions) for query, vacuum, and DML performance on the partitioned table as a whole.",
    symptoms=["Overall query performance against the partitioned table has not improved (or has regressed) since migration.", "Cross-partition queries (aggregates spanning many/all partitions) are slower than expected."],
    business_impact=["If partitioning does not deliver the expected benefit, the operational overhead of maintaining many partitions (index management, constraint management, partition-maintenance automation) becomes pure cost with no corresponding gain."],
    root_causes=["Poor partition pruning for the dominant query pattern (see partition-pruning).", "Too many partitions, adding planner/executor overhead for queries that must consider all of them (common with an overly fine-grained partition scheme).", "Partition skew concentrating most activity on one partition (see partition-skew), meaning that partition alone still behaves like an unpartitioned large table."],
    investigation_strategy=["Confirm pruning is effective for the dominant query pattern.", "Check total partition count against the table's actual size/access pattern -- too many small partitions can hurt as much as too few large ones.", "Check whether performance-sensitive queries are cross-partition aggregates that inherently cannot benefit from pruning."],
    prerequisites=["pg_stat_statements for query-level timing comparison."],
    interpretation_guide=["Cross-partition aggregate queries (e.g. a dashboard summing across all history) are expected to scan multiple/all partitions regardless of partitioning -- partitioning helps write/vacuum/maintenance performance and single-partition-scoped query performance, not necessarily whole-table aggregate performance."],
    remediation_immediate=["None -- this is a tuning/design investigation."],
    remediation_short_term=["Reduce partition count (merge overly fine-grained partitions) if planner overhead from a very large partition count is measurable."],
    remediation_long_term=["Consider a pre-aggregated summary table/materialized view for cross-partition dashboard queries instead of expecting partitioning alone to solve that access pattern."],
    production_safety=["Investigation scripts are read-only."],
    escalation_criteria=["The partition scheme requires a fundamental redesign -- escalate to database engineering for a re-migration planning discussion."],
    related_issues=["../partition-pruning/README.md", "../partition-skew/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_partition_count_and_size_overview", "Overview of total partition count and size distribution, to assess whether the granularity itself is appropriate.",
               """
-- Total partition count and aggregate size for a given partitioned table --
-- a very high partition count (thousands) increases planner/catalog
-- overhead for every query touching the table, even with effective pruning.
\\set schema_name 'public'
\\set parent_table 'orders'
SELECT
    count(*)                                                    AS partition_count,
    pg_size_pretty(sum(pg_total_relation_size(child.oid)))        AS total_size,
    pg_size_pretty(avg(pg_total_relation_size(child.oid))::bigint) AS avg_partition_size
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table';
""".strip("\n"),
               "A partition_count in the thousands with a small avg_partition_size suggests over-partitioning; consider a coarser granularity (e.g. monthly instead of daily) going forward.",
               related_scripts="../partition-pruning/README.md"),
]
