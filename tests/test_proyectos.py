"""Varios proyectos: configurar.py los registra, el hook marca cada evento con su proyecto y el servidor
arma una oficina por proyecto.

Uso: py -3 -m unittest discover -s tests -v
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
from servidor.oficinas import Oficinas  # noqa: E402

HOOK = REPO / "plugin" / "hooks" / "captura.py"
CONFIGURAR = REPO / "scripts" / "configurar.py"


class VariosProyectos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        raiz = Path(self.tmp.name)
        self.datos = raiz / "datos"
        self.a = raiz / "proyecto-a"
        self.b = raiz / "proyecto-b"
        self.ajeno = raiz / "otro"
        for p in (self.a, self.b, self.ajeno):
            (p / ".claude" / "agents").mkdir(parents=True)
        (self.a / ".claude" / "agents" / "lente-legal.md").write_text("---\nname: lente-legal\n---\n", encoding="utf-8")
        (self.b / "pendientes.md").write_text("# P\n\n## Siguen\n- [ ] algo que ya estaba\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def configurar(self, carpeta, *extra):
        r = subprocess.run([sys.executable, str(CONFIGURAR), str(carpeta), "--datos", str(self.datos), *extra],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def hook(self, proyecto, evento):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "AGENTS_OFFICE_DATOS")}
        env["CLAUDE_PROJECT_DIR"] = str(proyecto)
        datos = {"hook_event_name": evento, "session_id": f"s-{proyecto.name}", "cwd": str(proyecto),
                 "agent_type": "principal"}
        r = subprocess.run([sys.executable, "-I", str(HOOK), "--datos", str(self.datos)], input=json.dumps(datos).encode(),
                           capture_output=True, env=env, timeout=30)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))

    def test_plan_no_escribe_nada(self):
        salida = self.configurar(self.a)
        self.assertIn("Plan solamente", salida)
        self.assertFalse(self.datos.exists())
        self.assertFalse((self.a / "pendientes.md").exists())

    def test_cada_proyecto_ve_lo_suyo(self):
        self.configurar(self.a, "--aplicar")
        self.configurar(self.b, "--aplicar")
        # Tablones: en a se crean los dos; en b se respeta el pendientes.md que ya había
        self.assertTrue((self.a / "pendientes.md").exists() and (self.a / "fricciones.md").exists())
        self.assertIn("algo que ya estaba", (self.b / "pendientes.md").read_text(encoding="utf-8"))
        self.assertFalse((self.a / "CLAUDE.md").exists())  # sin --claude-md no se toca
        self.hook(self.a, "SessionStart")
        self.hook(self.b, "SessionStart")
        self.hook(self.b, "UserPromptSubmit")
        self.hook(self.ajeno, "SessionStart")  # no registrado: sin rastro
        eventos = [json.loads(l) for f in (self.datos / "eventos").glob("*.jsonl")
                   for l in f.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted(e["proyecto"] for e in eventos), ["proyecto-a", "proyecto-b", "proyecto-b"])
        oficinas = Oficinas(datos=self.datos)
        oficinas.actualizar(forzar=True)
        self.assertEqual(set(oficinas.oficinas), {"proyecto-a", "proyecto-b"})
        sesiones = {i: [s["id"] for s in o.foto["sesiones"]] for i, o in oficinas.oficinas.items()}
        self.assertEqual(sesiones, {"proyecto-a": ["s-proyecto-a"], "proyecto-b": ["s-proyecto-b"]})
        b = oficinas.oficinas["proyecto-b"].foto["tablones"]["pendientes"]
        self.assertEqual([i["titulo"] for i in b["siguen"]], ["algo que ya estaba"])
        self.assertEqual(oficinas.elegir("proyecto-a").proyecto, "proyecto-a")
        self.assertEqual({p["id"] for p in oficinas.lista()}, {"proyecto-a", "proyecto-b"})

    def test_claude_md_una_sola_vez_y_baja(self):
        self.configurar(self.a, "--aplicar", "--claude-md")
        self.configurar(self.a, "--aplicar", "--claude-md")
        self.assertEqual((self.a / "CLAUDE.md").read_text(encoding="utf-8").count("<!-- oficina:tablones -->"), 1)
        self.configurar(self.a, "--quitar")
        self.hook(self.a, "SessionStart")
        self.assertFalse((self.datos / "eventos").exists())


if __name__ == "__main__":
    unittest.main()
