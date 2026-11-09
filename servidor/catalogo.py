"""Agentes y skills del equipo, de <carpeta del equipo>/.claude en solo lectura.

Cada ciclo solo lista la carpeta y lee fechas de modificación. El contenido de las definiciones sale
de la caché del área (se lee cuando un evento nombra el archivo o en el barrido de 5 minutos).

- Agente nuevo: aparece (en la recepción si no tiene zona en config/zonas.json).
- Agente borrado: queda como vacante, con su historial.
- Definición modificada después del SessionStart de una sesión activa: aviso de reiniciar.
"""
import datetime as dt
from pathlib import Path

from .modelo import zona_de
from .util import frontmatter


class Catalogo:
    def __init__(self, equipo_dir, zonas, area):
        self.equipo = Path(equipo_dir)
        self.zonas = zonas
        self.area = area
        self.prefijo = self.equipo.relative_to(area.raiz).as_posix()
        self.agentes = {}
        self.skills = {}

    def escanear(self):
        carpeta = self.equipo / ".claude" / "agents"
        vistos = set()
        if carpeta.is_dir():
            for ruta in sorted(carpeta.glob("*.md")):
                try:
                    mtime = dt.datetime.fromtimestamp(ruta.stat().st_mtime).astimezone()
                except OSError:
                    continue
                campos = frontmatter(self.area.texto(f"{self.prefijo}/.claude/agents/{ruta.name}") or "")
                nombre = campos.get("name") or ruta.stem
                vistos.add(nombre)
                previo = self.agentes.get(nombre, {})
                zona, sin_zona = zona_de(nombre, self.zonas.get("reglas", []), self.zonas.get("generales", []),
                                         self.zonas.get("zona_generales", "flotante"), self.zonas.get("zona_sin_regla", "recepcion"))
                self.agentes[nombre] = {
                    "nombre": nombre,
                    "archivo": f"{self.prefijo}/.claude/agents/{ruta.name}",
                    "descripcion": campos.get("description"),
                    "model": campos.get("model"),
                    "effort": campos.get("effort"),
                    "tools": [t.strip() for t in campos.get("tools", "").split(",") if t.strip()] or None,
                    "modificado": mtime,
                    "zona": zona,
                    "sin_zona": sin_zona,
                    "vacante": False,
                    "visto_desde": previo.get("visto_desde") or mtime,
                }
        for nombre, agente in self.agentes.items():
            if nombre not in vistos:
                agente["vacante"] = True
        carpeta = self.equipo / ".claude" / "skills"
        self.skills = {}
        if carpeta.is_dir():
            for ruta in sorted(carpeta.glob("*/SKILL.md")):
                campos = frontmatter(self.area.texto(f"{self.prefijo}/.claude/skills/{ruta.parent.name}/SKILL.md") or "")
                nombre = campos.get("name") or ruta.parent.name
                self.skills[nombre] = {"nombre": nombre, "descripcion": campos.get("description"),
                                       "archivo": f"{self.prefijo}/.claude/skills/{ruta.parent.name}/SKILL.md"}
        return self

    def frontmatters(self):
        return {n: a for n, a in self.agentes.items() if not a["vacante"]}

    def avisos_reinicio(self, sesiones):
        """Definiciones modificadas después del inicio de una sesión abierta del equipo."""
        avisos = []
        for s in sesiones:
            if s.get("fin") or not s.get("inicio"):
                continue
            inicio = dt.datetime.fromisoformat(s["inicio"])
            cambiados = sorted(n for n, a in self.agentes.items() if a["modificado"] > inicio)
            if cambiados:
                avisos.append({"sesion": s["id"], "agentes": cambiados,
                               "texto": "Reiniciar la sesión para aplicar los cambios en: " + ", ".join(cambiados)})
        return avisos

    def foto(self):
        return {
            "agentes": [{**a, "modificado": a["modificado"].isoformat(timespec="seconds"),
                         "visto_desde": a["visto_desde"].isoformat(timespec="seconds")}
                        for a in sorted(self.agentes.values(), key=lambda a: a["nombre"])],
            "skills": sorted(self.skills.values(), key=lambda s: s["nombre"]),
        }
