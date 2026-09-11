/*
===============================================================================
SCRIPT NAME:
02_authentication_settings_and_role_overrides.sql

PURPOSE:
Reports the cluster's authentication-relevant settings and every per-role/per-database setting override that could weaken them for a specific identity.

AURORA POSTGRESQL VERSION:
Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)

EXECUTION LOCATION:
Any instance (writer or reader)

SAFETY:
READ ONLY

EXPECTED IMPACT:
Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.

REQUIRED PRIVILEGES:
Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. No superuser required. Some parameters are only visible in full to members of `pg_read_all_settings`; a restricted role sees the row but may see a masked value.

PREREQUISITES:
None beyond CONNECT on the target database.

EXECUTION ORDER:
Step 02 of workflow 'security-and-access/credential-and-authentication-hygiene'

RELATED SCRIPTS:
03_credential_rotation_and_hardening.md

HOW TO INTERPRET RESULTS:
password_encryption should read scram-sha-256; md5 means any password set under it is stored as an md5 verifier until that password is re-set, so changing the setting alone does not upgrade existing credentials. log_connections = off means there is no record of which credential connected from which address, which is the single setting that most limits a post-incident investigation (see access-anomaly-investigation). In the second result set, read every setting_overrides array carefully: a role-scoped override of statement_timeout or row_security is legitimate in some designs and a deliberate weakening in others, and only the documented intent distinguishes them.
===============================================================================
*/

-- Authentication- and session-security-relevant settings. All of these are
-- managed through the Aurora DB cluster/instance parameter group rather than
-- a postgresql.conf file, so `source` tells you whether the current value
-- came from the parameter group, a per-role override, or the built-in
-- default. Filtering pg_settings by name in a WHERE clause is safe even for
-- parameters that do not exist on a given engine version -- absent ones
-- simply return no row.
SELECT
    name,
    setting,
    unit,
    context,
    source,
    boot_val                                                     AS default_value
FROM pg_settings
WHERE name IN (
        'password_encryption',
        'ssl',
        'rds.force_ssl',
        'log_connections',
        'log_disconnections',
        'log_statement',
        'log_min_duration_statement',
        'idle_in_transaction_session_timeout',
        'idle_session_timeout',
        'statement_timeout',
        'authentication_timeout',
        'row_security'
    )
ORDER BY name;

-- Per-role and per-database setting overrides (ALTER ROLE ... SET / ALTER
-- DATABASE ... SET). An override here silently replaces the cluster-wide
-- value for that identity, which is a common way a tightened default gets
-- undone for exactly the role that most needed it.
SELECT
    coalesce(d.datname, 'all databases')                         AS applies_to_database,
    coalesce(r.rolname, 'all roles')                             AS applies_to_role,
    s.setconfig                                                  AS setting_overrides
FROM pg_db_role_setting s
LEFT JOIN pg_database d ON d.oid = s.setdatabase
LEFT JOIN pg_roles r ON r.oid = s.setrole
ORDER BY applies_to_database, applies_to_role;
