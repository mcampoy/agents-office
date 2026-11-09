"""Prepara e instala el plugin de la oficina a nivel usuario.

Uso: py -3 scripts/instalar.py [--datos CARPETA] [--solo-generar]

1. Resuelve la ruta absoluta de python.exe (el intérprete que corre este script).
   Rechaza el alias de la Microsoft Store: en la forma exec de los hooks no sirve.
2. Genera plugin/hooks/hooks.json con esa ruta y la carpeta común de datos (`--datos`, por defecto
   AGENTS_OFFICE_DATOS o ~/.agents-office).
3. Escribe <datos>/config.json a partir de los proyectos registrados (scripts/configurar.py).
4. Genera las skills /oficina:abrir y /oficina:configurar con las rutas de esta máquina.
5. Registra el marketplace local e instala el plugin (salvo con --solo-generar).

Los proyectos se dan de alta con scripts/configurar.py (o /oficina:configurar): sin proyectos, el hook no
captura nada.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from servidor.oficinas import carpeta_comun, leer_proyectos  # noqa: E402
from servidor.registro import escribir_config_hook  # noqa: E402

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


def escribir_config(python, datos):
    return escribir_config_hook(datos, {"python": python, "repo": str(REPO)})


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


SKILL_CONFIGURAR = """---
name: configurar
description: Registra el proyecto actual en la oficina de agentes (o lo da de baja), con sus tablones de pendientes y de auditorías. Usar cuando la persona pide sumar este proyecto a la oficina, configurarla o armar los tablones.
---

# Sumar este proyecto a la oficina

1. Mostrá el plan, sin escribir nada:

   ```
   "{python}" "{script}" "<carpeta del proyecto actual>"
   ```

2. Contale a la persona, en pocas líneas, qué va a pasar: el perfil que se crea, en qué sala queda cada
   agente, qué tablones se crean y el bloque que se agregaría al CLAUDE.md (mostralo tal cual).
3. Preguntale si lo aplica y si suma el bloque al CLAUDE.md. Recién con su sí:

   ```
   "{python}" "{script}" "<carpeta del proyecto actual>" --aplicar [--claude-md]
   ```

4. Avisá que las sesiones nuevas de este proyecto ya aparecen en la oficina (`/oficina:abrir`) y que la
   sala de cada agente se cambia en `zonas.json` del perfil que se creó.

Para darlo de baja: el mismo comando con `--quitar` (no borra el perfil ni los eventos).
"""


def generar_skills(python):
    """Skills /oficina:abrir y /oficina:configurar con las rutas de esta máquina (no se versionan)."""
    destinos = []
    for nombre, plantilla, datos in (
        ("abrir", SKILL_ABRIR, {"script": REPO / "iniciar-oficina.ps1", "repo": REPO}),
        ("configurar", SKILL_CONFIGURAR, {"script": REPO / "scripts" / "configurar.py", "python": python}),
    ):
        destino = REPO / "plugin" / "skills" / nombre / "SKILL.md"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(plantilla.format(**datos), encoding="utf-8")
        destinos.append(destino)
    return destinos


def claude(*args):
    ejecutable = shutil.which("claude") or "claude"
    r = subprocess.run([ejecutable, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout + r.stderr).strip())
    return r.returncode


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    datos = carpeta_comun(sys.argv[sys.argv.index("--datos") + 1] if "--datos" in sys.argv[:-1] else None)
    python = resolver_python()
    print(f"datos: {datos}")
    print(f"python: {python}")
    print(f"hooks: {generar_hooks(python, datos)}")
    print(f"config: {escribir_config(python, datos)}")
    for skill in generar_skills(python):
        print(f"skill: {skill}")
    proyectos = [p["id"] for p in leer_proyectos(datos)]
    print(f"proyectos: {', '.join(proyectos) if proyectos else 'ninguno (sumalos con scripts/configurar.py)'}")
    if "--solo-generar" in sys.argv:
        return 0
    claude("plugin", "marketplace", "add", str(REPO))
    # Si ya estaba instalado, update toma el hooks.json nuevo.
    if claude("plugin", "install", PLUGIN) != 0:
        return claude("plugin", "update", PLUGIN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
