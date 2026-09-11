# Scripts: SSL/TLS Connection Security

Execution order, safety classification, and expected runtime for every script
in `security-and-access/ssl-and-connection-security/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
| 01 | `01_current_connection_ssl_mix.sql` | Breaks down current backend connections by whether SSL is in use, and, for SSL connections, the negotiated protocol version and cipher. | READ ONLY | Low (sub-second to a few seconds) |
| 02 | `02_force_ssl_parameter_status.sql` | Checks whether the Aurora rds.force_ssl parameter is currently enabled on this instance, which is the authoritative server-side SSL enforcement mechanism. | READ ONLY | Low (sub-second to a few seconds) |
| 03 | `03_enabling_force_ssl.md` | Runbook for enabling rds.force_ssl via the Aurora cluster parameter group once client SSL-readiness has been confirmed. | LOW RISK WRITE (Aurora DB cluster parameter group change; typically requires a per-instance reboot to take effect -- see runbook) | Minutes to apply the parameter; a full maintenance-window reboot cycle across the cluster's instances for it to take effect. |

## Execution Order

Run scripts strictly in the numeric order shown above. Each script assumes the
operator has reviewed the output of the prior step. Do not skip ahead to a
remediation template (`.md` files, if present) without completing the
read-only investigation steps first.

## Required Permissions

Unless a script states otherwise in its `REQUIRED PRIVILEGES` header field, a
role with the built-in `pg_monitor` (or `pg_read_all_stats` /
`pg_read_all_settings`) attribute, `CONNECT` on the target database, and
`USAGE` on `public` is sufficient. Scripts that read `pg_stat_statements`
require that extension to be installed in the current database. Scripts that
touch DDL, `pg_terminate_backend()`, or write operations state elevated
requirements explicitly in their own header.

## Expected Output

Every script returns a result set intended to be read directly in `psql` (or
any SQL client). Columns are named for direct interpretation; each script's
header contains a `HOW TO INTERPRET RESULTS` section, and the parent
`README.md` section 8 ("Interpretation Guide") gives workflow-level guidance.

## When to Stop and Escalate

- Sensitive/financial-data connections are found using SSL protocol versions below TLSv1.2, or entirely unencrypted, on a production writer -- escalate to the security team regardless of whether rds.force_ssl is already enabled, since a permissive client-side sslmode can still coexist with a lenient server setting.

## Scripts That Should Not Be Run During Severe Incidents

- 03_enabling_force_ssl.md -- No impact until applied; once applied, any client still connecting without SSL will begin failing to connect immediately after each instance's reboot.
