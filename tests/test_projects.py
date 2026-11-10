"""Several projects: configure.py registers them, the hook tags every event with its project and the server
builds one office per project.

Usage: py -3 -m unittest discover -s tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from server.offices import Offices  # noqa: E402

HOOK = REPO / "plugin" / "hooks" / "capture.py"
CONFIGURE = REPO / "scripts" / "configure.py"


class SeveralProjects(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "data"
        self.a = root / "project-a"
        self.b = root / "project-b"
        self.foreign = root / "other"
        for p in (self.a, self.b, self.foreign):
            (p / ".claude" / "agents").mkdir(parents=True)
        (self.a / ".claude" / "agents" / "lente-legal.md").write_text("---\nname: lente-legal\n---\n", encoding="utf-8")
        (self.b / "pendientes.md").write_text("# P\n\n## Siguen\n- [ ] algo que ya estaba\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def configure(self, folder, *extra):
        r = subprocess.run([sys.executable, str(CONFIGURE), str(folder), "--data", str(self.data), *extra],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def hook(self, project, event):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "AGENTS_OFFICE_DATA")}
        env["CLAUDE_PROJECT_DIR"] = str(project)
        payload = {"hook_event_name": event, "session_id": f"s-{project.name}", "cwd": str(project),
                   "agent_type": "main"}
        r = subprocess.run([sys.executable, "-I", str(HOOK), "--data", str(self.data)], input=json.dumps(payload).encode(),
                           capture_output=True, env=env, timeout=30)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))

    def test_plan_writes_nothing(self):
        output = self.configure(self.a)
        self.assertIn("Plan solamente", output)
        self.assertFalse(self.data.exists())
        self.assertFalse((self.a / "pendientes.md").exists())

    def test_each_project_sees_its_own(self):
        self.configure(self.a, "--apply")
        self.configure(self.b, "--apply")
        # Boards: both are created in a; in b the existing pendientes.md is kept
        self.assertTrue((self.a / "pendientes.md").exists() and (self.a / "fricciones.md").exists())
        self.assertIn("algo que ya estaba", (self.b / "pendientes.md").read_text(encoding="utf-8"))
        self.assertFalse((self.a / "CLAUDE.md").exists())  # without --claude-md it is not touched
        zones = json.loads((self.data / "profiles" / "project-a" / "zones.json").read_text(encoding="utf-8"))
        self.assertIn({"agent": "lente-*", "zone": "reading"}, zones["rules"])
        # Built-in subagents go to the room of what they do, after the project's own rules
        self.assertIn({"agent": "Explore", "zone": "exploration"}, zones["rules"])
        self.assertIn({"agent": "general-purpose", "zone": "base"}, zones["rules"])
        agents = [r["agent"] for r in zones["rules"]]
        self.assertLess(agents.index("lente-*"), agents.index("Explore"))
        self.hook(self.a, "SessionStart")
        self.hook(self.b, "SessionStart")
        self.hook(self.b, "UserPromptSubmit")
        self.hook(self.foreign, "SessionStart")  # not registered: no trace
        events = [json.loads(l) for f in (self.data / "events").glob("*.jsonl")
                  for l in f.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(e["project"] for e in events), ["project-a", "project-b", "project-b"])
        offices = Offices(data=self.data)
        offices.update(force=True)
        self.assertEqual(set(offices.offices), {"project-a", "project-b"})
        sessions = {i: [s["id"] for s in o.snapshot["sessions"]] for i, o in offices.offices.items()}
        self.assertEqual(sessions, {"project-a": ["s-project-a"], "project-b": ["s-project-b"]})
        b = offices.offices["project-b"].snapshot["boards"]["tasks"]
        self.assertEqual([i["title"] for i in b["next"]], ["algo que ya estaba"])
        self.assertEqual(offices.pick("project-a").project, "project-a")
        self.assertEqual({p["id"] for p in offices.listing()}, {"project-a", "project-b"})

    def test_claude_md_only_once_and_removal(self):
        self.configure(self.a, "--apply", "--claude-md")
        self.configure(self.a, "--apply", "--claude-md")
        self.assertEqual((self.a / "CLAUDE.md").read_text(encoding="utf-8").count("<!-- agents-office:boards -->"), 1)
        self.configure(self.a, "--remove")
        self.hook(self.a, "SessionStart")
        self.assertFalse((self.data / "events").exists())


if __name__ == "__main__":
    unittest.main()
