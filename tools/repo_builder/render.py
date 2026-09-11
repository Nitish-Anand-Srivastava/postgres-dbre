"""Rendering helpers: turn Workflow/Script objects into file text."""
from __future__ import annotations

from typing import List

from .model import Script, Workflow

RULE = "=" * 79


def render_sql_header(wf: Workflow, s: Script) -> str:
    related = s.related_scripts or "None"
    lines = [
        "/*",
        RULE,
        "SCRIPT NAME:",
        s.filename,
        "",
        "PURPOSE:",
        s.purpose,
        "",
        "AURORA POSTGRESQL VERSION:",
        s.aurora_version,
        "",
        "EXECUTION LOCATION:",
        s.execution_location,
        "",
        "SAFETY:",
        s.safety,
        "",
        "EXPECTED IMPACT:",
        s.expected_impact,
        "",
        "REQUIRED PRIVILEGES:",
        s.required_privileges,
        "",
        "PREREQUISITES:",
        s.prerequisites,
        "",
        "EXECUTION ORDER:",
        f"Step {s.order} of workflow '{wf.category_slug}/{wf.slug}'",
        "",
        "RELATED SCRIPTS:",
        related,
        "",
        "HOW TO INTERPRET RESULTS:",
        s.interpretation,
        RULE,
        "*/",
    ]
    return "\n".join(lines)


def render_sql_file(wf: Workflow, s: Script) -> str:
    header = render_sql_header(wf, s)
    body = s.body.strip("\n")
    return f"{header}\n\n{body}\n"


def render_md_runbook(wf: Workflow, s: Script) -> str:
    """Render a markdown remediation runbook with the same header fields,
    expressed as a documentation frontmatter block instead of a SQL comment,
    since these files are read as documentation, not executed by psql.
    """
    lines = [
        f"# {s.name}",
        "",
        "> **This is a manual remediation/runbook template, not an automatic script.**",
        "> It contains guarded, potentially disruptive steps. Read it fully, adapt the",
        "> guard variables, and execute steps interactively with a second engineer",
        "> present before running anything against production.",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Script name | `{s.filename}` |",
        f"| Purpose | {s.purpose} |",
        f"| Aurora PostgreSQL version | {s.aurora_version} |",
        f"| Execution location | {s.execution_location} |",
        f"| Safety | {s.safety} |",
        f"| Expected impact | {s.expected_impact} |",
        f"| Required privileges | {s.required_privileges} |",
        f"| Prerequisites | {s.prerequisites} |",
        f"| Execution order | Step {s.order} of workflow `{wf.category_slug}/{wf.slug}` |",
        f"| Related scripts | {s.related_scripts or 'None'} |",
        "",
        "## How to interpret / use this runbook",
        "",
        s.interpretation,
        "",
        "---",
        "",
        s.body.strip("\n"),
        "",
    ]
    return "\n".join(lines)


def _bullets(items: List[str]) -> str:
    if not items:
        return "_None documented._"
    return "\n".join(f"- {item}" for item in items)


def _numbered(items: List[str]) -> str:
    if not items:
        return "_None documented._"
    return "\n".join(f"{i}. {item}" for i, item in enumerate(items, start=1))


def render_workflow_readme(wf: Workflow) -> str:
    script_list = "\n".join(
        f"{i}. [`scripts/{s.filename}`](scripts/{s.filename}) -- {s.purpose}"
        for i, s in enumerate(wf.scripts, start=1)
    )
    def _related_link(rel: str) -> str:
        # rel is a relative path like "../slow-queries/README.md"; derive a
        # readable label from the workflow slug it points at.
        parts = [p for p in rel.split("/") if p not in ("..", ".")]
        label_parts = [p for p in parts if p != "README.md"]
        label = label_parts[-1] if label_parts else rel
        return f"[{label}]({rel})"

    related = _bullets([_related_link(r) for r in wf.related_issues]) if wf.related_issues else "_None documented._"
    aurora_block = ""
    if wf.aurora_notes:
        aurora_block = (
            "\n## Aurora PostgreSQL Notes\n\n"
            "Differences from self-managed / standard PostgreSQL that matter for this "
            "workflow:\n\n" + _bullets(wf.aurora_notes) + "\n"
        )

    return f"""# {wf.title}

**Category:** {wf.category_title} | **Workflow:** `{wf.category_slug}/{wf.slug}`

## 1. Problem Description

{wf.summary}

## 2. Typical Symptoms

{_bullets(wf.symptoms)}

## 3. Business Impact

{_bullets(wf.business_impact)}

## 4. Possible Root Causes

{_bullets(wf.root_causes)}

## 5. Investigation Strategy

{_numbered(wf.investigation_strategy)}

## 6. Prerequisites

{_bullets(wf.prerequisites)}

## 7. Investigation Workflow

Run the scripts in `scripts/` in numeric order. See `scripts/README.md` for the
full execution table (safety, expected runtime, when to stop).

{script_list}
{aurora_block}
## 8. Interpretation Guide

{_bullets(wf.interpretation_guide)}

## 9. Remediation Options

**Immediate mitigation** (stop the bleeding, minutes):

{_bullets(wf.remediation_immediate)}

**Short-term remediation** (hours to days):

{_bullets(wf.remediation_short_term)}

**Long-term engineering fix** (days to weeks):

{_bullets(wf.remediation_long_term)}

## 10. Production Safety

{_bullets(wf.production_safety)}

## 11. Escalation Criteria

Escalate beyond the on-call DBA when any of the following are true:

{_bullets(wf.escalation_criteria)}

## 12. Related Issues

{related}
"""


def render_scripts_readme(wf: Workflow) -> str:
    rows = "\n".join(
        f"| {s.order} | `{s.filename}` | {s.table_purpose or s.purpose} | {s.safety} | {s.expected_runtime} |"
        for s in wf.scripts
    )
    stop_conditions = _bullets(wf.escalation_criteria)
    do_not_run = _bullets(
        [s.filename + " -- " + s.expected_impact for s in wf.scripts if "resource intensive" in s.safety.lower() or s.kind == "md"]
    )
    return f"""# Scripts: {wf.title}

Execution order, safety classification, and expected runtime for every script
in `{wf.category_slug}/{wf.slug}/scripts/`.

| Order | Script | Purpose | Safety | Expected Runtime |
| ----- | ------ | ------- | ------ | ---------------- |
{rows}

## Execution Order

Run scripts strictly in the numeric order shown above. Each script assumes the
operator has reviewed the output of the prior step. Do not skip ahead to a
remediation template (`.md` files, if present) without completing the
read-only investigation steps first.

## Required Permissions

Unless a script states otherwise in its `REQUIRED PRIVILEGES` header field, a
role with the built-in `pg_monitor` (or `pg_read_all_stats` /
`pg_read_all_settings`) attribute, `CONNECT` on the target database, and
`USAGE` on `public` is sufficient. Scripts that read `pg_stat_statements`
require that extension to be installed in the current database. Scripts that
touch DDL, `pg_terminate_backend()`, or write operations state elevated
requirements explicitly in their own header.

## Expected Output

Every script returns a result set intended to be read directly in `psql` (or
any SQL client). Columns are named for direct interpretation; each script's
header contains a `HOW TO INTERPRET RESULTS` section, and the parent
`README.md` section 8 ("Interpretation Guide") gives workflow-level guidance.

## When to Stop and Escalate

{stop_conditions}

## Scripts That Should Not Be Run During Severe Incidents

{do_not_run if do_not_run != '_None documented._' else '_All scripts in this workflow are lightweight, read-only, and safe to run even during a severe incident. Prefer the narrower/most targeted script first if the system is under extreme load._'}
"""
