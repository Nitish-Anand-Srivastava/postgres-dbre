# Prerequisites

What must be true before you can run the workflows in this repository
against an Aurora PostgreSQL cluster. Check this before an incident, not
during one.

## 1. Network access

* A route to the cluster's writer and reader endpoints (VPC access,
  VPN/bastion/Session Manager, or equivalent), on the PostgreSQL port
  (default `5432`).
* A `psql` client (or equivalent SQL client) at a version that can talk to
  PostgreSQL 17 -- `psql` 12+ works over the wire protocol, but using a
  matching-or-newer client avoids surprises with `\d`-style meta-commands.
* If your organization requires IAM database authentication, a valid,
  freshly-generated auth token (they expire, typically after 15 minutes)
  and the `rds_iam` role granted to your database user.

## 2. Database role

You need a database role that exists in the target cluster with, at
minimum, the privileges in `docs/permissions/README.md`. This repository
assumes an investigative role along these lines already exists in your
environment (created and managed outside this repository, typically via
your existing IAM/role-provisioning process):

* `CONNECT` on the databases you need to investigate.
* Membership in `pg_monitor` (which implies `pg_read_all_stats` and
  `pg_read_all_settings`) for the vast majority of read-only workflows.
* `USAGE` on `public` (or the relevant application schema) if a script
  needs to inspect table/index definitions your role does not otherwise
  see.

Elevated workflows (DDL, remediation) document additional requirements in
their own script headers -- do not grant elevated privileges broadly "just
in case."

## 3. Extensions

| Extension | Required for | Notes |
| --- | --- | --- |
| `pg_stat_statements` | Query-level performance history (`performance/`, `query-optimization/`) | Must be listed in the cluster parameter group's `shared_preload_libraries` **and** `CREATE EXTENSION pg_stat_statements;` run once per database. A cluster parameter group change requires a reboot to take effect. |
| `pgaudit` | Security/audit investigation | Optional; only needed if your environment already uses it for audit logging. |
| `pg_cron` | Some `automation/` scheduling examples | Optional; Aurora PostgreSQL supports `pg_cron` but it must be enabled via parameter group and only runs scheduled jobs inside the database, not host cron. |

This repository never runs `CREATE EXTENSION` as an unattended step inside
an investigation script -- confirm extension availability with
`common/scripts/03_installed_extensions.sql` before relying on a workflow
that needs one. If an extension you need is not installed, that is itself
an investigation finding (documented as a prerequisite gap), not something
a diagnostic script should silently fix.

## 4. Aurora configuration awareness

* Know whether Performance Insights and Enhanced Monitoring are enabled
  for the cluster -- several `observability/` and `database-health/`
  workflows lean on them for information SQL cannot provide (host-level
  CPU, memory, disk I/O).
* Know your cluster's parameter group(s) (cluster-level and per-instance)
  and who owns changing them -- several workflows recommend a parameter
  change as a long-term fix, which is a change-managed action, not
  something the workflow performs for you.
* Know your topology: writer identifier, reader identifiers, and whether
  you are using a reader endpoint, custom endpoint, or pinned instance
  endpoints for specific workloads.

## 5. Before you start an investigation

Run, in order, as a sanity check (all read-only, no parameters required):

1. `common/scripts/01_postgres_and_aurora_version.sql`
2. `common/scripts/02_current_role_and_privileges.sql`
3. `common/scripts/05_instance_recovery_and_role_status.sql`

If any of these fail or return unexpected results (wrong version, missing
expected role membership, unclear writer/reader status), resolve that
before trusting the output of any incident-specific workflow.

## 6. Related reading

* `docs/permissions/README.md` -- the full role/grant model.
* `docs/production-safety/README.md` -- why this repository never assumes
  superuser or arbitrary extension availability.
* `common/README.md` -- the full common utilities inventory referenced
  above.
