#!/usr/bin/env python3
"""Validate the Aurora PostgreSQL DBA Toolkit repository against the
structural, safety, and documentation contract defined in
``CONTRIBUTING.md``.

Usage:
    python tools/validation/validate_repo.py [--root PATH] [--check NAME ...]
                                              [--only-errors] [--quiet]

Exit code is non-zero if any ERROR-level issue is found. WARNING-level
issues (unresolved markdown links and stray filenames) are reported but do
not affect the exit code.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this file directly (``python tools/validation/validate_repo.py``)
# as well as as a module (``python -m tools.validation.validate_repo``).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.validation import checks  # type: ignore
else:
    from . import checks


def find_repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return start.resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root to validate (default: auto-detected from this file's location)",
    )
    parser.add_argument(
        "--check",
        action="append",
        dest="only_checks",
        default=None,
        help="Run only the named check(s) (repeatable). See --list-checks for names.",
    )
    parser.add_argument(
        "--list-checks",
        action="store_true",
        help="List available check names and exit.",
    )
    parser.add_argument(
        "--only-errors",
        action="store_true",
        help="Only print ERROR-level issues (suppress WARNING output).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print the final summary line, not individual issues.",
    )
    args = parser.parse_args(argv)

    if args.list_checks:
        for name, _ in checks.ALL_CHECKS:
            print(name)
        return 0

    root = Path(args.root).resolve() if args.root else find_repo_root(Path(__file__).parent)

    selected = checks.ALL_CHECKS
    if args.only_checks:
        wanted = set(args.only_checks)
        selected = [(name, fn) for name, fn in checks.ALL_CHECKS if name in wanted]
        unknown = wanted - {name for name, _ in checks.ALL_CHECKS}
        if unknown:
            print(f"Unknown check name(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2

    all_issues: list[checks.Issue] = []
    for name, fn in selected:
        section_issues = fn(root)
        all_issues.extend(section_issues)
        if not args.quiet:
            errors = [i for i in section_issues if i.severity == checks.ERROR]
            warnings = [i for i in section_issues if i.severity == checks.WARNING]
            print(f"\n== {name} ({len(errors)} error(s), {len(warnings)} warning(s)) ==")
            for issue in section_issues:
                if args.only_errors and issue.severity != checks.ERROR:
                    continue
                print(f"  {issue}")

    total_errors = sum(1 for i in all_issues if i.severity == checks.ERROR)
    total_warnings = sum(1 for i in all_issues if i.severity == checks.WARNING)

    print(f"\n{'=' * 70}")
    print(f"Validated: {root}")
    print(f"Total: {total_errors} error(s), {total_warnings} warning(s)")
    if total_errors:
        print("RESULT: FAIL (errors must be resolved)")
    else:
        print("RESULT: PASS (warnings, if any, are informational)")
    print(f"{'=' * 70}")

    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
