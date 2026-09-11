"""Filesystem writer: materializes Workflow objects into the repo tree."""
from __future__ import annotations

import os
from typing import Iterable, List

from .model import Workflow
from .render import (
    render_category_readme,
    render_md_runbook,
    render_scripts_readme,
    render_sql_file,
    render_workflow_readme,
)


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def write_workflows(root: str, workflows: Iterable[Workflow]) -> List[str]:
    written: List[str] = []
    workflows = list(workflows)
    for wf in workflows:
        base = os.path.join(root, wf.category_slug, wf.slug)
        readme_path = os.path.join(base, "README.md")
        write_text(readme_path, render_workflow_readme(wf))
        written.append(readme_path)

        scripts_readme_path = os.path.join(base, "scripts", "README.md")
        write_text(scripts_readme_path, render_scripts_readme(wf))
        written.append(scripts_readme_path)

        for s in wf.scripts:
            script_path = os.path.join(base, "scripts", s.filename)
            if s.kind == "sql":
                content = render_sql_file(wf, s)
            else:
                content = render_md_runbook(wf, s)
            write_text(script_path, content)
            written.append(script_path)

    # One category-root index README per category, generated (never
    # hand-authored) so it can never go stale relative to the actual
    # workflow set and so every "../../<category>/README.md" cross-link
    # used by workflow READMEs elsewhere in the repository resolves.
    if workflows:
        category_slug = workflows[0].category_slug
        category_title = workflows[0].category_title
        category_readme_path = os.path.join(root, category_slug, "README.md")
        write_text(category_readme_path, render_category_readme(category_slug, category_title, workflows))
        written.append(category_readme_path)

    return written
