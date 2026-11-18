"""Several offices, one per registered project.

Projects are registered with `scripts/configure.py` (or `/oficina:configurar`) in `<data>/projects.json`:

    {"projects": [{"id": "equipo-idi", "dir": "C:\\\\...\\\\equipo-idi", "profile": "C:\\\\...\\\\profile"}]}

`<data>` is the office's common folder (AGENTS_OFFICE_DATA or ~/.agents-office). All projects share the
events folder: the hook tags every event with its project id. Each project has its own profile (zones,
layout, flows, boards) and its own snapshot.

Without registered projects the office shows a single profile (the one from `--profile`,
AGENTS_OFFICE_PROFILE, local.json or the example), as before.

projects.json is checked on every cycle: registering, moving or removing a project takes effect without
restarting the server (the page picks it up when reloaded).
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
        # With --profile the office is that profile only; otherwise projects.json is followed while running
        self.fixed = profile
        self.reader = None
        self.offices = {}
        self._stamp = None
        self.reload()

    def registry_stamp(self):
        try:
            st = (self.data / "projects.json").stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def reload(self):
        """Builds the offices from projects.json when it changed (registered, moved or removed projects).

        An office whose id, folder and profile are the same is kept as is (with its state); a changed one is
        rebuilt. Without projects, the single-profile office."""
        if self.fixed is not None and self.offices:
            return False
        stamp = self.registry_stamp()
        if self.offices and stamp == self._stamp:
            return False
        self._stamp = stamp
        projects = [] if self.fixed is not None else read_projects(self.data)
        offices = {}
        reader = self.reader or EventReader(self.data / "events")
        for p in projects:
            old = self.offices.get(p["id"])
            if old is not None and getattr(old, "registered", None) == (p["dir"], p["profile"]):
                offices[p["id"]] = old
                continue
            try:
                office = Office(data=self.data, profile=Profile(p["profile"]), team_dir=p["dir"],
                                project=p["id"], reader=reader)
            except Exception as error:  # one broken project does not take down the others
                print(f"[office] project {p['id']} skipped: {type(error).__name__}: {error}")
                continue
            office.registered = (p["dir"], p["profile"])
            offices[p["id"]] = office
        if offices:
            self.reader = reader
        else:  # no projects (or none could be built): the single-profile office
            self.reader = None
            old = self.offices.get("office")
            keep = old is not None and old.project is None
            offices["office"] = old if keep else Office(data=self.data, profile=self.fixed)
        retired = [o for i, o in self.offices.items() if offices.get(i) is not o]
        self.offices = offices
        for o in retired:  # their streams end and the page reconnects to the current office
            with o.changed:
                o.version += 1
                o.changed.notify_all()
        return True

    def is_current(self, office):
        return any(o is office for o in self.offices.values())

    @classmethod
    def of_one(cls, office):
        """Wraps an already built Office (tests, single-profile mode)."""
        self = cls.__new__(cls)
        self.data = office.data
        self.fixed = office.profile.folder
        self.reader = None
        self.offices = {"office": office}
        self._stamp = None
        return self

    def update(self, now=None, force=False):
        if self.reload():
            force = True
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
