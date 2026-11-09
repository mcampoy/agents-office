"""Phase 2 tests: state model, flows, catalog, event reading, area and HTTP.

Usage: py -3 -m unittest discover -s tests -v
"""
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.area import Area, OutsideAllowlist  # noqa: E402
from server.events import EventReader  # noqa: E402
from server.flows import Flows  # noqa: E402
from server.model import Model, next_scheduled_run, zone_of  # noqa: E402
from server.office import Office  # noqa: E402
from server.profile import Profile, read_json  # noqa: E402
from server.util import header_table, relative_to_area  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PROFILE = REPO / "profiles" / "example"  # tests always use the example profile, never the local one
T0 = dt.datetime(2026, 10, 30, 10, 0, 0).astimezone()
ROOT = r"G:\area"
TEAM = ROOT + r"\equipo"


def ev(sec, event, session="s1", **fields):
    e = {"ts": (T0 + dt.timedelta(seconds=sec)).isoformat(timespec="milliseconds"), "event": event,
         "session_id": session, "cwd": TEAM}
    e.update({k: v for k, v in fields.items() if v is not None})
    return e


def main(sec, event, **fields):
    return ev(sec, event, agent_type="partner", **fields)


def sub(sec, event, agent, type_, **fields):
    return ev(sec, event, agent_id=agent, agent_type=type_, **fields)


def launch(sec, use, type_, description, model=None):
    return main(sec, "PreToolUse", tool_name="Agent", tool_use_id=use,
                summary={"subagent_type": type_, "description": description, **({"model": model} if model else {})})


def link(sec, use, type_, description, agent, model="claude-sonnet-5-5", status="async_launched"):
    return main(sec, "PostToolUse", tool_name="Agent", tool_use_id=use,
                summary={"subagent_type": type_, "description": description, "launched_agent": agent,
                         "resolved_model": model, "launch_status": status})


def model(events, **context):
    base = {"relative": lambda r, c: relative_to_area(r, ROOT, c),
            "agents": {"partner": {"model": "sonnet"}, "verificador": {"model": "opus"},
                       "investigador-proveedor": {"model": "sonnet"}},
            "generic": ["general-purpose", "Explore"],
            "scripts": Profile(PROFILE)["scripts"]}
    base.update(context)
    return Model(base).apply(events)


def example_area(root):
    """An Area with the allowlist and folders of the example profile."""
    profile = Profile(PROFILE)
    return Area(root, roots=profile["roots"], remember=profile["files"]["remember"], status=profile["files"]["status"])


def instances(snap):
    return {i["key"]: i for i in snap["instances"]}


class States(unittest.TestCase):
    def test_pre_post_by_tool_use_id_and_post_before_pre(self):
        events = [
            main(0, "SessionStart", summary={"source": "startup"}),
            main(5, "PostToolUse", tool_name="Read", tool_use_id="t1", summary={"path": "a.md"}),
            main(4, "PreToolUse", tool_name="Read", tool_use_id="t1", summary={"path": "a.md"}),  # arrives later
            main(6, "PreToolUse", tool_name="Write", tool_use_id="t2", summary={"path": "b.md"}),
        ]
        m = model(events)
        inst = m.instances["s1:main"]
        self.assertEqual(list(inst.open_calls), ["t2"])
        snap = m.snapshot(T0 + dt.timedelta(seconds=7))
        p = instances(snap)["s1:main"]
        self.assertEqual((p["state"], p["animation"], p["tool"]), ("working", "write", "Write"))

    def test_total_disorder_gives_the_same_result(self):
        events = [
            main(0, "SessionStart"), launch(1, "u1", "verificador", "verificar google"),
            sub(2, "SubagentStart", "a1", "verificador"),
            sub(3, "PreToolUse", "a1", "verificador", tool_name="WebFetch", tool_use_id="w", summary={"domain": "google.com"}),
            sub(4, "PostToolUse", "a1", "verificador", tool_name="WebFetch", tool_use_id="w"),
            sub(5, "SubagentStop", "a1", "verificador"), main(6, "Stop"),
        ]
        now = T0 + dt.timedelta(seconds=10)
        in_order = model(events).snapshot(now)
        reversed_ = model(list(reversed(events))).snapshot(now)
        self.assertEqual(in_order["instances"], reversed_["instances"])

    def test_subagent_event_before_its_subagentstart(self):
        events = [main(0, "SessionStart"), launch(1, "u1", "verificador", "verificar x"),
                  sub(3, "SubagentStart", "a1", "verificador"),
                  sub(2.5, "PreToolUse", "a1", "verificador", tool_name="Read", tool_use_id="r", summary={"path": "x.md"})]
        i = instances(model(events).snapshot(T0 + dt.timedelta(seconds=4)))["a1"]
        self.assertEqual((i["label"], i["state"], i["animation"]), ("verificar x", "working", "read"))

    def test_permission_wait_and_resolution(self):
        base = [main(0, "SessionStart"),
                main(1, "PreToolUse", tool_name="Write", tool_use_id="t", summary={"path": "x.md"}),
                main(2, "PermissionRequest", tool_name="Write", summary={"path": "x.md"})]
        snap = model(base).snapshot(T0 + dt.timedelta(seconds=30))
        p = instances(snap)["s1:main"]
        self.assertEqual((p["state"], p["wait"]["kind"], p["seconds_in_state"]), ("waiting", "permission", 28))
        self.assertEqual(len(snap["approvals"]), 1)
        resolved = model(base + [main(9, "PostToolUse", tool_name="Write", tool_use_id="t", summary={"path": "x.md"})])
        self.assertEqual(resolved.snapshot(T0 + dt.timedelta(seconds=10))["approvals"], [])
        denied = model(base + [main(9, "PermissionDenied", tool_name="Write")])
        self.assertEqual(instances(denied.snapshot(T0 + dt.timedelta(seconds=10)))["s1:main"]["state"], "working")

    def test_permission_notification_from_a_subagent(self):
        events = [main(0, "SessionStart"), launch(1, "u", "investigador-proveedor", "x"),
                  sub(2, "SubagentStart", "a1", "investigador-proveedor"),
                  sub(3, "Notification", "a1", "investigador-proveedor", summary={"notification_type": "permission_prompt"})]
        self.assertEqual(instances(model(events).snapshot(T0 + dt.timedelta(seconds=4)))["a1"]["state"], "waiting")

    def test_error_and_recovery(self):
        events = [main(0, "SessionStart"),
                  main(1, "PreToolUse", tool_name="Bash", tool_use_id="b", summary={"command": "x"}),
                  main(2, "PostToolUseFailure", tool_name="Bash", tool_use_id="b", summary={"command": "x"})]
        self.assertEqual(instances(model(events).snapshot(T0 + dt.timedelta(seconds=5)))["s1:main"]["state"], "error")
        self.assertNotEqual(instances(model(events).snapshot(T0 + dt.timedelta(seconds=400)))["s1:main"]["state"], "error")
        continues = events + [main(6, "PreToolUse", tool_name="Read", tool_use_id="r")]
        self.assertEqual(instances(model(continues).snapshot(T0 + dt.timedelta(seconds=7)))["s1:main"]["state"], "working")

    def test_interruption_is_not_an_error(self):
        events = [main(0, "SessionStart"),
                  main(2, "PostToolUseFailure", tool_name="Bash", tool_use_id="b", summary={"interrupted": True})]
        self.assertNotEqual(instances(model(events).snapshot(T0 + dt.timedelta(seconds=3)))["s1:main"]["state"], "error")

    def test_done_and_idle(self):
        events = [main(0, "SessionStart"), main(1, "UserPromptSubmit", summary={"origin": "user"}), main(5, "Stop")]
        m = model(events)
        self.assertEqual(instances(m.snapshot(T0 + dt.timedelta(seconds=10)))["s1:main"]["state"], "done")
        self.assertEqual(instances(m.snapshot(T0 + dt.timedelta(minutes=10)))["s1:main"]["state"], "idle")

    def test_subagent_prompt_does_not_count_as_the_owners(self):
        events = [main(0, "SessionStart"), main(1, "UserPromptSubmit", summary={"origin": "user"}),
                  main(9, "UserPromptSubmit", summary={"origin": "agent-message"})]
        snap = model(events).snapshot(T0 + dt.timedelta(seconds=10))
        self.assertEqual(snap["sessions"][0]["last_user_prompt"], (T0 + dt.timedelta(seconds=1)).isoformat(timespec="seconds"))


class Launches(unittest.TestCase):
    def parallel(self, start_order, with_link=True):
        events = [main(0, "SessionStart"),
                  launch(1, "u1", "investigador-proveedor", "Anthropic"),
                  launch(1.1, "u2", "investigador-proveedor", "OpenAI")]
        for k, agent in enumerate(start_order):
            events.append(sub(2 + k * 0.1, "SubagentStart", agent, "investigador-proveedor"))
        if with_link:
            events += [link(3, "u1", "investigador-proveedor", "Anthropic", "aA"),
                       link(3.1, "u2", "investigador-proveedor", "OpenAI", "aO")]
        return instances(model(events).snapshot(T0 + dt.timedelta(seconds=4)))

    def test_queue_by_arrival_order(self):
        i = self.parallel(["aA", "aO"], with_link=False)
        self.assertEqual((i["aA"]["label"], i["aO"]["label"]), ("Anthropic", "OpenAI"))
        self.assertEqual((i["aA"]["link"], i["aA"]["number"], i["aO"]["number"]), ("queue", 1, 2))
        self.assertEqual(i["aA"]["model"], "sonnet")  # no exact link: the frontmatter one

    def test_crossed_queue_and_exact_link_fixes_it(self):
        crossed = self.parallel(["aO", "aA"], with_link=False)
        self.assertEqual(crossed["aO"]["label"], "Anthropic")  # the documented margin of error
        fixed = self.parallel(["aO", "aA"])
        self.assertEqual((fixed["aA"]["label"], fixed["aO"]["label"]), ("Anthropic", "OpenAI"))
        self.assertEqual((fixed["aA"]["link"], fixed["aA"]["model"]), ("exact", "claude-sonnet-5-5"))

    def test_exact_link_before_the_subagentstart(self):
        events = [main(0, "SessionStart"), launch(1, "u1", "verificador", "v1"),
                  launch(1.1, "u2", "verificador", "v2"),
                  link(1.5, "u2", "verificador", "v2", "b2", "claude-opus-5-5"),
                  sub(2, "SubagentStart", "b2", "verificador"), sub(2.1, "SubagentStart", "b1", "verificador")]
        i = instances(model(events).snapshot(T0 + dt.timedelta(seconds=3)))
        self.assertEqual((i["b2"]["label"], i["b1"]["label"]), ("v2", "v1"))

    def test_numbering_reuses_free_numbers(self):
        events = [main(0, "SessionStart"),
                  launch(1, "u1", "verificador", "a"), sub(2, "SubagentStart", "v1", "verificador"),
                  sub(3, "SubagentStop", "v1", "verificador"),
                  launch(4, "u2", "verificador", "b"), sub(5, "SubagentStart", "v2", "verificador"),
                  launch(5.5, "u3", "verificador", "c"), sub(6, "SubagentStart", "v3", "verificador")]
        i = instances(model(events).snapshot(T0 + dt.timedelta(seconds=7)))
        self.assertEqual((i["v2"]["number"], i["v3"]["number"]), (1, 2))

    def test_general_agent_is_temporary_and_retires(self):
        events = [main(0, "SessionStart"), launch(1, "g", "general-purpose", "resumir PDF de Tactiq", "haiku"),
                  sub(2, "SubagentStart", "g1", "general-purpose"), sub(30, "SubagentStop", "g1", "general-purpose")]
        m = model(events)
        g = instances(m.snapshot(T0 + dt.timedelta(seconds=31)))["g1"]
        self.assertEqual((g["general"], g["label"], g["model"], g["state"]), (True, "resumir PDF de Tactiq", "haiku", "done"))
        self.assertNotIn("g1", instances(m.snapshot(T0 + dt.timedelta(seconds=400))))
        self.assertEqual(len(m.snapshot(T0)["general_launches"]), 1)

    def test_objects_mailbox_checks_memory_skills(self):
        events = [main(0, "SessionStart"),
                  main(1, "PreToolUse", tool_name="Bash", tool_use_id="n", summary={"script": "notificar.py", "channel": "radar"}),
                  main(2, "PreToolUse", tool_name="Bash", tool_use_id="c", summary={"script": "comprobar-citas.py", "path": "x.md"}),
                  main(3, "PreToolUse", tool_name="mcp__engram__mem_search", tool_use_id="m"),
                  main(4, "PreToolUse", tool_name="Skill", tool_use_id="s", summary={"skill": "estilo-equipo"})]
        m = model(events)
        snap = m.snapshot(T0 + dt.timedelta(seconds=5))
        self.assertEqual(snap["objects"]["mailbox"][0]["channel"], "radar")
        self.assertEqual(snap["objects"]["checks"][0]["script"], "comprobar-citas.py")
        self.assertEqual(snap["objects"]["memory"][0]["tool"], "mem_search")
        self.assertEqual(instances(snap)["s1:main"]["skills"], ["estilo-equipo"])


class FakeArea(unittest.TestCase):
    """An area in a temporary folder, shaped like the real one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "area"
        files = {
            "data-security-governance/registry/providers/google.md":
                "# Ficha de Google\n\n| Estado | Versión | Última revisión | Estado para el cliente |\n|---|---|---|---|\n| borrador | 0.7 | 28/10/2026 | aprobada |\n\nTexto SECRETO.\n",
            "data-security-governance/research/providers/google/2026-10-30-verificacion.md":
                "# Verificación de Google\n\n| Estado | Versión | Última revisión | Rondas |\n|---|---|---|---|\n| borrador | 0.2 | 30/10/2026 | 2 |\n\n## Ronda 1, versión 0.7\n\nx\n\n## Ronda 2, versión 0.8\n\ny\n",
            "data-security-governance/drafts/internal/uso.md":
                "# Uso\n\n| Estado | Versión | Última revisión |\n|---|---|---|\n| revisado | 0.10 | 28/10/2026 |\n",
            "data-security-governance/drafts/client/uso-cliente.md":
                "# Uso clientes\n\n| Estado | Versión | Última revisión |\n|---|---|---|\n| borrador | 0.9 | 28/10/2026 |\n",
            "data-security-governance/research/drafts/2026-10-30-verificacion.md":
                "# Verificación de borradores\n\n| Estado | Versión | Última revisión | Rondas | Documentos verificados |\n|---|---|---|---|---|\n| borrador | 0.1 | 30/10/2026 | 1 | `drafts/client/uso-cliente.md` (0.9) |\n\n## Resumen\n",
            "data-security-governance/communication/charla/guion.md":
                "# Guion\n\n| Estado | Versión | Última revisión |\n|---|---|---|\n| borrador | 0.1 | 30/10/2026 |\n",
            "data-security-governance/communication/charla/imagenes.md": "# Imágenes\n",
            "radar/2026-10-30-radar.md": "# Radar\n\n| Estado | Versión | Última revisión |\n|---|---|---|\n| borrador | 0.1 | 30/10/2026 |\n",
            "equipo/pendientes.md":
                "# Pendientes\n\n| Estado | Versión | Última revisión |\n|---|---|---|\n| revisado | 0.1 | 30/10/2026 |\n\nFormato.\n\n"
                "## 2026-10-30 · Google: queda un bloqueo tras dos rondas\n\n**Qué pasó:** la ronda 2 dejó un hallazgo.\n"
                "**Qué leer:** `data-security-governance/registry/providers/google.md`.\n**Qué queda frenado:** nada.\n",
            "equipo/fricciones.md": "# Fricciones\n\n## 2026-10-26 · Algo\n\nTexto.\nRepeticiones: 3.\nPropuesta: un script.\n",
            "equipo/decisiones.md": "# Decisiones\n\nsin entradas con formato\n",
            "equipo/status/2026-10-28-corrida.md": "Equipo · corrida semanal 28/10/2026\nFuentes oficiales: sin cambios.\n",
            "equipo/.remember/now.md": "\n## 10:59 | unknown\nAlgo pasó.\n",
            "equipo/.claude/agents/partner.md": "---\nname: partner\nmodel: sonnet\neffort: medium\n---\nx\n",
            "equipo/.claude/agents/verificador.md": "---\nname: verificador\nmodel: opus\n---\nx\n",
            "equipo/.claude/agents/lente-etica.md": "---\nname: lente-etica\nmodel: sonnet\n---\nx\n",
            "equipo/.claude/agents/partner.md.antes-marco": "---\nname: viejo\n---\n",
            "equipo/.claude/skills/estilo-equipo/SKILL.md": "---\nname: estilo-equipo\ndescription: estilo\n---\n",
            "otra-carpeta/secreto.md": "# no\n",
        }
        for rel, text in files.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.area = example_area(self.root)
        self.area.sweep()

    def tearDown(self):
        self.tmp.cleanup()


class AreaAndAllowlist(FakeArea):
    def test_allowlist(self):
        self.assertIn("Ficha de Google", self.area.read("data-security-governance/registry/providers/google.md"))
        for bad in ["otra-carpeta/secreto.md", "../area/radar/2026-10-30-radar.md", "radar/../otra-carpeta/secreto.md",
                    "equipo/.claude/agents/partner.md.antes-marco", "C:/Windows/win.ini", "", "radar"]:
            with self.assertRaises(OutsideAllowlist, msg=bad):
                self.area.read(bad)

    def test_header_only_table(self):
        head = self.area.header("data-security-governance/registry/providers/google.md")
        self.assertEqual((head["title"], head["status"], head["version"], head["last_review"]), ("Ficha de Google", "borrador", "0.7", "28/10/2026"))
        self.assertNotIn("SECRETO", json.dumps(head))

    def test_rounds_and_cycles(self):
        self.assertEqual(self.area.rounds("data-security-governance/research/providers/google/2026-10-30-verificacion.md")["round"], 2)
        self.assertEqual(self.area.rounds("data-security-governance/research/drafts/2026-10-30-verificacion.md")["round"], 1)
        path = self.root / "radar" / "ciclos-verificacion.md"
        path.write_text("# V\n\n## Ronda 1\n## Ronda 2\n## Ciclo 2, ronda 1, x\n## Ciclo 2, ronda 2, y\n## Ronda 1\n", encoding="utf-8")
        self.area.refresh("radar/ciclos-verificacion.md")
        r = self.area.rounds("radar/ciclos-verificacion.md")
        self.assertEqual((r["cycle"], r["round"]), (3, 1))

    def test_search(self):
        res = self.area.search("bloqueo")
        self.assertEqual([r["path"] for r in res], ["equipo/pendientes.md"])
        self.assertEqual(self.area.search("no"), [r for r in self.area.search("no") if not r["path"].startswith("otra-carpeta")])

    def test_parsers_and_raw(self):
        p = self.area.entries("equipo/pendientes.md")
        e = p["entries"][0]
        self.assertEqual((e["date"], e["title"]), ("2026-10-30", "Google: queda un bloqueo tras dos rondas"))
        self.assertIn("Qué queda frenado", e["fields"])
        self.assertEqual(e["paths"], ["data-security-governance/registry/providers/google.md"])
        f = self.area.entries("equipo/fricciones.md")["entries"][0]
        self.assertEqual((f["fields"]["Repeticiones"], f["fields"]["Propuesta"]), ("3.", "un script."))
        d = self.area.entries("equipo/decisiones.md")
        self.assertEqual(d["entries"], [])
        self.assertIn("sin entradas", d["raw"])
        self.assertEqual(self.area.remember()[0]["entries"][0]["title"], "10:59 | unknown")
        self.assertEqual(self.area.status()[0]["kind"], "run")


class FlowsPerDocument(FakeArea):
    def setUp(self):
        super().setUp()
        self.flows = Flows(read_json(PROFILE / "flows.json"), self.area)

    def run_model(self, events, seconds=1000):
        root = str(self.root)
        m = Model({"relative": lambda r, c: relative_to_area(r, root, c), "is_document": self.flows.is_document,
                   "agents": {"verificador": {"model": "opus"}}, "generic": ["general-purpose"]}).apply(events)
        snap = m.snapshot(T0 + dt.timedelta(seconds=seconds))
        return snap, self.flows.build(snap, m.writes, m.drive_operations,
                                      self.area.entries("equipo/pendientes.md"), labels=m.labels())

    def writes(self, sec, agent, type_, rel, use):
        absolute = str(self.root / rel)
        return [sub(sec, "PreToolUse", agent, type_, tool_name="Write", tool_use_id=use, summary={"path": absolute}),
                sub(sec + 1, "PostToolUse", agent, type_, tool_name="Write", tool_use_id=use, summary={"path": absolute})]

    def test_classification(self):
        c = self.flows.classify
        self.assertEqual(c("data-security-governance/registry/providers/google.md")["type"], "ficha")
        self.assertEqual(c("data-security-governance/research/providers/google/2026-10-30-verificacion.md")["type"], "verification")
        self.assertEqual(c("researches/cessi-ai-innovation/research/2026-10-30-verificacion-web.md")["type"], "verification")
        self.assertEqual(c("researches/buzz/research/2026-10-29-informe-inicial.md")["type"], "informe")
        self.assertEqual(c("data-security-governance/research/providers/cursor/2026-10-27-panel-cursor.md")["type"], "nota")
        self.assertEqual(c("data-security-governance/regulatory/cuestiones-para-legal.md")["type"], "informe de lente")
        self.assertEqual(c("data-security-governance/communication/charla/guion.md")["type"], "guion")
        self.assertEqual(c("radar/2026-10-30-radar.md")["type"], "radar")
        for outside in ["equipo/pendientes.md", "data-security-governance/registry/providers/_plantilla.md",
                        "data-security-governance/CHANGELOG.md", "researches/buzz/README.md"]:
            self.assertIsNone(c(outside), outside)

    def test_two_verifier_rounds_and_block(self):
        card = "data-security-governance/registry/providers/google.md"
        report = "data-security-governance/research/providers/google/2026-10-30-verificacion.md"
        events = [main(0, "SessionStart"),
                  launch(1, "l1", "investigador-proveedor", "Google"), sub(2, "SubagentStart", "i1", "investigador-proveedor"),
                  *self.writes(10, "i1", "investigador-proveedor", card, "w1"), sub(20, "SubagentStop", "i1", "investigador-proveedor"),
                  launch(21, "l2", "verificador", "verificar Google"), sub(22, "SubagentStart", "v1", "verificador"),
                  *self.writes(30, "v1", "verificador", report, "w2"), sub(40, "SubagentStop", "v1", "verificador"),
                  launch(41, "l3", "investigador-proveedor", "corregir Google"), sub(42, "SubagentStart", "i2", "investigador-proveedor"),
                  *self.writes(50, "i2", "investigador-proveedor", card, "w3"), sub(60, "SubagentStop", "i2", "investigador-proveedor"),
                  launch(61, "l4", "verificador", "verificación acotada"), sub(62, "SubagentStart", "v2", "verificador"),
                  *self.writes(70, "v2", "verificador", report, "w4"), sub(80, "SubagentStop", "v2", "verificador"),
                  main(90, "Stop")]
        snap, flows = self.run_model(events)
        doc = next(d for d in flows["documents"] if d["path"] == card)
        self.assertEqual([c["label"] for c in doc["verifications"]], ["1/2", "2/2"])
        self.assertEqual({c["document_type"] for c in doc["verifications"]}, {"ficha"})
        self.assertEqual([h["action"] for h in doc["history"]], ["escribe", "verifica (ronda 1/2)", "escribe", "verifica (ronda 2/2)"])
        self.assertEqual(doc["header"]["status"], "borrador")
        self.assertTrue(doc["blocked"])
        self.assertEqual(doc["stage"], "bloqueado tras 2 rondas")
        self.assertEqual(doc["tasks"][0]["date"], "2026-10-30")
        self.assertEqual(flows["verification_summary"], {"ficha 1/2": 1, "ficha 2/2": 1})

    def test_correction_and_owner_wait(self):
        card = "data-security-governance/registry/providers/google.md"
        report = "data-security-governance/research/providers/google/2026-10-30-verificacion.md"
        tasks = self.root / "equipo" / "pendientes.md"
        tasks.write_text("# Pendientes\n\n## 2026-10-30 · Otra cosa\n\nnada\n", encoding="utf-8")
        self.area.refresh("equipo/pendientes.md")
        base = [main(0, "SessionStart"), sub(1, "SubagentStart", "v1", "verificador"),
                *self.writes(5, "v1", "verificador", report, "w1"), sub(9, "SubagentStop", "v1", "verificador")]
        _, flows = self.run_model(base)
        doc = next(d for d in flows["documents"] if d["path"] == card)
        self.assertEqual((doc["stage"], doc["owner_wait"], doc["blocked"]),
                         ("revisión del responsable", "revisión del responsable", False))
        with_correction = base + [sub(10, "SubagentStart", "i1", "investigador-proveedor"),
                                  *self.writes(12, "i1", "investigador-proveedor", card, "w2")]
        _, flows = self.run_model(with_correction, seconds=14)
        doc = next(d for d in flows["documents"] if d["path"] == card)
        self.assertEqual((doc["stage"], doc["owner_wait"]), ("corrección", None))

    def test_draft_verification_by_header(self):
        report = "data-security-governance/research/drafts/2026-10-30-verificacion.md"
        _, flows = self.run_model([main(0, "SessionStart"), sub(1, "SubagentStart", "v1", "verificador"),
                                   *self.writes(2, "v1", "verificador", report, "w")])
        paths = {d["path"]: d for d in flows["documents"]}
        # The header names only the client one: it takes priority over the mirror (which would give both).
        self.assertEqual(list(paths), ["data-security-governance/drafts/client/uso-cliente.md"])
        self.assertEqual(paths["data-security-governance/drafts/client/uso-cliente.md"]["verifications"][0]["document_type"], "borrador")

    def test_script_images_and_layout_work(self):
        script = "data-security-governance/communication/charla/guion.md"
        images = "data-security-governance/communication/charla/imagenes.md"
        events = [main(0, "SessionStart"), sub(1, "SubagentStart", "e1", "editor-comunicacion"),
                  *self.writes(2, "e1", "editor-comunicacion", script, "g"),
                  *self.writes(4, "e1", "editor-comunicacion", images, "i"),
                  sub(6, "SubagentStop", "e1", "editor-comunicacion"),
                  sub(7, "SubagentStart", "m1", "maquetador"),
                  sub(8, "PostToolUse", "m1", "maquetador", tool_name="mcp__claude_ai_Google_Drive__copy_file",
                      tool_use_id="d", summary={"file": "Plantilla del equipo"}),
                  sub(9, "SubagentStop", "m1", "maquetador")]
        snap, flows = self.run_model(events, seconds=20)
        docs = {d["path"]: d for d in flows["documents"]}
        self.assertEqual(docs[script]["owner_wait"], "revisión del responsable")
        self.assertTrue(docs[images]["external_pending"])
        self.assertEqual(docs["drive:Plantilla del equipo"]["type"], "maquetado")
        self.assertEqual(instances(snap)["m1"]["document"], "drive:Plantilla del equipo")

    def test_current_document_of_the_instance(self):
        card = "data-security-governance/registry/providers/google.md"
        snap, _ = self.run_model([main(0, "SessionStart"), sub(1, "SubagentStart", "i1", "investigador-proveedor"),
                                  *self.writes(2, "i1", "investigador-proveedor", card, "w"),
                                  *self.writes(4, "i1", "investigador-proveedor", "equipo/pendientes.md", "w2")])
        self.assertEqual(instances(snap)["i1"]["document"], card)


class CatalogAndOffice(FakeArea):
    def office(self, data):
        return Office(data=data, profile=PROFILE, area_root=str(self.root), team_dir=str(self.root / "equipo"))

    def test_catalog_zones_vacancies_and_restart(self):
        data = Path(self.tmp.name) / "data"
        (data / "events").mkdir(parents=True)
        now = dt.datetime.now().astimezone()
        e = {"ts": (now - dt.timedelta(minutes=1)).isoformat(timespec="milliseconds"), "event": "SessionStart",
             "session_id": "s9", "agent_type": "partner", "cwd": str(self.root / "equipo")}
        (data / "events" / f"{now.date().isoformat()}.jsonl").write_text(json.dumps(e) + "\n", encoding="utf-8")
        an_hour_ago = time.time() - 3600
        for definition in (self.root / "equipo" / ".claude" / "agents").glob("*.md"):
            os.utime(definition, (an_hour_ago, an_hour_ago))
        o = self.office(data)
        o.update(force=True)
        agents = {a["name"]: a for a in o.catalog.snapshot()["agents"]}
        self.assertEqual(set(agents), {"partner", "verificador", "lente-etica"})  # .antes-marco does not count
        self.assertEqual((agents["lente-etica"]["zone"], agents["lente-etica"]["unzoned"]), ("reading", False))
        self.assertIsNone(o.snapshot["main"]["restart_notice"])  # the .md files predate the session
        new = self.root / "equipo" / ".claude" / "agents" / "auditor.md"
        new.write_text("---\nname: auditor\nmodel: haiku\n---\n", encoding="utf-8")
        (self.root / "equipo" / ".claude" / "agents" / "verificador.md").unlink()
        o.update(force=True)
        agents = {a["name"]: a for a in o.catalog.snapshot()["agents"]}
        self.assertEqual((agents["auditor"]["zone"], agents["auditor"]["unzoned"]), ("reception", True))
        self.assertTrue(agents["verificador"]["vacant"])
        self.assertEqual(o.snapshot["vacancies"], ["verificador"])
        self.assertIn("auditor", o.snapshot["main"]["restart_notice"])
        self.assertEqual(o.snapshot["clock"]["last"], "2026-10-28")
        self.assertEqual(o.snapshot["owner"]["tasks"], 1)


class IncrementalReading(unittest.TestCase):
    def test_half_written_line_and_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            today = dt.date(2026, 10, 30)
            path = folder / "2026-10-30.jsonl"
            path.write_bytes(b'{"ts":"2026-10-30T10:00:00","event":"A"}\n{"ts":"2026-10-30T10:00:01","event":"B"')
            reader = EventReader(folder)
            self.assertEqual(reader.read_new(today), 1)
            with open(path, "ab") as f:
                f.write(b'}\nno es json\n{"ts":"2026-10-30T10:00:02","event":"C"}\n')
            self.assertEqual(reader.read_new(today), 2)
            self.assertEqual([e["event"] for e in reader.events], ["A", "B", "C"])
            self.assertEqual(reader.discarded, 1)
            self.assertEqual(reader.read_new(today), 0)

    def test_yesterday_and_day_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "2026-10-29.jsonl").write_text('{"ts":"2026-10-29T23:59:00","event":"A"}\n')
            (folder / "2026-10-30.jsonl").write_text('{"ts":"2026-10-30T00:01:00","event":"B"}\n')
            reader = EventReader(folder)
            reader.read_new(dt.date(2026, 10, 30))
            self.assertEqual(len(reader.events), 2)
            reader.read_new(dt.date(2026, 10, 31))
            self.assertEqual([e["event"] for e in reader.events], ["B"])


class Misc(unittest.TestCase):
    def test_zones_by_pattern(self):
        zones = read_json(PROFILE / "zones.json")
        self.assertEqual(zone_of("lente-normativa", zones["rules"], zones["generic"]), ("reading", False))
        self.assertEqual(zone_of("Explore", zones["rules"], zones["generic"]), ("floating", False))
        self.assertEqual(zone_of("nuevo", zones["rules"], zones["generic"]), ("reception", True))

    def test_next_scheduled_run(self):
        tuesday = dt.datetime(2026, 11, 3, 15, 0).astimezone()
        self.assertEqual(next_scheduled_run(tuesday).date(), dt.date(2026, 11, 4))
        wednesday_late = dt.datetime(2026, 11, 4, 11, 0).astimezone()
        self.assertEqual(next_scheduled_run(wednesday_late).date(), dt.date(2026, 11, 11))

    def test_relative_paths(self):
        self.assertEqual(relative_to_area(r"G:\area\radar\x.md", ROOT), "radar/x.md")
        self.assertEqual(relative_to_area("G:/area/radar/x.md", ROOT), "radar/x.md")
        self.assertEqual(relative_to_area("../radar/x.md", ROOT, TEAM), "radar/x.md")
        self.assertIsNone(relative_to_area(r"G:\areas\x.md", ROOT))
        self.assertIsNone(relative_to_area(r"C:\x.md", ROOT))

    def test_table_by_column_name(self):
        t = header_table(["# T", "", "| Estado | Fecha | Rondas |", "|---|---|---|", "| borrador | 26/10 | 3 |"])
        self.assertEqual(t, {"Estado": "borrador", "Fecha": "26/10", "Rondas": "3"})


class Http(FakeArea):
    def setUp(self):
        super().setUp()
        from server.web import create_server
        data = Path(self.tmp.name) / "data"
        data.mkdir()
        self.office = Office(data=data, profile=PROFILE, area_root=str(self.root), team_dir=str(self.root / "equipo"))
        self.office.update(force=True)
        self.server = create_server(self.office, 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def get(self, path, host=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        request.add_header("Host", host or f"127.0.0.1:{self.port}")
        try:
            with urllib.request.urlopen(request, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def test_endpoints(self):
        code, body = self.get("/api/state")
        self.assertEqual(code, 200)
        self.assertIn("instances", json.loads(body))
        code, body = self.get("/api/search?q=bloqueo")
        self.assertEqual(json.loads(body)["results"][0]["path"], "equipo/pendientes.md")
        code, body = self.get("/api/file?path=radar/2026-10-30-radar.md")
        self.assertEqual(code, 200)
        self.assertEqual(self.get("/api/file?path=otra-carpeta/secreto.md")[0], 403)
        self.assertEqual(self.get("/api/file?path=radar/../otra-carpeta/secreto.md")[0], 403)
        self.assertEqual(self.get("/api/file?path=radar/no-existe.md")[0], 404)
        self.assertEqual(self.get("/api/team")[0], 200)
        self.assertEqual(self.get("/api/state", host="evil.example:80")[0], 421)

    def test_stream_sends_the_snapshot(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/stream")
        with urllib.request.urlopen(request, timeout=5) as r:
            first = b""
            while b"\n\n" not in first:
                first += r.read1(4096)
        self.assertTrue(first.startswith(b"event: state\nid: "))


class RealAcceptance(unittest.TestCase):
    """The real sequence of 30/10: partner launches two investigador-proveedor in parallel (events already redacted)."""

    def setUp(self):
        path = Path(__file__).parent / "fixtures" / "acceptance-2026-10-30.jsonl"
        self.events = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
        self.m = model(self.events, agents={"partner": {"model": "sonnet"}, "investigador-proveedor": {"model": "sonnet"}})

    def ts(self, event, agent=None, tool=None, n=0):
        found = [dt.datetime.fromisoformat(e["ts"]) for e in self.events if e["event"] == event
                 and (agent is None or (e.get("agent_id") or "").startswith(agent))
                 and (tool is None or e.get("tool_name") == tool)]
        return found[n]

    def states(self, moment):
        # Replays only what the server would have seen up to that moment.
        now = moment + dt.timedelta(milliseconds=50)
        seen = [e for e in self.events if dt.datetime.fromisoformat(e["ts"]) <= now]
        m = model(seen, agents={"partner": {"model": "sonnet"}, "investigador-proveedor": {"model": "sonnet"}})
        return {(i["type"] if i["main"] else i["label"]): i["state"]
                for i in m.snapshot(now)["instances"]}

    def test_partner_stop_with_two_active_subagents(self):
        first_stop = self.ts("Stop", n=0)
        s = self.states(first_stop)
        self.assertEqual(s["partner"], "waiting_subagents")
        self.assertEqual((s["portada Anthropic"], s["portada OpenAI"]), ("working", "working"))
        # Second Stop: Anthropic already finished, OpenAI is still going.
        s = self.states(self.ts("Stop", n=1))
        self.assertEqual((s["partner"], s["portada Anthropic"], s["portada OpenAI"]),
                         ("waiting_subagents", "done", "working"))
        # Third Stop: both finished.
        s = self.states(self.ts("Stop", n=2))
        self.assertEqual(s["partner"], "done")
        self.assertEqual(self.states(self.ts("SessionEnd"))["partner"], "done")

    def test_handing_off_from_the_handback_to_the_subagentstop(self):
        for agent, label in (("a774", "portada Anthropic"), ("a3d2", "portada OpenAI")):
            handback = self.ts("PreToolUse", agent, "SubagentHandback")
            end = self.ts("SubagentStop", agent)
            self.assertEqual(self.states(handback)[label], "handing_off")
            self.assertEqual(self.states(end - dt.timedelta(milliseconds=100))[label], "handing_off")
            self.assertEqual(self.states(end)[label], "done")

    def test_link_model_and_history_labels(self):
        snap = self.m.snapshot(self.ts("SessionEnd"))
        subs = [i for i in snap["instances"] if not i["main"]]
        self.assertEqual({(i["label"], i["link"], i["model"]) for i in subs},
                         {("portada Anthropic", "exact", "claude-haiku-5-5"), ("portada OpenAI", "exact", "claude-haiku-5-5")})
        self.assertEqual({i["history_label"] for i in subs},
                         {"investigador-proveedor · portada Anthropic", "investigador-proveedor · portada OpenAI"})
        who = {a["who"] for a in snap["activity"]}
        self.assertEqual(who, {"partner", "investigador-proveedor · portada Anthropic", "investigador-proveedor · portada OpenAI"})
        self.assertFalse(any("#" in w for w in who))

    def test_subagent_replies_do_not_move_the_avatar(self):
        snap = self.m.snapshot(self.ts("SessionEnd"))
        self.assertEqual(snap["sessions"][0]["last_user_prompt"][:19], self.ts("UserPromptSubmit").isoformat()[:19])


class NewStates(unittest.TestCase):
    def test_waiting_subagents_ends_when_they_return(self):
        events = [main(0, "SessionStart"), launch(1, "u", "verificador", "v"),
                  sub(2, "SubagentStart", "v1", "verificador"), main(3, "Stop")]
        m = model(events)
        self.assertEqual(instances(m.snapshot(T0 + dt.timedelta(seconds=4)))["s1:main"]["animation"], "wait_subagents")
        m = model(events + [sub(5, "SubagentStop", "v1", "verificador")])
        self.assertEqual(instances(m.snapshot(T0 + dt.timedelta(seconds=6)))["s1:main"]["state"], "done")

    def test_history_label_without_description_uses_short_id(self):
        events = [main(0, "SessionStart"), sub(2, "SubagentStart", "abcdef1234567890", "verificador")]
        i = instances(model(events).snapshot(T0 + dt.timedelta(seconds=3)))["abcdef1234567890"]
        self.assertEqual(i["history_label"], "verificador · abcdef12")


class AmbiguousRound(FlowsPerDocument):
    def test_no_titles_nor_column_is_unknown_round(self):
        report = "data-security-governance/research/providers/google/2026-10-31-verificacion.md"
        (self.root / report).write_text("# Verificación\n\n| Estado | Versión | Última revisión |\n|---|---|---|\n| borrador | 0.1 | 31/10/2026 |\n\n## Resumen\n", encoding="utf-8")
        self.area.refresh(report)
        _, flows = self.run_model([main(0, "SessionStart"), sub(1, "SubagentStart", "v1", "verificador"),
                                   *self.writes(2, "v1", "verificador", report, "w")])
        verification = flows["verifications"][0]
        self.assertEqual((verification["round"], verification["label"], verification["conclusive"], verification["round_source"]),
                         (None, "?", False, "assumed"))
        doc = flows["documents"][0]
        self.assertEqual(doc["history"][-1]["action"], "verifica (ronda ?)")
        self.assertEqual(flows["verification_summary"], {"ficha ronda ?": 1})

    def test_more_runs_than_rounds_is_unknown_round(self):
        """Three verifiers wrote today a report that has two rounds: we do not guess which was which."""
        report = "data-security-governance/research/providers/google/2026-10-30-verificacion.md"
        events = [main(0, "SessionStart")]
        for n in (1, 2, 3):
            events += [sub(n * 10, "SubagentStart", f"v{n}", "verificador"),
                       *self.writes(n * 10 + 1, f"v{n}", "verificador", report, f"w{n}"),
                       sub(n * 10 + 5, "SubagentStop", f"v{n}", "verificador")]
        _, flows = self.run_model(events)
        self.assertEqual([c["label"] for c in flows["verifications"]], ["?", "?", "?"])
        doc = next(d for d in flows["documents"] if d["path"].endswith("registry/providers/google.md"))
        self.assertFalse(doc["blocked"])  # without a known round it is not marked "blocked after 2 rounds"
        self.assertEqual(doc["stage"], "revisión del responsable")

    def test_rounds_column_without_titles_is_conclusive(self):
        report = "data-security-governance/research/drafts/2026-10-30-verificacion.md"
        _, flows = self.run_model([main(0, "SessionStart"), sub(1, "SubagentStart", "v1", "verificador"),
                                   *self.writes(2, "v1", "verificador", report, "w")])
        c = flows["verifications"][0]
        self.assertEqual((c["label"], c["round_source"]), ("1/2", "header"))


class DriveReading(FakeArea):
    """The drive is only read when an event names the path or in the 5-minute sweep."""

    def test_read_policy(self):
        data = Path(self.tmp.name) / "data"
        (data / "events").mkdir(parents=True)
        o = Office(data=data, profile=PROFILE, area_root=str(self.root), team_dir=str(self.root / "equipo"))
        o.update(force=True)
        after_sweep = o.area.reads
        self.assertGreater(after_sweep, 0)
        # No new events: not a single extra read, even if a file changes on disk.
        radar = self.root / "radar" / "2026-10-30-radar.md"
        radar.write_text("# Radar\n\n| Estado | Versión | Última revisión |\n|---|---|---|\n| revisado | 0.2 | 30/10/2026 |\n", encoding="utf-8")
        o.update(force=True)
        self.assertEqual(o.area.reads, after_sweep)
        self.assertEqual(o.area.header("radar/2026-10-30-radar.md")["status"], "borrador")  # stale cache
        # An event that names another path: only that one is read.
        card = self.root / "data-security-governance" / "registry" / "providers" / "google.md"
        card.write_text(card.read_text(encoding="utf-8").replace("0.7", "0.8"), encoding="utf-8")
        now = dt.datetime.now().astimezone()
        e = {"ts": now.isoformat(timespec="milliseconds"), "event": "PostToolUse", "session_id": "s", "agent_id": "i1",
             "agent_type": "investigador-proveedor", "tool_name": "Write", "tool_use_id": "w", "cwd": str(self.root / "equipo"),
             "summary": {"path": str(card)}}
        (data / "events" / f"{now.date().isoformat()}.jsonl").write_text(json.dumps(e) + "\n", encoding="utf-8")
        o.update()
        self.assertEqual(o.area.reads, after_sweep + 1)
        self.assertEqual(o.area.header("data-security-governance/registry/providers/google.md")["version"], "0.8")
        # The same event does not trigger reads again.
        o.update(force=True)
        self.assertEqual(o.area.reads, after_sweep + 1)
        # The sweep (every 5 min) picks up what changed without an event: only that.
        o._swept_at -= 301
        o.update()
        self.assertEqual(o.area.reads, after_sweep + 2)
        self.assertEqual(o.area.header("radar/2026-10-30-radar.md")["status"], "revisado")

    def test_search_and_team_do_not_read_the_drive(self):
        before = self.area.reads
        self.area.search("bloqueo")
        self.area.entries("equipo/pendientes.md")
        self.area.status()
        self.area.remember()
        self.assertEqual(self.area.reads, before)


class NoCors(Http):
    def headers(self, path, method="GET"):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        request.add_header("Origin", "https://evil.example")
        request.add_header("Access-Control-Request-Method", "GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as r:
                if path == "/api/stream":
                    return r.status, dict(r.headers)
                r.read()
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers)

    def test_no_response_enables_cors(self):
        for path in ("/", "/api/state", "/api/stream", "/api/search?q=x", "/api/file?path=radar/2026-10-30-radar.md",
                     "/api/team", "/no-existe"):
            code, headers = self.headers(path)
            self.assertFalse([h for h in headers if h.lower().startswith("access-control-")], path)
        code, headers = self.headers("/api/state", method="OPTIONS")  # preflight
        self.assertGreaterEqual(code, 400)
        self.assertFalse([h for h in headers if h.lower().startswith("access-control-")])


class SaveLayout(Http):
    """POST /api/layout: the server's only write, always to a copy of config/ (never the real one)."""

    def setUp(self):
        super().setUp()
        import shutil
        self.config = Path(self.tmp.name) / "config"
        shutil.copytree(PROFILE, self.config)
        self.office.config_dir = self.config
        self.layout = json.loads((self.config / "layout.json").read_text(encoding="utf-8"))

    def post(self, body, origin="own", content_type="application/json", path="/api/layout"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method="POST")
        request.add_header("Content-Type", content_type)
        if origin:
            request.add_header("Origin", f"http://127.0.0.1:{self.port}" if origin == "own" else origin)
        try:
            with urllib.request.urlopen(request, timeout=5) as r:
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers)

    def test_saves_and_keeps_a_backup(self):
        self.layout["furniture"] = self.layout["furniture"][:-1]
        code, headers = self.post(self.layout)
        self.assertEqual(code, 200)
        self.assertFalse([h for h in headers if h.lower().startswith("access-control-")])
        saved = json.loads((self.config / "layout.json").read_text(encoding="utf-8"))
        self.assertEqual(len(saved["furniture"]), len(self.layout["furniture"]))
        self.assertTrue((self.config / "layout.json.bak").exists())
        self.assertFalse((self.config / "layout.json.tmp").exists())
        code, body = self.get("/api/layout")
        self.assertEqual(json.loads(body)["furniture"], self.layout["furniture"])

    def test_rejects_foreign_origin_type_and_invalid_layout(self):
        original = (self.config / "layout.json").read_bytes()
        self.assertEqual(self.post(self.layout, origin="https://evil.example")[0], 403)
        self.assertEqual(self.post(self.layout, origin=None)[0], 403)
        self.assertEqual(self.post(self.layout, content_type="text/plain")[0], 415)
        self.assertEqual(self.post(self.layout, path="/api/state")[0], 404)
        self.assertEqual(self.post(b"{no es json")[0], 400)
        self.assertEqual(self.post({**self.layout, "version": 2})[0], 400)
        self.assertEqual(self.post({**self.layout, "tiles": self.layout["tiles"][:-1]})[0], 400)
        self.assertEqual(self.post({**self.layout, "furniture": [{"type": "DESK_FRONT"}]})[0], 400)
        self.assertEqual(self.post({**self.layout, "areaTiles": [None]})[0], 400)
        self.assertEqual((self.config / "layout.json").read_bytes(), original)
        self.assertFalse((self.config / "layout.json.bak").exists())

    def test_generated_layout_is_valid(self):
        from server.web import validate_layout
        validate_layout(json.loads((PROFILE / "layout.json").read_text(encoding="utf-8")))


class TeamProfile(unittest.TestCase):
    """The code knows nothing about the team: everything comes from the profile folder."""

    def test_profile_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "other"
            other.mkdir()
            (other / "profile.json").write_text(json.dumps({"name": "Otro", "team_dir": "eq", "area_root": tmp}),
                                                encoding="utf-8")
            old = os.environ.get("AGENTS_OFFICE_PROFILE")
            try:
                os.environ["AGENTS_OFFICE_PROFILE"] = str(other)
                self.assertEqual(Profile().folder, other.resolve())
                self.assertEqual(Profile(PROFILE).folder, PROFILE.resolve())  # the explicit one wins
            finally:
                if old is None:
                    os.environ.pop("AGENTS_OFFICE_PROFILE", None)
                else:
                    os.environ["AGENTS_OFFICE_PROFILE"] = old
            p = Profile(other)
            self.assertEqual(p["name"], "Otro")
            self.assertEqual(Path(p.team), Path(tmp) / "eq")
            self.assertEqual(p["scripts"]["checks"], [])   # defaults for whatever it does not define
            self.assertIsNone(p["verifier"])

    def test_the_web_gets_no_area_paths(self):
        web = json.dumps(Profile(PROFILE).for_web())
        for key in ("area_root", "team_dir", "data", "files", "roots", "origin_variable"):
            self.assertNotIn(f'"{key}"', web)

    def test_office_without_flows_or_files(self):
        """A minimal profile (no flows.json nor team files) builds the snapshot anyway."""
        with tempfile.TemporaryDirectory() as tmp:
            minimal = Path(tmp) / "minimal"
            minimal.mkdir()
            (minimal / "profile.json").write_text(json.dumps({"area_root": tmp, "team_dir": "eq"}), encoding="utf-8")
            o = Office(data=Path(tmp) / "data", profile=minimal)
            o.update(force=True)
            self.assertEqual(o.snapshot["documents"], [])
            self.assertIsNone(o.snapshot["clock"]["next"])
            self.assertEqual(o.snapshot["owner"]["tasks"], 0)


class ThinkingAndIdleSubagents(unittest.TestCase):
    """Decisions of 09/11: 'thinking' between recent activity and idleness, and partner does not wait for idle ones."""

    def sequence(self):
        return [main(0, "SessionStart", summary={"source": "startup"}),
                main(1, "UserPromptSubmit", summary={"length": 10, "origin": "user"}),
                main(2, "PreToolUse", tool_name="Agent", tool_use_id="L",
                     summary={"subagent_type": "investigador-proveedor", "description": "X"}),
                main(3, "PostToolUse", tool_name="Agent", tool_use_id="L",
                     summary={"subagent_type": "investigador-proveedor", "launched_agent": "a1"}),
                sub(4, "SubagentStart", "a1", "investigador-proveedor"),
                sub(5, "PreToolUse", "a1", "investigador-proveedor", tool_name="Read", tool_use_id="r"),
                sub(6, "PostToolUse", "a1", "investigador-proveedor", tool_name="Read", tool_use_id="r"),
                main(7, "Stop")]

    def state(self, seconds, key):
        m = model(self.sequence())
        return instances(m.snapshot(T0 + dt.timedelta(seconds=seconds)))[key]

    def test_thinking_between_activity_and_idleness(self):
        self.assertEqual(self.state(60, "a1")["state"], "working")
        s = self.state(150, "a1")
        self.assertEqual((s["state"], s["animation"]), ("thinking", "think"))
        self.assertEqual(self.state(400, "a1")["state"], "idle")

    def test_partner_does_not_wait_for_idle_subagents(self):
        self.assertEqual(self.state(150, "s1:main")["state"], "waiting_subagents")  # a1 thinking
        self.assertEqual(self.state(400, "s1:main")["state"], "idle")  # a1 idle: no longer waited for


class AgentCandidate(unittest.TestCase):
    """Phase 0, item 11: 3 general launches with similar descriptions in 14 days = candidate."""

    def write(self, folder, day, descriptions, type_="general-purpose"):
        lines = [json.dumps({"ts": f"{day}T10:00:0{i}-03:00", "event": "PreToolUse", "tool_name": "Agent",
                             "summary": {"subagent_type": type_, "description": d}}) for i, d in enumerate(descriptions)]
        (folder / f"{day}.jsonl").write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    def test_group_of_three_similar(self):
        from server.candidates import Candidates
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp)
            self.write(c, "2026-11-01", ["comparar precios de APIs de modelos de OpenAI"])
            self.write(c, "2026-11-05", ["comparar precios de APIs de modelos de Mistral",
                                         "resumir noticias"])          # short: fewer than 3 useful words
            self.write(c, "2026-11-09", ["Comparar los precios de las APIs de modelos (Cohere)",
                                         "redactar correo de seguimiento al cliente"])
            self.write(c, "2026-10-01", ["comparar precios de APIs de modelos"])  # outside the 14 days
            self.write(c, "2026-11-08", ["comparar precios de APIs de modelos"], type_="investigador-proveedor")
            r = Candidates(c).compute(dt.date(2026, 11, 9), lambda t: t == "general-purpose",
                                      ["temas/registry/providers/mistral.md", "temas/registry/providers/cohere.md"])
            self.assertEqual(len(r), 1)
            self.assertEqual(r[0]["launches"], 3)
            self.assertEqual(r[0]["words"], ["apis", "comparar", "modelos", "precios"])
            self.assertEqual(r[0]["types"], ["general-purpose"])

    def test_two_are_not_enough(self):
        from server.candidates import Candidates
        with tempfile.TemporaryDirectory() as tmp:
            self.write(Path(tmp), "2026-11-09", ["comparar precios de APIs de modelos"] * 2)
            self.assertEqual(Candidates(tmp).compute(dt.date(2026, 11, 9), lambda t: True), [])


class Boards(unittest.TestCase):
    """The tasks and audits boards, with the standard format and with the dated-entries one."""

    def test_tasks_with_sections_and_session_tasks(self):
        from server import boards
        text = (boards.TASKS_TEMPLATE
                .replace("## En curso\n", "## En curso\n- [ ] migrar la base\n")
                .replace("## Siguen\n", "## Siguen\n- [ ] revisar permisos\n- [x] ya estaba hecha\n"))
        r = boards.tasks(text, None, [{"title": "leer pendientes", "created": "t1", "completed": None},
                                      {"title": "armar informe", "created": "t0", "completed": "t2"}])
        self.assertEqual([i["title"] for i in r["in_progress"]], ["leer pendientes", "migrar la base"])
        self.assertEqual([i["title"] for i in r["next"]], ["revisar permisos"])
        self.assertEqual([i["title"] for i in r["done"]], ["armar informe", "ya estaba hecha"])

    def test_tasks_without_sections_go_to_next(self):
        from server import boards
        entries = {"entries": [{"title": "Presentación lista", "date": "2026-11-02"}]}
        r = boards.tasks("## 2026-11-02 · Presentación lista\n", entries, [])
        self.assertEqual(r["next"][0]["title"], "Presentación lista")
        self.assertEqual(r["in_progress"], [])

    def test_empty_templates_have_no_entries(self):
        """The format guide goes in an HTML comment: it counts neither as a friction nor as a task."""
        from server import boards
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fricciones.md").write_text(boards.FRICTIONS_TEMPLATE, encoding="utf-8")
            (root / "pendientes.md").write_text(boards.TASKS_TEMPLATE, encoding="utf-8")
            area = Area(root, roots=["."])
            area.sweep()
            self.assertEqual(boards.audits(area.entries("fricciones.md")), {"open": [], "resolved": []})
            empty = boards.tasks(area.text("pendientes.md"), area.entries("pendientes.md"), [])
            self.assertEqual(empty, {"in_progress": [], "next": [], "done": []})

    def test_open_and_resolved_audits(self):
        from server import boards
        entries = {"entries": [{"title": "Permiso de Drive", "date": "2026-11-01", "fields": {"Estado": "abierta"}},
                               {"title": "Hook roto", "date": "2026-10-30", "fields": {"Estado (05/11)": "resuelta"}},
                               {"title": "Sin estado", "date": None, "fields": {}}]}
        r = boards.audits(entries)
        self.assertEqual([i["title"] for i in r["open"]], ["Permiso de Drive", "Sin estado"])
        self.assertEqual([i["title"] for i in r["resolved"]], ["Hook roto"])


if __name__ == "__main__":
    unittest.main()
