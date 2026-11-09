"""Simulador de eventos para probar el piso sin una sesión real de partner.

Escribe, en tiempo real, eventos con el mismo formato que plugin/hooks/captura.py en una carpeta de datos
aparte (nunca en la carpeta de datos del perfil). Después se levanta el servidor apuntando a esa carpeta:

    py -3 scripts/simular.py                       # escribe en %TEMP%/agents-office-sim
    set AGENTS_OFFICE_DATOS=%TEMP%\\agents-office-sim
    py -3 -m servidor

El guion cubre todos los estados del piso: trabajando (lee y escribe), esperando aprobación, error,
entregando, terminado, ocioso, esperando subagentes, un agente general que se retira, un agente sin zona,
el buzón, el archivo (engram) y los controles del agente principal.

    --rapido N   divide los tiempos por N (por defecto 1)
    --datos DIR  carpeta de datos (por defecto %TEMP%/agents-office-sim)
"""
import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from servidor.perfil import Perfil  # noqa: E402

# El guion usa los roles y scripts del perfil activo (por defecto, el de ejemplo)
PERFIL = Perfil()
RAIZ = PERFIL.raiz
EQUIPO = PERFIL.equipo
PRINCIPAL = PERFIL["principal"]
BUZON = PERFIL["scripts"]["buzon"] or "notificar.py"
CONTROL = (PERFIL["scripts"]["controles"] or ["comprobar-citas.py"])[0]
PENDIENTES = PERFIL["archivos"]["pendientes"] or "pendientes.md"


def guion():
    """Lista de (segundo, evento). Los ids se generan en cada corrida."""
    s = f"sim-{uuid.uuid4().hex[:8]}"
    ids = {}

    def aid(nombre):
        return ids.setdefault(nombre, f"a{uuid.uuid4().hex[:15]}")

    def tu():
        return f"toolu_sim{uuid.uuid4().hex[:16]}"

    def area(rel):
        return str(Path(RAIZ) / rel)

    pasos = []

    def e(t, evento, agente=None, tipo=PRINCIPAL, **campos):
        d = {"evento": evento, "session_id": s, "agent_type": tipo, "cwd": EQUIPO, "permission_mode": "auto"}
        if agente:
            d["agent_id"] = aid(agente)
        d.update({k: v for k, v in campos.items() if v is not None})
        pasos.append((t, d))

    def herramienta(t0, dur, nombre, agente=None, tipo=PRINCIPAL, resumen=None, falla=False):
        u = tu()
        e(t0, "PreToolUse", agente, tipo, tool_name=nombre, tool_use_id=u, resumen=resumen)
        fin = "PostToolUseFailure" if falla else "PostToolUse"
        e(t0 + dur, fin, agente, tipo, tool_name=nombre, tool_use_id=u,
          resumen={**(resumen or {}), "duracion_ms": int(dur * 1000)})

    def lanzar(t, tipo, description, model, agente):
        u = tu()
        r = {"subagent_type": tipo, "description": description, "model": model}
        e(t, "PreToolUse", tool_name="Agent", tool_use_id=u, resumen=r)
        e(t + 0.5, "PostToolUse", tool_name="Agent", tool_use_id=u,
          resumen={**r, "agente_lanzado": aid(agente), "estado_lanzamiento": "async_launched"})
        e(t + 0.6, "SubagentStart", agente, tipo)

    # Partner arranca y recibe el pedido
    e(0, "SessionStart", resumen={"source": "startup"})
    e(2, "UserPromptSubmit", resumen={"largo": 420, "origen": "usuario"})
    herramienta(3, 2, "Read", resumen={"ruta": area(PENDIENTES)})
    herramienta(5, 1.5, "mcp__engram__mem_search")

    # Dos investigaciones en paralelo
    lanzar(7, "investigador-proveedor", "Mistral", "sonnet", "inv1")
    lanzar(8, "investigador-proveedor", "Cohere", "sonnet", "inv2")
    for k in range(6):
        herramienta(9 + k * 6, 4, "WebFetch", "inv1", "investigador-proveedor", {"dominio": "mistral.ai"})
    herramienta(46, 3, "Write", "inv1", "investigador-proveedor",
                {"ruta": area("data-security-governance/registry/providers/mistral.md")})
    e(52, "PreToolUse", "inv1", "investigador-proveedor", tool_name="SubagentHandback", tool_use_id="toolu_simhb1")
    e(58, "PostToolUse", "inv1", "investigador-proveedor", tool_name="SubagentHandback", tool_use_id="toolu_simhb1")
    e(59, "SubagentStop", "inv1", "investigador-proveedor")

    herramienta(10, 5, "mcp__playwright__browser_navigate", "inv2", "investigador-proveedor", {"dominio": "cohere.com"})
    # Pide permiso para un comando y espera la aprobación del responsable
    u = tu()
    e(17, "PreToolUse", "inv2", "investigador-proveedor", tool_name="Bash", tool_use_id=u,
      resumen={"comando": "curl -s https://docs.cohere.com/"})
    e(17.2, "PermissionRequest", "inv2", "investigador-proveedor", tool_name="Bash", tool_use_id=u,
      resumen={"comando": "curl -s https://docs.cohere.com/"})
    e(70, "PostToolUse", "inv2", "investigador-proveedor", tool_name="Bash", tool_use_id=u,
      resumen={"comando": "curl -s https://docs.cohere.com/", "duracion_ms": 900})
    for k in range(4):
        herramienta(72 + k * 5, 3, "Read", "inv2", "investigador-proveedor",
                    {"ruta": area("data-security-governance/registry/providers/cohere.md")})

    # Verificador cruzando una ficha
    lanzar(12, "verificador", "verificar ficha OpenAI", "opus", "ver")
    for k in range(5):
        herramienta(13 + k * 7, 5, "WebSearch", "ver", "verificador")
    herramienta(50, 3, "Write", "ver", "verificador",
                {"ruta": area("data-security-governance/research/registry/providers/openai/2026-11-09-verificacion.md")})

    # Una lente leyendo
    lanzar(14, "lente-normativa", "mapa de referencias", "sonnet", "len")
    for k in range(12):
        herramienta(15 + k * 6, 4, "Read", "len", "lente-normativa",
                    {"ruta": area("data-security-governance/regulatory/mapa-de-referencias.md")})

    # Redactor que falla al escribir (error) y no vuelve a hacer nada
    lanzar(16, "redactor", "borrador interno", "sonnet", "red")
    herramienta(17, 3, "Read", "red", "redactor", {"ruta": area("data-security-governance/registry/providers/openai.md")})
    herramienta(22, 2, "Write", "red", "redactor",
                {"ruta": area("data-security-governance/drafts/internal/borrador.md")}, falla=True)

    # Agente general temporal: trabaja un rato y termina (se retira a los 2 min)
    lanzar(18, "general-purpose", "comparar precios de APIs", "haiku", "gen")
    for k in range(4):
        herramienta(19 + k * 5, 3, "WebSearch", "gen", "general-purpose")
    e(40, "SubagentStop", "gen", "general-purpose")

    # Agente sin zona en config/zonas.json: va a la recepción
    lanzar(20, "auditor-costos", "revisar consumo", "haiku", "aud")
    for k in range(5):
        herramienta(21 + k * 6, 4, "Grep", "aud", "auditor-costos", {"patron": "costo"})

    # Partner: controles, aviso por Discord y fin de turno con subagentes todavía activos
    herramienta(24, 2, "Bash", resumen={"script": CONTROL,
                                        "ruta": area("data-security-governance/registry/providers/openai.md")})
    herramienta(27, 2, "Bash", resumen={"script": BUZON, "canal": (PERFIL["scripts"]["canales"] or ["avisos"])[0]})
    herramienta(29, 1, "Skill", resumen={"skill": "estilo-equipo"})
    e(32, "Stop")
    return sorted(pasos, key=lambda p: p[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rapido", type=float, default=1.0)
    parser.add_argument("--datos", default=str(Path(tempfile.gettempdir()) / "agents-office-sim"))
    args = parser.parse_args()
    if Path(args.datos).resolve() == PERFIL.carpeta_datos().resolve():
        raise SystemExit(f"El simulador no escribe en {PERFIL.carpeta_datos()}: usá otra carpeta de datos.")
    carpeta = Path(args.datos) / "eventos"
    carpeta.mkdir(parents=True, exist_ok=True)
    pasos = guion()
    inicio = time.monotonic()
    print(f"Simulando {len(pasos)} eventos en {carpeta} (AGENTS_OFFICE_DATOS={args.datos})")
    for t, d in pasos:
        espera = inicio + t / args.rapido - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        ahora = dt.datetime.now().astimezone()
        linea = {"ts": ahora.isoformat(timespec="milliseconds"), **d}
        with open(carpeta / f"{ahora.date().isoformat()}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(linea, ensure_ascii=False) + "\n")
    print("Guion terminado. Los estados que dependen del reloj (ocioso, retiro) siguen cambiando solos.")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
