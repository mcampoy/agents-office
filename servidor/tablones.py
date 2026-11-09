"""Los dos tablones fijos de cada proyecto: pendientes y auditorías (fricciones).

Pendientes (la bandeja del responsable), en tres columnas:
- en curso: tareas de Claude Code creadas y no completadas en la sesión, más la sección "En curso" de pendientes.md;
- siguen: la sección "Siguen" de pendientes.md. Si el archivo no tiene secciones (por ejemplo, entradas
  "## fecha · título" como en equipo-idi), cada entrada es algo que sigue;
- hechas: tareas completadas en la sesión, más la sección "Hechas" de pendientes.md.

Auditorías: las entradas "## fecha · título" de fricciones.md, abiertas o resueltas según su campo Estado.

Formatos estándar (los crea scripts/configurar.py en proyectos nuevos): ver PLANTILLA_PENDIENTES y
PLANTILLA_FRICCIONES.
"""
import re

PLANTILLA_PENDIENTES = """# Pendientes

Tablón de pendientes del proyecto: lo leen la oficina y los agentes. Una línea por tarea, `- [ ] tarea`
(`- [x]` cuando se termina), en la sección que corresponda.

## En curso

## Siguen

## Hechas
"""

PLANTILLA_FRICCIONES = """# Fricciones

Auditoría del trabajo: lo que trabó, salió mal o se repite. Una entrada por fricción, la más nueva arriba.

<!-- Formato de cada entrada:
## AAAA-MM-DD · Título corto
**Estado:** abierta
**Qué pasó:** ...
**Propuesta:** ...
-->
"""

SECCIONES = {
    "en_curso": ("en curso", "haciendo", "doing", "in progress"),
    "siguen": ("siguen", "siguientes", "próximas", "proximas", "pendientes", "por hacer", "to do", "todo", "next"),
    "hechas": ("hechas", "hecho", "realizadas", "terminadas", "done"),
}
ITEM = re.compile(r"^\s*[-*]\s+(?:\[( |x|X)\]\s+)?(.+?)\s*$")


def _columna(titulo):
    t = titulo.strip().lower()
    for columna, nombres in SECCIONES.items():
        if any(t.startswith(n) for n in nombres):
            return columna
    return None


def secciones(texto):
    """Ítems de las secciones En curso / Siguen / Hechas, o None si el archivo no las usa."""
    columnas = {"en_curso": [], "siguen": [], "hechas": []}
    actual = None
    encontradas = False
    for linea in (texto or "").splitlines():
        m = re.match(r"^#{2,3}\s+(.+)$", linea)
        if m:
            actual = _columna(m.group(1))
            encontradas = encontradas or actual is not None
            continue
        if actual:
            i = ITEM.match(linea)
            if i:
                hecha = (i.group(1) or "").lower() == "x"
                columnas["hechas" if hecha else actual].append({"titulo": i.group(2), "fuente": "archivo"})
    return columnas if encontradas else None


def pendientes(texto, bloques, tareas_sesion):
    columnas = secciones(texto) or {
        "en_curso": [],
        "siguen": [{"titulo": e["titulo"], "fecha": e.get("fecha"), "fuente": "archivo"} for e in (bloques or {}).get("entradas", [])],
        "hechas": [],
    }
    for t in tareas_sesion:
        item = {"titulo": t.get("titulo") or "(sin título)", "fuente": "sesion", "instancia": t.get("instancia"),
                "ts": t.get("completada") or t.get("creada")}
        columnas["hechas" if t.get("completada") else "en_curso"].insert(0, item)
    return columnas


def auditorias(bloques):
    abiertas, resueltas = [], []
    for e in (bloques or {}).get("entradas", []):
        campos = {k.lower(): v for k, v in (e.get("campos") or {}).items()}
        estado = next((v for k, v in campos.items() if k.startswith("estado")), "")
        resuelta = bool(re.search(r"resuelt|cerrad|hecho|solved|closed", estado, re.I))
        item = {"titulo": e["titulo"], "fecha": e.get("fecha"), "estado": estado or "abierta",
                "detalle": {k: v for k, v in (e.get("campos") or {}).items() if v}}
        (resueltas if resuelta else abiertas).append(item)
    return {"abiertas": abiertas, "resueltas": resueltas}
