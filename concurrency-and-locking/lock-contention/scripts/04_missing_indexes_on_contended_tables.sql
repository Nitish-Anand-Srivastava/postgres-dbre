/*
===============================================================================
SCRIPT NAME:
04_missing_indexes_on_contended_tables.sql

PURPOSE:
Checks index coverage on the most contended tables identified in script 02, since a missing index can widen lock scope under row-locking operations.

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
Step 04 of workflow 'concurrency-and-locking/lock-contention'

RELATED SCRIPTS:
../../tables-and-indexes/missing-index-candidates/README.md

HOW TO INTERPRET RESULTS:
A contended table with an unindexed foreign key or filter column is very likely locking far more rows/pages than the business logic actually requires.
===============================================================================
*/

-- Foreign key constraints whose referencing columns have no supporting
-- index on the child table. Unindexed FKs commonly cause full-table
-- sequential scans on the child table whenever the parent row is updated or
-- deleted (to check for dependents) and are one of the most common
-- "missing index candidate" findings in ledger/order/account schemas with
-- deep FK graphs.
SELECT
    con.conname                                                 AS constraint_name,
    tn.nspname                                                  AS child_schema,
    tc.relname                                                  AS child_table,
    pg_get_constraintdef(con.oid)                                AS constraint_definition
FROM pg_constraint con
JOIN pg_class tc ON tc.oid = con.conrelid
JOIN pg_namespace tn ON tn.oid = tc.relnamespace
WHERE con.contype = 'f'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_index ix
      WHERE ix.indrelid = con.conrelid
        -- Leftmost-prefix match: the index's first N columns (N = number of
        -- FK columns) must exactly equal the FK's referencing columns, in
        -- the same order, for the index to actually support the FK's
        -- lookup/cascade pattern.
        AND (ix.indkey::int2[])[0:array_length(con.conkey, 1) - 1] = con.conkey
  )
ORDER BY child_schema, child_table;
