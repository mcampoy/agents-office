"""The team's agents and skills, read-only from <team folder>/.claude.

Each cycle only lists the folder and reads modification times. Definition contents come from the area
cache (read when an event names the file, or in the 5-minute sweep).

- New agent: shows up (in the reception if zones.json has no zone for it).
- Deleted agent: stays as a vacancy, with its history.
- Definition modified after the SessionStart of an open session: restart notice.
"""
import datetime as dt
from pathlib import Path

from .model import zone_of
from .util import frontmatter


class Catalog:
    def __init__(self, team_dir, zones, area):
        self.team = Path(team_dir)
        self.zones = zones
        self.area = area
        self.prefix = self.team.relative_to(area.root).as_posix()
        self.agents = {}
        self.skills = {}

    def _zone(self, name):
        return zone_of(name, self.zones.get("rules", []), self.zones.get("generic", []),
                       self.zones.get("generic_zone", "floating"), self.zones.get("unzoned_zone", "reception"))

    def scan(self):
        folder = self.team / ".claude" / "agents"
        seen = set()
        if folder.is_dir():
            for path in sorted(folder.glob("*.md")):
                try:
                    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone()
                except OSError:
                    continue
                fields = frontmatter(self.area.text(f"{self.prefix}/.claude/agents/{path.name}") or "")
                name = fields.get("name") or path.stem
                seen.add(name)
                previous = self.agents.get(name, {})
                zone, unzoned = self._zone(name)
                self.agents[name] = {
                    "name": name,
                    "file": f"{self.prefix}/.claude/agents/{path.name}",
                    "description": fields.get("description"),
                    "model": fields.get("model"),
                    "effort": fields.get("effort"),
                    "tools": [t.strip() for t in fields.get("tools", "").split(",") if t.strip()] or None,
                    "modified": mtime,
                    "zone": zone,
                    "unzoned": unzoned,
                    "vacant": False,
                    "seen_since": previous.get("seen_since") or mtime,
                }
        for name, agent in self.agents.items():
            if name not in seen:
                agent["vacant"] = True
        folder = self.team / ".claude" / "skills"
        self.skills = {}
        if folder.is_dir():
            for path in sorted(folder.glob("*/SKILL.md")):
                fields = frontmatter(self.area.text(f"{self.prefix}/.claude/skills/{path.parent.name}/SKILL.md") or "")
                name = fields.get("name") or path.parent.name
                self.skills[name] = {"name": name, "description": fields.get("description"),
                                     "file": f"{self.prefix}/.claude/skills/{path.parent.name}/SKILL.md"}
        return self

    def frontmatters(self):
        return {n: a for n, a in self.agents.items() if not a["vacant"]}

    def restart_notices(self, sessions):
        """Definitions modified after the start of an open team session."""
        notices = []
        for s in sessions:
            if s.get("end") or not s.get("start"):
                continue
            start = dt.datetime.fromisoformat(s["start"])
            changed = sorted(n for n, a in self.agents.items() if a["modified"] > start)
            if changed:
                notices.append({"session": s["id"], "agents": changed})
        return notices

    def snapshot(self):
        return {
            "agents": [{**a, "modified": a["modified"].isoformat(timespec="seconds"),
                        "seen_since": a["seen_since"].isoformat(timespec="seconds")}
                       for a in sorted(self.agents.values(), key=lambda a: a["name"])],
            "skills": sorted(self.skills.values(), key=lambda s: s["name"]),
        }
