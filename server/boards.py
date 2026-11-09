"""The two fixed boards of every project: tasks and audits (frictions).

Tasks (the owner's inbox), in three columns:
- in_progress: Claude Code tasks created and not completed in the session, plus the "En curso" section of
  the tasks file;
- next: the "Siguen" section of the tasks file. If the file has no sections (for example "## date · title"
  entries, as in equipo-idi), every entry is something that comes next;
- done: tasks completed in the session, plus the "Hechas" section of the tasks file.

Audits: the "## date · title" entries of the frictions file, open or resolved according to their Estado field.

The files are team documents, written in Spanish: section names and templates are Spanish on purpose.
Standard formats (scripts/configure.py creates them in new projects): see TASKS_TEMPLATE and FRICTIONS_TEMPLATE.
"""
import re

TASKS_TEMPLATE = """# Pendientes

Tablón de pendientes del proyecto: lo leen la oficina y los agentes. Una línea por tarea, `- [ ] tarea`
(`- [x]` cuando se termina), en la sección que corresponda.

## En curso

## Siguen

## Hechas
"""

FRICTIONS_TEMPLATE = """# Fricciones

Auditoría del trabajo: lo que trabó, salió mal o se repite. Una entrada por fricción, la más nueva arriba.

<!-- Formato de cada entrada:
## AAAA-MM-DD · Título corto
**Estado:** abierta
**Qué pasó:** ...
**Propuesta:** ...
-->
"""

# Section titles accepted for each column (Spanish and English)
SECTIONS = {
    "in_progress": ("en curso", "haciendo", "doing", "in progress"),
    "next": ("siguen", "siguientes", "próximas", "proximas", "pendientes", "por hacer", "to do", "todo", "next"),
    "done": ("hechas", "hecho", "realizadas", "terminadas", "done"),
}
ITEM = re.compile(r"^\s*[-*]\s+(?:\[( |x|X)\]\s+)?(.+?)\s*$")


def _column(title):
    t = title.strip().lower()
    for column, names in SECTIONS.items():
        if any(t.startswith(n) for n in names):
            return column
    return None


def sections(text):
    """Items of the in progress / next / done sections, or None if the file does not use them."""
    columns = {"in_progress": [], "next": [], "done": []}
    current = None
    found = False
    for line in (text or "").splitlines():
        m = re.match(r"^#{2,3}\s+(.+)$", line)
        if m:
            current = _column(m.group(1))
            found = found or current is not None
            continue
        if current:
            i = ITEM.match(line)
            if i:
                checked = (i.group(1) or "").lower() == "x"
                columns["done" if checked else current].append({"title": i.group(2), "source": "file"})
    return columns if found else None


def tasks(text, entries, session_tasks):
    columns = sections(text) or {
        "in_progress": [],
        "next": [{"title": e["title"], "date": e.get("date"), "source": "file"} for e in (entries or {}).get("entries", [])],
        "done": [],
    }
    for t in session_tasks:
        item = {"title": t.get("title") or "(sin título)", "source": "session", "instance": t.get("instance"),
                "ts": t.get("completed") or t.get("created")}
        columns["done" if t.get("completed") else "in_progress"].insert(0, item)
    return columns


def audits(entries):
    open_, resolved = [], []
    for e in (entries or {}).get("entries", []):
        fields = {k.lower(): v for k, v in (e.get("fields") or {}).items()}
        status = next((v for k, v in fields.items() if k.startswith("estado") or k.startswith("status")), "")
        is_resolved = bool(re.search(r"resuelt|cerrad|hecho|solved|closed|resolved", status, re.I))
        item = {"title": e["title"], "date": e.get("date"), "status": status or "abierta",
                "details": {k: v for k, v in (e.get("fields") or {}).items() if v}}
        (resolved if is_resolved else open_).append(item)
    return {"open": open_, "resolved": resolved}
