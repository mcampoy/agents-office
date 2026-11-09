"""Señal de candidato a agente nuevo (heurística de la fase 0, punto 11).

Si el agente principal lanza agentes generales (sin definición propia) con descripciones parecidas varias
veces, puede convenir crear un agente especializado para esa tarea.

- Se miran los lanzamientos de agentes generales de los últimos 14 días (archivos de eventos del día).
- Cada `description` se normaliza: minúsculas, sin tildes, sin palabras vacías (español e inglés), sin
  números y sin nombres propios de proveedor (los de `*/registry/providers/*.md` del área).
- Se descartan descripciones con menos de 3 palabras útiles: con 2 palabras cualquier par se parece.
- Dos descripciones son parecidas si su similitud de Jaccard (palabras en común / palabras totales) es ≥ 0,5.
- Un grupo de 3 o más lanzamientos conectados por parecido es un candidato.

Es determinístico, no usa red y se puede explicar: el panel muestra las descripciones y las palabras en común.
Las descripciones ya están redactadas por el hook (nunca se guarda el prompt).
"""
import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

DIAS = 14
UMBRAL = 0.5
MINIMO_PALABRAS = 3
MINIMO_GRUPO = 3
LANZADORES = {"Agent", "Task"}

VACIAS = set("""
a al algo algun alguna algunas alguno algunos ante antes bajo cada como con contra cual cuales cuando de del
desde donde durante e el ella ellas ellos en entre era es esa esas ese eso esos esta estas este esto estos
hacia hasta la las le les lo los mas me mi mis muy ni no nos o otra otras otro otros para pero por porque que
quien se segun ser si sin sobre su sus tal tambien te tu tus un una unas uno unos y ya
the a an and or of to in on for with from by at as is are be this that these those it its into about over
""".split())


def normalizar(texto, propios=frozenset()):
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    palabras = re.findall(r"[a-z][a-z0-9-]*", texto)
    salida = set()
    for p in palabras:
        for parte in p.split("-"):
            if len(parte) > 2 and parte not in VACIAS and parte not in propios and not parte.isdigit():
                salida.add(parte)
    return salida


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def nombres_de_proveedores(rutas):
    propios = set()
    for r in rutas:
        m = re.search(r"/registry/providers/([^/]+)\.md$", r)
        if m:
            propios |= normalizar(m.group(1).replace("-", " "))
    return frozenset(propios)


class Candidatos:
    def __init__(self, carpeta_eventos, filtro=None):
        self.carpeta = Path(carpeta_eventos)
        self.filtro = filtro or (lambda e: True)
        self._cache = {}  # archivo -> (mtime_ns, lanzamientos)

    def _lanzamientos(self, ruta):
        try:
            mtime = ruta.stat().st_mtime_ns
        except OSError:
            return []
        previo = self._cache.get(ruta)
        if previo and previo[0] == mtime:
            return previo[1]
        salida = []
        with open(ruta, encoding="utf-8", errors="replace") as f:
            for linea in f:
                if '"PreToolUse"' not in linea:
                    continue
                try:
                    e = json.loads(linea)
                except ValueError:
                    continue
                if e.get("evento") != "PreToolUse" or e.get("tool_name") not in LANZADORES or not self.filtro(e):
                    continue
                r = e.get("resumen") or {}
                if r.get("subagent_type") and r.get("description"):
                    salida.append({"ts": e.get("ts"), "tipo": r["subagent_type"], "description": r["description"]})
        self._cache[ruta] = (mtime, salida)
        return salida

    def calcular(self, hoy, es_general, rutas_conocidas=()):
        """Grupos de lanzamientos de agentes generales con descripciones parecidas."""
        propios = nombres_de_proveedores(rutas_conocidas)
        lanzamientos = []
        for d in range(DIAS):
            ruta = self.carpeta / f"{(hoy - dt.timedelta(days=d)).isoformat()}.jsonl"
            if ruta.exists():
                lanzamientos += [l for l in self._lanzamientos(ruta) if es_general(l["tipo"])]
        vigentes = set(self._cache) & {self.carpeta / f"{(hoy - dt.timedelta(days=d)).isoformat()}.jsonl" for d in range(DIAS)}
        self._cache = {k: v for k, v in self._cache.items() if k in vigentes}

        utiles = [(l, normalizar(l["description"], propios)) for l in lanzamientos]
        utiles = [(l, p) for l, p in utiles if len(p) >= MINIMO_PALABRAS]
        # Grupos: componentes conexas del grafo "se parecen"
        padre = list(range(len(utiles)))

        def raiz(i):
            while padre[i] != i:
                padre[i] = padre[padre[i]]
                i = padre[i]
            return i

        for i in range(len(utiles)):
            for j in range(i + 1, len(utiles)):
                if jaccard(utiles[i][1], utiles[j][1]) >= UMBRAL:
                    padre[raiz(i)] = raiz(j)
        grupos = {}
        for i in range(len(utiles)):
            grupos.setdefault(raiz(i), []).append(utiles[i])
        candidatos = []
        for miembros in grupos.values():
            if len(miembros) < MINIMO_GRUPO:
                continue
            comunes = set.intersection(*(p for _, p in miembros))
            frecuentes = {}
            for _, p in miembros:
                for w in p:
                    frecuentes[w] = frecuentes.get(w, 0) + 1
            clave = sorted(frecuentes, key=lambda w: (-frecuentes[w], w))[:6]
            candidatos.append({
                "lanzamientos": len(miembros),
                "tipos": sorted({l["tipo"] for l, _ in miembros}),
                "palabras": sorted(comunes) or clave,
                "descripciones": sorted({l["description"] for l, _ in miembros})[:10],
                "ultimo": max(l["ts"] or "" for l, _ in miembros),
            })
        candidatos.sort(key=lambda c: (-c["lanzamientos"], c["ultimo"]), reverse=False)
        return candidatos
