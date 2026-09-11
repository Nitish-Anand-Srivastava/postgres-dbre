# Aurora Parameter Group Change Management

**Category:** Maintenance | **Workflow:** `maintenance/parameter-group-change-management`

## 1. Problem Description

Explains how Aurora's cluster vs. instance parameter groups work, how to tell whether a specific parameter change needs a reboot, and how to roll a change out safely -- the foundational mechanism every other workflow in this repository refers to whenever it says a setting must be changed via the parameter group rather than SQL.

## 2. Typical Symptoms

- A setting change made via the AWS Console/CLI does not appear to have taken effect.
- A previous parameter-group change is shown as 'pending-reboot' and nobody is sure whether/when it applied.

## 3. Business Impact

- A parameter-group change applied incorrectly (wrong scope, unexpected reboot, or a value that regresses performance) affects every database in the cluster/instance at once -- getting the mechanism itself right is a prerequisite for every other workflow in this repository that recommends a configuration change.

## 4. Possible Root Causes

- The change was made to the DB instance parameter group when it needed to be cluster-wide (or vice versa), so it did not apply where expected.
- The specific parameter is static (requires a reboot) and no reboot was performed after the change, so the running value has not changed even though the parameter group itself now shows the new value.
- The change was applied directly to the default parameter group rather than a custom one, which AWS does not allow to be modified -- the change silently failed to be created at all.

## 5. Investigation Strategy

1. Confirm which settings are cluster-scoped vs. instance-scoped by reviewing their context/source in pg_settings.
2. Check for any setting currently in a pending-restart state, meaning a parameter-group change has been made but not yet applied because the instance has not rebooted.
3. Confirm you are targeting a custom (non-default) parameter group, since AWS does not allow direct modification of the default one.

## 6. Prerequisites

- IAM permission to describe/modify DB cluster and instance parameter groups; a non-production cluster/parameter group to validate a new change against before applying to production.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_key_settings_and_scope.sql`](scripts/01_key_settings_and_scope.sql) -- Snapshots the settings most commonly changed operationally, including each one's context, which indicates whether it can be changed dynamically, via SIGHUP, or only at instance start.
2. [`scripts/02_pending_restart_settings.sql`](scripts/02_pending_restart_settings.sql) -- Lists every setting currently flagged as changed-in-the-parameter-group-but-not-yet-applied, the direct signal that a reboot (or failover) is needed to finish a previously started change.
3. [`scripts/03_parameter_group_change_runbook.md`](scripts/03_parameter_group_change_runbook.md) -- Guarded runbook for making an Aurora parameter-group change safely: validating on non-prod first, understanding ApplyType, and scheduling any required reboot.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora PostgreSQL uses two levels of parameter group: the DB cluster parameter group (values shared by every instance in the cluster -- most PostgreSQL settings live here) and the DB instance parameter group (writer/reader-specific overrides, used less often). Neither is edited via ALTER SYSTEM -- Aurora does not support ALTER SYSTEM for the great majority of parameters that matter operationally, and any attempt should be treated as a sign the wrong mechanism is being used, not as a workaround.

## 8. Interpretation Guide

- pending_restart = true for a setting means its parameter-group value has already changed but the running instance has not yet picked it up -- the instance needs a reboot (or, for some parameters, a failover) before the new value is actually in effect; do not assume a parameter-group change is live just because the AWS Console shows the parameter group itself updated.
- context in pg_settings ('postmaster', 'sighup', 'superuser', 'user', etc.) indicates how a setting can be changed at the PostgreSQL level, which combined with the parameter's ApplyType in describe-db-cluster-parameters tells you whether a reboot is required.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- N/A -- this is a foundational/reference workflow, not an incident-response one, though it is frequently consulted *during* an incident when another workflow's remediation calls for a configuration change.

**Short-term remediation** (hours to days):

- Apply any pending, already-approved parameter-group change during the next scheduled maintenance window rather than leaving it in pending-reboot indefinitely, since a change that is 'half-applied' (parameter group updated, instance not yet rebooted) is a common source of confusion during a later, unrelated investigation.

**Long-term engineering fix** (days to weeks):

- Maintain the cluster's parameter groups as infrastructure-as-code (not manual Console edits) so every change is reviewable, and always validate a new parameter-group value against a non-production cluster/parameter group before applying it to production.

## 10. Production Safety

- The SQL investigation here is entirely read-only. Applying a parameter-group change is an AWS control-plane action, not a SQL statement; for any parameter whose ApplyType requires a reboot, treat the reboot itself as the disruptive step and schedule it as a maintenance-window activity.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A parameter-group change is found in a pending-reboot state for longer than a routine maintenance window would explain -- escalate to confirm whether it was intentionally deferred or simply forgotten.

## 12. Related Issues

- [ssl-and-connection-security](../../security-and-access/ssl-and-connection-security/README.md)
- [audit-logging-and-iam-auth](../../security-and-access/audit-logging-and-iam-auth/README.md)
- [reindex-strategy](../reindex-strategy/README.md)
