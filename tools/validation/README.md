# Repository Validation

`validate_repo.py` checks this repository against the structural,
safety, and documentation contract defined in `CONTRIBUTING.md`. Run it
before opening a pull request.

## Usage

```powershell
python tools/validation/validate_repo.py
```

Exit code is non-zero only if at least one **ERROR**-level issue is
found. **WARNING**-level issues (unresolved markdown links and stray filenames
in a `scripts/` directory) are reported but do not fail the run and must still
be reviewed. Catalog drift is an error because the catalog now describes the
complete generated workflow tree.

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
| `catalog-completeness` | Compares the on-disk category/workflow tree against the authoritative catalog (`tools/validation/catalog.py`) | ERROR |
| `markdown-links` | Best-effort check that relative Markdown links resolve to an existing path | WARNING |

## Files

* `catalog.py` -- the authoritative expected category/workflow catalog.
  Update it together with the corresponding `tools/repo_builder/wf_*.py`
  source whenever the generated workflow set changes; it is intentionally
  kept separate from the checking logic so drift is detectable.
* `sql_header.py` -- header parsing helpers shared by the checks that
  need to read a script's header.
* `checks.py` -- the individual check implementations.
* `validate_repo.py` -- the CLI entry point that runs the checks above
  and prints a report.

## CI

A GitHub Actions workflow (`.github/workflows/validate-repository.yml`)
runs `validate_repo.py`, regenerates the workflow tree with
`python tools/build_repository.py`, runs the generator synchronization
regression tests, and fails if regeneration leaves any tracked or untracked
change. The generator's `.repo-builder-manifest.json` limits stale-file cleanup
to previously generated content whose hash is unchanged. All commands use only
the Python standard library; no extra dependencies are required.
