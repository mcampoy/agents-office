"""Team profile: everything the office needs to know about a specific team or project.

The office code is generic; a profile is a folder with:

    profile.json   team data (paths, roles, scripts, scheduled run, floor texts)
    zones.json     floor zone of each agent
    flows.json     path -> type -> stage rules for documents (optional: without it there are no flows)
    layout.json    floor plan (edited by the web editor)
    sprites.json   sprite of each agent (optional)

Usually each project is registered with scripts/configure.py (see server/offices.py). Without registered
projects, a single profile is used, chosen in this order: `--profile`, the AGENTS_OFFICE_PROFILE variable,
`local.json` at the repo root ({"profile": "<folder>"}, not versioned) and, failing that, `profiles/example`.
See docs/profile.md.
"""
import copy
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXAMPLE = REPO / "profiles" / "example"

DEFAULTS = {
    "name": "Oficina",
    "area_root": None,
    "team_dir": None,
    "port": 8765,
    "roots": [],
    "files": {
        "tasks": None,
        "frictions": None,
        "decisions": None,
        "remember": None,
        "status": None,
    },
    "main_agent": "main",
    "verifier": None,
    "owner_label": "responsable",
    "scripts": {
        "known": [],
        "mailbox": None,
        "channels": [],
        "default_channel": "avisos",
        "checks": [],
    },
    "memory_mcp": ["mcp__engram__", "mcp__plugin_engram"],
    "scheduled_run": None,
    "thresholds": {},
    "floor": {
        "rooms": {},
        "short_names": {},
        "accessories": {},
        "external_work": {},
        "next_to_clock": None,
        "lights_off": [],
    },
}


def _merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def data_folder(explicit=None):
    """The office's common data folder: events, config, registered projects."""
    chosen = explicit or os.environ.get("AGENTS_OFFICE_DATA") or "~/.agents-office"
    return Path(os.path.expandvars(str(chosen))).expanduser()


def profile_folder(explicit=None):
    if explicit:
        return Path(explicit)
    if os.environ.get("AGENTS_OFFICE_PROFILE"):
        return Path(os.environ["AGENTS_OFFICE_PROFILE"])
    local = REPO / "local.json"
    if local.exists():
        try:
            chosen = json.loads(local.read_text(encoding="utf-8")).get("profile")
        except ValueError:
            chosen = None
        if chosen:
            path = Path(chosen)
            return path if path.is_absolute() else (REPO / path)
    return EXAMPLE


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is not None:
            return default
        raise


class Profile:
    def __init__(self, folder=None):
        self.folder = profile_folder(folder).resolve()
        self.data = _merge(DEFAULTS, read_json(self.folder / "profile.json"))
        d = self.data
        root = d.get("area_root")
        self.root = str(Path(os.path.expandvars(root)).expanduser()) if root else str(self.folder / "area")
        team = d.get("team_dir")
        if team:
            path = Path(os.path.expandvars(team)).expanduser()
            self.team = str(path if path.is_absolute() else Path(self.root) / path)
        else:
            self.team = self.root

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def file(self, name, default=None):
        """A JSON file from the profile folder (zones, flows, layout, sprites)."""
        return read_json(self.folder / name, default)

    def for_web(self):
        """What the floor needs: names, roles and texts. No area paths."""
        d = self.data
        run = d.get("scheduled_run") or {}
        return {
            "name": d["name"],
            "main_agent": d["main_agent"],
            "verifier": d["verifier"],
            "owner_label": d["owner_label"],
            "scheduled_run": {k: v for k, v in run.items() if k in ("agent", "weekday", "hour")} or None,
            "floor": d["floor"],
        }

    def for_hook(self):
        """What the capture hook needs (written to <data>/config.json by the installer)."""
        d = self.data
        run = d.get("scheduled_run") or {}
        return {
            "team_dir": self.team,
            "scripts": d["scripts"]["known"],
            "mailbox": d["scripts"]["mailbox"],
            "channels": d["scripts"]["channels"],
            "default_channel": d["scripts"]["default_channel"],
            "checks": d["scripts"]["checks"],
            "origin_variable": run.get("origin_variable"),
        }
