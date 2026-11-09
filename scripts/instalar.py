"""Prepara e instala el plugin de la oficina a nivel usuario, para un perfil de equipo.

Uso: py -3 scripts/instalar.py [--perfil CARPETA] [--solo-generar]

El perfil se elige igual que en el servidor: --perfil, AGENTS_OFFICE_PERFIL, local.json o perfiles/ejemplo.

1. Resuelve la ruta absoluta de python.exe (el intérprete que corre este script).
   Rechaza el alias de la Microsoft Store: en la forma exec de los hooks no sirve.
2. Genera plugin/hooks/hooks.json con esa ruta y la carpeta de datos del perfil (`--datos`).
3. Escribe <datos>/config.json con lo que el hook necesita del perfil (carpeta del equipo, scripts, canales).
4. Registra el marketplace local e instala el plugin (salvo con --solo-generar).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from servidor.perfil import Perfil  # noqa: E402

PLUGIN = "oficina@agents-office"

EVENTOS = [
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PostToolUseFailure", "PermissionRequest", "PermissionDenied", "Notification",
    "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "Stop", "StopFailure",
]
# Sincrónicos: en claude -p los hooks async que siguen corriendo al cierre se matan.
SINCRONICOS = {"Stop", "StopFailure", "SubagentStop", "SessionEnd"}
TIMEOUT_SINCRONICO = 5


def resolver_python():
    python = Path(sys.executable).resolve()
    if "windowsapps" in str(python).lower() or not python.is_file():
        sys.exit(f"Este python no sirve para los hooks: {python}. Corré el instalador con el python.exe real (py -3).")
    return str(python)


def generar_hooks(python, datos):
    hooks = {}
    for evento in EVENTOS:
        hook = {
            "type": "command",
            "command": python,
            "args": ["-I", "${CLAUDE_PLUGIN_ROOT}/hooks/captura.py", "--datos", str(datos)],
            "onFailure": "continue",
        }
        if evento in SINCRONICOS:
            hook["timeout"] = TIMEOUT_SINCRONICO
        else:
            hook["async"] = True
        hooks[evento] = [{"hooks": [hook]}]
    destino = REPO / "plugin" / "hooks" / "hooks.json"
    destino.write_text(json.dumps({"description": "Captura de la oficina de agentes", "hooks": hooks}, indent=2) + "\n", encoding="utf-8")
    return destino


def escribir_config(python, perfil, datos):
    config = {**perfil.para_el_hook(), "python": python, "repo": str(REPO), "perfil": str(perfil.carpeta)}
    datos.mkdir(parents=True, exist_ok=True)
    destino = datos / "config.json"
    destino.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destino


def claude(*args):
    ejecutable = shutil.which("claude") or "claude"
    r = subprocess.run([ejecutable, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout + r.stderr).strip())
    return r.returncode


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    perfil = Perfil(sys.argv[sys.argv.index("--perfil") + 1] if "--perfil" in sys.argv[:-1] else None)
    datos = perfil.carpeta_datos()
    python = resolver_python()
    print(f"perfil: {perfil.carpeta}")
    print(f"python: {python}")
    print(f"hooks: {generar_hooks(python, datos)}")
    print(f"config: {escribir_config(python, perfil, datos)}")
    if "--solo-generar" in sys.argv:
        return 0
    claude("plugin", "marketplace", "add", str(REPO))
    # Si ya estaba instalado, update toma el hooks.json nuevo.
    if claude("plugin", "install", PLUGIN) != 0:
        return claude("plugin", "update", PLUGIN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
