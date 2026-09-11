/*
===============================================================================
SCRIPT NAME:
04_extended_statistics_inventory.sql

PURPOSE:
Lists the extended statistics objects defined in this database and the columns they cover.

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
Step 04 of workflow 'query-optimization/cardinality-estimation'

RELATED SCRIPTS:
05_confirm_estimate_error.md

HOW TO INTERPRET RESULTS:
An empty first result set is common and is itself a finding: most databases have no extended statistics at all, so every multi-column predicate is being estimated on an independence assumption that exchange data routinely violates. The second result set ranks large tables that carry several low-cardinality columns -- these are where a CREATE STATISTICS object is most likely to pay off, typically on pairs such as (market_symbol, order_status) or (asset, entry_type). Note that an extended statistics object listed here is inert until the table is analyzed: creating it does nothing on its own, and the populated data itself lives in a catalog that ordinary monitoring roles cannot read, so verify its effect through the plan rather than through the catalog.
===============================================================================
*/

-- Extended statistics objects teach the planner about relationships
-- BETWEEN columns. Without them, the planner assumes independence and
-- multiplies selectivities, which for correlated columns produces an
-- estimate that is far too small -- the classic trigger for a runaway
-- nested loop.
--
-- stxkind codes: 'd' = n-distinct, 'f' = functional dependencies,
-- 'm' = most-common-values list, 'e' = expression statistics.
--
-- stxkeys is an int2vector and is cast to smallint[] so it can be used
-- with ANY(); this is the same catalog-safe pattern used elsewhere in this
-- toolkit for pg_index.indkey.
SELECT
    sn.nspname                                                   AS statistics_schema,
    s.stxname                                                    AS statistics_name,
    tn.nspname                                                   AS table_schema,
    c.relname                                                    AS table_name,
    (
        SELECT array_agg(a.attname ORDER BY a.attnum)
        FROM pg_attribute a
        WHERE a.attrelid = s.stxrelid
          AND a.attnum = ANY (s.stxkeys::int2[])
    )                                                            AS covered_columns,
    s.stxkind                                                    AS statistic_kinds
FROM pg_statistic_ext s
JOIN pg_class c ON c.oid = s.stxrelid
JOIN pg_namespace tn ON tn.oid = c.relnamespace
JOIN pg_namespace sn ON sn.oid = s.stxnamespace
ORDER BY table_schema, table_name, statistics_name;

-- Candidate tables where extended statistics may be worth creating:
-- large tables carrying multiple low-cardinality columns that application
-- predicates commonly combine (for example market symbol plus order
-- status, or asset plus transaction type).
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    pg_size_pretty(pg_total_relation_size(c.oid))                 AS total_size,
    c.reltuples::bigint                                          AS estimated_rows,
    count(*) FILTER (WHERE st.n_distinct BETWEEN 1 AND 1000)       AS low_cardinality_columns,
    EXISTS (
        SELECT 1 FROM pg_statistic_ext s WHERE s.stxrelid = c.oid
    )                                                            AS already_has_extended_statistics
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stats st
       ON st.schemaname = n.nspname
      AND st.tablename = c.relname
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
GROUP BY n.nspname, c.relname, c.oid, c.reltuples
HAVING count(*) FILTER (WHERE st.n_distinct BETWEEN 1 AND 1000) >= 2
ORDER BY pg_total_relation_size(c.oid) DESC
LIMIT 25;
