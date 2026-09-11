"""Workflow definitions: schema-changes/ category (9 issue directories).

This is the category where the toolkit's read-only-by-default rule matters
most. Everything in `schema-changes` is *about* DDL -- index builds, column
additions, type changes, table rewrites, index drops -- and DDL cannot be
shipped as an auto-runnable `.sql` script. So the split here is strict and
deliberate:

  * `.sql` scripts are pre-flight and post-flight INVESTIGATION only. They
    read catalogs, locks, progress views, and statistics. Every one of them
    executes unmodified against a session with
    `default_transaction_read_only = on`.
  * `.md` runbooks carry the actual DDL. Each one documents, for every
    statement it contains: the lock level taken, the blocking risk that lock
    creates, the transaction behavior (which matters enormously, because
    `CREATE INDEX CONCURRENTLY` and `DROP INDEX CONCURRENTLY` cannot run
    inside a transaction block at all), the rollback story, and the
    production considerations specific to a 24/7 crypto exchange where there
    is no natural maintenance window.

The governing principle throughout: on a trading platform the lock is the
risk, not the work. An index build that takes four hours but never blocks a
writer is routine; a two-second `ALTER TABLE` that takes an
`AccessExclusiveLock` on the orders table at peak is an outage.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import (
    ANY_INSTANCE,
    GUARDED_DDL,
    PG_MONITOR,
    PG_MONITOR_PLUS_PGSS,
    TABLE_OWNER_OR_DDL,
    WRITER_ONLY,
    WRITER_PREFERRED,
    md_script,
    sql_script,
)
from .model import Workflow

CATEGORY_SLUG = "schema-changes"
CATEGORY_TITLE = "Schema Changes and DDL"

_PGSS_PREREQ = (
    "`pg_stat_statements` must already be installed in this database "
    "(`shared_preload_libraries` includes it on the Aurora cluster parameter "
    "group and `CREATE EXTENSION pg_stat_statements;` has been run by an "
    "administrator in a change-managed session). This script never creates it."
)

_DDL_PREREQ = (
    "The read-only investigation scripts for this workflow have been "
    "completed and reviewed; a change ticket exists; a second engineer is "
    "present; and the rollback path has been agreed before the first "
    "statement is executed."
)


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


def _pgss_guarded(body: str) -> str:
    """Wrap a pg_stat_statements-dependent query body in an extension-presence
    guard so the script still executes safely when the extension has not been
    created in this database. This never creates the extension -- it only
    detects whether it is already available and prints guidance otherwise.
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
        "SELECT 'pg_stat_statements is not installed in this database, so statement-level '\n"
        "       'statistics are unavailable for this check. Ask an administrator to add '\n"
        "       'pg_stat_statements to shared_preload_libraries in the Aurora DB cluster '\n"
        "       'parameter group (a reboot is required) and then install the extension in '\n"
        "       'a change-managed session; the exact statement is documented in the '\n"
        "       'repository prerequisites guide and is deliberately never executed by an '\n"
        "       'investigation script. The other scripts in this workflow do not depend on '\n"
        "       'this extension.'\n"
        "                                                                 AS notice;\n"
        "\\endif"
    )


_COLUMN_INVENTORY_SQL = """
-- Full column definition inventory for one target table: types, nullability,
-- defaults, identity/generated status, storage strategy, and whether a
-- previously added column is using a PostgreSQL 11+ "fast default" (stored in
-- the catalog rather than written into every existing row).
--
-- Ships with an illustrative default (public.trades); edit the \\set lines
-- below for your real target. Every name here is compared only inside a
-- catalog WHERE clause and is never cast to regclass, so running this
-- unmodified against a database without that table simply returns zero rows
-- rather than failing.
\\set schema_name 'public'
\\set table_name 'trades'
SELECT
    a.attnum                                                     AS ordinal,
    a.attname                                                    AS column_name,
    format_type(a.atttypid, a.atttypmod)                          AS data_type,
    a.attnotnull                                                 AS not_null,
    pg_get_expr(d.adbin, d.adrelid)                               AS default_expression,
    CASE a.attidentity
         WHEN 'a' THEN 'GENERATED ALWAYS AS IDENTITY'
         WHEN 'd' THEN 'GENERATED BY DEFAULT AS IDENTITY'
         ELSE NULL
    END                                                          AS identity_kind,
    CASE a.attgenerated
         WHEN 's' THEN 'GENERATED ALWAYS AS ... STORED'
         ELSE NULL
    END                                                          AS generated_kind,
    CASE a.attstorage
         WHEN 'p' THEN 'plain (never TOASTed)'
         WHEN 'e' THEN 'external (TOASTed, uncompressed)'
         WHEN 'm' THEN 'main (compressed inline where possible)'
         WHEN 'x' THEN 'extended (compressed, then TOASTed)'
         ELSE a.attstorage::text
    END                                                          AS storage_strategy,
    a.atthasmissing                                              AS uses_fast_default,
    col_description(a.attrelid, a.attnum)                         AS column_comment
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE n.nspname = :'schema_name'
  AND c.relname = :'table_name'
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum;
""".strip("\n")


_DEPENDENT_OBJECTS_SQL = """
-- Everything that depends on the target table and will therefore need
-- attention when its shape changes: indexes, constraints on it, foreign keys
-- pointing at it from elsewhere, dependent views/materialized views, and
-- user triggers.
--
-- to_regclass() is used rather than a ::regclass cast throughout. A cast
-- raises "relation does not exist" and aborts the whole statement the moment
-- the shipped default table is absent; to_regclass() returns NULL instead, so
-- each branch simply contributes zero rows and the script still runs clean.
\\set schema_name 'public'
\\set table_name 'trades'
SELECT 'index' AS dependent_kind,
       i.relname                                                 AS dependent_name,
       pg_get_indexdef(ix.indexrelid)                            AS definition
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
WHERE ix.indrelid = to_regclass(:'schema_name' || '.' || :'table_name')
UNION ALL
SELECT 'constraint on this table',
       con.conname,
       pg_get_constraintdef(con.oid)
FROM pg_constraint con
WHERE con.conrelid = to_regclass(:'schema_name' || '.' || :'table_name')
UNION ALL
SELECT 'incoming foreign key',
       con.conname,
       pg_get_constraintdef(con.oid)
FROM pg_constraint con
WHERE con.contype = 'f'
  AND con.confrelid = to_regclass(:'schema_name' || '.' || :'table_name')
UNION ALL
SELECT DISTINCT 'dependent view',
       v.relname,
       left(pg_get_viewdef(v.oid), 300)
FROM pg_depend dep
JOIN pg_rewrite r ON r.oid = dep.objid
JOIN pg_class v ON v.oid = r.ev_class
WHERE dep.refobjid = to_regclass(:'schema_name' || '.' || :'table_name')
  AND v.relkind IN ('v', 'm')
UNION ALL
SELECT 'trigger',
       tg.tgname,
       pg_get_triggerdef(tg.oid)
FROM pg_trigger tg
WHERE tg.tgrelid = to_regclass(:'schema_name' || '.' || :'table_name')
  AND NOT tg.tgisinternal
ORDER BY dependent_kind, dependent_name;
""".strip("\n")


WORKFLOWS: List[Workflow] = []


# ---------------------------------------------------------------------------
# 1. safe-index-creation
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="safe-index-creation",
    title="Safe Index Creation",
    summary=(
        "A new index is needed on a production table and the question is how "
        "to build it without blocking the trading path. This is the entry "
        "point for the whole index-creation family: it establishes whether "
        "the index is genuinely needed (a surprising proportion of proposed "
        "indexes are already covered by an existing one), which build method "
        "is appropriate for the table's size and write rate, and what the "
        "lock and rollback consequences of each option are. The single most "
        "important decision it drives is plain `CREATE INDEX` versus "
        "`CREATE INDEX CONCURRENTLY` -- the first takes a lock that blocks "
        "every write to the table for the entire build, and the second does "
        "not, at the cost of being slower, non-transactional, and able to "
        "fail in a way that leaves an unusable index behind."
    ),
    symptoms=[
        "A slow query investigation has identified a missing index on a large table such as orders, trades, or ledger_entries.",
        "A foreign key on a child table has no supporting index and parent deletes are performing sequential scans.",
        "A new feature or reporting requirement introduces an access pattern the current index set does not serve.",
        "A previous index build was attempted, blocked the application, and had to be cancelled.",
    ],
    business_impact=[
        "Building an index the wrong way on the orders table blocks every insert and update for the duration of the build -- on a multi-hundred-GB table that is an outage measured in hours, not seconds.",
        "Not building a needed index leaves the query it would serve doing sequential scans, which degrades continuously as the table grows.",
        "A failed build leaves an INVALID index consuming full storage and full write overhead while providing zero query benefit.",
        "Every additional index permanently increases write amplification on the hottest write path in the exchange, so an unnecessary index is a lasting cost, not a neutral one.",
    ],
    root_causes=[
        "N/A -- this is a planned change workflow, not an incident investigation. The inputs come from query-optimization and tables-and-indexes.",
    ],
    investigation_strategy=[
        "Inventory the indexes and constraints that already exist on the target table -- the proposed index is frequently already covered by the leading columns of an existing one.",
        "Measure the table's size, row count, and maintenance state to estimate build duration and decide which build method is viable.",
        "Check for existing duplicate indexes on the table, since adding another near-duplicate compounds an existing problem.",
        "Read the timeout and maintenance-memory settings that will govern the build's behavior when it cannot get its lock immediately.",
        "Choose the build method and execute it through the runbook, with the lock consequences understood before the first statement.",
        "Validate afterwards that the index is valid, is being used, and has not left anything behind.",
    ],
    prerequisites=[
        "A specific, justified index definition -- the query it serves should be named in the change ticket, not inferred afterwards.",
        "Table ownership or `MAINTAIN` privilege on the target table for the build itself; `pg_monitor` is sufficient for all the investigation scripts.",
        "Agreement on the build method and, if a blocking build is chosen, an agreed window.",
        "Enough free storage for the new index, plus awareness that on Aurora the space consumed permanently raises the volume high-water mark.",
    ],
    interpretation_guide=[
        "Before anything else, check whether an existing index already leads with the same column(s). PostgreSQL can use a multi-column index for queries filtering only on its leading columns, so an index on `(account_id, created_at)` already serves queries filtering on `account_id` alone and a separate single-column index would be pure duplication.",
        "Table size drives build duration, but write rate drives risk. A 50 GB table with light writes can tolerate a blocking build during a quiet hour; a 5 GB table taking ten thousand inserts a second cannot tolerate one at any hour.",
        "`maintenance_work_mem` is the main lever on build speed. A build that spills its sort to disk is dramatically slower, and on Aurora that spill consumes per-instance local storage.",
        "`max_parallel_maintenance_workers` above zero lets a plain `CREATE INDEX` use parallel workers. Note that `CREATE INDEX CONCURRENTLY` does not benefit from this in the same way, which is part of why it is slower.",
        "`lock_timeout` is the single most important safety setting for any blocking build: without it, a build that cannot acquire its lock queues, and every subsequent query on the table queues behind the build. With it, the build fails fast and harmlessly.",
        "If the table is partitioned, a `CREATE INDEX` on the parent recurses into every partition and holds locks across all of them. Build per-partition indexes concurrently and attach them instead -- this is covered in the runbook.",
    ],
    remediation_immediate=[
        "If a running index build is blocking the application right now, cancel it at the session level and let the partial work roll back. This is safe for a plain `CREATE INDEX` (it rolls back cleanly) and leaves an INVALID index behind for a concurrent build, which is then cleaned up via the failed-index-build workflow.",
    ],
    remediation_short_term=[
        "Build the index using the concurrent method documented in the runbook, which is the correct default for any production table on a 24/7 trading platform.",
        "Set `lock_timeout` on the session before any blocking DDL so a lock queue can never form behind it.",
        "Validate the index is being used after the build, and drop it if the query it was built for does not actually pick it up.",
    ],
    remediation_long_term=[
        "Make index review part of schema change review: every proposed index names its query and confirms no existing index covers the access pattern.",
        "Prefer partial indexes where the workload only queries a subset (an index on open orders is a fraction of the size of one on all orders).",
        "Adopt a standard index build procedure so the concurrent method is the default rather than a decision made under pressure each time.",
    ],
    production_safety=[
        "All `.sql` scripts in this workflow are read-only catalog and statistics queries and are safe to run at any time.",
        "The DDL lives exclusively in the `.md` runbook and must be executed statement by statement by an operator who has read it, never piped into psql.",
        "Never run a plain `CREATE INDEX` against a production table on the trading path. It holds a `ShareLock` that blocks every INSERT, UPDATE, and DELETE on the table for the entire build.",
        "`CREATE INDEX CONCURRENTLY` cannot run inside a transaction block. Do not wrap it in `BEGIN`/`COMMIT`, and be aware that many migration frameworks open a transaction implicitly -- that is the single most common reason concurrent builds fail in deployment pipelines.",
    ],
    escalation_criteria=[
        "The target table is on the live order-matching or wallet-balance path and a blocking build is being proposed -- this needs explicit sign-off, not a DBA decision.",
        "The estimated build duration exceeds the agreed window, or the table is large enough that the concurrent build will run for many hours across a market event.",
        "The table is partitioned with a large number of partitions, which turns one index build into hundreds and needs a coordinated plan.",
        "A previous build attempt failed and its cause is not understood -- resolve that through the failed-index-build workflow before retrying.",
    ],
    related_issues=[
        "../concurrent-index-build/README.md",
        "../add-index-large-table/README.md",
        "../failed-index-build/README.md",
        "../drop-index-safely/README.md",
        "../ddl-lock-investigation/README.md",
        "../../tables-and-indexes/missing-index-candidates/README.md",
        "../../tables-and-indexes/duplicate-indexes/README.md",
        "../../concurrency-and-locking/ddl-blocking/README.md",
    ],
    aurora_notes=[
        "Index builds run on the Aurora writer and generate substantial redo against the shared storage volume, which readers must apply. Expect reader lag to rise during a large build and schedule accordingly.",
        "The storage consumed by a new index permanently raises the Aurora volume high-water mark. Even if the index is later dropped, the volume does not shrink.",
        "`maintenance_work_mem` and `max_parallel_maintenance_workers` are set through the Aurora DB cluster or instance parameter group. A session-level `SET maintenance_work_mem` before a build is the least invasive way to give one build more memory.",
        "An Aurora failover during a `CREATE INDEX CONCURRENTLY` will abort the build and leave an INVALID index behind on the new writer -- check for one after any unplanned failover that coincided with a build.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_existing_index_and_constraint_inventory",
        "Inventories every index and constraint already on the target table, to establish whether the proposed index is genuinely new.",
        sb.index_and_constraint_inventory_for_table(),
        "Read the definition column carefully before accepting that a new index is needed. PostgreSQL can use a multi-column index for queries that filter only on its leading columns, so an existing index on (account_id, created_at) already serves a query filtering on account_id alone -- adding a single-column index there is pure duplication and pure write overhead. Also check is_valid and is_ready: a false value means an earlier build failed and left an unusable index behind, which must be cleaned up through the failed-index-build workflow before you attempt a new build of the same definition. Edit the schema_name and table_name variables at the top for your real target.",
        related_scripts="02_target_table_size_and_state.sql",
        table_purpose="Existing indexes and constraints on the target table.",
    ),
    sql_script(
        "02", "02_target_table_size_and_state",
        "Measures the target table's size, row estimates, and maintenance recency to estimate build duration and choose a build method.",
        sb.target_table_size_detail(),
        "Size drives duration, but write rate drives risk -- and the two are independent. A large, quiet table can tolerate a blocking build; a small, extremely hot table cannot tolerate one at any time of day. Use total_size_bytes for a rough duration estimate and index_count as a sanity check on whether this table should be receiving yet another index at all. If last_autovacuum is stale and n_dead_tup is high, consider vacuuming before the build: the build has to scan dead tuples too, so it will be slower than necessary on a bloated table.",
        related_scripts="03_duplicate_index_check.sql",
        table_purpose="Target table size, row estimates, and maintenance state.",
    ),
    sql_script(
        "03", "03_duplicate_index_check",
        "Checks the database for structurally duplicate indexes, so a new index is not added to a table that already has a redundancy problem.",
        sb.duplicate_indexes(),
        "If the target table already appears here, resolve the existing duplication before adding anything new -- otherwise you are compounding write amplification on a table that is already paying for it twice. Duplicates most commonly arise from an ORM migration and a hand-written migration creating the same index under different names, which is exactly the situation a new manual index build risks creating again. Nothing here should be dropped as part of this workflow; route it through the drop-index-safely runbook.",
        related_scripts="04_ddl_safety_settings.sql",
        table_purpose="Structurally duplicate indexes across the database.",
    ),
    sql_script(
        "04", "04_ddl_safety_settings",
        "Reads the timeout, memory, and parallelism settings that will govern the build's behavior and its blast radius if it cannot get its lock.",
        sb.ddl_safety_settings(),
        "lock_timeout is the setting that matters most. If it is 0 (disabled), a blocking build that cannot acquire its lock will queue indefinitely -- and because a pending lock request blocks every later request on the same table, the whole application queues behind it. Set it at session level before any blocking DDL so the statement fails fast and harmlessly instead. maintenance_work_mem determines whether the build's sort fits in memory; a spill makes the build dramatically slower and consumes per-instance local storage on Aurora. max_parallel_maintenance_workers speeds up a plain CREATE INDEX but does not help a concurrent build in the same way, which is part of why concurrent builds take longer.",
        related_scripts="05_safe_index_creation_runbook.md",
        table_purpose="Timeout, memory, and parallelism settings for the build.",
    ),
    md_script(
        "05", "05_safe_index_creation_runbook",
        "The guarded DDL runbook for creating an index, documenting lock level, blocking risk, transaction behavior, rollback, and production considerations for each method.",
        (
            "## Choosing a method\n\n"
            "| | Plain `CREATE INDEX` | `CREATE INDEX CONCURRENTLY` |\n"
            "|---|---|---|\n"
            "| Lock level | `ShareLock` on the table | `ShareUpdateExclusiveLock` on the table |\n"
            "| Blocks reads | No | No |\n"
            "| Blocks writes | **Yes, for the entire build** | No |\n"
            "| Blocks other DDL / autovacuum | Yes | Yes |\n"
            "| Table scans required | One | Two, plus two waits for concurrent transactions |\n"
            "| Relative duration | Baseline | Roughly 2-3x longer |\n"
            "| Runs inside a transaction block | Yes | **No -- not permitted** |\n"
            "| On failure | Rolls back cleanly, nothing left behind | Leaves an INVALID index that must be dropped |\n"
            "| Parallel workers | Yes | No |\n\n"
            "**On a 24/7 exchange, the concurrent form is the default.** Use the plain form "
            "only on a table that is genuinely not written to during the build -- a static "
            "reference table, or a brand-new table not yet receiving traffic.\n\n"
            "---\n\n"
            "## Method A: `CREATE INDEX CONCURRENTLY` (default for production)\n\n"
            "### Step A1 -- set a lock timeout for the session\n\n"
            "```sql\n"
            "SET lock_timeout = '5s';\n"
            "SET maintenance_work_mem = '2GB';  -- adjust to what the instance can spare\n"
            "```\n\n"
            "`SET lock_timeout` bounds how long the build waits for its initial\n"
            "`ShareUpdateExclusiveLock`. Even the concurrent form needs that lock briefly, and\n"
            "without a timeout it can queue behind a long-running transaction while every\n"
            "later statement on the table queues behind it.\n\n"
            "### Step A2 -- run the build\n\n"
            "```sql\n"
            "-- NOTE: this statement MUST NOT be wrapped in BEGIN/COMMIT. PostgreSQL rejects\n"
            "-- it inside a transaction block with:\n"
            "--   ERROR:  CREATE INDEX CONCURRENTLY cannot run inside a transaction block\n"
            "-- Many migration frameworks open a transaction implicitly around each\n"
            "-- migration; that is the most common reason concurrent builds fail in a\n"
            "-- deployment pipeline. Disable the framework's implicit transaction for this\n"
            "-- migration, or run the statement by hand.\n"
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trades_account_id_executed_at\n"
            "    ON public.trades (account_id, executed_at DESC);\n"
            "```\n\n"
            "- **Lock level:** `ShareUpdateExclusiveLock`. Reads and writes both proceed "
            "normally throughout. It does conflict with other DDL on the same table and with "
            "autovacuum, so only one such build per table at a time.\n"
            "- **Blocking risk:** low, but not zero. The build waits for all transactions "
            "that started before each of its two scan phases to finish. A single long-running "
            "transaction elsewhere in the database can stall the build indefinitely without "
            "blocking anything itself -- check for those first.\n"
            "- **Transaction behavior:** cannot run inside a transaction block. It manages its "
            "own internal transactions across multiple phases.\n"
            "- **Rollback:** there is no rollback. If the statement is cancelled or the "
            "session dies, PostgreSQL leaves the partially built index in place marked "
            "`INVALID`. It is invisible to the planner but still maintained by every write, so "
            "it must be dropped -- see the failed-index-build workflow.\n"
            "- **Production considerations:** the build generates significant redo. Watch "
            "Aurora reader lag while it runs and be prepared to cancel if lag becomes "
            "customer-visible. Do not start one immediately before a scheduled market event "
            "or deployment.\n\n"
            "### Step A3 -- verify validity\n\n"
            "Run `06_post_build_validation.sql` in this directory. If the index is marked "
            "invalid, do not retry the build until the leftover has been dropped.\n\n"
            "---\n\n"
            "## Method B: plain `CREATE INDEX` (only for tables not being written)\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '5s';\n"
            "  CREATE INDEX idx_instrument_reference_symbol\n"
            "      ON public.instrument_reference (symbol);\n"
            "COMMIT;\n"
            "```\n\n"
            "- **Lock level:** `ShareLock`. Concurrent reads are fine; **every write to the "
            "table blocks for the whole build**.\n"
            "- **Blocking risk:** total, for writes. On a table taking exchange traffic this "
            "is an outage for the duration.\n"
            "- **Transaction behavior:** fully transactional. It can be wrapped in "
            "`BEGIN`/`COMMIT` and combined with other DDL in one atomic change.\n"
            "- **Rollback:** clean. `ROLLBACK`, a cancellation, or a crash leaves no trace -- "
            "this is the one genuine advantage over the concurrent form.\n"
            "- **Production considerations:** acceptable for a static reference table, a "
            "brand-new table with no traffic yet, or a non-production environment. Always set "
            "`lock_timeout` so the statement cannot form a lock queue.\n\n"
            "---\n\n"
            "## Method C: partitioned tables\n\n"
            "A plain `CREATE INDEX` on a partitioned parent recurses into every partition and "
            "holds locks across all of them simultaneously. On a table with hundreds of "
            "partitions that is an unacceptable blast radius. Build it in three stages "
            "instead:\n\n"
            "```sql\n"
            "-- 1. Register the index definition on the parent without building anything.\n"
            "--    ON ONLY creates an invalid parent index as a template; the parent index\n"
            "--    becomes valid automatically once every partition's index is attached.\n"
            "CREATE INDEX idx_trades_part_account_id\n"
            "    ON ONLY public.trades (account_id);\n"
            "\n"
            "-- 2. Build a matching index concurrently on each partition, one at a time.\n"
            "CREATE INDEX CONCURRENTLY idx_trades_2026_01_account_id\n"
            "    ON public.trades_2026_01 (account_id);\n"
            "\n"
            "-- 3. Attach each partition index to the parent. This is a fast metadata\n"
            "--    operation; the parent index flips to valid after the last attach.\n"
            "ALTER INDEX idx_trades_part_account_id\n"
            "    ATTACH PARTITION idx_trades_2026_01_account_id;\n"
            "```\n\n"
            "- **Lock level:** step 1 takes a brief `ShareUpdateExclusiveLock` on the parent "
            "only (it builds nothing). Step 2 is per-partition and non-blocking. Step 3 is a "
            "brief metadata lock.\n"
            "- **Blocking risk:** minimal at every stage, which is the entire point of doing "
            "it this way.\n"
            "- **Rollback:** drop the parent index; attached partition indexes are dropped "
            "with it.\n"
            "- **Production considerations:** script the loop over partitions but run it "
            "serially, checking validity after each one. Repeat step 2 and 3 for every new "
            "partition created before the parent index existed.\n"
        ),
        "Pick the method from the comparison table first and write the choice into the change ticket with its justification, because that decision -- not the index definition -- is what determines whether this change is routine or an incident. Method A is the production default on a trading platform; Method B is only for tables genuinely not being written to; Method C is mandatory for partitioned tables regardless of size. Substitute your real schema, table, index name, and column list into the template before running anything, and execute the statements one at a time with the output of each checked before the next.",
        prerequisites=_DDL_PREREQ,
        related_scripts="06_post_build_validation.sql",
        expected_runtime="Minutes to many hours, depending on table size and method -- the concurrent form typically takes 2-3x the plain form.",
        table_purpose="Guarded DDL runbook: index creation methods and their lock behavior.",
    ),
    sql_script(
        "06", "06_post_build_validation",
        "Confirms after the build that the index is valid, that no build is still running, and that nothing was left behind.",
        sb.invalid_indexes() + "\n\n" + sb.create_index_progress(),
        "The first result set must be empty for the table you just built against. Any row for your new index means the build did not complete successfully and left an INVALID index behind -- it consumes full storage and full write overhead while the planner ignores it entirely, so it must be dropped through the failed-index-build workflow before you retry. The second result set shows any index build still in progress; if your build appears there, it has not finished yet and you should keep monitoring rather than declaring success. Once the index is confirmed valid, verify over the following days that the query it was built for actually picks it up -- an index that is never scanned is a permanent write-amplification cost with no benefit.",
        related_scripts="../failed-index-build/README.md",
        table_purpose="Post-build validity and in-progress build check.",
    ),
]


# ---------------------------------------------------------------------------
# 2. concurrent-index-build
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="concurrent-index-build",
    title="Concurrent Index Build",
    summary=(
        "`CREATE INDEX CONCURRENTLY` is the only index build method "
        "acceptable on a live exchange table, and it has a specific set of "
        "failure modes that have nothing to do with the index itself. It "
        "takes two full passes over the table and, between and after those "
        "passes, waits for every transaction that started before each pass to "
        "finish. That means a single long-running or idle-in-transaction "
        "session anywhere in the database -- one that never touches the "
        "target table at all -- can stall the build indefinitely. It also "
        "cannot run inside a transaction block, which is the reason most "
        "deployment pipelines fail to run it. This workflow covers the "
        "pre-flight checks that prevent a stall, live monitoring of a build "
        "in progress, and validation afterwards."
    ),
    symptoms=[
        "A concurrent index build has been running for far longer than the table size suggests it should.",
        "`pg_stat_progress_create_index` shows the build parked in a 'waiting for' phase and making no progress.",
        "A migration fails with 'CREATE INDEX CONCURRENTLY cannot run inside a transaction block'.",
        "A build completed but the index is marked INVALID and the planner will not use it.",
        "Aurora reader lag climbs while an index build is running on the writer.",
        "Autovacuum on the target table stops running while a concurrent build is in progress.",
    ],
    business_impact=[
        "A stalled build holds a `ShareUpdateExclusiveLock` on the table for its whole life, which blocks autovacuum on that table -- so a build stuck for hours on the trade tape is also hours of dead tuples accumulating unreclaimed.",
        "A build that has to be abandoned leaves an INVALID index consuming full storage and full write overhead for no benefit until someone notices and drops it.",
        "Extended builds generate sustained redo, raising reader lag and potentially serving stale balances and order states to customers.",
        "Repeated failed attempts delay the query improvement the index was meant to deliver, while the underlying slow query keeps degrading as the table grows.",
    ],
    root_causes=[
        "Stall: a long-running transaction elsewhere in the database that the build must wait for before it can proceed past a phase boundary.",
        "Stall: an idle-in-transaction session -- doing nothing, blocking everything, usually a connection-pool leak or a forgotten terminal.",
        "Stall: an orphaned prepared transaction, which holds its snapshot indefinitely and survives restarts.",
        "Failure: the statement wrapped in an explicit or framework-implicit transaction block, which PostgreSQL rejects outright.",
        "Failure: a `statement_timeout` set at the session, role, or database level firing mid-build.",
        "Failure: a unique index build encountering a duplicate key that violates the proposed uniqueness constraint.",
        "Failure: a deadlock between the build and application traffic on the same table.",
        "Failure: an Aurora failover during the build, which aborts it and leaves an INVALID index on the new writer.",
        "Slowness: `maintenance_work_mem` too small, forcing the build's sort to spill to local storage.",
    ],
    investigation_strategy=[
        "Before starting, find and clear anything that would stall the build: long-running transactions, idle-in-transaction sessions, prepared transactions.",
        "Confirm the timeout settings will not kill the build mid-flight, and that no transaction wrapper will reject it outright.",
        "Confirm the target table's size and existing index set so the expected duration is known before the clock starts.",
        "Start the build through the runbook, outside any transaction block.",
        "Monitor progress continuously via the progress view, paying particular attention to the phase rather than the percentage.",
        "If the build stalls, identify the exact blocking backend and decide whether to wait or abandon.",
        "Validate index validity afterwards and clean up if the build did not complete.",
    ],
    prerequisites=[
        "Table ownership or `MAINTAIN` privilege for the build itself; `pg_monitor` for all the monitoring scripts.",
        "A psql session or migration path that does not wrap the statement in a transaction -- verify this explicitly, because most frameworks do so by default.",
        "No `statement_timeout` in effect for the build session that is shorter than the expected build duration.",
        "Agreement that the build may need to be abandoned, and that doing so leaves cleanup work behind.",
    ],
    interpretation_guide=[
        "The `phase` column in the progress view is the diagnostic, not the percentage. 'building index' means real work is happening. 'waiting for writers before validation' or 'waiting for readers before marking dead' means the build is doing nothing at all and is waiting on older transactions -- no amount of patience helps until those finish.",
        "`current_locker_pid` names the exact backend the build is waiting on. That backend is your entire problem; look up what it is doing before considering any other explanation.",
        "A build waiting on a transaction that does not touch the target table is normal and is the most confusing part of this operation for people meeting it the first time. The build waits on transaction *age*, not on table access, because it needs a snapshot guarantee rather than a lock.",
        "`blocks_done` versus `blocks_total` tells you how far the current scan has progressed. Remember there are two scans, so reaching 100% once means roughly halfway.",
        "The `ShareUpdateExclusiveLock` the build holds conflicts with autovacuum on the same table. A build running for hours means hours without vacuum on that table, so check dead tuples after a long build completes.",
        "If the build fails, the leftover index is `indisvalid = false`. It is invisible to the planner but fully maintained by every write -- it is strictly worse than having no index, and must be dropped rather than left in place 'in case it is useful'.",
        "`CREATE INDEX CONCURRENTLY` is not restartable. A failed build must be cleaned up and started again from the beginning; there is no resume.",
    ],
    remediation_immediate=[
        "If the build is stalled on a specific backend, have the owning team close that session through their application -- that single action releases the build to continue.",
        "If reader lag has become customer-visible, cancel the build at the session level and clean up the INVALID index afterwards. Lag affecting customers outranks an index improvement every time.",
        "If the build failed with a transaction-block error, no cleanup is needed -- nothing was created. Re-run outside a transaction.",
    ],
    remediation_short_term=[
        "Drop the INVALID index left by a failed build before retrying, using the failed-index-build workflow.",
        "Set `idle_in_transaction_session_timeout` so a leaked connection cannot stall the next build the same way.",
        "Raise `maintenance_work_mem` for the build session so the sort stays in memory and the build finishes faster, shortening the window in which it can be disrupted.",
        "Schedule builds for the lowest-traffic window available, not because the build blocks writes (it does not) but because it minimizes the number of concurrent transactions it must wait for.",
    ],
    remediation_long_term=[
        "Make long-running and idle-in-transaction sessions a monitored, alerted condition -- they cause far more than index build stalls.",
        "Configure deployment pipelines to run index migrations outside transactions by default, so the transaction-block failure stops recurring.",
        "Adopt per-partition concurrent builds for partitioned tables so no single build has to span the whole dataset.",
        "Record actual build durations per table size so future change tickets carry a realistic estimate rather than a guess.",
    ],
    production_safety=[
        "All `.sql` scripts here are read-only and safe to run repeatedly during a build -- monitoring frequently is encouraged.",
        "`CREATE INDEX CONCURRENTLY` must never be wrapped in `BEGIN`/`COMMIT`, and migration frameworks that open an implicit transaction must be configured not to for this statement.",
        "Cancelling a concurrent build is safe for the database but always leaves an INVALID index behind. Plan the cleanup as part of the change, not as an afterthought.",
        "Do not run two concurrent builds against the same table simultaneously -- their `ShareUpdateExclusiveLock` requests conflict and the second will simply wait.",
    ],
    escalation_criteria=[
        "The build is stalled on a backend owned by a team that cannot be reached, and the stall is now blocking autovacuum on a high-write table.",
        "Reader lag caused by the build is affecting customer-facing reads -- treat as an incident and cancel the build.",
        "The build has failed more than once for reasons that are not understood -- stop retrying and investigate properly through failed-index-build.",
        "An Aurora failover occurred mid-build; confirm the state of the index on the new writer before any retry.",
    ],
    related_issues=[
        "../safe-index-creation/README.md",
        "../failed-index-build/README.md",
        "../add-index-large-table/README.md",
        "../ddl-lock-investigation/README.md",
        "../../concurrency-and-locking/long-running-transactions/README.md",
        "../../concurrency-and-locking/idle-in-transaction/README.md",
        "../../tables-and-indexes/invalid-indexes/README.md",
    ],
    aurora_notes=[
        "An Aurora failover aborts any in-flight concurrent index build. The new writer will have an INVALID index left behind -- always check after an unplanned failover that coincided with a build.",
        "The build's redo is applied by every Aurora reader from the shared storage volume, so reader lag is an expected side effect of a large build and should be monitored via CloudWatch `AuroraReplicaLag` throughout.",
        "Aurora does not expose `pg_stat_wal`, so the WAL generated by a build cannot be measured directly in SQL -- use CloudWatch `WriteThroughput` and `VolumeWriteIOPs` instead.",
        "`SET maintenance_work_mem` at session level works normally on Aurora and is the least invasive way to speed up one build without changing the cluster parameter group.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_preflight_blocking_transactions",
        "Finds the long-running transactions, idle-in-transaction sessions, and prepared transactions that would stall a concurrent build before it starts.",
        sb.long_running_transactions() + "\n\n" + sb.prepared_transactions(),
        "Clear this list before starting the build, not after it stalls. A concurrent build waits for every transaction that started before each of its two scan phases to finish -- including transactions that never touch the target table, because the guarantee it needs is about snapshot age rather than table access. That is why a forgotten session in a developer's terminal can stall a four-hour build indefinitely. Sessions in state 'idle in transaction' are the worst offenders: they do no work while blocking everything. The second result set lists prepared transactions; any older than a few minutes is an orphaned two-phase commit that will never resolve on its own and must be dealt with before the build starts.",
        related_scripts="02_target_table_and_settings.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="Transactions that would stall a concurrent build.",
    ),
    sql_script(
        "02", "02_target_table_and_settings",
        "Confirms the target table's size and the timeout settings that could kill the build mid-flight.",
        sb.target_table_size_detail() + "\n\n" + sb.ddl_safety_settings(),
        "Two things must be checked here before the build starts. First, total_size_bytes sets your duration expectation -- a concurrent build makes two passes plus two waits, so budget roughly two to three times a plain build. Second, statement_timeout and transaction_timeout must either be zero or comfortably longer than that expectation for the session running the build: a timeout firing mid-build aborts it and leaves an INVALID index behind, which is the most avoidable failure mode in this entire workflow. Also confirm maintenance_work_mem is generous enough that the build's sort does not spill to local storage, and remember to check for role-level and database-level timeout defaults, not just the cluster parameter group.",
        related_scripts="03_concurrent_index_build_runbook.md",
        table_purpose="Target table size plus timeout and memory settings.",
    ),
    md_script(
        "03", "03_concurrent_index_build_runbook",
        "The guarded DDL runbook for running a concurrent index build, with lock level, blocking risk, transaction behavior, rollback, and production considerations.",
        (
            "## Operation profile\n\n"
            "| Property | Value |\n"
            "|---|---|\n"
            "| Lock level | `ShareUpdateExclusiveLock` on the target table |\n"
            "| Blocks reads | No |\n"
            "| Blocks writes | No |\n"
            "| Blocks autovacuum on this table | **Yes, for the entire build** |\n"
            "| Blocks other DDL on this table | Yes |\n"
            "| Runs inside a transaction block | **No -- PostgreSQL rejects it** |\n"
            "| Rollback | None. A failure leaves an INVALID index that must be dropped. |\n"
            "| Restartable | No. A failed build starts again from the beginning. |\n\n"
            "---\n\n"
            "## Step 1 -- confirm you are not inside a transaction\n\n"
            "```sql\n"
            "-- In psql, this returns 'idle' when no transaction is open. Anything else\n"
            "-- means you are inside a transaction block and the build will be rejected.\n"
            "SELECT state, xact_start\n"
            "FROM pg_stat_activity\n"
            "WHERE pid = pg_backend_pid();\n"
            "```\n\n"
            "If you are driving this from a migration framework, disable its implicit\n"
            "per-migration transaction for this step. The error you get otherwise is:\n\n"
            "```\n"
            "ERROR:  CREATE INDEX CONCURRENTLY cannot run inside a transaction block\n"
            "```\n\n"
            "This is the single most common reason concurrent builds fail in deployment\n"
            "pipelines, and it is entirely preventable.\n\n"
            "## Step 2 -- set session parameters\n\n"
            "```sql\n"
            "SET lock_timeout = '5s';\n"
            "SET statement_timeout = 0;          -- the build must not be killed part-way\n"
            "SET maintenance_work_mem = '2GB';   -- keep the sort in memory if possible\n"
            "```\n\n"
            "`statement_timeout = 0` for this session only. A timeout firing mid-build is the\n"
            "most avoidable failure mode there is, and the cleanup it forces is more\n"
            "disruptive than the build itself.\n\n"
            "## Step 3 -- run the build\n\n"
            "```sql\n"
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ledger_entries_account_id_posted_at\n"
            "    ON public.ledger_entries (account_id, posted_at DESC);\n"
            "```\n\n"
            "- **Lock level:** `ShareUpdateExclusiveLock`. Application reads and writes are "
            "unaffected throughout.\n"
            "- **Blocking risk:** the build blocks nothing in the application, but it does "
            "block autovacuum on this table for its entire duration. On a high-write table, a "
            "multi-hour build means multi-hour dead tuple accumulation -- check dead tuples "
            "after it completes.\n"
            "- **Transaction behavior:** cannot run in a transaction block. Internally it runs "
            "several transactions and waits for older ones between phases, which is why it is "
            "slower and why it can stall on transactions that never touch this table.\n"
            "- **Rollback:** none. Cancellation, timeout, session death, or an Aurora failover "
            "leaves an INVALID index behind that must be dropped before retrying.\n"
            "- **Production considerations:** monitor Aurora reader lag throughout. Do not "
            "start a build immediately before a known market event, a deployment, or a "
            "scheduled failover test.\n\n"
            "## Step 4 -- monitor while it runs\n\n"
            "From a **second session** (the build session is busy), run\n"
            "`04_monitor_build_progress.sql` repeatedly. Watch the `phase` column rather than\n"
            "the percentages. If the phase does not change for a long period, run\n"
            "`05_blocking_sessions_during_build.sql` to find the backend it is waiting on.\n\n"
            "## Step 5 -- abandoning a build, if you must\n\n"
            "```sql\n"
            "-- Preferred: press Ctrl-C in the psql session running the build. That sends a\n"
            "-- cancel request to that backend only and is the least disruptive option.\n"
            "-- If the build session is unreachable, an authorized operator can cancel it by\n"
            "-- pid using the standard cancellation function, but confirm the pid against\n"
            "-- pg_stat_progress_create_index first and get a second pair of eyes on it --\n"
            "-- cancelling the wrong backend on a trading platform is its own incident.\n"
            "```\n\n"
            "After any abandonment, **the cleanup is mandatory, not optional**: an INVALID\n"
            "index is maintained by every write while being ignored by the planner, so leaving\n"
            "it in place is strictly worse than never having started. Go to the\n"
            "failed-index-build workflow.\n\n"
            "## Step 6 -- validate\n\n"
            "Run `06_post_build_validity_check.sql`. The index must report `indisvalid = true`\n"
            "before the change can be recorded as successful.\n"
        ),
        "Work through the steps strictly in order and do not skip step 1 -- the transaction-block check catches the most common failure before it wastes hours. Substitute your real schema, table, index name, and column list into the template in step 3. The two things that most often go wrong are entirely preventable from this runbook: a framework-implicit transaction (step 1) and a statement_timeout firing mid-build (step 2). Budget for the possibility of abandonment and cleanup before you start, so that decision is not being made under pressure.",
        prerequisites=_DDL_PREREQ,
        related_scripts="04_monitor_build_progress.sql, 06_post_build_validity_check.sql",
        expected_runtime="Typically 2-3x a plain index build; hours on a multi-hundred-GB exchange table.",
        table_purpose="Guarded DDL runbook: running a concurrent index build.",
    ),
    sql_script(
        "04", "04_monitor_build_progress",
        "Monitors an in-flight index build, showing its phase, progress, and the backend it is waiting on.",
        sb.create_index_progress(),
        "Read the phase column, not the percentages. 'building index' or 'index validation: scanning index' means real work is happening and the numbers will move. 'waiting for writers before validation' or 'waiting for readers before marking dead' means the build is doing nothing and is waiting for older transactions to end -- progress will not resume until they do, no matter how long you wait. When the build is in a waiting phase, current_locker_pid names the exact backend responsible, and that backend is your whole problem. Remember there are two full passes, so reaching the end of blocks_done once means roughly halfway. Run this from a second session every minute or two rather than once; the phase transitions are what tell you the build is healthy.",
        related_scripts="05_blocking_sessions_during_build.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="Live index build progress and phase.",
    ),
    sql_script(
        "05", "05_blocking_sessions_during_build",
        "Identifies the sessions a stalled build is waiting on, and what those sessions are actually doing.",
        sb.blocking_sessions_detail() + "\n\n" + sb.ddl_lock_waits(),
        "Use this the moment the progress view shows a waiting phase that is not advancing. The first result set expands every blocked session into one row per blocker with the blocker's own state and transaction age, which is what you need to decide whether to wait or abandon. Pay particular attention to a blocker in state 'idle in transaction' with a large blocking_txn_age: that session is doing no work at all and will block the build until someone closes it, so contacting the owning team is far more productive than waiting. The second result set shows the DDL-style lock queue on the table, which reveals whether anything else has queued behind the build's own lock -- if it has, the situation is escalating and abandoning the build may be the right call.",
        related_scripts="../ddl-lock-investigation/README.md",
        execution_location=WRITER_PREFERRED,
        table_purpose="Blockers stalling the build, and the lock queue behind it.",
    ),
    sql_script(
        "06", "06_post_build_validity_check",
        "Confirms the finished index is valid and usable, or identifies the INVALID leftover if it was not.",
        sb.invalid_indexes() + "\n\n" + sb.index_and_constraint_inventory_for_table(),
        "The first result set must not contain your new index. If it does, the build did not complete -- the index is invisible to the planner but still maintained by every write, so it is strictly worse than having no index and must be dropped before any retry. The second result set gives the full index inventory for the target table; confirm your new index appears there with is_valid and is_ready both true, and with the definition you intended. Edit the schema_name and table_name variables at the top for your real target. Finally, check dead tuples on the table over the next day: the build blocked autovacuum for its whole duration, so a long build usually leaves cleanup to catch up on.",
        related_scripts="../failed-index-build/README.md",
        table_purpose="Post-build validity and full index inventory.",
    ),
]


# ---------------------------------------------------------------------------
# 3. failed-index-build
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="failed-index-build",
    title="Failed Index Build Cleanup",
    summary=(
        "An index build did not complete and left an INVALID index behind. "
        "This is the specific, expected aftermath of a cancelled or "
        "interrupted `CREATE INDEX CONCURRENTLY` (and of "
        "`REINDEX CONCURRENTLY`), and it is worse than it looks: the leftover "
        "index is completely invisible to the planner, so it provides zero "
        "query benefit, while still being fully maintained by every insert "
        "and update on the table and fully processed by every vacuum. It is "
        "strictly worse than having no index at all. This workflow finds "
        "these leftovers, establishes why the build failed so the retry does "
        "not repeat it, cleans them up safely, and confirms the table is back "
        "to a known-good state."
    ),
    symptoms=[
        "A concurrent index build was cancelled, timed out, deadlocked, or died with its session.",
        "An index exists in the catalog but the planner never uses it, and `EXPLAIN` shows a sequential scan where the index should apply.",
        "An index appears with `indisvalid = false` or `indisready = false` in the catalog.",
        "Write latency on a table increased after a failed build and never came back down.",
        "An Aurora failover occurred while an index build was running.",
        "Storage consumption rose by roughly the size of an index, but the expected query improvement never materialized.",
    ],
    business_impact=[
        "The leftover index costs write amplification, WAL volume, storage, and vacuum time on every operation against the table -- continuously, for as long as it exists -- while delivering nothing.",
        "The query the index was meant to fix is still slow, so the original performance problem is unresolved and still degrading with growth.",
        "Repeated retries without cleanup can leave multiple INVALID indexes stacked on the same table, multiplying the waste.",
        "On Aurora the storage the failed build consumed permanently raised the volume high-water mark, so even after cleanup the cost remains.",
    ],
    root_causes=[
        "The build was cancelled manually because it was taking too long or causing reader lag.",
        "A `statement_timeout` set at session, role, or database level fired part-way through.",
        "The build session was disconnected -- a client timeout, a network interruption, a terminal closed.",
        "An Aurora failover or instance restart occurred mid-build, aborting it on the old writer.",
        "A unique index build found a duplicate key that violates the proposed uniqueness constraint.",
        "The build deadlocked with concurrent application traffic on the same table.",
        "The build exhausted local storage while spilling its sort, because `maintenance_work_mem` was too small for the table.",
        "A `REINDEX CONCURRENTLY` was interrupted, which leaves the same kind of leftover under a name suffixed `_ccnew`.",
    ],
    investigation_strategy=[
        "Find every INVALID index in the database and size the waste they represent.",
        "Check whether any build is still running -- an index that looks invalid may simply be a build that has not finished yet, and dropping it would be a serious mistake.",
        "Establish why the build failed, using the timeout settings and the current lock picture, so the retry does not repeat it.",
        "Drop the leftover safely through the runbook, using the concurrent drop form so the cleanup itself does not block anything.",
        "Confirm the cleanup is complete and the table's index inventory is back to a known-good state before retrying the build.",
    ],
    prerequisites=[
        "`pg_monitor` for the investigation scripts; index or table ownership for the drop itself.",
        "Certainty that no build is currently in progress for the index you are about to drop -- confirmed via the progress view, not assumed.",
        "An understanding of why the original build failed, so the retry is not simply a repeat of the same attempt.",
    ],
    interpretation_guide=[
        "`indisvalid = false` means the planner will never use the index. `indisready = false` means it is not even being maintained by writes yet. Both indicate an incomplete build; neither is recoverable by waiting.",
        "Before dropping anything, confirm via `pg_stat_progress_create_index` that no build is running. An index for an in-flight build legitimately shows as invalid until the build completes -- dropping it mid-build wastes hours of work and is the one genuinely destructive mistake available in this workflow.",
        "An index name ending in `_ccnew` (or `_ccnew1`, `_ccnew2`) is the signature of an interrupted `REINDEX CONCURRENTLY`. These are always safe to drop once no reindex is running, because the original index is still present and valid.",
        "Multiple INVALID indexes with similar definitions on the same table means the build has been retried repeatedly without cleanup. Drop all of them before the next attempt.",
        "`wasted_size` from the invalid index report is the storage being consumed for nothing. On Aurora, dropping the index frees it for reuse inside the volume but does not reduce billed storage, so the cost of the failed attempt is already sunk.",
        "If the build failed because of a duplicate key on a unique index, cleaning up the index is only half the job -- the duplicate data is a real data-integrity finding and needs the owning team involved before any retry.",
        "A failed build on a table that also shows high dead tuples is a compounding problem: the build blocked autovacuum while it ran, so cleanup plus a vacuum is usually the right sequence.",
    ],
    remediation_immediate=[
        "Confirm no build is in progress, then drop the INVALID index concurrently. This is one of the few remediations in the whole toolkit with essentially no downside -- the object being removed provides zero benefit by definition.",
    ],
    remediation_short_term=[
        "Fix whatever caused the original failure before retrying: clear the long-running transactions, remove the `statement_timeout`, raise `maintenance_work_mem`, or resolve the duplicate key.",
        "Run a vacuum on the affected table if the failed build blocked autovacuum for a long period.",
        "Retry the build through the concurrent-index-build runbook, with the failure cause addressed.",
    ],
    remediation_long_term=[
        "Add an INVALID index check to routine health checks so leftovers are found within a day rather than discovered months later during a storage investigation.",
        "Standardize build sessions with `statement_timeout = 0` and a generous `maintenance_work_mem`, removing the two most common failure causes structurally.",
        "Check for INVALID indexes as part of post-failover validation, since a failover during a build reliably produces one.",
    ],
    production_safety=[
        "All `.sql` scripts here are read-only.",
        "The drop is documented in the `.md` runbook and must use `DROP INDEX CONCURRENTLY`, which takes only a `ShareUpdateExclusiveLock` and does not block application traffic.",
        "`DROP INDEX CONCURRENTLY` cannot run inside a transaction block -- the same restriction, and the same common failure, as the concurrent create.",
        "Never drop an index without first confirming through the progress view that no build is running against it. That is the one action in this workflow that can genuinely destroy work.",
    ],
    escalation_criteria=[
        "The build failed because of a duplicate key violation on a unique index -- that is a data-integrity finding and needs the owning team before any retry.",
        "The same build has now failed three or more times for reasons that are not understood -- stop retrying and investigate the root cause properly.",
        "INVALID indexes are appearing without anyone having run a build, which suggests repeated failovers or instance instability and needs an AWS support case.",
        "The leftover is on a table where the write overhead is measurably affecting the trading path and the owning team is not available to authorize the drop.",
    ],
    related_issues=[
        "../concurrent-index-build/README.md",
        "../safe-index-creation/README.md",
        "../drop-index-safely/README.md",
        "../../tables-and-indexes/invalid-indexes/README.md",
        "../../storage-and-capacity/index-growth/README.md",
        "../../vacuum-and-autovacuum/index-bloat/README.md",
    ],
    aurora_notes=[
        "An Aurora failover during an index build reliably leaves an INVALID index on the new writer. Make an invalid-index check part of your standard post-failover validation.",
        "Dropping an INVALID index frees its space for reuse inside the Aurora volume but does not reduce the billed high-water mark. The storage cost of the failed build is already permanent.",
        "Aurora readers see the same catalog as the writer, so an INVALID index is invisible to the planner on every instance -- there is no scenario where a reader benefits from a leftover the writer cannot use.",
        "`REINDEX CONCURRENTLY` leftovers named with a `_ccnew` suffix behave identically on Aurora and are cleaned up the same way.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_invalid_indexes",
        "Finds every INVALID index in the database and quantifies the storage each one is wasting.",
        sb.invalid_indexes(),
        "Every row here is pure cost: the planner ignores the index completely, yet every insert and non-HOT update on the table still maintains it and every vacuum still processes it. Read the index_definition column to identify what the original build was trying to achieve, and note any name ending in _ccnew, _ccnew1 or similar -- that is the signature of an interrupted REINDEX CONCURRENTLY rather than a failed create, and the original index is still present and valid alongside it. Several INVALID indexes with similar definitions on one table means the build has been retried repeatedly without cleanup; drop all of them before the next attempt. Do not drop anything until script 02 confirms no build is in progress.",
        related_scripts="02_builds_currently_running.sql",
        table_purpose="INVALID indexes and the storage they waste.",
    ),
    sql_script(
        "02", "02_builds_currently_running",
        "Confirms whether any index build is still in progress, because an in-flight build legitimately appears invalid until it completes.",
        sb.create_index_progress(),
        "This is a mandatory safety gate, not an optional check. An index belonging to a build that is still running shows as invalid in the catalog and will become valid the moment the build finishes -- dropping it mid-build destroys hours of work and forces a restart from the beginning. If any row here names an index that also appeared in script 01, stop: that build is alive and should be monitored, not cleaned up. Only when this result set is empty, or contains no row matching your intended drop target, is it safe to proceed to the cleanup runbook.",
        related_scripts="03_failure_context_and_settings.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="Index builds currently in progress (safety gate before any drop).",
    ),
    sql_script(
        "03", "03_failure_context_and_settings",
        "Gathers the timeout settings and current lock picture that explain why the build failed, so the retry does not repeat it.",
        sb.ddl_safety_settings() + "\n\n" + sb.ddl_lock_waits(),
        "Work through the likely causes in order. A non-zero statement_timeout or transaction_timeout in effect for the build session is the most common and most easily fixed cause -- and remember these can be set at role or database level, not only in the cluster parameter group, so a session inheriting a role default is a frequent surprise. A small maintenance_work_mem means the build spilled its sort to local storage, which both slows it down and risks exhausting local storage on the instance. The lock-wait result set shows whether DDL-style locks are currently queued on the table, which would indicate the build was competing with other schema changes or with autovacuum. If none of these explain it, check whether an Aurora failover or instance restart coincided with the build, which aborts it unconditionally.",
        related_scripts="04_cleanup_invalid_index_runbook.md",
        execution_location=WRITER_PREFERRED,
        table_purpose="Timeout settings and lock context explaining the failure.",
    ),
    md_script(
        "04", "04_cleanup_invalid_index_runbook",
        "The guarded DDL runbook for removing an INVALID index left by a failed build, with lock level, blocking risk, transaction behavior, and rollback documented.",
        (
            "## Before you run anything\n\n"
            "**Mandatory gate:** `02_builds_currently_running.sql` must show no build in\n"
            "progress for the index you are about to drop. An in-flight build's index is\n"
            "legitimately invalid until it completes; dropping it destroys hours of work and\n"
            "forces a restart from scratch. This is the only genuinely destructive mistake\n"
            "available in this workflow, and it is entirely avoidable by running that script\n"
            "first.\n\n"
            "## Operation profile\n\n"
            "| Property | `DROP INDEX CONCURRENTLY` | `DROP INDEX` (plain) |\n"
            "|---|---|---|\n"
            "| Lock level | `ShareUpdateExclusiveLock` | `AccessExclusiveLock` |\n"
            "| Blocks reads | No | **Yes** |\n"
            "| Blocks writes | No | **Yes** |\n"
            "| Runs inside a transaction block | **No -- rejected** | Yes |\n"
            "| Rollback | None once it proceeds | Clean -- `ROLLBACK` undoes it |\n"
            "| Use on production | **Default choice** | Only inside a rehearsal transaction |\n\n"
            "---\n\n"
            "## Step 1 -- identify the exact index\n\n"
            "```sql\n"
            "-- Read the full name and definition from 01_invalid_indexes.sql output and\n"
            "-- confirm it is the one you mean. Index names are easy to confuse when a build\n"
            "-- has been retried several times and left several near-identical leftovers.\n"
            "SELECT n.nspname, i.relname, ix.indisvalid, ix.indisready,\n"
            "       pg_get_indexdef(ix.indexrelid)\n"
            "FROM pg_index ix\n"
            "JOIN pg_class i ON i.oid = ix.indexrelid\n"
            "JOIN pg_class t ON t.oid = ix.indrelid\n"
            "JOIN pg_namespace n ON n.oid = t.relnamespace\n"
            "WHERE NOT ix.indisvalid;\n"
            "```\n\n"
            "## Step 2 -- drop it concurrently\n\n"
            "```sql\n"
            "-- Must NOT be inside BEGIN/COMMIT. PostgreSQL rejects it with:\n"
            "--   ERROR:  DROP INDEX CONCURRENTLY cannot run inside a transaction block\n"
            "-- The same restriction, and the same framework pitfall, as the concurrent\n"
            "-- create. Only one index per statement is allowed in the concurrent form.\n"
            "SET lock_timeout = '5s';\n"
            "DROP INDEX CONCURRENTLY IF EXISTS public.idx_ledger_entries_account_id_posted_at;\n"
            "```\n\n"
            "- **Lock level:** `ShareUpdateExclusiveLock` on the parent table. Application "
            "reads and writes proceed normally.\n"
            "- **Blocking risk:** minimal. Like the concurrent create, it waits for "
            "transactions older than its phase boundaries, so a long-running transaction can "
            "delay it -- but it blocks nothing itself.\n"
            "- **Transaction behavior:** cannot run inside a transaction block, and cannot "
            "name more than one index.\n"
            "- **Rollback:** none once it proceeds. This is acceptable here precisely because "
            "the object being removed is INVALID and therefore provides no query benefit -- "
            "there is nothing to regress.\n"
            "- **Production considerations:** safe at any time of day. This is one of the few "
            "changes in this category that does not need a window.\n\n"
            "## Step 3 -- handle a `REINDEX CONCURRENTLY` leftover\n\n"
            "An index named `..._ccnew`, `..._ccnew1` and so on is the transient index from an\n"
            "interrupted `REINDEX CONCURRENTLY`. The original index is still present and\n"
            "valid, so the leftover is always safe to drop once no reindex is running:\n\n"
            "```sql\n"
            "DROP INDEX CONCURRENTLY IF EXISTS public.idx_trades_account_id_ccnew;\n"
            "```\n\n"
            "## Step 4 -- if the failure was a duplicate key\n\n"
            "If the original build was a unique index that failed on a duplicate key, **do not\n"
            "simply retry**. The duplicate rows are a real data-integrity finding. Identify\n"
            "them, involve the owning team, and resolve the data before rebuilding:\n\n"
            "```sql\n"
            "-- Read-only: find the offending duplicate values first. Adapt the column list\n"
            "-- to the proposed unique index definition.\n"
            "SELECT account_id, external_reference, count(*)\n"
            "FROM public.deposits\n"
            "GROUP BY account_id, external_reference\n"
            "HAVING count(*) > 1\n"
            "ORDER BY count(*) DESC\n"
            "LIMIT 50;\n"
            "```\n\n"
            "On an exchange, duplicates in a deposits, withdrawals, or ledger table are a\n"
            "financial-correctness issue, not a schema inconvenience. Escalate rather than\n"
            "deleting rows to make an index build succeed.\n\n"
            "## Step 5 -- vacuum if the build ran long\n\n"
            "A concurrent build holds a lock that blocks autovacuum on the table for its whole\n"
            "duration. After a long failed build, dead tuples have usually accumulated:\n\n"
            "```sql\n"
            "-- Plain VACUUM only. Never VACUUM FULL on a production exchange table: it takes\n"
            "-- an AccessExclusiveLock for its entire duration and, on Aurora, returns nothing\n"
            "-- to the cluster volume anyway.\n"
            "VACUUM (VERBOSE, ANALYZE) public.ledger_entries;\n"
            "```\n\n"
            "## Step 6 -- retry only after the cause is fixed\n\n"
            "Return to the concurrent-index-build workflow. Do not retry with the same session\n"
            "settings and the same blocking transactions still present -- that simply produces\n"
            "another leftover and another cleanup.\n"
        ),
        "Step 1 and the mandatory gate above it are the parts that matter; the drop itself is the easy bit. Confirm no build is running, confirm the exact index name, then drop it concurrently. Everything downstream of the drop -- the duplicate-key investigation in step 4 and the vacuum in step 5 -- is about making sure the retry succeeds where the original attempt did not, so do not skip straight back to rebuilding. Substitute your real schema and index names into every statement before running it.",
        prerequisites=(
            "Scripts 01-03 completed, and `02_builds_currently_running.sql` has confirmed "
            "no index build is in progress for the target index. " + _DDL_PREREQ
        ),
        related_scripts="02_builds_currently_running.sql, 05_verify_cleanup.sql",
        expected_runtime="Seconds to a few minutes for the drop; the optional vacuum can take much longer on a large table.",
        table_purpose="Guarded DDL runbook: removing an INVALID index safely.",
    ),
    sql_script(
        "05", "05_verify_cleanup",
        "Confirms the leftover is gone and the target table's index inventory is back to a known-good state before any retry.",
        sb.invalid_indexes() + "\n\n" + sb.index_and_constraint_inventory_for_table(),
        "The first result set should now be empty, or at least should no longer contain the index you dropped. The second gives the full index and constraint inventory for the target table -- confirm every remaining index shows is_valid and is_ready as true, and that nothing you did not intend to touch has changed. Edit the schema_name and table_name variables at the top for your real target. Only once both checks are clean should the build be retried, and only with the failure cause from script 03 actually addressed: retrying with the same session settings and the same blocking transactions present simply produces another leftover and another round of this workflow.",
        related_scripts="../concurrent-index-build/README.md",
        table_purpose="Post-cleanup verification and index inventory.",
    ),
]


# ---------------------------------------------------------------------------
# 4. large-table-ddl
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="large-table-ddl",
    title="DDL on a Large Production Table",
    summary=(
        "A schema change is needed on a table large enough and hot enough "
        "that the usual answer -- just run the ALTER -- is unacceptable. The "
        "governing insight is that on a live exchange the lock is the risk, "
        "not the work: PostgreSQL takes an `AccessExclusiveLock` for most "
        "`ALTER TABLE` variants, and while that lock is held every query "
        "against the table -- including plain SELECTs on the order-matching "
        "path -- queues behind it. Worse, a *pending* exclusive lock request "
        "blocks every later request too, so a statement that merely waits for "
        "its lock takes the application down just as effectively as one that "
        "holds it. This workflow classifies the intended change by lock level "
        "and rewrite behavior, checks the table is in a state where DDL can "
        "safely be attempted, and executes it with the lock-timeout-and-retry "
        "discipline that makes the difference between a routine change and an "
        "outage."
    ),
    symptoms=[
        "A schema change is required on a table in the hundreds of gigabytes, such as orders, trades, or ledger_entries.",
        "A previous `ALTER TABLE` on this table had to be cancelled because it blocked the application.",
        "A deployment is blocked pending a schema change nobody is willing to run during trading hours.",
        "An `ALTER TABLE` is currently queued waiting for a lock and the application is timing out.",
        "The change involves a column type change, a new `NOT NULL` constraint, or a new foreign key -- all of which have non-obvious rewrite and validation behavior.",
    ],
    business_impact=[
        "An `AccessExclusiveLock` on the orders table blocks order placement and cancellation entirely for as long as it is held -- on a rewriting DDL against a large table that can be many minutes or hours.",
        "A DDL statement waiting for a lock is just as damaging as one holding it, because every subsequent query queues behind the pending request. This is the mechanism behind most 'the database froze for no reason' incidents.",
        "A table rewrite doubles the table's storage for the duration, and on Aurora that peak permanently raises the volume high-water mark.",
        "Deferring necessary schema changes indefinitely because they are considered too dangerous accumulates technical debt that eventually forces a riskier, larger migration.",
    ],
    root_causes=[
        "N/A -- this is a planned change workflow. The risk being managed comes from table size, write rate, and the specific lock level of the chosen statement.",
    ],
    investigation_strategy=[
        "Measure the target table precisely: size, row estimate, index count, and maintenance state, which together determine rewrite duration.",
        "Inventory every dependent object -- indexes, constraints, incoming foreign keys, views, triggers -- because each may need attention after the change.",
        "Check the current lock picture on the table, so the change is not attempted into an existing lock queue.",
        "Check for long-running transactions, which are the usual reason a DDL statement cannot get its lock.",
        "Read the timeout settings that determine whether a failed lock acquisition is harmless or catastrophic.",
        "Classify the intended statement using the lock-level and rewrite reference before choosing an execution strategy.",
        "Execute through the runbook using lock timeout and retry, never as a bare statement.",
    ],
    prerequisites=[
        "Table ownership or equivalent DDL privilege; `pg_monitor` is sufficient for all investigation scripts.",
        "A precise statement of the intended change -- the exact `ALTER TABLE` text, not a description of the goal.",
        "A change ticket, a rollback plan, and a second engineer present for the execution.",
        "Enough free storage for a full table rewrite if the classification reference says the statement rewrites.",
    ],
    interpretation_guide=[
        "Classify the statement before anything else. The three questions are: what lock level does it take, does it rewrite the table, and does it scan the table to validate. A statement that takes `AccessExclusiveLock` but neither rewrites nor scans holds that lock for milliseconds and is essentially safe with a lock timeout. One that rewrites holds it for the duration of the rewrite and is not safe at any size that matters.",
        "`ShareUpdateExclusiveLock` (taken by `CREATE INDEX CONCURRENTLY`, `DROP INDEX CONCURRENTLY`, `ALTER TABLE ... SET STATISTICS`, `VALIDATE CONSTRAINT`) does not block reads or writes. This is the lock level you want, and several otherwise-blocking operations have a two-step form that lets you reach it.",
        "The pending-lock queue is the mechanism most people miss. When a DDL statement waits for `AccessExclusiveLock`, PostgreSQL queues every subsequent lock request behind it -- including plain SELECTs that would not have conflicted with the existing holders. One long-running read can therefore turn a waiting `ALTER TABLE` into a total application stall.",
        "This makes `lock_timeout` non-negotiable for production DDL. With a short timeout the statement either gets its lock immediately or fails harmlessly; without one it can take the application down while doing nothing at all.",
        "A table rewrite needs free space for a full second copy and generates WAL proportional to the entire table. On a multi-hundred-GB exchange table that is both a storage event and a replication event, not just a locking one.",
        "Several expensive operations have a cheap two-step alternative: add a `CHECK` constraint `NOT VALID` (brief exclusive lock, no scan) then `VALIDATE CONSTRAINT` (`ShareUpdateExclusiveLock`, scans without blocking). The same pattern applies to foreign keys. Reach for this before accepting a long blocking scan.",
        "If the table is partitioned, DDL on the parent recurses into every partition and holds locks across all of them at once. Always evaluate whether the change can be applied per-partition instead.",
    ],
    remediation_immediate=[
        "If an `ALTER TABLE` is currently queued and the application is stalling, cancel that statement immediately. The lock queue drains as soon as the pending request is withdrawn, and the application recovers within seconds.",
        "Do not attempt to fix a stalled DDL by adding more DDL. Cancel, let the queue drain, investigate, then retry with a lock timeout.",
    ],
    remediation_short_term=[
        "Re-run the change with `SET lock_timeout` and a retry loop, so it either acquires the lock immediately or fails without forming a queue.",
        "Split the change into its non-blocking equivalents where one exists -- `NOT VALID` plus `VALIDATE`, or the build-alongside-and-swap pattern for a rewrite.",
        "Clear the long-running transactions that are preventing lock acquisition, then retry.",
    ],
    remediation_long_term=[
        "Adopt the lock-timeout-and-retry pattern as the standard for all production DDL, enforced in the migration framework rather than remembered by individuals.",
        "Partition the largest tables so that future DDL can be applied one partition at a time instead of to a single monolithic relation.",
        "Add a schema-change review step that classifies every migration by lock level and rewrite behavior before it is approved.",
        "Set `idle_in_transaction_session_timeout` cluster-wide so leaked connections cannot indefinitely block schema changes.",
    ],
    production_safety=[
        "All `.sql` scripts here are read-only. Every DDL statement lives in the two `.md` runbooks and must be executed by hand, one statement at a time.",
        "Never issue DDL against a large production table without `lock_timeout` set. This is the single most important rule in this category.",
        "Never run a rewriting `ALTER TABLE` on a large exchange table during trading hours. Use the build-alongside-and-swap pattern instead.",
        "Check for long-running transactions immediately before executing, not an hour earlier -- the picture changes constantly.",
        "On a partitioned table, verify whether the statement recurses to partitions before running it on the parent.",
    ],
    escalation_criteria=[
        "The change requires a full table rewrite on a table on the live trading path -- this needs a migration design, not a single statement, and should go through the partitioning or archival migration patterns.",
        "An `ALTER TABLE` has already caused an application stall and the cause is not fully understood -- stop and investigate through ddl-lock-investigation before retrying.",
        "The table has incoming foreign keys from tables owned by other teams that must be coordinated with.",
        "The estimated rewrite duration exceeds any window the business is willing to accept, meaning the approach itself must change.",
    ],
    related_issues=[
        "../ddl-lock-investigation/README.md",
        "../column-type-change/README.md",
        "../add-column-large-table/README.md",
        "../add-index-large-table/README.md",
        "../../concurrency-and-locking/ddl-blocking/README.md",
        "../../concurrency-and-locking/blocked-queries/README.md",
        "../../concurrency-and-locking/long-running-transactions/README.md",
        "../../partitioning/partition-existing-large-table/README.md",
    ],
    aurora_notes=[
        "A table rewrite generates WAL proportional to the entire table, which every Aurora reader must apply from the shared storage volume. Expect substantial reader lag during a rewrite of a large table and plan for stale reads while it runs.",
        "The temporary second copy created by a rewrite permanently raises the Aurora volume high-water mark, even after the original is dropped. Budget for the peak, not the steady state.",
        "Aurora does not support `ALTER SYSTEM` for most parameters -- `lock_timeout` and friends are set in the DB cluster parameter group or, better for DDL, at session level with `SET`.",
        "An Aurora failover during a rewriting `ALTER TABLE` rolls the statement back entirely, since DDL is transactional. That is safe, but it means a long rewrite is exposed to any failover during its whole duration.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_target_table_size_and_state",
        "Measures the target table precisely, since size and index count are what determine how long any rewriting statement will hold its lock.",
        sb.target_table_size_detail(),
        "total_size_bytes is your rewrite duration proxy and index_count is the multiplier on it, because a rewrite has to rebuild every index as well as the heap. Treat any table above roughly ten gigabytes with a double-digit index count as one where a rewriting statement is simply not an option during trading hours. If n_dead_tup is high and last_autovacuum is stale, the rewrite also has to process all that dead space, so vacuuming first genuinely shortens the lock window. Edit the schema_name and table_name variables at the top for your real target.",
        related_scripts="02_dependent_objects_inventory.sql",
        table_purpose="Target table size, row estimates, and maintenance state.",
    ),
    sql_script(
        "02", "02_dependent_objects_inventory",
        "Inventories every index, constraint, incoming foreign key, view, and trigger that depends on the target table.",
        _DEPENDENT_OBJECTS_SQL,
        "Every row here is something the change may affect and must be accounted for in the plan. Incoming foreign keys are the most consequential: a rewrite or a swap requires them to be revalidated, and if they come from tables owned by other teams, coordination becomes the critical path rather than the DDL itself. Dependent views break if a column they reference is dropped or retyped, and materialized views additionally need refreshing. User triggers may fire unexpectedly during a backfill, which is a common and painful surprise in the build-alongside-and-swap pattern. Edit the schema_name and table_name variables at the top for your real target; the to_regclass guards mean an absent table simply returns zero rows.",
        related_scripts="03_current_lock_activity.sql",
        table_purpose="Indexes, constraints, foreign keys, views, and triggers depending on the table.",
    ),
    sql_script(
        "03", "03_current_lock_activity",
        "Shows the current DDL-style lock picture so a change is not attempted into an existing lock queue.",
        sb.ddl_lock_waits() + "\n\n" + sb.lock_detail_by_mode(),
        "Run this immediately before executing, not an hour earlier -- the lock picture changes by the second. Any ungranted AccessExclusiveLock request already queued on your target table means an application stall is either happening now or about to, and adding your own DDL to that queue makes it worse. The second result set is the ground truth for who holds what on which object, ordered with ungranted requests first. If anything is waiting on your target table, resolve that before you start; a clean lock picture at the moment of execution is what makes the difference between a millisecond metadata change and an incident.",
        related_scripts="04_long_running_transactions.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="Current DDL lock waits and full lock detail.",
    ),
    sql_script(
        "04", "04_long_running_transactions",
        "Finds the long-running transactions that are the usual reason a DDL statement cannot acquire its lock.",
        sb.long_running_transactions() + "\n\n" + sb.idle_in_transaction_sessions(),
        "A DDL statement needs its lock to be conflict-free against every existing holder, and a transaction that has been open for an hour holding even a weak lock on the table will block it. Sessions in state 'idle in transaction' are the most common culprit and the most frustrating: they are doing no work at all while preventing the schema change entirely, and they are almost always a connection-pool leak or a forgotten terminal rather than deliberate. Clear these before executing. Note that clearing them is not a permanent fix -- if they recur, set idle_in_transaction_session_timeout so they cannot accumulate, or every future schema change will hit the same wall.",
        related_scripts="05_ddl_safety_settings.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="Long-running and idle-in-transaction sessions blocking DDL.",
    ),
    md_script(
        "05", "05_lock_level_and_rewrite_reference",
        "Reference classification of every common ALTER TABLE variant by lock level, rewrite behavior, table scan, and safe alternative.",
        (
            "## How to use this reference\n\n"
            "Find your intended statement below and read three things: the **lock level**, "
            "whether it **rewrites** the table, and whether it **scans** the table. Those three "
            "facts determine everything about how risky the change is.\n\n"
            "The key distinction is duration of lock hold:\n\n"
            "- A statement that takes `AccessExclusiveLock` but neither rewrites nor scans "
            "holds it for **milliseconds**. With a lock timeout, that is safe on any table at "
            "any time.\n"
            "- A statement that **rewrites** holds `AccessExclusiveLock` for the entire "
            "rewrite. On a large table that is an outage.\n"
            "- A statement that **scans** holds its lock for the scan. Whether that is "
            "acceptable depends entirely on which lock level it holds while scanning.\n\n"
            "---\n\n"
            "## Metadata-only: `AccessExclusiveLock`, no rewrite, no scan\n\n"
            "These hold the strong lock only for as long as the catalog update takes -- "
            "typically milliseconds. Safe with a lock timeout even on a very large table.\n\n"
            "| Statement | Notes |\n"
            "|---|---|\n"
            "| `ALTER TABLE ... RENAME TO ...` | Pure catalog change |\n"
            "| `ALTER TABLE ... RENAME COLUMN ... TO ...` | Breaks application queries referencing the old name -- coordinate the deploy |\n"
            "| `ALTER TABLE ... ADD COLUMN ... ` (no default, or a constant default on PG11+) | See add-column-large-table |\n"
            "| `ALTER TABLE ... DROP COLUMN ...` | Marks the column dropped; space is reclaimed lazily by vacuum, not immediately |\n"
            "| `ALTER TABLE ... ALTER COLUMN ... DROP NOT NULL` | Catalog only |\n"
            "| `ALTER TABLE ... ALTER COLUMN ... SET DEFAULT` / `DROP DEFAULT` | Affects future rows only |\n"
            "| `ALTER TABLE ... SET (fillfactor = ...)` | Applies to future page writes only |\n"
            "| `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...) NOT VALID` | Existing rows are not checked -- this is the cheap half of the two-step pattern |\n"
            "| `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ... NOT VALID` | Same, for foreign keys |\n\n"
            "## Full rewrite: `AccessExclusiveLock` held for the whole rewrite\n\n"
            "**Not acceptable on a large production table during trading hours.** Use the "
            "build-alongside-and-swap pattern in script 06 instead.\n\n"
            "| Statement | Notes |\n"
            "|---|---|\n"
            "| `ALTER TABLE ... ALTER COLUMN ... TYPE ...` (most type changes) | Rewrites heap and every index; see column-type-change for the exceptions |\n"
            "| `ALTER TABLE ... ADD COLUMN ... DEFAULT <volatile expression>` | A volatile default such as `now()` or `gen_random_uuid()` forces a rewrite; a constant does not on PG11+ |\n"
            "| `ALTER TABLE ... ADD COLUMN ... GENERATED ALWAYS AS (...) STORED` | Must compute and store the value for every existing row |\n"
            "| `ALTER TABLE ... SET TABLESPACE ...` | Physically relocates the relation |\n"
            "| `VACUUM FULL` / `CLUSTER` | Full rewrite plus index rebuild; never on a production exchange table |\n\n"
            "## Scan without rewrite: `AccessExclusiveLock` held for the scan\n\n"
            "Cheaper than a rewrite but still holds the strong lock while reading every row. "
            "Prefer the two-step alternative in every case.\n\n"
            "| Statement | Safe alternative |\n"
            "|---|---|\n"
            "| `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...)` | Add `NOT VALID`, then `VALIDATE CONSTRAINT` |\n"
            "| `ALTER TABLE ... ADD CONSTRAINT ... FOREIGN KEY ...` | Add `NOT VALID`, then `VALIDATE CONSTRAINT` |\n"
            "| `ALTER TABLE ... ALTER COLUMN ... SET NOT NULL` | Add a `CHECK (col IS NOT NULL) NOT VALID`, validate it, then `SET NOT NULL` -- PostgreSQL 12+ uses the validated check to skip the scan |\n\n"
            "## Non-blocking: `ShareUpdateExclusiveLock`\n\n"
            "These do not block reads or writes. They do block other DDL and autovacuum on the "
            "same table.\n\n"
            "| Statement | Notes |\n"
            "|---|---|\n"
            "| `CREATE INDEX CONCURRENTLY` | Cannot run in a transaction block |\n"
            "| `DROP INDEX CONCURRENTLY` | Cannot run in a transaction block; one index per statement |\n"
            "| `REINDEX INDEX CONCURRENTLY` | Needs space for a second copy of the index |\n"
            "| `ALTER TABLE ... VALIDATE CONSTRAINT ...` | The safe half of the two-step pattern -- scans without blocking |\n"
            "| `ALTER TABLE ... ALTER COLUMN ... SET STATISTICS ...` | Catalog only; run `ANALYZE` afterwards to take effect |\n"
            "| `ALTER TABLE ... SET (autovacuum_* = ...)` | Per-table autovacuum tuning |\n\n"
            "## Write-blocking: `ShareRowExclusiveLock`\n\n"
            "| Statement | Notes |\n"
            "|---|---|\n"
            "| `CREATE TRIGGER` | Blocks writes briefly; reads continue |\n"
            "| `ALTER TABLE ... ADD CONSTRAINT ... EXCLUDE ...` | Also builds an index |\n\n"
            "---\n\n"
            "## Partitioned tables\n\n"
            "DDL on a partitioned parent generally recurses into every partition and acquires "
            "locks on all of them in one transaction. On a table with hundreds of partitions "
            "the blast radius is the whole dataset at once. Always ask whether the change can "
            "be applied partition by partition instead, and prefer `ONLY` plus per-partition "
            "execution where the semantics allow it.\n"
        ),
        "Classify the intended statement here before writing the change ticket, and record the lock level and rewrite answer in the ticket itself -- that classification, not the statement text, is what a reviewer needs to approve or reject the change. If the statement lands in the full-rewrite section and the table is large, stop: do not look for a way to make the rewrite faster, switch to the build-alongside-and-swap pattern in script 06. If it lands in the scan-without-rewrite section, always take the two-step alternative; there is no situation on a production exchange table where the one-step form is preferable.",
        safety=GUARDED_DDL,
        expected_impact="None by itself -- this is a reference document. The statements it classifies have the impacts described per row.",
        prerequisites="Scripts 01-04 completed so the table's size, dependencies, and current lock state are known.",
        required_privileges=TABLE_OWNER_OR_DDL,
        related_scripts="06_large_table_ddl_execution_runbook.md",
        expected_runtime="Not applicable -- reference document.",
        table_purpose="Lock level and rewrite classification for common ALTER TABLE variants.",
    ),
    md_script(
        "06", "06_large_table_ddl_execution_runbook",
        "The guarded execution runbook: lock-timeout-and-retry for fast DDL, the two-step pattern for constraints, and build-alongside-and-swap for rewrites.",
        (
            "## Pattern 1 -- lock timeout and retry (for metadata-only DDL)\n\n"
            "Use for anything classified as metadata-only in script 05. The point is that the\n"
            "statement either gets its lock immediately or fails harmlessly, and never forms\n"
            "a queue that stalls the application.\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  -- The single most important line in this entire category. Without it, a\n"
            "  -- statement that cannot get its lock queues, and every subsequent query on\n"
            "  -- the table queues behind it -- a total application stall caused by a\n"
            "  -- statement that has not done any work at all.\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "\n"
            "  ALTER TABLE public.orders ADD COLUMN settlement_batch_id bigint;\n"
            "COMMIT;\n"
            "```\n\n"
            "If it fails with `canceling statement due to lock timeout`, that is the system\n"
            "working correctly. Wait, check `04_long_running_transactions.sql`, and retry.\n"
            "Retry in a loop with a short sleep rather than raising the timeout -- on a busy\n"
            "table the window usually appears within a few attempts.\n\n"
            "- **Lock level:** `AccessExclusiveLock`, held for milliseconds.\n"
            "- **Blocking risk:** near zero with the timeout set; severe without it.\n"
            "- **Transaction behavior:** fully transactional and combinable with other DDL in "
            "the same transaction.\n"
            "- **Rollback:** clean. `ROLLBACK` undoes it entirely.\n"
            "- **Production considerations:** safe during trading hours *with* the timeout. "
            "Never without.\n\n"
            "---\n\n"
            "## Pattern 2 -- two-step constraint addition\n\n"
            "Use for `CHECK`, `FOREIGN KEY`, and `SET NOT NULL`. Splits one long blocking scan\n"
            "into a millisecond lock plus a non-blocking scan.\n\n"
            "```sql\n"
            "-- Step 1: add the constraint without checking existing rows.\n"
            "-- AccessExclusiveLock, milliseconds, no scan. New and updated rows are enforced\n"
            "-- from this moment on.\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "  ALTER TABLE public.withdrawals\n"
            "      ADD CONSTRAINT withdrawals_amount_positive\n"
            "      CHECK (amount > 0) NOT VALID;\n"
            "COMMIT;\n"
            "\n"
            "-- Step 2: validate existing rows. ShareUpdateExclusiveLock -- reads and writes\n"
            "-- both continue normally while this scans the whole table. Run it separately,\n"
            "-- and it can take as long as it needs to.\n"
            "ALTER TABLE public.withdrawals VALIDATE CONSTRAINT withdrawals_amount_positive;\n"
            "```\n\n"
            "The same pattern for a foreign key:\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "  ALTER TABLE public.ledger_entries\n"
            "      ADD CONSTRAINT ledger_entries_account_fk\n"
            "      FOREIGN KEY (account_id) REFERENCES public.accounts (id) NOT VALID;\n"
            "COMMIT;\n"
            "\n"
            "ALTER TABLE public.ledger_entries VALIDATE CONSTRAINT ledger_entries_account_fk;\n"
            "```\n\n"
            "And for `SET NOT NULL` on PostgreSQL 12 and later, where a validated check "
            "constraint lets the `SET NOT NULL` skip its scan entirely:\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "  ALTER TABLE public.trades\n"
            "      ADD CONSTRAINT trades_venue_id_not_null\n"
            "      CHECK (venue_id IS NOT NULL) NOT VALID;\n"
            "COMMIT;\n"
            "\n"
            "ALTER TABLE public.trades VALIDATE CONSTRAINT trades_venue_id_not_null;\n"
            "\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "  ALTER TABLE public.trades ALTER COLUMN venue_id SET NOT NULL;\n"
            "  -- The validated CHECK proves no NULLs exist, so no table scan is needed here.\n"
            "  -- The redundant CHECK can then be dropped.\n"
            "  ALTER TABLE public.trades DROP CONSTRAINT trades_venue_id_not_null;\n"
            "COMMIT;\n"
            "```\n\n"
            "- **Lock level:** step 1 `AccessExclusiveLock` (milliseconds); step 2 "
            "`ShareUpdateExclusiveLock` (duration of the scan, blocking nothing).\n"
            "- **Blocking risk:** minimal at both steps.\n"
            "- **Transaction behavior:** each step is transactional. Keep them in separate "
            "transactions -- combining them defeats the purpose entirely.\n"
            "- **Rollback:** step 1 rolls back cleanly. If step 2 fails, the constraint simply "
            "remains `NOT VALID` and can be validated again later; nothing is broken.\n"
            "- **Production considerations:** a `NOT VALID` constraint still enforces new "
            "writes, so leaving it unvalidated for a while is a legitimate intermediate state.\n\n"
            "---\n\n"
            "## Pattern 3 -- build alongside and swap (for rewrites)\n\n"
            "For anything classified as a full rewrite on a table too large to lock. The "
            "principle is to do all the expensive work on a copy nobody is using, then make "
            "the switch a millisecond metadata operation.\n\n"
            "1. Create the new table with the desired structure (empty, no traffic, no lock on "
            "the original).\n"
            "2. Create its indexes and constraints while it is still empty and cheap.\n"
            "3. Backfill in small committed batches -- never one large transaction, which "
            "would hold a long-running transaction, block vacuum cleanup everywhere, and "
            "generate one enormous WAL burst that spikes reader lag.\n"
            "4. Keep the copy current with ongoing writes via a trigger-based dual write or "
            "logical replication, active from before the backfill starts until after cutover.\n"
            "5. Validate row counts and checksums between the two, during a brief "
            "write-quiesce so both sides are compared at a consistent point.\n"
            "6. Swap with an atomic rename inside one short transaction with a lock timeout.\n"
            "7. Keep the old table (renamed, not dropped) for a rollback window.\n\n"
            "```sql\n"
            "-- Step 6, the only step that takes a strong lock. Typically milliseconds,\n"
            "-- because all the data work is already done.\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '5s';\n"
            "  ALTER TABLE public.orders RENAME TO orders_pre_change_backup;\n"
            "  ALTER TABLE public.orders_new RENAME TO orders;\n"
            "COMMIT;\n"
            "```\n\n"
            "- **Lock level:** `AccessExclusiveLock` for the rename only, held for "
            "milliseconds.\n"
            "- **Blocking risk:** confined to that one short transaction. In-flight queries "
            "wait or fail fast, then succeed immediately after commit.\n"
            "- **Transaction behavior:** the swap must be one atomic transaction so there is "
            "never a moment with no `orders` table.\n"
            "- **Rollback:** rename back. This is why the original is renamed rather than "
            "dropped, and why it should be kept for a full rollback window before cleanup.\n"
            "- **Production considerations:** the full pattern with backfill, sync, and "
            "validation is documented step by step in the partitioning category's "
            "large-table migration runbook -- the mechanics are identical whether the goal is "
            "partitioning or a column type change.\n\n"
            "---\n\n"
            "## Always, for every pattern\n\n"
            "- Run `03_current_lock_activity.sql` and `04_long_running_transactions.sql` "
            "immediately before executing, not an hour earlier.\n"
            "- Have a second session open and ready to cancel the statement if the application "
            "starts stalling.\n"
            "- Never issue production DDL without `lock_timeout`.\n"
            "- Re-run `02_dependent_objects_inventory.sql` afterwards and confirm nothing was "
            "left invalid or unvalidated.\n"
        ),
        "Choose the pattern from the classification in script 05 and do not improvise a fourth one. Pattern 1 covers most schema changes and is safe during trading hours as long as the lock timeout is set. Pattern 2 exists specifically so that constraint additions never need a blocking scan, and there is no production situation where the one-step form is preferable. Pattern 3 is a migration project rather than a statement -- if your change needs it, plan it as such. Substitute your real schema, table, column, and constraint names into every template before running anything, and execute one statement at a time with a second session standing by to cancel.",
        prerequisites=_DDL_PREREQ,
        related_scripts="05_lock_level_and_rewrite_reference.md, 03_current_lock_activity.sql",
        expected_runtime="Milliseconds for pattern 1; minutes to hours for pattern 2's validation; days for a pattern 3 migration.",
        table_purpose="Guarded DDL runbook: safe execution patterns for large-table schema changes.",
    ),
]


# ---------------------------------------------------------------------------
# 5. column-type-change
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="column-type-change",
    title="Changing a Column Type on a Production Table",
    summary=(
        "A column's data type must change -- the classic case on an exchange "
        "being an `integer` surrogate key on the trades or ledger table "
        "approaching the two-billion ceiling and needing to become `bigint`, "
        "or a `numeric` price column needing more scale. `ALTER TABLE ... "
        "ALTER COLUMN ... TYPE` is deceptively short for what it does: for "
        "most type changes it rewrites every row of the table and rebuilds "
        "every index, holding an `AccessExclusiveLock` throughout, which on a "
        "large exchange table is an outage measured in hours. A small number "
        "of type changes are metadata-only and genuinely instant. This "
        "workflow establishes which category your change falls into, "
        "inventories everything that depends on the column, and provides the "
        "online add-column-and-swap pattern for the cases where a rewrite is "
        "not acceptable."
    ),
    symptoms=[
        "An `integer` primary key or foreign key column is approaching the 2,147,483,647 ceiling on a high-volume table.",
        "A `numeric` or `decimal` price or amount column needs more precision or scale to support a new instrument.",
        "A `varchar(n)` column needs a larger length limit, or needs to become unbounded `text`.",
        "A timestamp column without time zone needs to become `timestamptz` after a timezone-correctness bug.",
        "An `ALTER COLUMN ... TYPE` was attempted and had to be cancelled because it blocked the application.",
        "Application inserts are failing with 'integer out of range' -- at which point the change is no longer optional and the sequence ceiling has already been reached.",
    ],
    business_impact=[
        "An integer key exhausting its range causes hard insert failures -- on a trades or ledger table that means the exchange cannot record activity, which is a full trading outage.",
        "A naive rewrite of a large table holds an exclusive lock for hours, which is itself a full outage on that table.",
        "A rewrite doubles storage for its duration and generates WAL proportional to the whole table, spiking reader lag and permanently raising the Aurora volume high-water mark.",
        "Precision changes on financial columns carry correctness risk: a wrong scale on an amount column is a reconciliation and regulatory problem, not just a schema one.",
    ],
    root_causes=[
        "N/A -- this is a planned change workflow. The urgency usually comes from an approaching range limit or a correctness requirement.",
    ],
    investigation_strategy=[
        "Inventory the column's current definition precisely: exact type, modifiers, nullability, default, identity or generated status.",
        "Inventory every dependent object -- indexes on the column, constraints referencing it, incoming foreign keys, views, triggers -- because each must be recreated or revalidated.",
        "Measure the table so the rewrite duration, and therefore the lock duration, can be estimated honestly.",
        "Classify the change against the rewrite reference to determine whether it is metadata-only or a full rewrite.",
        "For a metadata-only change, execute it directly with a lock timeout. For a rewrite, use the online add-and-swap pattern.",
        "Validate afterwards that the column has the intended type, that no index was left invalid, and that dependent views still work.",
    ],
    prerequisites=[
        "Table ownership; `pg_monitor` for the investigation scripts.",
        "Certainty about the target type, including precision and scale -- on financial columns this must be confirmed with the owning team, not inferred.",
        "For a rewrite: enough free storage for a full second copy, and acceptance that the Aurora volume high-water mark will rise permanently.",
        "For the online pattern: a maintenance window for the final swap only, plus time for the backfill to run online.",
    ],
    interpretation_guide=[
        "The decisive question is whether the change requires a rewrite. PostgreSQL skips the rewrite only when the new type is binary-coercible from the old one and no constraint needs rechecking.",
        "Metadata-only, genuinely instant: `varchar(n)` to a *larger* `varchar(m)`, `varchar(n)` to `text`, `numeric(p,s)` to a `numeric` with greater precision and the same scale, and `timestamp` to `timestamptz` *only* when the session `TimeZone` is UTC.",
        "Full rewrite: `integer` to `bigint`, any *narrowing* change, any numeric scale change, `text` to `varchar(n)`, and almost anything involving a `USING` expression.",
        "`integer` to `bigint` is the single most common case on an exchange and it always rewrites. There is no shortcut, which is exactly why the online add-and-swap pattern exists and why this change must be started long before the ceiling is reached.",
        "A rewrite rebuilds every index on the table as well as the heap, so a table with a dozen indexes takes far longer than its heap size alone suggests.",
        "Every dependent view must be dropped and recreated around a type change, because a view records the type of each output column. Materialized views additionally need repopulating.",
        "Incoming foreign keys referencing the changed column must have their referencing columns changed to a compatible type too -- and that means a coordinated change across every child table, which is usually the real scope of the work.",
        "If the column is fed by a sequence that is itself approaching its ceiling, the sequence needs attention as well; changing the column type does not widen the sequence.",
    ],
    remediation_immediate=[
        "If inserts are already failing with an out-of-range error, this is a live outage. The immediate mitigation is usually to reduce write pressure while the emergency change is planned -- there is no fast, safe fix at that point, which is why the change must be started with months of headroom.",
        "If an `ALTER COLUMN ... TYPE` is currently running and blocking the application, cancel it. A rewrite is fully transactional, so cancellation rolls back cleanly and leaves nothing behind.",
    ],
    remediation_short_term=[
        "For a metadata-only change, execute it directly with a lock timeout -- it takes milliseconds.",
        "For a rewrite on a small or quiet table, execute it in a window with a lock timeout and a second session standing by.",
        "For a rewrite on a large table, begin the online add-and-swap pattern; the backfill runs for as long as it needs to without any downtime.",
    ],
    remediation_long_term=[
        "Use `bigint` for every surrogate key on a high-volume table from the outset. The storage difference is negligible next to the cost of retrofitting it under time pressure.",
        "Monitor sequence and integer-column headroom proactively so a ceiling is detected with months of runway, not days.",
        "Use `numeric` with explicit, generous precision for financial amounts and agree the scale at design time with the settlement and compliance teams.",
        "Standardize on `timestamptz` everywhere so timezone corrections never become a type-change project.",
    ],
    production_safety=[
        "All `.sql` scripts here are read-only. Every DDL statement lives in the `.md` runbooks.",
        "Never run `ALTER COLUMN ... TYPE` on a large production table without first classifying it as metadata-only or rewriting. Getting that wrong is the difference between milliseconds and hours of exclusive lock.",
        "Always set `lock_timeout`, even for a metadata-only change, so the statement cannot form a lock queue.",
        "The backfill in the online pattern must be batched and committed in chunks -- never a single `UPDATE` across the whole table, which holds a long-running transaction, blocks vacuum cleanup database-wide, and generates one enormous WAL burst.",
        "On financial columns, validate the data after any conversion. A scale truncation on an amount column is a silent correctness failure that reconciliation will find later and much more expensively.",
    ],
    escalation_criteria=[
        "An integer column is within weeks of its ceiling on a table on the trading path -- this is a pending outage and needs immediate prioritization above normal work.",
        "The change is to a financial amount or price column where precision or scale is affected -- compliance and settlement must sign off before execution.",
        "Incoming foreign keys from tables owned by other teams must change type in lockstep -- that coordination is the critical path and needs engineering leadership.",
        "The online pattern's validation step shows any row count or checksum mismatch -- halt immediately and do not cut over with unvalidated financial data.",
    ],
    related_issues=[
        "../large-table-ddl/README.md",
        "../add-column-large-table/README.md",
        "../ddl-lock-investigation/README.md",
        "../../concurrency-and-locking/ddl-blocking/README.md",
        "../../partitioning/partition-existing-large-table/README.md",
        "../../storage-and-capacity/table-growth/README.md",
    ],
    aurora_notes=[
        "A full table rewrite generates WAL proportional to the entire table, which every Aurora reader applies from the shared storage volume. On a large table expect significant reader lag for the duration and plan for stale customer-facing reads.",
        "The second copy created by a rewrite permanently raises the Aurora volume high-water mark even after the original is released. Budget for the peak.",
        "An Aurora failover during a rewrite rolls the whole statement back, since DDL is transactional. Nothing is corrupted, but hours of work are lost -- another argument for the online pattern on large tables.",
        "The online add-and-swap pattern keeps every step short, which makes it far more resilient to an unplanned Aurora failover than a single multi-hour rewrite.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_column_definition_inventory",
        "Reads the exact current definition of every column on the target table, including type modifiers, defaults, and identity status.",
        _COLUMN_INVENTORY_SQL,
        "Read data_type exactly as reported, including the modifiers -- the difference between numeric(18,8) and numeric(20,8) determines whether the change is instant or a full rewrite, and a description like 'the amount column' is not precise enough to classify. Check identity_kind and generated_kind: an identity column is backed by a sequence that may itself be near its ceiling, and a stored generated column has its own rewrite rules. storage_strategy matters for wide columns, since changing a type can change how values are TOASTed. Edit the schema_name and table_name variables at the top for your real target; names are compared only inside a WHERE clause here, so an absent table returns zero rows rather than failing.",
        related_scripts="02_dependent_objects_inventory.sql",
        table_purpose="Exact column definitions for the target table.",
    ),
    sql_script(
        "02", "02_dependent_objects_inventory",
        "Inventories every index, constraint, incoming foreign key, view, and trigger that depends on the target table.",
        _DEPENDENT_OBJECTS_SQL,
        "This list is the real scope of the change and it is almost always larger than expected. Every index on the changed column is rebuilt by a rewrite. Every dependent view must be dropped and recreated, because a view records the type of each of its output columns. Incoming foreign keys are the biggest item: if another table references the column you are widening, its referencing column must change type in lockstep, which means coordinating a simultaneous change across every child table and every team that owns one. Triggers are the quiet hazard in the online pattern -- a trigger on the table will fire during the backfill unless you account for it. Edit the schema_name and table_name variables at the top for your real target.",
        related_scripts="03_target_table_size.sql",
        table_purpose="Objects depending on the target table.",
    ),
    sql_script(
        "03", "03_target_table_size",
        "Measures the target table so the rewrite duration, and therefore the exclusive lock duration, can be estimated honestly.",
        sb.target_table_size_detail(),
        "If the change turns out to require a rewrite, this is the number that decides everything. A rewrite rebuilds the heap and every index, so multiply your intuition by index_count -- a table with a dozen indexes takes far longer than its heap size alone suggests. Be honest about the estimate: a rewrite that will hold an AccessExclusiveLock for two hours is a two-hour outage on that table, and there is no tuning that changes that. Any table where the answer is more than a few minutes should go straight to the online add-and-swap pattern in script 05 rather than looking for a way to make the rewrite faster.",
        related_scripts="04_type_change_rewrite_reference.md",
        table_purpose="Target table size for rewrite duration estimation.",
    ),
    md_script(
        "04", "04_type_change_rewrite_reference",
        "Reference classification of column type changes into metadata-only and full-rewrite, with the direct-execution runbook for the metadata-only cases.",
        (
            "## Which changes avoid a rewrite\n\n"
            "PostgreSQL skips the table rewrite only when the new type is binary-coercible\n"
            "from the old one and nothing needs rechecking. That is a short list.\n\n"
            "| Change | Rewrite? | Notes |\n"
            "|---|---|---|\n"
            "| `varchar(n)` to `varchar(m)` where m > n | **No** | Widening a length limit is metadata-only |\n"
            "| `varchar(n)` to `text` | **No** | Removing the limit is metadata-only |\n"
            "| `text` to `varchar(n)` | Yes | Every row must be length-checked |\n"
            "| `varchar(n)` to `varchar(m)` where m < n | Yes | Narrowing requires checking every value |\n"
            "| `numeric(p,s)` to `numeric(p2,s)` where p2 > p, same scale | **No** | Widening precision at the same scale is metadata-only |\n"
            "| `numeric(p,s)` to any different scale | Yes | Values must be rescaled |\n"
            "| `numeric` to `numeric` unconstrained | **No** | Removing the constraint is metadata-only |\n"
            "| `integer` to `bigint` | Yes | Different physical width -- always rewrites |\n"
            "| `bigint` to `integer` | Yes | Narrowing, and can fail on out-of-range values |\n"
            "| `timestamp` to `timestamptz` | **Only if** session `TimeZone` is UTC | Otherwise every value must be shifted |\n"
            "| Anything with a `USING` expression | Yes | The expression must be evaluated per row |\n\n"
            "**The most common exchange case, `integer` to `bigint` on a trades or ledger key,\n"
            "always rewrites.** There is no shortcut. That is precisely why it must be started\n"
            "months before the ceiling is reached, using the online pattern in script 05.\n\n"
            "---\n\n"
            "## Runbook for a metadata-only change\n\n"
            "Only for a change confirmed **No** in the rewrite column above.\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "\n"
            "  ALTER TABLE public.orders\n"
            "      ALTER COLUMN client_order_reference TYPE varchar(128);\n"
            "  -- Widening from varchar(64): metadata only, no scan, no rewrite.\n"
            "COMMIT;\n"
            "```\n\n"
            "- **Lock level:** `AccessExclusiveLock`, held for milliseconds.\n"
            "- **Blocking risk:** near zero with the timeout set. Without a timeout, a "
            "statement that cannot get its lock queues and stalls every later query on the "
            "table.\n"
            "- **Transaction behavior:** fully transactional; can be combined with other DDL "
            "in the same transaction.\n"
            "- **Rollback:** clean. `ROLLBACK` undoes it entirely, and a crash or failover "
            "does the same.\n"
            "- **Production considerations:** safe during trading hours. Dependent views "
            "still need dropping and recreating if they expose the column, so check "
            "`02_dependent_objects_inventory.sql` output even for a metadata-only change.\n\n"
            "If it fails with `canceling statement due to lock timeout`, that is correct\n"
            "behavior. Check `large-table-ddl` script 04 for long-running transactions and\n"
            "retry in a loop rather than raising the timeout.\n\n"
            "---\n\n"
            "## Checking headroom before an integer ceiling is reached\n\n"
            "Read-only, safe to run at any time. Run it on a schedule, not once:\n\n"
            "```sql\n"
            "-- How close is each sequence to its maximum? Run this monthly on any table\n"
            "-- taking exchange-scale insert volume. int4 tops out at 2,147,483,647; a table\n"
            "-- inserting ten million rows a day reaches that in under a year.\n"
            "SELECT schemaname, sequencename, last_value, max_value,\n"
            "       round(100.0 * last_value / NULLIF(max_value, 0), 2) AS pct_consumed\n"
            "FROM pg_sequences\n"
            "ORDER BY pct_consumed DESC NULLS LAST;\n"
            "```\n\n"
            "Anything above 50 percent consumed on a high-volume table should already have a\n"
            "widening project scheduled. Above 80 percent it is urgent, because the online\n"
            "pattern itself takes weeks on a large table.\n"
        ),
        "Classify the change here before doing anything else, and be exact about the type modifiers -- 'widening the amount column' is not a classification, numeric(18,8) to numeric(20,8) is. If the row says No, use the runbook in this file and the change takes milliseconds. If it says Yes and the table is anything but small, go to script 05; do not look for a way to make the rewrite faster, because there is not one. The sequence headroom query at the end is the one thing here that should be run routinely rather than during a change: reaching an integer ceiling on a live trades table is an outage with no fast fix, and the only real defense is finding it a year early.",
        safety=GUARDED_DDL,
        prerequisites="Scripts 01-03 completed so the exact column definition, dependencies, and table size are known.",
        related_scripts="05_online_column_type_change_runbook.md",
        expected_runtime="Milliseconds for a metadata-only change.",
        table_purpose="Rewrite classification for type changes, plus the metadata-only runbook.",
    ),
    md_script(
        "05", "05_online_column_type_change_runbook",
        "The guarded online add-and-swap runbook for a type change that requires a rewrite, avoiding any long exclusive lock.",
        (
            "## Principle\n\n"
            "A rewriting `ALTER COLUMN ... TYPE` holds an `AccessExclusiveLock` for its entire\n"
            "duration. The way around that is not to make the rewrite faster -- it is to do\n"
            "the expensive work in a new column that nobody is reading, and make the switch a\n"
            "millisecond metadata operation.\n\n"
            "The worked example below widens `public.trades.id` from `integer` to `bigint`,\n"
            "which is the canonical exchange case. Adapt names and types to your change.\n\n"
            "---\n\n"
            "## Step 1 -- add the new column\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "  ALTER TABLE public.trades ADD COLUMN id_new bigint;\n"
            "COMMIT;\n"
            "```\n\n"
            "- **Lock level:** `AccessExclusiveLock`, milliseconds. Adding a nullable column "
            "with no default is a catalog-only change on PostgreSQL 11 and later.\n"
            "- **Blocking risk:** near zero with the timeout.\n"
            "- **Rollback:** clean -- drop the column.\n\n"
            "## Step 2 -- keep the new column in sync for ongoing writes\n\n"
            "```sql\n"
            "CREATE OR REPLACE FUNCTION public.trades_sync_id_new() RETURNS trigger AS $$\n"
            "BEGIN\n"
            "    NEW.id_new := NEW.id;\n"
            "    RETURN NEW;\n"
            "END;\n"
            "$$ LANGUAGE plpgsql;\n"
            "\n"
            "CREATE TRIGGER trg_trades_sync_id_new\n"
            "    BEFORE INSERT OR UPDATE ON public.trades\n"
            "    FOR EACH ROW EXECUTE FUNCTION public.trades_sync_id_new();\n"
            "```\n\n"
            "- **Lock level:** `CREATE TRIGGER` takes a `ShareRowExclusiveLock` -- it blocks "
            "writes briefly but not reads. Schedule this one statement for a quieter moment "
            "and keep a lock timeout set.\n"
            "- **Blocking risk:** brief, writes only.\n"
            "- **Rollback:** drop the trigger and the function.\n"
            "- **Production considerations:** this trigger runs on every write to the table "
            "for the duration of the migration, so it must be trivially cheap. Measure its "
            "overhead on the write path before leaving it in place.\n\n"
            "## Step 3 -- backfill in batches\n\n"
            "```sql\n"
            "-- Repeat, advancing the watermark, until no rows remain. Keep each batch small\n"
            "-- enough to finish in well under a second. Never a single UPDATE across the\n"
            "-- whole table: that holds one long-running transaction (blocking vacuum cleanup\n"
            "-- database-wide) and produces one enormous WAL burst that spikes reader lag.\n"
            "UPDATE public.trades\n"
            "SET id_new = id\n"
            "WHERE id_new IS NULL\n"
            "  AND id BETWEEN :batch_start AND :batch_end;\n"
            "-- COMMIT after each batch. Monitor Aurora reader lag between batches and slow\n"
            "-- down if it climbs. Each updated row is a new row version, so dead tuples\n"
            "-- accumulate throughout -- let autovacuum keep up rather than racing it.\n"
            "```\n\n"
            "- **Lock level:** ordinary row locks only. No table-level blocking.\n"
            "- **Blocking risk:** low, but the write volume is real -- this is the step that "
            "generates the WAL and the dead tuples.\n"
            "- **Rollback:** abandon at any point; the new column is simply left partly "
            "populated and unused.\n"
            "- **Production considerations:** this step can safely take days on a very large "
            "table. Slower is safer, and there is no deadline until the ceiling itself.\n\n"
            "## Step 4 -- build the replacement index concurrently\n\n"
            "```sql\n"
            "CREATE UNIQUE INDEX CONCURRENTLY trades_pkey_new ON public.trades (id_new);\n"
            "```\n\n"
            "Not inside a transaction block. See the concurrent-index-build workflow for the\n"
            "full operational detail and the failure modes.\n\n"
            "## Step 5 -- validate before the swap\n\n"
            "```sql\n"
            "-- Read-only. Must return zero before proceeding. Run during a brief write\n"
            "-- quiesce so both columns are compared at a consistent point in time.\n"
            "SELECT count(*) AS rows_not_yet_synced\n"
            "FROM public.trades\n"
            "WHERE id_new IS DISTINCT FROM id;\n"
            "```\n\n"
            "**Do not proceed with a non-zero result.** On a financial table an unexplained\n"
            "mismatch is a data-integrity finding, not a migration inconvenience.\n\n"
            "## Step 6 -- swap\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '5s';\n"
            "\n"
            "  ALTER TABLE public.trades DROP CONSTRAINT trades_pkey;\n"
            "  ALTER TABLE public.trades ADD CONSTRAINT trades_pkey\n"
            "      PRIMARY KEY USING INDEX trades_pkey_new;\n"
            "\n"
            "  ALTER TABLE public.trades DROP COLUMN id;\n"
            "  ALTER TABLE public.trades RENAME COLUMN id_new TO id;\n"
            "\n"
            "  DROP TRIGGER trg_trades_sync_id_new ON public.trades;\n"
            "COMMIT;\n"
            "```\n\n"
            "- **Lock level:** `AccessExclusiveLock`, held for milliseconds -- every one of "
            "these is a catalog operation because all the data work is already done.\n"
            "- **Blocking risk:** confined to this one short transaction. In-flight queries "
            "wait or fail fast, then succeed immediately after commit.\n"
            "- **Transaction behavior:** must be one atomic transaction so there is never a "
            "moment where the table lacks a primary key or the column.\n"
            "- **Rollback:** `ROLLBACK` restores everything, since it is all one transaction. "
            "This is the strongest safety property of the whole pattern.\n"
            "- **Production considerations:** run it in the lowest-traffic window available "
            "despite being fast, because a brief connection-retry blip is still expected.\n\n"
            "## Step 7 -- afterwards\n\n"
            "- Recreate any dependent views identified in "
            "`02_dependent_objects_inventory.sql`.\n"
            "- Widen the backing sequence if there is one: "
            "`ALTER SEQUENCE public.trades_id_seq AS bigint;`\n"
            "- Coordinate the same widening on every child table with a foreign key "
            "referencing this column -- until that is done, the referencing columns are still "
            "`integer` and the ceiling problem has only moved.\n"
            "- Run `06_post_change_verification.sql` and confirm the new type and that no "
            "index was left invalid.\n"
            "- Vacuum the table: the batched backfill created one dead tuple per row.\n"
        ),
        "Work through the steps in order and treat step 5 as an absolute gate -- on a financial table a non-zero mismatch is a data-integrity finding and must be understood before the swap, never explained away to keep the migration moving. The pattern's key property is that every individual step is short and reversible, which is what makes it survivable on a 24/7 platform and resilient to an unplanned Aurora failover. Steps 1 through 5 run fully online and can take as long as they need; only step 6 takes a strong lock, and only for milliseconds. Substitute your real schema, table, column, and type names into every statement before running it.",
        prerequisites=_DDL_PREREQ,
        related_scripts="06_post_change_verification.sql, ../concurrent-index-build/README.md",
        expected_runtime="Days for the online backfill on a very large table; milliseconds for the final swap.",
        table_purpose="Guarded DDL runbook: online column type change via add-and-swap.",
    ),
    sql_script(
        "06", "06_post_change_verification",
        "Confirms the column now has the intended type and that no index or constraint was left invalid by the change.",
        _COLUMN_INVENTORY_SQL + "\n\n" + sb.invalid_indexes(),
        "Check data_type on the changed column reports exactly the type and modifiers you intended, including precision and scale -- a financial column that ended up with the wrong scale is a silent correctness failure that reconciliation will find later and far more expensively. Confirm not_null and default_expression survived the change, since both are easy to lose in an add-and-swap. The second result set must contain no index on this table: an INVALID index here means the concurrent build in step 4 of the runbook did not complete, and the table is now missing an index the planner needs. Finally, re-run the dependent objects inventory and confirm every view still resolves and every constraint is still validated.",
        related_scripts="02_dependent_objects_inventory.sql",
        table_purpose="Post-change column type and index validity verification.",
    ),
]


# ---------------------------------------------------------------------------
# 6. add-column-large-table
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="add-column-large-table",
    title="Adding a Column to a Large Table",
    summary=(
        "Adding a column to a large production table is the schema change "
        "most often assumed to be trivial, and most of the time it now is -- "
        "but the exceptions are severe and they are not obvious from the "
        "statement text. Since PostgreSQL 11, `ADD COLUMN` with a constant "
        "default is a catalog-only operation: the default is stored once in "
        "`pg_attribute` and materialized lazily as rows are updated, so the "
        "statement takes an `AccessExclusiveLock` for milliseconds regardless "
        "of table size. But a *volatile* default such as `now()` or "
        "`gen_random_uuid()`, a `GENERATED ALWAYS AS ... STORED` column, or "
        "adding `NOT NULL` in the same statement without a default, each "
        "force a full table rewrite that holds that lock for hours on an "
        "exchange-scale table. This workflow tells the two cases apart before "
        "the statement is run, not after."
    ),
    symptoms=[
        "A feature requires a new column on orders, trades, wallets, or ledger_entries.",
        "A previous `ADD COLUMN` on a large table unexpectedly blocked the application for a long period.",
        "A migration is being reviewed and it is unclear whether it will rewrite the table.",
        "A column needs both a default and a `NOT NULL` constraint, and the safe ordering is not obvious.",
        "A computed column is wanted and the choice between a stored generated column and an application-maintained one has not been made.",
    ],
    business_impact=[
        "A rewriting `ADD COLUMN` on the orders table blocks all reads and writes for the duration -- a full trading outage on that table.",
        "The same statement doubles the table's storage for its duration and permanently raises the Aurora volume high-water mark.",
        "A rewrite generates WAL proportional to the whole table, spiking reader lag and causing customer-facing stale reads.",
        "Conversely, refusing to add columns at all because of a bad past experience blocks product delivery unnecessarily, since the safe form really is safe.",
    ],
    root_causes=[
        "N/A -- this is a planned change workflow. The risk comes entirely from which form of `ADD COLUMN` is used.",
    ],
    investigation_strategy=[
        "Measure the table so the cost of the rewrite form is known in concrete terms, not as an abstraction.",
        "Inventory the existing columns, including which earlier additions used a fast default, to confirm the table is in a normal state.",
        "Classify the intended statement against the semantics reference: constant default, volatile default, generated, or `NOT NULL`.",
        "Check the current lock picture immediately before executing.",
        "Execute the safe form through the runbook, splitting default and `NOT NULL` into separate steps where needed.",
        "Verify afterwards that the column exists with the intended definition and that a fast default was used where expected.",
    ],
    prerequisites=[
        "Table ownership; `pg_monitor` for the investigation scripts.",
        "The exact intended column definition, including type, default expression, and nullability -- the default expression in particular decides everything.",
        "Awareness of the PostgreSQL version's behavior: the fast-default optimization exists from PostgreSQL 11, so it is available on Aurora PostgreSQL 17.",
    ],
    interpretation_guide=[
        "The decisive question is whether the default expression is constant. `DEFAULT 0`, `DEFAULT false`, `DEFAULT 'pending'` are constant and use the fast path. `DEFAULT now()`, `DEFAULT gen_random_uuid()`, `DEFAULT random()` are volatile, must be evaluated per row, and force a full rewrite.",
        "`ADD COLUMN ... NOT NULL` with no default fails outright if the table has any rows, because existing rows would violate it. `ADD COLUMN ... NOT NULL DEFAULT <constant>` works and is still fast-path on PostgreSQL 11 and later.",
        "`GENERATED ALWAYS AS (...) STORED` always rewrites -- the value must be computed and physically stored for every existing row. If the table is large, add a plain column and backfill it in batches instead.",
        "A column added with a fast default shows `atthasmissing = true` in `pg_attribute`. That flag is the proof the optimization was actually used, and it is how you verify after the fact rather than assuming.",
        "`DROP COLUMN` is also catalog-only -- it marks the column dropped without touching the rows. The space is reclaimed lazily by vacuum as rows are rewritten for other reasons, so do not expect an immediate size reduction.",
        "Adding a column with a fast default does not slow down reads: PostgreSQL substitutes the missing value transparently when it reads a row written before the column existed.",
        "On a partitioned table, `ADD COLUMN` on the parent recurses to every partition and locks all of them in one transaction. The fast path still applies per partition, but the lock footprint is the whole table.",
    ],
    remediation_immediate=[
        "If a rewriting `ADD COLUMN` is currently running and blocking the application, cancel it. The statement is fully transactional, so it rolls back cleanly and leaves nothing behind.",
    ],
    remediation_short_term=[
        "Replace a volatile default with a constant default plus a batched backfill -- this converts a multi-hour blocking rewrite into a millisecond change plus an online backfill.",
        "Split `ADD COLUMN` and `SET NOT NULL` into separate steps, using the validated-check pattern so the `NOT NULL` never needs a blocking scan.",
        "Replace a stored generated column with a plain column maintained by the application or a trigger, if the table is too large for the rewrite.",
    ],
    remediation_long_term=[
        "Add a migration review rule: any `ADD COLUMN` with a non-constant default or a `GENERATED ... STORED` clause is rejected on tables above an agreed size threshold.",
        "Standardize on constant defaults plus backfill as the house pattern, so the safe form is the habitual one.",
        "Keep the largest tables partitioned so even a rewriting change can be applied one partition at a time.",
    ],
    production_safety=[
        "All `.sql` scripts here are read-only. The DDL lives in the `.md` runbooks.",
        "Always set `lock_timeout` before the statement, even for the fast form, so it cannot form a lock queue while waiting.",
        "Never add a column with a volatile default to a large table in a single statement. Split it.",
        "The backfill that replaces a volatile default must be batched and committed in chunks, never one `UPDATE` across the whole table.",
        "On a partitioned table, confirm the recursion behavior before running anything against the parent.",
    ],
    escalation_criteria=[
        "The proposed statement requires a rewrite on a table on the live trading path and the owning team is pushing to run it as-is.",
        "The column is a financial field whose default value affects settlement or reconciliation logic -- that needs compliance review, not just a DBA.",
        "The table is partitioned with a large number of partitions, making even the fast form a wide lock footprint.",
        "An earlier `ADD COLUMN` on this table caused an incident whose cause was never established -- resolve that before adding another.",
    ],
    related_issues=[
        "../large-table-ddl/README.md",
        "../column-type-change/README.md",
        "../ddl-lock-investigation/README.md",
        "../../concurrency-and-locking/ddl-blocking/README.md",
        "../../storage-and-capacity/table-growth/README.md",
        "../../partitioning/partition-existing-large-table/README.md",
    ],
    aurora_notes=[
        "The PostgreSQL 11 fast-default optimization is fully available on Aurora PostgreSQL 17, so a constant-default `ADD COLUMN` really is a millisecond operation regardless of table size.",
        "A rewriting `ADD COLUMN` generates WAL proportional to the whole table, which every Aurora reader must apply from the shared storage volume -- expect significant reader lag throughout.",
        "The temporary second copy created by a rewrite permanently raises the Aurora volume high-water mark even after the original is released.",
        "An Aurora failover during a rewriting `ADD COLUMN` rolls the statement back entirely. Nothing is corrupted, but the work is lost -- another reason to prefer the fast form plus backfill.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_target_table_size_and_state",
        "Measures the target table so the cost of the rewriting form is understood in concrete terms before a form is chosen.",
        sb.target_table_size_detail(),
        "This number only matters if the statement turns out to be a rewriting one -- but that is exactly why it should be read first, because an abstract 'it might rewrite' does not change behavior while 'it will hold an exclusive lock on this table for ninety minutes' does. Multiply your intuition by index_count, since a rewrite rebuilds every index as well as the heap. Any result above a few minutes means the volatile-default and generated-column forms are off the table entirely and the runbook's split pattern is mandatory. Edit the schema_name and table_name variables at the top for your real target.",
        related_scripts="02_existing_column_inventory.sql",
        table_purpose="Target table size and maintenance state.",
    ),
    sql_script(
        "02", "02_existing_column_inventory",
        "Inventories the table's current columns, including which earlier additions used a PostgreSQL fast default.",
        _COLUMN_INVENTORY_SQL,
        "Two things to look for. First, confirm the column you intend to add does not already exist under a similar name, which is a surprisingly common finding on tables that several teams have extended independently. Second, read the uses_fast_default column: a true value means that column was added with a constant default and the value is stored once in the catalog rather than written into every row. Seeing existing true values here confirms the optimization is available and working on this table, which is useful reassurance before relying on it. Also note any generated_kind value, since a stored generated column already on the table tells you someone has previously accepted a rewrite here. Edit the schema_name and table_name variables at the top for your real target.",
        related_scripts="03_add_column_semantics_reference.md",
        table_purpose="Existing column definitions and fast-default usage.",
    ),
    sql_script(
        "03", "03_current_lock_activity",
        "Shows the current lock picture and long-running transactions immediately before the statement is executed.",
        sb.ddl_lock_waits() + "\n\n" + sb.long_running_transactions(),
        "Run this in the minute before executing, not earlier -- the lock picture changes constantly on a busy exchange database. Even the fast form of ADD COLUMN needs an AccessExclusiveLock, and if it cannot get one immediately it queues, and every subsequent query on the table queues behind it. A long-running transaction holding any lock on the target table will cause exactly that. Clear the blockers or wait for a clean moment, and always execute with a lock timeout so that a failure to acquire is harmless rather than an application stall.",
        related_scripts="04_add_column_execution_runbook.md",
        execution_location=WRITER_PREFERRED,
        table_purpose="Lock waits and long-running transactions before execution.",
    ),
    md_script(
        "04", "04_add_column_semantics_reference",
        "Reference classification of every ADD COLUMN form by rewrite behavior, with the reasoning behind the PostgreSQL fast-default optimization.",
        (
            "## Which forms rewrite the table\n\n"
            "| Statement form | Rewrites? | Lock hold | Notes |\n"
            "|---|---|---|---|\n"
            "| `ADD COLUMN c type` | **No** | Milliseconds | Nullable, no default -- always cheap |\n"
            "| `ADD COLUMN c type DEFAULT <constant>` | **No** (PG11+) | Milliseconds | Default stored once in `pg_attribute`, materialized lazily |\n"
            "| `ADD COLUMN c type NOT NULL DEFAULT <constant>` | **No** (PG11+) | Milliseconds | The constant default satisfies `NOT NULL` for existing rows |\n"
            "| `ADD COLUMN c type NOT NULL` (no default) | Fails | n/a | Rejected outright if the table has any rows |\n"
            "| `ADD COLUMN c type DEFAULT now()` | **Yes** | Whole rewrite | Volatile -- must be evaluated per row |\n"
            "| `ADD COLUMN c type DEFAULT gen_random_uuid()` | **Yes** | Whole rewrite | Volatile, and each row needs a distinct value |\n"
            "| `ADD COLUMN c type GENERATED ALWAYS AS (...) STORED` | **Yes** | Whole rewrite | Value must be computed and stored for every existing row |\n"
            "| `ADD COLUMN c type GENERATED ... AS IDENTITY` | **Yes** | Whole rewrite | Every existing row needs a distinct identity value |\n"
            "| `ADD COLUMN c type REFERENCES other(id)` | No rewrite, but scans | Scan duration | Validates every existing row; use the `NOT VALID` two-step instead |\n\n"
            "## Why the fast path works\n\n"
            "Before PostgreSQL 11, adding a column with a default meant writing the value into "
            "every existing row -- a full rewrite. From PostgreSQL 11, a **constant** default "
            "is stored once in the `pg_attribute` catalog row for that column "
            "(`atthasmissing = true`, value in `attmissingval`). When a query reads a row "
            "written before the column existed, PostgreSQL substitutes that stored value "
            "transparently. Existing rows are never touched; they acquire a real physical "
            "value only if and when they are updated for some other reason.\n\n"
            "This means:\n\n"
            "- The statement is O(1) in table size. A 5 GB table and a 5 TB table take the "
            "same few milliseconds.\n"
            "- There is no read penalty afterwards -- the substitution is part of normal tuple "
            "deforming.\n"
            "- You can verify the optimization was used by checking `atthasmissing` in "
            "`06_post_change_verification.sql`, rather than assuming it.\n\n"
            "The optimization applies only to a **constant** default. `now()` is not constant "
            "(each row conceptually gets its own evaluation), so it falls back to the rewrite "
            "path -- and the statement text gives no hint that it has done so, which is why "
            "this classification must happen at review time.\n\n"
            "## `DROP COLUMN` for comparison\n\n"
            "`DROP COLUMN` is also catalog-only: the column is marked dropped and its data is "
            "ignored, but the bytes stay in every existing row until that row is rewritten for "
            "another reason. Storage is therefore reclaimed gradually by vacuum, not "
            "immediately -- do not expect a size drop after dropping a wide column from a "
            "large table.\n\n"
            "- **Lock level:** `AccessExclusiveLock`, milliseconds.\n"
            "- **Blocking risk:** near zero with a lock timeout.\n"
            "- **Rollback:** clean, but be aware that any dependent view or index on the "
            "column is dropped with it and `CASCADE` will silently take more than you "
            "expect -- check `large-table-ddl` script 02 first.\n"
        ),
        "Classify the exact statement text here before it reaches a change ticket, because the difference between the safe form and the rewriting form is a single expression in the default clause and is invisible to anyone skim-reading the migration. The practical rule for a large table is short: constant defaults only, never a volatile default, never GENERATED ... STORED, and never an identity column added to a populated table. Where the requirement genuinely needs a per-row value, the runbook in script 05 shows how to get it with a constant default plus a batched online backfill instead.",
        safety=GUARDED_DDL,
        expected_impact="None by itself -- this is a reference document. The statements it classifies have the impacts described per row.",
        prerequisites="Scripts 01-03 completed so the table size, existing columns, and lock state are known.",
        related_scripts="05_add_column_execution_runbook.md",
        expected_runtime="Not applicable -- reference document.",
        table_purpose="Rewrite classification for every ADD COLUMN form.",
    ),
    md_script(
        "05", "05_add_column_execution_runbook",
        "The guarded DDL runbook for adding a column safely, including how to get a per-row default value without a rewrite.",
        (
            "## Pattern A -- the safe form (constant or no default)\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "\n"
            "  ALTER TABLE public.orders\n"
            "      ADD COLUMN settlement_status text NOT NULL DEFAULT 'pending';\n"
            "COMMIT;\n"
            "```\n\n"
            "- **Lock level:** `AccessExclusiveLock`, held for milliseconds regardless of "
            "table size.\n"
            "- **Blocking risk:** near zero with the timeout set. Without it, the statement can "
            "queue behind a long-running transaction and stall every later query on the "
            "table -- the classic 'a trivial migration took the site down' incident.\n"
            "- **Transaction behavior:** fully transactional and combinable with other DDL.\n"
            "- **Rollback:** clean. `ROLLBACK`, a crash, or an Aurora failover all leave no "
            "trace.\n"
            "- **Production considerations:** safe during trading hours. If it fails with "
            "`canceling statement due to lock timeout`, that is the system protecting you -- "
            "retry in a loop rather than raising the timeout.\n\n"
            "---\n\n"
            "## Pattern B -- a per-row value without a rewrite\n\n"
            "When the requirement is really 'every row needs its own value' -- a creation "
            "timestamp, a generated identifier -- do not use a volatile default. Split it "
            "into a cheap DDL step and an online backfill.\n\n"
            "```sql\n"
            "-- Step 1: add the column with NO default. Milliseconds, catalog only.\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "  ALTER TABLE public.deposits ADD COLUMN external_ref uuid;\n"
            "COMMIT;\n"
            "\n"
            "-- Step 2: set the default for NEW rows only. Also catalog only.\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "  ALTER TABLE public.deposits ALTER COLUMN external_ref SET DEFAULT gen_random_uuid();\n"
            "COMMIT;\n"
            "\n"
            "-- Step 3: backfill existing rows in small committed batches. Never one UPDATE\n"
            "-- across the whole table: that holds a long-running transaction (blocking vacuum\n"
            "-- cleanup database-wide), produces one enormous WAL burst that spikes Aurora\n"
            "-- reader lag, and creates a dead tuple for every row at once.\n"
            "UPDATE public.deposits\n"
            "SET external_ref = gen_random_uuid()\n"
            "WHERE external_ref IS NULL\n"
            "  AND id BETWEEN :batch_start AND :batch_end;\n"
            "-- COMMIT after each batch, advance the watermark, repeat. Monitor reader lag and\n"
            "-- dead tuple growth between batches and slow down if either climbs.\n"
            "```\n\n"
            "- **Lock level:** steps 1 and 2 take `AccessExclusiveLock` for milliseconds; step "
            "3 takes ordinary row locks only.\n"
            "- **Blocking risk:** minimal at every step. The backfill's real cost is WAL "
            "volume and dead tuples, not locking.\n"
            "- **Transaction behavior:** keep the three steps in separate transactions; the "
            "backfill must commit per batch.\n"
            "- **Rollback:** steps 1 and 2 roll back cleanly. The backfill can be abandoned "
            "part-way, leaving the column partly populated and no harm done.\n"
            "- **Production considerations:** the backfill can safely take days. There is no "
            "deadline and slower is safer.\n\n"
            "---\n\n"
            "## Pattern C -- adding NOT NULL after the fact\n\n"
            "If the column was added nullable and must become `NOT NULL` once backfilled, do "
            "not use a bare `SET NOT NULL` on a large table -- it scans every row while "
            "holding `AccessExclusiveLock`. Use the validated-check pattern instead:\n\n"
            "```sql\n"
            "-- Step 1: cheap constraint, no scan. AccessExclusiveLock for milliseconds.\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "  ALTER TABLE public.deposits\n"
            "      ADD CONSTRAINT deposits_external_ref_nn\n"
            "      CHECK (external_ref IS NOT NULL) NOT VALID;\n"
            "COMMIT;\n"
            "\n"
            "-- Step 2: scan without blocking. ShareUpdateExclusiveLock -- reads and writes\n"
            "-- both continue normally. Takes as long as it needs.\n"
            "ALTER TABLE public.deposits VALIDATE CONSTRAINT deposits_external_ref_nn;\n"
            "\n"
            "-- Step 3: PostgreSQL 12+ uses the validated CHECK to prove no NULLs exist, so\n"
            "-- SET NOT NULL skips its own scan entirely and is a metadata operation.\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "  ALTER TABLE public.deposits ALTER COLUMN external_ref SET NOT NULL;\n"
            "  ALTER TABLE public.deposits DROP CONSTRAINT deposits_external_ref_nn;\n"
            "COMMIT;\n"
            "```\n\n"
            "- **Rollback:** each step is independently reversible. If step 2 finds a NULL it "
            "fails and the constraint simply remains `NOT VALID` -- nothing is broken, and you "
            "have learned the backfill is incomplete.\n\n"
            "---\n\n"
            "## Partitioned tables\n\n"
            "`ADD COLUMN` on a partitioned parent recurses into every partition and holds "
            "`AccessExclusiveLock` on all of them in a single transaction. The fast-default "
            "optimization still applies per partition, so the operation remains fast, but the "
            "lock footprint is the entire table at once. On a table with hundreds of "
            "partitions, run it with a short lock timeout in the quietest window available and "
            "be ready to retry.\n"
        ),
        "Use Pattern A whenever the default is constant or absent -- that covers most real requirements and is safe during trading hours with the lock timeout set. Reach for Pattern B the moment someone asks for now() or gen_random_uuid() as a default on a large table; it delivers the same end state with no blocking rewrite. Pattern C exists so that tightening to NOT NULL never needs a blocking scan, and there is no production case where the bare SET NOT NULL is preferable. Substitute your real schema, table, column, and default values into every template before running anything.",
        prerequisites=_DDL_PREREQ,
        related_scripts="04_add_column_semantics_reference.md, 06_post_change_verification.sql",
        expected_runtime="Milliseconds for the DDL steps; hours to days for an online backfill on a very large table.",
        table_purpose="Guarded DDL runbook: adding a column without a rewrite.",
    ),
    sql_script(
        "06", "06_post_change_verification",
        "Confirms the new column exists with the intended definition and that the fast-default optimization was actually used.",
        _COLUMN_INVENTORY_SQL,
        "Find the new column and check three things. data_type must be exactly what you intended, including modifiers. not_null and default_expression must match the change ticket -- it is easy to end up with the default but not the constraint, or the reverse, when the steps are split. Most importantly, uses_fast_default should be true if you added the column with a constant default: that flag is the catalog's own confirmation that PostgreSQL stored the default once rather than writing it into every row, which is the difference between a millisecond change and a full rewrite. If it is false on a column you expected to be fast, the statement took the rewrite path and you should understand why before the next migration takes the same route. Edit the schema_name and table_name variables at the top for your real target.",
        related_scripts="02_existing_column_inventory.sql",
        table_purpose="Post-change column definition and fast-default verification.",
    ),
]


# ---------------------------------------------------------------------------
# 7. add-index-large-table
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="add-index-large-table",
    title="Adding an Index to a Large Table",
    summary=(
        "An index is needed on a table large enough that the build itself is "
        "a production event: hours of elapsed time, substantial redo, "
        "sustained Aurora reader lag, and a permanent increase in write "
        "amplification on every subsequent insert and update. This workflow "
        "is deliberately more sceptical than safe-index-creation. Before "
        "committing to the build it asks whether the index is justified at "
        "all -- is there real evidence of the sequential scans it would "
        "eliminate, is the access pattern already covered by an existing "
        "index's leading columns, and is the table's write rate high enough "
        "that the ongoing maintenance cost outweighs the query benefit. Only "
        "then does it cover the build, which on a table this size must always "
        "be concurrent and should usually be partial."
    ),
    symptoms=[
        "A query against a multi-hundred-gigabyte table is doing a sequential scan and the latency is no longer acceptable.",
        "A foreign key on a large child table has no supporting index, so parent deletes scan the whole child.",
        "Query latency on a large table is degrading steadily as the table grows, with no plan change.",
        "A new reporting or compliance requirement introduces an access pattern the current index set does not serve.",
        "A previous attempt to build an index on this table was abandoned because of its duration or its impact on reader lag.",
    ],
    business_impact=[
        "Sequential scans on a large exchange table consume disproportionate I/O and buffer cache, degrading latency for every other query on the instance, not just the slow one.",
        "The build itself generates hours of sustained redo, raising Aurora reader lag and risking customer-visible stale balances and order states.",
        "Every index permanently increases write amplification on the table's insert and update path, which on the trading path is the most latency-sensitive operation the exchange performs.",
        "The index permanently raises the Aurora volume high-water mark, and dropping it later does not reduce the bill.",
    ],
    root_causes=[
        "N/A -- this is a planned change workflow. The evidence for the change comes from query-optimization and tables-and-indexes.",
    ],
    investigation_strategy=[
        "Establish the evidence: which tables are actually suffering from sequential scans, and how expensive those scans are.",
        "Check whether the access pattern is already covered by an existing index's leading columns -- a surprising proportion of proposed indexes are redundant.",
        "Measure the table's write volume, because that is what determines the ongoing cost of the new index rather than its one-off build cost.",
        "Measure the table's size to estimate build duration and storage impact.",
        "Build concurrently through the runbook, considering a partial or covering index rather than a plain one.",
        "Monitor the build, then confirm afterwards that the index is valid and is actually being used.",
    ],
    prerequisites=[
        "Concrete evidence that the index is needed -- a specific slow query with a plan showing the sequential scan, named in the change ticket.",
        "Table ownership or `MAINTAIN` privilege for the build; `pg_monitor` for the investigation.",
        "`pg_stat_statements` is helpful for identifying the queries involved but is not required by these scripts.",
        "Enough free storage for the new index, and acceptance that the Aurora volume high-water mark rises permanently.",
    ],
    interpretation_guide=[
        "A high `seq_scan` count alone is not evidence. Small lookup tables are scanned sequentially by design and that is faster than an index. What matters is `seq_tup_read` relative to table size -- large numbers of rows read per scan on a large table is the pattern worth fixing.",
        "Check the existing index list before accepting that a new index is needed. PostgreSQL uses a multi-column index for queries filtering only on its leading columns, so an index on `(account_id, executed_at)` already serves a filter on `account_id` alone.",
        "Write volume determines the ongoing cost. On a table taking millions of inserts a day, each additional index is millions of extra index entries written, WAL-logged, replicated, and vacuumed daily -- forever. Weigh that against the query benefit explicitly rather than assuming the index is free.",
        "A low `pct_hot_updates` on the target table is a warning: the new index may make it worse. Every additional index reduces the chance of a HOT update, because HOT requires that no indexed column changed and that the new row version fits on the same page.",
        "A partial index is usually the right answer on a large table. An index on open orders is a tiny fraction of the size of one on all orders, builds in a fraction of the time, and costs far less to maintain -- because rows outside the predicate are not indexed at all.",
        "A covering index with `INCLUDE` can turn a heap fetch into an index-only scan, but it makes the index larger and is only worth it when the query genuinely returns those columns.",
        "Estimate build duration from table size, then double or triple it for the concurrent form, which makes two passes plus two waits for older transactions.",
    ],
    remediation_immediate=[
        "If a build is causing customer-visible reader lag, cancel it and clean up the INVALID index afterwards. Lag affecting customers outranks a query improvement.",
    ],
    remediation_short_term=[
        "Build the index concurrently through the runbook, preferring a partial index where the workload only queries a subset.",
        "Verify after the build that the query actually uses the new index -- if it does not, drop it rather than leaving a permanent write cost with no benefit.",
        "If the build is not viable at this size, consider whether partitioning the table first makes both this index and every future one cheaper.",
    ],
    remediation_long_term=[
        "Partition the largest tables so index builds are per-partition operations rather than whole-table events.",
        "Review the full index set on the table as a unit whenever adding to it, rather than only evaluating the new index in isolation.",
        "Track index usage over time so indexes that stop earning their keep are found and removed.",
    ],
    production_safety=[
        "All `.sql` scripts here are read-only. The build DDL lives in the `.md` runbook.",
        "On a table this size, only the concurrent build form is acceptable. A plain `CREATE INDEX` would block every write for hours.",
        "`CREATE INDEX CONCURRENTLY` cannot run inside a transaction block, and most migration frameworks open one implicitly -- verify before starting.",
        "Monitor Aurora reader lag throughout the build and be prepared to cancel. Plan for the cleanup a cancellation requires before you begin.",
        "Do not start a build immediately before a known market event, a deployment, or a scheduled failover test.",
    ],
    escalation_criteria=[
        "The build's estimated duration spans a market event or a scheduled deployment window.",
        "Reader lag during the build reaches a level that affects customer-facing reads -- treat as an incident and cancel.",
        "The table is large enough that the build cannot realistically complete in any acceptable window, which means the answer is partitioning rather than indexing.",
        "The proposed index would be the tenth or more on a table on the trading path -- that needs an index-set review, not another addition.",
    ],
    related_issues=[
        "../concurrent-index-build/README.md",
        "../safe-index-creation/README.md",
        "../failed-index-build/README.md",
        "../drop-index-safely/README.md",
        "../../tables-and-indexes/missing-index-candidates/README.md",
        "../../tables-and-indexes/sequential-scan-investigation/README.md",
        "../../storage-and-capacity/index-growth/README.md",
        "../../query-optimization/inefficient-index-usage/README.md",
    ],
    aurora_notes=[
        "A large index build generates sustained redo against the Aurora shared storage volume, which every reader applies. Monitor CloudWatch `AuroraReplicaLag` throughout and treat customer-visible lag as grounds to cancel.",
        "The new index permanently raises the Aurora volume high-water mark. Dropping it later frees space for reuse but does not reduce billed storage.",
        "`SET maintenance_work_mem` at session level is the least invasive way to give one build more memory on Aurora, and keeping the build's sort in memory materially shortens the exposure window.",
        "An Aurora failover during the build aborts it and leaves an INVALID index on the new writer -- budget for that possibility on a build measured in hours.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_sequential_scan_evidence",
        "Establishes whether there is real evidence of expensive sequential scans justifying a new index on a large table.",
        sb.sequential_scan_heavy_tables(),
        "This is the evidence step and it should be allowed to say no. A high seq_scan count by itself proves nothing -- small lookup tables are scanned sequentially by design and that is genuinely faster than using an index. What justifies an index on a large table is a high avg_rows_per_seq_scan combined with a large table_size and a low idx_scan, which together describe a query repeatedly reading most of a very large relation. If the target table does not appear prominently here, pause and re-examine the assumption that an index is the right fix; the answer may be a better predicate, a partition key, or moving the query off the OLTP path entirely.",
        related_scripts="02_existing_index_inventory.sql",
        table_purpose="Tables suffering expensive sequential scans.",
    ),
    sql_script(
        "02", "02_existing_index_inventory",
        "Checks whether the proposed access pattern is already covered by an existing index's leading columns.",
        sb.index_and_constraint_inventory_for_table(),
        "Read every definition, not just the index names. PostgreSQL uses a multi-column index for queries filtering only on its leading columns, so an existing index on (account_id, executed_at DESC) already serves a query filtering on account_id alone, and adding a single-column index there buys nothing while costing write amplification forever. Count the indexes too: if the table already carries ten or more, the right conversation is an index-set review rather than another addition. Check is_valid and is_ready as well -- a leftover from a previous failed build must be cleaned up before a new build is attempted. Edit the schema_name and table_name variables at the top for your real target.",
        related_scripts="03_write_volume_and_hot_ratio.sql",
        table_purpose="Existing indexes and constraints on the target table.",
    ),
    sql_script(
        "03", "03_write_volume_and_hot_ratio",
        "Measures the table's write volume and HOT update ratio, which determine the ongoing cost of the new index.",
        sb.write_volume_by_table(),
        "This is the cost side of the decision and it is routinely skipped. An index is not a one-off build cost; on a table taking millions of inserts a day it is millions of additional index entries written, WAL-logged, shipped to every Aurora reader, and vacuumed every single day for as long as the index exists. Find your target table and read total_row_writes: that number multiplied by the index's per-entry cost is what you are signing up for permanently. Then read pct_hot_updates -- if it is already low, the new index will make it lower, because a HOT update requires that no indexed column changed. On an update-heavy table, adding an index on a column that changes is one of the most expensive things you can do to the write path.",
        related_scripts="04_target_table_size.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="Per-table write volume and HOT update ratio.",
    ),
    sql_script(
        "04", "04_target_table_size",
        "Measures the target table to estimate build duration and the storage the new index will consume.",
        sb.target_table_size_detail(),
        "Use total_size_bytes for a duration estimate, then multiply by two or three for the concurrent form, which makes two full passes plus two waits for older transactions to finish. Be honest about the result: a build estimated at six hours will span market events and possibly a deployment, and it is exposed to an Aurora failover for that whole period. If n_dead_tup is high and last_autovacuum is stale, vacuum first -- the build has to read dead tuples too, so a bloated table makes an already long build longer. Edit the schema_name and table_name variables at the top for your real target.",
        related_scripts="05_large_table_index_build_runbook.md",
        table_purpose="Target table size and maintenance state.",
    ),
    md_script(
        "05", "05_large_table_index_build_runbook",
        "The guarded DDL runbook for building an index on a very large table, including partial and covering index alternatives.",
        (
            "## Prefer a smaller index first\n\n"
            "Before building a plain index over an entire multi-hundred-gigabyte table, check "
            "whether a smaller one satisfies the query. On exchange data it usually does.\n\n"
            "### Partial index -- usually the right answer\n\n"
            "```sql\n"
            "-- Open orders are a tiny fraction of all orders ever placed. This index is a\n"
            "-- fraction of the size, builds in a fraction of the time, and -- critically --\n"
            "-- costs nothing to maintain for the overwhelming majority of rows, because rows\n"
            "-- outside the predicate are never indexed at all.\n"
            "CREATE INDEX CONCURRENTLY idx_orders_open_by_account\n"
            "    ON public.orders (account_id, created_at DESC)\n"
            "    WHERE status IN ('open', 'partially_filled');\n"
            "```\n\n"
            "The planner only uses a partial index when it can prove the query's predicate "
            "implies the index predicate, so the query must filter on `status` with compatible "
            "values. Confirm with `EXPLAIN` on a representative query before committing to the "
            "build.\n\n"
            "### Covering index -- when an index-only scan is the goal\n\n"
            "```sql\n"
            "-- INCLUDE columns are stored in the leaf pages but not used for ordering or\n"
            "-- searching. This can turn a heap fetch into an index-only scan, at the cost of\n"
            "-- a larger index. Only worth it when the query genuinely returns those columns\n"
            "-- and the table is well vacuumed (the visibility map must be current for an\n"
            "-- index-only scan to avoid the heap).\n"
            "CREATE INDEX CONCURRENTLY idx_trades_account_covering\n"
            "    ON public.trades (account_id, executed_at DESC)\n"
            "    INCLUDE (quantity, price);\n"
            "```\n\n"
            "---\n\n"
            "## The build\n\n"
            "| Property | Value |\n"
            "|---|---|\n"
            "| Lock level | `ShareUpdateExclusiveLock` |\n"
            "| Blocks reads | No |\n"
            "| Blocks writes | No |\n"
            "| Blocks autovacuum on this table | **Yes, for the whole build** |\n"
            "| Runs inside a transaction block | **No -- rejected** |\n"
            "| Rollback | None. Failure leaves an INVALID index to drop. |\n\n"
            "### Step 1 -- session setup\n\n"
            "```sql\n"
            "SET lock_timeout = '5s';\n"
            "SET statement_timeout = 0;         -- must not be killed part-way\n"
            "SET maintenance_work_mem = '4GB';  -- keep the sort off local storage if possible\n"
            "```\n\n"
            "On a very large table, `maintenance_work_mem` is the difference between an\n"
            "in-memory sort and one that spills to per-instance local storage -- which is both\n"
            "much slower and a `FreeLocalStorage` risk on Aurora.\n\n"
            "### Step 2 -- clear the blockers\n\n"
            "Re-run `large-table-ddl` script 04. A concurrent build waits for every transaction\n"
            "that started before each of its two phase boundaries, including transactions that\n"
            "never touch this table. On a build measured in hours, a single idle-in-transaction\n"
            "session can stall it indefinitely.\n\n"
            "### Step 3 -- build\n\n"
            "```sql\n"
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ledger_entries_account_posted\n"
            "    ON public.ledger_entries (account_id, posted_at DESC);\n"
            "```\n\n"
            "- **Blocking risk:** the build blocks no application traffic, but it blocks "
            "autovacuum on this table for its entire duration. On a high-write table a "
            "six-hour build means six hours of dead tuple accumulation -- plan a vacuum "
            "afterwards.\n"
            "- **Transaction behavior:** not permitted inside a transaction block. Disable your "
            "migration framework's implicit transaction or run it by hand.\n"
            "- **Rollback:** none. Cancellation, timeout, session loss, or an Aurora failover "
            "leaves an INVALID index that must be dropped before any retry.\n"
            "- **Production considerations:** monitor Aurora reader lag throughout. Customer-"
            "visible lag is grounds to cancel -- the index can wait, stale balances cannot.\n\n"
            "### Step 4 -- monitor\n\n"
            "From a second session, run `06_build_progress_and_validity.sql` repeatedly and\n"
            "watch the `phase` column rather than the percentages.\n\n"
            "### Step 5 -- after the build\n\n"
            "```sql\n"
            "-- 1. Refresh statistics so the planner knows about the new index's column\n"
            "--    correlation immediately rather than waiting for autoanalyze.\n"
            "ANALYZE public.ledger_entries;\n"
            "\n"
            "-- 2. Vacuum, because the build blocked autovacuum on this table throughout.\n"
            "--    Plain VACUUM only -- never VACUUM FULL on a production exchange table.\n"
            "VACUUM (ANALYZE) public.ledger_entries;\n"
            "```\n\n"
            "Then confirm over the following days that the query you built the index for "
            "actually uses it. An index that is never scanned is a permanent write-"
            "amplification cost with no benefit, and should be dropped through the "
            "drop-index-safely workflow rather than left in place out of sunk-cost "
            "attachment.\n"
        ),
        "Start from the partial index section rather than the plain build -- on exchange data the queries that matter almost always filter on a status, a date window, or an account subset, and a partial index delivers the same plan improvement at a fraction of the build time, the storage, and the permanent write cost. Whatever form you choose, the build must be concurrent and must not be inside a transaction block. Budget for the cleanup a cancellation would require before you start, and treat customer-visible reader lag as an unconditional reason to stop. Substitute your real schema, table, index name, column list, and predicate into the templates before running anything.",
        prerequisites=_DDL_PREREQ,
        related_scripts="06_build_progress_and_validity.sql, ../concurrent-index-build/README.md",
        expected_runtime="Hours on a multi-hundred-gigabyte table; roughly 2-3x a plain build.",
        table_purpose="Guarded DDL runbook: building an index on a very large table.",
    ),
    sql_script(
        "06", "06_build_progress_and_validity",
        "Monitors the build while it runs and confirms afterwards that the index is valid and nothing was left behind.",
        sb.create_index_progress() + "\n\n" + sb.invalid_indexes(),
        "While the build is running, the first result set is what you watch -- and the phase column is the diagnostic, not the percentages. 'building index' means real work is happening; 'waiting for writers before validation' means the build is idle and waiting on older transactions, with current_locker_pid naming the exact backend responsible. Remember there are two full passes, so reaching the end of blocks_done once means roughly halfway. After the build, the second result set must not contain your new index: an entry there means the build did not complete and left an INVALID index that consumes full storage and full write overhead while the planner ignores it entirely. Clean it up through the failed-index-build workflow before retrying.",
        related_scripts="../failed-index-build/README.md",
        execution_location=WRITER_PREFERRED,
        table_purpose="Live build progress plus post-build validity check.",
    ),
]


# ---------------------------------------------------------------------------
# 8. drop-index-safely
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="drop-index-safely",
    title="Dropping an Index Safely",
    summary=(
        "An index looks unused and someone wants to remove it. Dropping an "
        "index is trivially easy and disproportionately dangerous: the "
        "statement takes a second, and if the index turns out to have been "
        "serving a query that only runs at month-end reconciliation, the "
        "consequence is a full sequential scan of a multi-hundred-gigabyte "
        "table discovered under time pressure during the regulatory reporting "
        "window. This workflow is therefore built around evidence and "
        "reversibility rather than around the statement itself. It "
        "establishes that the index is genuinely unused across every instance "
        "and a full business cycle, confirms it is not structurally required, "
        "rehearses the drop inside a transaction that is then rolled back, "
        "and only then removes it -- concurrently, so the removal itself "
        "blocks nothing."
    ),
    symptoms=[
        "An index review has identified indexes with zero scans since the last statistics reset.",
        "Structurally duplicate indexes exist on the same table under different names.",
        "Index storage on a write-heavy table has grown to exceed the table's own heap size.",
        "Write latency on the trading path has degraded as indexes accumulated over time.",
        "An INVALID index from a failed build is consuming storage while providing nothing.",
    ],
    business_impact=[
        "Removing genuinely unused indexes reduces write amplification on the hottest path in the exchange, cuts WAL volume and reader lag, and shortens every vacuum cycle -- it is one of the highest-value, lowest-effort optimizations available.",
        "Removing an index that was actually needed causes an immediate, severe query regression, typically discovered when a periodic job runs and takes hours instead of minutes.",
        "Rebuilding a mistakenly dropped index on a large table takes hours and cannot be done quickly under pressure, so the recovery from a wrong drop is slow.",
        "On Aurora, dropping an index frees space for reuse but does not reduce billed storage, so the benefit is in write performance rather than cost.",
    ],
    root_causes=[
        "N/A -- this is a planned change workflow. Candidates come from the index-growth and unused-indexes investigations.",
    ],
    investigation_strategy=[
        "Identify never-scanned candidates, deliberately excluding indexes that back constraints.",
        "Identify structural duplicates, which are the safest possible candidates because the surviving copy serves exactly the same queries.",
        "For each candidate, establish its structural role: primary key, unique constraint, replica identity, foreign-key support, or purely a query optimization.",
        "Confirm the usage evidence spans a full business cycle and every instance in the cluster, not just the writer since the last failover.",
        "Rehearse the drop inside a transaction and roll it back, using `EXPLAIN` to prove the affected queries do not regress.",
        "Drop concurrently, then monitor query performance for a regression over the following days.",
    ],
    prerequisites=[
        "Index or table ownership for the drop; `pg_monitor` for the investigation.",
        "Usage statistics accumulated across at least one full business cycle, including month-end and quarter-end reconciliation and regulatory reporting.",
        "Usage statistics from every instance in the cluster, since reporting traffic is often pinned to a reader.",
        "Sign-off from the team owning the queries against the table.",
    ],
    interpretation_guide=[
        "`idx_scan = 0` is necessary but nowhere near sufficient. The counter resets on instance restart and on every Aurora failover, so a zero on the writer may mean 'nothing used this since the failover an hour ago' rather than 'nothing has ever used this'.",
        "`last_idx_scan` (PostgreSQL 16+) is far more trustworthy, because a timestamp survives as evidence in a way a counter does not. An index last scanned eight months ago is genuinely unused.",
        "Check usage on the readers, not only the writer. Reporting and analytics traffic is commonly routed to a reader, and an index used exclusively by those queries reads as unused on the writer.",
        "Never drop an index backing a primary key, unique, or exclusion constraint by name -- drop the constraint instead, which removes the index with it. Attempting the direct drop simply fails.",
        "An index that is the table's replica identity must not be dropped while logical replication depends on it, or `UPDATE` and `DELETE` on that table will start failing.",
        "An index supporting a foreign key must not be dropped on scan counts alone. It may show zero scans while still preventing every parent delete from sequentially scanning the child table, because that check does not always register as an index scan in the same way.",
        "Structural duplicates are the highest-confidence candidates in the whole workflow: by definition the surviving copy serves exactly the same queries, so the planner cannot regress. Keep the one with the clearer name and the longer usage history.",
        "A `DROP INDEX` inside an explicit transaction is fully reversible by `ROLLBACK`, which makes a rehearsal genuinely safe -- this is the single most useful technique in this workflow and it is underused.",
    ],
    remediation_immediate=[
        "If a query has regressed after a drop, recreate the index concurrently immediately. Keep the exact original definition recorded before the drop so this can be done without reconstruction.",
    ],
    remediation_short_term=[
        "Drop confirmed structural duplicates first -- they are risk-free and deliver immediate write-path benefit.",
        "Drop confirmed INVALID indexes unconditionally; the planner never used them.",
        "Drop never-scanned indexes one at a time with a monitoring gap between each, so any regression can be attributed to a specific drop.",
    ],
    remediation_long_term=[
        "Schedule a recurring index audit so accretion is corrected continuously rather than as an occasional large cleanup.",
        "Record the full definition of every dropped index in the change ticket, so recreating it is a copy-paste rather than a reconstruction under pressure.",
        "Require every new index to name the query it serves, so future audits have something to check against.",
    ],
    production_safety=[
        "All `.sql` scripts here are read-only. The drop lives in the `.md` runbook.",
        "Always use `DROP INDEX CONCURRENTLY` on a production table -- the plain form takes an `AccessExclusiveLock` and blocks reads as well as writes.",
        "`DROP INDEX CONCURRENTLY` cannot run inside a transaction block and can name only one index per statement.",
        "Rehearse first: `BEGIN; DROP INDEX ...; EXPLAIN <query>; ROLLBACK;` proves the planner's behavior without the index while changing nothing permanently. Note this rehearsal uses the plain form and therefore takes a strong lock for the duration of the transaction, so keep it very short and set a lock timeout.",
        "Record the exact index definition before dropping it. Reconstructing a definition from memory during a regression is how a bad afternoon becomes a bad week.",
    ],
    escalation_criteria=[
        "The candidate is on the live order-matching or wallet-balance path -- the owning team must sign off, because a wrong drop there is an immediate trading incident.",
        "The index cannot be attributed to any query or team after investigation -- do not guess; escalate for ownership rather than dropping something nobody understands.",
        "The index is the table's replica identity or supports an active logical replication or DMS pipeline.",
        "A query regression is observed after a drop and recreating the index does not resolve it -- escalate, because something else changed at the same time.",
    ],
    related_issues=[
        "../failed-index-build/README.md",
        "../safe-index-creation/README.md",
        "../add-index-large-table/README.md",
        "../large-table-ddl/README.md",
        "../../tables-and-indexes/unused-indexes/README.md",
        "../../tables-and-indexes/duplicate-indexes/README.md",
        "../../storage-and-capacity/index-growth/README.md",
        "../../query-optimization/query-plan-regression/README.md",
    ],
    aurora_notes=[
        "`idx_scan` and `last_idx_scan` reset on instance restart and on every Aurora failover. After a failover, every index on the new writer reads as unused -- wait for a full business cycle of fresh statistics before making any drop decision.",
        "Index usage counters are per instance. Check every reader as well as the writer, because reporting traffic pinned to a reader produces exactly the pattern that makes a needed index look droppable.",
        "Dropping an index frees its space for reuse inside the Aurora volume but does not reduce the billed high-water mark. The benefit is reduced write amplification, WAL volume, and vacuum time -- not storage cost.",
        "Reduced WAL volume from fewer indexes directly reduces Aurora reader lag on a write-heavy table, which is often the most valuable outcome of an index cleanup.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_unused_index_candidates",
        "Lists never-scanned, non-constraint-backing indexes as candidates, with the caveats that make a candidate list not a decision.",
        sb.unused_indexes(),
        "Treat this strictly as a candidate list. Before any of these becomes a proposal, three things must be true: statistics have accumulated across at least one full business cycle including month-end and quarter-end reconciliation and regulatory reporting runs; the index shows zero scans on every reader as well as the writer, because reporting traffic is commonly pinned to a reader; and no Aurora failover has reset the counters inside the observation window. The backs_constraint column is already excluded from this list deliberately, since those indexes exist for correctness rather than performance. Record the full index definition for every candidate now -- you will want it if a regression forces a rebuild.",
        related_scripts="02_duplicate_index_candidates.sql",
        table_purpose="Never-scanned index drop candidates.",
    ),
    sql_script(
        "02", "02_duplicate_index_candidates",
        "Finds structurally identical indexes, which are the safest possible drop candidates.",
        sb.duplicate_indexes(),
        "Start your cleanup here rather than with the unused list. Anything reported is wasted storage and wasted write overhead by definition: the surviving copy serves exactly the same queries, so the planner cannot regress and the usual month-end-reconciliation worry does not apply. Keep the copy with the clearer, more descriptive name and the longer usage history from script 03, and drop the other. Duplicates most commonly arise when an ORM migration and a hand-written migration create the same index under different names, so expect to find them in pairs on tables that several teams have extended.",
        related_scripts="03_index_role_and_drop_verdict.sql",
        table_purpose="Structurally duplicate indexes.",
    ),
    sql_script(
        "03", "03_index_role_and_drop_verdict",
        "Establishes the structural role of every index on the target table and produces an explicit per-index verdict.",
        """
-- Structural role and an explicit drop verdict for every index on one target
-- table. An index can be unused by the planner and still be structurally
-- required -- backing a primary key or unique constraint, serving as the
-- table's replica identity for logical replication, or supporting a foreign
-- key check. This script surfaces all of those roles together so the decision
-- is made on structure first and usage second.
--
-- Ships with an illustrative default (public.trades); edit the \\set lines
-- below for your real target. Names are compared only inside a catalog WHERE
-- clause and never cast to regclass, so running this unmodified against a
-- database without that table simply returns zero rows.
\\set schema_name 'public'
\\set table_name 'trades'
SELECT
    n.nspname                                                    AS schema_name,
    t.relname                                                    AS table_name,
    i.relname                                                    AS index_name,
    pg_size_pretty(pg_relation_size(i.oid))                       AS index_size,
    ix.indisprimary                                              AS is_primary_key,
    ix.indisunique                                               AS is_unique,
    ix.indisvalid                                                AS is_valid,
    ix.indisreplident                                            AS is_replica_identity,
    EXISTS (
        SELECT 1 FROM pg_constraint con WHERE con.conindid = ix.indexrelid
    )                                                            AS backs_constraint,
    (
        SELECT string_agg(con.conname || ' (' || con.contype::text || ')', ', ')
        FROM pg_constraint con
        WHERE con.conindid = ix.indexrelid
    )                                                            AS backing_constraints,
    s.idx_scan,
    s.last_idx_scan,
    pg_get_indexdef(ix.indexrelid)                               AS index_definition,
    CASE
        WHEN ix.indisprimary
            THEN 'DO NOT DROP -- primary key index'
        WHEN EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = ix.indexrelid)
            THEN 'DO NOT DROP DIRECTLY -- backs a constraint; drop the constraint instead'
        WHEN ix.indisreplident
            THEN 'DO NOT DROP -- this is the table replica identity for logical replication'
        WHEN NOT ix.indisvalid
            THEN 'SAFE TO DROP -- INVALID index, never used by the planner'
        WHEN COALESCE(s.idx_scan, 0) = 0
            THEN 'CANDIDATE -- zero scans since the last stats reset; verify across a full business cycle AND on every instance before proposing'
        ELSE 'IN USE -- ' || s.idx_scan ||
             ' scans recorded; do not drop without a query-level review'
    END                                                          AS drop_verdict
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
LEFT JOIN pg_stat_all_indexes s ON s.indexrelid = ix.indexrelid
WHERE n.nspname = :'schema_name'
  AND t.relname = :'table_name'
ORDER BY pg_relation_size(i.oid) DESC;
""".strip("\n"),
        "Read drop_verdict first and structure before usage. An index backing a primary key or unique constraint cannot be dropped by name at all -- the statement fails, and the correct action is to drop the constraint, which removes the index with it. An index flagged as replica identity must stay while any logical replication or AWS DMS pipeline depends on the table, or UPDATE and DELETE against it will start failing outright. A foreign-key-supporting index deserves particular caution even at zero scans, because it may be preventing every parent delete from sequentially scanning this child table without that registering as a conventional index scan. Copy index_definition for every index you intend to drop into the change ticket before proceeding. Edit the schema_name and table_name variables at the top for your real target.",
        related_scripts="04_drop_index_safely_runbook.md",
        table_purpose="Structural role and explicit drop verdict per index.",
    ),
    md_script(
        "04", "04_drop_index_safely_runbook",
        "The guarded DDL runbook for dropping an index, including the transaction-rollback rehearsal that proves the drop is safe first.",
        (
            "## Step 1 -- record the definition, before anything else\n\n"
            "```sql\n"
            "-- Read-only. Copy the output into the change ticket verbatim. If a regression\n"
            "-- forces a rebuild, you want a copy-paste, not a reconstruction from memory\n"
            "-- while a reconciliation job is failing.\n"
            "SELECT pg_get_indexdef(ix.indexrelid) AS exact_definition\n"
            "FROM pg_index ix\n"
            "JOIN pg_class i ON i.oid = ix.indexrelid\n"
            "JOIN pg_class t ON t.oid = ix.indrelid\n"
            "JOIN pg_namespace n ON n.oid = t.relnamespace\n"
            "WHERE n.nspname = 'public'\n"
            "  AND t.relname = 'trades'\n"
            "  AND i.relname = 'idx_trades_legacy_lookup';\n"
            "```\n\n"
            "## Step 2 -- rehearse the drop and roll it back\n\n"
            "This is the most valuable technique in this workflow and the most underused. "
            "`DROP INDEX` (the plain form) is fully transactional, so you can remove the "
            "index, ask the planner what it would do without it, and then undo everything.\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  -- Keep this transaction very short. The plain DROP INDEX takes an\n"
            "  -- AccessExclusiveLock on the table and holds it until COMMIT or ROLLBACK,\n"
            "  -- which blocks reads as well as writes for that whole window.\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "\n"
            "  DROP INDEX public.idx_trades_legacy_lookup;\n"
            "\n"
            "  -- Now ask the planner what it would do WITHOUT the index. Use EXPLAIN only,\n"
            "  -- never EXPLAIN ANALYZE here -- ANALYZE actually executes the query, which\n"
            "  -- inside this transaction means running a potentially enormous sequential\n"
            "  -- scan while holding an AccessExclusiveLock on a production table.\n"
            "  EXPLAIN SELECT * FROM public.trades\n"
            "  WHERE account_id = 12345 AND executed_at > now() - interval '30 days';\n"
            "\n"
            "ROLLBACK;  -- nothing is changed; the index is still there\n"
            "```\n\n"
            "If the plan is still acceptable -- another index covers it, or the remaining plan "
            "is a cheap scan on a small partition -- the drop is safe. If it turns into a "
            "sequential scan over the whole table, you have just prevented an incident at the "
            "cost of thirty seconds.\n\n"
            "Repeat for every query you believe might depend on the index, including the "
            "month-end and reconciliation queries that are precisely the ones the usage "
            "counters fail to reflect.\n\n"
            "## Step 3 -- drop it concurrently\n\n"
            "```sql\n"
            "-- Must NOT be inside BEGIN/COMMIT. PostgreSQL rejects it with:\n"
            "--   ERROR:  DROP INDEX CONCURRENTLY cannot run inside a transaction block\n"
            "-- Only one index per statement is permitted in the concurrent form.\n"
            "SET lock_timeout = '5s';\n"
            "DROP INDEX CONCURRENTLY IF EXISTS public.idx_trades_legacy_lookup;\n"
            "```\n\n"
            "| Property | `DROP INDEX CONCURRENTLY` | `DROP INDEX` (plain) |\n"
            "|---|---|---|\n"
            "| Lock level | `ShareUpdateExclusiveLock` | `AccessExclusiveLock` |\n"
            "| Blocks reads | No | **Yes** |\n"
            "| Blocks writes | No | **Yes** |\n"
            "| Inside a transaction block | **Not permitted** | Yes |\n"
            "| Rollback | None once it proceeds | Clean -- `ROLLBACK` undoes it |\n"
            "| Production use | **Default** | Rehearsal only (step 2) |\n\n"
            "- **Blocking risk:** minimal. Like the concurrent create, it waits for "
            "transactions older than its phase boundaries, so a long-running transaction can "
            "delay it -- but it blocks nothing itself.\n"
            "- **Rollback:** none once it proceeds. Recovery is recreating the index "
            "concurrently from the definition recorded in step 1, which on a large table takes "
            "hours -- which is exactly why step 2 exists.\n"
            "- **Production considerations:** drop one index at a time with a monitoring gap "
            "between each, so any regression can be attributed to a specific drop rather than "
            "to a batch of five.\n\n"
            "## Step 4 -- constraint-backed indexes\n\n"
            "An index backing a primary key or unique constraint cannot be dropped by name; "
            "the statement fails. Drop the constraint instead, which removes the index with "
            "it:\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "  ALTER TABLE public.trades DROP CONSTRAINT trades_external_id_key;\n"
            "COMMIT;\n"
            "```\n\n"
            "- **Lock level:** `AccessExclusiveLock`, milliseconds -- it is a catalog "
            "operation, the index file is removed afterwards.\n"
            "- **Rollback:** clean while inside the transaction.\n"
            "- **Production considerations:** dropping a unique constraint removes a "
            "correctness guarantee, not just an index. On a financial table this needs explicit "
            "sign-off from the owning team and, for deposits, withdrawals, or ledger tables, "
            "from compliance.\n\n"
            "## Step 5 -- monitor afterwards\n\n"
            "Run `05_post_drop_regression_check.sql` immediately and again over the following "
            "days, covering at least one full cycle of periodic jobs. A regression from a "
            "wrong drop typically appears when a weekly or month-end job runs, not in the "
            "first hour.\n\n"
            "If a regression appears, recreate the index concurrently from the definition "
            "recorded in step 1 and treat it as a normal index build.\n"
        ),
        "Step 2 is the point of this runbook -- everything else is routine. Rehearsing the drop inside a transaction and rolling it back gives you the planner's real answer for the cost of a few seconds, and it is the only technique here that catches the month-end reconciliation query that usage counters never reflected. Keep the rehearsal transaction extremely short and use EXPLAIN without ANALYZE, because the plain DROP INDEX inside it holds an AccessExclusiveLock that blocks reads as well as writes until you roll back. Drop one index at a time with a monitoring gap between each so a regression is attributable. Substitute your real schema, table, index, and query names into every template before running anything.",
        prerequisites=(
            "Scripts 01-03 completed, usage evidence gathered across a full business cycle "
            "and from every instance in the cluster, and the exact index definition "
            "recorded. " + _DDL_PREREQ
        ),
        related_scripts="03_index_role_and_drop_verdict.sql, 05_post_drop_regression_check.sql",
        expected_runtime="Seconds for the rehearsal; seconds to minutes for the concurrent drop.",
        table_purpose="Guarded DDL runbook: rehearsing and executing an index drop.",
    ),
    sql_script(
        "05", "05_post_drop_regression_check",
        "Watches for a query regression after the drop, over a window long enough to include periodic jobs.",
        _pgss_guarded(sb.pgss_top_by_mean_time()),
        "Run this immediately after the drop and again daily for at least a full cycle of periodic jobs, because a regression from a wrong drop usually appears when a weekly or month-end reconciliation job runs rather than in the first hour. Compare mean_exec_time_ms for statements touching the affected table against the values recorded before the drop -- a statement whose mean execution time has jumped by an order of magnitude is the signature of a lost index, and the fix is to recreate it concurrently from the definition you recorded in step 1 of the runbook. If pg_stat_statements is not installed, the script prints guidance instead of failing, and you should fall back to application-level latency monitoring and the sequential-scan counters on the affected table.",
        related_scripts="../../query-optimization/query-plan-regression/README.md",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=_PGSS_PREREQ,
        execution_location=WRITER_PREFERRED,
        table_purpose="Post-drop query regression check.",
    ),
]


# ---------------------------------------------------------------------------
# 9. ddl-lock-investigation
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="ddl-lock-investigation",
    title="DDL Lock Investigation",
    summary=(
        "A schema change is stuck, or a schema change has stalled the "
        "application, and you need to know exactly what is holding what. The "
        "mechanism behind almost every incident of this shape is the same and "
        "is worth understanding before reading any output: when a DDL "
        "statement requests `AccessExclusiveLock` and cannot get it "
        "immediately, PostgreSQL queues that request -- and then queues every "
        "*subsequent* lock request on the same table behind it, including "
        "plain `SELECT`s that would not have conflicted with the current "
        "holders at all. So a single long-running read, plus one waiting "
        "`ALTER TABLE`, is enough to freeze every query against the orders "
        "table while nothing is actually doing any work. This workflow finds "
        "the head of that queue, identifies the root blocker, and provides "
        "the guarded remediation."
    ),
    symptoms=[
        "A deployment's migration step has been running far longer than expected with no visible progress.",
        "Queries against one specific table have all stopped returning, while the rest of the database is completely healthy.",
        "Application connections are piling up and timing out, all on statements against the same table.",
        "An `ALTER TABLE`, `CREATE INDEX`, or `DROP INDEX` appears in `pg_stat_activity` with a lock wait event.",
        "`pg_locks` shows a long chain of ungranted lock requests on one relation.",
        "A concurrent index build has been parked in a waiting phase for hours.",
    ],
    business_impact=[
        "A lock queue on the orders table stops order placement and cancellation entirely -- a complete trading outage on that instrument set, with no error the application can retry its way out of.",
        "Because the queue blocks reads too, customer-facing balance and order-history views fail as well, multiplying the visible impact.",
        "Connection pools exhaust as every connection waits on the same lock, which spreads the failure to unrelated parts of the application that merely share a pool.",
        "These incidents are often misdiagnosed as database performance problems, wasting critical minutes looking at CPU and I/O when nothing is actually executing.",
    ],
    root_causes=[
        "A DDL statement waiting for `AccessExclusiveLock` behind a long-running read, with every later query queued behind the DDL's pending request.",
        "A long-running analytical or reporting query holding a `AccessShareLock` on the table for minutes, which is enough to block the DDL and start the queue.",
        "An idle-in-transaction session holding a lock acquired earlier in its transaction and doing nothing -- usually a connection-pool leak or a forgotten terminal.",
        "An orphaned prepared transaction holding locks indefinitely, which survives restarts and never resolves itself.",
        "Autovacuum holding a `ShareUpdateExclusiveLock` and conflicting with a DDL statement. Autovacuum yields to most conflicting lock requests, but an anti-wraparound vacuum does not.",
        "Two concurrent schema changes on the same table contending with each other.",
        "A concurrent index build waiting for transactions older than its phase boundary -- including transactions that never touch the table.",
        "DDL issued against a partitioned parent, which acquires locks across every partition in a single transaction.",
    ],
    investigation_strategy=[
        "Look first at DDL-style lock waits specifically, which immediately shows whether a schema change is at the head of the problem.",
        "List every blocked session to establish the scale -- how much of the application is actually stalled.",
        "Expand the blocking relationships to find the root blocker, following the chain rather than stopping at the first blocker found.",
        "Read the raw lock detail by mode for ground truth on who holds what, in what mode, on which object.",
        "Check long-running and idle-in-transaction sessions, which are the usual root cause at the bottom of the chain.",
        "Apply the remediation runbook: cancel the pending DDL first to drain the queue, then deal with the root blocker, then retry with a lock timeout.",
    ],
    prerequisites=[
        "`pg_monitor` role membership for all investigation scripts.",
        "Authorization to cancel or terminate backends if remediation is needed -- establish who holds that authority before the incident, not during it.",
        "The writer endpoint: DDL and its lock queue live on the writer.",
        "Knowledge of what deployment or migration is currently in flight, which usually identifies the DDL statement immediately.",
    ],
    interpretation_guide=[
        "Read `granted = false` rows first and order by wait duration. The oldest ungranted request is usually the head of the queue and the thing to act on.",
        "The critical insight: a *pending* `AccessExclusiveLock` blocks every later request on that relation, even requests that would not conflict with the current holders. That is why cancelling the waiting DDL -- not the long-running query it is waiting for -- is normally the fastest way to restore service. The queue drains within seconds.",
        "Follow the chain to its root. `pg_blocking_pids()` gives direct blockers, but the direct blocker may itself be blocked. The root blocker is the one that is not waiting on anything, and it is the only one worth acting on.",
        "A blocker in state `idle in transaction` is the most common and most frustrating root cause: it is doing no work at all while holding the lock. Its `blocking_txn_age` tells you how long it has been that way, and a large value with an idle state is effectively a confirmed leak.",
        "`AccessExclusiveLock` is taken by most `ALTER TABLE` forms, plain `DROP INDEX`, `TRUNCATE`, `REINDEX`, and `VACUUM FULL`. `ShareUpdateExclusiveLock` is taken by the concurrent index operations, `VALIDATE CONSTRAINT`, and autovacuum. `ShareLock` is taken by a plain `CREATE INDEX`.",
        "Autovacuum normally yields when it conflicts with a user lock request -- but an anti-wraparound autovacuum does not, and will not. If the blocker is an anti-wraparound vacuum, do not cancel it: it is protecting the cluster from a far worse outcome, and the correct action is to wait.",
        "If the waiting statement is a concurrent index build parked in a waiting phase, it is not in a lock queue in the conventional sense -- it is waiting for transaction age, and cancelling the transactions it waits on is the only thing that helps.",
    ],
    remediation_immediate=[
        "Cancel the pending DDL statement first. This drains the queue immediately and restores service within seconds, and it is almost always the right first move because the DDL has not done any work yet.",
        "Then deal with the root blocker: contact the owning team to close a long-running or idle-in-transaction session through their application.",
        "Only if the root blocker cannot be reached, and only with explicit authorization, terminate it at the backend level. Confirm the process identifier against the investigation output first -- terminating the wrong backend on a trading platform is its own incident.",
        "Never cancel an anti-wraparound autovacuum to unblock DDL. It is preventing a far more serious problem and must be allowed to finish.",
    ],
    remediation_short_term=[
        "Retry the schema change with `SET lock_timeout` so it fails fast instead of forming a queue.",
        "Resolve any orphaned prepared transaction, which will otherwise block the next attempt identically.",
        "Move the blocking long-running reporting query to a reader, so it cannot block writer DDL at all.",
    ],
    remediation_long_term=[
        "Set `idle_in_transaction_session_timeout` cluster-wide so leaked connections cannot hold locks indefinitely.",
        "Enforce `lock_timeout` on all production DDL in the migration framework rather than relying on individuals to remember it.",
        "Route analytical and reporting workloads to dedicated readers so they never contend with writer DDL.",
        "Enable `log_lock_waits` so future lock waits are recorded with their full context and can be investigated after the fact.",
        "Monitor and alert on long-running transactions and prepared transactions, which are the root cause of most of these incidents.",
    ],
    production_safety=[
        "Every script in this workflow is read-only and safe to run during an active incident -- they are designed to be run under exactly these conditions.",
        "The remediation runbook contains session cancellation and termination guidance and must be read before any action is taken. Confirm every process identifier against the investigation output first.",
        "Cancelling is always preferable to terminating: a cancel ends the statement and lets the session clean up, while a termination drops the connection entirely and may surface as an application error.",
        "Terminating a backend rolls back its transaction. On a long-running write transaction that rollback can itself take a while and generate its own load.",
        "Never cancel an anti-wraparound autovacuum to unblock a schema change.",
    ],
    escalation_criteria=[
        "The lock queue is blocking order placement, matching, or wallet operations -- this is a full trading incident and needs incident command, not just a DBA.",
        "The root blocker is a backend owned by a team that cannot be reached, and the outage is ongoing.",
        "The blocker is an anti-wraparound autovacuum, which must not be cancelled -- escalate to the transaction ID wraparound workflow, because that is the more serious underlying problem.",
        "Cancelling the DDL does not drain the queue, which indicates something beyond a simple lock queue and needs deeper investigation.",
        "The same DDL has caused a lock incident more than once -- stop retrying and fix the process that keeps issuing it without a lock timeout.",
    ],
    related_issues=[
        "../large-table-ddl/README.md",
        "../concurrent-index-build/README.md",
        "../safe-index-creation/README.md",
        "../column-type-change/README.md",
        "../../concurrency-and-locking/ddl-blocking/README.md",
        "../../concurrency-and-locking/blocked-queries/README.md",
        "../../concurrency-and-locking/lock-contention/README.md",
        "../../concurrency-and-locking/long-running-transactions/README.md",
        "../../concurrency-and-locking/idle-in-transaction/README.md",
        "../../transactions-and-xid/prepared-transactions/README.md",
    ],
    aurora_notes=[
        "Lock state is entirely per instance. DDL and its lock queue live on the writer, so always investigate a DDL lock incident against the writer endpoint -- a reader shows a completely different and irrelevant lock picture.",
        "An Aurora failover clears all locks by restarting the database, which does resolve a lock queue -- but it is a heavy-handed remedy with its own disruption, and it does nothing about the application behavior that created the blocker in the first place.",
        "`log_lock_waits` and `deadlock_timeout` are set through the Aurora DB cluster parameter group. Enabling `log_lock_waits` is one of the cheapest observability improvements available for this class of incident.",
        "Performance Insights shows `Lock:relation` and `Lock:transactionid` wait events prominently, which is often the fastest way to spot a lock queue forming before anyone reports an application problem.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_ddl_lock_waits",
        "Shows sessions holding or waiting on the strong lock modes taken by DDL, which immediately reveals whether a schema change is at the head of the problem.",
        sb.ddl_lock_waits(),
        "This is the first script to run and frequently the only one you need. Rows are ordered with ungranted requests first: if you see an ALTER TABLE, CREATE INDEX, or DROP INDEX with granted = false and a long wait_duration, you have found the head of the queue. That statement has done no work at all, yet its pending AccessExclusiveLock request is blocking every later query on the relation -- including plain SELECTs that would never have conflicted with the current holders. Cancelling it is normally the fastest route back to service, and the queue drains within seconds. Note the relation_name, because it tells you exactly which part of the application is affected.",
        related_scripts="02_blocked_sessions_overview.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="DDL-mode lock holders and waiters.",
    ),
    sql_script(
        "02", "02_blocked_sessions_overview",
        "Lists every currently blocked session with its direct blockers, establishing how much of the application is actually stalled.",
        sb.blocked_sessions(),
        "Use this to size the incident. A handful of blocked sessions is a contention problem; dozens or hundreds all waiting on the same relation is a full lock queue and an outage in progress. Read blocked_duration to see how long this has been going on, and blocking_pids to see whether everything converges on a single culprit -- which it usually does. If the blocked queries are ordinary application statements against one table and the blocking_pids array repeatedly names the same process, you already know the shape of the problem and script 03 will name the root.",
        related_scripts="03_blocking_chain_detail.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="All blocked sessions and their direct blockers.",
    ),
    sql_script(
        "03", "03_blocking_chain_detail",
        "Expands every blocking relationship into one row per blocker, showing what each blocker is actually doing.",
        sb.blocking_sessions_detail(),
        "Follow the chain to its root rather than acting on the first blocker you see -- a direct blocker may itself be blocked by something else, and only the backend that is not waiting on anything is worth acting on. The blocking_state column is the key field: a blocker in state 'idle in transaction' with a large blocking_txn_age is doing no work whatsoever while holding the lock, which is almost always a connection-pool leak or a forgotten session, and contacting the owning team is far more productive than waiting. A blocker in state 'active' with a long-running query is at least doing something, and the judgement is whether that work matters more than the stalled application -- on the trading path, it does not.",
        related_scripts="04_lock_detail_by_mode.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="Expanded blocker detail per blocked session.",
    ),
    sql_script(
        "04", "04_lock_detail_by_mode",
        "Provides the raw ground truth of who holds what lock, in which mode, on which object.",
        sb.lock_detail_by_mode(),
        "This is the authoritative view when the higher-level scripts disagree or the picture is confusing. Ungranted requests are listed first, which reconstructs the queue order directly. Match the mode column against what you expect: AccessExclusiveLock from most ALTER TABLE forms, plain DROP INDEX, TRUNCATE, REINDEX and VACUUM FULL; ShareUpdateExclusiveLock from the concurrent index operations, VALIDATE CONSTRAINT and autovacuum; ShareLock from a plain CREATE INDEX. If the blocker turns out to be an autovacuum worker, check whether it is an anti-wraparound vacuum before considering any action -- ordinary autovacuum yields to a conflicting lock request, but anti-wraparound does not and must never be cancelled to unblock a schema change.",
        related_scripts="05_long_running_and_idle_transactions.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="Raw lock detail by mode, ungranted requests first.",
    ),
    sql_script(
        "05", "05_long_running_and_idle_transactions",
        "Finds the long-running and idle-in-transaction sessions, plus prepared transactions, that sit at the root of most DDL lock incidents.",
        sb.long_running_transactions() + "\n\n" + sb.idle_in_transaction_sessions() + "\n\n" + sb.prepared_transactions(),
        "The root cause is usually in one of these three result sets. A long-running read that is genuinely working is the most defensible blocker and the judgement is simply whether its work outranks the stalled application. An idle-in-transaction session is not defensible at all: it is holding locks while doing nothing, and it is almost always a connection-pool leak, an application that forgot to commit, or a terminal someone walked away from. A prepared transaction older than a few minutes is an orphaned two-phase commit whose coordinator died -- it holds its locks indefinitely, survives instance restarts, and will block the next attempt identically unless it is resolved. Whichever it is, note that clearing it does not by itself release the queue if a pending DDL request is still sitting at the head; cancel the DDL first.",
        related_scripts="06_ddl_lock_remediation_runbook.md",
        execution_location=WRITER_PREFERRED,
        table_purpose="Long-running, idle-in-transaction, and prepared transactions.",
    ),
    md_script(
        "06", "06_ddl_lock_remediation_runbook",
        "The guarded remediation runbook for draining a DDL lock queue and safely retrying the schema change.",
        (
            "## Understand the mechanism before acting\n\n"
            "```\n"
            "  Session A: long-running SELECT on public.orders   -> holds AccessShareLock\n"
            "  Session B: ALTER TABLE public.orders ...          -> WAITING for AccessExclusiveLock\n"
            "  Session C: SELECT ... FROM public.orders          -> WAITING behind B\n"
            "  Session D..Z: every later query on public.orders  -> WAITING behind B\n"
            "```\n\n"
            "Session C would not have conflicted with session A at all. It is blocked purely "
            "because PostgreSQL queues lock requests in order and B's pending exclusive "
            "request sits in front of it. **This is why the fastest fix is almost always to "
            "cancel B, not A.** B has done no work, so cancelling it costs nothing, and the "
            "queue drains within seconds.\n\n"
            "---\n\n"
            "## Step 1 -- cancel the pending DDL\n\n"
            "```sql\n"
            "-- Preferred: press Ctrl-C in the session running the DDL, or have the\n"
            "-- deployment pipeline abort the migration step.\n"
            "--\n"
            "-- If that session is unreachable, an authorized operator can cancel it by\n"
            "-- process id. Confirm the pid against 01_ddl_lock_waits.sql output first --\n"
            "-- cancelling the wrong backend on a trading platform is its own incident.\n"
            "-- Cancel (graceful, ends the statement, session survives):\n"
            "--     SELECT pg_cancel_backend(<pid>);\n"
            "-- Terminate (drops the connection entirely -- only if cancel does not work):\n"
            "--     SELECT pg_terminate_backend(<pid>);\n"
            "```\n\n"
            "Always try cancel before terminate. A cancel ends the statement and lets the "
            "session clean up normally; a terminate drops the connection and usually surfaces "
            "as an application error.\n\n"
            "Re-run `02_blocked_sessions_overview.sql` immediately afterwards. The queue should "
            "drain within seconds. If it does not, the pending DDL was not the head of the "
            "queue and you should re-read `04_lock_detail_by_mode.sql`.\n\n"
            "## Step 2 -- deal with the root blocker\n\n"
            "Now that service is restored, address the thing that made the DDL wait.\n\n"
            "**If it is an application session (long-running or idle in transaction):** "
            "contact the owning team and have them close it through their application. This is "
            "always preferable to terminating it from the database side, because they know "
            "what work it was doing.\n\n"
            "**If it is unreachable and the incident is ongoing:** terminate it with explicit "
            "authorization, having confirmed the pid. Note that terminating a long-running "
            "*write* transaction triggers a rollback that can itself take time and generate "
            "load.\n\n"
            "**If it is an orphaned prepared transaction:**\n\n"
            "```sql\n"
            "-- Read-only first -- confirm it is genuinely orphaned, not a live two-phase\n"
            "-- commit mid-flight. Anything older than a few minutes with no coordinator is\n"
            "-- orphaned; it holds its locks indefinitely and survives restarts.\n"
            "SELECT gid, prepared, owner, database FROM pg_prepared_xacts ORDER BY prepared;\n"
            "\n"
            "-- Then, with the owning team's confirmation, resolve it:\n"
            "--     ROLLBACK PREPARED '<gid>';\n"
            "-- (or COMMIT PREPARED if the transaction is confirmed to have been intended to\n"
            "-- commit -- on a financial table this decision is never the DBA's alone).\n"
            "```\n\n"
            "**If it is an anti-wraparound autovacuum: do not cancel it.** It does not yield "
            "the way ordinary autovacuum does, and it is preventing transaction ID wraparound, "
            "which is a far more serious outcome than a delayed schema change. Wait for it, and "
            "treat the underlying transaction age as the real problem.\n\n"
            "## Step 3 -- retry the schema change safely\n\n"
            "```sql\n"
            "BEGIN;\n"
            "  -- Never retry production DDL without this. With a short timeout the statement\n"
            "  -- either gets its lock immediately or fails harmlessly, and can never form the\n"
            "  -- queue that caused this incident.\n"
            "  SET LOCAL lock_timeout = '3s';\n"
            "\n"
            "  ALTER TABLE public.orders ADD COLUMN settlement_batch_id bigint;\n"
            "COMMIT;\n"
            "```\n\n"
            "If it fails with `canceling statement due to lock timeout`, that is the system "
            "working exactly as intended. Wait a few seconds and retry in a loop -- on a busy "
            "table a clean window usually appears within a handful of attempts. Do **not** "
            "respond by raising the timeout; that reintroduces the original failure mode.\n\n"
            "## Step 4 -- prevent the recurrence\n\n"
            "- Set `idle_in_transaction_session_timeout` in the Aurora cluster parameter group "
            "so a leaked connection cannot hold locks indefinitely.\n"
            "- Enforce `lock_timeout` for all DDL in the migration framework, not by "
            "convention.\n"
            "- Enable `log_lock_waits` so the next occurrence is fully recorded and can be "
            "investigated after the fact rather than only live.\n"
            "- Route long-running analytical and reporting queries to a reader so they cannot "
            "block writer DDL at all.\n"
            "- Alert on long-running transactions and on any prepared transaction older than a "
            "few minutes.\n"
        ),
        "The ordering here is the whole point: cancel the waiting DDL first to restore service, then deal with the root blocker, then retry with a lock timeout. Reversing the first two steps means the application stays down while you negotiate with whoever owns the blocking session. Confirm every process identifier against the script output before acting on it, prefer cancelling over terminating, and never cancel an anti-wraparound autovacuum to unblock a schema change -- it is protecting the cluster from something considerably worse than a delayed migration. Substitute your real schema, table, and statement text into the step 3 template before retrying.",
        safety=GUARDED_DDL,
        expected_impact="Varies by step -- cancelling a waiting DDL is near-instant and low risk; terminating an application backend rolls back its transaction and may surface as an application error.",
        prerequisites=(
            "Scripts 01-05 completed so the lock queue, the root blocker, and the affected "
            "relation are all identified, and authorization to cancel or terminate backends "
            "has been confirmed."
        ),
        required_privileges=(
            "`pg_monitor` for the investigation. Cancelling or terminating another role's "
            "backend additionally requires membership in `pg_signal_backend`, or ownership of "
            "the target role. Resolving a prepared transaction requires the original "
            "transaction owner or superuser-equivalent privileges."
        ),
        related_scripts="01_ddl_lock_waits.sql, 02_blocked_sessions_overview.sql",
        expected_runtime="Seconds for the cancellation; the retry depends on the underlying DDL.",
        table_purpose="Guarded runbook: draining a DDL lock queue and retrying safely.",
    ),
]
