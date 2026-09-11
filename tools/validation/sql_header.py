"""SQL script header parsing utilities.

Every ``.sql`` file in this repository must begin with a block comment
containing a fixed set of labeled fields (see ``CONTRIBUTING.md`` section
2.1 for the authoritative template). This module extracts that header and
exposes helpers to check for required fields and read the declared safety
classification.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

REQUIRED_HEADER_FIELDS: list[str] = [
    "SCRIPT NAME:",
    "PURPOSE:",
    "AURORA POSTGRESQL VERSION:",
    "EXECUTION LOCATION:",
    "SAFETY:",
    "EXPECTED IMPACT:",
    "REQUIRED PRIVILEGES:",
    "PREREQUISITES:",
    "EXECUTION ORDER:",
    "RELATED SCRIPTS:",
    "HOW TO INTERPRET RESULTS:",
]

# Recognized SAFETY classification labels (see docs/production-safety/README.md)
KNOWN_SAFETY_LABELS = {
    "READ ONLY",
    "LOW RISK WRITE",
    "ELEVATED RISK",
    "DESTRUCTIVE",
}

_HEADER_BLOCK_RE = re.compile(r"\A\s*/\*(.*?)\*/", re.DOTALL)
_SAFETY_VALUE_RE = re.compile(r"SAFETY:\s*\r?\n\s*([^\r\n]+)")


@dataclass
class SqlHeader:
    found: bool = False
    raw_text: str = ""
    missing_fields: list[str] = field(default_factory=list)
    safety_label: str | None = None
    safety_label_recognized: bool = False


def parse_sql_header(content: str) -> SqlHeader:
    """Parse the leading block-comment header out of a SQL file's content."""
    match = _HEADER_BLOCK_RE.match(content)
    if not match:
        return SqlHeader(found=False, missing_fields=list(REQUIRED_HEADER_FIELDS))

    header_text = match.group(1)
    missing = [f for f in REQUIRED_HEADER_FIELDS if f not in header_text]

    safety_label = None
    safety_recognized = False
    safety_match = _SAFETY_VALUE_RE.search(header_text)
    if safety_match:
        safety_label = safety_match.group(1).strip()
        # Allow trailing prose after the label, e.g. "READ ONLY" alone, or
        # a label followed by a qualifier -- only require it to *start*
        # with a known label.
        safety_recognized = any(
            safety_label.upper().startswith(label) for label in KNOWN_SAFETY_LABELS
        )

    return SqlHeader(
        found=True,
        raw_text=header_text,
        missing_fields=missing,
        safety_label=safety_label,
        safety_label_recognized=safety_recognized,
    )


def strip_sql_comments(content: str) -> str:
    """Remove all block and line comments from SQL content.

    Used for scanning the *executable* body of a script (e.g. for
    forbidden destructive statements) without matching keywords that only
    appear in header prose or inline explanatory comments.
    """
    without_block_comments = re.sub(r"/\*.*?\*/", " ", content, flags=re.DOTALL)
    without_comments = re.sub(r"--[^\n]*", " ", without_block_comments)
    return without_comments


_SINGLE_QUOTED_STRING_RE = re.compile(r"'(?:[^']|'')*'", re.DOTALL)
_DOLLAR_QUOTED_STRING_RE = re.compile(r"\$([A-Za-z_]*)\$.*?\$\1\$", re.DOTALL)


def strip_sql_comments_and_literals(content: str) -> str:
    """Remove comments *and* string literal contents from SQL content.

    Keyword scans (e.g. "does the body contain an executable
    ``CREATE EXTENSION`` statement") must not match keywords that only
    appear as text inside a quoted string literal -- for example, a
    read-only script that prints an instructional notice mentioning
    ``CREATE EXTENSION`` as prose, without ever executing it. Each string
    literal is replaced with a same-shaped empty literal so surrounding
    statement structure (and offsets, for error messages) are preserved.
    """
    without_comments = strip_sql_comments(content)
    without_dollar_strings = _DOLLAR_QUOTED_STRING_RE.sub("''", without_comments)
    without_strings = _SINGLE_QUOTED_STRING_RE.sub("''", without_dollar_strings)
    return without_strings
