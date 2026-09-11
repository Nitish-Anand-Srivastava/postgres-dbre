/*
===============================================================================
SCRIPT NAME:
03_dependent_objects_inventory.sql

PURPOSE:
Inventories every index, constraint, trigger, view, and foreign key touching the candidate table that must be recreated or adapted on the new partitioned structure.

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
Step 03 of workflow 'partitioning/partition-existing-large-table'

RELATED SCRIPTS:
04_row_count_baseline.sql

HOW TO INTERPRET RESULTS:
Every object returned here needs an explicit plan: indexes must be recreated per-partition (PostgreSQL 11+ propagates a CREATE INDEX on the parent to all partitions automatically), triggers may need to be re-evaluated for partition-local vs. parent-level behavior, and dependent views must be tested against the new partitioned table before cutover.
===============================================================================
*/

-- Full dependency inventory for the migration plan: indexes, constraints,
-- triggers, and dependent views. Foreign keys are covered separately by
-- investigate-partitioning-candidate/scripts/03_constraint_and_fk_complexity.sql.
-- Ships with an illustrative default (public.orders); edit the \set lines
-- below for your real candidate table. to_regclass() (never a bare
-- ::regclass cast) is used throughout so a missing default table returns
-- zero rows for the trigger/view branches instead of aborting the query.
\set schema_name 'public'
\set table_name 'orders'
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
