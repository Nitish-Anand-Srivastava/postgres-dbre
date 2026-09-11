# 03_enabling_force_ssl

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_enabling_force_ssl.md` |
| Purpose | Runbook for enabling rds.force_ssl via the Aurora cluster parameter group once client SSL-readiness has been confirmed. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | LOW RISK WRITE (Aurora DB cluster parameter group change; typically requires a per-instance reboot to take effect -- see runbook) |
| Expected impact | No impact until applied; once applied, any client still connecting without SSL will begin failing to connect immediately after each instance's reboot. |
| Required privileges | IAM permission to modify the DB cluster parameter group (rds:ModifyDBClusterParameterGroup or console equivalent); no PostgreSQL role required for the parameter-group step itself. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 03 of workflow `security-and-access/ssl-and-connection-security` |
| Related scripts | 02_force_ssl_parameter_status.sql |

## How to interpret / use this runbook

Read the full rollout sequence before applying -- the risk in this change is almost never the parameter itself, it is enforcing it before every client is confirmed ready.

---

## Before enabling

Confirm every application/service that connects to this cluster is already capable of SSL connections (ideally `sslmode=verify-full` with the RDS CA bundle installed) using `01_current_connection_ssl_mix.sql` -- enabling `rds.force_ssl` before every client is ready will disconnect and then continuously reject any client still connecting with `sslmode=disable`.

## Enabling via the AWS CLI

`rds.force_ssl` is set on the DB cluster parameter group, not per instance:

```
aws rds modify-db-cluster-parameter-group \
  --db-cluster-parameter-group-name <cluster-parameter-group-name> \
  --parameters "ParameterName=rds.force_ssl,ParameterValue=1,ApplyMethod=pending-reboot"
```

Confirm the parameter's `ApplyType` via `describe-db-cluster-parameters` before assuming it is dynamic -- on many Aurora PostgreSQL engine versions `rds.force_ssl` requires a reboot of each instance in the cluster to take effect, which is a brief availability interruption per instance and should be scheduled as a maintenance-window activity (see maintenance/parameter-group-change-management), not applied immediately to a live production writer.

## Rolling out safely

1. Apply the parameter-group change to a non-production cluster's parameter group first and confirm existing non-SSL client configurations there actually fail as expected.
2. Update any client still on `sslmode=disable`/`allow` to `require` or stronger.
3. Schedule the reboot for the production cluster's instances during a maintenance window, rebooting readers before the writer where failover order matters.
4. Re-run `01_current_connection_ssl_mix.sql` afterward to confirm no connection is being silently rejected in a way that surfaces as an application-level outage.
