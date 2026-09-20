# Aurora PostgreSQL DBA Toolkit

Production investigation workflows, runbooks, and safe diagnostic SQL for
a Staff Database Engineer / Staff PostgreSQL DBA operating **Amazon Aurora
PostgreSQL-Compatible Edition, version 17+**, in a high-throughput,
low-latency, business-critical environment (trading, order books, wallets
and ledgers, deposits/withdrawals, real-time balances, market data, risk
and compliance, and the microservices around them).

This is **not** a random collection of SQL scripts. It is organized around
real DBA problems: **one directory = one operational problem**, with a
numbered, read-only-by-default investigation sequence you can follow start
to finish during an incident.

---

## 1. Repository purpose

Give a Staff-level DBA everything needed to go from "something is wrong"
to "here is the root cause and here are my remediation options" without
improvising SQL under incident pressure -- covering performance
troubleshooting, locking/concurrency, transaction ID management, vacuum
health, partitioning, archival, table/index health, connection
management, replication/HA, database health checks, query optimization,
storage/capacity, schema changes, incident response, security, and
observability integration (AWS Performance Insights / CloudWatch
alongside SQL-level diagnostics).

### Current repository inventory

The authoritative workflow registry (`tools/repo_builder/wf_*.py`) currently
materializes **19 operational categories**, **143 workflows**, and **555
numbered workflow artifacts**: 478 SQL files and 77 manual Markdown runbooks.
Of those, 554 are rendered by the generator and the comprehensive HTML
report SQL is preserved as one generator-registered external artifact.
Including the eight hand-authored `common/scripts/` utilities, the repository
contains **486 SQL files** and **563 numbered operational artifacts**.

## 2. Target platform

* Amazon Aurora PostgreSQL-Compatible Edition, engine version **17+**.
* Aurora writer and reader instances, cluster/reader/custom endpoints.
* Multi-AZ clusters, read replicas, connection pooling (PgBouncer /
  RDS Proxy), and failover scenarios.
* Every script and runbook is written against Aurora's actual behavior --
  see `docs/aurora-postgresql/README.md` for where that diverges from
  community PostgreSQL, and what is documented as **not** assumed
  available (superuser, arbitrary extensions, local filesystem access).

## 3. Target audience

Staff/senior Database Engineers and DBAs responsible for production
incident investigation, root cause analysis, capacity planning,
reliability, scalability, query optimization, schema lifecycle, HA/
failover readiness, transaction/concurrency troubleshooting, preventative
maintenance, automation, and observability for a mission-critical Aurora
PostgreSQL platform. Familiarity with PostgreSQL fundamentals is assumed;
Aurora-specific concepts are explained where they diverge from that
baseline.

## 4. How to navigate the repository

1. Identify the problem category from the map in section 13 below.
2. Open that category directory, then the specific workflow
   (e.g. `performance/slow-queries/`, not just `performance/`).
3. Read the workflow's `README.md` in full -- symptoms, business impact,
   root-cause tree, and escalation criteria are specific to that problem.
4. Run `scripts/` in strict numeric order, using `scripts/README.md` as
   the safety/runtime reference.
5. Use `docs/` for cross-cutting background (architecture, Aurora
   differences, methodology, safety, prerequisites, permissions,
   glossary) and `common/` for generic environment/preflight checks --
   neither is required reading to run a single workflow, but both help
   you interpret results correctly.

You should never need to search across unrelated directories to complete
one investigation.

### Running the SQL

Clone the repository and run commands from its root; the SQL has no install
step or Python dependency. Most numbered `.sql` files are terminal
diagnostics and can be run with:

```text
psql -X -v ON_ERROR_STOP=1 -f <category>/<workflow>/scripts/NN_script.sql
```

The exception is
[`observability/comprehensive-html-report/`](observability/comprehensive-html-report/README.md):
it is a broad, self-contained HTML snapshot rather than a normal terminal
diagnostic. Follow its platform-specific instructions and supply `-o
postgres_observability_report.html`. It is `LOW RISK WRITE` because it uses a
session-local temporary table; it does not persist database objects or modify
application data. The generated HTML can contain query text and operational
metadata and is ignored by Git at the documented root output path.

## 5. Investigation philosophy

Every workflow follows the same loop: **start broad, narrow to the
affected scope, correlate contributing factors, confirm root cause, then
provide remediation guidance** -- immediate mitigation, short-term
remediation, and long-term engineering fix, kept clearly separate. Some
SQL logic intentionally repeats across workflows: **duplication is
preferred over coupling unrelated incident directories together.** Full
methodology: `docs/investigation-methodology/README.md`.

## 6. Production safety model

Investigation scripts are **read-only by default**. Nothing terminates a
session, runs `VACUUM FULL`, or `ANALYZE`s every table automatically.
Nothing assumes superuser (Aurora has none) or an unconfirmed extension.
Every script is labeled `READ ONLY`, `LOW RISK WRITE`, `ELEVATED RISK`, or
`DESTRUCTIVE` in its header, and destructive operations against a specific
table always require the operator to supply a target -- never a hardcoded
production table name. Full model: `docs/production-safety/README.md`.
The comprehensive HTML report is the documented exception: it is classified
`LOW RISK WRITE` solely because it creates a session-scoped temporary table.

## 7. Required permissions

Nearly every read-only workflow needs only membership in the built-in
`pg_monitor` role (which implies `pg_read_all_stats` and
`pg_read_all_settings`) plus `CONNECT` on the target database. Elevated
workflows document their own additional requirements (e.g. table
ownership for DDL, `pg_signal_backend` for session termination
remediation) in their script headers rather than assuming broad access.
Full model, including an example role definition: `docs/permissions/README.md`.
The comprehensive HTML report additionally requires the database `TEMPORARY`
privilege; this is granted to `PUBLIC` by default but may be revoked in
hardened environments.

## 8. Required extensions

| Extension | Needed for |
| --- | --- |
| `pg_stat_statements` | Query-level performance history across most of `performance/` and `query-optimization/` |
| `pgaudit` | Optional; security/audit investigation, only if already in use |
| `pg_cron` | Optional; some `automation/` scheduling examples |

Extensions must be preloaded via the cluster parameter group's
`shared_preload_libraries` (requires a reboot) and then explicitly
`CREATE EXTENSION`-ed per database -- no script in this repository runs
`CREATE EXTENSION` automatically. Verify availability with
`common/scripts/03_installed_extensions.sql`. Details:
`docs/prerequisites/README.md`.

## 9. Aurora-specific limitations

No superuser (only `rds_superuser`, itself more limited than community
superuser); no arbitrary filesystem access; extensions restricted to
AWS's per-version allow-list; reader replication behaves as storage-level
log replay rather than traditional streaming replication (so
`pg_stat_replication` is not the right tool for reader lag -- use
`aurora_replica_status()` instead); parameter changes go through cluster/
instance parameter groups and may require a reboot or failover. Full
comparison table: `docs/aurora-postgresql/README.md`.

## 10. Recommended incident workflow

```text
1. Run common/scripts/ 01, 02, 08  -> confirm version, role, and connection target
2. Identify the symptom            -> pick a category from the map below
3. Open that workflow's README.md  -> symptoms / impact / root-cause tree
4. Run scripts/ 01..N in order     -> narrow from broad state to root cause
5. Apply the workflow's Interpretation Guide to the results
6. Choose: immediate mitigation / short-term remediation / long-term fix
7. Escalate per the workflow's Escalation Criteria if the incident
   exceeds a DBA-only fix, or if a step is flagged unsafe to run now
```

For a full outage, start at `incident-response/database-unavailable/`
instead of a performance-specific workflow -- most SQL-level diagnosis is
impossible until connectivity is restored.

## 11. How to contribute new investigations

Read `CONTRIBUTING.md` before adding or changing anything. In short: one
new directory per operational problem, both `README.md` files required
(parent + `scripts/`), sequential script numbering, the full SQL header on
every script, no placeholders, no unattended destructive statements, and
`python tools/validation/validate_repo.py` passing before a PR.

## 12. Version compatibility

This repository targets **Aurora PostgreSQL 17 and later**, using community
PostgreSQL 17 catalogs and syntax as the compatibility baseline. It is not a
generic community PostgreSQL toolkit: Aurora availability and behavior are
checked separately. Point-release validation is documented in each script's
`AURORA POSTGRESQL VERSION` header; the comprehensive HTML report is
specifically production-validated on Aurora PostgreSQL 17.7. For a newer
Aurora major version, review the relevant headers and validate in a
non-production cluster before use (see `CONTRIBUTING.md` section 2.3).

## Generated files and validation

Category and workflow READMEs, script indexes, and generator-managed numbered
artifacts come from `tools/repo_builder/`; edit those sources rather than the
rendered files. The comprehensive HTML report SQL is intentionally registered
with `generator_managed=False`, so regeneration verifies its presence without
overwriting the imported artifact. `.repo-builder-manifest.json` records each
managed path and content hash. A full build removes an obsolete path only when
it is listed in that manifest and still matches its last generated hash;
modified, untracked, and externally managed files are preserved.

```text
python tools/build_repository.py
python tools/validation/validate_repo.py
```

Run the generator twice when changing workflow sources: the second run must
leave `git diff` unchanged. CI runs the same generator/clean-diff check and the
full validator with Python 3.11.

---

## 13. Repository map (visual navigation)

```text
aurora-postgresql-dba-toolkit/
│
├── README.md                     <- you are here
├── CONTRIBUTING.md                <- workflow + SQL contribution contract
├── LICENSE
│
├── docs/                          <- cross-cutting background reading
│   ├── architecture/               Aurora cluster/storage/failover model
│   ├── aurora-postgresql/          Aurora vs. community PostgreSQL differences
│   ├── investigation-methodology/  the broad -> narrow -> RCA -> remediation loop
│   ├── production-safety/          safety classification model (READ ONLY .. DESTRUCTIVE)
│   ├── prerequisites/              network, roles, extensions needed before you start
│   ├── permissions/                the concrete role/grant model
│   └── glossary/                   terminology used throughout the repository
│
├── common/                        <- generic, read-only, parameter-free utilities
│   ├── README.md
│   ├── scripts/                    version / role / extensions / topology checks
│   └── documentation/              result-interpretation standards, Aurora function reference
│
├── archival-and-data-lifecycle/  <- Archival & Data Lifecycle
├── automation/                   <- Automation
├── concurrency-and-locking/      <- Concurrency & Locking
├── connections/                  <- Connections
├── database-health/              <- Database Health
├── disaster-recovery/            <- Disaster Recovery
├── incident-response/            <- Incident Response
├── maintenance/                  <- Maintenance
├── observability/                <- Observability
├── partitioning/                 <- Partitioning
├── performance/                  <- Performance
├── query-optimization/           <- Query Optimization
├── replication-and-ha/           <- Replication & HA
├── schema-changes/               <- Schema Changes
├── security-and-access/          <- Security & Access
├── storage-and-capacity/         <- Storage & Capacity
├── tables-and-indexes/           <- Tables & Indexes
├── transactions-and-xid/         <- Transactions & XID
└── vacuum-and-autovacuum/        <- Vacuum & Autovacuum
```

## Quick links

* [`CONTRIBUTING.md`](CONTRIBUTING.md) -- how to add or change a workflow
* [`LICENSE`](LICENSE)
* [`docs/architecture/`](docs/architecture/README.md)
* [`docs/aurora-postgresql/`](docs/aurora-postgresql/README.md)
* [`docs/investigation-methodology/`](docs/investigation-methodology/README.md)
* [`docs/production-safety/`](docs/production-safety/README.md)
* [`docs/prerequisites/`](docs/prerequisites/README.md)
* [`docs/permissions/`](docs/permissions/README.md)
* [`docs/glossary/`](docs/glossary/README.md)
* [`common/`](common/README.md)
