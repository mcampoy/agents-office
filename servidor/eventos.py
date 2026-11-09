"""Lectura incremental de <datos>/eventos/AAAA-MM-DD.jsonl (la carpeta de datos sale del perfil).

Al iniciar carga el archivo de hoy (y el de ayer, por las sesiones que cruzan la medianoche).
Después lee solo lo nuevo desde el último byte leído. Una línea sin '\\n' final todavía se está
escribiendo: se deja para la próxima lectura. Una línea que no es JSON se descarta y se cuenta.
"""
import datetime as dt
import json
from pathlib import Path


class LectorEventos:
    def __init__(self, carpeta, dias=2):
        self.carpeta = Path(carpeta)
        self.dias = dias
        self.posiciones = {}
        self.eventos = []
        self.descartadas = 0

    def archivos(self, hoy):
        return [self.carpeta / f"{(hoy - dt.timedelta(days=d)).isoformat()}.jsonl" for d in range(self.dias - 1, -1, -1)]

    def leer_nuevos(self, hoy=None):
        """Devuelve la cantidad de eventos nuevos."""
        hoy = hoy or dt.date.today()
        nuevos = 0
        vigentes = set()
        for ruta in self.archivos(hoy):
            vigentes.add(ruta)
            if not ruta.exists():
                continue
            posicion = self.posiciones.get(ruta, 0)
            tamano = ruta.stat().st_size
            if tamano < posicion:  # el archivo se recreó
                posicion = 0
            if tamano == posicion:
                continue
            with open(ruta, "rb") as f:
                f.seek(posicion)
                bloque = f.read()
            fin = bloque.rfind(b"\n")
            if fin < 0:
                continue
            for linea in bloque[:fin].split(b"\n"):
                if not linea.strip():
                    continue
                try:
                    evento = json.loads(linea)
                except ValueError:
                    self.descartadas += 1
                    continue
                if isinstance(evento, dict):
                    self.eventos.append(evento)
                    nuevos += 1
            self.posiciones[ruta] = posicion + fin + 1
        # Cambio de día: lo que sale de la ventana se olvida.
        if any(r not in vigentes for r in self.posiciones):
            nombres = {r.stem for r in vigentes}
            self.eventos = [e for e in self.eventos if (e.get("ts") or "")[:10] in nombres]
            self.posiciones = {r: p for r, p in self.posiciones.items() if r in vigentes}
            nuevos += 1
        return nuevos
