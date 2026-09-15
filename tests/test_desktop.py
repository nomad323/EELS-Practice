import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from eels_sim.desktop import BrowserLifetime, DesktopServer, run, self_test


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for desktop lifecycle")


class LifetimeTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.life = BrowserLifetime(clock=lambda: self.now)

    def test_unused_launcher_expires_and_cannot_revive(self):
        self.now = 89
        self.assertFalse(self.life.expired())
        self.now = 90
        self.assertTrue(self.life.expired())
        self.assertIsNone(self.life.attach())

    def test_refresh_reconnect_and_last_tab_grace(self):
        a = self.life.attach()
        b = self.life.attach()
        self.now = 100
        self.life.detach(a)
        self.assertFalse(self.life.expired())
        self.life.detach(b)
        self.now = 104
        refreshed = self.life.attach()
        self.now = 1000
        self.assertFalse(self.life.expired())
        self.life.detach(refreshed)
        self.life.detach(refreshed)  # Duplicate cleanup cannot extend deadline.
        self.now = 1005
        self.assertTrue(self.life.expired())

    def test_background_connection_needs_no_js_timer(self):
        connection = self.life.attach()
        self.now = 24 * 3600
        self.assertFalse(self.life.expired())
        self.assertTrue(self.life.connected_once)
        self.life.detach(connection)
        self.now += 5
        self.assertTrue(self.life.expired())

    def test_late_attach_is_rejected_even_before_monitor_polls(self):
        self.now = 91
        self.assertIsNone(self.life.attach())
        self.assertTrue(self.life.expired())


class DesktopHTTPTests(unittest.TestCase):
    def setUp(self):
        self.life = BrowserLifetime()
        self.server = DesktopServer(self.life)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.life.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, headers=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        self.clients.append(client)
        client.request("GET", path, headers=headers or {})
        response = client.getresponse()
        self.addCleanup(response.close)
        return client, response

    def test_stream_tracks_socket_disconnect_and_multiple_tabs(self):
        path = f"/api/desktop/events?token={self.life.token}"
        a, ra = self.request(path)
        b, rb = self.request(path)
        self.assertEqual(ra.status, 200)
        self.assertEqual(ra.version, 11)
        self.assertTrue(ra.will_close)
        self.assertEqual(ra.headers['Connection'], 'close')
        self.assertEqual(ra.headers["Content-Type"], "text/event-stream")
        self.assertEqual(ra.readline(), b"data: alive\n")
        self.assertEqual(rb.readline(), b"data: alive\n")
        self.assertEqual(len(self.life.connections), 2)
        ra.close()
        a.close()
        wait_for(lambda: len(self.life.connections) == 1)
        self.assertFalse(self.life.expired())
        rb.close()
        b.close()
        wait_for(lambda: len(self.life.connections) == 0)
        self.assertFalse(self.life.expired())  # Refresh grace still applies.

    def test_capability_origin_host_and_manual_api(self):
        good = f"/api/desktop/events?token={self.life.token}"
        for path, headers in (("/api/desktop/events", {}),
                              ("/api/desktop/events?token=wrong", {}),
                              (good + "&token=wrong", {}),
                              ("/api/desktop/events?token=%E4%B8%AD", {}),
                              (good, {"Host": "attacker.invalid"}),
                              (good, {"Origin": "https://example.invalid"}),
                              (good, {"Sec-Fetch-Site": "cross-site"})):
            with self.subTest(path=path, headers=headers):
                _, response = self.request(path, headers)
                self.assertEqual(response.status, 403)
                response.read()
        self.assertEqual(len(self.life.connections), 0)
        self.assertFalse(self.life.connected_once)
        _, meta = self.request("/api/meta")
        self.assertNotIn(self.life.token.encode(), meta.read())
        for path in ("/", "/app.js", "/desktop.js", "/style.css"):
            _, response = self.request(path)
            self.assertEqual(response.status, 200)
            self.assertGreater(len(response.read()), 100)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")


class LauncherTests(unittest.TestCase):
    def test_browser_open_failure_closes_listener(self):
        life = BrowserLifetime()
        server = DesktopServer(life)
        opened = []
        with patch("eels_sim.desktop.DesktopServer", return_value=server):
            with self.assertRaisesRegex(RuntimeError, "默认浏览器"):
                run(opener=lambda url: opened.append(url) or False, lifetime=life)
        parsed = urlsplit(opened[0])
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.fragment, "desktop=" + life.token)
        self.assertGreater(parsed.port, 0)
        self.assertEqual(server.socket.fileno(), -1)
        self.assertTrue(life.stopping.is_set())

    def test_browser_never_connects_exits(self):
        life = BrowserLifetime(startup_timeout=0.02)
        with self.assertRaisesRegex(RuntimeError, "未连接"):
            run(opener=lambda url: True, lifetime=life)
        self.assertTrue(life.stopping.is_set())

    def test_last_connection_exit_stops_launcher_and_port(self):
        life = BrowserLifetime(close_grace=0.02)
        server = DesktopServer(life)

        def opener(url):
            connection = life.attach()
            life.detach(connection)
            return True

        with patch("eels_sim.desktop.DesktopServer", return_value=server):
            run(opener=opener, lifetime=life)
        self.assertEqual(server.socket.fileno(), -1)
        self.assertTrue(life.connected_once)

    def test_offline_self_test_report(self):
        with tempfile.TemporaryDirectory(prefix="eels-self-test-") as folder:
            report = Path(folder) / "测试 report.json"
            self_test(report)
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "PASS")
            self.assertFalse(data["frozen"])
            self.assertAlmostEqual(data["baseline_fwhm_mev"], 8, delta=0.2)


if __name__ == "__main__":
    unittest.main()
