# Permissions

The concrete privilege model referenced by `docs/prerequisites/README.md`
and by every script's `REQUIRED PRIVILEGES` header field. Aurora
PostgreSQL has no superuser; this document maps "what a script needs" to
"what role attribute grants it," using Aurora/RDS's built-in predefined
roles wherever possible instead of broad, one-off `GRANT` statements.

## 1. Aurora's privileged roles

| Role | What it can do | Notes |
| --- | --- | --- |
| `rds_superuser` | The most privileged role available on RDS/Aurora PostgreSQL; can create roles, manage most extensions on the allow-list, and perform administrative tasks that do not require host/OS access | Not equivalent to community PostgreSQL `superuser`; still cannot access the filesystem, load arbitrary shared libraries, or bypass Aurora's storage layer |
| `rds_replication` | Manage physical replication slots and related replication objects | Needed for some `replication-and-ha/` investigations that inspect slots |
| `pg_monitor` | Built-in PostgreSQL predefined role; grants `pg_read_all_stats`, `pg_read_all_settings`, and `pg_stat_scan_tables` | The role the overwhelming majority of investigation scripts in this repository require -- see below |
| `pg_read_all_stats` | Read all rows in statistics views/functions, including ones that otherwise hide rows belonging to other roles (e.g., full visibility into `pg_stat_activity.query`) | Subset of `pg_monitor` |
| `pg_read_all_settings` | Read all `pg_settings` values, including ones normally hidden from non-superusers | Subset of `pg_monitor` |
| `pg_signal_backend` | Allows calling `pg_cancel_backend()` / `pg_terminate_backend()` against other users' sessions (subject to further restriction against superuser-owned backends) | Only required by explicitly `ELEVATED RISK` / `DESTRUCTIVE` remediation scripts, never by investigation scripts |

## 2. Recommended investigative role

This is the role every `READ ONLY` script in this repository is written
against. Provisioning it is outside the scope of this repository (it is
an IAM/role-management concern for your environment), but for reference,
the equivalent SQL is:

```sql
-- Illustrative only -- provision through your standard role-management
-- process, not by running this ad hoc against production.
CREATE ROLE dba_investigator WITH LOGIN;
GRANT pg_monitor TO dba_investigator;
GRANT CONNECT ON DATABASE <target_database> TO dba_investigator;
GRANT USAGE ON SCHEMA public TO dba_investigator;
```

This role can run every script whose header states
`REQUIRED PRIVILEGES: pg_monitor (or pg_read_all_stats), CONNECT`. It
cannot run DDL, cannot terminate sessions, and cannot see column-level
data in application tables it has not separately been granted `SELECT` on
(statistics views expose query text and aggregate metrics, not table
contents).

The comprehensive HTML report is a documented exception because it creates a
session-scoped temporary table. It also requires `TEMPORARY` on the target
database. PostgreSQL grants that privilege to `PUBLIC` by default, but a
hardened environment may revoke it; grant it only on the database where the
report must run.

## 3. Elevated / remediation privileges

Documented per-script, only when needed, and never bundled into the
investigative role above:

* **Schema changes** (`schema-changes/`) -- typically require table
  ownership or a role with `CREATE` on the schema; `CREATE INDEX
  CONCURRENTLY` additionally requires that the operation not run inside an
  explicit transaction block.
* **Session termination** (`ELEVATED RISK` / `DESTRUCTIVE` remediation
  scripts) -- require `pg_signal_backend`, and Aurora further restricts
  signaling backends owned by `rds_superuser`.
* **Vacuum-related remediation** -- table owner or a role with sufficient
  privilege on the target table; no special role is required beyond that
  for `VACUUM` (unlike `ANALYZE`, `VACUUM` cannot be run by just any
  role with `SELECT`).

## 4. Principle applied throughout this repository

> Grant the least privilege that lets an investigation complete. Treat any
> script that asks for more than `pg_monitor` + `CONNECT` as a signal to
> re-read its header before running it, and treat "I don't have
> permission to run this script" during an investigation as a
> prerequisites gap to fix outside of the incident, not a reason to grant
> broad ad hoc privileges under time pressure.

## 5. Related reading

* `docs/prerequisites/README.md` -- what to verify before starting.
* `docs/production-safety/README.md` -- the safety classification that
  determines which privilege tier a script needs.
* `common/scripts/02_current_role_and_privileges.sql` -- a read-only
  script that reports exactly which of the roles above your current
  session role holds.
