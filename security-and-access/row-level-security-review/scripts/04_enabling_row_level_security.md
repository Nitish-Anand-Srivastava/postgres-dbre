# 04_enabling_row_level_security

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `04_enabling_row_level_security.md` |
| Purpose | Guarded runbook for enabling RLS, adding a tenant-isolation policy, forcing it for the table owner, and removing a BYPASSRLS attribute -- with lock behavior and rollback for each step. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity |
| Safety | GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement) |
| Expected impact | Each statement takes a brief ACCESS EXCLUSIVE lock (milliseconds of catalog work, but it queues behind and then blocks concurrent access on the table). Once enabled, every query against the table returns a restricted row set -- an incorrect policy presents to the application as missing data. |
| Required privileges | Table owner, or a role granted the `MAINTAIN` privilege on the table (PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants additionally require the privileges needed for the specific DDL statement (e.g. ownership to ALTER TABLE). Removing a BYPASSRLS attribute additionally requires CREATEROLE or rds_superuser membership. |
| Prerequisites | Scripts 01-03 completed for the target table; the tenant-identity column and session-context mechanism confirmed with the owning application team; the sequence rehearsed on a non-production clone. |
| Execution order | Step 04 of workflow `security-and-access/row-level-security-review` |
| Related scripts | 03_rls_coverage_for_sensitive_table.sql |

## How to interpret / use this runbook

Run the steps in order (policy, enable, force, then attribute cleanup) and verify with script 03 after each one. If the application begins returning empty result sets, the correct immediate action is the Step 2 rollback (`DISABLE ROW LEVEL SECURITY`), not editing the policy under time pressure.

---

## Before you run anything here

1. Complete scripts 01-03 and write down, for the target table, the current `rls_enabled` / `rls_forced_for_owner` values, the existing policy list, and the role the application actually connects as.
2. Confirm with the owning application team which column carries the tenant/customer identity and how the session communicates it (a `SET` of a custom GUC per request, or a per-customer role). A policy written against the wrong column silently returns the wrong rows.
3. Test the whole sequence on a non-production clone with production-like traffic first. An over-restrictive policy presents to the application as missing data, and on a trading platform missing wallet rows is an availability incident.

## Lock behavior

`ALTER TABLE ... ENABLE ROW LEVEL SECURITY`, `... FORCE ROW LEVEL SECURITY`, and `CREATE POLICY` each take a brief `ACCESS EXCLUSIVE` lock on the table. The statements themselves are catalog-only and complete in milliseconds, but acquiring that lock behind a long-running transaction queues every subsequent query on the table behind it. Always set a short `lock_timeout` first and retry rather than waiting:

```sql
SET lock_timeout = '3s';
```

## Step 1 -- add the policy while RLS is still disabled

Creating the policy first means it is already in place the instant RLS is switched on, rather than leaving a window in which RLS is enabled with no policy (which denies all rows to non-owners):

```sql
CREATE POLICY wallets_tenant_isolation ON public.wallets
    FOR ALL
    TO app_readwrite
    USING (customer_id = current_setting('app.current_customer_id', true)::bigint)
    WITH CHECK (customer_id = current_setting('app.current_customer_id', true)::bigint);
```

The `true` second argument to `current_setting` makes it return NULL instead of erroring when the application has not set the GUC -- with the comparison above, an unset GUC yields NULL and therefore no rows, which fails closed. Verify that is the behavior you want before deploying; failing closed is correct for wallet data but will break any batch job that legitimately reads across customers.

Rollback: `DROP POLICY wallets_tenant_isolation ON public.wallets;`

## Step 2 -- enable RLS

```sql
ALTER TABLE public.wallets ENABLE ROW LEVEL SECURITY;
```

Rollback: `ALTER TABLE public.wallets DISABLE ROW LEVEL SECURITY;` -- this restores unrestricted visibility immediately and is the correct emergency action if the application starts returning empty result sets after Step 2.

## Step 3 -- force RLS for the owner (only if the application connects as the owner)

```sql
ALTER TABLE public.wallets FORCE ROW LEVEL SECURITY;
```

This is the step that actually closes the ownership bypass, and it is also the step most likely to break a migration tool or maintenance job that legitimately needs to see all rows. Confirm every such job either connects as a different role or has its own policy before running it.

Rollback: `ALTER TABLE public.wallets NO FORCE ROW LEVEL SECURITY;`

## Step 4 -- remove an unjustified BYPASSRLS attribute

```sql
ALTER ROLE legacy_backfill_svc NOBYPASSRLS;
```

Rollback: `ALTER ROLE legacy_backfill_svc BYPASSRLS;`. Removing the attribute takes effect for that role's *new* transactions; an in-flight session keeps its current behavior for the remainder of its transaction, so re-run script 02 after the role's sessions have cycled to confirm.

## Do NOT

- Do NOT enable RLS on a table before its policy exists unless you intend an immediate deny-all for non-owners.
- Do NOT write `USING (true)` as a temporary measure to get the change deployed -- it satisfies the audit checkbox while providing no isolation, which is the exact failure mode this workflow exists to find.
- Do NOT run any step here without `lock_timeout` set, on a table that is in the hot path of order placement or settlement.
