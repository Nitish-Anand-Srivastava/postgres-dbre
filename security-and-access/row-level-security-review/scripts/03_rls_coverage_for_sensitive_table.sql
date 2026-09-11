/*
===============================================================================
SCRIPT NAME:
03_rls_coverage_for_sensitive_table.sql

PURPOSE:
End-to-end RLS review of one specific high-sensitivity table -- flags, policies, and object-level grants -- defaulting to public.wallets and guarded so it prints a notice rather than failing if that table does not exist.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required. Reading `information_schema.table_privileges` additionally shows only grants involving roles the current role is a member of or can otherwise see, so a full grant picture may require an ownership-level or `pg_read_all_stats`-plus-ownership role.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 03 of workflow 'security-and-access/row-level-security-review'

RELATED SCRIPTS:
04_enabling_row_level_security.md

HOW TO INTERPRET RESULTS:
Read the three result sets together: the first says whether the control is active and whether the owner is exempt, the second says whether the policies actually restrict anything, and the third says which roles reach the table at all. A table with strong policies but a SELECT grant to a broad group role still exposes exactly as many rows as its weakest policy allows for that group. If the notice row appears instead, the default table name does not match this schema -- pick a real one from script 01 rather than concluding there is nothing sensitive here.
===============================================================================
*/

-- Focused, end-to-end review of one table. The default target is
-- public.wallets, the table most exchange schemas use for per-customer
-- balances; change the two variables below to review any other sensitive
-- table (public.ledger_entries, public.withdrawals, and so on).
--
-- to_regclass() is used rather than a bare ::regclass cast so that a
-- schema which names this table differently produces an instructional
-- notice instead of a "relation does not exist" parse failure.
\set schema_name 'public'
\set table_name 'wallets'

SELECT to_regclass(:'schema_name' || '.' || :'table_name') IS NOT NULL AS target_table_exists
\gset

\if :target_table_exists
SELECT
    n.nspname                                                    AS schema_name,
    c.relname                                                    AS table_name,
    c.relrowsecurity                                             AS rls_enabled,
    c.relforcerowsecurity                                        AS rls_forced_for_owner,
    pg_get_userbyid(c.relowner)                                  AS table_owner,
    (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)  AS policy_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.oid = to_regclass(:'schema_name' || '.' || :'table_name');

SELECT
    policyname                                                   AS policy_name,
    permissive,
    roles                                                        AS applies_to_roles,
    cmd                                                          AS applies_to_command,
    qual                                                         AS using_expression,
    with_check                                                   AS with_check_expression
FROM pg_policies
WHERE schemaname = :'schema_name'
  AND tablename = :'table_name'
ORDER BY policy_name;

SELECT
    grantee,
    privilege_type,
    is_grantable
FROM information_schema.table_privileges
WHERE table_schema = :'schema_name'
  AND table_name = :'table_name'
ORDER BY grantee, privilege_type;
\else
SELECT
    'The configured target table does not exist in this database. Set the '
    'schema_name and table_name variables at the top of this script to a '
    'table that does exist (use 01_rls_status_by_table.sql to pick the '
    'highest-sensitivity uncovered table) and re-run.'                     AS notice;
\endif
