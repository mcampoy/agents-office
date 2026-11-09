"""Perfil de equipo: todo lo que la oficina necesita saber de un equipo concreto.

El código de la oficina es genérico; un perfil es una carpeta con:

    perfil.json    datos del equipo (rutas, roles, scripts, corrida programada, textos del piso)
    zonas.json     zona del piso de cada agente
    flujos.json    reglas ruta -> tipo -> etapa de los documentos (opcional: sin él no hay flujos)
    layout.json    plano del piso (lo edita el editor de la web)
    sprites.json   sprite de cada agente (opcional)

Qué perfil se usa, en este orden: `--perfil`, la variable AGENTS_OFFICE_PERFIL, `local.json` en la raíz del
repo ({"perfil": "<carpeta>"}, no se versiona) y, si no hay nada, `perfiles/ejemplo`.
Ver docs/perfil.md.
"""
import copy
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EJEMPLO = REPO / "perfiles" / "ejemplo"

POR_DEFECTO = {
    "nombre": "Oficina",
    "raiz_area": None,
    "equipo_dir": None,
    "datos": "~/.agents-office",
    "puerto": 8765,
    "raices": [],
    "archivos": {
        "pendientes": None,
        "fricciones": None,
        "decisiones": None,
        "remember": None,
        "status": None,
    },
    "principal": "principal",
    "verificador": None,
    "responsable": "responsable",
    "scripts": {
        "conocidos": [],
        "buzon": None,
        "canales": [],
        "canal_por_defecto": "avisos",
        "controles": [],
    },
    "memoria_mcp": ["mcp__engram__", "mcp__plugin_engram"],
    "corrida": None,
    "umbrales": {},
    "piso": {
        "salas": {},
        "nombres_cortos": {},
        "accesorios": {},
        "trabajo_externo": {},
        "junto_al_reloj": None,
    },
}


def _fusionar(base, extra):
    salida = copy.deepcopy(base)
    for clave, valor in (extra or {}).items():
        if clave.startswith("_"):
            continue
        if isinstance(valor, dict) and isinstance(salida.get(clave), dict):
            salida[clave] = _fusionar(salida[clave], valor)
        else:
            salida[clave] = valor
    return salida


def carpeta_del_perfil(explicita=None):
    if explicita:
        return Path(explicita)
    if os.environ.get("AGENTS_OFFICE_PERFIL"):
        return Path(os.environ["AGENTS_OFFICE_PERFIL"])
    local = REPO / "local.json"
    if local.exists():
        try:
            elegido = json.loads(local.read_text(encoding="utf-8")).get("perfil")
        except ValueError:
            elegido = None
        if elegido:
            ruta = Path(elegido)
            return ruta if ruta.is_absolute() else (REPO / ruta)
    return EJEMPLO


def leer_json(ruta, por_defecto=None):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if por_defecto is not None:
            return por_defecto
        raise


class Perfil:
    def __init__(self, carpeta=None):
        self.carpeta = carpeta_del_perfil(carpeta).resolve()
        self.datos = _fusionar(POR_DEFECTO, leer_json(self.carpeta / "perfil.json"))
        d = self.datos
        raiz = d.get("raiz_area")
        self.raiz = str(Path(os.path.expandvars(raiz)).expanduser()) if raiz else str(self.carpeta / "area")
        equipo = d.get("equipo_dir")
        if equipo:
            ruta = Path(os.path.expandvars(equipo)).expanduser()
            self.equipo = str(ruta if ruta.is_absolute() else Path(self.raiz) / ruta)
        else:
            self.equipo = self.raiz

    def __getitem__(self, clave):
        return self.datos[clave]

    def get(self, clave, por_defecto=None):
        return self.datos.get(clave, por_defecto)

    def carpeta_datos(self, explicita=None):
        elegida = explicita or os.environ.get("AGENTS_OFFICE_DATOS") or self.datos["datos"]
        return Path(os.path.expandvars(str(elegida))).expanduser()

    def archivo(self, nombre, por_defecto=None):
        """Un JSON de la carpeta del perfil (zonas, flujos, layout, sprites)."""
        return leer_json(self.carpeta / nombre, por_defecto)

    def para_la_web(self):
        """Lo que necesita el piso: nombres, roles y textos. Sin rutas del área."""
        d = self.datos
        return {
            "nombre": d["nombre"],
            "principal": d["principal"],
            "verificador": d["verificador"],
            "responsable": d["responsable"],
            "corrida": {k: v for k, v in (d.get("corrida") or {}).items() if k in ("agente", "dia_semana", "hora")} or None,
            "piso": d["piso"],
        }

    def para_el_hook(self):
        """Lo que necesita el hook de captura (se escribe en <datos>/config.json al instalar)."""
        d = self.datos
        corrida = d.get("corrida") or {}
        return {
            "equipo_dir": self.equipo,
            "scripts": d["scripts"]["conocidos"],
            "buzon": d["scripts"]["buzon"],
            "canales": d["scripts"]["canales"],
            "canal_por_defecto": d["scripts"]["canal_por_defecto"],
            "controles": d["scripts"]["controles"],
            "variable_origen": corrida.get("variable_origen"),
        }
