# Common

Reusable, read-only environment and preflight utilities shared across the
repository. **No issue workflow depends on anything in this directory** --
every `performance/`, `concurrency-and-locking/`, `vacuum-and-autovacuum/`
(etc.) workflow is self-contained and understandable on its own, per
`CONTRIBUTING.md`'s "duplication over coupling" rule. `common/` exists
purely for operator convenience: quick answers to "what am I connected to,
what can I see, is this even Aurora" before diving into a specific
incident workflow.

## What lives here

```text
common/
├── README.md            <- this file
├── scripts/              <- safe, read-only, parameter-free SQL utilities
│   ├── README.md          (execution order / safety table)
│   ├── 01_postgres_and_aurora_version.sql
│   ├── 02_current_role_and_privileges.sql
│   ├── 03_installed_extensions.sql
│   ├── 04_database_and_cluster_inventory.sql
│   ├── 05_instance_recovery_and_role_status.sql
│   ├── 06_aurora_replica_topology_and_lag.sql
│   ├── 07_key_monitoring_settings.sql
│   └── 08_environment_summary.sql
└── documentation/        <- reference material supporting the scripts above
    ├── result-interpretation-standards.md
    └── aurora-function-reference.md
```

## Script inventory

| Script | Purpose | Safety |
| --- | --- | --- |
| `01_postgres_and_aurora_version.sql` | PostgreSQL + Aurora engine version | READ ONLY |
| `02_current_role_and_privileges.sql` | Current role attributes and predefined-role membership | READ ONLY |
| `03_installed_extensions.sql` | Installed vs. available-but-not-installed extensions | READ ONLY |
| `04_database_and_cluster_inventory.sql` | Every non-template database, size, connection limit | READ ONLY |
| `05_instance_recovery_and_role_status.sql` | Writer vs. reader status of the connected instance | READ ONLY |
| `06_aurora_replica_topology_and_lag.sql` | Every cluster instance and current replica lag | READ ONLY |
| `07_key_monitoring_settings.sql` | Key parameters other workflows depend on | READ ONLY |
| `08_environment_summary.sql` | One-row "where and who am I" summary | READ ONLY |

Full execution-order and safety details: `scripts/README.md`.

## Design rules for this directory

* **Every script here is `READ ONLY`, requires no parameters, and is safe
  to execute exactly as shipped** -- no `psql` variables, no
  "replace this before running" placeholders, no destructive statements
  of any kind. This is a stricter bar than issue workflows, which may
  legitimately ship parameterized remediation templates.
* **No script here assumes anything beyond `CONNECT`** on the target
  database (see each script's `REQUIRED PRIVILEGES` header).
* **Duplication is acceptable, dependency is not.** If a workflow needs a
  version check, it may copy the relevant query inline rather than
  `\include`-ing a common script, so the workflow remains understandable
  in isolation during an incident.
* **This directory grows conservatively.** A script belongs here only if
  it answers a generic "what is this cluster / what can I see" question
  useful across nearly every workflow -- problem-specific diagnostics
  belong in the relevant category directory (e.g. `performance/`,
  `vacuum-and-autovacuum/`), not here.

## When to use `common/` during an incident

Run the relevant `common/scripts/` entries once, at the start of a new
session against an unfamiliar cluster or after reconnecting following a
failover, to confirm:

1. You are connected to the version and cluster you expect
   (`01`, `08`).
2. Your role can actually see what the workflow you are about to run
   expects it to see (`02`).
3. Any extension the workflow depends on is installed
   (`03`).
4. You know whether you are on the writer or a reader, and what the
   cluster topology looks like right now
   (`05`, `06`).

Then proceed to the specific issue workflow's own `README.md` and
`scripts/`.

## Related reading

* `docs/prerequisites/README.md` -- prerequisites these scripts help
  verify.
* `docs/permissions/README.md` -- the full privilege model.
* `docs/production-safety/README.md` -- the safety classification system
  these scripts are held to.
