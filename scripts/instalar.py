"""Prepara e instala el plugin de la oficina a nivel usuario, para un perfil de equipo.

Uso: py -3 scripts/instalar.py [--perfil CARPETA] [--solo-generar]

El perfil se elige igual que en el servidor: --perfil, AGENTS_OFFICE_PERFIL, local.json o perfiles/ejemplo.

1. Resuelve la ruta absoluta de python.exe (el intérprete que corre este script).
   Rechaza el alias de la Microsoft Store: en la forma exec de los hooks no sirve.
2. Genera plugin/hooks/hooks.json con esa ruta y la carpeta de datos del perfil (`--datos`).
3. Escribe <datos>/config.json con lo que el hook necesita del perfil (carpeta del equipo, scripts, canales).
   Genera también plugin/skills/abrir/SKILL.md (/oficina:abrir) con la ruta de iniciar-oficina.ps1.
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


SKILL_ABRIR = """---
name: abrir
description: Levanta la oficina de agentes local (si no está corriendo) y la abre en el navegador. Usar cuando la persona pide abrir, ver o mostrar la oficina.
---

# Abrir la oficina

Corré este comando (PowerShell), sin cambiarlo:

```
powershell -NoProfile -ExecutionPolicy Bypass -File "{script}"
```

- Si dice que la oficina ya está corriendo o que la levantó, contestá en una línea con la URL que imprimió.
- Si dice que el python.exe registrado ya no existe, decí que hay que reinstalar con `py -3 scripts\\instalar.py` en `{repo}`.
- Si avisa que falta la web compilada, decilo: se ve la vista básica hasta compilar `web\\pixel-agents` con `npm run build`.
- La oficina es de solo lectura: no ofrezcas aprobar permisos ni lanzar agentes desde ella.
"""


def generar_skill():
    """plugin/skills/abrir/SKILL.md con la ruta de iniciar-oficina.ps1 de esta máquina (no se versiona)."""
    destino = REPO / "plugin" / "skills" / "abrir" / "SKILL.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(SKILL_ABRIR.format(script=REPO / "iniciar-oficina.ps1", repo=REPO), encoding="utf-8")
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
    print(f"skill /oficina:abrir: {generar_skill()}")
    if "--solo-generar" in sys.argv:
        return 0
    claude("plugin", "marketplace", "add", str(REPO))
    # Si ya estaba instalado, update toma el hooks.json nuevo.
    if claude("plugin", "install", PLUGIN) != 0:
        return claude("plugin", "update", PLUGIN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
