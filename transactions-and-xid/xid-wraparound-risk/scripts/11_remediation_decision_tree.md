# 11_remediation_decision_tree

> **This is a manual remediation/runbook template, not an automatic script.**
> It contains guarded, potentially disruptive steps. Read it fully, adapt the
> guard variables, and execute steps interactively with a second engineer
> present before running anything against production.

| Field | Value |
|---|---|
| Script name | `11_remediation_decision_tree.md` |
| Purpose | Manual remediation decision tree and safe commands for resolving an active or imminent wraparound risk once the blocker is identified. |
| Aurora PostgreSQL version | Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise) |
| Execution location | Writer instance only (the query reads/writes state that only exists or is meaningful on the writer) |
| Safety | GUARDED -- MANUAL EXECUTION ONLY, SEVERITY-DEPENDENT (some branches are routine, others are incident-level) |
| Expected impact | Varies by branch -- from none (read-only confirmation) to a full-outage recovery procedure. |
| Required privileges | Varies by branch; branch 4 requires a superuser-equivalent (rds_superuser on Aurora) role. |
| Prerequisites | Scripts 01-10 completed and a specific blocker or critical age identified. |
| Execution order | Step 11 of workflow `transactions-and-xid/xid-wraparound-risk` |
| Related scripts | ../../vacuum-and-autovacuum/emergency-autovacuum/README.md |

## How to interpret / use this runbook

This file documents decisions, not automatic actions -- read the matching scenario fully, confirm you are in it, and execute only the specific command it prescribes.

---

## Decision tree

1. **A specific long-running transaction or prepared transaction is the blocker (scripts 06/07 found one, and the oldest table's autovacuum worker is NOT running or is stuck):**
   - Contact the owning team first if the session/transaction is identifiable.
   - Prepared transaction: `COMMIT PREPARED 'gid';` or `ROLLBACK PREPARED 'gid';` as appropriate -- confirm with the owning distributed-transaction coordinator which outcome is correct; guessing wrong can leave a partial multi-database commit inconsistent.
   - Ordinary session: `SELECT pg_terminate_backend(<pid>);` after documented approval.

2. **An inactive, abandoned replication slot is pinning the horizon (script 08):**
   - Confirm the consuming application/service is genuinely gone, not just temporarily disconnected.
   - `SELECT pg_drop_replication_slot('slot_name');`
   - This is irreversible for that slot's consumer -- it will need to re-sync from scratch if it ever reconnects.

3. **No blocker found, but a specific table's age is critically high and autovacuum has not caught up (scripts 02/04):**
   ```sql
   -- Safe to run concurrently with production traffic. Does not take an
   -- exclusive lock and does not rewrite the table.
   VACUUM (VERBOSE, ANALYZE) schema_name.table_name;
   ```
   - Monitor progress with pg_stat_progress_vacuum (script 04) while it runs.
   - Do NOT use `VACUUM FULL` for this purpose -- it is not required to advance relfrozenxid and adds an unnecessary AccessExclusiveLock and full table rewrite.

4. **Cluster has already entered wraparound-protection mode (refusing new transactions):**
   - This is a full outage. Follow your organization's major-incident process immediately.
   - Connect as a superuser-equivalent role, identify the offending table(s) via script 02 (single-user/limited connectivity may still be possible for monitoring roles depending on how deep into the condition the cluster is), and issue a manual `VACUUM (FREEZE)` against them.
   - Engage AWS Support in parallel -- they can advise on Aurora-specific recovery options and should be aware of the incident regardless.
