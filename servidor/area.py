"""Lectura de la raíz del área, solo lectura y con lista blanca.

Nada de este módulo escribe en la unidad. Las rutas que recibe son relativas a la raíz, con '/'.

Política de lectura (la unidad es Google Drive en modo streaming): leer un archivo que está solo en la
nube obliga a bajarlo, y Drive no deja distinguir esos archivos (el volumen se presenta como FAT32 sin
atributos de "solo en la nube"). Por eso todo archivo se trata como si pudiera estar solo en la nube y se
lee únicamente:
  - con `refrescar(ruta)`, que el servidor llama cuando un evento nombra esa ruta;
  - con `barrido()`, cada 5 minutos;
  - con `leer(ruta)`, cuando el responsable abre ese archivo desde la web.
Las dos primeras leen solo si cambió la fecha de modificación. Todo lo demás (encabezados, rondas,
búsqueda, pendientes, .remember, status) trabaja sobre la caché, sin tocar la unidad.
Listar carpetas y leer fechas de modificación no baja contenido.
"""
import os
import re
from pathlib import Path

from .util import tabla_de_encabezado

EXTENSIONES = (".md",)
EXCLUIDAS = {".git", "__pycache__", "node_modules", "pages", "logs", "tmp", ".playwright-mcp", ".venv", "venv",
             "dist", "build", ".next", ".cache"}
# Con "." en las raíces, la lista blanca es todo el proyecto (salvo EXCLUIDAS y carpetas ocultas),
# hasta esta profundidad: los proyectos de código pueden ser grandes.
PROFUNDIDAD_TODO = 4
LIMITE_BYTES = 2_000_000
LINEAS_DE_ENCABEZADO = 15


class FueraDeLaListaBlanca(PermissionError):
    pass


class Area:
    def __init__(self, raiz, raices=(), extensiones=EXTENSIONES, remember=None, status=None):
        """raices: carpetas de primer nivel de la lista blanca (del perfil). remember y status: carpetas
        relativas con las notas de .remember y los informes de corridas, si el equipo los tiene."""
        self.raiz = Path(raiz)
        self.raices = tuple(raices)
        self.carpeta_remember = remember.strip("/") + "/" if remember else None
        self.carpeta_status = status.strip("/") + "/" if status else None
        self.extensiones = tuple(e.lower() for e in extensiones)
        self._cache = {}   # ruta relativa -> (mtime_ns, texto)
        self.lecturas = 0  # cuántos archivos se leyeron de la unidad (para pruebas y diagnóstico)

    # --- Lista blanca ---------------------------------------------------------

    def ruta_segura(self, relativa):
        if not isinstance(relativa, str) or not relativa.strip():
            raise FueraDeLaListaBlanca("ruta vacía")
        rel = relativa.replace("\\", "/").strip("/")
        partes = rel.split("/")
        if any(p in ("", ".", "..") for p in partes) or ":" in rel:
            raise FueraDeLaListaBlanca("ruta no permitida")
        todo = "." in self.raices
        if not todo and partes[0] not in self.raices:
            raise FueraDeLaListaBlanca("fuera de las raíces permitidas")
        if todo and any(p in EXCLUIDAS for p in partes[:-1]):
            raise FueraDeLaListaBlanca("carpeta excluida")
        if not rel.lower().endswith(self.extensiones):
            raise FueraDeLaListaBlanca("extensión no permitida")
        absoluta = (self.raiz / rel).resolve()
        permitida = self.raiz.resolve() if todo else (self.raiz / partes[0]).resolve()
        if permitida not in absoluta.parents:
            raise FueraDeLaListaBlanca("la ruta sale de su raíz")
        return absoluta

    # --- Las únicas lecturas de la unidad ------------------------------------------

    def refrescar(self, relativa):
        """Lee el archivo si cambió desde la última lectura. Devuelve True si lo leyó."""
        try:
            ruta = self.ruta_segura(relativa)
            st = ruta.stat()
        except FueraDeLaListaBlanca:
            return False
        except OSError:
            self._cache.pop(relativa, None)
            return False
        guardado = self._cache.get(relativa)
        if guardado and guardado[0] == st.st_mtime_ns:
            return False
        if st.st_size > LIMITE_BYTES:
            return False
        try:
            texto = ruta.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        self.lecturas += 1
        self._cache[relativa] = (st.st_mtime_ns, texto)
        return True

    def barrido(self):
        """Barrido completo: lista la lista blanca y refresca lo que cambió. Olvida lo borrado."""
        presentes = set(self.archivos())
        leidos = sum(1 for rel in sorted(presentes) if self.refrescar(rel))
        for rel in list(self._cache):
            if rel not in presentes:
                del self._cache[rel]
        return leidos

    def leer(self, relativa):
        """Para la web: el responsable abre un archivo. Refresca y devuelve el texto."""
        self.ruta_segura(relativa)
        self.refrescar(relativa)
        if relativa not in self._cache:
            raise FileNotFoundError(relativa)
        return self._cache[relativa][1]

    # --- Caché ----------------------------------------------------------------------

    def texto(self, relativa):
        guardado = self._cache.get(relativa)
        return guardado[1] if guardado else None

    def en_cache(self):
        return sorted(self._cache)

    def existe(self, relativa):
        return relativa in self._cache

    def _lineas(self, relativa, n=LINEAS_DE_ENCABEZADO):
        texto = self.texto(relativa)
        return texto.splitlines()[:n] if texto is not None else None

    # --- Documentos: solo el encabezado ---------------------------------------------

    def encabezado(self, relativa):
        """Título y tabla de encabezado. No usa nada más del contenido."""
        lineas = self._lineas(relativa)
        if lineas is None:
            return None
        titulo = next((l[2:].strip() for l in lineas if l.startswith("# ")), None)
        tabla = tabla_de_encabezado(lineas)
        estado = tabla.get("Estado")
        return {
            "titulo": titulo,
            "estado": estado.lower() if estado else None,
            "version": tabla.get("Versión"),
            "ultima_revision": tabla.get("Última revisión") or tabla.get("Fecha"),
            "columnas": tabla,
        }

    def rondas(self, relativa):
        """Rondas de un informe de verificación, de sus títulos o, si no tiene, de su encabezado.

        Devuelve {"ciclo", "ronda", "total_en_encabezado", "fuente": titulos|encabezado|supuesta}.
        Usa solo las líneas de título y la tabla de encabezado.
        """
        texto = self.texto(relativa)
        if texto is None:
            return None
        ciclo, ronda = 1, 0
        for linea in texto.splitlines():
            if not linea.startswith("#"):
                continue
            m = re.match(r"^#{2,3}\s+(?:Ciclo\s+(\d+),\s*)?[Rr]onda\s+(\d+)\b", linea)
            if m:
                n = int(m.group(2))
                if m.group(1):
                    ciclo = int(m.group(1))
                elif ronda and n <= ronda:
                    ciclo += 1
                ronda = n
        encabezado = tabla_de_encabezado(texto.splitlines()[:LINEAS_DE_ENCABEZADO])
        numeros = re.findall(r"\d+", encabezado.get("Rondas", ""))
        total = int(numeros[-1]) if numeros else None
        if ronda:
            fuente = "titulos"
        elif total:
            ronda, fuente = total, "encabezado"
        else:
            ronda, fuente = 1, "supuesta"
        return {"ciclo": ciclo, "ronda": ronda, "total_en_encabezado": total, "fuente": fuente}

    def documentos_nombrados(self, relativa):
        """Rutas entre backticks en la columna de documento verificado del encabezado."""
        cab = self.encabezado(relativa) or {}
        rutas = []
        for columna, valor in cab.get("columnas", {}).items():
            if "verificad" in columna.lower():
                rutas += re.findall(r"`([^`]+\.md)`", valor)
        return rutas

    # --- Listado y búsqueda ---------------------------------------------------------------

    def archivos(self):
        """Lista la lista blanca (no lee contenido)."""
        for raiz in self.raices:
            base = self.raiz / raiz
            if not base.is_dir():
                continue
            for carpeta, subcarpetas, nombres in os.walk(base):
                if raiz == ".":
                    nivel = len(Path(carpeta).relative_to(base).parts)
                    subcarpetas[:] = [] if nivel >= PROFUNDIDAD_TODO else [
                        s for s in subcarpetas if s not in EXCLUIDAS and not s.startswith(".") or s == ".claude"]
                else:
                    subcarpetas[:] = [s for s in subcarpetas if s not in EXCLUIDAS]
                for nombre in nombres:
                    if nombre.lower().endswith(self.extensiones):
                        yield (Path(carpeta) / nombre).relative_to(self.raiz).as_posix()

    def buscar(self, consulta, limite=100):
        """Sobre la caché: lo que el barrido o los eventos ya leyeron."""
        consulta = (consulta or "").strip()
        if len(consulta) < 2:
            return []
        aguja = consulta.lower()
        resultados = []
        for rel in self.en_cache():
            for n, linea in enumerate(self.texto(rel).splitlines(), 1):
                if aguja in linea.lower():
                    resultados.append({"ruta": rel, "linea": n, "texto": linea.strip()[:200]})
                    if len(resultados) >= limite:
                        return resultados
        return resultados

    # --- Archivos del equipo (desde la caché) ----------------------------------------------

    def bloques(self, relativa):
        """Entradas '## fecha · título' con sus campos en negrita. Si no se puede, el texto crudo."""
        texto = self.texto(relativa)
        if texto is None:
            return {"ruta": relativa, "entradas": [], "sin_leer": True}
        entradas, actual = [], None
        # Los comentarios HTML (por ejemplo, la guía de formato de las plantillas) no son entradas
        for linea in re.sub(r"<!--.*?-->", "", texto, flags=re.S).splitlines():
            m = re.match(r"^##\s+(.+)$", linea)
            if m:
                titulo = m.group(1).strip()
                f = re.match(r"^(\d{4}-\d{2}-\d{2})\s*[·\-–]\s*(.+)$", titulo)
                actual = {"fecha": f.group(1) if f else None, "titulo": f.group(2) if f else titulo,
                          "campos": {}, "texto": []}
                entradas.append(actual)
                continue
            if actual is None:
                continue
            actual["texto"].append(linea)
            c = re.match(r"^\*\*([^*]+?):?\*\*:?\s*(.*)$", linea)
            if c:
                actual["campos"][c.group(1).strip().rstrip(":")] = c.group(2).strip()
            r = re.match(r"^(Repeticiones|Propuesta|Riesgo):\s*(.*)$", linea)
            if r:
                actual["campos"][r.group(1)] = r.group(2).strip()
        for e in entradas:
            e["texto"] = "\n".join(e["texto"]).strip()
            e["rutas"] = sorted(set(re.findall(r"`([^`\s]+\.md)`", e["texto"])))
        resultado = {"ruta": relativa, "encabezado": self.encabezado(relativa), "entradas": entradas}
        if not entradas:
            resultado["crudo"] = texto
        return resultado

    def remember(self):
        prefijo = self.carpeta_remember
        archivos = []
        if not prefijo:
            return archivos
        for rel in self.en_cache():
            if not rel.startswith(prefijo) or "/" in rel[len(prefijo):]:
                continue
            texto = self.texto(rel)
            entradas = [{"titulo": t.strip(), "texto": c.strip()}
                        for t, c in re.findall(r"^##\s+(.+)\n((?:(?!^##\s).*\n?)*)", texto, flags=re.M)]
            archivos.append({"ruta": rel, "entradas": entradas, **({} if entradas else {"crudo": texto})})
        return archivos

    def status(self):
        prefijo = self.carpeta_status
        archivos = []
        if not prefijo:
            return archivos
        for rel in sorted(self.en_cache(), reverse=True):
            if not rel.startswith(prefijo) or "/" in rel[len(prefijo):]:
                continue
            nombre = rel[len(prefijo):]
            m = re.match(r"^(\d{4}-\d{2}-\d{2})-(corrida|cambios)(.*)\.md$", nombre)
            lineas = self._lineas(rel, 12) or []
            archivos.append({
                "ruta": rel,
                "fecha": m.group(1) if m else None,
                "tipo": m.group(2) if m else "otro",
                "variante": m.group(3).strip("-") if m and m.group(3) else None,
                "titulo": (lineas[0].lstrip("# ").strip() if lineas else None),
                "tabla": tabla_de_encabezado(lineas),
            })
        return archivos
