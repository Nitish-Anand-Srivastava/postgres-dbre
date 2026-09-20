#!/usr/bin/env python3
"""Build the Aurora PostgreSQL DBA Toolkit repository from the workflow
registry in tools/repo_builder/.

Usage:
    python tools/build_repository.py [--root PATH] [--only category1,category2]

Re-running this script is safe and idempotent for generated workflow
directories (it overwrites README.md, scripts/README.md, and scripts/*.sql
under each workflow path). A manifest records generator-owned files so obsolete
outputs can be removed without deleting hand-authored or modified files. The
builder never touches hand-authored root-level files (README.md,
CONTRIBUTING.md, LICENSE, docs/, common/) or scripts registered with
generator_managed=False.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.repo_builder.writer import sync_managed_artifacts, write_workflows  # noqa: E402

# Each entry: (module_path, attribute_name)
CATEGORY_MODULES = [
    "tools.repo_builder.wf_performance",
    "tools.repo_builder.wf_locking",
    "tools.repo_builder.wf_xid",
    "tools.repo_builder.wf_vacuum",
    "tools.repo_builder.wf_partitioning",
    "tools.repo_builder.wf_archival",
    "tools.repo_builder.wf_tables_indexes",
    "tools.repo_builder.wf_connections",
    "tools.repo_builder.wf_replication",
    "tools.repo_builder.wf_health",
    "tools.repo_builder.wf_query_optimization",
    "tools.repo_builder.wf_storage",
    "tools.repo_builder.wf_schema_changes",
    "tools.repo_builder.wf_incident_response",
    "tools.repo_builder.wf_security",
    "tools.repo_builder.wf_observability",
    "tools.repo_builder.wf_maintenance",
    "tools.repo_builder.wf_dr",
    "tools.repo_builder.wf_automation",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--only", default=None, help="Comma-separated substrings to filter category modules")
    args = parser.parse_args()

    modules = CATEGORY_MODULES
    if args.only:
        filters = args.only.split(",")
        modules = [m for m in modules if any(f in m for f in filters)]

    total_workflows = 0
    total_scripts = 0
    generated_by_category: dict[str, dict[str, str]] = {}
    selected_categories: set[str] = set()
    for mod_name in modules:
        import importlib

        mod = importlib.import_module(mod_name)
        workflows = getattr(mod, "WORKFLOWS")
        category = getattr(mod, "CATEGORY_SLUG")
        selected_categories.add(category)
        if not workflows:
            generated_by_category[category] = {}
            continue
        if any(workflow.category_slug != category for workflow in workflows):
            raise ValueError(f"{mod_name} contains workflows from multiple categories")
        generated_by_category[category] = write_workflows(args.root, workflows)
        total_workflows += len(workflows)
        total_scripts += sum(len(w.scripts) for w in workflows)
        print(f"[ok] {mod_name}: {len(workflows)} workflows, {sum(len(w.scripts) for w in workflows)} scripts")

    removed = sync_managed_artifacts(
        args.root,
        generated_by_category,
        selected_categories=selected_categories,
        full_build=args.only is None,
    )
    if removed:
        print(f"[clean] removed {len(removed)} obsolete generator-managed file(s)")

    print(f"\nTotal: {total_workflows} workflows, {total_scripts} scripts written under {args.root}")


if __name__ == "__main__":
    main()
