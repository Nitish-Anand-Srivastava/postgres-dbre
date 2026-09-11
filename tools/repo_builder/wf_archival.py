"""Workflow definitions: archival-and-data-lifecycle/ category (6 issue directories).

archive-large-table is the flagship workflow for safely archiving/purging
data from a very large, high-throughput transactional table.
"""
from __future__ import annotations

from typing import List

from . import sql_blocks as sb
from .helpers import PG_MONITOR, md_script, sql_script
from .model import Workflow

CATEGORY_SLUG = "archival-and-data-lifecycle"
CATEGORY_TITLE = "Archiving and Data Lifecycle"


def _wf(**kwargs) -> Workflow:
    kwargs.setdefault("category_slug", CATEGORY_SLUG)
    kwargs.setdefault("category_title", CATEGORY_TITLE)
    return Workflow(**kwargs)


WORKFLOWS: List[Workflow] = []

WORKFLOWS.append(_wf(
    slug="investigate-archiving-candidate",
    title="Investigating an Archiving Candidate",
    summary="Determines whether a table is a good candidate for archiving/retention-based purging, and establishes the data required (growth rate, access pattern, regulatory retention requirements) to plan a safe archive-large-table migration.",
    symptoms=["A table's growth is a recurring topic in capacity planning.", "Old data in the table is rarely or never queried by the live application."],
    business_impact=["Archiving reduces storage cost, improves vacuum/backup efficiency, and reduces the working set for queries and cache -- but for a financial platform, retention must also satisfy regulatory/compliance requirements, which take priority over any performance motivation."],
    root_causes=["N/A -- feasibility assessment workflow."],
    investigation_strategy=["Check table growth trend and current size.", "Check the access-age profile: what fraction of queries touch recent vs. old data.", "Confirm regulatory/compliance retention requirements with legal/compliance stakeholders before setting any retention boundary."],
    prerequisites=["Legal/compliance sign-off on minimum retention period before any purge boundary is finalized -- this is a compliance decision, not a purely technical one, especially for ledger/transaction history."],
    interpretation_guide=["A table where the vast majority of queries filter on a recent time window (e.g. 'last 90 days') while the table itself spans years of history is a strong archiving candidate -- the old data is costing storage/vacuum/backup overhead without serving the live query pattern."],
    remediation_immediate=["N/A."],
    remediation_short_term=["If confirmed a good candidate with a compliance-approved retention boundary, proceed to archive-large-table."],
    remediation_long_term=["Establish a standing retention-policy document (see retention-policy) so future tables are designed with archiving in mind from the start."],
    production_safety=["All scripts are read-only."],
    escalation_criteria=["Retention requirements are unclear or contested -- escalate to legal/compliance before proceeding with any technical planning."],
    related_issues=["../archive-large-table/README.md", "../retention-policy/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_table_growth_and_age_profile", "Checks table size and estimates the age distribution of its data via a candidate timestamp column.",
               """
-- Row count by age bucket for a candidate archival table, to understand how
-- much of the table is 'old' vs. 'recent' by a chosen timestamp column.
-- Ships with an illustrative default (public.orders / created_at); edit the
-- \\set lines below to point at your real candidate table. The to_regclass
-- guard below means running this unmodified against a database that does
-- not have that default table prints an instructional notice instead of
-- failing with "relation does not exist".
\\set schema_name 'public'
\\set table_name 'orders'
\\set timestamp_column 'created_at'
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\\gset

\\if :target_table_exists
SELECT
    width_bucket(
        extract(epoch FROM now() - :"timestamp_column"),
        0, extract(epoch FROM interval '3 years'), 12
    )                                                            AS age_bucket_quarter,
    count(*)                                                    AS row_count
FROM :"schema_name".:"table_name"
GROUP BY 1
ORDER BY 1;
\\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name/timestamp_column '
    '\\set lines above to point at your real archival candidate table '
    'before relying on this report.'                              AS notice;
\\endif
""".strip("\n"),
               "A large fraction of rows in the oldest age buckets confirms the table has substantial historical data that is a candidate for archiving, subject to compliance-approved retention.",
               related_scripts="02_recent_vs_historical_query_pattern.sql"),
    sql_script("02", "02_recent_vs_historical_query_pattern", "Reviews top queries against the table to assess whether the live application query pattern is scoped to recent data only.",
               sb.pgss_top_by_calls(),
               "If every frequent query's filter clause is scoped to a recent window (e.g. 'WHERE created_at > now() - interval'), historical rows are not serving live traffic and are a strong archiving candidate.",
               related_scripts="../archive-large-table/README.md"),
]

WORKFLOWS.append(_wf(
    slug="archive-large-table",
    title="Archiving a Large Production Table",
    summary=(
        "A comprehensive Staff DBA runbook for safely archiving historical "
        "data out of a very large, high-throughput production table --"
        " covering boundary selection, batch export/migration, batch "
        "deletion without long locks or WAL spikes, partition-based "
        "detach/drop shortcuts where applicable, and validation before any "
        "destructive step."
    ),
    symptoms=["The table has been confirmed an archiving candidate with an approved retention boundary (see investigate-archiving-candidate)."],
    business_impact=["Successful archiving reduces storage cost and improves vacuum/backup/query performance; a poorly executed archive risks data loss of records that may still be required for compliance/audit purposes."],
    root_causes=["N/A -- planned data-lifecycle operation."],
    investigation_strategy=[
        "Confirm the exact retention boundary and compliance sign-off.",
        "Export/copy the to-be-archived rows to durable, queryable cold storage before any deletion.",
        "Validate the exported data completely and independently before deleting anything from the source table.",
        "Delete the archived rows from the source table in small batches, monitoring WAL generation and replica lag throughout.",
        "If the table is already partitioned by the archival boundary (e.g. by month), prefer DETACH PARTITION + separate archival of the detached partition over row-by-row DELETE.",
        "Run a targeted VACUUM on the source table after large-scale deletion to reclaim space for reuse.",
    ],
    prerequisites=[
        "Compliance-approved retention boundary from investigate-archiving-candidate.",
        "A durable archive destination (e.g. an S3-backed cold-storage export via `aws_s3`/COPY TO, or a separate lower-cost Aurora/RDS instance) already provisioned and access-tested.",
        "DDL/DML privileges on the source table for the export and delete steps.",
    ],
    interpretation_guide=[
        "Never delete before the export is independently validated (row counts, checksums, and ideally a spot-check restore/query against the archived copy) -- an archive is only as good as its untested restore path.",
    ],
    remediation_immediate=["N/A -- see the rollback/validation guidance in scripts 05-06 if an issue is found mid-process."],
    remediation_short_term=["N/A."],
    remediation_long_term=["Once a table has a proven archive process, automate it on a recurring schedule (see retention-policy and automation/) rather than repeating this runbook manually each time."],
    production_safety=[
        "The batch DELETE step is the highest-risk part of this workflow -- it is provided as a guarded `.md` template, never a ready-to-run script, and must run in small, committed batches with monitoring, never as a single unbounded DELETE.",
        "Never DELETE before the corresponding export has been independently validated.",
        "Prefer PARTITION DETACH + archive-then-drop over row-level DELETE wherever the table is already partitioned by a compatible boundary -- it is dramatically faster and lower-risk (see archive-partition).",
    ],
    escalation_criteria=[
        "Any validation step fails (exported row count does not match source) -- halt immediately and do not proceed to deletion; escalate to database engineering.",
        "The retention boundary is later found to conflict with an active legal hold or audit -- escalate to legal/compliance immediately and pause the archive process.",
    ],
    related_issues=["../investigate-archiving-candidate/README.md", "../archive-partition/README.md", "../archive-validation/README.md", "../purge-old-data/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_confirm_archive_boundary", "Confirms the exact row count and boundary that will be affected by the approved retention cutoff, before any data movement begins.",
               """
-- Confirms the exact scope of the archive operation: row count and date
-- range for rows older than the approved retention boundary. Ships with an
-- illustrative default (public.orders / created_at); edit the \\set lines
-- below for your real candidate table -- the guard below means running
-- this unmodified prints an instructional notice instead of failing.
\\set schema_name 'public'
\\set table_name 'orders'
\\set timestamp_column 'created_at'
\\set retention_cutoff '2023-01-01'
SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\\gset

\\if :target_table_exists
SELECT
    count(*)                                                    AS rows_to_archive,
    min(:"timestamp_column")                                      AS oldest_row_timestamp,
    max(:"timestamp_column")                                      AS newest_row_to_archive_timestamp
FROM :"schema_name".:"table_name"
WHERE :"timestamp_column" < :'retention_cutoff'::timestamptz;
\\else
SELECT
    'Table ' || :'schema_name' || '.' || :'table_name' || ' does not exist '
    'in this database. Edit the schema_name/table_name/timestamp_column/ '
    'retention_cutoff \\set lines above before relying on this report.'   AS notice;
\\endif
""".strip("\n"),
               "Record rows_to_archive as your ground-truth scope figure -- every later validation step (script 04) must reconcile against this exact number.",
               related_scripts="02_export_to_cold_storage.md"),
    md_script("02", "02_export_to_cold_storage", "Exports the to-be-archived rows to durable cold storage before any deletion, using batched, checkpointed exports.",
              (
                  "## Option A: Export to S3 via aws_s3 extension (Aurora-supported)\n\n"
                  "```sql\n"
                  "-- aws_s3 is an AWS-provided extension available on Aurora PostgreSQL for\n"
                  "-- direct export to S3 without an intermediate application hop.\n"
                  "CREATE EXTENSION IF NOT EXISTS aws_s3 CASCADE;\n\n"
                  "SELECT aws_s3.query_export_to_s3(\n"
                  "    'SELECT * FROM public.orders WHERE created_at < ''2023-01-01''::timestamptz',\n"
                  "    aws_commons.create_s3_uri('your-archive-bucket', 'orders/pre-2023.csv', 'us-east-1')\n"
                  ");\n"
                  "```\n"
                  "This runs as a read-only query against the source table (no lock beyond a "
                  "normal read snapshot) and streams results directly to S3.\n\n"
                  "## Option B: Export to a separate archive database/table\n\n"
                  "```sql\n"
                  "-- If the archive destination is another PostgreSQL/Aurora database, use\n"
                  "-- postgres_fdw or dblink to copy in batches:\n"
                  "INSERT INTO archive_db.orders_archive\n"
                  "SELECT * FROM public.orders\n"
                  "WHERE created_at < '2023-01-01'::timestamptz\n"
                  "  AND id > :last_exported_id\n"
                  "ORDER BY id\n"
                  "LIMIT 10000;\n"
                  "-- Repeat, advancing :last_exported_id, until fully exported. Batching avoids\n"
                  "-- one enormous read/write transaction and its associated WAL/replica-lag\n"
                  "-- impact on both the source and destination.\n"
                  "```\n\n"
                  "Whichever option is used, confirm the exported data is genuinely queryable at "
                  "the destination (not just 'the export command succeeded') before proceeding.\n"
              ),
              "This step only reads from the source table -- it does not modify or lock it beyond a normal read. Safe to run against production at any time; batch it to avoid a single very long-running read transaction on a huge historical range.",
              related_scripts="03_validate_export_row_counts.sql"),
    sql_script("03", "03_validate_export_row_counts", "Compares the exported row count against the confirmed source scope from script 01.",
               """
-- Run the equivalent count against the ARCHIVE destination (via postgres_fdw/
-- dblink, or by querying the destination database directly) and compare
-- against the source count captured in script 01's rows_to_archive value.
-- This assumes the archive destination is reachable as a local relation
-- (e.g. a postgres_fdw foreign table) named archive_schema.archive_table --
-- edit the \\set lines below to match your real archive destination.
\\set archive_schema 'archive_db'
\\set archive_table 'orders_archive'
\\set timestamp_column 'created_at'
\\set retention_cutoff '2023-01-01'
SELECT to_regclass(:'archive_schema' || '.' || :'archive_table') IS NOT NULL AS archive_table_exists
\\gset

\\if :archive_table_exists
SELECT count(*) AS exported_row_count
FROM :"archive_schema".:"archive_table"
WHERE :"timestamp_column" < :'retention_cutoff'::timestamptz;
\\else
SELECT
    'Archive destination ' || :'archive_schema' || '.' || :'archive_table' ||
    ' is not reachable as a local relation in this database. Edit the '
    'archive_schema/archive_table \\set lines above, or run the equivalent '
    'COUNT directly against your archive destination connection instead.' AS notice;
\\endif
""".strip("\n"),
               "exported_row_count MUST equal script 01's rows_to_archive exactly. Any difference means the export is incomplete -- investigate and re-export before proceeding to deletion under any circumstances.",
               related_scripts="04_spot_check_data_integrity.sql"),
    sql_script("04", "04_spot_check_data_integrity", "Spot-checks a sample of archived rows for full column-level integrity against the source, beyond just a row count match.",
               """
-- Compares a checksum of full row content for a random sample of archived
-- IDs against the corresponding source rows, to catch column-level
-- corruption/truncation that a row-count-only check would miss. Ships with
-- illustrative defaults; edit the \\set lines below for your real source
-- table and archive destination.
\\set source_schema 'public'
\\set source_table 'orders'
\\set archive_schema 'archive_db'
\\set archive_table 'orders_archive'
\\set timestamp_column 'created_at'
\\set retention_cutoff '2023-01-01'
\\set sample_size 500
SELECT
    to_regclass(:'source_schema' || '.' || :'source_table') IS NOT NULL
    AND to_regclass(:'archive_schema' || '.' || :'archive_table') IS NOT NULL AS both_relations_exist
\\gset

\\if :both_relations_exist
SELECT
    s.id,
    s.source_checksum,
    a.archive_checksum,
    s.source_checksum = a.archive_checksum AS matches
FROM (
    SELECT id, md5(t::text) AS source_checksum
    FROM :"source_schema".:"source_table" t
    WHERE :"timestamp_column" < :'retention_cutoff'::timestamptz
    ORDER BY random()
    LIMIT :sample_size
) s
JOIN (
    SELECT id, md5(t::text) AS archive_checksum
    FROM :"archive_schema".:"archive_table" t
) a ON a.id = s.id
WHERE s.source_checksum <> a.archive_checksum;
\\else
SELECT
    'One or both of ' || :'source_schema' || '.' || :'source_table' || ' and '
    || :'archive_schema' || '.' || :'archive_table' || ' do not exist in '
    'this database. Edit the \\set lines above to point at your real '
    'source table and archive destination before relying on this '
    'comparison.'                                                  AS notice;
\\endif
-- An empty result set (zero mismatched rows) is the expected, passing
-- outcome once both relations exist. NOTE: md5(t::text) is sensitive to
-- column order/type formatting differences between source and archive
-- schemas -- ensure both have an identical column definition before
-- relying on this comparison.
""".strip("\n"),
               "This query is written to return ONLY mismatches -- an empty result is success. Any returned row is a data-integrity failure in the archive and must be resolved before deletion.",
               related_scripts="05_batched_deletion.md"),
    md_script("05", "05_batched_deletion", "Deletes the validated, archived rows from the source table in small, monitored batches -- the highest-risk step in this workflow.",
              (
                  "## Prerequisites for this step\n\n"
                  "- Scripts 01-04 completed with full validation success.\n"
                  "- A recent, verified backup/snapshot exists independent of this archive (Aurora "
                  "automated backups/snapshots satisfy this, but confirm the retention window "
                  "covers your rollback needs).\n\n"
                  "## Batched delete template\n\n"
                  "```sql\n"
                  "-- Never run a single unbounded DELETE against a large historical range: it\n"
                  "-- holds row locks for the whole statement, generates a single enormous WAL\n"
                  "-- burst, and can bloat the table (freed space is not reclaimed by DELETE\n"
                  "-- itself -- a subsequent VACUUM in script 06 is required for that).\n"
                  "\\set batch_size 5000\n"
                  "DO $$\n"
                  "DECLARE\n"
                  "    deleted_count integer;\n"
                  "BEGIN\n"
                  "    LOOP\n"
                  "        DELETE FROM public.orders\n"
                  "        WHERE id IN (\n"
                  "            SELECT id FROM public.orders\n"
                  "            WHERE created_at < '2023-01-01'::timestamptz\n"
                  "            ORDER BY id\n"
                  "            LIMIT 5000\n"
                  "        );\n"
                  "        GET DIAGNOSTICS deleted_count = ROW_COUNT;\n"
                  "        EXIT WHEN deleted_count = 0;\n"
                  "        COMMIT;\n"
                  "        PERFORM pg_sleep(0.25); -- brief pause between batches to smooth I/O/WAL\n"
                  "    END LOOP;\n"
                  "END $$;\n"
                  "```\n"
                  "Note: a plain `DO` block cannot COMMIT inside itself in vanilla PL/pgSQL prior to "
                  "procedures; use a PL/pgSQL **procedure** called via `CALL`, or drive the loop "
                  "from an external script/psql `\\watch`-based loop, so each batch genuinely "
                  "commits independently. Monitor storage-and-capacity/wal-generation and "
                  "replication-and-ha/reader-lag-investigation while this runs, and slow down "
                  "(increase pg_sleep, or reduce batch_size) if either climbs beyond tolerance.\n"
              ),
              "This is the irreversible step in the workflow (barring a full restore from backup). Do not begin until every validation step above has passed without exception.",
              related_scripts="06_post_archive_vacuum.sql"),
    sql_script("06", "06_post_archive_vacuum", "Checks dead tuple accumulation after the batched deletion and confirms whether a manual VACUUM is warranted to reclaim space.",
               sb.dead_tuples_ranked(),
               "A large deletion produces a correspondingly large number of dead tuples; a manual `VACUUM (VERBOSE, ANALYZE) <table>;` after the batched delete completes reclaims that space for reuse and refreshes planner statistics promptly, rather than waiting for the next scheduled autovacuum pass.",
               related_scripts="../../vacuum-and-autovacuum/table-bloat/README.md"),
]

WORKFLOWS.append(_wf(
    slug="archive-partition",
    title="Archiving via Partition Detach",
    summary="For tables already partitioned by a time/range-compatible key, archives historical data by detaching whole partitions instead of row-by-row deletion -- dramatically faster and lower-risk than archive-large-table's batched-DELETE path.",
    symptoms=["A partitioned table has old partitions (e.g. entire months) that are now fully outside the retention window."],
    business_impact=["Partition detach is a near-instant metadata operation regardless of the partition's row count, avoiding the hours of batched deletion an equivalent unpartitioned-table archive would require."],
    root_causes=["N/A -- planned operation, only applicable to already-partitioned tables."],
    investigation_strategy=["Identify partitions fully outside the retention window.", "Detach the partition (fast, low-lock metadata operation).", "Export the detached partition's data to cold storage (it is now a standalone ordinary table).", "Drop the detached table once its export is validated."],
    prerequisites=["The table must already be partitioned by a boundary compatible with the retention window (see partitioning/partition-existing-large-table if it is not yet partitioned)."],
    interpretation_guide=["`ALTER TABLE ... DETACH PARTITION ... CONCURRENTLY` (PostgreSQL 14+) avoids taking a blocking AccessExclusiveLock on the parent for the duration, at the cost of running as two internal transactions -- prefer it for partitions still receiving any residual read traffic."],
    remediation_immediate=["N/A."],
    remediation_short_term=["N/A."],
    remediation_long_term=["Automate this pattern for time-based partitioned tables via pg_partman's retention policies (see partitioning/partition-maintenance)."],
    production_safety=["DETACH PARTITION (especially CONCURRENTLY) is a fast, low-risk operation. DROP TABLE on the detached partition is irreversible -- always export/validate first, exactly as in archive-large-table."],
    escalation_criteria=["The detached partition's data has not been fully exported/validated and there is pressure to drop it early -- escalate/push back; do not skip validation."],
    related_issues=["../archive-large-table/README.md", "../../partitioning/partition-maintenance/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_partitions_outside_retention", "Identifies partitions whose range is fully outside the approved retention window.",
               """
-- Lists partitions of a given parent table with their bounds, to identify
-- which are fully outside the retention window and eligible for detach.
-- This query is safe to run unmodified: it filters pg_catalog data by name
-- (never a direct FROM/regclass reference to the parent table itself), so
-- an unmatched default parent_table simply returns zero rows rather than
-- failing -- edit the \\set lines below to point at your real partitioned
-- parent table.
\\set schema_name 'public'
\\set parent_table 'orders'
SELECT
    child.relname                                               AS partition_name,
    pg_get_expr(child.relpartbound, child.oid)                    AS partition_bound,
    pg_size_pretty(pg_total_relation_size(child.oid))              AS partition_size
FROM pg_inherits i
JOIN pg_class parent ON parent.oid = i.inhparent
JOIN pg_class child ON child.oid = i.inhrelid
JOIN pg_namespace n ON n.oid = parent.relnamespace
WHERE n.nspname = :'schema_name' AND parent.relname = :'parent_table'
ORDER BY child.relname;
""".strip("\n"),
               "Manually confirm which partition_bound values fall entirely before your approved retention cutoff; only fully-outside-window partitions should be detached.",
               related_scripts="02_detach_and_archive.md"),
    md_script("02", "02_detach_and_archive", "Detaches the identified old partition and archives it before dropping.",
              (
                  "```sql\n"
                  "-- CONCURRENTLY avoids a blocking AccessExclusiveLock on the parent table for\n"
                  "-- the duration (PostgreSQL 14+). It cannot run inside an explicit transaction\n"
                  "-- block.\n"
                  "ALTER TABLE public.orders DETACH PARTITION public.orders_y2022m11 CONCURRENTLY;\n"
                  "```\n\n"
                  "The detached table (`orders_y2022m11`) is now a standalone ordinary table, no "
                  "longer part of the partitioned parent and no longer receiving any pruning-based "
                  "query traffic. Export it to cold storage using the same approach as "
                  "archive-large-table script 02, validate with the same row-count/checksum "
                  "approach as scripts 03-04, and only then:\n\n"
                  "```sql\n"
                  "DROP TABLE public.orders_y2022m11; -- irreversible; only after validated export\n"
                  "```\n"
              ),
              "Do not DROP the detached table until its export has been independently validated, exactly as in archive-large-table.",
              related_scripts="../archive-large-table/scripts/02_export_to_cold_storage.md"),
]

WORKFLOWS.append(_wf(
    slug="purge-old-data",
    title="Purging Old Data (Non-Archived Deletion)",
    summary="Investigates and safely executes deletion of old data that does NOT need to be retained/archived at all (e.g. expired sessions, ephemeral cache-like rows, expired idempotency keys) -- distinct from archive-large-table, where the data must be preserved in cold storage first.",
    symptoms=["A table of inherently ephemeral/expiring data (sessions, tokens, idempotency keys, rate-limit counters) growing without bound.", "No compliance requirement to retain this specific data at all."],
    business_impact=["Ephemeral tables left unpurged grow indefinitely, consuming storage and slowing down any query/index touching them for no business benefit."],
    root_causes=["No scheduled purge job ever implemented for a table designed to hold only transient data.", "A purge job exists but has silently stopped running or is filtering incorrectly."],
    investigation_strategy=["Confirm the data genuinely requires no retention (distinct from archive-large-table's compliance-sensitive data).", "Check current row count/growth and the age distribution of rows.", "Implement or fix a scheduled batched purge."],
    prerequisites=["Explicit confirmation that this data has zero compliance/audit retention requirement -- if there is any doubt, treat it as an archive-large-table candidate instead, not a purge candidate."],
    interpretation_guide=["Unlike archive-large-table, purge-old-data does not require an export step, since the data is deliberately being discarded -- but the batched-deletion safety practices (small batches, monitoring WAL/replica lag) still fully apply."],
    remediation_immediate=["Run a batched purge for the current backlog if one has never been run or has stalled."],
    remediation_short_term=["Schedule a recurring automated purge job (see automation/) sized to keep the table consistently small going forward rather than requiring periodic large manual catch-up purges."],
    remediation_long_term=["Add a TTL-style design pattern (e.g. an expires_at column with an index, or partitioning by creation time with routine detach+drop) for any new ephemeral table from the outset."],
    production_safety=["Batched DELETE guidance mirrors archive-large-table's script 05 -- small batches, monitored, never a single unbounded statement."],
    escalation_criteria=["Uncertainty about whether the data actually requires retention -- escalate to compliance before purging; when in doubt, do not purge."],
    related_issues=["../archive-large-table/README.md", "../retention-policy/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_ephemeral_table_growth_check", "Checks size and age distribution for a candidate ephemeral/expiring table.",
               sb.largest_tables(),
               "Confirm the table's growth trend and cross-reference against your session/token/idempotency-key expiry policy to determine the correct purge cutoff.",
               related_scripts="02_batched_purge.md"),
    md_script("02", "02_batched_purge", "Batched purge template for confirmed-ephemeral data with no retention requirement.",
              (
                  "```sql\n"
                  "-- Same batching discipline as archive-large-table's deletion step, but\n"
                  "-- without any preceding export -- this data is being discarded, not archived.\n"
                  "\\set batch_size 5000\n"
                  "\\set expiry_column 'expires_at'\n"
                  "DELETE FROM public.sessions\n"
                  "WHERE ctid IN (\n"
                  "    SELECT ctid FROM public.sessions\n"
                  "    WHERE expires_at < now()\n"
                  "    LIMIT 5000\n"
                  ");\n"
                  "-- Repeat/COMMIT per batch (drive from an external loop or a PL/pgSQL\n"
                  "-- procedure called via CALL) until GET DIAGNOSTICS reports 0 rows deleted.\n"
                  "```\n"
              ),
              "Confirm zero compliance retention requirement before running -- this data is discarded, not archived, and is not recoverable after each batch commits (barring point-in-time recovery).",
              related_scripts="../../maintenance/README.md"),
]

WORKFLOWS.append(_wf(
    slug="retention-policy",
    title="Retention Policy Documentation and Enforcement",
    summary="Establishes and documents durable retention policy per table/data category, distinguishing compliance-mandated retention (must archive, never purge) from purely operational ephemeral data (safe to purge), and tracks which tables have an active, working enforcement mechanism.",
    symptoms=["No single source of truth exists for how long each table's data must be retained.", "A table has grown for years with no active archiving/purging mechanism despite an intended policy."],
    business_impact=["Inconsistent or undocumented retention creates both a compliance risk (data deleted too early) and an operational/cost risk (data kept indefinitely with no plan)."],
    root_causes=["Retention policy was decided informally at table-creation time and never documented centrally.", "A previously working archive/purge job was silently disabled or broken and never noticed."],
    investigation_strategy=["Inventory large/growing tables and their current retention behavior (archived, purged, or neither).", "Cross-reference against documented compliance requirements.", "Confirm any claimed automated retention job is actually running and succeeding."],
    prerequisites=["Access to compliance/legal retention requirements documentation."],
    interpretation_guide=["A table with continuous growth and no corresponding archive-large-table or purge-old-data mechanism in place is retention policy debt -- flag it even if no incident has occurred yet."],
    remediation_immediate=["N/A -- this is a documentation/audit workflow."],
    remediation_short_term=["For any table found lacking an enforcement mechanism, initiate archive-large-table or purge-old-data as appropriate."],
    remediation_long_term=["Maintain a durable, reviewed retention-policy document (docs/) mapping every large/growing table to its retention period, archive/purge mechanism, and last-verified-working date."],
    production_safety=["This workflow itself is investigative/documentation-only."],
    escalation_criteria=["A table handling regulated financial data has no confirmed retention mechanism -- escalate to compliance/legal and database engineering leadership immediately."],
    related_issues=["../investigate-archiving-candidate/README.md", "../purge-old-data/README.md", "../archive-validation/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_growing_tables_without_retention_evidence", "Surfaces large, continuously growing tables as candidates to audit against the retention-policy document.",
               sb.largest_tables(),
               "Cross-reference every table above a size/growth threshold against your retention-policy document; any table not listed there is retention policy debt and should be triaged.",
               related_scripts="../archive-validation/README.md"),
]

WORKFLOWS.append(_wf(
    slug="archive-validation",
    title="Archive Validation",
    summary="Standalone, repeatable validation procedures to confirm an existing archive (already exported, whether recently or long ago) remains complete, queryable, and restorable -- distinct from the one-time validation performed during an active archive-large-table migration.",
    symptoms=["An archive has not been test-restored/validated since it was created.", "Uncertainty about whether an archive destination (S3, a separate database) is still accessible and intact."],
    business_impact=["An archive that cannot actually be restored/queried when needed (for an audit, a legal request, or a data-recovery need) provides none of the assurance it was created for."],
    root_causes=["Archive validation was a one-time step at creation and was never repeated.", "Underlying storage (S3 bucket policy, a decommissioned archive database) changed in a way that broke access without anyone noticing."],
    investigation_strategy=["Periodically re-run row-count reconciliation between the source table's retained metadata (if any) and the archive.", "Periodically test an actual restore/query against the archive destination.", "Confirm access credentials/permissions to the archive destination are still valid."],
    prerequisites=["Access to both the (if still present) source-side archival record and the archive destination."],
    interpretation_guide=["A successful validation is not just 'the S3 object exists' -- it means the data was actually queried/restored and matched expectations."],
    remediation_immediate=["If validation fails, treat it as a data-loss risk and escalate immediately -- do not wait for a real audit/legal request to discover the problem."],
    remediation_short_term=["Fix access/permission issues found during validation."],
    remediation_long_term=["Schedule recurring archive-validation checks (see automation/) rather than relying on a single point-in-time validation from the original archive-large-table run."],
    production_safety=["Validation queries against the archive destination are read-only; validation against the source table (if any residual metadata is compared) is also read-only."],
    escalation_criteria=["An archive fails validation and no other copy of the data exists -- escalate immediately as a potential data-loss/compliance incident."],
    related_issues=["../archive-large-table/README.md", "../retention-policy/README.md"],
))
wf = WORKFLOWS[-1]
wf.scripts = [
    sql_script("01", "01_periodic_archive_reconciliation", "Re-runs the row-count/checksum reconciliation used during the original archive to confirm the archive remains intact over time.",
               """
-- Periodic re-validation: compares a checksum of the archived data against
-- a previously recorded baseline checksum (stored at archive time) to
-- detect silent corruption/loss in the archive destination over time.
-- expected_row_count/expected_checksum below are illustrative placeholders
-- -- replace them with the real baseline values recorded when this archive
-- was created (see archive-large-table scripts 03/04) before relying on
-- the row_count_matches/checksum comparison.
\\set archive_schema 'archive_db'
\\set archive_table 'orders_archive'
\\set expected_row_count 1500000
\\set expected_checksum 'baseline-checksum-recorded-at-archive-time'
SELECT to_regclass(:'archive_schema' || '.' || :'archive_table') IS NOT NULL AS archive_table_exists
\\gset

\\if :archive_table_exists
SELECT
    count(*)                                                    AS current_row_count,
    md5(string_agg(id::text, ',' ORDER BY id))                    AS current_checksum,
    count(*) = :expected_row_count                                AS row_count_matches
FROM :"archive_schema".:"archive_table";
\\else
SELECT
    'Archive destination ' || :'archive_schema' || '.' || :'archive_table' ||
    ' is not reachable as a local relation in this database. Edit the '
    'archive_schema/archive_table \\set lines above, or run the equivalent '
    'reconciliation directly against your archive destination connection '
    'instead.'                                                     AS notice;
\\endif
""".strip("\n"),
               "row_count_matches must be true and current_checksum must equal the baseline recorded at archive time; any mismatch is a validation failure and should be escalated immediately, not silently re-baselined.",
               related_scripts="../archive-large-table/scripts/04_spot_check_data_integrity.sql"),
]
