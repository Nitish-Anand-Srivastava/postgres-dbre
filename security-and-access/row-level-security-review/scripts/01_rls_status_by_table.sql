/*
===============================================================================
SCRIPT NAME:
01_rls_status_by_table.sql

PURPOSE:
Inventories every table in a non-system schema with its row-level-security flags, policy count, owner, and size, so sensitive tables with no coverage surface first.

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
Step 01 of workflow 'security-and-access/row-level-security-review'

RELATED SCRIPTS:
02_policy_definitions_and_bypass_roles.sql

HOW TO INTERPRET RESULTS:
Rows sort with unprotected tables first, largest first -- a large table at the top of this list holding per-customer wallet, ledger, or withdrawal data is the finding. rls_enabled = true with rls_forced_for_owner = false means the owner (often the same role the application connects as) sees every row regardless of policy; confirm which role the application actually connects as before recording that table as protected. policy_count = 0 with rls_enabled = true is a deny-all table for non-owners, which is a functional risk rather than a security one -- verify the application is not silently returning zero rows.
===============================================================================
*/

-- RLS posture for every ordinary/partitioned table outside the system
-- schemas. relrowsecurity is the "RLS is enabled" flag; relforcerowsecurity
-- additionally subjects the table's *owner* to its own policies (owners are
-- exempt by default, which is the single most common reason RLS looks
-- enabled but does not restrict the application).
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    c.relrowsecurity                                             AS rls_enabled,
    c.relforcerowsecurity                                        AS rls_forced_for_owner,
    (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)  AS policy_count,
    pg_get_userbyid(c.relowner)                                  AS table_owner,
    pg_size_pretty(pg_total_relation_size(c.oid))                AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY c.relrowsecurity ASC, pg_total_relation_size(c.oid) DESC, schema_name, table_name;
