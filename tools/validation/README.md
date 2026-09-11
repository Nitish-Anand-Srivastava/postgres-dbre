# Repository Validation

`validate_repo.py` checks this repository against the structural,
safety, and documentation contract defined in `CONTRIBUTING.md`. Run it
before opening a pull request.

## Usage

```powershell
python tools/validation/validate_repo.py
```

Exit code is non-zero only if at least one **ERROR**-level issue is
found. **WARNING**-level issues (catalog completeness gaps, unresolved
markdown links, stray filenames in a `scripts/` directory) are reported
but do not fail the run, since the operational category tree
(`performance/`, `vacuum-and-autovacuum/`, etc.) is expected to grow
incrementally and will legitimately have outstanding workflows at any
given point in time.

Useful flags:

```powershell
# List available check names
python tools/validation/validate_repo.py --list-checks

# Run a subset of checks
python tools/validation/validate_repo.py --check sql-headers --check no-placeholders

# Only print ERROR-level findings
python tools/validation/validate_repo.py --only-errors

# Only print the final summary line
python tools/validation/validate_repo.py --quiet
```

## What is checked

| Check | What it verifies | Severity |
| --- | --- | --- |
| `workflow-readmes` | Every `<category>/<workflow>/` directory has a `README.md` and a `scripts/README.md` | ERROR |
| `sql-headers` | Every `.sql` file has the full required header (see `CONTRIBUTING.md` section 2.1) with a recognized `SAFETY` label | ERROR (missing field) / WARNING (unrecognized label text) |
| `no-placeholders` | No `.sql`/`.md` file (outside this validator's own source and the documented-forbidden-marker examples in `CONTRIBUTING.md` / `docs/production-safety/README.md`) contains `REPLACE_ME`, `PLACEHOLDER`, `TODO`, `FIXME`, `TBD`, or `Lorem ipsum` | ERROR |
| `no-destructive-statements` | No script executes `CREATE EXTENSION`; no script declaring `SAFETY: READ ONLY` contains a destructive/DDL/DML statement in its executable body | ERROR |
| `sequential-filenames` | Every `scripts/` directory's numbered files (`NN_description.sql`/`.md`) are sequential starting at `01` with no gaps or duplicates | ERROR (numbering) / WARNING (unrecognized filenames) |
| `catalog-completeness` | Compares the on-disk category/workflow tree against the documented catalog (`tools/validation/catalog.py`) | WARNING |
| `markdown-links` | Best-effort check that relative Markdown links resolve to an existing path | WARNING |

## Files

* `catalog.py` -- the authoritative expected category/workflow catalog,
  transcribed from the repository's design specification. Update this
  file if the specification's explicit workflow lists ever change --
  it is intentionally kept separate from the checking logic.
* `sql_header.py` -- header parsing helpers shared by the checks that
  need to read a script's header.
* `checks.py` -- the individual check implementations.
* `validate_repo.py` -- the CLI entry point that runs the checks above
  and prints a report.

## CI

A GitHub Actions workflow (`.github/workflows/validate-repository.yml`,
if present) runs `validate_repo.py` on every push/pull request using only
the Python standard library -- no extra dependencies are required.
