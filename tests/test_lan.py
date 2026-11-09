"""Access from the local network (phone on the same Wi-Fi): key, cookie, read-only and attempt limit.

Usage: py -3 -m unittest discover -s tests -v
"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from server import lan  # noqa: E402
from server.office import Office  # noqa: E402
from server.web import create_server  # noqa: E402

PROFILE = REPO / "profiles" / "example"
LAN_IP = "192.168.0.10"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


class Settings(unittest.TestCase):
    def test_enable_disable_and_new_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            self.assertIsNone(lan.load(data))
            first = lan.enable(data)
            self.assertTrue(first["enabled"])
            self.assertGreaterEqual(len(first["key"]), 12)
            self.assertEqual(lan.load(data)["key"], first["key"])
            # Enabling again keeps the key, so the phone does not have to enter it again
            self.assertEqual(lan.enable(data)["key"], first["key"])
            lan.disable(data)
            self.assertIsNone(lan.load(data))
            self.assertNotEqual(lan.new_key(data)["key"], first["key"])

    def test_phone_url(self):
        self.assertEqual(lan.phone_url("192.168.1.5", 8765, "abc"), "http://192.168.1.5:8765/?key=abc")


class Network(unittest.TestCase):
    """The test client is 127.0.0.1, so `loopback=set()` makes the server treat it as a phone on the Wi-Fi."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        data = Path(self.tmp.name) / "data"
        data.mkdir()
        area = Path(self.tmp.name) / "area"
        (area / "equipo").mkdir(parents=True)
        self.office = Office(data=data, profile=PROFILE, area_root=str(area), team_dir=str(area / "equipo"))
        self.office.update(force=True)
        self.key = "k3y-de-prueba-123"
        self.server = create_server(self.office, 0, lan={"key": self.key, "addresses": [LAN_IP]},
                                    host="127.0.0.1", loopback=set())
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, cookie=None, host=None, method="GET", body=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, method=method)
        r.add_header("Host", host or f"{LAN_IP}:{self.port}")
        if cookie:
            r.add_header("Cookie", cookie)
        if body is not None:
            r.add_header("Content-Type", "application/json")
            r.add_header("Origin", f"http://{LAN_IP}:{self.port}")
        try:
            with OPENER.open(r, timeout=5) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers), e.read()

    def cookie(self):
        return f"{lan.COOKIE}={self.key}"

    def test_without_key_nothing_is_shown(self):
        code, headers, body = self.request("/api/state")
        self.assertEqual(code, 401)
        self.assertNotIn(b"instances", body)
        code, headers, body = self.request("/")
        self.assertEqual(code, 401)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn("clave".encode(), body)
        self.assertEqual(self.request("/api/state", cookie=f"{lan.COOKIE}=otra")[0], 401)

    def test_key_in_the_url_sets_the_cookie_and_is_removed(self):
        code, headers, _ = self.request(f"/?p=equipo&key={self.key}")
        self.assertEqual(code, 302)
        self.assertEqual(headers["Location"], "/?p=equipo")
        cookie = headers["Set-Cookie"]
        self.assertIn(f"{lan.COOKIE}={self.key}", cookie)
        for flag in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, cookie)
        code, _, body = self.request("/api/state", cookie=self.cookie())
        self.assertEqual(code, 200)
        self.assertIn("instances", json.loads(body))

    def test_hosts(self):
        self.assertEqual(self.request("/api/state", cookie=self.cookie(), host=f"127.0.0.1:{self.port}")[0], 200)
        self.assertEqual(self.request("/api/state", cookie=self.cookie(), host=f"evil.example:{self.port}")[0], 421)

    def test_lan_endpoint_hidden_from_the_network(self):
        self.assertEqual(self.request("/api/lan", cookie=self.cookie())[0], 404)

    def test_read_only_from_the_network(self):
        layout = (PROFILE / "layout.json").read_bytes()
        code, _, body = self.request("/api/layout", cookie=self.cookie(), method="POST", body=layout)
        self.assertEqual(code, 403)

    def test_attempt_limit(self):
        for _ in range(lan.MAX_FAILURES):
            self.assertEqual(self.request("/?key=mala")[0], 401)
        # Blocked for a while, even with the right key
        self.assertEqual(self.request(f"/?key={self.key}")[0], 429)


class LocalComputer(Network):
    """With the network enabled, the computer itself (loopback) still needs no key and can save the layout."""

    def setUp(self):
        super().setUp()
        self.server.shutdown()
        self.server.server_close()
        self.server = create_server(self.office, 0, lan={"key": self.key, "addresses": [LAN_IP]}, host="127.0.0.1")
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def test_without_key_nothing_is_shown(self):
        self.assertEqual(self.request("/api/state", host=f"127.0.0.1:{self.port}")[0], 200)

    def test_key_in_the_url_sets_the_cookie_and_is_removed(self):
        self.skipTest("only for network clients")

    def test_read_only_from_the_network(self):
        self.skipTest("only for network clients")

    def test_attempt_limit(self):
        self.skipTest("only for network clients")

    def test_lan_endpoint_hidden_from_the_network(self):
        self.skipTest("only for network clients")

    def test_lan_endpoint_only_for_the_computer(self):
        code, _, body = self.request("/api/lan", host=f"127.0.0.1:{self.port}")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["url"], f"http://{LAN_IP}:{self.port}/?key={self.key}")


class Addresses(unittest.TestCase):
    """The computer's IP can change while the office runs (DHCP, another Wi-Fi): the server notices."""

    def test_cached_and_refreshed_on_a_miss(self):
        now = [0.0]
        found = [["192.168.0.10"]]
        calls = []

        def lookup():
            calls.append(1)
            return list(found[0])

        addresses = lan.Addresses(lookup=lookup, clock=lambda: now[0], ttl_s=30, retry_s=5)
        self.assertEqual(addresses(), ["192.168.0.10"])
        self.assertEqual(addresses(), ["192.168.0.10"])
        self.assertEqual(len(calls), 1)
        found[0] = ["192.168.0.77"]
        # An unknown Host refreshes, but not more than once every retry_s
        self.assertFalse(addresses.knows("192.168.0.77"))
        now[0] = 6
        self.assertTrue(addresses.knows("192.168.0.77"))
        self.assertEqual(addresses()[0], "192.168.0.77")
        now[0] = 7
        self.assertFalse(addresses.knows("10.0.0.1"))
        self.assertEqual(len(calls), 2)
        # And it refreshes on its own after ttl_s
        found[0] = ["192.168.0.88"]
        now[0] = 40
        self.assertEqual(addresses(), ["192.168.0.88"])


class NewAddress(Network):
    def setUp(self):
        self.current = [LAN_IP]
        super().setUp()
        self.server.shutdown()
        self.server.server_close()
        addresses = lan.Addresses(lookup=lambda: list(self.current), retry_s=0)
        self.server = create_server(self.office, 0, lan={"key": self.key, "addresses": addresses},
                                    host="127.0.0.1", loopback=set())
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def test_the_new_ip_is_accepted(self):
        self.current[:] = ["192.168.0.77"]
        code, _, _ = self.request(f"/api/state?key={self.key}", host=f"192.168.0.77:{self.port}")
        self.assertEqual(code, 302)

    def test_without_key_nothing_is_shown(self):
        self.skipTest("covered by Network")

    def test_key_in_the_url_sets_the_cookie_and_is_removed(self):
        self.skipTest("covered by Network")

    def test_read_only_from_the_network(self):
        self.skipTest("covered by Network")

    def test_attempt_limit(self):
        self.skipTest("covered by Network")

    def test_lan_endpoint_hidden_from_the_network(self):
        self.skipTest("covered by Network")


class StartupMessage(unittest.TestCase):
    def test_the_key_is_not_printed(self):
        # server.log keeps stdout: the phone URL must not carry the key
        line = lan.startup_line("192.168.0.10", 8765)
        self.assertIn("http://192.168.0.10:8765/", line)
        self.assertNotIn("key=", line)


if __name__ == "__main__":
    unittest.main()
