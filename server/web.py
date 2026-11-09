"""The office's local HTTP server. Only 127.0.0.1. Read-only over the area and the team.

Endpoints:
  /                the compiled web (web/dist) or, if it does not exist yet, the basic view (web/basic)
  /api/state       full snapshot
  /api/stream      SSE: 'state' event with the snapshot every time it changes
  /api/search?q=   text search over the allowlisted .md files
  /api/file?path=  text of an allowlisted .md file
  /api/team        tasks, frictions, decisions, .remember, status and catalog, parsed
  /api/layout      GET: the profile's layout.json. POST: saved by the floor editor (the only write, and it goes
                   to the profile folder, never to the area). Requires JSON, our own Origin and a valid layout
  /api/sprites     the profile's sprites.json
  /api/profile     team name, roles and floor texts (no area paths)
  /api/projects    registered projects, with their last activity

All of them (except /api/projects) accept `?project=<id>`; without it, the project with the latest activity.
Error messages are shown in the web, so they are Spanish.
"""
import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .area import OutsideAllowlist

WEB = Path(__file__).resolve().parent.parent / "web"
HEARTBEAT_S = 15
MAX_LAYOUT_BYTES = 2_000_000


class InvalidLayout(ValueError):
    pass


def validate_layout(layout):
    """Minimal checks so nothing that breaks the floor gets saved. Returns the layout unchanged."""
    if not isinstance(layout, dict) or layout.get("version") != 1:
        raise InvalidLayout("se espera un layout versión 1")
    cols, rows = layout.get("cols"), layout.get("rows")
    if not (isinstance(cols, int) and isinstance(rows, int) and 1 <= cols <= 200 and 1 <= rows <= 200):
        raise InvalidLayout("cols y rows deben ser enteros entre 1 y 200")
    tiles = layout.get("tiles")
    if not isinstance(tiles, list) or len(tiles) != cols * rows or not all(isinstance(t, int) for t in tiles):
        raise InvalidLayout("tiles debe tener cols × rows enteros")
    for key in ("tileColors", "areaTiles", "carpetTiles"):
        if key in layout and layout[key] is not None and (not isinstance(layout[key], list) or len(layout[key]) != cols * rows):
            raise InvalidLayout(f"{key} debe tener cols × rows elementos")
    furniture = layout.get("furniture")
    if not isinstance(furniture, list) or not all(
            isinstance(f, dict) and isinstance(f.get("uid"), str) and isinstance(f.get("type"), str)
            and isinstance(f.get("col"), int) and isinstance(f.get("row"), int) for f in furniture):
        raise InvalidLayout("furniture debe ser una lista de {uid, type, col, row}")
    return layout


def web_folder():
    dist = WEB / "dist"
    return dist if (dist / "index.html").exists() else WEB / "basic"


def create_server(offices, port):
    from .offices import Offices
    if not isinstance(offices, Offices):
        offices = Offices.of_one(offices)

    class Handler(BaseHTTPRequestHandler):
        server_version = "agents-office"

        def log_message(self, *args):
            pass

        def do_GET(self):
            real = self.server.server_address[1]
            hosts = {f"127.0.0.1:{real}", f"localhost:{real}"}
            if self.headers.get("Host") not in hosts:
                return self.respond(421, {"error": "host no permitido"})
            url = urlsplit(self.path)
            q = parse_qs(url.query)
            office = offices.pick(q.get("project", [None])[0])
            try:
                if url.path == "/api/projects":
                    return self.respond(200, {"projects": offices.listing()})
                if url.path == "/api/state":
                    return self.respond(200, office.snapshot)
                if url.path == "/api/stream":
                    return self.stream(office)
                if url.path == "/api/search":
                    return self.respond(200, {"results": office.area.search(q.get("q", [""])[0])})
                if url.path == "/api/file":
                    path = q.get("path", [""])[0]
                    return self.respond(200, {"path": path, "text": office.area.read(path)})
                if url.path == "/api/team":
                    return self.respond(200, office.team_files())
                if url.path == "/api/layout":
                    return self.respond(200, office.config_json("layout.json"))
                if url.path == "/api/sprites":
                    return self.respond(200, office.profile.file("sprites.json", {}))
                if url.path == "/api/profile":
                    return self.respond(200, office.profile.for_web())
                return self.static(url.path)
            except OutsideAllowlist as error:
                return self.respond(403, {"error": str(error)})
            except FileNotFoundError:
                return self.respond(404, {"error": "no existe"})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return None

        def do_POST(self):
            real = self.server.server_address[1]
            hosts = {f"127.0.0.1:{real}", f"localhost:{real}"}
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            # The body is always read (with a cap) before answering: if a request is rejected without reading
            # it, Windows may reset the connection and the client never gets the error code
            body = self.rfile.read(length) if 0 < length <= MAX_LAYOUT_BYTES else b""
            if self.headers.get("Host") not in hosts:
                return self.respond(421, {"error": "host no permitido"})
            # Only our own web: Origin equal to the server and a JSON body (another site cannot send
            # application/json without a preflight, and the preflight gets no CORS)
            if self.headers.get("Origin") not in {f"http://{h}" for h in hosts}:
                return self.respond(403, {"error": "origen no permitido"})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self.respond(415, {"error": "se espera application/json"})
            if urlsplit(self.path).path != "/api/layout":
                return self.respond(404, {"error": "no existe"})
            if not 0 < length <= MAX_LAYOUT_BYTES:
                self.close_connection = True
                return self.respond(413, {"error": "tamaño inválido"})
            office = offices.pick(parse_qs(urlsplit(self.path).query).get("project", [None])[0])
            try:
                layout = validate_layout(json.loads(body.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return self.respond(400, {"error": "JSON inválido"})
            except InvalidLayout as error:
                return self.respond(400, {"error": str(error)})
            office.save_layout(layout)
            return self.respond(200, {"saved": True})

        def respond(self, code, body):
            data = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def static(self, path):
            base = web_folder().resolve()
            target = (base / (path.lstrip("/") or "index.html")).resolve()
            if base not in target.parents and target != base:
                return self.respond(403, {"error": "fuera de la web"})
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                return self.respond(404, {"error": "no existe"})
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(data)

        def stream(self, office):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            sent = -1
            last_heartbeat = time.monotonic()
            while True:
                with office.changed:
                    office.changed.wait_for(lambda: office.version != sent, timeout=HEARTBEAT_S)
                    version, snapshot = office.version, office.snapshot
                if version != sent and snapshot is not None:
                    data = json.dumps(snapshot, ensure_ascii=False, default=str)
                    self.wfile.write(f"event: state\nid: {version}\ndata: {data}\n\n".encode("utf-8"))
                    sent = version
                elif time.monotonic() - last_heartbeat >= HEARTBEAT_S:
                    self.wfile.write(b": heartbeat\n\n")
                    last_heartbeat = time.monotonic()
                self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def run(offices, port, interval=0.5):
    offices.update(force=True)

    def cycle():
        while True:
            try:
                offices.update()
            except Exception as error:  # the server does not die because of an odd file
                print(f"[office] update error: {type(error).__name__}: {error}")
            time.sleep(interval)

    threading.Thread(target=cycle, daemon=True).start()
    server = create_server(offices, port)
    print(f"Office at http://127.0.0.1:{port}/")
    server.serve_forever()
