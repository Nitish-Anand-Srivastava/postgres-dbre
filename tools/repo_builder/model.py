"""Core data model for workflow directories, scripts, and README rendering."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Script:
    """A single numbered artifact inside a workflow's scripts/ directory.

    ``kind`` is ``"sql"`` for an executable, read-only-by-default psql script
    or ``"md"`` for a remediation/runbook template that intentionally contains
    manual, guarded, potentially disruptive steps and must never be piped
    directly into psql without an operator reading it first.
    """

    order: str  # e.g. "01"
    name: str  # file stem without extension, e.g. "01_identify_blocked_sessions"
    purpose: str
    safety: str  # "READ ONLY", "READ ONLY (may be resource intensive)", "MANUAL / GUARDED DDL", etc.
    expected_impact: str
    required_privileges: str
    prerequisites: str
    related_scripts: str
    interpretation: str
    body: str  # SQL body or markdown body (without the header block)
    kind: str = "sql"
    execution_location: str = "Any instance (writer or reader)"
    aurora_version: str = "Aurora PostgreSQL 17+ (also compatible with community PostgreSQL 17+ unless noted)"
    expected_runtime: str = "Low (sub-second to a few seconds)"
    table_purpose: Optional[str] = None  # short purpose for the scripts/README.md table; falls back to purpose

    @property
    def filename(self) -> str:
        ext = "sql" if self.kind == "sql" else "md"
        return f"{self.name}.{ext}"


@dataclass
class Workflow:
    category_slug: str          # e.g. "performance"
    category_title: str         # e.g. "Performance Issues"
    slug: str                   # e.g. "high-cpu"
    title: str                  # e.g. "High CPU Utilization"
    summary: str                # one-paragraph problem description
    symptoms: List[str]
    business_impact: List[str]
    root_causes: List[str]      # may contain nested "Category: cause" strings
    investigation_strategy: List[str]
    prerequisites: List[str]
    interpretation_guide: List[str]
    remediation_immediate: List[str]
    remediation_short_term: List[str]
    remediation_long_term: List[str]
    production_safety: List[str]
    escalation_criteria: List[str]
    related_issues: List[str]   # relative markdown links, e.g. "../slow-queries/README.md"
    scripts: List[Script] = field(default_factory=list)
    aurora_notes: List[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return f"{self.category_slug}/{self.slug}"
