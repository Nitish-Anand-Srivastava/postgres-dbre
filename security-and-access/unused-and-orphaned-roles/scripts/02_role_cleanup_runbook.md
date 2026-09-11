# 02_role_cleanup_runbook

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `02_role_cleanup_runbook.md` |
| Purpose | Guarded, manual runbook for reassigning ownership away from and then dropping a role confirmed abandoned by script 01 and by cross-referencing your service/employee inventory. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Varies by step -- read each step's own warning before executing it. |
| Required privileges | Membership in a role with CREATEROLE, or rds_superuser, to REASSIGN OWNED / DROP OWNED / DROP ROLE. |
| Prerequisites | Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained. |
| Execution order | Step 02 of workflow `security-and-access/unused-and-orphaned-roles` |
| Related scripts | 01_candidate_roles_by_activity_and_ownership.sql |

## How to interpret / use this runbook

Follow the three steps in order, confirming the outcome of each before moving to the next. A role that resists Step 3 after Steps 1-2 have run cleanly still has a dependency you have not found yet -- do not force it.

---

## Before you run anything here

1. Confirm the candidate role from `01_candidate_roles_by_activity_and_ownership.sql` against your organization's current service/employee inventory -- a zero connection count on this snapshot does not prove the role is never used (e.g. a monthly batch job).
2. Get a second engineer to independently confirm the same conclusion before proceeding -- this is destructive with respect to the role's identity and any grants attached to it.

## Step 1 -- reassign ownership (only if objects_owned > 0)

Replace `legacy_reporting_svc` below with the actual confirmed-abandoned role name, and `app_readonly` with the current role that should inherit ownership of whatever it owned:

```sql
REASSIGN OWNED BY legacy_reporting_svc TO app_readonly;
```

## Step 2 -- drop any remaining grants/dependencies owned by the role

```sql
DROP OWNED BY legacy_reporting_svc;
```

This revokes any privileges the role was separately granted (as opposed to objects it owned, already handled in Step 1) and removes any default-privilege entries associated with it.

## Step 3 -- drop the role

```sql
DROP ROLE legacy_reporting_svc;
```

This will fail with an explicit dependency error if Steps 1-2 missed something -- treat that failure as useful information (something still depends on this role) and investigate it rather than forcing the drop through.

## Do NOT

- Do NOT run `DROP ROLE` directly without Steps 1-2 on a role that owns any object -- it will simply fail, but repeatedly attempting workarounds without understanding why is how ownership gets reassigned to the wrong place under time pressure.
- Do NOT drop a role solely because `current_connections` was zero on one snapshot -- re-run script 01 at a different time of day/week first if the role's expected usage pattern is infrequent.
