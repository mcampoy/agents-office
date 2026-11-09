"""Pruebas del hook de captura. Corren el script como proceso, igual que Claude Code.

Uso: py -3 -m unittest discover -s tests -v
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
from servidor.perfil import Perfil  # noqa: E402

HOOK = REPO / "plugin" / "hooks" / "captura.py"
PERFIL = REPO / "perfiles" / "ejemplo"
SECRETO = "SECRETO-NO-DEBE-APARECER"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        raiz = Path(self.tmp.name)
        self.datos = raiz / "datos"
        self.equipo = raiz / "area" / "equipo"
        self.equipo.mkdir(parents=True)
        self.datos.mkdir()
        # La config que el instalador genera a partir del perfil de ejemplo, con la carpeta del equipo de la prueba
        config = {**Perfil(PERFIL).para_el_hook(), "equipo_dir": str(self.equipo)}
        (self.datos / "config.json").write_text(json.dumps(config), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def entorno(self, proyecto=None, extra=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ("OFICINA_CORRIDA", "CLAUDE_PROJECT_DIR", "AGENTS_OFFICE_DATOS")}
        env.update({"AGENTS_OFFICE_DATOS": str(self.datos), "CLAUDE_PROJECT_DIR": str(proyecto or self.equipo), **(extra or {})})
        return env

    def correr(self, payload, entorno=None, crudo=None, proyecto=None):
        entrada = crudo if crudo is not None else json.dumps(payload).encode("utf-8")
        r = subprocess.run([sys.executable, "-I", str(HOOK)], input=entrada, capture_output=True,
                           env=self.entorno(proyecto, entorno), timeout=20)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"")
        self.assertEqual(r.stderr, b"")
        return r

    def sin_rastro(self):
        """Ni eventos ni errores: la carpeta de datos tiene solo config.json."""
        self.assertEqual(sorted(p.name for p in self.datos.iterdir()), ["config.json"])

    def evento(self, nombre, **campos):
        base = {"session_id": "s1", "transcript_path": "x", "cwd": str(self.equipo),
                "permission_mode": "default", "hook_event_name": nombre, "prompt_id": "p1"}
        base.update(campos)
        return base

    def lineas(self):
        archivos = list((self.datos / "eventos").glob("*.jsonl")) if (self.datos / "eventos").exists() else []
        texto = "".join(a.read_text(encoding="utf-8") for a in archivos)
        return [json.loads(l) for l in texto.splitlines()], texto

    def ultima(self):
        lineas, _ = self.lineas()
        return lineas[-1]


class Filtro(Base):
    def test_sin_config_no_captura(self):
        """Sin <datos>/config.json (el instalador no corrió) no se sabe cuál es el equipo: no se guarda nada."""
        (self.datos / "config.json").unlink()
        self.correr(self.evento("SessionStart", source="startup"))
        self.assertEqual(list(self.datos.iterdir()), [])

    def test_sesion_ajena_no_deja_rastro(self):
        """Proyecto fuera de equipo: nada en el JSONL ni en errores.log, aunque el cwd apunte al equipo
        o el payload esté roto."""
        otro = Path(self.tmp.name) / "otro"
        casos = [
            json.dumps(self.evento("SessionStart", source="startup")).encode(),
            json.dumps(self.evento("PreToolUse", tool_name="Write", tool_use_id="t",
                                   tool_input={"file_path": "x", "content": SECRETO})).encode(),
            f"{{roto {SECRETO}".encode(),
            b"\xff\xfe" + SECRETO.encode(),
        ]
        for crudo in casos:
            self.correr(None, crudo=crudo, proyecto=otro)
        self.sin_rastro()

    def test_sin_claude_project_dir_no_registra(self):
        env = {k: v for k, v in self.entorno().items() if k != "CLAUDE_PROJECT_DIR"}
        r = subprocess.run([sys.executable, "-I", str(HOOK)], input=json.dumps(self.evento("Stop")).encode(),
                           capture_output=True, env=env, timeout=20)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"", b""))
        self.sin_rastro()

    def test_filtra_por_proyecto_no_por_cwd(self):
        """Claude puede cambiar de directorio: el cwd va como dato, el filtro es CLAUDE_PROJECT_DIR."""
        radar = str(Path(self.tmp.name) / "area" / "radar")
        self.correr(self.evento("PreToolUse", cwd=radar, tool_name="Read", tool_input={"file_path": "x.md"}, tool_use_id="t1"))
        self.assertEqual(self.ultima()["cwd"], radar)
        self.correr(self.evento("PreToolUse", tool_name="Read", tool_input={"file_path": "y.md"}, tool_use_id="t2"),
                    proyecto=Path(self.tmp.name) / "otro")
        self.assertEqual([l["tool_use_id"] for l in self.lineas()[0]], ["t1"])

    def test_subcarpeta_del_equipo_cuenta(self):
        self.correr(self.evento("Stop"), proyecto=self.equipo / "scripts")
        self.assertEqual(len(self.lineas()[0]), 1)

    def test_carpeta_con_prefijo_parecido_no_cuenta(self):
        self.correr(self.evento("SessionStart", source="startup"), proyecto=str(self.equipo) + "-copia")
        self.sin_rastro()


class Redaccion(Base):
    def test_write_solo_ruta(self):
        self.correr(self.evento("PreToolUse", tool_name="Write", tool_use_id="t",
                                tool_input={"file_path": "C:/a/registry/providers/x.md", "content": SECRETO}))
        l = self.ultima()
        self.assertEqual(l["resumen"], {"ruta": "C:/a/registry/providers/x.md"})

    def test_edit_post_sin_respuesta(self):
        self.correr(self.evento("PostToolUse", tool_name="Edit", tool_use_id="t", duration_ms=12,
                                tool_input={"file_path": "f.md", "old_string": SECRETO, "new_string": SECRETO},
                                tool_response={"filePath": "f.md", "structuredPatch": SECRETO}))
        self.assertEqual(self.ultima()["resumen"], {"ruta": "f.md", "duracion_ms": 12})

    def test_grep_patron_y_ruta(self):
        self.correr(self.evento("PreToolUse", tool_name="Grep", tool_use_id="t",
                                tool_input={"pattern": "Estado", "path": "radar/"}))
        self.assertEqual(self.ultima()["resumen"], {"patron": "Estado", "ruta": "radar/"})

    def test_notificar_nunca_guarda_el_mensaje(self):
        for comando, canal in [
            (f'python -I equipo/scripts/notificar.py "{SECRETO}"', "avisos"),
            (f'python -I "G:/x/equipo/scripts/notificar.py" --canal radar "{SECRETO}"', "radar"),
            (f'cd equipo && python -I scripts\\notificar.py --canal researches "{SECRETO} con \'comillas"', "researches"),
        ]:
            self.correr(self.evento("PreToolUse", tool_name="Bash", tool_use_id="t", tool_input={"command": comando}))
            self.assertEqual(self.ultima()["resumen"], {"script": "notificar.py", "canal": canal})

    def test_notificar_irreconocible_tampoco(self):
        self.correr(self.evento("PreToolUse", tool_name="PowerShell", tool_use_id="t",
                                tool_input={"command": f"& $env:X\\notificar `\"{SECRETO}`\""}))
        self.assertEqual(self.ultima()["resumen"], {"script": "notificar.py"})

    def test_comprobar_citas_y_revisar_estilo(self):
        self.correr(self.evento("PreToolUse", tool_name="Bash", tool_use_id="t",
                                tool_input={"command": "python -I equipo/scripts/comprobar-citas.py data-security-governance/registry/providers/google.md"}))
        self.assertEqual(self.ultima()["resumen"], {"script": "comprobar-citas.py", "ruta": "data-security-governance/registry/providers/google.md"})
        self.correr(self.evento("PreToolUse", tool_name="Bash", tool_use_id="t",
                                tool_input={"command": "pwsh -File equipo/.claude/skills/estilo-equipo/scripts/revisar-estilo.ps1 -Ruta radar/2026-10-28-radar.md"}))
        self.assertEqual(self.ultima()["resumen"], {"script": "revisar-estilo.ps1", "ruta": "radar/2026-10-28-radar.md"})

    def test_otro_script_del_equipo_solo_banderas(self):
        self.correr(self.evento("PreToolUse", tool_name="Bash", tool_use_id="t",
                                tool_input={"command": f"python -I scripts/detector-cambios.py --aplicar {SECRETO}"}))
        self.assertEqual(self.ultima()["resumen"], {"script": "detector-cambios.py", "banderas": ["--aplicar"]})

    def test_comando_comun_120_caracteres(self):
        comando = "git status " + "x" * 300
        self.correr(self.evento("PreToolUse", tool_name="Bash", tool_use_id="t", tool_input={"command": comando}))
        self.assertEqual(self.ultima()["resumen"], {"comando": comando[:120]})

    def test_lanzamiento_sin_prompt(self):
        self.correr(self.evento("PreToolUse", tool_name="Agent", tool_use_id="t",
                                tool_input={"subagent_type": "verificador", "description": "verificar google",
                                            "model": "opus", "prompt": SECRETO, "run_in_background": True}))
        self.assertEqual(self.ultima()["resumen"], {"subagent_type": "verificador", "description": "verificar google",
                                                    "model": "opus", "en_segundo_plano": True})

    def test_respuesta_de_lanzamiento_solo_vinculo(self):
        respuesta = {"isAsync": True, "status": "async_launched", "agentId": "a6e6f23af10b8faed",
                     "description": "leer alfa", "resolvedModel": "claude-haiku-5-5", "prompt": SECRETO,
                     "outputFile": SECRETO, "content": [{"type": "text", "text": SECRETO}], "handbackReport": SECRETO}
        self.correr(self.evento("PostToolUse", tool_name="Agent", tool_use_id="t", duration_ms=5,
                                tool_input={"subagent_type": "lector", "description": "leer alfa", "prompt": SECRETO},
                                tool_response=respuesta))
        self.assertEqual(self.ultima()["resumen"], {"subagent_type": "lector", "description": "leer alfa",
                                                    "agente_lanzado": "a6e6f23af10b8faed",
                                                    "modelo_resuelto": "claude-haiku-5-5",
                                                    "estado_lanzamiento": "async_launched", "duracion_ms": 5})

    def test_mcp_drive_solo_id(self):
        self.correr(self.evento("PreToolUse", tool_name="mcp__claude_ai_Google_Drive__read_file_content", tool_use_id="t",
                                tool_input={"fileId": "1AbC", "query": SECRETO}))
        self.assertEqual(self.ultima()["resumen"], {"archivo": "1AbC"})

    def test_mcp_comun_solo_nombre(self):
        self.correr(self.evento("PreToolUse", tool_name="mcp__engram__mem_search", tool_use_id="t",
                                tool_input={"query": SECRETO}))
        l = self.ultima()
        self.assertEqual(l["tool_name"], "mcp__engram__mem_search")
        self.assertNotIn("resumen", l)

    def test_web_solo_dominio(self):
        self.correr(self.evento("PreToolUse", tool_name="WebFetch", tool_use_id="t",
                                tool_input={"url": f"https://docs.anthropic.com/x?q={SECRETO}", "prompt": SECRETO}))
        self.assertEqual(self.ultima()["resumen"], {"dominio": "docs.anthropic.com"})
        self.correr(self.evento("PreToolUse", tool_name="WebSearch", tool_use_id="t", tool_input={"query": SECRETO}))
        self.assertNotIn("resumen", self.ultima())

    def test_dominio_en_texto_plano_y_en_browser_navigate(self):
        casos = [
            ("WebFetch", f"https://usuario:{SECRETO}@Docs.Anthropic.com:8443/ruta/{SECRETO}?q={SECRETO}#{SECRETO}", "docs.anthropic.com"),
            ("mcp__playwright__browser_navigate", f"https://openai.com/es-419/?x={SECRETO}", "openai.com"),
            ("mcp__playwright__browser_navigate", "innovacionia.appcenter.ar/consentimiento", "innovacionia.appcenter.ar"),
        ]
        for herramienta, url, esperado in casos:
            self.correr(self.evento("PreToolUse", tool_name=herramienta, tool_use_id="t", tool_input={"url": url}))
            self.assertEqual(self.ultima()["resumen"], {"dominio": esperado})
        self.correr(self.evento("PreToolUse", tool_name="mcp__playwright__browser_snapshot", tool_use_id="t", tool_input={"url": "https://x.com"}))
        self.assertNotIn("resumen", self.ultima())
        self.correr(self.evento("PreToolUse", tool_name="WebFetch", tool_use_id="t", tool_input={"url": f"javascript:{SECRETO}"}))
        self.assertNotIn("resumen", self.ultima())
        _, texto = self.lineas()
        self.assertNotIn(SECRETO, texto)

    def test_prompt_solo_largo_y_origen(self):
        self.correr(self.evento("UserPromptSubmit", prompt=SECRETO))
        self.assertEqual(self.ultima()["resumen"], {"largo": len(SECRETO), "origen": "usuario"})
        self.correr(self.evento("UserPromptSubmit", prompt=f'<agent-message from="a1">\n{SECRETO}'))
        self.assertEqual(self.ultima()["resumen"]["origen"], "agent-message")

    def test_stop_sin_ultimo_mensaje(self):
        for nombre in ("Stop", "SubagentStop"):
            self.correr(self.evento(nombre, agent_id="a1", agent_type="lector", last_assistant_message=SECRETO,
                                    agent_transcript_path=SECRETO, stop_hook_active=False))
            self.assertNotIn("resumen", self.ultima())

    def test_falla_sin_texto_de_error(self):
        self.correr(self.evento("PostToolUseFailure", tool_name="Read", tool_use_id="t", tool_input={"file_path": "x"},
                                error=SECRETO, is_interrupt=False, duration_ms=3))
        self.assertEqual(self.ultima()["resumen"], {"ruta": "x", "duracion_ms": 3, "interrumpido": False})

    def test_tareas_solo_titulo(self):
        self.correr(self.evento("TaskCreated", task_id="7", task_subject="Verificar Google", task_description=SECRETO))
        self.assertEqual(self.ultima()["resumen"], {"task_id": "7", "titulo": "Verificar Google"})

    def test_effort_objeto(self):
        self.correr(self.evento("Stop", effort={"level": "high"}))
        self.assertEqual(self.ultima()["effort"], "high")

    def test_corrida_semanal(self):
        self.correr(self.evento("SessionStart", source="startup", agent_type="radar"), entorno={"OFICINA_CORRIDA": "1"})
        self.assertEqual(self.ultima()["resumen"], {"source": "startup", "origen": "corrida-semanal"})

    def test_ningun_evento_filtra_el_secreto(self):
        for nombre in ("SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                       "PostToolUseFailure", "PermissionRequest", "PermissionDenied", "Notification",
                       "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "Stop", "StopFailure"):
            self.correr(self.evento(nombre, tool_name="Bash", tool_use_id="t", prompt=SECRETO, message=SECRETO,
                                    tool_input={"command": f"python notificar.py {SECRETO}", "description": SECRETO},
                                    tool_response=SECRETO, error=SECRETO, last_assistant_message=SECRETO,
                                    task_subject="t", task_description=SECRETO, notification_type="permission_prompt",
                                    title=SECRETO))
        _, texto = self.lineas()
        self.assertNotIn(SECRETO, texto)


class NoFiltracion(Base):
    """Una cadena única en todo campo de contenido no aparece nunca en el JSONL ni en errores.log."""

    def payloads(self):
        S = SECRETO
        respuesta_agente = {"status": "completed", "agentId": "a1", "resolvedModel": "m", "prompt": S,
                            "content": [{"type": "text", "text": S}], "handback": S, "handbackReport": S, "outputFile": S}
        yield self.evento("UserPromptSubmit", prompt=S)
        yield self.evento("UserPromptSubmit", prompt=f'<agent-message from="a1">\n[Subagent hand-back] {S}')
        yield self.evento("UserPromptSubmit", prompt=f"<task-notification>{S}</task-notification>")
        yield self.evento("PreToolUse", tool_name="Write", tool_use_id="t", tool_input={"file_path": "f.md", "content": S})
        yield self.evento("PostToolUse", tool_name="Write", tool_use_id="t", tool_input={"file_path": "f.md", "content": S},
                          tool_response={"type": "create", "filePath": "f.md", "content": S})
        yield self.evento("PreToolUse", tool_name="Edit", tool_use_id="t",
                          tool_input={"file_path": "f.md", "old_string": S, "new_string": S})
        yield self.evento("PreToolUse", tool_name="MultiEdit", tool_use_id="t",
                          tool_input={"file_path": "f.md", "edits": [{"old_string": S, "new_string": S}]})
        yield self.evento("PostToolUse", tool_name="Read", tool_use_id="t", tool_input={"file_path": "f.md"},
                          tool_response={"file": {"content": S}})
        yield self.evento("PreToolUse", tool_name="Agent", tool_use_id="t",
                          tool_input={"subagent_type": "verificador", "description": "d", "prompt": S})
        yield self.evento("PostToolUse", tool_name="Agent", tool_use_id="t",
                          tool_input={"subagent_type": "verificador", "description": "d", "prompt": S}, tool_response=respuesta_agente)
        yield self.evento("PostToolUse", tool_name="Bash", tool_use_id="t",
                          tool_input={"command": f'python -I scripts/notificar.py --canal radar "{S}"', "description": S},
                          tool_response={"stdout": S, "stderr": S})
        yield self.evento("PostToolUseFailure", tool_name="Bash", tool_use_id="t", error=S,
                          tool_input={"command": f"python scripts/notificar.py '{S}'"})
        yield self.evento("PermissionRequest", tool_name="Write", tool_input={"file_path": "f.md", "content": S},
                          permission_suggestions=[{"rule": S}])
        yield self.evento("PermissionDenied", tool_name="Edit", tool_input={"file_path": "f.md", "new_string": S}, reason=S)
        yield self.evento("PreToolUse", tool_name="SendMessage", tool_use_id="t", tool_input={"to": "partner", "message": S})
        yield self.evento("PreToolUse", tool_name="mcp__claude_ai_Google_Drive__read_file_content", tool_use_id="t",
                          tool_input={"fileId": "1Ab", "content": S})
        yield self.evento("PostToolUse", tool_name="mcp__engram__mem_save", tool_use_id="t",
                          tool_input={"content": S, "title": S}, tool_response=S)
        yield self.evento("Notification", notification_type="permission_prompt", message=S, title=S)
        yield self.evento("SubagentStop", agent_id="a1", agent_type="lector", last_assistant_message=S, agent_transcript_path=S)
        yield self.evento("Stop", last_assistant_message=S, background_tasks=[S])
        yield self.evento("StopFailure", error=S, error_details=S)
        yield self.evento("TaskCreated", task_id="1", task_subject="Verificar", task_description=S)
        yield self.evento("SessionEnd", reason="other", message=S)

    def test_jsonl_sin_la_cadena(self):
        for payload in self.payloads():
            self.correr(payload)
        lineas, texto = self.lineas()
        self.assertEqual(len(lineas), len(list(self.payloads())))
        self.assertNotIn(SECRETO, texto)
        self.assertFalse((self.datos / "errores.log").exists())

    def test_errores_log_sin_la_cadena(self):
        # Una falla de escritura en cada evento (la carpeta de eventos es un archivo): todo va a errores.log.
        (self.datos / "eventos").write_text("no es carpeta")
        for payload in self.payloads():
            self.correr(payload)
        log = (self.datos / "errores.log").read_text(encoding="utf-8")
        self.assertEqual(len(log.splitlines()), len(list(self.payloads())))
        self.assertNotIn(SECRETO, log)


class Robustez(Base):
    def test_json_invalido_sale_cero_y_no_guarda_payload(self):
        self.correr(None, crudo=f"{{no es json {SECRETO}".encode())
        log = (self.datos / "errores.log").read_text(encoding="utf-8")
        self.assertIn("JSONDecodeError", log)
        self.assertNotIn(SECRETO, log)

    def test_utf8_invalido(self):
        self.correr(None, crudo=b'{"hook_event_name": "\xff\xfe' + SECRETO.encode() + b'"}')
        self.assertNotIn(SECRETO, (self.datos / "errores.log").read_text(encoding="utf-8"))

    def simultaneos(self, n=50):
        """n procesos arrancados antes de recibir su payload; después se les entrega a todos juntos.
        Líneas largas (~2 KB) para que una escritura partida se note."""
        largo = "registry/providers/" + "x" * 1900 + ".md"
        procesos = [subprocess.Popen([sys.executable, "-I", str(HOOK)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.entorno())
                    for _ in range(n)]
        cargas = [json.dumps(self.evento("PreToolUse", tool_name="Write", tool_use_id=f"t{i}",
                                         tool_input={"file_path": f"{i}-{largo}"})).encode() for i in range(n)]
        with concurrent.futures.ThreadPoolExecutor(n) as pool:
            salidas = list(pool.map(lambda pc: pc[0].communicate(pc[1], timeout=60), zip(procesos, cargas)))
        self.assertTrue(all(p.returncode == 0 for p in procesos))
        self.assertTrue(all(s == (b"", b"") for s in salidas))
        texto = (next((self.datos / "eventos").glob("*.jsonl"))).read_text(encoding="utf-8")
        lineas = [json.loads(l) for l in texto.splitlines()]  # falla si alguna línea quedó partida o mezclada
        self.assertTrue(texto.endswith("\n"))
        self.assertEqual(sorted(l["tool_use_id"] for l in lineas), sorted(f"t{i}" for i in range(n)))
        for l in lineas:
            self.assertEqual(l["resumen"]["ruta"], f"{l['tool_use_id'][1:]}-{largo}"[:200])

    def test_50_escrituras_simultaneas(self):
        self.simultaneos(50)

    @unittest.skipUnless(os.name == "nt", "el respaldo FILE_APPEND_DATA es de Windows")
    def test_50_simultaneas_sin_cerrojo(self):
        """Con el cerrojo tomado por otro proceso, todos escriben sin él (tras esperar): el handle
        FILE_APPEND_DATA sigue dando líneas enteras."""
        import msvcrt
        eventos = self.datos / "eventos"
        eventos.mkdir()
        from datetime import date
        with open(eventos / f"{date.today().isoformat()}.jsonl.lock", "a+b") as cerrojo:
            cerrojo.seek(0)
            msvcrt.locking(cerrojo.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                self.simultaneos(50)
            finally:
                cerrojo.seek(0)
                msvcrt.locking(cerrojo.fileno(), msvcrt.LK_UNLCK, 1)

    def test_poda_14_dias(self):
        eventos = self.datos / "eventos"
        eventos.mkdir()
        (eventos / "2020-01-01.jsonl").write_text("{}\n")
        self.correr(self.evento("SessionStart", source="startup"))
        self.assertFalse((eventos / "2020-01-01.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
