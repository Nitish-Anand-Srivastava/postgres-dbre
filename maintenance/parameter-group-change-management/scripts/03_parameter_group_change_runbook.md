# 03_parameter_group_change_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `03_parameter_group_change_runbook.md` |
| Purpose | Guarded runbook for making an Aurora parameter-group change safely: validating on non-prod first, understanding ApplyType, and scheduling any required reboot. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Any instance (writer or reader) |
| Safety | LOW RISK WRITE (Aurora DB cluster/instance parameter group change; static parameters require a per-instance reboot to take effect -- see runbook) |
| Expected impact | None until applied; a static parameter's eventual reboot causes a brief per-instance availability interruption, worse on the writer than on a reader. |
| Required privileges | IAM permission to describe/modify DB cluster and instance parameter groups; no PostgreSQL role required for the parameter-group step itself. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 03 of workflow `maintenance/parameter-group-change-management` |
| Related scripts | 01_key_settings_and_scope.sql, 02_pending_restart_settings.sql |

## How to interpret / use this runbook

Confirm ApplyType before choosing ApplyMethod, and always validate on non-production first -- the mechanism itself (cluster vs. instance parameter group, dynamic vs. static) is what most parameter-group-change mistakes get wrong, not the chosen value.

---

## Choose the right parameter group

Cluster-wide settings (the majority of what matters operationally -- memory, autovacuum, logging, statement/lock timeouts) belong on the DB **cluster** parameter group, applied to every instance in the cluster. A small number of instance-specific overrides belong on the DB **instance** parameter group instead. Confirm you are editing a **custom** parameter group, not the AWS-managed default one, which cannot be modified.

## Validate on non-production first

Apply the intended change to a non-production cluster's parameter group and confirm the resulting behavior (via `01_key_settings_and_scope.sql`) before touching production, especially for any setting affecting memory sizing or autovacuum aggressiveness, where an overly aggressive value can itself cause a performance regression.

## Applying the change

```
aws rds modify-db-cluster-parameter-group \
  --db-cluster-parameter-group-name <cluster-parameter-group-name> \
  --parameters "ParameterName=<parameter-name>,ParameterValue=<new-value>,ApplyMethod=pending-reboot"
```

Check the parameter's `ApplyType` first via:

```
aws rds describe-db-cluster-parameters \
  --db-cluster-parameter-group-name <cluster-parameter-group-name> \
  --query "Parameters[?ParameterName=='<parameter-name>'].ApplyType"
```

An `ApplyType` of `dynamic` can use `ApplyMethod=immediate` and takes effect without a reboot; `static` requires `ApplyMethod=pending-reboot` and will not take effect until each instance is rebooted.

## Scheduling the reboot (static parameters only)

Reboot readers first, then the writer, during an agreed maintenance window -- rebooting the writer causes a brief failover-like interruption (see disaster-recovery/cluster-failover-drill for what that interruption looks like from the application's perspective). Re-run `02_pending_restart_settings.sql` immediately after each reboot to confirm the setting cleared from the pending list.

## Do NOT

- Do NOT attempt `ALTER SYSTEM SET ...` as a substitute -- Aurora does not support it for parameter-group-managed settings, and it will either fail outright or (for the handful of settings where it is accepted) create a confusing split between the session/instance-level value and the parameter group's own value.
- Do NOT apply a `static` parameter change with `ApplyMethod=immediate` expecting it to take effect without a reboot -- AWS will accept the parameter-group update but the running instance will not reflect it until rebooted regardless of the ApplyMethod requested.
