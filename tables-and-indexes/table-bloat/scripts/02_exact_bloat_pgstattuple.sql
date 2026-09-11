/*
===============================================================================
SCRIPT NAME:
02_exact_bloat_pgstattuple.sql

PURPOSE:
Exact physical bloat scan for one specific table.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY (may be resource intensive on very large tables -- see EXPECTED IMPACT)

EXPECTED IMPACT:
Full or sampled table scan; can be I/O-intensive on very large tables.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required.

PREREQUISITES:
pgstattuple extension must be created in the current database.

EXECUTION ORDER:
Step 02 of workflow 'tables-and-indexes/table-bloat'

RELATED SCRIPTS:
../../maintenance/README.md

HOW TO INTERPRET RESULTS:
free_pct + dead_tuple_pct above 30-40% on a large table is a strong candidate for a scheduled space-reclaiming operation.
===============================================================================
*/

-- Exact physical bloat via the pgstattuple extension, for the single
-- largest ordinary user table in the current database (a bounded,
-- automatic candidate -- edit the candidate_relation query below to target
-- a specific table instead). Performs a full scan of that table (a light
-- read lock, not a blocking lock) -- do not run this against your largest
-- hot tables during peak trading hours without testing impact first;
-- prefer pgstattuple_approx() for very large tables.
--
-- IMPORTANT: this script deliberately does NOT run `CREATE EXTENSION
-- pgstattuple` -- that is a DDL/catalog-write operation that cannot execute
-- under `default_transaction_read_only = on` (the recommended posture for
-- an investigation script, and the default on an Aurora reader), and
-- installing extensions is a change-managed decision, not something an
-- ad hoc investigation script should do silently. If the extension is not
-- installed, this prints an instructional notice instead of failing, and
-- never references the pgstattuple() function by name unless the
-- extension is confirmed present -- referencing a function that does not
-- exist yet would otherwise fail at parse/analysis time even inside a
-- branch that "looks" conditional.
SELECT EXISTS (
    SELECT 1 FROM pg_extension WHERE extname = 'pgstattuple'
)                                                                AS pgstattuple_available
\gset

\if :pgstattuple_available
SELECT c.oid::regclass::text AS candidate_relation
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT 1
\gset

SELECT
    :'candidate_relation'                                       AS table_analyzed,
    table_len,
    tuple_count,
    tuple_len,
    round(100.0 * tuple_len / NULLIF(table_len, 0), 2)            AS tuple_pct,
    dead_tuple_count,
    dead_tuple_len,
    round(100.0 * dead_tuple_len / NULLIF(table_len, 0), 2)       AS dead_tuple_pct,
    free_space,
    round(100.0 * free_space / NULLIF(table_len, 0), 2)           AS free_pct
FROM pgstattuple(:'candidate_relation'::regclass);
\else
SELECT
    'pgstattuple extension is not installed in this database. This script '
    'never runs CREATE EXTENSION automatically (DDL is out of scope for a '
    'read-only investigation script). Ask an administrator to run '
    'CREATE EXTENSION pgstattuple; in a change-managed session if exact '
    'physical bloat is required, or use 01_table_bloat_estimate.sql in this '
    'same directory for a no-extension catalog-only proxy.'               AS notice;
\endif
