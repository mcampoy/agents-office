"""Shared helpers: glob patterns, area paths, frontmatter and header tables."""
import functools
import os
import re
from pathlib import PureWindowsPath


@functools.lru_cache(maxsize=512)
def glob_to_regex(pattern):
    """Glob with '/' as separator: '*' does not cross folders, '**' does (including none)."""
    parts, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            parts.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            parts.append(".*")
            i += 2
        elif c == "*":
            parts.append("[^/]*")
            i += 1
        elif c == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(parts) + "$", re.IGNORECASE)


def matches(path, pattern):
    return bool(glob_to_regex(pattern).match(path))


def relative_to_area(path, root, cwd=None):
    """Path relative to the area root with '/', or None if it falls outside.

    Accepts absolute Windows paths, with '/' or '\\', and paths relative to the event's cwd.
    """
    if not path or not isinstance(path, str):
        return None
    p = path.strip().strip('"')
    if not (PureWindowsPath(p).is_absolute() or p.startswith(("/", "\\"))):
        if not cwd:
            return None
        p = os.path.join(cwd, p)
    absolute = os.path.normcase(os.path.normpath(p))
    base = os.path.normcase(os.path.normpath(root)).rstrip("\\/")
    if not absolute.startswith(base + os.sep):
        return None
    # Keep the original casing of the relative part.
    original = os.path.normpath(p)
    return original[len(base) + 1:].replace("\\", "/")


def frontmatter(text):
    """Simple 'key: value' fields from the leading YAML block of an agent or skill."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fields = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return fields


def header_table(lines):
    """The first table in the first lines: {column: value}. Read by column name."""
    rows = []
    for line in lines:
        s = line.strip()
        if s.startswith("|"):
            rows.append(s)
        elif rows:
            break
    if len(rows) < 3 or not re.fullmatch(r"\|[\s:|-]+\|", rows[1]):
        return {}
    columns = [c.strip() for c in rows[0].strip("|").split("|")]
    values = [c.strip() for c in rows[2].strip("|").split("|")]
    return {c: v for c, v in zip(columns, values) if c}


def inside(path, base):
    """True if `path` is `base` or lies under it (case-insensitive on Windows)."""
    if not path or not base:
        return False
    p = os.path.normcase(os.path.normpath(path))
    b = os.path.normcase(os.path.normpath(base))
    return p == b or p.startswith(b.rstrip("\\/") + os.sep)
