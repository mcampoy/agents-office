"""Several offices, one per registered project.

Projects are registered with `scripts/configure.py` (or `/oficina:configurar`) in `<data>/projects.json`:

    {"projects": [{"id": "equipo-idi", "dir": "C:\\\\...\\\\equipo-idi", "profile": "C:\\\\...\\\\profile"}]}

`<data>` is the office's common folder (AGENTS_OFFICE_DATA or ~/.agents-office). All projects share the
events folder: the hook tags every event with its project id. Each project has its own profile (zones,
layout, flows, boards) and its own snapshot.

Without registered projects the office shows a single profile (the one from `--profile`,
AGENTS_OFFICE_PROFILE, local.json or the example), as before.
"""
import datetime as dt
import json
from pathlib import Path

from .events import EventReader
from .office import Office
from .profile import Profile, data_folder


def read_projects(data):
    try:
        registry = json.loads((Path(data) / "projects.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in registry.get("projects", []) if p.get("id") and p.get("dir") and p.get("profile")]


class Offices:
    def __init__(self, data=None, profile=None):
        self.data = data_folder(data)
        projects = [] if profile else read_projects(self.data)
        self.offices = {}
        if projects:
            self.reader = EventReader(self.data / "events")
            for p in projects:
                self.offices[p["id"]] = Office(data=self.data, profile=Profile(p["profile"]), team_dir=p["dir"],
                                               project=p["id"], reader=self.reader)
        else:
            self.reader = None
            self.offices["office"] = Office(data=data, profile=profile)

    @classmethod
    def of_one(cls, office):
        """Wraps an already built Office (tests, single-profile mode)."""
        self = cls.__new__(cls)
        self.data = office.data
        self.reader = None
        self.offices = {"office": office}
        return self

    def update(self, now=None, force=False):
        if self.reader is not None:
            now = now or dt.datetime.now().astimezone()
            has_new = self.reader.read_new(now.date()) > 0
            for o in self.offices.values():
                o.update(now, force=force, has_new=has_new)
        else:
            for o in self.offices.values():
                o.update(now, force=force)

    def last_event(self, office):
        sessions = (office.snapshot or {}).get("sessions") or []
        return max((s.get("last_event") or "" for s in sessions), default="")

    def pick(self, ident=None):
        """The requested office or, if none is requested, the project with the latest activity."""
        if ident and ident in self.offices:
            return self.offices[ident]
        return max(self.offices.values(), key=self.last_event)

    def listing(self):
        out = []
        for ident, o in self.offices.items():
            snap = o.snapshot or {}
            active = sum(1 for i in snap.get("instances", []) if i.get("state") not in ("idle", "done"))
            out.append({"id": ident, "name": o.profile["name"], "last_event": self.last_event(o) or None,
                        "active": active})
        return sorted(out, key=lambda p: p["last_event"] or "", reverse=True)
