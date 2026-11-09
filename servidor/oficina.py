"""La oficina: arma la foto completa a partir de eventos, catálogo, flujos y archivos del equipo."""
import datetime as dt
import hashlib
import json
import os
import threading
import time
from pathlib import Path

from .area import Area
from .candidatos import Candidatos
from .catalogo import Catalogo
from .eventos import LectorEventos
from .flujos import Flujos
from .modelo import Modelo, proxima_corrida, zona_de
from .perfil import Perfil
from . import tablones
from .util import relativa_al_area

REPO = Path(__file__).resolve().parent.parent
CADA_CATALOGO_S = 5
CADA_BARRIDO_S = 300
CADA_RECALCULO_S = 10


def cargar_json(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def dentro_de(ruta, base):
    if not ruta or not base:
        return False
    r = os.path.normcase(os.path.normpath(ruta))
    b = os.path.normcase(os.path.normpath(base))
    return r == b or r.startswith(b.rstrip("\\/") + os.sep)


class Oficina:
    """La oficina de un proyecto. Con `proyecto` (y un `lector` compartido) se queda solo con sus eventos:
    los que el hook marcó con su id o, en eventos viejos sin marca, los de su carpeta."""

    def __init__(self, datos=None, perfil=None, raiz_area=None, equipo_dir=None, proyecto=None, lector=None):
        self.perfil = perfil if isinstance(perfil, Perfil) else Perfil(perfil)
        self.config = self.perfil.datos
        # La carpeta del perfil: de ahí salen zonas, flujos, layout y sprites, y ahí guarda el editor
        self.config_dir = self.perfil.carpeta
        self.datos = Path(datos) if datos else self.perfil.carpeta_datos()
        self.raiz = raiz_area or self.perfil.raiz
        self.equipo = equipo_dir or self.perfil.equipo
        self.zonas = self.perfil.archivo("zonas.json", {})
        self.archivos = self.perfil["archivos"]
        self.area = Area(self.raiz, raices=self.perfil["raices"], remember=self.archivos.get("remember"),
                         status=self.archivos.get("status"))
        self.flujos = Flujos({"verificador": self.perfil["verificador"], **self.perfil.archivo("flujos.json", {})}, self.area)
        self.catalogo = Catalogo(self.equipo, self.zonas, self.area)
        self.proyecto = proyecto
        self.lector_propio = lector is None
        self.lector = lector or LectorEventos(self.datos / "eventos")
        self.candidatos = Candidatos(self.datos / "eventos", self.es_mio)
        self.umbrales = self.config.get("umbrales", {})
        self._conocidos = []
        self._barrido_en = None
        self._refrescadas = set()
        self._catalogo_en = 0
        self._recalculo_en = 0
        self._huella = None
        self.version = 0
        self.foto = None
        self.cambio = threading.Condition()

    # --- Ciclo --------------------------------------------------------------------

    def es_mio(self, evento):
        if not self.proyecto:
            return True
        marca = evento.get("proyecto")
        if marca:
            return marca == self.proyecto
        return dentro_de(evento.get("cwd"), self.equipo)

    def eventos(self):
        return [e for e in self.lector.eventos if self.es_mio(e)] if self.proyecto else self.lector.eventos

    def actualizar(self, ahora=None, forzar=False, hay_nuevos=None):
        """Lee lo nuevo y recalcula si hace falta. Devuelve True si la foto cambió.
        Con un lector compartido, quien lo maneja lee y pasa `hay_nuevos`."""
        ahora = ahora or dt.datetime.now().astimezone()
        reloj = time.monotonic()
        if hay_nuevos is None:
            hay_nuevos = self.lector.leer_nuevos(ahora.date()) > 0
        barrido = self._barrido_en is None or reloj - self._barrido_en > CADA_BARRIDO_S
        if barrido:
            self.barrido()
            self._barrido_en = reloj
        if forzar or barrido or reloj - self._catalogo_en > CADA_CATALOGO_S:
            self.catalogo.escanear()
            self._catalogo_en = reloj
        if not (forzar or barrido or hay_nuevos or self.foto is None or reloj - self._recalculo_en > CADA_RECALCULO_S):
            return False
        self._recalculo_en = reloj
        foto = self.armar(ahora)
        huella = hashlib.sha1(json.dumps({k: v for k, v in foto.items() if k != "generado"}, sort_keys=True,
                                         default=str).encode()).hexdigest()
        if huella == self._huella:
            return False
        with self.cambio:
            self._huella = huella
            self.version += 1
            foto["version"] = self.version
            self.foto = foto
            self.cambio.notify_all()
        return True

    def barrido(self):
        """Cada 5 minutos: lista la lista blanca y lee lo que cambió (encabezados, archivos del equipo)."""
        self.area.barrido()
        self._conocidos = sorted(set(self.area.en_cache()))

    def conocidos(self):
        return sorted(set(self._conocidos) | set(self.area.en_cache()))

    def refrescar_nombradas(self, escrituras):
        """Lee solo las rutas que nombró un evento nuevo (cada escritura se refresca una vez)."""
        for w in escrituras:
            clave = (w["ruta"], w["ts"])
            if clave not in self._refrescadas:
                self._refrescadas.add(clave)
                self.area.refrescar(w["ruta"])

    # --- Foto ---------------------------------------------------------------------

    def armar(self, ahora):
        agentes = self.catalogo.frontmatters()
        contexto = {
            "raiz_area": self.raiz,
            "relativa": lambda ruta, cwd: relativa_al_area(ruta, self.raiz, cwd),
            "es_documento": self.flujos.es_documento,
            "agentes": agentes,
            "generales": self.zonas.get("generales", []),
            "umbrales": self.umbrales,
            "scripts": self.perfil["scripts"],
            "memoria_mcp": self.perfil["memoria_mcp"],
        }
        modelo = Modelo(contexto).aplicar(self.eventos())
        self.refrescar_nombradas(modelo.escrituras)
        foto = modelo.foto(ahora)
        for inst in foto["instancias"]:
            zona, sin_zona = zona_de(inst["tipo"], self.zonas.get("reglas", []), self.zonas.get("generales", []),
                                     self.zonas.get("zona_generales", "flotante"), self.zonas.get("zona_sin_regla", "recepcion"))
            if inst["general"]:
                zona, sin_zona = self.zonas.get("zona_generales", "flotante"), False
            inst["zona"], inst["sin_zona"] = zona, sin_zona
            inst["rol"] = (agentes.get(inst["tipo"]) or {}).get("descripcion")
        pendientes = self.bloques("pendientes")
        flujos = self.flujos.construir(foto, modelo.escrituras, modelo.operaciones_drive, pendientes, self.conocidos(),
                                       modelo.etiquetas())
        abiertas = [s for s in foto["sesiones"] if not s["fin"]]
        actual = (sorted([s for s in abiertas if s["origen"] != "corrida-semanal"], key=lambda s: s["ultimo_evento"])
                  or sorted(foto["sesiones"], key=lambda s: s["ultimo_evento"]) or [None])[-1]
        principal = next((i for i in foto["instancias"] if actual and i["principal"] and i["sesion"] == actual["id"]), None)
        avisos = self.catalogo.avisos_reinicio(abiertas)
        status = self.area.status()
        corridas = [s for s in status if s["tipo"] == "corrida"]
        corrida_sesiones = [s for s in foto["sesiones"] if s["origen"] == "corrida-semanal"]
        tablero = self.tablones(pendientes, foto["tareas_sesion"])
        return {
            "generado": ahora.isoformat(timespec="seconds"),
            "principal": principal and {**principal, "aviso_reinicio": next((a["texto"] for a in avisos if a["sesion"] == principal["sesion"]), None)},
            "sesion_actual": actual,
            **foto,
            **flujos,
            "avisos": avisos,
            "vacantes": [a["nombre"] for a in self.catalogo.foto()["agentes"] if a["vacante"]],
            "responsable": {
                "pendientes": len(tablero["pendientes"]["en_curso"]) + len(tablero["pendientes"]["siguen"]),
                "aprobaciones": len(foto["aprobaciones"]),
                "ultimo_prompt": (actual or {}).get("ultimo_prompt_usuario"),
                "esperas": [{"ruta": d["ruta"], "espera": d["espera_responsable"]} for d in flujos["documentos"] if d["espera_responsable"]],
            },
            "reloj": {
                "proxima": self.proxima_corrida(ahora),
                "ultima": max([c["fecha"] for c in corridas if c["fecha"]] + [s["inicio"][:10] for s in corrida_sesiones], default=None),
                "en_curso": any(not s["fin"] for s in corrida_sesiones),
            },
            "salud": self.salud(ahora),
            "tablones": tablero,
            "statusline": self.statusline(ahora, actual),
            "candidatos": self.candidatos.calcular(
                ahora.date(),
                lambda tipo: tipo in self.zonas.get("generales", []) or (bool(agentes) and tipo not in agentes),
                self.conocidos()),
        }

    def salud(self, ahora):
        errores = self.datos / "errores.log"
        recientes = 0
        if errores.exists():
            limite = (ahora - dt.timedelta(hours=24)).isoformat(timespec="seconds")
            for linea in errores.read_text(encoding="utf-8", errors="replace").splitlines():
                if linea[:19] >= limite[:19]:
                    recientes += 1
        return {"errores_hook_24h": recientes, "lineas_descartadas": self.lector.descartadas}

    # --- Consultas -----------------------------------------------------------------

    def guardar_layout(self, datos):
        """Escritura atómica de layout.json en la carpeta del perfil; la anterior queda en layout.json.bak."""
        destino = self.config_dir / "layout.json"
        temporal = destino.with_suffix(".json.tmp")
        temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        if destino.exists():
            os.replace(destino, destino.with_suffix(".json.bak"))
        os.replace(temporal, destino)

    def statusline(self, ahora, sesion_actual):
        """Lo último que la statusline (plugin/statusline/envoltorio.mjs) vio de este proyecto: modelo,
        esfuerzo, contexto y límites. Prefiere la sesión actual; ignora fotos de más de 12 horas."""
        carpeta = self.datos / "statusline"
        if not carpeta.is_dir():
            return None
        limite = time.time() - 12 * 3600
        candidatas = []
        for ruta in carpeta.glob("*.json"):
            try:
                if ruta.stat().st_mtime < limite:
                    if ruta.stat().st_mtime < time.time() - 7 * 86400:
                        ruta.unlink(missing_ok=True)
                    continue
                f = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if self.proyecto and f.get("proyecto") != self.proyecto:
                continue
            candidatas.append(f)
        if not candidatas:
            return None
        actual = (sesion_actual or {}).get("id")
        elegida = next((f for f in candidatas if actual and f.get("sesion") == actual), None)             or max(candidatas, key=lambda f: f.get("ts") or "")
        try:
            edad = (ahora - dt.datetime.fromisoformat(elegida["ts"].replace("Z", "+00:00"))).total_seconds()
        except (KeyError, ValueError, TypeError):
            edad = None
        return {**elegida, "segundos": int(edad) if edad is not None else None}

    def tablones(self, pendientes, tareas_sesion):
        ruta_p = self.archivos.get("pendientes")
        texto = self.area.texto(ruta_p) if ruta_p else None
        return {
            "pendientes": {"ruta": ruta_p, **tablones.pendientes(texto, pendientes, tareas_sesion)},
            "auditorias": {"ruta": self.archivos.get("fricciones"), **tablones.auditorias(self.bloques("fricciones"))},
        }

    def bloques(self, cual):
        """pendientes.md, fricciones.md o decisiones.md del equipo, si el perfil los define."""
        ruta = self.archivos.get(cual)
        return self.area.bloques(ruta) if ruta else {"ruta": None, "entradas": []}

    def proxima_corrida(self, ahora):
        corrida = self.perfil.get("corrida")
        if not corrida:
            return None
        return proxima_corrida(ahora, corrida.get("dia_semana", 2), corrida.get("hora", 10)).isoformat(timespec="minutes")

    def config_json(self, nombre):
        """Un archivo de config/ (layout o sprites). Si no existe, FileNotFoundError → 404."""
        return cargar_json(self.config_dir / nombre)

    def equipo_archivos(self):
        return {
            "pendientes": self.bloques("pendientes"),
            "fricciones": self.bloques("fricciones"),
            "decisiones": self.bloques("decisiones"),
            "remember": self.area.remember(),
            "status": self.area.status(),
            "catalogo": self.catalogo.foto(),
        }
