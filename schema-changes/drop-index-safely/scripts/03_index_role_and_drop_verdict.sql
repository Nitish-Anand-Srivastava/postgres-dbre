/*
===============================================================================
SCRIPT NAME:
03_index_role_and_drop_verdict.sql

PURPOSE:
Establishes the structural role of every index on the target table and produces an explicit per-index verdict.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 03 of workflow 'schema-changes/drop-index-safely'

RELATED SCRIPTS:
04_drop_index_safely_runbook.md

HOW TO INTERPRET RESULTS:
Read drop_verdict first and structure before usage. An index backing a primary key or unique constraint cannot be dropped by name at all -- the statement fails, and the correct action is to drop the constraint, which removes the index with it. An index flagged as replica identity must stay while any logical replication or AWS DMS pipeline depends on the table, or UPDATE and DELETE against it will start failing outright. A foreign-key-supporting index deserves particular caution even at zero scans, because it may be preventing every parent delete from sequentially scanning this child table without that registering as a conventional index scan. Copy index_definition for every index you intend to drop into the change ticket before proceeding. Edit the schema_name and table_name variables at the top for your real target.
===============================================================================
*/

-- Structural role and an explicit drop verdict for every index on one target
-- table. An index can be unused by the planner and still be structurally
-- required -- backing a primary key or unique constraint, serving as the
-- table's replica identity for logical replication, or supporting a foreign
-- key check. This script surfaces all of those roles together so the decision
-- is made on structure first and usage second.
--
-- Ships with an illustrative default (public.trades); edit the \set lines
-- below for your real target. Names are compared only inside a catalog WHERE
-- clause and never cast to regclass, so running this unmodified against a
-- database without that table simply returns zero rows.
\set schema_name 'public'
\set table_name 'trades'
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
