"""Servidor HTTP local de la oficina. Solo 127.0.0.1. Solo lectura sobre el área y el equipo.

Endpoints:
  /               la web compilada (web/dist) o, si todavía no existe, la vista básica (web/basico)
  /api/estado     foto completa
  /api/stream     SSE: evento 'estado' con la foto cada vez que cambia
  /api/buscar?q=  búsqueda de texto en los .md de la lista blanca
  /api/archivo?ruta=  texto de un .md de la lista blanca
  /api/equipo     pendientes, fricciones, decisiones, .remember, status y catálogo, parseados
  /api/layout     GET: layout.json del perfil. POST: lo guarda el editor del piso (única escritura, y es en
                  la carpeta del perfil, nunca en el área). Exige JSON, Origin propio y un layout válido
  /api/sprites    sprites.json del perfil
  /api/perfil     nombre del equipo, roles y textos del piso (sin rutas del área)
"""
import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .area import FueraDeLaListaBlanca

WEB = Path(__file__).resolve().parent.parent / "web"
LATIDO_S = 15
MAX_LAYOUT_BYTES = 2_000_000


class LayoutInvalido(ValueError):
    pass


def validar_layout(datos):
    """Chequeos mínimos para no guardar algo que rompa el piso. Devuelve el layout tal cual."""
    if not isinstance(datos, dict) or datos.get("version") != 1:
        raise LayoutInvalido("se espera un layout versión 1")
    cols, filas = datos.get("cols"), datos.get("rows")
    if not (isinstance(cols, int) and isinstance(filas, int) and 1 <= cols <= 200 and 1 <= filas <= 200):
        raise LayoutInvalido("cols y rows deben ser enteros entre 1 y 200")
    tiles = datos.get("tiles")
    if not isinstance(tiles, list) or len(tiles) != cols * filas or not all(isinstance(t, int) for t in tiles):
        raise LayoutInvalido("tiles debe tener cols × rows enteros")
    for clave in ("tileColors", "areaTiles", "carpetTiles"):
        if clave in datos and datos[clave] is not None and (not isinstance(datos[clave], list) or len(datos[clave]) != cols * filas):
            raise LayoutInvalido(f"{clave} debe tener cols × rows elementos")
    muebles = datos.get("furniture")
    if not isinstance(muebles, list) or not all(
            isinstance(m, dict) and isinstance(m.get("uid"), str) and isinstance(m.get("type"), str)
            and isinstance(m.get("col"), int) and isinstance(m.get("row"), int) for m in muebles):
        raise LayoutInvalido("furniture debe ser una lista de {uid, type, col, row}")
    return datos


def carpeta_web():
    dist = WEB / "dist"
    return dist if (dist / "index.html").exists() else WEB / "basico"


def crear_servidor(oficina, puerto):
    class Manejador(BaseHTTPRequestHandler):
        server_version = "oficina-idi"

        def log_message(self, *args):
            pass

        def do_GET(self):
            real = self.server.server_address[1]
            anfitriones = {f"127.0.0.1:{real}", f"localhost:{real}"}
            if self.headers.get("Host") not in anfitriones:
                return self.responder(421, {"error": "host no permitido"})
            url = urlsplit(self.path)
            q = parse_qs(url.query)
            try:
                if url.path == "/api/estado":
                    return self.responder(200, oficina.foto)
                if url.path == "/api/stream":
                    return self.stream()
                if url.path == "/api/buscar":
                    return self.responder(200, {"resultados": oficina.area.buscar(q.get("q", [""])[0])})
                if url.path == "/api/archivo":
                    ruta = q.get("ruta", [""])[0]
                    return self.responder(200, {"ruta": ruta, "texto": oficina.area.leer(ruta)})
                if url.path == "/api/equipo":
                    return self.responder(200, oficina.equipo_archivos())
                if url.path == "/api/layout":
                    return self.responder(200, oficina.config_json("layout.json"))
                if url.path == "/api/sprites":
                    return self.responder(200, oficina.perfil.archivo("sprites.json", {}))
                if url.path == "/api/perfil":
                    return self.responder(200, oficina.perfil.para_la_web())
                return self.estatico(url.path)
            except FueraDeLaListaBlanca as error:
                return self.responder(403, {"error": str(error)})
            except FileNotFoundError:
                return self.responder(404, {"error": "no existe"})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return None

        def do_POST(self):
            real = self.server.server_address[1]
            anfitriones = {f"127.0.0.1:{real}", f"localhost:{real}"}
            if self.headers.get("Host") not in anfitriones:
                return self.responder(421, {"error": "host no permitido"})
            # Solo la propia web: Origin igual al servidor y cuerpo JSON (otro sitio no puede mandar
            # application/json sin un preflight, y el preflight no tiene CORS)
            if self.headers.get("Origin") not in {f"http://{a}" for a in anfitriones}:
                return self.responder(403, {"error": "origen no permitido"})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self.responder(415, {"error": "se espera application/json"})
            if urlsplit(self.path).path != "/api/layout":
                return self.responder(404, {"error": "no existe"})
            try:
                largo = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                largo = -1
            if not 0 < largo <= MAX_LAYOUT_BYTES:
                return self.responder(413, {"error": "tamaño inválido"})
            try:
                datos = validar_layout(json.loads(self.rfile.read(largo).decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self.responder(400, {"error": "JSON inválido"})
            except LayoutInvalido as error:
                return self.responder(400, {"error": str(error)})
            oficina.guardar_layout(datos)
            return self.responder(200, {"guardado": True})

        def responder(self, codigo, cuerpo):
            datos = json.dumps(cuerpo, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(datos)

        def estatico(self, ruta):
            base = carpeta_web().resolve()
            destino = (base / (ruta.lstrip("/") or "index.html")).resolve()
            if base not in destino.parents and destino != base:
                return self.responder(403, {"error": "fuera de la web"})
            if destino.is_dir():
                destino = destino / "index.html"
            if not destino.is_file():
                return self.responder(404, {"error": "no existe"})
            datos = destino.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(destino.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(datos)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(datos)

        def stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            enviada = -1
            ultimo_latido = time.monotonic()
            while True:
                with oficina.cambio:
                    oficina.cambio.wait_for(lambda: oficina.version != enviada, timeout=LATIDO_S)
                    version, foto = oficina.version, oficina.foto
                if version != enviada and foto is not None:
                    datos = json.dumps(foto, ensure_ascii=False, default=str)
                    self.wfile.write(f"event: estado\nid: {version}\ndata: {datos}\n\n".encode("utf-8"))
                    enviada = version
                elif time.monotonic() - ultimo_latido >= LATIDO_S:
                    self.wfile.write(b": latido\n\n")
                    ultimo_latido = time.monotonic()
                self.wfile.flush()

    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    servidor.daemon_threads = True
    return servidor


def correr(oficina, puerto, intervalo=0.5):
    oficina.actualizar(forzar=True)

    def ciclo():
        while True:
            try:
                oficina.actualizar()
            except Exception as error:  # el servidor no se cae por un archivo raro
                print(f"[oficina] error al actualizar: {type(error).__name__}: {error}")
            time.sleep(intervalo)

    threading.Thread(target=ciclo, daemon=True).start()
    servidor = crear_servidor(oficina, puerto)
    print(f"Oficina en http://127.0.0.1:{puerto}/")
    servidor.serve_forever()
