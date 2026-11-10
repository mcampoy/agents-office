"""Registers a project in the office (what /oficina:configurar does).

Usage:
    py -3 scripts/configure.py [FOLDER] [--profile FOLDER] [--id ID] [--data FOLDER] [--apply] [--claude-md] [--remove]

Without --apply it only shows the plan: it writes nothing. With --apply:
1. If --profile is not given, builds one in <data>/profiles/<id>/:
   - profile.json with the project as the area (allowlist: the whole project, except build folders);
   - zones.json from the agents in .claude/agents (lente-* to reading, verifier to verification,
     researchers to exploration, the rest to the base room);
   - the example layout and an empty sprites.json.
   With --profile (an existing profile, like equipo-idi's) it uses that one and does not touch the project.
2. Boards: looks for pendientes.md and fricciones.md (at the root or in docs/). If missing, creates them with
   the standard format (server/boards.py).
3. With --claude-md, adds to the project's CLAUDE.md a block (between markers, can be re-run) asking the
   agents to keep the boards up to date.
4. Registers the project in <data>/projects.json and regenerates <data>/config.json for the hook.

New sessions of the project are captured from then on (the hook reads the config on every event).
--remove unregisters it (does not delete the profile or the events).

The output and the files it creates are read by the user, so they are Spanish.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from server import boards, registry  # noqa: E402
from server.offices import read_projects  # noqa: E402
from server.profile import EXAMPLE, Profile, data_folder  # noqa: E402
from server.util import frontmatter  # noqa: E402

START_MARK = "<!-- agents-office:boards -->"
END_MARK = "<!-- /agents-office:boards -->"
# Markers written before the rename: still recognized so the block is not added twice
OLD_START_MARK = "<!-- oficina:tablones -->"


def claude_md_block(tasks, frictions):
    return f"""{START_MARK}
## Tablones de la oficina

- `{tasks}`: cuando empezás una tarea pedida, anotala en **En curso** (`- [ ] tarea`). Lo que quede para
  después va en **Siguen**. Al terminarla, pasala a **Hechas** con `- [x]`.
- `{frictions}`: si algo traba el trabajo (falta un permiso, falla una herramienta, un pedido es ambiguo, un
  error se repite), agregá arriba una entrada `## AAAA-MM-DD · título` con **Estado:** abierta, **Qué pasó:** y
  **Propuesta:**. Cuando se resuelva, cambiá el estado a `resuelta`.
{END_MARK}
"""


def find(folder, names):
    for n in names:
        if (folder / n).is_file():
            return n
    return None


# Claude Code's built-in subagents, each in the room of what it does (after the project's own rules, which win).
# Coordination has a single desk, the main agent's: Plan goes to the reading room's meeting table
GENERIC_RULES = [
    {"agent": "Explore", "zone": "exploration"},
    {"agent": "codebase-memory*", "zone": "exploration"},
    {"agent": "Plan", "zone": "reading"},
    {"agent": "claude-code-guide", "zone": "reading"},
    {"agent": "*review*", "zone": "verification"},
    {"agent": "general-purpose", "zone": "base"},
]


def suggested_zone(name):
    n = name.lower()
    if "lente" in n or "lens" in n:
        return "reading"
    if "verific" in n or "review" in n or "audit" in n:
        return "verification"
    if "investig" in n or "research" in n or "explor" in n or n == "radar":
        return "exploration"
    if "comunic" in n or "maquet" in n or "design" in n or "disen" in n:
        return "communication"
    return "base"


def project_agents(folder):
    out = []
    for path in sorted((folder / ".claude" / "agents").glob("*.md")):
        try:
            fields = frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            fields = {}
        out.append(fields.get("name") or path.stem)
    return out


def project_main_agent(folder):
    for name in ("settings.json", "settings.local.json"):
        try:
            settings = json.loads((folder / ".claude" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(settings.get("agent"), str):
            return settings["agent"]
    return "main"


def plan(folder, ident, given_profile, data):
    actions = []
    if given_profile:
        profile = Profile(given_profile)
        actions.append(f"Usar el perfil existente {profile.folder} (no se toca el proyecto).")
        return {"ident": ident, "profile": profile.folder, "boards": {}, "actions": actions, "claude_md": None}
    target = data / "profiles" / ident
    agents = project_agents(folder)
    main_agent = project_main_agent(folder)
    tasks = find(folder, ["pendientes.md", "PENDIENTES.md", "docs/pendientes.md"])
    frictions = find(folder, ["fricciones.md", "FRICCIONES.md", "docs/fricciones.md"])
    board_files = {"tasks": tasks or "pendientes.md", "frictions": frictions or "fricciones.md",
                   "create": [n for n, exists in (("pendientes.md", tasks), ("fricciones.md", frictions)) if not exists]}
    zones = [{"agent": a, "zone": suggested_zone(a)} for a in agents if a != main_agent]
    actions.append(f"Crear el perfil en {target} (agente principal: {main_agent}; {len(agents)} agentes).")
    for z in zones:
        actions.append(f"  - {z['agent']} → sala {z['zone']}")
    for n in board_files["create"]:
        actions.append(f"Crear {folder / n} con el formato estándar del tablón.")
    for key in ("tasks", "frictions"):
        if board_files[key] not in board_files["create"]:
            actions.append(f"Usar el que ya existe: {board_files[key]}.")
    claude_md = folder / "CLAUDE.md"
    current = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
    return {"ident": ident, "profile": target, "main_agent": main_agent, "zones": zones, "boards": board_files,
            "actions": actions, "agents": agents,
            "claude_md": {"path": claude_md, "present": START_MARK in current or OLD_START_MARK in current,
                          "block": claude_md_block(board_files["tasks"], board_files["frictions"])}}


def create_profile(folder, p):
    target = Path(p["profile"])
    target.mkdir(parents=True, exist_ok=True)
    example = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
    profile = {
        "_comment": "Perfil generado por scripts/configure.py. Formato: docs/profile.md del repo agents-office.",
        "name": folder.name,
        "area_root": str(folder),
        "team_dir": ".",
        "port": 8765,
        "roots": ["."],
        "files": {"tasks": p["boards"]["tasks"], "frictions": p["boards"]["frictions"]},
        "main_agent": p["main_agent"],
        "verifier": next((z["agent"] for z in p["zones"] if z["zone"] == "verification"), None),
        "owner_label": "responsable",
        "scripts": {"known": [], "mailbox": None, "channels": [], "default_channel": "avisos", "checks": []},
        "scheduled_run": None,
        "floor": {**example["floor"], "short_names": {"general-purpose": "general"}, "next_to_clock": None,
                  "external_work": {}},
    }
    if not (target / "profile.json").exists():
        (target / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    zones = {
        "_comment": "Zona de cada agente. Patrones con '*'. Un agente sin regla va a la recepción.",
        "rules": [{"agent": "lente-*", "zone": "reading"}, {"agent": p["main_agent"], "zone": "coordination"}]
                 + [z for z in p["zones"] if not z["agent"].startswith("lente-")] + GENERIC_RULES,
        "generic": ["general-purpose", "Explore", "Plan", "claude", "claude-code-guide", "statusline-setup"],
        "generic_zone": "floating",
        "unzoned_zone": "reception",
    }
    if not (target / "zones.json").exists():
        (target / "zones.json").write_text(json.dumps(zones, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not (target / "layout.json").exists():
        shutil.copyfile(EXAMPLE / "layout.json", target / "layout.json")
    if not (target / "sprites.json").exists():
        (target / "sprites.json").write_text('{\n  "agents": {}\n}\n', encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("folder", nargs="?", default=".")
    a.add_argument("--profile")
    a.add_argument("--id")
    a.add_argument("--data")
    a.add_argument("--apply", action="store_true")
    a.add_argument("--claude-md", action="store_true")
    a.add_argument("--remove", action="store_true")
    args = a.parse_args()
    folder = Path(args.folder).resolve()
    data = data_folder(args.data)
    ident = args.id or registry.ident_of(folder)
    if args.remove:
        registry.unregister(data, ident)
        print(f"config del hook: {registry.write_hook_config(data, kept_extra(data))}")
        print(f"Proyecto {ident} dado de baja. El perfil y los eventos quedan.")
        return 0
    if not folder.is_dir():
        sys.exit(f"No existe la carpeta {folder}")
    p = plan(folder, ident, args.profile, data)
    print(f"Proyecto: {folder} (id: {ident})")
    for line in p["actions"]:
        print(line)
    if p["claude_md"] and not p["claude_md"]["present"]:
        print(f"\nCon --claude-md se agrega a {p['claude_md']['path']}:\n\n{p['claude_md']['block']}")
    elif p["claude_md"]:
        print(f"\n{p['claude_md']['path']} ya tiene el bloque de los tablones.")
    if not args.apply:
        print("\n(Plan solamente: no se escribió nada. Para aplicarlo: --apply)")
        return 0
    if not args.profile:
        create_profile(folder, p)
        for n in p["boards"]["create"]:
            template = boards.TASKS_TEMPLATE if n.startswith("pend") else boards.FRICTIONS_TEMPLATE
            (folder / n).write_text(template, encoding="utf-8")
        if args.claude_md and not p["claude_md"]["present"]:
            path = p["claude_md"]["path"]
            previous = path.read_text(encoding="utf-8") if path.exists() else ""
            path.write_text(previous.rstrip() + ("\n\n" if previous.strip() else "") + p["claude_md"]["block"],
                            encoding="utf-8")
            print(f"Bloque de tablones agregado a {path}")
    registry.register(data, ident, folder, p["profile"])
    print(f"Registrado en {data / 'projects.json'}")
    print(f"config del hook: {registry.write_hook_config(data, kept_extra(data))}")
    others = [x["id"] for x in read_projects(data)]
    print(f"Proyectos en la oficina: {', '.join(others)}")
    return 0


def kept_extra(data):
    """Keeps what the installer registered (python, repo, original statusline): start-office.ps1 checks python."""
    try:
        previous = json.loads((data / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"repo": str(REPO)}
    return {k: previous[k] for k in ("python", "repo", "original_statusline") if k in previous} or {"repo": str(REPO)}


if __name__ == "__main__":
    sys.exit(main())
