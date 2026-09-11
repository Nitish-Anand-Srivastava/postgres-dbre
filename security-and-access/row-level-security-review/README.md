# Row-Level Security Coverage Review

**Category:** Security and Access | **Workflow:** `security-and-access/row-level-security-review`

## 1. Problem Description

Reviews which tables actually have row-level security (RLS) enabled, what their policies allow, and which roles can bypass RLS entirely -- the control that decides whether a single compromised or over-broad application role can read every customer's wallet balance and ledger history, or only the rows it is entitled to.

## 2. Typical Symptoms

- A security or compliance review asks how per-customer data isolation is enforced inside the database itself, not just in the application's query layer.
- A support/reporting role that was only meant to see one customer's records is found returning rows for every customer.
- RLS was enabled on a sensitive table at some point, but nobody can currently state which policies apply or whether the application role is exempt from them.

## 3. Business Impact

- On an exchange, wallet balances, deposit/withdrawal history, and the ledger are per-customer data: if isolation is enforced only in application code, any SQL path that bypasses that code (an ad hoc analyst query, a reporting tool, a compromised service credential) reads everything, which is simultaneously a customer-privacy breach, an insider-risk exposure, and a reportable compliance incident.
- RLS enabled but silently bypassed (owner tables without FORCE, or a role with rolbypassrls) is arguably worse than no RLS, because the control shows as 'in place' on an audit checklist while providing no actual isolation.

## 4. Possible Root Causes

- RLS was enabled on a table (`relrowsecurity`) but the application connects as the table's owner, and owners are exempt from their own table's policies unless `FORCE ROW LEVEL SECURITY` is also set.
- A role was granted the BYPASSRLS attribute for a one-off backfill or migration and the attribute was never removed.
- Policies exist but are written `USING (true)` for convenience during rollout, so they satisfy the 'policy exists' checkbox without restricting anything.
- New sensitive tables were added by a later migration and nobody extended the RLS design to cover them, so isolation is inconsistent across tables that hold equally sensitive data.

## 5. Investigation Strategy

1. Inventory every table in non-system schemas with its RLS enabled/forced flags and its policy count, so tables holding sensitive data with zero policies stand out immediately.
2. Read the actual policy definitions (command, roles, USING and WITH CHECK expressions) rather than trusting that a non-zero policy count means meaningful restriction.
3. Identify every role that can bypass RLS outright -- BYPASSRLS holders and table owners on tables without FORCE -- since each one is a complete exemption from whatever the policies say.
4. Drill into one specific high-sensitivity table (wallets by default) end to end: RLS flags, policies, and the object-level grants that determine who reaches the table at all.

## 6. Prerequisites

- Read access to pg_class/pg_policy/pg_policies/pg_roles (available to any authenticated role; `pg_policies` shows policies on tables the current role can see).
- A documented statement of which tables are expected to be per-customer isolated -- without it, this workflow can report the current posture but not whether that posture is correct.

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

1. [`scripts/01_rls_status_by_table.sql`](scripts/01_rls_status_by_table.sql) -- Inventories every table in a non-system schema with its row-level-security flags, policy count, owner, and size, so sensitive tables with no coverage surface first.
2. [`scripts/02_policy_definitions_and_bypass_roles.sql`](scripts/02_policy_definitions_and_bypass_roles.sql) -- Prints the actual USING/WITH CHECK expression of every policy in the database, then lists every role that bypasses RLS entirely.
3. [`scripts/03_rls_coverage_for_sensitive_table.sql`](scripts/03_rls_coverage_for_sensitive_table.sql) -- End-to-end RLS review of one specific high-sensitivity table -- flags, policies, and object-level grants -- defaulting to public.wallets and guarded so it prints a notice rather than failing if that table does not exist.
4. [`scripts/04_enabling_row_level_security.md`](scripts/04_enabling_row_level_security.md) -- Guarded runbook for enabling RLS, adding a tenant-isolation policy, forcing it for the table owner, and removing a BYPASSRLS attribute -- with lock behavior and rollback for each step.

## Aurora PostgreSQL Notes

Differences from self-managed / standard PostgreSQL that matter for this workflow:

- Aurora PostgreSQL enforces RLS exactly as community PostgreSQL 17 does -- the difference is who can bypass it: there is no OS-level superuser on Aurora, but members of `rds_superuser` and any role with the BYPASSRLS attribute still read past every policy, so 'no superuser exists on Aurora' is not an argument that the isolation model is safe.
- RLS is evaluated on readers exactly as on the writer, so routing analytics traffic to an Aurora reader does not change which rows a role can see -- a reporting role that is over-permissive on the writer is equally over-permissive on every reader in the cluster.

## 8. Interpretation Guide

- `rls_enabled = false` on a table holding per-customer financial data is the headline finding -- no policy in the database restricts any role's row visibility on that table; isolation, if any, exists only in application code.
- `rls_enabled = true` with `rls_forced_for_owner = false` means the table owner sees and modifies every row regardless of policy. If the application connects as the owner (a very common pattern after a migration tool created the tables), RLS is effectively inert for the application's own traffic.
- A policy with a `qual` of `true` (or no `qual` at all for a permissive SELECT policy) restricts nothing; count it as absent, not as coverage.
- Any role with `rolbypassrls = true` is exempt from every policy on every table -- treat each one as a standing exception that needs a written justification, and expect that list to be empty or near-empty in steady state.
- `policy_count > 0` with `cmd` values covering only SELECT means INSERT/UPDATE/DELETE paths are unrestricted -- a role that can write can then write rows attributed to another customer even though it cannot read them.

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

- If an active incident involves a role reading rows it should not, determine from this workflow's output whether the role is exempt (BYPASSRLS or owner-without-FORCE) or simply covered by a permissive policy -- that distinction decides whether containment means revoking an attribute or fixing a policy, and they are not interchangeable.

**Short-term remediation** (hours to days):

- Remove the BYPASSRLS attribute from any role that does not have a written, current justification for it (guarded runbook, script 04).
- Add `FORCE ROW LEVEL SECURITY` on tables where RLS is enabled but the application connects as the owner, so the owner is subject to its own policies.
- Replace any `USING (true)` policy with a real predicate tied to the session's tenant/customer context.

**Long-term engineering fix** (days to weeks):

- Make RLS coverage a standing part of the schema-change review: any new table holding per-customer wallet/ledger/order data ships with its policies in the same migration that creates it, not as a follow-up.
- Stop connecting the application as the table owner -- separate the migration/owner role from the runtime application role, so ownership exemptions stop being a silent bypass of the isolation model.
- Re-run this review on a scheduled cadence (see maintenance/routine-maintenance-checklist) so tables added between audits do not accumulate uncovered.

## 10. Production Safety

- Scripts 01-03 are read-only catalog queries and are safe at any time, including during an incident.
- Script 04 is a guarded manual runbook: enabling RLS or altering policies takes a brief ACCESS EXCLUSIVE lock on the table and changes which rows every query returns -- an incorrect policy is indistinguishable from data loss from the application's point of view, so it is never executed automatically.

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

- A table holding customer balances, ledger entries, or withdrawal records is found with RLS disabled and no compensating documented control -- escalate to the security/compliance owner the same day.
- A login-capable application or human role is found with `rolbypassrls = true` and no documented justification -- escalate immediately; this is a complete exemption from the isolation model, not a tuning detail.
- Policy definitions found in the database do not match the isolation model the compliance documentation claims is in place -- escalate before changing anything, since the documentation may be describing an intended design that was never implemented.

## 12. Related Issues

- [role-and-privilege-audit](../role-and-privilege-audit/README.md)
- [public-schema-exposure](../public-schema-exposure/README.md)
- [access-anomaly-investigation](../access-anomaly-investigation/README.md)
