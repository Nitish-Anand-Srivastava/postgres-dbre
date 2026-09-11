"""Small shared helpers used by every per-category workflow definition module."""
from __future__ import annotations

from typing import Optional

from .model import Script

READ_ONLY = "READ ONLY"
READ_ONLY_HEAVY = "READ ONLY (may be resource intensive on very large tables -- see EXPECTED IMPACT)"
GUARDED_DDL = "GUARDED -- MANUAL EXECUTION ONLY (see safety warnings in this file before running any statement)"
GUARDED_DML = "GUARDED -- MANUAL EXECUTION ONLY, WRITE OPERATION (see safety warnings before running)"

PG_MONITOR = (
    "Role membership in `pg_monitor` (or `pg_read_all_stats`) is sufficient. "
    "No superuser required."
)
PG_MONITOR_PLUS_PGSS = (
    "Role membership in `pg_monitor`, plus SELECT on `pg_stat_statements` "
    "(granted automatically to `pg_read_all_stats` once the extension is "
    "created; otherwise `GRANT SELECT ON pg_stat_statements TO <role>;`)."
)
CONNECT_ONLY = "CONNECT on the target database. No elevated privileges required."
TABLE_OWNER_OR_DDL = (
    "Table owner, or a role granted the `MAINTAIN` privilege on the table "
    "(PostgreSQL 16+), or a role with `pg_maintain` membership. DDL variants "
    "additionally require the privileges needed for the specific DDL "
    "statement (e.g. ownership to ALTER TABLE)."
)

AURORA_17 = "Aurora PostgreSQL 17+ (compatible with community PostgreSQL 17+ unless a note says otherwise)"

ANY_INSTANCE = "Any instance (writer or reader)"
WRITER_ONLY = "Writer instance only (the query reads/writes state that only exists or is meaningful on the writer)"
WRITER_PREFERRED = "Writer instance preferred; safe to run on a reader but results reflect only that reader's local activity"


def sql_script(
    order: str,
    name: str,
    purpose: str,
    body: str,
    interpretation: str,
    safety: str = READ_ONLY,
    expected_impact: str = "Minimal -- reads system catalogs/statistics views only, no table locks beyond a brief catalog lookup.",
    required_privileges: str = PG_MONITOR,
    prerequisites: str = "None beyond CONNECT on the target database.",
    related_scripts: str = "",
    execution_location: str = ANY_INSTANCE,
    expected_runtime: str = "Low (sub-second to a few seconds)",
    table_purpose: Optional[str] = None,
    generator_managed: bool = True,
) -> Script:
    return Script(
        order=order,
        name=name,
        purpose=purpose,
        safety=safety,
        expected_impact=expected_impact,
        required_privileges=required_privileges,
        prerequisites=prerequisites,
        related_scripts=related_scripts,
        interpretation=interpretation,
        body=body,
        kind="sql",
        execution_location=execution_location,
        aurora_version=AURORA_17,
        expected_runtime=expected_runtime,
        table_purpose=table_purpose,
        generator_managed=generator_managed,
    )


def md_script(
    order: str,
    name: str,
    purpose: str,
    body: str,
    interpretation: str,
    safety: str = GUARDED_DDL,
    expected_impact: str = "Varies by step -- read each step's own warning before executing it.",
    required_privileges: str = TABLE_OWNER_OR_DDL,
    prerequisites: str = "Full read-only investigation for this workflow completed; maintenance window and second engineer approval obtained.",
    related_scripts: str = "",
    execution_location: str = WRITER_ONLY,
    expected_runtime: str = "Variable -- depends on table size and chosen batch size; see runbook.",
    table_purpose: Optional[str] = None,
) -> Script:
    return Script(
        order=order,
        name=name,
        purpose=purpose,
        safety=safety,
        expected_impact=expected_impact,
        required_privileges=required_privileges,
        prerequisites=prerequisites,
        related_scripts=related_scripts,
        interpretation=interpretation,
        body=body,
        kind="md",
        execution_location=execution_location,
        aurora_version=AURORA_17,
        expected_runtime=expected_runtime,
        table_purpose=table_purpose,
    )
