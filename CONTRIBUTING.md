# Contributing

This repository is a production operations toolkit for Aurora PostgreSQL,
not a general-purpose SQL snippet collection. Every addition is expected
to meet the bar of something a Staff DBA would trust during a live
incident. This document is the contract every workflow, script, and
document in this repository must satisfy, and the checklist reviewers use
to enforce it.

## 1. The structural contract

### 1.1 One directory = one operational problem

New content is organized by **operational problem** (e.g. `high-cpu`,
`replication-lag`, `xid-wraparound-risk`), never by PostgreSQL feature
(e.g. do not create a generic `locks.sql` grab-bag). If you are unsure
which existing category a new workflow belongs in, look at the root
`README.md` navigation tree and `docs/investigation-methodology/README.md`
before inventing a new top-level category.

### 1.2 Every workflow directory requires

```text
<category>/<workflow>/
├── README.md              <- problem description, symptoms, impact, RCA tree,
│                              investigation strategy, prerequisites, workflow,
│                              interpretation guide, remediation, safety,
│                              escalation criteria, related issues
└── scripts/
    ├── README.md           <- execution-order / safety / runtime table
    ├── 01_....sql
    ├── 02_....sql
    └── ...
```

Both `README.md` files are mandatory, not optional. A workflow without a
`scripts/README.md` execution-order table, or a workflow whose parent
`README.md` is missing the required sections, will fail
`tools/validation/validate_repo.py` and should not be merged.

### 1.3 Numbering is a contract, not decoration

Scripts are numbered `01_`, `02_`, ... reflecting the intended
investigation order (broad → narrow → root cause → remediation guidance),
with no gaps and no duplicate numbers. If you insert a step, renumber the
scripts after it -- do not use `01a_` or skip numbers.

### 1.4 Duplication over coupling

Prefer copying a similar query into a new workflow over creating a shared
dependency between two unrelated incident directories. A DBA reading one
workflow during an incident must not need to open a second, unrelated
workflow's directory to understand it. `common/` is the sole exception,
and only for scripts that are generic (version, permissions, topology --
see `common/README.md`), never workflow-specific, and no workflow may
require a `common/` script to function.

## 2. SQL script standards

### 2.1 Required header

Every `.sql` file must begin with a block comment containing exactly these
labeled fields, in this order:

```sql
/*
===============================================================================
SCRIPT NAME:
<filename>.sql

PURPOSE:
<one to three sentences>

AURORA POSTGRESQL VERSION:
17+ (call out specific version caveats if the script depends on one)

EXECUTION LOCATION:
<Writer instance / Any instance / Specific requirement, with justification>

SAFETY:
<READ ONLY / LOW RISK WRITE / ELEVATED RISK / DESTRUCTIVE -- see
docs/production-safety/README.md for the definition of each label>

EXPECTED IMPACT:
<what running this costs the cluster: locks, duration, resource use>

REQUIRED PRIVILEGES:
<the specific role/grant needed -- see docs/permissions/README.md>

PREREQUISITES:
<extensions, configuration, or None>

EXECUTION ORDER:
<Step NN of workflow '<category>/<workflow>'>

RELATED SCRIPTS:
<filenames, or None>

HOW TO INTERPRET RESULTS:
<what the important columns mean and how to read them>
===============================================================================
*/
```

`tools/validation/validate_repo.py` checks for the presence of every field
label above (not the prose after it) in every `.sql` file in the
repository, `common/scripts/` included.

### 2.2 Safety rules (non-negotiable)

See `docs/production-safety/README.md` for the full model. In summary:

* Investigation scripts are `READ ONLY` by default.
* No script terminates or cancels another session unless it is explicitly
  labeled `ELEVATED RISK` / `DESTRUCTIVE` and requires the operator to
  supply the target after reviewing evidence.
* No script runs `VACUUM FULL`, or `ANALYZE` across every table in a
  database, automatically.
* No script assumes superuser (Aurora has none) or an extension/feature
  not confirmed available on Aurora PostgreSQL 17+.
* Destructive or write operations against a specific table must never
  rely on a placeholder relation name the operator is expected to edit in
  before running (e.g. `<schema>.<table>`, `REPLACE_ME`) -- see section
  2.4. Every script, including one whose operation is inherently
  target-specific, must execute successfully exactly as shipped.
* `common/scripts/` is held to a stricter bar still: every script there
  must be `READ ONLY`, take no parameters, and be safe to run exactly as
  shipped.

### 2.3 Catalog and compatibility checklist (verify before submitting)

1. Every catalog/view/function referenced exists in PostgreSQL 17.
2. Every catalog/view/function referenced is available on Aurora
   PostgreSQL (cross-check `docs/aurora-postgresql/README.md` -- do not
   assume upstream behavior for `pg_stat_replication`-style views without
   verifying).
3. No deprecated syntax (check against the PostgreSQL 17 release notes if
   unsure).
4. NULLs are handled defensively (e.g., `NULLS LAST` in `ORDER BY` on
   potentially-null timing/lag columns; avoid division by a column that
   can be zero without a `NULLIF` guard).
5. The script does not assume superuser or an unconfirmed extension.
6. The script is executable independently -- it does not `\i` or
   otherwise require another script to have run first, unless it is
   explicitly a numbered continuation within the same `scripts/` directory
   (in which case that dependency is stated in `RELATED SCRIPTS`).

### 2.4 No placeholders -- guarded defaults instead

Do not commit scripts containing `REPLACE_ME`, `TODO`, `FIXME`,
`PLACEHOLDER`, `TBD`, `Lorem ipsum`, or similar unfinished markers. This
also prohibits **placeholder relation names** of any form --
`<schema>.<table>`, `<table_name>`, `your_table_here`, `target_table`, and
the like are not an acceptable substitute for `REPLACE_ME`. Per
`docs/production-safety/README.md`, every script in this repository --
including one whose operation is inherently target-specific (archiving,
partitioning migration, a remediation script) -- must execute
successfully, as shipped, with no arguments and no find-and-replace step.

When a script needs a specific table/schema/threshold to act on, it must
not depend on the operator editing a placeholder into the SQL text.
Instead:

* Have the script derive a **safe default target** itself (e.g. the
  single largest table in a documented, bounded candidate set, computed
  by a query), and state in the header and in-script comments that this
  default can be overridden.
* Gate any target-specific or precondition-dependent step behind a
  **guarded `psql` conditional** (`\if` / `\gset` / `\endif`), so that
  when no override is supplied and no safe default can be established
  (for example, a required extension is not installed), the script
  prints an explicit instructional notice explaining what to do and why
  it did not proceed -- it must never fall through to executing SQL
  against an unresolved or literal placeholder relation name.
* Accept an override exclusively through a `psql` variable set before
  invocation (`-v target_relation=...` or `\set`), referenced in the
  script as `:'target_relation'` -- never through in-file text
  substitution.

See `tables-and-indexes/table-bloat/scripts/02_exact_bloat_pgstattuple.sql`
for the pattern: it auto-selects a bounded default candidate relation
instead of requiring a placeholder, and emits an instructional notice
(rather than executing against anything unresolved) when its
prerequisite extension is not installed.

## 3. Documentation standards

### 3.1 Parent `README.md` required sections

Every workflow parent `README.md` must contain all twelve sections, in
order: Problem Description, Typical Symptoms, Business Impact, Possible
Root Causes, Investigation Strategy, Prerequisites, Investigation
Workflow, Interpretation Guide, Remediation Options (Immediate /
Short-term / Long-term), Production Safety, Escalation Criteria, Related
Issues.

### 3.2 `scripts/README.md` required content

A table of Order / Script / Purpose / Safety / Expected Runtime for every
script in the directory, plus sections covering execution order, required
permissions, expected output, when to stop and escalate, and which
scripts (if any) should not be run during severe incidents.

### 3.3 Markdown links

Prefer relative links between related workflows/docs
(e.g. `[replication-and-ha](../../replication-and-ha/)`). Verify links
resolve to an existing path -- `tools/validation/validate_repo.py` checks
this on a best-effort basis.

## 4. Ownership boundaries

To keep concurrent contributions conflict-free:

* `README.md`, `CONTRIBUTING.md`, `LICENSE`, `.gitignore`, `docs/**`,
  `common/**`, and `tools/validation/**` are repository-foundation content
  maintained independently of the generated operational category
  directories.
* Category workflow directories (`performance/`, `concurrency-and-
  locking/`, `vacuum-and-autovacuum/`, etc.) are generated from
  `tools/repo_builder/**`. Change the workflow registry or renderer first,
  then run `python tools/build_repository.py`; do not hand-edit generated
  category files. A script explicitly registered with
  `generator_managed=False` is an authoritative checked-in external artifact
  and is preserved by the generator.

## 5. Before opening a pull request

1. Run `python tools/build_repository.py` from the repository root, then
   confirm `git diff` contains only the intended generated changes. Run the
   generator a second time and confirm it produces no further diff.
2. Run `python tools/validation/validate_repo.py` and resolve every reported
   error (warnings should be reviewed but do not necessarily block a PR if
   justified in the PR description).
3. Re-read the header of every new/changed `.sql` file against section 2
   above.
4. Confirm every new workflow directory has both required `README.md`
   files and that scripts are sequentially numbered with no gaps.
5. Confirm no destructive statement is executable "as shipped" without an
   operator supplying a target.

## 6. Style

* Directories: `kebab-case`.
* Scripts: `NN_snake_case_description.sql` (or `.md` for a numbered
  guidance step that is documentation rather than a query).
* SQL keywords upper-case; identifiers lower-case; two-space or
  four-space indentation consistent within a file.
* Prefer explicit column lists over `SELECT *` except in scripts whose
  entire purpose is a full-row dump of a small, well-understood catalog
  view (and even then, only when every column is relevant).
