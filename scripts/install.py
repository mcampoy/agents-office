"""Prepares and installs the office plugin at user level.

Usage: py -3 scripts/install.py [--data FOLDER] [--generate-only] [--statusline | --remove-statusline]

1. Resolves the absolute path of python.exe (the interpreter running this script).
   Rejects the Microsoft Store alias: it does not work in the exec form of the hooks.
2. Generates plugin/hooks/hooks.json with that path and the common data folder (`--data`, by default
   AGENTS_OFFICE_DATA or ~/.agents-office).
3. Writes <data>/config.json from the registered projects (scripts/configure.py).
4. Generates the /oficina:abrir and /oficina:configurar skills with this machine's paths.
5. Registers the local marketplace and installs the plugin (except with --generate-only).

With --statusline, wraps the statusline in ~/.claude/settings.json: the original is still shown the same and,
in registered projects, the office receives model, effort, context and limits
(plugin/statusline/wrapper.mjs). Leaves a backup in settings.json.antes-oficina.
--remove-statusline goes back to the original.

Projects are registered with scripts/configure.py (or /oficina:configurar): without projects, the hook
captures nothing.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from server.offices import read_projects  # noqa: E402
from server.profile import data_folder  # noqa: E402
from server.registry import write_hook_config  # noqa: E402

PLUGIN = "oficina@agents-office"

EVENTS = [
    "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "PostToolUseFailure", "PermissionRequest", "PermissionDenied", "Notification",
    "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted", "Stop", "StopFailure",
]
# Synchronous: in claude -p, async hooks still running at exit are killed.
SYNCHRONOUS = {"Stop", "StopFailure", "SubagentStop", "SessionEnd"}
SYNCHRONOUS_TIMEOUT = 5
# Wrapper names, current and previous (to recognize an installation made before the rename)
WRAPPER_NAMES = ("wrapper.mjs", "envoltorio.mjs")


def resolve_python():
    python = Path(sys.executable).resolve()
    if "windowsapps" in str(python).lower() or not python.is_file():
        sys.exit(f"Este python no sirve para los hooks: {python}. Corré el instalador con el python.exe real (py -3).")
    return str(python)


def generate_hooks(python, data):
    hooks = {}
    for event in EVENTS:
        hook = {
            "type": "command",
            "command": python,
            "args": ["-I", "${CLAUDE_PLUGIN_ROOT}/hooks/capture.py", "--data", str(data)],
            "onFailure": "continue",
        }
        if event in SYNCHRONOUS:
            hook["timeout"] = SYNCHRONOUS_TIMEOUT
        else:
            hook["async"] = True
        hooks[event] = [{"hooks": [hook]}]
    target = REPO / "plugin" / "hooks" / "hooks.json"
    target.write_text(json.dumps({"description": "Agents office capture", "hooks": hooks}, indent=2) + "\n",
                      encoding="utf-8")
    return target


CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
WRAPPER = REPO / "plugin" / "statusline" / "wrapper.mjs"


def previous_config(data):
    try:
        config = json.loads((data / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    # Before the rename the key was statusline_original
    if "statusline_original" in config:
        config.setdefault("original_statusline", config.pop("statusline_original"))
    return config


def write_config(python, data):
    extra = {"python": python, "repo": str(REPO)}
    previous = previous_config(data)
    if previous.get("original_statusline"):
        extra["original_statusline"] = previous["original_statusline"]
    return write_hook_config(data, extra)


def expand_home(command):
    """`node ~/.claude/x.mjs` -> absolute path: the wrapper runs the command with cmd.exe, which does not expand ~."""
    return re.sub(r"(^|\s)~(?=[/\\])", lambda m: m.group(1) + str(Path.home()).replace("\\", "/"), command)


def wrapper_command(data):
    return f'node "{WRAPPER.as_posix()}" --data "{data.as_posix()}"'


def wrap_statusline(data):
    settings = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
    current = (settings.get("statusLine") or {}).get("command") or ""
    if current == wrapper_command(data):
        return "la statusline ya estaba envuelta"
    previous = previous_config(data)
    if any(name in current for name in WRAPPER_NAMES):
        # Wrapped by an older version: only the command is updated, the original stays the same
        settings["statusLine"]["command"] = wrapper_command(data)
        CLAUDE_SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (data / "config.json").write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return f"statusline actualizada al envoltorio nuevo (original: {previous.get('original_statusline')})"
    backup = CLAUDE_SETTINGS.with_name("settings.json.antes-oficina")
    backup.write_text(CLAUDE_SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
    previous["original_statusline"] = expand_home(current) if current else None
    (data / "config.json").write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    new = dict(settings.get("statusLine") or {"type": "command", "padding": 0})
    new["command"] = wrapper_command(data)
    settings["statusLine"] = new
    CLAUDE_SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"statusline envuelta (respaldo: {backup}; original: {previous['original_statusline']})"


def unwrap_statusline(data):
    settings = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8"))
    current = (settings.get("statusLine") or {}).get("command") or ""
    if not any(name in current for name in WRAPPER_NAMES):
        return "la statusline no estaba envuelta"
    original = previous_config(data).get("original_statusline")
    if original:
        settings["statusLine"]["command"] = original
    else:
        settings.pop("statusLine", None)
    CLAUDE_SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return f"statusline restaurada: {original}"


# The skills are the user's interface: their text is Spanish.
OPEN_SKILL = """---
name: abrir
description: Levanta la oficina de agentes local (si no está corriendo) y la abre en el navegador. Usar cuando la persona pide abrir, ver o mostrar la oficina.
---

# Abrir la oficina

Corré este comando (PowerShell), sin cambiarlo:

```
powershell -NoProfile -ExecutionPolicy Bypass -File "{script}"
```

- Si dice que la oficina ya está corriendo o que la levantó, contestá en una línea con la URL que imprimió.
- Si dice que el python.exe registrado ya no existe, decí que hay que reinstalar con `py -3 scripts\\install.py` en `{repo}`.
- Si avisa que falta la web compilada, decilo: se ve la vista básica hasta compilar `web\\pixel-agents` con `npm run build`.
- La oficina es de solo lectura: no ofrezcas aprobar permisos ni lanzar agentes desde ella.
"""


CONFIGURE_SKILL = """---
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
   "{python}" "{script}" "<carpeta del proyecto actual>" --apply [--claude-md]
   ```

4. Avisá que las sesiones nuevas de este proyecto ya aparecen en la oficina (`/oficina:abrir`) y que la
   sala de cada agente se cambia en `zones.json` del perfil que se creó.

Para darlo de baja: el mismo comando con `--remove` (no borra el perfil ni los eventos).
"""


def generate_skills(python):
    """/oficina:abrir and /oficina:configurar skills with this machine's paths (not versioned)."""
    targets = []
    for name, template, values in (
        ("abrir", OPEN_SKILL, {"script": REPO / "start-office.ps1", "repo": REPO}),
        ("configurar", CONFIGURE_SKILL, {"script": REPO / "scripts" / "configure.py", "python": python}),
    ):
        target = REPO / "plugin" / "skills" / name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template.format(**values), encoding="utf-8")
        targets.append(target)
    return targets


def claude(*args):
    executable = shutil.which("claude") or "claude"
    r = subprocess.run([executable, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout + r.stderr).strip())
    return r.returncode


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    data = data_folder(sys.argv[sys.argv.index("--data") + 1] if "--data" in sys.argv[:-1] else None)
    python = resolve_python()
    print(f"data: {data}")
    print(f"python: {python}")
    print(f"hooks: {generate_hooks(python, data)}")
    print(f"config: {write_config(python, data)}")
    for skill in generate_skills(python):
        print(f"skill: {skill}")
    if "--statusline" in sys.argv:
        print(wrap_statusline(data))
    if "--remove-statusline" in sys.argv:
        print(unwrap_statusline(data))
    projects = [p["id"] for p in read_projects(data)]
    print(f"proyectos: {', '.join(projects) if projects else 'ninguno (sumalos con scripts/configure.py)'}")
    if "--generate-only" in sys.argv:
        return 0
    claude("plugin", "marketplace", "add", str(REPO))
    # If it was already installed, update picks up the new hooks.json.
    if claude("plugin", "install", PLUGIN) != 0:
        return claude("plugin", "update", PLUGIN)
    return 0


if __name__ == "__main__":
    sys.exit(main())
