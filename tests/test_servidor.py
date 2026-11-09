"""Pruebas de la fase 2: modelo de estados, flujos, catálogo, lectura de eventos, área y HTTP.

Uso: py -3 -m unittest discover -s tests -v
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

from servidor.area import Area, FueraDeLaListaBlanca  # noqa: E402
from servidor.eventos import LectorEventos  # noqa: E402
from servidor.flujos import Flujos  # noqa: E402
from servidor.modelo import Modelo, proxima_corrida, zona_de  # noqa: E402
from servidor.oficina import Oficina, cargar_json  # noqa: E402
from servidor.perfil import Perfil  # noqa: E402
from servidor.util import relativa_al_area, tabla_de_encabezado  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PERFIL = REPO / "perfiles" / "ejemplo"  # las pruebas usan siempre el perfil de ejemplo, nunca el local
T0 = dt.datetime(2026, 10, 30, 10, 0, 0).astimezone()
RAIZ = r"G:\area"
EQUIPO = RAIZ + r"\equipo"


def ev(seg, evento, sesion="s1", **campos):
    e = {"ts": (T0 + dt.timedelta(seconds=seg)).isoformat(timespec="milliseconds"), "evento": evento,
         "session_id": sesion, "cwd": EQUIPO}
    e.update({k: v for k, v in campos.items() if v is not None})
    return e


def principal(seg, evento, **campos):
    return ev(seg, evento, agent_type="partner", **campos)


def sub(seg, evento, agente, tipo, **campos):
    return ev(seg, evento, agent_id=agente, agent_type=tipo, **campos)


def lanzar(seg, uso, tipo, descripcion, model=None):
    return principal(seg, "PreToolUse", tool_name="Agent", tool_use_id=uso,
                     resumen={"subagent_type": tipo, "description": descripcion, **({"model": model} if model else {})})


def vinculo(seg, uso, tipo, descripcion, agente, modelo="claude-sonnet-5-5", estado="async_launched"):
    return principal(seg, "PostToolUse", tool_name="Agent", tool_use_id=uso,
                     resumen={"subagent_type": tipo, "description": descripcion, "agente_lanzado": agente,
                              "modelo_resuelto": modelo, "estado_lanzamiento": estado})


def modelo(eventos, **contexto):
    base = {"relativa": lambda r, c: relativa_al_area(r, RAIZ, c),
            "agentes": {"partner": {"model": "sonnet"}, "verificador": {"model": "opus"},
                        "investigador-proveedor": {"model": "sonnet"}},
            "generales": ["general-purpose", "Explore"],
            "scripts": Perfil(PERFIL)["scripts"]}
    base.update(contexto)
    return Modelo(base).aplicar(eventos)


def area_de_ejemplo(raiz):
    """Un Area con la lista blanca y las carpetas del perfil de ejemplo."""
    perfil = Perfil(PERFIL)
    return Area(raiz, raices=perfil["raices"], remember=perfil["archivos"]["remember"], status=perfil["archivos"]["status"])


def instancias(foto):
    return {i["clave"]: i for i in foto["instancias"]}


class Estados(unittest.TestCase):
    def test_pre_post_por_tool_use_id_y_post_antes_que_pre(self):
        eventos = [
            principal(0, "SessionStart", resumen={"source": "startup"}),
            principal(5, "PostToolUse", tool_name="Read", tool_use_id="t1", resumen={"ruta": "a.md"}),
            principal(4, "PreToolUse", tool_name="Read", tool_use_id="t1", resumen={"ruta": "a.md"}),  # llega después
            principal(6, "PreToolUse", tool_name="Write", tool_use_id="t2", resumen={"ruta": "b.md"}),
        ]
        m = modelo(eventos)
        inst = m.instancias["s1:principal"]
        self.assertEqual(list(inst.abiertas), ["t2"])
        foto = m.foto(T0 + dt.timedelta(seconds=7))
        p = instancias(foto)["s1:principal"]
        self.assertEqual((p["estado"], p["animacion"], p["herramienta"]), ("trabajando", "escribe", "Write"))

    def test_desorden_total_da_el_mismo_resultado(self):
        eventos = [
            principal(0, "SessionStart"), lanzar(1, "u1", "verificador", "verificar google"),
            sub(2, "SubagentStart", "a1", "verificador"),
            sub(3, "PreToolUse", "a1", "verificador", tool_name="WebFetch", tool_use_id="w", resumen={"dominio": "google.com"}),
            sub(4, "PostToolUse", "a1", "verificador", tool_name="WebFetch", tool_use_id="w"),
            sub(5, "SubagentStop", "a1", "verificador"), principal(6, "Stop"),
        ]
        ahora = T0 + dt.timedelta(seconds=10)
        ordenada = modelo(eventos).foto(ahora)
        invertida = modelo(list(reversed(eventos))).foto(ahora)
        self.assertEqual(ordenada["instancias"], invertida["instancias"])

    def test_evento_de_subagente_antes_de_su_subagentstart(self):
        eventos = [principal(0, "SessionStart"), lanzar(1, "u1", "verificador", "verificar x"),
                   sub(3, "SubagentStart", "a1", "verificador"),
                   sub(2.5, "PreToolUse", "a1", "verificador", tool_name="Read", tool_use_id="r", resumen={"ruta": "x.md"})]
        i = instancias(modelo(eventos).foto(T0 + dt.timedelta(seconds=4)))["a1"]
        self.assertEqual((i["etiqueta"], i["estado"], i["animacion"]), ("verificar x", "trabajando", "lee"))

    def test_espera_de_permiso_y_resolucion(self):
        base = [principal(0, "SessionStart"),
                principal(1, "PreToolUse", tool_name="Write", tool_use_id="t", resumen={"ruta": "x.md"}),
                principal(2, "PermissionRequest", tool_name="Write", resumen={"ruta": "x.md"})]
        foto = modelo(base).foto(T0 + dt.timedelta(seconds=30))
        p = instancias(foto)["s1:principal"]
        self.assertEqual((p["estado"], p["espera"]["tipo"], p["segundos_en_estado"]), ("esperando", "permiso", 28))
        self.assertEqual(len(foto["aprobaciones"]), 1)
        resuelta = modelo(base + [principal(9, "PostToolUse", tool_name="Write", tool_use_id="t", resumen={"ruta": "x.md"})])
        self.assertEqual(resuelta.foto(T0 + dt.timedelta(seconds=10))["aprobaciones"], [])
        denegada = modelo(base + [principal(9, "PermissionDenied", tool_name="Write")])
        self.assertEqual(instancias(denegada.foto(T0 + dt.timedelta(seconds=10)))["s1:principal"]["estado"], "trabajando")

    def test_notificacion_de_permiso_de_un_subagente(self):
        eventos = [principal(0, "SessionStart"), lanzar(1, "u", "investigador-proveedor", "x"),
                   sub(2, "SubagentStart", "a1", "investigador-proveedor"),
                   sub(3, "Notification", "a1", "investigador-proveedor", resumen={"tipo": "permission_prompt"})]
        self.assertEqual(instancias(modelo(eventos).foto(T0 + dt.timedelta(seconds=4)))["a1"]["estado"], "esperando")

    def test_error_y_recuperacion(self):
        eventos = [principal(0, "SessionStart"),
                   principal(1, "PreToolUse", tool_name="Bash", tool_use_id="b", resumen={"comando": "x"}),
                   principal(2, "PostToolUseFailure", tool_name="Bash", tool_use_id="b", resumen={"comando": "x"})]
        self.assertEqual(instancias(modelo(eventos).foto(T0 + dt.timedelta(seconds=5)))["s1:principal"]["estado"], "error")
        self.assertNotEqual(instancias(modelo(eventos).foto(T0 + dt.timedelta(seconds=400)))["s1:principal"]["estado"], "error")
        sigue = eventos + [principal(6, "PreToolUse", tool_name="Read", tool_use_id="r")]
        self.assertEqual(instancias(modelo(sigue).foto(T0 + dt.timedelta(seconds=7)))["s1:principal"]["estado"], "trabajando")

    def test_interrupcion_no_es_error(self):
        eventos = [principal(0, "SessionStart"),
                   principal(2, "PostToolUseFailure", tool_name="Bash", tool_use_id="b", resumen={"interrumpido": True})]
        self.assertNotEqual(instancias(modelo(eventos).foto(T0 + dt.timedelta(seconds=3)))["s1:principal"]["estado"], "error")

    def test_terminado_y_ocioso(self):
        eventos = [principal(0, "SessionStart"), principal(1, "UserPromptSubmit", resumen={"origen": "usuario"}), principal(5, "Stop")]
        m = modelo(eventos)
        self.assertEqual(instancias(m.foto(T0 + dt.timedelta(seconds=10)))["s1:principal"]["estado"], "terminado")
        self.assertEqual(instancias(m.foto(T0 + dt.timedelta(minutes=10)))["s1:principal"]["estado"], "ocioso")

    def test_prompt_de_subagente_no_cuenta_como_del_responsable(self):
        eventos = [principal(0, "SessionStart"), principal(1, "UserPromptSubmit", resumen={"origen": "usuario"}),
                   principal(9, "UserPromptSubmit", resumen={"origen": "agent-message"})]
        foto = modelo(eventos).foto(T0 + dt.timedelta(seconds=10))
        self.assertEqual(foto["sesiones"][0]["ultimo_prompt_usuario"], (T0 + dt.timedelta(seconds=1)).isoformat(timespec="seconds"))


class Lanzamientos(unittest.TestCase):
    def paralelos(self, orden_inicio, con_vinculo=True):
        eventos = [principal(0, "SessionStart"),
                   lanzar(1, "u1", "investigador-proveedor", "Anthropic"),
                   lanzar(1.1, "u2", "investigador-proveedor", "OpenAI")]
        for k, agente in enumerate(orden_inicio):
            eventos.append(sub(2 + k * 0.1, "SubagentStart", agente, "investigador-proveedor"))
        if con_vinculo:
            eventos += [vinculo(3, "u1", "investigador-proveedor", "Anthropic", "aA"),
                        vinculo(3.1, "u2", "investigador-proveedor", "OpenAI", "aO")]
        return instancias(modelo(eventos).foto(T0 + dt.timedelta(seconds=4)))

    def test_cola_por_orden_de_llegada(self):
        i = self.paralelos(["aA", "aO"], con_vinculo=False)
        self.assertEqual((i["aA"]["etiqueta"], i["aO"]["etiqueta"]), ("Anthropic", "OpenAI"))
        self.assertEqual((i["aA"]["vinculo"], i["aA"]["numero"], i["aO"]["numero"]), ("cola", 1, 2))
        self.assertEqual(i["aA"]["modelo"], "sonnet")  # sin vínculo exacto: el del frontmatter

    def test_cola_cruzada_y_vinculo_exacto_la_corrige(self):
        cruzada = self.paralelos(["aO", "aA"], con_vinculo=False)
        self.assertEqual(cruzada["aO"]["etiqueta"], "Anthropic")  # el margen de error documentado
        corregida = self.paralelos(["aO", "aA"])
        self.assertEqual((corregida["aA"]["etiqueta"], corregida["aO"]["etiqueta"]), ("Anthropic", "OpenAI"))
        self.assertEqual((corregida["aA"]["vinculo"], corregida["aA"]["modelo"]), ("exacto", "claude-sonnet-5-5"))

    def test_vinculo_exacto_antes_del_subagentstart(self):
        eventos = [principal(0, "SessionStart"), lanzar(1, "u1", "verificador", "v1"),
                   lanzar(1.1, "u2", "verificador", "v2"),
                   vinculo(1.5, "u2", "verificador", "v2", "b2", "claude-opus-5-5"),
                   sub(2, "SubagentStart", "b2", "verificador"), sub(2.1, "SubagentStart", "b1", "verificador")]
        i = instancias(modelo(eventos).foto(T0 + dt.timedelta(seconds=3)))
        self.assertEqual((i["b2"]["etiqueta"], i["b1"]["etiqueta"]), ("v2", "v1"))

    def test_numeracion_reutiliza_numeros_libres(self):
        eventos = [principal(0, "SessionStart"),
                   lanzar(1, "u1", "verificador", "a"), sub(2, "SubagentStart", "v1", "verificador"),
                   sub(3, "SubagentStop", "v1", "verificador"),
                   lanzar(4, "u2", "verificador", "b"), sub(5, "SubagentStart", "v2", "verificador"),
                   lanzar(5.5, "u3", "verificador", "c"), sub(6, "SubagentStart", "v3", "verificador")]
        i = instancias(modelo(eventos).foto(T0 + dt.timedelta(seconds=7)))
        self.assertEqual((i["v2"]["numero"], i["v3"]["numero"]), (1, 2))

    def test_agente_general_temporal_y_se_retira(self):
        eventos = [principal(0, "SessionStart"), lanzar(1, "g", "general-purpose", "resumir PDF de Tactiq", "haiku"),
                   sub(2, "SubagentStart", "g1", "general-purpose"), sub(30, "SubagentStop", "g1", "general-purpose")]
        m = modelo(eventos)
        g = instancias(m.foto(T0 + dt.timedelta(seconds=31)))["g1"]
        self.assertEqual((g["general"], g["etiqueta"], g["modelo"], g["estado"]), (True, "resumir PDF de Tactiq", "haiku", "terminado"))
        self.assertNotIn("g1", instancias(m.foto(T0 + dt.timedelta(seconds=400))))
        self.assertEqual(len(m.foto(T0)["lanzamientos_generales"]), 1)

    def test_objetos_buzon_controles_memoria_skills(self):
        eventos = [principal(0, "SessionStart"),
                   principal(1, "PreToolUse", tool_name="Bash", tool_use_id="n", resumen={"script": "notificar.py", "canal": "radar"}),
                   principal(2, "PreToolUse", tool_name="Bash", tool_use_id="c", resumen={"script": "comprobar-citas.py", "ruta": "x.md"}),
                   principal(3, "PreToolUse", tool_name="mcp__engram__mem_search", tool_use_id="m"),
                   principal(4, "PreToolUse", tool_name="Skill", tool_use_id="s", resumen={"skill": "estilo-equipo"})]
        m = modelo(eventos)
        foto = m.foto(T0 + dt.timedelta(seconds=5))
        self.assertEqual(foto["objetos"]["buzon"][0]["canal"], "radar")
        self.assertEqual(foto["objetos"]["controles"][0]["script"], "comprobar-citas.py")
        self.assertEqual(foto["objetos"]["memoria"][0]["herramienta"], "mem_search")
        self.assertEqual(instancias(foto)["s1:principal"]["skills"], ["estilo-equipo"])


class AreaFalsa(unittest.TestCase):
    """Un área en una carpeta temporal, con la forma de la real."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name) / "area"
        archivos = {
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
        for rel, texto in archivos.items():
            ruta = self.raiz / rel
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_text(texto, encoding="utf-8")
        self.area = area_de_ejemplo(self.raiz)
        self.area.barrido()

    def tearDown(self):
        self.tmp.cleanup()


class AreaYListaBlanca(AreaFalsa):
    def test_lista_blanca(self):
        self.assertIn("Ficha de Google", self.area.leer("data-security-governance/registry/providers/google.md"))
        for mala in ["otra-carpeta/secreto.md", "../area/radar/2026-10-30-radar.md", "radar/../otra-carpeta/secreto.md",
                     "equipo/.claude/agents/partner.md.antes-marco", "C:/Windows/win.ini", "", "radar"]:
            with self.assertRaises(FueraDeLaListaBlanca, msg=mala):
                self.area.leer(mala)

    def test_encabezado_solo_tabla(self):
        cab = self.area.encabezado("data-security-governance/registry/providers/google.md")
        self.assertEqual((cab["titulo"], cab["estado"], cab["version"], cab["ultima_revision"]), ("Ficha de Google", "borrador", "0.7", "28/10/2026"))
        self.assertNotIn("SECRETO", json.dumps(cab))

    def test_rondas_y_ciclos(self):
        self.assertEqual(self.area.rondas("data-security-governance/research/providers/google/2026-10-30-verificacion.md")["ronda"], 2)
        self.assertEqual(self.area.rondas("data-security-governance/research/drafts/2026-10-30-verificacion.md")["ronda"], 1)
        ruta = self.raiz / "radar" / "ciclos-verificacion.md"
        ruta.write_text("# V\n\n## Ronda 1\n## Ronda 2\n## Ciclo 2, ronda 1, x\n## Ciclo 2, ronda 2, y\n## Ronda 1\n", encoding="utf-8")
        self.area.refrescar("radar/ciclos-verificacion.md")
        r = self.area.rondas("radar/ciclos-verificacion.md")
        self.assertEqual((r["ciclo"], r["ronda"]), (3, 1))

    def test_busqueda(self):
        res = self.area.buscar("bloqueo")
        self.assertEqual([r["ruta"] for r in res], ["equipo/pendientes.md"])
        self.assertEqual(self.area.buscar("no"), [r for r in self.area.buscar("no") if not r["ruta"].startswith("otra-carpeta")])

    def test_parsers_y_crudo(self):
        p = self.area.bloques("equipo/pendientes.md")
        e = p["entradas"][0]
        self.assertEqual((e["fecha"], e["titulo"]), ("2026-10-30", "Google: queda un bloqueo tras dos rondas"))
        self.assertIn("Qué queda frenado", e["campos"])
        self.assertEqual(e["rutas"], ["data-security-governance/registry/providers/google.md"])
        f = self.area.bloques("equipo/fricciones.md")["entradas"][0]
        self.assertEqual((f["campos"]["Repeticiones"], f["campos"]["Propuesta"]), ("3.", "un script."))
        d = self.area.bloques("equipo/decisiones.md")
        self.assertEqual(d["entradas"], [])
        self.assertIn("sin entradas", d["crudo"])
        self.assertEqual(self.area.remember()[0]["entradas"][0]["titulo"], "10:59 | unknown")
        self.assertEqual(self.area.status()[0]["tipo"], "corrida")


class FlujosPorDocumento(AreaFalsa):
    def setUp(self):
        super().setUp()
        self.flujos = Flujos(cargar_json(PERFIL / "flujos.json"), self.area)

    def correr(self, eventos, segundos=1000):
        raiz = str(self.raiz)
        m = Modelo({"relativa": lambda r, c: relativa_al_area(r, raiz, c), "es_documento": self.flujos.es_documento,
                    "agentes": {"verificador": {"model": "opus"}}, "generales": ["general-purpose"]}).aplicar(eventos)
        foto = m.foto(T0 + dt.timedelta(seconds=segundos))
        return foto, self.flujos.construir(foto, m.escrituras, m.operaciones_drive,
                                           self.area.bloques("equipo/pendientes.md"), etiquetas=m.etiquetas())

    def escribe(self, seg, agente, tipo, rel, uso):
        absoluta = str(self.raiz / rel)
        return [sub(seg, "PreToolUse", agente, tipo, tool_name="Write", tool_use_id=uso, resumen={"ruta": absoluta}),
                sub(seg + 1, "PostToolUse", agente, tipo, tool_name="Write", tool_use_id=uso, resumen={"ruta": absoluta})]

    def test_clasificacion(self):
        c = self.flujos.clasificar
        self.assertEqual(c("data-security-governance/registry/providers/google.md")["tipo"], "ficha")
        self.assertEqual(c("data-security-governance/research/providers/google/2026-10-30-verificacion.md")["tipo"], "verificacion")
        self.assertEqual(c("researches/cessi-ai-innovation/research/2026-10-30-verificacion-web.md")["tipo"], "verificacion")
        self.assertEqual(c("researches/buzz/research/2026-10-29-informe-inicial.md")["tipo"], "informe")
        self.assertEqual(c("data-security-governance/research/providers/cursor/2026-10-27-panel-cursor.md")["tipo"], "nota")
        self.assertEqual(c("data-security-governance/regulatory/cuestiones-para-legal.md")["tipo"], "informe de lente")
        self.assertEqual(c("data-security-governance/communication/charla/guion.md")["tipo"], "guion")
        self.assertEqual(c("radar/2026-10-30-radar.md")["tipo"], "radar")
        for fuera in ["equipo/pendientes.md", "data-security-governance/registry/providers/_plantilla.md",
                      "data-security-governance/CHANGELOG.md", "researches/buzz/README.md"]:
            self.assertIsNone(c(fuera), fuera)

    def test_dos_rondas_del_verificador_y_bloqueo(self):
        ficha = "data-security-governance/registry/providers/google.md"
        informe = "data-security-governance/research/providers/google/2026-10-30-verificacion.md"
        eventos = [principal(0, "SessionStart"),
                   lanzar(1, "l1", "investigador-proveedor", "Google"), sub(2, "SubagentStart", "i1", "investigador-proveedor"),
                   *self.escribe(10, "i1", "investigador-proveedor", ficha, "w1"), sub(20, "SubagentStop", "i1", "investigador-proveedor"),
                   lanzar(21, "l2", "verificador", "verificar Google"), sub(22, "SubagentStart", "v1", "verificador"),
                   *self.escribe(30, "v1", "verificador", informe, "w2"), sub(40, "SubagentStop", "v1", "verificador"),
                   lanzar(41, "l3", "investigador-proveedor", "corregir Google"), sub(42, "SubagentStart", "i2", "investigador-proveedor"),
                   *self.escribe(50, "i2", "investigador-proveedor", ficha, "w3"), sub(60, "SubagentStop", "i2", "investigador-proveedor"),
                   lanzar(61, "l4", "verificador", "verificación acotada"), sub(62, "SubagentStart", "v2", "verificador"),
                   *self.escribe(70, "v2", "verificador", informe, "w4"), sub(80, "SubagentStop", "v2", "verificador"),
                   principal(90, "Stop")]
        foto, flujos = self.correr(eventos)
        doc = next(d for d in flujos["documentos"] if d["ruta"] == ficha)
        self.assertEqual([c["etiqueta"] for c in doc["cruces"]], ["1/2", "2/2"])
        self.assertEqual({c["tipo_documento"] for c in doc["cruces"]}, {"ficha"})
        self.assertEqual([h["accion"] for h in doc["historial"]], ["escribe", "verifica (ronda 1/2)", "escribe", "verifica (ronda 2/2)"])
        self.assertEqual(doc["encabezado"]["estado"], "borrador")
        self.assertTrue(doc["bloqueado"])
        self.assertEqual(doc["etapa"], "bloqueado tras 2 rondas")
        self.assertEqual(doc["pendientes"][0]["fecha"], "2026-10-30")
        self.assertEqual(flujos["resumen_cruces"], {"ficha 1/2": 1, "ficha 2/2": 1})

    def test_correccion_y_espera_del_responsable(self):
        ficha = "data-security-governance/registry/providers/google.md"
        informe = "data-security-governance/research/providers/google/2026-10-30-verificacion.md"
        pendientes = self.raiz / "equipo" / "pendientes.md"
        pendientes.write_text("# Pendientes\n\n## 2026-10-30 · Otra cosa\n\nnada\n", encoding="utf-8")
        self.area.refrescar("equipo/pendientes.md")
        base = [principal(0, "SessionStart"), sub(1, "SubagentStart", "v1", "verificador"),
                *self.escribe(5, "v1", "verificador", informe, "w1"), sub(9, "SubagentStop", "v1", "verificador")]
        _, flujos = self.correr(base)
        doc = next(d for d in flujos["documentos"] if d["ruta"] == ficha)
        self.assertEqual((doc["etapa"], doc["espera_responsable"], doc["bloqueado"]),
                         ("revisión del responsable", "revisión del responsable", False))
        con_correccion = base + [sub(10, "SubagentStart", "i1", "investigador-proveedor"),
                                 *self.escribe(12, "i1", "investigador-proveedor", ficha, "w2")]
        _, flujos = self.correr(con_correccion, segundos=14)
        doc = next(d for d in flujos["documentos"] if d["ruta"] == ficha)
        self.assertEqual((doc["etapa"], doc["espera_responsable"]), ("corrección", None))

    def test_verificacion_de_borrador_por_encabezado(self):
        informe = "data-security-governance/research/drafts/2026-10-30-verificacion.md"
        _, flujos = self.correr([principal(0, "SessionStart"), sub(1, "SubagentStart", "v1", "verificador"),
                                 *self.escribe(2, "v1", "verificador", informe, "w")])
        rutas = {d["ruta"]: d for d in flujos["documentos"]}
        # El encabezado nombra solo el de clientes: tiene prioridad sobre el espejo (que daría los dos).
        self.assertEqual(list(rutas), ["data-security-governance/drafts/client/uso-cliente.md"])
        self.assertEqual(rutas["data-security-governance/drafts/client/uso-cliente.md"]["cruces"][0]["tipo_documento"], "borrador")

    def test_guion_imagenes_y_maquetado(self):
        guion = "data-security-governance/communication/charla/guion.md"
        imagenes = "data-security-governance/communication/charla/imagenes.md"
        eventos = [principal(0, "SessionStart"), sub(1, "SubagentStart", "e1", "editor-comunicacion"),
                   *self.escribe(2, "e1", "editor-comunicacion", guion, "g"),
                   *self.escribe(4, "e1", "editor-comunicacion", imagenes, "i"),
                   sub(6, "SubagentStop", "e1", "editor-comunicacion"),
                   sub(7, "SubagentStart", "m1", "maquetador"),
                   sub(8, "PostToolUse", "m1", "maquetador", tool_name="mcp__claude_ai_Google_Drive__copy_file",
                       tool_use_id="d", resumen={"archivo": "Plantilla del equipo"}),
                   sub(9, "SubagentStop", "m1", "maquetador")]
        foto, flujos = self.correr(eventos, segundos=20)
        docs = {d["ruta"]: d for d in flujos["documentos"]}
        self.assertEqual(docs[guion]["espera_responsable"], "revisión del responsable")
        self.assertTrue(docs[imagenes]["pendiente_codex"])
        self.assertEqual(docs["drive:Plantilla del equipo"]["tipo"], "maquetado")
        self.assertEqual(instancias(foto)["m1"]["documento"], "drive:Plantilla del equipo")

    def test_documento_en_curso_de_la_instancia(self):
        ficha = "data-security-governance/registry/providers/google.md"
        foto, _ = self.correr([principal(0, "SessionStart"), sub(1, "SubagentStart", "i1", "investigador-proveedor"),
                               *self.escribe(2, "i1", "investigador-proveedor", ficha, "w"),
                               *self.escribe(4, "i1", "investigador-proveedor", "equipo/pendientes.md", "w2")])
        self.assertEqual(instancias(foto)["i1"]["documento"], ficha)


class CatalogoYOficina(AreaFalsa):
    def oficina(self, datos):
        return Oficina(datos=datos, perfil=PERFIL, raiz_area=str(self.raiz), equipo_dir=str(self.raiz / "equipo"))

    def test_catalogo_zonas_vacantes_y_reinicio(self):
        datos = Path(self.tmp.name) / "datos"
        (datos / "eventos").mkdir(parents=True)
        ahora = dt.datetime.now().astimezone()
        e = {"ts": (ahora - dt.timedelta(minutes=1)).isoformat(timespec="milliseconds"), "evento": "SessionStart",
             "session_id": "s9", "agent_type": "partner", "cwd": str(self.raiz / "equipo")}
        (datos / "eventos" / f"{ahora.date().isoformat()}.jsonl").write_text(json.dumps(e) + "\n", encoding="utf-8")
        hace_una_hora = time.time() - 3600
        for definicion in (self.raiz / "equipo" / ".claude" / "agents").glob("*.md"):
            os.utime(definicion, (hace_una_hora, hace_una_hora))
        o = self.oficina(datos)
        o.actualizar(forzar=True)
        agentes = {a["nombre"]: a for a in o.catalogo.foto()["agentes"]}
        self.assertEqual(set(agentes), {"partner", "verificador", "lente-etica"})  # .antes-marco no cuenta
        self.assertEqual((agentes["lente-etica"]["zona"], agentes["lente-etica"]["sin_zona"]), ("lectura", False))
        self.assertIsNone(o.foto["principal"]["aviso_reinicio"])  # los .md son anteriores a la sesión
        nuevo = self.raiz / "equipo" / ".claude" / "agents" / "auditor.md"
        nuevo.write_text("---\nname: auditor\nmodel: haiku\n---\n", encoding="utf-8")
        (self.raiz / "equipo" / ".claude" / "agents" / "verificador.md").unlink()
        o.actualizar(forzar=True)
        agentes = {a["nombre"]: a for a in o.catalogo.foto()["agentes"]}
        self.assertEqual((agentes["auditor"]["zona"], agentes["auditor"]["sin_zona"]), ("recepcion", True))
        self.assertTrue(agentes["verificador"]["vacante"])
        self.assertEqual(o.foto["vacantes"], ["verificador"])
        self.assertIn("auditor", o.foto["principal"]["aviso_reinicio"])
        self.assertEqual(o.foto["reloj"]["ultima"], "2026-10-28")
        self.assertEqual(o.foto["responsable"]["pendientes"], 1)


class LecturaIncremental(unittest.TestCase):
    def test_linea_a_medio_escribir_y_basura(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            hoy = dt.date(2026, 10, 30)
            ruta = carpeta / "2026-10-30.jsonl"
            ruta.write_bytes(b'{"ts":"2026-10-30T10:00:00","evento":"A"}\n{"ts":"2026-10-30T10:00:01","evento":"B"')
            lector = LectorEventos(carpeta)
            self.assertEqual(lector.leer_nuevos(hoy), 1)
            with open(ruta, "ab") as f:
                f.write(b'}\nno es json\n{"ts":"2026-10-30T10:00:02","evento":"C"}\n')
            self.assertEqual(lector.leer_nuevos(hoy), 2)
            self.assertEqual([e["evento"] for e in lector.eventos], ["A", "B", "C"])
            self.assertEqual(lector.descartadas, 1)
            self.assertEqual(lector.leer_nuevos(hoy), 0)

    def test_ayer_y_cambio_de_dia(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            (carpeta / "2026-10-29.jsonl").write_text('{"ts":"2026-10-29T23:59:00","evento":"A"}\n')
            (carpeta / "2026-10-30.jsonl").write_text('{"ts":"2026-10-30T00:01:00","evento":"B"}\n')
            lector = LectorEventos(carpeta)
            lector.leer_nuevos(dt.date(2026, 10, 30))
            self.assertEqual(len(lector.eventos), 2)
            lector.leer_nuevos(dt.date(2026, 10, 31))
            self.assertEqual([e["evento"] for e in lector.eventos], ["B"])


class Varios(unittest.TestCase):
    def test_zonas_por_patron(self):
        reglas = cargar_json(PERFIL / "zonas.json")
        self.assertEqual(zona_de("lente-normativa", reglas["reglas"], reglas["generales"]), ("lectura", False))
        self.assertEqual(zona_de("Explore", reglas["reglas"], reglas["generales"]), ("flotante", False))
        self.assertEqual(zona_de("nuevo", reglas["reglas"], reglas["generales"]), ("recepcion", True))

    def test_proxima_corrida(self):
        martes = dt.datetime(2026, 11, 3, 15, 0).astimezone()
        self.assertEqual(proxima_corrida(martes).date(), dt.date(2026, 11, 4))
        miercoles_tarde = dt.datetime(2026, 11, 4, 11, 0).astimezone()
        self.assertEqual(proxima_corrida(miercoles_tarde).date(), dt.date(2026, 11, 11))

    def test_rutas_relativas(self):
        self.assertEqual(relativa_al_area(r"G:\area\radar\x.md", RAIZ), "radar/x.md")
        self.assertEqual(relativa_al_area("G:/area/radar/x.md", RAIZ), "radar/x.md")
        self.assertEqual(relativa_al_area("../radar/x.md", RAIZ, EQUIPO), "radar/x.md")
        self.assertIsNone(relativa_al_area(r"G:\areas\x.md", RAIZ))
        self.assertIsNone(relativa_al_area(r"C:\x.md", RAIZ))

    def test_tabla_por_nombre_de_columna(self):
        t = tabla_de_encabezado(["# T", "", "| Estado | Fecha | Rondas |", "|---|---|---|", "| borrador | 26/10 | 3 |"])
        self.assertEqual(t, {"Estado": "borrador", "Fecha": "26/10", "Rondas": "3"})


class Http(AreaFalsa):
    def setUp(self):
        super().setUp()
        from servidor.red import crear_servidor
        datos = Path(self.tmp.name) / "datos"
        datos.mkdir()
        self.oficina = Oficina(datos=datos, perfil=PERFIL, raiz_area=str(self.raiz), equipo_dir=str(self.raiz / "equipo"))
        self.oficina.actualizar(forzar=True)
        self.servidor = crear_servidor(self.oficina, 0)
        self.puerto = self.servidor.server_address[1]
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        super().tearDown()

    def get(self, ruta, host=None):
        pedido = urllib.request.Request(f"http://127.0.0.1:{self.puerto}{ruta}")
        pedido.add_header("Host", host or f"127.0.0.1:{self.puerto}")
        try:
            with urllib.request.urlopen(pedido, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def test_endpoints(self):
        codigo, cuerpo = self.get("/api/estado")
        self.assertEqual(codigo, 200)
        self.assertIn("instancias", json.loads(cuerpo))
        codigo, cuerpo = self.get("/api/buscar?q=bloqueo")
        self.assertEqual(json.loads(cuerpo)["resultados"][0]["ruta"], "equipo/pendientes.md")
        codigo, cuerpo = self.get("/api/archivo?ruta=radar/2026-10-30-radar.md")
        self.assertEqual(codigo, 200)
        self.assertEqual(self.get("/api/archivo?ruta=otra-carpeta/secreto.md")[0], 403)
        self.assertEqual(self.get("/api/archivo?ruta=radar/../otra-carpeta/secreto.md")[0], 403)
        self.assertEqual(self.get("/api/archivo?ruta=radar/no-existe.md")[0], 404)
        self.assertEqual(self.get("/api/equipo")[0], 200)
        self.assertEqual(self.get("/api/estado", host="evil.example:80")[0], 421)

    def test_stream_envia_la_foto(self):
        pedido = urllib.request.Request(f"http://127.0.0.1:{self.puerto}/api/stream")
        with urllib.request.urlopen(pedido, timeout=5) as r:
            primera = b""
            while b"\n\n" not in primera:
                primera += r.read1(4096)
        self.assertTrue(primera.startswith(b"event: estado\nid: "))


class AceptacionReal(unittest.TestCase):
    """La secuencia real del 30/10: partner lanza dos investigador-proveedor en paralelo (eventos ya redactados)."""

    def setUp(self):
        ruta = Path(__file__).parent / "fixtures" / "aceptacion-2026-10-30.jsonl"
        self.eventos = [json.loads(l) for l in ruta.read_text(encoding="utf-8").splitlines()]
        self.m = modelo(self.eventos, agentes={"partner": {"model": "sonnet"}, "investigador-proveedor": {"model": "sonnet"}})

    def ts(self, evento, agente=None, herramienta=None, n=0):
        hallados = [dt.datetime.fromisoformat(e["ts"]) for e in self.eventos if e["evento"] == evento
                    and (agente is None or (e.get("agent_id") or "").startswith(agente))
                    and (herramienta is None or e.get("tool_name") == herramienta)]
        return hallados[n]

    def estados(self, momento):
        # Reproduce solo lo que el servidor habría visto hasta ese momento.
        ahora = momento + dt.timedelta(milliseconds=50)
        vistos = [e for e in self.eventos if dt.datetime.fromisoformat(e["ts"]) <= ahora]
        m = modelo(vistos, agentes={"partner": {"model": "sonnet"}, "investigador-proveedor": {"model": "sonnet"}})
        return {(i["tipo"] if i["principal"] else i["etiqueta"]): i["estado"]
                for i in m.foto(ahora)["instancias"]}

    def test_stop_de_partner_con_dos_subagentes_activos(self):
        primer_stop = self.ts("Stop", n=0)
        e = self.estados(primer_stop)
        self.assertEqual(e["partner"], "esperando_subagentes")
        self.assertEqual((e["portada Anthropic"], e["portada OpenAI"]), ("trabajando", "trabajando"))
        # Segundo Stop: Anthropic ya terminó, OpenAI sigue.
        e = self.estados(self.ts("Stop", n=1))
        self.assertEqual((e["partner"], e["portada Anthropic"], e["portada OpenAI"]),
                         ("esperando_subagentes", "terminado", "trabajando"))
        # Tercer Stop: los dos terminaron.
        e = self.estados(self.ts("Stop", n=2))
        self.assertEqual(e["partner"], "terminado")
        self.assertEqual(self.estados(self.ts("SessionEnd"))["partner"], "terminado")

    def test_entregando_desde_el_handback_hasta_el_subagentstop(self):
        for agente, etiqueta in (("a774", "portada Anthropic"), ("a3d2", "portada OpenAI")):
            entrega = self.ts("PreToolUse", agente, "SubagentHandback")
            fin = self.ts("SubagentStop", agente)
            self.assertEqual(self.estados(entrega)[etiqueta], "entregando")
            self.assertEqual(self.estados(fin - dt.timedelta(milliseconds=100))[etiqueta], "entregando")
            self.assertEqual(self.estados(fin)[etiqueta], "terminado")

    def test_vinculo_modelo_y_etiquetas_de_historial(self):
        foto = self.m.foto(self.ts("SessionEnd"))
        subs = [i for i in foto["instancias"] if not i["principal"]]
        self.assertEqual({(i["etiqueta"], i["vinculo"], i["modelo"]) for i in subs},
                         {("portada Anthropic", "exacto", "claude-haiku-5-5"), ("portada OpenAI", "exacto", "claude-haiku-5-5")})
        self.assertEqual({i["etiqueta_historial"] for i in subs},
                         {"investigador-proveedor · portada Anthropic", "investigador-proveedor · portada OpenAI"})
        quienes = {a["quien"] for a in foto["actividad"]}
        self.assertEqual(quienes, {"partner", "investigador-proveedor · portada Anthropic", "investigador-proveedor · portada OpenAI"})
        self.assertFalse(any("#" in q for q in quienes))

    def test_respuestas_de_subagentes_no_mueven_al_avatar(self):
        foto = self.m.foto(self.ts("SessionEnd"))
        self.assertEqual(foto["sesiones"][0]["ultimo_prompt_usuario"][:19], self.ts("UserPromptSubmit").isoformat()[:19])


class EstadosNuevos(unittest.TestCase):
    def test_esperando_subagentes_termina_cuando_vuelven(self):
        eventos = [principal(0, "SessionStart"), lanzar(1, "u", "verificador", "v"),
                   sub(2, "SubagentStart", "v1", "verificador"), principal(3, "Stop")]
        m = modelo(eventos)
        self.assertEqual(instancias(m.foto(T0 + dt.timedelta(seconds=4)))["s1:principal"]["animacion"], "espera_subagentes")
        m = modelo(eventos + [sub(5, "SubagentStop", "v1", "verificador")])
        self.assertEqual(instancias(m.foto(T0 + dt.timedelta(seconds=6)))["s1:principal"]["estado"], "terminado")

    def test_etiqueta_historial_sin_description_usa_id_corto(self):
        eventos = [principal(0, "SessionStart"), sub(2, "SubagentStart", "abcdef1234567890", "verificador")]
        i = instancias(modelo(eventos).foto(T0 + dt.timedelta(seconds=3)))["abcdef1234567890"]
        self.assertEqual(i["etiqueta_historial"], "verificador · abcdef12")


class RondaAmbigua(FlujosPorDocumento):
    def test_sin_titulos_ni_columna_es_ronda_desconocida(self):
        informe = "data-security-governance/research/providers/google/2026-10-31-verificacion.md"
        (self.raiz / informe).write_text("# Verificación\n\n| Estado | Versión | Última revisión |\n|---|---|---|\n| borrador | 0.1 | 31/10/2026 |\n\n## Resumen\n", encoding="utf-8")
        self.area.refrescar(informe)
        _, flujos = self.correr([principal(0, "SessionStart"), sub(1, "SubagentStart", "v1", "verificador"),
                                 *self.escribe(2, "v1", "verificador", informe, "w")])
        cruce = flujos["cruces"][0]
        self.assertEqual((cruce["ronda"], cruce["etiqueta"], cruce["concluyente"], cruce["fuente_ronda"]), (None, "?", False, "supuesta"))
        doc = flujos["documentos"][0]
        self.assertEqual(doc["historial"][-1]["accion"], "verifica (ronda ?)")
        self.assertEqual(flujos["resumen_cruces"], {"ficha ronda ?": 1})

    def test_mas_ejecuciones_que_rondas_es_ronda_desconocida(self):
        """Tres verificadores escribieron hoy un informe que tiene dos rondas: no se adivina cuál fue cuál."""
        informe = "data-security-governance/research/providers/google/2026-10-30-verificacion.md"
        eventos = [principal(0, "SessionStart")]
        for n in (1, 2, 3):
            eventos += [sub(n * 10, "SubagentStart", f"v{n}", "verificador"),
                        *self.escribe(n * 10 + 1, f"v{n}", "verificador", informe, f"w{n}"),
                        sub(n * 10 + 5, "SubagentStop", f"v{n}", "verificador")]
        _, flujos = self.correr(eventos)
        self.assertEqual([c["etiqueta"] for c in flujos["cruces"]], ["?", "?", "?"])
        doc = next(d for d in flujos["documentos"] if d["ruta"].endswith("registry/providers/google.md"))
        self.assertFalse(doc["bloqueado"])  # sin ronda conocida no se marca "bloqueado tras 2 rondas"
        self.assertEqual(doc["etapa"], "revisión del responsable")

    def test_columna_rondas_sin_titulos_es_concluyente(self):
        informe = "data-security-governance/research/drafts/2026-10-30-verificacion.md"
        _, flujos = self.correr([principal(0, "SessionStart"), sub(1, "SubagentStart", "v1", "verificador"),
                                 *self.escribe(2, "v1", "verificador", informe, "w")])
        c = flujos["cruces"][0]
        self.assertEqual((c["etiqueta"], c["fuente_ronda"]), ("1/2", "encabezado"))


class LecturaDeDrive(AreaFalsa):
    """Solo se lee la unidad cuando un evento nombra la ruta o en el barrido de 5 minutos."""

    def test_politica_de_lectura(self):
        datos = Path(self.tmp.name) / "datos"
        (datos / "eventos").mkdir(parents=True)
        o = Oficina(datos=datos, perfil=PERFIL, raiz_area=str(self.raiz), equipo_dir=str(self.raiz / "equipo"))
        o.actualizar(forzar=True)
        tras_barrido = o.area.lecturas
        self.assertGreater(tras_barrido, 0)
        # Sin eventos nuevos: ni una lectura más, aunque un archivo cambie en disco.
        radar = self.raiz / "radar" / "2026-10-30-radar.md"
        radar.write_text("# Radar\n\n| Estado | Versión | Última revisión |\n|---|---|---|\n| revisado | 0.2 | 30/10/2026 |\n", encoding="utf-8")
        o.actualizar(forzar=True)
        self.assertEqual(o.area.lecturas, tras_barrido)
        self.assertEqual(o.area.encabezado("radar/2026-10-30-radar.md")["estado"], "borrador")  # caché vieja
        # Un evento que nombra otra ruta: se lee esa sola.
        ficha = self.raiz / "data-security-governance" / "registry" / "providers" / "google.md"
        ficha.write_text(ficha.read_text(encoding="utf-8").replace("0.7", "0.8"), encoding="utf-8")
        ahora = dt.datetime.now().astimezone()
        e = {"ts": ahora.isoformat(timespec="milliseconds"), "evento": "PostToolUse", "session_id": "s", "agent_id": "i1",
             "agent_type": "investigador-proveedor", "tool_name": "Write", "tool_use_id": "w", "cwd": str(self.raiz / "equipo"),
             "resumen": {"ruta": str(ficha)}}
        (datos / "eventos" / f"{ahora.date().isoformat()}.jsonl").write_text(json.dumps(e) + "\n", encoding="utf-8")
        o.actualizar()
        self.assertEqual(o.area.lecturas, tras_barrido + 1)
        self.assertEqual(o.area.encabezado("data-security-governance/registry/providers/google.md")["version"], "0.8")
        # El mismo evento no vuelve a disparar lecturas.
        o.actualizar(forzar=True)
        self.assertEqual(o.area.lecturas, tras_barrido + 1)
        # El barrido (cada 5 min) toma lo que cambió sin evento: solo eso.
        o._barrido_en -= 301
        o.actualizar()
        self.assertEqual(o.area.lecturas, tras_barrido + 2)
        self.assertEqual(o.area.encabezado("radar/2026-10-30-radar.md")["estado"], "revisado")

    def test_busqueda_y_equipo_no_leen_la_unidad(self):
        antes = self.area.lecturas
        self.area.buscar("bloqueo")
        self.area.bloques("equipo/pendientes.md")
        self.area.status()
        self.area.remember()
        self.assertEqual(self.area.lecturas, antes)


class SinCors(Http):
    def cabeceras(self, ruta, metodo="GET"):
        pedido = urllib.request.Request(f"http://127.0.0.1:{self.puerto}{ruta}", method=metodo)
        pedido.add_header("Origin", "https://evil.example")
        pedido.add_header("Access-Control-Request-Method", "GET")
        try:
            with urllib.request.urlopen(pedido, timeout=5) as r:
                if ruta == "/api/stream":
                    return r.status, dict(r.headers)
                r.read()
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers)

    def test_ninguna_respuesta_habilita_cors(self):
        for ruta in ("/", "/api/estado", "/api/stream", "/api/buscar?q=x", "/api/archivo?ruta=radar/2026-10-30-radar.md",
                     "/api/equipo", "/no-existe"):
            codigo, cabeceras = self.cabeceras(ruta)
            self.assertFalse([c for c in cabeceras if c.lower().startswith("access-control-")], ruta)
        codigo, cabeceras = self.cabeceras("/api/estado", metodo="OPTIONS")  # preflight
        self.assertGreaterEqual(codigo, 400)
        self.assertFalse([c for c in cabeceras if c.lower().startswith("access-control-")])


class GuardarLayout(Http):
    """POST /api/layout: la única escritura del servidor, siempre en una copia de config/ (nunca la real)."""

    def setUp(self):
        super().setUp()
        import shutil
        self.config = Path(self.tmp.name) / "config"
        shutil.copytree(PERFIL, self.config)
        self.oficina.config_dir = self.config
        self.layout = json.loads((self.config / "layout.json").read_text(encoding="utf-8"))

    def post(self, cuerpo, origen="propio", tipo="application/json", ruta="/api/layout"):
        datos = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
        pedido = urllib.request.Request(f"http://127.0.0.1:{self.puerto}{ruta}", data=datos, method="POST")
        pedido.add_header("Content-Type", tipo)
        if origen:
            pedido.add_header("Origin", f"http://127.0.0.1:{self.puerto}" if origen == "propio" else origen)
        try:
            with urllib.request.urlopen(pedido, timeout=5) as r:
                return r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers)

    def test_guarda_y_deja_respaldo(self):
        self.layout["furniture"] = self.layout["furniture"][:-1]
        codigo, cabeceras = self.post(self.layout)
        self.assertEqual(codigo, 200)
        self.assertFalse([c for c in cabeceras if c.lower().startswith("access-control-")])
        guardado = json.loads((self.config / "layout.json").read_text(encoding="utf-8"))
        self.assertEqual(len(guardado["furniture"]), len(self.layout["furniture"]))
        self.assertTrue((self.config / "layout.json.bak").exists())
        self.assertFalse((self.config / "layout.json.tmp").exists())
        codigo, cuerpo = self.get("/api/layout")
        self.assertEqual(json.loads(cuerpo)["furniture"], self.layout["furniture"])

    def test_rechaza_origen_ajeno_tipo_y_layout_invalido(self):
        original = (self.config / "layout.json").read_bytes()
        self.assertEqual(self.post(self.layout, origen="https://evil.example")[0], 403)
        self.assertEqual(self.post(self.layout, origen=None)[0], 403)
        self.assertEqual(self.post(self.layout, tipo="text/plain")[0], 415)
        self.assertEqual(self.post(self.layout, ruta="/api/estado")[0], 404)
        self.assertEqual(self.post(b"{no es json")[0], 400)
        self.assertEqual(self.post({**self.layout, "version": 2})[0], 400)
        self.assertEqual(self.post({**self.layout, "tiles": self.layout["tiles"][:-1]})[0], 400)
        self.assertEqual(self.post({**self.layout, "furniture": [{"type": "DESK_FRONT"}]})[0], 400)
        self.assertEqual(self.post({**self.layout, "areaTiles": [None]})[0], 400)
        self.assertEqual((self.config / "layout.json").read_bytes(), original)
        self.assertFalse((self.config / "layout.json.bak").exists())

    def test_layout_generado_es_valido(self):
        from servidor.red import validar_layout
        validar_layout(json.loads((PERFIL / "layout.json").read_text(encoding="utf-8")))


class PerfilDeEquipo(unittest.TestCase):
    """El código no sabe nada del equipo: todo sale de la carpeta del perfil."""

    def test_eleccion_del_perfil(self):
        with tempfile.TemporaryDirectory() as tmp:
            otro = Path(tmp) / "otro"
            otro.mkdir()
            (otro / "perfil.json").write_text(json.dumps({"nombre": "Otro", "equipo_dir": "eq", "raiz_area": tmp}),
                                              encoding="utf-8")
            viejo = os.environ.get("AGENTS_OFFICE_PERFIL")
            try:
                os.environ["AGENTS_OFFICE_PERFIL"] = str(otro)
                self.assertEqual(Perfil().carpeta, otro.resolve())
                self.assertEqual(Perfil(PERFIL).carpeta, PERFIL.resolve())  # el explícito gana
            finally:
                if viejo is None:
                    os.environ.pop("AGENTS_OFFICE_PERFIL", None)
                else:
                    os.environ["AGENTS_OFFICE_PERFIL"] = viejo
            p = Perfil(otro)
            self.assertEqual(p["nombre"], "Otro")
            self.assertEqual(Path(p.equipo), Path(tmp) / "eq")
            self.assertEqual(p["scripts"]["controles"], [])   # valores por defecto para lo que no define
            self.assertIsNone(p["verificador"])

    def test_la_web_no_recibe_rutas_del_area(self):
        web = json.dumps(Perfil(PERFIL).para_la_web())
        for clave in ("raiz_area", "equipo_dir", "datos", "archivos", "raices", "variable_origen"):
            self.assertNotIn(f'"{clave}"', web)

    def test_oficina_sin_flujos_ni_archivos(self):
        """Un perfil mínimo (sin flujos.json ni archivos del equipo) arma la foto igual."""
        with tempfile.TemporaryDirectory() as tmp:
            minimo = Path(tmp) / "minimo"
            minimo.mkdir()
            (minimo / "perfil.json").write_text(json.dumps({"raiz_area": tmp, "equipo_dir": "eq"}), encoding="utf-8")
            o = Oficina(datos=Path(tmp) / "datos", perfil=minimo)
            o.actualizar(forzar=True)
            self.assertEqual(o.foto["documentos"], [])
            self.assertIsNone(o.foto["reloj"]["proxima"])
            self.assertEqual(o.foto["responsable"]["pendientes"], 0)


class PensandoYSubagentesOciosos(unittest.TestCase):
    """Decisiones del 09/11: 'pensando' entre la actividad reciente y el ocio, y partner no espera a ociosos."""

    def secuencia(self):
        return [principal(0, "SessionStart", resumen={"source": "startup"}),
                principal(1, "UserPromptSubmit", resumen={"largo": 10, "origen": "usuario"}),
                principal(2, "PreToolUse", tool_name="Agent", tool_use_id="L",
                          resumen={"subagent_type": "investigador-proveedor", "description": "X"}),
                principal(3, "PostToolUse", tool_name="Agent", tool_use_id="L",
                          resumen={"subagent_type": "investigador-proveedor", "agente_lanzado": "a1"}),
                sub(4, "SubagentStart", "a1", "investigador-proveedor"),
                sub(5, "PreToolUse", "a1", "investigador-proveedor", tool_name="Read", tool_use_id="r"),
                sub(6, "PostToolUse", "a1", "investigador-proveedor", tool_name="Read", tool_use_id="r"),
                principal(7, "Stop")]

    def estado(self, segundos, clave):
        m = modelo(self.secuencia())
        return instancias(m.foto(T0 + dt.timedelta(seconds=segundos)))[clave]

    def test_pensando_entre_actividad_y_ocio(self):
        self.assertEqual(self.estado(60, "a1")["estado"], "trabajando")
        e = self.estado(150, "a1")
        self.assertEqual((e["estado"], e["animacion"]), ("pensando", "piensa"))
        self.assertEqual(self.estado(400, "a1")["estado"], "ocioso")

    def test_partner_no_espera_subagentes_ociosos(self):
        self.assertEqual(self.estado(150, "s1:principal")["estado"], "esperando_subagentes")  # a1 pensando
        self.assertEqual(self.estado(400, "s1:principal")["estado"], "ocioso")  # a1 ocioso: ya no lo espera


class CandidatoAAgente(unittest.TestCase):
    """Fase 0, punto 11: 3 lanzamientos de generales con descripciones parecidas en 14 días = candidato."""

    def escribir(self, carpeta, dia, descripciones, tipo="general-purpose"):
        lineas = [json.dumps({"ts": f"{dia}T10:00:0{i}-03:00", "evento": "PreToolUse", "tool_name": "Agent",
                              "resumen": {"subagent_type": tipo, "description": d}}) for i, d in enumerate(descripciones)]
        (carpeta / f"{dia}.jsonl").write_text("".join(linea + "\n" for linea in lineas), encoding="utf-8")

    def test_grupo_de_tres_parecidos(self):
        from servidor.candidatos import Candidatos
        with tempfile.TemporaryDirectory() as tmp:
            c = Path(tmp)
            self.escribir(c, "2026-11-01", ["comparar precios de APIs de modelos de OpenAI"])
            self.escribir(c, "2026-11-05", ["comparar precios de APIs de modelos de Mistral",
                                            "resumir noticias"])          # corta: menos de 3 palabras útiles
            self.escribir(c, "2026-11-09", ["Comparar los precios de las APIs de modelos (Cohere)",
                                            "redactar correo de seguimiento al cliente"])
            self.escribir(c, "2026-10-01", ["comparar precios de APIs de modelos"])  # fuera de los 14 días
            self.escribir(c, "2026-11-08", ["comparar precios de APIs de modelos"], tipo="investigador-proveedor")
            r = Candidatos(c).calcular(dt.date(2026, 11, 9), lambda t: t == "general-purpose",
                                       ["temas/registry/providers/mistral.md", "temas/registry/providers/cohere.md"])
            self.assertEqual(len(r), 1)
            self.assertEqual(r[0]["lanzamientos"], 3)
            self.assertEqual(r[0]["palabras"], ["apis", "comparar", "modelos", "precios"])
            self.assertEqual(r[0]["tipos"], ["general-purpose"])

    def test_dos_no_alcanzan(self):
        from servidor.candidatos import Candidatos
        with tempfile.TemporaryDirectory() as tmp:
            self.escribir(Path(tmp), "2026-11-09", ["comparar precios de APIs de modelos"] * 2)
            self.assertEqual(Candidatos(tmp).calcular(dt.date(2026, 11, 9), lambda t: True), [])


class Tablones(unittest.TestCase):
    """Los tablones de pendientes y auditorías, con el formato estándar y con el de entradas por fecha."""

    def test_pendientes_con_secciones_y_tareas_de_sesion(self):
        from servidor import tablones
        texto = (tablones.PLANTILLA_PENDIENTES
                 .replace("## En curso\n", "## En curso\n- [ ] migrar la base\n")
                 .replace("## Siguen\n", "## Siguen\n- [ ] revisar permisos\n- [x] ya estaba hecha\n"))
        r = tablones.pendientes(texto, None, [{"titulo": "leer pendientes", "creada": "t1", "completada": None},
                                             {"titulo": "armar informe", "creada": "t0", "completada": "t2"}])
        self.assertEqual([i["titulo"] for i in r["en_curso"]], ["leer pendientes", "migrar la base"])
        self.assertEqual([i["titulo"] for i in r["siguen"]], ["revisar permisos"])
        self.assertEqual([i["titulo"] for i in r["hechas"]], ["armar informe", "ya estaba hecha"])

    def test_pendientes_sin_secciones_van_a_siguen(self):
        from servidor import tablones
        bloques = {"entradas": [{"titulo": "Presentación lista", "fecha": "2026-11-02"}]}
        r = tablones.pendientes("## 2026-11-02 · Presentación lista\n", bloques, [])
        self.assertEqual(r["siguen"][0]["titulo"], "Presentación lista")
        self.assertEqual(r["en_curso"], [])

    def test_plantillas_vacias_no_tienen_entradas(self):
        """La guía de formato va en un comentario HTML: no cuenta como fricción ni como pendiente."""
        from servidor import tablones
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "fricciones.md").write_text(tablones.PLANTILLA_FRICCIONES, encoding="utf-8")
            (raiz / "pendientes.md").write_text(tablones.PLANTILLA_PENDIENTES, encoding="utf-8")
            area = Area(raiz, raices=["."])
            area.barrido()
            self.assertEqual(tablones.auditorias(area.bloques("fricciones.md")), {"abiertas": [], "resueltas": []})
            vacio = tablones.pendientes(area.texto("pendientes.md"), area.bloques("pendientes.md"), [])
            self.assertEqual(vacio, {"en_curso": [], "siguen": [], "hechas": []})

    def test_auditorias_abiertas_y_resueltas(self):
        from servidor import tablones
        bloques = {"entradas": [{"titulo": "Permiso de Drive", "fecha": "2026-11-01", "campos": {"Estado": "abierta"}},
                                {"titulo": "Hook roto", "fecha": "2026-10-30", "campos": {"Estado (05/11)": "resuelta"}},
                                {"titulo": "Sin estado", "fecha": None, "campos": {}}]}
        r = tablones.auditorias(bloques)
        self.assertEqual([i["titulo"] for i in r["abiertas"]], ["Permiso de Drive", "Sin estado"])
        self.assertEqual([i["titulo"] for i in r["resueltas"]], ["Hook roto"])


if __name__ == "__main__":
    unittest.main()
