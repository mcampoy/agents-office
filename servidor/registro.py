"""Registro de proyectos de la oficina (<datos>/proyectos.json) y la config del hook (<datos>/config.json).

Lo usan scripts/configurar.py (alta de un proyecto) y scripts/instalar.py (instalación del plugin).
"""
import json
import re
from pathlib import Path

from .oficinas import carpeta_comun, leer_proyectos
from .perfil import Perfil


def ident_de(carpeta):
    """Id legible y estable a partir del nombre de la carpeta del proyecto."""
    nombre = Path(carpeta).name.lower()
    return re.sub(r"[^a-z0-9]+", "-", nombre).strip("-") or "proyecto"


def registrar(datos, ident, carpeta, perfil):
    datos = carpeta_comun(datos)
    datos.mkdir(parents=True, exist_ok=True)
    proyectos = [p for p in leer_proyectos(datos) if p["id"] != ident]
    proyectos.append({"id": ident, "dir": str(Path(carpeta).resolve()), "perfil": str(Path(perfil).resolve())})
    (datos / "proyectos.json").write_text(json.dumps({"proyectos": proyectos}, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return proyectos


def quitar(datos, ident):
    datos = carpeta_comun(datos)
    proyectos = [p for p in leer_proyectos(datos) if p["id"] != ident]
    (datos / "proyectos.json").write_text(json.dumps({"proyectos": proyectos}, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return proyectos


def escribir_config_hook(datos, extra=None):
    """<datos>/config.json: un bloque por proyecto con lo que el hook necesita para filtrar y redactar."""
    datos = carpeta_comun(datos)
    proyectos = []
    for p in leer_proyectos(datos):
        try:
            perfil = Perfil(p["perfil"])
        except (OSError, ValueError):
            continue
        hook = perfil.para_el_hook()
        hook.pop("equipo_dir", None)
        proyectos.append({"id": p["id"], "dir": p["dir"], **hook})
    config = {"proyectos": proyectos, **(extra or {})}
    datos.mkdir(parents=True, exist_ok=True)
    destino = datos / "config.json"
    destino.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destino
