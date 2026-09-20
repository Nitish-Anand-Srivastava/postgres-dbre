# Production Safety Model

This repository is designed to be run against **production, business-
critical Aurora PostgreSQL clusters** (order execution, ledgers, wallets,
balances). Every script and workflow follows the safety model documented
here. If a script appears to violate this model, treat that as a bug --
open an issue rather than assuming the script is safe because it exists in
the repository.

## 1. Safety classification labels

Every script header has a `SAFETY` field using one of the following
labels. Workflow `scripts/README.md` tables restate the label for each
script so it is visible without opening the file.

| Label | Meaning | Default expectation |
| --- | --- | --- |
| `READ ONLY` | Only reads catalogs/statistics views; issues no DDL/DML | Safe to run at any time, on any instance, without a change ticket |
| `LOW RISK WRITE` | Writes but is scoped, reversible, and non-locking beyond a brief catalog lock (e.g., `ANALYZE` on one named table, resetting one statistics counter) | Safe with awareness; note the target and expected duration before running |
| `ELEVATED RISK` | Takes locks that can block other sessions, can run for a non-trivial duration, or changes configuration (e.g., `CREATE INDEX CONCURRENTLY`, adjusting a runtime parameter) | Requires understanding current lock/traffic conditions first; run during a low-traffic window when possible |
| `DESTRUCTIVE` | Can irreversibly remove or rewrite data, or forcibly end sessions (e.g., `DROP`, `TRUNCATE`, batched `DELETE`, `pg_terminate_backend()`) | Requires explicit human confirmation, a named target, and (for data-removal operations) a validated backup/rollback plan; never shipped as auto-executing against a hardcoded target |

Investigation workflows are expected to be entirely `READ ONLY`, with a
small number of clearly separated remediation templates going up to
`ELEVATED RISK` or `DESTRUCTIVE` -- those are never mixed into the numbered
investigation sequence without an unmistakable label change in both the
script header and the `scripts/README.md` table.

The comprehensive HTML observability report is the deliberate diagnostic
exception: it is `LOW RISK WRITE` because it creates and populates one
session-scoped temporary table. It does not persist database objects or write
application data, but its broad catalog/statistics scan should not be treated
as equivalent to the lightweight `READ ONLY` scripts during a severe incident.

## 2. Non-negotiable rules

* **No script terminates a session** (`pg_terminate_backend()`,
  `pg_cancel_backend()`) **unless it is explicitly a remediation script**,
  labeled `DESTRUCTIVE` (terminate) or `ELEVATED RISK` (cancel), and
  requires the operator to supply the target PID after reviewing blocking
  evidence -- never a script that terminates sessions matching a query
  automatically.
* **No script runs `VACUUM FULL` automatically.** `VACUUM FULL` takes an
  `ACCESS EXCLUSIVE` lock and rewrites the entire table; it is only ever
  presented as a documented, manually-invoked remediation option with its
  locking behavior explained.
* **No script runs `ANALYZE` indiscriminately across every table** in a
  database as a default action; statistics-refresh scripts target a named
  table/set of tables the operator has already identified as relevant.
* **No script assumes superuser.** Aurora does not offer superuser; the
  most privileged role available is `rds_superuser`. Required privileges
  are documented per script (`REQUIRED PRIVILEGES` header field) and
  generally target `pg_monitor` / `pg_read_all_stats` /
  `pg_read_all_settings` for investigation scripts.
* **No script assumes a PostgreSQL feature unsupported on Aurora** (see
  `docs/aurora-postgresql/README.md`) without documenting the assumption
  in its header.
* **All potentially disruptive operations document lock level, blocking
  risk, and expected duration** in their header and in the owning
  workflow's README "Production Safety" section.
* **Common utilities (`common/scripts/`) are always read-only, require no
  parameters, and are safe to run as shipped**, on any instance, at any
  time -- they exist to answer "what am I even connected to" questions
  before an investigation starts, and must never become a dependency that
  blocks an incident workflow from being understood standalone.

## 3. Guarded defaults, not hardcoded destruction or placeholders

Where a workflow legitimately needs a write or destructive operation
(e.g., archiving old data, dropping an unused index), the script:

* Never uses a placeholder relation name (`<schema>.<table>`,
  `REPLACE_ME`, or similar) that the operator is expected to find-and-
  replace before running -- every script must execute successfully
  exactly as shipped, with no arguments and no edit step. This applies
  repository-wide, not only to `common/scripts/`.
* Derives a **safe default target** itself where one is needed (e.g. the
  single largest table in a documented, bounded candidate set) and
  documents in its header that the default can be overridden.
* Gates the destructive/write step behind a **guarded `psql`
  conditional** (`\if` / `\gset` / `\endif`): if no override is supplied
  and no safe default can be established, the script prints an
  instructional notice describing what to do next -- it never falls
  through to executing SQL against a literal or unresolved placeholder.
* Accepts an override exclusively through a `psql` variable supplied
  before invocation (`-v target_relation=...` / `\set`), referenced as
  `:'target_relation'` -- never through in-file text substitution.
* States, in its header, exactly what will happen if run (including what
  the safe default resolves to) and how to validate the target before
  running it.

See `CONTRIBUTING.md` section 2.4 for the full authoring rule and a
worked example.

## 4. Severity vs. what to run

| Incident severity | What's appropriate |
| --- | --- |
| Elevated latency, degraded but serving traffic | Full read-only investigation sequence; avoid `ELEVATED RISK` steps (e.g., new index builds) until root cause is confirmed |
| Active incident, partial outage | Read-only investigation only; any mitigation (e.g., cancelling one confirmed runaway query) requires explicit sign-off per the workflow's escalation criteria |
| Full outage / database unavailable | `incident-response/database-unavailable/` triage first; most SQL-level investigation is not possible until connectivity is restored -- lean on Performance Insights / CloudWatch / RDS events (`observability/`) |

## 5. Related reading

* `docs/permissions/README.md` -- the concrete role/grant model backing
  "no superuser assumed."
* `docs/prerequisites/README.md` -- what must be true before a workflow
  can run at all.
* `CONTRIBUTING.md` -- the SQL standards that enforce this model at
  review time (required header fields, banned patterns, review
  checklist).
