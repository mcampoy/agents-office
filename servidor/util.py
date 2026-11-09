"""Utilidades compartidas: patrones glob, rutas del área, frontmatter y tabla de encabezado."""
import functools
import os
import re
from pathlib import PureWindowsPath


@functools.lru_cache(maxsize=512)
def glob_a_regex(patron):
    """Glob con '/' como separador: '*' no cruza carpetas, '**' sí (incluida ninguna)."""
    partes, i = [], 0
    while i < len(patron):
        c = patron[i]
        if patron.startswith("**/", i):
            partes.append("(?:.*/)?")
            i += 3
        elif patron.startswith("**", i):
            partes.append(".*")
            i += 2
        elif c == "*":
            partes.append("[^/]*")
            i += 1
        elif c == "?":
            partes.append("[^/]")
            i += 1
        else:
            partes.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(partes) + "$", re.IGNORECASE)


def coincide(ruta, patron):
    return bool(glob_a_regex(patron).match(ruta))


def relativa_al_area(ruta, raiz, cwd=None):
    """Ruta relativa a la raíz del área con '/', o None si queda afuera.

    Acepta rutas absolutas de Windows, con '/' o '\\', y relativas al cwd del evento.
    """
    if not ruta or not isinstance(ruta, str):
        return None
    p = ruta.strip().strip('"')
    if not (PureWindowsPath(p).is_absolute() or p.startswith(("/", "\\"))):
        if not cwd:
            return None
        p = os.path.join(cwd, p)
    absoluta = os.path.normcase(os.path.normpath(p))
    base = os.path.normcase(os.path.normpath(raiz)).rstrip("\\/")
    if not absoluta.startswith(base + os.sep):
        return None
    # Conserva las mayúsculas originales del tramo relativo.
    original = os.path.normpath(p)
    return original[len(base) + 1:].replace("\\", "/")


def frontmatter(texto):
    """Campos simples 'clave: valor' del bloque YAML inicial de un agente o skill."""
    if not texto.startswith("---"):
        return {}
    fin = texto.find("\n---", 3)
    if fin < 0:
        return {}
    campos = {}
    for linea in texto[3:fin].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", linea)
        if m:
            campos[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return campos


def tabla_de_encabezado(lineas):
    """La primera tabla de las primeras líneas: {columna: valor}. Se lee por nombre de columna."""
    filas = []
    for linea in lineas:
        s = linea.strip()
        if s.startswith("|"):
            filas.append(s)
        elif filas:
            break
    if len(filas) < 3 or not re.fullmatch(r"\|[\s:|-]+\|", filas[1]):
        return {}
    columnas = [c.strip() for c in filas[0].strip("|").split("|")]
    valores = [c.strip() for c in filas[2].strip("|").split("|")]
    return {c: v for c, v in zip(columnas, valores) if c}


ESTADOS_DOCUMENTO = ("borrador", "revisado", "aprobado para difusión")
