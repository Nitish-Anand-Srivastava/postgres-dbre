"""Filesystem writer: materializes Workflow objects into the repo tree."""
from __future__ import annotations

import os
from typing import Iterable, List

from .model import Workflow
from .render import render_md_runbook, render_scripts_readme, render_sql_file, render_workflow_readme


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def write_workflows(root: str, workflows: Iterable[Workflow]) -> List[str]:
    written: List[str] = []
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
    return written
