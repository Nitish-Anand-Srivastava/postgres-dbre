/*
===============================================================================
SCRIPT NAME:
01_current_connection_ssl_mix.sql

PURPOSE:
Breaks down current backend connections by whether SSL is in use, and, for SSL connections, the negotiated protocol version and cipher.

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
Step 01 of workflow 'security-and-access/ssl-and-connection-security'

RELATED SCRIPTS:
02_force_ssl_parameter_status.sql

HOW TO INTERPRET RESULTS:
Any row with ssl = false is a currently-unencrypted connection -- note its application_name/usename to identify the responsible client for remediation. Among ssl = true rows, a tls_version below TLSv1.2 is also worth flagging even though the connection is nominally encrypted.
===============================================================================
*/

-- Current connection mix by SSL status/protocol/cipher, joined against
-- pg_stat_activity so each row is attributable to an application/user. A
-- row with ssl = false is an unencrypted connection right now.
SELECT
    a.application_name,
    a.usename,
    s.ssl,
    s.version                                                    AS tls_version,
    s.cipher,
    count(*)                                                     AS connection_count
FROM pg_stat_ssl s
JOIN pg_stat_activity a ON a.pid = s.pid
WHERE a.pid <> pg_backend_pid()
GROUP BY a.application_name, a.usename, s.ssl, s.version, s.cipher
ORDER BY s.ssl ASC, connection_count DESC;
