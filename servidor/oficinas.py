"""Varias oficinas, una por proyecto registrado.

Los proyectos se registran con `scripts/configurar.py` (o `/oficina:configurar`) en `<datos>/proyectos.json`:

    {"proyectos": [{"id": "equipo-idi", "dir": "G:\\\\...\\\\equipo-idi", "perfil": "C:\\\\...\\\\perfil"}]}

`<datos>` es la carpeta común de la oficina (AGENTS_OFFICE_DATOS o ~/.agents-office). Todos los proyectos
comparten la carpeta de eventos: el hook marca cada evento con el id de su proyecto. Cada proyecto tiene su
perfil (zonas, layout, flujos, tablones) y su propia foto.

Sin proyectos registrados, la oficina muestra un solo perfil (el de `--perfil`, AGENTS_OFFICE_PERFIL,
local.json o el de ejemplo), como antes.
"""
import json
import os
from pathlib import Path

from .eventos import LectorEventos
from .oficina import Oficina
from .perfil import Perfil


def carpeta_comun(explicita=None):
    elegida = explicita or os.environ.get("AGENTS_OFFICE_DATOS") or "~/.agents-office"
    return Path(os.path.expandvars(str(elegida))).expanduser()


def leer_proyectos(datos):
    try:
        registro = json.loads((Path(datos) / "proyectos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in registro.get("proyectos", []) if p.get("id") and p.get("dir") and p.get("perfil")]


class Oficinas:
    def __init__(self, datos=None, perfil=None):
        self.datos = carpeta_comun(datos)
        proyectos = [] if perfil else leer_proyectos(self.datos)
        self.oficinas = {}
        if proyectos:
            self.lector = LectorEventos(self.datos / "eventos")
            for p in proyectos:
                self.oficinas[p["id"]] = Oficina(datos=self.datos, perfil=Perfil(p["perfil"]), equipo_dir=p["dir"],
                                                 proyecto=p["id"], lector=self.lector)
        else:
            unica = Oficina(datos=datos, perfil=perfil)
            self.lector = None
            self.oficinas["oficina"] = unica

    @classmethod
    def de_una(cls, oficina):
        """Envuelve una Oficina ya armada (pruebas, modo de un solo perfil)."""
        self = cls.__new__(cls)
        self.datos = oficina.datos
        self.lector = None
        self.oficinas = {"oficina": oficina}
        return self

    def actualizar(self, ahora=None, forzar=False):
        if self.lector is not None:
            import datetime as dt
            ahora = ahora or dt.datetime.now().astimezone()
            hay = self.lector.leer_nuevos(ahora.date()) > 0
            for o in self.oficinas.values():
                o.actualizar(ahora, forzar=forzar, hay_nuevos=hay)
        else:
            for o in self.oficinas.values():
                o.actualizar(ahora, forzar=forzar)

    def ultimo_evento(self, oficina):
        sesiones = (oficina.foto or {}).get("sesiones") or []
        return max((s.get("ultimo_evento") or "" for s in sesiones), default="")

    def elegir(self, ident=None):
        """La oficina pedida o, si no se pide ninguna, la del proyecto con actividad más reciente."""
        if ident and ident in self.oficinas:
            return self.oficinas[ident]
        return max(self.oficinas.values(), key=self.ultimo_evento)

    def lista(self):
        salida = []
        for ident, o in self.oficinas.items():
            foto = o.foto or {}
            activos = sum(1 for i in foto.get("instancias", []) if i.get("estado") not in ("ocioso", "terminado"))
            salida.append({"id": ident, "nombre": o.perfil["nombre"], "ultimo_evento": self.ultimo_evento(o) or None,
                           "activos": activos})
        return sorted(salida, key=lambda p: p["ultimo_evento"] or "", reverse=True)
