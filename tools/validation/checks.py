"""Individual validation checks for the Aurora PostgreSQL DBA Toolkit
repository.

Each ``check_*`` function takes the repository root and returns a list of
``Issue`` objects. ``validate_repo.py`` aggregates these into a report.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import catalog
from .sql_header import (
    REQUIRED_HEADER_FIELDS,
    parse_sql_header,
    strip_sql_comments_and_literals,
)

ERROR = "error"
WARNING = "warning"


@dataclass
class Issue:
    severity: str
    check: str
    path: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - formatting only
        tag = "ERROR" if self.severity == ERROR else "WARN "
        return f"[{tag}] ({self.check}) {self.path}: {self.message}"


PLACEHOLDER_TOKENS = [
    (re.compile(r"REPLACE_ME"), "REPLACE_ME"),
    (re.compile(r"\bPLACEHOLDER\b", re.IGNORECASE), "PLACEHOLDER"),
    (re.compile(r"\bTODO\b"), "TODO"),
    (re.compile(r"\bFIXME\b"), "FIXME"),
    (re.compile(r"\bTBD\b"), "TBD"),
    (re.compile(r"lorem ipsum", re.IGNORECASE), "Lorem ipsum"),
]

# Paths (relative to repo root, POSIX-style) excluded from the placeholder
# scan because they document these tokens as *forbidden examples* rather
# than using them as unfinished content.
PLACEHOLDER_SCAN_EXCLUDE_FILES = {
    "CONTRIBUTING.md",
    "docs/production-safety/README.md",
}
PLACEHOLDER_SCAN_EXCLUDE_DIR_PREFIXES = ("tools/validation",)

# Statement keywords forbidden in the executable body of a script whose
# header declares SAFETY: READ ONLY. Matched against comment-stripped SQL.
READ_ONLY_FORBIDDEN_PATTERNS = [
    re.compile(r"\bDROP\s+(TABLE|INDEX|SCHEMA|DATABASE|SEQUENCE|VIEW|FUNCTION|EXTENSION|ROLE)\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
    re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+\S+\s+SET\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+(TABLE|SYSTEM|DATABASE|INDEX|SEQUENCE)\b", re.IGNORECASE),
    re.compile(r"\bVACUUM\s+FULL\b", re.IGNORECASE),
    re.compile(r"\bCREATE\s+(TABLE|INDEX|EXTENSION|SEQUENCE|VIEW)\b", re.IGNORECASE),
    re.compile(r"\bpg_terminate_backend\s*\(", re.IGNORECASE),
    re.compile(r"\bpg_cancel_backend\s*\(", re.IGNORECASE),
]

# Forbidden regardless of the declared safety label -- extension creation
# must never ship as an auto-executing statement (see
# docs/production-safety/README.md and docs/prerequisites/README.md).
CREATE_EXTENSION_RE = re.compile(r"\bCREATE\s+EXTENSION\b", re.IGNORECASE)

SCRIPT_FILENAME_RE = re.compile(r"^(\d+)_.+\.(sql|md)$", re.IGNORECASE)


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def discover_category_dirs(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.iterdir()
        if p.is_dir()
        and p.name not in catalog.NON_CATEGORY_ROOT_DIRS
        and not p.name.startswith(".")
    )


def discover_workflow_dirs(root: Path) -> list[Path]:
    """Return every ``<category>/<workflow>`` directory that looks like a
    workflow (i.e. it is a direct child of a category directory and is
    itself a directory, not a file)."""
    workflows: list[Path] = []
    for category in discover_category_dirs(root):
        for child in sorted(category.iterdir()):
            if child.is_dir():
                workflows.append(child)
    return workflows


def discover_sql_files(root: Path) -> list[Path]:
    exclude_dirs = {".git", "node_modules"}
    sql_files: list[Path] = []
    for path in root.rglob("*.sql"):
        if any(part in exclude_dirs for part in path.parts):
            continue
        sql_files.append(path)
    return sorted(sql_files)


def discover_scripts_dirs(root: Path) -> list[Path]:
    return sorted({p.parent for p in discover_sql_files(root) if p.parent.name == "scripts"})


# ---------------------------------------------------------------------------
# Check 1: every workflow directory has README.md and scripts/README.md
# ---------------------------------------------------------------------------

def check_workflow_readmes(root: Path) -> list[Issue]:
    issues: list[Issue] = []
    for workflow in discover_workflow_dirs(root):
        rel = _rel(root, workflow)
        readme = workflow / "README.md"
        scripts_dir = workflow / "scripts"
        scripts_readme = scripts_dir / "README.md"

        if not readme.is_file():
            issues.append(Issue(ERROR, "workflow-readme", rel, "missing README.md"))
        if not scripts_dir.is_dir():
            issues.append(Issue(ERROR, "workflow-readme", rel, "missing scripts/ directory"))
        elif not scripts_readme.is_file():
            issues.append(Issue(ERROR, "workflow-readme", rel, "missing scripts/README.md"))
    return issues


# ---------------------------------------------------------------------------
# Check 2: SQL header required fields
# ---------------------------------------------------------------------------

def check_sql_headers(root: Path) -> list[Issue]:
    issues: list[Issue] = []
    for sql_file in discover_sql_files(root):
        rel = _rel(root, sql_file)
        content = sql_file.read_text(encoding="utf-8", errors="replace")
        header = parse_sql_header(content)
        if not header.found:
            issues.append(
                Issue(ERROR, "sql-header", rel, "no leading block-comment header found")
            )
            continue
        if header.missing_fields:
            issues.append(
                Issue(
                    ERROR,
                    "sql-header",
                    rel,
                    "header missing required field(s): " + ", ".join(header.missing_fields),
                )
            )
        if header.safety_label is None:
            issues.append(Issue(ERROR, "sql-header", rel, "SAFETY field has no value"))
        elif not header.safety_label_recognized:
            issues.append(
                Issue(
                    WARNING,
                    "sql-header",
                    rel,
                    f"SAFETY value '{header.safety_label}' does not start with a recognized "
                    "label (READ ONLY / LOW RISK WRITE / ELEVATED RISK / DESTRUCTIVE)",
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Check 3: no placeholder / unfinished-content markers
# ---------------------------------------------------------------------------

def check_no_placeholders(root: Path) -> list[Issue]:
    issues: list[Issue] = []
    for path in list(root.rglob("*.sql")) + list(root.rglob("*.md")):
        rel = _rel(root, path)
        if rel in PLACEHOLDER_SCAN_EXCLUDE_FILES:
            continue
        if any(rel.startswith(prefix) for prefix in PLACEHOLDER_SCAN_EXCLUDE_DIR_PREFIXES):
            continue
        if ".git" in path.parts:
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for pattern, label in PLACEHOLDER_TOKENS:
            if pattern.search(content):
                issues.append(
                    Issue(ERROR, "no-placeholders", rel, f"contains placeholder marker '{label}'")
                )
    return issues


# ---------------------------------------------------------------------------
# Check 4: no executable CREATE EXTENSION / destructive statements
# ---------------------------------------------------------------------------

def check_no_destructive_statements(root: Path) -> list[Issue]:
    issues: list[Issue] = []
    for sql_file in discover_sql_files(root):
        rel = _rel(root, sql_file)
        content = sql_file.read_text(encoding="utf-8", errors="replace")
        header = parse_sql_header(content)
        body = strip_sql_comments_and_literals(content)

        if CREATE_EXTENSION_RE.search(body):
            issues.append(
                Issue(
                    ERROR,
                    "no-destructive-statements",
                    rel,
                    "contains an executable CREATE EXTENSION statement; extension setup "
                    "must be documented (docs/prerequisites/README.md), not auto-run",
                )
            )

        declared_read_only = bool(header.safety_label) and header.safety_label.upper().startswith("READ ONLY")
        if declared_read_only:
            for pattern in READ_ONLY_FORBIDDEN_PATTERNS:
                if pattern.search(body):
                    issues.append(
                        Issue(
                            ERROR,
                            "no-destructive-statements",
                            rel,
                            f"declares SAFETY: READ ONLY but body matches forbidden pattern "
                            f"'{pattern.pattern}'",
                        )
                    )
    return issues


# ---------------------------------------------------------------------------
# Check 5: sequential script filenames
# ---------------------------------------------------------------------------

def check_sequential_filenames(root: Path) -> list[Issue]:
    issues: list[Issue] = []
    for scripts_dir in discover_scripts_dirs(root):
        rel = _rel(root, scripts_dir)
        numbers: list[int] = []
        stray_files: list[str] = []
        for entry in sorted(scripts_dir.iterdir()):
            if not entry.is_file():
                continue
            if entry.name.lower() == "readme.md":
                continue
            match = SCRIPT_FILENAME_RE.match(entry.name)
            if not match:
                stray_files.append(entry.name)
                continue
            numbers.append(int(match.group(1)))

        for stray in stray_files:
            issues.append(
                Issue(
                    WARNING,
                    "sequential-filenames",
                    rel,
                    f"file '{stray}' does not follow the NN_description.(sql|md) naming convention",
                )
            )

        if not numbers:
            continue

        numbers_sorted = sorted(numbers)
        if len(set(numbers_sorted)) != len(numbers_sorted):
            dupes = sorted({n for n in numbers_sorted if numbers_sorted.count(n) > 1})
            issues.append(
                Issue(ERROR, "sequential-filenames", rel, f"duplicate script number(s): {dupes}")
            )
            continue

        expected = list(range(1, len(numbers_sorted) + 1))
        if numbers_sorted != expected:
            issues.append(
                Issue(
                    ERROR,
                    "sequential-filenames",
                    rel,
                    f"script numbering is not sequential starting at 1 (found {numbers_sorted}, "
                    f"expected {expected})",
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Check 6: expected explicit workflow catalog completeness
# ---------------------------------------------------------------------------

def check_catalog_completeness(root: Path) -> list[Issue]:
    issues: list[Issue] = []
    existing_categories = {p.name for p in discover_category_dirs(root)}

    for category in catalog.ALL_EXPECTED_CATEGORIES:
        if category not in existing_categories:
            issues.append(
                Issue(WARNING, "catalog-completeness", category, "expected category directory does not exist yet")
            )

    for category, expected_workflows in catalog.EXPLICIT_CATALOG.items():
        category_path = root / category
        if not category_path.is_dir():
            continue
        existing_workflows = {p.name for p in category_path.iterdir() if p.is_dir()}
        missing = sorted(set(expected_workflows) - existing_workflows)
        extra = sorted(existing_workflows - set(expected_workflows))
        for workflow in missing:
            issues.append(
                Issue(
                    WARNING,
                    "catalog-completeness",
                    f"{category}/{workflow}",
                    "expected workflow directory does not exist yet",
                )
            )
        for workflow in extra:
            issues.append(
                Issue(
                    WARNING,
                    "catalog-completeness",
                    f"{category}/{workflow}",
                    "workflow directory not present in the documented catalog (informational -- "
                    "the specification allows building at least the documented set)",
                )
            )

    for category in catalog.OPEN_CATALOG:
        category_path = root / category
        if category_path.is_dir():
            has_any_workflow = any(p.is_dir() for p in category_path.iterdir())
            if not has_any_workflow:
                issues.append(
                    Issue(WARNING, "catalog-completeness", category, "category directory exists but has no workflows yet")
                )
    return issues


# ---------------------------------------------------------------------------
# Check 7: markdown links resolve
# ---------------------------------------------------------------------------

_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def check_markdown_links(root: Path) -> list[Issue]:
    issues: list[Issue] = []
    for md_file in sorted(root.rglob("*.md")):
        if ".git" in md_file.parts:
            continue
        rel = _rel(root, md_file)
        content = md_file.read_text(encoding="utf-8", errors="replace")
        for link in _MD_LINK_RE.findall(content):
            target = link.strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            resolved = (md_file.parent / path_part).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                # Link escapes the repository root -- not our concern here.
                continue
            if not resolved.exists():
                issues.append(
                    Issue(WARNING, "markdown-links", rel, f"link target does not exist: '{target}'")
                )
    return issues


ALL_CHECKS = [
    ("workflow-readmes", check_workflow_readmes),
    ("sql-headers", check_sql_headers),
    ("no-placeholders", check_no_placeholders),
    ("no-destructive-statements", check_no_destructive_statements),
    ("sequential-filenames", check_sequential_filenames),
    ("catalog-completeness", check_catalog_completeness),
    ("markdown-links", check_markdown_links),
]
