"""Workflow definitions: storage-and-capacity/ category (7 issue directories).

Storage on Aurora PostgreSQL is a different animal from storage on a
self-managed instance: the cluster volume auto-extends in 10 GiB increments
up to 128 TiB, it is shared by every reader, and -- critically -- it does
*not* shrink back when data is deleted. Space freed inside PostgreSQL is
returned to the relation's free space map for reuse, not to the Aurora
storage layer, so a one-off purge of a year of `order_book_snapshots` shows
up as "reusable free space" in PostgreSQL and as "still billed" in
CloudWatch. Every workflow in this category is therefore framed around two
separate questions: what is growing inside the database, and what that
growth actually costs on the Aurora volume.

All scripts here are read-only measurement/observation; the remediation
levers (partition detach, archival, index drops, DDL) live in the
partitioning, archival-and-data-lifecycle, tables-and-indexes and
schema-changes categories and are cross-linked from each workflow.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import (
    ANY_INSTANCE,
    PG_MONITOR,
    PG_MONITOR_PLUS_PGSS,
    READ_ONLY,
    WRITER_ONLY,
    WRITER_PREFERRED,
    md_script,
    sql_script,
)
from .model import Workflow

CATEGORY_SLUG = "storage-and-capacity"
CATEGORY_TITLE = "Storage and Capacity"

_PGSS_PREREQ = (
    "`pg_stat_statements` must already be installed in this database "
    "(`shared_preload_libraries` includes it on the Aurora cluster parameter "
    "group and `CREATE EXTENSION pg_stat_statements;` has been run by an "
    "administrator in a change-managed session). This script never creates it."
)


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


def _pgss_guarded(body: str) -> str:
    """Wrap a pg_stat_statements-dependent query body in an extension-
    presence guard so the script executes safely even when the extension has
    not been created in this database. This never creates the extension
    itself -- it only detects whether it is already available, and prints an
    instructional notice instead of failing with "relation
    pg_stat_statements does not exist" when it is absent.
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
        "       'statistics are unavailable for this capacity check. Ask an administrator '\n"
        "       'to add pg_stat_statements to shared_preload_libraries in the Aurora DB '\n"
        "       'cluster parameter group (a reboot is required) and then install the '\n"
        "       'extension in a change-managed session; the exact statement is documented '\n"
        "       'in the repository prerequisites guide and is deliberately never executed '\n"
        "       'by an investigation script. The remaining scripts in this workflow do not '\n"
        "       'depend on this extension.'\n"
        "                                                                 AS notice;\n"
        "\\endif"
    )


WORKFLOWS: List[Workflow] = []


# ---------------------------------------------------------------------------
# 1. database-growth
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="database-growth",
    title="Database Growth Investigation",
    summary=(
        "The cluster volume is growing and someone needs to say -- with "
        "evidence, not intuition -- which database, schema, and set of "
        "relations is responsible. This is the top-down entry point for the "
        "whole storage category: it walks from cluster volume down through "
        "per-database size, per-schema size, per-relation size, and object "
        "counts, so that by the end you can name the handful of objects "
        "driving the trend and hand off to the narrower workflow that owns "
        "the fix. On an exchange platform the answer is almost always a "
        "small number of append-only relations -- the trade tape, the "
        "double-entry ledger, order-book snapshots, or an audit/compliance "
        "log -- that have no retention policy attached to them."
    ),
    symptoms=[
        "CloudWatch `VolumeBytesUsed` for the Aurora cluster is trending up steadily with no corresponding increase in customer or order volume.",
        "`FreeLocalStorage` on individual instances is falling (this is local scratch space for sorts and temp tables, not the cluster volume -- a different problem, but frequently reported together).",
        "The monthly AWS bill line for Aurora storage and storage I/O is rising faster than trading volume.",
        "`pg_database_size()` for the primary application database has grown materially since the last capacity review.",
        "A backup, `pg_dump`, logical replication initial sync, or clone operation now takes noticeably longer than it did a quarter ago.",
    ],
    business_impact=[
        "Aurora storage is billed on the high-water mark of allocated volume and never shrinks -- an unmanaged growth trend is a permanent, compounding cost increase, not a temporary one.",
        "Larger relations mean longer vacuum cycles, longer index builds, and longer restore/clone times, which directly extends the recovery time objective for the exchange during an incident.",
        "Snapshot and export durations grow with volume size, eroding the margin in the nightly regulatory reporting and reconciliation windows.",
        "Once growth is driven by a genuinely business-critical table (the ledger), the remediation options are slow and risky (partitioning, archival migrations) -- so catching the trend early is worth far more than reacting to it late.",
    ],
    root_causes=[
        "Retention: append-only history (trades, ledger_entries, order_book_snapshots, audit logs, webhook/callback logs) written forever with no retention or archival policy.",
        "Retention: soft-delete patterns where rows are flagged `deleted_at` rather than removed, so the table only ever grows.",
        "Bloat: dead tuples not being reclaimed because autovacuum is not keeping up, or because a long-running transaction or stale replication slot is holding back the xmin horizon.",
        "Indexing: over-indexing on wide, write-heavy tables -- index bytes frequently exceed heap bytes on an over-indexed order table.",
        "Schema design: wide JSON/JSONB payload columns (raw exchange API responses, blockchain transaction bodies) that TOAST heavily and are never pruned.",
        "Schema design: a partitioned table whose maintenance job creates new partitions but never detaches/archives old ones, accumulating both data and catalog entries.",
        "Workload: a genuine, expected increase in trading volume -- which is a capacity-planning outcome, not a defect, but must still be forecast and budgeted.",
        "Operational: an abandoned migration leaving a full backup copy of a large table (`orders_old`, `trades_backup_2024`) behind indefinitely.",
    ],
    investigation_strategy=[
        "Establish the cluster-level picture first from CloudWatch (`VolumeBytesUsed`), because PostgreSQL cannot see the Aurora volume -- SQL only sees logical object size.",
        "Rank databases by size to confirm which database the growth lives in before drilling further.",
        "Rank user schemas within that database to attribute growth to a business domain (trading path, money path, audit/compliance).",
        "Rank individual relations by total size, then break the largest ones into heap / TOAST / index components -- the component split determines which remediation applies.",
        "Rank indexes separately: over-indexing is a common and easily reversible cause that is invisible when looking only at total relation size.",
        "Count objects per schema to detect partition sprawl and catalog inflation, which do not show up as bytes in the top-N relation list.",
        "Finally, if a size-history collector has been deployed, compute actual growth rates over the retention window rather than reasoning from a single snapshot.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`) and `CONNECT` on each database you want to size.",
        "Read access to the AWS Console or CloudWatch for `VolumeBytesUsed` -- the true Aurora storage figure is not available from SQL at all.",
        "Optionally, the `dba_toolkit.table_size_history` collector (see the growth-monitoring automation) for genuine growth-rate rather than point-in-time data.",
    ],
    interpretation_guide=[
        "The sum of `pg_database_size()` across all databases will be *smaller* than CloudWatch `VolumeBytesUsed`. That gap is normal and is made up of WAL, temporary space, the free space map, and -- most importantly -- previously-allocated volume that Aurora never released after deletes. A large and growing gap is itself a finding: it means space is being freed logically but not recovered physically.",
        "If one schema accounts for more than roughly 60-70% of user data, the entire capacity conversation belongs to that schema's owning team; do not spread remediation effort evenly across schemas.",
        "When a relation's `pct_indexes` exceeds 50%, the cheapest available win is almost always index cleanup, not data archival -- it is reversible, needs no data migration, and also reduces write amplification and WAL volume.",
        "A high `pct_toast` points at wide varlena columns (JSON payloads, blobs). These compress well but are expensive to scan; consider whether the payload needs to live in the OLTP database at all, or belongs in object storage with only a reference retained.",
        "A very high `estimated_row_count` with a modest heap size means narrow rows and genuine volume -- that is a partitioning/archival conversation. A modest row count with a large heap means wide rows or bloat -- check dead tuples before assuming it is real data.",
        "A schema with thousands of objects but modest bytes is partition sprawl. The cost there is planning time, catalog size, and lock footprint rather than storage, and the fix is partition retention, not archival.",
    ],
    remediation_immediate=[
        "Nothing in this workflow requires an immediate action -- growth is a trend, not an outage. Resist the urge to run `VACUUM FULL` to 'get space back': it takes an `AccessExclusiveLock` for the duration, and on Aurora it does not return the freed space to the volume anyway.",
        "If free space on the cluster is genuinely close to the 128 TiB ceiling, or `FreeLocalStorage` on an instance is near zero, treat it as an incident and escalate to AWS support immediately rather than attempting a SQL-level fix.",
    ],
    remediation_short_term=[
        "Drop confirmed-unused and duplicate indexes on the largest relations -- see the index-growth workflow here and the drop-index-safely runbook in schema-changes.",
        "Remove abandoned migration leftovers (`*_old`, `*_backup_*` copies of large tables) after confirming with the owning team, using the archival validation process rather than an ad-hoc DROP.",
        "Fix whatever is holding back the xmin horizon (idle-in-transaction sessions, inactive replication slots) so that autovacuum can actually reclaim space for reuse -- see the unexpected-storage-growth workflow.",
        "Attach a retention policy to the top one or two append-only relations, even a conservative one, so the trend stops compounding while the longer-term design work is scheduled.",
    ],
    remediation_long_term=[
        "Partition the largest time-series relations (trade tape, ledger, order-book snapshots) so that retention becomes a metadata-only `DETACH PARTITION` rather than a `DELETE` that generates bloat and WAL.",
        "Move cold history out of the OLTP cluster entirely -- S3/Parquet for analytics, a separate reporting store for compliance queries -- keeping only the hot window online.",
        "Move large opaque payloads (raw exchange API responses, blockchain transaction bodies) to object storage and keep only a key plus indexed metadata in PostgreSQL.",
        "Make retention a schema-design requirement: no new high-volume table ships without a documented retention/partitioning plan and an owner.",
        "Deploy the size-history collector and a capacity dashboard so growth is reviewed on a schedule rather than discovered from a bill.",
    ],
    production_safety=[
        "Every script in this workflow is read-only and safe to run at any time, including during an incident; they touch catalogs and statistics views only.",
        "`pg_total_relation_size()` over many thousands of relations involves one stat() per fork per relation and can take a few seconds on a database with heavy partition sprawl -- prefer running the top-N variants on the writer during a busy period rather than an unbounded scan.",
        "Do not run `VACUUM FULL`, `CLUSTER`, or `pg_repack` as a response to anything found here without going through the table-bloat workflow first; on Aurora they consume the volume's high-water mark twice and do not shrink billed storage.",
    ],
    escalation_criteria=[
        "Cluster volume growth is on a trajectory to reach the Aurora 128 TiB volume limit within the forecast horizon -- involve AWS support and database engineering leadership immediately.",
        "The largest and fastest-growing relation is the financial ledger, where no data may be deleted for regulatory reasons -- this needs a compliance-approved archival design, not a DBA-level fix.",
        "PostgreSQL-reported logical size is flat or falling while CloudWatch `VolumeBytesUsed` keeps climbing -- that pattern is not explainable from inside the database and needs an AWS support case.",
        "Growth rate has changed abruptly (a step change rather than a trend) with no corresponding deployment or volume event -- treat it as unexpected-storage-growth and investigate as a possible defect or runaway process.",
    ],
    related_issues=[
        "../table-growth/README.md",
        "../index-growth/README.md",
        "../capacity-forecasting/README.md",
        "../unexpected-storage-growth/README.md",
        "../../tables-and-indexes/large-tables/README.md",
        "../../partitioning/investigate-partitioning-candidate/README.md",
        "../../archival-and-data-lifecycle/investigate-archiving-candidate/README.md",
    ],
    aurora_notes=[
        "The Aurora cluster volume grows automatically in 10 GiB increments and is never reduced by deleting data. A 2 TB volume that is logically emptied to 200 GB is still a 2 TB volume for billing purposes; the only way to reclaim it is to create a new cluster (snapshot restore, or a logical dump/restore) and cut over.",
        "`pg_database_size()` measures logical PostgreSQL object size only. It has no visibility into the Aurora storage layer, does not include WAL, and cannot be reconciled exactly against `VolumeBytesUsed`. Always quote CloudWatch, not SQL, when discussing billed storage.",
        "Aurora storage is shared across the writer and all readers -- adding readers does not multiply storage, which is why reader-heavy fanout is cheap on Aurora compared with self-managed replicas.",
        "`FreeLocalStorage` is a completely separate, per-instance resource used for temporary files and local scratch. Filling it up will fail queries even when the cluster volume has plenty of room -- see the temp-file-growth workflow, not this one.",
        "Aurora backups and snapshots are incremental against the storage layer and do not consume additional space proportional to logical size, so backup storage is not a useful proxy for database growth.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_database_sizes",
        "Ranks every connectable database in the cluster by logical size to confirm which database the growth actually lives in.",
        sb.database_sizes(),
        "Expect one dominant application database. If a database you did not expect (a staging copy, an old migration target, a forgotten reporting database) appears near the top, that is your finding -- confirm ownership before anything else. Note that the sum of these figures will be smaller than the CloudWatch VolumeBytesUsed figure for the cluster; the difference is WAL, temp space, free space map, and volume Aurora allocated previously and never released.",
        related_scripts="02_schema_size_breakdown.sql",
        table_purpose="Per-database logical size ranking.",
    ),
    sql_script(
        "02", "02_schema_size_breakdown",
        "Attributes the current database's footprint to individual user schemas so growth can be assigned to a business domain and an owning team.",
        sb.schema_sizes(),
        "Look at pct_of_user_data rather than raw bytes. A single schema holding more than roughly 60-70% of user data owns the capacity conversation, and the rest of this investigation should stay inside it. On an exchange schema layout, a dominant trading schema (orders/trades/order_book_snapshots) usually means a retention problem, whereas a dominant ledger/settlement schema means a compliance-constrained archival problem with far fewer options.",
        related_scripts="01_database_sizes.sql, 03_largest_tables.sql",
        table_purpose="Per-schema size and share of user data.",
    ),
    sql_script(
        "03", "03_largest_tables",
        "Ranks individual relations by total size (heap plus indexes plus TOAST) -- the definitive list of what is consuming the volume.",
        sb.largest_tables(),
        "The distribution matters more than the absolute numbers: storage growth is nearly always concentrated, so expect the top 5-10 relations to account for the large majority of the database. Those relations, and only those, are worth remediation effort. A partitioned parent shows a total_size of 0 here because its storage lives in its partitions -- if you see many similarly-named relations with a date suffix, you are looking at a partitioned table and should evaluate it as a whole.",
        related_scripts="04_table_size_components.sql",
        table_purpose="Top relations by total size.",
    ),
    sql_script(
        "04", "04_table_size_components",
        "Splits each large relation into heap, TOAST, and index bytes, because the component mix determines which remediation is actually available.",
        sb.table_size_components(),
        "This is the script that chooses your remediation path. High pct_indexes (over 50%) means the cheapest win is index cleanup -- reversible, no data migration, and it also cuts write amplification and WAL. High pct_toast means wide varlena payloads (JSON order snapshots, raw blockchain transaction bodies) and the question becomes whether that payload belongs in the OLTP database at all. A dominant heap with a proportionate estimated_row_count is genuine data volume, which means partitioning and archival. A dominant heap with a modest row count means wide rows or bloat -- check dead tuples before treating it as real data.",
        related_scripts="03_largest_tables.sql, 05_largest_indexes.sql",
        table_purpose="Heap / TOAST / index split for the largest relations.",
    ),
    sql_script(
        "05", "05_largest_indexes",
        "Ranks individual indexes by size so that over-indexing is visible independently of the tables that own the indexes.",
        sb.largest_indexes(),
        "An individual index approaching or exceeding the size of its own table is worth immediate scrutiny -- it is usually either a multi-column index whose leading column is already covered by another index, or an index on a wide text/JSON column that should be an expression or partial index instead. Cross-check anything that looks suspicious against the index-growth workflow before proposing a drop; size alone is never sufficient evidence.",
        related_scripts="../index-growth/README.md",
        table_purpose="Top indexes by size.",
    ),
    sql_script(
        "06", "06_object_counts_and_growth_history",
        "Counts objects per schema to expose partition sprawl, then reports measured growth over time if the size-history collector has been deployed.",
        sb.object_counts_by_schema() + "\n\n" + sb.table_growth_rate_from_snapshot(),
        "The first result set finds partition sprawl: thousands of objects in one schema costs planning time, catalog size, and DDL lock footprint even when the byte total is modest, and the fix is partition retention rather than archival. The second result set is the only genuine growth-rate measurement in this workflow -- everything above it is a single point in time. If it reports that the history table does not exist, deploy the collector now; a snapshot taken today becomes a trend line in a week, and capacity-forecasting depends on it.",
        related_scripts="../capacity-forecasting/README.md",
        expected_runtime="Low to moderate (a few seconds; longer on a database with tens of thousands of partitions).",
        table_purpose="Object counts per schema plus measured growth from size history.",
    ),
]


# ---------------------------------------------------------------------------
# 2. table-growth
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="table-growth",
    title="Table Growth Investigation",
    summary=(
        "One or more specific tables are growing faster than expected and "
        "you need to establish whether that growth is real inserted data, "
        "update churn leaving dead tuples behind, TOAST expansion from wide "
        "payload columns, or index overhead. These four causes look "
        "identical from a size graph and have completely different fixes, so "
        "this workflow measures write volume alongside size instead of "
        "reasoning from size alone. The canonical exchange offenders are the "
        "trade tape and order table (pure insert volume), the wallet and "
        "balance tables (update churn on a small row set), and audit or "
        "order-book snapshot tables (wide TOASTed payloads written once and "
        "never read again)."
    ),
    symptoms=[
        "A specific table appears at the top of the largest-relations list and its position is climbing week over week.",
        "Queries against the table have become progressively slower even though their plans have not changed and the index set is the same.",
        "Autovacuum runs on this table take dramatically longer than they did last quarter, or never seem to finish before the next one is triggered.",
        "The table's index set is now larger than the table's own heap.",
        "`n_dead_tup` on the table is persistently high and does not fall after an autovacuum cycle completes.",
    ],
    business_impact=[
        "Growth concentrated in the order or trade tables directly degrades the hot path of the exchange -- order placement, matching, and fill lookups.",
        "Growth in the ledger increases settlement and reconciliation batch duration, squeezing the overnight window that regulatory reporting depends on.",
        "Every additional index byte on a write-heavy table multiplies write amplification: the same insert now dirties more pages, generates more WAL, and takes longer to vacuum.",
        "Unbounded growth eventually forces an emergency, high-risk intervention (partitioning or archival under time pressure) on a business-critical table, which is far riskier than doing the same work on a schedule.",
    ],
    root_causes=[
        "Insert volume: genuine, expected append-only growth (trade tape, ledger entries, deposit/withdrawal history) with no retention policy.",
        "Update churn: hot rows updated repeatedly (wallet balances, order status transitions) where each non-HOT update writes a new row version plus a new entry in every index.",
        "Update churn: HOT updates prevented by an index on a frequently-updated column, turning cheap in-page updates into full row-plus-index rewrites.",
        "Bloat: dead tuples accumulating because autovacuum is throttled, starved of workers, or repeatedly cancelled by conflicting locks.",
        "Bloat: the xmin horizon held back by a long-running transaction, an idle-in-transaction session, or an inactive replication slot, so vacuum cannot remove tuples it otherwise would.",
        "TOAST: wide JSON/JSONB or bytea columns (raw venue responses, signed transaction payloads) pushing large values out of line and growing the TOAST relation faster than the heap.",
        "Indexes: indexes added incrementally over time to fix individual slow queries, never reviewed as a set.",
        "Schema: soft deletes (`deleted_at IS NOT NULL`) or status-flag patterns that keep historical rows in the hot table forever.",
    ],
    investigation_strategy=[
        "Rank tables by total size to confirm exactly which relations are in scope, and record the numbers so the next run can be compared against them.",
        "Split each in-scope relation into heap, TOAST, and index components -- this single step eliminates two of the four possible causes immediately.",
        "Measure write volume per table (inserts, updates, deletes, HOT update ratio) to distinguish append-only growth from update churn.",
        "Check dead tuple accumulation to establish whether a meaningful fraction of the size is reclaimable space rather than live data.",
        "Compare measured growth against the size history collector, if deployed, to get a real rate rather than a snapshot.",
        "Drill into the single worst table for its exact size, row estimates, and vacuum/analyze timestamps before deciding on remediation.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`) and `CONNECT` on the target database.",
        "Awareness of when statistics were last reset (`pg_stat_database.stats_reset`) -- every write counter here is cumulative since that moment, and a recent failover resets them.",
        "Ideally the `dba_toolkit.table_size_history` collector deployed, so growth can be measured rather than inferred.",
    ],
    interpretation_guide=[
        "High `n_tup_ins` with near-zero `n_tup_upd` and `n_tup_del` is clean append-only growth. There is no bloat to reclaim and no vacuum tuning that will help -- the only levers are partitioning, retention, and archival.",
        "High `n_tup_upd` with a low `pct_hot_updates` is the most expensive pattern in PostgreSQL: every update writes a new row version *and* a new entry in every index on the table. Look for an index on the column being updated (a `status` or `updated_at` column is the usual culprit) and consider whether it can be dropped or the fillfactor lowered to allow HOT updates.",
        "`n_dead_tup` above roughly 20% of `n_live_tup` that persists across autovacuum cycles means space is being consumed by tuples that *should* be reclaimable -- this is a vacuum problem, not a growth problem, and belongs in the vacuum category.",
        "A TOAST share above roughly 40% means the table is really a document store wearing a relational table's clothes. Evaluate whether the payload is ever queried, or only ever written and occasionally fetched by primary key -- in the latter case object storage is usually the right home.",
        "`estimated_row_count` from `reltuples` is only as fresh as the last vacuum or analyze; if `last_analyze` and `last_autoanalyze` are both old, treat the row estimate as unreliable and do not use it for projections.",
        "If growth is real, sustained, and in a table that cannot be deleted from for regulatory reasons, stop investigating and start designing: this is a partitioning-plus-archival project, and the only question left is timing.",
    ],
    remediation_immediate=[
        "None required -- table growth is a trend. Do not run `VACUUM FULL` on a large production table as a reflex; it takes an `AccessExclusiveLock` for its entire duration and will stall the trading path.",
        "If growth turns out to be dead tuples rather than live data, clearing whatever is holding back the xmin horizon (an idle-in-transaction session, an abandoned replication slot) is genuinely immediate and low-risk.",
    ],
    remediation_short_term=[
        "Drop confirmed-unused and duplicate indexes on the table to cut both stored bytes and per-write amplification.",
        "Lower `fillfactor` on an update-heavy table (via a schema-changes DDL runbook) so future updates can take the HOT path and avoid touching every index.",
        "Tune autovacuum per-table (`autovacuum_vacuum_scale_factor`, cost limits) so a large table is vacuumed on a sensible cadence rather than the cluster default, which scales badly at size.",
        "Introduce a conservative retention window on the table's oldest data, even before a full partitioning project, to arrest the trend.",
    ],
    remediation_long_term=[
        "Partition the table on its natural time or tenant key so retention becomes a metadata-only `DETACH PARTITION` instead of a `DELETE` that generates bloat and WAL.",
        "Split wide payload columns into a separate relation, or move them to object storage with only a reference and indexed metadata retained in PostgreSQL.",
        "Replace soft-delete and status-history-in-place patterns with an explicit history table (or an event log) that has its own independent retention.",
        "Add growth budgets and retention policies to the schema review checklist so this table is the last one that reaches this state unmanaged.",
    ],
    production_safety=[
        "Every script here is read-only. The write-volume and dead-tuple scripts read cumulative statistics views and are safe under any load.",
        "The single-table deep-dive script ships with an illustrative default table name guarded by `to_regclass()`, so it prints guidance rather than failing if that table does not exist in your database.",
        "Do not use `count(*)` on a multi-hundred-GB table to 'check the real row count' during a busy period -- it is a full heap scan. The `reltuples` estimate plus `last_analyze` is sufficient for capacity work.",
    ],
    escalation_criteria=[
        "The fastest-growing table is the financial ledger or another relation under a regulatory retention mandate -- archival design needs compliance sign-off before any DBA action.",
        "Growth rate has more than doubled with no corresponding change in trading volume or deployment -- treat it as unexpected-storage-growth rather than normal capacity planning.",
        "Remediation requires partitioning a table that is on the live order-placement path -- that migration needs database engineering leadership and a formal change window.",
        "Dead tuples remain high across multiple autovacuum cycles despite no long-running transactions and no lagging replication slots -- escalate to the vacuum category and, if unexplained, to AWS support.",
    ],
    related_issues=[
        "../database-growth/README.md",
        "../index-growth/README.md",
        "../capacity-forecasting/README.md",
        "../../tables-and-indexes/rapidly-growing-tables/README.md",
        "../../vacuum-and-autovacuum/table-bloat/README.md",
        "../../partitioning/investigate-partitioning-candidate/README.md",
        "../../archival-and-data-lifecycle/investigate-archiving-candidate/README.md",
    ],
    aurora_notes=[
        "Deleting rows from a large table on Aurora frees space for reuse inside the relation but returns nothing to the Aurora volume, and the delete itself generates WAL and dead tuples. Partition detach avoids both problems and is strongly preferred at exchange data volumes.",
        "Autovacuum cost parameters are set through the Aurora cluster parameter group, not `postgresql.conf`; per-table `ALTER TABLE ... SET (autovacuum_*)` overrides still work normally and are the right tool for one oversized relation.",
        "`pg_stat_all_tables` counters reset on instance restart and on failover. After an Aurora failover the new writer starts from zero, so a sudden 'drop' in write volume immediately after a failover event is an artifact, not a workload change.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_largest_tables",
        "Establishes which relations are actually in scope, ranked by total size, before any deeper analysis.",
        sb.largest_tables(),
        "Record these numbers somewhere durable, not just your terminal scrollback -- a single size snapshot becomes a growth rate the moment you have a second one. Expect concentration: if the top five relations are not most of the database, the problem is probably partition sprawl or index overhead rather than one runaway table, and database-growth is the better starting point.",
        related_scripts="02_table_size_components.sql",
        table_purpose="Top relations by total size.",
    ),
    sql_script(
        "02", "02_table_size_components",
        "Splits the in-scope relations into heap, TOAST, and index bytes to narrow four possible growth causes down to one or two.",
        sb.table_size_components(),
        "Use this to eliminate causes rather than confirm them. A pct_indexes above 50% makes index cleanup the first move regardless of what else is true. A pct_toast above 40% means the growth is in wide payload columns and no amount of vacuum or index work will touch it. If both are low, the growth is heap -- real rows or dead ones -- and scripts 03 and 04 tell you which.",
        related_scripts="01_largest_tables.sql, 03_write_volume_by_table.sql",
        table_purpose="Heap / TOAST / index split per relation.",
    ),
    sql_script(
        "03", "03_write_volume_by_table",
        "Measures inserts, updates, deletes, and the HOT update ratio per table to distinguish append-only growth from update churn.",
        sb.write_volume_by_table(),
        "This is the decisive script. High n_tup_ins with negligible updates and deletes is clean append-only growth: partitioning and retention are the only levers, and vacuum tuning will not help. High n_tup_upd with pct_hot_updates well below 50% is the expensive case -- every update rewrites the row and every index entry for it, so look for an index on the column being updated (status, updated_at) and consider dropping it or lowering fillfactor. Always check stats_reset before drawing conclusions: an Aurora failover zeroes these counters, so a low number may mean a recent failover rather than a quiet table.",
        related_scripts="04_dead_tuples_ranked.sql",
        table_purpose="Per-table write volume and HOT update ratio.",
    ),
    sql_script(
        "04", "04_dead_tuples_ranked",
        "Quantifies how much of each table's footprint is dead tuples awaiting reclamation rather than live data.",
        sb.dead_tuples_ranked(),
        "A dead tuple ratio above roughly 20% that persists across autovacuum cycles means a material share of the table's size is reclaimable space, not growth -- the investigation should move to the vacuum category and look for a held-back xmin horizon (long-running transactions, idle-in-transaction sessions, inactive replication slots). Conversely, a large table with a very low dead tuple ratio is genuinely full of live data, which confirms the partitioning/archival path.",
        related_scripts="../../vacuum-and-autovacuum/dead-tuples/README.md",
        table_purpose="Dead tuple accumulation per table.",
    ),
    sql_script(
        "05", "05_measured_growth_from_history",
        "Reports actual measured growth per table over the retention window, using the size-history collector rather than a single snapshot.",
        sb.table_growth_rate_from_snapshot(),
        "This is the only script in the workflow that measures a rate rather than a level. Compare growth_over_window against the current total size from script 01: a table that grew by 20% of its own size in 30 days doubles in well under a year, which is the number that makes the capacity case. If the script reports that the history table does not exist, deploy the collector today -- it costs nothing to run and every day of delay is a day of trend data you cannot recover retroactively.",
        related_scripts="../capacity-forecasting/README.md",
        table_purpose="Measured per-table growth over the history window.",
    ),
    sql_script(
        "06", "06_single_table_deep_dive",
        "Drills into one named table for exact size, live/dead row estimates, and vacuum/analyze recency before committing to a remediation path.",
        sb.target_table_size_detail(),
        "Read last_autovacuum and last_autoanalyze first: if both are stale, n_live_tup and n_dead_tup are stale too and nothing else on this row can be trusted. A healthy large table shows recent autovacuum activity, a dead tuple count well under 20% of live tuples, and an index_count you can justify one index at a time. An index_count in double digits on a write-heavy exchange table is itself the finding. Edit the schema_name and table_name variables at the top to point at your real target -- the shipped default is illustrative and guarded, so running it unmodified prints guidance instead of failing.",
        related_scripts="../../tables-and-indexes/large-tables/README.md",
        table_purpose="Single-table size, row estimates, and maintenance recency.",
    ),
]


# ---------------------------------------------------------------------------
# 3. index-growth
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="index-growth",
    title="Index Growth Investigation",
    summary=(
        "Index bytes are growing faster than the tables they support, or the "
        "index set on a hot relation has quietly become larger than the "
        "relation itself. Index growth is the most commonly overlooked "
        "storage problem because indexes are added one at a time to fix one "
        "slow query at a time and are almost never reviewed as a set. The "
        "cost is not only storage: every index on a write-heavy exchange "
        "table multiplies the WAL generated by each insert, forces every "
        "non-HOT update to write an additional index entry, and lengthens "
        "every vacuum cycle. This workflow measures the index footprint, "
        "separates genuine bloat from genuine size, and produces a defensible "
        "drop list -- it never drops anything itself."
    ),
    symptoms=[
        "Total index size on a core table (orders, trades, ledger_entries) now exceeds the table's own heap size.",
        "Write latency on the trading path has crept upward over months with no query plan or hardware change.",
        "Autovacuum on a specific table takes far longer than its heap size alone would suggest, because each index must be scanned in the index cleanup phase.",
        "A REINDEX of one index reclaims a surprisingly large amount of space, implying the rest are similarly bloated.",
        "The largest-indexes report contains indexes nobody on the owning team recognizes or can attribute to a query.",
    ],
    business_impact=[
        "Write amplification on the order and trade path directly increases order-placement latency, which is the most latency-sensitive operation the exchange performs.",
        "Extra index bytes are stored, backed up, replicated to every reader through the Aurora storage layer, and vacuumed forever -- the cost is recurring, not one-off.",
        "Longer vacuum cycles raise the risk of falling behind on freezing, which is the path to transaction ID wraparound pressure on a high-write cluster.",
        "Unused indexes give a false sense of query coverage during incident response, sending engineers looking for plan problems that are really write-path problems.",
    ],
    root_causes=[
        "Accretion: indexes added incrementally to fix individual slow queries, with no review of whether an existing index already covered the access pattern via its leading columns.",
        "Duplication: structurally identical indexes created by different teams, or by an ORM migration plus a hand-written migration, on the same columns.",
        "Redundancy: a single-column index fully covered by the leading column of an existing multi-column index.",
        "Bloat: B-tree pages left partially empty after heavy update/delete churn; PostgreSQL reuses free space within an index but does not return whole pages to the filesystem without a REINDEX.",
        "Design: indexes on wide text/JSONB columns that should have been expression indexes, partial indexes, or not indexes at all.",
        "Failed builds: INVALID indexes left behind by an interrupted concurrent index build, consuming full storage while being unusable by the planner.",
        "Partitioning: an index created on a partitioned parent propagating to hundreds of partitions, multiplying a single design mistake across the whole table.",
    ],
    investigation_strategy=[
        "Rank indexes by raw size to see where the bytes are.",
        "Compute the index-to-heap ratio per table, which is the metric that actually flags over-indexing (raw size alone just re-finds your biggest tables).",
        "Pull index size alongside usage counters and last-scan timestamps so size and value can be judged together.",
        "Identify never-scanned indexes as drop candidates, deliberately excluding constraint-backing indexes.",
        "Identify structurally duplicate indexes, which are the safest possible drop candidates.",
        "Identify INVALID indexes from failed builds -- pure waste with no possible query benefit.",
        "Only then assemble the drop list and hand off to the schema-changes drop-index-safely runbook.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`) and `CONNECT` on the target database.",
        "Knowledge of when statistics were last reset -- `idx_scan` counters are cumulative since then, and an Aurora failover resets them to zero, which makes every index briefly look unused.",
        "Agreement with the owning application team that they will review the drop list before anything is executed.",
    ],
    interpretation_guide=[
        "An `index_to_heap_ratio` above 1.0 on a narrow, read-heavy lookup table is normal and healthy. The same ratio on a wide, write-heavy order or ledger table is a strong over-indexing signal, because the write amplification cost scales with index count while the read benefit usually does not.",
        "`idx_scan = 0` is necessary but nowhere near sufficient evidence for dropping an index. Confirm the counter has been accumulating across at least one full business cycle -- including month-end and quarter-end reconciliation, regulatory reporting runs, and any quarterly batch jobs -- before treating zero as real.",
        "`last_idx_scan` (PostgreSQL 16+) is far more trustworthy than `idx_scan` alone, because it survives as a timestamp rather than a counter: an index last scanned eight months ago is genuinely unused in a way a zero counter after a recent failover is not.",
        "Structurally duplicate indexes are the highest-confidence drop candidates in this entire workflow: by definition the remaining copy serves exactly the same queries, so the risk of dropping the extra one is close to zero.",
        "An INVALID index is pure cost with zero benefit -- the planner will not use it, but writes still maintain it and vacuum still processes it. These should be dropped unconditionally and rebuilt only if the original need still exists.",
        "Indexes that back a primary key, unique, exclusion, or foreign-key constraint must never be dropped based on scan counts. They exist for correctness, and an unindexed foreign key turns every parent delete into a sequential scan of the child table.",
        "Bloat that a REINDEX would recover looks like a large index with a low tuple-to-byte density. `REINDEX INDEX CONCURRENTLY` recovers it without blocking, but it needs enough free space to build the new index alongside the old one -- on Aurora, that space is permanently added to the volume high-water mark.",
    ],
    remediation_immediate=[
        "None. Nothing in this workflow justifies an immediate change, and dropping an index during an incident on the basis of a scan counter is a reliable way to turn one incident into two.",
        "The single exception: an INVALID index from a failed build can be dropped at any time with no query-plan risk, since the planner never uses it.",
    ],
    remediation_short_term=[
        "Drop confirmed INVALID indexes using the failed-index-build runbook in schema-changes.",
        "Drop confirmed structural duplicates using the drop-index-safely runbook, keeping the copy with the more descriptive name and the longer usage history.",
        "`REINDEX INDEX CONCURRENTLY` the most bloated large indexes to recover empty pages without taking a blocking lock.",
        "Consolidate a redundant single-column index into an existing multi-column index where the multi-column index already leads with that column.",
    ],
    remediation_long_term=[
        "Add index review to the schema change checklist: every new index must name the query it serves and confirm no existing index already covers that access pattern.",
        "Replace broad indexes with partial indexes where the workload only ever queries a subset (`WHERE status = 'open'` on an order table typically indexes a tiny fraction of the rows).",
        "Schedule a recurring index audit (quarterly is typical) so accretion is caught as a small correction rather than a large project.",
        "On partitioned tables, review index definitions at the parent level, since one unnecessary index there is replicated across every partition.",
    ],
    production_safety=[
        "Every script in this workflow is read-only and safe during an incident.",
        "The index-to-heap ratio script calls `pg_indexes_size()` and `pg_relation_size()` per relation; on a database with tens of thousands of partitions this can take a few seconds, and it filters to relations above 100 MB by default for exactly that reason.",
        "Never act on this workflow's output directly. Every drop must go through the schema-changes drop-index-safely runbook, which includes the transaction-rollback rehearsal technique for proving a drop is safe before making it permanent.",
    ],
    escalation_criteria=[
        "A proposed drop target is an index on the live order-matching or wallet-balance path -- the owning team must sign off, because a wrong drop there is an immediate trading incident.",
        "Index bloat is severe enough that the REINDEX rebuild would meaningfully raise the Aurora volume high-water mark -- that is a cost decision, not a DBA decision.",
        "The same table keeps accumulating new indexes between audits -- escalate as a process problem to engineering leadership rather than repeatedly cleaning up after it.",
        "An index cannot be attributed to any query or team after investigation -- do not guess; escalate for ownership before dropping anything.",
    ],
    related_issues=[
        "../table-growth/README.md",
        "../database-growth/README.md",
        "../../tables-and-indexes/unused-indexes/README.md",
        "../../tables-and-indexes/duplicate-indexes/README.md",
        "../../tables-and-indexes/invalid-indexes/README.md",
        "../../vacuum-and-autovacuum/index-bloat/README.md",
        "../../schema-changes/drop-index-safely/README.md",
    ],
    aurora_notes=[
        "`REINDEX INDEX CONCURRENTLY` builds the replacement index alongside the original, so peak space usage is roughly double the index size. On Aurora that peak permanently raises the volume high-water mark even after the old index is dropped -- factor it into the cost case before reindexing a very large index.",
        "`idx_scan` and `last_idx_scan` reset to zero/NULL when an instance restarts or the cluster fails over. After an Aurora failover, every index on the new writer looks unused; wait for a full business cycle of fresh statistics before making any drop decision.",
        "Index usage counters are per-instance. An index used exclusively by reporting queries pinned to a reader will show `idx_scan = 0` on the writer. Always check usage on every instance in the cluster before concluding an index is unused.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_largest_indexes",
        "Ranks every index in the database by raw size to establish where index bytes are concentrated.",
        sb.largest_indexes(),
        "This is a starting inventory, not a verdict -- the biggest index on the biggest table is usually entirely legitimate. What you are looking for is an index whose size is disproportionate to its table, or an index name nobody recognizes. Note the totals so you can compare against the table sizes from the table-growth workflow.",
        related_scripts="02_index_to_table_size_ratio.sql",
        table_purpose="Top indexes by size.",
    ),
    sql_script(
        "02", "02_index_to_table_size_ratio",
        "Computes index bytes relative to heap bytes per table, which is the metric that actually identifies over-indexing.",
        sb.index_to_table_size_ratio(),
        "A ratio above 1.0 means more storage is spent on indexes than on the data itself. Treat that as normal on a narrow, read-heavy reference table and as a red flag on a wide, write-heavy table such as orders or ledger_entries, where each additional index multiplies WAL volume and vacuum cost on the hottest write path in the system. Read index_count alongside the ratio: eight or more indexes on a high-throughput table almost always contains at least one redundancy. The script filters out relations under 100 MB by default -- adjust min_total_bytes if you need a wider view.",
        related_scripts="03_index_usage_and_bloat.sql",
        expected_runtime="Low to moderate (a few seconds on a database with many partitions).",
        table_purpose="Index-to-heap size ratio per table.",
    ),
    sql_script(
        "03", "03_index_usage_and_bloat",
        "Pairs index size with scan counters and last-scan timestamps so cost and value can be judged in the same view.",
        sb.index_bloat_and_usage(),
        "Read size and usage together: a large index with millions of scans is earning its keep, and a large index with a last_idx_scan months in the past is not. last_idx_scan is the more reliable of the two signals because it is a timestamp rather than a counter -- counters reset on failover, timestamps simply stop advancing. Also check indisvalid here: a false value means a failed build left the index unusable while still consuming its full size.",
        related_scripts="04_unused_index_candidates.sql",
        table_purpose="Index size, scan counters, and last-scan recency.",
    ),
    sql_script(
        "04", "04_unused_index_candidates",
        "Lists never-scanned, non-constraint-backing indexes as drop candidates for review by the owning team.",
        sb.unused_indexes(),
        "This is a candidate list, never a decision. Before proposing any drop, confirm three things: statistics have been accumulating across at least one full business cycle including month-end and regulatory reporting runs, the index shows zero scans on the readers as well as the writer (reporting traffic is often pinned to a reader), and the owning application team recognizes the access pattern it was built for. Constraint-backing and primary-key indexes are deliberately excluded here because they exist for correctness rather than performance.",
        related_scripts="../../schema-changes/drop-index-safely/README.md",
        table_purpose="Never-scanned index drop candidates.",
    ),
    sql_script(
        "05", "05_duplicate_index_candidates",
        "Finds structurally identical indexes on the same table -- the highest-confidence, lowest-risk drop candidates available.",
        sb.duplicate_indexes(),
        "Anything reported here is wasted storage and wasted write overhead by definition: the duplicate serves exactly the same queries as the copy you keep, so the planner cannot regress. Keep the copy with the clearer name and the longer usage history from script 03, and drop the other through the drop-index-safely runbook. Duplicates most often come from an ORM migration and a hand-written migration creating the same index under different names.",
        related_scripts="../../tables-and-indexes/duplicate-indexes/README.md",
        table_purpose="Structurally duplicate indexes.",
    ),
    sql_script(
        "06", "06_invalid_index_waste",
        "Finds indexes left INVALID by an interrupted build, which consume full storage while being unusable by the planner.",
        sb.invalid_indexes(),
        "Every row here is pure waste: the planner ignores an INVALID index entirely, but every write still maintains it and every vacuum still processes it. The usual cause is a concurrent index build that was cancelled, hit a statement timeout, or died with its session. Drop these unconditionally via the failed-index-build runbook, and only rebuild if the original query need still exists -- often it does not, because someone already solved the problem another way after the build failed.",
        related_scripts="../../schema-changes/failed-index-build/README.md",
        table_purpose="INVALID indexes wasting storage.",
    ),
]


# ---------------------------------------------------------------------------
# 4. wal-generation
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="wal-generation",
    title="WAL Generation Investigation",
    summary=(
        "Write-ahead log generation is the hidden multiplier behind almost "
        "every Aurora storage and replication problem: the volume of redo a "
        "workload produces determines storage I/O cost, reader apply lag, "
        "checkpoint pressure, and how much space a lagging replication slot "
        "can pin. This workflow measures how much WAL the cluster is "
        "producing and attributes it to specific tables and statements. It "
        "opens with an important Aurora caveat -- the community "
        "`pg_stat_wal` view is not implemented on Aurora PostgreSQL -- and "
        "then works around it using per-table write volume, checkpoint "
        "behavior, and `pg_stat_statements`, backed by CloudWatch for the "
        "authoritative cluster-level numbers."
    ),
    symptoms=[
        "Aurora reader instances show rising `AuroraReplicaLag` during periods of heavy writing, even though reader CPU is low.",
        "CloudWatch `VolumeWriteIOPs` and `WriteThroughput` are climbing faster than the transaction rate.",
        "Storage I/O charges on the AWS bill are growing out of proportion to data volume.",
        "Checkpoints are frequently forced (requested) rather than timed, indicating WAL is filling `max_wal_size` faster than the checkpoint interval.",
        "A logical replication slot or AWS DMS task is falling behind and retaining a growing amount of WAL.",
        "A batch job (settlement, reconciliation, end-of-day mark-to-market) reliably causes a lag spike on every reader while it runs.",
    ],
    business_impact=[
        "Reader lag means stale data on any read path routed to a reader -- balance displays, order history, and reporting can show a customer state that is seconds behind reality, which is both a support burden and a trust problem on an exchange.",
        "Aurora bills storage I/O per request; excessive WAL generation is a direct, ongoing cash cost independent of stored bytes.",
        "High WAL volume lengthens crash recovery and failover, extending the exchange's effective downtime during an incident.",
        "A replication slot pinned behind a WAL flood can retain enough log to threaten cluster storage, which escalates from a performance issue to an availability issue.",
    ],
    root_causes=[
        "Volume: genuine high write throughput -- order placement, fills, and ledger postings during a market event.",
        "Write amplification: over-indexing, where every insert writes one heap tuple and N index entries, each of which is WAL-logged.",
        "Write amplification: non-HOT updates caused by an index on a frequently-updated column, turning a cheap in-page update into a full row-plus-all-indexes rewrite.",
        "Full page writes: the first modification of a page after each checkpoint writes the entire page to WAL, so frequent checkpoints multiply WAL volume dramatically.",
        "Checkpoint tuning: `max_wal_size` too small for the write rate, forcing requested checkpoints and therefore more full-page-write bursts.",
        "Batch patterns: large single-transaction bulk operations (a full-table `UPDATE`, a mass backfill, an unbatched purge) generating a burst of WAL that readers must apply serially.",
        "Maintenance: index builds, `VACUUM FULL`, and table rewrites generating enormous WAL volumes in a short window.",
        "Bloat churn: a heavily bloated table generating far more page modifications than the logical change rate would suggest.",
    ],
    investigation_strategy=[
        "Confirm which instance you are connected to and whether the community WAL statistics view is available at all -- on Aurora it is not, and knowing that up front prevents chasing a dead end.",
        "Read checkpoint statistics, since forced checkpoints and full-page-write amplification are the most common tunable cause.",
        "Capture the WAL-related configuration and the current WAL position, taking two samples a known interval apart to derive a real bytes-per-second rate.",
        "Attribute WAL to statements using `pg_stat_statements`, noting the Aurora reporting caveat for its WAL columns.",
        "Attribute WAL to tables using per-table write volume and HOT update ratios, which are reliable on Aurora where the WAL view is not.",
        "Check replication slots for retained WAL, since a stalled consumer converts a transient WAL spike into persistent storage consumption.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`).",
        "`pg_stat_statements` installed for the statement-level attribution script; it is never created by these scripts.",
        "CloudWatch access for `VolumeWriteIOPs`, `WriteThroughput`, and `AuroraReplicaLag` -- on Aurora these are the authoritative WAL-volume signals, not any SQL view.",
        "The writer endpoint for the WAL position script; WAL position functions cannot be called on an instance in recovery.",
    ],
    interpretation_guide=[
        "If the WAL activity script reports that `pg_stat_wal` is unavailable, that is the expected and correct result on Aurora PostgreSQL -- not an error and not a permissions problem. Aurora writes redo directly to its distributed storage layer rather than to local WAL segments, so the community WAL-writer counters have nothing to report. Use CloudWatch and the per-table/per-statement attribution scripts instead.",
        "A `pct_forced_checkpoints` above roughly 10% means `max_wal_size` is too small for the write rate. This matters far more than it sounds: each checkpoint restarts the full-page-write cycle, so frequent checkpoints multiply total WAL volume rather than merely rescheduling it.",
        "Take two samples of the WAL position script several minutes apart and difference them to get bytes per second. A single sample tells you almost nothing; the rate is the whole point.",
        "In `pg_stat_statements`, a `wal_bytes` of 0 for a statement you know performs writes means the instrumentation did not observe it on this engine version -- it is not evidence the statement is WAL-cheap. Corroborate with per-table write counters before concluding anything.",
        "A table with high `n_tup_upd` and a low `pct_hot_updates` is generating far more WAL per logical change than necessary. This is usually the single largest addressable source of WAL amplification and the fix (dropping an index on the updated column, or lowering fillfactor) is cheap relative to the benefit.",
        "A replication slot with a large `retained_wal` and `active = false` is an abandoned consumer. It pins WAL indefinitely and will keep doing so until the slot is dropped -- this is one of the few storage problems that genuinely gets worse the longer you leave it.",
    ],
    remediation_immediate=[
        "If a single batch job is flooding WAL and readers are lagging badly, pause or throttle that job -- this is the fastest lever available and has no lasting side effects.",
        "If an inactive replication slot is retaining a dangerous amount of WAL and its consumer is confirmed dead, drop the slot. Confirm with the owning team first: dropping an active consumer's slot forces a full resynchronization.",
        "Do not start an index build, bulk backfill, or table rewrite while WAL generation is already elevated and readers are lagging.",
    ],
    remediation_short_term=[
        "Increase `max_wal_size` in the Aurora cluster parameter group to reduce forced checkpoints, which reduces full-page-write amplification.",
        "Batch large write operations into small committed chunks rather than single large transactions, so WAL is produced as a steady stream readers can keep up with.",
        "Drop unused and duplicate indexes on the highest-write tables -- each one removed is a WAL entry removed from every single insert and non-HOT update on that table.",
        "Reschedule heavy batch jobs (settlement, reconciliation, reporting extracts) outside peak trading hours so WAL bursts do not coincide with peak read traffic on the readers.",
    ],
    remediation_long_term=[
        "Lower `fillfactor` on update-heavy tables so more updates take the HOT path and skip index maintenance entirely.",
        "Partition large time-series tables so that retention is a metadata-only detach rather than a `DELETE` that generates WAL proportional to the data removed.",
        "Review the index set on every high-write table against its actual queries, and make write amplification an explicit consideration in index review.",
        "Move analytics and reporting workloads that drive large temporary write activity off the OLTP cluster entirely.",
        "Build WAL rate and replica lag into capacity dashboards so a step change is noticed immediately rather than at the next bill.",
    ],
    production_safety=[
        "All scripts in this workflow are read-only.",
        "The WAL position script calls `pg_current_wal_lsn()`, which raises an error on an instance in recovery; it detects recovery state first and takes a reader-safe branch instead, so it is safe to run anywhere.",
        "The replication slot script also reads the current WAL position and is therefore writer-only in practice -- run it against the cluster writer endpoint.",
        "Never drop a replication slot to reclaim WAL without confirming the consumer is genuinely dead. Dropping a live slot forces the consumer into a full resynchronization, which is a far larger event than the storage it frees.",
    ],
    escalation_criteria=[
        "Reader lag is high enough that reads are returning materially stale balances or order states to customers -- this is a customer-facing correctness issue and should be treated as an incident.",
        "A replication slot is retaining enough WAL to threaten cluster storage and the consumer cannot be contacted or recovered -- escalate for an authoritative decision to drop it.",
        "WAL generation has stepped up sharply with no deployment, no volume change, and no identifiable batch job -- investigate as unexpected-storage-growth and involve application engineering.",
        "CloudWatch shows write I/O rising while every in-database write counter is flat -- that discrepancy is not explainable from inside the database and needs an AWS support case.",
    ],
    related_issues=[
        "../unexpected-storage-growth/README.md",
        "../database-growth/README.md",
        "../capacity-forecasting/README.md",
        "../../replication-and-ha/replication-lag/README.md",
        "../../replication-and-ha/reader-lag-investigation/README.md",
        "../../performance/high-iops/README.md",
        "../../tables-and-indexes/unused-indexes/README.md",
    ],
    aurora_notes=[
        "`pg_stat_wal` exists in the Aurora catalog but cannot be selected: the underlying `pg_stat_get_wal()` function is not implemented, and querying the view raises an error. This is by design -- Aurora writes redo to its distributed storage layer rather than to local WAL segments, so the community WAL-writer counters have no meaning. The first script in this workflow detects Aurora before ever touching the view.",
        "On Aurora, the authoritative WAL-volume signals are CloudWatch `VolumeWriteIOPs`, `WriteThroughput`, and `WriteIOPS`, plus the Performance Insights wait-event breakdown. No SQL view substitutes for them.",
        "Aurora readers do not replay a WAL stream from the writer the way a standard physical standby does; they read redo from the shared storage volume. WAL volume still drives reader lag, but `pg_stat_replication` will not show Aurora readers at all -- only genuine streaming consumers such as logical subscribers or DMS tasks.",
        "`full_page_writes` cannot be disabled on Aurora and should not be reasoned about as a tuning lever; reduce full-page-write volume by reducing checkpoint frequency (a larger `max_wal_size`) instead.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_cluster_wal_activity",
        "Reports cluster-wide WAL generation counters, detecting up front whether this engine exposes them at all.",
        sb.wal_activity(),
        "On Aurora PostgreSQL this script will report that pg_stat_wal is not available, and that is the correct, expected outcome rather than a failure -- Aurora writes redo to its distributed storage layer, so the community WAL-writer counters do not exist. Treat that output as your instruction to use CloudWatch (VolumeWriteIOPs, WriteThroughput) for cluster-level WAL volume, and the remaining scripts in this workflow for in-database attribution. On community PostgreSQL you get real counters: compare wal_fpi against wal_records, because a high full-page-image share points directly at checkpoint frequency as the amplifier.",
        related_scripts="02_checkpoint_activity.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="Cluster WAL counters (with Aurora availability detection).",
    ),
    sql_script(
        "02", "02_checkpoint_activity",
        "Reports checkpoint frequency and the forced-versus-timed split, the most common tunable cause of WAL amplification.",
        sb.checkpoint_activity(),
        "pct_forced_checkpoints above roughly 10% means max_wal_size is too small for the current write rate. This matters more than it first appears: every checkpoint restarts the full-page-write cycle, so the first write to each page after a checkpoint logs the entire page. Frequent checkpoints therefore multiply total WAL volume rather than just rescheduling it, and raising max_wal_size in the Aurora cluster parameter group is usually the single highest-leverage change available. Note that PostgreSQL 17 moved these counters out of pg_stat_bgwriter into pg_stat_checkpointer -- querying the old location returns nothing useful.",
        related_scripts="03_wal_settings_and_position.sql",
        execution_location=WRITER_PREFERRED,
        table_purpose="Checkpoint frequency and forced-checkpoint share.",
    ),
    sql_script(
        "03", "03_wal_settings_and_position",
        "Captures WAL-related configuration and an engine-safe write-volume reference; community PostgreSQL also reports the current WAL position for rate sampling.",
        """
-- Part 1: the WAL and checkpoint settings that determine how much WAL this
-- workload produces and how often the full-page-write cycle restarts. On
-- Aurora these come from the DB cluster parameter group, not
-- postgresql.conf; the `source` column shows whether the live value came
-- from the parameter group (reported as a configuration file), a
-- session-level SET, or the built-in default.
SELECT
    name,
    setting,
    unit,
    context,
    source,
    short_desc
FROM pg_settings
WHERE name IN (
    'wal_level', 'max_wal_size', 'min_wal_size', 'wal_compression',
    'wal_buffers', 'full_page_writes', 'synchronous_commit',
    'checkpoint_timeout', 'checkpoint_completion_target',
    'wal_keep_size', 'max_slot_wal_keep_size', 'wal_writer_delay'
)
ORDER BY name;

-- Part 2: current WAL position. Aurora PostgreSQL 17.7 rejects the upstream
-- WAL/LSN functions even for read-only inspection. Detect Aurora before
-- psql sends any statement containing those functions; use AWS-native
-- telemetry on Aurora and retain upstream LSN diagnostics only for
-- community PostgreSQL.
SELECT (
    current_setting('aurora_version', true) IS NOT NULL
    OR current_setting('rds.extensions', true) IS NOT NULL
    OR EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'aurora_version')
)                                                                AS is_aurora
\\gset

\\if :is_aurora
SELECT
    CASE WHEN pg_is_in_recovery() THEN 'reader' ELSE 'writer' END AS instance_role,
    clock_timestamp()                                             AS captured_at,
    current_setting('wal_level')                                  AS wal_level,
    'Aurora PostgreSQL does not expose the upstream WAL/LSN inspection '
    'functions safely. Use CloudWatch WriteThroughput, VolumeWriteIOPs and '
    'VolumeBytesUsed for write volume, Performance Insights for Log waits, '
    'and AuroraReplicaLag for reader apply delay.'                 AS guidance;
\\else
SELECT pg_is_in_recovery() AS in_recovery
\\gset

\\if :in_recovery
SELECT
    'reader (in recovery)'::text                                  AS instance_role,
    pg_last_wal_receive_lsn()                                     AS last_wal_receive_lsn,
    pg_last_wal_replay_lsn()                                      AS last_wal_replay_lsn,
    pg_last_xact_replay_timestamp()                               AS last_replayed_xact_time,
    now() - pg_last_xact_replay_timestamp()                       AS replay_delay;
\\else
SELECT
    'writer (not in recovery)'::text                              AS instance_role,
    pg_current_wal_lsn()                                          AS current_wal_lsn,
    pg_current_wal_insert_lsn()                                   AS current_wal_insert_lsn,
    pg_walfile_name(pg_current_wal_lsn())                         AS current_wal_segment,
    pg_size_pretty(
        pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0'::pg_lsn)
    )                                                             AS wal_position_as_bytes,
    'Take a second sample of this script a known interval later (5 or 10 '
    'minutes is usually enough) and difference wal_position_as_bytes to get '
    'a genuine WAL bytes-per-second rate. A single sample is only a position, '
    'not a rate.'                                                 AS how_to_get_a_rate;
\\endif
\\endif
""".strip("\n"),
        "Read the settings first: a small max_wal_size relative to your write rate is what produces the forced checkpoints seen in script 02. On Aurora, the script intentionally returns no WAL/LSN value; use CloudWatch WriteThroughput, VolumeWriteIOPs and VolumeBytesUsed as the authoritative rate and volume sources. On community PostgreSQL, run the LSN branch twice several minutes apart and subtract the positions to derive a rate.",
        related_scripts="04_wal_heavy_statements.sql",
        execution_location=ANY_INSTANCE,
        table_purpose="WAL configuration plus current WAL position.",
    ),
    sql_script(
        "04", "04_wal_heavy_statements",
        "Attributes WAL generation to individual statements using pg_stat_statements, with the Aurora reporting caveat applied.",
        _pgss_guarded(sb.pgss_wal_heavy()),
        "Rank by total WAL first to find the statements that dominate cluster-wide volume, then look at avg_wal_per_call to find individually expensive statements that may simply not run often yet. Critically: a reported wal_bytes of 0 for a statement you know performs writes means this engine version did not record it, NOT that the statement is WAL-cheap -- the script flags this explicitly in wal_reporting_caveat. Corroborate every conclusion here against the per-table write counters in script 05 before acting, and prefer the table-level evidence when the two disagree.",
        related_scripts="05_write_volume_by_table.sql",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=_PGSS_PREREQ,
        execution_location=WRITER_PREFERRED,
        table_purpose="Top WAL-generating statements.",
    ),
    sql_script(
        "05", "05_write_volume_by_table",
        "Attributes write volume to individual tables, which is the reliable WAL proxy on Aurora where the WAL statistics view is unavailable.",
        sb.write_volume_by_table(),
        "This is the most dependable attribution available on Aurora. Rank by total_row_writes to find the tables driving redo volume, then read pct_hot_updates on the update-heavy ones: a low HOT ratio means every update is rewriting the row plus an entry in every index, which is pure, addressable WAL amplification. Cross-reference the offending table against its index count -- dropping one unnecessary index on a table taking millions of updates removes a WAL entry from every one of them. Always check stats_reset first; an Aurora failover zeroes these counters and makes a busy table look idle.",
        related_scripts="../table-growth/README.md",
        execution_location=WRITER_PREFERRED,
        table_purpose="Per-table write volume and HOT update ratio.",
    ),
    sql_script(
        "06", "06_replication_slot_wal_retention",
        "Identifies replication slots retaining WAL, which converts a transient write burst into persistent storage consumption.",
        sb.replication_slots_and_wal_retention(),
        "Any slot with active = false and a large retained_wal is an abandoned consumer pinning storage indefinitely, and it will keep growing until the slot is dropped or the consumer returns. Slots with wal_status of 'extended' or 'lost' need immediate attention: 'lost' means required WAL has already been removed and the consumer can no longer resume without a full resynchronization. On Aurora, note that the cluster's own reader instances never appear here -- only genuine streaming consumers such as logical replication subscribers or AWS DMS tasks do. This script reads the current WAL position and therefore must run against the writer.",
        related_scripts="../../replication-and-ha/replication-health/README.md",
        execution_location=WRITER_ONLY,
        table_purpose="Replication slots retaining WAL.",
    ),
]


# ---------------------------------------------------------------------------
# 5. temp-file-growth
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="temp-file-growth",
    title="Temporary File Growth Investigation",
    summary=(
        "Queries are spilling sorts, hashes, and materializations to disk "
        "instead of completing in memory. Temporary files are a distinct "
        "storage problem from table growth: they consume per-instance local "
        "storage rather than the shared Aurora cluster volume, they appear "
        "and vanish within the lifetime of a single query, and they are "
        "nearly always a symptom of an undersized `work_mem` or a planner "
        "row-count misestimate rather than of genuine data volume. On an "
        "exchange platform the usual sources are reporting and reconciliation "
        "queries sorting large trade or ledger result sets, and hash joins "
        "whose build side the planner underestimated because statistics were "
        "stale."
    ),
    symptoms=[
        "CloudWatch `FreeLocalStorage` on an instance falls sharply during certain queries or batch windows, sometimes approaching zero.",
        "Queries fail outright with 'could not write to file' or 'temporary file size exceeds temp_file_limit'.",
        "`temp_bytes` in `pg_stat_database` climbs steadily throughout the trading day.",
        "Reporting or reconciliation queries have unpredictable runtimes -- fast most days, dramatically slower on high-volume days.",
        "Sessions are visibly waiting on `BufFileRead` or `BufFileWrite` wait events during peak periods.",
        "The PostgreSQL log is full of 'temporary file' lines when `log_temp_files` is enabled.",
    ],
    business_impact=[
        "Exhausting local storage on an instance causes query failures and, in the worst case, instance instability -- an availability event, not merely a slow query.",
        "Spilling converts an in-memory operation into a disk-based one, typically an order-of-magnitude slowdown, which pushes reconciliation and regulatory reporting past their windows.",
        "Temp file I/O competes with regular query I/O on the same instance, so one spilling report query degrades latency for unrelated trading traffic.",
        "Unpredictable query runtimes make capacity planning and SLA commitments for batch processes unreliable.",
    ],
    root_causes=[
        "Memory sizing: `work_mem` set too low for the actual query shapes in production, so every large sort or hash spills.",
        "Memory sizing: `work_mem` is per sort/hash node, not per query -- a query with several such nodes running at high concurrency can use many multiples of the configured value, so administrators often set it conservatively and cause spills.",
        "Statistics: stale or insufficient statistics causing the planner to underestimate the build side of a hash join, so it allocates too little and spills mid-execution.",
        "Query shape: `ORDER BY` or `DISTINCT` over a large unindexed result set, where an appropriate index would allow an ordered index scan with no sort at all.",
        "Query shape: large `GROUP BY` aggregations over unfiltered history, typical of reconciliation and reporting queries run against the OLTP database.",
        "Query shape: a missing or non-selective predicate causing a join to process far more rows than the business question requires.",
        "Workload placement: analytics and reporting workloads running on the OLTP cluster instead of a dedicated reporting path.",
        "Volume: a genuine spike in matched trade volume producing legitimately larger intermediate result sets during a market event.",
    ],
    investigation_strategy=[
        "Read cumulative temp file counters per database to establish scale and confirm which database is responsible.",
        "Capture the memory-related configuration, since `work_mem` and `hash_mem_multiplier` determine the spill threshold for every node.",
        "Attribute temp file volume to specific statements via `pg_stat_statements`, which is where the actionable finding usually is.",
        "Look at what is spilling right now, so a live incident can be tied to a specific session and query.",
        "List actual temporary files currently on disk to size the immediate local-storage exposure.",
        "Check statistics freshness, because a planner misestimate is a far cheaper fix than a memory increase and is frequently the real cause.",
    ],
    prerequisites=[
        "`pg_monitor` role membership -- also required to execute `pg_ls_tmpdir()` for the on-disk listing script.",
        "`pg_stat_statements` installed for statement-level attribution.",
        "CloudWatch access for `FreeLocalStorage`, which is the authoritative measure of how much local scratch space remains on each instance.",
        "An understanding that temp files live on per-instance local storage, not the shared Aurora cluster volume -- the two have completely different limits and remediation.",
    ],
    interpretation_guide=[
        "Interpret `temp_bytes` as a rate, not a total: divide by the time since `stats_reset` to get bytes per hour, and compare that against the instance's `FreeLocalStorage` headroom to understand how much margin you actually have.",
        "A small number of statements almost always accounts for the large majority of temp bytes. Fix those and the problem usually disappears; there is rarely a need for a cluster-wide memory change.",
        "`work_mem` is allocated per sort or hash node per backend, not per query. A query plan with four such nodes running across fifty concurrent backends can consume two hundred times `work_mem` in the worst case -- this is precisely why raising it globally is dangerous and why a targeted session-level or role-level increase for the reporting workload is the safer fix.",
        "If `pct_modified_since_analyze` is high on the tables involved in a spilling query, fix statistics first. A planner that underestimates the build side of a hash join will spill no matter how much memory you give it, because it sized the hash table from a wrong estimate.",
        "A large sort on a column that could be served by an ordered index scan is a query and indexing problem, not a memory problem. Adding the right index eliminates the sort node entirely rather than making it cheaper.",
        "Sessions waiting on `BufFileRead` or `BufFileWrite` are actively reading or writing temp files right now -- that is a live spill, and the query text on that row is your culprit.",
        "Temp files that persist on disk for a long time usually belong to a still-running query. Files left behind by a crashed backend are cleaned up on the next instance restart, so a growing count of old files with no matching active session is worth noting.",
    ],
    remediation_immediate=[
        "If local storage is close to exhausted, stop the offending report or batch job at the application layer -- this is the fastest safe lever.",
        "Raise `work_mem` for the single offending session or role (`SET work_mem`, or `ALTER ROLE reporting SET work_mem`), never globally as a reflex during an incident.",
        "If a specific runaway query is spilling unboundedly, have the owning team cancel it through their application rather than reaching for backend termination as a first response.",
    ],
    remediation_short_term=[
        "Run `ANALYZE` on the tables involved in the spilling queries so the planner sizes its hash tables and sorts from accurate row counts.",
        "Set a higher `work_mem` on the reporting role specifically, isolating the increase to the workload that needs it and leaving the trading path untouched.",
        "Add the index that lets the worst sorting query use an ordered index scan instead of an explicit sort.",
        "Add or tighten predicates on reporting queries so they process the business-relevant window rather than full history.",
        "Set `temp_file_limit` as a guardrail so a single runaway query fails fast instead of filling local storage and destabilizing the instance.",
    ],
    remediation_long_term=[
        "Move reporting, reconciliation, and analytics workloads off the OLTP cluster to a dedicated reader, a separate reporting database, or an analytics store.",
        "Introduce pre-aggregated summary tables for the recurring reconciliation and regulatory reports instead of recomputing them from raw trade and ledger history every run.",
        "Right-size instance classes for the reporting path: local storage scales with instance size on Aurora, so a larger reader is a legitimate answer for a genuinely memory-hungry workload.",
        "Set an appropriate per-table statistics target on the columns that drive join and filter estimates for the big reporting queries.",
        "Add temp file rate to routine monitoring so a growing spill trend is a scheduled conversation rather than an incident.",
    ],
    production_safety=[
        "All scripts here are read-only.",
        "The on-disk temp file listing uses `pg_ls_tmpdir()`, which requires `pg_monitor` membership; the script checks role membership first and prints guidance rather than failing for an under-privileged role.",
        "Temp file listings are per-instance. Run them on the instance that is actually reporting low `FreeLocalStorage`, not on whichever instance you happen to be connected to.",
        "Do not raise `work_mem` cluster-wide during an incident. The parameter is allocated per node per backend, so a global increase under high concurrency can turn a disk-spill problem into an out-of-memory problem.",
    ],
    escalation_criteria=[
        "`FreeLocalStorage` on any instance is approaching zero -- this is an availability risk and should be treated as an incident, with the offending workload stopped immediately.",
        "Queries are failing with temp file write errors on the writer, meaning the trading path is affected rather than only reporting.",
        "Temp file volume has grown sharply with no query change, no volume change, and no statistics drift -- involve application engineering to identify a changed access pattern.",
        "The correct fix requires a larger instance class or a new reporting architecture -- that is a cost and design decision for engineering leadership.",
    ],
    related_issues=[
        "../unexpected-storage-growth/README.md",
        "../capacity-forecasting/README.md",
        "../../query-optimization/sort-spills/README.md",
        "../../query-optimization/temp-file-investigation/README.md",
        "../../query-optimization/stale-statistics/README.md",
        "../../performance/high-iops/README.md",
    ],
    aurora_notes=[
        "Temporary files consume per-instance local NVMe storage (`FreeLocalStorage` in CloudWatch), which is completely separate from the shared Aurora cluster volume (`VolumeBytesUsed`). You can exhaust local storage and fail queries while the cluster volume has terabytes of room -- and the reverse is equally possible.",
        "Local storage capacity scales with the instance class. Moving the reporting workload to a larger reader instance is a legitimate and sometimes the cheapest remediation, and it isolates the spill from the writer entirely.",
        "Aurora readers each have their own local storage and their own temp file usage. A reporting query spilling on a reader has no effect on the writer's local storage, which is a strong argument for pinning reporting traffic to a dedicated reader.",
        "`work_mem` is set through the Aurora DB cluster or instance parameter group. Per-role overrides via `ALTER ROLE ... SET work_mem` work normally and are the preferred way to give the reporting workload more memory without affecting the trading path.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_temp_file_usage_by_database",
        "Reports cumulative temporary file count and volume per database to establish scale and locate the responsible database.",
        sb.temp_file_usage_by_database(),
        "Convert this into a rate before judging it: divide temp_bytes by the elapsed time since stats_reset to get bytes per hour, then compare that against the instance's FreeLocalStorage headroom in CloudWatch. A few hundred megabytes a day on a busy analytical database is routine; tens of gigabytes an hour on the OLTP database that also serves order placement is not. Remember these counters are per instance and reset on failover, so a low number immediately after an Aurora failover means nothing.",
        related_scripts="02_memory_and_temp_settings.sql",
        table_purpose="Cumulative temp file usage per database.",
    ),
    sql_script(
        "02", "02_memory_and_temp_settings",
        "Captures the memory and temp file settings that determine when a sort or hash spills to disk.",
        """
-- The settings that decide whether an operation completes in memory or
-- spills to local disk. On Aurora these come from the DB cluster/instance
-- parameter group rather than postgresql.conf; the `source` column tells
-- you whether the live value came from the parameter group (reported as a
-- configuration file), a session-level SET, a per-role default, or the
-- built-in default.
--
-- The single most important thing to understand here: work_mem is allocated
-- per sort/hash/materialize node, per backend -- NOT per query and not per
-- connection. A plan with four such nodes running across fifty concurrent
-- backends can, worst case, use two hundred times the configured value.
-- That is why raising work_mem globally is risky and why a targeted
-- per-role increase (ALTER ROLE reporting SET work_mem = ...) is almost
-- always the safer remediation.
SELECT
    name,
    setting,
    unit,
    context,
    source,
    short_desc
FROM pg_settings
WHERE name IN (
    'work_mem', 'hash_mem_multiplier', 'maintenance_work_mem',
    'temp_file_limit', 'log_temp_files', 'temp_buffers',
    'max_connections', 'shared_buffers', 'effective_cache_size',
    'enable_sort', 'enable_hashagg', 'random_page_cost'
)
ORDER BY name;

-- Any non-default per-role or per-database overrides already in place.
-- A reporting role with its own elevated work_mem is the recommended
-- pattern; discovering that a *login* role used by the trading application
-- has an inflated override is a finding in its own right.
--
-- Access to pg_db_role_setting is not guaranteed for every role on every
-- deployment, so check SELECT privilege first rather than risking a
-- permission error part-way through the script.
SELECT has_table_privilege(
    current_user, 'pg_catalog.pg_db_role_setting', 'SELECT'
)                                                                 AS can_read_role_settings
\\gset

\\if :can_read_role_settings
SELECT
    COALESCE(r.rolname, 'ALL ROLES')                              AS role_name,
    COALESCE(d.datname, 'ALL DATABASES')                          AS database_name,
    s.setconfig                                                   AS settings_override
FROM pg_db_role_setting s
LEFT JOIN pg_roles r ON r.oid = s.setrole
LEFT JOIN pg_database d ON d.oid = s.setdatabase
ORDER BY role_name, database_name;
\\else
SELECT
    'The current role cannot read pg_catalog.pg_db_role_setting, so existing '
    'per-role/per-database work_mem overrides cannot be listed here. Ask an '
    'administrator to run this part, or inspect a specific role with '
    'the psql meta-command \\drds instead.'                        AS notice;
\\endif
""".strip("\n"),
        "Read work_mem together with max_connections: the theoretical worst case is roughly work_mem multiplied by the number of concurrent sort/hash nodes across all backends, which is why a value that looks generous per query can be dangerous in aggregate. If log_temp_files is -1 (disabled), enable it with a threshold so future spills are recorded with their query text -- that single change makes every later investigation far easier. The second result set shows existing per-role overrides; a dedicated reporting role with elevated work_mem is the pattern you want, and an inflated override on the trading application's login role is a finding to correct.",
        related_scripts="03_temp_heavy_statements.sql",
        table_purpose="Memory and temp file settings, plus per-role overrides.",
    ),
    sql_script(
        "03", "03_temp_heavy_statements",
        "Attributes temporary file volume to individual statements, which is where the actionable finding almost always is.",
        _pgss_guarded(sb.pgss_temp_and_io_heavy()),
        "Expect extreme concentration: a handful of statements typically account for the vast majority of temp bytes, and fixing those removes the problem without any cluster-wide memory change. For each offender decide which of three fixes applies: a sort that an index could serve as an ordered scan (add the index, the sort node disappears entirely), a hash join whose build side was underestimated (fix statistics -- more memory will not help a wrongly sized hash table), or a genuinely large aggregation over full history (add a predicate, pre-aggregate, or move the workload off the OLTP cluster). Divide temp_blks_written by calls to distinguish one catastrophic run from a steadily expensive statement.",
        related_scripts="04_sessions_spilling_now.sql",
        required_privileges=PG_MONITOR_PLUS_PGSS,
        prerequisites=_PGSS_PREREQ,
        table_purpose="Top temp-file-generating statements.",
    ),
    sql_script(
        "04", "04_sessions_spilling_now",
        "Shows currently active sessions and flags those waiting on temporary file I/O right now.",
        """
-- Live view of active backends with an explicit flag for the ones that are
-- reading or writing temporary files at this instant. BufFileRead,
-- BufFileWrite and BufFileTruncate are the IO wait events PostgreSQL
-- reports while a sort, hash, or materialize node is spilling to local
-- storage -- if a session is parked on one of these, its query text is your
-- immediate culprit.
--
-- Absence of rows flagged here does NOT prove nothing is spilling: this is
-- an instantaneous sample, and a query can write a large temp file between
-- two samples. Use script 01 and script 03 for cumulative evidence and this
-- script for live incident attribution.
SELECT
    pid,
    datname,
    usename,
    application_name,
    client_addr,
    wait_event_type,
    wait_event,
    (wait_event_type = 'IO' AND wait_event LIKE 'BufFile%')       AS spilling_to_temp_now,
    now() - query_start                                          AS query_runtime,
    now() - xact_start                                           AS transaction_runtime,
    left(query, 250)                                             AS query_snippet
FROM pg_stat_activity
WHERE state = 'active'
  AND pid <> pg_backend_pid()
  AND backend_type = 'client backend'
ORDER BY spilling_to_temp_now DESC, query_runtime DESC NULLS LAST;
""".strip("\n"),
        "Any row with spilling_to_temp_now = true is actively writing or reading a temp file, and its query_snippet plus application_name tells you exactly which workload and which team to contact. During a local-storage incident this is the script that names the offender. Long query_runtime combined with a BufFile wait event is the worst case -- a query that has been spilling for minutes may have already written many gigabytes. Cross-check the statement against script 03 to see whether this is a recurring pattern or a one-off, because that determines whether the fix is a code change or a parameter change.",
        related_scripts="05_temp_files_on_disk.sql",
        table_purpose="Active sessions, flagging live temp file spills.",
    ),
    sql_script(
        "05", "05_temp_files_on_disk",
        "Lists the temporary files physically present on this instance right now to size the immediate local-storage exposure.",
        """
-- Temporary files currently on disk for THIS instance. Temp files live on
-- per-instance local storage (CloudWatch FreeLocalStorage), which is
-- entirely separate from the shared Aurora cluster volume -- so always run
-- this on the instance that is actually reporting low local storage, not
-- on whichever instance you happen to be connected to.
--
-- pg_ls_tmpdir() execution is granted to pg_monitor by default. Check role
-- membership first rather than letting the call fail with a permission
-- error, so this script degrades to guidance instead of an error for an
-- under-privileged role.
\\set top_n 50
SELECT pg_has_role(current_user, 'pg_monitor', 'MEMBER')          AS can_list_tmpdir
\\gset

\\if :can_list_tmpdir
SELECT
    name                                                         AS temp_file_name,
    pg_size_pretty(size)                                          AS file_size,
    size                                                          AS size_bytes,
    modification                                                  AS last_modified,
    now() - modification                                          AS age
FROM pg_ls_tmpdir()
ORDER BY size DESC
LIMIT :top_n;
\\else
SELECT
    'The current role is not a member of pg_monitor, so pg_ls_tmpdir() '
    'cannot be executed and on-disk temp files cannot be listed. Ask an '
    'administrator to GRANT pg_monitor TO your role, or use the CloudWatch '
    'FreeLocalStorage metric for this instance instead -- it measures the '
    'same exposure from outside the database and needs no database '
    'privileges at all.'                                          AS notice;
\\endif
""".strip("\n"),
        "Zero rows is the healthy steady state and simply means nothing is spilling at this instant. A small number of very large files usually belongs to one still-running query -- match it against script 04 by timing. Many files with an age of hours and no matching active session suggests files left behind by backends that died; PostgreSQL cleans these up on the next instance restart, so note them but do not attempt manual cleanup. Sum size_bytes and compare against CloudWatch FreeLocalStorage for this specific instance to judge how close to the edge you are.",
        related_scripts="06_statistics_freshness.sql",
        execution_location=ANY_INSTANCE,
        table_purpose="Temporary files currently on local disk.",
    ),
    sql_script(
        "06", "06_statistics_freshness",
        "Checks planner statistics freshness, since a row-count misestimate causes spills that no amount of extra memory will prevent.",
        sb.statistics_freshness(),
        "This is the cheapest possible fix and is frequently the real cause, so do not skip it. When the planner underestimates the build side of a hash join it sizes the hash table from that wrong estimate and spills mid-execution regardless of how much work_mem is available -- raising memory simply moves the cliff. A high pct_modified_since_analyze on any table involved in the spilling statements from script 03 means you should run ANALYZE on those tables and re-measure before considering any memory change. Stale statistics on a fast-growing trade or ledger table are extremely common, because the default autoanalyze scale factor triggers proportionally less often as the table grows.",
        related_scripts="../../query-optimization/stale-statistics/README.md",
        table_purpose="Planner statistics freshness per table.",
    ),
]


# ---------------------------------------------------------------------------
# 6. capacity-forecasting
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="capacity-forecasting",
    title="Storage Capacity Forecasting",
    summary=(
        "Turns observed growth into a defensible projection: how large will "
        "this database be in ninety or a hundred and eighty days, when does "
        "it cross the thresholds we care about, and how much runway do we "
        "have before remediation stops being optional. This workflow is "
        "deliberately a simple linear projection from measured history, "
        "because a naive model whose assumptions are written down and "
        "understood is far more useful operationally than a sophisticated "
        "one nobody can sanity-check at three in the morning. Every output "
        "here is a heuristic, not a guarantee: it assumes the last observed "
        "growth rate continues unchanged, which is exactly what a crypto "
        "exchange workload does not do around market events, listings, and "
        "volatility spikes."
    ),
    symptoms=[
        "A capacity review is due and nobody can answer 'when do we run out of runway' with a number.",
        "Aurora storage cost is rising and finance wants a forecast rather than a current figure.",
        "A partitioning or archival project needs a business case, and the case rests on projected rather than current size.",
        "CloudWatch `VolumeBytesUsed` is trending up and leadership wants to know how far away the Aurora 128 TiB volume ceiling is.",
        "A new product launch or venue listing is planned and someone must estimate its storage impact before it ships.",
    ],
    business_impact=[
        "Without a forecast, storage remediation is always reactive -- done under time pressure, on a business-critical table, with the worst available risk profile.",
        "Aurora storage never shrinks, so every month of unmanaged growth permanently raises the cost floor; forecasting is what converts that into a budgetable, decidable number.",
        "Backup, restore, clone, and failover durations all scale with volume size, so a storage forecast is implicitly a recovery-time forecast for the exchange.",
        "Credible projections are what buy engineering time for partitioning and archival work *before* it becomes an emergency.",
    ],
    root_causes=[
        "N/A -- this is a planning workflow rather than an incident investigation. The inputs it consumes come from database-growth, table-growth, index-growth, and wal-generation.",
    ],
    investigation_strategy=[
        "Capture the current size baseline at database and relation level, so the projection has a defensible starting point.",
        "Read measured growth from the size-history collector over the retention window; this is the only real rate available.",
        "Project each relation forward linearly from its observed rate and compute days-to-threshold for each.",
        "Where no size history exists yet, fall back to a write-rate proxy derived from insert counters and average row width, with its weaker assumptions stated explicitly.",
        "Sanity-check every projection against CloudWatch `VolumeBytesUsed`, which is the figure that actually drives cost and the volume ceiling.",
        "Record the assumptions, the horizon, and the review date in the forecast worksheet so the projection can be re-evaluated rather than quietly trusted forever.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`).",
        "The `dba_toolkit.table_size_history` collector deployed with at least two, and preferably thirty or more, days of samples. Without it, only the weaker write-rate proxy is available.",
        "CloudWatch history for `VolumeBytesUsed` covering the same window, to reconcile logical projections against actual billed storage.",
        "Agreed thresholds to forecast against (a per-table size limit, a cluster volume budget, a cost ceiling) -- a projection with no threshold produces a number nobody can act on.",
    ],
    interpretation_guide=[
        "Treat every output here as a heuristic with a stated assumption -- that the recently observed growth rate continues unchanged. That assumption is routinely wrong on an exchange, where a single listing or volatility event can double write volume for a week. Use projections to prioritize and to buy lead time, never as a commitment.",
        "A short observation window produces a wildly unreliable rate. Under seven days of history, treat the output as directional only; thirty days or more is where the numbers become worth quoting to anyone else.",
        "Look at `days_until_threshold_at_current_rate` as a triage signal, not a deadline. Under ninety days means remediation must be scheduled now, because partitioning and archival projects on a large production table take months. Over a year means note it and re-review next quarter.",
        "Reconcile the sum of projected logical sizes against CloudWatch `VolumeBytesUsed`. Because Aurora never releases space, actual volume growth is always greater than or equal to logical growth -- if logical growth is flat while the volume keeps climbing, the projection is missing something and the unexpected-storage-growth workflow should run first.",
        "The write-rate proxy is deliberately cruder than the history-based projection: it assumes average row width stays constant and that inserts dominate deletes. It is useful when you have no history, and it should be replaced by the history-based number as soon as the collector has enough samples.",
        "A negative or zero growth rate for a relation usually means a purge or archival ran during the window, not that the table is genuinely stable. Check with the owning team before recording a table as 'not growing'.",
        "Forecast indexes as part of their table, not separately -- index growth generally tracks heap growth, and forecasting them independently double-counts the same underlying insert volume.",
    ],
    remediation_immediate=[
        "None -- forecasting produces decisions, not actions. If a projection shows runway measured in weeks rather than months, escalate immediately rather than continuing to model it.",
    ],
    remediation_short_term=[
        "Deploy the size-history collector on every production cluster if it is not already running; there is no way to reconstruct history retroactively and every day of delay is permanently lost trend data.",
        "Publish the projection with its assumptions, horizon, and review date so it is challenged rather than quietly trusted.",
        "Schedule the remediation work implied by the shortest runway item -- index cleanup, retention policy, or archival -- while there is still time to do it carefully.",
    ],
    remediation_long_term=[
        "Make a storage forecast a standing input to quarterly capacity and budget reviews rather than an ad-hoc exercise triggered by a bill.",
        "Attach a growth budget to every high-volume table at design time, so a table exceeding its budget becomes a review trigger rather than a discovery.",
        "Automate the forecast into a dashboard with alerting on days-to-threshold, so the number is monitored instead of periodically recomputed by hand.",
        "Model the storage impact of planned product changes (new venues, new instruments, longer retention requirements) before they ship, using the per-row costs measured here.",
    ],
    production_safety=[
        "Every script here is read-only and lightweight.",
        "The projection scripts are guarded against the size-history table being absent and print instructions rather than failing.",
        "All byte thresholds are cast to `numeric` before being multiplied up to GB or TB scale; multiplying a bare psql integer variable by 1024^3 overflows int4 and raises 'integer out of range', which is why the casts are not optional.",
        "Do not present these projections without their caveats attached. A linear projection quoted as a fact in a leadership deck is how capacity planning loses credibility the first time a market event breaks the trend.",
    ],
    escalation_criteria=[
        "Any projection shows the cluster approaching the Aurora 128 TiB volume limit inside the forecast horizon -- involve AWS support and engineering leadership immediately.",
        "Projected runway on a business-critical relation is under ninety days, which is less than a realistic partitioning or archival project takes -- this needs prioritization at leadership level, not a DBA backlog ticket.",
        "Projected storage cost growth exceeds the budgeted envelope -- a finance and engineering decision, not a database one.",
        "Actual measured growth has diverged sharply from the previous forecast with no known cause -- re-run unexpected-storage-growth before issuing a revised number.",
    ],
    related_issues=[
        "../database-growth/README.md",
        "../table-growth/README.md",
        "../index-growth/README.md",
        "../unexpected-storage-growth/README.md",
        "../wal-generation/README.md",
        "../../database-health/capacity-health-check/README.md",
        "../../tables-and-indexes/rapidly-growing-tables/README.md",
    ],
    aurora_notes=[
        "Forecast against CloudWatch `VolumeBytesUsed`, not against the sum of `pg_database_size()`. Aurora volume only ever grows, so logical projections systematically understate billed storage -- the gap widens every time data is deleted.",
        "The Aurora cluster volume auto-extends in 10 GiB increments up to 128 TiB. There is no manual pre-allocation and no shrink operation; the only way to reclaim a high-water mark is to build a new cluster and cut over, which is a project in its own right.",
        "Aurora storage is shared across the writer and every reader, so adding readers does not change the storage forecast at all -- only write volume does.",
        "Aurora bills storage I/O separately from stored bytes, so a complete capacity forecast has two axes: projected volume (from this workflow) and projected I/O (from the wal-generation workflow).",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_database_size_baseline",
        "Records the current per-database size baseline that every projection in this workflow starts from.",
        sb.database_sizes(),
        "Record these figures with a timestamp in the forecast document, not just in your terminal. Also record the current CloudWatch VolumeBytesUsed alongside them and note the gap -- that gap is space Aurora has allocated and will never release, and tracking how it widens over time is itself a useful capacity signal that no SQL query can give you.",
        related_scripts="02_relation_size_baseline.sql",
        table_purpose="Per-database size baseline.",
    ),
    sql_script(
        "02", "02_relation_size_baseline",
        "Records the current per-relation size baseline so projections can be made for the relations that actually matter.",
        sb.largest_tables(),
        "Forecast the top ten relations individually and treat everything else as a single aggregate; storage growth is concentrated enough that per-relation modelling below the top ten adds precision nobody will use. Note index_size alongside heap_size for each -- index growth generally tracks heap growth, so forecast it as part of the table rather than separately, which would double-count the same underlying insert volume.",
        related_scripts="03_measured_growth_from_history.sql",
        table_purpose="Per-relation size baseline.",
    ),
    sql_script(
        "03", "03_measured_growth_from_history",
        "Reports measured growth per relation over the collector's retention window -- the only genuine rate input available.",
        sb.table_growth_rate_from_snapshot(),
        "This is the input the whole workflow depends on. If it reports that the tracking table does not exist, stop forecasting and deploy the collector first: script 05 offers a weaker proxy, but there is no substitute for measured history and none of it can be reconstructed after the fact. Where history does exist, check the window length before trusting the numbers -- under seven days of samples produces a rate dominated by noise, and thirty days or more is where projections become defensible.",
        related_scripts="04_linear_projection_and_runway.sql",
        table_purpose="Measured growth per relation over the history window.",
    ),
    sql_script(
        "04", "04_linear_projection_and_runway",
        "Projects each relation forward linearly from its measured growth rate and computes days-to-threshold runway.",
        """
-- Naive linear capacity projection from the size-history collector.
--
-- METHOD, STATED PLAINLY: take the earliest and latest size sample for each
-- relation inside the lookback window, divide the difference by the elapsed
-- days to get bytes/day, and extend that rate forward. That is the entire
-- model. It assumes the observed rate continues unchanged, which is exactly
-- what an exchange workload does not do around listings, market events, and
-- volatility spikes. Use the output to prioritize remediation and to buy
-- lead time -- never as a commitment or an SLA.
--
-- The tracking table is optional infrastructure created by the
-- growth-monitoring collector, not a built-in catalog, so to_regclass() is
-- used to detect its absence. A bare FROM or a ::regclass cast would fail
-- at analysis time with "relation does not exist" before the guard could
-- ever run.
--
-- Note the ::numeric cast on table_threshold_gb: the psql variable is
-- substituted as a bare int4 literal, and "2000 * 1024 * 1024 * 1024"
-- overflows int4 (max ~2.1 billion) and raises "integer out of range"
-- unless numeric arithmetic is forced first.
\\set tracking_table 'dba_toolkit.table_size_history'
\\set lookback_days 30
\\set projection_days 180
\\set table_threshold_gb 2000
SELECT to_regclass(:'tracking_table') IS NOT NULL                 AS tracking_table_exists
\\gset

\\if :tracking_table_exists
WITH sized AS (
    SELECT
        schema_name,
        table_name,
        captured_at,
        size_bytes,
        min(captured_at) OVER w                                   AS first_capture,
        max(captured_at) OVER w                                   AS last_capture
    FROM dba_toolkit.table_size_history
    WHERE captured_at > now() - make_interval(days => :lookback_days)
    WINDOW w AS (PARTITION BY schema_name, table_name)
),
endpoints AS (
    SELECT
        schema_name,
        table_name,
        max(first_capture)                                        AS first_capture,
        max(last_capture)                                         AS last_capture,
        max(size_bytes) FILTER (WHERE captured_at = first_capture) AS start_bytes,
        max(size_bytes) FILTER (WHERE captured_at = last_capture)  AS end_bytes
    FROM sized
    GROUP BY schema_name, table_name
),
rates AS (
    SELECT
        schema_name,
        table_name,
        start_bytes,
        end_bytes,
        (extract(epoch FROM (last_capture - first_capture)) / 86400.0)::numeric
                                                                  AS window_days,
        (end_bytes - start_bytes)::numeric
            / NULLIF((extract(epoch FROM (last_capture - first_capture))
                      / 86400.0)::numeric, 0)                     AS growth_bytes_per_day
    FROM endpoints
)
SELECT
    schema_name,
    table_name,
    round(window_days, 1)                                         AS observed_window_days,
    pg_size_pretty(start_bytes)                                   AS size_at_window_start,
    pg_size_pretty(end_bytes)                                     AS size_now,
    pg_size_pretty(round(growth_bytes_per_day))                   AS avg_growth_per_day,
    :projection_days                                              AS projection_horizon_days,
    pg_size_pretty(
        round(end_bytes + growth_bytes_per_day * :projection_days)
    )                                                             AS projected_size_at_horizon,
    :table_threshold_gb                                           AS threshold_gb,
    CASE
        WHEN growth_bytes_per_day IS NULL OR growth_bytes_per_day <= 0
            THEN NULL
        ELSE round(
            ((:table_threshold_gb::numeric * 1024 * 1024 * 1024) - end_bytes)
            / growth_bytes_per_day, 0)
    END                                                           AS days_until_threshold_at_current_rate,
    CASE
        WHEN window_days < 7 THEN 'LOW CONFIDENCE -- under 7 days of history'
        WHEN window_days < 30 THEN 'MODERATE CONFIDENCE -- under 30 days of history'
        ELSE 'REASONABLE CONFIDENCE -- 30+ days of history'
    END                                                           AS confidence_note
FROM rates
WHERE window_days > 0
ORDER BY growth_bytes_per_day DESC NULLS LAST;
\\else
SELECT
    'No size history is available, because ' || :'tracking_table' || ' does '
    'not exist in this database. A linear projection needs at least two '
    'point-in-time samples and history cannot be reconstructed after the '
    'fact, so deploy the growth-monitoring collector now and re-run this '
    'script once at least a week of samples has accumulated. In the '
    'meantime, use 05_write_rate_projection_proxy.sql in this same '
    'directory, which derives a cruder estimate from insert counters and '
    'average row width without needing any history at all.'       AS notice;
\\endif
""".strip("\n"),
        "Read days_until_threshold_at_current_rate as a triage signal rather than a deadline, and always read confidence_note next to it -- a ninety-day runway derived from four days of samples is noise dressed up as a number. Under ninety days means schedule remediation immediately, because partitioning or archival on a large production table realistically takes months from design to cutover. Over a year means record it and re-review next quarter. A NULL or negative growth rate usually means a purge or archival ran inside the window rather than that the table is stable, so confirm with the owning team before recording anything as 'not growing'. Adjust lookback_days, projection_days, and table_threshold_gb at the top to match your review cadence and your agreed thresholds.",
        related_scripts="05_write_rate_projection_proxy.sql",
        table_purpose="Linear size projection and days-to-threshold runway.",
    ),
    sql_script(
        "05", "05_write_rate_projection_proxy",
        "Provides a fallback growth estimate from insert counters and average row width for databases with no size history yet.",
        """
-- Fallback projection for a database where the size-history collector has
-- not been deployed yet.
--
-- METHOD AND ITS WEAKNESSES, STATED PLAINLY: derive average bytes per row
-- from current total relation size divided by the live row estimate, derive
-- an insert rate from n_tup_ins divided by the time since statistics were
-- last reset, and multiply the two out over the horizon. This is
-- deliberately cruder than the history-based projection in script 04 and
-- carries three extra assumptions:
--   1. average row width stays constant (wrong if payload columns are
--      growing, or if the table is bloated today and vacuumed tomorrow),
--   2. inserts dominate -- deletes and purges are ignored entirely, so an
--      actively purged table is over-forecast,
--   3. the workload since stats_reset is representative, which it is not
--      if the window included a market event, a backfill, or a failover.
-- Replace this with script 04 as soon as the collector has enough samples.
\\set top_n 30
\\set projection_days 180
SELECT
    s.schemaname                                                  AS schema_name,
    s.relname                                                     AS table_name,
    pg_size_pretty(pg_total_relation_size(s.relid))               AS current_total_size,
    s.n_live_tup,
    s.n_tup_ins,
    d.stats_reset,
    round(
        extract(epoch FROM (now() - d.stats_reset))::numeric / 86400.0, 2
    )                                                             AS stats_window_days,
    round(
        s.n_tup_ins::numeric
        / NULLIF(extract(epoch FROM (now() - d.stats_reset))::numeric
                 / 86400.0, 0), 0
    )                                                             AS avg_rows_inserted_per_day,
    round(
        pg_total_relation_size(s.relid)::numeric
        / NULLIF(s.n_live_tup, 0), 0
    )                                                             AS avg_bytes_per_row,
    :projection_days                                              AS projection_horizon_days,
    pg_size_pretty(round(
        (pg_total_relation_size(s.relid)::numeric / NULLIF(s.n_live_tup, 0))
        * (s.n_tup_ins::numeric
           / NULLIF(extract(epoch FROM (now() - d.stats_reset))::numeric
                    / 86400.0, 0))
        * :projection_days
    ))                                                            AS projected_growth_over_horizon,
    CASE
        WHEN s.n_tup_del > s.n_tup_ins / 2
            THEN 'OVER-FORECAST LIKELY -- this table is actively purged (high n_tup_del), which this model ignores'
        WHEN extract(epoch FROM (now() - d.stats_reset)) < 86400 * 7
            THEN 'LOW CONFIDENCE -- statistics window is under 7 days'
        ELSE 'USABLE AS A ROUGH ESTIMATE ONLY -- prefer 04_linear_projection_and_runway.sql once history exists'
    END                                                           AS confidence_note
FROM pg_stat_all_tables s
CROSS JOIN (
    SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()
) d
WHERE s.schemaname NOT IN ('pg_catalog', 'information_schema')
  AND s.n_tup_ins > 0
  AND d.stats_reset IS NOT NULL
  AND s.n_live_tup > 0
ORDER BY pg_total_relation_size(s.relid) DESC
LIMIT :top_n;
""".strip("\n"),
        "Use projected_growth_over_horizon only for relative prioritization between tables, never as an absolute number to quote. Read confidence_note on every row: a table with heavy deletes is systematically over-forecast here because the model ignores them entirely, and a statistics window shorter than a week is dominated by whatever happened to be running. avg_bytes_per_row is independently useful even when the projection is not -- it is the number you need to estimate the storage impact of a planned product change such as a new venue, a new instrument, or a longer retention requirement. If stats_reset is recent because of an Aurora failover, every rate here is understated and the script should be re-run after a representative period.",
        related_scripts="06_capacity_forecast_worksheet.md",
        table_purpose="Fallback growth projection from write rates.",
    ),
    md_script(
        "06", "06_capacity_forecast_worksheet",
        "A structured worksheet for recording the forecast, its assumptions, its thresholds, and its review date so the projection can be challenged rather than quietly trusted.",
        (
            "## Why this worksheet exists\n\n"
            "A projection without its assumptions written down next to it is worse than no "
            "projection at all, because it gets quoted as a fact and then breaks the first "
            "time a market event changes the growth rate. This worksheet is the artifact "
            "you attach to the capacity review; the scripts produce numbers, this produces "
            "a decision record.\n\n"
            "Nothing in this file is executed. It contains no DDL and no statements to run.\n\n"
            "## 1. Inputs -- record these with a timestamp\n\n"
            "| Input | Source | Value | Captured at |\n"
            "|---|---|---|---|\n"
            "| Cluster volume used | CloudWatch `VolumeBytesUsed` | | |\n"
            "| Sum of logical database sizes | script 01 | | |\n"
            "| Gap (volume minus logical) | derived | | |\n"
            "| Top relation by size | script 02 | | |\n"
            "| Observed growth window length | script 03 / 04 | | |\n"
            "| Cluster-wide growth rate | script 04 | | |\n\n"
            "The gap between cluster volume and logical size is space Aurora has allocated "
            "and will never release. Record it every review: a widening gap means deletes are "
            "freeing space logically without reducing cost, which changes what remediation is "
            "worth doing.\n\n"
            "## 2. Thresholds being forecast against\n\n"
            "A projection with no threshold produces a number nobody can act on. Agree these "
            "before running the forecast, not after seeing it:\n\n"
            "| Threshold | Value | Owner | Why this number |\n"
            "|---|---|---|---|\n"
            "| Per-relation size limit | | | |\n"
            "| Cluster volume budget | | | |\n"
            "| Monthly storage cost ceiling | | | |\n"
            "| Aurora hard volume limit | 128 TiB | AWS | Engine limit, not negotiable |\n\n"
            "## 3. Projection results\n\n"
            "| Relation | Size now | Growth/day | Projected at horizon | Days to threshold | Confidence |\n"
            "|---|---|---|---|---|---|\n"
            "| | | | | | |\n\n"
            "Copy the top ten rows from script 04 (or script 05 if no history exists yet). "
            "Carry the `confidence_note` column through verbatim -- it is the single most "
            "important column in the table and the first thing a reviewer should see.\n\n"
            "## 4. Assumptions -- state them explicitly\n\n"
            "Tick each one that this forecast depends on, and note anything known to break it:\n\n"
            "- The growth rate observed over the last window continues unchanged.\n"
            "- No new product, venue listing, instrument, or retention requirement ships "
            "inside the horizon. (List any that are planned -- these invalidate the model.)\n"
            "- No archival, purge, or partition-detach runs inside the horizon. (If one is "
            "scheduled, the forecast should be adjusted down by its expected reclaim.)\n"
            "- Average row width stays constant (relevant only for the script 05 proxy).\n"
            "- Trading volume follows its recent trend. On an exchange this is the weakest "
            "assumption in the list and the one most likely to be wrong.\n\n"
            "## 5. Decisions and triage\n\n"
            "Map the shortest runway in section 3 to an action:\n\n"
            "| Runway | Required action |\n"
            "|---|---|\n"
            "| Under 30 days | Escalate now. Too short for any safe structural remediation -- expect a tactical intervention and an AWS conversation. |\n"
            "| 30-90 days | Schedule remediation immediately. Index cleanup and retention policy are the only levers that fit this window. |\n"
            "| 90-365 days | Plan a partitioning or archival project this quarter; there is time to do it carefully. |\n"
            "| Over 365 days | Record and re-review next quarter. |\n\n"
            "## 6. Remediation candidates considered\n\n"
            "For each, record the expected reclaim, the effort, and the decision:\n\n"
            "- Drop unused and duplicate indexes (from the index-growth workflow).\n"
            "- Attach a retention policy to the largest append-only relation.\n"
            "- Partition the largest time-series relation so retention becomes a detach.\n"
            "- Move cold history or wide payload columns out of the OLTP cluster.\n"
            "- Accept the growth and budget for it (a legitimate decision when growth is "
            "genuine revenue-driven volume -- just make it explicitly rather than by default).\n\n"
            "## 7. Review\n\n"
            "| Field | Value |\n"
            "|---|---|\n"
            "| Forecast produced by | |\n"
            "| Date produced | |\n"
            "| Horizon used | |\n"
            "| Next review date | |\n"
            "| Reviewers | |\n\n"
            "Set the next review date no further out than half the shortest runway in "
            "section 3. A forecast that outlives its own review cadence is how capacity "
            "surprises happen.\n"
        ),
        "Fill this in at every capacity review and keep the completed copies -- comparing successive forecasts against what actually happened is the only way to learn how wrong the linear model is for your specific workload, and that correction factor is worth more than any refinement to the model itself. Sections 4 and 5 are the ones that matter: the assumptions are what a reviewer should attack, and the runway-to-action mapping is what turns a number into a decision.",
        safety=READ_ONLY,
        expected_impact="None -- this file is a documentation worksheet and contains no executable statements.",
        required_privileges=PG_MONITOR,
        prerequisites="Output from scripts 01-05 of this workflow, plus CloudWatch VolumeBytesUsed history for the same window.",
        execution_location=ANY_INSTANCE,
        expected_runtime="Not applicable -- documentation worksheet.",
        table_purpose="Forecast worksheet: inputs, assumptions, thresholds, decisions.",
    ),
]


# ---------------------------------------------------------------------------
# 7. unexpected-storage-growth
# ---------------------------------------------------------------------------

WORKFLOWS.append(_wf(
    slug="unexpected-storage-growth",
    title="Unexpected Storage Growth",
    summary=(
        "Storage has jumped in a way the normal growth trend does not "
        "explain: a step change rather than a slope, or the Aurora volume "
        "climbing while logical database size stays flat. This is an "
        "incident-shaped investigation rather than a capacity-planning one, "
        "and its defining characteristic is that the obvious answer -- more "
        "data was inserted -- is usually wrong. The far more common causes "
        "are space that cannot be reclaimed (dead tuples pinned by a "
        "held-back xmin horizon, an abandoned replication slot retaining "
        "WAL, an orphaned transaction) and space consumed by something other "
        "than table data (a runaway index build, an unfinished migration "
        "copy, a flood of temporary files). The distinguishing question this "
        "workflow answers is: is space being consumed, or merely failing to "
        "be released?"
    ),
    symptoms=[
        "CloudWatch `VolumeBytesUsed` steps up sharply within hours rather than trending, with no corresponding deployment or volume event.",
        "`pg_database_size()` is flat or falling while the Aurora volume keeps climbing.",
        "A purge or archival job completed successfully but freed no storage at all.",
        "Dead tuple counts on one or more large tables are high and refuse to fall despite autovacuum running.",
        "`FreeLocalStorage` on an instance is dropping independently of the cluster volume.",
        "An unfamiliar large relation has appeared near the top of the size rankings.",
        "Storage growth started at a precisely identifiable moment that correlates with a deployment, a failover, or a long-running batch job.",
    ],
    business_impact=[
        "Unexplained growth erodes capacity headroom without warning, removing the lead time that would otherwise allow a careful remediation.",
        "If the cause is a held-back xmin horizon, the same root cause is simultaneously preventing vacuum from freezing tuples -- which puts the cluster on the path to transaction ID wraparound, a far more serious availability event.",
        "An abandoned replication slot retaining WAL will keep growing indefinitely and can eventually threaten the cluster, so the problem strictly worsens with time.",
        "On Aurora the storage consumed by a transient event is never released, so even a fully resolved incident leaves a permanent cost increase behind.",
    ],
    root_causes=[
        "Not released: a long-running transaction or idle-in-transaction session holding back the xmin horizon, so vacuum cannot remove dead tuples anywhere in the database.",
        "Not released: an inactive or lagging replication slot (a logical subscriber, an abandoned AWS DMS task) pinning both WAL and the xmin horizon.",
        "Not released: an orphaned prepared transaction, which holds locks and the xmin horizon indefinitely and survives restarts.",
        "Not released: autovacuum repeatedly cancelled by conflicting locks on a busy table, so dead tuples accumulate faster than they are reclaimed.",
        "Consumed: a bulk operation -- an unbatched `UPDATE` or `DELETE` across a large table -- creating one dead tuple per row touched plus a burst of WAL.",
        "Consumed: an index build or table rewrite in progress, which requires space for the new object alongside the old one.",
        "Consumed: a migration leftover, such as a full backup copy of a large table created 'temporarily' and never dropped.",
        "Consumed: a flood of temporary files from a spilling query, which consumes per-instance local storage rather than the cluster volume.",
        "Consumed: a partition maintenance job creating new partitions without detaching old ones, or creating far more partitions than intended.",
        "Consumed: a runaway application defect -- a retry loop inserting duplicates, a logging table with no retention, a webhook handler recording every payload.",
    ],
    investigation_strategy=[
        "Establish first whether the growth is logical (visible in `pg_database_size()`) or purely at the Aurora volume level -- this single question splits the investigation in two.",
        "Snapshot relation sizes and compare against the last recorded baseline to find what changed, looking specifically for relations that are new rather than merely large.",
        "Check dead tuple accumulation, since 'space not released' is the most common cause and dead tuples are its fingerprint.",
        "Hunt for anything holding back the xmin horizon: long-running transactions, idle-in-transaction sessions, prepared transactions.",
        "Check replication slots for retained WAL and pinned xmin, which is the second most common cause and the one that worsens fastest.",
        "Check temp file usage, which explains local storage growth that never appears in the cluster volume at all.",
        "Check for in-progress index builds and for INVALID indexes left by builds that already failed.",
    ],
    prerequisites=[
        "`pg_monitor` role membership (or `pg_read_all_stats`).",
        "A previous size baseline to compare against -- from the size-history collector, a prior capacity review, or the database-growth workflow. Without a baseline, 'unexpected' cannot be distinguished from 'always been that way'.",
        "CloudWatch `VolumeBytesUsed` and `FreeLocalStorage` history covering the period in question, ideally at one-minute resolution so the step change can be timed precisely.",
        "A deployment and change timeline for the same period, so a correlation can be tested rather than guessed at.",
    ],
    interpretation_guide=[
        "Start with the split: if `pg_database_size()` grew in step with the volume, something was written and the investigation is about finding what. If logical size is flat while the volume climbed, space was consumed by something outside normal table data -- WAL retention, temp files, or an index build -- and the table-level scripts will find nothing.",
        "High dead tuples that persist across autovacuum cycles is the signature of 'space not released'. Do not tune autovacuum in response; find what is holding back the xmin horizon, because until that is cleared, no amount of vacuum effort can remove those tuples.",
        "A transaction open for hours -- especially one sitting `idle in transaction` -- pins the xmin horizon for the entire database, not just for the tables it touched. A single forgotten session in a developer's terminal or a connection-pool leak can block reclamation cluster-wide.",
        "A replication slot with `active = false` and large retained WAL is an abandoned consumer. It pins both WAL and, for a logical slot, the xmin horizon. This is the cause that most reliably gets worse the longer it is left, and the fix (dropping the slot) needs confirmation but not much deliberation.",
        "A prepared transaction that has been open for more than a few minutes is almost certainly orphaned -- a two-phase commit whose coordinator died. It holds locks and the xmin horizon indefinitely and survives instance restarts, so it will never resolve itself.",
        "An in-progress index build temporarily needs space for the new index alongside the existing data, and a build on a very large table can consume a surprising amount. This is expected and transient -- but on Aurora the volume high-water mark it creates is permanent.",
        "A new relation you do not recognize near the top of the size rankings, particularly one named like a copy (`orders_old`, `trades_backup`, `ledger_entries_new`), is a migration leftover until someone proves otherwise. Confirm ownership before proposing anything.",
        "If logical size is flat, dead tuples are normal, no slot is retaining WAL, and no build is running, yet the Aurora volume still climbed -- that is not explainable from inside the database and needs an AWS support case with the CloudWatch timeline attached.",
    ],
    remediation_immediate=[
        "End whatever is holding back the xmin horizon: have the owning team close long-running or idle-in-transaction sessions through their application. This is the highest-value immediate action and it unblocks reclamation across the whole database.",
        "Roll back or commit an orphaned prepared transaction once its coordinator is confirmed dead -- it will never resolve on its own and blocks reclamation indefinitely.",
        "Drop an inactive replication slot whose consumer is confirmed dead, after checking with the owning team. Dropping a live consumer's slot forces a full resynchronization, so confirm before acting.",
        "Stop a runaway bulk operation or spilling query at the application layer if it is actively consuming storage right now.",
    ],
    remediation_short_term=[
        "Once the xmin horizon is free, allow autovacuum to reclaim the dead tuples, or run a manual `VACUUM` (never `VACUUM FULL`) on the worst-affected tables during a quieter period.",
        "Drop confirmed migration leftovers and INVALID indexes after establishing ownership.",
        "Batch the operation that caused the burst -- a `DELETE` of millions of rows in one transaction creates millions of dead tuples at once and should have been chunked.",
        "Add monitoring for long-running transactions, idle-in-transaction sessions, and inactive replication slots so the same cause is detected in minutes rather than discovered as a storage step change.",
    ],
    remediation_long_term=[
        "Set `idle_in_transaction_session_timeout` on the cluster so a leaked connection cannot pin the xmin horizon indefinitely.",
        "Establish ownership and an expiry review for every replication slot, so abandoned consumers are found by process rather than by incident.",
        "Replace bulk `DELETE`-based purges with partition detach, which reclaims space as a metadata operation and creates no dead tuples at all.",
        "Add a cleanup step with an owner and a deadline to every migration runbook, so backup copies of large tables are removed rather than forgotten.",
        "Alert on the rate of change of `VolumeBytesUsed`, not just its level, so a step change pages someone the same day it happens.",
    ],
    production_safety=[
        "Every script in this workflow is read-only and safe to run during an active incident; they read catalogs and statistics views only.",
        "Do not reach for `VACUUM FULL` to recover space during an incident. It takes an `AccessExclusiveLock` for its entire duration, needs as much free space as the table it rewrites, and on Aurora returns nothing to the volume anyway.",
        "Never terminate a backend or drop a replication slot on the basis of these reports alone -- confirm ownership and impact first. Dropping an active consumer's slot is a far larger event than the storage it frees.",
        "The replication slot script reads the current WAL position and must therefore run against the writer.",
    ],
    escalation_criteria=[
        "The Aurora volume is growing while every in-database metric is flat and no slot, build, or temp file activity explains it -- open an AWS support case with the CloudWatch timeline attached.",
        "The same root cause holding back the xmin horizon is also driving transaction age upward -- this is a wraparound risk and takes priority over the storage symptom entirely.",
        "An abandoned replication slot is retaining enough WAL to threaten cluster storage and its owner cannot be identified or contacted -- escalate for an authoritative decision to drop it.",
        "Growth is traced to an application defect actively writing unbounded data -- escalate to application engineering as a production incident, since every minute of delay is permanent Aurora storage.",
        "Remediation would require terminating sessions on the trading path, or dropping a relation whose ownership is unclear -- both need explicit authorization above the on-call DBA.",
    ],
    related_issues=[
        "../database-growth/README.md",
        "../table-growth/README.md",
        "../wal-generation/README.md",
        "../temp-file-growth/README.md",
        "../../vacuum-and-autovacuum/dead-tuples/README.md",
        "../../concurrency-and-locking/long-running-transactions/README.md",
        "../../concurrency-and-locking/idle-in-transaction/README.md",
        "../../transactions-and-xid/prepared-transactions/README.md",
        "../../replication-and-ha/replication-health/README.md",
    ],
    aurora_notes=[
        "Aurora volume growth is permanent. Even a fully resolved transient event -- a one-off bulk update, a completed index build, a purge that generated millions of dead tuples -- leaves the high-water mark where it peaked. This is why speed of response matters more on Aurora than on a self-managed instance where space returns to the filesystem.",
        "Logical size flat while the volume climbs is the classic Aurora signature of WAL retention, temp file usage, or an in-progress build. It is not a PostgreSQL-visible phenomenon, which is exactly why the CloudWatch timeline is a mandatory input to this investigation.",
        "Aurora readers do not appear in `pg_stat_replication`, so a lagging reader is not a possible cause of retained WAL here. Only genuine streaming consumers -- logical replication subscribers, AWS DMS tasks -- can pin WAL through a slot.",
        "`FreeLocalStorage` dropping while `VolumeBytesUsed` is flat means the growth is temp files on one instance, not cluster data. Those are entirely different problems with entirely different fixes -- see the temp-file-growth workflow.",
        "Aurora's storage layer performs its own garbage collection asynchronously, so small timing discrepancies between a completed cleanup inside PostgreSQL and the CloudWatch metric are normal. A sustained divergence over hours is not.",
    ],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script(
        "01", "01_database_size_snapshot",
        "Takes a current per-database size snapshot to determine whether the growth is logical at all, or purely at the Aurora volume level.",
        sb.database_sizes(),
        "This is the fork in the investigation. Compare these figures against your last baseline and against CloudWatch VolumeBytesUsed over the same period. If logical size grew in step with the volume, data was written and scripts 02 through 04 will find it. If logical size is flat or falling while the volume climbed, nothing was written -- the space went to WAL retention, temp files, or an in-progress build, and you should jump to scripts 05 through 07. Getting this split right in the first two minutes saves an hour of looking in the wrong place.",
        related_scripts="02_largest_tables_snapshot.sql",
        table_purpose="Per-database size snapshot for baseline comparison.",
    ),
    sql_script(
        "02", "02_largest_tables_snapshot",
        "Snapshots relation sizes so they can be compared against the previous baseline to find what actually changed.",
        sb.largest_tables(),
        "You are looking for two specific things, not for the biggest table. First, a relation that is new since the last baseline -- particularly one named like a copy (orders_old, trades_backup, ledger_entries_new), which is a migration leftover until someone proves otherwise. Second, a relation whose size changed far more than the others; storage step changes are almost always concentrated in one place. A table that is merely large and unchanged is not the finding, however alarming its absolute size looks.",
        related_scripts="03_dead_tuple_accumulation.sql",
        table_purpose="Relation size snapshot for baseline comparison.",
    ),
    sql_script(
        "03", "03_dead_tuple_accumulation",
        "Quantifies dead tuples per table to test the most common hypothesis: that space is not being released rather than consumed.",
        sb.dead_tuples_ranked(),
        "High dead tuple counts that persist through autovacuum cycles are the fingerprint of 'space not released', which is the single most common cause of unexpected growth. Do not respond by tuning autovacuum -- if the xmin horizon is held back, vacuum is running and correctly declining to remove tuples that a still-open transaction could theoretically still see. Go straight to scripts 04 and 05 to find what is holding it. A sudden jump in dead tuples on one table instead points at a bulk DELETE or UPDATE that ran unbatched, in which case the table names the job for you.",
        related_scripts="04_xmin_horizon_holders.sql",
        table_purpose="Dead tuple accumulation per table.",
    ),
    sql_script(
        "04", "04_xmin_horizon_holders",
        "Finds long-running transactions, idle-in-transaction sessions, and prepared transactions that hold back the xmin horizon and block all reclamation.",
        sb.long_running_transactions() + "\n\n" + sb.prepared_transactions(),
        "Any transaction open for hours pins the xmin horizon for the entire database, not only for the tables it touched, so a single forgotten session blocks reclamation everywhere. Sessions in state 'idle in transaction' are the worst case: they are doing no work at all while blocking cleanup, and they are almost always a connection-pool leak or a forgotten terminal rather than deliberate. The second result set lists prepared transactions -- any of these older than a few minutes is an orphaned two-phase commit whose coordinator died; it holds locks and the xmin horizon indefinitely and survives instance restarts, so it will never resolve on its own. Confirm ownership before ending anything, and note that clearing the holder does not reclaim space by itself -- it only lets the next vacuum do so.",
        related_scripts="05_replication_slot_retention.sql",
        table_purpose="Transactions and prepared transactions pinning the xmin horizon.",
    ),
    sql_script(
        "05", "05_replication_slot_retention",
        "Checks replication slots for retained WAL and pinned xmin -- the cause that worsens fastest if left alone.",
        sb.replication_slots_and_wal_retention(),
        "A slot with active = false and large retained_wal is an abandoned consumer pinning storage indefinitely, and a logical slot additionally pins the xmin horizon, which explains dead tuples that will not clear no matter what you do to autovacuum. A wal_status of 'lost' means required WAL has already been removed and the consumer cannot resume without a full resynchronization -- at that point the slot is providing nothing and is pure cost. Confirm with the owning team before dropping any slot: on an exchange these usually feed a data warehouse, a compliance archive, or an AWS DMS pipeline, and forcing a resynchronization is a bigger event than the storage it frees. Aurora's own readers never appear here.",
        related_scripts="06_temp_file_and_local_storage.sql",
        execution_location=WRITER_ONLY,
        table_purpose="Replication slots retaining WAL and pinning xmin.",
    ),
    sql_script(
        "06", "06_temp_file_and_local_storage",
        "Checks temporary file usage, which explains local storage growth that never appears in the cluster volume.",
        sb.temp_file_usage_by_database(),
        "This script matters most when CloudWatch shows FreeLocalStorage dropping while VolumeBytesUsed stays flat -- that pattern means temp files on a single instance, not cluster data, and the entire cluster-volume investigation is a dead end. A sharp rise in temp_bytes points at a query spilling sorts or hashes, usually a reporting or reconciliation job running against full history. Follow up in the temp-file-growth workflow for live attribution. Remember these counters are per instance: run this on the instance that is actually reporting low local storage.",
        related_scripts="../temp-file-growth/README.md",
        table_purpose="Temp file usage per database.",
    ),
    sql_script(
        "07", "07_index_builds_and_invalid_indexes",
        "Finds in-progress index builds consuming space right now, and INVALID indexes left behind by builds that already failed.",
        sb.create_index_progress() + "\n\n" + sb.invalid_indexes(),
        "An in-progress build in the first result set explains a live, transient step up in storage: the new index is being written alongside the existing data, and on a very large exchange table that can be a substantial amount of space. That is expected and will complete -- but on Aurora the volume high-water mark it creates is permanent, so record it rather than dismissing it. The second result set is the aftermath case: INVALID indexes from builds that were cancelled, timed out, or died with their session. Those consume their full size while being completely unusable by the planner, and they are the one thing in this entire workflow you can drop with no query-plan risk whatsoever.",
        related_scripts="../../schema-changes/failed-index-build/README.md",
        table_purpose="Running index builds plus INVALID index leftovers.",
    ),
]
