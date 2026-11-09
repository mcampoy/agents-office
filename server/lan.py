"""Access from the local network (a phone on the same Wi-Fi).

Off by default: the server only listens on 127.0.0.1. `scripts/lan.py --enable` writes <data>/lan.json with a
random key; from then on the server listens on every interface and asks network clients for that key:

- The first time, the phone opens http://<computer-ip>:<port>/?key=<key>. The server stores the key in an
  HttpOnly, SameSite=Strict cookie and redirects to the same URL without the key.
- Without a valid cookie or key, nothing is shown (401). After MAX_FAILURES wrong keys from one address in
  BLOCK_S seconds, that address gets 429 for the rest of the window.
- From the network everything is read-only: POST is rejected (the floor editor is used from the computer).
- The computer itself (loopback) works as always, without a key.

The traffic is plain HTTP: use it only on a trusted Wi-Fi (home or office), never on a public one.
"""
import json
import secrets
import socket
import threading
import time
from pathlib import Path

FILE = "lan.json"
COOKIE = "ao_key"
COOKIE_MAX_AGE_S = 90 * 86400
MAX_FAILURES = 10
BLOCK_S = 600
# No 0/o, 1/l/i: easy to type on a phone
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
KEY_LENGTH = 14


def _path(data):
    return Path(data) / FILE


def _read(data):
    try:
        return json.loads(_path(data).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(data, settings):
    Path(data).mkdir(parents=True, exist_ok=True)
    _path(data).write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return settings


def generate_key():
    return "".join(secrets.choice(ALPHABET) for _ in range(KEY_LENGTH))


def load(data):
    """The settings if network access is enabled, else None."""
    settings = _read(data)
    return settings if settings.get("enabled") and settings.get("key") else None


def enable(data):
    settings = _read(data)
    return _write(data, {"enabled": True, "key": settings.get("key") or generate_key()})


def disable(data):
    settings = _read(data)
    return _write(data, {**settings, "enabled": False})


def new_key(data):
    """A new key: every phone has to enter it again."""
    settings = _read(data)
    return _write(data, {"enabled": bool(settings.get("enabled")), "key": generate_key()})


def primary_ip():
    """The computer's address on the local network. Connecting a UDP socket sends no packet."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def local_addresses():
    """IPv4 addresses of this computer (for the Host check), the primary one first."""
    out = []
    first = primary_ip()
    if first:
        out.append(first)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except OSError:
        pass
    return out


def phone_url(ip, port, key):
    return f"http://{ip}:{port}/?key={key}"


def startup_line(ip, port):
    """What the server prints at startup. stdout ends up in server.log, so it carries no key."""
    return f"Phone (same Wi-Fi): http://{ip}:{port}/ (key: py -3 scripts/lan.py --show)"


class Addresses:
    """The computer's LAN addresses, looked up again every `ttl_s` seconds: the IP can change while the
    office runs (DHCP, another Wi-Fi). An unknown Host forces a lookup, at most once every `retry_s`."""

    def __init__(self, lookup=local_addresses, clock=time.monotonic, ttl_s=30, retry_s=5):
        self.lookup = lookup
        self.clock = clock
        self.ttl_s = ttl_s
        self.retry_s = retry_s
        self.lock = threading.Lock()
        self.found = []
        self.at = None

    def _refresh(self, now):
        self.found = list(self.lookup())
        self.at = now

    def __call__(self):
        with self.lock:
            now = self.clock()
            if self.at is None or now - self.at >= self.ttl_s:
                self._refresh(now)
            return list(self.found)

    def knows(self, ip):
        with self.lock:
            now = self.clock()
            if self.at is None or now - self.at >= self.ttl_s:
                self._refresh(now)
            if ip in self.found:
                return True
            if now - self.at >= self.retry_s:
                self._refresh(now)
            return ip in self.found


class Guard:
    """Wrong-key counter per client address."""

    def __init__(self, max_failures=MAX_FAILURES, window_s=BLOCK_S):
        self.max_failures = max_failures
        self.window_s = window_s
        self.failures = {}
        self.lock = threading.Lock()

    def _recent(self, ip, now):
        return [t for t in self.failures.get(ip, []) if now - t < self.window_s]

    def blocked(self, ip):
        with self.lock:
            return len(self._recent(ip, time.monotonic())) >= self.max_failures

    def fail(self, ip):
        with self.lock:
            now = time.monotonic()
            self.failures[ip] = self._recent(ip, now) + [now]


def valid(given, key):
    return isinstance(given, str) and secrets.compare_digest(given.encode(), key.encode())


# Shown to the user, so it is Spanish
KEY_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Oficina · clave</title>
<style>body{font:16px/1.4 system-ui,sans-serif;background:#181828;color:#ddd;margin:0;display:grid;place-items:center;min-height:100vh}
form{display:grid;gap:12px;padding:24px;max-width:320px}input,button{font:inherit;padding:10px;border-radius:6px;border:1px solid #556}
input{background:#22223a;color:#fff}button{background:#4aa3ff;color:#111;border:0}p{color:#aab;margin:0}</style></head>
<body><form method="get" action=""><h1 style="margin:0;font-size:20px">Oficina</h1>
<p>{message}</p><input name="key" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="clave" required autofocus>
<button type="submit">Entrar</button>
<p style="font-size:13px">La clave está en la compu: botón «Celular» de la oficina o <code>py -3 scripts/lan.py --show</code>.</p>
</form></body></html>"""
