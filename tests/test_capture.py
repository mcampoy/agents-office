"""Tests of the capture hook. They run the script as a process, like Claude Code does.

Usage: py -3 -m unittest discover -s tests -v
"""
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from server.profile import Profile  # noqa: E402

HOOK = REPO / "plugin" / "hooks" / "capture.py"
PROFILE = REPO / "profiles" / "example"
SECRET = "SECRET-MUST-NOT-APPEAR"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "data"
        self.team = root / "area" / "equipo"
        self.team.mkdir(parents=True)
        self.data.mkdir()
        # The config the installer generates from the example profile, with the test's team folder
        hook = Profile(PROFILE).for_hook()
        hook.pop("team_dir")
        config = {"projects": [{"id": "example", "dir": str(self.team), **hook}]}
        (self.data / "config.json").write_text(json.dumps(config), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def environment(self, project=None, extra=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OFICINA_CORRIDA", "CLAUDE_PROJECT_DIR", "AGENTS_OFFICE_DATA")}
        env.update({"AGENTS_OFFICE_DATA": str(self.data), "CLAUDE_PROJECT_DIR": str(project or self.team), **(extra or {})})
        return env

    def run_hook(self, payload, environment=None, raw=None, project=None):
        stdin = raw if raw is not None else json.dumps(payload).encode("utf-8")
        r = subprocess.run([sys.executable, "-I", str(HOOK)], input=stdin, capture_output=True,
                           env=self.environment(project, environment), timeout=20)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"")
        self.assertEqual(r.stderr, b"")
        return r

    def no_trace(self):
        """Neither events nor errors: the data folder only has config.json."""
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), ["config.json"])

    def event(self, name, **fields):
        base = {"session_id": "s1", "transcript_path": "x", "cwd": str(self.team),
                "permission_mode": "default", "hook_event_name": name, "prompt_id": "p1"}
        base.update(fields)
        return base

    def lines(self):
        files = list((self.data / "events").glob("*.jsonl")) if (self.data / "events").exists() else []
        text = "".join(f.read_text(encoding="utf-8") for f in files)
        return [json.loads(l) for l in text.splitlines()], text

    def last(self):
        lines, _ = self.lines()
        return lines[-1]


class Filter(Base):
    def test_without_config_nothing_is_captured(self):
        """Without <data>/config.json (the installer did not run) the team is unknown: nothing is stored."""
        (self.data / "config.json").unlink()
        self.run_hook(self.event("SessionStart", source="startup"))
        self.assertEqual(list(self.data.iterdir()), [])

    def test_foreign_session_leaves_no_trace(self):
        """Project outside the team: nothing in the JSONL or errors.log, even if the cwd points to the team
        or the payload is broken."""
        other = Path(self.tmp.name) / "other"
        cases = [
            json.dumps(self.event("SessionStart", source="startup")).encode(),
            json.dumps(self.event("PreToolUse", tool_name="Write", tool_use_id="t",
                                  tool_input={"file_path": "x", "content": SECRET})).encode(),
            f"{{broken {SECRET}".encode(),
            b"\xff\xfe" + SECRET.encode(),
        ]
        for raw in cases:
            self.run_hook(None, raw=raw, project=other)
        self.no_trace()

    def test_without_claude_project_dir_nothing_is_recorded(self):
        env = {k: v for k, v in self.environment().items() if k != "CLAUDE_PROJECT_DIR"}
        r = subprocess.run([sys.executable, "-I", str(HOOK)], input=json.dumps(self.event("Stop")).encode(),
                           capture_output=True, env=env, timeout=20)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        self.no_trace()

    def test_filters_by_project_not_by_cwd(self):
        """Claude may change directory: the cwd is stored as data, the filter is CLAUDE_PROJECT_DIR."""
        radar = str(Path(self.tmp.name) / "area" / "radar")
        self.run_hook(self.event("PreToolUse", cwd=radar, tool_name="Read", tool_input={"file_path": "x.md"}, tool_use_id="t1"))
        self.assertEqual(self.last()["cwd"], radar)
        self.run_hook(self.event("PreToolUse", tool_name="Read", tool_input={"file_path": "y.md"}, tool_use_id="t2"),
                      project=Path(self.tmp.name) / "other")
        self.assertEqual([l["tool_use_id"] for l in self.lines()[0]], ["t1"])

    def test_team_subfolder_counts(self):
        self.run_hook(self.event("Stop"), project=self.team / "scripts")
        self.assertEqual(len(self.lines()[0]), 1)

    def test_folder_with_similar_prefix_does_not_count(self):
        self.run_hook(self.event("SessionStart", source="startup"), project=str(self.team) + "-copy")
        self.no_trace()

    def test_event_is_tagged_with_the_project(self):
        self.run_hook(self.event("Stop"))
        self.assertEqual(self.last()["project"], "example")


class Redaction(Base):
    def test_write_only_path(self):
        self.run_hook(self.event("PreToolUse", tool_name="Write", tool_use_id="t",
                                 tool_input={"file_path": "C:/a/registry/providers/x.md", "content": SECRET}))
        self.assertEqual(self.last()["summary"], {"path": "C:/a/registry/providers/x.md"})

    def test_edit_post_without_response(self):
        self.run_hook(self.event("PostToolUse", tool_name="Edit", tool_use_id="t", duration_ms=12,
                                 tool_input={"file_path": "f.md", "old_string": SECRET, "new_string": SECRET},
                                 tool_response={"filePath": "f.md", "structuredPatch": SECRET}))
        self.assertEqual(self.last()["summary"], {"path": "f.md", "duration_ms": 12})

    def test_grep_pattern_and_path(self):
        self.run_hook(self.event("PreToolUse", tool_name="Grep", tool_use_id="t",
                                 tool_input={"pattern": "Estado", "path": "radar/"}))
        self.assertEqual(self.last()["summary"], {"pattern": "Estado", "path": "radar/"})

    def test_mailbox_never_stores_the_message(self):
        for command, channel in [
            (f'python -I equipo/scripts/notificar.py "{SECRET}"', "avisos"),
            (f'python -I "G:/x/equipo/scripts/notificar.py" --canal radar "{SECRET}"', "radar"),
            (f'cd equipo && python -I scripts\\notificar.py --canal researches "{SECRET} con \'comillas"', "researches"),
        ]:
            self.run_hook(self.event("PreToolUse", tool_name="Bash", tool_use_id="t", tool_input={"command": command}))
            self.assertEqual(self.last()["summary"], {"script": "notificar.py", "channel": channel})

    def test_unrecognizable_mailbox_call_neither(self):
        self.run_hook(self.event("PreToolUse", tool_name="PowerShell", tool_use_id="t",
                                 tool_input={"command": f"& $env:X\\notificar `\"{SECRET}`\""}))
        self.assertEqual(self.last()["summary"], {"script": "notificar.py"})

    def test_checks_keep_their_path(self):
        self.run_hook(self.event("PreToolUse", tool_name="Bash", tool_use_id="t",
                                 tool_input={"command": "python -I equipo/scripts/comprobar-citas.py data-security-governance/registry/providers/google.md"}))
        self.assertEqual(self.last()["summary"], {"script": "comprobar-citas.py", "path": "data-security-governance/registry/providers/google.md"})
        self.run_hook(self.event("PreToolUse", tool_name="Bash", tool_use_id="t",
                                 tool_input={"command": "pwsh -File equipo/.claude/skills/estilo-equipo/scripts/revisar-estilo.ps1 -Ruta radar/2026-10-28-radar.md"}))
        self.assertEqual(self.last()["summary"], {"script": "revisar-estilo.ps1", "path": "radar/2026-10-28-radar.md"})

    def test_other_team_script_only_flags(self):
        self.run_hook(self.event("PreToolUse", tool_name="Bash", tool_use_id="t",
                                 tool_input={"command": f"python -I scripts/detector-cambios.py --aplicar {SECRET}"}))
        self.assertEqual(self.last()["summary"], {"script": "detector-cambios.py", "flags": ["--aplicar"]})

    def test_common_command_120_characters(self):
        command = "git status " + "x" * 300
        self.run_hook(self.event("PreToolUse", tool_name="Bash", tool_use_id="t", tool_input={"command": command}))
        self.assertEqual(self.last()["summary"], {"command": command[:120]})

    def test_launch_without_prompt(self):
        self.run_hook(self.event("PreToolUse", tool_name="Agent", tool_use_id="t",
                                 tool_input={"subagent_type": "verificador", "description": "verificar google",
                                             "model": "opus", "prompt": SECRET, "run_in_background": True}))
        self.assertEqual(self.last()["summary"], {"subagent_type": "verificador", "description": "verificar google",
                                                  "model": "opus", "background": True})

    def test_launch_response_only_link(self):
        response = {"isAsync": True, "status": "async_launched", "agentId": "a6e6f23af10b8faed",
                    "description": "leer alfa", "resolvedModel": "claude-haiku-5-5", "prompt": SECRET,
                    "outputFile": SECRET, "content": [{"type": "text", "text": SECRET}], "handbackReport": SECRET}
        self.run_hook(self.event("PostToolUse", tool_name="Agent", tool_use_id="t", duration_ms=5,
                                 tool_input={"subagent_type": "lector", "description": "leer alfa", "prompt": SECRET},
                                 tool_response=response))
        self.assertEqual(self.last()["summary"], {"subagent_type": "lector", "description": "leer alfa",
                                                  "launched_agent": "a6e6f23af10b8faed",
                                                  "resolved_model": "claude-haiku-5-5",
                                                  "launch_status": "async_launched", "duration_ms": 5})

    def test_mcp_drive_only_id(self):
        self.run_hook(self.event("PreToolUse", tool_name="mcp__claude_ai_Google_Drive__read_file_content", tool_use_id="t",
                                 tool_input={"fileId": "1AbC", "query": SECRET}))
        self.assertEqual(self.last()["summary"], {"file": "1AbC"})

    def test_common_mcp_only_name(self):
        self.run_hook(self.event("PreToolUse", tool_name="mcp__engram__mem_search", tool_use_id="t",
                                 tool_input={"query": SECRET}))
        l = self.last()
        self.assertEqual(l["tool_name"], "mcp__engram__mem_search")
        self.assertNotIn("summary", l)

    def test_web_only_domain(self):
        self.run_hook(self.event("PreToolUse", tool_name="WebFetch", tool_use_id="t",
                                 tool_input={"url": f"https://docs.anthropic.com/x?q={SECRET}", "prompt": SECRET}))
        self.assertEqual(self.last()["summary"], {"domain": "docs.anthropic.com"})
        self.run_hook(self.event("PreToolUse", tool_name="WebSearch", tool_use_id="t", tool_input={"query": SECRET}))
        self.assertNotIn("summary", self.last())

    def test_domain_as_plain_text_and_in_browser_navigate(self):
        cases = [
            ("WebFetch", f"https://user:{SECRET}@Docs.Anthropic.com:8443/path/{SECRET}?q={SECRET}#{SECRET}", "docs.anthropic.com"),
            ("mcp__playwright__browser_navigate", f"https://openai.com/es-419/?x={SECRET}", "openai.com"),
            ("mcp__playwright__browser_navigate", "innovacionia.appcenter.ar/consentimiento", "innovacionia.appcenter.ar"),
        ]
        for tool, url, expected in cases:
            self.run_hook(self.event("PreToolUse", tool_name=tool, tool_use_id="t", tool_input={"url": url}))
            self.assertEqual(self.last()["summary"], {"domain": expected})
        self.run_hook(self.event("PreToolUse", tool_name="mcp__playwright__browser_snapshot", tool_use_id="t", tool_input={"url": "https://x.com"}))
        self.assertNotIn("summary", self.last())
        self.run_hook(self.event("PreToolUse", tool_name="WebFetch", tool_use_id="t", tool_input={"url": f"javascript:{SECRET}"}))
        self.assertNotIn("summary", self.last())
        _, text = self.lines()
        self.assertNotIn(SECRET, text)

    def test_prompt_only_length_and_origin(self):
        self.run_hook(self.event("UserPromptSubmit", prompt=SECRET))
        self.assertEqual(self.last()["summary"], {"length": len(SECRET), "origin": "user"})
        self.run_hook(self.event("UserPromptSubmit", prompt=f'<agent-message from="a1">\n{SECRET}'))
        self.assertEqual(self.last()["summary"]["origin"], "agent-message")

    def test_stop_without_last_message(self):
        for name in ("Stop", "SubagentStop"):
            self.run_hook(self.event(name, agent_id="a1", agent_type="lector", last_assistant_message=SECRET,
                                     agent_transcript_path=SECRET, stop_hook_active=False))
            self.assertNotIn("summary", self.last())

    def test_failure_without_error_text(self):
        self.run_hook(self.event("PostToolUseFailure", tool_name="Read", tool_use_id="t", tool_input={"file_path": "x"},
                                 error=SECRET, is_interrupt=False, duration_ms=3))
        self.assertEqual(self.last()["summary"], {"path": "x", "duration_ms": 3, "interrupted": False})

    def test_tasks_only_title(self):
        self.run_hook(self.event("TaskCreated", task_id="7", task_subject="Verificar Google", task_description=SECRET))
        self.assertEqual(self.last()["summary"], {"task_id": "7", "title": "Verificar Google"})

    def test_effort_object(self):
        self.run_hook(self.event("Stop", effort={"level": "high"}))
        self.assertEqual(self.last()["effort"], "high")

    def test_scheduled_run(self):
        self.run_hook(self.event("SessionStart", source="startup", agent_type="radar"), environment={"OFICINA_CORRIDA": "1"})
        self.assertEqual(self.last()["summary"], {"source": "startup", "origin": "scheduled-run"})

    def test_no_event_leaks_the_secret(self):
        for name in ("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                     "PostToolUseFailure", "PermissionRequest", "PermissionDenied", "Notification",
                     "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "Stop", "StopFailure"):
            self.run_hook(self.event(name, tool_name="Bash", tool_use_id="t", prompt=SECRET, message=SECRET,
                                     tool_input={"command": f"python notificar.py {SECRET}", "description": SECRET},
                                     tool_response=SECRET, error=SECRET, last_assistant_message=SECRET,
                                     task_subject="t", task_description=SECRET, notification_type="permission_prompt",
                                     title=SECRET))
        _, text = self.lines()
        self.assertNotIn(SECRET, text)


class NoLeak(Base):
    """A unique string in every content field never shows up in the JSONL or in errors.log."""

    def payloads(self):
        S = SECRET
        agent_response = {"status": "completed", "agentId": "a1", "resolvedModel": "m", "prompt": S,
                          "content": [{"type": "text", "text": S}], "handback": S, "handbackReport": S, "outputFile": S}
        yield self.event("UserPromptSubmit", prompt=S)
        yield self.event("UserPromptSubmit", prompt=f'<agent-message from="a1">\n[Subagent hand-back] {S}')
        yield self.event("UserPromptSubmit", prompt=f"<task-notification>{S}</task-notification>")
        yield self.event("PreToolUse", tool_name="Write", tool_use_id="t", tool_input={"file_path": "f.md", "content": S})
        yield self.event("PostToolUse", tool_name="Write", tool_use_id="t", tool_input={"file_path": "f.md", "content": S},
                         tool_response={"type": "create", "filePath": "f.md", "content": S})
        yield self.event("PreToolUse", tool_name="Edit", tool_use_id="t",
                         tool_input={"file_path": "f.md", "old_string": S, "new_string": S})
        yield self.event("PreToolUse", tool_name="MultiEdit", tool_use_id="t",
                         tool_input={"file_path": "f.md", "edits": [{"old_string": S, "new_string": S}]})
        yield self.event("PostToolUse", tool_name="Read", tool_use_id="t", tool_input={"file_path": "f.md"},
                         tool_response={"file": {"content": S}})
        yield self.event("PreToolUse", tool_name="Agent", tool_use_id="t",
                         tool_input={"subagent_type": "verificador", "description": "d", "prompt": S})
        yield self.event("PostToolUse", tool_name="Agent", tool_use_id="t",
                         tool_input={"subagent_type": "verificador", "description": "d", "prompt": S}, tool_response=agent_response)
        yield self.event("PostToolUse", tool_name="Bash", tool_use_id="t",
                         tool_input={"command": f'python -I scripts/notificar.py --canal radar "{S}"', "description": S},
                         tool_response={"stdout": S, "stderr": S})
        yield self.event("PostToolUseFailure", tool_name="Bash", tool_use_id="t", error=S,
                         tool_input={"command": f"python scripts/notificar.py '{S}'"})
        yield self.event("PermissionRequest", tool_name="Write", tool_input={"file_path": "f.md", "content": S},
                         permission_suggestions=[{"rule": S}])
        yield self.event("PermissionDenied", tool_name="Edit", tool_input={"file_path": "f.md", "new_string": S}, reason=S)
        yield self.event("PreToolUse", tool_name="SendMessage", tool_use_id="t", tool_input={"to": "partner", "message": S})
        yield self.event("PreToolUse", tool_name="mcp__claude_ai_Google_Drive__read_file_content", tool_use_id="t",
                         tool_input={"fileId": "1Ab", "content": S})
        yield self.event("PostToolUse", tool_name="mcp__engram__mem_save", tool_use_id="t",
                         tool_input={"content": S, "title": S}, tool_response=S)
        yield self.event("Notification", notification_type="permission_prompt", message=S, title=S)
        yield self.event("SubagentStop", agent_id="a1", agent_type="lector", last_assistant_message=S, agent_transcript_path=S)
        yield self.event("Stop", last_assistant_message=S, background_tasks=[S])
        yield self.event("StopFailure", error=S, error_details=S)
        yield self.event("TaskCreated", task_id="1", task_subject="Verificar", task_description=S)
        yield self.event("SessionEnd", reason="other", message=S)

    def test_jsonl_without_the_string(self):
        for payload in self.payloads():
            self.run_hook(payload)
        lines, text = self.lines()
        self.assertEqual(len(lines), len(list(self.payloads())))
        self.assertNotIn(SECRET, text)
        self.assertFalse((self.data / "errors.log").exists())

    def test_errors_log_without_the_string(self):
        # A write failure on every event (the events folder is a file): everything goes to errors.log.
        (self.data / "events").write_text("not a folder")
        for payload in self.payloads():
            self.run_hook(payload)
        log = (self.data / "errors.log").read_text(encoding="utf-8")
        self.assertEqual(len(log.splitlines()), len(list(self.payloads())))
        self.assertNotIn(SECRET, log)


class Robustness(Base):
    def test_invalid_json_exits_zero_and_does_not_store_payload(self):
        self.run_hook(None, raw=f"{{not json {SECRET}".encode())
        log = (self.data / "errors.log").read_text(encoding="utf-8")
        self.assertIn("JSONDecodeError", log)
        self.assertNotIn(SECRET, log)

    def test_invalid_utf8(self):
        self.run_hook(None, raw=b'{"hook_event_name": "\xff\xfe' + SECRET.encode() + b'"}')
        self.assertNotIn(SECRET, (self.data / "errors.log").read_text(encoding="utf-8"))

    def simultaneous(self, n=50):
        """n processes started before getting their payload; then all are fed together.
        Long lines (~2 KB) so a split write would show."""
        long_path = "registry/providers/" + "x" * 1900 + ".md"
        processes = [subprocess.Popen([sys.executable, "-I", str(HOOK)], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.environment())
                     for _ in range(n)]
        payloads = [json.dumps(self.event("PreToolUse", tool_name="Write", tool_use_id=f"t{i}",
                                          tool_input={"file_path": f"{i}-{long_path}"})).encode() for i in range(n)]
        with concurrent.futures.ThreadPoolExecutor(n) as pool:
            outputs = list(pool.map(lambda pc: pc[0].communicate(pc[1], timeout=60), zip(processes, payloads)))
        self.assertTrue(all(p.returncode == 0 for p in processes))
        self.assertTrue(all(o == (b"", b"") for o in outputs))
        text = (next((self.data / "events").glob("*.jsonl"))).read_text(encoding="utf-8")
        lines = [json.loads(l) for l in text.splitlines()]  # fails if any line was split or mixed
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(sorted(l["tool_use_id"] for l in lines), sorted(f"t{i}" for i in range(n)))
        for l in lines:
            self.assertEqual(l["summary"]["path"], f"{l['tool_use_id'][1:]}-{long_path}"[:200])

    def test_50_simultaneous_writes(self):
        self.simultaneous(50)

    @unittest.skipUnless(os.name == "nt", "the FILE_APPEND_DATA fallback is Windows only")
    def test_50_simultaneous_without_lock(self):
        """With the lock held by another process, all write without it (after waiting): the
        FILE_APPEND_DATA handle still gives whole lines."""
        import msvcrt
        events = self.data / "events"
        events.mkdir()
        from datetime import date
        with open(events / f"{date.today().isoformat()}.jsonl.lock", "a+b") as lock:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                self.simultaneous(50)
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

    def test_prune_14_days(self):
        events = self.data / "events"
        events.mkdir()
        (events / "2020-01-01.jsonl").write_text("{}\n")
        self.run_hook(self.event("SessionStart", source="startup"))
        self.assertFalse((events / "2020-01-01.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
