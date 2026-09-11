# SSL/TLS Connection Security

**Category:** Security and Access | **Workflow:** `security-and-access/ssl-and-connection-security`

## 1. Problem Description

Verifies whether client connections to the cluster are actually using SSL/TLS, and whether SSL enforcement is configured at the Aurora parameter-group level -- distinct from a typical PostgreSQL deployment, where SSL enforcement is a postgresql.conf/pg_hba.conf concern rather than a parameter-group one.

## 2. Typical Symptoms

- A security review asks 'are all connections to this cluster encrypted in transit'.
- An application team reports a client-side SSL negotiation error connecting to the cluster.

## 3. Business Impact

- Unencrypted connections to a database holding financial transaction data are both a direct security exposure (credentials and data readable on the network path) and very likely a compliance finding (PCI-DSS and similar frameworks generally require encryption in transit for this kind of data).

## 4. Possible Root Causes

- The Aurora cluster parameter group's rds.force_ssl parameter is not enabled, so the server accepts both encrypted and unencrypted connections and enforcement is left entirely to each client's own configuration.
- An application or tool is configured with sslmode=disable or sslmode=allow (client-side opt-out) even though the server would accept SSL if requested.
- An older client library or connection pooler defaults to no SSL and was never explicitly configured to require it.

## 5. Investigation Strategy

1. Check the current mix of SSL vs. non-SSL connections and, for SSL connections, which protocol version/cipher is in use.
2. Check whether rds.force_ssl is enabled at the parameter-group level, which is the authoritative, server-side enforcement mechanism -- not a client-side setting.

## 6. Prerequisites

- pg_monitor role membership to read pg_stat_ssl/pg_stat_activity.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_current_connection_ssl_mix.sql`](scripts/01_current_connection_ssl_mix.sql) -- Breaks down current backend connections by whether SSL is in use, and, for SSL connections, the negotiated protocol version and cipher.
2. [`scripts/02_force_ssl_parameter_status.sql`](scripts/02_force_ssl_parameter_status.sql) -- Checks whether the Aurora rds.force_ssl parameter is currently enabled on this instance, which is the authoritative server-side SSL enforcement mechanism.
3. [`scripts/03_enabling_force_ssl.md`](scripts/03_enabling_force_ssl.md) -- Runbook for enabling rds.force_ssl via the Aurora cluster parameter group once client SSL-readiness has been confirmed.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- SSL/TLS enforcement on Aurora PostgreSQL is controlled by the rds.force_ssl parameter on the DB cluster (and/or instance) parameter group, applied via the AWS Console/CLI/infrastructure-as-code -- there is no postgresql.conf-level ssl=on/off toggle to edit directly the way there is on self-managed PostgreSQL, and ALTER SYSTEM cannot set it.

## 8. Interpretation Guide

- A non-zero count of ssl = false rows in the connection mix confirms unencrypted connections currently exist -- ssl = false with rds.force_ssl not enabled means the server is silently allowing them; ssl = false while rds.force_ssl is enabled should not be possible for ordinary client connections, but Aurora's own internal management connections may be exempt, so investigate the specific application_name/usename before assuming a client bypassed enforcement.
- A low/old TLS version (anything below TLSv1.2) on any connection is worth flagging even if the connection is nominally 'using SSL', since an outdated protocol version undermines the intended security guarantee.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If unencrypted connections are found carrying sensitive data in an active-incident context, work with the owning application team to force a client-side reconnect with sslmode=require or stronger while the parameter-group change (below) is scheduled.

**Short-term remediation** (hours to days):

- Enable rds.force_ssl on the cluster parameter group (see this workflow's runbook script) once client applications have been confirmed SSL-capable, so the server itself refuses unencrypted connections rather than relying on every client to opt in correctly.

**Long-term engineering fix** (days to weeks):

- Standardize on sslmode=verify-full (certificate validation, not just encryption) in every application's connection configuration, using the Aurora/RDS CA bundle, so connections are also protected against interception via a spoofed endpoint, not just eavesdropping.

## 10. Production Safety

- The SQL investigation scripts here are read-only. Enabling rds.force_ssl is a parameter-group change: for parameters requiring a reboot to take effect, plan it as a maintenance-window activity (see maintenance/parameter-group-change-management), and confirm every client that will connect afterward is SSL-capable before enforcing it cluster-wide.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- Sensitive/financial-data connections are found using SSL protocol versions below TLSv1.2, or entirely unencrypted, on a production writer -- escalate to the security team regardless of whether rds.force_ssl is already enabled, since a permissive client-side sslmode can still coexist with a lenient server setting.

## 12. Related Issues

- [audit-logging-and-iam-auth](../audit-logging-and-iam-auth/README.md)
- [parameter-group-change-management](../../maintenance/parameter-group-change-management/README.md)
