# 03_installing_pgaudit_and_granting_iam_auth

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_installing_pgaudit_and_granting_iam_auth.md` |
| Purpose | Guarded runbook for installing pgaudit (change-managed, reboot-driving) and for granting IAM database authentication to a role. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | LOW RISK WRITE (shared_preload_libraries parameter-group change requires a reboot; CREATE EXTENSION and GRANT are schema/role changes -- see runbook for sequencing) |
| Expected impact | pgaudit adds per-statement logging overhead proportional to its configured scope once installed and enabled; granting rds_iam has no impact until the client is updated to use an IAM token. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). Additionally, IAM permission to modify the DB cluster parameter group, and CREATEROLE (or rds_superuser) to GRANT rds_iam to another role. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 03 of workflow `security-and-access/audit-logging-and-iam-auth` |
| Related scripts | 01_pgaudit_installation_and_scope.sql, 02_iam_authenticated_roles.sql |

## How to interpret / use this runbook

Both changes here are deliberate, change-managed steps -- pgaudit installation because it requires a reboot and adds ongoing logging overhead, and rds_iam grants because they change how an application authenticates and require a coordinated client-side update.

---

## Installing pgaudit

pgaudit requires two steps, the first of which needs a reboot to take effect and must be scheduled as a maintenance-window activity (see maintenance/parameter-group-change-management):

1. Add `pgaudit` to the DB cluster parameter group's `shared_preload_libraries`:

```
aws rds modify-db-cluster-parameter-group \
  --db-cluster-parameter-group-name <cluster-parameter-group-name> \
  --parameters "ParameterName=shared_preload_libraries,ParameterValue=pgaudit,ApplyMethod=pending-reboot"
```

   If `shared_preload_libraries` already lists other modules (e.g. `pg_stat_statements`), include the full comma-separated list -- this parameter is not additive across separate calls.

2. After the reboot, install the extension itself. This is the one and only place in this runbook where `CREATE EXTENSION` appears, and it is intentionally shown only as documentation, not as an auto-executing script, because installing an extension is a schema-level, change-managed decision:

```sql
CREATE EXTENSION pgaudit;
```

   Then set `pgaudit.log` (and any other `pgaudit.*` parameter) through the DB cluster/instance parameter group -- the same mechanism as `shared_preload_libraries` above, not a SQL session command, since Aurora does not support `ALTER SYSTEM` for this or any other parameter-group-managed setting:

```
aws rds modify-db-cluster-parameter-group \
  --db-cluster-parameter-group-name <cluster-parameter-group-name> \
  --parameters "ParameterName=pgaudit.log,ParameterValue='write\,ddl\,role',ApplyMethod=immediate"
```

   choosing a scope (e.g. `write, ddl, role`) that matches your actual compliance requirement.

## Granting IAM database authentication to a role

```sql
GRANT rds_iam TO app_readonly;
```

After granting, update the connecting application/service to request an IAM auth token (via the AWS SDK's `generate-db-auth-token` or equivalent) instead of a static password, and confirm `pg_hba.conf`-equivalent Aurora auth configuration permits IAM auth for that role's connection path -- this is itself managed through the parameter group / AWS Console, not a SQL statement.

## Verifying afterward

Re-run `01_pgaudit_installation_and_scope.sql` and `02_iam_authenticated_roles.sql` to confirm both changes took effect as intended.
