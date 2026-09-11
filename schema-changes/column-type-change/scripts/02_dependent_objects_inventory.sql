/*
===============================================================================
SCRIPT NAME:
02_dependent_objects_inventory.sql

PURPOSE:
Inventories every index, constraint, incoming foreign key, view, and trigger that depends on the target table.

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
Step 02 of workflow 'schema-changes/column-type-change'

RELATED SCRIPTS:
03_target_table_size.sql

HOW TO INTERPRET RESULTS:
This list is the real scope of the change and it is almost always larger than expected. Every index on the changed column is rebuilt by a rewrite. Every dependent view must be dropped and recreated, because a view records the type of each of its output columns. Incoming foreign keys are the biggest item: if another table references the column you are widening, its referencing column must change type in lockstep, which means coordinating a simultaneous change across every child table and every team that owns one. Triggers are the quiet hazard in the online pattern -- a trigger on the table will fire during the backfill unless you account for it. Edit the schema_name and table_name variables at the top for your real target.
===============================================================================
*/

-- Everything that depends on the target table and will therefore need
-- attention when its shape changes: indexes, constraints on it, foreign keys
-- pointing at it from elsewhere, dependent views/materialized views, and
-- user triggers.
--
-- to_regclass() is used rather than a ::regclass cast throughout. A cast
-- raises "relation does not exist" and aborts the whole statement the moment
-- the shipped default table is absent; to_regclass() returns NULL instead, so
-- each branch simply contributes zero rows and the script still runs clean.
\set schema_name 'public'
\set table_name 'trades'
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
