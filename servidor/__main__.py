"""Uso: py -3 -m servidor [--perfil CARPETA] [--puerto 8765] [--datos CARPETA]

Sin --perfil: AGENTS_OFFICE_PERFIL, local.json o perfiles/ejemplo (ver docs/perfil.md)."""
import argparse
import sys

from .oficina import Oficina
from .red import correr


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="servidor")
    p.add_argument("--puerto", type=int)
    p.add_argument("--datos")
    p.add_argument("--perfil")
    args = p.parse_args()
    oficina = Oficina(datos=args.datos, perfil=args.perfil)
    print(f"Perfil: {oficina.perfil.carpeta} · datos: {oficina.datos}")
    correr(oficina, args.puerto or oficina.config.get("puerto", 8765))


if __name__ == "__main__":
    main()
