"""Uso: py -3 -m servidor [--perfil CARPETA] [--puerto 8765] [--datos CARPETA]

Sin --perfil: los proyectos registrados en <datos>/proyectos.json (scripts/configurar.py). Si no hay ninguno,
un solo perfil: AGENTS_OFFICE_PERFIL, local.json o perfiles/ejemplo (ver docs/perfil.md)."""
import argparse
import sys

from .oficinas import Oficinas
from .red import correr


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="servidor")
    p.add_argument("--puerto", type=int)
    p.add_argument("--datos")
    p.add_argument("--perfil")
    args = p.parse_args()
    oficinas = Oficinas(datos=args.datos, perfil=args.perfil)
    for ident, o in oficinas.oficinas.items():
        print(f"Proyecto {ident}: perfil {o.perfil.carpeta}")
    print(f"Datos: {oficinas.datos if oficinas.lector else next(iter(oficinas.oficinas.values())).datos}")
    primera = next(iter(oficinas.oficinas.values()))
    correr(oficinas, args.puerto or primera.config.get("puerto", 8765))


if __name__ == "__main__":
    main()
