"""One project's office: builds the full snapshot from events, catalog, flows and team files."""
import datetime as dt
import hashlib
import json
import os
import threading
import time
from pathlib import Path

from . import boards
from .area import Area
from .candidates import Candidates
from .catalog import Catalog
from .events import EventReader
from .flows import Flows
from .model import Model, next_scheduled_run, zone_of
from .profile import Profile, data_folder
from .util import inside, relative_to_area

CATALOG_EVERY_S = 5
SWEEP_EVERY_S = 300
REBUILD_EVERY_S = 10
SCHEDULED_ORIGIN = "scheduled-run"


class Office:
    """The office of one project. With `project` (and a shared `reader`) it keeps only its own events:
    the ones the hook tagged with its id or, for old untagged events, the ones from its folder."""

    def __init__(self, data=None, profile=None, area_root=None, team_dir=None, project=None, reader=None):
        self.profile = profile if isinstance(profile, Profile) else Profile(profile)
        self.config = self.profile.data
        # The profile folder: zones, flows, layout and sprites come from there, and the editor saves there
        self.config_dir = self.profile.folder
        self.data = Path(data) if data else data_folder()
        self.root = area_root or self.profile.root
        self.team = team_dir or self.profile.team
        self.zones = self.profile.file("zones.json", {})
        self.files = self.profile["files"]
        self.area = Area(self.root, roots=self.profile["roots"], remember=self.files.get("remember"),
                         status=self.files.get("status"))
        self.flows = Flows(self.profile.file("flows.json", {}), self.area)
        self.catalog = Catalog(self.team, self.zones, self.area)
        self.project = project
        self.reader = reader or EventReader(self.data / "events")
        self.candidates = Candidates(self.data / "events", self.is_mine)
        self.thresholds = self.config.get("thresholds", {})
        self._known = []
        self._swept_at = None
        self._refreshed = set()
        self._catalog_at = 0
        self._rebuilt_at = 0
        self._fingerprint = None
        self.version = 0
        self.snapshot = None
        self.changed = threading.Condition()

    # --- Cycle -----------------------------------------------------------------------

    def is_mine(self, event):
        if not self.project:
            return True
        tag = event.get("project")
        if tag:
            return tag == self.project
        return inside(event.get("cwd"), self.team)

    def events(self):
        return [e for e in self.reader.events if self.is_mine(e)] if self.project else self.reader.events

    def update(self, now=None, force=False, has_new=None):
        """Reads what is new and rebuilds if needed. Returns True if the snapshot changed.
        With a shared reader, its owner reads and passes `has_new`."""
        now = now or dt.datetime.now().astimezone()
        clock = time.monotonic()
        if has_new is None:
            has_new = self.reader.read_new(now.date()) > 0
        sweep = self._swept_at is None or clock - self._swept_at > SWEEP_EVERY_S
        if sweep:
            self.sweep()
            self._swept_at = clock
        if force or sweep or clock - self._catalog_at > CATALOG_EVERY_S:
            self.catalog.scan()
            self._catalog_at = clock
        if not (force or sweep or has_new or self.snapshot is None or clock - self._rebuilt_at > REBUILD_EVERY_S):
            return False
        self._rebuilt_at = clock
        snapshot = self.build(now)
        fingerprint = hashlib.sha1(json.dumps({k: v for k, v in snapshot.items() if k != "generated"}, sort_keys=True,
                                              default=str).encode()).hexdigest()
        if fingerprint == self._fingerprint:
            return False
        with self.changed:
            self._fingerprint = fingerprint
            self.version += 1
            snapshot["version"] = self.version
            self.snapshot = snapshot
            self.changed.notify_all()
        return True

    def sweep(self):
        """Every 5 minutes: lists the allowlist and reads what changed (headers, team files)."""
        self.area.sweep()
        self._known = sorted(set(self.area.cached()))

    def known(self):
        return sorted(set(self._known) | set(self.area.cached()))

    def refresh_named(self, writes):
        """Reads only the paths a new event named (each write is refreshed once)."""
        for w in writes:
            key = (w["path"], w["ts"])
            if key not in self._refreshed:
                self._refreshed.add(key)
                self.area.refresh(w["path"])

    # --- Snapshot -------------------------------------------------------------------------

    def _zone(self, type_, general=False):
        return zone_of(type_, self.zones.get("rules", []), self.zones.get("generic", []),
                       self.zones.get("generic_zone", "floating"), self.zones.get("unzoned_zone", "reception"), general)

    def build(self, now):
        agents = self.catalog.frontmatters()
        context = {
            "area_root": self.root,
            "relative": lambda path, cwd: relative_to_area(path, self.root, cwd),
            "is_document": self.flows.is_document,
            "agents": agents,
            "generic": self.zones.get("generic", []),
            "thresholds": self.thresholds,
            "scripts": self.profile["scripts"],
            "memory_mcp": self.profile["memory_mcp"],
        }
        model = Model(context).apply(self.events())
        self.refresh_named(model.writes)
        snap = model.snapshot(now)
        for inst in snap["instances"]:
            zone, unzoned = self._zone(inst["type"], inst["general"])
            inst["zone"], inst["unzoned"] = zone, unzoned
            inst["role"] = (agents.get(inst["type"]) or {}).get("description")
        tasks = self.entries("tasks")
        flows = self.flows.build(snap, model.writes, model.drive_operations, tasks, self.known(), model.labels())
        open_sessions = [s for s in snap["sessions"] if not s["end"]]
        # The current session is the one the owner talked to last (its main agent is the orchestrator); not the one
        # with the newest event, which alternates when two sessions work at once. One without prompts counts from
        # its start (a terminal just opened)
        current = (sorted([s for s in open_sessions if s["origin"] != SCHEDULED_ORIGIN],
                          key=lambda s: s["last_user_prompt"] or s["start"] or s["last_event"])
                   or sorted(snap["sessions"], key=lambda s: s["last_event"]) or [None])[-1]
        main = next((i for i in snap["instances"] if current and i["main"] and i["session"] == current["id"]), None)
        notices = self.catalog.restart_notices(open_sessions)
        status = self.area.status()
        runs = [s for s in status if s["kind"] == "run"]
        run_sessions = [s for s in snap["sessions"] if s["origin"] == SCHEDULED_ORIGIN]
        board = self.boards(tasks, snap["session_tasks"])
        return {
            "generated": now.isoformat(timespec="seconds"),
            "main": main and {**main, "restart_notice": next((n["agents"] for n in notices if n["session"] == main["session"]), None)},
            "current_session": current,
            **snap,
            **flows,
            "notices": notices,
            "vacancies": [a["name"] for a in self.catalog.snapshot()["agents"] if a["vacant"]],
            "owner": {
                "tasks": len(board["tasks"]["in_progress"]) + len(board["tasks"]["next"]),
                "approvals": len(snap["approvals"]),
                "last_prompt": (current or {}).get("last_user_prompt"),
                "waits": [{"path": d["path"], "wait": d["owner_wait"]} for d in flows["documents"] if d["owner_wait"]],
            },
            "clock": {
                "next": self.next_run(now),
                "last": max([r["date"] for r in runs if r["date"]] + [s["start"][:10] for s in run_sessions], default=None),
                "running": any(not s["end"] for s in run_sessions),
            },
            "health": self.health(now),
            "boards": board,
            "statusline": self.statusline(now, current),
            "candidates": self.candidates.compute(
                now.date(),
                lambda type_: type_ in self.zones.get("generic", []) or (bool(agents) and type_ not in agents),
                self.known()),
        }

    def health(self, now):
        errors = self.data / "errors.log"
        recent = 0
        if errors.exists():
            limit = (now - dt.timedelta(hours=24)).isoformat(timespec="seconds")
            for line in errors.read_text(encoding="utf-8", errors="replace").splitlines():
                if line[:19] >= limit[:19]:
                    recent += 1
        return {"hook_errors_24h": recent, "discarded_lines": self.reader.discarded}

    # --- Queries -------------------------------------------------------------------------

    def save_layout(self, layout):
        """Atomic write of layout.json in the profile folder; the previous one is kept as layout.json.bak."""
        target = self.config_dir / "layout.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")
        if target.exists():
            os.replace(target, target.with_suffix(".json.bak"))
        os.replace(temporary, target)

    def statusline(self, now, current_session):
        """The latest the statusline (plugin/statusline/wrapper.mjs) saw of this project: model, effort,
        context and limits. Prefers the current session; ignores snapshots older than 12 hours."""
        folder = self.data / "statusline"
        if not folder.is_dir():
            return None
        limit = time.time() - 12 * 3600
        candidates = []
        for path in folder.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
                if mtime < limit:
                    if mtime < time.time() - 7 * 86400:
                        path.unlink(missing_ok=True)
                    continue
                snap = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if self.project and snap.get("project") != self.project:
                continue
            candidates.append(snap)
        if not candidates:
            return None
        session_id = (current_session or {}).get("id")
        chosen = next((s for s in candidates if session_id and s.get("session") == session_id), None) \
            or max(candidates, key=lambda s: s.get("ts") or "")
        try:
            age = (now - dt.datetime.fromisoformat(chosen["ts"].replace("Z", "+00:00"))).total_seconds()
        except (KeyError, ValueError, TypeError):
            age = None
        return {**chosen, "seconds": int(age) if age is not None else None}

    def boards(self, tasks, session_tasks):
        tasks_path = self.files.get("tasks")
        text = self.area.text(tasks_path) if tasks_path else None
        return {
            "tasks": {"path": tasks_path, **boards.tasks(text, tasks, session_tasks)},
            "audits": {"path": self.files.get("frictions"), **boards.audits(self.entries("frictions"))},
        }

    def entries(self, which):
        """The team's tasks, frictions or decisions file, if the profile defines it."""
        path = self.files.get(which)
        return self.area.entries(path) if path else {"path": None, "entries": []}

    def next_run(self, now):
        run = self.profile.get("scheduled_run")
        if not run:
            return None
        return next_scheduled_run(now, run.get("weekday", 2), run.get("hour", 10)).isoformat(timespec="minutes")

    def config_json(self, name):
        """A file from the profile folder (layout or sprites). If missing, FileNotFoundError -> 404."""
        with open(self.config_dir / name, encoding="utf-8") as f:
            return json.load(f)

    def team_files(self):
        return {
            "tasks": self.entries("tasks"),
            "frictions": self.entries("frictions"),
            "decisions": self.entries("decisions"),
            "remember": self.area.remember(),
            "status": self.area.status(),
            "catalog": self.catalog.snapshot(),
        }
