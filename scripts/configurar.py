"""Registra un proyecto en la oficina (lo que hace /oficina:configurar).

Uso:
    py -3 scripts/configurar.py [CARPETA] [--perfil CARPETA] [--id ID] [--aplicar] [--claude-md] [--quitar]

Sin --aplicar solo muestra el plan: no escribe nada. Con --aplicar:
1. Si no se da --perfil, arma uno en <datos>/perfiles/<id>/:
   - perfil.json con el proyecto como área (lista blanca: todo el proyecto, salvo carpetas de build);
   - zonas.json a partir de los agentes de .claude/agents (lente-* a lectura, verificador al paso,
     investigadores a exploración, el resto a la sala base);
   - el layout de ejemplo y sprites.json vacío.
   Con --perfil (un perfil ya armado, como el de equipo-idi) usa ese y no toca el proyecto.
2. Tablones: busca pendientes.md y fricciones.md (en la raíz o en docs/). Si faltan, los crea con el
   formato estándar (servidor/tablones.py).
3. Con --claude-md, agrega al CLAUDE.md del proyecto un bloque (entre marcas, se puede volver a correr)
   que les pide a los agentes mantener los tablones.
4. Registra el proyecto en <datos>/proyectos.json y regenera <datos>/config.json para el hook.

Las sesiones nuevas del proyecto se capturan desde ese momento (el hook lee la config en cada evento).
--quitar lo da de baja (no borra el perfil ni los eventos).
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from servidor.oficinas import carpeta_comun, leer_proyectos  # noqa: E402
from servidor.perfil import Perfil  # noqa: E402
from servidor import registro, tablones  # noqa: E402
from servidor.util import frontmatter  # noqa: E402

EJEMPLO = REPO / "perfiles" / "ejemplo"
MARCA_INICIO = "<!-- oficina:tablones -->"
MARCA_FIN = "<!-- /oficina:tablones -->"


def bloque_claude_md(pendientes, fricciones):
    return f"""{MARCA_INICIO}
## Tablones de la oficina

- `{pendientes}`: cuando empezás una tarea pedida, anotala en **En curso** (`- [ ] tarea`). Lo que quede para
  después va en **Siguen**. Al terminarla, pasala a **Hechas** con `- [x]`.
- `{fricciones}`: si algo traba el trabajo (falta un permiso, falla una herramienta, un pedido es ambiguo, un
  error se repite), agregá arriba una entrada `## AAAA-MM-DD · título` con **Estado:** abierta, **Qué pasó:** y
  **Propuesta:**. Cuando se resuelva, cambiá el estado a `resuelta`.
{MARCA_FIN}
"""


def buscar(carpeta, nombres):
    for n in nombres:
        if (carpeta / n).is_file():
            return n
    return None


def zona_sugerida(nombre):
    n = nombre.lower()
    if n.startswith("lente-") or "lente" in n:
        return "lectura"
    if "verific" in n or "review" in n or "audit" in n:
        return "paso-verificacion"
    if "investig" in n or "research" in n or "explor" in n or n == "radar":
        return "exploracion"
    if "comunic" in n or "maquet" in n or "design" in n or "disen" in n:
        return "comunicacion"
    return "base"


def agentes_del_proyecto(carpeta):
    salida = []
    for ruta in sorted((carpeta / ".claude" / "agents").glob("*.md")):
        try:
            campos = frontmatter(ruta.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            campos = {}
        salida.append(campos.get("name") or ruta.stem)
    return salida


def principal_del_proyecto(carpeta):
    for nombre in ("settings.json", "settings.local.json"):
        try:
            datos = json.loads((carpeta / ".claude" / nombre).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(datos.get("agent"), str):
            return datos["agent"]
    return "principal"


def plan(carpeta, ident, perfil_dado, datos):
    acciones = []
    if perfil_dado:
        perfil = Perfil(perfil_dado)
        acciones.append(f"Usar el perfil existente {perfil.carpeta} (no se toca el proyecto).")
        return {"ident": ident, "perfil": perfil.carpeta, "crear_perfil": None, "tablones": {}, "acciones": acciones,
                "claude_md": None}
    destino = datos / "perfiles" / ident
    agentes = agentes_del_proyecto(carpeta)
    principal = principal_del_proyecto(carpeta)
    pend = buscar(carpeta, ["pendientes.md", "PENDIENTES.md", "docs/pendientes.md"])
    fric = buscar(carpeta, ["fricciones.md", "FRICCIONES.md", "docs/fricciones.md"])
    tab = {"pendientes": pend or "pendientes.md", "fricciones": fric or "fricciones.md",
           "crear": [n for n, existe in (("pendientes.md", pend), ("fricciones.md", fric)) if not existe]}
    zonas = [{"agente": a, "zona": zona_sugerida(a)} for a in agentes if a != principal]
    acciones.append(f"Crear el perfil en {destino} (agente principal: {principal}; {len(agentes)} agentes).")
    for z in zonas:
        acciones.append(f"  - {z['agente']} → sala {z['zona']}")
    for n in tab["crear"]:
        acciones.append(f"Crear {carpeta / n} con el formato estándar del tablón.")
    for clave in ("pendientes", "fricciones"):
        if tab[clave] not in tab["crear"]:
            acciones.append(f"Usar el {clave} que ya existe: {tab[clave]}.")
    claude_md = carpeta / "CLAUDE.md"
    actual = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
    return {"ident": ident, "perfil": destino, "principal": principal, "zonas": zonas, "tablones": tab,
            "acciones": acciones, "agentes": agentes,
            "claude_md": {"ruta": claude_md, "ya_esta": MARCA_INICIO in actual,
                          "bloque": bloque_claude_md(tab["pendientes"], tab["fricciones"])}}


def crear_perfil(carpeta, p):
    destino = Path(p["perfil"])
    destino.mkdir(parents=True, exist_ok=True)
    ejemplo = json.loads((EJEMPLO / "perfil.json").read_text(encoding="utf-8"))
    perfil = {
        "_comentario": "Perfil generado por scripts/configurar.py. Formato: docs/perfil.md del repo agents-office.",
        "nombre": carpeta.name,
        "raiz_area": str(carpeta),
        "equipo_dir": ".",
        "puerto": 8765,
        "raices": ["."],
        "archivos": {"pendientes": p["tablones"]["pendientes"], "fricciones": p["tablones"]["fricciones"]},
        "principal": p["principal"],
        "verificador": next((z["agente"] for z in p["zonas"] if z["zona"] == "paso-verificacion"), None),
        "responsable": "responsable",
        "scripts": {"conocidos": [], "buzon": None, "canales": [], "canal_por_defecto": "avisos", "controles": []},
        "corrida": None,
        "piso": {**ejemplo["piso"], "nombres_cortos": {"general-purpose": "general"}, "junto_al_reloj": None,
                 "trabajo_externo": {}},
    }
    if not (destino / "perfil.json").exists():
        (destino / "perfil.json").write_text(json.dumps(perfil, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    zonas = {
        "_comentario": "Zona de cada agente. Patrones con '*'. Un agente sin regla va a la recepción.",
        "reglas": [{"agente": "lente-*", "zona": "lectura"}, {"agente": p["principal"], "zona": "coordinacion"}]
                  + [z for z in p["zonas"] if not z["agente"].startswith("lente-")],
        "generales": ["general-purpose", "Explore", "Plan", "claude", "claude-code-guide", "statusline-setup"],
        "zona_generales": "flotante",
        "zona_sin_regla": "recepcion",
    }
    if not (destino / "zonas.json").exists():
        (destino / "zonas.json").write_text(json.dumps(zonas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not (destino / "layout.json").exists():
        shutil.copyfile(EJEMPLO / "layout.json", destino / "layout.json")
    if not (destino / "sprites.json").exists():
        (destino / "sprites.json").write_text('{\n  "agentes": {}\n}\n', encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("carpeta", nargs="?", default=".")
    a.add_argument("--perfil")
    a.add_argument("--id")
    a.add_argument("--datos")
    a.add_argument("--aplicar", action="store_true")
    a.add_argument("--claude-md", action="store_true")
    a.add_argument("--quitar", action="store_true")
    args = a.parse_args()
    carpeta = Path(args.carpeta).resolve()
    datos = carpeta_comun(args.datos)
    ident = args.id or registro.ident_de(carpeta)
    if args.quitar:
        registro.quitar(datos, ident)
        print(f"config del hook: {registro.escribir_config_hook(datos, extra_python(datos))}")
        print(f"Proyecto {ident} dado de baja. El perfil y los eventos quedan.")
        return 0
    if not carpeta.is_dir():
        sys.exit(f"No existe la carpeta {carpeta}")
    p = plan(carpeta, ident, args.perfil, datos)
    print(f"Proyecto: {carpeta} (id: {ident})")
    for linea in p["acciones"]:
        print(linea)
    if p["claude_md"] and not p["claude_md"]["ya_esta"]:
        print(f"\nCon --claude-md se agrega a {p['claude_md']['ruta']}:\n\n{p['claude_md']['bloque']}")
    elif p["claude_md"]:
        print(f"\n{p['claude_md']['ruta']} ya tiene el bloque de los tablones.")
    if not args.aplicar:
        print("\n(Plan solamente: no se escribió nada. Para aplicarlo: --aplicar)")
        return 0
    if not args.perfil:
        crear_perfil(carpeta, p)
        for n in p["tablones"]["crear"]:
            plantilla = tablones.PLANTILLA_PENDIENTES if n.startswith("pend") else tablones.PLANTILLA_FRICCIONES
            (carpeta / n).write_text(plantilla, encoding="utf-8")
        if args.claude_md and not p["claude_md"]["ya_esta"]:
            ruta = p["claude_md"]["ruta"]
            previo = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
            ruta.write_text(previo.rstrip() + ("\n\n" if previo.strip() else "") + p["claude_md"]["bloque"], encoding="utf-8")
            print(f"Bloque de tablones agregado a {ruta}")
    registro.registrar(datos, ident, carpeta, p["perfil"])
    print(f"Registrado en {datos / 'proyectos.json'}")
    print(f"config del hook: {registro.escribir_config_hook(datos, extra_python(datos))}")
    otros = [x["id"] for x in leer_proyectos(datos)]
    print(f"Proyectos en la oficina: {', '.join(otros)}")
    return 0


def extra_python(datos):
    """Conserva el python registrado por el instalador (iniciar-oficina.ps1 lo verifica)."""
    try:
        previo = json.loads((datos / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"repo": str(REPO)}
    return {k: previo[k] for k in ("python", "repo") if k in previo} or {"repo": str(REPO)}


if __name__ == "__main__":
    sys.exit(main())
