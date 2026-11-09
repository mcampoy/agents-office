"""Project registry of the office (<data>/projects.json) and the hook config (<data>/config.json).

Used by scripts/configure.py (registering a project) and scripts/install.py (installing the plugin).
"""
import json
import re
from pathlib import Path

from .offices import read_projects
from .profile import Profile, data_folder


def ident_of(folder):
    """Readable, stable id from the project folder name."""
    name = Path(folder).name.lower()
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-") or "project"


def _write(data, projects):
    (data / "projects.json").write_text(json.dumps({"projects": projects}, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")


def register(data, ident, folder, profile):
    data = data_folder(data)
    data.mkdir(parents=True, exist_ok=True)
    projects = [p for p in read_projects(data) if p["id"] != ident]
    projects.append({"id": ident, "dir": str(Path(folder).resolve()), "profile": str(Path(profile).resolve())})
    _write(data, projects)
    return projects


def unregister(data, ident):
    data = data_folder(data)
    projects = [p for p in read_projects(data) if p["id"] != ident]
    _write(data, projects)
    return projects


def write_hook_config(data, extra=None):
    """<data>/config.json: one block per project with what the hook needs to filter and redact."""
    data = data_folder(data)
    projects = []
    for p in read_projects(data):
        try:
            profile = Profile(p["profile"])
        except (OSError, ValueError):
            continue
        hook = profile.for_hook()
        hook.pop("team_dir", None)
        projects.append({"id": p["id"], "dir": p["dir"], **hook})
    config = {"projects": projects, **(extra or {})}
    data.mkdir(parents=True, exist_ok=True)
    target = data / "config.json"
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
