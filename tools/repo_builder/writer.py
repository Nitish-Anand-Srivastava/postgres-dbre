"""Filesystem writer: materializes Workflow objects into the repo tree."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable

from .model import Workflow
from .render import (
    render_category_readme,
    render_md_runbook,
    render_scripts_readme,
    render_sql_file,
    render_workflow_readme,
)

MANIFEST_FILENAME = ".repo-builder-manifest.json"
MANIFEST_VERSION = 1


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _relative_path(root: str, path: str) -> str:
    return Path(os.path.relpath(path, root)).as_posix()


def write_workflows(root: str, workflows: Iterable[Workflow]) -> dict[str, str]:
    """Write one category and return its managed paths with content hashes."""
    written: dict[str, str] = {}
    workflows = list(workflows)
    for wf in workflows:
        base = os.path.join(root, wf.category_slug, wf.slug)
        readme_path = os.path.join(base, "README.md")
        readme = render_workflow_readme(wf)
        write_text(readme_path, readme)
        written[_relative_path(root, readme_path)] = _content_hash(readme)

        scripts_readme_path = os.path.join(base, "scripts", "README.md")
        scripts_readme = render_scripts_readme(wf)
        write_text(scripts_readme_path, scripts_readme)
        written[_relative_path(root, scripts_readme_path)] = _content_hash(scripts_readme)

        for s in wf.scripts:
            script_path = os.path.join(base, "scripts", s.filename)
            if not s.generator_managed:
                if not os.path.isfile(script_path):
                    raise FileNotFoundError(
                        f"generator-aware external script is missing: {script_path}"
                    )
                continue
            if s.kind == "sql":
                content = render_sql_file(wf, s)
            else:
                content = render_md_runbook(wf, s)
            write_text(script_path, content)
            written[_relative_path(root, script_path)] = _content_hash(content)

    # One category-root index README per category, generated (never
    # hand-authored) so it can never go stale relative to the actual
    # workflow set and so every "../../<category>/README.md" cross-link
    # used by workflow READMEs elsewhere in the repository resolves.
    if workflows:
        category_slug = workflows[0].category_slug
        category_title = workflows[0].category_title
        category_readme_path = os.path.join(root, category_slug, "README.md")
        category_readme = render_category_readme(category_slug, category_title, workflows)
        write_text(category_readme_path, category_readme)
        written[_relative_path(root, category_readme_path)] = _content_hash(category_readme)

    return written


def _load_manifest(root: Path) -> dict[str, dict[str, str]]:
    path = root / MANIFEST_FILENAME
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != MANIFEST_VERSION or not isinstance(data.get("categories"), dict):
        raise ValueError(f"unsupported or invalid generator manifest: {path}")
    categories = data["categories"]
    for category, files in categories.items():
        if not isinstance(category, str) or not isinstance(files, dict):
            raise ValueError(f"invalid generator manifest entry for category: {category!r}")
        for relative, digest in files.items():
            candidate = Path(relative)
            if (
                not isinstance(relative, str)
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or candidate.is_absolute()
                or ".." in candidate.parts
                or not candidate.parts
                or candidate.parts[0] != category
            ):
                raise ValueError(f"unsafe generator manifest path: {relative!r}")
    return categories


def _file_hash(path: Path) -> str:
    return _content_hash(path.read_text(encoding="utf-8"))


def _remove_empty_parents(path: Path, root: Path) -> None:
    parent = path.parent
    while parent != root:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def sync_managed_artifacts(
    root: str,
    generated_by_category: dict[str, dict[str, str]],
    *,
    selected_categories: set[str],
    full_build: bool,
) -> list[str]:
    """Remove stale manifest-owned files and persist the current ownership set.

    A stale path is deleted only when its current SHA-256 still matches the
    digest recorded when the generator last wrote it. Modified files and paths
    never recorded in the manifest are never removed.
    """
    root_path = Path(root).resolve()
    previous = _load_manifest(root_path)
    categories_to_sync = set(previous) | set(generated_by_category) if full_build else selected_categories
    removed: list[str] = []

    for category in sorted(categories_to_sync):
        old_files = previous.get(category, {})
        current_files = generated_by_category.get(category, {})
        for relative in sorted(set(old_files) - set(current_files)):
            path = root_path / Path(relative)
            if not path.exists() and not path.is_symlink():
                continue
            if path.is_symlink() or path.is_dir() or _file_hash(path) != old_files[relative]:
                raise RuntimeError(
                    f"refusing to remove stale generated path with modified content: {relative}"
                )
            path.unlink()
            removed.append(relative)
            _remove_empty_parents(path, root_path)

    next_categories = dict(previous)
    if full_build:
        next_categories = {}
    for category in categories_to_sync:
        current_files = generated_by_category.get(category, {})
        if current_files:
            next_categories[category] = dict(sorted(current_files.items()))
        else:
            next_categories.pop(category, None)

    manifest = {
        "version": MANIFEST_VERSION,
        "categories": dict(sorted(next_categories.items())),
    }
    write_text(
        str(root_path / MANIFEST_FILENAME),
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    return removed
