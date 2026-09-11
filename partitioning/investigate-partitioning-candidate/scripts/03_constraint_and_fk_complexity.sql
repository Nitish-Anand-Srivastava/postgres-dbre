/*
===============================================================================
SCRIPT NAME:
03_constraint_and_fk_complexity.sql

PURPOSE:
Inventories existing constraints and foreign keys referencing/referenced-by the candidate table, since these materially affect migration difficulty.

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
Step 03 of workflow 'partitioning/investigate-partitioning-candidate'

RELATED SCRIPTS:
../partition-existing-large-table/README.md

HOW TO INTERPRET RESULTS:
Every foreign key pointing INTO the candidate table needs the referenced unique/PK constraint to include the partition key columns after migration -- this is frequently the single biggest source of migration complexity and must be planned for explicitly in partition-existing-large-table.
===============================================================================
*/

-- All constraints on the candidate table, plus any foreign keys FROM other
-- tables pointing AT it (which is the more complex direction to migrate,
-- since referenced unique/PK constraints on a partitioned table have extra
-- requirements in PostgreSQL: the referenced columns must be part of the
-- partition key for a FK to reference a partitioned table in PG12+). Ships
-- with an illustrative default (public.orders); edit the \set lines below
-- for your real candidate table.
\set schema_name 'public'
\set table_name 'orders'
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
